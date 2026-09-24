/*  2x1 12-bit MUX  */

module M1 (
    input CSR_WR_EN, 
    input [11:0]INS, 
    input [11:0] CSR_ADDR, 
    output reg [11:0] CSR_Addr
    );

    always@(*) begin 
        if(CSR_WR_EN) begin 
            CSR_Addr = CSR_ADDR; 
        end 
        else begin 
            CSR_Addr = INS; 
        end 
    end
     
endmodule
