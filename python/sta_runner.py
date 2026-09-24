"""
sta_runner.py
Runs YOUR existing sta.tcl (which reads constraints.sdc, the liberty file,
and the netlist using its own hardcoded relative paths) exactly as-is -
no generated/duplicate script. After it finishes, copies the reports/
folder it produced into <this_dir>/sta_iterations/reports so you have a
consistent, known location to point report_parser.py at.

Assumes your existing layout:
    <sta_dir>/sta.tcl
    <sta_dir>/constraints.sdc
    <sta_dir>/reports/            (written by sta.tcl itself)
    <sta_dir>/../synthesis/<TOP>_netlist.v   (netlist sta.tcl reads)

Python 3.6.8 compatible (no f-strings, no capture_output=True).
"""

import shutil
import subprocess
from pathlib import Path


class STAError(Exception):
    pass


def _next_iteration_dir(output_root):
    """Finds the next free iter_N folder under output_root, so repeated
    runs never overwrite a previous iteration's reports. Used only when
    the caller doesn't supply an explicit iteration_label.
    Returns (iteration_number, Path)."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)

    existing = []
    for d in root.glob("iter_*"):
        if d.is_dir():
            try:
                existing.append(int(d.name.split("_")[1]))
            except (IndexError, ValueError):
                continue

    next_n = (max(existing) + 1) if existing else 1
    return next_n, root / ("iter_%d" % next_n)


def run_sta(sta_dir="sta", tcl_script="sta.tcl",
            output_root=None, timeout=180,
            netlist_src=None, top_module="top", source_sta_dir=None,
            iteration_label=None):
    """
    Runs `sta -exit <tcl_script>` with cwd=sta_dir, so all of sta.tcl's
    existing relative paths (constraints.sdc, ../synthesis/..., reports/)
    resolve exactly as they do when you run it manually.

    If source_sta_dir is given, all *.tcl and *.sdc files from there are
    copied into sta_dir first (overwriting any existing copies) - lets
    you keep a self-contained python/sta/ workspace that's always synced
    from your original, hand-validated ../sta/ folder, without a manual
    `cp` step each time. Leave as None if sta_dir already has its own
    files and you don't want them touched.

    If netlist_src is given, it's copied to
    <sta_dir>/../synthesis/<top_module>_netlist.v first - the fixed
    location sta.tcl expects. Leave as None if you're placing the
    netlist there yourself.

    output_root defaults to <sta_dir>/sta_iterations (i.e. lives inside
    your sta/ workspace, not as a sibling of it). Pass an explicit path
    to override.

    iteration_label: pass an explicit folder name (e.g. 'iter_3') to
    keep this STA run's reports folder in lockstep with a specific
    patch_applier.py iteration number - important once this is called
    from orchestrator.py, since patch_applier's iteration_num and this
    function's own auto-incrementing counter are otherwise independent
    and can drift apart (e.g. after manual test runs). If None, falls
    back to auto-incrementing (iter_1, iter_2, ... based on what's
    already in output_root) - fine for standalone/manual use.

    After a successful run, copies sta_dir/reports/ into the resulting
    iteration folder under output_root, so every run's reports are
    preserved - nothing is ever overwritten.

    Returns dict: {success, reports_dir, log_path, iteration}
    """
    sta_path = Path(sta_dir)
    sta_path.mkdir(parents=True, exist_ok=True)

    if output_root is None:
        output_root = str(sta_path / "sta_iterations")

    if source_sta_dir:
        src = Path(source_sta_dir)
        if not src.exists():
            raise STAError("source_sta_dir not found: %s" % source_sta_dir)
        for pattern in ("*.tcl", "*.sdc"):
            for f in src.glob(pattern):
                shutil.copy(str(f), str(sta_path / f.name))

    script_file = sta_path / tcl_script
    if not script_file.exists():
        raise STAError("Script not found: %s" % str(script_file))

    # sta.tcl writes into reports/ via '>' redirects but doesn't create
    # the directory itself - OpenSTA errors out if it's missing
    (sta_path / "reports").mkdir(parents=True, exist_ok=True)

    if netlist_src:
        netlist_dst = (sta_path / ".." / "synthesis" / ("%s_netlist.v" % top_module)).resolve()
        netlist_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(netlist_src), str(netlist_dst))

    try:
        result = subprocess.run(
            ["sta", "-exit", tcl_script],
            cwd=str(sta_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise STAError("OpenSTA ('sta') not found on PATH.")
    except subprocess.TimeoutExpired:
        return {"success": False, "reports_dir": None, "log_path": None, "iteration": None}

    log_text = result.stdout.decode("utf-8", errors="replace")
    success = (result.returncode == 0) and ("Error" not in log_text)

    if iteration_label is not None:
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        iter_dir = root / iteration_label
        iteration_n = iteration_label
    else:
        iteration_n, iter_dir = _next_iteration_dir(output_root)

    iter_dir.mkdir(parents=True, exist_ok=True)

    log_path = iter_dir / "sta_log.txt"
    log_path.write_text(log_text)

    reports_dst = iter_dir / "reports"
    live_reports = sta_path / "reports"
    if success and live_reports.exists():
        if reports_dst.exists():
            shutil.rmtree(str(reports_dst))
        shutil.copytree(str(live_reports), str(reports_dst))

    return {
        "success": success,
        "reports_dir": str(reports_dst) if success else None,
        "log_path": str(log_path),
        "iteration": iteration_n,
    }


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    sta_dir = sys.argv[1] if len(sys.argv) > 1 else "sta"
    tcl_script = sys.argv[2] if len(sys.argv) > 2 else "sta.tcl"
    netlist_src = sys.argv[3] if len(sys.argv) > 3 else None
    top = sys.argv[4] if len(sys.argv) > 4 else "top"
    source_sta_dir = sys.argv[5] if len(sys.argv) > 5 else None
    iteration_label = sys.argv[6] if len(sys.argv) > 6 else None

    result = run_sta(sta_dir=sta_dir, tcl_script=tcl_script,
                      netlist_src=netlist_src, top_module=top,
                      source_sta_dir=source_sta_dir,
                      iteration_label=iteration_label)
    print("Success:", result["success"])
    print("Iteration:", result["iteration"])
    print("Reports dir:", result["reports_dir"])
    print("Log:", result["log_path"])
