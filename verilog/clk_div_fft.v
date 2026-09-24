`timescale 1ns / 1ps
module clk_div_fft(
    input  wire reset,
    input  wire clk_fft,
    output reg  clk_fft_main, // true divide by 4
    output wire clk_fft_core  // passthrough
);
    assign clk_fft_core = clk_fft;

    reg [1:0] div_cnt;
    always @(posedge clk_fft or posedge reset) begin
        if (reset) begin
            div_cnt      <= 2'b00;
            clk_fft_main <= 1'b0;
        end else begin
            div_cnt      <= div_cnt + 1'b1;
            clk_fft_main <= div_cnt[1];   // MSB toggles once per 4 cycles, 50% duty, true /4
        end
    end
endmodule
