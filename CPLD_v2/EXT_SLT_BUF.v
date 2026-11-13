`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Design Name : EXPAND SLOT (4 SLOT, buffered / 50pin IDC version)
// Module Name : EXT_SLT_BUF
// Target      : XC9536XL-10VQ44C
//
// Based on EXT_SLT (CPLD/EXTSLT.v) by @v9938.
//
// Changes from v1
//  - The CPLD now sits on the buffered (slot) side of the bus.
//    Host -> 74HCT541 x4 (A/control) / 74HCT245 (D) -> CPLD + slots.
//  - DATA_DIR controls the 74HCT245 direction and also drives host BUSDIR:
//      DATA_DIR = 1 : host -> slot (default)
//      DATA_DIR = 0 : slot -> host, when
//                     (a) memory read of this primary slot (SLTSL & RD), or
//                     (b) I/O read where a cartridge asserts BUSDIR (BUSDIR_IN & RD)
//    The FFFFh sub-slot register read is case (a): the CPLD drives the slot-side
//    data bus and the 74HCT245 passes it to the host.
//  - CLOCK is no longer used (pins). The sub-slot register is latched on the
//    falling edge of WR. On a Z80 memory write, data, address and SLTSL are
//    stable before WR goes low.
//  - EXTSLT outputs and data are push-pull (the bus on this side is local).
//////////////////////////////////////////////////////////////////////////////////

module EXT_SLT_BUF(
    input        SLT_WRn,       // buffered WR      (GCK3)
    input        SLT_RDn,       // buffered RD
    input        SLT_RESETn,    // buffered RESET
    input        SLT_SLTSLn,    // buffered SLTSL of this primary slot
    input [15:0] SLT_A,         // buffered address
    inout [7:0]  SLT_D,         // slot-side data bus
    input        BUSDIR_INn,    // AND of all slot BUSDIR (sub-slots 0-3 + I/O-only 4-5, 74HCT21)
    output       DATA_DIR,      // 74HCT245 DIR (A->B when 1), also host BUSDIR
    output [3:0] EXTSLTn        // sub-slot SLTSL to slot 0..3
    );

    // FFFFh: sub-slot select register ------------------------------------
    wire SubRegSel = (SLT_A == 16'hFFFF) & ~SLT_SLTSLn;

    reg [7:0] SubReg;
    always @(negedge SLT_WRn or negedge SLT_RESETn) begin
        if (!SLT_RESETn)
            SubReg <= 8'h00;
        else if (SubRegSel)
            SubReg <= SLT_D;
    end

    // read back = complement (MSX expanded slot spec)
    wire SubRegRd = SubRegSel & ~SLT_RDn;
    assign SLT_D = SubRegRd ? ~SubReg : 8'bzzzz_zzzz;

    // sub-slot decode ----------------------------------------------------
    wire [1:0] SubNum = (SLT_A[15:14] == 2'b00) ? SubReg[1:0] :
                        (SLT_A[15:14] == 2'b01) ? SubReg[3:2] :
                        (SLT_A[15:14] == 2'b10) ? SubReg[5:4] : SubReg[7:6];

    wire SubActive = ~SLT_SLTSLn & ~SubRegSel;

    assign EXTSLTn[0] = ~(SubActive & (SubNum == 2'd0));
    assign EXTSLTn[1] = ~(SubActive & (SubNum == 2'd1));
    assign EXTSLTn[2] = ~(SubActive & (SubNum == 2'd2));
    assign EXTSLTn[3] = ~(SubActive & (SubNum == 2'd3));

    // data buffer direction / host BUSDIR ---------------------------------
    assign DATA_DIR = SLT_RDn | (SLT_SLTSLn & BUSDIR_INn);

endmodule
