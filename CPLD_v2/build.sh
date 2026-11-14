#!/bin/sh
# Command-line build of EXT_SLT_BUF.jed (XC9536XL-10VQ44) with Xilinx ISE 14.7.
# Usage:  . /opt/Xilinx/14.7/ISE_DS/settings64.sh && ./build.sh
# Output: build/EXT_SLT_BUF.jed, build/EXT_SLT_BUF.svf (+ fitter report build/EXT_SLT_BUF.rpt)
# Program via FT232H: openocd -f ft232h.cfg -c "init; svf build/EXT_SLT_BUF.svf; shutdown"
set -e
cd "$(dirname "$0")"
TOP=EXT_SLT_BUF
PART=xc9536xl-10-VQ44

for t in xst ngdbuild cpldfit hprep6 impact; do
    command -v $t >/dev/null || { echo "$t not found: source ISE settings64.sh first" >&2; exit 1; }
done

rm -rf build && mkdir -p build/xst/tmp && cd build
echo "verilog work ../$TOP.v" > $TOP.prj
cat > $TOP.xst <<EOF
set -tmpdir xst/tmp
set -xsthdpdir xst
run
-ifn $TOP.prj
-ifmt mixed
-ofn $TOP
-ofmt NGC
-p xc9500xl
-top $TOP
-opt_mode Speed
-opt_level 1
EOF

xst -ifn $TOP.xst -ofn $TOP.syr
ngdbuild -dd _ngo -uc ../$TOP.ucf -p $PART $TOP.ngc $TOP.ngd
cpldfit -p $PART -optimize speed -loc on -slew fast -init low -inputs 54 -pterms 25 \
        -power std -unused float -terminate keeper $TOP.ngd
hprep6 -s IEEE1149 -n $TOP -i $TOP

# SVF (erase + program + verify) for OpenOCD/FT232H, see ft232h.cfg
cat > svf.cmd <<EOF
setMode -bs
setCable -port svf -file $TOP.svf
addDevice -p 1 -file $TOP.jed
program -e -v -p 1
closeCable
quit
EOF
impact -batch svf.cmd > impact_svf.log 2>&1
grep -q "Programming completed successfully" impact_svf.log || { cat impact_svf.log >&2; exit 1; }

echo
echo "OK: build/$TOP.jed, build/$TOP.svf"
grep -A12 -i "Resources" $TOP.rpt | head -20 || true
