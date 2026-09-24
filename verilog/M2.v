/*  2x1 32-bit MUX  */

module M2 (
    input [31:0]RS1, 
    input [31:0] PC, 
    input ALUSrcA, 
    output reg [31:0]SrcA
    ); 
    
    always@(*) begin 
        if(ALUSrcA) begin 
            SrcA = RS1; 
        end 
        else begin 
            SrcA = PC; 
        end 
    end 

endmodule
