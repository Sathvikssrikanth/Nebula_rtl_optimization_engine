/*  Hazard unit :
    It performs data forwarding in case of data dependencies among consecutive instructions.
    It also stalls the pipeline in case of load instruction dependency
*/

module hazard( 

    //DECODE STAGE 
    input  [4:0] rs1_D, 
    input  [4:0] rs2_D, 
    input rs1_Dvalid, 
    input rs2_Dvalid, 
 
    //EXECUTE STAGE 
    input  [4:0] rs1_E, 
    input  [4:0] rs2_E, 
    input  [4:0] rd_E, 
    input rs1_Evalid, 
    input rs2_Evalid, 
    input rd_Evalid, 
    input MemRead, 
 
    //MEMORY STAGE 
    input  [4:0] rd_M, 
    input rd_Mvalid, 
 
    //WB STAGE 
    input  [4:0] rd_W, 
    input rd_Wvalid, 
 
    //OUTPUTS 
    output reg [1:0] fwdA, 
    output reg [1:0] fwdB, 
    output reg stallF, 
    output reg flushPR1 
    ); 
    
    wire rs1_load_use = rs1_Dvalid && rd_Evalid && MemRead && (rd_E != 5'd0) && (rd_E == rs1_D); 
    wire rs2_load_use = rs2_Dvalid && rd_Evalid && MemRead && (rd_E != 5'd0) && (rd_E == rs2_D); 
 
    // fwdA logic 
    always @(*) begin 
        if ((rd_Mvalid && rs1_Evalid) && (rd_M != 5'd0) && (rd_M == rs1_E)) 
            fwdA = 2'b01;   // MEM stage 
        else if ((rd_Wvalid && rs1_Evalid) && (rd_W != 5'd0) && (rd_W == rs1_E)) 
            fwdA = 2'b10;   // WB stage 
        else 
            fwdA = 2'b00;   // No forwarding 
    end 
 
    // fwdB logic 
    always @(*) begin 
        if ((rd_Mvalid && rs2_Evalid) && (rd_M != 5'd0) && (rd_M == rs2_E)) 
            fwdB = 2'b01;   // MEM stage 
        else if ((rd_Wvalid && rs2_Evalid) && (rd_W != 5'd0) && (rd_W == rs2_E)) 
            fwdB = 2'b10;   // WB stage 
        else 
            fwdB = 2'b00;   // No forwarding 
    end 
 
    // Load-use logic 
    always @(*) begin 
        if (rs1_load_use || rs2_load_use) begin 
            stallF    = 1'b1; 
            flushPR1  = 1'b0; 
        end 
 
        else begin 
            stallF = 1'b0; 
            flushPR1 = 1'b0; 
            end 
    end 
 
endmodule
