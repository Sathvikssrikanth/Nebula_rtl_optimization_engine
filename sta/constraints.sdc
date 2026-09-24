####################################################################
# soc_top.sdc
# Timing constraints matched to the current soc_top port list.
#
# 5 top-level async clocks: clk, clk_md, clk_fft, clk_spi, clk_fp.
# Derived clocks (clk_md_mul, clk_md_div, clk_fft_main, clk_fft_core,
# clk_fp_add, clk_fp_mul, clk_gpio, clk_spi_div) are generated clocks off
# their real parent - synchronous divides, not independent domains.
#
# Hierarchical pin paths in create_generated_clock are based on instance
# names seen in the RTL - verify against the actual synthesized netlist
# and fix any that don't resolve.
#
# All input/output delay and uncertainty values are placeholders -
# replace with real budget numbers once available.
####################################################################

# ==================== Primary (top-level) clocks ====================

create_clock -name clk      -period 50.0 [get_ports clk]
create_clock -name clk_md   -period 3.66 [get_ports clk_md]
create_clock -name clk_fft  -period 8.0  [get_ports clk_fft]
create_clock -name clk_spi  -period 1.0  [get_ports clk_spi]
create_clock -name clk_fp   -period 4.0 [get_ports clk_fp]

# ==================== Generated (derived) clocks ====================

create_generated_clock -name clk_md_mul \
    -source [get_ports clk_md] -divide_by 3 \
    [get_pins u_riscv_top/derive_clk_mu1_div/clk_md_mul]

create_generated_clock -name clk_md_div \
    -source [get_ports clk_md] -divide_by 6 \
    [get_pins u_riscv_top/derive_clk_mu1_div/clk_md_div]

create_generated_clock -name clk_fft_core \
    -source [get_ports clk_fft] -divide_by 1 \
    [get_pins u_riscv_top/clk_div_fft/clk_fft_core]

create_generated_clock -name clk_fft_main \
    -source [get_ports clk_fft] -divide_by 4 \
    [get_pins u_riscv_top/clk_div_fft/clk_fft_main]

create_generated_clock -name clk_fp_add \
    -source [get_ports clk_fp] -divide_by 2 \
    [get_pins u_riscv_top/clk_fp_divider/clk_fp_add]

create_generated_clock -name clk_fp_mul \
    -source [get_ports clk_fp] -divide_by 4 \
    [get_pins u_riscv_top/clk_fp_divider/clk_fp_mul]

create_generated_clock -name clk_spi_div \
    -source [get_ports clk_spi] -divide_by 3 \
    [get_pins u_derive_clk_spi/clk_spi_div]

create_generated_clock -name clk_gpio \
    -source [get_ports clk] -divide_by 2 \
    [get_pins u_derive_clk_gpio/clk_gpio]

# ==================== Async clock groups ====================
# ==================== Async clock groups ====================

set_clock_groups -asynchronous \
    -group {clk clk_gpio} \
    -group {clk_md clk_md_mul clk_md_div} \
    -group {clk_fft clk_fft_core clk_fft_main} \
    -group {clk_spi clk_spi_div} \
    -group {clk_fp clk_fp_add clk_fp_mul}

# ==================== Clock uncertainty ====================

set_clock_uncertainty 0.1 [get_clocks clk]
set_clock_uncertainty 0.1 [get_clocks clk_md]
set_clock_uncertainty 0.1 [get_clocks clk_fft]
set_clock_uncertainty 0.1 [get_clocks clk_spi]
set_clock_uncertainty 0.1 [get_clocks clk_fp]
set_clock_uncertainty 0.1 [get_clocks clk_md_mul]
set_clock_uncertainty 0.1 [get_clocks clk_md_div]
set_clock_uncertainty 0.1 [get_clocks clk_fft_core]
set_clock_uncertainty 0.1 [get_clocks clk_fft_main]
set_clock_uncertainty 0.1 [get_clocks clk_fp_add]
set_clock_uncertainty 0.1 [get_clocks clk_fp_mul]
set_clock_uncertainty 0.1 [get_clocks clk_spi_div]
set_clock_uncertainty 0.1 [get_clocks clk_gpio]

# ===================FALSE Paths ====================

set_false_path -through [get_nets -hierarchical stage0_n]
set_false_path -through [get_nets -hierarchical req_sync0]
set_false_path -through [get_nets -hierarchical ack_sync0]

# ==================== Reset ====================
# rst fans into all domains async. Constrain against the tightest clock
# (clk_spi, 6ns) so it's not under-constrained on any domain.

set_input_delay -clock clk_spi 0.3 [get_ports rst]

# ==================== Instruction memory load interface (clk domain) ====================

set_input_delay -clock clk 0.3 [get_ports im_wr_addr]
set_input_delay -clock clk 0.3 [get_ports im_wr_inst]
set_input_delay -clock clk 0.3 [get_ports wr_en_im]
set_input_delay -clock clk 0.3 [get_ports reset_im]

# ==================== GPIO (clk_gpio domain) ====================

set_input_delay  -clock clk_gpio 0.3 [get_ports gpio_in]
set_output_delay -clock clk_gpio 0.3 [get_ports gpio_out]

# ==================== SPI (clk_spi domain) ====================

set_output_delay -clock clk_spi 0.3 [get_ports spi_mosi]
set_input_delay  -clock clk_spi 0.3 [get_ports spi_miso]

# spi_sclk / spi_ss are bidirectional (inout) - constrain both directions
set_input_delay  -clock clk_spi 0.3 [get_ports spi_sclk]
set_output_delay -clock clk_spi 0.3 [get_ports spi_sclk]
set_input_delay  -clock clk_spi 0.3 [get_ports spi_ss]
set_output_delay -clock clk_spi 0.3 [get_ports spi_ss]

# dbg_mosi / dbg_miso are direct assigns off spi_mosi / spi_miso, so they
# live in the clk_spi domain too
set_output_delay -clock clk_spi 0.3 [get_ports dbg_mosi]
set_output_delay -clock clk_spi 0.3 [get_ports dbg_miso]

# ==================== Simulation/debug outputs (clk domain) ====================
# All *_sim outputs are pure observability off core-domain (clk) internal
# state - controller, register file, ALU, write-back, and the CDC
# outstanding-op status signals.

set_output_delay -clock clk 0.3 [get_ports {i_decode i_ex i_mem i_wb}]
set_output_delay -clock clk 0.3 [get_ports RegWrEn_sim]
set_output_delay -clock clk 0.3 [get_ports {RD1_sim RD2_sim RD3_sim RD4_sim WD5_sim}]
set_output_delay -clock clk 0.3 [get_ports {A1_sim A2_sim A3_sim A4_sim A5_sim}]
set_output_delay -clock clk 0.3 [get_ports AluOp_sim]
set_output_delay -clock clk 0.3 [get_ports AluResultSrc]
set_output_delay -clock clk 0.3 [get_ports wb_data_sim]
set_output_delay -clock clk 0.3 [get_ports {start_mul_sim mul_done_sim}]
set_output_delay -clock clk 0.3 [get_ports {start_div_sim div_done_sim}]
set_output_delay -clock clk 0.3 [get_ports {start_fft_sim done_fft_sim}]

# APB-side sim outputs - core-domain (clk) signals, upstream of both
# apb_cdc_bridge instances
set_output_delay -clock clk 0.3 [get_ports apb_trans_done_sim]
set_output_delay -clock clk 0.3 [get_ports {pready_gpio_sim prdata_gpio_sim psel_gpio_sim}]
set_output_delay -clock clk 0.3 [get_ports {pready_spi_sim prdata_spi_sim psel_spi_sim}]
set_output_delay -clock clk 0.3 [get_ports {penable_sim pwrite_sim paddr_sim pwdata_sim}]

####################################################################
# End of soc_top.sdc
####################################################################
