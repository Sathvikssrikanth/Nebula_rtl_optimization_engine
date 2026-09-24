/*  4x1 32-bit MUX  */

module M5 (
    input [1:0] ResultSrc, 
    input [31:0]Alu_result, 
    input [31:0] RD, 
    input [31:0]CSR_Data_Reg, 
    output reg [31:0] wb_data
    ); 

    always@(*) begin 
        case (ResultSrc) 
            3'b000: wb_data = Alu_result; 
            3'b001: wb_data = RD; 
            3'b010: wb_data = CSR_Data_Reg; 
            default: wb_data = 32'd0;
        endcase 
    end 
    
endmodule
