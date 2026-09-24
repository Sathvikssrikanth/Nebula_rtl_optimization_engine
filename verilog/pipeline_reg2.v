/*  Pipeline reg 2 :
    Shared between Execute - Memory Access stage 
*/

module pipeline_reg2 (
    input           clk,
    input           reset,
    input           tick_in,
    input           zero_in,
    input           sign_in,
    input [31:0]    Alu_Result_in,
    input [31:0]    Next_PC_in,
    input [31:0]    RS2_in,
    input [31:0]    CSR_Data_in,
    input branch,

    output reg           zero_out,
    output reg           sign_out,
    output reg [31:0]    Alu_Result_out,
    output reg [31:0]    Next_PC_out,
    output reg [31:0]    RS2_out,
    output reg [31:0]    CSR_Data_out
    );
    
    always @(posedge clk)
    begin
        if(reset) begin
            zero_out        <=  1'b0;
            sign_out        <=  1'b0;
            Alu_Result_out  <=  32'b0;
            Next_PC_out     <=  32'd0;
            RS2_out         <=  32'b0;
            CSR_Data_out    <=  32'b0;
        
        end else if(!reset && (tick_in || branch)) begin
            zero_out        <=  zero_in;
            sign_out        <=  sign_in;
            Alu_Result_out  <=  Alu_Result_in;
            RS2_out         <=  RS2_in;
            CSR_Data_out    <=  CSR_Data_in;   

        end else if(!branch) begin
            Next_PC_out     <=  Next_PC_in; 
        end
    end
endmodule
