/* Instruction memory */

`timescale 1ns / 1ps

module instr_mem(
    input reset_im,
    input clk,
    input  [31:0] addr,
    input wr_en_im,
    input [31:0] im_wr_addr,
    input [31:0] im_wr_inst,
    output [31:0] instr
    );
   
    wire [31:0] index_r;
    assign index_r = addr >> 2;

    wire [31:0] index_w;
    assign index_w = im_wr_addr >> 2;

    reg [31:0] mem [0:31];
    integer i;
    parameter NUM_INSTR = 32;        



    always@(posedge clk)
    begin
       /*  if (reset_im) begin
//            for (i = 0; i < NUM_INSTR; i = i + 1) begin
//                mem[i] <= 32'b0;
//            end

           mem[0] <= 32'h00100093;
            mem[1] <= 32'h00200113;
            mem[2] <= 32'h001101B3;
            mem[3] <= 32'h02210233;
            mem[4] <= 32'h001202B3;
            mem[5] <= 32'h00119333;
            mem[6] <= 32'h003263B3;
            mem[7] <= 32'h00309413;
            mem[8] <= 32'h00146493;
            mem[9] <= 32'h00240513;
            mem[10] <= 32'h003445B3;
            mem[11] <= 32'h00219613;
            mem[12] <= 32'h00164693;
            mem[13] <= 32'h02238733;
            mem[14] <= 32'h007407B3;
            mem[15] <= 32'h00311833;
            mem[16] <= 32'h00180893;
            mem[17] <= 32'h02248933;
            mem[18] <= 32'h003809B3;
            mem[19] <= 32'h00229A13;
            mem[20] <= 32'h001A0A93;
            mem[21] <= 32'h02258B33;
            mem[22] <= 32'h001B0BB3;
            mem[23] <= 32'h02260C33;
            mem[24] <= 32'h02528CB3;
            mem[25] <= 32'h001C8D13;
            mem[26] <= 32'h02348DB3;
            mem[27] <= 32'h02270E33;
            mem[28] <= 32'h001E0EB3;
            mem[29] <= 32'h02278F33;
            mem[30] <= 32'h00F86FB3;
            mem[31] <= 32'h0051F0B3;

            mem[32] <= 32'h0030A133;
            mem[33] <= 32'h0032A1B3;
            mem[34] <= 32'h0050B233;
            mem[35] <= 32'h0044B2B3;
            mem[36] <= 32'h00245333;
            mem[37] <= 32'h402453B3;
            mem[38] <= 32'hFF800513;
            mem[39] <= 32'h402555B3;
            mem[40] <= 32'h40448633;
            mem[41] <= 32'h409206B3;
            mem[42] <= 32'h0054F713;
            mem[43] <= 32'h00512793;
            mem[44] <= 32'h0054B813;
            mem[45] <= 32'h00513893;
            mem[46] <= 32'h0054B913;
            mem[47] <= 32'h00145993;
            mem[48] <= 32'h00245A13;
            mem[49] <= 32'h40155A93;
            mem[50] <= 32'h40145B13;

            mem[51] <= 32'h00001BB7;
            mem[52] <= 32'hABCDEC37;
            mem[53] <= 32'h00000C97;
            mem[54] <= 32'h00001D17;

            mem[55] <= 32'h00208663;
            mem[56] <= 32'h00700093;
            mem[57] <= 32'h00700113;
            mem[58] <= 32'h00700193;
            mem[59] <= 32'h00700213;
            mem[60] <= 32'h0140036F;
            mem[61] <= 32'h00D00093;
            mem[62] <= 32'h00D00113;
            mem[63] <= 32'h00D00193;
            mem[64] <= 32'h00D00213;

            mem[65] <= 32'h200000B7;
            mem[66] <= 32'h00F00113;
            mem[67] <= 32'h0020A023;
            mem[68] <= 32'h0220A923;
            mem[69] <= 32'h300000B7;
            mem[70] <= 32'h00000137;
            mem[71] <= 32'h0F200193;
            mem[72] <= 32'h0030A023;

            mem[73] <= 32'h300D1773;
            mem[74] <= 32'h00500513;
            mem[75] <= 32'h00500513;
            mem[76] <= 32'h00500513;
            mem[77] <= 32'h3006B7F3;
            mem[78] <= 32'h00500513;
            mem[79] <= 32'h00500513;
            mem[80] <= 32'h00500513;
            mem[81] <= 32'h300E2873;
            mem[82] <= 32'h00500513;
            mem[83] <= 32'h00500513;
            mem[84] <= 32'h00500513;

            mem[85] <= 32'h024382B3;
            mem[86] <= 32'h02438433;
            mem[87] <= 32'h02438633;
            mem[88] <= 32'h02438933;
            mem[89] <= 32'h024380B3;

            mem[90] <= 32'h00500E93;
            mem[91] <= 32'h00A00F13;
            mem[92] <= 32'h20000FB7;
            mem[93] <= 32'h01EFA023;
            mem[94] <= 32'h000FAF03;
            mem[95] <= 32'h000FA083;
            mem[96] <= 32'h01DFA023;
            mem[97] <= 32'h01EFA023;
            mem[98] <= 32'h01D1A023;
            mem[99] <= 32'h000FAF03;
            
            mem[100] <= 32'hF0064537;
            mem[101] <= 32'hA0D50513;   
            mem[102] <= 32'h1EE115B7;
            mem[103] <= 32'hD1E58593;
            mem[104] <= 32'hD415D637;
            mem[105] <= 32'h4EE60613;
            mem[106] <= 32'hC7EC36B7;
            mem[107] <= 32'hFEC68693;
            mem[108] <= 32'h00000093;
            mem[109] <= 32'h00000113;
            mem[110] <= 32'h0200008B;
            mem[111] <= 32'h0200110B;
            mem[112] <= 32'h0200218B;
            mem[113] <= 32'h0200320B;
            mem[114] <= 32'h00000093;
            mem[115] <= 32'h00000113;
            mem[116] <= 32'h30000337;
            mem[117] <= 32'h0F200293;
            mem[118] <= 32'h00532023;
            mem[119] <= 32'h00400293;
            mem[120] <= 32'h00532223; 
            mem[121] <= 32'h05A00293;
            mem[122] <= 32'h00532623;
            mem[123] <= 32'h01032283;
            mem[124] <= 32'h00000093;
            mem[125] <= 32'h00000113;
            mem[126] <= 32'h00000193;
            mem[127] <= 32'h00000213;
            mem[128] <= 32'h00000293;
            mem[129] <= 32'h00000313;
            mem[130] <= 32'h00000393;
            mem[131] <= 32'h00000413;
            mem[132] <= 32'h00000493;
            mem[133] <= 32'h00000513;
            mem[134] <= 32'h00000593;
            mem[135] <= 32'h00000613;
            mem[136] <= 32'h00000693;
            mem[137] <= 32'h00000713;
            mem[138] <= 32'h00000793;
            mem[139] <= 32'h00000813;
            mem[140] <= 32'h00000893;
            mem[141] <= 32'h00000913;
            mem[142] <= 32'h00000993;
            mem[143] <= 32'h00000A13;
            mem[144] <= 32'h00000A93;
            mem[145] <= 32'h00000B13;
            mem[146] <= 32'h00000B93;
            mem[147] <= 32'h00000C13;
            mem[148] <= 32'h00000C93;
            mem[149] <= 32'h00000D13;
            mem[150] <= 32'h00000D93;
            mem[151] <= 32'h00000E13;
            mem[152] <= 32'h00000E93;
            mem[153] <= 32'h00000F13;
            mem[154] <= 32'h00000F93;
            mem[153] <= 32'hD95FF16F; // infinite loop
            mem[154] <= 32'h00000000; // infinite loop
            mem[155] <= 32'h00000000; // infinite loop
            mem[156] <= 32'h00000000; // infinite loop
            mem[157] <= 32'h00000000; // infinite loop
        end */
        if (reset_im) begin
  //  for (i = 0; i < NUM_INSTR; i = i + 1) begin
    //    mem[i] <= 32'b0;
    // end

   
    mem[0] <= 32'h002081B3; // add  x3, x1, x2      -> x3 = x1+x2
    mem[1] <= 32'h00000013; // nop
   /* mem[2] <= 32'h022082B3; // mul  x5, x1, x2      -> x5 = x1*x2
    mem[3] <= 32'h00A00393; // addi x7, x0, 0xA     -> x7 = 0x0000000A
    mem[4] <= 32'h00000013; // nop
    mem[5] <= 32'h00000013; // nop
    mem[6] <= 32'h00732023; // sw   x7, 0(x6)       -> GPIO DATA_OUT = 0xA
    mem[7] <= 32'h00000063; // beq  x0, x0, 0       -> halt
        mem[8] <= 32'h00000063; // beq  x0, x0, 0       -> halt */
        
    
    /*mem[3] <= 32'h20000337; // lui  x6, 0x20000     -> x6 = 0x20000000
    mem[4] <= 32'h00A00393; // addi x7, x0, 0xA     -> x7 = 0x0000000A
    mem[5] <= 32'h00732023; // sw   x7, 0(x6)       -> GPIO DATA_OUT = 0xA*/
   
    mem[2] <= 32'h022082B3; // mul  x5, x1, x2      -> x5 = x1*x2
    mem[3]  <= 32'h035A4CB3;   // div x25, x20, x21   -> 20 / 3   = 6
    mem[4]  <= 32'h039c8cdb;   // Fp Mul x25,x25,x25    -> x25 =2.5
    mem[5] <= 32'h002081B3;   // add  x3, x1, x2        -> x3 = x1+x2
    mem[6]  <= 32'h038c0c2b;   // Fp Add x24,x24,x24    -> x24 =2.5
    mem[7] <= 32'h0200038B;   // fft  x7, fft_wb=00      -> x7 = {y0,y1}
    mem[8] <= 32'h00000063; // beq  x0, x0, 0       -> halt
    mem[9] <= 32'h00000063; // beq  x0, x0, 0       -> halt
  /* mem[3] <= 32'h20000337; // lui  x6, 0x20000     -> x6 = 0x20000000
    mem[4] <= 32'h00A00393; // addi x7, x0, 0xA     -> x7 = 0x0000000A
    mem[5] <= 32'h00732023; // sw   x7, 0(x6)       -> GPIO DATA_OUT = 0xA
    mem[6] <= 32'h00000063; // beq  x0, x0, 0       -> halt */
    //mem[3] <= 32'h022082B3;   // mul  x5, x1, x2         -> x5 = x1*x2
    //mem[4] <= 32'h0200038B;   // fft  x7, fft_wb=00      -> x7 = {y0,y1}
    //mem[4] <= 32'h00000013;   // nop  (addi x0,x0,0)
   //mem[5] <= 32'h00822023;   // lw   x9, 0(x4)          -> x9 = mem[x4]
    
    //mem[5]  <= 32'h035A4CB3;   // div x25, x20, x21   -> 20 / 3   = 6
    //mem[6]  <= 32'h035A6D33;   // rem x26, x20, x21   -> 20 % 3   = 2
    /*mem[3]  <= 32'h039c8cdb;   // Fp Mul x25,x25,x25    -> x25 =2.5 
    mem[4] <= 32'h002081B3;   // add  x3, x1, x2        -> x3 = x1+x2
    mem[5] <= 32'h002081B3;   // add  x3, x1, x2        -> x3 = x1+x2
    mem[6]  <= 32'h038c0c2b;   // Fp Add x24,x24,x24    -> x24 =2.5 
    mem[7] <= 32'h002081B3;   // add  x3, x1, x2        -> x3 = x1+x2
    mem[8] <= 32'h002081B3;   // add  x3, x1, x2        -> x3 = x1+x2
    mem[11]  <= 32'h035A4CB3;   // div x25, x20, x21   -> 20 / 3   = 6*/
    //mem[12]  <= 32'h035A6D33;   // rem x26, x20, x21   -> 20 % 3   = 2
    //mem[7] <= 32'h00000013;   // nop  (addi x0,x0,0)
    //mem[8] <= 32'h020A4EB3;   // div x29, x20, x0    -> 20 / 0   = -1 (div-by-zero path)
   /* mem[8]  <= 32'h035B4DB3;   // div x27, x22, x21   -> -20 / 3  = -6 
   // mem[3] <= 32'h05200293;   // addi x5, x0, 0x52    -> x5 = SPICR val (MSTR=1,SPE=1,SSOE=1)
    mem[4] <= 32'h00000013;   // nop (was: fft x7, fft_wb=00)
    mem[5] <= 32'h00532023;   // sw   x5, 0(x6)        -> SPICR = 0x52
    mem[6] <= 32'h05A00293;   // addi x5, x0, 0x5A     -> x5 = byte to transmit
    mem[7] <= 32'h00000013;   // nop                       (unchanged)
    mem[8] <= 32'h00532623;   // sw   x5, 12(x6)       -> SPI_TX_reg = 0x5A, triggers transfer 
    
    mem[9] <= 32'h00000063;   // beq x0, x0, 0       -> halt (shifted from mem[7]) */
    
    
    end
        else if (!reset_im && wr_en_im) begin
            mem[index_w] <= im_wr_inst;
        end
    end

    assign instr = mem[index_r];

endmodule