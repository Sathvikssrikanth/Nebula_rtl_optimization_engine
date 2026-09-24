"""
config.py
Central place for paths, tool settings, and thresholds used across the
framework.

Python 3.6.8 compatible - plain module-level constants, no dataclasses.
"""

# ---------------------------------------------------------------------------
# Project layout - baseline RTL, top module, liberty file
# ---------------------------------------------------------------------------
BASELINE_VERILOG_DIR = "../verilog"
TOP_MODULE = "soc_top"
LIBERTY_PATH = (
    "../../../digital/Flow_With_Scan_Verification/physical_design/"
    "defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib"
)

# ---------------------------------------------------------------------------
# STA (sta_runner.py) - runs your hand-written sta.tcl in an isolated workspace
# ---------------------------------------------------------------------------
STA_DIR = "sta"
STA_TCL_SCRIPT = "sta.tcl"
SOURCE_STA_DIR = "../sta"
STA_TIMEOUT = 600

# ---------------------------------------------------------------------------
# Physical Design / PnR (pnr_runner.py) - optional one-shot OpenROAD sign-off,
# disabled by default; same DIR/SCRIPT/SOURCE/TIMEOUT pattern as STA above
# ---------------------------------------------------------------------------
PNR_ENABLED = 1
PNR_DIR = "pnr"
PNR_TCL_SCRIPT = "pnr.tcl"
SOURCE_PNR_DIR = "../pnr"
PNR_TIMEOUT = 10800

# ---------------------------------------------------------------------------
# Synthesis (synth_runner.py) - script is generated fresh each run, not
# hand-written, so there's no SOURCE dir here unlike STA/PnR
# ---------------------------------------------------------------------------
SYNTH_OUTPUT_DIR = "synth"
SYNTH_TIMEOUT = 600

# ---------------------------------------------------------------------------
# Formal equivalence (formal_check.py) - per-module checks every iteration,
# plus one harder whole-design sign-off check at the end before PnR
# ---------------------------------------------------------------------------
FORMAL_OUTPUT_DIR = "formal"
EQY_DEPTH = 5
EQY_TIMEOUT = 600
OVERALL_FORMAL_CHECK_ENABLED = 1
OVERALL_EQY_TIMEOUT = 3600
OVERALL_SAT_TIMEOUT = 600

# ---------------------------------------------------------------------------
# Patch iterations (patch_applier.py)
# ---------------------------------------------------------------------------
VERILOG_ITERATIONS_ROOT = "verilog_iterations"

# ---------------------------------------------------------------------------
# LLM (llm_client.py) - provider/model selection and retry budgets; API keys
# are read from environment variables by llm_client.py, never hardcoded here
# ---------------------------------------------------------------------------
LLM_PROVIDER = "gemini"
LLM_MODEL = None
MAX_LLM_RETRIES = 3
MAX_SYNTAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Clock domains - periods, async families (for CDC detection), and which
# module runs on which clock (so synth_runner.py gives ABC the right
# per-module timing target instead of one global period for everything)
# ---------------------------------------------------------------------------

CLOCK_PERIODS_NS = {
    "clk": 50.0,
    "clk_md": 3.66,
    "clk_fft": 8.0,
    "clk_spi": 1.0,
    "clk_fp": 4.0,
    # Generated (derived) clocks - period = parent_period * divide_by,
    # per soc_top.sdc's create_generated_clock declarations.
    "clk_md_mul": 10.98,     # clk_md (12) x3
    "clk_md_div": 21.96,     # clk_md (12) x6
    "clk_fft_core": 8.0,    # clk_fft (9) x1
    "clk_fft_main": 32.0,   # clk_fft (9) x4
    "clk_fp_add": 8.0,     # clk_fp (10) x2
    "clk_fp_mul": 16.0,     # clk_fp (10) x4
    "clk_spi_div": 3.0,    # clk_spi (6) x3
    "clk_gpio": 100.0,       # clk (20) x2
}

CLOCK_FAMILY_MAP = {
    "clk": "clk", "clk_gpio": "clk",
    "clk_md": "clk_md", "clk_md_mul": "clk_md", "clk_md_div": "clk_md",
    "clk_fft": "clk_fft", "clk_fft_core": "clk_fft", "clk_fft_main": "clk_fft",
    "clk_spi": "clk_spi", "clk_spi_div": "clk_spi",
    "clk_fp": "clk_fp", "clk_fp_add": "clk_fp", "clk_fp_mul": "clk_fp",
}

MODULE_CLOCK_MAP = {
    "PC": "clk",
    "alu": "clk",
    "controller": "clk",
    "register_file": "clk",
    "CSR": "clk",
    "pipeline_reg1": "clk",
    "pipeline_reg2": "clk",
    "pipeline_reg3": "clk",
    "Multiplier": "clk_md_mul",
    "divider": "clk_md_div",
    "FP_Adder": "clk_fp_add",
    "FP_Mult": "clk_fp_mul",
    "fft_top": "clk_fft_main",
    "apb": "clk",
    "interrupt_arbiter": "clk",
    "data_mem": "clk",
    "derive_clk_gpio": "clk",
    "derive_clk_spi": "clk_spi",
    "gpio": "clk_gpio",
    "spi": "clk_spi_div",
    "handshake_bridge": "clk",
    "reset_sync": "clk_spi_div",
    "apb_cdc_bridge": "clk_spi_div",
    # Combinational modules with no clock port (hazard, address_decoder,
    # M1-M7, mux8_1) and the clock dividers themselves are intentionally
    # omitted - nothing for ABC to time-optimize without a clocked register.
}

PRIMARY_CLOCK = "clk"   #For any leftover logic - clock targets

DOMAIN_TIMING_FILES = {
    "clk": "timing_core.txt",
    "clk_md": "timing_md.txt",
    "clk_fft": "timing_fft.txt",
    "clk_spi": "timing_spi.txt",
    "clk_fp": "timing_fp.txt",
}

# ---------------------------------------------------------------------------
# Orchestrator decision thresholds - how the accept/reject loop behaves
# ---------------------------------------------------------------------------
SLACK_IMPROVEMENT_THRESHOLD = 0.0   #How much improvement in slack has to be accepted as success
MAX_ITERATIONS = 10
INTERACTIVE_MODE = 1  # 1=On, 0=OFF
MAX_REJECTED_RETRIES_PER_VIOLATION = 2

# ---------------------------------------------------------------------------
# Output paths - final RTL, logs, and every generated report/dashboard
# ---------------------------------------------------------------------------
FINAL_OUTPUT_DIR = "optimized_rtl"
LOG_PATH = "logs/run.jsonl"
REPORT_PATH = "logs/report.md"
DEMO_OUTPUT_PATH = "logs/demo.html"
PNR_RESULT_PATH = "logs/pnr_result.json"
UNRESOLVED_EXCLUSIONS_PATH = "logs/unresolved_exclusions.json"
