/*  Address Decoder :
    This module is used to decode the address for connecting the RISC-V module to Data memory 
    as well as other memory mapped peripherals (SPI/GPIO) 
*/

`timescale 1ns / 1ps

module address_decoder(

    input wire        riscv_we,
    input wire [31:0] riscv_addr,               //Address
    input wire [31:0] riscv_wdata,              //wd - Write data
    output reg [31:0] riscv_rdata,              //rd - Read data
    output reg        riscv_trans_done,         //Valid to RISCV whenever read data comes or write completed

    output reg        apb_we,
    output reg [31:0] apb_addr,                 //apb address
    output reg [31:0] apb_wdata,                //wd - Write data (apb)
    input wire [31:0] apb_rdata,                //rd - Read data (apb)
    input wire        apb_trans_done,           //apb Valid to RISCV whenever read data comes

    output reg        mem_we,                   //wea - write enable
    output reg [31:0] mem_addr,                 //addra - address (Mem)
    output reg [31:0] mem_wdata,                //dina - Write data (Mem)
    input wire [31:0] mem_rdata,                //douta - Read data
    output reg        mem_ena                   //ena - Enable for mem

    );

    always@(*) begin

        //Default
        mem_ena  = 1'b0;
        mem_we   = 1'b0;
        mem_addr = 32'b0;
        mem_wdata = 32'b0;
        apb_we   = 1'b0;
        apb_addr = 32'b0;
        apb_wdata = 32'b0;
        riscv_rdata = 32'b0;
        riscv_trans_done = 1'b0;

        if(riscv_addr[31:16] == 16'h0000) begin 
            mem_ena = 1'b1;
            mem_we = riscv_we;
            mem_addr = riscv_addr;
            mem_wdata = riscv_wdata;
            riscv_rdata = mem_rdata;
            //if(riscv_we)
                //riscv_trans_done = 1'b0;       
            //else 
                riscv_trans_done = 1'b1;    //Assuming Memory sends data in 1 clock cycle
        end
        else if ((riscv_addr[31:28] == 4'h3) || (riscv_addr[31:28] == 4'h2)) begin
            apb_we = riscv_we;
            apb_addr = riscv_addr;
            apb_wdata = riscv_wdata;
            riscv_rdata = apb_rdata;
            riscv_trans_done = apb_trans_done;
        end
        
        else begin
            mem_ena  = 1'b0;
            mem_we   = 1'b0;
            mem_addr = 32'b0;
            mem_wdata = 32'b0;
            apb_we   = 1'b0;
            apb_addr = 32'b0;
            apb_wdata = 32'b0;
            riscv_rdata = 32'b0;
            riscv_trans_done = 1'b0;
        end
    end

endmodule
