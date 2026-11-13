`timescale 1ns / 100ps
// Self-checking testbench for EXT_SLT_BUF (models the buffered slot side).
// iverilog -o sim sim_top.v EXT_SLT_BUF.v && vvp sim

module sim_top();
    parameter CYC = 140;            // ~3.58MHz half period

    reg         WRn = 1, RDn = 1, RESETn = 0, SLTSLn = 1, BUSDIR_INn = 1;
    reg  [15:0] A = 16'h0000;
    reg  [7:0]  Dout;               // data driven by host side (through 245)
    reg         Ddrv = 0;
    wire [7:0]  D;
    wire        DATA_DIR;
    wire [3:0]  EXTSLTn;
    integer     errors = 0;

    assign D = Ddrv ? Dout : 8'bzzzz_zzzz;
    pullup p0(D[0]); pullup p1(D[1]); pullup p2(D[2]); pullup p3(D[3]);
    pullup p4(D[4]); pullup p5(D[5]); pullup p6(D[6]); pullup p7(D[7]);

    EXT_SLT_BUF dut(.SLT_WRn(WRn), .SLT_RDn(RDn), .SLT_RESETn(RESETn),
                    .SLT_SLTSLn(SLTSLn), .SLT_A(A), .SLT_D(D),
                    .BUSDIR_INn(BUSDIR_INn), .DATA_DIR(DATA_DIR), .EXTSLTn(EXTSLTn));

    task check(input cond, input [8*48-1:0] msg);
        if (!cond) begin
            errors = errors + 1;
            $display("FAIL @%0t: %0s", $time, msg);
        end
    endtask

    // Z80 memory write: address+SLTSL, data, then WR low
    task mem_write(input [15:0] addr, input [7:0] data);
    begin
        A = addr; #(CYC) SLTSLn = 0;
        Dout = data; Ddrv = 1;
        #(CYC) WRn = 0;
        check(DATA_DIR == 1, "DATA_DIR must be host->slot on write");
        #(2*CYC) WRn = 1;
        #(20) SLTSLn = 1; Ddrv = 0;
        #(CYC);
    end
    endtask

    // Z80 memory read of this primary slot; returns slot-side data
    task mem_read(input [15:0] addr, output [7:0] data, output [3:0] sel);
    begin
        A = addr; #(CYC) SLTSLn = 0; RDn = 0;
        #(2*CYC);
        data = D; sel = EXTSLTn;
        check(DATA_DIR == 0, "DATA_DIR must be slot->host on read");
        RDn = 1; #(20) SLTSLn = 1;
        #(CYC);
    end
    endtask

    reg [7:0] d;
    reg [3:0] s;
    initial begin
        $dumpfile("sim_top.vcd"); $dumpvars(0, sim_top);
        #(3*CYC) RESETn = 1;
        #(CYC);

        // after reset: register 00, read back FF (complement)
        mem_read(16'hFFFF, d, s);
        check(d == 8'hFF, "reset value readback ~00");
        check(s == 4'b1111, "no sub-slot selected at FFFF");

        // page0->0 page1->1 page2->2 page3->3 : 11_10_01_00 = E4
        mem_write(16'hFFFF, 8'hE4);
        mem_read(16'hFFFF, d, s);
        check(d == 8'h1B, "readback ~E4 = 1B");

        mem_read(16'h0000, d, s); check(s == 4'b1110, "page0 -> sub0");
        mem_read(16'h4000, d, s); check(s == 4'b1101, "page1 -> sub1");
        mem_read(16'h8000, d, s); check(s == 4'b1011, "page2 -> sub2");
        mem_read(16'hC000, d, s); check(s == 4'b0111, "page3 -> sub3");
        mem_read(16'hFFFE, d, s); check(s == 4'b0111, "FFFE is still sub3");
        check(d == 8'hFF, "empty sub-slot reads FF (pull-ups)");

        // write not latched when SLTSL inactive (other primary slot)
        A = 16'hFFFF; Dout = 8'h00; Ddrv = 1;
        #(CYC) WRn = 0; #(2*CYC) WRn = 1; #(20) Ddrv = 0;
        mem_read(16'hFFFF, d, s); check(d == 8'h1B, "write to other slot ignored");

        // idle: no read -> host->slot
        A = 16'h1234; #(CYC); check(DATA_DIR == 1, "idle DATA_DIR = 1");
        check(EXTSLTn == 4'b1111, "idle no sub-slot");

        // I/O read with cartridge BUSDIR -> slot->host
        RDn = 0; #(CYC); check(DATA_DIR == 1, "I/O read w/o BUSDIR: host side");
        BUSDIR_INn = 0; #(10); check(DATA_DIR == 0, "I/O read with BUSDIR: slot->host");
        RDn = 1; #(10); check(DATA_DIR == 1, "BUSDIR without RD ignored");
        BUSDIR_INn = 1;

        // reset clears register
        RESETn = 0; #(CYC) RESETn = 1;
        mem_read(16'hFFFF, d, s); check(d == 8'hFF, "reset clears register");

        if (errors == 0) $display("PASS: all checks");
        else             $display("FAILED: %0d errors", errors);
        $finish;
    end
endmodule
