"""
syntax_check.py
Runs iverilog -tnull (parse/elaborate only, no simulation output) against
a patched RTL directory to catch syntax errors before wasting a
synthesis + STA cycle on broken code from the LLM.
"""

import subprocess
from pathlib import Path


class SyntaxCheckError(Exception):
    pass


def check_syntax(verilog_dir, top_module=None, timeout=30):
    """
    Runs iverilog -tnull against all .v files in verilog_dir.

    verilog_dir : directory containing the (possibly patched) RTL
    top_module  : optional, unused by -tnull directly but kept for
                  future use / logging clarity
    timeout     : seconds before giving up on iverilog (safety net)

    Returns: (success: bool, message: str)
        success=True, message="" on clean parse
        success=False, message=<iverilog stderr/stdout> on syntax error
    """
    vfiles = sorted(str(f) for f in Path(verilog_dir).glob("*.v"))
    if not vfiles:
        return False, "No .v files found in %s" % verilog_dir

    cmd = ["iverilog", "-g2005", "-tnull"] + vfiles

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise SyntaxCheckError(
            "iverilog not found on PATH. Make sure Icarus Verilog is "
            "installed and available in this environment."
        )
    except subprocess.TimeoutExpired:
        return False, "iverilog timed out after %ds (possible infinite loop in RTL)" % timeout

    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout).strip()
        return False, error_msg

    return True, ""


def check_syntax_with_retry_context(verilog_dir, timeout=30):
    """Same as check_syntax but returns a dict suitable for feeding
    straight back into prompt_builder.py for a self-correction retry
    prompt, if the check fails.
    """
    success, message = check_syntax(verilog_dir, timeout=timeout)
    return {
        "success": success,
        "error_message": message if not success else None,
    }


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    vdir = sys.argv[1] if len(sys.argv) > 1 else "verilog"
    success, message = check_syntax(vdir)

    if success:
        print("Syntax OK: %s" % vdir)
        sys.exit(0)
    else:
        print("Syntax check FAILED for %s" % vdir)
        print(message)
        sys.exit(1)
