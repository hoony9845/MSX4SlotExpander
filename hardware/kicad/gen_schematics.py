#!/usr/bin/env python3
"""
MSX 4Slot Expander v2 - KiCad 8 schematic generator.

Generates two KiCad projects from a single netlist definition:
  adapter/   : MSX cartridge edge -> 50pin IDC (passive)
  expander/  : 50pin IDC -> bus buffer -> CPLD sub-slot -> 4 x MSX slot

Pins are connected by a short wire stub plus a net label rather than drawn
wires, so the netlist is defined in one place (dicts below). After running,
open each project in KiCad to tidy up placement and wiring.

Usage:  python3 gen_schematics.py   (needs the KiCad 8 standard symbol libraries)
Check:  kicad-cli sch erc expander/expander.kicad_sch
"""
import json
import os
import re
import uuid as _uuid

SYMDIR = os.environ.get("KICAD8_SYMBOL_DIR", "/usr/share/kicad/symbols")
HERE = os.path.dirname(os.path.abspath(__file__))
G = 2.54


def uid():
    return str(_uuid.uuid4())


# --------------------------------------------------------------------------
# minimal S-expression reader / writer
# --------------------------------------------------------------------------
class Sym(str):
    """bare atom (non-quoted)"""


def parse(text):
    tok = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')
    stack, cur = [], []
    for m in tok.finditer(text):
        t = m.group(0)
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif t[0] == '"':
            cur.append(t[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            cur.append(Sym(t))
    return cur


def dump(e, ind=0):
    if isinstance(e, list):
        if not e:
            return "()"
        simple = all(not isinstance(x, list) for x in e)
        if simple:
            return "(" + " ".join(dump(x) for x in e) + ")"
        k = 1
        while k < len(e) and not isinstance(e[k], list):
            k += 1
        s = "(" + " ".join(dump(x) for x in e[:k])
        for x in e[k:]:
            s += "\n" + "\t" * (ind + 1) + dump(x, ind + 1)
        return s + "\n" + "\t" * ind + ")"
    if isinstance(e, Sym):
        return str(e)
    if isinstance(e, (int, float)):
        return fmt(e)
    return '"' + str(e).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def fmt(v):
    v = round(float(v), 4)
    return ("%d" % v) if v == int(v) else ("%g" % v)


def S(*a):
    return list(a)


def A(x):
    return Sym(x)


def find(e, key):
    return [x for x in e if isinstance(x, list) and x and x[0] == key]


# --------------------------------------------------------------------------
# library symbols
# --------------------------------------------------------------------------
_libcache = {}


def lib_symbols(lib):
    if lib not in _libcache:
        tree = parse(open(os.path.join(SYMDIR, lib + ".kicad_sym")).read())[0]
        _libcache[lib] = {x[1]: x for x in find(tree, "symbol")}
    return _libcache[lib]


def flatten(lib, name):
    """return a self-contained symbol definition (extends resolved)"""
    syms = lib_symbols(lib)
    s = syms[name]
    ext = find(s, "extends")
    if not ext:
        out = [x for x in s]
    else:
        parent = flatten(lib, ext[0][1])
        pname = parent[1]
        out = [A("symbol"), name]
        # child properties override parent properties
        cprops = {p[1]: p for p in find(s, "property")}
        for x in parent[2:]:
            if isinstance(x, list) and x[0] == "property":
                out.append(cprops.pop(x[1], x))
            elif isinstance(x, list) and x[0] == "symbol":
                sub = [y for y in x]
                sub[1] = sub[1].replace(pname + "_", name + "_", 1)
                out.append(sub)
            else:
                out.append(x)
        for p in cprops.values():
            out.insert(2, p)
    return out


def symbol_pins(symdef, unit, style=1):
    """[(number, name, type, x, y, angle, hidden)] for given unit/style"""
    name = symdef[1]
    res = []
    for sub in find(symdef, "symbol"):
        m = re.match(re.escape(name) + r"_(\d+)_(\d+)$", sub[1])
        u, st = int(m.group(1)), int(m.group(2))
        if u not in (0, unit) or st not in (0, style):
            continue
        for p in find(sub, "pin"):
            at = find(p, "at")[0]
            nm = find(p, "name")[0][1]
            num = find(p, "number")[0][1]
            hidden = any(isinstance(x, Sym) and x == "hide" for x in p) or bool(
                find(p, "hide"))
            res.append((num, nm, str(p[1]), float(at[1]), float(at[2]),
                        int(float(at[3])), hidden))
    return res


def custom_symbol(name, ref, value, left, right, top=(), bottom=(),
                  width=25.4, fp="", ds=""):
    """build a simple box symbol. sides: list of (num, name, type) or None(gap)"""
    pl = 5.08
    n = max(len(left), len(right))
    h = (n + 1) * G
    y0 = h / 2
    w2 = width / 2
    ytop = round(y0 / G) * G
    graphics = [S(A("rectangle"), S(A("start"), -w2, ytop),
                  S(A("end"), w2, ytop - h - G),
                  S(A("stroke"), S(A("width"), 0.254), S(A("type"), A("default"))),
                  S(A("fill"), S(A("type"), A("background"))))]
    pins = []

    def pin(num, nm, typ, x, y, ang):
        pins.append(S(A("pin"), A(typ), A("line"), S(A("at"), x, y, ang),
                      S(A("length"), pl),
                      S(A("name"), nm, S(A("effects"), S(A("font"), S(A("size"), 1.27, 1.27)))),
                      S(A("number"), num, S(A("effects"), S(A("font"), S(A("size"), 1.27, 1.27))))))

    for i, p in enumerate(left):
        if p:
            pin(p[0], p[1], p[2], -w2 - pl, ytop - (i + 1) * G, 0)
    for i, p in enumerate(right):
        if p:
            pin(p[0], p[1], p[2], w2 + pl, ytop - (i + 1) * G, 180)
    for i, p in enumerate(top):
        if p:
            pin(p[0], p[1], p[2], -w2 + (i + 2) * G, ytop + pl, 270)
    for i, p in enumerate(bottom):
        if p:
            pin(p[0], p[1], p[2], -w2 + (i + 2) * G, ytop - h - G - pl, 90)

    def prop(k, v, y, hide=False):
        eff = [A("effects"), S(A("font"), S(A("size"), 1.27, 1.27))]
        if hide:
            eff.append(S(A("hide"), A("yes")))
        return S(A("property"), k, v, S(A("at"), 0, y, 0), eff)

    return [A("symbol"), name, S(A("exclude_from_sim"), A("no")),
            S(A("in_bom"), A("yes")), S(A("on_board"), A("yes")),
            prop("Reference", ref, ytop + 8),
            prop("Value", value, ytop + 5.5),
            prop("Footprint", fp, 0, True), prop("Datasheet", ds, 0, True),
            prop("Description", "", 0, True),
            [A("symbol"), name + "_0_1"] + graphics,
            [A("symbol"), name + "_1_1"] + pins]


# --------------------------------------------------------------------------
# schematic builder
# --------------------------------------------------------------------------
class Sch:
    def __init__(self, project, title, paper="A1"):
        self.project = project
        self.title = title
        self.paper = paper
        self.root = uid()
        self.libs = {}          # lib_id -> flattened def
        self.items = []
        self.netpins = {}       # net -> [(ref, pin)]
        self.custom = []

    def add_lib(self, lib_id, symdef):
        if lib_id not in self.libs:
            d = [x for x in symdef]
            d[1] = lib_id
            # sub symbol names stay with the bare name (KiCad convention)
            self.libs[lib_id] = d
        return self.libs[lib_id]

    def place(self, lib, name, ref, value, x, y, nets, unit=1, fp="",
              symdef=None, style=1, nc_ok=(), note=None):
        lib_id = "%s:%s" % (lib, name)
        if symdef is None:
            symdef = flatten(lib, name)
        else:
            self.custom.append(symdef)
        self.add_lib(lib_id, symdef)
        pins = symbol_pins(symdef, unit, style)
        props = [
            S(A("property"), "Reference", ref, S(A("at"), x, y - 2 * G, 0),
              S(A("effects"), S(A("font"), S(A("size"), 1.27, 1.27)))),
            S(A("property"), "Value", value, S(A("at"), x, y - G, 0),
              S(A("effects"), S(A("font"), S(A("size"), 1.27, 1.27)))),
            S(A("property"), "Footprint", fp, S(A("at"), x, y, 0),
              S(A("effects"), S(A("font"), S(A("size"), 1.27, 1.27)), S(A("hide"), A("yes")))),
            S(A("property"), "Datasheet", "", S(A("at"), x, y, 0),
              S(A("effects"), S(A("font"), S(A("size"), 1.27, 1.27)), S(A("hide"), A("yes")))),
        ]
        sym = [A("symbol"), S(A("lib_id"), lib_id), S(A("at"), x, y, 0),
               S(A("unit"), unit), S(A("exclude_from_sim"), A("no")),
               S(A("in_bom"), A("yes")), S(A("on_board"), A("yes")),
               S(A("dnp"), A("no")), S(A("uuid"), uid())] + props
        seen = set()
        for (num, nm, typ, px, py, ang, hidden) in pins:
            if num in seen:
                continue
            seen.add(num)
            sym.append(S(A("pin"), num, S(A("uuid"), uid())))
        sym.append(S(A("instances"), S(A("project"), self.project,
                                       S(A("path"), "/" + self.root,
                                         S(A("reference"), ref), S(A("unit"), unit)))))
        self.items.append(sym)

        used = set()
        for (num, nm, typ, px, py, ang, hidden) in pins:
            if num in used:
                continue
            used.add(num)
            ax, ay = x + px, y - py
            net = nets.get(num)
            if net is None:
                if typ != "no_connect" and num not in nc_ok:
                    raise SystemExit("%s pin %s (%s) not assigned" % (ref, num, nm))
                if typ != "no_connect":
                    self.items.append(S(A("no_connect"), S(A("at"), ax, ay),
                                        S(A("uuid"), uid())))
                continue
            if net == "NC":
                self.items.append(S(A("no_connect"), S(A("at"), ax, ay),
                                    S(A("uuid"), uid())))
                continue
            # stub outward (opposite of pin direction)
            dx = {0: -1, 90: 0, 180: 1, 270: 0}[ang]
            dy = {0: 0, 90: 1, 180: 0, 270: -1}[ang]   # schematic y is down
            ex, ey = ax + dx * G, ay + dy * G
            self.items.append(S(A("wire"), S(A("pts"), S(A("xy"), ax, ay), S(A("xy"), ex, ey)),
                                S(A("stroke"), S(A("width"), 0), S(A("type"), A("default"))),
                                S(A("uuid"), uid())))
            lang = {(-1, 0): 180, (1, 0): 0, (0, -1): 90, (0, 1): 270}[(dx, dy)]
            just = [A("justify"), A("right" if lang in (180, 270) else "left"), A("bottom")]
            self.items.append(S(A("label"), net, S(A("at"), ex, ey, lang),
                                S(A("fields_autoplaced"), A("yes")),
                                S(A("effects"), S(A("font"), S(A("size"), 1.27, 1.27)), just),
                                S(A("uuid"), uid())))
            self.netpins.setdefault(net, []).append((ref, num))
        if unknown := set(nets) - used:
            raise SystemExit("%s: unknown pins %s" % (ref, sorted(unknown)))

    def text(self, s, x, y, size=1.27):
        self.items.append(S(A("text"), s, S(A("exclude_from_sim"), A("no")),
                            S(A("at"), x, y, 0),
                            S(A("effects"), S(A("font"), S(A("size"), size, size)),
                              S(A("justify"), A("left"), A("top"))),
                            S(A("uuid"), uid())))

    def check(self):
        """fail if stubs/labels of different nets touch (accidental shorts)"""
        lab = {}
        for it in self.items:
            if it[0] == "label":
                lab.setdefault((round(it[2][1], 3), round(it[2][2], 3)), set()).add(it[1])
        segs = []
        for it in self.items:
            if it[0] == "wire":
                a, b = [(round(p[1], 3), round(p[2], 3)) for p in it[1][1:]]
                segs.append((a, b, frozenset(lab.get(a, set()) | lab.get(b, set()))))
        for it in self.items:
            if it[0] == "no_connect":
                p = (round(it[1][1], 3), round(it[1][2], 3))
                segs.append((p, p, frozenset(["<NC>"])))

        def on(p, a, b):
            (x, y), (x1, y1), (x2, y2) = p, a, b
            return ((x1 == x2 == x and min(y1, y2) <= y <= max(y1, y2)) or
                    (y1 == y2 == y and min(x1, x2) <= x <= max(x1, x2)))
        bad = []
        for i, (a, b, n) in enumerate(segs):
            for c, d, m in segs[i + 1:]:
                if n != m and (on(c, a, b) or on(d, a, b) or on(a, c, d) or on(b, c, d)):
                    bad.append((a, sorted(n), sorted(m)))
        if bad:
            raise SystemExit("%s: overlapping connections: %s" % (self.project, bad[:5]))

    def write(self, outdir, rev="v2.0"):
        self.check()
        os.makedirs(outdir, exist_ok=True)
        doc = [A("kicad_sch"), S(A("version"), 20231120), S(A("generator"), "eeschema"),
               S(A("generator_version"), "8.0"), S(A("uuid"), self.root),
               S(A("paper"), self.paper),
               S(A("title_block"), S(A("title"), self.title), S(A("rev"), rev),
                 S(A("comment"), 1, "Generated by hardware/kicad/gen_schematics.py"))]
        doc.append([A("lib_symbols")] + list(self.libs.values()))
        doc += self.items
        doc.append(S(A("sheet_instances"), S(A("path"), "/", S(A("page"), "1"))))
        base = os.path.join(outdir, self.project)
        with open(base + ".kicad_sch", "w") as f:
            f.write(dump(doc) + "\n")
        # keep board/net settings already in the project file (KiCad, gen_adapter_pcb.py)
        pro = {}
        if os.path.exists(base + ".kicad_pro"):
            with open(base + ".kicad_pro") as f:
                pro = json.load(f)
        pro.setdefault("meta", {"filename": self.project + ".kicad_pro", "version": 1})
        pro["sheets"] = [[self.root, "Root"]]
        with open(base + ".kicad_pro", "w") as f:
            json.dump(pro, f, indent=2)
        if self.custom:
            lib = [A("kicad_symbol_lib"), S(A("version"), 20231120),
                   S(A("generator"), "gen_schematics")]
            lib += [c for c in self.custom]
            with open(os.path.join(outdir, "MSXExp.kicad_sym"), "w") as f:
                f.write(dump(lib) + "\n")
            with open(os.path.join(outdir, "sym-lib-table"), "w") as f:
                f.write('(sym_lib_table\n  (version 7)\n  (lib (name "MSXExp")(type "KiCad")'
                        '(uri "${KIPRJMOD}/MSXExp.kicad_sym")(options "")(descr "MSX expander parts"))\n)\n')
        return base + ".kicad_sch"


# --------------------------------------------------------------------------
# MSX slot pinout (cartridge numbering)
# --------------------------------------------------------------------------
MSX_PINS = {
    1: "CS1n", 2: "CS2n", 3: "CS12n", 4: "SLTSLn", 5: "RSV5", 6: "RFSHn",
    7: "WAITn", 8: "INTn", 9: "M1n", 10: "BUSDIRn", 11: "IORQn", 12: "MREQn",
    13: "WRn", 14: "RDn", 15: "RESETn", 16: "RSV16",
    17: "A9", 18: "A15", 19: "A11", 20: "A10", 21: "A7", 22: "A6", 23: "A12",
    24: "A8", 25: "A14", 26: "A13", 27: "A1", 28: "A0", 29: "A3", 30: "A2",
    31: "A5", 32: "A4", 33: "D1", 34: "D0", 35: "D3", 36: "D2", 37: "D5",
    38: "D4", 39: "D7", 40: "D6", 41: "GND", 42: "CLOCK", 43: "GND", 44: "SW1",
    45: "+5V", 46: "SW2", 47: "+5V", 48: "+12V", 49: "SOUNDIN", 50: "-12V",
}

FP_IDC = "Connector_IDC:IDC-Header_2x25_P2.54mm_Vertical"
FP_IDC_RA = "Connector_IDC:IDC-Header_2x25_P2.54mm_Horizontal"    # adapter: right-angle
# expander J1: right-angle header with the odd row (+5V 45/47) on the opening (cable) side
FP_IDC_RA_ODD_FRONT = "MSXExp:IDC-Header_2x25_P2.54mm_Horizontal_OddRowFront"


IDC_ROW_MIRROR = False     # True: slot pin N <-> IDC N+1 (N odd) / N-1 (N even)


def idc_pin(n):
    """50pin IDC header pin <-> MSX slot pin (Daewoo rear-slot pinout).
    Currently 1:1 (IDC pin N = slot pin N, +5V on IDC 45/47). With
    IDC_ROW_MIRROR the odd/even rows are swapped (+5V on IDC 46/48).
    The mapping is its own inverse either way."""
    if not IDC_ROW_MIRROR:
        return n
    return n + 1 if n % 2 else n - 1


IDC_PINS = {idc_pin(p): n for p, n in MSX_PINS.items()}   # IDC pin -> signal
FP_EDGE = "MSXExp:MSX_CardEdge_50P_P2.54mm"          # custom, see docs
FP_SLOT = "MSXExp:MSX_Slot_AMP5530843"               # custom, see docs
FP_SO20 = "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm"
FP_SO14 = "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
FP_C = "Capacitor_SMD:C_0805_2012Metric"
FP_R = "Resistor_SMD:R_0805_2012Metric"
FP_RN = "Resistor_THT:R_Array_SIP5"


# --------------------------------------------------------------------------
# Adapter: MSX cartridge edge -> 50pin IDC (passive, slot pin N -> IDC pin idc_pin(N))
# --------------------------------------------------------------------------
def build_adapter():
    s = Sch("adapter", "MSX Slot -> 50pin IDC Adapter (Daewoo rear-slot compatible)", "A3")
    nets = {}
    for p, n in MSX_PINS.items():
        if n in ("RSV5", "RSV16", "SW1", "SW2"):
            n = "MSX_" + n          # passed through anyway (1:1 cable)
        nets[str(p)] = n
    s.place("Connector_Generic", "Conn_02x25_Odd_Even", "J1", "MSX_CardEdge(to MSX slot)",
            60.96, 50.8, nets, fp=FP_EDGE)
    s.place("Connector_Generic", "Conn_02x25_Odd_Even", "J2", "IDC50(Daewoo pinout)",
            203.2, 50.8, {str(idc_pin(int(p))): n for p, n in nets.items()}, fp=FP_IDC_RA)
    s.place("power", "PWR_FLAG", "#FLG01", "PWR_FLAG", 127, 30.48, {"1": "GND"})
    s.place("power", "PWR_FLAG", "#FLG02", "PWR_FLAG", 139.7, 30.48, {"1": "+5V"})
    s.text("J1 = card edge plugged into MSX cartridge slot.\n"
           "J2 = 2x25 2.54mm right-angle box header (bottom side, opening at the cartridge top).\n"
           "IDC pin N = MSX slot pin N (+5V = IDC 45, 47; odd row toward the card edge).\n"
           "Same numbering as Daewoo rear expansion header (verify orientation: docs/expander_v2.md).\n"
           "Cable: 50-core flat ribbon, both IDC sockets same orientation (pin1-pin1).\n"
           "Optional: C1 100uF on +5V near J2 is NOT fitted (keep passive).",
           20.32, 152.4)
    return s


# --------------------------------------------------------------------------
# Expander
# --------------------------------------------------------------------------
# CPLD (XC9536XL VQ44) pin assignment. The PCB brings the slot-side bus into
# the CPLD from the left in slot-row order (top to bottom: D6 D7 D4 D5 ... RD,
# WR); with U7 rotated 180 deg the pins 12..44 run counter-clockwise along the
# top, left and bottom edges in exactly that order, so the tracks fan in
# without crossing. /WR stays on P1 (GCK3, register clock); JTAG and supply
# pins are fixed by the package.
_CPLD_ORDER = ["D6", "D7", "D4", "D5", "D2", "D3", "D0", "D1", "A4", "A5", "A2", "A3",
               "A0", "A1", "A13", "A14", "A8", "A12", "A6", "A7", "A10", "A11", "A15",
               "A9", "RESETn", "RDn"]
_CPLD_SLOTS = [12, 13, 14, 16, 18, 19, 20, 21, 22, 23, 27, 28, 29, 30, 31, 32, 33, 34,
               36, 37, 38, 39, 40, 41, 42, 43]
CPLD_PINS = {str(p): n for p, n in zip(_CPLD_SLOTS, _CPLD_ORDER)}
CPLD_PINS.update({"1": "WRn", "44": "DATA_DIR", "2": "EXTSLT0n", "3": "EXTSLT1n",
                  "5": "EXTSLT2n", "6": "EXTSLT3n", "7": "SLTSLn", "8": "BUSDIR_INn"})


def write_ucf():
    """CPLD_v2/EXT_SLT_BUF.ucf from CPLD_PINS (net names of EXT_SLT_BUF.v)."""
    def hdl(n):
        m = re.fullmatch(r"([AD])(\d+)", n)
        if m:
            return "SLT_%s<%s>" % (m.group(1), m.group(2))
        m = re.fullmatch(r"EXTSLT(\d)n", n)
        if m:
            return "EXTSLTn<%s>" % m.group(1)
        return {"WRn": "SLT_WRn", "RDn": "SLT_RDn", "RESETn": "SLT_RESETn",
                "SLTSLn": "SLT_SLTSLn"}.get(n, n)
    lines = ["# EXT_SLT_BUF (XC9536XL-10VQ44C) - generated by hardware/kicad/gen_schematics.py",
             "# Pins follow the expander PCB (U7): the slot bus enters in row order.",
             "# P1 = GCK3 (register clock on /WR). JTAG P9/P10/P11/P24, supplies P4/15/17/25/26/35."]
    for p, n in sorted(CPLD_PINS.items(), key=lambda kv: int(kv[0])):
        lines.append('NET "%s" LOC = "P%s" ;' % (hdl(n), p))
    path = os.path.join(HERE, "..", "..", "CPLD_v2", "EXT_SLT_BUF.ucf")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
def xc9536xl_vq44():
    io = lambda n, nm: (str(n), nm, "bidirectional")
    left = [io(1, "I/O/GCK3"), io(2, "I/O"), io(3, "I/O"), io(5, "I/O"), io(6, "I/O"),
            io(7, "I/O"), io(8, "I/O"), io(12, "I/O"), io(13, "I/O"), io(14, "I/O"),
            io(16, "I/O"), io(18, "I/O"), io(19, "I/O"), io(20, "I/O"), io(21, "I/O"),
            io(22, "I/O"), io(23, "I/O"), None,
            ("9", "TDI", "input"), ("10", "TMS", "input"), ("11", "TCK", "input"),
            ("24", "TDO", "output")]
    right = [io(27, "I/O"), io(28, "I/O"), io(29, "I/O"), io(30, "I/O"), io(31, "I/O"),
             io(32, "I/O"), io(33, "I/O/GSR"), io(34, "I/O/GTS2"), io(36, "I/O/GTS1"),
             io(37, "I/O"), io(38, "I/O"), io(39, "I/O"), io(40, "I/O"), io(41, "I/O"),
             io(42, "I/O"), io(43, "I/O/GCK1"), io(44, "I/O/GCK2"), None,
             ("15", "VCCINT", "power_in"), ("35", "VCCINT", "power_in"),
             ("26", "VCCIO", "power_in"), None,
             ("4", "GND", "power_in"), ("17", "GND", "power_in"), ("25", "GND", "power_in")]
    return custom_symbol("XC9536XL-VQ44", "U", "XC9536XL-10VQ44C", left, right,
                         width=30.48, fp="Package_QFP:TQFP-44_10x10mm_P0.8mm",
                         ds="https://docs.amd.com/v/u/en-US/ds058")


def build_expander():
    s = Sch("expander", "MSX Buffered 6Slot Expander (4 sub-slots + 2 I/O-only, 50pin IDC input)", "A1")
    X0, Y0 = 25.4, 25.4

    # ---- host connector (from cable) --------------------------------------
    host = {}
    for p, n in IDC_PINS.items():
        if n in ("RSV5", "RSV16", "SW1", "SW2"):
            host[str(p)] = "NC"
        elif n in ("GND", "+12V", "-12V", "SOUNDIN", "WAITn", "INTn"):
            host[str(p)] = n
        elif n == "+5V":
            host[str(p)] = "+5V_HOST"
        else:
            host[str(p)] = "H_" + n
    s.place("Connector_Generic", "Conn_02x25_Odd_Even", "J1", "IDC50 HOST (Daewoo pinout)",
            X0 + 12.7, Y0 + 30.48, host, fp=FP_IDC_RA_ODD_FRONT)

    # ---- unidirectional buffers 74HCT541 x4 --------------------------------
    # Channel order follows the slot pin rows (channel 1 = pins 2/18 = topmost on
    # the PCB = highest slot pin number), so J1 -> buffer -> slot bus needs
    # almost no crossings. The PCB stacks U2, U5, U1, U3, U4 from the top.
    groups = [
        ["A3", "A0", "A1", "A13", "A14", "A8", "A12", "A6"],             # U1: slot pins 29..22
        ["CLOCK", "A4", "A5", "A2", None, None, None, None],             # U2: pins 42, 32..30
        ["A7", "A10", "A11", "A15", "A9", "RESETn", "RDn", "WRn"],       # U3: pins 21..13
        ["MREQn", "IORQn", "M1n", "RFSHn", "SLTSLn", "CS12n", "CS2n", "CS1n"],  # U4: pins 12..1
    ]
    for i, g in enumerate(groups):
        nets = {"1": "GND", "19": "GND", "10": "GND", "20": "VCC"}
        for k, sig in enumerate(g):
            a, y = str(2 + k), str(18 - k)
            if sig:
                nets[a] = "H_" + sig
                nets[y] = sig
            else:
                nets[a] = "GND"
                nets[y] = "NC"
        s.place("74xx", "74HCT541", "U%d" % (i + 1), "74HCT541",
                X0 + 76.2, Y0 + 25.4 + i * 50.8, nets, fp=FP_SO20)

    # ---- data buffer 74HCT245 (A = host, B = slot side) --------------------
    nets = {"1": "DATA_DIR", "19": "GND", "10": "GND", "20": "VCC"}
    for k, d in enumerate([6, 7, 4, 5, 2, 3, 0, 1]):     # slot pins 40..33
        nets[str(2 + k)] = "H_D%d" % d
        nets[str(18 - k)] = "D%d" % d
    s.place("74xx", "74HC245", "U5", "74HCT245", X0 + 76.2, Y0 + 228.6, nets, fp=FP_SO20)

    # ---- BUSDIR combiner 74HCT21 -----------------------------------------
    # gate 1: sub-slots 0-3, gate 2: I/O-only slots 4-5 + gate 1 -> BUSDIR_INn
    s.place("74xx", "74LS21", "U6", "74HCT21", X0 + 76.2, Y0 + 279.4,
            {"1": "BUSDIR_S0n", "2": "BUSDIR_S1n", "4": "BUSDIR_S2n", "5": "BUSDIR_S3n",
             "6": "BUSDIR_S03n"}, unit=1, fp=FP_SO14)
    s.place("74xx", "74LS21", "U6", "74HCT21", X0 + 76.2, Y0 + 304.8,
            {"9": "BUSDIR_S4n", "10": "BUSDIR_S5n", "12": "BUSDIR_S03n", "13": "VCC",
             "8": "BUSDIR_INn"}, unit=2, fp=FP_SO14)
    s.place("74xx", "74LS21", "U6", "74HCT21", X0 + 101.6, Y0 + 292.1,
            {"14": "VCC", "7": "GND"}, unit=3, fp=FP_SO14)

    # ---- CPLD ---------------------------------------------------------------
    ucf = dict(CPLD_PINS)
    ucf.update({"9": "TDI", "10": "TMS", "11": "TCK", "24": "TDO",
                "15": "+3V3", "35": "+3V3", "26": "+3V3", "4": "GND", "17": "GND", "25": "GND"})
    write_ucf()
    s.place("MSXExp", "XC9536XL-VQ44", "U7", "XC9536XL-10VQ44C", X0 + 152.4, Y0 + 50.8,
            ucf, symdef=xc9536xl_vq44(), fp="Package_QFP:TQFP-44_10x10mm_P0.8mm")
    # host BUSDIR is the data-buffer direction (low while expander drives host bus)
    s.place("Device", "R", "R1", "100", X0 + 152.4, Y0 + 116.84,
            {"1": "DATA_DIR", "2": "H_BUSDIRn"}, fp=FP_R)
    s.place("Connector_Generic", "Conn_01x06", "J3", "JTAG", X0 + 152.4, Y0 + 132.08,
            {"1": "+3V3", "2": "GND", "3": "TCK", "4": "TDO", "5": "TDI", "6": "TMS"},
            fp="Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical")

    # 3.3V regulator
    s.place("Regulator_Linear", "AP2112K-3.3", "U8", "AP2112K-3.3", X0 + 152.4, Y0 + 157.48,
            {"1": "VCC", "2": "GND", "3": "VCC", "5": "+3V3"},
            fp="Package_TO_SOT_SMD:SOT-23-5")
    s.place("Device", "C", "C1", "1u", X0 + 137.16, Y0 + 157.48, {"1": "VCC", "2": "GND"}, fp=FP_C)
    s.place("Device", "C", "C2", "1u", X0 + 172.72, Y0 + 157.48, {"1": "+3V3", "2": "GND"}, fp=FP_C)

    # ---- pull-ups -----------------------------------------------------------
    s.place("Device", "R_Network04", "RN1", "4.7k", X0 + 190.5, Y0 + 180.34,
            {"1": "VCC", "2": "D0", "3": "D1", "4": "D2", "5": "D3"}, fp=FP_RN)
    s.place("Device", "R_Network04", "RN2", "4.7k", X0 + 210.82, Y0 + 180.34,
            {"1": "VCC", "2": "D4", "3": "D5", "4": "D6", "5": "D7"}, fp=FP_RN)
    s.place("Device", "R_Network04", "RN3", "4.7k", X0 + 231.14, Y0 + 180.34,
            {"1": "VCC", "2": "SLTSL_S0n", "3": "SLTSL_S1n", "4": "SLTSL_S2n",
             "5": "SLTSL_S3n"}, fp=FP_RN)
    s.place("Device", "R_Network04", "RN4", "10k", X0 + 251.46, Y0 + 180.34,
            {"1": "VCC", "2": "BUSDIR_S0n", "3": "BUSDIR_S1n", "4": "BUSDIR_S2n",
             "5": "BUSDIR_S3n"}, fp=FP_RN)
    # I/O-only slots: /SLTSL held inactive, /BUSDIR pulled up
    s.place("Device", "R_Network04", "RN5", "10k", X0 + 271.78, Y0 + 180.34,
            {"1": "VCC", "2": "BUSDIR_S4n", "3": "BUSDIR_S5n", "4": "SLTSL_S4n",
             "5": "SLTSL_S5n"}, fp=FP_RN)

    # ---- slots ------------------------------------------------------------
    for k in range(6):
        nets = {}
        for p, n in MSX_PINS.items():
            if n in ("RSV5", "RSV16", "SW1", "SW2"):
                v = "NC"
            elif n == "SLTSLn":
                v = "SLTSL_S%dn" % k
            elif n == "BUSDIRn":
                v = "BUSDIR_S%dn" % k
            elif n == "SOUNDIN":
                v = "SOUND_S%d" % k
            elif n == "+5V":
                v = "VCC"
            else:
                v = n
            nets[str(p)] = v
        sx = X0 + 297.18 + (k % 2) * 101.6
        sy = Y0 + 45.72 + (k // 2) * 109.22
        ref = "J%d" % (4 + k)     # J4-J9
        label = "MSX SLOT %d (sub-slot %d)" % (k, k) if k < 4 else "MSX SLOT %d (I/O only)" % k
        s.place("Connector_Generic", "Conn_02x25_Odd_Even", ref, label, sx, sy, nets, fp=FP_SLOT)
        if k < 4:
            # slot enable switch (sub-slots only)
            s.place("Switch", "SW_SPDT", "SW%d" % (k + 1), "SLOT%d ON/OFF" % k,
                    sx + 55.88, sy - 12.7,
                    {"2": "SLTSL_S%dn" % k, "1": "EXTSLT%dn" % k, "3": "NC"},
                    fp="Button_Switch_THT:SW_Slide_SPDT_Angled_CK_OS102011MA1Q")
        # sound jumper: 2-pin header + shunt (fitted by default, pull to isolate)
        s.place("Jumper", "Jumper_2_Bridged", "JP%d" % (k + 1 if k < 4 else k + 2), "SOUND%d" % k,
                sx + 55.88, sy + 5.08, {"1": "SOUND_S%d" % k, "2": "SOUNDIN"},
                fp="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")

    # ---- power ---------------------------------------------------------------
    PX, PY = X0 + 152.4, Y0 + 304.8
    s.place("Connector", "Barrel_Jack", "J2", "DC5V IN (5.5/2.1, center +)", PX, PY,
            {"1": "+5V_EXT", "2": "GND"},
            fp="Connector_BarrelJack:BarrelJack_Horizontal")
    s.place("Relay", "Relay_SPST-NO", "K1", "G5NB-1A DC5", PX + 30.48, PY,
            {"A1": "+5V_HOST", "A2": "GND", "13": "+5V_EXT", "14": "RLY_OUT"},
            fp="Relay_THT:Relay_SPST_Omron_G5NB")
    s.place("Device", "D", "D1", "1N4148W", PX + 50.8, PY,
            {"1": "+5V_HOST", "2": "GND"}, fp="Diode_SMD:D_SOD-123")
    s.place("Jumper", "Jumper_3_Open", "JP5", "PWR INT/EXT", PX + 71.12, PY,
            {"1": "+5V_HOST", "2": "VCC", "3": "RLY_OUT"},
            fp="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical")
    s.place("Device", "C_Polarized", "C3", "220u", PX + 91.44, PY, {"1": "VCC", "2": "GND"},
            fp="Capacitor_THT:CP_Radial_D6.3mm_P2.50mm")
    # ---- sound out: passive resistor mix of the six slot SOUND pins -> 3.5mm jack
    AX, AY = PX, PY + 40.64
    for k in range(6):     # R2-R7: slot k SOUND (slot side of its JP) -> mix node
        s.place("Device", "R", "R%d" % (2 + k), "2.2k", AX + k * 10.16, AY,
                {"1": "SOUND_S%d" % k, "2": "SND_MIX"}, fp=FP_R)
    s.place("Device", "C", "C13", "10u", AX + 66.04, AY, {"1": "SND_MIX", "2": "SND_OUT"}, fp=FP_C)
    s.place("Device", "R", "R8", "47k", AX + 76.2, AY, {"1": "SND_OUT", "2": "GND"}, fp=FP_R)
    s.place("Connector_Audio", "AudioJack3", "J10", "SOUND OUT (3.5mm, mono on L+R)", AX + 96.52, AY,
            {"T": "SND_OUT", "R": "SND_OUT", "S": "GND"},
            fp="Connector_Audio:Jack_3.5mm_CUI_SJ1-3523N_Horizontal")
    # decoupling
    for i in range(6):     # C4-C9: U1-U6
        s.place("Device", "C", "C%d" % (4 + i), "100n", PX + 109.22 + i * 10.16, PY,
                {"1": "VCC", "2": "GND"}, fp=FP_C)
    for i in range(3):
        s.place("Device", "C", "C%d" % (10 + i), "100n", PX + 172.72 + i * 10.16, PY,
                {"1": "+3V3", "2": "GND"}, fp=FP_C)
    for i, n in enumerate(["GND", "VCC", "+5V_HOST", "+5V_EXT"]):
        s.place("power", "PWR_FLAG", "#FLG0%d" % (i + 1), "PWR_FLAG",
                PX + 215.9 + i * 12.7, PY, {"1": n})

    s.text("NOTES\n"
           "- J1: IDC pin N = MSX slot pin N (Daewoo rear-slot pinout, +5V = IDC 45/47). Connect to MSX via\n"
           "  50-core ribbon + adapter board, or directly to Daewoo CPC/DPC rear expansion header.\n"
           "- U1-U4 (74HCT541) buffer host->slot. U5 (74HCT245) data: DATA_DIR=H host->slot,\n"
           "  DATA_DIR=L slot->host (memory read of this primary slot, or I/O read with BUSDIR).\n"
           "- WAITn / INTn are open-collector wired-OR lines, passed through unbuffered.\n"
           "- CPLD sits on the buffered (slot) side; FFFFh sub-slot register read goes host-ward\n"
           "  through U5. H_BUSDIRn = DATA_DIR (same as v1 behaviour).\n"
           "- JP5: 1-2 = slots powered from MSX, 2-3 = from DC jack (relay K1 enabled by MSX +5V).\n"
           "- Slots 4/5 (J8/J9) are I/O-only: /SLTSL held high (RN5), not part of the sub-slot register.\n"
           "  Their /BUSDIR joins U6 gate 2 so I/O reads from them turn the data buffer around.",
           X0 + 152.4, Y0 + 330.2)
    return s


if __name__ == "__main__":
    a = build_adapter().write(os.path.join(HERE, "adapter"))
    e = build_expander().write(os.path.join(HERE, "expander"))
    print("wrote", a)
    print("wrote", e)
