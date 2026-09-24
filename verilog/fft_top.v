/*  8-point FFT Accelerator :
    It accepts 128 bits of input data (8 complex samples x 16 bits).
    Once the buffer is full, all 8 complex samples are fed in parallel into the butterfly network.
    Upon completion, the transformed outputs are latched into a 128-bit internal output buffer.

    CDC UPDATE: the fft_wb readback mux has been moved OUT of this module and
    into riscv_top (core clock domain). This module now exports the full
    128-bit result as y_all, which crosses to the core via handshake_bridge.
    fft_wb never crosses a clock boundary now - it selects a slice of an
    already-synchronised core-domain register.

    y_all packing: {y0,y1,y2,y3,y4,y5,y6,y7}, y0 in the MSBs.
      fft_wb 2'b00 -> y_all[127:96]
      fft_wb 2'b01 -> y_all[95:64]
      fft_wb 2'b10 -> y_all[63:32]
      fft_wb 2'b11 -> y_all[31:0]

    Note: clk_fft_main is a divide-by-2 of clk_fft_core (see clk_div_fft), so
    the fft_top FSM and the fft8 core are synchronous to each other. The
    compute_start / compute_done handshake between them needs no synchroniser.
*/

module fft_top(

    input clk_fft_main,
    input clk_fft_core,
    input reset,

    input start,

    input  [31:0] rs1_data,
    input  [31:0] rs2_data,
    input  [31:0] rs3_data,
    input  [31:0] rs4_data,

    output [127:0] y_all,
    output reg busy,
    output reg done,
    output reg compute_start
    );


    // FSM STATES
    localparam IDLE    = 2'd0;
    localparam LOAD    = 2'd1;
    localparam COMPUTE = 2'd2;
    localparam DONE_S  = 2'd3;

    reg [1:0] state;


    // FFT INPUT REGISTERS
    reg [15:0] a0,a1,a2,a3,a4,a5,a6,a7;


    // FFT OUTPUT WIRES
    wire [15:0] y0,y1,y2,y3,y4,y5,y6,y7;
    wire compute_done;

    assign y_all = {y0,y1,y2,y3,y4,y5,y6,y7};


    // FFT
    fft8 fft_core(

        .clk_fft_core(clk_fft_core),
        .reset(reset),
        .compute_done(compute_done),
        .compute_start(compute_start),

        .a0(a0),
        .a1(a1),
        .a2(a2),
        .a3(a3),
        .a4(a4),
        .a5(a5),
        .a6(a6),
        .a7(a7),

        .y0(y0),
        .y1(y1),
        .y2(y2),
        .y3(y3),
        .y4(y4),
        .y5(y5),
        .y6(y6),
        .y7(y7)
    );


    // FSM
    always @(posedge clk_fft_main or posedge reset) begin

        if(reset) begin

            state <= IDLE;
            busy  <= 0;
            done  <= 0;
            compute_start <= 1'b0;

        end

        else begin

            case(state)

            IDLE: begin
                done <= 0;
                compute_start <= 1'b0;
                if(start) begin
                    busy <= 1;
                    state <= LOAD;
                end
            end


            LOAD: begin

                a0 <= rs1_data[31:16];
                a1 <= rs1_data[15:0];

                a2 <= rs2_data[31:16];
                a3 <= rs2_data[15:0];

                a4 <= rs3_data[31:16];
                a5 <= rs3_data[15:0];

                a6 <= rs4_data[31:16];
                a7 <= rs4_data[15:0];

                state <= COMPUTE;
                compute_start <= 1'b1;
            end


            COMPUTE: begin
                compute_start <= 1'b0;
                if(compute_done)
                    state <= DONE_S;
            end


            DONE_S: begin

                busy <= 0;
                done <= 1;

                state <= IDLE;

            end

            default: state <= IDLE;

            endcase

        end

    end

endmodule


///////////////////////////////////Computing Module////////////////////

module fft8(
    input clk_fft_core, reset, compute_start,
    input signed [15:0] a0,a1,a2,a3,a4,a5,a6,a7,
    output reg signed [15:0] y0,y1,y2,y3,y4,y5,y6,y7,
    output reg compute_done
    );

    //Split real and imaginary

    wire signed [7:0] a0_r = a0[15:8];
    wire signed [7:0] a0_i = a0[7:0];

    wire signed [7:0] a1_r = a1[15:8];
    wire signed [7:0] a1_i = a1[7:0];

    wire signed [7:0] a2_r = a2[15:8];
    wire signed [7:0] a2_i = a2[7:0];

    wire signed [7:0] a3_r = a3[15:8];
    wire signed [7:0] a3_i = a3[7:0];

    wire signed [7:0] a4_r = a4[15:8];
    wire signed [7:0] a4_i = a4[7:0];

    wire signed [7:0] a5_r = a5[15:8];
    wire signed [7:0] a5_i = a5[7:0];

    wire signed [7:0] a6_r = a6[15:8];
    wire signed [7:0] a6_i = a6[7:0];

    wire signed [7:0] a7_r = a7[15:8];
    wire signed [7:0] a7_i = a7[7:0];

    // Stage 3 Twiddle Factors (Q4.4)

    parameter signed [7:0] s3_W1_r = 8'h0B; // 0.707
    parameter signed [7:0] s3_W1_i = 8'hF5; // -0.707

    parameter signed [7:0] s3_W2_r = 8'h00; // 0
    parameter signed [7:0] s3_W2_i = 8'hF0; // -1

    parameter signed [7:0] s3_W3_r = 8'hF5; // -0.707
    parameter signed [7:0] s3_W3_i = 8'hF5; // -0.707

    reg [2:0] stage;

    // stage1
    reg signed [7:0] t1_0_r,t1_0_i,t1_1_r,t1_1_i,t1_2_r,t1_2_i,t1_3_r,t1_3_i;
    reg signed [7:0] t1_4_r,t1_4_i,t1_5_r,t1_5_i,t1_6_r,t1_6_i,t1_7_r,t1_7_i;

    // stage2
    reg signed [7:0] p1_2_r,p1_2_i,p1_3_r,p1_3_i,p1_6_r,p1_6_i,p1_7_r,p1_7_i;
    reg signed [7:0] t2_0_r = 8'd0, t2_0_i = 8'd0;
    reg signed [7:0] t2_1_r = 8'd0, t2_1_i = 8'd0;
    reg signed [7:0] t2_2_r = 8'd0, t2_2_i = 8'd0;
    reg signed [7:0] t2_3_r = 8'd0, t2_3_i = 8'd0;

    reg signed [7:0] t2_4_r = 8'd0, t2_4_i = 8'd0;
    reg signed [7:0] t2_5_r = 8'd0, t2_5_i = 8'd0;
    reg signed [7:0] t2_6_r = 8'd0, t2_6_i = 8'd0;
    reg signed [7:0] t2_7_r = 8'd0, t2_7_i = 8'd0;

    // stage3
    reg signed [7:0] p2_4_r,p2_4_i,p2_5_r,p2_5_i,p2_6_r,p2_6_i,p2_7_r,p2_7_i;
    reg signed [7:0] t3_0_r,t3_0_i,t3_1_r,t3_1_i,t3_2_r,t3_2_i,t3_3_r,t3_3_i;
    reg signed [7:0] t3_4_r,t3_4_i,t3_5_r,t3_5_i,t3_6_r,t3_6_i,t3_7_r,t3_7_i;

    //multiplication

    wire signed [15:0] mul1_r = (t2_5_r*s3_W1_r) - (t2_5_i*s3_W1_i);
    wire signed [15:0] mul1_i = (t2_5_r*s3_W1_i) + (t2_5_i*s3_W1_r);

    wire signed [15:0] mul2_r = (t2_6_r*s3_W2_r) - (t2_6_i*s3_W2_i);
    wire signed [15:0] mul2_i = (t2_6_r*s3_W2_i) + (t2_6_i*s3_W2_r);

    wire signed [15:0] mul3_r = (t2_7_r*s3_W3_r) - (t2_7_i*s3_W3_i);
    wire signed [15:0] mul3_i = (t2_7_r*s3_W3_i) + (t2_7_i*s3_W3_r);

    always @(posedge clk_fft_core) begin
        if (reset) begin
            stage <= 3'd0;
            y0 <= 16'd0;
            y1 <= 16'd0;
            y2 <= 16'd0;
            y3 <= 16'd0;
            y4 <= 16'd0;
            y5 <= 16'd0;
            y6 <= 16'd0;
            y7 <= 16'd0;
            compute_done <= 1'b0;
        end
        else begin
            case(stage)

            0: begin
            //Stage1 add/sub
            if(compute_start) begin
                t1_0_r <= a0_r + a4_r;
                t1_0_i <= a0_i + a4_i;

                t1_1_r <= a0_r - a4_r;
                t1_1_i <= a0_i - a4_i;

                t1_2_r <= a2_r + a6_r;
                t1_2_i <= a2_i + a6_i;

                t1_3_r <= a2_r - a6_r;
                t1_3_i <= a2_i - a6_i;

                t1_4_r <= a1_r + a5_r;
                t1_4_i <= a1_i + a5_i;

                t1_5_r <= a1_r - a5_r;
                t1_5_i <= a1_i - a5_i;

                t1_6_r <= a3_r + a7_r;
                t1_6_i <= a3_i + a7_i;

                t1_7_r <= a3_r - a7_r;
                t1_7_i <= a3_i - a7_i;

                stage <= 1;
                compute_done <= 1'b0;
                end
                end

            // Stage2 multiply

            1: begin

                p1_2_r <= t1_2_r;
                p1_2_i <= t1_2_i;

                p1_3_r <= t1_3_r;
                p1_3_i <= t1_3_i;

                p1_6_r <= t1_6_r;
                p1_6_i <= t1_6_i;

                p1_7_r <= t1_7_r;
                p1_7_i <= t1_7_i;

                stage <= 2;

                end


            // Stage2 add/sub

            2: begin

                t2_0_r <= t1_0_r + p1_2_r;
                t2_0_i <= t1_0_i + p1_2_i;

                t2_1_r <= t1_1_r + p1_3_r;
                t2_1_i <= t1_1_i + p1_3_i;

                t2_2_r <= t1_0_r - p1_2_r;
                t2_2_i <= t1_0_i - p1_2_i;

                t2_3_r <= t1_1_r - p1_3_r;
                t2_3_i <= t1_1_i - p1_3_i;

                t2_4_r <= t1_4_r + p1_6_r;
                t2_4_i <= t1_4_i + p1_6_i;

                t2_5_r <= t1_5_r + p1_7_r;
                t2_5_i <= t1_5_i + p1_7_i;

                t2_6_r <= t1_4_r - p1_6_r;
                t2_6_i <= t1_4_i - p1_6_i;

                t2_7_r <= t1_5_r - p1_7_r;
                t2_7_i <= t1_5_i - p1_7_i;

                stage <= 3;

                end

            // Stage3 multiply

            3: begin

                p2_4_r <= t2_4_r;
                p2_4_i <= t2_4_i;

                p2_5_r <= mul1_r >>> 4;
                p2_5_i <= mul1_i >>> 4;

                p2_6_r <= mul2_r >>> 4;
                p2_6_i <= mul2_i >>> 4;

                p2_7_r <= mul3_r >>> 4;
                p2_7_i <= mul3_i >>> 4;

                stage <= 4;

                end


            // Stage3 add/sub

            4: begin

                t3_0_r <= t2_0_r + p2_4_r;
                t3_0_i <= t2_0_i + p2_4_i;

                t3_1_r <= t2_1_r + p2_5_r;
                t3_1_i <= t2_1_i + p2_5_i;

                t3_2_r <= t2_2_r + p2_6_r;
                t3_2_i <= t2_2_i + p2_6_i;

                t3_3_r <= t2_3_r + p2_7_r;
                t3_3_i <= t2_3_i + p2_7_i;

                t3_4_r <= t2_0_r - p2_4_r;
                t3_4_i <= t2_0_i - p2_4_i;

                t3_5_r <= t2_1_r - p2_5_r;
                t3_5_i <= t2_1_i - p2_5_i;

                t3_6_r <= t2_2_r - p2_6_r;
                t3_6_i <= t2_2_i - p2_6_i;

                t3_7_r <= t2_3_r - p2_7_r;
                t3_7_i <= t2_3_i - p2_7_i;


            stage <= 5;

                end
            5: begin

                //outputs
                y0 <= {t3_0_r,t3_0_i};
                y1 <= {t3_1_r,t3_1_i};
                y2 <= {t3_2_r,t3_2_i};
                y3 <= {t3_3_r,t3_3_i};
                y4 <= {t3_4_r,t3_4_i};
                y5 <= {t3_5_r,t3_5_i};
                y6 <= {t3_6_r,t3_6_i};
                y7 <= {t3_7_r,t3_7_i};

                stage <= 0;
                compute_done <= 1'b1;
                end

            default: stage <= 0;

            endcase

        end
    end

endmodule