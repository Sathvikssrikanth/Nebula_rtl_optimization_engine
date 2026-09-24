/*  8x1 32-bit MUX  */

module M3 (
    input [2:0] AluSrcB,
    input [31:0] RS2,
    input [31:0] CSR_Data_Reg,
    input [31:0] I_Reg,
    input [31:0] S_Reg,
    input [31:0] B_Reg,
    input [31:0] J_Reg,
    input [31:0] U_Reg,
    output reg [31:0]SrcB
    );

    always@(*) begin
        case (AluSrcB)
            3'b000: SrcB = RS2;
            3'b001: SrcB = 32'd4;
            3'b010: SrcB = CSR_Data_Reg;
            3'b011: SrcB = I_Reg;
            3'b100: SrcB = S_Reg;
            3'b101: SrcB = B_Reg;
            3'b110: SrcB = J_Reg;
            3'b111: SrcB = U_Reg;
        endcase
    end
    
endmodule
