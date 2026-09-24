/*  ALU :
    It performs the required arithmetic or logical operation (based on alu_ctrl) in the first clock cycle
    as well as calculates the next_pc value in the next clock cycle. 
    Both, the ALU_result and Next_PC are held in a latch before they are written to the pipeline register. 
*/

module alu (
    input clk,
    input tick_in,
    input reset,
    input [31:0] src_a,
    input [31:0] src_b,
    input [4:0] alu_ctrl,
    input alu_en,
    output [31:0] alu_result,
    output [31:0] next_pc,
    output zero_flag,
    output sign_flag
    );
            
    wire [31:0] int_alu_result, int_next_pc;
    wire alu_valid, pc_valid;
            
    alu_internal alu (
        .src_a(src_a),
        .src_b(src_b),
        .alu_ctrl(alu_ctrl),
        .alu_en(alu_en),
        .reset(reset),
        .alu_result(int_alu_result),
        .alu_valid(alu_valid),
        .next_pc(int_next_pc),
        .pc_valid(pc_valid),
        .zero_flag(zero_flag),
        .sign_flag(sign_flag)
    );
        
    latch alu_res (
        .in(int_alu_result),
        .clk(clk),
        .tick(~tick_in),
        .reset(reset),
        .out(alu_result)
    );
        
    latch next_pc_res (
        .in(int_next_pc),
        .clk(clk),
        .tick(tick_in && (alu_ctrl != 5'd18)),
        .reset(reset),
        .out(next_pc)
    );
    
            
endmodule

module latch (
    input clk,
    input tick,
    input reset,
    input [31:0] in,
    output reg [31:0] out
    );
        
    always @(posedge clk) begin
        if(reset)
            out <= 32'd0;
        else if(tick)
            out <= in;
    end
        
endmodule
                
module alu_internal (
    input [31:0] src_a,
    input [31:0] src_b,
    input [4:0] alu_ctrl,
    input alu_en,
    input reset,
    output reg [31:0] alu_result,
    output reg [31:0] next_pc,
    output reg alu_valid,
    output reg pc_valid,
    output zero_flag,
    output sign_flag
    );

    wire [4:0] shift_amt;
    assign shift_amt = src_b[4:0];

    always@(*) begin
        // Defaults - every output gets a value on EVERY path through
        // this block, regardless of reset/alu_en/case-arm taken. This
        // is required: alu_result/next_pc/alu_valid/pc_valid are all
        // driven ONLY combinationally here (the real flip-flops are
        // the separate 'latch' module instances in alu.v, which are
        // genuinely posedge-clocked). Without a default at the top,
        // any signal left unassigned on some path (e.g. the
        // !reset && !alu_en case, which previously had no branch at
        // all, or case arms that only touch one of alu_result/next_pc)
        // makes Yosys correctly infer an actual level-sensitive latch
        // for it - which then has no mappable cell in this library
        // ($_DLATCH_N_/$_DLATCH_NP0_ black-boxed at synthesis, then
        // failing PnR since there's no real LEF master for it).
        alu_result = 32'b0;
        next_pc    = 32'd0;
        alu_valid  = 1'b0;
        pc_valid   = 1'b0;

        if(!reset && alu_en) begin
            case(alu_ctrl[4:0])
                5'd0  : alu_result = src_a + src_b;                                         // add
                5'd1  : alu_result = src_a - src_b;                                         // sub
                5'd2  : alu_result = src_a & src_b;                                         // bitwise and
                5'd3  : alu_result = src_a | src_b;                                         // bitwise or
                5'd4  : alu_result = src_a ^ src_b;                                         // bitwise xor
                5'd5  : alu_result = ($signed(src_a) < $signed(src_b)) ? 32'd1 : 32'd0;     // slt
                5'd6  : alu_result = (src_a < src_b) ? 32'd1 : 32'd0;                       // sltu
                5'd7  : alu_result = (~src_a) & src_b;                                      // CSR -> (~src_a + src_b)    
                5'd8  : alu_result = src_a << shift_amt;                                    // sll
                5'd9  : alu_result = src_a >> shift_amt;                                    // srl
                5'd10 : alu_result = $signed(src_a) >>> shift_amt;                          // sra
                5'd11 : alu_result = src_b;                                                 // lui
                5'd12 : alu_result = src_a - src_b;                                         // bltu / bgeu
                5'd13 : alu_result = src_a + 4;                                             // jal/jalr -- save current pc in rd    // 04-04-26 : Changed to (src_a + 4) from (src_a) to correct writeback address
                5'd14 : next_pc = (src_a + src_b) & ~32'd3;                                 // jalr
                5'd15 : next_pc = src_a + src_b;                                            // pc update
                5'd16 : next_pc = src_a - src_b;
                5'd17 : alu_result = src_a;                                                 // CSRRW
            endcase

        end else if (reset) begin
            alu_result = 32'b0;
            next_pc = 32'd0;
            alu_valid =1'b0;
            pc_valid = 1'b0;
        end
        
    end

    assign zero_flag = (alu_result == 32'b0);
    assign sign_flag = (alu_ctrl == 4'd12) ? (src_a < src_b) : alu_result[31];           
    // sign flag is alu_result msb for all cases except for unsigned branch conditions bltu and bgeu

endmodule
