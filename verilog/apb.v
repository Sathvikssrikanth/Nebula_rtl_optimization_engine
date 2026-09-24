/*  APB module :
    It connects RISC-V with Data memory as well as peripherals
*/
 
module apb ( 
    input wire clk, 
    input wire rst, 
    input wire we,                  // Write Enable 
    input wire [31:0] addr,         // Address 
    input wire [31:0] wdata,        // wd - Write data 
    output reg [31:0] rdata,        // rd - Read data 
    output reg trans_done,          // Sending done to RISCV, whenever data is written or read is valid 
 
    input pready_gpio,              // GPIO specific APB interface 
    input [31:0] prdata_gpio, 
    output reg psel_gpio, 
 
    input pready_spi,               // SPI Specific APB interface 
    input [31:0] prdata_spi, 
    output reg psel_spi, 
 
    output reg penable,             // Other APB interfaces 
    output reg pwrite, 
    output reg [31:0] paddr, 
    output reg [31:0] pwdata 
 
    ); 
 
    localparam IDLE = 2'b00, 
            SETUP = 2'b01, 
            ACCESS = 2'b10; 
    
    reg [1:0] state; 
    
    always @(posedge clk) begin 
        if (rst) begin 
            state <= IDLE; 
            psel_gpio <= 1'b0; 
            psel_spi <= 1'b0; 
            penable <= 1'b0; 
            pwrite <= 1'b0; 
            paddr <= 32'd0; 
            pwdata <= 32'd0; 
            trans_done <= 1'b0; 
            rdata <= 32'd0; 
        end else begin 
            case (state) 
                IDLE: begin 
                    if ((addr[31:28] == 4'h3) || (addr[31:28] == 4'h2)) begin 
                        if (!we) begin 
                            pwrite <= 1'b0; 
                            paddr <= addr; 
                        end else if (we) begin 
                            pwrite <= 1'b1; 
                            paddr <= addr; 
                            pwdata <= wdata; 
                        end  
                        psel_gpio <= (addr[31:28] == 4'h2) ? 1'b1 : 1'b0; 
                        psel_spi <= (addr[31:28] == 4'h3) ? 1'b1 : 1'b0; 
                        penable <= 1'b0; 
                        state <= SETUP; 
                    end 
                    trans_done <= 1'b0;  //Clearing the bit that was set high in Access phase 
                end 
    
                SETUP: begin 
                    penable <= 1'b1; 
                    state <= ACCESS; 
                end 
    
                ACCESS: begin 
                    
                    if(psel_gpio && pready_gpio) begin      // Wait for slave ready 
                        if (pwrite) begin 
                            // Write completed 
                            trans_done <= 1'b1;             // Write transaction done 
                            state <= IDLE; 
                        end else begin 
                            // Read completed 
                            rdata <= prdata_gpio; 
                            trans_done <= 1'b1;             //Read valid 
                            state <= IDLE; 
                        end 
                        psel_gpio <= 1'b0; 
                        psel_spi  <= 1'b0; 
                        penable   <= 1'b0; 
                    end 
                    else if (psel_spi && pready_spi) begin 
                        if (pwrite) begin 
                            // Write completed 
                            trans_done <= 1'b1; 
                            state <= IDLE; 
                        end else begin 
                            // Read completed 
                            rdata <= prdata_spi; 
                            trans_done <= 1'b1; 
                            state <= IDLE; 
                        end 
                        psel_gpio <= 1'b0; 
                        psel_spi  <= 1'b0; 
                        penable   <= 1'b0; 
                    end 
                end 
    
                default: state <= IDLE; 
            endcase 
        end 
    end 

endmodule