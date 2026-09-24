/*  GPIO module :
    It supports 4 input and 4 output ports. Configurations of each port can be modified individually as required.
    An interrupt is generated upon receiving data in any input port, which is sent to the controller via APB
*/

`timescale 1ns / 1ps

module gpio(

    /* APB Interface */
    input  wire        PCLK,
    input  wire        PRESETn,
    input  wire        PSEL,
    input  wire        PENABLE,
    input  wire        PWRITE,
    input  wire [31:0] PADDR,
    input  wire [31:0] PWDATA,

    output wire [31:0] PRDATA,
    output wire        PREADY,

    /* GPIO */
    input  wire        riscv_ready,
    input  wire        irq_ack,
    output wire [3:0]  gpio_out,
    input  wire [3:0]  gpio_in,
    output wire        gpio_irq
    );

    localparam DATA_OUT_ADDR   = 32'h20000000;
    localparam OUT_SET_ADDR    = 32'h20000004;
    localparam OUT_CLR_ADDR    = 32'h20000008;
    localparam DATA_IN_ADDR    = 32'h20000010;
    localparam CLR_RISE_ADDR   = 32'h20000014;
    localparam SET_RISE_ADDR   = 32'h20000018;
    localparam SET_FALL_ADDR   = 32'h2000001C;
    localparam CLR_FALL_ADDR   = 32'h20000020;
    localparam INT_ENABLE_ADDR = 32'h20000024;
    localparam INT_STATUS_ADDR = 32'h20000028;
    localparam INT_CLR_ADDR    = 32'h2000002C;
    localparam OUT_TOGGLE_ADDR = 32'h20000030;

    reg [31:0] rise_en_q;
    reg [31:0] rise_en_next_r;
    reg [31:0] fall_en_q;
    reg [31:0] fall_en_next_r;

    reg [31:0] int_enable_q;
    reg [31:0] sync_ff1;
    reg [31:0] sync_ff2;
    wire [31:0] gpio_in_ext;
    reg gpio_irq_q;
    reg [31:0] prev_sync_q;
    reg [31:0] int_status_q;
    reg [31:0] int_status_next_r;
    reg [2:0] irq_delay_q;
    reg [31:0] data_out_q;
    reg [31:0] data_out_next_r;
    reg setup_d;
    reg busy;
    wire write_en_w = PSEL & PENABLE &  PWRITE;
    wire read_en_w  = PSEL & PENABLE & ~PWRITE;

    wire data_out_wr_w   = write_en_w && (PADDR == DATA_OUT_ADDR);
    wire out_set_wr_w    = write_en_w && (PADDR == OUT_SET_ADDR);
    wire out_clr_wr_w    = write_en_w && (PADDR == OUT_CLR_ADDR);
    wire out_toggle_wr_w = write_en_w && (PADDR == OUT_TOGGLE_ADDR);
    wire set_rise_wr_w   = write_en_w && (PADDR == SET_RISE_ADDR);
    wire clr_rise_wr_w   = write_en_w && (PADDR == CLR_RISE_ADDR);
    wire set_fall_wr_w   = write_en_w && (PADDR == SET_FALL_ADDR);
    wire clr_fall_wr_w   = write_en_w && (PADDR == CLR_FALL_ADDR);
    wire int_enable_wr_w = write_en_w && (PADDR == INT_ENABLE_ADDR);
    wire int_clr_wr_w    = write_en_w && (PADDR == INT_CLR_ADDR);

    wire [31:0] raw_rise_w  =  sync_ff2 & ~prev_sync_q;
    wire [31:0] raw_fall_w  = ~sync_ff2 &  prev_sync_q;

    wire [31:0] rise_event_w = raw_rise_w & rise_en_q;
    wire [31:0] fall_event_w = raw_fall_w & fall_en_q;

    wire [31:0] interrupt_event_w = (rise_event_w | fall_event_w) & int_enable_q;



    wire irq_pending_w = |(int_status_q & int_enable_q);


    wire auto_clr_w = irq_delay_q[2];
    assign PREADY = (setup_d | (PSEL & PENABLE)) & ~busy;

    assign gpio_in_ext = {28'b0, gpio_in};

    assign gpio_out = data_out_q[3:0];

    //assign gpio_irq = gpio_irq_q;
    assign gpio_irq = 1'b0;

    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            setup_d <= 1'b0;
        else
            setup_d <= PSEL & ~PENABLE;
    end

    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            busy <= 1'b1;
        else
            busy <= 1'b0;
    end





    always @(*) begin
        data_out_next_r = data_out_q;

        if      (data_out_wr_w)   data_out_next_r = PWDATA;
        else if (out_set_wr_w)    data_out_next_r = data_out_q |  PWDATA;
        else if (out_clr_wr_w)    data_out_next_r = data_out_q & ~PWDATA;
        else if (out_toggle_wr_w) data_out_next_r = data_out_q ^  PWDATA;
    end

    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            data_out_q <= 32'b0;
        else
            data_out_q <= data_out_next_r;
    end



    always @(*) begin
        rise_en_next_r = rise_en_q;

        if      (set_rise_wr_w) rise_en_next_r = rise_en_q |  PWDATA;
        else if (clr_rise_wr_w) rise_en_next_r = rise_en_q & ~PWDATA;
    end

    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            rise_en_q <= 32'h0000000F;
        else
            rise_en_q <= rise_en_next_r;
    end




    always @(*) begin
        fall_en_next_r = fall_en_q;

        if      (set_fall_wr_w) fall_en_next_r = fall_en_q |  PWDATA;
        else if (clr_fall_wr_w) fall_en_next_r = fall_en_q & ~PWDATA;
    end

    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            fall_en_q <= 32'b0;
        else
            fall_en_q <= fall_en_next_r;
    end



    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            int_enable_q <= 32'h0000000F;
        else if (int_enable_wr_w)
            int_enable_q <= PWDATA;
    end



    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn) begin
            sync_ff1 <= 32'b0;
            sync_ff2 <= 32'b0;
        end
        else begin
            sync_ff1 <= gpio_in_ext;
            sync_ff2 <= sync_ff1;
        end
    end




    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            prev_sync_q <= 32'b0;
        else
            prev_sync_q <= sync_ff2;
    end



    always @(*) begin
        int_status_next_r = int_status_q;

        if (int_clr_wr_w)
            int_status_next_r = int_status_next_r & ~PWDATA;

        if (auto_clr_w)
            int_status_next_r = 32'b0;

        int_status_next_r = int_status_next_r | interrupt_event_w;
    end


    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            int_status_q <= 32'b0;
        else
            int_status_q <= int_status_next_r;
    end





    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            gpio_irq_q <= 1'b0;
        else
            gpio_irq_q <= riscv_ready & irq_pending_w;
    end





    always @(posedge PCLK or posedge PRESETn) begin
        if (PRESETn)
            irq_delay_q <= 3'b0;
        else if ((riscv_ready & irq_pending_w) && (irq_delay_q == 3'b0))
            irq_delay_q <= 3'b001;
        else
            irq_delay_q <= {irq_delay_q[1:0], 1'b0};
    end



    assign PRDATA = (read_en_w) ? (
        (PADDR == DATA_OUT_ADDR)   ? data_out_q  :
        (PADDR == OUT_SET_ADDR)    ? data_out_q  :
        (PADDR == OUT_CLR_ADDR)    ? data_out_q  :
        (PADDR == OUT_TOGGLE_ADDR) ? data_out_q  :
        (PADDR == DATA_IN_ADDR)    ? sync_ff2    :
        (PADDR == SET_RISE_ADDR)   ? rise_en_q   :
        (PADDR == CLR_RISE_ADDR)   ? rise_en_q   :
        (PADDR == SET_FALL_ADDR)   ? fall_en_q   :
        (PADDR == CLR_FALL_ADDR)   ? fall_en_q   :
        (PADDR == INT_ENABLE_ADDR) ? int_enable_q:
        (PADDR == INT_STATUS_ADDR) ? int_status_q:
                                    32'b0
    ) : 32'b0;


endmodule
