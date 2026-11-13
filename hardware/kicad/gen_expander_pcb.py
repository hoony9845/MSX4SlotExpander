#!/usr/bin/env python3
"""
MSX 6Slot Expander v2: PCB generator (KiCad 8, 2 layers).

    python3 gen_expander_pcb.py            # place + fixed slot bus, autoroute, pours, fab
    python3 gen_expander_pcb.py place      # only stage 1 (no routing)

Layout (KiCad coordinates, y down; board W x H mm, rectangular):
  - J1 (50pin IDC, right-angle, same part as the adapter J2) on the left edge,
    opening facing left, pins in the same rows as the slot connectors (pin 1/2
    at the bottom); odd row (+5V 45/47) nearer the opening (left), even row right.
  - U1-U5 bus buffers next to J1, CPLD U7 right of slot 5 (bus line ends run into it).
  - six slot connectors J4-J9 (slot 0..5, slot 4/5 I/O only), vertical, pin
    1/2 at the bottom, even pins in the left column (same as v1).
    Pitch 22mm, 27mm between slot 3 and slot 4.
  - power (relay, JP5) below the CPLD, DC jack bottom right, sound jumpers above the slots,
    right-angle slot switches on the bottom edge, pull-ups/U6 below the bus between connectors.

Slot bus (generated here, locked): every bused pin row of the six connectors
is joined by straight horizontal tracks running in the 2.54mm gaps between
the pin rows (one track per layer per gap, 0.3mm; power 0.4mm). Each row's
signals use the gap above the row, except rows 1-5, which are arranged so
that the F.Cu layer stays free up to row 5:

  below row 1   CS2 (B.Cu, y+1.27), CS1 (F.Cu, y+3.0)
  gap 1-2  CS12 (B)   gap 2-3  RFSH (B)   gap 3-4  WAIT (B)
  gap 4-5  INT  (B)   gap 5-6  M1 (B)
  rows 6-24: gap above the row, even pin on F.Cu, odd pin on B.Cu
  above row 25: -12V (B)

That leaves room for the per-slot signals without crossing the bus:
  /SLTSL (pin 4): F.Cu at x_even - 1.27 down to a via below the bus, then B.Cu
  /BUSDIR (pin 10): F.Cu in the channel between the two pin columns, via, B.Cu
  SOUND (pin 49): F.Cu straight up from the pin
Everything else is routed by Freerouting (Specctra DSN/SES), then GND pours.
"""
import glob
import math
import os
import re
import subprocess
import sys

sys.path.insert(0, "/usr/lib/python3.8/site-packages")
import pcbnew  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen_schematics import MSX_PINS, parse  # noqa: E402
from gen_adapter_pcb import add_circle, add_segment, add_text  # noqa: E402

PROJ = os.environ.get("EXP_PROJ", os.path.join(HERE, "expander"))     # variants: another folder
SCH = os.path.join(PROJ, "expander.kicad_sch")
PCB = os.path.join(PROJ, "expander.kicad_pcb")
NET = os.path.join(PROJ, "expander.net")
LIB = "MSXExp"
LIB_DIR = os.path.join(HERE, LIB + ".pretty")
SLOT_FP = "MSX_Slot_AMP5530843"
KICAD_FP = "/usr/share/kicad/footprints"
FREEROUTING = os.path.expanduser("~/tools/freerouting/freerouting-2.4.1.jar")
JAVA = (glob.glob(os.path.expanduser("~/tools/jre25/*/bin/java")) or ["java"])[0]

MM = pcbnew.FromMM
T = pcbnew.ToMM


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


# ---------------------------------------------------------------------------
# Geometry (mm)
# ---------------------------------------------------------------------------
W, H = 206.0, 124.5
Y25 = 36.5                       # pin row 25 (pins 49/50); connector body top 25mm below the edge
                                 # (cartridges are longer than the connector)
Y1 = Y25 + 24 * 2.54             # pin row 1 (pins 1/2) = 75.96
SLOT_X = [54.0 + d for d in (0.0, 22.0, 44.0, 66.0, 93.0, 115.0)]   # 22mm pitch, 27mm between slot 3 and 4
J1_BODY = 13.28                  # right-angle IDC: far pin row -> mating face
SLOT_HOLE_DY = 39.055            # connector mounting holes from the connector centre (v1)
SLOT_YC = (Y1 + Y25) / 2
X_BUS_L = SLOT_X[0] - 8.0        # left end of the bus tracks (buffers are routed to here)
X_PWR_R = SLOT_X[5] + 12.0       # VCC/GND rows end right of slot 5 (autorouted on)
W_SIG, W_PWR = 0.3, 0.4
VIA_DY = 2.1                     # per-slot via below the bus (between CS2 and CS1)
CS1_DY = 3.0
END_DY = 5.0                     # per-slot B.Cu stubs end here (Freerouting continues)
SOUND_END = Y25 - 4.5


def row_y(k):
    """y of pin row k (1 = pins 1/2 ... 25 = pins 49/50)."""
    return Y1 - 2.54 * (k - 1)


def pin_xy(slot, n):
    x = SLOT_X[slot] + (-2.54 if n % 2 == 0 else 2.54)
    return x, row_y((n + 1) // 2)


# ---------------------------------------------------------------------------
# Footprints
# ---------------------------------------------------------------------------
def write_slot_footprint():
    """MSX cartridge slot connector (AMP 5530843-5 / 5530841-5), dimensions from
    the v1 drill data: 2 x 25 pins, 2.54mm pitch, rows 5.08mm apart, 1.0mm
    holes, two 3.5mm fixing holes 78.11mm apart. Origin = connector centre.
    Pin 1/2 at +y (bottom), even pins at -x, odd pins at +x (as on v1)."""
    import uuid
    u = lambda: str(uuid.uuid4())
    font = "(effects (font (size 1 1) (thickness 0.15)))"
    L = [
        f'(footprint "{SLOT_FP}" (version 20240108) (generator "pcbnew") (generator_version "8.0") (layer "F.Cu")',
        '  (descr "MSX cartridge slot connector, 50 contacts, 2.54mm pitch, rows 5.08mm apart '
        '(AMP 5530843-5 / 5530841-5). Geometry from MSX Simple 4Slot Expander v1.")',
        '  (tags "MSX slot cartridge connector")',
        f'  (property "Reference" "J" (at 0 -44 0) (layer "F.SilkS") (uuid "{u()}") {font})',
        f'  (property "Value" "{SLOT_FP}" (at 0 0 90) (layer "F.Fab") (uuid "{u()}") {font})',
        f'  (property "Footprint" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{u()}") {font})',
        f'  (property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{u()}") {font})',
        f'  (property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{u()}") {font})',
        '  (attr through_hole)',
    ]
    for n in range(1, 51):
        k = (n - 1) // 2
        x = -2.54 if n % 2 == 0 else 2.54
        y = 30.48 - 2.54 * k
        shape = "rect" if n == 1 else "circle"
        L.append(f'  (pad "{n}" thru_hole {shape} (at {x} {y:.2f}) (size 1.7 1.7) (drill 1.0) '
                 f'(layers "*.Cu" "*.Mask") (remove_unused_layers no) (uuid "{u()}"))')
    for y in (-39.055, 39.055):
        L.append(f'  (pad "" np_thru_hole circle (at 0 {y}) (size 3.5 3.5) (drill 3.5) '
                 f'(layers "*.Cu" "*.Mask") (uuid "{u()}"))')
    for layer, hw, hh, w in (("F.SilkS", 4.6, 41.9, 0.12), ("F.Fab", 4.5, 41.8, 0.1), ("F.CrtYd", 4.85, 42.15, 0.05)):
        L.append(f'  (fp_rect (start -{hw} -{hh}) (end {hw} {hh}) (stroke (width {w}) (type default)) '
                 f'(fill none) (layer "{layer}") (uuid "{u()}"))')
    for txt, x, y in (("1", 4.4 + 0.9, 30.48 + 2.2), ("2", -4.4 - 0.9, 30.48 + 2.2),
                      ("49", 4.4 + 1.3, -30.48 - 2.2), ("50", -4.4 - 1.3, -30.48 - 2.2)):
        pass   # pin numbers are placed as board text (outside the body)
    L.append(")")
    os.makedirs(LIB_DIR, exist_ok=True)
    with open(os.path.join(LIB_DIR, SLOT_FP + ".kicad_mod"), "w") as f:
        f.write("\n".join(L) + "\n")


J1_FP = "IDC-Header_2x25_P2.54mm_Horizontal_OddRowFront"


def write_j1_footprint():
    """KiCad's right-angle 2x25 box header with the two rows swapped so that the
    odd row (pin 1, +5V on 45/47) is the row nearer the opening (cable side).
    Pad N takes the position of pad N+1 (N odd) / N-1 (N even); pad 1 keeps its
    shape. The real header must have this pin order (odd row at the opening)."""
    src = os.path.join(KICAD_FP, "Connector_IDC.pretty", "IDC-Header_2x25_P2.54mm_Horizontal.kicad_mod")
    text = open(src).read()
    swap = lambda n: n + 1 if n % 2 else n - 1
    pos = {int(m.group(1)): m.group(2) for m in re.finditer(r'\(pad "(\d+)"[^(]*\(at ([^)]*)\)', text)}
    assert len(pos) == 50
    text = re.sub(r'(\(pad "(\d+)"[^(]*\(at )([^)]*)\)',
                  lambda m: f"{m.group(1)}{pos[swap(int(m.group(2)))]})", text)
    text = text.replace('(footprint "IDC-Header_2x25_P2.54mm_Horizontal"', f'(footprint "{J1_FP}"', 1)
    text = text.replace('(descr "', '(descr "Rows swapped: odd row (pin 1) at the opening. ', 1)
    with open(os.path.join(LIB_DIR, J1_FP + ".kicad_mod"), "w") as f:
        f.write(text)


def write_project_files():
    import json
    pro_path = os.path.join(PROJ, "expander.kicad_pro")
    pro = json.load(open(pro_path))
    pro.setdefault("board", {})["design_settings"] = {
        "defaults": {"board_outline_line_width": 0.1, "copper_line_width": 0.2,
                     "silk_line_width": 0.12, "silk_text_size_h": 1.0,
                     "silk_text_size_v": 1.0, "silk_text_thickness": 0.15},
        "rules": {
            "min_clearance": 0.15, "min_track_width": 0.15, "min_connection": 0.13,
            "min_via_annular_width": 0.13, "min_via_diameter": 0.5,
            "min_through_hole_diameter": 0.3, "min_hole_clearance": 0.25,
            "min_hole_to_hole": 0.25, "min_copper_edge_clearance": 0.3,
            "min_silk_clearance": 0.0, "min_text_height": 0.8, "min_text_thickness": 0.12,
            "solder_mask_to_copper_clearance": 0.0,
            "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1,
            "allow_blind_buried_vias": False, "allow_microvias": False,
        },
        "rule_severities": {
            "silk_edge_clearance": "ignore", "silk_over_copper": "warning",
            "silk_overlap": "ignore", "text_height": "warning",
            "lib_footprint_issues": "ignore", "lib_footprint_mismatch": "ignore",
        },
        "track_widths": [0.0, 0.25, 0.3, 0.4, 0.6],
        "via_dimensions": [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.6, "drill": 0.3}],
    }

    def netclass(name, track, prio):
        return {"name": name, "clearance": 0.2, "track_width": track, "via_diameter": 0.6,
                "via_drill": 0.3, "microvia_diameter": 0.3, "microvia_drill": 0.1,
                "diff_pair_width": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
                "wire_width": 6, "bus_width": 12, "line_style": 0,
                "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
                "priority": prio}
    ns = pro.setdefault("net_settings", {})
    ns["meta"] = {"version": 3}
    ns["classes"] = [netclass("Default", 0.25, 2147483647), netclass("Power", 0.4, 0)]
    ns["netclass_patterns"] = [{"netclass": "Power", "pattern": p} for p in
                               ("/GND", "/VCC", "/+5V_HOST", "/+5V_EXT", "/RLY_OUT", "/+3V3")]
    with open(pro_path, "w") as f:
        json.dump(pro, f, indent=2)
    with open(os.path.join(PROJ, "expander.kicad_dru"), "w") as f:
        f.write('(version 1)\n'
                '# A single thermal spoke is acceptable (hand-soldered parts).\n'
                '(rule "thermal_spokes"\n  (constraint min_resolved_spokes 1))\n')
    with open(os.path.join(PROJ, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table (version 7)\n'
                f'  (lib (name "{LIB}")(type "KiCad")(uri "${{KIPRJMOD}}/../{LIB}.pretty")(options "")'
                '(descr "MSX 4Slot Expander footprints"))\n)\n')


def load_netlist():
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", NET, SCH],
                   check=True, capture_output=True)
    root = parse(open(NET).read())[0]
    get = lambda e, k: next((x for x in e if isinstance(x, list) and x and x[0] == k), None)
    comps, nets = {}, {}
    for c in get(root, "components")[1:]:
        if isinstance(c, list) and c[0] == "comp":
            comps[get(c, "ref")[1]] = dict(value=get(c, "value")[1], footprint=get(c, "footprint")[1],
                                           tstamp=get(c, "tstamps")[1])
    for n in get(root, "nets")[1:]:
        if isinstance(n, list) and n[0] == "net":
            nets[get(n, "name")[1]] = [(get(nd, "ref")[1], get(nd, "pin")[1]) for nd in n[1:]
                                       if isinstance(nd, list) and nd[0] == "node"]
    return comps, nets


def load_footprint(fpid):
    lib, name = fpid.split(":")
    path = LIB_DIR if lib == LIB else os.path.join(KICAD_FP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f"footprint not found: {fpid}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def track(board, a, b, net, width, layer):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(*a))
    t.SetEnd(V(*b))
    t.SetWidth(MM(width))
    t.SetLayer(layer)
    t.SetNet(net)
    t.SetLocked(True)
    board.Add(t)


def via(board, pos, net, locked=True):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(*pos))
    v.SetWidth(MM(0.6))
    v.SetDrill(MM(0.3))
    v.SetNet(net)
    v.SetLocked(locked)
    board.Add(v)


def path(board, pts, net, width, layer):
    for a, b in zip(pts, pts[1:]):
        track(board, a, b, net, width, layer)


# ---------------------------------------------------------------------------
# Placement: ref -> (x, y, rotation)
# ---------------------------------------------------------------------------
X_CPLD = SLOT_X[5] + 23.0          # CPLD zone right of slot 5 (taps the bus line ends)
PLACE = {
    # right-angle box header (odd row at the opening), opening flush with the left
    # board edge: footprint origin = pin 2 here, pins upwards, odd column
    # (pin 1, +5V 45/47; nearer the opening) at x - 2.54
    "J1": (J1_BODY, Y1, 180),
    # buffers stacked in slot-row order (see the channel order in gen_schematics.py)
    "U2": (24.0, 37.0, 0), "U5": (24.0, 51.0, 0), "U1": (24.0, 65.0, 0),
    "U3": (24.0, 79.0, 0), "U4": (24.0, 93.0, 0),
    "R1": (16.5, 106.5, 90),
    # CPLD right of slot 5: address/data/RD/WR/RESET bus tracks run straight into it
    # rotated 180 deg: pins 12..44 run along the top, left and bottom edges in the
    # order the bus tracks arrive (see CPLD_PINS in gen_schematics.py)
    "U7": (X_CPLD, 64.5 + float(os.environ.get("CPLD_DY", "0")), 180),
    "C10": (X_CPLD + 9.0, 61.5, 90), "C11": (X_CPLD + 9.0, 66.5, 90), "C12": (X_CPLD + 9.0, 71.5, 90),
    "U8": (X_CPLD + 2.5, 79.0, 0), "C1": (X_CPLD - 1.5, 79.0, 90), "C2": (X_CPLD + 6.5, 79.0, 90),
    "RN1": (36.0, 23.0, 0), "RN2": (36.0, 27.0, 0),     # D0-D7 pull-ups, top left
    "J3": (SLOT_X[5] + 17.0, 30.0, 90),                  # JTAG, above the CPLD
    # below the bus, between the connectors: SLTSL/BUSDIR pull-ups (slot 0-3) in the
    # wide gap between slot 3 and slot 4, U6 between slot 4 and 5, RN5 right of slot 5
    "RN3": ((SLOT_X[3] + SLOT_X[4]) / 2 - 3.6, H - 6.0, 0),
    "RN4": ((SLOT_X[3] + SLOT_X[4]) / 2 - 3.6, H - 2.4, 0),
    "U6": ((SLOT_X[4] + SLOT_X[5]) / 2 - 1.0, H - 4.0, 90),
    "C9": ((SLOT_X[4] + SLOT_X[5]) / 2 + 5.1, H - 4.0, 90),
    "RN5": (SLOT_X[5] + 8.5, H - 16.5, 270),
    # power section below the CPLD: DC jack (bottom right, facing right), relay
    "J2": (W - 13.9, H - 5.3, 180),
    "K1": (X_CPLD - 4.0, H - 21.5, 270),
    "JP5": (X_CPLD + 6.5, H - 24.5, 270),     # pin 1 (+5V_HOST) right, pin 3 (relay) left
    "D1": (X_CPLD - 6.4, H - 25.2, 0),
    "C3": (X_CPLD + 1.0, H - 17.5, 0),
}
for i, u in enumerate(["U1", "U2", "U3", "U4", "U5"]):
    x, y, _ = PLACE[u]
    PLACE["C%d" % (4 + i)] = (x + 8.2, y - 5.6, 90)     # next to VCC pin 20 (top right)
# right-angle slide switches on the bottom edge (actuator sticking out), centred
# below their slot connector, ~10mm clear of the connector body
SW_Y = H - 2.2
for k in range(4):
    PLACE["SW%d" % (k + 1)] = (SLOT_X[k] - 2.0, SW_Y, 0)
# sound jumpers (2-pin header + shunt) along the top edge above their slot, clear
# of the cartridge (longer than the connector); pin 1 = slot SOUND, pin 2 = SOUNDIN
for k, ref in enumerate(["JP1", "JP2", "JP3", "JP4", "JP6", "JP7"]):
    PLACE[ref] = (SLOT_X[k] - 1.27, 4.6, 90)
    PLACE["R%d" % (2 + k)] = (SLOT_X[k] + 5.2, 4.6, 0)      # 2.2k mix resistor
# sound out: 3.5mm jack on the left edge above J1 (facing left, snout 1.8mm out),
# clear of the M3 screw head at (3.5, 3.5); coupling cap + bleeder right of it
PLACE["J10"] = (4.5, 17.0, 270)
PLACE["C13"] = (19.0, 14.0, 0)
PLACE["R8"] = (19.0, 18.0, 0)

HOLES = [(3.5, 3.5), (3.5, H - 3.5), (W - 3.5, H - 18.0), (W - 3.5, 3.5)]   # M3, 3.2mm (J2 takes the corner)


# ---------------------------------------------------------------------------
# Slot bus
# ---------------------------------------------------------------------------
def bus_plan(slot_nets):
    """[(net, layer, y_line, [(slot, pin)...], width)] for the shared bus."""
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    gap_above = lambda k: row_y(k) - 1.27
    plan = []

    def add(pin, layer, y, width=W_SIG):
        net = slot_nets[0][pin]
        plan.append((net, layer, y, pin, width))

    add(2, B, Y1 + 1.27)            # CS2
    add(1, F, Y1 + CS1_DY)          # CS1
    add(3, B, row_y(1) - 1.27)      # CS12   gap 1-2
    add(6, B, row_y(2) - 1.27)      # RFSH   gap 2-3
    add(7, B, row_y(3) - 1.27)      # WAIT   gap 3-4
    add(8, B, row_y(4) - 1.27)      # INT    gap 4-5
    add(9, B, row_y(5) - 1.27)      # M1     gap 5-6
    for k in range(6, 25):
        for pin in (2 * k - 1, 2 * k):
            name = MSX_PINS[pin]
            if name in ("RSV5", "RSV16", "SW1", "SW2"):
                continue
            power = name in ("GND", "+5V")
            add(pin, F if pin % 2 == 0 else B, gap_above(k), W_PWR if power else W_SIG)
    # unused second layer of the power rows: double them up
    add(43, F, gap_above(22), W_PWR)     # GND (pin 44 = SW1 unused)
    add(45, F, gap_above(23), W_PWR)     # VCC (pin 46 = SW2 unused)
    add(50, B, Y25 - 1.27)               # -12V above row 25
    return plan


TERM_F_L, TERM_B_L = X_BUS_L + 1.5, X_BUS_L - 2.0      # left terminal vias (F lines / B lines)


def route_bus(board, nets_by_name, slot_nets, cpld_nets=()):
    """Bus tracks plus a terminal via at each open end. A line on F.Cu bends half a
    pitch up onto the (empty) pin-row line and ends in a via there, a B.Cu line
    bends half a pitch down; F and B terminals use different x so the vias of
    neighbouring lines never meet. The autorouter then only has to reach a via."""
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    term_f_r, term_b_r = SLOT_X[5] + 6.0, SLOT_X[5] + 9.0
    for net, layer, y, pin, width in bus_plan(slot_nets):
        ni = nets_by_name[net]
        xs = []
        for s in range(6):
            px, py = pin_xy(s, pin)
            xs.append(px)
            track(board, (px, y), (px, py), ni, width, layer)        # stub into the pad
        direct = net in ("/CS1n", "/CS2n", "/-12V")                 # outside the dense rows
        dy = -1.27 if layer == F else 1.27

        def terminal(xt, toward):
            # toward = +1: the line comes from the right (left end), -1: from the left
            if direct:
                track(board, (xt, y), (xt + toward * 1.27, y), ni, width, layer)
                via(board, (xt, y), ni)
                return xt + toward * 1.27
            track(board, (xt + toward * 1.27, y), (xt, y + dy), ni, width, layer)
            via(board, (xt, y + dy), ni)
            return xt + toward * 1.27

        xl = terminal(TERM_F_L if layer == F else TERM_B_L, +1)
        xr = max(xs)
        if net in ("/VCC", "/GND"):
            xr = terminal(X_PWR_R - (1.5 if layer == F else 0.0), -1)
        elif net in cpld_nets:
            xr = terminal(term_f_r if layer == F else term_b_r, -1)
        track(board, (xl, y), (xr, y), ni, width, layer)


def route_per_slot(board, nets_by_name, slot_nets):
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    for s in range(6):
        X = SLOT_X[s]
        xe = X - 2.54
        # /SLTSL (pin 4)
        ni = nets_by_name[slot_nets[s][4]]
        xa = xe - 1.27
        path(board, [(xe, row_y(2)), (xa, row_y(2)), (xa, Y1 + VIA_DY)], ni, W_SIG, F)
        via(board, (xa, Y1 + VIA_DY), ni)
        path(board, [(xa, Y1 + VIA_DY), (xa, Y1 + END_DY)], ni, W_SIG, B)
        # /BUSDIR (pin 10)
        ni = nets_by_name[slot_nets[s][10]]
        path(board, [(xe, row_y(5)), (X, row_y(5)), (X, Y1 + VIA_DY)], ni, W_SIG, F)
        via(board, (X, Y1 + VIA_DY), ni)
        path(board, [(X, Y1 + VIA_DY), (X, Y1 + END_DY - 1.0)], ni, W_SIG, B)
        # SOUND (pin 49): F.Cu straight up past the fixing hole, then to the
        # jumper pin 1 (left) and the 2.2k mix resistor pad 1 (right), see PLACE
        ni = nets_by_name[slot_nets[s][49]]
        xo = X + 2.54
        jx, jy, _ = PLACE["JP%d" % (s + 1 if s < 4 else s + 2)]
        rx, ry, _ = PLACE["R%d" % (2 + s)]
        yb = jy + 3.4
        path(board, [(xo, Y25), (xo, yb), (jx, yb), (jx, jy)], ni, W_SIG, F)
        path(board, [(xo, yb), (rx - 0.91, yb - 1.75), (rx - 0.91, ry)], ni, W_SIG, F)


def gnd_fanout(board, fps, gnd):
    """GND is not autorouted (both layers get a GND pour). Every SMD GND pad gets
    a short fixed track to a via: ICs towards the body (perpendicular to the pad
    row), two-terminal parts away from the other pad."""
    for ref, fp in fps.items():
        pads = list(fp.Pads())
        c = fp.GetPosition()
        for p in pads:
            if p.GetNetname() != "/GND" or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            px, py = T(p.GetPosition().x), T(p.GetPosition().y)
            cx, cy = T(c.x), T(c.y)
            if len(pads) <= 3:            # caps, diodes: away from the other pad
                o = next(q for q in pads if q.GetNumber() != p.GetNumber())
                dx, dy = px - T(o.GetPosition().x), py - T(o.GetPosition().y)
                dist = 1.35
            else:                         # ICs: towards the body, perpendicular to the row
                bb = p.GetBoundingBox()
                if bb.GetHeight() > bb.GetWidth():
                    dx, dy = 0.0, (1.0 if cy > py else -1.0)
                else:
                    dx, dy = (1.0 if cx > px else -1.0), 0.0
                dist = 1.7 if "SOIC-20W" in fp.GetFPIDAsString() else 1.3
                if len(pads) == 5:        # SOT-23-5: away from the body
                    dx, dy, dist = -dx, -dy, 1.3
            n = math.hypot(dx, dy)
            v = (px + dx / n * dist, py + dy / n * dist)
            track(board, (px, py), v, gnd, 0.3, pcbnew.F_Cu)
            via(board, v, gnd)


# ---------------------------------------------------------------------------
def stage_place():
    write_slot_footprint()
    write_j1_footprint()
    write_project_files()
    comps, nets = load_netlist()
    board = pcbnew.NewBoard(PCB)
    board.GetDesignSettings().SetBoardThickness(MM(1.6))
    board.SetCopperLayerCount(2)
    nets_by_name = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets_by_name[name] = ni
    fps = {}
    for ref, c in comps.items():
        fp = load_footprint(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH("/" + c["tstamp"]))
        fp.SetSheetname("Root")
        fp.SetSheetfile("expander.kicad_sch")
        fp.SetExcludedFromBOM(False)        # solder jumpers: keep in step with the symbols
        for g in list(fp.GraphicalItems()):   # J10: no board notch for the jack snout
            if g.GetLayer() == pcbnew.Edge_Cuts:
                fp.Remove(g)
        board.Add(fp)
        fps[ref] = fp
    for name, nodes in nets.items():
        for ref, pin in nodes:
            for pad in fps[ref].Pads():
                if pad.GetNumber() == pin:
                    pad.SetNet(nets_by_name[name])
    for k in range(6):
        PLACE["J%d" % (4 + k)] = (SLOT_X[k], SLOT_YC, 0)
    missing = set(fps) - set(PLACE)
    if missing:
        raise SystemExit(f"no placement for {sorted(missing)}")
    for ref, (x, y, rot) in PLACE.items():
        fps[ref].SetPosition(V(x, y))
        fps[ref].SetOrientationDegrees(rot)
        t = fps[ref].Reference()
        t.SetTextSize(pcbnew.VECTOR2I(MM(0.9), MM(0.9)))
        t.SetTextThickness(MM(0.15))
        fps[ref].Value().SetVisible(False)
    # slot pin <-> net, checked against the footprint geometry
    slot_nets = []
    for k in range(6):
        d = {}
        for p in fps["J%d" % (4 + k)].Pads():
            if p.GetNumber():
                n = int(p.GetNumber())
                d[n] = p.GetNetname()
                ex = pin_xy(k, n)
                got = (T(p.GetPosition().x), T(p.GetPosition().y))
                assert abs(got[0] - ex[0]) < 1e-3 and abs(got[1] - ex[1]) < 1e-3, (k, n, got, ex)
        slot_nets.append(d)
    for n in range(1, 51):
        if MSX_PINS[n] not in ("SLTSLn", "BUSDIRn", "SOUNDIN", "RSV5", "RSV16", "SW1", "SW2"):
            assert len({slot_nets[k][n] for k in range(6)}) == 1, (n, [slot_nets[k][n] for k in range(6)])
    # J1 rows line up with the slot rows
    for p in fps["J1"].Pads():
        n = int(p.GetNumber())
        assert abs(T(p.GetPosition().y) - row_y((n + 1) // 2)) < 1e-3, n

    for ref in ("RN3", "RN4"):          # stacked arrays: reference right of pin 5
        x, y, _ = PLACE[ref]
        fps[ref].Reference().SetPosition(V(x + 10.16 + 3.4, y))
        fps[ref].Reference().SetTextAngleDegrees(0)
    for k in range(4):                  # the "SWn: SLOTk ON" label replaces the reference
        fps["SW%d" % (k + 1)].Reference().SetVisible(False)

    # outline + mounting holes
    pts = [(0, 0), (W, 0), (W, H), (0, H)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        add_segment(board, a, b)
    for x, y in HOLES:
        add_circle(board, (x, y), 1.6)

    cpld_nets = {p.GetNetname() for r in ("U7", "RN1", "RN2") for p in fps[r].Pads()}
    route_bus(board, nets_by_name, slot_nets, cpld_nets)
    route_per_slot(board, nets_by_name, slot_nets)
    # -12V: J1 pin 50 straight to the left terminal via of the -12V bus line
    p50 = next(p for p in fps["J1"].Pads() if p.GetNumber() == "50")
    x50, y50 = T(p50.GetPosition().x), T(p50.GetPosition().y)
    yl = Y25 - 1.27
    path(board, [(x50, y50), (x50 + 1.27, yl), (TERM_B_L, yl)], p50.GetNet(), W_SIG, pcbnew.B_Cu)
    gnd_fanout(board, fps, nets_by_name["/GND"])
    # CPLD TDO and 3V3 pins sit between the incoming bus pins: leave through a
    # via under the package instead of crossing the bus tracks
    u7 = fps["U7"]
    c = u7.GetPosition()
    for p in u7.Pads():
        if p.GetNetname() in ("/TDO", "/+3V3"):
            px, py = T(p.GetPosition().x), T(p.GetPosition().y)
            dx, dy = T(c.x) - px, T(c.y) - py
            if abs(dx) > abs(dy):
                v = (px + math.copysign(1.3, dx), py)
            else:
                v = (px, py + math.copysign(1.3, dy))
            track(board, (px, py), v, p.GetNet(), 0.3, pcbnew.F_Cu)
            via(board, v, p.GetNet())
    # +5V_HOST: J1 pins 45/47 (left) -> along the top edge (round the top right
    # mounting hole) -> down the right edge -> relay coil A1, JP5 pin 1 (D1 autorouted)
    h5 = nets_by_name["/+5V_HOST"]
    p45, p47 = [next(p for p in fps["J1"].Pads() if p.GetNumber() == n) for n in ("45", "47")]
    x45, y45 = T(p45.GetPosition().x), T(p45.GetPosition().y)
    x47, y47 = T(p47.GetPosition().x), T(p47.GetPosition().y)
    xr = W - 1.6
    xh = HOLES[3][0] - 3.7          # top track turns down before the mounting hole
    yt = 2.0                        # top track
    xj = 14.0                       # rises right of the sound jack J10
    yj = PLACE["J10"][1] + 11.5     # jog between J10 and the top of J1
    # THT pads only (this track is on B.Cu); the SMD diode D1 is autorouted
    ends = [next(p for p in fps[r].Pads() if p.GetNumber() == n)
            for r, n in (("K1", "A1"), ("JP5", "1"))]
    y_last = max(T(q.GetPosition().y) for q in ends)
    taps = sorted({T(q.GetPosition().y) for q in ends})
    path(board, [(x45, y45), (x47, y47), (x47 - 2.3, y47), (x47 - 2.3, yj), (xj, yj), (xj, yt), (xh, yt), (xh, 6.0), (xr, 6.0)]
         + [(xr, ty) for ty in taps], h5, 0.6, pcbnew.B_Cu)
    for q in ends:
        qx, qy = T(q.GetPosition().x), T(q.GetPosition().y)
        path(board, [(xr, qy), (qx, qy)], h5, 0.6, pcbnew.B_Cu)

    # silkscreen
    for k in range(6):
        X = SLOT_X[k]
        # between the two pin columns, clear of the pads
        t = "SLOT %d  (sub-slot %d)" % (k, k) if k < 4 else "SLOT %d  I/O ONLY" % k
        add_text(board, t, X, SLOT_YC, 1.2, bold=True, angle=90)
        add_text(board, "1", X + 2.54 + 2.0, Y1 + 0.0, 0.8)
        add_text(board, "2", X - 2.54 - 2.0, Y1 + 0.0, 0.8)
        add_text(board, "49", X + 2.54 + 2.3, Y25, 0.8)
        add_text(board, "50", X - 2.54 - 2.3, Y25, 0.8)
    xt = (SLOT_X[3] + SLOT_X[4]) / 2       # wide gap between slot 3 and 4
    add_text(board, "MSX 6SLOT EXPANDER v2", xt, SLOT_YC, 1.4, bold=True, angle=90)
    add_text(board, "J1: IDC pin N = slot pin N", 33.0, H - 7.0, 0.9)
    add_text(board, "EXT  PWR  INT", PLACE["JP5"][0] - 2.54, PLACE["JP5"][1] - 2.7, 0.8)
    add_text(board, "DC 5V", W - 6.0, H - 12.6, 1.0)
    add_text(board, "SOUND OUT", 7.0, PLACE["J10"][1] + 8.0, 0.9)
    fps["J10"].Reference().SetPosition(V(8.0, PLACE["J10"][1] - 8.0))
    fps["J10"].Reference().SetTextAngleDegrees(0)
    for k in range(4):
        x, y, _ = PLACE["SW%d" % (k + 1)]
        add_text(board, "SW%d: SLOT%d ON" % (k + 1, k), x + 2.0 - 11.0, y, 0.8)
    add_text(board, "generated by gen_expander_pcb.py", xt, SLOT_YC, 0.9, layer=pcbnew.B_SilkS, angle=90)
    pcbnew.SaveBoard(PCB, board)
    print("placed:", PCB)


def unconnected_after(ses):
    """Import a Freerouting result into a scratch copy of the board and count
    the connections KiCad still reports as missing. (Freerouting's own count
    is useless here: it treats the locked bus tracks as unrouted.)"""
    board = pcbnew.LoadBoard(PCB)
    if not pcbnew.ImportSpecctraSES(board, ses):
        return None, None
    add_pours(board)                      # GND is connected by the pours only
    tmp = os.path.join(PROJ, "route_eval.kicad_pcb")
    pcbnew.SaveBoard(tmp, board)
    rpt = os.path.join(PROJ, "route_eval.rpt")
    subprocess.run(["kicad-cli", "pcb", "drc", "-o", rpt, tmp], capture_output=True)
    m = re.search(r"Found (\d+) unconnected", open(rpt).read())
    for f in (tmp, rpt, tmp.replace(".kicad_pcb", ".kicad_prl"), tmp.replace(".kicad_pcb", ".kicad_pro")):
        if os.path.exists(f) and f != PCB:
            os.remove(f)
    return (int(m.group(1)) if m else None), board


def stage_route(passes="100"):
    """Route from the board as it is: from the placed board, or again from an
    already routed one (Freerouting keeps the unlocked tracks and continues)."""
    board = pcbnew.LoadBoard(PCB)
    dsn = os.path.join(PROJ, "route.dsn")
    ses = os.path.join(PROJ, "route.ses")
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        raise SystemExit("DSN export failed")
    text = open(dsn).read().replace("(clearance 200)", "(clearance 220)")
    # GND is connected by the pours (stage_finish): leave it out of autorouting,
    # its pads stay obstacles
    i = text.find("(net /GND")
    if i >= 0:
        depth, j = 0, i
        while True:
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        text = text[:i] + text[j + 1:]
    text = re.sub(r"(\(class Power[^)]*?) /GND", r"\1", text)
    open(dsn, "w").write(text)
    # Freerouting 2.4 gives the same result for every optimizer strategy on this
    # board; the number of passes is what changes the outcome.
    args = os.environ.get("FR_ARGS", "-us hybrid -hr 1:1")
    best = None
    for passes in passes.split(","):
        if os.path.exists(ses):
            os.remove(ses)
        res = subprocess.run([JAVA, "-jar", FREEROUTING, "-de", dsn, "-do", ses, "-mp", passes,
                              "--gui.enabled=false", *args.split()], capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(ses):
            print(f"passes {passes}: failed rc={res.returncode}")
            continue
        n, _ = unconnected_after(ses)
        print(f"passes {passes}: {n} unconnected (KiCad)", flush=True)
        if n is not None and (best is None or n < best[0]):
            best = (n, passes)
            os.replace(ses, ses + ".best")
        if best and best[0] == 0:
            break
    if best is None:
        raise SystemExit("Freerouting failed")
    os.replace(ses + ".best", ses)
    board = pcbnew.LoadBoard(PCB)
    if not pcbnew.ImportSpecctraSES(board, ses):
        raise SystemExit("SES import failed")
    pcbnew.SaveBoard(PCB, board)
    print("routed with", best[1], "passes - unconnected:", best[0])


def add_pours(board):
    gnd = board.FindNet("/GND")
    for t in list(board.GetTracks()):        # stitching vias of a previous run
        if t.GetClass() == "PCB_VIA" and t.GetNetname() == "/GND" and not t.IsLocked():
            board.Remove(t)
    for z in list(board.Zones()):
        if not z.GetIsRuleArea():
            board.Remove(z)
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(gnd)
        z.SetZoneName("GND_" + board.GetLayerName(layer))
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.3))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)
        z.SetThermalReliefGap(MM(0.4))
        z.SetThermalReliefSpokeWidth(MM(0.45))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        o = z.Outline()
        o.NewOutline()
        for x, y in ((0, 0), (W, 0), (W, H), (0, H)):
            o.Append(MM(x), MM(y))
        board.Add(z)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    stitch(board, gnd)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


def stitch(board, gnd, pitch=2.5):
    """GND stitching vias wherever both pours are solid around the point (the
    fill already keeps 0.3mm from everything else, so such a via is safe).
    Ties the pour fragments between the bus tracks to each other."""
    fills = [z.GetFilledPolysList(z.GetFirstLayer()) for z in board.Zones()
             if not z.GetIsRuleArea() and z.GetNetname() == "/GND"]
    ring = [(0.0, 0.0)] + [(0.45 * math.cos(a * math.pi / 4), 0.45 * math.sin(a * math.pi / 4)) for a in range(8)]
    vias = [(T(t.GetPosition().x), T(t.GetPosition().y)) for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    n = 0
    y = 1.5
    while y < H - 1.0:
        x = 1.5
        while x < W - 1.0:
            ok = all(f.Contains(V(x + dx, y + dy)) for f in fills for dx, dy in ring)
            if ok and all(math.hypot(x - vx, y - vy) > 1.0 for vx, vy in vias):
                via(board, (x, y), gnd, locked=False)
                vias.append((x, y))
                n += 1
            x += pitch
        y += pitch
    return n


def drop_single_layer_vias(board):
    """Terminal vias whose tracks all ended up on one layer are not needed."""
    tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    for v in [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]:
        if v.GetNetname() == "/GND":
            continue
        p = v.GetPosition()
        near = lambda q: (q - p).EuclideanNorm() < MM(0.25)
        layers = {t.GetLayer() for t in tracks if t.GetNetCode() == v.GetNetCode()
                  and (near(t.GetStart()) or near(t.GetEnd()))}
        if len(layers) == 1:
            board.Remove(v)


def prune_dangling(board):
    """Remove short tracks with an open end (unused terminal stubs) and vias left
    without tracks, until nothing changes."""
    def pads_at(pt, netcode, layer):
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetCode() == netcode and p.IsOnLayer(layer) and p.HitTest(pt):
                    return True
        return False
    while True:
        items = list(board.GetTracks())
        tracks = [t for t in items if t.GetClass() == "PCB_TRACK"]
        vias = [t for t in items if t.GetClass() == "PCB_VIA"]
        removed = False
        for t in tracks:
            if t.GetLength() > MM(2.0):
                continue
            for end in (t.GetStart(), t.GetEnd()):
                near = lambda q: (q - end).EuclideanNorm() < MM(0.05)
                other = any(o is not t and o.GetNetCode() == t.GetNetCode() and o.GetLayer() == t.GetLayer()
                            and (near(o.GetStart()) or near(o.GetEnd()) or o.HitTest(end))
                            for o in tracks)
                via_ok = any(v.GetNetCode() == t.GetNetCode() and (v.GetPosition() - end).EuclideanNorm() < MM(0.3)
                             for v in vias)
                if not (other or via_ok or pads_at(end, t.GetNetCode(), t.GetLayer())):
                    board.Remove(t)
                    removed = True
                    break
        for v in vias:
            if v.GetNetname() == "/GND":
                continue
            p = v.GetPosition()
            if not any(t.GetNetCode() == v.GetNetCode() and
                       ((t.GetStart() - p).EuclideanNorm() < MM(0.3) or (t.GetEnd() - p).EuclideanNorm() < MM(0.3))
                       for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"):
                board.Remove(v)
                removed = True
        if not removed:
            return


def tidy_tracks(board):
    """Split tracks where another track of the same net ends on them (T-junctions),
    then remove track pieces with an open end (left over from unused terminals)."""
    from collections import defaultdict
    pads = defaultdict(list)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            pads[p.GetNetCode()].append(p)
    near = lambda a, b, d=0.05: (a - b).EuclideanNorm() < MM(d)

    def groups():
        g = defaultdict(list)
        for t in board.GetTracks():
            if t.GetClass() == "PCB_TRACK":
                g[(t.GetNetCode(), t.GetLayer())].append(t)
        return g

    cp = lambda q: pcbnew.VECTOR2I(int(q.x), int(q.y))      # GetStart/GetEnd return references
    for (net, layer), ts in groups().items():
        ends = [cp(q) for o in ts for q in (o.GetStart(), o.GetEnd())]
        for t in ts:
            a, b = cp(t.GetStart()), cp(t.GetEnd())
            def on_axis(q):          # split only at points on the centre line (no geometry change)
                ab = b - a
                L2 = float(ab.x) ** 2 + float(ab.y) ** 2
                if L2 == 0:
                    return False
                u = ((q.x - a.x) * ab.x + (q.y - a.y) * ab.y) / L2
                if not 0 < u < 1:
                    return False
                px, py = a.x + u * ab.x, a.y + u * ab.y
                return math.hypot(q.x - px, q.y - py) < MM(0.002)
            cuts = {(q.x, q.y): q for q in ends
                    if not near(q, a) and not near(q, b) and on_axis(q)}
            if not cuts:
                continue
            ln = (b - a).EuclideanNorm()
            pts = sorted(cuts.values(), key=lambda q: (q - a).EuclideanNorm()) + [b]
            t.SetEnd(pts[0])
            prev = pts[0]
            for q in pts[1:]:
                if (q - prev).EuclideanNorm() < MM(0.01) or ln == 0:
                    continue
                n = pcbnew.PCB_TRACK(board)
                n.SetStart(prev)
                n.SetEnd(q)
                n.SetWidth(t.GetWidth())
                n.SetLayer(t.GetLayer())
                n.SetNet(t.GetNet())
                n.SetLocked(t.IsLocked())
                board.Add(n)
                prev = q

    vias = defaultdict(list)
    for v in board.GetTracks():
        if v.GetClass() == "PCB_VIA":
            vias[v.GetNetCode()].append(v.GetPosition())
    for (net, layer), ts in groups().items():
        ts = list(ts)
        while True:
            def attached(t, pt):
                return (any(o is not t and (near(o.GetStart(), pt) or near(o.GetEnd(), pt) or o.HitTest(pt, 0))
                            for o in ts)
                        or any(near(v, pt, 0.3) for v in vias[net])
                        or any(p.IsOnLayer(layer) and p.HitTest(pt) for p in pads[net]))
            dead = next((t for t in ts if not (attached(t, t.GetStart()) and attached(t, t.GetEnd()))), None)
            if dead is None:
                break
            ts.remove(dead)
            board.Remove(dead)


def stage_finish():
    board = pcbnew.LoadBoard(PCB)
    drop_single_layer_vias(board)
    prune_dangling(board)
    tidy_tracks(board)
    add_pours(board)
    pcbnew.SaveBoard(PCB, board)
    print("filled:", PCB)


def export_fab():
    import zipfile
    fab = os.path.join(PROJ, "fab")
    os.makedirs(fab, exist_ok=True)
    for f in glob.glob(os.path.join(fab, "*")):
        os.remove(f)
    layers = "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
    run = lambda *a: subprocess.run(["kicad-cli", "pcb", "export", *a], check=True, capture_output=True)
    run("gerbers", "--layers", layers, "--subtract-soldermask", "--no-x2", "-o", fab + "/", PCB)
    run("drill", "--format", "excellon", "--excellon-separate-th", "--generate-map",
        "--map-format", "gerberx2", "-o", fab + "/", PCB)
    zpath = os.path.join(PROJ, "expander_fab.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(glob.glob(os.path.join(fab, "*"))):
            z.write(f, os.path.basename(f))
    print("wrote", zpath)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("place", "all"):
        stage_place()
    if what in ("route", "all"):
        stage_route(os.environ.get("PASSES", "60,80,120"))
        # a second round starting from the routed board picks up stragglers
        for _ in range(int(os.environ.get("REROUTE", "2"))):
            stage_route(os.environ.get("PASSES2", "60,120"))
    if what == "reroute":
        stage_route(os.environ.get("PASSES2", "100"))
    if what in ("finish", "all"):
        stage_finish()
        export_fab()
