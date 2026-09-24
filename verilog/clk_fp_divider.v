`timescale 1ns / 1ps
module clk_fp_divider(
    input  wire clk_fp,   // input clock
    input  wire rst,      // synchronous reset
    output reg  clk_fp_add, // half frequency (/2)
    output reg  clk_fp_mul  // true quarter frequency (/4)
);
    // Divide-by-2 for clk_fp_add
    always @(posedge clk_fp or posedge rst) begin
        if (rst)
            clk_fp_add <= 1'b0;
        else
            clk_fp_add <= ~clk_fp_add;
    end

    // Divide-by-4 for clk_fp_mul (MSB of 2-bit counter, true /4, 50% duty)
    reg [1:0] div_cnt;
    always @(posedge clk_fp or posedge rst) begin
        if (rst) begin
            div_cnt    <= 2'b00;
            clk_fp_mul <= 1'b0;
        end else begin
            div_cnt    <= div_cnt + 1'b1;
            clk_fp_mul <= div_cnt[1];
        end
    end
endmodule
