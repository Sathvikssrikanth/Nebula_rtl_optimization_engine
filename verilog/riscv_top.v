/*  RISC-V top :
    Integrates all the modules in the RISC-V core
    CDC UPDATE: Core<->Multiplier crossing now goes through handshake_bridge
    + reset_sync instead of raw signal crossing. See u_bridge_core_to_mult /
    u_bridge_mult_to_core / u_rst_sync_md / u_rst_sync_core below.
*/

module riscv_top (
    input clk_md, //aditya
    input clk_fft, //aditya
    input clk_fp,
    input clk,
    input reset,

    // IRQ
    input spi_irq,
    input gpio_irq,
    output trap_busy,

    output [31:0] PC_out,
    input [31:0] instr_in,
    output ins_ena,

    // Data Memory   
    input [31:0] data_in,
    input trans_done,
    output  [31:0] data_addr,
    output  [31:0] data_out,
    output  data_wr_en,
    output  data_en,
        
    // Simulation
    output wire [31:0] i_decode,i_ex,i_mem,i_wb,   //Controller

    output wire RegWrEn_sim ,
    output wire [31:0] RD1_sim,RD2_sim ,RD3_sim ,RD4_sim ,WD5_sim,
    output wire [4:0] A1_sim,A2_sim ,A3_sim ,A4_sim ,A5_sim,        //RF

    output wire CSR_EN_sim ,CSR_WR_EN_sim,
    output wire [31:0] CSR_WD_sim,PC_NEXT_CSR_sim,CSR_Data_sim,
    output wire [11:0] CSR_Addr_sim,                                 //CSR

    output wire [31:0] SrcA_sim ,SrcB_sim, AluOp_sim,Next_PC_Alu_out_sim,    //ALU
    output wire [4:0] AluControl_sim,
    output wire [2:0] AluResultSrc,

    output wire [31:0] wb_data_sim,      //WB

    output wire start_mul_sim, mul_done_sim,
    output wire done_fft_sim, start_fft_sim,
    output wire start_div_sim,
    output wire div_done_sim //FFT, MUlt, Division
    
    );
 
    wire [31:0] pc_d;
    wire [1:0] ResultSrc;
    wire [31:0] wb_data;
    wire [31:0] CSR_Data_out,Next_PC_Alu;
    wire zero_out,sign_out;
    wire [1:0] fft_wb;
    wire start_mul, mul_busy,mul_done;
    wire start_div, div_busy,div_done;
    wire [2:0] func3;
    wire start_fp_mul ,fp_mul_busy,fp_mul_done;
    wire start_fp_add ,fp_add_busy,fp_add_done;

    wire [31:0] Mult_out,AluResult,Div_out,fp_mul_out,fp_add_out;
    wire branch_mux;
    wire [31:0] pc_e;
    wire [2:0]AluSrcB;
    wire AluSrcA;
    wire [31:0] z;
    wire [11:0] CSR_ADDR;

    wire [31:0] SrcA,SrcB,AluOp,Next_PC_Alu_out;
    wire [4:0] AluControl;
    wire zero,sign,AluEn;

    wire TICK;
    wire [31:0] muxB0,muxB2,muxB3,muxB4,muxB5,muxB6,muxB7,muxA1;
    wire [31:0] FFT3,FFT4;
    wire [11:0] I_TYPE,S_TYPE,B_TYPE;
    wire [19:0] J_TYPE,U_TYPE;

    wire CSR_EN,CSR_WR_EN,mret,INS_COM,wb_valid,trap,PC_src;
    wire [31:0] CSR_WD,PC_NEXT_CSR,CSR_Data;
    wire [11:0] CSR_Addr;
    wire RegWrEn;
    wire [31:0] RD1,RD2,RD3,RD4,WD5;
    wire [4:0] A1,A2,A3,A4,A5;
    wire [31:0] NEXT_PC;

    //Hazard

    wire [4:0] rs1_D,rs2_D,rs1_E,rs2_E,rd_E,rd_M,rd_W;
    wire [31:0] h1,h2,h3,h4;
    wire [1:0] fwdA, fwdB;
    wire stallF, flushPR1;
    
    // Forward declarations - actual drivers are the CDC bridge blocks further down
    wire [32:0] mult_result_core;
    wire [31:0] div_result_core;
    wire [31:0] fp_add_result_core;
    wire [31:0] fp_mul_result_core;
    reg  [31:0] fft_rd_data_core;
    // Instruction Memory
    
    assign data_en = 1'b1;
    
    wire clk_md_mul,clk_md_div;
    derive_clk_mu1_div  derive_clk_mu1_div (
    .clk_md(clk_md),  // input clock
    .reset(reset),        // synchronous reset (active high)
    .clk_md_mul(clk_md_mul),      // clk = input / 2
    .clk_md_div(clk_md_div)       // clk = input / 4
);

    wire clk_fft_main,clk_fft_core;
    clk_div_fft clk_div_fft(
    .reset(reset),
    .clk_fft(clk_fft),
    .clk_fft_main(clk_fft_main),
    .clk_fft_core(clk_fft_core)
);
    wire clk_fp_add, clk_fp_mul;
    clk_fp_divider clk_fp_divider (
        .clk_fp(clk_fp),   // input clock
        .rst(reset),      // synchronous reset
        .clk_fp_add(clk_fp_add), // half frequency
        .clk_fp_mul(clk_fp_mul)  // quarter frequency
    );
    
    
    // Program Counter
    PC PC_inst (
        .clk(clk),
        .reset(reset),
        .PC_next_in(NEXT_PC),
        .stall(stallF),
        .pc(PC_out)
    );
        
    
    // Register File
    register_file register_file (
        .clk(clk),
        .rst(reset),
    
        .we(RegWrEn),
        .a5(A5),     
        .wd(WD5),    

        .a1(A1),
        .a2(A2),
        .a3(A3),
        .a4(A4),
        
        .rd1(RD1),
        .rd2(RD2),
        .rd3(RD3),
        .rd4(RD4)
        );
     
 
    // CSR Register
    CSR CSR_Register (
        .CSR_EN(CSR_EN),
        .CSR_WR_EN(CSR_WR_EN),
        .pc(PC_out),
        .CSR_WD(CSR_WD),
        .mret(mret),
        .INS_COM(wb_valid),
        .CSR_addr(CSR_Addr),
        .clk(clk),
        .trap(trap),
        .reset(reset),
        .PC_src(PC_src),
        .pc_next(PC_NEXT_CSR),
        .CSR_DATA(CSR_Data)
        //.spi_q(spi_irq),
        //.gpio_q(gpio_irq)
    );  
    
    // Pipeline Register 1
    pipeline_reg1 pipeline_reg1 (
        .clk(clk),
        .reset(reset),
        .tick_in(TICK),
        .I_TYPE_in(I_TYPE),
        .S_TYPE_in(S_TYPE),
        .B_TYPE_in(B_TYPE),
        .J_TYPE_in(J_TYPE),
        .U_TYPE_in(U_TYPE),
        .CSR_Data_in(CSR_Data),
        .RD1_in(RD1),
        .RD2_in(RD2),
        .RD3_in(RD3),
        .RD4_in(RD4),
        .pc_d(pc_d),
        .I_TYPE_out(muxB3),
        .S_TYPE_out(muxB4),
        .B_TYPE_out(muxB5),
        .J_TYPE_out(muxB6),
        .U_TYPE_out(muxB7),
        .CSR_Data_out(muxB2),
        .RD1_out(muxA1),
        .RD2_out(muxB0),
        .RD3_out(FFT3),
        .RD4_out(FFT4) ,
        .pc_e(pc_e)
        );
    
    // ALU 
    alu ALU (
        .clk(clk),
        .reset(reset),
        .tick_in(TICK),
        .src_a(SrcA),
        .src_b(SrcB),
        .alu_ctrl(AluControl),
        .alu_en(AluEn),
        .alu_result(AluOp),
        .next_pc(Next_PC_Alu_out),
        .zero_flag(zero),
        .sign_flag(sign)
        );

    // Mux1
    M1 Mux1 ( 
        .CSR_WR_EN(CSR_WR_EN),
        .INS(I_TYPE),
        .CSR_ADDR(CSR_ADDR),
        .CSR_Addr(CSR_Addr)
        );
    
    // Mux2
     M2 mux2 (   
        .RS1(h1),
        .PC(z),
        .ALUSrcA(AluSrcA),
        .SrcA(SrcA)
        );
    
    // Mux 7
     M7 mux7 ( 
        .x(PC_out),
        .y(pc_d),
        .branch_mux(branch_mux),
        .z(z)
        );


    //HAZARD UNIT MUX
    //fwdA
    M4 M8 (
        .AluResultSrc(fwdA),
        .AluOp(muxA1),
        .FFT_rd_data(h3),
        .Mult_rd_data(h4),
        .Alu_result(h1),
        .Div_rd_data(h4)
       
        );

    //fwdB

    M4 M9 (
        .AluResultSrc(fwdB),
        .AluOp(muxB0),
        .FFT_rd_data(h3),
        .Mult_rd_data(h4),
        .Div_rd_data(h4),
        .Alu_result(h2)
       
        );

    // Mux3
    M3 mux3 (    
        .AluSrcB(AluSrcB),
        .RS2(h2),
        .CSR_Data_Reg(muxB2),
        .I_Reg(muxB3),
        .S_Reg(muxB4),
        .B_Reg(muxB5),
        .J_Reg(muxB6),
        .U_Reg(muxB7),
        .SrcB(SrcB)
        );
    
    // Mux4
    mux8_1 mux8_1 (    
        .AluResultSrc(AluResultSrc),
        .AluOp(AluOp),
        .FFT_rd_data(fft_rd_data_core),
        .Mult_rd_data(mult_result_core),
        .Alu_result(AluResult),
        .Div_rd_data(div_result_core),
        .FP_Mul_result(fp_mul_result_core),
        .FP_Add_result(fp_add_result_core)
        );

    // -----------------------------------------------------------------
    // CDC: Core (clk) <-> Multiplier (clk_md_mul)
    // -----------------------------------------------------------------

    // Reset synchronizers - one per domain touched by this crossing
    wire rst_md_n;
    reset_sync u_rst_sync_md (
        .clk        (clk_md_mul),
        .arst_n     (~reset),
        .rst_sync_n (rst_md_n)
    );

    wire rst_core_n;
    reset_sync u_rst_sync_core (
        .clk        (clk),
        .arst_n     (~reset),
        .rst_sync_n (rst_core_n)
    );

    // Core -> Mult: pack rs1_data(h1) + rs2_data(h2) + func3, gated by start_mul
    wire [66:0] mult_req_data_a = {h1, h2, func3};   // 32+32+3 = 67 bits
    wire        mult_req_busy;                        // drives controller's mul_busy
    wire [66:0] mult_req_data_b;
    wire        mult_start_md;

    handshake_bridge #(.WIDTH(67)) u_bridge_core_to_mult (
        .clka      (clk),
        .rst_a_n   (rst_core_n),
        .data_in   (mult_req_data_a),
        .valid_in  (start_mul),
        .busy_out  (mult_req_busy),

        .clkb      (clk_md_mul),
        .rst_b_n   (rst_md_n),
        .data_out  (mult_req_data_b),
        .valid_out (mult_start_md)
    );

    wire [31:0] rs1_md   = mult_req_data_b[66:35];
    wire [31:0] rs2_md   = mult_req_data_b[34:3];
    wire [2:0]  func3_md = mult_req_data_b[2:0];

    wire [31:0] mult_result_md;
    wire        mult_busy_md, mult_done_md;

    // Multiplier
    Multiplier multiplier (
        .clk_md_mul (clk_md_mul), //aditya
        .rst        (~rst_md_n),

        .start_mul  (mult_start_md),
        .rs1_data   (rs1_md),
        .rs2_data   (rs2_md),
        .func3      (func3_md),

        .result     (mult_result_md),
        .mul_busy   (mult_busy_md),
        .mul_done   (mult_done_md)
        );

    // Mult -> Core: result, gated by mult_done_md
    //wire [31:0] mult_result_core;
    wire        mul_done_synced;

    handshake_bridge #(.WIDTH(32)) u_bridge_mult_to_core (
        .clka      (clk_md_mul),
        .rst_a_n   (rst_md_n),
        .data_in   (mult_result_md),
        .valid_in  (mult_done_md),
        .busy_out  (),

        .clkb      (clk),
        .rst_b_n   (rst_core_n),
        .data_out  (mult_result_core),
        .valid_out (mul_done_synced)
    );

    // Outstanding-op latch: bridge's busy_out only covers the request
    // handshake, not the full compute+response duration. Controller needs
    // to stall until the result actually comes back.
    reg mult_op_outstanding;
    always @(posedge clk or negedge rst_core_n) begin
        if (!rst_core_n)
            mult_op_outstanding <= 1'b0;
        else if (start_mul)
            mult_op_outstanding <= 1'b1;
        else if (mul_done_synced)
            mult_op_outstanding <= 1'b0;
    end
    // -----------------------------------------------------------------

    // -----------------------------------------------------------------
    // CDC: Core (clk) <-> Divider (clk_md_div)
    // -----------------------------------------------------------------
    wire rst_div_n;
    reset_sync u_rst_sync_div (
        .clk        (clk_md_div),
        .arst_n     (~reset),
        .rst_sync_n (rst_div_n)
    );

    // Core -> Divider
    wire [66:0] div_req_data_a = {h1, h2, func3};
    wire        div_req_busy;                // -> controller's div_busy
    wire [66:0] div_req_data_b;
    wire        div_start_md;

    handshake_bridge #(.WIDTH(67)) u_bridge_core_to_div (
        .clka      (clk),
        .rst_a_n   (rst_core_n),   // reuse core reset_sync from Mult crossing
        .data_in   (div_req_data_a),
        .valid_in  (start_div),
        .busy_out  (div_req_busy),

        .clkb      (clk_md_div),
        .rst_b_n   (rst_div_n),
        .data_out  (div_req_data_b),
        .valid_out (div_start_md)
    );

    wire [31:0] rs1_div_md   = div_req_data_b[66:35];
    wire [31:0] rs2_div_md   = div_req_data_b[34:3];
    wire [2:0]  func3_div_md = div_req_data_b[2:0];

    wire [31:0] div_result_md;
    wire        div_busy_md, div_done_md;

     divider divider (
        .clk_md_div(clk_md_div), //aditya
        .rst(~rst_div_n),
    
        .start_div(div_start_md),
        .rs1_data(rs1_div_md),
        .rs2_data(rs2_div_md),
        .func3(func3_div_md),
    
        .result(div_result_md),
        .div_busy(div_busy_md),
        .div_done(div_done_md)
        );

    // Divider -> Core: result
    //wire [31:0] div_result_core;
    wire        div_done_synced;

    handshake_bridge #(.WIDTH(32)) u_bridge_div_to_core (
        .clka      (clk_md_div),
        .rst_a_n   (rst_div_n),
        .data_in   (div_result_md),
        .valid_in  (div_done_md),
        .busy_out  (),

        .clkb      (clk),
        .rst_b_n   (rst_core_n),
        .data_out  (div_result_core),
        .valid_out (div_done_synced)
    );

    // Outstanding-op latch: same reasoning as mult_op_outstanding above.
    reg div_op_outstanding;
    always @(posedge clk or negedge rst_core_n) begin
        if (!rst_core_n)
            div_op_outstanding <= 1'b0;
        else if (start_div)
            div_op_outstanding <= 1'b1;
        else if (div_done_synced)
            div_op_outstanding <= 1'b0;
    end
    // -----------------------------------------------------------------
        
    // -----------------------------------------------------------------
    // CDC: Core (clk) <-> FP Adder (clk_fp_add)
    // -----------------------------------------------------------------
    wire rst_fp_add_n;
    reset_sync u_rst_sync_fp_add (
        .clk        (clk_fp_add),
        .arst_n     (~reset),
        .rst_sync_n (rst_fp_add_n)
    );

    wire [63:0] fp_add_req_data_a = {h1, h2};
    wire        fp_add_req_busy;
    wire [63:0] fp_add_req_data_b;
    wire        fp_add_start_b;

    handshake_bridge #(.WIDTH(64)) u_bridge_core_to_fp_add (
        .clka      (clk),
        .rst_a_n   (rst_core_n),
        .data_in   (fp_add_req_data_a),
        .valid_in  (start_fp_add),
        .busy_out  (fp_add_req_busy),

        .clkb      (clk_fp_add),
        .rst_b_n   (rst_fp_add_n),
        .data_out  (fp_add_req_data_b),
        .valid_out (fp_add_start_b)
    );

    wire [31:0] fp_add_A_b = fp_add_req_data_b[63:32];
    wire [31:0] fp_add_B_b = fp_add_req_data_b[31:0];

    wire [31:0] fp_add_result_b;
    wire        fp_add_busy_b, fp_add_done_b;

    FP_Adder FP_Adder (
    .clk(clk_fp_add),
    .rst(~rst_fp_add_n),    // synchronous, active-high
    .A(fp_add_A_b),
    .B(fp_add_B_b),
    .start_FP_Add(fp_add_start_b),   // pulse: inputs valid
    .FP_Add_Busy(fp_add_busy_b),    // high while adding
    .FP_Add_result(fp_add_result_b),
    .FP_Add_Ready(fp_add_done_b)   // pulse: result valid
        );

    //wire [31:0] fp_add_result_core;
    wire        fp_add_done_synced;

    handshake_bridge #(.WIDTH(32)) u_bridge_fp_add_to_core (
        .clka      (clk_fp_add),
        .rst_a_n   (rst_fp_add_n),
        .data_in   (fp_add_result_b),
        .valid_in  (fp_add_done_b),
        .busy_out  (),

        .clkb      (clk),
        .rst_b_n   (rst_core_n),
        .data_out  (fp_add_result_core),
        .valid_out (fp_add_done_synced)
    );

    reg fp_add_op_outstanding;
    always @(posedge clk or negedge rst_core_n) begin
        if (!rst_core_n)
            fp_add_op_outstanding <= 1'b0;
        else if (start_fp_add)
            fp_add_op_outstanding <= 1'b1;
        else if (fp_add_done_synced)
            fp_add_op_outstanding <= 1'b0;
    end
    // -----------------------------------------------------------------

    // -----------------------------------------------------------------
    // CDC: Core (clk) <-> FP Multiplier (clk_fp_mul)
    // -----------------------------------------------------------------
    wire rst_fp_mul_n;
    reset_sync u_rst_sync_fp_mul (
        .clk        (clk_fp_mul),
        .arst_n     (~reset),
        .rst_sync_n (rst_fp_mul_n)
    );

    wire [63:0] fp_mul_req_data_a = {h1, h2};
    wire        fp_mul_req_busy;
    wire [63:0] fp_mul_req_data_b;
    wire        fp_mul_start_b;

    handshake_bridge #(.WIDTH(64)) u_bridge_core_to_fp_mul (
        .clka      (clk),
        .rst_a_n   (rst_core_n),
        .data_in   (fp_mul_req_data_a),
        .valid_in  (start_fp_mul),
        .busy_out  (fp_mul_req_busy),

        .clkb      (clk_fp_mul),
        .rst_b_n   (rst_fp_mul_n),
        .data_out  (fp_mul_req_data_b),
        .valid_out (fp_mul_start_b)
    );

    wire [31:0] fp_mul_A_b = fp_mul_req_data_b[63:32];
    wire [31:0] fp_mul_B_b = fp_mul_req_data_b[31:0];

    wire [31:0] fp_mul_result_b;
    wire        fp_mul_busy_b, fp_mul_done_b;

    FP_Mult FP_Mult (
    .clk(clk_fp_mul),
    .rst(~rst_fp_mul_n),    // synchronous, active-high
    .A(fp_mul_A_b),
    .B(fp_mul_B_b),
    .start_FP_Mul(fp_mul_start_b),   // pulse: inputs valid
    .FP_Mul_Busy(fp_mul_busy_b),    // high while multiplying
    .FP_Mul_result(fp_mul_result_b),
    .FP_Mul_Ready(fp_mul_done_b)   // pulse: result valid
        );

    //wire [31:0] fp_mul_result_core;
    wire        fp_mul_done_synced;

    handshake_bridge #(.WIDTH(32)) u_bridge_fp_mul_to_core (
        .clka      (clk_fp_mul),
        .rst_a_n   (rst_fp_mul_n),
        .data_in   (fp_mul_result_b),
        .valid_in  (fp_mul_done_b),
        .busy_out  (),

        .clkb      (clk),
        .rst_b_n   (rst_core_n),
        .data_out  (fp_mul_result_core),
        .valid_out (fp_mul_done_synced)
    );

    reg fp_mul_op_outstanding;
    always @(posedge clk or negedge rst_core_n) begin
        if (!rst_core_n)
            fp_mul_op_outstanding <= 1'b0;
        else if (start_fp_mul)
            fp_mul_op_outstanding <= 1'b1;
        else if (fp_mul_done_synced)
            fp_mul_op_outstanding <= 1'b0;
    end
    // -----------------------------------------------------------------
    
    // -----------------------------------------------------------------
    // CDC: Core (clk) <-> FFT (clk_fft domain)
    //
    // clk_fft_core is clk_fft passed through; clk_fft_main is a synchronous
    // divide-by-2 of it. So the two FFT clocks are synchronous to each other
    // and only ONE reset_sync / bridge pair is needed against the core.
    // The fft_wb readback mux now lives here, in the core domain, operating
    // on the already-synchronised 128-bit result.
    // -----------------------------------------------------------------
    wire rst_fft_n;
    reset_sync u_rst_sync_fft (
        .clk        (clk_fft_main),
        .arst_n     (~reset),
        .rst_sync_n (rst_fft_n)
    );

    wire [127:0] fft_req_data_a = {muxA1, muxB0, FFT3, FFT4};
    wire         fft_req_busy;
    wire [127:0] fft_req_data_b;
    wire         fft_start_b;

    handshake_bridge #(.WIDTH(128)) u_bridge_core_to_fft (
        .clka      (clk),
        .rst_a_n   (rst_core_n),
        .data_in   (fft_req_data_a),
        .valid_in  (start_fft),
        .busy_out  (fft_req_busy),

        .clkb      (clk_fft_main),
        .rst_b_n   (rst_fft_n),
        .data_out  (fft_req_data_b),
        .valid_out (fft_start_b)
    );

    wire [127:0] fft_y_all;
    wire         fft_busy_b, fft_done_b;

    fft_top fft (
        .clk_fft_main(clk_fft_main),
        .clk_fft_core(clk_fft_core),
        .reset(~rst_fft_n),
        .start(fft_start_b),
        .rs1_data(fft_req_data_b[127:96]),
        .rs2_data(fft_req_data_b[95:64]),
        .rs3_data(fft_req_data_b[63:32]),
        .rs4_data(fft_req_data_b[31:0]),
        .y_all(fft_y_all),
        .busy(fft_busy_b),
        .done(fft_done_b),
        .compute_start()
        );

    wire [127:0] fft_result_core;
    wire         fft_done_synced;

    handshake_bridge #(.WIDTH(128)) u_bridge_fft_to_core (
        .clka      (clk_fft_main),
        .rst_a_n   (rst_fft_n),
        .data_in   (fft_y_all),
        .valid_in  (fft_done_b),
        .busy_out  (),

        .clkb      (clk),
        .rst_b_n   (rst_core_n),
        .data_out  (fft_result_core),
        .valid_out (fft_done_synced)
    );

    // fft_wb readback mux - core domain, no crossing
    //reg [31:0] fft_rd_data_core;
    always @(*) begin
        case (fft_wb)
            2'b00: fft_rd_data_core = fft_result_core[127:96];  // {y0,y1}
            2'b01: fft_rd_data_core = fft_result_core[95:64];   // {y2,y3}
            2'b10: fft_rd_data_core = fft_result_core[63:32];   // {y4,y5}
            2'b11: fft_rd_data_core = fft_result_core[31:0];    // {y6,y7}
            default: fft_rd_data_core = 32'd0;
        endcase
    end

    reg fft_op_outstanding;
    always @(posedge clk or negedge rst_core_n) begin
        if (!rst_core_n)
            fft_op_outstanding <= 1'b0;
        else if (start_fft)
            fft_op_outstanding <= 1'b1;
        else if (fft_done_synced)
            fft_op_outstanding <= 1'b0;
    end
    // -----------------------------------------------------------------
       
                
    // Pipeline Register 2
    pipeline_reg2 pipeline_reg2 (
        .clk(clk),
        .reset(reset),
        .tick_in(TICK),
        .zero_in(zero),
        .sign_in(sign),
        .Alu_Result_in(AluResult),
        .Next_PC_in(Next_PC_Alu_out),
        .RS2_in(h2),
        .CSR_Data_in(muxB2),
        .branch(branch_mux),
        .zero_out(zero_out),
        .sign_out(sign_out),
        .Alu_Result_out(data_addr),
        .Next_PC_out(Next_PC_Alu),
        .RS2_out(data_out),
        .CSR_Data_out(CSR_Data_out)
        );


    // Mux5 
    M5 mux5 (
        .ResultSrc(ResultSrc),
        .Alu_result(data_addr),
        .RD(data_in),
        .CSR_Data_Reg(CSR_Data_out),
        .wb_data(wb_data)
        );
    
    // Mux6
    M6 mux6 (
        .PC_Src(PC_src),
        .Next_PC_Reg(Next_PC_Alu),
        .Next_PC_CSR(PC_NEXT_CSR),
        .NEXT_PC(NEXT_PC)
        );
    
    //
    pipeline_reg3 pipeline_register3 (
        .clk(clk),
        .reset(reset),
        .tick_in(TICK),
        .wb_data_in(wb_data),
        .csr_wb_in(data_addr),
        .wb_data_out(WD5),
        .csr_wb_out(CSR_WD),
        .stall(stallF)
        );       
    
    // Controller
    controller controller (
        .opcode(instr_in),
        
        .clk(clk),
        .reset(reset),
        .flush(flushPR1),
        
        .zero(zero),
        .sign(sign),
        
        .mul_done(mul_done_synced),
        .mul_busy(mult_op_outstanding),
        
        .fft_done(fft_done_synced),
        .fft_busy(fft_op_outstanding),
        
        .div_busy(div_op_outstanding),
        .div_done(div_done_synced),
        .start_div(start_div),
        
        .start_fp_mul(start_fp_mul),
        .fp_mul_busy(fp_mul_op_outstanding),
        .fp_mul_done(fp_mul_done_synced),
        
        .start_fp_add(start_fp_add),
        .fp_add_busy(fp_add_op_outstanding),
        .fp_add_done(fp_add_done_synced),
    

        .spi_irq(spi_irq),
        .gpio_irq(gpio_irq),
        
        .pc_in(PC_out),
        .pc_d(pc_d),
        .BRANCH_MUX(branch_mux),
        //DECODE STAGE
        .A1(A1),
        .A2(A2),
        .A3(A3),
        .A4(A4),
        
        .I_TYPE(I_TYPE),
        .S_TYPE(S_TYPE),
        .B_TYPE(B_TYPE),
        .J_TYPE(J_TYPE),
        .U_TYPE(U_TYPE),
        .CSR_Addr(CSR_ADDR),
        
        //EXCEUTE STAGE
        .AluSrcA(AluSrcA),
        .AluSrcB(AluSrcB),
        .AluControl(AluControl),
        .AluResultSrc(AluResultSrc),
        //output reg PcResEn,
        //output reg AluResEn,
        .AluEn(AluEn),

        //Multiplier
        .start_mul(start_mul),
        .func3(func3),
        // FFT 
        .start_fft(start_fft),
        .fft_wb(fft_wb),
        
        // MEMORY STAGE
        .MemWrEn(data_wr_en),
        .ResultSrc(ResultSrc),
        .trans_done(trans_done),
        
        // CSR
        .CsrWrEn(CSR_WR_EN),
        .CsrEn(CSR_EN),
        .wb_valid(wb_valid),
        .trap(trap),
        .mret(mret),
        .trap_busy(trap_busy),
        
        //WRITE BACK STAGE
        .RegWrEn(RegWrEn),
        .A5(A5),

        .tick(TICK)  ,
        .i_decode(i_decode),
        .i_ex(i_ex),
        .i_mem(i_mem),
        .i_wb(i_wb),

        // HAZARD UNI
        .rs1_d(rs1_D),
        .rs2_d(rs2_D),
        .rs1_e(rs1_E),
        .rs2_e(rs2_E),
        .rd_e(rd_E),
        .rd_m(rd_M),
        .rd_w(rd_W),
        .rs1_d_valid(rs1_Dvalid),
        .rs2_d_valid(rs2_Dvalid),
        .rs1_e_valid(rs1_Evalid),
        .rs2_e_valid(rs2_Evalid),
        .rd_e_valid(rd_Evalid),
        .rd_m_valid(rd_Mvalid),
        .rd_w_valid(rd_Wvalid),
        .memread(MemRead),
        
        
        .ins_ena(ins_ena),
        .stall(stallF)
        );

    //Hazard unit

    assign h3 = data_addr;
    assign h4 = WD5;

    hazard H (
        .rs1_D(rs1_D),
        .rs2_D(rs2_D),
        .rs1_Dvalid(rs1_Dvalid),
        .rs2_Dvalid(rs2_Dvalid),
        .rs1_E(rs1_E),
        .rs2_E(rs2_E),
        .rd_E(rd_E),
        .rs1_Evalid(rs1_Evalid),
        .rs2_Evalid(rs2_Evalid),
        .rd_Evalid(rd_Evalid),
        .MemRead(MemRead),
        .rd_M(rd_M),
        .rd_Mvalid(rd_Mvalid),
        .rd_W(rd_W),
        .rd_Wvalid(rd_Wvalid),
        .fwdA(fwdA),
        .fwdB(fwdB),
        .stallF(stallF),
        .flushPR1(flushPR1)
        );

    assign RegWrEn_sim = RegWrEn;
    assign RD1_sim = RD1;
    assign RD2_sim = RD2;
    assign RD3_sim  = RD3;
    assign RD4_sim = RD4;
    assign WD5_sim = WD5;
    assign A1_sim = A1;
    assign A2_sim = A2;
    assign A3_sim = A3;
    assign A4_sim = A4;
    assign A5_sim = A5;

    assign CSR_Data_sim = CSR_Data;
    assign CSR_Addr_sim = CSR_Addr;
    assign CSR_EN_sim = CSR_EN;
    assign CSR_WR_EN_sim = CSR_WR_EN; 
    assign CSR_WD_sim = CSR_WD;
    assign PC_NEXT_CSR_sim = PC_NEXT_CSR;

    assign SrcA_sim = SrcA;
    assign SrcB_sim =  SrcB;
    assign AluOp_sim = AluOp;
    assign Next_PC_Alu_out_sim = Next_PC_Alu_out;
    assign AluControl_sim = AluControl;
    assign AluResult_sim = AluResult;

    assign wb_data_sim = wb_data;

    assign start_mul_sim = start_mul;
    assign mul_done_sim = mul_done_synced;
    
    assign start_div_sim = start_div;
    assign div_done_sim  = div_done_synced;

    assign start_fft_sim = start_fft;
    assign done_fft_sim = fft_done_synced;

endmodule
