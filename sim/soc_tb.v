`timescale 1ns/1ps

module soc_top_tb;

    // Clocks and reset
    reg clk;
    reg clk_md;
    reg clk_fft;
    reg clk_fp;
    reg clk_spi;
    reg rst;

    // Instruction memory load interface
    reg [31:0] im_wr_addr;
    reg [31:0] im_wr_inst;
    reg        wr_en_im;
    reg        reset_im;

    // GPIO
    reg  [3:0] gpio_in;
    wire [3:0] gpio_out;

    // SPI
    wire spi_mosi;
    wire spi_sclk;
    wire spi_ss;
    wire spi_miso;
    assign spi_miso = spi_mosi;   // loopback self-test

    // -------------------------------------------------
    // Simulation outputs
    // -------------------------------------------------

    // APB
    wire        apb_trans_done_sim;
    wire        pready_gpio_sim;
    wire        psel_gpio_sim;
    wire [31:0] prdata_gpio_sim;

    wire        pready_spi_sim;
    wire        psel_spi_sim;
    wire [31:0] prdata_spi_sim;

    wire        penable_sim;
    wire        pwrite_sim;
    wire [31:0] paddr_sim;
    wire [31:0] pwdata_sim;

    // Pipeline instructions
    wire [31:0] i_decode;
    wire [31:0] i_ex;
    wire [31:0] i_mem;
    wire [31:0] i_wb;

    // Register File
    wire        RegWrEn_sim;
    wire [31:0] RD1_sim;
    wire [31:0] RD2_sim;
    wire [31:0] RD3_sim;
    wire [31:0] RD4_sim;
    wire [31:0] WD5_sim;

    wire [4:0] A1_sim;
    wire [4:0] A2_sim;
    wire [4:0] A3_sim;
    wire [4:0] A4_sim;
    wire [4:0] A5_sim;

    // ALU
    wire [31:0] AluOp_sim;
    wire [2:0]  AluResultSrc;

    // Writeback
    wire [31:0] wb_data_sim;

    // Multiplier
    wire start_mul_sim;
    wire mul_done_sim;

    // Divider
    wire start_div_sim;
    wire div_done_sim;

    // FFT
    wire done_fft_sim;
    wire start_fft_sim;

    // SPI debug
    wire dbg_mosi;
    wire dbg_miso;


    // -------------------------------------------------
    // DUT
    // -------------------------------------------------

    soc_top dut (

        // Clocks
        .clk_md   (clk_md),
        .clk_fp   (clk_fp),
        .clk_fft  (clk_fft),
        .clk_spi  (clk_spi),
        .clk      (clk),
        .rst      (rst),

        // Instruction memory
        .im_wr_addr (im_wr_addr),
        .im_wr_inst (im_wr_inst),
        .wr_en_im   (wr_en_im),
        .reset_im   (reset_im),

        // GPIO
        .gpio_in  (gpio_in),
        .gpio_out (gpio_out),

        // SPI
        .spi_mosi (spi_mosi),
        .spi_miso (spi_miso),
        .spi_sclk (spi_sclk),
        .spi_ss   (spi_ss),

        // APB simulation
        .apb_trans_done_sim (apb_trans_done_sim),
        .pready_gpio_sim    (pready_gpio_sim),
        .prdata_gpio_sim    (prdata_gpio_sim),
        .psel_gpio_sim      (psel_gpio_sim),

        .pready_spi_sim     (pready_spi_sim),
        .prdata_spi_sim     (prdata_spi_sim),
        .psel_spi_sim       (psel_spi_sim),

        .penable_sim        (penable_sim),
        .pwrite_sim         (pwrite_sim),
        .paddr_sim          (paddr_sim),
        .pwdata_sim         (pwdata_sim),

        // Pipeline simulation
        .i_decode (i_decode),
        .i_ex     (i_ex),
        .i_mem    (i_mem),
        .i_wb     (i_wb),

        // Register file simulation
        .RegWrEn_sim (RegWrEn_sim),
        .RD1_sim     (RD1_sim),
        .RD2_sim     (RD2_sim),
        .RD3_sim     (RD3_sim),
        .RD4_sim     (RD4_sim),
        .WD5_sim     (WD5_sim),

        .A1_sim (A1_sim),
        .A2_sim (A2_sim),
        .A3_sim (A3_sim),
        .A4_sim (A4_sim),
        .A5_sim (A5_sim),

        // ALU simulation
        .AluOp_sim    (AluOp_sim),
        .AluResultSrc (AluResultSrc),

        // Writeback
        .wb_data_sim (wb_data_sim),

        // Multiplier simulation
        .start_mul_sim (start_mul_sim),
        .mul_done_sim  (mul_done_sim),

        // Divider simulation
        .start_div_sim (start_div_sim),
        .div_done_sim  (div_done_sim),

        // FFT simulation
        .done_fft_sim  (done_fft_sim),
        .start_fft_sim (start_fft_sim),

        // SPI debug
        .dbg_mosi (dbg_mosi),
        .dbg_miso (dbg_miso)
    );


    // -------------------------------------------------
    // Clock generation
    // -------------------------------------------------

    initial clk = 0;
    always #10 clk = ~clk;

    initial clk_md = 0;
    always #3 clk_md = ~clk_md;

    initial clk_fft = 0;
    always #3 clk_fft = ~clk_fft;

    initial clk_fp = 0;
    always #3 clk_fp = ~clk_fp;

    initial clk_spi = 0;
    always #2 clk_spi = ~clk_spi;


    // -------------------------------------------------
    // Stimulus
    // -------------------------------------------------

    initial begin

        rst        = 1;
        reset_im   = 1;
        wr_en_im   = 0;
        im_wr_addr = 32'd0;
        im_wr_inst = 32'd0;

        gpio_in    = 4'b0000;

        #50;

        rst      = 0;
        reset_im = 0;

        #100;

        #200000;

        $finish;

    end

    initial begin
    $dumpfile("waveform.vcd");
    $dumpvars(0, soc_top_tb);   // 0 = dump all levels, replace with your actual top TB module name
end

endmodule
