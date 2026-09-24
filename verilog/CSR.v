/*  CSR (Control and Status Register) Module :
    It supports CSR read and write operations based on address decoding, tracks cycle count (mcycle) and instruction retire count (minstret),
    handles trap and interrupt events, updating PC and control status accordingly, and, supports return from trap (mret) by restoring execution state.
*/

module CSR( 
    input CSR_EN, 
    input CSR_WR_EN, 
    input [31:0] pc, 
    input [31:0] CSR_WD, 
    input mret, 
    input INS_COM, 
    input [11:0] CSR_addr, 
    input clk, 
    input spi_q, 
    input gpio_q, 
    input trap, 
    input reset, 
    output reg PC_src, 
    output reg [31:0] pc_next, 
    output reg [31:0] CSR_DATA 
    ); 

    reg [63:0] mcycle; 
    reg [63:0] minstret; 
    reg [31:0] mtvec1; 
    reg [31:0] mtvec2; 
    reg [31:0] mepc; 
    reg [31:0] mstatus; 
    
    reg [31:0] old_value; 
    reg [11:0] CSR_addr_r; 
    reg [31:0] CSR_WD_r; 
    reg trap_r; 
    reg mret_r; 
    reg CSR_WR_EN_r; 
    reg [63:0] mcycle_next; 
    reg [63:0] minstret_next; 
    
    
    always @(posedge clk) begin 
        CSR_addr_r <= CSR_addr; 
        CSR_WD_r <= CSR_WD; 
        trap_r <= trap; 
        mret_r <= mret; 
        CSR_WR_EN_r <= CSR_WR_EN; 
    end 
    
    //Reading from CSR is based on the Address received and is combinational 
    always@(*) begin 
        if((~trap_r)&(~mret_r)&(~reset)&(CSR_EN)&(~CSR_WR_EN)) begin 
            case (CSR_addr_r) 
                12'hB00: CSR_DATA = mcycle; 
                12'hB02: CSR_DATA = minstret; 
                12'h305: CSR_DATA = mtvec1 ; 
                12'h306: CSR_DATA = mtvec2 ; 
                12'h341: CSR_DATA = mepc ; 
                12'h300: CSR_DATA = mstatus ; 
                default: CSR_DATA = 0; 
            endcase 
        end else begin 
            CSR_DATA = 0; 
        end 
    end 
    
    //Mcycle is incremented for every positive edge of clock except for Reset or Loading into Mcycle 
    always @(*) begin 
        mcycle_next = mcycle + 1; 
        if (CSR_WR_EN_r && CSR_addr_r == 12'hB00) 
            mcycle_next = CSR_WD_r; 
    end 
    always @(posedge clk) begin 
        if (reset) 
            mcycle <= 0; 
        else 
            mcycle <= mcycle_next; 
    end 
    
    //Minstret is incremented for every instruction completed except for Reset or Loading into minstret 
    always @(*) begin 
        minstret_next = minstret;    
        if (INS_COM) 
            minstret_next = minstret + 1;    
        if (CSR_WR_EN_r && (CSR_addr_r == 12'hB02)) 
            minstret_next = CSR_WD_r;        
    end 
    
    always @(posedge clk) begin 
        if (reset) 
            minstret <= 0; 
        else 
            minstret <= minstret_next; 
    end 
    
    //mepc, mtvec, mstatus are updated  
    always@(posedge clk) begin 
    PC_src <= 0; 
        if(reset) begin 
            mtvec1 <= 0; 
            mtvec2 <= 32'd440; 
            mepc <= 0; 
            mstatus <= 0; 
            pc_next <= 0; 
            PC_src <= 0; 
        end  
        
        //Trap Execution               
        //else if(trap_r & CSR_EN) begin 
        else if(trap_r) begin 
            mepc <= pc; 
            mstatus[7] <= mstatus[3]; 
            mstatus[3] <= 0; 
            if(spi_q) begin 
                        pc_next <= mtvec1; 
                    end 
            else if(gpio_q) begin 
                                pc_next <= mtvec2; 
                            end 
            PC_src <= 1;  
        
        //Return Signal execution                     
        end else if(mret_r) begin 
                pc_next <= mepc; 
                mstatus[3] <= mstatus[7]; 
                mstatus[7] <= 1; 
                PC_src <= 1; 
        
        end else if(CSR_WR_EN & CSR_EN) begin 
            case (CSR_addr_r) 
                12'h305: mtvec1 <= CSR_WD_r; 
                12'h306: mtvec2 <= CSR_WD_r; 
                12'h341: mepc <= CSR_WD_r; 
                12'h300: mstatus <= CSR_WD_r; 
                default: ;                                             
            endcase 
            PC_src <= 0; 
        end                                        
    end 
endmodule
