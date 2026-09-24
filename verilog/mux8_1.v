`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 25.08.2026 16:46:14
// Design Name: 
// Module Name: mux8_1
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



module mux8_1(
    input [2:0] AluResultSrc, 
    input [31:0]AluOp, 
    input [31:0] FFT_rd_data, 
    input[31:0] Mult_rd_data, 
    input [31:0] Div_rd_data,
    input [31:0] FP_Add_result,
    input [31:0] FP_Mul_result,
    output reg [31:0] Alu_result 
    ); 

    always@(*) begin 
        case (AluResultSrc) 
            3'b000: Alu_result = AluOp; 
            3'b001: Alu_result = FFT_rd_data; 
            3'b010: Alu_result = Mult_rd_data; 
            3'b011: Alu_result = Div_rd_data;
            3'b100: Alu_result = FP_Add_result;
            3'b101: Alu_result = FP_Mul_result;
            default: Alu_result = 32'd0;
        endcase 
    end
    
endmodule
