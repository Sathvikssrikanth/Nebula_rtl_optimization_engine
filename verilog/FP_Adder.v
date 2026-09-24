// =============================================================
// Sequential IEEE-754 Single Precision (32-bit) FP Adder
// FSM-based. Alignment shift and post-normalize shift are done
// 1 bit/cycle (iterative), matching the style of the FP multiplier.
//
// Limitations (kept out to control scope, add if you need them):
//   - Subnormal inputs treated as zero (no gradual underflow)
//   - Inf/NaN operands not specially decoded
//   - No exponent overflow saturation to Inf; underflow flushes
//     toward zero rather than producing true denormals
//   - Sign-of-zero-from-cancellation not IEEE-exact (always uses
//     sign of the larger-magnitude operand)
// =============================================================

// FIX_DESCRIPTION: Registered the synchronous reset input inside FP_Adder to break the critical timing path from the external reset synchronizer.
// PIPELINE_STAGES_ADDED: 0
module FP_Adder (
    input  wire        clk,
    input  wire        rst,            // synchronous, active-high
    input  wire [31:0] A,
    input  wire [31:0] B,
    input  wire        start_FP_Add,   // pulse: inputs valid
    output reg         FP_Add_Busy,    // high while adding
    output reg  [31:0] FP_Add_result,
    output reg          FP_Add_Ready   // pulse: result valid
);

    // ---------------- FSM states ----------------
    localparam S_IDLE    = 4'd0,
               S_LOAD     = 4'd1,
               S_SPECIAL  = 4'd2,
               S_CMP      = 4'd3,
               S_ALIGN    = 4'd4,
               S_ADDSUB   = 4'd5,
               S_NORM     = 4'd6,
               S_ROUND    = 4'd7,
               S_PACK     = 4'd8,
               S_DONE     = 4'd9;

    reg [3:0] state;

    // ---------------- Latched/decoded operand fields ----------------
    reg         signA, signB;
    reg  [7:0]  expA, expB;
    reg  [22:0] fracA, fracB;
    reg         zeroA, zeroB;

    // ---------------- Ordered operands (big has larger magnitude) --
    reg         big_sign, small_sign;
    reg  [7:0]  big_exp,  small_exp;
    reg  [26:0] big_mant, small_mant;   // {implicit1, frac[22:0], G,R,S(3'b0)}

    // ---------------- Alignment ----------------
    reg  [7:0]  diff_cnt;
    reg         sticky_acc;

    // ---------------- Add/Sub & normalize ----------------
    reg         result_sign;
    reg  [7:0]  exp_r;
    reg  [27:0] sum_reg;               // extra top bit catches carry-out

    // ---------------- Round ----------------
    wire        G = sum_reg[2];
    wire        R = sum_reg[1];
    wire        Sb = sum_reg[0] | sticky_acc;
    wire [22:0] mant_frac = sum_reg[25:3];
    wire        round_up  = G & (R | Sb | mant_frac[0]);
    wire [23:0] mant_plus = {1'b0, mant_frac} + round_up;

    reg  [7:0]  exp_result;
    reg  [22:0] mant_result;

    reg rst_q;
    always @(posedge clk) begin
        rst_q <= rst;
    end

    always @(posedge clk) begin
        if (rst_q) begin
            state         <= S_IDLE;
            FP_Add_Busy   <= 1'b0;
            FP_Add_Ready  <= 1'b0;
            FP_Add_result <= 32'd0;
        end else begin

            FP_Add_Ready <= 1'b0; // default: ready is a 1-cycle pulse

            case (state)

                // -------------------------------------------------
                S_IDLE: begin
                    FP_Add_Busy <= 1'b0;
                    if (start_FP_Add) begin
                        signA <= A[31]; expA <= A[30:23]; fracA <= A[22:0];
                        signB <= B[31]; expB <= B[30:23]; fracB <= B[22:0];
                        FP_Add_Busy <= 1'b1;
                        state <= S_LOAD;
                    end
                end

                // -------------------------------------------------
                S_LOAD: begin
                    zeroA <= (expA == 8'd0) && (fracA == 23'd0);
                    zeroB <= (expB == 8'd0) && (fracB == 23'd0);
                    state <= S_SPECIAL;
                end

                // -------------------------------------------------
                S_SPECIAL: begin
                    if (zeroA && zeroB) begin
                        exp_result  <= 8'd0;  mant_result <= 23'd0;
                        result_sign <= signA & signB;
                        state <= S_PACK;
                    end else if (zeroA) begin
                        exp_result <= expB; mant_result <= fracB;
                        result_sign <= signB;
                        state <= S_PACK;
                    end else if (zeroB) begin
                        exp_result <= expA; mant_result <= fracA;
                        result_sign <= signA;
                        state <= S_PACK;
                    end else begin
                        state <= S_CMP;
                    end
                end

                // -------------------------------------------------
                // pick larger-magnitude operand, compute exponent diff
                S_CMP: begin
                    if ({expA, fracA} >= {expB, fracB}) begin
                        big_sign   <= signA; big_exp   <= expA; big_mant   <= {1'b1, fracA, 3'b0};
                        small_sign <= signB; small_exp <= expB; small_mant <= {1'b1, fracB, 3'b0};
                    end else begin
                        big_sign   <= signB; big_exp   <= expB; big_mant   <= {1'b1, fracB, 3'b0};
                        small_sign <= signA; small_exp <= expA; small_mant <= {1'b1, fracA, 3'b0};
                    end
                    diff_cnt   <= (expA >= expB) ? (expA - expB) : (expB - expA);
                    sticky_acc <= 1'b0;
                    state <= S_ALIGN;
                end

                // -------------------------------------------------
                // right-shift the smaller mantissa 1 bit/cycle, OR
                // shifted-out bits into sticky; clamp long shifts
                S_ALIGN: begin
                    if (diff_cnt > 8'd27) begin
                        sticky_acc <= sticky_acc | (|small_mant);
                        small_mant <= 27'd0;
                        diff_cnt   <= 8'd0;
                    end else if (diff_cnt > 8'd0) begin
                        sticky_acc <= sticky_acc | small_mant[0];
                        small_mant <= {1'b0, small_mant[26:1]};
                        diff_cnt   <= diff_cnt - 8'd1;
                    end else begin
                        state <= S_ADDSUB;
                    end
                end

                // -------------------------------------------------
                S_ADDSUB: begin
                    if (big_sign == small_sign)
                        sum_reg <= {1'b0, big_mant} + {1'b0, small_mant};
                    else
                        sum_reg <= {1'b0, big_mant} - {1'b0, small_mant};
                    result_sign <= big_sign;
                    exp_r <= big_exp;
                    state <= S_NORM;
                end

                // -------------------------------------------------
                // handle carry-out (shift right once) or leading
                // zeros from cancellation (shift left, 1 bit/cycle)
                S_NORM: begin
                    if (sum_reg[27]) begin
                        sticky_acc <= sticky_acc | sum_reg[0];
                        sum_reg <= sum_reg >> 1;
                        exp_r   <= exp_r + 1'b1;
                        state   <= S_ROUND;
                    end else if (!sum_reg[26] && exp_r > 8'd0) begin
                        sum_reg <= sum_reg << 1;
                        exp_r   <= exp_r - 1'b1;
                        // stays in S_NORM until normalized or exponent hits 0
                    end else begin
                        state <= S_ROUND;
                    end
                end

                // -------------------------------------------------
                // round-to-nearest-even using guard/round/sticky
                S_ROUND: begin
                    if (mant_plus[23]) begin
                        mant_result <= 23'd0;
                        exp_result  <= exp_r + 1'b1;
                    end else begin
                        mant_result <= mant_plus[22:0];
                        exp_result  <= exp_r;
                    end
                    state <= S_PACK;
                end

                // -------------------------------------------------
                S_PACK: begin
                    FP_Add_result <= {result_sign, exp_result, mant_result};
                    state <= S_DONE;
                end

                // -------------------------------------------------
                S_DONE: begin
                    FP_Add_Ready <= 1'b1;
                    FP_Add_Busy  <= 1'b0;
                    state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule 