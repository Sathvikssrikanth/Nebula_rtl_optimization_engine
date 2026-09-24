/*  2x1 32-bit MUX  */

module M6 (
    input PC_Src, 
    input [31:0] Next_PC_Reg, 
    input [31:0] Next_PC_CSR, 
    output reg [31:0] NEXT_PC
    );

    always@(*) begin 
        case (PC_Src) 
            1'b0: NEXT_PC = Next_PC_Reg; 
            1'b1: NEXT_PC = Next_PC_CSR; 
        endcase 
    end 
    
endmodule
