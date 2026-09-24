"""
generate_demo.py
Builds a single, self-contained, OFFLINE HTML dashboard from logs/run.jsonl -
the "interactive demo showcasing RTL optimization workflow" deliverable, as a
SUPPLEMENT to recording a live orchestrator.py run (not a replacement for it).

Design choices, deliberately:
    - No CDN / external JS or CSS libraries. Charts are hand-drawn inline SVG,
      computed directly from the log data. This must work reliably with no
      internet access at recording time - a CDN dependency is a real risk
      there is no reason to take.
    - No JavaScript required for interactivity. Expand/collapse per-iteration
      detail uses native HTML5 <details>/<summary> - built into every modern
      browser, nothing that can silently break.
    - Reads via logger.py's existing run-isolation logic (run_id), so it
      always reflects the LATEST real run, never stale data mixed in from
      an earlier test.

Usage:
    python3 generate_demo.py [log_path] [output_path]
    (defaults: logs/run.jsonl -> logs/demo.html)
"""

import html
from pathlib import Path

from logger import read_log, summarize, _filter_to_run, read_pnr_result, read_unresolved_exclusions


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def _fmt(v, places=2, unit=""):
    if v is None:
        return "N/A"
    try:
        return ("%." + str(places) + "f%s") % (v, unit)
    except (TypeError, ValueError):
        return str(v)


def _esc(s):
    return html.escape(str(s)) if s is not None else ""


def _decision_class(decision):
    return {
        "accept": "badge-accept",
        "user_accept": "badge-accept",
        "reject": "badge-reject",
        "user_reject": "badge-reject",
        "pending_user": "badge-pending",
    }.get(decision, "badge-unknown")


def _decision_label(decision):
    return {
        "accept": "ACCEPTED",
        "user_accept": "ACCEPTED (user)",
        "reject": "REJECTED",
        "user_reject": "REJECTED (user)",
        "pending_user": "PENDING",
    }.get(decision, decision or "UNKNOWN")


# ---------------------------------------------------------------------------
# Hand-drawn inline SVG line chart - no external library
# ---------------------------------------------------------------------------

def render_line_chart(labels, series, title, y_label, width=760, height=280,
                       colors=("#2563eb", "#dc2626")):
    """series: list of (name, values) tuples, values may contain None.
    Draws a simple multi-line chart with axes, gridlines, and a legend.
    Returns an SVG string. All coordinates computed by hand - no charting
    library involved.
    """
    margin_l, margin_r, margin_t, margin_b = 60, 20, 30, 40
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    all_vals = [v for _, vals in series for v in vals if v is not None]
    if not all_vals:
        return "<p><em>No data available for '%s'</em></p>" % _esc(title)

    y_min, y_max = min(all_vals), max(all_vals)
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    y_pad = (y_max - y_min) * 0.1
    y_min -= y_pad
    y_max += y_pad

    n = len(labels)

    def x_pos(i):
        if n <= 1:
            return margin_l + plot_w / 2.0
        return margin_l + (plot_w * i) / float(n - 1)

    def y_pos(v):
        return margin_t + plot_h - ((v - y_min) / (y_max - y_min)) * plot_h

    svg = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" class="chart">' % (width, height)]
    svg.append('<text x="%d" y="18" class="chart-title">%s</text>' % (width // 2, _esc(title)))

    for t in range(5):
        frac = t / 4.0
        gy = margin_t + plot_h - frac * plot_h
        val = y_min + frac * (y_max - y_min)
        svg.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="gridline"/>' %
                    (margin_l, gy, margin_l + plot_w, gy))
        svg.append('<text x="%d" y="%.1f" class="axis-label" text-anchor="end">%.1f</text>' %
                    (margin_l - 8, gy + 4, val))

    for i, lab in enumerate(labels):
        svg.append('<text x="%.1f" y="%d" class="axis-label" text-anchor="middle">%s</text>' %
                    (x_pos(i), height - margin_b + 16, _esc(lab)))

    svg.append('<text x="14" y="%d" class="axis-title" transform="rotate(-90 14 %d)">%s</text>' %
                (margin_t + plot_h // 2, margin_t + plot_h // 2, _esc(y_label)))

    for si, (name, values) in enumerate(series):
        color = colors[si % len(colors)]
        points = [(x_pos(i), y_pos(v)) for i, v in enumerate(values) if v is not None]
        if len(points) >= 2:
            path = " ".join("%.1f,%.1f" % p for p in points)
            svg.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.5"/>' % (path, color))
        for x, y in points:
            svg.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>' % (x, y, color))
        svg.append('<circle cx="%d" cy="%d" r="5" fill="%s"/>' % (margin_l + si * 150, height - 6, color))
        svg.append('<text x="%d" y="%d" class="legend-label">%s</text>' %
                    (margin_l + si * 150 + 12, height - 2, _esc(name)))

    svg.append("</svg>")
    return "\n".join(svg)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def render_summary_table(summary, pnr_result=None):
    """Renders the top-level metrics AND per-domain frequencies as ONE
    table - Metric | Baseline | Synthesis | Delta | % Improvement |
    PNR (if pnr_result given) - rather than a card grid.

    IMPORTANT: Delta and % Improvement are computed STRICTLY from
    Baseline -> Synthesis, never involving the PnR value even when
    present. This is deliberate: Baseline->Synthesis isolates what the
    LLM optimization loop itself achieved, while Baseline->PnR would
    conflate that with a completely different effect (RTL-estimate vs.
    real physical implementation) into one misleading number - e.g. a
    frequency that looks like it "regressed 90%" going baseline->PnR
    is really just synthesis-stage timing being an optimistic estimate
    with no real wire parasitics, not the optimization loop failing.
    The PNR column is shown purely as reference data alongside, with
    no delta/% of its own, for exactly the reason requested: comparing
    PnR against the ORIGINAL baseline "makes no sense" as a measure of
    the optimization's effect.

    pnr_result: a logger.read_pnr_result() dict (or None if PnR didn't
    run) - its per-metric values are already paired as (synth, pnr)
    tuples (see compute_ppa_comparison()), so the PnR value for each
    metric is simply that tuple's second element. When None, the PNR
    column is omitted entirely rather than shown empty.
    """
    show_pnr_col = pnr_result is not None

    def row(label, baseline, synth_final, pnr_value=None,
            unit="", places=2, lower_is_better=True, show_pct=True):
        """Delta/% computed strictly baseline -> synth_final.
        show_pct=False for WNS/TNS: slack routinely crosses zero, and a
        percentage across a sign change is meaningless (e.g. -1.59 ->
        0.02 is a clean fix, not a "-101.9%" regression) -
        Area/Power/Frequency are always positive, so their percentage
        is well-defined.
        """
        cells = "<td>%s</td><td>%s</td>" % (_fmt(baseline, places, unit),
                                             _fmt(synth_final, places, unit))

        delta_cell, pct_cell = "<td>&#8212;</td>", "<td>&#8212;</td>"
        if baseline is not None and synth_final is not None:
            d = synth_final - baseline
            improved = (d < 0) if lower_is_better else (d > 0)
            cls = "delta-good" if improved else ("delta-bad" if d != 0 else "")
            arrow = "&#9650;" if d > 0 else ("&#9660;" if d < 0 else "&#8212;")
            delta_cell = '<td class="%s">%s %s</td>' % (cls, arrow, _fmt(d, places, unit))
            if show_pct and baseline != 0:
                pct = abs(d) / abs(baseline) * 100.0
                word = "better" if cls == "delta-good" else ("worse" if cls == "delta-bad" else "change")
                pct_cell = '<td class="%s">%.1f%% %s</td>' % (cls, pct, word)

        pnr_cell = ""
        if show_pnr_col:
            pnr_cell = "<td>%s</td>" % _fmt(pnr_value, places, unit)

        return "<tr><td>%s</td>%s%s%s%s</tr>" % (label, cells, delta_cell, pct_cell, pnr_cell)

    def pnr_val(pnr_key):
        pnr_pair = pnr_result.get(pnr_key) if pnr_result else None
        return pnr_pair[1] if pnr_pair else None

    rows = [
        row("WNS (setup)", summary.get("wns_setup_baseline"), summary.get("wns_setup_final"),
            pnr_val("wns_setup"), " ns", lower_is_better=False, show_pct=False),
        row("TNS (setup)", summary.get("tns_setup_baseline"), summary.get("tns_setup_final"),
            pnr_val("tns_setup"), " ns", lower_is_better=False, show_pct=False),
        row("Area", summary.get("area_baseline"), summary.get("area_final"),
            pnr_val("area"), " \u00b5m\u00b2", 1),
        row("Power", summary.get("power_w_baseline"), summary.get("power_w_final"),
            pnr_val("power_w"), " W", 5),
    ]

    freq_by_domain = summary.get("frequency_by_domain") or {}
    pnr_domains = {d: p for d, s, p in (pnr_result.get("domains") or [])} if pnr_result else {}
    colspan = 6 if show_pnr_col else 5
    if freq_by_domain:
        rows.append('<tr class="table-section-row"><td colspan="%d">Frequency by Domain</td></tr>' % colspan)
        for domain, d in sorted(freq_by_domain.items()):
            rows.append(row(domain, d.get("baseline_mhz"), d.get("final_mhz"),
                             pnr_domains.get(domain), " MHz", 2, lower_is_better=False))

    pnr_th = "<th>PNR Results</th>" if show_pnr_col else ""
    header_html = (
        "<tr>"
        "<th>Metric</th>"
        "<th>Baseline Synthesis</th>"
        "<th>Optimised Synthesis</th>"
        "<th>&Delta; (Optimized)</th>"
        "<th>%% Improvement (Optimized)</th>"
        "%s"
        "</tr>"
    ) % pnr_th

    table_html = (
        '<table class="summary-table"><thead>%s</thead>'
        '<tbody>%s</tbody></table>' % (header_html, "".join(rows))
    )

    sign_flip_html = ""
    if pnr_result and pnr_result.get("sign_flips"):
        flip_rows = []
        for domain, s_ok, p_ok in pnr_result["sign_flips"]:
            if s_ok and not p_ok:
                flip_rows.append(
                    "<li><strong>%s</strong>: MET at synthesis-stage STA, "
                    "but VIOLATED post-route - real routing parasitics "
                    "broke a path that looked fine before physical "
                    "implementation.</li>" % _esc(domain))
            else:
                flip_rows.append(
                    "<li><strong>%s</strong>: VIOLATED at synthesis-stage "
                    "STA, but MET post-route - less common; possibly "
                    "OpenROAD's own CTS/routing optimization recovered "
                    "slack the synthesis-stage estimate didn't account "
                    "for.</li>" % _esc(domain))
        sign_flip_html = (
            '<div class="warning-banner">'
            '<strong>&#9888; Timing sign flip(s) between synthesis and post-route:</strong>'
            '<ul>%s</ul></div>' % "".join(flip_rows))

    return table_html + sign_flip_html


def render_decision_breakdown(summary):
    counts = summary.get("decision_counts", {})
    total = sum(counts.values()) or 1
    order = [("accept", "#16a34a"), ("user_accept", "#22c55e"),
             ("reject", "#dc2626"), ("user_reject", "#f87171"),
             ("pending_user", "#eab308")]
    bars = []
    for key, color in order:
        n = counts.get(key, 0)
        if n == 0:
            continue
        pct = 100.0 * n / total
        bars.append(
            '<div class="bar-segment" style="width:%.1f%%;background:%s" '
            'title="%s: %d">%s: %d</div>' % (pct, color, key, n, key, n)
        )
    return '<div class="decision-bar">%s</div>' % "".join(bars) if bars else "<p>No iterations recorded.</p>"


def render_unresolved_exclusions_section(exclusions):
    """Renders the recovery/removal, CDC, and path-group-only violations
    the auto-fix loop deliberately never attempted, from a
    logger.read_unresolved_exclusions() dict.

    Returns an HTML string, or None if exclusions is None (the running
    orchestrator.py predates this feature, or reports_dir wasn't
    available when it tried to write the file) - callers should skip
    the section entirely in that case. A genuinely EMPTY result (all
    three lists empty - i.e. nothing was excluded) is different from
    None and IS rendered, as a clear "nothing excluded" confirmation,
    matching the console's own "None. No recovery/removal or CDC
    violations remain." message.
    """
    if exclusions is None:
        return None

    rr = exclusions.get("recovery_removal") or []
    cdc = exclusions.get("cdc") or []
    pg_only = exclusions.get("path_group_only") or []

    if not rr and not cdc and not pg_only:
        return ('<div class="exclusions-clean">'
                'None. No recovery/removal or CDC violations remain.</div>')

    def path_row(p):
        return "<li>%s &nbsp;<span class=\"iter-slack\">slack %s ns</span>&nbsp; %s &rarr; %s</li>" % (
            _esc(p.get("check_type", "-")), _fmt(p.get("slack")),
            _esc(p.get("startpoint", "-")), _esc(p.get("endpoint", "-")))

    def cdc_row(p):
        return ("<li><span class=\"iter-slack\">slack %s ns</span>&nbsp; "
                "%s (%s) &rarr; %s (%s)</li>") % (
            _fmt(p.get("slack")), _esc(p.get("startpoint", "-")),
            _esc(p.get("startpoint_clock", "-")), _esc(p.get("endpoint", "-")),
            _esc(p.get("endpoint_clock", "-")))

    blocks = []
    if rr:
        blocks.append(
            '<div class="exclusion-group">'
            '<h3>Recovery/removal (async reset) violations: %d</h3>'
            '<p>These check reset DEASSERTION timing, not data-path setup/hold. '
            'None of the 6 RTL optimization techniques apply - the correct fix '
            'is structural (reset synchronizer / adjusted reset release). '
            '<strong>Not attempted by this framework; needs manual attention.</strong></p>'
            '<ul>%s</ul></div>' % (len(rr), "".join(path_row(p) for p in rr)))

    if cdc:
        blocks.append(
            '<div class="exclusion-group">'
            '<h3>CDC (cross-clock-domain) violations: %d</h3>'
            '<p>Confirmed cross-domain: startpoint and endpoint clocks are in '
            'different async families (verified from the actual clock names). '
            'Deliberately not handed to the LLM - patching logic around a '
            'synchronizer risks breaking metastability protection. '
            '<strong>Not attempted by this framework; needs manual attention.</strong></p>'
            '<ul>%s</ul></div>' % (len(cdc), "".join(cdc_row(p) for p in cdc)))

    if pg_only:
        blocks.append(
            '<div class="exclusion-group">'
            '<h3>Excluded by path_group label only: %d</h3>'
            '<p>Not recovery/removal checks, and start/end clocks are in the '
            'SAME family - only the tool\'s "Path Group" label marks these as '
            'special. Held back as a conservative measure, but <strong>some '
            'may be false exclusions</strong> - worth reviewing manually.</p>'
            '<ul>%s</ul></div>' % (len(pg_only), "".join(path_row(p) for p in pg_only)))

    return "".join(blocks)


def render_iteration_row(r):
    v = r.get("violation") or {}
    loc = "%s &rarr; %s" % (_esc(v.get("startpoint", "-")), _esc(v.get("endpoint", "-")))
    hints = ", ".join(r.get("technique_hints") or []) or "none"
    fix_desc = r.get("fix_description")
    decision = r.get("decision")

    return """
    <details class="iter-row">
      <summary>
        <span class="iter-num">#%s</span>
        <span class="iter-module">%s</span>
        <span class="iter-slack">%s &rarr; %s ns</span>
        <span class="badge %s">%s</span>
      </summary>
      <div class="iter-detail">
        <p><strong>Violation:</strong> %s</p>
        <p><strong>Check type:</strong> %s &nbsp; <strong>Path group:</strong> %s</p>
        <p><strong>Technique hints given:</strong> %s</p>
        <p><strong>%s's own description of the fix:</strong> %s</p>
        <p><strong>EQY equivalent:</strong> %s</p>
        <p><strong>Decision reason:</strong> %s</p>
        <p><strong>Syntax retries used:</strong> %s &nbsp; <strong>Prior rejections of this violation:</strong> %s</p>
      </div>
    </details>""" % (
        _esc(r.get("iteration")), _esc(r.get("patched_module") or "-"),
        _fmt(r.get("slack_before")), _fmt(r.get("slack_after")),
        _decision_class(decision), _decision_label(decision),
        loc, _esc(v.get("check_type", "-")), _esc(v.get("path_group", "-")),
        _esc(hints),
        _esc(r.get("llm_provider") or "LLM"),
        _esc(fix_desc) if fix_desc else "<em>not reported</em>",
        _esc(r.get("eqy_equivalent")),
        _esc(r.get("decision_reason") or "-"),
        _esc(r.get("syntax_retries_used", 0)), _esc(r.get("rejected_attempts", 0)),
    )


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:24px; }
h1 { color:#f8fafc; margin-bottom:4px; }
.subtitle { color:#94a3b8; margin-bottom:28px; }
.summary-table { width:100%; table-layout:fixed; border-collapse:collapse; margin-bottom:32px; background:#1e293b; border-radius:10px; overflow:hidden; }
.summary-table th:nth-child(5), .summary-table td:nth-child(5) { width:20%; }
.summary-table th { white-space:normal; }
.summary-table th { background:#0f172a; color:#94a3b8; font-size:12px; text-transform:uppercase; letter-spacing:0.05em; text-align:left; padding:10px 16px; border-bottom:1px solid #334155; }
.summary-table td { padding:10px 16px; font-size:14px; color:#f8fafc; border-bottom:1px solid #263449; }
.summary-table td:nth-child(3), .summary-table td:nth-child(4), .summary-table td:nth-child(5) { padding-left:10px; padding-right:10px; }
.summary-table td.delta-good { color:#4ade80; }
.summary-table td.delta-bad { color:#f87171; }
.summary-table tr:last-child td { border-bottom:none; }
.summary-table td:first-child { color:#cbd5e1; font-weight:600; }
.table-section-row td { background:#0f172a; color:#94a3b8; font-size:12px; text-transform:uppercase; letter-spacing:0.05em; font-weight:700; padding-top:14px; }
.chart { background:#1e293b; border-radius:10px; padding:8px; margin-bottom:24px; width:100%; height:auto; }
.chart-title { fill:#f8fafc; font-size:14px; text-anchor:middle; }
.axis-label { fill:#94a3b8; font-size:10px; }
.axis-title { fill:#94a3b8; font-size:11px; }
.legend-label { fill:#e2e8f0; font-size:11px; }
.gridline { stroke:#334155; stroke-width:1; }
.decision-bar { display:flex; height:36px; border-radius:6px; overflow:hidden; margin-bottom:32px; }
.bar-segment { color:#0f172a; font-size:12px; font-weight:600; display:flex; align-items:center; justify-content:center; white-space:nowrap; overflow:hidden; }
.iter-row { background:#1e293b; border-radius:8px; margin-bottom:8px; padding:10px 16px; }
.iter-row summary { cursor:pointer; display:flex; gap:16px; align-items:center; list-style:none; }
.iter-row summary::-webkit-details-marker { display:none; }
.iter-num { color:#94a3b8; font-weight:600; width:40px; }
.iter-module { color:#f8fafc; font-weight:600; flex:1; }
.iter-slack { color:#cbd5e1; font-family:monospace; }
.badge { padding:3px 10px; border-radius:12px; font-size:11px; font-weight:700; }
.badge-accept { background:#16a34a; color:#f0fdf4; }
.badge-reject { background:#dc2626; color:#fef2f2; }
.badge-pending { background:#eab308; color:#422006; }
.badge-unknown { background:#475569; color:#e2e8f0; }
.iter-detail { margin-top:12px; padding-top:12px; border-top:1px solid #334155; color:#cbd5e1; font-size:13px; line-height:1.6; }
.iter-detail strong { color:#e2e8f0; }
.footnote { color:#64748b; font-size:12px; margin-top:32px; }
.warning-banner { background:#450a0a; border:1px solid #dc2626; border-radius:8px; padding:14px 18px; margin-top:16px; color:#fecaca; }
.warning-banner strong { color:#fef2f2; }
.warning-banner ul { margin:8px 0 0 0; padding-left:20px; }
.warning-banner li { margin-bottom:4px; }
.exclusions-clean { background:#052e16; border:1px solid #16a34a; border-radius:8px; padding:14px 18px; color:#bbf7d0; }
.exclusion-group { background:#1e293b; border-radius:8px; padding:14px 18px; margin-bottom:12px; }
.exclusion-group h3 { color:#fbbf24; font-size:14px; margin:0 0 8px 0; }
.exclusion-group p { color:#cbd5e1; font-size:13px; line-height:1.5; margin:0 0 10px 0; }
.exclusion-group ul { margin:0; padding-left:18px; color:#e2e8f0; font-size:13px; }
.exclusion-group li { margin-bottom:6px; font-family:monospace; }
section { margin-bottom:36px; }
h2 { color:#f8fafc; font-size:16px; border-bottom:1px solid #334155; padding-bottom:8px; }
"""


def generate_demo(log_path="logs/run.jsonl", output_path="logs/demo.html",
                   run_id=None, pnr_result_path="logs/pnr_result.json",
                   unresolved_exclusions_path="logs/unresolved_exclusions.json"):
    all_records = read_log(log_path)
    if not all_records:
        raise ValueError("No records found in %s - run orchestrator.py first." % log_path)

    records = _filter_to_run(all_records, run_id)
    used_run_id = records[0]["run_id"] if records else "unknown"
    summary = summarize(log_path, run_id=used_run_id)

    iterations = [r for r in records if r["iteration"] != "baseline"]

    labels = [str(r["iteration"]) for r in iterations]
    wns_after = [r.get("wns_setup_after") for r in iterations]
    area_after = [r.get("area_after") for r in iterations]

    baseline = next((r for r in records if r["iteration"] == "baseline"), None)
    if baseline:
        labels = ["baseline"] + labels
        wns_after = [baseline.get("wns_setup_after")] + wns_after
        area_after = [baseline.get("area_after")] + area_after

    wns_chart = render_line_chart(labels, [("WNS (setup)", wns_after)],
                                   "Worst Negative Slack over iterations", "ns")
    area_chart = render_line_chart(labels, [("Area", area_after)],
                                    "Area over iterations", "\u00b5m\u00b2", colors=("#f59e0b",))

    rows_html = "\n".join(render_iteration_row(r) for r in iterations) or "<p>No iterations recorded.</p>"

    # Optional - only present if PNR_ENABLED and a one-shot PnR sign-off
    # actually ran and produced a comparison (see logger.write_pnr_result,
    # called from orchestrator.py). Folded directly into
    # render_summary_cards() below as a third stage in each card's
    # progression, rather than rendered as its own separate section -
    # see render_summary_cards()'s docstring for why.
    pnr_result = read_pnr_result(pnr_result_path)

    # Placed at the very end of the page, per request - these are
    # violations the auto-fix loop deliberately never touched, so they
    # read as a closing "here's what still needs manual attention"
    # note rather than competing with the actual optimization results
    # above. Omitted entirely (not shown empty) if the file doesn't
    # exist at all (see render_unresolved_exclusions_section's
    # None-vs-empty distinction) - a genuinely empty result (nothing
    # excluded) still renders, as a clear confirmation, not silence.
    exclusions = read_unresolved_exclusions(unresolved_exclusions_path)
    exclusions_html = render_unresolved_exclusions_section(exclusions)
    exclusions_section_block = ("""
  <section>
    <h2>Unresolved - Excluded from the Auto-Fix Loop</h2>
    %s
  </section>
""" % exclusions_html) if exclusions_html else ""

    html_doc = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>NEBULA - RTL Timing Optimization Report</title>
<style>%s</style>
</head>
<body>
  <h1>NEBULA - GenAI RTL Timing Optimization</h1>
  <div class="subtitle">Run: %s &nbsp;|&nbsp; %d iteration(s) &nbsp;|&nbsp; %s</div>

  <section>
    <h2>Baseline &rarr; Final Result</h2>
    %s
  </section>

  <section>
    <h2>Timing Convergence</h2>
    %s
  </section>

  <section>
    <h2>Area Over Iterations</h2>
    %s
  </section>

  <section>
    <h2>Decision Breakdown</h2>
    %s
  </section>

  <section>
    <h2>Iteration Detail (click a row to expand)</h2>
    %s
  </section>
%s
</body>
</html>""" % (
        _CSS, _esc(used_run_id), len(iterations),
        _esc(records[-1]["timestamp"]) if records else "",
        render_summary_table(summary, pnr_result),
        wns_chart,
        area_chart,
        render_decision_breakdown(summary),
        rows_html,
        exclusions_section_block,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc)
    return str(out)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    log_path = sys.argv[1] if len(sys.argv) > 1 else "logs/run.jsonl"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "logs/demo.html"
    pnr_result_path = sys.argv[3] if len(sys.argv) > 3 else "logs/pnr_result.json"
    unresolved_exclusions_path = sys.argv[4] if len(sys.argv) > 4 else "logs/unresolved_exclusions.json"

    path = generate_demo(log_path, output_path, pnr_result_path=pnr_result_path,
                          unresolved_exclusions_path=unresolved_exclusions_path)
    print("Demo written to: %s" % path)
    print("Open it directly in any browser - no server, no internet required.")
