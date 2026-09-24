/*  Pipeline reg 1 :
    Shared between Decode - Execute stage 
*/

module pipeline_reg1 ( 
    input clk, 
    input reset, 
    input tick_in, 
    input [11:0] I_TYPE_in, 
    input [11:0] S_TYPE_in, 
    input [11:0] B_TYPE_in, 
    input [19:0] J_TYPE_in, 
    input [19:0] U_TYPE_in, 
    input [31:0] CSR_Data_in, 
    input [31:0] RD1_in, 
    input [31:0] RD2_in, 
    input [31:0] RD3_in, 
    input [31:0] RD4_in, 
    input [31:0] pc_d, 
    output reg [31:0] I_TYPE_out, 
    output reg [31:0] S_TYPE_out, 
    output reg [31:0] B_TYPE_out, 
    output reg [31:0] J_TYPE_out, 
    output reg [31:0] U_TYPE_out, 
    output reg [31:0] CSR_Data_out, 
    output reg [31:0] RD1_out, 
    output reg [31:0] RD2_out, 
    output reg [31:0] RD3_out, 
    output reg [31:0] RD4_out, 
    output reg [31:0] pc_e 
    ); 
 
 
    always @(posedge clk) 
    begin 
        
        if(reset) begin 
            I_TYPE_out      <=  32'd0; 
            S_TYPE_out      <=  32'd0; 
            B_TYPE_out      <=  32'd0; 
            J_TYPE_out      <=  32'd0; 
            U_TYPE_out      <=  32'd0; 
            CSR_Data_out    <=  32'd0; 
            RD1_out         <=  32'd0; 
            RD2_out         <=  32'd0; 
            RD3_out         <=  32'd0; 
            RD4_out         <=  32'd0; 
        
        end else if(!reset && tick_in) begin 
            I_TYPE_out      <=  {{20{I_TYPE_in[11]}},  I_TYPE_in}; 
            S_TYPE_out      <=  {{20{S_TYPE_in[11]}},  S_TYPE_in}; 
            B_TYPE_out      <=  {{19{B_TYPE_in[11]}},  B_TYPE_in,  1'b0}; 
            J_TYPE_out      <=  {{11{J_TYPE_in[19]}},  J_TYPE_in,  1'b0}; 
            U_TYPE_out      <=  {U_TYPE_in  ,   12'd0}; 
            CSR_Data_out    <=  CSR_Data_in; 
            RD1_out         <=  RD1_in; 
            RD2_out         <=  RD2_in; 
            RD3_out         <=  RD3_in; 
            RD4_out         <=  RD4_in; 
            pc_e            <=  pc_d; 
        end 

    end 

endmodule
