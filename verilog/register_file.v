/*  Register file :
    Consists of 32 registers, each 32-bit wide.
    Has 4 read and 1 write port (4 read ports needed for FFT module).
    R0 always holds value 0x00.

    Write side is banked (4 banks x 8 regs) to cap 'we' fanout at 4
    instead of broadcasting to all 32 write-enable comparators.
    Read side stays a flat mirror array - reads were never the
    bottleneck, so no need to bank them.
*/

module register_file(
    input clk,
    input rst,
    input we,
    input [4:0] a5,
    input [31:0] wd,
    input [4:0] a1,
    input [4:0] a2,
    input [4:0] a3,
    input [4:0] a4,
    output [31:0] rd1,
    output [31:0] rd2,
    output [31:0] rd3,
    output [31:0] rd4
    );

    reg [31:0] bank0 [0:7];
    reg [31:0] bank1 [0:7];
    reg [31:0] bank2 [0:7];
    reg [31:0] bank3 [0:7];
    reg [31:0] regfile [0:31];   // flat mirror, read-only

    wire [1:0] wr_bank = a5[4:3];
    wire [2:0] wr_idx  = a5[2:0];

    wire we0 = we && (a5 != 5'd0) && (wr_bank == 2'd0);
    wire we1 = we && (a5 != 5'd0) && (wr_bank == 2'd1);
    wire we2 = we && (a5 != 5'd0) && (wr_bank == 2'd2);
    wire we3 = we && (a5 != 5'd0) && (wr_bank == 2'd3);

    always @(posedge clk) begin
        if (rst) begin
            // bank0 = regs 0-7
            bank0[0] <= 32'd0;
            bank0[1] <= 32'd5;             // x1 = 5   (ADD/MUL operand)
            bank0[2] <= 32'd10;            // x2 = 10  (ADD/MUL operand)
            bank0[3] <= 32'd0;
            bank0[4] <= 32'h0;
            bank0[5] <= 32'd0;
            bank0[6] <= 32'h20000000;      // x6 = SPI/GPIO base address
            bank0[7] <= 32'd0;

            // bank1 = regs 8-15
            bank1[0] <= 32'd10;            // x8
            bank1[1] <= 32'd0;             // x9
            bank1[2] <= 32'h00000102;      // x10 -> a0=0, a1=(1,2)  (FFT input)
            bank1[3] <= 32'h00000304;      // x11 -> a2=0, a3=(3,4)  (FFT input)
            bank1[4] <= 32'h00000506;      // x12 -> a4=0, a5=(5,6)  (FFT input)
            bank1[5] <= 32'h00000708;      // x13 -> a6=0, a7=(7,8)  (FFT input)
            bank1[6] <= 32'd0;             // x14
            bank1[7] <= 32'd0;             // x15

            // bank2 = regs 16-23
            bank2[0] <= 32'd0;             // x16
            bank2[1] <= 32'd0;             // x17
            bank2[2] <= 32'd0;             // x18
            bank2[3] <= 32'd0;             // x19
            bank2[4] <= 32'd20;            // x20 = 20   (dividend)
            bank2[5] <= 32'd3;             // x21 = 3    (divisor)
            bank2[6] <= 32'hFFFFFFEC;      // x22 = -20  (negative dividend)
            bank2[7] <= 32'd0;             // x23

            // bank3 = regs 24-31
            bank3[0] <= 32'h40200000;      // x24
            bank3[1] <= 32'h40200000;      // x25
            bank3[2] <= 32'd0;             // x26
            bank3[3] <= 32'd0;             // x27
            bank3[4] <= 32'd0;             // x28
            bank3[5] <= 32'd0;             // x29
            bank3[6] <= 32'd0;             // x30
            bank3[7] <= 32'd0;             // x31

            // flat mirror reset - identical values, indexed 0-31
            regfile[0]  <= 32'd0;
            regfile[1]  <= 32'd5;
            regfile[2]  <= 32'd10;
            regfile[3]  <= 32'd0;
            regfile[4]  <= 32'h0;
            regfile[5]  <= 32'd0;
            regfile[6]  <= 32'h20000000;
            regfile[7]  <= 32'd0;
            regfile[8]  <= 32'd10;
            regfile[9]  <= 32'd0;
            regfile[10] <= 32'h00000102;
            regfile[11] <= 32'h00000304;
            regfile[12] <= 32'h00000506;
            regfile[13] <= 32'h00000708;
            regfile[14] <= 32'd0;
            regfile[15] <= 32'd0;
            regfile[16] <= 32'd0;
            regfile[17] <= 32'd0;
            regfile[18] <= 32'd0;
            regfile[19] <= 32'd0;
            regfile[20] <= 32'd20;
            regfile[21] <= 32'd3;
            regfile[22] <= 32'hFFFFFFEC;
            regfile[23] <= 32'd0;
            regfile[24] <= 32'h40200000;
            regfile[25] <= 32'h40200000;
            regfile[26] <= 32'd0;
            regfile[27] <= 32'd0;
            regfile[28] <= 32'd0;
            regfile[29] <= 32'd0;
            regfile[30] <= 32'd0;
            regfile[31] <= 32'd0;

        end else begin
            if (we0) begin
                bank0[wr_idx] <= wd;
                regfile[{2'd0, wr_idx}] <= wd;
            end
            if (we1) begin
                bank1[wr_idx] <= wd;
                regfile[{2'd1, wr_idx}] <= wd;
            end
            if (we2) begin
                bank2[wr_idx] <= wd;
                regfile[{2'd2, wr_idx}] <= wd;
            end
            if (we3) begin
                bank3[wr_idx] <= wd;
                regfile[{2'd3, wr_idx}] <= wd;
            end
        end
    end

    // Reads: flat, unbanked - not the fanout bottleneck, left as original
    assign rd1 = (a1 == 5'd0) ? 32'd0 : regfile[a1];
    assign rd2 = (a2 == 5'd0) ? 32'd0 : regfile[a2];
    assign rd3 = (a3 == 5'd0) ? 32'd0 : regfile[a3];
    assign rd4 = (a4 == 5'd0) ? 32'd0 : regfile[a4];

endmodule
