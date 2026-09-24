"""
logger.py
Records one structured entry per iteration (violation, patch attempt,
before/after PPA numbers, formal check result, accept/reject decision)
to a JSON-lines log file. This is the single source of truth that:
  - the PPA comparison deliverable is built from
  - the formal equivalence report is built from
  - the interactive demo reads to render charts/tables

Does NOT make any accept/reject decisions itself - that's
orchestrator.py's job. This file only records what happened and
provides read-side helpers to summarize/export it afterward.

Python 3.6.8 compatible (no f-strings, no dataclasses).
"""

import json
import uuid
from datetime import datetime
from pathlib import Path


def new_run_id():
    """Generates a fresh run identifier - call once per orchestrator.py
    invocation and pass into every build_record() call for that run.
    Timestamp prefix makes it sortable/human-readable; the short random
    suffix avoids collisions if two runs start in the same second."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def build_record(iteration, run_id=None, violation=None, technique_hints=None,
                  technique_used=None, fix_description=None, llm_provider=None,
                  syntax_retries_used=0, rejected_attempts=0,
                  patched_module=None,
                  slack_before=None, slack_after=None,
                  wns_setup_before=None, wns_setup_after=None,
                  tns_setup_before=None, tns_setup_after=None,
                  area_before=None, area_after=None,
                  frequency_by_domain_before=None, frequency_by_domain_after=None,
                  power_before_w=None, power_after_w=None,
                  eqy_equivalent=None, eqy_log_path=None,
                  decision=None, decision_reason=None):
    """Builds one iteration record dict with a consistent schema.

    run_id: pass the SAME id (from new_run_id()) for every record within
    one orchestrator.py execution. This is what lets summarize()/
    export_chart_data()/render_markdown_report() correctly isolate the
    current run's data even though log_iteration() always APPENDS -
    without this, an old run's entries left in the log file (e.g. from
    an earlier test on a different design) get silently mixed into the
    current run's summary. If None, defaults to "unknown" - fine for
    quick manual testing, not for a real run.

    All fields except 'iteration' are optional - pass whatever you have
    at the point you're logging (e.g. a baseline record won't have
    'violation' or 'decision').

    violation: dict like {"startpoint":, "endpoint":, "check_type":,
               "path_group":} - build this from a TimingPath object's
               fields at the call site, e.g.:
                   {"startpoint": worst.startpoint, "endpoint": worst.endpoint,
                    "check_type": worst.check_type, "path_group": worst.path_group}

    decision: one of 'accept', 'reject', 'pending_user', 'user_accept',
              'user_reject', or None for records that aren't a
              patch-decision point (e.g. the baseline record).
    """
    return {
        "run_id": run_id or "unknown",
        "iteration": iteration,
        "timestamp": datetime.now().isoformat(),
        "violation": violation,
        "technique_hints": technique_hints or [],
        "technique_used": technique_used,
        "fix_description": fix_description,
        "llm_provider": llm_provider,
        "syntax_retries_used": syntax_retries_used,
        "rejected_attempts": rejected_attempts,
        "patched_module": patched_module,
        "slack_before": slack_before,
        "slack_after": slack_after,
        "wns_setup_before": wns_setup_before,
        "wns_setup_after": wns_setup_after,
        "tns_setup_before": tns_setup_before,
        "tns_setup_after": tns_setup_after,
        "area_before": area_before,
        "area_after": area_after,
        "frequency_by_domain_before": frequency_by_domain_before,
        "frequency_by_domain_after": frequency_by_domain_after,
        "power_before_w": power_before_w,
        "power_after_w": power_after_w,
        "eqy_equivalent": eqy_equivalent,
        "eqy_log_path": eqy_log_path,
        "decision": decision,
        "decision_reason": decision_reason,
    }


def log_iteration(log_path, record):
    """Appends one record as a JSON line to log_path. Creates the file
    and parent directory if needed. Never overwrites - always appends."""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_log(log_path):
    """Reads all records back from log_path as a list of dicts, in the
    order they were written. Returns [] if the file doesn't exist."""
    path = Path(log_path)
    if not path.exists():
        return []
    records = []
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def latest_run_id(log_path):
    """Returns the run_id of the most recently written record, or None
    if the log is empty."""
    records = read_log(log_path)
    return records[-1]["run_id"] if records else None


def _filter_to_run(records, run_id):
    """Filters records to a specific run_id. If run_id is None, filters
    to the LATEST run found in records - this is the default behavior
    that protects against stale data from earlier runs (a different
    design, an earlier test) left in the same log file."""
    if not records:
        return records
    if run_id is None:
        run_id = records[-1]["run_id"]
    return [r for r in records if r.get("run_id") == run_id]


def pending_user_decisions(log_path):
    """Returns records still awaiting a user decision (decision ==
    'pending_user') - useful for orchestrator.py to resume a run and
    check if anything was left unresolved."""
    return [r for r in read_log(log_path) if r.get("decision") == "pending_user"]


# ---------------------------------------------------------------------------
# Summarizing
# ---------------------------------------------------------------------------

def summarize(log_path, run_id=None):
    """Returns a dict summarizing the run: counts by decision, and
    baseline-vs-final-accepted deltas for the PPA metrics.

    By default (run_id=None) only considers the LATEST run in the log
    file, so old entries from a previous run (a different design, an
    earlier test) never contaminate the current summary even though
    log_iteration() always appends rather than overwrites. Pass an
    explicit run_id to inspect a specific past run instead.
    """
    all_records = read_log(log_path)
    records = _filter_to_run(all_records, run_id)
    if not records:
        return {"total_iterations": 0}

    baseline = next((r for r in records if r["iteration"] == "baseline"), records[0])

    accepted = [r for r in records if r.get("decision") in ("accept", "user_accept")]
    final = accepted[-1] if accepted else None

    counts = {"accept": 0, "reject": 0, "pending_user": 0,
              "user_accept": 0, "user_reject": 0}
    for r in records:
        d = r.get("decision")
        if d in counts:
            counts[d] += 1

    summary = {
        "total_iterations": len([r for r in records if r["iteration"] != "baseline"]),
        "decision_counts": counts,
        "baseline_iteration": baseline["iteration"],
        "final_accepted_iteration": final["iteration"] if final else None,
    }

    # explicit field pairs - field names aren't perfectly uniform
    # (e.g. area_before / area_after), so map them explicitly rather
    # than guessing a pattern. Frequency is handled separately below
    # since it's per-domain (5 values), not a single scalar.
    metric_fields = [
        ("wns_setup", "wns_setup_before", "wns_setup_after"),
        ("tns_setup", "tns_setup_before", "tns_setup_after"),
        ("area", "area_before", "area_after"),
        ("power_w", "power_before_w", "power_after_w"),
    ]
    for name, before_field, after_field in metric_fields:
        b_val = baseline.get(after_field)  # baseline's "after" IS the starting point
        f_val = final.get(after_field) if final else None
        summary[name + "_baseline"] = b_val
        summary[name + "_final"] = f_val
        summary[name + "_delta"] = (f_val - b_val) if (b_val is not None and f_val is not None) else None

    # Per-domain frequency: baseline's *_after IS the starting point (same
    # convention as above), final accepted iteration's *_after is the result.
    # A 5-clock SoC has 5 real frequencies, not one - kept as a dict per
    # domain rather than flattened into the scalar metric loop above.
    baseline_freq = baseline.get("frequency_by_domain_after") or {}
    final_freq = (final.get("frequency_by_domain_after") if final else None) or {}
    freq_by_domain = {}
    for domain in set(list(baseline_freq.keys()) + list(final_freq.keys())):
        b = (baseline_freq.get(domain) or {}).get("frequency_mhz")
        f = (final_freq.get(domain) or {}).get("frequency_mhz")
        freq_by_domain[domain] = {
            "baseline_mhz": b,
            "final_mhz": f,
            "delta_mhz": (f - b) if (b is not None and f is not None) else None,
        }
    summary["frequency_by_domain"] = freq_by_domain

    return summary


# ---------------------------------------------------------------------------
# Export for demo/charts
# ---------------------------------------------------------------------------

def export_chart_data(log_path, run_id=None):
    """Returns parallel lists suitable for feeding straight into a
    plotting library (matplotlib/plotly) for the interactive demo -
    one entry per non-baseline iteration of the LATEST run by default
    (see summarize() docstring for why), in order."""
    all_records = read_log(log_path)
    records = [r for r in _filter_to_run(all_records, run_id) if r["iteration"] != "baseline"]

    frequency_by_domain_series = {}
    all_domains = set()
    for r in records:
        d = r.get("frequency_by_domain_after") or {}
        all_domains.update(d.keys())
    for domain in all_domains:
        frequency_by_domain_series[domain] = [
            ((r.get("frequency_by_domain_after") or {}).get(domain) or {}).get("frequency_mhz")
            for r in records
        ]

    return {
        "iterations": [r["iteration"] for r in records],
        "wns_setup_after": [r.get("wns_setup_after") for r in records],
        "tns_setup_after": [r.get("tns_setup_after") for r in records],
        "area_after": [r.get("area_after") for r in records],
        "power_after_w": [r.get("power_after_w") for r in records],
        "frequency_by_domain": frequency_by_domain_series,
        "decisions": [r.get("decision") for r in records],
        "techniques_used": [r.get("technique_used") for r in records],
    }


# ---------------------------------------------------------------------------
# Markdown report (for the written report deliverable)
# ---------------------------------------------------------------------------

def compute_ppa_comparison(synth_metrics, pnr_metrics):
    """Compares synthesis-stage vs. post-route PPA metrics (same
    {wns_setup, tns_setup, area, frequency_by_domain, power_w} shape
    orchestrator.py's _extract_metrics() already produces for both
    stages). Returns a plain dict, not text - shared by BOTH the
    console printout (orchestrator.py) and the persisted markdown
    report (append_ppa_section() below), so the comparison numbers and
    the sign-flip detection logic exist in exactly one place and can
    never drift apart between the two renderings.

    The single most important thing this computes: a SIGN FLIP is any
    clock domain whose timing status (met vs. violated, read from that
    domain's worst_slack_ns - NOT from frequency_mhz, which stays
    positive even for a violated domain, see below) differs between the
    two stages. Synthesis-stage STA has no real wire parasitics, so a
    path that looked fine at that stage can genuinely fail once
    actually placed and routed - this is the one number in this
    comparison that should never be buried in a quiet numeric diff.

    Returns: {
        "wns_setup": (synth_val, pnr_val),
        "tns_setup": (synth_val, pnr_val),
        "area": (synth_val, pnr_val),
        "power_w": (synth_val, pnr_val),
        "domains": [(domain, synth_mhz, pnr_mhz), ...],  # sorted
        "sign_flips": [(domain, was_met_at_synth, met_post_route), ...],
    }
    """
    synth_domains = synth_metrics.get("frequency_by_domain") or {}
    pnr_domains = pnr_metrics.get("frequency_by_domain") or {}
    all_domains = sorted(set(synth_domains) | set(pnr_domains))

    domain_rows = []
    sign_flips = []
    for domain in all_domains:
        s_domain = synth_domains.get(domain) or {}
        p_domain = pnr_domains.get(domain) or {}
        s_freq = s_domain.get("frequency_mhz")
        p_freq = p_domain.get("frequency_mhz")
        domain_rows.append((domain, s_freq, p_freq))
        # IMPORTANT: met/violated status must be read from worst_slack_ns,
        # NOT from frequency_mhz - compute_achievable_frequency() in
        # report_parser.py returns a valid POSITIVE frequency even for a
        # VIOLATED domain (a negative slack just means a lower achievable
        # frequency than the target clock, not None/0) - frequency_mhz
        # being present/positive does NOT mean the domain met timing.
        s_slack = s_domain.get("worst_slack_ns")
        p_slack = p_domain.get("worst_slack_ns")
        s_ok = s_slack is not None and s_slack >= 0
        p_ok = p_slack is not None and p_slack >= 0
        if s_ok != p_ok:
            sign_flips.append((domain, s_ok, p_ok))

    return {
        "wns_setup": (synth_metrics.get("wns_setup"), pnr_metrics.get("wns_setup")),
        "tns_setup": (synth_metrics.get("tns_setup"), pnr_metrics.get("tns_setup")),
        "area": (synth_metrics.get("area"), pnr_metrics.get("area")),
        "power_w": (synth_metrics.get("power_w"), pnr_metrics.get("power_w")),
        "domains": domain_rows,
        "sign_flips": sign_flips,
    }


def append_ppa_section(report_path, comparison):
    """Appends a '## Physical Design (PnR) - PPA Comparison' section to
    an ALREADY-WRITTEN markdown report file (i.e. call this AFTER
    render_markdown_report(), not instead of it - PnR is a one-shot,
    end-of-run step with no per-iteration record, so it doesn't fit
    render_markdown_report()'s iteration-log-driven structure and is
    deliberately kept as a separate bolt-on section rather than forcing
    it into that schema.

    Without this, orchestrator.py's PPA comparison would only ever
    reach the console - never the persisted report file - and would be
    lost the moment the terminal scrolls or the session ends.
    """
    def _fmt(v, places=3):
        if v is None:
            return "N/A"
        try:
            return str(round(v, places))
        except TypeError:
            return str(v)

    lines = ["", "## Physical Design (PnR) - PPA Comparison", "",
              "Synthesis-stage STA vs. post-route (real wire parasitics) - "
              "see note below on any sign flips before treating the "
              "synthesis-stage numbers as final.", ""]

    s_wns, p_wns = comparison["wns_setup"]
    s_tns, p_tns = comparison["tns_setup"]
    s_area, p_area = comparison["area"]
    s_pow, p_pow = comparison["power_w"]

    lines.append("- WNS (setup): %s ns -> %s ns" % (_fmt(s_wns), _fmt(p_wns)))
    lines.append("- TNS (setup): %s ns -> %s ns" % (_fmt(s_tns), _fmt(p_tns)))
    area_note = ("  (could not parse post-route area - check "
                 "reports/area.rpt exists under the PnR reports dir)"
                 if p_area is None else "")
    lines.append("- Area: %s -> %s%s" % (_fmt(s_area, 2), _fmt(p_area, 2), area_note))
    lines.append("- Power: %s W -> %s W" % (_fmt(s_pow), _fmt(p_pow)))
    lines.append("- Max Frequency by domain:")
    for domain, s_freq, p_freq in comparison["domains"]:
        lines.append("  - %s: %s MHz -> %s MHz" % (domain, _fmt(s_freq, 2), _fmt(p_freq, 2)))

    if comparison["sign_flips"]:
        lines.append("")
        lines.append("**WARNING: timing sign flip(s) between synthesis and post-route:**")
        for domain, s_ok, p_ok in comparison["sign_flips"]:
            if s_ok and not p_ok:
                lines.append(
                    "- `%s`: MET at synthesis-stage STA, but VIOLATED "
                    "post-route - real routing parasitics broke a path "
                    "that looked fine before physical implementation." % domain)
            else:
                lines.append(
                    "- `%s`: VIOLATED at synthesis-stage STA, but MET "
                    "post-route - less common; possibly OpenROAD's own "
                    "CTS/routing optimization recovered slack the "
                    "synthesis-stage estimate didn't account for." % domain)

    out = Path(report_path)
    with out.open("a") as f:
        f.write("\n".join(lines) + "\n")


def write_pnr_result(path, comparison):
    """Persists a PnR PPA comparison (see compute_ppa_comparison()) as a
    single JSON object - deliberately NOT written into the per-iteration
    run.jsonl log alongside build_record() entries. PnR is a one-shot,
    end-of-run event, not a violation-fix iteration - build_record()'s
    schema (violation, technique_used, slack_before/after,
    eqy_equivalent, decision, ...) doesn't fit it, and summarize() /
    render_markdown_report() / generate_demo.py's existing record-
    iteration logic would need to explicitly special-case a new record
    shape to safely skip over it. A separate file avoids all of that
    risk entirely: nothing that already reads run.jsonl is affected,
    and this file simply may or may not exist.

    Exists so generate_demo.py (which has no other way to know a PnR
    stage ran, since nothing about it is logged anywhere else) can
    optionally render a PPA comparison section - see read_pnr_result().
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(comparison, indent=2))
    return str(out)


def read_pnr_result(path):
    """Reads back a PnR PPA comparison written by write_pnr_result().
    Returns None if the file doesn't exist (PnR was disabled, didn't
    run, or failed before producing a comparison) or can't be parsed -
    callers should treat None as "no PnR section to show", not an
    error.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _timing_path_to_dict(p):
    """Converts a report_parser.TimingPath object to a plain,
    JSON-serializable dict, keeping only the fields actually shown by
    orchestrator._report_unresolved_exclusions()'s console output -
    NOT the full 'stages' list (too much data for this summary view,
    and not something that console output shows for this section
    either).
    """
    return {
        "startpoint": p.startpoint,
        "endpoint": p.endpoint,
        "check_type": p.check_type,
        "slack": p.slack,
        "path_group": p.path_group,
        "startpoint_clock": p.startpoint_clock,
        "endpoint_clock": p.endpoint_clock,
    }


def write_unresolved_exclusions(path, recovery_removal, cdc, path_group_only):
    """Persists the violations orchestrator._report_unresolved_exclusions()
    deliberately excludes from the auto-fix loop (recovery/removal
    async-reset checks, confirmed CDC crossings, and path-group-only
    exclusions) as a single JSON object - same reasoning as
    write_pnr_result(): this is a one-shot, end-of-run summary over the
    FINAL accepted baseline's reports, not a per-iteration event, so it
    doesn't fit build_record()'s schema and is kept as a separate file
    rather than forced into run.jsonl.

    Without this, these lists exist only as console output during the
    live run - printing "None. No recovery/removal or CDC violations
    remain." (or the actual list) and then being gone forever the
    moment the terminal scrolls or the session ends, exactly like the
    PnR PPA comparison was before write_pnr_result() existed.

    Each argument is a list of report_parser.TimingPath objects (or
    empty/None) - converted to plain dicts via _timing_path_to_dict()
    before serializing, since TimingPath itself isn't JSON-serializable.
    """
    data = {
        "recovery_removal": [_timing_path_to_dict(p) for p in (recovery_removal or [])],
        "cdc": [_timing_path_to_dict(p) for p in (cdc or [])],
        "path_group_only": [_timing_path_to_dict(p) for p in (path_group_only or [])],
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2))
    return str(out)


def read_unresolved_exclusions(path):
    """Reads back the unresolved-exclusions summary written by
    write_unresolved_exclusions(). Returns None if the file doesn't
    exist or can't be parsed - callers should treat None as "no
    exclusions section to show" (e.g. orchestrator.py hasn't been run
    with the updated code yet), NOT the same as "zero exclusions
    found" (which is a real, valid result: {"recovery_removal": [],
    "cdc": [], "path_group_only": []}, distinct from None).
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_overall_formal_result(path, result):
    """Persists the whole-design (soc_top-level) formal equivalence
    check's outcome - see orchestrator.py's "OVERALL FORMAL
    VERIFICATION" section - as a single JSON object, same reasoning as
    write_pnr_result()/write_unresolved_exclusions(): this is a
    one-shot, end-of-run event, not a per-iteration record, so it
    doesn't fit build_record()'s schema and is kept separate.

    Exists so render_formal_verification_report() (below) can lead
    with this result - without it, the overall check's outcome only
    ever existed as console output, gone the moment the terminal
    scrolls.

    result: {"status": "pass"|"fail"|"timeout"|"error"|"disabled",
             "log_path": str or None, "top_module": str}
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    return str(out)


def read_overall_formal_result(path):
    """Reads back the overall formal result written by
    write_overall_formal_result(). Returns None if the file doesn't
    exist or can't be parsed.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def render_formal_verification_report(log_path, overall_formal_path, output_path, run_id=None):
    """Builds the dedicated 'Formal Equivalence Verification Report'
    deliverable - previously, formal-check results only existed
    scattered across raw per-iteration EQY logs and a single "EQY"
    column buried inside the generic Iteration Log table in
    render_markdown_report()'s output, with no single coherent
    artifact a reader could be pointed to as THE formal verification
    report. This pulls both the overall (whole-design) result and
    every per-module per-iteration result together into one file.

    Returns the output path (a .md file) - orchestrator.py prints this
    path at the end of run(), same as it does for the iteration log,
    the main report, and the demo dashboard.
    """
    all_records = read_log(log_path)
    records = _filter_to_run(all_records, run_id)
    used_run_id = records[0]["run_id"] if records else "unknown"

    overall = read_overall_formal_result(overall_formal_path)

    lines = ["# Formal Equivalence Verification Report", "",
             "Run: %s" % used_run_id, ""]

    lines.append("## Overall Design Verification")
    lines.append("")
    if overall is None:
        lines.append("Not available - the running orchestrator.py predates this "
                      "feature, or the overall check's result wasn't written.")
    else:
        status = overall.get("status")
        status_label = {
            "pass": "**PASS** - the final design is formally equivalent to the original baseline.",
            "fail": "**FAIL** - the final design is NOT formally equivalent to the original baseline.",
            "timeout": "**TIMED OUT** - no conclusion reached; NOT treated as a pass.",
            "error": "**COULD NOT RUN** - the check itself failed to execute; NOT treated as a pass.",
            "disabled": "DISABLED (config.OVERALL_FORMAL_CHECK_ENABLED=0) - not run for this session.",
        }.get(status, status or "unknown")
        lines.append("- Top module checked: `%s`" % overall.get("top_module", "-"))
        lines.append("- Result: %s" % status_label)
        if overall.get("log_path"):
            lines.append("- Log: `%s`" % overall["log_path"])
    lines.append("")

    lines.append("## Per-Module Verification (Per Iteration)")
    lines.append("")
    iterations = [r for r in records if r["iteration"] != "baseline" and r.get("patched_module")]
    if not iterations:
        lines.append("No per-module formal checks recorded for this run.")
    else:
        passed = sum(1 for r in iterations if r.get("eqy_equivalent") is True)
        lines.append("**%d/%d per-module checks passed formally.**" % (passed, len(iterations)))
        lines.append("")
        lines.append("| Iter | Module | Result | Log |")
        lines.append("|---|---|---|---|")
        for r in iterations:
            eq = r.get("eqy_equivalent")
            result_label = "PASS" if eq is True else ("FAIL" if eq is False else "N/A")
            log_ref = ("`%s`" % r["eqy_log_path"]) if r.get("eqy_log_path") else "-"
            lines.append("| %s | %s | %s | %s |" % (
                r["iteration"], r.get("patched_module", "-"), result_label, log_ref))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    return str(out)


def render_markdown_report(log_path, output_path, run_id=None):
    """Writes a formatted markdown table (one row per iteration of the
    LATEST run by default - see summarize() docstring) plus a summary
    section, for inclusion in the 10-12 page report."""
    all_records = read_log(log_path)
    records = _filter_to_run(all_records, run_id)
    summary = summarize(log_path, run_id=run_id)

    lines = ["# Nebula - Iteration Report", ""]

    lines.append("## Summary")
    lines.append("")
    lines.append("- Total iterations: %s" % summary.get("total_iterations"))
    lines.append("- Decisions: %s" % summary.get("decision_counts"))
    lines.append("- WNS (setup): %s ns -> %s ns (delta %s)" % (
        summary.get("wns_setup_baseline"), summary.get("wns_setup_final"),
        summary.get("wns_setup_delta")))
    lines.append("- TNS (setup): %s ns -> %s ns (delta %s)" % (
        summary.get("tns_setup_baseline"), summary.get("tns_setup_final"),
        summary.get("tns_setup_delta")))
    lines.append("- Area: %s -> %s (delta %s)" % (
        summary.get("area_baseline"), summary.get("area_final"),
        summary.get("area_delta")))
    lines.append("- Max Frequency by domain:")
    for domain, d in sorted((summary.get("frequency_by_domain") or {}).items()):
        lines.append("  - %s: %s MHz -> %s MHz (delta %s)" % (
            domain, d.get("baseline_mhz"), d.get("final_mhz"), d.get("delta_mhz")))
    lines.append("- Power: %s W -> %s W (delta %s)" % (
        summary.get("power_w_baseline"), summary.get("power_w_final"),
        summary.get("power_w_delta")))
    lines.append("")

    lines.append("## Iteration Log")
    lines.append("")
    lines.append("| Iter | Violation | Technique Hint | Fix Description (LLM's own words) | Slack Before | Slack After | EQY | Decision |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in records:
        if r["iteration"] == "baseline":
            continue
        v = r.get("violation") or {}
        loc = "%s -> %s" % (v.get("startpoint", "-"), v.get("endpoint", "-"))
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["iteration"], loc, r.get("technique_used") or "-",
            r.get("fix_description") or "-",
            r.get("slack_before"), r.get("slack_after"),
            r.get("eqy_equivalent"), r.get("decision"),
        ))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    return str(out)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    log_path = sys.argv[1] if len(sys.argv) > 1 else "logs/run.jsonl"

    records = read_log(log_path)
    print("Records:", len(records))
    print()
    print("Summary:", summarize(log_path))
