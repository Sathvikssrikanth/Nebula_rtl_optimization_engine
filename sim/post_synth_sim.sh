# ================= POST-SYNTHESIS SIMULATION =================

# Generic version: just netlist + testbench (works with Yosys's internal cell models)
iverilog -o synth_sim_out ../synthesis/top_netlist.v ../verilog/tb_top.v

# --- sky130-specific: uncomment and use this instead if mapped to sky130 cells ---
# iverilog -o post_synth_sim adder_netlist.v ../verilog_model/primitives.v ../verilog_model/sky130_fd_sc_hd_edited.v tb_adder.v

# Run the compiled simulation (generic)
vvp synth_sim_out

# View waveform (generic)
gtkwave tb_top.vcd
