set TOP soc_top

# ================= SETUP =================

read_liberty /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib
read_verilog ../synthesis/${TOP}_netlist.v
link_design $TOP
read_sdc constraints.sdc

# ================= Setting Wire load to remove Capacitive Violations =================
#set_wire_load_model -name "TSMC64K_Lowk_Aggresive"
#set_wire_load_mode top

# ================= ONE-TIME SANITY CHECK =================

report_clock_properties > reports/clock_properties.txt

# ================= CRITICAL PATH REPORTS (main LLM input) =================

report_checks -path_delay max -group_count 1 -endpoint_path_count 1 -fields {slew cap fanout input_pin} > reports/critical_paths.txt
report_checks -path_delay min -group_count 1 -endpoint_path_count 1 -fields {slew cap fanout input_pin} >> reports/critical_paths.txt
report_checks -unconstrained > reports/unconstrained_paths.txt

report_checks -path_delay min_max -endpoint_path_count 1 > reports/worst_setup_hold.txt

# ================= SLEW / CAPACITANCE / FANOUT VIOLATIONS =================

report_check_types -max_slew -max_capacitance -max_fanout -violators > reports/violations.txt

# ================= SLACK SUMMARIES (per-iteration tracking) =================

report_worst_slack -max > reports/worst_slack_setup.txt
report_worst_slack -min > reports/worst_slack_hold.txti
report_tns > reports/tns.txt
report_checks -through [get_nets -hierarchical stage0_n]
# ================= POWER =================
report_power > reports/power_report.txt

# ================= PER-DOMAIN TIMING (unrestricted - no group_count cap) =================
# Each file now covers the primary clock AND its generated/derived children,
# since real logic (Multiplier, FFT, FP_Adder, etc.) runs on the derived
# clocks, not the primary clock itself - a report using only the primary
# clock would miss most of that domain's actual timing behavior.

report_checks -from [get_clocks clk]      -path_delay max >  reports/timing_core.txt
report_checks -from [get_clocks clk_gpio] -path_delay max >> reports/timing_core.txt

report_checks -from [get_clocks clk_md]     -path_delay max >  reports/timing_md.txt
report_checks -from [get_clocks clk_md_mul] -path_delay max >> reports/timing_md.txt
report_checks -from [get_clocks clk_md_div] -path_delay max >> reports/timing_md.txt

report_checks -from [get_clocks clk_fft]      -path_delay max >  reports/timing_fft.txt
report_checks -from [get_clocks clk_fft_core] -path_delay max >> reports/timing_fft.txt
report_checks -from [get_clocks clk_fft_main] -path_delay max >> reports/timing_fft.txt

report_checks -from [get_clocks clk_spi]     -path_delay max >  reports/timing_spi.txt
report_checks -from [get_clocks clk_spi_div] -path_delay max >> reports/timing_spi.txt

report_checks -from [get_clocks clk_fp]     -path_delay max >  reports/timing_fp.txt
report_checks -from [get_clocks clk_fp_add] -path_delay max >> reports/timing_fp.txt
report_checks -from [get_clocks clk_fp_mul] -path_delay max >> reports/timing_fp.txt

