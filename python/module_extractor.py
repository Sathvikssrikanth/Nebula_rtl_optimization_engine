"""
module_extractor.py
Resolves OpenSTA instance paths (e.g. 'u_counter_fast/_106_') back to the
actual RTL module + file, and extracts just that module's source code so
prompt_builder.py can hand a small, scoped snippet to the LLM instead of
the whole design.
"""

import re
from pathlib import Path


MODULE_DECL_RE = re.compile(r"^\s*module\s+(\w+)\s*[\(#]", re.MULTILINE)
# Matches instantiations like:  counter_fast u_counter_fast ( ... );
# or with parameters:            counter_fast #(...) u_counter_fast ( ... );
INSTANCE_RE = re.compile(
    r"^\s*(\w+)\s*(?:#\s*\([^;]*?\))?\s+(\w+)\s*\(", re.MULTILINE
)
# Verilog keywords that could false-match the instance pattern - excluded
KEYWORDS = {
    "module", "input", "output", "inout", "wire", "reg", "assign",
    "always", "initial", "begin", "end", "if", "else", "case", "endcase",
    "function", "task", "parameter", "localparam", "generate", "endgenerate",
    "for", "while", "posedge", "negedge",
}


class ModuleInfo(object):
    def __init__(self, name, filepath, source, role=None):
        self.name = name
        self.filepath = filepath
        self.source = source
        # role: 'startpoint', 'endpoint', or 'both' - which end of the
        # violating path this module was resolved from. Used to tell
        # the LLM which module(s) most likely contain the actual
        # timing-relevant registers/logic, versus a hierarchy wrapper
        # that just happened to appear in the instance path.
        self.role = role

    def __repr__(self):
        return "ModuleInfo(%s, %s, role=%s)" % (self.name, self.filepath, self.role)


def build_module_map(verilog_dir):
    """Scans all .v files in verilog_dir, returns {module_name: filepath (str)}."""
    module_map = {}
    for vfile in Path(verilog_dir).glob("*.v"):
        text = vfile.read_text()
        for m in MODULE_DECL_RE.finditer(text):
            module_map[m.group(1)] = str(vfile)
    return module_map


def build_instance_map(verilog_dir, module_map):
    """Scans all .v files for instantiations, returns
    {instance_name: module_name}. Only records instances whose type is a
    known module (from module_map) to avoid false positives on generic
    statements.
    """
    instance_map = {}
    for vfile in Path(verilog_dir).glob("*.v"):
        text = vfile.read_text()
        for m in INSTANCE_RE.finditer(text):
            mod_type, inst_name = m.group(1), m.group(2)
            if mod_type in KEYWORDS:
                continue
            if mod_type not in module_map:
                continue
            instance_map[inst_name] = mod_type
    return instance_map


def extract_module_source(module_name, module_map):
    """Pulls just 'module ... endmodule' text for module_name out of its file."""
    filepath = module_map.get(module_name)
    if not filepath:
        return None

    text = Path(filepath).read_text()
    pat = re.compile(
        r"(module\s+%s\b.*?endmodule)" % re.escape(module_name),
        re.DOTALL,
    )
    m = pat.search(text)
    return m.group(1) if m else None


# Matches a single ANSI-style port declaration inside a module's port
# list, e.g. "output reg [31:0] mem_rdata" or "input clk". Verilog-2001
# ANSI port style only (the whole design already uses this style
# throughout - see e.g. data_mem.v, register_file.v) - does not handle
# older non-ANSI (separate input/output statements in the module body).
PORT_DECL_RE = re.compile(
    r"\b(input|output)\b\s*(reg|wire)?\s*(\[[^\]]+\])?\s*(\w+)"
)


def extract_module_ports(module_name, module_map):
    """Parses just the port LIST (module name(...);) of module_name -
    not the whole body - and returns a list of dicts:
        {"direction": "input"|"output", "width": "[31:0]" or "" (1-bit),
         "name": "mem_rdata"}
    inout ports are skipped (not needed for the gold-wrapper use case
    this exists for - see formal_check.generate_gold_wrapper - and
    ambiguous to handle generically since the wrapper only forwards
    inputs through unchanged and delays outputs).

    Returns None if module_name isn't found, or its port list can't be
    isolated (e.g. non-ANSI port style) - caller should treat that as
    "wrapper generation not possible for this module" rather than
    guessing at a partial port list.
    """
    filepath = module_map.get(module_name)
    if not filepath:
        return None

    text = Path(filepath).read_text()
    header_pat = re.compile(
        r"module\s+%s\s*(?:#\s*\([^;]*?\))?\s*\((.*?)\)\s*;" % re.escape(module_name),
        re.DOTALL,
    )
    m = header_pat.search(text)
    if not m:
        return None

    port_list_text = m.group(1)
    ports = []
    for pm in PORT_DECL_RE.finditer(port_list_text):
        direction, _reg_or_wire, width, name = pm.groups()
        ports.append({
            "direction": direction,
            "width": width or "",
            "name": name,
        })

    if not ports:
        return None

    return ports


def resolve_instance_path(instance_path, instance_map, module_map):
    """Given an STA instance path like 'u_counter_fast/_106_', walks each
    path segment through the instance hierarchy and returns the list of
    ModuleInfo objects touched, deepest-first-relevant (usually just one
    for single-level hierarchy, more if the path crosses module boundaries).
    """
    segments = instance_path.split("/")
    modules_found = []
    seen = set()

    for seg in segments:
        # strip array indices e.g. u_foo[3] -> u_foo
        seg_clean = re.sub(r"\[\d+\]$", "", seg)
        mod_name = instance_map.get(seg_clean)
        if mod_name and mod_name not in seen:
            src = extract_module_source(mod_name, module_map)
            if src:
                modules_found.append(ModuleInfo(mod_name, module_map[mod_name], src))
                seen.add(mod_name)

    return modules_found


def get_modules_for_path(timing_path, verilog_dir):
    """Convenience wrapper: given a TimingPath (from report_parser.py) and
    the verilog source directory, returns the list of ModuleInfo objects
    relevant to that path's startpoint AND endpoint (handles paths that
    cross module boundaries, e.g. CDC).

    Each ModuleInfo's .role is set to one of:
        'startpoint_leaf', 'startpoint_ancestor',
        'endpoint_leaf',   'endpoint_ancestor',
        'both_leaf',       'both_ancestor'
    'leaf' = the deepest, most specific module resolved for that side -
    e.g. pipeline_reg2 or data_mem, the module that actually contains
    the violating register/logic. 'ancestor' = a wrapper module the
    instance path passed through on the way there (e.g. riscv_top) -
    usually just hierarchy context, but occasionally a legitimate fix
    target itself if it contains glue/combinational logic written
    directly in its own body that lies on the critical path (e.g. a mux
    selecting between sources before feeding a submodule). This
    distinction is what lets prompt_builder.py correctly steer the LLM
    toward the leaf modules by default while still allowing an ancestor
    when genuinely needed, instead of presenting every resolved module
    as equally likely - resolve_instance_path() already walks the
    hierarchy shallow-to-deep, so the LAST module found per side is
    that side's leaf.
    """
    module_map = build_module_map(verilog_dir)
    instance_map = build_instance_map(verilog_dir, module_map)

    modules = {}
    roles = {}
    for side, instance_path in (("startpoint", timing_path.startpoint),
                                 ("endpoint", timing_path.endpoint)):
        side_modules = resolve_instance_path(instance_path, instance_map, module_map)
        for i, mi in enumerate(side_modules):
            is_leaf = (i == len(side_modules) - 1)
            new_role = "%s_%s" % (side, "leaf" if is_leaf else "ancestor")

            modules[mi.name] = mi
            if mi.name in roles and roles[mi.name].split("_")[0] != side:
                # appears on both sides - keep whichever specificity is
                # higher (leaf beats ancestor) since that's the more
                # informative signal for the LLM
                prev_specificity = roles[mi.name].split("_")[1]
                specificity = "leaf" if (is_leaf or prev_specificity == "leaf") else "ancestor"
                roles[mi.name] = "both_%s" % specificity
            elif mi.name in roles:
                # same side seen again (e.g. a shared module instantiated
                # at multiple points in the same side's path) - upgrade
                # to leaf if either occurrence was a leaf
                if roles[mi.name].endswith("leaf") or is_leaf:
                    roles[mi.name] = new_role if is_leaf else roles[mi.name]
            else:
                roles[mi.name] = new_role

    for name, mi in modules.items():
        mi.role = roles[name]

    return list(modules.values())


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    vdir = sys.argv[1] if len(sys.argv) > 1 else "verilog"
    test_path = sys.argv[2] if len(sys.argv) > 2 else "u_counter_fast/_106_"

    mmap = build_module_map(vdir)
    imap = build_instance_map(vdir, mmap)

    print("Modules found:", mmap)
    print("Instances found:", imap)

    modules = resolve_instance_path(test_path, imap, mmap)
    for mi in modules:
        print("\n--- %s (%s) ---" % (mi.name, mi.filepath))
        print(mi.source[:300], "...")
