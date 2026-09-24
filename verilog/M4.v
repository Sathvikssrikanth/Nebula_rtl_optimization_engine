/*  4x1 32-bit MUX  */
 
module M4 (
    input [1:0] AluResultSrc, 
    input [31:0]AluOp, 
    input [31:0] FFT_rd_data, 
    input[31:0] Mult_rd_data, 
    input [31:0] Div_rd_data,
    output reg [31:0] Alu_result 
    ); 

    always@(*) begin 
        case (AluResultSrc) 
            2'b00: Alu_result = AluOp; 
            2'b01: Alu_result = FFT_rd_data; 
            2'b10: Alu_result = Mult_rd_data;
            2'b11: Alu_result = Div_rd_data; 
        endcase 
    end
     
endmodule
