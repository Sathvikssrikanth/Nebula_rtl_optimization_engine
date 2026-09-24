`timescale 1ns / 1ps
module derive_clk_spi(
    input  wire clk_spi,     // input clock
    input  wire reset,       // active-high async reset
    output reg  clk_spi_div  // divide by 3 (asymmetric duty)
);
    reg [1:0] cnt3;
    always @(posedge clk_spi or posedge reset) begin
        if (reset) begin
            cnt3        <= 2'b00;
            clk_spi_div <= 1'b0;
        end else begin
            if (cnt3 == 2'd2)
                cnt3 <= 2'd0;
            else
                cnt3 <= cnt3 + 1'b1;

            clk_spi_div <= (cnt3 < 2'd2) ? 1'b1 : 1'b0;
        end
    end
endmodule
