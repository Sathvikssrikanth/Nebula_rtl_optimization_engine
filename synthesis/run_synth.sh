#!/bin/bash
source /vlsi/cad/eda_tools/eda_env.sh
LIB=/home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib
# ================== SYNTHESIS ==================
#
# 5 top-level async clock domains (derived/divided clocks are not given
# their own -D target - they inherit their parent's period, which is the
# safe/tighter choice since a divided clock is always slower):
#
#   clk      : period 20 ns  -> freq  50.00 MHz
#   clk_md   : period 12 ns  -> freq  83.33 MHz
#   clk_fft  : period  9 ns  -> freq 111.11 MHz
#   clk_spi  : period  6 ns  -> freq 166.67 MHz
#   clk_fp   : period 10 ns  -> freq 100.00 MHz
yosys -p "
read_verilog ../verilog/CSR.v
read_verilog ../verilog/M1.v
read_verilog ../verilog/M2.v
read_verilog ../verilog/M3.v
read_verilog ../verilog/M4.v
read_verilog ../verilog/M5.v
read_verilog ../verilog/M6.v
read_verilog ../verilog/M7.v
read_verilog ../verilog/FP_Adder.v
read_verilog ../verilog/FP_Mult.v
read_verilog ../verilog/Hazard.v
read_verilog ../verilog/Multiplier.v
read_verilog ../verilog/PC.v
read_verilog ../verilog/Reset_sync.v
read_verilog ../verilog/address_decoder.v
read_verilog ../verilog/alu.v
read_verilog ../verilog/apb.v
read_verilog ../verilog/apb_cdc_bridge.v
read_verilog ../verilog/clk_div_fft.v
read_verilog ../verilog/clk_fp_divider.v
read_verilog ../verilog/controller.v
read_verilog ../verilog/data_mem.v
read_verilog ../verilog/derive_clk_gpio.v
read_verilog ../verilog/derive_clk_mul_div.v
read_verilog ../verilog/derive_clk_spi.v
read_verilog ../verilog/divider.v
read_verilog ../verilog/fft_top.v
read_verilog ../verilog/gpio.v
read_verilog ../verilog/handshake_bridge.v
read_verilog ../verilog/instr_mem.v
read_verilog ../verilog/interrupt_arbiter.v
read_verilog ../verilog/mux8_1.v
read_verilog ../verilog/pipeline_reg1.v
read_verilog ../verilog/pipeline_reg2.v
read_verilog ../verilog/pipeline_reg3.v
read_verilog ../verilog/register_file.v
read_verilog ../verilog/riscv_top.v
read_verilog ../verilog/slave_spi.v
read_verilog ../verilog/spi.v
read_verilog ../verilog/soc_top.v
synth -top soc_top
dfflibmap -liberty /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib
# --- core : clk domain, period 20 ns (50.00 MHz) ---
select riscv_top
abc -liberty /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib -D 20000
select -clear
# --- mult + div : clk_md domain, period 12 ns (83.33 MHz) ---
select Multiplier divider
abc -liberty /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib -D 12000
select -clear
# --- fft : clk_fft domain, period 9 ns (111.11 MHz) ---
select fft_top
abc -liberty /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib -D 9000
select -clear
# --- fp adder + fp mult : clk_fp domain, period 10 ns (100.00 MHz) ---
select FP_Adder FP_Mult
abc -liberty /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib -D 10000
select -clear

# --- spi : clk_spi domain, period 6 ns (166.67 MHz) ---
select spi
abc -liberty /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib -D 6000
select -clear

# --- remaining logic (top-level glue, APB/GPIO, CDC bridges) : clk domain, period 20 ns (50.00 MHz) ---
select soc_top
abc -liberty /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib -D 20000
select -clear

opt_clean

# Report area/cell statistics
tee -o ../synthesis/gates_report.txt stat
tee -o ../synthesis/area_report.txt stat -liberty /home/ppandit/digital/Flow_With_Scan_Verification/physical_design/defCDAC_DECODER_FINAL_done.enc.dat/libs/mmmc/tcbn65gplushvtwc_ccs.lib

# Final cleanup - strip unused public names before writeout
opt -purge soc_top

# Write out the gate-level netlist
write_verilog -noattr -noexpr soc_top_netlist.v
"

sed -i 's/\bsigned //g' ../synthesis/soc_top_netlist.v
