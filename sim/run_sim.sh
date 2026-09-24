#!/bin/bash

iverilog -o sim_out -f files.f 
#../verilog/adder.v ../verilog/tb_adder.v
vvp sim_out
