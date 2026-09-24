/*  Control unit :
    It generates all the necessary control signals for the instructions at different stages of pipeline at once.
    Every newly fetched instruction from the instruction memory first comes to i_decode, where all signals needed for decode stage are generated.
    In the next fetch cycle, this instruction passes in the execute stage and next instruction comes in decode stage. Necessary control signals
    for both these instructions are generated at once.
    This process continues till instruction is passed on to all stages (Decode / Execute/ Memory Access/ Writeback)      
 */ 
`timescale 1ns / 1ps 

// FIX_DESCRIPTION: Pre-computed and registered the FFT instruction decode signal alongside i_decode to eliminate combinational decode delay on register file address outputs.
// PIPELINE_STAGES_ADDED: 0

module controller( 
    
    input [31:0] opcode, 
     
    input clk, 
    input reset, 
    input flush, 
    input stall, 
     
    input zero, 
    input sign, 
     
    input mul_done, 
    input mul_busy, 
     
    input  div_busy,
    input  div_done,
    
    input fp_mul_busy,fp_mul_done,fp_add_busy,fp_add_done,
    
    input fft_done, 
    input fft_busy, 
     
    input spi_irq, 
    input gpio_irq, 
     
    input [31:0] pc_in, 
     
    //DECODE STAGE 
    output [4:0] A1, 
    output [4:0] A2, 
    output [4:0] A3, 
    output [4:0] A4, 
     
    output [11:0] I_TYPE, 
    output [11:0] S_TYPE, 
    output [11:0] B_TYPE, 
    output [19:0] J_TYPE, 
    output [19:0] U_TYPE, 
    output [11:0] CSR_Addr, 
     
    //EXECUTE STAGE 
    output reg  AluSrcA, 
    output reg [2:0] AluSrcB, 
    output reg [4:0] AluControl, 
    output reg [2:0] AluResultSrc, 
    output reg AluEn, 
 
    //Multiplier 
    output reg start_mul, 
    output [2:0] func3, 
    
    //Divider
    output reg start_div,
    
    //FP Unit
    output reg start_fp_mul,
    output reg start_fp_add,
    
              
    // FFT  
    output reg start_fft, 
    output  [1:0] fft_wb, 
     
    // MEMORY STAGE 
    output MemWrEn, 
    output [1:0] ResultSrc, 
    input trans_done, 
     
    // CSR 
    output CsrWrEn, 
    output CsrEn, 
    output wb_valid, 
    output trap, 
    output mret, 
    output reg trap_busy, 
     
    //WRITE BACK STAGE 
    output RegWrEn, 
    output [4:0] A5, 
 
    output tick, 
    output reg [31:0] pc_d, 
    output BRANCH_MUX, 
    output reg [31:0] i_decode, i_ex, i_mem, i_wb, 
     
    //HAZARDS 
    output [4:0] rs1_d,rs2_d,rs1_e,rs2_e,rd_e,rd_m,rd_w, 
    output rs2_d_valid, rs1_d_valid, rs1_e_valid, rs2_e_valid, rd_e_valid, rd_m_valid, rd_w_valid, 
     
    output memread,  
    output  ins_ena 
    ); 
 
 
    reg [1:0]  state; 
    reg branch; 
    reg last_mul; 
    reg last_div,last_fp_add,last_fp_mul;
    reg last_fft; 
    reg tick_ex , tick_mem; 
    reg branch_flush; 
    reg [31:0] temp_pc; 
    reg is_fft_dec;
    
    //--------- COMBINATIONAL PART -------------------------------------------------
    
    assign tick = tick_ex && tick_mem && !mul_busy && !div_busy && !fft_busy ;
    
    // DECODE STAGE 
    assign I_TYPE   = i_decode[31:20]; 
    assign S_TYPE   = {i_decode[31:25], i_decode[11:7]}; 
    assign B_TYPE   = {i_decode[31], i_decode[7], i_decode[30:25], i_decode[11:8]}; 
    assign J_TYPE   = {i_decode[31], i_decode[19:12], i_decode[20], i_decode[30:21]}; 
    assign U_TYPE   = i_decode[31:12]; 
    assign A5       = i_wb[11:7]; 
    assign A1       = is_fft_dec ? 5'b01010 : i_decode[19:15]; 
    assign A2       = is_fft_dec ? 5'b01011 : i_decode[24:20]; 
    assign A3       = is_fft_dec ? 5'b01100 : 5'b0; 
    assign A4       = is_fft_dec ? 5'b01101 : 5'b0; 
    assign CSR_Addr = i_wb[31:20]; 
    
    // Multiplier / FFT 
    assign func3    = i_ex[14:12]; 
    assign fft_wb   = i_ex[13:12]; 
    
    // WRITE BACK 
    assign RegWrEn  = (i_wb[6:0] == 7'b0110011) ||  // R-type 
                    (i_wb[6:0] == 7'b0010011) ||  // I-type ALU 
                    (i_wb[6:0] == 7'b0000011) ||  // Load 
                    (i_wb[6:0] == 7'b1100111) ||  // JALR 
                    (i_wb[6:0] == 7'b1101111) ||  // JAL 
                    (i_wb[6:0] == 7'b0110111) ||  // LUI 
                    (i_wb[6:0] == 7'b1110011) ||  // CSR 
                    (i_wb[6:0] == 7'b0010111) ||  // AUIPC 
                    (i_wb[6:0] == 7'b0001011);    // Multiplication 
    
    // CSR 
    assign CsrEn    = ((i_decode[6:0] == 7'b1110011) || (i_wb[6:0] == 7'b1110011)); 
    assign CsrWrEn  = (i_wb[6:0] == 7'b1110011); 
    assign wb_valid = tick && (i_wb != 32'b0); 
    assign trap     = spi_irq | gpio_irq; 
    
    // BRANCH / MEMORY 
    assign BRANCH_MUX = branch; 
    assign MemWrEn     = (i_mem[6:0] == 7'b0100011); 
    assign ResultSrc   = ((i_mem[6:0] == 7'b0000011) || (i_decode == 32'h30200073)) ? 2'b01 : 
                        (i_mem[6:0] == 7'b1110011) ? 2'b10 : 
                        2'b00; 
    
    
    // hazard unit// 
    assign rs1_d = i_decode[19:15]; 
    assign rs2_d = i_decode[24:20]; 
    assign rs1_e = i_ex[19:15]; 
    assign rs2_e = i_ex[24:20]; 
    assign rd_e  = i_ex[11:7]; 
    assign rd_m  = i_mem[11:7]; 
    assign rd_w  = i_wb[11:7]; 
    
    assign rs1_d_valid = 
        (i_decode[6:0] == 7'b0110011) || // R-type 
        (i_decode[6:0] == 7'b0010011) || // I-type 
        (i_decode[6:0] == 7'b0000011) || // Load 
        (i_decode[6:0] == 7'b0100011) || // Store 
        (i_decode[6:0] == 7'b1100011) || // Branch 
        (i_decode[6:0] == 7'b1100111) || // JALR 
        (i_decode[6:0] == 7'b1110011);   // CSR 
        
        
    assign rs2_d_valid  =   (i_decode[6:0] == 7'b0110011) ||  // R-type 
                            (i_decode[6:0] == 7'b0100011) ||  // Store 
                            (i_decode[6:0] == 7'b1100011);    // Branch 
                            
    assign rs1_e_valid  = (i_ex[6:0] == 7'b0110011) || // R-type 
        (i_ex[6:0] == 7'b0010011) || // I-type 
        (i_ex[6:0] == 7'b0000011) || // Load 
        (i_ex[6:0] == 7'b0100011) || // Store 
        (i_ex[6:0] == 7'b1100011) || // Branch 
        (i_ex[6:0] == 7'b1100111) || // JALR 
        (i_ex[6:0] == 7'b1110011);   // CSR 
        
    assign rs2_e_valid  = (i_ex[6:0] == 7'b0110011) ||  // R-type 
                            (i_ex[6:0] == 7'b0100011) ||  // Store 
                            (i_ex[6:0] == 7'b1100011); 
                            
    assign rd_e_valid   = !((i_ex[6:0] == 7'b0100011) ||  // Store 
                            (i_ex[6:0] == 7'b1100011) ||  // Branch 
                            (i_ex == 32'b00110000001000000000000001110011)); //mret 
                            
    assign rd_m_valid   = !((i_mem[6:0] == 7'b0100011) ||  // Store 
                            (i_mem[6:0] == 7'b1100011) ||  // Branch 
                            (i_mem == 32'b00110000001000000000000001110011)); //mret 
                            
    assign rd_w_valid   =!((i_wb[6:0] == 7'b0100011) ||  // Store 
                            (i_wb[6:0] == 7'b1100011) ||  // Branch 
                            (i_wb == 32'b00110000001000000000000001110011)); //mret 
        
    assign memread =(i_ex[6:0] == 7'b0000011); 
    
    //assign ins_ena = ((i_ex[6:0] == 7'b0110011) && (i_ex[31:25] ==7'b0000001)&& (i_mem[31:25] !=7'b0000001)&& (i_mem[31:25] !=7'b0000001) /*&& (!last_mul)*/)? 1'b0: 1'b1; 
    assign ins_ena =1; 
    //Interrupts 
    assign mret = (i_decode == 32'h30200073)? 1'b1 :1'b0; 
    
    // Passing instructions to the nextstage 
    
    always @(posedge clk) 
    begin 
        if(reset) begin 
            i_decode     <= 32'd0; 
            is_fft_dec   <= 1'b0;
            i_ex         <= 32'd0; 
            i_mem        <= 32'd0; 
            i_wb         <= 32'd0; 
            AluEn        <= 1'b0; 
            AluSrcA      <= 1'b1; 
            AluSrcB      <= 3'b0; 
            AluControl   <= 5'd0; 
            AluResultSrc <= 3'd0; 
            start_mul    <= 1'b0; 
            start_fft    <= 1'b0; 
            start_div    <= 1'b0; 
            start_fp_add <= 1'b0; start_fp_mul <= 1'b0; 
            tick_ex      <= 1'b1; 
            branch       <= 1'b0; 
            trap_busy    <= 1'b0; 
            state        <= 2'b00; 
            last_mul     <= 1'b0; 
            last_fft     <= 1'b0; 
            last_div     <= 1'b0; 
            last_fp_add  <= 1'b0; 
            last_fp_mul  <= 1'b0; 
            
        end else if(branch) begin 
            i_decode    <= 32'd0; 
            is_fft_dec  <= 1'b0;
            i_ex        <= 32'd0; 
            i_mem       <= i_ex; 
            i_wb        <= i_mem; 
            tick_ex     <= 1'b0; 
            branch      <= 1'b0;

        end else if(stall) begin  
            i_ex  <= 32'd0; 
            i_mem <= i_ex; 
            i_wb <= i_mem; 
            tick_ex <= 1'b0; 

        end else if (tick) begin 
            i_decode    <= opcode; 
            is_fft_dec  <= (opcode[6:0] == 7'b0001011);
            i_ex        <= i_decode; 
            i_mem       <= i_ex; 
            i_wb        <= i_mem; 
            tick_ex     <= 1'b0; 
            AluEn       <= 1'b0; 
            if(last_mul | last_div | last_fp_add | last_fp_mul) begin 
            /*i_decode    <= 32'b0;*/ last_mul<=1'b0; 
                                       last_div<=1'b0; last_fp_add<=1'b0;  last_fp_mul<=1'b0; end 
            temp_pc   <= pc_in;             // 04-04-26 : Added to correct Branch / Jump PC values 
            pc_d      <= temp_pc;           // 04-04-26 : Added to correct Branch / Jump PC values 
    
            
        end else begin 

            case(i_ex[6:0])  
            
                // Rtype 
                7'b0110011: begin 
                        
                    case(i_ex[31:25]) 
                        // Rtype  (ADD SLL SLT SLTU XOR SRL OR AND) 
                        7'b0000000:  begin 
                            if(state == 2'd0)  
                                begin 
                                    AluEn        <= 1'b1; 
                                    AluSrcA      <= 1'b1; 
                                    AluSrcB      <= 3'd0; 
                                    AluResultSrc <= 3'd0; 
                                    start_mul    <= 1'b0; 
                                    start_fft    <= 1'b0; 
                                    start_div <= 1'b0;
                                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                                    branch       <= 1'b0; 
                                    state        <= 2'd1; 
                                    tick_ex         <= 1'b0; 
                                    case(i_ex[14:12])  
                                        3'b000 : AluControl <= 5'd0; // ADD 
                                        3'b001 : AluControl <= 5'd8; // SLL 
                                        3'b010 : AluControl <= 5'd5; // SLT 
                                        3'b011 : AluControl <= 5'd6; // SLTU 
                                        3'b100 : AluControl <= 5'd4; // XOR 
                                        3'b101 : AluControl <= 5'd9; // SRL 
                                        3'b110 : AluControl <= 5'd3; // OR 
                                        3'b111 : AluControl <= 5'd2; // AND 
                                    endcase     
                                end 
                            if(state == 2'd1) 
                                begin 
                                    AluEn        <= 1'b1; 
                                    AluSrcA      <= 1'b0; 
                                    AluSrcB      <= 3'd1; 
                                    AluControl   <= 5'd15; 
                                    AluResultSrc <= 3'b0; 
                                    start_mul    <= 1'b0; 
                                    start_fft    <= 1'b0; 
                                    start_div <= 1'b0;
                                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                                    branch       <= 1'b0; 
                                    state        <= 2'd0; 
                                    tick_ex         <= 1'b1; 
                                end 
                            end 
            
                        // Rtype ( SUB SRA) 
                        7'b0100000: begin 
                            if(state == 2'd0)  
                                begin 
                                    AluEn        <= 1'b1; 
                                    AluSrcA      <= 1'b1; 
                                    AluSrcB      <= 3'd0; 
                                    AluResultSrc <= 3'd0; 
                                    start_mul    <= 1'b0; 
                                    start_fft    <= 1'b0; 
                                    start_div <= 1'b0;
                                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                                    branch       <= 1'b0; 
                                    state        <= 2'd1; 
                                    tick_ex         <= 1'b0; 
                                    case(i_ex[14:12])  
                                    3'b000 : AluControl <= 5'd1;  // Sub 
                                    3'b101 : AluControl <= 5'd10; // SRA  
                                    endcase 
                                    
                                end 
                            if(state == 2'd1) 
                                begin 
                                    AluEn        <= 1'b1; 
                                    AluSrcA      <= 1'b0; 
                                    AluSrcB      <= 3'd1; 
                                    AluControl   <= 5'd15; 
                                    AluResultSrc <= 3'b0; 
                                    start_mul    <= 1'b0; 
                                    start_fft    <= 1'b0; 
                                    start_div    <= 1'b0;
                                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                                    branch       <= 1'b0; 
                                    state        <= 2'd0; 
                                    tick_ex         <= 1'b1; 
                                end 
                            end 
                        
            
                        // Multiplication  
                        7'b0000001: 
                        begin 
                        case(i_ex[14:12])
                        3'b001,3'b000: begin
                                if (state == 2'd0) 
                                begin 
                                    if(!last_mul) 
                                    begin 
                                    AluEn        <= 1'b1;  
                                    AluSrcA      <= 1'b0; 
                                    AluSrcB      <= 3'd1; 
                                    AluControl   <= 5'd15; 
                                    AluResultSrc <= 3'd2; 
                                    start_mul    <= 1'b1; 
                                    start_fft    <= 1'b0; 
                                    start_div    <= 1'b0;
                                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                                    branch       <= 1'b0; 
                                    state        <= 2'd1; 
                                    tick_ex         <= 1'b0; 
                                    last_fft     <= 1'b0; 
                                    last_div     <= 1'b0;
                                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                                    end 
                                    
                                    else begin 
                                    AluEn        <= 1'b1;  
                                    AluSrcA      <= 1'b0; 
                                    AluSrcB      <= 3'd1; 
                                    AluControl   <= 5'd15; 
                                    AluResultSrc <= 3'd2; 
                                    start_mul    <= 1'b1; 
                                    start_fft    <= 1'b0;
                                    start_div    <= 1'b0; 
                                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                                    branch       <= 1'b0; 
                                    state        <= 2'd1; 
                                    tick_ex         <= 1'b0; 
                                    last_fft     <= 1'b0; 
                                    last_div     <= 1'b0;
                                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                                    end 
                                end 
                                else if (state == 2'd1) 
                                begin 
                                // AluEn <= 1'b1; 
                                    AluEn        <= 1'b0;  
                                    AluSrcA      <= 1'b0; 
                                    AluSrcB      <= 3'd1; 
                                    AluControl   <= 5'd15; 
                                    start_mul    <= 1'b0; 
                                    if (mul_done) begin 
                                        tick_ex  <= 1'b1; 
                                        AluEn <= 1'b1; 
                                        state <= 2'd0; 
                                        last_mul <=1'b1; 
                                    end 
                                end 
                             end
                             
                               3'b100,3'b110: begin    //Division
                                if (state == 2'd0) begin
                                    AluEn        <= 1'b1;
                                    AluSrcA      <= 1'b0;
                                    AluSrcB      <= 3'd1;
                                    AluControl   <= 5'd15;
                                    AluResultSrc <= 3'd3;
                                    start_div    <= 1'b1;
                                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                                    start_mul    <= 1'b0;
                                    start_fft    <= 1'b0;
                                    branch       <= 1'b0;
                                    //state        <= 2'd1;
                                    tick_ex      <= 1'b0;
                                    last_mul     <= 1'b0;
                                    last_fft     <= 1'b0;
                                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                                    
                                    // Divider may finish immediately, for example DIV by zero
                                     if (div_busy) begin
                                        start_div <= 1'b0;
                                        state     <= 2'd1;
                                    end
                                end
                                    
                                
                                else if (state == 2'd1) begin
                                    AluEn        <= 1'b0;
                                    AluSrcA      <= 1'b0;
                                    AluSrcB      <= 3'd1;
                                    AluControl   <= 5'd15;
                                    start_div    <= 1'b0;
                                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                                    if (div_done) begin
                                        tick_ex  <= 1'b1;
                                        AluEn    <= 1'b1;
                                        state    <= 2'd0;
                                        last_div <= 1'b1;
                                    end
                                end
                                end
                            endcase
                        end 
                    endcase 
                end
            // Custom Instruction
            7'b0101011: begin   //FP ADDER
                    if (state == 2'd0) begin
                                    AluEn        <= 1'b1;
                                    AluSrcA      <= 1'b0;
                                    AluSrcB      <= 3'd1;
                                    AluControl   <= 5'd15;
                                    AluResultSrc <= 3'd4;
                                    start_div    <= 1'b0;
                                    start_mul    <= 1'b0;
                                    start_fft    <= 1'b0;
                                    branch       <= 1'b0;
                                    //state        <= 2'd1;
                                    tick_ex      <= 1'b0;
                                    last_mul     <= 1'b0;
                                    last_fft     <= 1'b0;
                                    last_div <=1'b0;
                                    last_fp_mul<=1'b0;
                                    start_fp_add <= 1'b1;
                                    start_fp_mul <= 1'b0;
                                    
                                    // Divider may finish immediately, for example DIV by zero
                                     if (fp_add_busy) begin
                                        start_fp_add <= 1'b0;
                                        state     <= 2'd1;
                                    end
                                end
                      else if (state == 2'd1) begin
                                    AluEn        <= 1'b0;
                                    AluSrcA      <= 1'b0;
                                    AluSrcB      <= 3'd1;
                                    AluControl   <= 5'd15;
                                    start_div    <= 1'b0;
                                    start_fp_add <= 1'b0;
                                    start_fp_mul <= 1'b0;
                                    if (fp_add_done) begin
                                        tick_ex  <= 1'b1;
                                        AluEn    <= 1'b1;
                                        state    <= 2'd0;
                                        last_div <= 1'b0;
                                        last_fp_add <=1'b1;
                                    end
                                end
            end
            
            7'b1011011: begin   //FP multiplication
                    if (state == 2'd0) begin
                                    AluEn        <= 1'b1;
                                    AluSrcA      <= 1'b0;
                                    AluSrcB      <= 3'd1;
                                    AluControl   <= 5'd15;
                                    AluResultSrc <= 3'd5;
                                    start_div    <= 1'b0;
                                    start_mul    <= 1'b0;
                                    start_fft    <= 1'b0;
                                    branch       <= 1'b0;
                                    //state        <= 2'd1;
                                    tick_ex      <= 1'b0;
                                    last_mul     <= 1'b0;
                                    last_fft     <= 1'b0;
                                    last_div <=1'b0;
                                    last_fp_mul<=1'b0;
                                    start_fp_add <= 1'b0;
                                    start_fp_mul <= 1'b1;
                                    
                                    // Divider may finish immediately, for example DIV by zero
                                     if (fp_mul_busy) begin
                                        start_fp_mul <= 1'b0;
                                        state     <= 2'd1;
                                    end
                                end
                      else if (state == 2'd1) begin
                                    AluEn        <= 1'b0;
                                    AluSrcA      <= 1'b0;
                                    AluSrcB      <= 3'd1;
                                    AluControl   <= 5'd15;
                                    start_div    <= 1'b0;
                                    start_fp_add <= 1'b0;
                                    start_fp_mul <= 1'b0;
                                    if (fp_mul_done) begin
                                        tick_ex  <= 1'b1;
                                        AluEn    <= 1'b1;
                                        state    <= 2'd0;
                                        last_div <= 1'b0;
                                        last_fp_mul <=1'b1;
                                    end
                                end
            end
            
            
            // I type  
            7'b0010011: begin 
                if (state == 2'd0) begin 
                        AluEn        <= 1'b1; 
                        AluSrcA      <= 1'b1; 
                        AluSrcB      <= 3'd3; 
                        AluControl   <= 5'd0; 
                        AluResultSrc <= 3'd0; 
                        start_mul    <= 1'b0; 
                        start_fft    <= 1'b0; 
                        start_div    <= 1'b0;
                        start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                        branch       <= 1'b0; 
                        state        <= 2'd1; 
                        tick_ex         <= 1'b0; 
                        last_mul     <= 1'b0; 
                        last_fft     <= 1'b0; 
                        last_div     <= 1'b0;
                        last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                        case(i_ex[14:12])  
                        3'b000 : AluControl <= 5'd0; // ADDI 
                        3'b001 : AluControl <= 5'd8; // SLLI 
                        3'b010 : AluControl <= 5'd5; // SLTI 
                        3'b011 : AluControl <= 5'd6; // SLTIU 
                        3'b100 : AluControl <= 5'd4; // XORI 
                        3'b101 :begin   
                                if(i_ex[30]) begin AluControl <= 5'd10; end // SRLI 
                                else begin AluControl <= 5'd9; end // SRAI 
                                end 
                        3'b110 : AluControl <= 5'd3; // ORI 
                        3'b111 : AluControl <= 5'd2; // ANDI 
                        endcase 
                        
                    end 
                    else if (state == 2'd1) begin 
                        AluEn        <= 1'b1; 
                        AluSrcA      <= 1'b0; 
                        AluSrcB      <= 3'd1; 
                        AluControl   <= 5'd15; 
                        AluResultSrc <= 3'b0; 
                        start_mul    <= 1'b0; 
                        start_fft    <= 1'b0; 
                        start_div    <= 1'b0;
                        start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                        branch       <= 1'b0; 
                        state        <= 2'd0; 
                        tick_ex         <= 1'b1; 
                        
                    end 
                end 
                            
            // LOAD 
            7'b0000011: begin 
                if (state == 2'd0)  
                    begin 
                        AluEn        <= 1'b1; 
                        AluSrcA      <= 1'b1; 
                        AluSrcB      <= 3'd3; 
                        AluControl   <= 5'd0; 
                        AluResultSrc <= 3'd0; 
                        start_mul    <= 1'b0; 
                        start_fft    <= 1'b0; 
                        start_div    <= 1'b0;
                        start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                        branch       <= 1'b0; 
                        state        <= 2'd1; 
                        tick_ex         <= 1'b0; 
                        last_mul     <= 1'b0; 
                        last_fft     <= 1'b0; 
                        last_div     <= 1'b0;
                        last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                    end 
                else if (state == 2'd1)  
                    begin 
                        AluEn        <= 1'b1; 
                        AluSrcA      <= 1'b0; 
                        AluSrcB      <= 3'd1; 
                        AluControl   <= 5'd15; 
                        AluResultSrc <= 3'b0; 
                        start_mul    <= 1'b0; 
                        start_fft    <= 1'b0; 
                        start_div    <= 1'b0;
                        start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                        branch       <= 1'b0; 
                        state        <= 2'd0; 
                        tick_ex         <= 1'b1;    
                    end 
                end   
                    
            // Store  
            7'b0100011: begin 
                if (state == 2'd0)  
                begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b1; 
                    AluSrcB      <= 3'd4; 
                    AluControl   <= 5'd0; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd1; 
                    tick_ex      <= 1'b0; 
                    last_mul     <= 1'b0; 
                    last_fft     <= 1'b0; 
                    last_div     <= 1'b0;
                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                end 
                else if (state == 2'd1) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd1; 
                    AluControl   <= 5'd15; 
                    AluResultSrc <= 3'b0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd0; 
                    tick_ex      <= 1'b1;    

                end 
            end 
            
            // Branch  
            7'b1100011: begin 
                if(state == 2'd0)  
                begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b1; 
                    AluSrcB      <= 3'd0; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd1; 
                    tick_ex         <= 1'b0; 
                    case(i_ex[14:12])  
                    3'b000 : AluControl <= 5'd1;  //BEQ 
                    3'b001 : AluControl <= 5'd1;  //BNE 
                    3'b100 : AluControl <= 5'd1;  //BLT 
                    3'b101 : AluControl <= 5'd1;  //BGE 
                    3'b110 : AluControl <= 5'd12; //BLTU 
                    3'b111 : AluControl <= 5'd12; //BGEU 
                    endcase     
                end 
                
                else if(state == 2'd1) 
                begin 
                    state       <=  2'b0; 
                    tick_ex     <=  1'b1; 
                    case(i_ex[14:12])  
                        3'b000 :begin //BEQ 
                                    if (zero) begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd5; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b1; 
                                    end 
                                    else begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd1; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b0; 
                                    end 
                                end  
                                
                        3'b001 :begin  //BNE 
                                    if (!zero) begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd5; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b1; 
                                    end 
                                    else begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd1; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b0; 
                                    end 
                                end 
                                    
                        3'b100 : begin //BLT 
                                    if (sign) begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd5; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b1; 
                                    end 
                                    else begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd1; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b0; 
                                    end 
                                end  
                                
                        3'b101 : begin //BGE 
                                    if (!sign) begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd5; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b1; 
                                    end 
                                    else begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd1; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b0; 
                                    end 
                                end   
                                
                        3'b110 : begin //BLTU 
                                    if (sign) begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd5; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b1; 
                                    end 
                                    else begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd1; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b0; 
                                    end 
                                end 
                                    
                        3'b111 :  begin//BGEU 
                                    if (!sign) begin 
                                    AluEn        <= 1'b1; 
                                    AluSrcA      <= 1'b0; 
                                    AluSrcB      <= 3'd5; 
                                    AluControl   <= 5'd15; 
                                    AluResultSrc <= 3'd0; 
                                    branch       <= 1'b1; 
                                    end 
                                    else begin 
                                        AluEn        <= 1'b1; 
                                        AluSrcA      <= 1'b0; 
                                        AluSrcB      <= 3'd1; 
                                        AluControl   <= 5'd15; 
                                        AluResultSrc <= 3'd0; 
                                        branch       <= 1'b0; 
                                    end 
                                end 
                    endcase    
                end 
                
            end 
            
            // LUI 
            7'b0110111: begin 
                if (state == 2'd0) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd7; 
                    AluControl   <= 5'd11; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd1; 
                    tick_ex      <= 1'b0; 
                    last_mul     <= 1'b0; 
                    last_fft     <= 1'b0; 
                    last_div     <= 1'b0;
                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                end 
                else if (state == 2'd1) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd1; 
                    AluControl   <= 5'd15; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd0; 
                    tick_ex      <= 1'b1; 
                end 
            end 
            
            // AUIPC 
            7'b0010111: begin 
                if (state == 2'd0) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd7; 
                    AluControl   <= 5'd0; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0;   // ? FIXED: no branch in state=0 
                    state        <= 2'd1; 
                    tick_ex      <= 1'b0; 
                    last_mul     <= 1'b0; 
                    last_fft     <= 1'b0; 
                    last_div     <= 1'b0;
                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                end 
                else if (state == 2'd1) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd1; 
                    AluControl   <= 5'd15; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd0; 
                    tick_ex      <= 1'b1; 
                end 
            end 
            
            // JAL 
            7'b1101111: begin 
                if (state == 2'd0) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd3; 
                    AluControl   <= 5'd13; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd1; 
                    tick_ex      <= 1'b0; 
                    last_mul     <= 1'b0; 
                    last_fft     <= 1'b0; 
                    last_div     <= 1'b0;
                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                end 
                else if (state == 2'd1) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd6; 
                    AluControl   <= 5'd15; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b1; 
                    state        <= 2'd0; 
                    tick_ex      <= 1'b1; 
                    last_mul     <= 1'b0; 
                    last_fft     <= 1'b0; 
                    last_div     <= 1'b0;
                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                end 
            end 
    
            // ?? JALR 
            7'b1100111: begin 
                if (state == 2'd0) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd2; 
                    AluControl   <= 5'd13; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b1; 
                    state        <= 2'd1; 
                    tick_ex      <= 1'b0; 
                    last_mul     <= 1'b0; 
                    last_fft     <= 1'b0; 
                    last_div     <= 1'b0;
                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                end 
                else if (state == 2'd1) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b1; 
                    AluSrcB      <= 3'd3; 
                    AluControl   <= 5'd14; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0;
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0; 
                    branch       <= 1'b1; 
                    state        <= 2'd0; 
                    tick_ex      <= 1'b1; 
                end 
            end 
    
            // CSR 
            7'b1110011: begin 
                if (state == 2'd0 ) begin 
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b1; 
                    AluSrcB      <= 3'd2; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd1;    
                    tick_ex      <= 1'b0; 
                    last_mul     <= 1'b0; 
                    last_fft     <= 1'b0; 
                    last_div     <= 1'b0;
                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                    case (i_ex[14:12]) 
                        3'b001: AluControl <= 5'd17; // CSRRW 
                        3'b010: AluControl <= 5'd3;  // CSRRS 
                        3'b011: AluControl <= 5'd7;  // CSRRC 
                        default: AluControl <= 5'd0; 
                    endcase 
                end 
                else if (state == 2'd1) begin   
                    AluEn        <= 1'b1; 
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd1; 
                    AluControl   <= 5'd15; 
                    AluResultSrc <= 3'd0; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b0; 
                    start_div    <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd0; 
                    tick_ex      <= 1'b1; 
                end 
            end 
            
            //FFT 
            7'b0001011: begin 
                if (state == 2'd0) begin 
                    if(!last_fft) begin 
                    AluEn        <= 1'b1;  
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd1; 
                    AluControl   <= 5'd15; 
                    AluResultSrc <= 3'd1; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b1; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd1; 
                    tick_ex         <= 1'b0; 
                    last_fft     <= 1'b0; 
                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                    
                    end 
                    
                    else begin 
                    AluEn        <= 1'b1;  
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd1; 
                    AluControl   <= 5'd15; 
                    AluResultSrc <= 3'd1; 
                    start_mul    <= 1'b0; 
                    start_fft    <= 1'b1; 
                    start_div    <= 1'b0;
                    start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                    branch       <= 1'b0; 
                    state        <= 2'd1; 
                    tick_ex         <= 1'b0; 
                    last_fft     <= 1'b0; 
                    last_fp_add<=1'b0;  last_fp_mul<=1'b0;
                    end 
                end 
                else if (state == 2'd1) begin 
                    //AluEn <= 1'b1; 
                    start_fft    <= 1'b0; 
                    AluEn        <= 1'b0;  
                    AluSrcA      <= 1'b0; 
                    AluSrcB      <= 3'd1; 
                    AluControl   <= 5'd15; 
                    if (fft_done) begin 
                        tick_ex  <= 1'b1; 
                        AluEn <= 1'b1; 
                        state <= 2'd0; 
                        last_fft <=1'b1; 
                    end 
                end 
            end 
            
            
            default: begin 
                if(state == 2'd0)  
                    begin 
                        AluEn        <= 1'b1; 
                        AluSrcA      <= 1'b1; 
                        AluSrcB      <= 3'd0; 
                        AluResultSrc <= 3'd0; 
                        start_mul    <= 1'b0; 
                        start_fft    <= 1'b0; 
                        start_div    <= 1'b0;
                        branch       <= 1'b0; 
                        state        <= 2'd1; 
                        tick_ex      <= 1'b0; 
                        AluControl   <= 15'd0; 
                        
                    end 
                if(state == 2'd1) 
                    begin 
                        AluEn        <= 1'b1; 
                        AluSrcA      <= 1'b0; 
                        AluSrcB      <= 3'd1; 
                        AluControl   <= 5'd15; 
                        AluResultSrc <= 3'b0; 
                        start_mul    <= 1'b0; 
                        start_fft    <= 1'b0; 
                        start_div    <= 1'b0;
                        start_fp_add <= 1'b0; start_fp_mul <= 1'b0;
                        branch       <= 1'b0; 
                        state        <= 2'd0; 
                        tick_ex         <= 1'b1; 
                    end 
                end 

            endcase 
        end   
    end 


    // ---------- Memory FSM ------------------------------------------
    
    always @(*) 
    begin 
        if((i_mem[6:0] == 7'b0000011) || (i_mem[6:0] == 7'b0100011)) // load and store instruction 
        begin 
            if(trans_done) begin tick_mem = 1'b1; end 
            else begin tick_mem = 1'b0; end 
        end 
        else  
        begin 
            tick_mem = 1'b1; 
        end 
    end   

endmodule
