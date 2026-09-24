/*  Pipeline reg 3 :
    Shared between Memory Access - Writeback stage 
*/

module pipeline_reg3 ( 
    input           clk, 
    input           reset, 
    input           tick_in, 
    input           stall, 
    input   [31:0]  wb_data_in, 
    input   [31:0]  csr_wb_in, 
    
    output reg  [31:0] wb_data_out, 
    output reg  [31:0] csr_wb_out 
    ); 
     
    always @(posedge clk) 
    begin 
        if(reset) begin 
            wb_data_out <=  32'd0; 
            csr_wb_out  <=  32'd0; 
        
        end else if(!reset && (tick_in || stall)) begin 
            wb_data_out <= wb_data_in; 
            csr_wb_out  <= csr_wb_in; 
        end 
    end 
     
endmodule
