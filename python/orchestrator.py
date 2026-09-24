"""
orchestrator.py
The main closed loop. Ties every other module together:

    STA -> parse -> pick worst violation -> extract module -> build prompt
    -> LLM patch -> syntax check (retry on compile error) -> apply patch
    -> synthesize -> STA -> compare PPA -> formal equivalence check
    -> decision -> log -> ask user -> repeat

Decision matrix (per iteration):
    formal PASS + slack better        -> accept   (auto)
    formal PASS + slack worse/same    -> reject   (auto)
    formal FAIL + slack worse/same    -> reject   (auto)
    formal FAIL + slack better        -> ASK USER (ambiguous: could be a
                                         legitimate latency-adding fix
                                         such as pipelining, which plain
                                         EQY cannot verify, or a real
                                         functional bug)

After every iteration - accepted, rejected or user-decided - the loop
pauses and asks whether to continue to the next iteration.

Formal equivalence is always checked against the ORIGINAL baseline RTL,
not the most recently accepted iteration, to match the deliverable
"Formally verify equivalence between original and optimized RTL".

Python 3.6.8 compatible (no f-strings, no dataclasses).
"""

import shutil
import sys
from pathlib import Path

import config
from report_parser import (parse_all_reports, worst_violation,
                            recovery_removal_violations, cdc_violations,
                            path_group_excluded_violations,
                            compute_achievable_frequency,
                            parse_domain_worst_slack, parse_design_area,
                            parse_critical_paths, compute_filtered_wns,
                            parse_power_corner, parse_openroad_wns_tns)
from module_extractor import get_modules_for_path
from prompt_builder import (build_prompt, build_retry_prompt,
                             build_alternative_prompt, classify_violation)
from llm_client import get_rtl_patch, LLMError
from patch_applier import apply_patch, PatchError
from syntax_check import check_syntax, SyntaxCheckError
from synth_runner import synthesize, SynthError
from sta_runner import run_sta, STAError
from pnr_runner import run_pnr, PnRError
from generate_demo import generate_demo
from formal_check import check_equivalence, FormalCheckError
from logger import (build_record, log_iteration, summarize, render_markdown_report,
                     new_run_id, compute_ppa_comparison, append_ppa_section,
                     write_pnr_result, write_unresolved_exclusions,
                     write_overall_formal_result, render_formal_verification_report)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _hr(char="-"):
    print(char * 70)


def _violation_key(path):
    """Stable identity for a violation, so repeated attempts at the same
    path can be counted across iterations."""
    return "%s->%s" % (path.startpoint, path.endpoint)


def _violation_dict(path):
    """Converts a TimingPath into the plain dict logger.py expects."""
    return {
        "startpoint": path.startpoint,
        "endpoint": path.endpoint,
        "check_type": path.check_type,
        "path_group": path.path_group,
        "slack": path.slack,
    }


def _compute_per_domain_frequencies(reports_dir):
    """Computes achievable frequency SEPARATELY for each of the 5 clock
    domains, using each domain's OWN worst slack (from its own
    dedicated, unrestricted timing_*.txt file, which also covers that
    domain's generated/derived children) paired with that domain's OWN
    period.

    This replaces an earlier, incorrect approach that combined
    config.PRIMARY_CLOCK's period with parsed.wns_setup - the GLOBAL
    worst slack across ALL 5 domains combined. That produced a number
    that could mix one domain's period with a different domain's
    violation, corresponding to no real clock in the design. A 5-clock
    SoC does not have a single "frequency" - this returns 5 real ones.

    Returns {domain_name: {"period_ns", "worst_slack_ns", "frequency_mhz"}}.
    """
    result = {}
    for domain, filename in config.DOMAIN_TIMING_FILES.items():
        filepath = str(Path(reports_dir) / filename)
        period = config.CLOCK_PERIODS_NS.get(domain)
        worst_slack = parse_domain_worst_slack(filepath)
        freq = compute_achievable_frequency(period, worst_slack) if worst_slack is not None else None
        result[domain] = {
            "period_ns": period,
            "worst_slack_ns": worst_slack,
            "frequency_mhz": freq,
        }
    return result


def _gather_all_timing_paths(reports_dir, parsed):
    """Combines parsed.critical_paths with a FULL (not just single-
    worst-value) re-parse of every per-domain timing file, for
    compute_filtered_wns() to draw from.

    parsed.critical_paths alone isn't sufficient here: it may be
    sampled/capped by -group_count/-endpoint_path_count in sta.tcl (see
    parse_domain_worst_slack()'s docstring), so it could miss the true
    worst path for some domain entirely. The per-domain timing_*.txt
    files are NOT capped - re-parsing them fully (not just pulling
    their single worst-slack float via parse_domain_worst_slack, which
    doesn't retain check_type/clock info needed for filtering) gives a
    complete, correctly-filterable path set.
    """
    all_paths = list(parsed.critical_paths)
    for domain, filename in config.DOMAIN_TIMING_FILES.items():
        filepath = str(Path(reports_dir) / filename)
        all_paths.extend(parse_critical_paths(filepath))
    return all_paths


def _extract_metrics(reports_dir, area):
    """Pulls the full PPA + timing metric set out of a reports folder.
    Returns (parsed, metrics_dict)."""
    parsed = parse_all_reports(reports_dir)

    per_domain_freq = _compute_per_domain_frequencies(reports_dir)

    power_total = None
    if parsed.power and "total" in parsed.power:
        power_total = parsed.power["total"].get("total")

    # IMPORTANT: this WNS is filtered to exclude recovery/removal and
    # CDC paths, matching worst_violation()'s selection filtering
    # exactly (see compute_filtered_wns()'s docstring for the bug this
    # fixes) - it is NOT parsed.wns_setup (the raw, unfiltered OpenSTA
    # report), which used to let an unfixable, permanently-excluded
    # violation (e.g. a reset-recovery check) become the reported "WNS"
    # and silently block every future accept/reject decision once it
    # became the numerically worst path in the design.
    all_paths = _gather_all_timing_paths(reports_dir, parsed)
    filtered_wns = compute_filtered_wns(all_paths, clock_family_map=config.CLOCK_FAMILY_MAP)

    metrics = {
        "wns_setup": filtered_wns,
        "tns_setup": parsed.tns_setup,
        "area": area,
        "frequency_by_domain": per_domain_freq,
        "power_w": power_total,
    }
    return parsed, metrics


# PnR report filenames, confirmed directly against a real pnr.tcl and
# real report samples - CONFIRMED DIFFERENT from sta.tcl's filenames/
# formats in several real, non-cosmetic ways (see each parser's
# docstring in report_parser.py for specifics: parse_power_corner()
# for the two-corners-concatenated-with-no-marker issue,
# parse_openroad_wns_tns() for report_wns/report_tns being a
# genuinely different, simpler command+format than OpenSTA's
# report_worst_slack/report_tns). _extract_metrics() above is for
# sta.tcl's schema ONLY - do not point it at PnR reports.
PNR_TIMING_SETUP_FILE = "timing_setup_wc.rpt"
PNR_POWER_FILE = "power.rpt"
PNR_WNS_TNS_FILE = "wns.rpt"


def _compute_pnr_per_domain_frequencies(critical_paths):
    """PnR-side equivalent of _compute_per_domain_frequencies() above,
    adapted to a REAL, CONFIRMED difference: pnr.tcl produces ONE
    combined timing_setup_wc.rpt (all clocks together, each path
    already carrying its own path_group), not 5 separate per-domain
    files the way sta.tcl does via config.DOMAIN_TIMING_FILES. Domains
    are recovered here by GROUPING the already-parsed path list by
    path_group instead of reading separate files.

    NOTE: unlike _compute_per_domain_frequencies() (which reads
    dedicated, UNCAPPED per-domain files), this is only as complete as
    timing_setup_wc.rpt itself - if that report is capped/sampled
    (e.g. via -group_count in pnr.tcl's report_checks call), a
    domain's true worst path could be missing. Confirm pnr.tcl's exact
    report_checks flags if per-domain PnR frequencies look suspiciously
    good compared to the overall filtered WNS.
    """
    by_domain = {}
    for p in critical_paths:
        # Only group into REAL clock domains (ones config.CLOCK_PERIODS_NS
        # actually knows about) - path_group can also be a non-domain
        # label like "asynchronous" (seen on recovery/removal and CDC
        # paths in the real sample data), which isn't a clock and
        # would otherwise show up as a spurious entry with a null
        # period/frequency.
        if p.path_group not in config.CLOCK_PERIODS_NS:
            continue
        by_domain.setdefault(p.path_group, []).append(p)

    result = {}
    for domain, paths in by_domain.items():
        period = config.CLOCK_PERIODS_NS.get(domain)
        worst_slack = min(p.slack for p in paths) if paths else None
        freq = compute_achievable_frequency(period, worst_slack) if (
            worst_slack is not None and period is not None) else None
        result[domain] = {
            "period_ns": period,
            "worst_slack_ns": worst_slack,
            "frequency_mhz": freq,
        }
    return result


def _extract_pnr_metrics(reports_dir, area):
    """PnR-side equivalent of _extract_metrics() above, built against
    CONFIRMED REAL pnr.tcl report filenames and formats (see the
    PNR_*_FILE constants above) rather than assuming reuse of
    sta.tcl's schema - that assumption was tested directly against
    real report samples and found wrong in several specific ways.

    Returns the SAME metrics dict shape _extract_metrics() produces
    ({wns_setup, tns_setup, area, frequency_by_domain, power_w}), so
    compute_ppa_comparison() and everything downstream of it keeps
    working unchanged regardless of which side (synthesis-stage vs.
    post-route) produced the dict.
    """
    d = Path(reports_dir)
    critical_paths = parse_critical_paths(str(d / PNR_TIMING_SETUP_FILE))

    # Filtered the same way as the synthesis-stage fix (see
    # compute_filtered_wns()'s docstring) - the real sample data
    # confirms recovery/removal checks (e.g. a reset-recovery path)
    # DO appear mixed into timing_setup_wc.rpt, so the same
    # contamination risk applies here, not just on the synthesis side.
    wns_setup = compute_filtered_wns(critical_paths, clock_family_map=config.CLOCK_FAMILY_MAP)

    per_domain_freq = _compute_pnr_per_domain_frequencies(critical_paths)

    # TNS: uses OpenROAD's own report_tns figure (wns.rpt) rather than
    # summing critical_paths, since that file may not contain EVERY
    # violated path (no guarantee report_checks in pnr.tcl was run
    # without a group/count cap) - summing an incomplete list would
    # UNDERSTATE the true TNS. This has the same "indicative only"
    # caveat the synthesis-side TNS already carries (see the demo
    # report's footnote) - not re-derived here, just carried over.
    wns_tns = parse_openroad_wns_tns(str(d / PNR_WNS_TNS_FILE))
    tns_setup = wns_tns.get("tns")

    power_data = parse_power_corner(str(d / PNR_POWER_FILE), corner_index=0)  # wc = worst-case, index 0
    power_total = power_data.get("total", {}).get("total")

    metrics = {
        "wns_setup": wns_setup,
        "tns_setup": tns_setup,
        "area": area,
        "frequency_by_domain": per_domain_freq,
        "power_w": power_total,
    }
    return metrics


def _print_metrics(label, metrics):
    print("%s:" % label)
    print("  WNS (setup): %s ns" % metrics["wns_setup"])
    print("  TNS (setup): %s ns" % metrics["tns_setup"])
    print("  Area:        %s" % metrics["area"])
    print("  Max Frequency by domain:")
    for domain, d in metrics["frequency_by_domain"].items():
        freq = d["frequency_mhz"]
        print("    %-10s %s MHz  (worst slack %s ns @ %s ns period)" % (
            domain, round(freq, 2) if freq is not None else "N/A",
            d["worst_slack_ns"], d["period_ns"]))
    print("  Power:       %s W" % metrics["power_w"])


def _print_ppa_comparison(synth_metrics, pnr_metrics):
    """Prints a synthesis-stage vs. post-route PPA comparison to the
    console. Uses logger.compute_ppa_comparison() for the actual
    comparison data (including sign-flip detection) so this console
    view and the persisted markdown section (logger.append_ppa_section,
    called separately after this) can never drift apart - see that
    function's docstring for why sign flips specifically matter here.
    """
    def _fmt(v, places=3):
        if v is None:
            return "N/A"
        try:
            return str(round(v, places))
        except TypeError:
            return str(v)

    comparison = compute_ppa_comparison(synth_metrics, pnr_metrics)
    s_wns, p_wns = comparison["wns_setup"]
    s_tns, p_tns = comparison["tns_setup"]
    s_area, p_area = comparison["area"]
    s_pow, p_pow = comparison["power_w"]

    print("PPA Comparison: Synthesis-stage vs. Post-Route")
    print("  WNS (setup): %s -> %s ns" % (_fmt(s_wns), _fmt(p_wns)))
    print("  TNS (setup): %s -> %s ns" % (_fmt(s_tns), _fmt(p_tns)))
    area_note = ("  (could not parse post-route area - check "
                 "reports/area.rpt exists under the PnR reports dir)"
                 if p_area is None else "")
    print("  Area:        %s -> %s%s" % (_fmt(s_area, 2), _fmt(p_area, 2), area_note))
    print("  Power:       %s -> %s W" % (_fmt(s_pow), _fmt(p_pow)))

    print("  Max Frequency by domain:")
    for domain, s_freq, p_freq in comparison["domains"]:
        print("    %-10s %s -> %s MHz" % (domain, _fmt(s_freq, 2), _fmt(p_freq, 2)))

    if comparison["sign_flips"]:
        print("")
        print("  *** WARNING: timing sign flip(s) between synthesis and "
              "post-route ***")
        for domain, s_ok, p_ok in comparison["sign_flips"]:
            if s_ok and not p_ok:
                print("    %-10s MET at synthesis-stage STA, but VIOLATED "
                      "post-route - real routing parasitics broke a path "
                      "that looked fine before physical implementation."
                      % domain)
            else:
                print("    %-10s VIOLATED at synthesis-stage STA, but MET "
                      "post-route - possible, though less common (e.g. "
                      "OpenROAD's own optimization/buffering during CTS "
                      "or routing recovered slack synthesis-stage "
                      "estimates didn't account for)." % domain)

    return comparison



def _ask(question, valid):
    """Prompts until the user enters one of `valid` (case-insensitive).
    Returns the lowercase answer."""
    options = "/".join(valid)
    while True:
        try:
            answer = raw_input("%s [%s]: " % (question, options))  # noqa: F821 (py2 fallback)
        except NameError:
            answer = input("%s [%s]: " % (question, options))
        answer = answer.strip().lower()
        if answer in valid:
            return answer
        print("Please enter one of: %s" % options)


def _should_continue_iterating():
    """Replaces the repeated `_ask("Continue to the next iteration?",
    ["y", "n"])` pattern at every early-exit/end-of-iteration point in
    run(). When config.INTERACTIVE_MODE is off, auto-continues without
    asking (printing a short note so this is visible in the transcript,
    not silent) - config.MAX_ITERATIONS still caps the loop regardless,
    so this can never run unattended forever.
    """
    if not config.INTERACTIVE_MODE:
        print("(non-interactive mode - continuing automatically)")
        return True
    return _ask("Continue to the next iteration?", ["y", "n"]) == "y"


def _slack_improved(before, after):
    """True if `after` is meaningfully better (less negative) than `before`.
    Treats missing values as 'not improved' rather than guessing."""
    if before is None or after is None:
        return False
    return (after - before) > config.SLACK_IMPROVEMENT_THRESHOLD


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def run_synth_and_sta(verilog_dir, iteration_label):
    """Synthesize a given RTL directory, then run STA on the resulting
    netlist. Both stages write into per-iteration folders so a failed
    run's logs survive for inspection afterward.
    Returns (success, area, reports_dir, message, synth_log_path,
             netlist_path). netlist_path is None on any failure before
             synthesis produces one - only meaningful when success=True.
    """
    try:
        synth = synthesize(verilog_dir, config.TOP_MODULE, config.LIBERTY_PATH,
                            output_dir=config.SYNTH_OUTPUT_DIR,
                            iteration_label=iteration_label,
                            module_clock_map=config.MODULE_CLOCK_MAP,
                            clock_periods_ns=config.CLOCK_PERIODS_NS,
                            catchall_clock=config.PRIMARY_CLOCK)
    except SynthError as e:
        return False, None, None, "Synthesis error: %s" % e, None, None

    if not synth["success"]:
        return (False, None, None,
                "Synthesis failed (see %s)" % synth["log_path"], synth["log_path"], None)

    try:
        sta = run_sta(sta_dir=config.STA_DIR,
                       tcl_script=config.STA_TCL_SCRIPT,
                       netlist_src=synth["netlist_path"],
                       top_module=config.TOP_MODULE,
                       source_sta_dir=config.SOURCE_STA_DIR,
                       iteration_label=iteration_label,
                       timeout=config.STA_TIMEOUT)
    except STAError as e:
        return False, synth["area"], None, "STA error: %s" % e, synth["log_path"], synth["netlist_path"]

    if not sta["success"]:
        return (False, synth["area"], None,
                "STA failed (see %s)" % sta["log_path"], synth["log_path"], synth["netlist_path"])

    return True, synth["area"], sta["reports_dir"], "", synth["log_path"], synth["netlist_path"]


def get_patch_with_syntax_retries(prompt, baseline_dir, iteration_num, allowed_modules=None):
    """Calls the LLM, applies the patch, and syntax-checks it. On a
    compile failure, re-prompts with the exact compiler error up to
    config.MAX_SYNTAX_RETRIES times.

    allowed_modules: module names the patch is permitted to target
    (see patch_applier.apply_patch) - typically the same module names
    shown to the LLM in the prompt.

    Returns (ok, iter_dir, module_name, fix_description,
             pipeline_stages_added, stretched_ports, retries_used, message).
    fix_description is the LLM's own free-text description of what it did (from
    the required TECHNIQUE_USED marker - see prompt_builder.py), or
    None if it was missing/malformed on the successful attempt.
    pipeline_stages_added is the LLM's self-reported added output latency
    (int, 0 if none/missing - see llm_client.extract_pipeline_stages_added),
    used by formal_check.py to build a latency-matched gold wrapper instead
    of comparing gold/gate at a mismatched cycle offset.
    stretched_ports is the LLM's self-reported list of output ports whose
    asserted DURATION (not just timing) changed (list of str, empty if
    none/missing - see llm_client.extract_stretched_ports), used by
    formal_check.py to widen those specific ports in the gold wrapper
    instead of just delaying them - see generate_gold_wrapper()'s
    docstring for why a plain delay can't handle a stretched status signal.
    """
    current_prompt = prompt

    for attempt in range(config.MAX_SYNTAX_RETRIES + 1):
        try:
            patch_text, fix_description, pipeline_stages_added, stretched_ports = get_rtl_patch(
                current_prompt, provider=config.LLM_PROVIDER,
                retries=config.MAX_LLM_RETRIES, model=config.LLM_MODEL)
        except LLMError as e:
            return False, None, None, None, 0, [], attempt, "LLM error: %s" % e

        try:
            iter_dir, patched_file, module_name = apply_patch(
                baseline_dir, patch_text, iteration_num,
                output_root=config.VERILOG_ITERATIONS_ROOT,
                allowed_modules=allowed_modules)
        except PatchError as e:
            return False, None, None, None, 0, [], attempt, "Patch rejected: %s" % e

        try:
            ok, error_msg = check_syntax(iter_dir)
        except SyntaxCheckError as e:
            return False, None, None, None, 0, [], attempt, "Syntax check error: %s" % e

        if ok:
            return (True, iter_dir, module_name, fix_description,
                     pipeline_stages_added, stretched_ports, attempt, "")

        print("  Syntax check failed (attempt %d/%d):" % (
            attempt + 1, config.MAX_SYNTAX_RETRIES + 1))
        print("    %s" % error_msg.replace("\n", "\n    "))

        if attempt < config.MAX_SYNTAX_RETRIES:
            print("  Re-prompting the LLM with the compiler error...")
            current_prompt = build_retry_prompt(prompt, patch_text, error_msg)

    return (False, None, None, None, 0, [], config.MAX_SYNTAX_RETRIES,
            "Patch still failed syntax check after %d retries" % config.MAX_SYNTAX_RETRIES)


def decide(formal_equivalent, slack_before, slack_after):
    """Applies the decision matrix. Returns (decision, reason).
    decision is one of 'accept', 'reject', 'pending_user'."""
    improved = _slack_improved(slack_before, slack_after)

    if formal_equivalent and improved:
        return "accept", "Formal equivalence passed and slack improved (%s -> %s)" % (
            slack_before, slack_after)

    if formal_equivalent and not improved:
        return "reject", "Formal equivalence passed but slack did not improve (%s -> %s)" % (
            slack_before, slack_after)

    if not formal_equivalent and not improved:
        return "reject", "Formal equivalence failed and slack did not improve (%s -> %s)" % (
            slack_before, slack_after)

    return "pending_user", (
        "Formal equivalence FAILED but slack improved (%s -> %s)." % (
            slack_before, slack_after))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run():
    run_id = new_run_id()
    _hr("=")
    print("NEBULA - GenAI RTL Timing Optimization Framework")
    _hr("=")
    print("Run ID       : %s" % run_id)
    print("Baseline RTL : %s" % config.BASELINE_VERILOG_DIR)
    print("Top module   : %s" % config.TOP_MODULE)
    print("LLM provider : %s" % config.LLM_PROVIDER)
    print("Max iters    : %d" % config.MAX_ITERATIONS)
    print("")

    original_rtl_dir = config.BASELINE_VERILOG_DIR
    current_baseline_dir = original_rtl_dir

    # ---------------- Baseline ----------------
    print("Establishing baseline (synthesis + STA)...")
    ok, area, reports_dir, msg, _synth_log, current_netlist_path = run_synth_and_sta(current_baseline_dir, "baseline")
    if not ok:
        print("Baseline failed: %s" % msg)
        return 1

    parsed, baseline_metrics = _extract_metrics(reports_dir, area)
    _print_metrics("Baseline", baseline_metrics)

    _warn_unmapped_clocks(parsed)

    rr = recovery_removal_violations(parsed)
    cdc = cdc_violations(parsed, clock_family_map=config.CLOCK_FAMILY_MAP)
    pg_only = path_group_excluded_violations(
        parsed, clock_family_map=config.CLOCK_FAMILY_MAP)
    if rr:
        print("  Note: %d recovery/removal violation(s) present - excluded from "
              "the auto-fix loop (async reset checks, different fix class)." % len(rr))
    if cdc:
        print("  Note: %d confirmed cross-domain (CDC) violation(s) present - "
              "excluded from the auto-fix loop (patching these could break "
              "metastability protection)." % len(cdc))
    if pg_only:
        print("  Note: %d violation(s) excluded by path_group label alone - "
              "same clock family, so some may be false exclusions. Listed in "
              "full at the end of the run." % len(pg_only))
    print("")

    log_iteration(config.LOG_PATH, build_record(
        run_id=run_id,
        iteration="baseline",
        wns_setup_after=baseline_metrics["wns_setup"],
        tns_setup_after=baseline_metrics["tns_setup"],
        area_after=baseline_metrics["area"],
        frequency_by_domain_after=baseline_metrics["frequency_by_domain"],
        power_after_w=baseline_metrics["power_w"],
        llm_provider=config.LLM_PROVIDER,
    ))

    current_metrics = baseline_metrics
    current_reports_dir = reports_dir
    rejected_counts = {}     # violation_key -> times rejected
    tried_techniques = {}    # violation_key -> [technique names attempted]
    last_rejection_reason = {}  # violation_key -> the actual reason it was most recently rejected

    # ---------------- Iterations ----------------
    for iteration in range(1, config.MAX_ITERATIONS + 1):
        _hr("=")
        print("ITERATION %d" % iteration)
        _hr("=")

        parsed = parse_all_reports(current_reports_dir)
        worst = worst_violation(parsed, clock_family_map=config.CLOCK_FAMILY_MAP)

        if worst is None:
            print("No fixable violations remain. Timing closure reached.")
            break

        vkey = _violation_key(worst)

        if rejected_counts.get(vkey, 0) > config.MAX_REJECTED_RETRIES_PER_VIOLATION:
            print("Violation %s has been rejected %d times - giving up on it." % (
                vkey, rejected_counts[vkey]))
            print("No other fixable violation is worse. Stopping.")
            break

        print("Worst violation: %s -> %s" % (worst.startpoint, worst.endpoint))
        print("  check type : %s" % worst.check_type)
        print("  path group : %s" % worst.path_group)
        print("  slack      : %s ns" % worst.slack)
        print("  stages     : %d" % len(worst.stages))
        print("")

        modules = get_modules_for_path(worst, current_baseline_dir)
        if not modules:
            print("Could not resolve this violation to any RTL module - skipping.")
            break
        print("Resolved to module(s): %s" % ", ".join(m.name for m in modules))

        hints = classify_violation(worst, parsed.critical_paths,
                                    modules[0].source if modules else "")
        hint_names = [t for (t, _) in hints]
        if hint_names:
            print("Suggested technique(s): %s" % ", ".join(hint_names))

        already_tried = tried_techniques.get(vkey, [])
        if already_tried:
            print("Previously attempted (rejected): %s" % ", ".join(already_tried))
            prompt = build_alternative_prompt(
                worst, parsed.critical_paths, modules,
                previous_patch="",
                rejection_reason=last_rejection_reason.get(
                    vkey, "A previous patch for this violation was rejected."),
                previously_tried_techniques=already_tried)
            remaining = [t for t in hint_names if t not in already_tried]
            technique_hint = remaining[0] if remaining else None
        else:
            prompt = build_prompt(worst, parsed.critical_paths, modules)
            technique_hint = hint_names[0] if hint_names else None

        print("")
        print("Requesting patch from %s..." % config.LLM_PROVIDER)
        allowed_module_names = [m.name for m in modules]
        (ok, iter_dir, module_name, fix_description, pipeline_stages_added,
         stretched_ports, retries, msg) = get_patch_with_syntax_retries(
            prompt, current_baseline_dir, iteration,
            allowed_modules=allowed_module_names)

        # technique_hint (the pre-call heuristic guess, from the fixed
        # 6-technique vocabulary) and fix_description (the LLM's own
        # free-text account of what it actually did) are deliberately
        # kept SEPARATE, not merged into one field:
        #   - technique_hint drives the "don't repeat the same technique
        #     on retry" exclusion logic (tried_techniques below), which
        #     needs a consistent, comparable vocabulary to work at all -
        #     a free-text sentence can't be matched against itself
        #     across attempts the way a fixed category name can.
        #   - fix_description is purely for human-readable reporting -
        #     what the LLM says it actually changed, in its own words,
        #     not constrained to the 6 suggested techniques since those
        #     are only optional starting points.

        if not ok:
            print("Failed to obtain a usable patch: %s" % msg)
            _hr()
            print("SUMMARY: patch failed before synthesis | REJECT")
            _hr()
            log_iteration(config.LOG_PATH, build_record(
                run_id=run_id,
                iteration=iteration,
                violation=_violation_dict(worst),
                technique_hints=hint_names,
                technique_used=technique_hint,
                llm_provider=config.LLM_PROVIDER,
                syntax_retries_used=retries,
                rejected_attempts=rejected_counts.get(vkey, 0),
                slack_before=worst.slack,
                wns_setup_before=current_metrics["wns_setup"],
                tns_setup_before=current_metrics["tns_setup"],
                area_before=current_metrics["area"],
                frequency_by_domain_before=current_metrics["frequency_by_domain"],
                power_before_w=current_metrics["power_w"],
                decision="reject",
                decision_reason=msg,
            ))
            rejected_counts[vkey] = rejected_counts.get(vkey, 0) + 1
            last_rejection_reason[vkey] = "Patch failed before synthesis: %s" % msg
            if technique_hint:
                tried_techniques.setdefault(vkey, []).append(technique_hint)
            if not _should_continue_iterating():
                break
            continue

        print("Patch applied to module '%s' -> %s" % (module_name, iter_dir))
        print("Syntax check passed (%d retry/retries used)." % retries)
        print("")
        print("--- %s's self-report ---" % config.LLM_PROVIDER)
        if fix_description:
            print("  Fix description       : %s" % fix_description)
        else:
            print("  Fix description       : (not reported - missing marker)")
        print("  Pipeline stages added : %d" % pipeline_stages_added)
        if stretched_ports:
            print("  Stretched ports       : %s" % ", ".join(stretched_ports))
        else:
            print("  Stretched ports       : none reported")
        print("")

        print("Re-synthesizing and re-running STA...")
        ok, new_area, new_reports_dir, msg, synth_log, new_netlist_path = run_synth_and_sta(
            iter_dir, "iter_%d" % iteration)

        if not ok:
            print("Patched design failed to build/analyze: %s" % msg)
            _hr()
            print("SUMMARY: module '%s' | build/analysis failed | REJECT" % module_name)
            _hr()
            if synth_log:
                print("  Synthesis log preserved at: %s" % synth_log)
            log_iteration(config.LOG_PATH, build_record(
                run_id=run_id,
                iteration=iteration,
                violation=_violation_dict(worst),
                technique_hints=hint_names,
                technique_used=technique_hint,
                fix_description=fix_description,
                llm_provider=config.LLM_PROVIDER,
                syntax_retries_used=retries,
                rejected_attempts=rejected_counts.get(vkey, 0),
                patched_module=module_name,
                slack_before=worst.slack,
                wns_setup_before=current_metrics["wns_setup"],
                tns_setup_before=current_metrics["tns_setup"],
                area_before=current_metrics["area"],
                decision="reject",
                decision_reason=msg,
            ))
            rejected_counts[vkey] = rejected_counts.get(vkey, 0) + 1
            last_rejection_reason[vkey] = "Build/analysis failed: %s" % msg
            if technique_hint:
                tried_techniques.setdefault(vkey, []).append(technique_hint)
            if not _should_continue_iterating():
                break
            continue

        new_parsed, new_metrics = _extract_metrics(new_reports_dir, new_area)
        print("")
        _print_metrics("Before (current baseline)", current_metrics)
        _print_metrics("After  (this patch)", new_metrics)
        print("")

        print("Running formal equivalence check (module '%s' against ORIGINAL RTL)..." % module_name)
        try:
            formal = check_equivalence(original_rtl_dir, iter_dir, config.TOP_MODULE,
                                        "%s/iter_%d/check.eqy" % (config.FORMAL_OUTPUT_DIR, iteration),
                                        depth=config.EQY_DEPTH,
                                        timeout=config.EQY_TIMEOUT,
                                        check_module=module_name,
                                        added_stages=pipeline_stages_added,
                                        stretched_ports=stretched_ports)
            if formal.get("timed_out"):
                # Same reasoning as the FormalCheckError branch just
                # below: a timeout means EQY ran out of time before
                # reaching ANY conclusion - not that it proved
                # inequivalence. check_equivalence() previously
                # returned {"equivalent": False, ...} for this case
                # with no way to tell it apart from a genuine completed
                # disproof, which would have fed straight into
                # decide()'s pending_user path exactly like the earlier
                # stale-directory bug did. Route it through the exact
                # same auto-reject handling by raising here, so a
                # timeout can never be silently accepted as a formally
                # verified result.
                raise FormalCheckError(
                    "EQY timed out after %ds without reaching a "
                    "conclusion (increase config.EQY_TIMEOUT and/or "
                    "sat_timeout if legitimate proofs are being cut "
                    "off too early, or investigate whether this "
                    "specific partition is simply intractable for the "
                    "configured strategies)." % config.EQY_TIMEOUT
                )
            formal_equivalent = formal["equivalent"]
            formal_log = formal["log_path"]
        except FormalCheckError as e:
            # IMPORTANT: this is a TOOLING failure (EQY/subprocess/
            # filesystem problem - e.g. a stuck leftover process from a
            # previous run holding the output directory busy) - the
            # check never actually RAN, so it has proven nothing about
            # this patch either way. This must NOT be treated the same
            # as formal_equivalent=False (a genuine, completed proof
            # that the patch is NOT equivalent): collapsing the two
            # previously fed straight into decide()'s pending_user path
            # with the same "Formal equivalence FAILED" wording, and if
            # the user then chose to accept based on the (also real)
            # slack improvement, the log would have recorded that
            # accept as formally verified when no verification of any
            # kind actually took place - a false claim in exactly the
            # artifact (formal-verification-of-every-patch) this whole
            # framework exists to produce honestly. Auto-reject
            # immediately here, the same way a synth/STA build failure
            # does above - skip decide() entirely, since there is no
            # timing OR equivalence result to weigh a decision on.
            print("  Formal check could not run: %s" % e)
            _hr()
            print("SUMMARY: module '%s' | formal check tooling failure | REJECT" % module_name)
            _hr()
            log_iteration(config.LOG_PATH, build_record(
                run_id=run_id,
                iteration=iteration,
                violation=_violation_dict(worst),
                technique_hints=hint_names,
                technique_used=technique_hint,
                fix_description=fix_description,
                llm_provider=config.LLM_PROVIDER,
                syntax_retries_used=retries,
                rejected_attempts=rejected_counts.get(vkey, 0),
                patched_module=module_name,
                slack_before=worst.slack,
                slack_after=new_metrics["wns_setup"],
                wns_setup_before=current_metrics["wns_setup"],
                tns_setup_before=current_metrics["tns_setup"],
                area_before=current_metrics["area"],
                decision="reject",
                decision_reason="Formal check tooling failure (check did not run): %s" % e,
            ))
            rejected_counts[vkey] = rejected_counts.get(vkey, 0) + 1
            last_rejection_reason[vkey] = "Formal check tooling failure: %s" % e
            if technique_hint:
                tried_techniques.setdefault(vkey, []).append(technique_hint)
            if not _should_continue_iterating():
                break
            continue

        print("  Equivalent: %s" % formal_equivalent)
        if formal_log:
            print("  Log: %s" % formal_log)
        print("")

        decision, reason = decide(formal_equivalent,
                                   current_metrics["wns_setup"],
                                   new_metrics["wns_setup"])

        _hr()
        print("DECISION: %s" % decision.upper())
        print(reason)
        _hr()

        if decision == "pending_user":
            print("")
            print("Formal verification failed, but slack has improved.")
            print("Recommended: formal verification should pass for any")
            print("LLM-generated code before it's accepted. Accepting anyway")
            print("keeps this patch as the new baseline WITHOUT formal proof")
            print("of equivalence to the original, and that will be recorded")
            print("in the log.")
            if not config.INTERACTIVE_MODE:
                # Auto-reject, not auto-accept - matches the recommendation
                # printed above. Accepting unverified code by default
                # would mean non-interactive mode silently makes the
                # RISKIER choice whenever no human is present to weigh
                # in, which is the wrong default for something the
                # framework itself is actively recommending against.
                print("(non-interactive mode - auto-rejecting per the "
                      "recommendation above)")
                decision = "user_reject"
                reason = reason + " | Auto-rejected (non-interactive mode)."
            else:
                answer = _ask("Reject this patch, or continue to the next "
                               "iteration with it accepted?", ["r", "c"])
                decision = "user_accept" if answer == "c" else "user_reject"
                reason = reason + " | User chose to %s." % (
                    "accept" if answer == "c" else "reject")
            print("Recorded as: %s" % decision)

        _hr()
        print("SUMMARY: module '%s' | slack %.2f -> %.2f ns | %s" % (
            module_name,
            current_metrics["wns_setup"] if current_metrics["wns_setup"] is not None else float("nan"),
            new_metrics["wns_setup"] if new_metrics["wns_setup"] is not None else float("nan"),
            decision.upper(),
        ))
        if fix_description:
            print("  %s's fix: %s" % (config.LLM_PROVIDER, fix_description))
        _hr()

        log_iteration(config.LOG_PATH, build_record(
            run_id=run_id,
            iteration=iteration,
            violation=_violation_dict(worst),
            technique_hints=hint_names,
            technique_used=technique_hint,
            fix_description=fix_description,
            llm_provider=config.LLM_PROVIDER,
            syntax_retries_used=retries,
            rejected_attempts=rejected_counts.get(vkey, 0),
            patched_module=module_name,
            slack_before=current_metrics["wns_setup"],
            slack_after=new_metrics["wns_setup"],
            wns_setup_before=current_metrics["wns_setup"],
            wns_setup_after=new_metrics["wns_setup"],
            tns_setup_before=current_metrics["tns_setup"],
            tns_setup_after=new_metrics["tns_setup"],
            area_before=current_metrics["area"],
            area_after=new_metrics["area"],
            frequency_by_domain_before=current_metrics["frequency_by_domain"],
            frequency_by_domain_after=new_metrics["frequency_by_domain"],
            power_before_w=current_metrics["power_w"],
            power_after_w=new_metrics["power_w"],
            eqy_equivalent=formal_equivalent,
            eqy_log_path=formal_log,
            decision=decision,
            decision_reason=reason,
        ))

        if decision in ("accept", "user_accept"):
            current_baseline_dir = iter_dir
            current_metrics = new_metrics
            current_reports_dir = new_reports_dir
            current_netlist_path = new_netlist_path
            rejected_counts.pop(vkey, None)
            tried_techniques.pop(vkey, None)
            last_rejection_reason.pop(vkey, None)
            print("")
            print("Patch ACCEPTED. New baseline: %s" % current_baseline_dir)
        else:
            rejected_counts[vkey] = rejected_counts.get(vkey, 0) + 1
            last_rejection_reason[vkey] = reason
            if technique_hint:
                tried_techniques.setdefault(vkey, []).append(technique_hint)
            print("")
            print("Patch REJECTED. Baseline unchanged: %s" % current_baseline_dir)
            print("This violation has now been rejected %d time(s) "
                  "(cap: %d)." % (rejected_counts[vkey],
                                   config.MAX_REJECTED_RETRIES_PER_VIOLATION))

        print("")
        if iteration < config.MAX_ITERATIONS:
            if not _should_continue_iterating():
                print("Stopping at your request.")
                break
        else:
            print("Reached max iterations (%d)." % config.MAX_ITERATIONS)

    # ---------------- Wrap up ----------------
    _hr("=")
    print("RUN COMPLETE")
    _hr("=")

    if current_baseline_dir != original_rtl_dir:
        out = Path(config.FINAL_OUTPUT_DIR)
        if out.exists():
            shutil.rmtree(str(out))
        shutil.copytree(current_baseline_dir, str(out))
        print("Optimized RTL written to: %s" % out)
    else:
        print("No patch was accepted - the original RTL is unchanged.")
        print("Nothing written to %s." % config.FINAL_OUTPUT_DIR)

    summary = summarize(config.LOG_PATH)

    def _fmt(v, places=2):
        if v is None:
            return "None"
        try:
            return str(round(v, places))
        except TypeError:
            return str(v)

    print("")
    print("Summary:")
    print("  Iterations run          : %s" % summary.get("total_iterations"))
    print("  Decisions               : %s" % summary.get("decision_counts"))
    print("  WNS (setup) %s -> %s ns" % (_fmt(summary.get("wns_setup_baseline"), 3),
                                          _fmt(summary.get("wns_setup_final"), 3)))
    print("  TNS (setup) %s -> %s ns" % (_fmt(summary.get("tns_setup_baseline"), 3),
                                          _fmt(summary.get("tns_setup_final"), 3)))
    print("  Area        %s -> %s" % (_fmt(summary.get("area_baseline")),
                                       _fmt(summary.get("area_final"))))
    print("  Max Frequency by domain:")
    for domain, d in sorted((summary.get("frequency_by_domain") or {}).items()):
        print("    %-10s %s -> %s MHz" % (
            domain, _fmt(d.get("baseline_mhz")), _fmt(d.get("final_mhz"))))
    print("  Power       %s -> %s W" % (summary.get("power_w_baseline"),
                                         summary.get("power_w_final")))

    # Printed here (before Physical Design starts, not at the very end)
    # so it reads as "here's what still needs manual attention before
    # we move to physical implementation" rather than being buried
    # after a potentially long PnR run.
    _report_unresolved_exclusions(current_reports_dir)

    # ---------------- Overall formal equivalence (whole-design sign-off) ---
    # Runs ONCE, after the loop finishes: compares the ORIGINAL baseline
    # RTL against the FINAL accepted RTL (every accepted patch applied
    # together) at the TOP MODULE level - a final sign-off gate, distinct
    # from every per-iteration check above (each of which only proved ONE
    # patched module equivalent in isolation). See config.py's
    # OVERALL_FORMAL_CHECK_ENABLED/OVERALL_EQY_TIMEOUT comments for why
    # this is a genuinely harder problem than those per-iteration checks.
    #
    # overall_formal_passed starts True (not False) when the check is
    # DISABLED - "disabled" must never silently behave like "failed",
    # since that would incorrectly block Physical Design below for a
    # check the user explicitly turned off.
    print("")
    _hr("=")
    print("OVERALL FORMAL VERIFICATION")
    _hr("=")
    overall_formal_passed = True
    if not config.OVERALL_FORMAL_CHECK_ENABLED:
        print("Overall formal check: DISABLED (config.OVERALL_FORMAL_CHECK_ENABLED=0) - skipping.")
        write_overall_formal_result("logs/overall_formal_result.json", {
            "status": "disabled", "log_path": None, "top_module": config.TOP_MODULE})
    else:
        print("Running overall formal equivalence check (original baseline "
              "vs. final accepted RTL, top module '%s')..." % config.TOP_MODULE)
        print("This checks the WHOLE design, not a single module - expect it")
        print("to take meaningfully longer than any per-iteration check above.")
        try:
            overall_formal = check_equivalence(
                original_rtl_dir, current_baseline_dir, config.TOP_MODULE,
                "%s/overall/check.eqy" % config.FORMAL_OUTPUT_DIR,
                depth=config.EQY_DEPTH,
                timeout=config.OVERALL_EQY_TIMEOUT,
                sat_timeout=config.OVERALL_SAT_TIMEOUT,
            )
            if overall_formal.get("timed_out"):
                overall_formal_passed = False
                print("  TIMED OUT after %ds without reaching a conclusion." %
                      config.OVERALL_EQY_TIMEOUT)
                print("  Treated as NOT passed - a timeout proves nothing "
                      "either way, so this does not count as a positive "
                      "confirmation of equivalence.")
                write_overall_formal_result("logs/overall_formal_result.json", {
                    "status": "timeout", "log_path": None, "top_module": config.TOP_MODULE})
            elif overall_formal["equivalent"]:
                overall_formal_passed = True
                print("  PASS - final design is formally equivalent to the "
                      "original baseline.")
                write_overall_formal_result("logs/overall_formal_result.json", {
                    "status": "pass", "log_path": overall_formal.get("log_path"),
                    "top_module": config.TOP_MODULE})
            else:
                overall_formal_passed = False
                print("  FAIL - final design is NOT formally equivalent to "
                      "the original baseline.")
                write_overall_formal_result("logs/overall_formal_result.json", {
                    "status": "fail", "log_path": overall_formal.get("log_path"),
                    "top_module": config.TOP_MODULE})
            print("  Log: %s" % overall_formal.get("log_path"))
        except FormalCheckError as e:
            overall_formal_passed = False
            print("  Could not run: %s" % e)
            print("  Treated as NOT passed - the check never actually ran, "
                  "so there is no positive confirmation of equivalence.")
            write_overall_formal_result("logs/overall_formal_result.json", {
                "status": "error", "log_path": None, "top_module": config.TOP_MODULE})

    # ---------------- Physical Design (PnR) - optional, one-shot ----------
    # Deliberately NOT run per-iteration above (unlike synthesis+STA) -
    # real detail routing is slow (tens of minutes even for a design
    # this size, per observed real runs), so this runs exactly ONCE,
    # here, against the FINAL accepted baseline only. Gated by
    # config.PNR_ENABLED so the framework's default behavior (synthesis
    # + STA only) is completely unaffected when this feature is off -
    # every place PnR would otherwise run prints a clear, explicit
    # "disabled" message instead of silently skipping.
    #
    # ALSO gated on overall_formal_passed: physical implementation is
    # never attempted on a design that failed (or never completed) the
    # whole-design formal check above, regardless of how promising the
    # timing/PPA numbers looked - if OVERALL_FORMAL_CHECK_ENABLED=0,
    # overall_formal_passed stays True (see above), so this has no
    # effect when the check itself is turned off.
    print("")
    _hr("=")
    print("PHYSICAL DESIGN")
    _hr("=")
    ppa_comparison_result = None  # set below only if PnR actually produced one -
                                   # used after render_markdown_report() to persist
                                   # this into the actual report FILE, not just the
                                   # console (see logger.append_ppa_section).

    # Clear any STALE pnr_result.json from a PREVIOUS run before deciding
    # anything about THIS run - write_pnr_result() below only ever runs
    # inside the PNR_ENABLED branch, so without this, disabling PnR (or
    # it failing/timing out) after a prior run where it succeeded would
    # leave that old file sitting untouched. generate_demo.py has no way
    # to tell "this is stale" from "this is current" - it would silently
    # show PNR data that has nothing to do with this run. Deleting first
    # and only re-writing on genuine success this run guarantees the
    # file's presence/absence always matches THIS run's actual outcome.
    try:
        Path(config.PNR_RESULT_PATH).unlink()
    except OSError:
        pass  # didn't exist - nothing to clear, which is fine

    if not config.PNR_ENABLED:
        print("Physical design (PnR): DISABLED (config.PNR_ENABLED=0) - skipping.")
    elif not overall_formal_passed:
        print("Physical design (PnR): SKIPPED - overall formal verification "
              "did not pass above.")
        print("Fix the final design (or investigate the failing/timed-out "
              "check) before attempting physical implementation.")
    else:
        print("Physical design (PnR): running OpenROAD sign-off on the final "
              "accepted baseline...")
        try:
            pnr_result = run_pnr(pnr_dir=config.PNR_DIR,
                                  tcl_script=config.PNR_TCL_SCRIPT,
                                  netlist_src=current_netlist_path,
                                  top_module=config.TOP_MODULE,
                                  source_pnr_dir=config.SOURCE_PNR_DIR,
                                  iteration_label="final",
                                  timeout=config.PNR_TIMEOUT)
        except PnRError as e:
            pnr_result = None
            print("  PnR could not run: %s" % e)

        if pnr_result is not None:
            if pnr_result.get("timed_out"):
                print("  PnR timed out after %ds (process group killed) - no "
                      "post-route result available." % config.PNR_TIMEOUT)
            elif not pnr_result["success"]:
                print("  PnR failed (see %s)" % pnr_result["log_path"])
            else:
                print("  PnR complete. Reports: %s" % pnr_result["reports_dir"])
                # NOTE: reuses _extract_metrics() against the PnR reports
                # dir, which assumes pnr.tcl's report_checks/report_tns/
                # report_power commands write the SAME filenames/format
                # that sta.tcl does (OpenROAD's STA engine IS OpenSTA
                # under the hood, so this is expected to work, but has
                # not been verified against a real report sample as of
                # this writing - sanity-check the parsed numbers below
                # against pnr.tcl's raw report files before trusting
                # them for anything beyond a first-pass sanity check).
                #
                # Post-route area: parsed from OpenROAD's own
                # 'report_design_area' command (assumed written to
                # reports/area.rpt by pnr.tcl, per the confirmed real
                # output format documented in
                # report_parser.parse_design_area - a genuinely
                # different report/command than synthesis-stage area,
                # which comes from Yosys 'stat -liberty', not OpenSTA).
                # Falls back to None (shown as N/A) if that file isn't
                # there or doesn't parse, rather than guessing.
                pnr_area = parse_design_area(
                    str(Path(pnr_result["reports_dir"]) / "area.rpt"))
                try:
                    pnr_metrics = _extract_pnr_metrics(
                        pnr_result["reports_dir"], area=pnr_area)
                    # Uses current_metrics DIRECTLY (the final accepted
                    # baseline's own full metrics dict, already in the
                    # exact shape _extract_metrics() produces) rather
                    # than reconstructing from `summary` - summary's
                    # frequency_by_domain only carries baseline_mhz/
                    # final_mhz/delta_mhz, NOT worst_slack_ns, and
                    # compute_ppa_comparison()'s sign-flip detection
                    # needs worst_slack_ns specifically (frequency_mhz
                    # alone can't tell met from violated - see that
                    # function's docstring).
                    print("")
                    ppa_comparison_result = _print_ppa_comparison(
                        current_metrics, pnr_metrics)
                except Exception as e:
                    print("  Could not parse PnR reports into PPA metrics: %s" % e)

    report = render_markdown_report(config.LOG_PATH, config.REPORT_PATH)
    if ppa_comparison_result is not None:
        # PnR is a one-shot, end-of-run step with no per-iteration
        # record, so it doesn't fit render_markdown_report()'s
        # iteration-log-driven structure - append it as a bolt-on
        # section onto the file that function just wrote, using the
        # SAME comparison data already printed to console above (see
        # _print_ppa_comparison's return value) so the two can never
        # show different numbers.
        append_ppa_section(config.REPORT_PATH, ppa_comparison_result)
        # Also persisted separately as JSON (not into run.jsonl - see
        # write_pnr_result()'s docstring for why) so generate_demo.py
        # can render a PPA section too, despite having no other way to
        # know a PnR stage even ran.
        write_pnr_result(config.PNR_RESULT_PATH, ppa_comparison_result)
    print("")
    print("Iteration log : %s" % config.LOG_PATH)
    print("Report        : %s" % report)

    # Dedicated Formal Equivalence Verification Report deliverable -
    # pulls together the overall (whole-design) result (written above,
    # in the OVERALL FORMAL VERIFICATION section) and every per-module
    # per-iteration result from run.jsonl into one coherent file,
    # rather than leaving formal-check results scattered across raw
    # EQY logs and a single buried column in the main report.
    try:
        formal_report_path = render_formal_verification_report(
            config.LOG_PATH, "logs/overall_formal_result.json", "logs/formal_verification_report.md")
        print("Formal verification final report in path: %s" % formal_report_path)
    except Exception as e:
        print("Could not generate formal verification report: %s" % e)

    # Generates the offline HTML dashboard automatically, now that every
    # source it reads from (run.jsonl, pnr_result.json if PnR ran,
    # unresolved_exclusions.json written earlier above, before the
    # Physical Design section) is in place. Kept as a best-effort step,
    # not a hard requirement for run() to succeed - generate_demo.py is
    # explicitly documented as a SUPPLEMENT to a live orchestrator.py
    # run, not a replacement for it, so a failure here (e.g. a
    # malformed log entry) shouldn't crash an otherwise-successful run.
    try:
        demo_path = generate_demo(config.LOG_PATH, config.DEMO_OUTPUT_PATH,
                                   pnr_result_path=config.PNR_RESULT_PATH,
                                   unresolved_exclusions_path=config.UNRESOLVED_EXCLUSIONS_PATH)
        print("Demo dashboard: %s" % demo_path)
    except Exception as e:
        print("Could not generate demo dashboard: %s" % e)

    print("")
    _hr("=")
    if ppa_comparison_result is not None:
        print("Framework run completed with Physical Design - check %s for "
              "the results comparison." % config.DEMO_OUTPUT_PATH)
    else:
        print("Framework run completed - check %s for the results comparison."
              % config.DEMO_OUTPUT_PATH)
    _hr("=")

    return 0


def _warn_unmapped_clocks(parsed):
    """Warns if the STA reports mention any clock that is missing from
    config.CLOCK_FAMILY_MAP.

    This matters because report_parser's cross-domain (CDC) detection
    FAILS OPEN: _is_cross_domain() returns False - i.e. "not CDC, safe
    to hand to the LLM" - whenever it can't find a clock in the map.
    That's deliberate (failing closed would block legitimate work
    whenever the map is merely incomplete), but it means an unmapped
    clock silently loses CDC protection. This turns that silent gap
    into a visible one.

    CLOCK_FAMILY_MAP is hand-maintained in config.py, so it can drift
    out of sync whenever a clock is added or renamed in the design.
    """
    family_map = getattr(config, "CLOCK_FAMILY_MAP", None)
    if not family_map:
        print("")
        print("  WARNING: config.CLOCK_FAMILY_MAP is empty or missing - "
              "cross-domain (CDC) detection is effectively DISABLED.")
        print("  Every path will be treated as same-domain and is eligible "
              "to be sent to the LLM.")
        return

    seen_clocks = set()
    for p in parsed.critical_paths:
        if p.startpoint_clock:
            seen_clocks.add(p.startpoint_clock)
        if p.endpoint_clock:
            seen_clocks.add(p.endpoint_clock)

    unmapped = sorted(c for c in seen_clocks if c not in family_map)
    if unmapped:
        print("")
        print("  WARNING: %d clock(s) found in the STA reports are NOT in "
              "config.CLOCK_FAMILY_MAP:" % len(unmapped))
        for c in unmapped:
            print("    - %s" % c)
        print("  CDC detection fails open on unknown clocks, so paths "
              "involving these are NOT protected from being")
        print("  handed to the LLM. Add them to CLOCK_FAMILY_MAP under "
              "their correct async family.")


def _report_unresolved_exclusions(reports_dir):
    """Prints every violation the framework deliberately EXCLUDED from
    the auto-fix loop and therefore never attempted to resolve.

    These are excluded for good reasons (recovery/removal need reset-
    synchronizer-class fixes, not the 6 timing techniques; CDC paths
    must not be patched by an LLM without risking metastability
    protection) - but silently dropping them from the final output
    would leave the user believing the design is clean when it isn't.
    Anything listed here still needs manual attention.
    """
    if not reports_dir:
        return

    parsed = parse_all_reports(reports_dir)
    rr = recovery_removal_violations(parsed)
    cdc = cdc_violations(parsed, clock_family_map=config.CLOCK_FAMILY_MAP)
    pg_only = path_group_excluded_violations(
        parsed, clock_family_map=config.CLOCK_FAMILY_MAP)

    # Persisted here (not just printed below) so generate_demo.py can
    # show these too - without this, "None. No recovery/removal or CDC
    # violations remain." (or the actual list) only ever existed as
    # console output, gone the moment the terminal scrolls or the
    # session ends, exactly like the PnR PPA comparison was before
    # write_pnr_result() existed. Written unconditionally, every run
    # (unlike the PnR result, which is gated by config.PNR_ENABLED) -
    # this check always runs against the final baseline, so there's
    # always something meaningful to persist, even when it's an empty
    # "nothing excluded" result.
    write_unresolved_exclusions(config.UNRESOLVED_EXCLUSIONS_PATH, rr, cdc, pg_only)

    print("")
    _hr("=")
    print("UNRESOLVED - EXCLUDED FROM THE AUTO-FIX LOOP")
    _hr("=")

    if not rr and not cdc and not pg_only:
        print("None. No recovery/removal or CDC violations remain.")
        return

    if rr:
        print("")
        print("Recovery/removal (async reset) violations: %d" % len(rr))
        print("  These check reset DEASSERTION timing, not data-path setup/hold.")
        print("  None of the 6 RTL optimization techniques apply - the correct")
        print("  fix is structural (reset synchronizer / adjusted reset release).")
        print("  NOT attempted by this framework; needs manual attention.")
        for p in rr:
            print("    %-10s slack %8.3f ns   %s -> %s" % (
                p.check_type, p.slack, p.startpoint, p.endpoint))

    if cdc:
        print("")
        print("CDC (cross-clock-domain) violations: %d" % len(cdc))
        print("  CONFIRMED cross-domain: startpoint and endpoint clocks are in")
        print("  different async families (verified from the actual clock names).")
        print("  Deliberately NOT handed to the LLM - patching logic around a")
        print("  synchronizer risks breaking metastability protection.")
        print("  NOT attempted by this framework; needs manual attention.")
        for p in cdc:
            print("    slack %8.3f ns   %s (%s) -> %s (%s)" % (
                p.slack, p.startpoint, p.startpoint_clock,
                p.endpoint, p.endpoint_clock))

    if pg_only:
        print("")
        print("Excluded by path_group label only: %d" % len(pg_only))
        print("  These are NOT recovery/removal checks, and their start/end")
        print("  clocks are in the SAME family - so nothing except the tool's")
        print("  'Path Group' label marks them as special. Held back as a")
        print("  conservative measure, but SOME MAY BE FALSE EXCLUSIONS:")
        print("  ordinary same-domain violations that are safe to fix.")
        print("  Worth reviewing manually - if a path here is genuinely")
        print("  ordinary, fix it by hand or relax the path_groups exclusion.")
        for p in pg_only:
            print("    slack %8.3f ns   path_group=%-14s %s (%s) -> %s (%s)" % (
                p.slack, p.path_group, p.startpoint, p.startpoint_clock,
                p.endpoint, p.endpoint_clock))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sys.exit(run())
