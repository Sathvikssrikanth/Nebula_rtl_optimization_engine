/*  apb_cdc_bridge.v
    Clock-domain-crossing bridge for an APB transfer.

    Presents an APB SLAVE interface to the core-domain APB master, and an
    APB MASTER interface to the peripheral running in its own clock domain.

    The core-side master is stalled by holding pready_c low for the whole
    round trip - APB's own wait-state mechanism is exactly the right hook,
    so no extra buffering is needed.

    Data buses never cross by themselves: the request payload
    {pwrite, paddr, pwdata} and the response payload prdata are carried by
    handshake_bridge instances, which sync only the toggle control and hold
    the data stable across the boundary.

    One outstanding transfer at a time. APB is not pipelined, so that is
    sufficient.
*/

module apb_cdc_bridge (
    // ---------------- Core-side APB slave (clk_core) ----------------
    input  wire        clk_core,
    input  wire        rst_core_n,
    input  wire        psel_c,
    input  wire        penable_c,
    input  wire        pwrite_c,
    input  wire [31:0] paddr_c,
    input  wire [31:0] pwdata_c,
    output reg  [31:0] prdata_c,
    output reg         pready_c,

    // ------------- Peripheral-side APB master (clk_periph) ----------
    input  wire        clk_periph,
    input  wire        rst_periph_n,
    output reg         psel_p,
    output reg         penable_p,
    output wire        pwrite_p,
    output wire [31:0] paddr_p,
    output wire [31:0] pwdata_p,
    input  wire [31:0] prdata_p,
    input  wire        pready_p
);

    // ---------------- Request path: core -> peripheral ----------------
    wire [64:0] req_data_c = {pwrite_c, paddr_c, pwdata_c};
    reg         req_valid_c;
    wire        req_busy_c;

    wire [64:0] req_data_p;
    wire        req_valid_p;

    handshake_bridge #(.WIDTH(65)) u_req_bridge (
        .clka      (clk_core),
        .rst_a_n   (rst_core_n),
        .data_in   (req_data_c),
        .valid_in  (req_valid_c),
        .busy_out  (req_busy_c),

        .clkb      (clk_periph),
        .rst_b_n   (rst_periph_n),
        .data_out  (req_data_p),
        .valid_out (req_valid_p)
    );

    assign pwrite_p = req_data_p[64];
    assign paddr_p  = req_data_p[63:32];
    assign pwdata_p = req_data_p[31:0];

    // ---------------- Response path: peripheral -> core ----------------
    reg  [31:0] resp_data_p;
    reg         resp_valid_p;

    wire [31:0] resp_data_c;
    wire        resp_valid_c;

    handshake_bridge #(.WIDTH(32)) u_resp_bridge (
        .clka      (clk_periph),
        .rst_a_n   (rst_periph_n),
        .data_in   (resp_data_p),
        .valid_in  (resp_valid_p),
        .busy_out  (),

        .clkb      (clk_core),
        .rst_b_n   (rst_core_n),
        .data_out  (resp_data_c),
        .valid_out (resp_valid_c)
    );

    // ---------------- Core-side FSM ----------------
    localparam C_IDLE = 2'd0,
               C_REQ  = 2'd1,
               C_WAIT = 2'd2,
               C_ACK  = 2'd3;

    reg [1:0] c_state;

    always @(posedge clk_core or negedge rst_core_n) begin
        if (!rst_core_n) begin
            c_state     <= C_IDLE;
            req_valid_c <= 1'b0;
            pready_c    <= 1'b0;
            prdata_c    <= 32'd0;
        end else begin
            req_valid_c <= 1'b0;   // default: single-cycle pulse
            pready_c    <= 1'b0;   // default: stall the master

            case (c_state)

                C_IDLE: begin
                    // APB access phase seen and bridge free -> launch
                    if (psel_c && penable_c && !req_busy_c) begin
                        req_valid_c <= 1'b1;
                        c_state     <= C_REQ;
                    end
                end

                C_REQ: begin
                    c_state <= C_WAIT;
                end

                C_WAIT: begin
                    if (resp_valid_c) begin
                        prdata_c <= resp_data_c;
                        pready_c <= 1'b1;   // one-cycle ready, master completes
                        c_state  <= C_ACK;
                    end
                end

                C_ACK: begin
                    // hold here until the master drops psel, so we do not
                    // immediately re-trigger on the same transfer
                    if (!psel_c)
                        c_state <= C_IDLE;
                end

                default: c_state <= C_IDLE;

            endcase
        end
    end

    // ---------------- Peripheral-side FSM ----------------
    localparam P_IDLE   = 2'd0,
               P_SETUP  = 2'd1,
               P_ACCESS = 2'd2,
               P_RESP   = 2'd3;

    reg [1:0] p_state;

    always @(posedge clk_periph or negedge rst_periph_n) begin
        if (!rst_periph_n) begin
            p_state      <= P_IDLE;
            psel_p       <= 1'b0;
            penable_p    <= 1'b0;
            resp_valid_p <= 1'b0;
            resp_data_p  <= 32'd0;
        end else begin
            resp_valid_p <= 1'b0;   // default: single-cycle pulse

            case (p_state)

                P_IDLE: begin
                    psel_p    <= 1'b0;
                    penable_p <= 1'b0;
                    if (req_valid_p) begin
                        psel_p    <= 1'b1;   // APB setup phase
                        penable_p <= 1'b0;
                        p_state   <= P_SETUP;
                    end
                end

                P_SETUP: begin
                    penable_p <= 1'b1;       // APB access phase
                    p_state   <= P_ACCESS;
                end

                P_ACCESS: begin
                    // wait for the peripheral's own pready - may be many
                    // cycles (e.g. SPI TX-empty wait on register 0x0C)
                    if (pready_p) begin
                        resp_data_p  <= prdata_p;
                        resp_valid_p <= 1'b1;
                        psel_p       <= 1'b0;
                        penable_p    <= 1'b0;
                        p_state      <= P_RESP;
                    end
                end

                P_RESP: begin
                    p_state <= P_IDLE;
                end

                default: p_state <= P_IDLE;

            endcase
        end
    end

endmodule