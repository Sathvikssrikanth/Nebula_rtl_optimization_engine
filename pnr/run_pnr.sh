openroad pnr.tcl 2>&1 | tee pnr_log.txt
grep "Design area" pnr_log.txt | tail -1 > reports/area.rpt
