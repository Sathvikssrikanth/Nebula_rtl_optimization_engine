/*  Pipeline reg 0 : 
    Holds the PC, which is to be sent to the instruction memory
*/
 
module PC ( 
    input clk, 
    input reset, 
    input [31:0] PC_next_in, 
    input stall, 
    output reg [31:0] pc 
    ); 
     
    always @ (posedge clk)  
    begin 
        if(reset) 
        begin 
            pc  <=  32'd0; 
        end 
        
        if(!reset && !stall) 
        begin 
            pc  <=  PC_next_in; 
        end 
    end     

endmodule
