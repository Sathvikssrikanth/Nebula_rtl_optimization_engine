module Multiplier(
    input  wire         clk_md_mul,
    input  wire         rst,

    input  wire         start_mul,
    input  wire [31:0]  rs1_data,
    input  wire [31:0]  rs2_data,
    input  wire [2:0]   func3,

    output reg  [31:0]  result,
    output reg          mul_busy,
    output reg          mul_done
);

    wire [31:0] abs_rs1 = rs1_data[31] ? -rs1_data : rs1_data;
    wire [31:0] abs_rs2 = rs2_data[31] ? -rs2_data : rs2_data;
    wire        sign_bit = rs1_data[31] ^ rs2_data[31];

    // Fully combinational 32x32 array multiplier
    // 32 partial products, each summed via ripple-carry addition,
    // chained sequentially -> long combinational critical path
    wire [63:0] pp [0:31];
    wire [63:0] sum [0:32];

    genvar i;
    generate
        for (i = 0; i < 32; i = i + 1) begin : gen_pp
            assign pp[i] = abs_rs2[i] ? ({32'b0, abs_rs1} << i) : 64'b0;
        end
    endgenerate

    assign sum[0] = 64'b0;
    generate
        for (i = 0; i < 32; i = i + 1) begin : gen_sum
            // plain ripple-carry adder inferred here (no CSA/Wallace optimization)
            assign sum[i+1] = sum[i] + pp[i];
        end
    endgenerate

    wire [63:0] raw_product = sign_bit ? (-sum[32]) : sum[32];

    always @(posedge clk_md_mul or posedge rst) begin
        if (rst) begin
            result   <= 32'd0;
            mul_busy <= 1'b0;
            mul_done <= 1'b0;
        end else begin
            mul_busy <= start_mul;
            mul_done <= start_mul;
            if (start_mul) begin
                case (func3)
                    3'b000: result <= raw_product[31:0];   // MUL
                    3'b001: result <= raw_product[63:32];  // MULH
                    default: result <= 32'd0;
                endcase
            end
        end
    end

endmodule



