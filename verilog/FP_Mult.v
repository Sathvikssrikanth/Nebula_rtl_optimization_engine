
    
// =============================================================
// Sequential IEEE-754 Single Precision (32-bit) FP Multiplier
// FSM-based, mantissa multiply done via 24-cycle shift-add loop
// (i.e., true multi-cycle sequential datapath, not combinational *)
//
// Limitations (kept out to control scope, add if you need them):
//   - Subnormal inputs treated as zero (no gradual underflow)
//   - Inf/NaN operands not specially decoded (will produce
//     garbage exponent/mantissa - add checks if required)
//   - No exponent overflow/underflow saturation to Inf/0
// =============================================================

module FP_Mult (
    input  wire        clk,
    input  wire        rst,            // synchronous, active-high
    input  wire [31:0] A,
    input  wire [31:0] B,
    input  wire        start_FP_Mul,   // pulse: inputs valid
    output reg         FP_Mul_Busy,    // high while multiplying
    output reg  [31:0] FP_Mul_result,
    output reg         FP_Mul_Ready    // pulse: result valid
);

    // ---------------- FSM states ----------------
    localparam S_IDLE    = 3'd0,
               S_LOAD     = 3'd1,
               S_SPECIAL  = 3'd2,
               S_MUL      = 3'd3,
               S_NORM     = 3'd4,
               S_ROUND    = 3'd5,
               S_PACK     = 3'd6,
               S_DONE     = 3'd7;

    reg [2:0] state;

    // ---------------- Latched/decoded operand fields ----------------
    reg         signA, signB, sign_r;
    reg  [7:0]  expA, expB;
    reg  [22:0] fracA, fracB;
    reg         zeroA, zeroB;

    reg  [23:0] mant_a, mant_b;   // 1.frac with implicit leading 1
    reg  [8:0]  exp_sum;          // expA + expB (unsigned, up to 510)

    // ---------------- Shift-add multiplier datapath ----------------
    reg  [24:0] acc;              // 25-bit accumulator
    reg  [23:0] mplier;           // multiplier (shifts right each cycle)
    reg  [23:0] mcand;            // multiplicand (fixed)
    reg  [4:0]  count;            // 0..23 iteration counter
    wire [24:0] acc_next = mplier[0] ? (acc + mcand) : acc;

    reg  [47:0] product;          // final 48-bit mantissa product

    // ---------------- Normalize / round ----------------
    reg  signed [9:0] exp_temp;
    reg  [22:0] mant_result;
    reg  [7:0]  exp_result;
    reg         round_bit, sticky;
    reg         round_carry;

    always @(posedge clk) begin
        if (rst) begin
            state         <= S_IDLE;
            FP_Mul_Busy   <= 1'b0;
            FP_Mul_Ready  <= 1'b0;
            FP_Mul_result <= 32'd0;
        end else begin

            FP_Mul_Ready <= 1'b0; // default: ready is a 1-cycle pulse

            case (state)

                // -------------------------------------------------
                S_IDLE: begin
                    FP_Mul_Busy <= 1'b0;
                    if (start_FP_Mul) begin
                        signA <= A[31]; expA <= A[30:23]; fracA <= A[22:0];
                        signB <= B[31]; expB <= B[30:23]; fracB <= B[22:0];
                        FP_Mul_Busy <= 1'b1;
                        state <= S_LOAD;
                    end
                end

                // -------------------------------------------------
                S_LOAD: begin
                    zeroA  <= (expA == 8'd0) && (fracA == 23'd0);
                    zeroB  <= (expB == 8'd0) && (fracB == 23'd0);
                    sign_r <= signA ^ signB;
                    mant_a <= {1'b1, fracA};
                    mant_b <= {1'b1, fracB};
                    exp_sum <= {1'b0, expA} + {1'b0, expB};
                    state <= S_SPECIAL;
                end

                // -------------------------------------------------
                S_SPECIAL: begin
                    if (zeroA || zeroB) begin
                        exp_result  <= 8'd0;
                        mant_result <= 23'd0;
                        state <= S_PACK;
                    end else begin
                        mcand  <= mant_a;
                        mplier <= mant_b;
                        acc    <= 25'd0;
                        count  <= 5'd0;
                        state  <= S_MUL;
                    end
                end

                // -------------------------------------------------
                // 24-cycle shift-add mantissa multiply (24x24 -> 48)
                S_MUL: begin
                    acc    <= acc_next >> 1;
                    mplier <= {acc_next[0], mplier[23:1]};
                    if (count == 5'd23)
                        state <= S_NORM;
                    else
                        count <= count + 1'b1;
                end

                // -------------------------------------------------
                S_NORM: begin
                    product = {acc[23:0], mplier}; // blocking for local use
                    exp_temp = $signed({2'b0, exp_sum}) - 10'sd127;

                    if (product[47]) begin
                        exp_temp    <= exp_temp + 1'sd1;
                        mant_result <= product[46:24];
                        round_bit   <= product[23];
                        sticky      <= |product[22:0];
                    end else begin
                        mant_result <= product[45:23];
                        round_bit   <= product[22];
                        sticky      <= |product[21:0];
                    end
                    state <= S_ROUND;
                end

                // -------------------------------------------------
                S_ROUND: begin
                    // round-to-nearest-even
                    if (round_bit && (sticky || mant_result[0])) begin
                        {round_carry, mant_result} <= mant_result + 1'b1;
                    end else begin
                        round_carry <= 1'b0;
                    end
                    state <= S_PACK;
                end

                // -------------------------------------------------
                S_PACK: begin
                    if (round_carry) begin
                        mant_result <= 23'd0;
                        exp_temp    <= exp_temp + 1'sd1;
                    end
                    exp_result <= exp_temp[7:0];
                    state <= S_DONE;
                end

                // -------------------------------------------------
                S_DONE: begin
                    FP_Mul_result <= {sign_r, exp_result, mant_result};
                    FP_Mul_Ready  <= 1'b1;
                    FP_Mul_Busy   <= 1'b0;
                    state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
