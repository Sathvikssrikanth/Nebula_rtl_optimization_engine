"""
formal_check.py
Wraps EQY (Equivalence Checking with Yosys) to formally verify that a
patched module is functionally equivalent to the baseline - the safety
gate that must pass before any LLM timing fix is accepted, and the
source of your "formal equivalence verification report" deliverable.

Generates a .eqy config comparing:
    [gold] = baseline RTL (known-good, pre-patch)
    [gate] = patched RTL (post-patch, from patch_applier.py's iteration dir)

Python 3.6.8 compatible (no f-strings, no capture_output=True).
"""

import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

from module_extractor import (
    build_module_map, extract_module_ports, extract_module_source)


class FormalCheckError(Exception):
    pass


# ---------------------------------------------------------------------------
# Latency-matched gold wrapper
# ---------------------------------------------------------------------------
#
# EQY's `depth` parameter controls how many cycles a k-induction proof
# runs for - it does NOT search for or absorb a phase/latency offset
# between gold and gate. If the LLM's patch adds N registers of new
# output latency (see prompt_builder.py's PIPELINE_STAGES_ADDED marker
# and llm_client.extract_pipeline_stages_added), gold's output at cycle
# t and gate's output at cycle t are no longer the same logical value -
# gate's is what gold produces at cycle t-N. Comparing them directly at
# any depth will correctly report a mismatch, because the check itself
# is testing the wrong thing.
#
# The standard technique (used in real G2G/RTL-vs-gate equivalence
# flows) is to insert "pipeline-equalizing" dummy registers on the
# side with fewer stages so both sides are compared at the same
# logical point in time. Here, gate always has the added latency, so
# we always delay gold's own outputs by exactly N cycles via a thin
# wrapper module - gold's *logic* is untouched, only compared later.

def generate_gold_wrapper(module_name, module_map, added_stages,
                           wrapper_dir, stretched_ports=None):
    """Writes a Verilog file containing TWO modules:
      1. The ORIGINAL module_name's own source, renamed to
         '<module_name>_gold_orig' (a plain identifier rename of the
         'module ... (' declaration only - ports/body untouched).
      2. A wrapper named EXACTLY '<module_name>' (same name as the
         module in gate) that instantiates the renamed original and
         delays every OUTPUT port by exactly added_stages clock cycles
         (via a simple shift register per output). Input ports pass
         through unchanged - only outputs need delaying, since the
         same input is applied to both gold and gate at the same
         cycle; it's the point at which each design's logic finishes
         reacting to that input that differs.

    stretched_ports: optional list of output port names (from the LLM's
    self-reported STRETCHED_PORTS - see llm_client.extract_stretched_ports())
    whose ASSERTED DURATION changed, not just their timing. A plain
    per-cycle delay only ever replays a signal's exact original
    waveform later in time - it cannot turn a short pulse into a wider
    one. This matters for status/handshake outputs (e.g. "busy") that
    used to pulse for a short, fixed duration while a computation ran:
    if that computation now genuinely takes added_stages more cycles,
    the signal must STAY asserted for that many cycles longer, not
    just move later while keeping its original short width - otherwise
    a functionally correct patch still fails equivalence checking on
    that one port. For any port named here, instead of taking only the
    final delay stage as output, this OR-reduces the raw signal
    together with every intermediate delay stage - equivalent to a
    sliding-window "was this signal asserted at any point in the last
    (added_stages + 1) cycles" - which both starts at gold's original
    (unshifted) assertion time AND stays high through the full delayed
    completion time, matching a computation that now genuinely spans
    more cycles. Ports not listed here keep the existing plain-delay
    behavior unchanged. Intended for 1-bit status-style signals; for a
    multi-bit port this OR-reduces bit-for-bit, which is unlikely to be
    the right semantics and is not a case this feature was built for.

    Why the wrapper must be named identically to the original (not
    '<module_name>_gold_delay_wrapper', which an earlier version of
    this function used): EQY's 'combine' step requires gold's and
    gate's TOP MODULE to have the SAME NAME - it errors out with
    "Top modules of gold and gate do not have the same name" otherwise
    (confirmed against a real EQY run). Since the wrapper now reuses
    the original name, gold's file list must NOT also separately
    include module_name's own unmodified .v file (that would be a
    duplicate module-name conflict when Yosys reads both) - see
    generate_eqy_config(), which handles this exclusion.

    Requires a 'clk' port to exist on module_name (used as the shift
    register clock) - raises FormalCheckError if not found, since
    there's no way to build a synchronous delay without one.

    added_stages must be > 0 - callers should skip wrapper generation
    entirely (compare the plain original module) when added_stages == 0,
    since a 0-stage wrapper is just needless indirection around an
    already-aligned comparison.

    Returns the path to the written wrapper file (str).
    """
    stretched_ports = set(stretched_ports or [])
    if added_stages <= 0:
        raise FormalCheckError(
            "generate_gold_wrapper called with added_stages=%d - only "
            "call this when added_stages > 0." % added_stages)

    ports = extract_module_ports(module_name, module_map)
    if not ports:
        raise FormalCheckError(
            "Could not parse ANSI port list for module '%s' - cannot "
            "build a latency-matched gold wrapper. Check the module "
            "uses Verilog-2001 ANSI port style." % module_name)

    if not any(p["name"] == "clk" and p["direction"] == "input" for p in ports):
        raise FormalCheckError(
            "Module '%s' has no 'clk' input port - cannot build a "
            "synchronous delay wrapper for a %d-stage latency match. "
            "If this module is purely combinational, the LLM's "
            "PIPELINE_STAGES_ADDED value is likely wrong (should be 0)."
            % (module_name, added_stages)
        )

    original_source = extract_module_source(module_name, module_map)
    if not original_source:
        raise FormalCheckError(
            "Could not extract source text for module '%s' to embed "
            "(renamed) alongside its gold delay wrapper." % module_name)

    renamed_module_name = "%s_gold_orig" % module_name
    # Rename ONLY the 'module <name>' declaration token, not any other
    # occurrence of module_name elsewhere in the body (e.g. as a port
    # or local variable name that happens to share the string) - the
    # module keyword followed by whitespace then the exact identifier,
    # word-bounded, is unambiguous and appears exactly once per file.
    renamed_source, n_subs = re.subn(
        r"\bmodule\s+%s\b" % re.escape(module_name),
        "module %s" % renamed_module_name,
        original_source,
        count=1,
    )
    if n_subs != 1:
        raise FormalCheckError(
            "Expected exactly one 'module %s' declaration to rename in "
            "its own source, found %d - refusing to guess." % (module_name, n_subs))

    inputs = [p for p in ports if p["direction"] == "input"]
    outputs = [p for p in ports if p["direction"] == "output"]

    # Only honor names that are actually real output ports of this module -
    # a hallucinated or misspelled name from the LLM's self-report should
    # be silently ignored (falls back to plain-delay for that name) rather
    # than crash or silently apply the wrong treatment to nothing.
    stretched_ports &= {p["name"] for p in outputs}

    port_decls = []
    for p in inputs:
        port_decls.append("    input %s %s" % (p["width"], p["name"]) if p["width"]
                           else "    input %s" % p["name"])
    for p in outputs:
        port_decls.append("    output %s %s" % (p["width"], p["name"]) if p["width"]
                           else "    output %s" % p["name"])

    inst_ports = []
    for p in inputs:
        inst_ports.append("        .%s(%s)" % (p["name"], p["name"]))
    for p in outputs:
        inst_ports.append("        .%s(%s_raw)" % (p["name"], p["name"]))

    raw_wire_decls = []
    delay_regs = []
    delay_assigns = []
    for p in outputs:
        width = p["width"]
        raw_wire_decls.append(
            "    wire %s %s_raw;" % (width, p["name"]) if width
            else "    wire %s_raw;" % p["name"]
        )
        # One shift-register array per output port, added_stages deep.
        # Verilog-2001/Yosys-compatible packed-array-of-regs syntax.
        reg_width = width if width else ""
        delay_regs.append(
            "    reg %s %s_delay [0:%d];" % (reg_width, p["name"], added_stages - 1)
        )
        delay_assigns.append(
            "            %s_delay[0] <= %s_raw;" % (p["name"], p["name"])
        )
        delay_assigns.append(
            "            for (%s_i = 1; %s_i < %d; %s_i = %s_i + 1)\n"
            "                %s_delay[%s_i] <= %s_delay[%s_i - 1];"
            % (p["name"], p["name"], added_stages, p["name"], p["name"],
               p["name"], p["name"], p["name"], p["name"])
        )

    def _output_assign(p):
        name = p["name"]
        if name in stretched_ports:
            # OR the raw (undelayed) signal together with every intermediate
            # delay stage - a sliding "asserted at any point in the last
            # (added_stages + 1) cycles" window. Starts at gold's original
            # assertion time (via name_raw) and stays high through the
            # full delayed completion time (via name_delay[added_stages-1]),
            # matching a computation that now genuinely spans more cycles -
            # see this function's stretched_ports docstring for why a plain
            # delay (the else branch below) cannot do this.
            terms = ["%s_raw" % name] + [
                "%s_delay[%d]" % (name, i) for i in range(added_stages)
            ]
            return "    assign %s = %s;" % (name, " | ".join(terms))
        return "    assign %s = %s_delay[%d];" % (name, name, added_stages - 1)

    output_assigns = [_output_assign(p) for p in outputs]

    loop_var_decls = [
        "    integer %s_i;" % p["name"] for p in outputs
    ]

    wrapper_text = (
        "module %s (\n%s\n);\n\n"
        "%s\n"
        "%s\n\n"
        "%s u_gold_original (\n%s\n    );\n\n"
        "    always @(posedge clk) begin\n%s\n    end\n\n"
        "%s\n"
        "endmodule\n"
    ) % (
        module_name, ",\n".join(port_decls),
        "\n".join(raw_wire_decls),
        "\n".join(delay_regs + loop_var_decls),
        renamed_module_name, ",\n".join(inst_ports),
        "\n".join(delay_assigns),
        "\n".join(output_assigns),
    )

    stretch_note = (
        "// Widened (not just delayed) for: %s - see stretched_ports\n"
        "// docstring above for why a plain delay can't handle these.\n"
        % ", ".join(sorted(stretched_ports))
    ) if stretched_ports else "// No ports required widening (plain delay only).\n"

    text = (
        "// Auto-generated by formal_check.generate_gold_wrapper().\n"
        "// Contains the ORIGINAL '%s' (renamed '%s' below, to avoid a\n"
        "// duplicate-module-name clash with the real %s.v also read by\n"
        "// EQY for hierarchy resolution) plus a wrapper named exactly\n"
        "// '%s' - matching gate's own module name, as EQY's 'combine'\n"
        "// step requires gold and gate to share the same top module\n"
        "// name - that delays every output by %d cycle(s) so EQY\n"
        "// compares gold and gate at matching logical time steps, per\n"
        "// the patch's self-reported PIPELINE_STAGES_ADDED value.\n"
        "%s"
        "// Do not hand-edit - regenerated fresh every iteration.\n\n"
        "%s\n\n"
        "%s"
    ) % (
        module_name, renamed_module_name, module_name, module_name,
        added_stages, stretch_note, renamed_source, wrapper_text,
    )

    wrapper_path = Path(wrapper_dir) / ("%s_gold_delay_wrapper.v" % module_name)
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text(text)

    return str(wrapper_path)


def generate_eqy_config(gold_dir, gate_dir, top_module,
                         config_path="formal/check.eqy", depth=5,
                         check_module=None, added_stages=0, sat_timeout=120,
                         stretched_ports=None):
    """Writes a .eqy config comparing all .v files in gold_dir (baseline)
    against all .v files in gate_dir (patched iteration).

    check_module: when given, 'prep -top' targets THIS module instead
    of top_module - both sides still read ALL files (needed so Yosys
    can resolve any hierarchy the module instantiates), but EQY's own
    hierarchy-based scoping then limits the actual equivalence check to
    just that module's own subtree, not the entire design. This matters
    a lot at real SoC scale: without it, every single-module patch
    triggers a full-chip equivalence proof (slow, sometimes
    intractable) when only one small module actually changed. Leave as
    None to check the whole design against top_module (useful for a
    final end-of-run sanity check, not per-iteration use).

    added_stages: the patch's self-reported PIPELINE_STAGES_ADDED value
    (see llm_client.extract_pipeline_stages_added). When > 0, a
    latency-matched gold wrapper is generated (see
    generate_gold_wrapper()) and used as the gold side's prep target
    INSTEAD of check_module/top_module directly - see the module-level
    comment above generate_gold_wrapper() for why this is necessary
    (depth alone cannot compensate for a genuine latency/phase offset
    between gold and gate). When 0 (the default - same-cycle
    equivalence, no latency change), behaves exactly as before.

    sat_timeout: seconds given to the 'sat' strategy PER PARTITION
    before EQY moves on to the 'induction' (sby) strategy instead -
    this is EQY's own native per-strategy 'timeout' option, distinct
    from check_equivalence()'s outer 'timeout' argument (which just
    kills the whole EQY subprocess if exceeded, with no graceful
    handoff to sby). Per EQY's own docs, this per-strategy timeout is
    NOT enabled by default - without setting it explicitly, a 'sat'
    problem that just runs indefinitely (as opposed to being skipped
    outright for containing memory) will never fall through to sby at
    all, no matter how long you wait. Set to None to disable (restores
    EQY's default: sat runs with no time limit).

    stretched_ports: optional list of output port names whose asserted
    DURATION changed, not just their timing - passed straight through
    to generate_gold_wrapper() when added_stages > 0. See that
    function's docstring for why a plain delay cannot correctly handle
    these. Ignored when added_stages == 0 (no wrapper is built at all
    in that case).

    Uses absolute paths for the RTL files - EQY runs commands inside its
    own nested working directory (e.g. formal/check/), one level deeper
    than where the .eqy file itself lives, so relative paths written
    relative to the .eqy file's location resolve incorrectly. Absolute
    paths sidestep this regardless of EQY's internal working directory.

    Returns config_path (str)."""
    gold_files = sorted(str(f.resolve()) for f in Path(gold_dir).glob("*.v"))
    gate_files = sorted(str(f.resolve()) for f in Path(gate_dir).glob("*.v"))

    if not gold_files:
        raise FormalCheckError("No .v files found in gold_dir: %s" % gold_dir)
    if not gate_files:
        raise FormalCheckError("No .v files found in gate_dir: %s" % gate_dir)

    prep_target = check_module if check_module else top_module
    gold_prep_target = prep_target

    if added_stages > 0:
        if not check_module:
            raise FormalCheckError(
                "added_stages=%d given but no check_module specified - "
                "latency-matched wrapper generation requires knowing "
                "exactly which module's outputs to delay; wrapping the "
                "whole top_module's I/O is not supported." % added_stages
            )
        module_map = build_module_map(gold_dir)
        wrapper_dir = str(Path(config_path).parent / "gold_wrapper")
        wrapper_path = generate_gold_wrapper(
            check_module, module_map, added_stages, wrapper_dir,
            stretched_ports=stretched_ports)
        # The wrapper file above already contains a (renamed) copy of
        # check_module's own source embedded inside it - reading the
        # ORIGINAL check_module.v file as well would define the same
        # module name twice and fail to elaborate. Drop it from gold's
        # read list; the wrapper file supplies that logic instead.
        original_file = module_map.get(check_module)
        if original_file:
            original_resolved = str(Path(original_file).resolve())
            gold_files = [f for f in gold_files if f != original_resolved]
        gold_files = gold_files + [str(Path(wrapper_path).resolve())]
        # gold_prep_target stays check_module (unchanged, NOT renamed) -
        # the wrapper module itself is named exactly check_module (see
        # generate_gold_wrapper()'s docstring for why this must match
        # gate's module name for EQY's 'combine' step to succeed).

    gold_reads = "\n".join("read_verilog %s" % f for f in gold_files)
    gate_reads = "\n".join("read_verilog %s" % f for f in gate_files)

    # gold and gate prep the SAME top module name in every case now
    # (even with a wrapper in play) - EQY's 'combine' step requires
    # this and errors ("Top modules of gold and gate do not have the
    # same name") otherwise. When added_stages > 0, gold's copy of
    # that name refers to the wrapper (see generate_gold_wrapper),
    # which internally instantiates the true original under a
    # different, renamed identifier - gate's copy of the name refers
    # to the actual patched module. Same name, different definitions -
    # exactly what EQY's gold-vs-gate comparison is meant to check.
    #
    # 'memory_map -formal' runs right after prep on BOTH sides: Yosys's
    # proc pass can turn a sufficiently wide/ROM-like case statement
    # (e.g. a big opcode-to-AluControl decode) into a $mem_v2 cell.
    # EQY's formal x-propagation ("maybe-x marking") preprocessing does
    # not support $mem_v2 at all and hard-errors ("Unhandled cell
    # ...$mem_v2") the moment such a partition is checked under ANY
    # strategy that uses xprop (which includes 'sby', used below) -
    # this is a known EQY limitation (YosysHQ/eqy#42), and the
    # documented fix is exactly this: map the memory down to flops +
    # muxes before xprop ever sees it. Doing this also means such
    # partitions likely become provable under plain 'sat' too, without
    # needing the 'induction' fallback at all.
    #
    # TWO strategies still configured as a fallback tier, not one:
    # Yosys's plain 'sat' command has no support for TRUE memories
    # (real arrays like data_mem/register_file, which are NOT mapped
    # away here - only synthesis-inferred ROMs like AluControl's are)
    # and automatically skips (not fails) any partition whose logic
    # cone contains one (per EQY's own docs). Without a second
    # strategy that DOES support memory, EQY has nothing left to try
    # for that partition and hard-errors ("No configured strategy
    # supports partition ...") rather than reporting a genuine
    # equivalence pass/fail - this is a strategy
    # coverage gap, not a logic bug in the patch. 'sby' with the
    # 'smtbmc' engine handles memory-containing partitions; EQY tries
    # each partition against every strategy in order, so 'sat' still
    # runs first (fast) and only memory partitions fall through to this.
    #
    # Requires yosys-smtbmc AND a working SMT solver backend on PATH
    # (bitwuzla here - z3/boolector/yices are alternatives if bitwuzla
    # isn't installed on the institute server; check with
    # `which bitwuzla` before relying on this).
    sat_timeout_line = "timeout %d\n" % sat_timeout if sat_timeout else ""
    config_text = (
        "[gold]\n%s\nprep -top %s\nmemory_map -formal\n\n"
        "[gate]\n%s\nprep -top %s\nmemory_map -formal\n\n"
        "[strategy sat]\nuse sat\ndepth %s\n%s\n"
        "[strategy induction]\nuse sby\nengine smtbmc bitwuzla\ndepth %s\n"
    ) % (gold_reads, gold_prep_target, gate_reads, prep_target, depth,
         sat_timeout_line, depth)

    config_file = Path(config_path)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(config_text)

    return str(config_file)


def _kill_processes_using_path(path):
    """Best-effort: finds and SIGKILLs any process with an open file
    (including cwd) anywhere under `path`, using `lsof +D` (recursive
    directory search - a plain `fuser` on an arbitrary directory only
    catches exact-path matches, not descendants, so it wouldn't find a
    process whose cwd is a subdirectory several levels down, which is
    exactly the shape of the orphaned eqy/sby/yosys-smtbmc processes
    this is meant to catch).

    This is what lets run_eqy() clean up automatically from a PREVIOUS
    run's leftover processes (e.g. one that outlived an old-style
    timeout that only killed the top-level 'eqy' PID, before run_eqy
    started using process groups - see the timeout handling in
    run_eqy() below) so the retry loop there rarely even needs to
    fire, and the NEXT iteration doesn't need a manual `ps aux` /
    `kill` from the user just to get formal verification running
    again.

    Silently does nothing if `lsof` isn't installed, or finds nothing -
    this is a proactive convenience, not a required dependency; the
    existing retry-then-clear-error-message behavior in run_eqy()
    still applies as a fallback either way.
    """
    try:
        result = subprocess.run(
            ["lsof", "+D", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return  # lsof not installed, or itself hung - don't block on this

    pids = set()
    for line in result.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1].isdigit():
            pids.add(int(fields[1]))

    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # already dead, or owned by another user - nothing more we can do

    if pids:
        time.sleep(1)  # give the OS a moment to actually reap them


def run_eqy(config_path, timeout=300):
    """Runs `eqy <config_path>`. EQY creates an output directory named
    after the config file (minus .eqy extension), containing logfile.txt
    and a PASS or FAIL marker file.

    Returns dict: {equivalent: bool, output_dir: str, timed_out: bool,
                   log_text: str}
    """
    config_file = Path(config_path)
    if not config_file.exists():
        raise FormalCheckError("Config not found: %s" % config_path)

    run_dir = config_file.parent
    config_name = config_file.name

    # EQY refuses to run if its output dir (named after the config file,
    # minus .eqy) already exists from a previous run - clear it first so
    # every run starts clean without needing a manual `rm -rf` each time.
    #
    # This can fail with OSError [Errno 16] Device or resource busy on a
    # directory that's a lingering process's current working directory,
    # or (especially on NFS-mounted home directories, common on shared
    # institute servers) a stale handle left behind by a PREVIOUS EQY
    # run that was killed or crashed mid-execution rather than exiting
    # cleanly - _kill_processes_using_path() proactively clears out any
    # such leftover process first, so the retry loop below rarely even
    # needs to fire; it still retries a few times with a short backoff
    # as a fallback, since a busy state can also be transient (e.g. the
    # OS finishing cleanup of a just-killed process) even with nothing
    # left for lsof to find.
    stale_output_dir = run_dir / config_file.stem
    if stale_output_dir.exists():
        _kill_processes_using_path(stale_output_dir)
        last_error = None
        for attempt in range(5):
            try:
                shutil.rmtree(str(stale_output_dir))
                last_error = None
                break
            except OSError as e:
                last_error = e
                time.sleep(1)
        if last_error is not None:
            raise FormalCheckError(
                "Could not remove stale output directory '%s' after 5 "
                "retries (%s). This usually means a process from a "
                "PREVIOUS eqy run is still alive with its working "
                "directory inside it (check for orphaned eqy/yosys/sby/"
                "sat processes and kill them), or - especially on an "
                "NFS-mounted home directory - a stale lock left behind "
                "by a run that was killed rather than exiting cleanly. "
                "Try manually removing it once any lingering processes "
                "are gone: rm -rf %s"
                % (stale_output_dir, last_error, stale_output_dir)
            )

    # Launched with start_new_session=True so this process becomes the
    # leader of its OWN process group (pgid == pid) - required for the
    # timeout handling below. Plain subprocess.run(..., timeout=...)
    # only SIGKILLs the single top-level 'eqy' PID when the timeout
    # fires; eqy itself spawns further subprocesses (make -> yosys/sby/
    # the actual SAT/SMT solver) as its own children, and killing just
    # the parent leaves those running - orphaned, still holding files
    # open in the output directory (this is exactly what caused the
    # "Device or resource busy" stale-directory error above: a leftover
    # yosys process from a PREVIOUS run whose eqy parent had been killed
    # by an earlier timeout, still grinding away 87+ minutes later).
    # Using a dedicated process group lets us kill the entire tree at
    # once via os.killpg() instead of just the top PID.
    proc = subprocess.Popen(
        ["eqy", config_name],
        cwd=str(run_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        stdout_bytes, _ = proc.communicate(timeout=timeout)
    except FileNotFoundError:
        raise FormalCheckError("eqy not found on PATH.")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # already exited between the timeout firing and this call
        proc.wait()
        return {"equivalent": False, "output_dir": None, "timed_out": True,
                "log_text": "EQY timed out after %ds (process group killed)" % timeout}

    log_text = stdout_bytes.decode("utf-8", errors="replace")

    # EQY names its output dir after the config file without extension
    output_dir = run_dir / config_file.stem

    # Authoritative check: EQY writes a PASS or FAIL marker file
    equivalent = (output_dir / "PASS").exists()
    if not equivalent and not (output_dir / "FAIL").exists():
        # neither marker present - something went wrong before EQY
        # could conclude (crash, bad config, etc.) - fall back to
        # scanning the log text as a secondary signal
        equivalent = bool(re.search(r"Successfully proved designs equivalent", log_text))

    return {
        "equivalent": equivalent,
        "output_dir": str(output_dir),
        "timed_out": False,
        "log_text": log_text,
    }


def check_equivalence(gold_dir, gate_dir, top_module,
                       config_path="formal/check.eqy", depth=5, timeout=300,
                       check_module=None, added_stages=0, sat_timeout=120,
                       stretched_ports=None):
    """Full convenience wrapper: generate config -> run EQY -> result.

    check_module: see generate_eqy_config() - pass the specific module
    that was actually patched (e.g. from patch_applier.py's returned
    module_name) to scope the equivalence check to just that module's
    subtree instead of the whole design. Strongly recommended for any
    design bigger than a handful of modules - see generate_eqy_config()
    docstring for why.

    added_stages: the patch's self-reported PIPELINE_STAGES_ADDED value
    (from orchestrator.py, sourced via llm_client.get_rtl_patch) -
    pass through unchanged so a latency-adding patch gets compared
    against a latency-matched gold wrapper instead of a phase-mismatched
    direct comparison. See generate_eqy_config()/generate_gold_wrapper()
    for why this is necessary. 0 (default) preserves prior behavior
    exactly - same-cycle equivalence, no wrapper.

    stretched_ports: the patch's self-reported STRETCHED_PORTS value
    (from llm_client.get_rtl_patch/extract_stretched_ports) - pass
    through unchanged so a status/handshake output whose asserted
    duration genuinely widened gets OR-reduced across the delay stages
    instead of plainly delayed. See generate_gold_wrapper()'s docstring.
    Ignored when added_stages == 0.

    sat_timeout: see generate_eqy_config() - EQY's native per-strategy
    timeout, distinct from the 'timeout' argument above (which only
    kills the whole subprocess, with no graceful sat->sby handoff).

    Returns dict: {equivalent, output_dir, config_path, log_path}."""
    config = generate_eqy_config(gold_dir, gate_dir, top_module, config_path,
                                  depth, check_module=check_module,
                                  added_stages=added_stages,
                                  sat_timeout=sat_timeout,
                                  stretched_ports=stretched_ports)
    result = run_eqy(config, timeout=timeout)

    log_path = Path(config_path).parent / "eqy_log.txt"
    log_path.write_text(result["log_text"])

    return {
        "equivalent": result["equivalent"],
        "output_dir": result["output_dir"],
        "timed_out": result.get("timed_out", False),
        "config_path": config,
        "log_path": str(log_path),
    }


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    gold = sys.argv[1] if len(sys.argv) > 1 else "verilog"
    gate = sys.argv[2] if len(sys.argv) > 2 else "verilog_iterations/iter_1"
    top = sys.argv[3] if len(sys.argv) > 3 else "top"

    result = check_equivalence(gold, gate, top)
    print("Equivalent:", result["equivalent"])
    print("Output dir:", result["output_dir"])
    print("Config:", result["config_path"])
    print("Log:", result["log_path"])
