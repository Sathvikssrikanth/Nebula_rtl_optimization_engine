// handshake_bridge.v
// Generic CDC data bridge: sync req/ack via toggle + 2FF, data held stable.
// Reusable for Core<->Mult, Core<->APB, etc.

module handshake_bridge #(
    parameter WIDTH = 8
)(
    // Sender side (clka domain)
    input  wire             clka,
    input  wire             rst_a_n,
    input  wire [WIDTH-1:0] data_in,
    input  wire             valid_in,   // pulse: "new data ready to send"
    output reg              busy_out,   // sender must wait if high

    // Receiver side (clkb domain)
    input  wire             clkb,
    input  wire             rst_b_n,
    output reg  [WIDTH-1:0] data_out,
    output reg              valid_out   // pulse: "new data arrived"
);

    // ---------------- Sender side ----------------
    reg              req_toggle;
    reg [WIDTH-1:0]  data_hold;

    reg ack_sync0, ack_sync1;   // 2FF sync of ack into clka domain

    always @(posedge clka or negedge rst_a_n) begin
        if (!rst_a_n) begin
            req_toggle <= 1'b0;
            data_hold  <= {WIDTH{1'b0}};
            busy_out   <= 1'b0;
        end else begin
            if (valid_in && !busy_out) begin
                data_hold  <= data_in;
                req_toggle <= ~req_toggle;
                busy_out   <= 1'b1;
            end else if (busy_out && (ack_sync1 == req_toggle)) begin
                // ack caught up with our latest request -> free to send again
                busy_out <= 1'b0;
            end
        end
    end

    // ---------------- Receiver side ----------------
    reg req_sync0, req_sync1;   // 2FF sync of req into clkb domain
    reg req_sync1_d;            // delayed copy to edge-detect
    reg ack_toggle;

    always @(posedge clkb or negedge rst_b_n) begin
        if (!rst_b_n) begin
            req_sync0   <= 1'b0;
            req_sync1   <= 1'b0;
            req_sync1_d <= 1'b0;
            ack_toggle  <= 1'b0;
            data_out    <= {WIDTH{1'b0}};
            valid_out   <= 1'b0;
        end else begin
            req_sync0   <= req_toggle;
            req_sync1   <= req_sync0;
            req_sync1_d <= req_sync1;

            if (req_sync1 != req_sync1_d) begin
                // new request detected -> data_hold is guaranteed stable
                data_out   <= data_hold;
                valid_out  <= 1'b1;
                ack_toggle <= ~ack_toggle;
            end else begin
                valid_out <= 1'b0;
            end
        end
    end

    // ---------------- Ack sync back to clka ----------------
    always @(posedge clka or negedge rst_a_n) begin
        if (!rst_a_n) begin
            ack_sync0 <= 1'b0;
            ack_sync1 <= 1'b0;
        end else begin
            ack_sync0 <= ack_toggle;
            ack_sync1 <= ack_sync0;
        end
    end

endmodule