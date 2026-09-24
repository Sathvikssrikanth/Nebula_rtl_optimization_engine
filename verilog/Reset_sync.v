// reset_sync.v
// Async assert, synchronized deassert - one instance per clock domain.
module reset_sync (
    input  wire clk,
    input  wire arst_n,     // raw async reset in (active-low)
    output reg  rst_sync_n  // synchronized reset out (active-low)
);
    reg stage0_n;

    always @(posedge clk or negedge arst_n) begin
        if (!arst_n) begin
            stage0_n     <= 1'b0;
            rst_sync_n   <= 1'b0;
        end else begin
            stage0_n     <= 1'b1;
            rst_sync_n   <= stage0_n;
        end
    end
endmodule