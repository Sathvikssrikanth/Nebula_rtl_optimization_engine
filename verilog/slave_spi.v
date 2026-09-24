`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 12.04.2026 14:42:47
// Design Name: 
// Module Name: slave_spi
// Project Name: 
// Target Devices: 
// Tool Versions: 
// Description: 
// 
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
/////////////////////////////////////////////////////////////////////////////////

module slave_spi(
    output MOSI,  
    input MISO,  
//    inout SCK,
//    inout SS,
    input  SCK_i,
    output SCK_o,
    output SCK_oe,
    
    input  SS_i,
    output SS_o,
    output SS_oe,
   
    input system_clock,
    input reset,
    input SPI_select,
      
    input [31:0] address,
    input [31:0] data,
    output reg [31:0] rdata,
    input read_write,
    output reg pready,
    input penable,
    
    input RISCV_ready,
    input ack_spi,
    output SPI_interrupt,
    
    //VIO ports
    input [31:0] vio_tx_data,
    input        vio_tx_we,
    input [31:0] vio_cr_data,
    input        vio_cr_we
    );
    
    reg [31:0]SPICR; //   LOR_SPIE_SPE_SPTIE_MSTR_CPOL_CPHA_SSOE_LSBF
    reg [31:0]SPISR; //   SPIF_0_SPTEF_X_0_0_0_0   //read only
    reg [31:0]SPIBR; //   0_SPPR2_SPPR1_SPPR0_0_SPR2_SPR1_SPR0
    reg [31:0]SPI_TX_reg;
    reg [31:0]SPI_RX_reg;
    
    reg sample_reg; 
    reg [1:0] mode; 
    wire M_SS;
    wire [7:0] parallel_rx_wire;  
    
    assign SCK_oe = SPICR[4];
    assign SS_oe  = SPICR[4];
    assign SS_o = M_SS;
    
    wire active_ss  = SPICR[4] ? SS_o  : SS_i;
    wire active_sck = SPICR[4] ? SCK_o : SCK_i;

    
    //decoded logic used to enable Memory IO
    wire [15:0]reg_enable;
    ADD_DECO_slave init_reg(
                    .en(SPI_select),
                    .address(address[4:0]),
                    .out(reg_enable));
    
    //clock generator
    wire baud_clk;
    BAUD_GEN_slave init_BG(
                    .sys_clk(system_clock),
                    .reset(reset),
                    .SPPR(SPIBR[6:4]),
                    .SPR(SPIBR[2:0]),
                    .MSTR(SPICR[4]),
                    .SPE(SPICR[6]),
                    .baud_clk(baud_clk)
                    );
    
    //sample clock and shift clock
    wire shift_clk; wire sample_clk;
    PHASE_POLARITY_slave init_PP(
                    .baurd_clk(baud_clk),
                    .CPOL(SPICR[3]),
                    .CPHA(SPICR[2]),
                    .MSTR(SPICR[4]),
                    .SS(M_SS),
                    .sck_i(SCK_i),         
                    .sck_o(SCK_o),
                    .shift_clk(shift_clk),
                    .sample_clk(sample_clk)
                    ); 
    
    //system clock for slave to load the data
    wire ussr_clk; wire serial_tx_wire;
    //assign ussr_clk =SPICR[4]?shift_clk:(SS?system_clock:shift_clk);
    

    
    USR_slave init_USR(
                .clk(system_clock),
                .reset(reset),
                .enable(SPICR[6]),
                .mode(mode),
                .parallel_data(SPI_TX_reg[7:0]),
                .mux_in(sample_reg),
                .LSBF(SPICR[0]),
                .LOR(SPICR[8]),
                .SSOE(SPICR[1]),
                .SPICR_m(SPICR[4]),
                .shift_clk(shift_clk),
                .master_SS(M_SS),
                .mux_out(serial_tx_wire),
                .rx_data(parallel_rx_wire)
                );
     assign MOSI = active_ss ? 1'b1 : serial_tx_wire;        
    //sampling register
    always @(posedge sample_clk) begin
        if(reset)
            sample_reg<=0;
        else
            sample_reg<=MISO;
    end
    
    //transfer update
    wire transfer_active;
    EDGE_COUNTER_16_slave init_edge16(
                    .system_clk(system_clock),
                    .sck(active_sck),
                    .reset(reset),
                    .SS(active_ss),
                    //.SPIF(SPISR[7]),
                    .transfer_active(transfer_active)
                    );
                    
                    
//    //SS pin                
//    assign SS = SPICR[4] ? M_SS : 1'bz;                
                    
    parameter IDLE  = 2'b00;
    parameter LOAD  = 2'b01;
    parameter SHIFT = 2'b10;
    reg [1:0] state;
    
    parameter idle  = 2'b00;
    parameter load  = 2'b01;
    parameter shift = 2'b10;
    parameter wait_ss = 2'b11;
    reg [1:0] s_state;  
    
    //interupt handling 
    assign SPI_interrupt=RISCV_ready&&SPISR[7]&&SPICR[7];
  
    
    always@(*)begin
        if(read_write)begin
            if(penable)begin
                case(address[4:0])
                    5'h00: pready=(transfer_active)?0:1;
                    5'h04: pready=(transfer_active)?0:1;
                    5'h0C: pready=SPICR[5]&&SPISR[5];
                    default: pready=0;
                endcase
            end
        end
        else begin
            if(penable)begin
                pready=1;
            end
            else begin
                pready=0;
            end 
        end
    end
    //rdata
    always @(*) begin
    rdata = 32'h0;

        if (SPI_select && !read_write) begin
            case(address[4:0])
                5'h00: rdata = SPICR;
                5'h04: rdata = SPIBR;
                5'h08: rdata = SPISR;
                5'h0C: rdata = SPI_TX_reg;
                5'h10: rdata = SPI_RX_reg;
                default: rdata = 32'h0;
            endcase
        end
    end
    
    always @(posedge system_clock) begin
    if(reset) 
        begin
    
            SPICR <= 32'd4;        // CPHA = 1
            SPISR <= 32'd32;       // SPTEF = 1
            SPIBR <= 32'd0;
    
            SPI_RX_reg <= 32'b0;
            SPI_TX_reg <= 32'b0;
    
            mode   <= 2'b00;
            state  <= IDLE;
            s_state<= idle;
    
       end 
       else begin
//                if(SPI_select && read_write)//write registers
//                   begin
//                        if(reg_enable[0]) SPICR<=data;
//                        if(reg_enable[1]) SPIBR<=data;
//                        if(reg_enable[3]) 
//                            begin 
//                               SPI_TX_reg<=data;
//                               SPISR[5] <= 1'b0; 
//                               end          
//                end

                if (vio_cr_we) begin
                SPICR <= vio_cr_data;
                end
                else if(SPI_select && read_write && reg_enable[0]) begin
                    SPICR <= data; 
                end
    
                if (vio_tx_we) begin
                    SPI_TX_reg <= vio_tx_data;
                    SPISR[5] <= 1'b0; 
                end
                else if(SPI_select && read_write && reg_enable[3]) begin
                    SPI_TX_reg <= data; 
                    SPISR[5] <= 1'b0; 
                end
                
                if(SPI_select && read_write && reg_enable[1]) begin
                    SPIBR <= data;
                end 
                if (SPICR[4] && SPICR[6]) begin   // MSTR=1, SPE=1
                     if (ack_spi) begin
                            SPISR[7] <= 1'b0; 
                    end
                    case (state)
        
                        IDLE: begin
                            // Move to LOAD only if: No transfer AND TX is full AND no interrupt
                            if (!transfer_active && !SPISR[5] && !SPISR[7]) begin
                                state <= LOAD;
                                mode  <= 2'b11;   // parallel load
                            end
                            else begin
                                // Hold in IDLE if interrupt is set, TX is empty, or transfer is active
                                state <= IDLE;
                                mode  <= 2'b00; 
                            end
                        end
        
                        LOAD: begin
                            if (transfer_active) begin
                                if (!active_ss) begin
                                    SPISR[5] <= 1'b1;   
                                    case(SPICR[8])
                                        1'b0: mode <= 2'b10; // shift left
                                        1'b1: mode <= 2'b01; // shift right
                                    endcase
                                    state <= SHIFT;
                                end
                                else begin
                                    // Wait for active_ss to drop
                                    state <= LOAD; 
                                    mode  <= 2'b11; //potential bugg if trasfer active keeps counting it resets right for ss=1
                                end
                            end  
                            else begin
                                // Keep broadcasting the load command until transfer starts
                                state <= LOAD;
                                mode  <= 2'b11; 
                            end
                        end  
        
                        SHIFT: begin
                            if (!transfer_active) begin
                                mode <= 2'b00;     // hold
                                state <= IDLE;
        
                                SPISR[7] <= 1;     // transfer complete
                                SPI_RX_reg[7:0] <= parallel_rx_wire;
                            end
                            else begin
                                state<=SHIFT;
                            end
                        end
        
                        default: state <= IDLE;
        
                    endcase
                end
                
                else if(!SPICR[4] && SPICR[6]) begin   //MSTR=0, SPE=1
                     if (ack_spi) begin
                         SPISR[7] <= 1'b0; 
                    end
                    
                    case (s_state)
                    
                        idle:begin
                            if(active_ss)begin
                                if (!SPISR[5]) begin
                                    mode <= 2'b11;
                                    SPISR[5] <= 1'b1;
                                end
                                else begin  
                                    mode <=2'b00;
                                end
                                s_state <= idle;
                            end 
                            else begin
                                case(SPICR[8])
                                    1'b0: mode <= 2'b10; // shift left
                                    1'b1: mode <= 2'b01; // shift right
                                endcase
                                if (transfer_active) begin
                                    s_state <= shift;
                                end else begin
                                    s_state <= idle; 
                                end
                            end
                        end
                        
                       shift: begin
                            // active_ss HIGH = End of frame (highest priority)
                            if (active_ss) begin
                                mode <= 2'b00;
                                SPI_RX_reg[7:0] <= parallel_rx_wire;
                                SPISR[7] <= 1'b1;   // Transfer complete flag
                                s_state <= idle;
                            end
                        
                            // Transfer still ongoing
                            else if (transfer_active) begin
                                s_state <= shift;
                            end
                        
                            // Transfer done but SS still low ? wait for SS high
                            else begin
                                mode <= 2'b00;
                                SPI_RX_reg[7:0] <= parallel_rx_wire;
                                SPISR[7] <= 1'b1;
                                s_state <= wait_ss;
                            end
                        end  
                        wait_ss: begin
                            mode <= 2'b00;
                            if (active_ss)
                                s_state <= idle;
                            else
                                s_state <= wait_ss;
                        end 
                        default: begin
                             s_state <= idle;
                             mode    <= 2'b00;
                         end
                    endcase
                end 
       end
    end          
endmodule





module USR_slave(
    input wire clk,
    input wire reset,
    input wire enable,
    input wire [1:0] mode,
    input wire [7:0] parallel_data,
    input wire mux_in,
    input wire LSBF,
    input wire LOR,
    input wire SSOE,
    input wire SPICR_m,
    input wire shift_clk,
    output wire master_SS, //master decides to pull SS down that happens when data is corectly latched into shift register
    output mux_out,
    output wire [7:0] rx_data
    );
    
    reg internal_SS;
    
    reg [7:0] q;
    wire serial_in_right;
    wire serial_in_left;
    
    reg shift_clk_reg1;
    reg shift_clk_reg2;
    wire shift_tick;

    assign shift_tick = (shift_clk_reg1 && !shift_clk_reg2);

    assign master_SS=internal_SS|(~SPICR_m);
    always @(posedge clk) begin
        if (reset) begin
            q <= 8'b00000000; 
            internal_SS<=1'b1;
        end else if(enable) begin
            shift_clk_reg1 <= shift_clk;
            shift_clk_reg2 <= shift_clk_reg1;
            case (mode)
                2'b00: begin
                 //hold
                    q<=q;
                        internal_SS <= 1'b1;
                end
                2'b01: begin
                    // Shift right
                    if (shift_tick) begin
                        q <= {serial_in_right, q[7:1]};
                    end
                end
                2'b10: begin
                    // Shift left
                        if (shift_tick)  begin
                            q <= {q[6:0], serial_in_left};
                        end
                end
                2'b11: begin
                    //parall load
                    q <= parallel_data; 
                    if(SSOE) 
                        begin   
                            internal_SS<=1'b0; 
                        end
                    //else
                end
                default: begin
                    q <= q;
                end
            endcase
        end
    end
    assign rx_data=q;
    assign serial_in_left  = (!LOR) ? mux_in : 1'b0;
    assign serial_in_right = (LOR)  ? mux_in : 1'b0; //its a demux logic 
    assign mux_out= LSBF?q[0]:q[7];
    
endmodule




module PHASE_POLARITY_slave(
    input  wire baurd_clk,
    input  wire CPOL,
    input  wire CPHA,
    input  wire MSTR,
    input  wire SS,            //chip select
    input  wire sck_i,
    output wire sck_o,      
    output wire shift_clk,    // Internal clock for Shifter
    output wire sample_clk    // Internal clock for Sampler
    );
    
    
    // ideal value of sck_pin depends upon CPOL

        assign sck_o = SS ? CPOL : (CPOL ? ~baurd_clk : baurd_clk); 
        
        wire active_clk = (MSTR) ? baurd_clk : sck_i; //if its slave choose SCK as input pin 

        assign sample_clk = (CPHA == 0) ? active_clk : ~active_clk; 
        assign shift_clk  = (CPHA == 0) ? ~active_clk : active_clk;

    
endmodule




module EDGE_COUNTER_16_slave(
    input system_clk,
    input sck,              //sck from phase and polarity module 
    input reset,
    input SS,
//    input SPIF,
    output reg transfer_active
    );
    
    reg[3:0]edge_count;
    reg b_clk_reg, b_clk_reg2;
    wire toggle_strobe;

    reg transfer_done_lock; // to lock the transfer activity till ss goes high 
    always @(posedge system_clk) begin
        b_clk_reg  <= sck;
        b_clk_reg2 <= b_clk_reg; //buffer
    end
    assign toggle_strobe = (!SS)&&(b_clk_reg ^ b_clk_reg2);


    always @(posedge system_clk) begin
        if (reset) begin
            edge_count <= 4'd0;
            transfer_active <= 1'b0;
            transfer_done_lock <= 1'b0;
        end 
        else begin
            if (SS) begin
                edge_count <= 4'd0;
                transfer_active <= 1'b0;
                transfer_done_lock <= 1'b0;
            end
            else if (toggle_strobe && !transfer_done_lock) begin
                if (edge_count==4'd15) begin
                    transfer_active <= 1'b0;
                    edge_count <= 4'd0;
                    transfer_done_lock <= 1'b1;//lock
                end 
                else begin
                    edge_count <= edge_count + 1'b1;
                    transfer_active <= 1'b1;
                end
            end
           end
    end
endmodule




module BAUD_GEN_slave(
    input sys_clk,
    input reset,
    input [2:0] SPPR,
    input [2:0] SPR,
    input MSTR,
    input SPE,
    output baud_clk
    );
    
    reg [2:0] prescale_count;
    reg [7:0] main_count;
    
    wire prescale_ticking;
    reg mux_out;//do we need to thake the mux out in reg first??
    wire run;
    assign run= SPE && MSTR;
    //prescale_counter
    always @(posedge sys_clk) 
    begin    
        if(reset)begin 
            prescale_count<=3'b000;
        end
        else if(run)begin
                if(prescale_ticking)
                    prescale_count<=3'b000;
                else
                    prescale_count<=prescale_count+1'b1;
                end 
    end
    
    assign prescale_ticking=(run)&&(prescale_count==SPPR);
    
    //main_counter
    always @(posedge sys_clk)
    begin
        if(reset)begin
            main_count<=8'h00;
            end
        else if(prescale_ticking)begin
            main_count<=main_count+1'b1;
            end
    end 
    
    //choosing baurd_clk
    always @(*) begin 
        case(SPR)
            3'b000: mux_out=main_count[0];
            3'b001: mux_out=main_count[1];
            3'b010: mux_out=main_count[2];
            3'b011: mux_out=main_count[3];
            3'b100: mux_out=main_count[4];
            3'b101: mux_out=main_count[5];
            3'b110: mux_out=main_count[6];
            3'b111: mux_out=main_count[7];
            default: mux_out=1'b0;
            endcase 
        end
      assign baud_clk=mux_out;      
endmodule




module ADD_DECO_slave(
            input en,
            input [4:0]address, 
            output reg [15:0] out 
            );
    always@(*) begin
        out = 16'b0; 
         if(en) begin
            case(address)
                5'h00:out=16'b0000_0000_0000_0001;
                5'h04:out=16'b0000_0000_0000_0010;
                5'h08:out=16'b0000_0000_0000_0100;
                5'h0C:out=16'b0000_0000_0000_1000;
                5'h10:out=16'b0000_0000_0001_0000;
            endcase
         end
    end
endmodule