"""
synth_runner.py
Wraps Yosys synthesis: generates a .ys script, runs it, and returns
paths to the synthesized netlist + area report (stat -liberty).

Maps each clock domain's module(s) to ABC with THAT domain's own
timing target (via -D), instead of one blind global `abc -liberty`
call with no delay target at all. Without this, ABC has no idea what
clock period it's optimizing for and just does generic area/delay
balancing - meaning re-synthesis after an LLM patch could leave a
violation unresolved (or resolved by luck) for reasons that have
nothing to do with whether the RTL patch itself was good.

IMPORTANT - please verify the -D unit on your setup before trusting
the numbers below. Yosys's documented convention for the abc9/FPGA
delay model is picoseconds; this hasn't been independently confirmed
here for the classic `abc -liberty` ASIC flow used against your TSMC
liberty file. Check with:
    yosys -p "abc -help"
on your server and look at the -D option's description. If it turns
out to expect a different unit, only ABC_DELAY_UNIT_SCALE below needs
to change - nothing else in this file depends on the specific value.

Python 3.6.8 compatible (no f-strings, no capture_output=True).
"""

import subprocess
from pathlib import Path


class SynthError(Exception):
    pass


# Multiply a period given in nanoseconds by this to get whatever unit
# -D expects. 1000 = convert ns -> ps (current best-guess default,
# per Yosys's documented ps convention - VERIFY before trusting, see
# module docstring above).
ABC_DELAY_UNIT_SCALE = 1000


YS_HEADER = """\
read_verilog {rtl_files}
synth -top {top_module}
dfflibmap -liberty {liberty_path}
"""

# One block per clock domain's module(s): scope to that module via
# `select`, run abc with THAT domain's own delay target, then clear
# the selection before the next domain.
YS_ABC_BLOCK = """\
select {module_name}
abc -liberty {liberty_path} -D {delay_target}
select -clear
"""

# Safety-net pass with nothing selected (whole design), run AFTER all
# per-module blocks above. `select <module>` only reaches that module's
# OWN local cells - submodule instances appear as opaque black-box
# references, not their internals (verified directly against this real
# design: `select riscv_top` returns zero objects with a `CSR/` prefix,
# even though CSR is instantiated inside riscv_top). Any module not
# explicitly listed in module_clock_map - combinational glue like
# address_decoder/hazard/the mux tree, or the clock-divider modules
# themselves - would otherwise be left in Yosys's generic, liberty-free
# internal cell representation from synth's own default abc pass, which
# OpenSTA cannot resolve against the real liberty file. Re-running abc
# on already-mapped modules here is harmless (idempotent, just a little
# extra runtime) - this is a safety net, not the primary mapping step.
YS_CATCHALL_BLOCK = """\
select *
abc -liberty {liberty_path} -D {catchall_delay_target}
select -clear
"""

YS_FOOTER = """\
tee -o {area_report} stat -liberty {liberty_path}
opt -purge {top_module}
write_verilog -noattr -noexpr {netlist_out}
"""


def generate_yosys_script(verilog_dir, top_module, liberty_path,
                           output_dir, module_clock_map=None,
                           clock_periods_ns=None, catchall_clock=None,
                           script_path="synth/run_synth.ys"):
    """Writes a .ys script covering all .v files in verilog_dir.

    module_clock_map:  {module_name: clock_name}, e.g.
                        {"counter_fast": "clk_fast", "sync_bridge": "clk_slow"}
                        - which clock domain each module belongs to.
    clock_periods_ns:  {clock_name: period_in_ns}, e.g.
                        {"clk_fast": 0.6, "clk_slow": 10.0}
    catchall_clock:    clock name (must exist in clock_periods_ns) used
                        as the target for a final, unrestricted
                        `select *` / abc pass run AFTER all per-module
                        blocks - see YS_CATCHALL_BLOCK docstring above
                        for why this is needed. Pass config.PRIMARY_CLOCK
                        for the real SoC. Omit to skip the catch-all
                        entirely (only safe if module_clock_map already
                        covers every module with logic of its own).

    If module_clock_map/clock_periods_ns are None/empty, falls back to a
    single global `abc -liberty <lib>` with no delay target (the old,
    timing-blind behaviour).

    Modules NOT listed in module_clock_map (e.g. a pure structural
    top-level wrapper with no registers/logic of its own) are skipped
    for the per-domain ABC step - the catch-all pass (if given) is what
    actually maps their combinational logic to real liberty cells.

    Returns (script_path, netlist_out_path, area_report_path)."""
    vfiles = sorted(str(f) for f in Path(verilog_dir).glob("*.v"))
    if not vfiles:
        raise SynthError("No .v files found in %s" % verilog_dir)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    netlist_out = str(out_dir / (top_module + "_netlist.v"))
    area_report = str(out_dir / "area_report.txt")

    module_clock_map = module_clock_map or {}
    clock_periods_ns = clock_periods_ns or {}

    script_text = YS_HEADER.format(
        rtl_files=" ".join(vfiles),
        top_module=top_module,
        liberty_path=liberty_path,
    )

    if module_clock_map:
        for module_name, clock_name in sorted(module_clock_map.items()):
            period_ns = clock_periods_ns.get(clock_name)
            if period_ns is None:
                raise SynthError(
                    "Module '%s' is mapped to clock '%s', but no period "
                    "for that clock was found in clock_periods_ns." %
                    (module_name, clock_name)
                )
            delay_target = int(round(period_ns * ABC_DELAY_UNIT_SCALE))
            script_text += YS_ABC_BLOCK.format(
                module_name=module_name,
                liberty_path=liberty_path,
                delay_target=delay_target,
            )
    else:
        # No domain mapping supplied - fall back to one blind global
        # pass (previous behaviour), better than nothing but not
        # timing-aware.
        script_text += "abc -liberty %s\n" % liberty_path

    if catchall_clock:
        catchall_period_ns = clock_periods_ns.get(catchall_clock)
        if catchall_period_ns is None:
            raise SynthError(
                "catchall_clock '%s' has no period in clock_periods_ns."
                % catchall_clock
            )
        catchall_delay_target = int(round(catchall_period_ns * ABC_DELAY_UNIT_SCALE))
        script_text += YS_CATCHALL_BLOCK.format(
            liberty_path=liberty_path,
            catchall_delay_target=catchall_delay_target,
        )

    script_text += YS_FOOTER.format(
        area_report=area_report,
        liberty_path=liberty_path,
        top_module=top_module,
        netlist_out=netlist_out,
    )

    script_file = Path(script_path)
    script_file.parent.mkdir(parents=True, exist_ok=True)
    script_file.write_text(script_text)

    return str(script_file), netlist_out, area_report


def run_synthesis(script_path, log_path="synth/synth_log.txt", timeout=300):
    """Runs `yosys -s <script_path>`, saves full stdout+stderr to log_path.
    Returns (success: bool, log_text: str)."""
    try:
        result = subprocess.run(
            ["yosys", "-s", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise SynthError("yosys not found on PATH.")
    except subprocess.TimeoutExpired:
        return False, "yosys timed out after %ds" % timeout

    log_text = result.stdout.decode("utf-8", errors="replace")
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    Path(log_path).write_text(log_text)

    success = (result.returncode == 0) and ("ERROR" not in log_text)
    return success, log_text


def parse_area(log_text):
    """Pulls the TOTAL chip area from stat -liberty output.
    Yosys prints per-submodule 'Chip area for module ...' lines first,
    then a final 'Chip area for top module ...' line with the rolled-up
    total - we want that last one, not the first submodule match.
    Returns float or None if not found."""
    import re
    matches = re.findall(r"Chip area for top module .*?:\s*([\d.]+)", log_text)
    if matches:
        return float(matches[-1])
    # fallback: older Yosys versions may omit "top" in the label
    matches = re.findall(r"Chip area for .*?:\s*([\d.]+)", log_text)
    return float(matches[-1]) if matches else None


def strip_signed_keyword(netlist_path):
    """Removes the standalone 'signed' keyword from the written netlist,
    for OpenSTA compatibility - equivalent to your manual
    `sed -i 's/\\bsigned //g' <netlist>` post-processing step. Done in
    Python (regex, word-boundary matched) rather than shelling out to
    sed, so this works identically regardless of whether sed is on PATH.
    """
    import re
    path = Path(netlist_path)
    text = path.read_text()
    stripped = re.sub(r"\bsigned ", "", text)
    path.write_text(stripped)


def synthesize(verilog_dir, top_module, liberty_path, output_dir="synth",
                iteration_label=None, module_clock_map=None,
                clock_periods_ns=None, catchall_clock=None,
                strip_signed=True):
    """Full convenience wrapper: script -> run -> area.

    module_clock_map, clock_periods_ns, catchall_clock: see
    generate_yosys_script() - pass these (typically from
    config.MODULE_CLOCK_MAP, config.CLOCK_PERIODS_NS, and
    config.PRIMARY_CLOCK) to get timing-aware, per-domain ABC mapping
    with a safety-net catch-all pass, instead of one blind global pass.

    strip_signed: if True (default), runs strip_signed_keyword() on the
    written netlist after a successful synthesis - required for OpenSTA
    compatibility with this liberty/netlist combination.

    iteration_label: when given (e.g. 'baseline', 'iter_3'), all outputs
    for this run go to <output_dir>/<iteration_label>/ instead of the
    flat <output_dir>/, so nothing is overwritten between iterations -
    important because a failed synthesis' log is the only evidence of
    what went wrong, and a flat folder loses it on the next run.
    When None, behaves exactly as before (flat output_dir), so existing
    manual command-line usage is unaffected.

    Returns dict with netlist_path, success, area, log_path, area_report_path."""
    base_dir = Path(output_dir)
    if iteration_label:
        base_dir = base_dir / iteration_label

    script_path = str(base_dir / "run_synth.ys")
    log_path = str(base_dir / "synth_log.txt")

    script_path, netlist_out, area_report = generate_yosys_script(
        verilog_dir, top_module, liberty_path, str(base_dir),
        module_clock_map=module_clock_map,
        clock_periods_ns=clock_periods_ns,
        catchall_clock=catchall_clock,
        script_path=script_path)
    success, log_text = run_synthesis(script_path, log_path=log_path)
    area = parse_area(log_text) if success else None

    if success and strip_signed:
        strip_signed_keyword(netlist_out)

    return {
        "success": success,
        "netlist_path": netlist_out if success else None,
        "area": area,
        "log_path": log_path,
        "area_report_path": area_report if success else None,
    }


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    vdir = sys.argv[1] if len(sys.argv) > 1 else "verilog"
    top = sys.argv[2] if len(sys.argv) > 2 else "top"
    lib = sys.argv[3] if len(sys.argv) > 3 else "/path/to/tsmc65.lib"

    try:
        import config
        module_clock_map = config.MODULE_CLOCK_MAP
        clock_periods_ns = config.CLOCK_PERIODS_NS
        catchall_clock = getattr(config, "PRIMARY_CLOCK", None)
    except ImportError:
        module_clock_map = None
        clock_periods_ns = None
        catchall_clock = None

    result = synthesize(vdir, top, lib, module_clock_map=module_clock_map,
                         clock_periods_ns=clock_periods_ns,
                         catchall_clock=catchall_clock)
    print("Success:", result["success"])
    print("Netlist:", result["netlist_path"])
    print("Area:", result["area"])
    print("Area report:", result["area_report_path"])
    print("Log:", result["log_path"])
