"""
prompt_builder.py
Builds LLM prompts for RTL timing fixes. Runs a lightweight heuristic
classifier on the violation + path data to suggest likely-applicable
optimization techniques (pipelining, retiming, logic restructuring,
FSM re-encoding, register balancing, resource duplication), then
constructs a scoped prompt containing only the relevant module(s).
"""

import re


ALLOWED_TECHNIQUES = [
    "pipelining",
    "retiming",
    "logic restructuring",
    "FSM re-encoding",
    "register balancing",
    "resource duplication",
]


# ---------------------------------------------------------------------------
# Classifier - suggests likely techniques from path + module data
# ---------------------------------------------------------------------------

def classify_violation(worst_path, all_paths, module_source):
    """Returns a list of (technique, reason) hint tuples based on
    heuristics over the timing path and RTL structure. Best-effort only -
    these are hints for the LLM prompt, not hard rules.
    """
    hints = []

    if not worst_path.stages:
        return hints

    stage_count = len(worst_path.stages)
    delays = [s.delay for s in worst_path.stages]
    max_stage_delay = max(delays)
    total_delay = worst_path.data_arrival_time or sum(delays)

    # --- Pipelining: many stages, delay spread fairly evenly ---
    if stage_count >= 4 and max_stage_delay < 0.4 * total_delay:
        hints.append((
            "pipelining",
            "Path has %d combinational stages with delay spread across "
            "them (no single dominant gate) - inserting a pipeline "
            "register mid-chain could split this into two faster stages."
            % stage_count
        ))

    # --- Logic restructuring: one gate dominates the delay ---
    if max_stage_delay >= 0.4 * total_delay:
        dominant = max(worst_path.stages, key=lambda s: s.delay)
        hints.append((
            "logic restructuring",
            "A single cell (%s, %s) contributes %.2fns of the %.2fns "
            "path delay - consider restructuring/simplifying this "
            "logic or using a wider/faster equivalent cell."
            % (dominant.instance, dominant.cell_type, dominant.delay, total_delay)
        ))

    # --- Retiming: nearby paths in same region show uneven slack ---
    same_region_prefix = worst_path.startpoint.split("/")[0]
    same_region = [
        p for p in all_paths
        if p.startpoint.split("/")[0] == same_region_prefix and p.stages
    ]
    if len(same_region) >= 2:
        slacks = [p.slack for p in same_region]
        spread = max(slacks) - min(slacks)
        if spread > 0.3:
            hints.append((
                "retiming",
                "Paths within this region show uneven slack (spread of "
                "%.2fns across %d nearby paths) - register boundaries "
                "may be unbalanced; retiming could redistribute logic "
                "between adjacent pipeline stages." % (spread, len(same_region))
            ))

    # --- Register balancing: similar signal to retiming, chain of regs ---
    if stage_count >= 3 and 0.3 <= max_stage_delay / max(total_delay, 0.01) < 0.6:
        hints.append((
            "register balancing",
            "Path shows moderately uneven per-stage delay - balancing "
            "register placement across the existing pipeline stages "
            "may help without adding new registers."
        ))

    # --- FSM re-encoding: case statement present in module source ---
    if module_source and re.search(r"\bcase\s*\(", module_source):
        hints.append((
            "FSM re-encoding",
            "Module contains a case statement (possible FSM) - if the "
            "violating path passes through state decode logic, "
            "re-encoding (e.g. one-hot) may shorten the critical path."
        ))

    # --- Resource duplication: high fanout on a stage feeding the path ---
    # Severity is scaled, not a single generic sentence for every case:
    # a fanout of 5 and a fanout of 700 call for very different framing -
    # the latter is a structural problem (a single gate driving hundreds
    # of loads with no buffering), not a minor tuning opportunity, and
    # is usually visible as extreme SLEW degradation as much as delay.
    high_fanout_stages = [s for s in worst_path.stages if s.fanout >= 4]
    if high_fanout_stages:
        worst_fanout_stage = max(high_fanout_stages, key=lambda s: s.fanout)
        fanout = worst_fanout_stage.fanout
        slew = worst_fanout_stage.slew

        is_register_driver = worst_fanout_stage.pin in ("Q", "QN")

        if fanout >= 100 and is_register_driver:
            severity = (
                "EXTREME fanout (%d) on register %s (pin %s) - this "
                "register's value is read by many separate comparators/"
                "consumers, not by one shared wire. Duplicating the "
                "register alone is not enough: you must also (1) create "
                "2+ identically-assigned copies of this register, (2) "
                "SPLIT its downstream readers so each copy feeds a "
                "distinct subset of consumers, and (3) add "
                "'(* keep = \"true\" *)' above each copy so synthesis "
                "does not merge them back into one net. A single "
                "duplicate register with all consumers still reading "
                "both copies fixes nothing."
                % (fanout, worst_fanout_stage.instance, worst_fanout_stage.pin)
            )
        elif fanout >= 100:
            severity = (
                "EXTREME fanout (%d) on combinational cell %s (%s) - a "
                "single gate is directly driving %d loads with no "
                "buffering. Insert an explicit buffer tree or duplicate "
                "this specific gate to split the load, so no single "
                "instance drives more than ~15-20."
                % (fanout, worst_fanout_stage.instance,
                   worst_fanout_stage.cell_type, fanout)
            )
        elif fanout >= 20:
            severity = (
                "High fanout (%d) on %s, with slew %.2fns at that stage - "
                "duplicate the driving gate/register to split the load "
                "across two drivers, each handling roughly half the fanout."
                % (fanout, worst_fanout_stage.instance, slew)
            )
        else:
            severity = (
                "Stage(s) with fanout >= 4 detected (%s) - duplicating the "
                "driving gate/register to split the load may reduce delay "
                "at some area cost."
                % ", ".join(s.instance for s in high_fanout_stages)
            )

        hints.append(("resource duplication", severity))

    return hints


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PREAMBLE = """You are an expert RTL timing-closure engineer. You will be \
given a Verilog module and a timing violation found by static timing analysis. \
Suggest a minimal, targeted code change to fix the violation.

Rules:
- Only modify the module shown below. Do not rename ports or change the module interface.
- Keep the fix as small and localized as possible.
- Preserve functional correctness - the patched RTL must remain logically equivalent \
to the original (this will be verified via EQY equivalence checking) in steady-state \
behavior, unless pipelining intentionally adds latency (acceptable for setup fixes).
- Any suggested techniques mentioned below are optional starting points, not \
requirements - they are heuristic guesses made before seeing your response. Use \
your own judgement; if a different approach is genuinely better for this specific \
violation, use that instead.
- If your fix removes combinational delay by pre-computing something from an \
EXISTING register (e.g. a case/comparison on a signal that is itself just a \
slice or check of another register) and storing the result in a NEW register \
that is kept "in sync" with the original via matching update conditions \
elsewhere in the same always block: do NOT do this. This pattern (a new \
register shadowing/duplicating state that is only guaranteed consistent \
because two separate always-block branches happen to update together) reliably \
fails formal equivalence checking in this flow, even when it is behaviorally \
correct - the equivalence checker verifies each output's logic cone mostly in \
isolation and cannot see the cross-register invariant that ties the new \
register to the original one, so it will treat them as independent and \
report a false failure. If you want to remove combinational logic from an \
OUTPUT's critical path, instead register that OUTPUT directly (e.g. change \
`assign A1 = f(i_decode)` to a `reg` driven by `A1 <= f(i_decode)` inside the \
existing clocked always block, using i_decode - or whatever signal already \
holds the needed value - directly, not a new signal that duplicates a check \
already being made elsewhere). This is a standard 1-cycle latency addition: \
report it via PIPELINE_STAGES_ADDED as described below, and it will be \
verified correctly against a latency-matched reference automatically. Prefer \
this over introducing any new register whose only purpose is to mirror/track \
an existing signal's derived value.
- The FIRST line of your response must be a comment, in this exact format:
    // FIX_DESCRIPTION: <one sentence>
  describing in your own words, specifically, what you actually changed and why \
it should help (e.g. "Inserted a pipeline register between the multiplier's \
partial-product stage and the final adder to split the critical path" or \
"Restructured the priority-encoder chain to reduce logic depth from 6 levels to 3"). \
Do not just restate a technique name - describe the actual change.
- The SECOND line of your response must be a comment, in this exact format:
    // PIPELINE_STAGES_ADDED: <integer>
  stating exactly how many additional clock cycles of output latency your change \
introduces, relative to the original module. This is not limited to techniques \
labeled "pipelining" - ANY change that converts a signal from combinational \
(assign, or an always @(*) block) to synchronous (assigned with <= inside an \
always @(posedge clk...) block) adds exactly 1 cycle of latency to that signal \
and everything downstream of it within this module, REGARDLESS of what you call \
the technique or why you did it (e.g. "registering an output to break a \
critical path", "adding a hold register", "buffering a signal with a flop" all \
add 1 stage each, even if the word "pipeline" never appears in your own \
description). If you converted N formerly-combinational signals on the same \
input-to-output path into registers, that path's latency increases by N, not \
by however many of them you personally think of as "pipeline stages" - count \
every new register on the path, one cycle each. Use 0 ONLY if every output of \
this module is driven by the exact same combinational-vs-sequential structure \
(same signals still 'assign'-driven if they were before, same signals still \
inside the same always @(posedge...) blocks if they were before) as the \
original - i.e. no output's relationship to the clock changed at all. Before \
writing this number, re-examine your own diff specifically for any output (or \
any internal signal that an output depends on) that used to be combinational \
and is now inside a posedge-clocked always block, or vice versa - this is the \
single most common way this count gets under-reported, and an incorrect count \
here will cause equivalence checking to give a misleading result.
- The THIRD line of your response must be a comment, in this exact format:
    // STRETCHED_PORTS: <comma-separated port names, or "none">
  listing any OUTPUT port whose ASSERTED DURATION changed, not just its timing. \
This is different from PIPELINE_STAGES_ADDED, which only covers WHEN a signal \
appears. A port needs listing here specifically when it is a status/handshake \
signal (e.g. "busy", "valid_out") that used to pulse for a fixed, short number \
of cycles while the original computation ran, and your change made that same \
computation take more clock cycles (e.g. converting a single-cycle combinational \
computation into a multi-cycle iterative one) - such a signal must now stay \
asserted for LONGER, covering the whole new computation window, not just move \
to a later moment while keeping its old short duration. Do NOT list a port here \
just because it now appears later (that is what PIPELINE_STAGES_ADDED already \
covers) - only list a port whose asserted WIDTH (how many consecutive cycles \
it stays high) is itself different from the original, wider by the same amount \
as PIPELINE_STAGES_ADDED. If no output's asserted duration changed - the normal \
case for a simple pipeline-register insertion - write "none".
- Return ONLY the full modified module (module ... endmodule), wrapped in a single \
```verilog code block, with the FIX_DESCRIPTION comment as its first line, the \
PIPELINE_STAGES_ADDED comment as its second line, and the STRETCHED_PORTS comment \
as its third line. \
Do not include explanations outside the code block.
"""


def _format_module_selection(modules):
    """Builds an explicit list of which modules were provided, their
    role (startpoint/endpoint/both), and a hard requirement that the
    LLM pick exactly one of them by name. Without this, when multiple
    modules are shown (e.g. a path crossing hierarchy from
    pipeline_reg2 through riscv_top's wiring into data_mem), there is
    no correspondence given at all between the modules shown and which
    one actually needs the fix - the LLM decides silently, and if it
    ever returns more than one module block, only the first would be
    applied (the rest silently dropped) unless patch_applier.py's
    single-module enforcement rejects it outright (see patch_applier.py).
    """
    allowed_names = [m.name for m in modules]
    lines = ["Modules provided (choose exactly ONE of these to modify):"]
    for m in modules:
        role = m.role or ""
        if role == "both_leaf":
            note = "contains BOTH the startpoint and endpoint - most likely candidate"
        elif role == "startpoint_leaf":
            note = "the STARTPOINT's own module (launch register/logic) - likely candidate"
        elif role == "endpoint_leaf":
            note = "the ENDPOINT's own module (capture register/logic) - likely candidate"
        elif role.endswith("ancestor"):
            note = (
                "a HIERARCHY WRAPPER the path passes through, not the leaf module "
                "itself - only modify this if it contains glue/combinational logic "
                "written DIRECTLY in its own body (not inside a further submodule) "
                "that lies on this specific path; otherwise prefer a module above"
            )
        else:
            note = "related to this path"
        lines.append("  - %s  (%s)" % (m.name, note))
    lines.append("")
    lines.append(
        "You MUST modify exactly ONE module from this list: %s. A pure "
        "hierarchy-wrapper module (one that only instantiates the others "
        "and contains no logic of its own relevant to this path) is "
        "rarely the right target - prefer a module marked as containing "
        "the startpoint, endpoint, or both, unless the violation clearly "
        "originates in wiring/glue logic at the wrapper level. "
        "Return ONLY that one module's full text. If you modify a module "
        "not in this list, or return more than one module, your patch "
        "will be rejected." % ", ".join(allowed_names)
    )
    return "\n".join(lines)


def _format_path_summary(path):
    lines = [
        "Startpoint: %s" % path.startpoint,
        "Endpoint:   %s" % path.endpoint,
        "Path type:  %s (%s)" % (path.path_type, "setup" if path.path_type == "max" else "hold"),
        "Slack:      %.3f ns (VIOLATED)" % path.slack,
        "",
        "Path stages:",
    ]
    for s in path.stages:
        lines.append(
            "  %-30s %-14s fanout=%-3s cap=%-5s slew=%-5s delay=%.2fns"
            % (s.instance, s.cell_type, s.fanout, s.cap, s.slew, s.delay)
        )
    return "\n".join(lines)


def _format_hints(hints):
    if not hints:
        return "No strong heuristic signal - use your own judgement on the best fix."
    lines = [
        "Possible starting points, based on simple heuristics over the path data "
        "below (these are guesses, not requirements - ignore them if you see a "
        "better fix for this specific violation):"
    ]
    for technique, reason in hints:
        lines.append("  - %s: %s" % (technique, reason))
    return "\n".join(lines)


def build_setup_prompt(worst_path, all_paths, modules):
    """modules: list of ModuleInfo from module_extractor.py"""
    hints = classify_violation(worst_path, all_paths,
                                modules[0].source if modules else "")
    module_text = "\n\n".join(
        "// File: %s\n%s" % (m.filepath, m.source) for m in modules
    )

    prompt = _SYSTEM_PREAMBLE + """
This is a SETUP violation: data is arriving too late relative to the clock. \
Valid fix directions: reduce combinational delay (pipelining, logic restructuring, \
retiming, register balancing, resource duplication) or, if applicable, FSM re-encoding. \
Do NOT simply add delay - that fixes hold, not setup.

--- Timing violation ---
%s

--- Heuristic hints ---
%s

--- %s ---

--- RTL module(s) ---
%s
""" % (_format_path_summary(worst_path), _format_hints(hints),
       _format_module_selection(modules), module_text)

    return prompt


def build_hold_prompt(worst_path, all_paths, modules):
    """modules: list of ModuleInfo from module_extractor.py"""
    module_text = "\n\n".join(
        "// File: %s\n%s" % (m.filepath, m.source) for m in modules
    )

    prompt = _SYSTEM_PREAMBLE + """
This is a HOLD violation: data is arriving too early relative to the clock. \
Valid fix direction: insert delay (e.g. buffer cells / extra logic) on the \
offending path. Do NOT remove logic or speed up the path - that fixes setup, not hold. \
Be conservative: hold fixes should add the minimum delay needed to clear the \
violation without affecting other paths.

--- Timing violation ---
%s

--- %s ---

--- RTL module(s) ---
%s
""" % (_format_path_summary(worst_path), _format_module_selection(modules), module_text)

    return prompt


def build_retry_prompt(original_prompt, failed_patch, error_message):
    """Builds a follow-up prompt after syntax_check.py rejects a patch -
    shows the LLM its own broken output plus the exact compiler error,
    and asks for a corrected version. Used by orchestrator.py's
    MAX_SYNTAX_RETRIES loop (see config.py).

    original_prompt: the prompt string that produced the failed patch
                      (kept for context - violation details, hints, etc.)
    failed_patch:     the Verilog text that failed syntax_check.py
    error_message:    the exact iverilog error string from syntax_check.py
    """
    return original_prompt + """

--- Your previous attempt failed to compile ---
Your last response produced the following Verilog, which failed syntax
checking (iverilog -g2005 -tnull):

%s

Compiler error:
%s

Please fix ONLY the syntax error(s) causing this failure, keeping your
intended optimization approach the same. Return the full corrected
module (module ... endmodule), wrapped in a single ```verilog code
block, following the same rules as before.
""" % (failed_patch, error_message)


def build_alternative_prompt(worst_path, all_paths, modules, previous_patch,
                              rejection_reason, previously_tried_techniques=None):
    """Builds a follow-up prompt after a patch was REJECTED by the
    orchestrator's decision matrix (compiled fine, but made timing
    worse, or failed formal equivalence, or both) - this is different
    from build_retry_prompt(), which only handles syntax failures.
    Simply re-sending the original prompt would likely produce the same
    rejected patch again, so this version:
      - tells the LLM what was tried and why it was rejected
      - explicitly excludes previously-tried technique(s) from the
        suggested hints, steering it toward a genuinely different
        approach rather than a minor variation of the same one

    previous_patch:               the Verilog text that was rejected
    rejection_reason:             human-readable string, e.g.
                                   "Timing got worse (slack -0.42 -> -0.91)"
                                   or "Formal equivalence check failed"
                                   or both, combined
    previously_tried_techniques:  list of technique name strings already
                                   attempted for this violation (from
                                   prior classify_violation hints or
                                   orchestrator's own tracking) - these
                                   are excluded from the new hint list.
                                   None or [] if unknown.
    """
    excluded = set(previously_tried_techniques or [])
    module_source = modules[0].source if modules else ""

    all_hints = classify_violation(worst_path, all_paths, module_source)
    remaining_hints = [(t, r) for (t, r) in all_hints if t not in excluded]

    # If every heuristically-suggested technique has already been tried,
    # fall back to the full ALLOWED_TECHNIQUES list minus what's excluded,
    # so the LLM still has concrete options rather than nothing at all.
    if not remaining_hints:
        remaining_techniques = [t for t in ALLOWED_TECHNIQUES if t not in excluded]
        remaining_hints = [(t, "Not yet tried for this violation.") for t in remaining_techniques]

    base_prompt = build_prompt(worst_path, all_paths, modules)

    tried_list = ", ".join(sorted(excluded)) if excluded else "none recorded"

    return base_prompt + """

--- Your previous attempt was rejected ---
A prior patch for this exact violation was tried and rejected:

Reason: %s

Previously attempted technique(s): %s

Please try a genuinely DIFFERENT approach this time - do not repeat the
same technique. Consider instead:
%s

Return the full corrected module (module ... endmodule), wrapped in a
single ```verilog code block, following the same rules as before.
""" % (rejection_reason, tried_list, _format_hints(remaining_hints))


def build_prompt(worst_path, all_paths, modules):
    """Dispatches to setup or hold prompt based on path_type ('max' = setup, 'min' = hold)."""
    if worst_path.path_type == "min":
        return build_hold_prompt(worst_path, all_paths, modules)
    return build_setup_prompt(worst_path, all_paths, modules)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from report_parser import parse_all_reports, worst_violation
    from module_extractor import get_modules_for_path

    reports_dir = sys.argv[1] if len(sys.argv) > 1 else "reports"
    verilog_dir = sys.argv[2] if len(sys.argv) > 2 else "verilog"

    parsed = parse_all_reports(reports_dir)
    worst = worst_violation(parsed)
    if not worst:
        print("No violations found.")
        sys.exit(0)

    modules = get_modules_for_path(worst, verilog_dir)
    prompt = build_prompt(worst, parsed.critical_paths, modules)
    print(prompt)
