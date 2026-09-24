"""
pnr_runner.py
Runs YOUR existing pnr.tcl (OpenROAD place-and-route script, which reads
constraints.sdc, LEF/Liberty files, and the netlist using its own
hardcoded paths) exactly as-is - no generated/duplicate script. Mirrors
sta_runner.py's structure and conventions exactly, since this is
functionally the same pattern (run an existing hand-validated Tcl
script in a self-contained copied workspace, capture its reports) just
against OpenROAD instead of OpenSTA.

Assumes your existing layout:
    <pnr_dir>/pnr.tcl
    <pnr_dir>/constraints.sdc
    <pnr_dir>/reports/            (written by pnr.tcl itself)
    <pnr_dir>/../synthesis/<TOP>_netlist.v   (netlist pnr.tcl reads)

Deliberately NOT called per-iteration from orchestrator.py's LLM patch
loop - real detail routing is slow (tens of minutes even for a design
this size, per observed real runs), unlike synthesis+STA which need to
run fast, many times per session. This is meant to be called ONCE,
after the loop finishes, against the final accepted baseline - see
config.PNR_ENABLED, which gates whether orchestrator.py calls this at
all.

Python 3.6.8 compatible (no f-strings, no capture_output=True).
"""

import os
import shutil
import signal
import subprocess
from pathlib import Path


class PnRError(Exception):
    pass


def run_pnr(pnr_dir="pnr", tcl_script="pnr.tcl",
            output_root=None, timeout=7200,
            netlist_src=None, top_module="top", source_pnr_dir=None,
            iteration_label=None):
    """
    Runs `openroad -exit <tcl_script>` with cwd=pnr_dir, so all of
    pnr.tcl's existing relative paths (constraints.sdc, ../synthesis/...,
    reports/) resolve exactly as they do when you run it manually. LEF/
    Liberty paths are expected to be absolute INSIDE pnr.tcl itself
    (matching your existing hand-written script) - nothing here
    overrides or duplicates them.

    If source_pnr_dir is given, all *.tcl and *.sdc files from there are
    copied into pnr_dir first (overwriting any existing copies) - lets
    you keep a self-contained python/pnr/ workspace that's always synced
    from your original, hand-validated ../pnr/ folder, without a manual
    `cp` step each time. Leave as None if pnr_dir already has its own
    files and you don't want them touched. Mirrors sta_runner.run_sta()'s
    source_sta_dir behavior exactly.

    If netlist_src is given, it's copied to
    <pnr_dir>/../synthesis/<top_module>_netlist.v first - the fixed
    location pnr.tcl expects. Leave as None if you're placing the
    netlist there yourself (e.g. it's already there from a prior
    synth_runner.py run against the same baseline).

    output_root defaults to <pnr_dir>/pnr_runs (i.e. lives inside your
    pnr/ workspace, not as a sibling of it). Pass an explicit path to
    override.

    iteration_label: pass an explicit folder name (e.g. 'final') to
    control the output folder name directly - unlike sta_runner.py,
    this is expected to be used ONCE per orchestrator.py run (against
    the final accepted baseline only), so 'final' is a more meaningful
    default label than an auto-incrementing counter, but the counter
    fallback is kept for standalone/manual/repeated use.

    Launched with start_new_session=True so this becomes the leader of
    its own process group - required so a timeout kills OpenROAD AND
    everything it spawned underneath it (its own detail-router
    subprocesses etc.), not just the top-level PID. See
    formal_check.py's run_eqy() for the same pattern and the reasoning
    behind it (a plain subprocess.run(..., timeout=...) only kills the
    single top-level PID on timeout, leaving grandchildren orphaned -
    confirmed as a real, repeated problem in this project's formal
    verification flow, and just as real a risk here given OpenROAD's
    detail router is its own long-running subprocess).

    After a successful run, copies pnr_dir/reports/ into the resulting
    iteration folder under output_root, so results are preserved.

    Returns dict: {success, reports_dir, log_path, iteration}
    """
    pnr_path = Path(pnr_dir)
    pnr_path.mkdir(parents=True, exist_ok=True)

    if output_root is None:
        output_root = str(pnr_path / "pnr_runs")

    if source_pnr_dir:
        src = Path(source_pnr_dir)
        if not src.exists():
            raise PnRError("source_pnr_dir not found: %s" % source_pnr_dir)
        for pattern in ("*.tcl", "*.sdc"):
            for f in src.glob(pattern):
                shutil.copy(str(f), str(pnr_path / f.name))

    script_file = pnr_path / tcl_script
    if not script_file.exists():
        raise PnRError("Script not found: %s" % str(script_file))

    # pnr.tcl writes into reports/ via '>' redirects but doesn't create
    # the directory itself - OpenROAD errors out if it's missing (same
    # requirement as sta.tcl).
    (pnr_path / "reports").mkdir(parents=True, exist_ok=True)

    if netlist_src:
        netlist_dst = (pnr_path / ".." / "synthesis" / ("%s_netlist.v" % top_module)).resolve()
        netlist_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(netlist_src), str(netlist_dst))

    proc = subprocess.Popen(
        ["openroad", "-exit", tcl_script],
        cwd=str(pnr_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        stdout_bytes, _ = proc.communicate(timeout=timeout)
    except FileNotFoundError:
        raise PnRError("OpenROAD ('openroad') not found on PATH.")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # already exited between the timeout firing and this call
        proc.wait()
        return {"success": False, "reports_dir": None, "log_path": None,
                "iteration": None, "timed_out": True}

    log_text = stdout_bytes.decode("utf-8", errors="replace")
    success = (proc.returncode == 0) and ("Error" not in log_text)

    if iteration_label is not None:
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        iter_dir = root / iteration_label
        iteration_n = iteration_label
    else:
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        existing = []
        for d in root.glob("run_*"):
            if d.is_dir():
                try:
                    existing.append(int(d.name.split("_")[1]))
                except (IndexError, ValueError):
                    continue
        next_n = (max(existing) + 1) if existing else 1
        iteration_n = next_n
        iter_dir = root / ("run_%d" % next_n)

    iter_dir.mkdir(parents=True, exist_ok=True)

    log_path = iter_dir / "pnr_log.txt"
    log_path.write_text(log_text)

    reports_dst = iter_dir / "reports"
    # WHY TWO FOLDERS EXIST (not redundant): live_reports
    # (pnr_dir/reports, e.g. pnr/reports/) is the WORKSPACE OpenROAD
    # itself writes into during the run, via pnr.tcl's own relative
    # paths (e.g. `> reports/timing_setup_wc.rpt`) - it gets
    # OVERWRITTEN every time PnR runs again, since pnr.tcl always
    # targets that same relative path. reports_dst (iter_dir/reports,
    # e.g. pnr/pnr_runs/final/reports/) is a PERMANENT per-run
    # snapshot, copied out before the next run can overwrite the live
    # one - the exact same pattern already used for
    # verilog_iterations/iter_N/ and formal/iter_N/ elsewhere in this
    # project, for the same reason (preserve history instead of
    # letting each run destroy the last one's results).
    live_reports = pnr_path / "reports"
    if success and live_reports.exists():
        if reports_dst.exists():
            shutil.rmtree(str(reports_dst))
        shutil.copytree(str(live_reports), str(reports_dst))

        # Equivalent to: grep "Design area" pnr_log.txt | tail -1 > reports/area.rpt
        # - done here in Python against the already-captured log_text
        # rather than shelling out, since it's already fully in memory
        # (no need to re-read the file we just wrote). Takes the LAST
        # matching line specifically (matching `tail -1`'s intent) in
        # case report_design_area (or something producing similar-
        # looking output, e.g. an intermediate placement/GRT utilization
        # message) appears more than once in the full run log - the
        # FINAL one is the actual sign-off area, matching what
        # report_parser.parse_design_area() expects to find in this
        # file (see that function for the confirmed real output format:
        # "Design area 3773 u^2 13% utilization.").
        #
        # Written into BOTH folders - reports_dst (the permanent
        # archive orchestrator.py's PPA comparison actually reads from)
        # AND live_reports (pnr_dir/reports/, so a quick manual look in
        # the live workspace right after a run also has it, matching
        # every OTHER report file, which already lands in both places
        # via the copytree above - area.rpt is the one exception since
        # it's generated here rather than by pnr.tcl itself).
        area_lines = [line for line in log_text.splitlines() if "Design area" in line]
        if area_lines:
            area_content = area_lines[-1] + "\n"
            (reports_dst / "area.rpt").write_text(area_content)
            (live_reports / "area.rpt").write_text(area_content)

    return {
        "success": success,
        "reports_dir": str(reports_dst) if success else None,
        "log_path": str(log_path),
        "iteration": iteration_n,
        "timed_out": False,
    }
