/*  Interrupt Arbiter :
    This module arbitrates interrupt requests from multiple sources (SPI and GPIO)
    and forwards them to the RISC-V core based on a priority mechanism.
*/

`timescale 1ns / 1ps

module interrupt_arbiter (
    input wire clk,
    input wire rst,

    input wire int_gpio_req,          //Interrupt Req from GPIO
    input wire int_spi_req,           //Interrupt Req from SPI
    output reg ack_spi,               //Ack sent to SPI that irq has been accepted
    output reg ack_gpio,              //Ack sent to GPIO that irq has been accepted
    output reg riscv_ready,

    input wire riscv_busy,
    output reg irq_spi_riscv,         //SPI interrupt to RISCV
    output reg irq_gpio_riscv         //GPIO interrupt to RISCV

);

    reg priority;

    always @(posedge clk) begin
        if (rst) begin
            riscv_ready <= 1;
            irq_spi_riscv <= 0;
            irq_gpio_riscv <= 0;
            ack_gpio <= 0;
            ack_spi <= 0;
            priority <= 0;                 //Initially setting priority to SPI
        
        end else if (riscv_busy) begin
            riscv_ready <= 0;
            irq_spi_riscv <= 0;
            irq_gpio_riscv <= 0;
            ack_gpio <= 0;
            ack_spi <= 0;
        
        end else begin
            irq_spi_riscv <= 0;
            irq_gpio_riscv <= 0;
            ack_gpio <= 0;
            ack_spi <= 0;
            riscv_ready <= 1;

            case({int_spi_req, int_gpio_req})
                
                2'b00 : begin
                    riscv_ready <= 1;
                    irq_spi_riscv <= 0;
                    irq_gpio_riscv <= 0;
                    ack_gpio <= 0;
                    ack_spi <= 0;
                end

                2'b01 : begin
                    riscv_ready <= 0;
                    irq_spi_riscv <= 0;
                    irq_gpio_riscv <= 1;
                    ack_gpio <= 1;
                    ack_spi <= 0;
                    priority <= 0;         //Once GPIO is done, changin priority to SPI
                end

                2'b10 : begin
                    riscv_ready <= 0;
                    irq_spi_riscv <= 1;
                    irq_gpio_riscv <= 0;
                    ack_gpio <= 0;
                    ack_spi <= 1;
                    priority <= 1;            //Once SPI is done, changing priority to GPIO
                end

                2'b11 : begin
                    if (!priority) begin
                        riscv_ready <= 0;
                        irq_spi_riscv <= 1;
                        irq_gpio_riscv <= 0;
                        ack_spi <= 1;
                        ack_gpio <= 0;
                        priority <= 1;              //Changing the priority next time to GPIO
                    end
                    else begin
                        riscv_ready <= 0;
                        irq_spi_riscv <= 0;
                        irq_gpio_riscv <= 1;
                        ack_spi <= 0;
                        ack_gpio <= 1;
                        priority <= 0;
                    end
                end

                default : begin
                    riscv_ready <= 1;
                    irq_spi_riscv <= 0;
                    irq_gpio_riscv <= 0;
                    ack_gpio <= 0;
                    ack_spi <= 0;
                end

            endcase

        end
                    
    end

endmodule
