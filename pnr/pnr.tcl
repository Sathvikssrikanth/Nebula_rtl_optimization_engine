####################################################################
# pnr.tcl - OpenROAD flow for soc_top (5 async top clocks, 8 generated)
####################################################################

# ==================== 1. READ DESIGN ====================

read_lef  /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/lef/tcbn65gplushvt_9lmT2.lef
define_corners wc bc
read_liberty -corner wc /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib
read_liberty -corner bc /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtbc_ccs.lib

read_verilog ../synthesis/soc_top_netlist.v
link_design soc_top
read_sdc constraints.sdc

report_clock_properties

# ==================== 2. FLOORPLAN ====================
# Sized for actual chip area (~565K um^2) at ~55% utilization.
# Previous {5 5 625 625} core was <100% util and caused massive
# routing congestion (49K+ DRC violations). This fixes that.

initialize_floorplan -site core \
    -die_area  {0 0 1040 1040} \
    -core_area {10 10 1030 1030}

# ==================== 3. TRACKS (LEF has no tracks section) ====================
# Values grepped directly from tcbn65gplushvt_9lmT2.lef PITCH/OFFSET.
# Must run AFTER initialize_floorplan (tracks are relative to die area).

make_tracks M1 -x_offset 0.000 -x_pitch 0.200 -y_offset 0.000 -y_pitch 0.200
make_tracks M2 -x_offset 0.100 -x_pitch 0.200 -y_offset 0.100 -y_pitch 0.200
make_tracks M3 -x_offset 0.000 -x_pitch 0.200 -y_offset 0.000 -y_pitch 0.200
make_tracks M4 -x_offset 0.100 -x_pitch 0.200 -y_offset 0.100 -y_pitch 0.200
make_tracks M5 -x_offset 0.000 -x_pitch 0.200 -y_offset 0.000 -y_pitch 0.200
make_tracks M6 -x_offset 0.100 -x_pitch 0.200 -y_offset 0.100 -y_pitch 0.200
make_tracks M7 -x_offset 0.000 -x_pitch 0.200 -y_offset 0.000 -y_pitch 0.200
make_tracks M8 -x_offset 0.100 -x_pitch 0.800 -y_offset 0.100 -y_pitch 0.800
make_tracks M9 -x_offset 0.000 -x_pitch 0.800 -y_offset 0.000 -y_pitch 0.800

insert_tiecells -prefix TIE_ZERO_ TIELHVT/ZN
insert_tiecells -prefix TIE_ONE_  TIEHHVT/Z

# ==================== 4. IO PIN PLACEMENT ====================
# M4 is VERTICAL, M5 is HORIZONTAL per LEF DIRECTION - do not swap.

place_pins -hor_layers M5 -ver_layers M4

# ==================== 5. POWER PLANNING (PDN) ====================
# Netlist has no power/ground nets from synthesis - create them here.
# M2/M3 were the most congested signal-routing layers (M3 alone had
# 18K+ shorts in early runs) - wide power stripes moved to M4/M5,
# M2 kept only for -followpins rail connections.

add_global_connection -net VDD -pin_pattern "^VDD$" -power
add_global_connection -net VSS -pin_pattern "^VSS$" -ground
global_connect

set_voltage_domain -name CORE -power VDD -ground VSS

define_pdn_grid -name grid \
    -voltage_domains CORE

add_pdn_stripe -grid grid -layer M2 -width 0.2 -pitch 5.0  -offset 0.5 -followpins
add_pdn_stripe -grid grid -layer M4 -width 0.4 -pitch 10.0 -offset 0.5
add_pdn_stripe -grid grid -layer M5 -width 0.4 -pitch 10.0 -offset 0.5

add_pdn_ring -grid grid -layers {M6 M7} -widths 0.5 -spacings 0.5 -core_offsets 0.5

add_pdn_connect -grid grid -layers {M2 M4}
add_pdn_connect -grid grid -layers {M4 M5}
add_pdn_connect -grid grid -layers {M5 M6}
add_pdn_connect -grid grid -layers {M6 M7}

pdngen

# ==================== 6. PLACEMENT ====================
# -routability_driven + lower density (0.55) + padding gives the
# router real headroom. Default (no options) caused near-max packing
# and cascading M2/M3 congestion in earlier runs.

global_placement -routability_driven -density 0.55 -pad_left 2 -pad_right 2
detailed_placement
check_placement -verbose

# NOTE: report_design_area's output does not go through the same
# capture mechanism as report_power/report_wns, so a direct '>' or
# 'redirect'-style capture doesn't work in this build. It still
# prints to stdout/log normally - pull it out of pnr_log.txt after
# the run instead (see bottom of this file for the exact command).

report_design_area

# ==================== 7. CLOCK TREE SYNTHESIS ====================
# 13 clocks total (5 primary async + 8 generated).

clock_tree_synthesis -root_buf BUFFD1HVT -buf_list BUFFD1HVT
detailed_placement
check_placement -verbose

set_propagated_clock [all_clocks]

# ==================== 7b. HOLD FIXING ====================
# Post-CTS hold violations are expected (clock network delay can
# outpace near-zero-delay data paths on divider/adjacent-FF chains).
# estimate_parasitics gives repair_timing realistic delay data to
# work with before routing exists; repair_timing -hold inserts delay
# buffers on the violating paths only (setup is already met, so we
# skip touching it here to avoid undoing that).

estimate_parasitics -placement
repair_timing -hold -hold_margin 0.05

detailed_placement
check_placement -verbose

report_clock_skew > reports/clock_skew.rpt

# ==================== 8. ROUTING ====================

global_route
write_guide reports/route.guide      ;# save global route result
write_db reports/checkpoint.db       ;# save full design state (physical only - liberty/SDC must be re-read if reloading later)
detailed_route -output_drc reports/route_drc.rpt -drc_report_iter_step 1
check_antennas

# ==================== 9. PPA SIGN-OFF REPORTS ====================

# Power - this build requires -scene on every call when multiple
# corners are defined (define_corners wc bc) - a scene-less call
# errors with STA-0103, unlike a single-corner session.

report_power -scene wc     > reports/power.rpt
report_power -scene bc    >> reports/power.rpt

# Performance (timing) - report_checks DOES accept -corner in this build.
# report_wns / report_tns do NOT accept -corner - drop the flag or they error.

report_checks -path_delay max -corner wc -fields {slew cap input} > reports/timing_setup_wc.rpt
report_checks -path_delay min -corner bc -fields {slew cap input} > reports/timing_hold_bc.rpt
report_wns                                                         > reports/wns.rpt
report_tns                                                        >> reports/wns.rpt

# Hold-specific worst slack/TNS for a clean before/after check
# against the violations seen pre-fix.
# Hold-specific worst slack/TNS - printed to log/stdout only, same
# reason as report_design_area above. Grep from pnr_log.txt after run.
report_worst_slack -min
report_tns -digits 4
report_clock_skew                                                  > reports/clock_skew_final.rpt


# Area - report_design_area does not support '>' redirection in this
# build (confirmed: file never gets created even when the line prints
# to terminal/log). Prints to stdout/log only - grep it from
# pnr_log.txt after the run (see note at the bottom of this script).

report_design_area

####################################################################
# End of pnr.tcl
####################################################################
#
# POST-RUN: to pull the design-area number out of the run log
# (it does not reliably capture to file in this build), run:
####################################################################
