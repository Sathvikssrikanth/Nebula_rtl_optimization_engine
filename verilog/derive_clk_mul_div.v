`timescale 1ns / 1ps
module derive_clk_mu1_div (
    input  wire clk_md,   // input clock
    input  wire reset,    // active-high async reset
    output reg  clk_md_mul,  // divide by 3 (asymmetric duty)
    output reg  clk_md_div   // divide by 6
);
    // ---------------- clk_md_mul: divide-by-3 ----------------
    reg [1:0] cnt3;
    always @(posedge clk_md or posedge reset) begin
        if (reset) begin
            cnt3       <= 2'b00;
            clk_md_mul <= 1'b0;
        end else begin
            if (cnt3 == 2'd2)
                cnt3 <= 2'd0;
            else
                cnt3 <= cnt3 + 1'b1;

            clk_md_mul <= (cnt3 < 2'd2) ? 1'b1 : 1'b0;
        end
    end

    // ---------------- clk_md_div: divide-by-6 ----------------
    reg [1:0] cnt6;
    always @(posedge clk_md or posedge reset) begin
        if (reset) begin
            cnt6       <= 2'b00;
            clk_md_div <= 1'b0;
        end else begin
            cnt6 <= cnt6 + 1'b1;
            if (cnt6 == 2'd2) begin
                clk_md_div <= ~clk_md_div;
                cnt6       <= 2'd0;
            end
        end
    end
endmodule
