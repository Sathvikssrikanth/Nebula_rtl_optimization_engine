module data_mem(
    input clk, input rst, input mem_we,
    input [31:0] mem_wdata, input [12:0] mem_addr,
    output [31:0] mem_rdata, input mem_ena
    );

    reg [31:0] bank0 [0:63];
    reg [31:0] bank1 [0:63];
    reg [31:0] bank2 [0:63];
    reg [31:0] bank3 [0:63];
    integer i;

    wire [7:0] word_addr = mem_addr[7:0];
    wire [1:0] bank_sel  = word_addr[7:6];
    wire [5:0] bank_idx  = word_addr[5:0];

    wire wr0 = mem_ena && mem_we && (bank_sel==2'd0);
    wire wr1 = mem_ena && mem_we && (bank_sel==2'd1);
    wire wr2 = mem_ena && mem_we && (bank_sel==2'd2);
    wire wr3 = mem_ena && mem_we && (bank_sel==2'd3);

    always @(posedge clk) begin
        if (rst) begin
            for (i=0; i<64; i=i+1) begin
                bank0[i]<=32'b0; bank1[i]<=32'b0; bank2[i]<=32'b0; bank3[i]<=32'b0;
            end
        end else begin
            if (wr0) bank0[bank_idx] <= mem_wdata;
            if (wr1) bank1[bank_idx] <= mem_wdata;
            if (wr2) bank2[bank_idx] <= mem_wdata;
            if (wr3) bank3[bank_idx] <= mem_wdata;
        end
    end

    reg [31:0] bank_rdata;
    always @(*) begin
        case (bank_sel)
            2'd0: bank_rdata = bank0[bank_idx];
            2'd1: bank_rdata = bank1[bank_idx];
            2'd2: bank_rdata = bank2[bank_idx];
            2'd3: bank_rdata = bank3[bank_idx];
        endcase
    end

    assign mem_rdata = (mem_ena) ? bank_rdata : 32'd0;
endmodule
