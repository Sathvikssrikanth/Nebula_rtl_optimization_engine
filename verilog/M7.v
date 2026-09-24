/*  2x1 32-bit MUX  */

module M7 ( 
    input [31:0]x,
    input [31:0] y,
    input branch_mux,
    output [31:0] z
    );

    assign z = (branch_mux == 1'b1)? y:x;
 
endmodule
