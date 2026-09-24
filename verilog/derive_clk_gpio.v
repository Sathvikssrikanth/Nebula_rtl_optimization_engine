`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 30.08.2026 15:53:19
// Design Name: 
// Module Name: derive_clk_gpio
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
////////////////////////////////////////////////////////////////////////////

module derive_clk_gpio (
    input  wire clk,      // core clock in
    input  wire reset,
    output reg  clk_gpio
);
    always @(posedge clk or posedge reset) begin
        if (reset)
            clk_gpio <= 1'b0;
        else
            clk_gpio <= ~clk_gpio;
    end
endmodule
