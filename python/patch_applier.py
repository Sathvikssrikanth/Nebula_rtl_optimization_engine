"""
patch_applier.py
Applies an LLM-generated patch (full replacement module text) into an
isolated iteration folder, without touching the original/baseline RTL.
Copies all other unmodified modules alongside it so the folder is a
complete, buildable design ready for syntax_check.py / synth_runner.py.
"""

import re
import shutil
from pathlib import Path


MODULE_NAME_RE = re.compile(r"\bmodule\s+(\w+)\b")
MODULE_COUNT_RE = re.compile(r"\bmodule\s+\w+\b")


class PatchError(Exception):
    pass


def extract_module_name(patch_text):
    """Pulls the module name out of the patch text (e.g. 'module counter_fast (').
    Raises PatchError if no module is found, or if MORE THAN ONE module
    declaration is present - previously this silently took just the
    first match and any additional module(s) in the response were
    dropped without warning. Rejecting outright is safer: it surfaces
    the problem (via the normal syntax-retry path) instead of quietly
    discarding part of what the LLM returned.
    """
    matches = MODULE_COUNT_RE.findall(patch_text)
    if not matches:
        raise PatchError("Could not find 'module <name>' in patch text.")
    if len(matches) > 1:
        names = [MODULE_NAME_RE.match(m).group(1) for m in matches]
        raise PatchError(
            "Patch contains %d module declarations (%s), expected exactly "
            "1. Only one module may be modified per patch - resubmit with "
            "just the single module that needs the fix."
            % (len(matches), ", ".join(names))
        )
    m = MODULE_NAME_RE.search(patch_text)
    return m.group(1)


def apply_patch(baseline_dir, patch_text, iteration_num, output_root="verilog_iterations",
                 allowed_modules=None):
    """
    baseline_dir    : directory containing the current known-good RTL (.v files)
    patch_text      : full replacement module text returned by llm_client.py
    iteration_num   : integer, used to name the iteration folder
    output_root     : parent directory under which iteration folders are created
    allowed_modules : optional list/set of module names the patch is permitted
                      to target (typically the module names shown to the LLM
                      in the prompt, from module_extractor.get_modules_for_path()).
                      If given and the patch's module isn't in this set, raises
                      PatchError rather than silently applying a fix to a module
                      that was never shown as a valid target - e.g. the LLM
                      inventing or guessing a module name outside the ones
                      it was actually given context for.

    Returns: (iter_dir, patched_filepath, module_name)
    Raises PatchError if the patch's target module isn't found in baseline_dir,
    contains more than one module declaration, or isn't in allowed_modules.
    """
    module_name = extract_module_name(patch_text)

    if allowed_modules is not None and module_name not in allowed_modules:
        raise PatchError(
            "Patch targets module '%s', which was not one of the modules "
            "provided in the prompt (%s). Refusing to apply - this usually "
            "means the LLM invented a module name or misread the context."
            % (module_name, ", ".join(allowed_modules))
        )

    baseline = Path(baseline_dir)
    iter_dir = Path(output_root) / ("iter_%d" % iteration_num)

    # Clear any leftovers from a previous run before writing. Without
    # this, a file that was in the baseline back then but has since been
    # removed (a testbench, an obsolete module) survives in the folder
    # and gets picked up by the *.v glob in synth_runner/syntax_check,
    # breaking synthesis for reasons that have nothing to do with this
    # patch. mkdir(exist_ok=True) alone does not remove stale contents.
    if iter_dir.exists():
        shutil.rmtree(str(iter_dir))
    iter_dir.mkdir(parents=True, exist_ok=True)

    # Find which file in baseline currently defines this module
    target_file = None
    for vfile in baseline.glob("*.v"):
        text = vfile.read_text()
        if re.search(r"\bmodule\s+%s\b" % re.escape(module_name), text):
            target_file = vfile
            break

    if target_file is None:
        raise PatchError(
            "Patch defines module '%s' but no matching module was found "
            "in baseline dir '%s'. Refusing to apply - patch may have "
            "renamed the module or targeted the wrong one."
            % (module_name, baseline_dir)
        )

    # Copy all baseline files into the iteration dir unchanged first
    for vfile in baseline.glob("*.v"):
        shutil.copy(str(vfile), str(iter_dir / vfile.name))

    # Replace ONLY the target module's text inside its file, leaving any
    # sibling modules in that same file untouched. Overwriting the whole
    # file with the patch would silently delete them - several files in
    # a real design hold more than one module (e.g. spi.v holds spi plus
    # USR, PHASE_POLARITY, EDGE_COUNTER_16, BAUD_GEN and ADD_DECO).
    patched_filepath = iter_dir / target_file.name
    original_text = patched_filepath.read_text()

    module_block_re = re.compile(
        r"module\s+%s\b.*?endmodule" % re.escape(module_name),
        re.DOTALL,
    )
    if not module_block_re.search(original_text):
        raise PatchError(
            "Found module '%s' declared in '%s', but could not match a "
            "complete 'module ... endmodule' block for it - refusing to "
            "patch rather than risk corrupting the file."
            % (module_name, target_file.name)
        )

    new_block = patch_text.strip()
    # re.sub would interpret backslashes/group refs in the patch text,
    # so substitute via a lambda that returns it literally.
    patched_text, n_replaced = module_block_re.subn(
        lambda _m: new_block, original_text, count=1)

    if n_replaced != 1:
        raise PatchError(
            "Expected exactly 1 replacement of module '%s' in '%s', "
            "made %d." % (module_name, target_file.name, n_replaced)
        )

    patched_filepath.write_text(patched_text)

    return str(iter_dir), str(patched_filepath), module_name


def diff_summary(original_filepath, patched_filepath):
    """Returns a simple line-count diff summary for logging purposes.
    Not a full diff - just enough to sanity-check patch size in logs."""
    orig_lines = Path(original_filepath).read_text().splitlines()
    patched_lines = Path(patched_filepath).read_text().splitlines()
    return {
        "original_lines": len(orig_lines),
        "patched_lines": len(patched_lines),
        "delta": len(patched_lines) - len(orig_lines),
    }


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    baseline_dir = sys.argv[1] if len(sys.argv) > 1 else "verilog"
    iteration_num = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    # simple manual test patch - pipelined counter_fast with an extra stage
    test_patch = """module counter_fast (
    input  wire       clk_fast,
    input  wire       rst_n,
    output reg  [7:0] count_out
);

    reg [7:0] count;
    reg [7:0] stage_reg;   // added pipeline register
    wire [7:0] next_val;

    wire [7:0] stage1, stage2, stage3, stage4;

    assign stage1 = count ^ 8'hA5;
    assign stage2 = stage1 & (count << 1);
    assign stage3 = stage2 | (count >> 1);
    assign stage4 = stage3 ^ (stage1 & stage2);
    assign next_val = stage_reg + count + 8'h01;

    always @(posedge clk_fast or negedge rst_n) begin
        if (!rst_n)
            stage_reg <= 8'h00;
        else
            stage_reg <= stage4;
    end

    always @(posedge clk_fast or negedge rst_n) begin
        if (!rst_n)
            count <= 8'h00;
        else
            count <= next_val;
    end

    always @(posedge clk_fast or negedge rst_n) begin
        if (!rst_n)
            count_out <= 8'h00;
        else
            count_out <= count;
    end

endmodule
"""

    iter_dir, patched_file, mod_name = apply_patch(baseline_dir, test_patch, iteration_num)
    print("Module patched:", mod_name)
    print("Iteration dir:", iter_dir)
    print("Patched file:", patched_file)

    orig_file = str(Path(baseline_dir) / (mod_name + ".v"))
    print("Diff summary:", diff_summary(orig_file, patched_file))

    print("\nFiles in iteration dir:")
    for f in sorted(Path(iter_dir).glob("*.v")):
        print(" ", f.name)
