/*  SOC top :
    Integrates RISC-V with all peripherals via the APB

    CDC UPDATE:
      - APB<->SPI goes through apb_cdc_bridge. clk_spi is an independent
        top-level clock, so this is a true async crossing.
      - APB<->GPIO goes through apb_cdc_bridge too. clk_gpio is a
        synchronous div-2 of clk, so this is not a metastability fix - it
        widens the APB access phase to a full clk_gpio cycle so gpio's
        write strobe is actually captured.
      - reset_sync added for the SPI and GPIO domains.

    STILL RAW (not yet done):
      - Interrupt path (int_spi_req / ack_spi / riscv_ready / ack_gpio)
        still crosses unsynchronised. Left as-is for now since riscv_top
        ties spi_irq and gpio_irq to 0, so the interrupt path is inactive.
        Needs bit_sync on each signal when interrupts are enabled.
*/

module soc_top ( 
    input wire clk_md, 
    input wire clk_fft, 
    input wire clk, 
    input wire rst, 
    input wire clk_fp,
    input wire clk_spi,   // dedicated SPI domain input clock

    input [31:0] im_wr_addr,
    input [31:0] im_wr_inst,
    input        wr_en_im,
    input        reset_im,

    input  wire [3:0] gpio_in, 
    output wire [3:0] gpio_out, 
 
    output wire spi_mosi,   
    input  wire spi_miso,   
    inout  wire spi_sclk, 
    inout  wire spi_ss, 

    //Simulation 
    output wire apb_trans_done_sim,         //APB 
    output wire pready_gpio_sim, 
    output wire [31:0] prdata_gpio_sim, 
    output wire psel_gpio_sim, 
    output wire pready_spi_sim, 
    output wire [31:0] prdata_spi_sim, 
    output wire psel_spi_sim, 
    output wire penable_sim, 
    output wire pwrite_sim, 
    output wire [31:0] paddr_sim, 
    output wire [31:0] pwdata_sim, 
 
    output wire [31:0] i_decode,i_ex,i_mem,i_wb,    //Controller 
 
    output wire RegWrEn_sim , 
    output wire [31:0] RD1_sim,RD2_sim ,RD3_sim ,RD4_sim ,WD5_sim,  //RF 
    output wire [4:0] A1_sim,A2_sim ,A3_sim ,A4_sim ,A5_sim,         
 
    output wire [31:0] AluOp_sim,    //ALU 
    output wire [2:0] AluResultSrc, 
 
    output wire [31:0] wb_data_sim,         //WB 
 
    output wire start_mul_sim, mul_done_sim, 
    output wire done_fft_sim, start_fft_sim, 
    output wire start_div_sim,
    output wire div_done_sim,   //FFT, MUlt 
 
    output wire dbg_mosi, 
    output wire dbg_miso              // SPI 
 
    ); 
        
    wire [31:0] imem_addr;
    wire [31:0] imem_instr;
    
    //RISCV -- Address decoder 
    wire        riscv_we; 
    wire [31:0] riscv_addr; 
    wire [31:0] riscv_wdata; 
    wire [31:0] riscv_rdata; 
    wire        riscv_trans_done; 
    
    //RISV -- Interrupt Arbiter 
    wire        irq_gpio_riscv; 
    wire        irq_spi_riscv; 
    wire        riscv_busy; 
    
    //Address Decoder -- APB 
    wire apb_we; 
    wire [31:0] apb_addr; 
    wire [31:0] apb_wdata; 
    wire [31:0] apb_rdata; 
    wire apb_trans_done; 
    
    //Address Decoder -- Data Mem 
    wire mem_we; 
    wire [31:0] mem_addr; 
    wire [31:0] mem_wdata; 
    wire [31:0] mem_rdata; 
    wire mem_ena; 
    
    //APB -- SPI/GPIO 
    wire        clk_spi_div;
    wire        psel_spi; 
    wire        pready_spi; 
    wire [31:0] prdata_spi; 
    wire        penable; 
    
    wire        clk_gpio;
    wire        pwrite; 
    wire [31:0] paddr; 
    wire [31:0] pwdata; 
    wire        psel_gpio; 
    wire        pready_gpio; 
    wire [31:0] prdata_gpio; 
    
    wire sck_i_int; 
    wire sck_o_int; 
    wire sck_oe_int; 
    
    wire ss_i_int; 
    wire ss_o_int; 
    wire ss_oe_int; 
    
    //SPI/GPIO -- Interrupt Arbiter 
    wire int_gpio_req; 
    wire int_spi_req; 
    wire ack_gpio; 
    wire ack_spi; 
    wire riscv_ready; 

    // Internal-only signals not observed at top level
    wire        SrcA_sim, SrcB_sim, Next_PC_Alu_out_sim; // placeholder types overridden below
    
    instr_mem imem ( 
        .reset_im (reset_im),
        .clk (clk),
        .addr (imem_addr),
        .instr (imem_instr),
        .wr_en_im (wr_en_im),
        .im_wr_addr (im_wr_addr),
        .im_wr_inst (im_wr_inst)
        );
    
    // internal wires for riscv_top ports no longer exposed at soc_top
    wire [31:0] SrcA_sim_i, SrcB_sim_i, Next_PC_Alu_out_sim_i;
    wire [4:0]  AluControl_sim_i;

    riscv_top u_riscv_top ( 
        .clk            (clk), 
        .reset          (rst), 
    
        // IRQ 
        .spi_irq        (1'b0), 
        .gpio_irq       (1'b0), 
        .trap_busy      (riscv_busy), 
    
        // Instruction Memory 
        .PC_out         (imem_addr), 
        .instr_in       (imem_instr), 
        .ins_ena        (imem_ena), 
    
        // Controller 
        .i_decode(i_decode), 
        .i_ex(i_ex), 
        .i_mem(i_mem), 
        .i_wb(i_wb), 
    
        // Register File (RF) 
        .RegWrEn_sim(RegWrEn_sim), 
        .RD1_sim(RD1_sim), 
        .RD2_sim(RD2_sim), 
        .RD3_sim(RD3_sim), 
        .RD4_sim(RD4_sim), 
        .WD5_sim(WD5_sim), 
        .A1_sim(A1_sim), 
        .A2_sim(A2_sim), 
        .A3_sim(A3_sim), 
        .A4_sim(A4_sim), 
        .A5_sim(A5_sim), 
    
        // ALU 
        .SrcA_sim(SrcA_sim_i), 
        .SrcB_sim(SrcB_sim_i), 
        .AluOp_sim(AluOp_sim), 
        .Next_PC_Alu_out_sim(Next_PC_Alu_out_sim_i), 
        .AluControl_sim(AluControl_sim_i), 
        .AluResultSrc(AluResultSrc), 
    
        // Write Back 
        .wb_data_sim(wb_data_sim), 
    
        // Multiplier 
        .start_mul_sim(start_mul_sim), 
        .mul_done_sim(mul_done_sim), 
        .clk_md(clk_md), 
        
        // Divider
        .start_div_sim(start_div_sim),
        .div_done_sim(div_done_sim),
        
        // FFT 
        .done_fft_sim(done_fft_sim), 
        .start_fft_sim(start_fft_sim), 
        .clk_fft(clk_fft), 
        
        .clk_fp(clk_fp),
        .data_wr_en(riscv_we), 
        .data_addr(riscv_addr), 
        .data_out(riscv_wdata), 
        .data_in(riscv_rdata), 
        .trans_done(riscv_trans_done) 
        ); 
    
    

    address_decoder u_address_decoder ( 
        .riscv_we               (riscv_we), 
        .riscv_addr             (riscv_addr), 
        .riscv_wdata            (riscv_wdata), 
        .riscv_rdata            (riscv_rdata), 
        .riscv_trans_done  (riscv_trans_done), 
    
        .apb_we                 (apb_we), 
        .apb_addr               (apb_addr), 
        .apb_wdata              (apb_wdata), 
        .apb_rdata              (apb_rdata), 
        .apb_trans_done    (apb_trans_done), 
    
        .mem_we                 (mem_we), 
        .mem_addr               (mem_addr), 
        .mem_wdata              (mem_wdata), 
        .mem_rdata              (mem_rdata), 
        .mem_ena                (mem_ena) 
        ); 
    
    
    
    data_mem u_data_mem ( 
        .clk       (clk), 
        .rst       (rst), 
        .mem_we    (mem_we), 
        .mem_wdata (mem_wdata), 
        .mem_addr  (mem_addr), 
        .mem_rdata (mem_rdata), 
        .mem_ena   (mem_ena) 
        ); 
    
    
    apb u_apb ( 
        .clk                (clk), 
        .rst                (rst), 
        .we                 (apb_we), 
        .addr               (apb_addr), 
        .wdata              (apb_wdata), 
        .rdata              (apb_rdata), 
        .trans_done    (apb_trans_done), 
    
        .pready_gpio        (pready_gpio), 
        .prdata_gpio        (prdata_gpio), 
        .psel_gpio          (psel_gpio), 
    
        .pready_spi         (pready_spi), 
        .prdata_spi         (prdata_spi), 
        .psel_spi           (psel_spi), 
    
        .penable            (penable), 
        .pwrite             (pwrite), 
        .paddr              (paddr), 
        .pwdata             (pwdata) 
        ); 
        
    // ------------------------------------------------------------------
    // Core-domain reset synchroniser (shared by all core-side CDC logic)
    // ------------------------------------------------------------------
    wire rst_core_n;
    reset_sync u_rst_sync_core_soc (
        .clk        (clk),
        .arst_n     (~rst),
        .rst_sync_n (rst_core_n)
    );

    derive_clk_gpio u_derive_clk_gpio (
        .clk      (clk),
        .reset    (rst),
        .clk_gpio (clk_gpio)
        );

    // ==================================================================
    // CDC: APB (core clk) <-> GPIO (clk_gpio)
    // ==================================================================

    wire rst_gpio_n;
    reset_sync u_rst_sync_gpio (
        .clk        (clk_gpio),
        .arst_n     (~rst),
        .rst_sync_n (rst_gpio_n)
    );

    wire        psel_gpio_p;
    wire        penable_gpio_p;
    wire        pwrite_gpio_p;
    wire [31:0] paddr_gpio_p;
    wire [31:0] pwdata_gpio_p;
    wire [31:0] prdata_gpio_p;
    wire        pready_gpio_p;

    apb_cdc_bridge u_apb_cdc_gpio (
        .clk_core     (clk),
        .rst_core_n   (rst_core_n),
        .psel_c       (psel_gpio),
        .penable_c    (penable),
        .pwrite_c     (pwrite),
        .paddr_c      (paddr),
        .pwdata_c     (pwdata),
        .prdata_c     (prdata_gpio),
        .pready_c     (pready_gpio),

        .clk_periph   (clk_gpio),
        .rst_periph_n (rst_gpio_n),
        .psel_p       (psel_gpio_p),
        .penable_p    (penable_gpio_p),
        .pwrite_p     (pwrite_gpio_p),
        .paddr_p      (paddr_gpio_p),
        .pwdata_p     (pwdata_gpio_p),
        .prdata_p     (prdata_gpio_p),
        .pready_p     (pready_gpio_p)
    );

    gpio u_gpio ( 
        .PCLK           (clk_gpio), 
        .PRESETn        (~rst_gpio_n),   
        .PSEL           (psel_gpio_p), 
        .PENABLE        (penable_gpio_p), 
        .PWRITE         (pwrite_gpio_p), 
        .PADDR          (paddr_gpio_p), 
        .PWDATA         (pwdata_gpio_p), 
    
        .PRDATA         (prdata_gpio_p), 
        .PREADY         (pready_gpio_p), 
    
        .riscv_ready    (riscv_ready), 
        .irq_ack        (ack_gpio), 
        .gpio_out       (gpio_out), 
        .gpio_in        (gpio_in), 
        .gpio_irq       (int_gpio_req)
        ); 
        
    derive_clk_spi u_derive_clk_spi (
        .clk_spi (clk_spi),
        .reset      (rst),
        .clk_spi_div    (clk_spi_div)
        );      

    // ==================================================================
    // CDC: APB (core clk) <-> SPI (clk_spi_div)
    // ==================================================================

    wire rst_spi_n;
    reset_sync u_rst_sync_spi (
        .clk        (clk_spi_div),
        .arst_n     (~rst),
        .rst_sync_n (rst_spi_n)
    );

    wire        psel_spi_p;
    wire        penable_spi_p;
    wire        pwrite_spi_p;
    wire [31:0] paddr_spi_p;
    wire [31:0] pwdata_spi_p;
    wire [31:0] prdata_spi_p;
    wire        pready_spi_p;

    apb_cdc_bridge u_apb_cdc_spi (
        .clk_core     (clk),
        .rst_core_n   (rst_core_n),
        .psel_c       (psel_spi),
        .penable_c    (penable),
        .pwrite_c     (pwrite),
        .paddr_c      (paddr),
        .pwdata_c     (pwdata),
        .prdata_c     (prdata_spi),
        .pready_c     (pready_spi),

        .clk_periph   (clk_spi_div),
        .rst_periph_n (rst_spi_n),
        .psel_p       (psel_spi_p),
        .penable_p    (penable_spi_p),
        .pwrite_p     (pwrite_spi_p),
        .paddr_p      (paddr_spi_p),
        .pwdata_p     (pwdata_spi_p),
        .prdata_p     (prdata_spi_p),
        .pready_p     (pready_spi_p)
    );

    spi u_spi ( 
        .MOSI           (spi_mosi), 
        .MISO           (spi_miso), 
        
        .SCK_i          (sck_i_int), 
        .SCK_o          (sck_o_int), 
        .SCK_oe         (sck_oe_int), 
        
        .SS_i           (ss_i_int), 
        .SS_o           (ss_o_int), 
        .SS_oe          (ss_oe_int), 
    
        .system_clock   (clk_spi_div), 
        .reset          (~rst_spi_n), 
        .SPI_select     (psel_spi_p), 
    
        .address        (paddr_spi_p), 
        .data           (pwdata_spi_p), 
        .rdata          (prdata_spi_p), 
        .read_write     (pwrite_spi_p), 
        .pready         (pready_spi_p), 
        .penable        (penable_spi_p), 
    
        .RISCV_ready    (riscv_ready), 
        .ack_spi        (ack_spi), 
        .SPI_interrupt  (int_spi_req) 
        ); 
    
    
    interrupt_arbiter u_interrupt_arbiter ( 
        .clk            (clk), 
        .rst            (rst), 
    
        .int_gpio_req   (int_gpio_req), 
        .int_spi_req    (int_spi_req), 
        .ack_spi        (ack_spi), 
        .ack_gpio       (ack_gpio), 
        .riscv_ready    (riscv_ready), 
    
        .riscv_busy     (riscv_busy), 
        .irq_spi_riscv  (irq_spi_riscv), 
        .irq_gpio_riscv (irq_gpio_riscv) 
        ); 

    assign dbg_mosi   = spi_mosi; 
    assign dbg_miso   = spi_miso; 
 
    assign apb_trans_done_sim = apb_trans_done; 
    assign pready_gpio_sim = pready_gpio; 
    assign prdata_gpio_sim = prdata_gpio; 
    assign psel_gpio_sim   = psel_gpio; 
 
    assign pready_spi_sim  = pready_spi; 
    assign prdata_spi_sim  = prdata_spi; 
    assign psel_spi_sim    = psel_spi; 
 
    assign penable_sim = penable; 
    assign pwrite_sim  = pwrite; 
    assign paddr_sim   = paddr; 
    assign pwdata_sim  = pwdata; 
 
endmodule