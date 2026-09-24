`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 19.08.2026 16:54:13
// Design Name: 
// Module Name: divider
// Project Name: 
// Target Devices: 
// Tool Versions: 
// Description: 
// 
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
//////////////////////////////////////////////////////////////////////////////////


module divider(
    input  wire        clk_md_div,
    input  wire        rst,
    input  wire        start_div,
    input  wire [31:0] rs1_data,
    input  wire [31:0] rs2_data,
    input  wire [2:0]  func3,
    output reg  [31:0] result,
    output reg         div_busy,
    output reg         div_done
);

    localparam IDLE   = 2'd0,
               CALC   = 2'd1,
               FINISH = 2'd2;

    reg [1:0]  state;
    reg [31:0] rs1_latched;
    reg        dividend_sign, divisor_sign;
    reg [31:0] dividend_abs, divisor_abs;
    reg        is_rem;        // 1 = REM (func3=110), 0 = DIV (func3=100)
    reg        is_div_zero;
    reg        is_overflow;   // MIN_INT / -1 case
    reg [63:0] work;          // {remainder, quotient}
    reg [63:0] temp;
    reg [5:0]  count;
    reg        start_div_d; 
    
    always @(posedge clk_md_div or posedge rst) begin
        if (rst)
            start_div_d <= 1'b0;
        else
            start_div_d <= start_div;
    end

    wire start_div_pulse = start_div & ~start_div_d;

    always @(posedge clk_md_div or posedge rst) begin
        if (rst) begin
            state    <= IDLE;
            div_busy <= 1'b0;
            div_done <= 1'b0;
            result   <= 32'b0;
        end else begin
            div_done <= 1'b0;   // default: pulse only in FINISH

            case (state)

                IDLE: begin
                    if (start_div_pulse) begin
                        rs1_latched   <= rs1_data;
                        is_rem        <= (func3 == 3'b110);

                        dividend_sign <= rs1_data[31];
                        divisor_sign  <= rs2_data[31];
                        dividend_abs  <= rs1_data[31] ? (~rs1_data + 1'b1) : rs1_data;
                        divisor_abs   <= rs2_data[31] ? (~rs2_data + 1'b1) : rs2_data;

                        is_div_zero   <= (rs2_data == 32'b0);
                        is_overflow   <= (rs1_data == 32'h8000_0000) &&
                                         (rs2_data == 32'hFFFF_FFFF);

                        count    <= 6'd0;
                        div_busy <= 1'b1;

                        if ((rs2_data == 32'b0) ||
                            ((rs1_data == 32'h8000_0000) && (rs2_data == 32'hFFFF_FFFF))) begin
                            state <= FINISH;          // no iteration needed
                        end else begin
                            work  <= {32'b0, (rs1_data[31] ? (~rs1_data + 1'b1) : rs1_data)};
                            state <= CALC;
                        end
                    end
                end

                CALC: begin
                    // one restoring-division step per cycle, 32 steps total
                    temp = work << 1;
                    if (temp[63:32] >= divisor_abs) begin
                        temp[63:32] = temp[63:32] - divisor_abs;
                        temp[0]     = 1'b1;
                    end
                    work <= temp;

                    if (count == 6'd31)
                        state <= FINISH;
                    else
                        count <= count + 1'b1;
                end

                FINISH: begin
                    if (is_div_zero) begin
                        result <= is_rem ? rs1_latched : 32'hFFFF_FFFF; // REM=dividend, DIV=-1
                    end else if (is_overflow) begin
                        result <= is_rem ? 32'b0 : 32'h8000_0000;
                    end else if (is_rem) begin
                        // remainder takes sign of dividend
                        result <= dividend_sign ? (~work[63:32] + 1'b1) : work[63:32];
                    end else begin
                        // quotient sign = sign(rs1) XOR sign(rs2)
                        result <= (dividend_sign ^ divisor_sign) ? (~work[31:0] + 1'b1) : work[31:0];
                    end
                    div_busy <= 1'b0;
                    div_done <= 1'b1;   // one-cycle pulse
                    state    <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
