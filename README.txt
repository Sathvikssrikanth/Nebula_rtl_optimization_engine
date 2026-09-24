================================================================
NEBULA - GenAI RTL Timing Optimization Framework
================================================================

TOOLS: Yosys, OpenSTA, EQY, SimbiYosys, OpenROAD, iverilog

HOW TO RUN
----------
1. Make sure your LLM API key is set in the environment, matching
   whichever provider config.py's LLM_PROVIDER is set to:
       export GOOGLE_API_KEY=...      (for "gemini")
       export ANTHROPIC_API_KEY=...   (for "claude")
       export OPENAI_API_KEY=...      (for "openai")
   You can set it by sourcing the tools.sh file

2. Check config.py at a glance before running:
     - BASELINE_VERILOG_DIR  -> must point to your real baseline RTL
       (SEE THE NOTE BELOW - this currently says "../rtl", confirm
       that folder actually exists relative to python/, i.e. as a
       sibling of python/ itself)
     - TOP_MODULE            -> your design's top-level module name
     - LLM_PROVIDER          -> "gemini" / "claude" / "openai"
     - PNR_ENABLED           -> 0 = skip Physical Design, 1 = run it
     - INTERACTIVE_MODE      -> 1 = pauses to ask you things,
                                 0 = runs unattended start to finish

3. Run from inside the python/ directory:
       cd python
       python3 orchestrator.py

   Everything else (synthesis, STA, formal checks, PnR, reports,
   the dashboard) happens automatically from there.

4. When it finishes, check:
       python/logs/demo.html                       - the dashboard
       python/logs/report.md                        - the main report
       python/logs/formal_verification_report.md    - formal sign-off
       python/optimized_rtl/                         - final accepted RTL


DIRECTORY GUIDE
----------------

Everything below python/ is created and managed automatically by
the framework - safe to delete any of it and re-run; it all
regenerates from scratch (see config.py comments / your own earlier
question about this). The only things that must genuinely already
exist and be hand-maintained are your baseline RTL and the SOURCE
sta/pnr script folders described below.

--- Inside python/ ---

  config.py            Central settings file - paths, clock periods,
                        LLM provider, timeouts, feature toggles.
                        Read this first if anything looks wrong.

  orchestrator.py       The main script - this is what you actually run.

  formal_check.py        The older EQY-based equivalence checking
                        backend - still used for anything that isn't
                        the per-iteration accelerator-module check.

  report_parser.py       Parses raw STA/PnR text reports into data.
  module_extractor.py    Maps a timing violation to its RTL module.
  prompt_builder.py      Builds the prompt sent to the LLM.
  llm_client.py          Calls Claude/Gemini/GPT, extracts the patch.
  patch_applier.py       Writes the LLM's patch into a new RTL folder.
  syntax_check.py        Runs Icarus Verilog to catch broken syntax.
  synth_runner.py        Runs Yosys synthesis (script generated fresh
                        every run - see the file itself for details).
  sta_runner.py          Runs your own hand-written sta.tcl script.
  pnr_runner.py           Runs your own hand-written pnr.tcl script.
  generate_demo.py       Builds the offline HTML dashboard.
  logger.py              Records every iteration; builds the reports.

  synth/                Yosys synthesis workspace + per-iteration
                        output (config.SYNTH_OUTPUT_DIR). Regenerated
                        every run.

  sta/                  STA WORKSPACE - a working copy of your real
                        sta.tcl/*.sdc files (config.STA_DIR), synced
                        in automatically each run from ../sta (see
                        below). Safe to delete; it re-syncs itself.

  pnr/                  Same idea as sta/, but for pnr.tcl
                        (config.PNR_DIR), synced from ../pnr.

  formal/               EQY-backend equivalence-check workspace
                        (config.FORMAL_OUTPUT_DIR) - the older
                        formal_check.py backend's working files.

  verilog_iterations/    Every patched RTL attempt, one folder per
                        iteration (config.VERILOG_ITERATIONS_ROOT) -
                        this is where each LLM patch actually gets
                        written and built from.

  optimized_rtl/        The FINAL accepted RTL, copied here at the
                        end of the run (config.FINAL_OUTPUT_DIR).
                        Only appears if at least one patch was
                        accepted.

  logs/                 Every generated report and log
                        (config.LOG_PATH / REPORT_PATH /
                        DEMO_OUTPUT_PATH / etc.) - run.jsonl is the
                        single source of truth everything else is
                        built from.

--- One level up (sibling of python/) ---

  sta/                  The REAL, hand-written STA source - sta.tcl
                        and your .sdc constraints live here
                        permanently (config.SOURCE_STA_DIR = "../sta").
                        python/sta/ is just a disposable synced copy
                        of this - edit the real files HERE, not there.

  pnr/                  Same idea - your real, hand-written pnr.tcl
                        lives here (config.SOURCE_PNR_DIR = "../pnr").

  verilog/              Your baseline RTL - see the NOTE above about
                        this exact folder name. This one is NEVER
                        modified by the framework; every patch attempt
                        works from a COPY of it.

  formal/, synthesis/    Not referenced anywhere in config.py - these
                         are separate, manually-created folders for external user runs

  sim/, sync/, tools.sh  Also not referenced in config.py - User Directories
