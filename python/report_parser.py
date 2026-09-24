"""
report_parser.py
Parses OpenSTA report_*.txt outputs into structured Python dicts/dataclasses.
"""

import re
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures (plain classes - Python 3.6 compatible, no dataclasses)
# ---------------------------------------------------------------------------

class PathStage(object):
    def __init__(self, instance, pin, cell_type, fanout, cap, slew, delay, time):
        self.instance = instance
        self.pin = pin
        self.cell_type = cell_type
        self.fanout = fanout
        self.cap = cap
        self.slew = slew
        self.delay = delay
        self.time = time

    def __repr__(self):
        return "PathStage(%s/%s, %s, delay=%.2f)" % (
            self.instance, self.pin, self.cell_type, self.delay)


class TimingPath(object):
    def __init__(self, startpoint, endpoint, path_group, path_type, stages,
                 data_arrival_time, data_required_time, slack, violated,
                 check_type="setup", startpoint_clock=None, endpoint_clock=None):
        self.startpoint = startpoint
        self.endpoint = endpoint
        self.path_group = path_group
        self.path_type = path_type
        self.stages = stages
        self.data_arrival_time = data_arrival_time
        self.data_required_time = data_required_time
        self.slack = slack
        self.violated = violated
        # check_type: 'setup', 'hold', 'recovery', or 'removal'.
        # Recovery/removal are async-reset-related checks, not normal
        # data-path setup/hold - they need different handling and should
        # be excluded from the standard 6-technique auto-fix loop.
        self.check_type = check_type
        # The actual clock driving each end, parsed from the
        # "(... clocked by <name>)" text under Startpoint:/Endpoint:.
        # This is independent of path_group - path_group reflects the
        # SDC's clock grouping, which can have gaps; comparing the real
        # clock names directly is a second, SDC-independent line of
        # defense for detecting genuine cross-domain (CDC) paths.
        self.startpoint_clock = startpoint_clock
        self.endpoint_clock = endpoint_clock

    def __repr__(self):
        return "TimingPath(%s -> %s, slack=%.2f, violated=%s, check_type=%s)" % (
            self.startpoint, self.endpoint, self.slack, self.violated, self.check_type)


class ParsedReports(object):
    def __init__(self):
        self.wns_setup = None
        self.wns_hold = None
        self.tns_setup = None
        self.tns_hold = None
        self.critical_paths = []
        self.violations = []
        self.unconstrained_paths = []
        self.clock_properties = ""
        self.power = {}


# ---------------------------------------------------------------------------
# Individual file parsers
# ---------------------------------------------------------------------------

def parse_worst_slack(filepath: str) -> Optional[float]:
    """Parses 'worst_slack_setup.txt' / 'worst_slack_hold.txt'
    Format: 'worst slack max -0.42' or 'worst slack min 1.05'
    """
    text = Path(filepath).read_text()
    m = re.search(r"worst slack\s+(max|min)\s+(-?\d+\.?\d*)", text)
    return float(m.group(2)) if m else None


def parse_design_area(filepath: str) -> Optional[float]:
    """Parses OpenROAD's `report_design_area` output (post-route area,
    for the PnR PPA comparison - see pnr_runner.py/orchestrator.py).

    Confirmed real-world format (verified against actual OpenROAD output):
        --------------------------------------------------------------------------
        Design area 264357 um^2 25% utilization.

    A single line: "Design area <NUMBER> um^2 <NUMBER>% utilization." Note
    the unit is "um^2" (micrometers squared) - NOT "u^2"; an earlier
    version of this regex assumed "u^2" and silently matched nothing
    against real OpenROAD output, always returning None (shown as N/A)
    even though area.rpt genuinely existed and had real content.
    Units are um^2 - same physical unit as Yosys 'stat -liberty'
    reports for synthesis-stage cell area, so this IS directly
    comparable in the PPA comparison without a unit-conversion step,
    unlike some other tool pairings. Returns None if the file is
    missing or the expected line isn't found (e.g. pnr.tcl wasn't run,
    or report_design_area failed to produce output for some reason) -
    callers should treat None as "not available" and show N/A rather
    than a computed value of 0.
    """
    try:
        text = Path(filepath).read_text()
    except (FileNotFoundError, OSError):
        return None

    # findall + last match, not re.search's first match - matches
    # `grep ... | tail -1` semantics in case this file ever contains
    # more than one "Design area" line (pnr_runner.py's own area.rpt
    # generation already trims to one line, but this stays robust to a
    # fuller log being pointed at this function directly).
    matches = re.findall(r"Design area\s+([\d.]+)\s*um\^2", text)
    return float(matches[-1]) if matches else None


def parse_tns(filepath: str) -> dict:
    """Parses 'tns.txt'. Expected lines like:
    'tns max -1.23' and/or 'tns min 0.00'
    OpenSTA omits a line entirely when that check has zero violations,
    so absence is treated as 0.0 (clean), not unknown.
    Returns {'setup': float, 'hold': float}
    """
    text = Path(filepath).read_text()
    result = {"setup": 0.0, "hold": 0.0}
    for m in re.finditer(r"tns\s+(max|min)\s+(-?\d+\.?\d*)", text):
        key = "setup" if m.group(1) == "max" else "hold"
        result[key] = float(m.group(2))
    return result


def parse_critical_paths(filepath: str) -> List[TimingPath]:
    """Parses OpenSTA 'report_checks' style path reports (critical_paths.txt).
    Handles multiple concatenated path blocks in one file.
    """
    text = Path(filepath).read_text()
    blocks = re.split(r"\n(?=Startpoint:)", text)
    paths = []

    for block in blocks:
        if "Startpoint:" not in block:
            continue

        start_m = re.search(r"Startpoint:\s*(\S+)", block)
        end_m = re.search(r"Endpoint:\s*(\S+)", block)
        group_m = re.search(r"Path Group:\s*(\S+)", block)
        type_m = re.search(r"Path Type:\s*(\S+)", block)
        arrival_m = re.search(r"(-?\d+\.?\d*)\s+data arrival time", block)
        required_m = re.search(r"(-?\d+\.?\d*)\s+data required time", block)
        slack_m = re.search(r"(-?\d+\.?\d*)\s+slack\s*\((VIOLATED|MET)\)", block)

        # The clock name each end is actually driven by, from lines like:
        #   "(rising edge-triggered flip-flop clocked by clk_fast)"
        #   "(recovery check against rising-edge clock clk_fp_add)"
        #   "(input port clocked by clk_spi)"
        # Startpoint's clock is whichever "clocked by X" / "clock X)"
        # phrase appears first in the block; endpoint's is the second
        # (the endpoint description always follows the startpoint one).
        clock_name_matches = re.findall(
            r"(?:clocked by|rising-edge clock|falling-edge clock)\s+(\w+)", block)
        startpoint_clock = clock_name_matches[0] if len(clock_name_matches) > 0 else None
        endpoint_clock = clock_name_matches[1] if len(clock_name_matches) > 1 else None

        if not (start_m and end_m and slack_m):
            continue

        # Detect check type from the endpoint description line, e.g.:
        #   "(recovery check against rising-edge clock clk_fast)"  -> recovery
        #   "(removal check against rising-edge clock clk_fast)"   -> removal
        #   "(rising edge-triggered flip-flop clocked by clk_fast)" -> normal
        # Normal setup/hold checks fall back to path_type (max=setup, min=hold).
        path_type_val = type_m.group(1) if type_m else ""
        if re.search(r"recovery check", block, re.IGNORECASE):
            check_type = "recovery"
        elif re.search(r"removal check", block, re.IGNORECASE):
            check_type = "removal"
        else:
            check_type = "hold" if path_type_val == "min" else "setup"

        # Parse individual stage rows, e.g.:
        # 6   0.00  0.05  0.22  0.22  v u_counter_fast/_106_/Q (DFCNQD1HVT)
        stage_pat = re.compile(
            r"^\s*(\d+)?\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+[v^]\s+"
            r"(\S+)/(\S+)\s+\((\S+)\)",
            re.MULTILINE,
        )
        stages = []
        for sm in stage_pat.finditer(block):
            fanout, cap, slew, delay, time, inst, pin, cell = sm.groups()
            stages.append(PathStage(
                instance=inst,
                pin=pin,
                cell_type=cell,
                fanout=float(fanout) if fanout else 0.0,
                cap=float(cap),
                slew=float(slew),
                delay=float(delay),
                time=float(time),
            ))

        paths.append(TimingPath(
            startpoint=start_m.group(1),
            endpoint=end_m.group(1),
            path_group=group_m.group(1) if group_m else "",
            path_type=path_type_val,
            stages=stages,
            data_arrival_time=float(arrival_m.group(1)) if arrival_m else 0.0,
            data_required_time=float(required_m.group(1)) if required_m else 0.0,
            slack=float(slack_m.group(1)),
            violated=(slack_m.group(2) == "VIOLATED"),
            check_type=check_type,
            startpoint_clock=startpoint_clock,
            endpoint_clock=endpoint_clock,
        ))

    return paths


def parse_domain_worst_slack(filepath: str) -> Optional[float]:
    """Parses a per-domain timing file (timing_core.txt, timing_md.txt,
    etc. - same block format as critical_paths.txt, just filtered to one
    clock domain and its generated children, with no group_count/
    endpoint_path_count restriction) and returns the worst (most
    negative, or least positive if the domain is fully MET) slack found.

    Unlike critical_paths.txt, these files are NOT sampled/capped, so
    this reliably finds the true worst path for the domain rather than
    risking a miss if the domain didn't make a top-N cut.

    Returns None if the file doesn't exist or has no parseable paths -
    e.g. a domain with genuinely zero timing paths (unlikely but
    possible for an unused clock).
    """
    path = Path(filepath)
    if not path.exists():
        return None
    paths = parse_critical_paths(filepath)
    if not paths:
        return None
    return min(p.slack for p in paths)


def parse_violations(filepath: str) -> List[str]:
    """Parses 'violations.txt' (report_check_types -violators output).
    Returns raw violator lines (empty list if clean)."""
    text = Path(filepath).read_text().strip()
    if not text or "No violations" in text:
        return []
    return [line for line in text.splitlines() if line.strip()]


def parse_unconstrained(filepath: str) -> List[str]:
    text = Path(filepath).read_text().strip()
    if not text:
        return []
    return [line for line in text.splitlines() if line.strip()]


def parse_clock_properties(filepath: str) -> str:
    return Path(filepath).read_text().strip()


# ---------------------------------------------------------------------------
# Top-level driver
# ---------------------------------------------------------------------------

def parse_power_corner(filepath: str, corner_index: int = 0) -> dict:
    """Parses OpenROAD's power report format when it contains MULTIPLE
    concatenated corner blocks (e.g. pnr.tcl's
    'report_power -scene wc > reports/power.rpt' followed by
    'report_power -scene bc >> reports/power.rpt' in the same file) -
    a real, confirmed difference from sta.tcl's single-corner
    power_report.txt, which parse_power() above handles.

    IMPORTANT BUG THIS FIXES: the confirmed real power.rpt format has
    NO textual marker distinguishing which block belongs to which
    corner (no "Corner: wc" line the way the timing reports have) -
    calling plain parse_power() on this file uses a regex .finditer()
    that matches BOTH corners' "Total" rows and overwrites the dict
    key with whichever appears LAST in the file, silently returning
    the WRONG corner's numbers with no indication anything went wrong
    (confirmed: returns the bc/best-case total, not the wc/worst-case
    sign-off number a PPA comparison should conservatively report).

    Blocks are identified purely by ORDER in the file (corner_index=0
    is the first block, 1 is the second, etc.) since that's the only
    distinguishing signal available - this assumes pnr.tcl's actual
    -scene call order (wc first, bc second) stays consistent, which is
    the same assumption report_design_area's ordering already relies
    on for area.rpt via `tail -1`.

    Returns the same shape as parse_power() (dict keyed by group name),
    or {} if corner_index is out of range for however many blocks are
    actually present.
    """
    text = Path(filepath).read_text()
    # Each corner's block starts with its own "Group ... Total" header
    # line - split on that repeated header to isolate blocks.
    blocks = re.split(r"(?=^Group\s+Internal)", text, flags=re.MULTILINE)
    blocks = [b for b in blocks if b.strip()]

    if corner_index >= len(blocks):
        return {}

    row_pat = re.compile(
        r"^(Sequential|Combinational|Clock|Macro|Pad|Total)\s+"
        r"([\d.]+e[+-]\d+)\s+([\d.]+e[+-]\d+)\s+([\d.]+e[+-]\d+)\s+"
        r"([\d.]+e[+-]\d+)\s+([\d.]+)%",
        re.MULTILINE,
    )
    result = {}
    for m in row_pat.finditer(blocks[corner_index]):
        group, internal, switching, leakage, total, pct = m.groups()
        result[group.lower()] = {
            "internal": float(internal),
            "switching": float(switching),
            "leakage": float(leakage),
            "total": float(total),
            "percent": float(pct),
        }
    return result


def parse_openroad_wns_tns(filepath: str) -> dict:
    """Parses OpenROAD's own `report_wns`/`report_tns` commands' output
    format - CONFIRMED to be a completely different, much simpler text
    format than OpenSTA's report_worst_slack/report_tns used in
    sta.tcl (which parse_worst_slack()/parse_tns() above handle):

        wns max 0.00
        tns max 0.00

    This is a genuinely different command producing genuinely
    different output, not just a formatting variation of the same
    thing - report_wns/report_tns are OpenROAD-specific convenience
    commands, distinct from the underlying OpenSTA commands, despite
    OpenROAD using OpenSTA internally for the actual timing engine.

    Returns {"wns": float or None, "wns_check": "max"/"min" or None,
    "tns": float or None, "tns_check": "max"/"min" or None}.
    """
    try:
        text = Path(filepath).read_text()
    except (FileNotFoundError, OSError):
        return {"wns": None, "wns_check": None, "tns": None, "tns_check": None}

    wns_m = re.search(r"wns\s+(max|min)\s+(-?[\d.]+)", text)
    tns_m = re.search(r"tns\s+(max|min)\s+(-?[\d.]+)", text)
    return {
        "wns": float(wns_m.group(2)) if wns_m else None,
        "wns_check": wns_m.group(1) if wns_m else None,
        "tns": float(tns_m.group(2)) if tns_m else None,
        "tns_check": tns_m.group(1) if tns_m else None,
    }


def parse_power(filepath: str) -> dict:
    """Parses 'power_report.txt' (OpenSTA report_power output).
    Format:
        Group          Internal   Switching    Leakage      Total
                          Power       Power       Power  Power(Watts)
        --------------------------------------------------------
        Sequential     3.08e-04    0.00e+00   6.29e-07   3.09e-04  100.0%
        Combinational  0.00e+00    0.00e+00   1.24e-07   1.24e-07    0.0%
        Clock          ...
        Macro          ...
        Pad            ...
        --------------------------------------------------------
        Total          3.08e-04    0.00e+00   7.53e-07   3.09e-04  100.0%

    Returns dict keyed by group name (lowercase), each value a dict with
    internal/switching/leakage/total (Watts, float) and percent (float).
    'total' key holds the design-wide total row.
    """
    text = Path(filepath).read_text()
    result = {}

    row_pat = re.compile(
        r"^(Sequential|Combinational|Clock|Macro|Pad|Total)\s+"
        r"([\d.]+e[+-]\d+)\s+([\d.]+e[+-]\d+)\s+([\d.]+e[+-]\d+)\s+"
        r"([\d.]+e[+-]\d+)\s+([\d.]+)%",
        re.MULTILINE,
    )
    for m in row_pat.finditer(text):
        group, internal, switching, leakage, total, pct = m.groups()
        result[group.lower()] = {
            "internal": float(internal),
            "switching": float(switching),
            "leakage": float(leakage),
            "total": float(total),
            "percent": float(pct),
        }

    return result


def parse_all_reports(reports_dir: str) -> ParsedReports:
    d = Path(reports_dir)
    result = ParsedReports()

    if (d / "worst_slack_setup.txt").exists():
        result.wns_setup = parse_worst_slack(d / "worst_slack_setup.txt")
    if (d / "worst_slack_hold.txt").exists():
        result.wns_hold = parse_worst_slack(d / "worst_slack_hold.txt")

    if (d / "tns.txt").exists():
        tns = parse_tns(d / "tns.txt")
        result.tns_setup = tns["setup"]
        result.tns_hold = tns["hold"]

    if (d / "critical_paths.txt").exists():
        result.critical_paths = parse_critical_paths(d / "critical_paths.txt")

    if (d / "violations.txt").exists():
        result.violations = parse_violations(d / "violations.txt")

    if (d / "unconstrained_paths.txt").exists():
        result.unconstrained_paths = parse_unconstrained(d / "unconstrained_paths.txt")

    if (d / "clock_properties.txt").exists():
        result.clock_properties = parse_clock_properties(d / "clock_properties.txt")

    if (d / "power_report.txt").exists():
        result.power = parse_power(d / "power_report.txt")

    return result


def _is_cross_domain(path, clock_family_map):
    """True if startpoint_clock and endpoint_clock belong to DIFFERENT
    families per clock_family_map - independent of what path_group says.
    clock_family_map: {clock_name: family_name}, e.g.
        {"clk": "clk", "clk_gpio": "clk",
         "clk_spi": "clk_spi", "clk_spi_div": "clk_spi", ...}
    (see config.py's CLOCK_FAMILY_MAP). Returns False (not cross-domain)
    if either clock is missing from the map or from the path - can't
    make a claim without data, so it doesn't get excluded on that basis
    alone.
    """
    if not clock_family_map:
        return False
    if not path.startpoint_clock or not path.endpoint_clock:
        return False
    start_family = clock_family_map.get(path.startpoint_clock)
    end_family = clock_family_map.get(path.endpoint_clock)
    if start_family is None or end_family is None:
        return False
    return start_family != end_family


def _filter_valid_paths(paths, exclude_check_types=("recovery", "removal"),
                         exclude_path_groups=("asynchronous",), clock_family_map=None):
    """Shared filtering logic used by BOTH worst_violation() (iteration
    target selection) and compute_filtered_wns() (the WNS metric used
    for reporting and accept/reject decisions) - kept in exactly one
    place so the two can never drift apart. See worst_violation()'s
    docstring for the full reasoning behind each exclusion category.
    """
    return [
        p for p in paths
        if p.check_type not in exclude_check_types
        and p.path_group not in exclude_path_groups
        and not _is_cross_domain(p, clock_family_map)
    ]


def worst_violation(parsed: ParsedReports, exclude_check_types=("recovery", "removal"),
                     exclude_path_groups=("asynchronous",), clock_family_map=None) -> Optional[TimingPath]:
    """Returns the single worst (most negative slack) violated path,
    excluding:
    - recovery/removal (async reset) checks by default - a different
      class of problem than normal setup/hold, needs separate handling
    - paths grouped under an asynchronous clock group by default - even
      when set_clock_groups -asynchronous is configured correctly, a
      genuine cross-domain (CDC) data path can occasionally still show
      up as a normal-looking setup/hold check with path_group set to
      'asynchronous' (e.g. if SDC clock-group coverage has a gap for a
      given domain pair). These should not be handed to the standard
      6-technique auto-fix loop, since an LLM patch could break
      metastability protection on a synchronizer without realizing it.
    - (if clock_family_map is given) any path whose startpoint and
      endpoint clocks belong to different families per that map,
      REGARDLESS of what path_group says - a second, SDC-independent
      line of defense, since path_group depends entirely on the SDC's
      clock grouping being complete and correct. This is what catches
      the case where a genuine cross-domain path gets labeled with an
      ordinary-looking path_group (e.g. 'clk') because a generated
      clock was missing from its parent's async group.
    """
    candidates = _filter_valid_paths(parsed.critical_paths, exclude_check_types,
                                      exclude_path_groups, clock_family_map)
    violated = [p for p in candidates if p.violated]
    if not violated:
        return None
    return min(violated, key=lambda p: p.slack)


def compute_filtered_wns(paths, exclude_check_types=("recovery", "removal"),
                          exclude_path_groups=("asynchronous",), clock_family_map=None) -> Optional[float]:
    """Computes a WNS value using the SAME exclusion filtering
    worst_violation() applies for iteration target selection - fixes a
    real bug where the two used to disagree: worst_violation() already
    correctly ignored recovery/removal and CDC paths when picking what
    to hand the LLM, but the WNS number used for the printed "WNS
    (setup)" figure AND for decide()'s accept/reject slack-improvement
    comparison came from a raw, UNFILTERED OpenSTA report
    (worst_slack_setup.txt) that includes every check type.

    Concretely, this caused a real failure mode: once a recovery/
    removal violation became the numerically worst slack in the design
    (which the auto-fix loop can never touch, by design - see
    recovery_removal_violations()), decide() would compare that same,
    permanently-unchanged number against itself on every subsequent
    iteration, see "no improvement", and REJECT every future patch
    regardless of how much it genuinely improved the actual (non-
    excluded) violation it was targeting.

    `paths` should be a combined list of TimingPath objects gathered
    from every available UNCAPPED source (typically: parsed per-domain
    timing files, NOT parsed.critical_paths alone, since that file may
    be sampled/capped by -group_count/-endpoint_path_count in sta.tcl
    and could miss the true worst path for a domain that didn't make
    the cut - see orchestrator._extract_metrics() for how these are
    gathered together).

    Unlike worst_violation() (which only considers p.violated==True,
    since it needs an actual violation to hand the LLM), this
    deliberately does NOT filter by p.violated - WNS is conventionally
    the worst slack across all analyzed paths regardless of sign (a
    fully-met domain still reports its worst, positive, slack as its
    WNS - see parse_domain_worst_slack()'s docstring for the same
    convention already used elsewhere in this file).

    Returns None if no paths remain after filtering (e.g. every path
    in every domain happens to be recovery/removal or CDC - possible
    only in a degenerate/tiny design).
    """
    candidates = _filter_valid_paths(paths, exclude_check_types,
                                      exclude_path_groups, clock_family_map)
    if not candidates:
        return None
    return min(p.slack for p in candidates)


def recovery_removal_violations(parsed: ParsedReports) -> List[TimingPath]:
    """Returns violated recovery/removal (async reset) paths separately,
    for a future dedicated handler rather than the standard fix loop."""
    return [
        p for p in parsed.critical_paths
        if p.violated and p.check_type in ("recovery", "removal")
    ]


def cdc_violations(parsed: ParsedReports, clock_family_map=None) -> List[TimingPath]:
    """Returns violated paths CONFIRMED to be genuine cross-domain data
    paths - startpoint and endpoint clocks are in different families
    per clock_family_map, verified from the actual clock names in the
    report rather than inferred from a group label. Excludes recovery/
    removal checks (see recovery_removal_violations()).

    Note this no longer includes 'path_group == asynchronous' paths -
    those are returned separately by path_group_excluded_violations(),
    because that label alone does NOT prove a path is cross-domain and
    lumping the two together mislabels one as the other.
    """
    return [
        p for p in parsed.critical_paths
        if p.violated
        and p.check_type not in ("recovery", "removal")
        and _is_cross_domain(p, clock_family_map)
    ]


def path_group_excluded_violations(parsed: ParsedReports,
                                    path_groups=("asynchronous",),
                                    clock_family_map=None) -> List[TimingPath]:
    """Returns violated paths that were excluded from the auto-fix loop
    SOLELY because of their path_group label - i.e. they are not
    recovery/removal checks, and their clocks are NOT in different
    families, so nothing except the group name marks them as special.

    These are kept excluded as a conservative belt-and-braces measure,
    but flagged separately because some of them may be FALSE
    EXCLUSIONS: an ordinary same-domain setup/hold violation that is
    perfectly safe to fix, withheld only because the tool grouped it
    under 'asynchronous'. Anything listed here is worth a manual look -
    if it turns out to be a normal path, it can be fixed by hand, or
    the path_groups exclusion can be relaxed.
    """
    return [
        p for p in parsed.critical_paths
        if p.violated
        and p.check_type not in ("recovery", "removal")
        and p.path_group in path_groups
        and not _is_cross_domain(p, clock_family_map)
    ]


def compute_achievable_frequency(clock_period_ns, wns_ns):
    """PPA 'performance' metric: the maximum frequency the design could
    actually run at, given the worst negative slack observed.

    achievable_period = clock_period - wns
      - if wns is negative (violated), achievable_period > clock_period
        -> slower than the target clock, frequency drops accordingly
      - if wns is positive (margin to spare), achievable_period < clock_period
        -> the design could run faster than the target clock

    Returns frequency in MHz (float), or None if inputs are invalid.
    """
    if clock_period_ns is None or wns_ns is None:
        return None
    achievable_period_ns = clock_period_ns - wns_ns
    if achievable_period_ns <= 0:
        return None
    return 1000.0 / achievable_period_ns


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    reports_dir = sys.argv[1] if len(sys.argv) > 1 else "reports"
    parsed = parse_all_reports(reports_dir)

    print(f"WNS setup: {parsed.wns_setup}")
    print(f"WNS hold:  {parsed.wns_hold}")
    print(f"TNS setup: {parsed.tns_setup}")
    print(f"TNS hold:  {parsed.tns_hold}")
    print(f"Critical paths parsed: {len(parsed.critical_paths)}")
    print(f"Violations (slew/cap/fanout): {len(parsed.violations)}")

    worst = worst_violation(parsed)
    if worst:
        print(f"\nWorst violated path (excluding recovery/removal): {worst.startpoint} -> {worst.endpoint}, "
              f"slack={worst.slack}, check_type={worst.check_type}, stages={len(worst.stages)}")

    recovery_removal = recovery_removal_violations(parsed)
    if recovery_removal:
        print(f"\n{len(recovery_removal)} recovery/removal violation(s) found (excluded from auto-fix loop):")
        for p in recovery_removal:
            print(f"  {p.startpoint} -> {p.endpoint}, slack={p.slack}, check_type={p.check_type}")
