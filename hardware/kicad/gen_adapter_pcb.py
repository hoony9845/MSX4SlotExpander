#!/usr/bin/env python3
"""
MSX slot -> 50pin IDC adapter: PCB generator (KiCad 8).

Board outline, gold fingers and cartridge-shell post holes are taken from
msx_v9990/hardware/gen/gen_pcb.py (cartridge PCB known to fit real MSX slots
and the Konami-style shell). The adapter is passive: card-edge pin N goes to
IDC header pin idc_pin(N) (rows mirrored, see gen_schematics.py), so every net
is a single track routed here deterministically (no autorouter):

  fingers (2.54mm) --fan-in--> 2.0mm pitch between the two shell holes
                   --fan-out--> 2x25 right-angle box header J2 at the top edge
  J2 (KiCad right-angle box header) sits on the bottom side, pin 1 on the
  right, its opening J2_OVERHANG beyond the top board edge (visible at the top
  of the cartridge). The odd IDC row (1..49, +5V on 45/47) is the lower row
  (toward the fingers), the even row the upper one. With idc_pin() = 1:1:
  odd slot pins (1..49, B.Cu) -> odd IDC row (lower), straight;
  even slot pins (2..50, F.Cu, label side) -> even IDC row (upper), passing
  between the lower-row pads (x + 1.27).

Usage (after gen_schematics.py):
    python3 gen_adapter_pcb.py
    kicad-cli pcb drc --schematic-parity adapter/adapter.kicad_pcb
"""
import json
import math
import os
import subprocess
import sys
import uuid

sys.path.insert(0, "/usr/lib/python3.8/site-packages")
import pcbnew  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen_schematics import idc_pin, parse  # noqa: E402

PROJ = os.path.join(HERE, "adapter")
SCH = os.path.join(PROJ, "adapter.kicad_sch")
PCB = os.path.join(PROJ, "adapter.kicad_pcb")
NET = os.path.join(PROJ, "adapter.net")
LIB = "MSXExp"
LIB_DIR = os.path.join(HERE, LIB + ".pretty")
EDGE_FP = "MSX_CardEdge_50P_P2.54mm"
KICAD_FP = "/usr/share/kicad/footprints"

MM = pcbnew.FromMM


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def u():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Board geometry (mm) - identical to msx_v9990 cartridge (gen_pcb.py)
# ---------------------------------------------------------------------------
EDGE_PIN1_X = 105.682        # x of pins 1/2; pins 49/50 at 105.682 - 24 * 2.54
FINGER_Y = 78.808            # finger centre line
FINGER_W, FINGER_L = 1.5, 8.0
BOARD_BOTTOM = FINGER_Y + FINGER_L / 2
BOARD_TOP = 19.038             # 1mm below the msx_v9990 cartridge top edge (18.038)
BOARD_LEFT, BOARD_RIGHT = 19.602, 120.692
TONGUE_TOP = 70.918
TONGUE_LEFT, TONGUE_RIGHT = 42.812, 107.597
NOTCH_X, NOTCH_Y = 30.112, 59.567


def _corner(cx, cy, a0, a1, r=1.0, n=6):
    return [(round(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), 4),
             round(cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)), 4)) for i in range(n + 1)]


OUTLINE = (
    [(BOARD_LEFT, BOARD_TOP), (BOARD_RIGHT, BOARD_TOP), (BOARD_RIGHT, TONGUE_TOP), (TONGUE_RIGHT, TONGUE_TOP)]
    + _corner(TONGUE_RIGHT - 1.0, BOARD_BOTTOM - 1.0, 0, 90)
    + _corner(TONGUE_LEFT + 1.0, BOARD_BOTTOM - 1.0, 90, 180)
    + [(TONGUE_LEFT, TONGUE_TOP), (NOTCH_X, TONGUE_TOP), (NOTCH_X, NOTCH_Y), (BOARD_LEFT, NOTCH_Y)]
)
HOLES = [(46.862, 61.318, 2.18),     # H2 cartridge-shell post (4.36mm cutout)
         (103.062, 66.718, 2.18)]    # H1
HOLE_KEEPOUT = 0.45
TONGUE = [(TONGUE_LEFT, TONGUE_TOP), (TONGUE_RIGHT, TONGUE_TOP),
          (TONGUE_RIGHT, BOARD_BOTTOM), (TONGUE_LEFT, BOARD_BOTTOM)]

# ---------------------------------------------------------------------------
# Routing geometry
# ---------------------------------------------------------------------------
CENTER_X = EDGE_PIN1_X - 12 * 2.54   # 75.202, pins 25/26
J2_BODY = 13.28                      # right-angle header: odd pin row -> mating face
J2_ROW_TO_EDGE = 1.8                 # upper (even) pad row centre -> top board edge
J2_OVERHANG = round(J2_BODY - 2.54 - J2_ROW_TO_EDGE, 3)   # mating face beyond the top edge
J2_PIN1_X = (BOARD_LEFT + BOARD_RIGHT) / 2 + 12 * 2.54        # header centred on the board width
J2_ORIGIN = (J2_PIN1_X, BOARD_TOP + J2_BODY - J2_OVERHANG)    # footprint origin = IDC pin 1 (lower row)
SQUEEZE = 2.0                        # pitch between the shell holes
Y_FINGER_START = FINGER_Y - FINGER_L / 2 + 0.6   # inside the finger pad
Y_FINGER_EXIT = 74.0                 # leave the finger straight up to here
Y_LOW = 69.5                         # below H1 -> squeezed
Y_HIGH = 57.5                        # above H2 -> fan out
Y_HEADER = 50.0                      # header column positions reached
W_SIG, W_PWR, W_PWR_NARROW = 0.3, 0.6, 0.4
POWER = ("/GND", "/+5V")


def write_edge_footprint():
    """MSX cartridge edge: odd pins on B.Cu, even on F.Cu, pins 1/2 on the right
    seen from the component (label) side. Pin 44 (SW1) 1mm shorter at the edge."""
    os.makedirs(LIB_DIR, exist_ok=True)
    font = "(effects (font (size 1 1) (thickness 0.15)))"
    lines = [
        f'(footprint "{EDGE_FP}" (version 20240108) (generator "pcbnew") (generator_version "8.0") (layer "F.Cu")',
        '  (descr "MSX cartridge edge connector, 50 contacts, 2.54mm pitch. Odd pins on B.Cu, even pins on F.Cu, '
        'pins 1/2 on the right seen from the component side. Order with gold fingers + 45 deg bevel.")',
        '  (tags "MSX cartridge edge connector")',
        f'  (property "Reference" "J1" (at -34 -3 0) (layer "F.SilkS") (uuid "{u()}") {font})',
        f'  (property "Value" "{EDGE_FP}" (at 0 6 0) (layer "F.Fab") (uuid "{u()}") {font})',
        f'  (property "Footprint" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{u()}") {font})',
        f'  (property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{u()}") {font})',
        f'  (property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{u()}") {font})',
        '  (attr exclude_from_pos_files allow_missing_courtyard)',
    ]
    for n in range(1, 51):
        k = (n - 1) // 2
        x = (12 - k) * 2.54
        layer = '"B.Cu" "B.Mask"' if n % 2 else '"F.Cu" "F.Mask"'
        length, y = (FINGER_L - 1.0, -0.5) if n == 44 else (FINGER_L, 0.0)
        lines.append(f'  (pad "{n}" connect rect (at {x:.3f} {y}) (size {FINGER_W} {length}) '
                     f'(layers {layer}) (uuid "{u()}"))')
    for txt, x, layer, mirror in (("2", 30.48, "F.SilkS", ""), ("50", -30.48, "F.SilkS", ""),
                                  ("1", 30.48, "B.SilkS", " (justify mirror)"),
                                  ("49", -30.48, "B.SilkS", " (justify mirror)")):
        lines.append(f'  (fp_text user "{txt}" (at {x} -5.6 0) (layer "{layer}") (uuid "{u()}") '
                     f'(effects (font (size 1 1) (thickness 0.15)){mirror}))')
    lines.append(f'  (fp_rect (start -31.5 -4.2) (end 31.5 4.2) (stroke (width 0.05) (type default)) '
                 f'(fill none) (layer "F.CrtYd") (uuid "{u()}"))')
    lines.append(")")
    with open(os.path.join(LIB_DIR, EDGE_FP + ".kicad_mod"), "w") as f:
        f.write("\n".join(lines) + "\n")


def write_project_files():
    """Design rules (JLCPCB 2-layer friendly), net classes, DRU, fp-lib-table.
    Merged into the .kicad_pro written by gen_schematics.py."""
    pro_path = os.path.join(PROJ, "adapter.kicad_pro")
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
        "track_widths": [0.0, 0.3, 0.4, 0.6],
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
    ns["classes"] = [netclass("Default", W_SIG, 2147483647), netclass("Power", W_PWR_NARROW, 0)]
    ns["netclass_patterns"] = [{"netclass": "Power", "pattern": p} for p in ("/GND", "/+5V", "/+12V", "/-12V")]
    with open(pro_path, "w") as f:
        json.dump(pro, f, indent=2)
    with open(os.path.join(PROJ, "adapter.kicad_dru"), "w") as f:
        f.write('(version 1)\n'
                '# The gold fingers run right up to the bottom board edge (bevelled at the fab).\n'
                '(rule "gold_fingers_to_edge"\n'
                '  (condition "A.memberOfFootprint(\'J1\')")\n'
                '  (constraint edge_clearance (min 0)))\n')
    with open(os.path.join(PROJ, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table (version 7)\n'
                f'  (lib (name "{LIB}")(type "KiCad")(uri "${{KIPRJMOD}}/../{LIB}.pretty")(options "")'
                '(descr "MSX 4Slot Expander footprints"))\n)\n')


def load_netlist():
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", NET, SCH],
                   check=True, capture_output=True)
    root = parse(open(NET).read())[0]
    get = lambda e, k: next((x for x in e if isinstance(x, list) and x and x[0] == k), None)
    comps = {}
    for c in get(root, "components")[1:]:
        if isinstance(c, list) and c[0] == "comp":
            comps[get(c, "ref")[1]] = dict(value=get(c, "value")[1], footprint=get(c, "footprint")[1],
                                           tstamp=get(c, "tstamps")[1])
    nets = {}
    for n in get(root, "nets")[1:]:
        if isinstance(n, list) and n[0] == "net":
            nodes = [(get(nd, "ref")[1], get(nd, "pin")[1]) for nd in n[1:]
                     if isinstance(nd, list) and nd[0] == "node"]
            nets[get(n, "name")[1]] = nodes
    return comps, nets


def load_footprint(fpid):
    lib, name = fpid.split(":")
    path = LIB_DIR if lib == LIB else os.path.join(KICAD_FP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f"footprint not found: {fpid}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def add_segment(board, a, b, layer=pcbnew.Edge_Cuts, width=0.1):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(*a))
    s.SetEnd(V(*b))
    s.SetLayer(layer)
    s.SetWidth(MM(width))
    board.Add(s)


def add_circle(board, c, r, layer=pcbnew.Edge_Cuts, width=0.1):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_CIRCLE)
    s.SetCenter(V(*c))
    s.SetEnd(V(c[0] + r, c[1]))
    s.SetLayer(layer)
    s.SetWidth(MM(width))
    board.Add(s)


def add_text(board, txt, x, y, size=1.0, layer=pcbnew.F_SilkS, bold=False, angle=0):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(txt)
    t.SetPosition(V(x, y))
    t.SetTextAngleDegrees(angle)
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(max(0.15, size * (0.2 if bold else 0.15))))
    if layer == pcbnew.B_SilkS:
        t.SetMirrored(True)
    board.Add(t)


def add_rule_area(board, pts, layers, no_tracks=False, name=""):
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowVias(True)
    z.SetDoNotAllowTracks(no_tracks)
    z.SetDoNotAllowCopperPour(True)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET()
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    z.SetZoneName(name)
    o = z.Outline()
    o.NewOutline()
    for p in pts:
        o.Append(MM(p[0]), MM(p[1]))
    board.Add(z)


def add_track(board, a, b, net, width, layer):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(*a))
    t.SetEnd(V(*b))
    t.SetWidth(MM(width))
    t.SetLayer(layer)
    t.SetNet(net)
    board.Add(t)


def add_via(board, pos, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(*pos))
    v.SetWidth(MM(0.6))
    v.SetDrill(MM(0.3))
    v.SetNet(net)
    board.Add(v)


def route_pin(board, n, net):
    """Card-edge pin n -> J2 pin idc_pin(n) (same column index)."""
    k = (n - 1) // 2
    xf = EDGE_PIN1_X - 2.54 * k        # finger
    x = J2_PIN1_X - 2.54 * k           # header column
    c = CENTER_X + (12 - k) * SQUEEZE
    odd = n % 2 == 1
    layer = pcbnew.B_Cu if odd else pcbnew.F_Cu
    power = net.GetNetname() in POWER
    w = W_PWR if power else W_SIG
    near_y, far_y = J2_ORIGIN[1], J2_ORIGIN[1] - 2.54   # lower row (IDC 1, 3..), upper row (IDC 2, 4..)
    m = idc_pin(n)
    assert (m % 2 == 1) == odd, "routing assumes slot odd pins -> lower IDC row"
    if odd:
        path = [(xf, Y_FINGER_START), (xf, Y_FINGER_EXIT), (c, Y_LOW), (c, Y_HIGH), (x, Y_HEADER), (x, near_y)]
        for a, b in zip(path, path[1:]):
            add_track(board, a, b, net, w, layer)
        if n == 47:                # tie the two +5V pins (IDC 45, 47) along the lower row
            add_track(board, (x, near_y), (x + 2.54, near_y), net, W_PWR_NARROW, layer)
    else:
        t = x + 1.27               # between the lower-row pads
        path = [(xf, Y_FINGER_START), (xf, Y_FINGER_EXIT), (c, Y_LOW), (c, Y_HIGH), (t, Y_HEADER)]
        for a, b in zip(path, path[1:]):
            add_track(board, a, b, net, w, layer)
        wn = W_PWR_NARROW if power else W_SIG
        add_track(board, (t, Y_HEADER), (t, far_y), net, wn, layer)
        add_track(board, (t, far_y), (x, far_y), net, wn, layer)


def main():
    write_edge_footprint()
    write_project_files()
    comps, nets = load_netlist()

    board = pcbnew.NewBoard(PCB)
    board.GetDesignSettings().SetBoardThickness(MM(1.6))
    board.SetCopperLayerCount(2)

    net_items = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        net_items[name] = ni

    fps = {}
    for ref, c in comps.items():
        fp = load_footprint(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH("/" + c["tstamp"]))
        fp.SetSheetname("Root")
        fp.SetSheetfile("adapter.kicad_sch")
        board.Add(fp)
        fps[ref] = fp
    pad_net = {}
    for name, nodes in nets.items():
        for ref, pin in nodes:
            for pad in fps[ref].Pads():
                if pad.GetNumber() == pin:
                    pad.SetNet(net_items[name])
                    if ref == "J1":
                        pad_net[int(pin)] = net_items[name]

    fps["J1"].SetPosition(V(CENTER_X, FINGER_Y))
    fps["J2"].SetPosition(V(*J2_ORIGIN))
    fps["J2"].Flip(fps["J2"].GetPosition(), False)   # bottom side
    fps["J2"].SetOrientationDegrees(90)        # pin 1 right, opening at the top edge
    fps["J2"].Value().SetVisible(False)
    for ref in ("J1", "J2"):
        fps[ref].Reference().SetTextSize(pcbnew.VECTOR2I(MM(1.0), MM(1.0)))
    fps["J2"].Reference().SetPosition(V(J2_PIN1_X + 9.0, J2_ORIGIN[1] - 1.3))
    fps["J2"].Reference().SetTextAngleDegrees(0)
    fps["J1"].Reference().SetPosition(V(TONGUE_LEFT + 4.0, TONGUE_TOP - 0.9))

    # sanity check: J2 pin geometry as assumed by route_pin()
    for p in fps["J2"].Pads():
        n = int(p.GetNumber())
        k = (n - 1) // 2
        ex = (J2_PIN1_X - 2.54 * k, J2_ORIGIN[1] - (0 if n % 2 else 2.54))
        got = (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
        assert abs(got[0] - ex[0]) < 1e-3 and abs(got[1] - ex[1]) < 1e-3, (n, got, ex)

    # outline + shell-post holes
    for a, b in zip(OUTLINE, OUTLINE[1:] + OUTLINE[:1]):
        add_segment(board, a, b)
    for x, y, r in HOLES:
        add_circle(board, (x, y), r)
        pts = [(x + (r + HOLE_KEEPOUT) * math.cos(a * math.pi / 12),
                y + (r + HOLE_KEEPOUT) * math.sin(a * math.pi / 12)) for a in range(24)]
        add_rule_area(board, pts, [pcbnew.F_Cu, pcbnew.B_Cu], no_tracks=True, name="hole_keepout")
    # no vias / no pour on the gold-finger tongue
    add_rule_area(board, TONGUE, [pcbnew.F_Cu, pcbnew.B_Cu], name="gold_fingers")

    for n in range(1, 51):
        route_pin(board, n, pad_net[n])

    # J2 sits right at the top edge, so there is no pour strip above it. Tie the
    # GND pours (left of / right of the header) to the lower-row GND pads with a
    # B.Cu bus between the two pad rows (B.Cu is free there: the odd tracks end
    # at the lower row, the even ones run on F.Cu), ending in a via on each side.
    gnd = board.FindNet("/GND")
    assert gnd is not None
    bus_y = J2_ORIGIN[1] - 1.27
    bus_l, bus_r = J2_PIN1_X - 24 * 2.54 - 3.0, J2_PIN1_X + 4.5
    add_track(board, (bus_l, bus_y), (bus_r, bus_y), gnd, W_PWR_NARROW, pcbnew.B_Cu)
    for n in range(1, 51, 2):
        if pad_net[n].GetNetname() == "/GND":
            x = J2_PIN1_X - 2.54 * ((n - 1) // 2)
            add_track(board, (x, J2_ORIGIN[1]), (x - 1.27, bus_y), gnd, W_PWR_NARROW, pcbnew.B_Cu)
    for bx in (bus_l, bus_r):
        add_via(board, (bx, bus_y), gnd)

    # GND stitching vias in the empty areas (left, right, top strip)
    spots = [(x, y) for x in (20.8, 37.0) for y in range(22, 58, 4)]       # beside the left text block
    spots += [(x, y) for x in (25.0, 29.0, 33.0) for y in (22.0, 26.0, 30.0, 34.0, 57.0)]
    spots += [(x, y) for x in (113.5, 117.5) for y in range(22, 70, 4)]
    for s in sorted(set(spots)):
        if all(math.hypot(s[0] - bx, s[1] - bus_y) > 1.0 for bx in (bus_l, bus_r)):   # clear of the bus vias
            add_via(board, s, gnd)

    # GND pours on both layers
    bb = board.GetBoardEdgesBoundingBox()
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
        for px, py in ((bb.GetX(), bb.GetY()), (bb.GetRight(), bb.GetY()),
                       (bb.GetRight(), bb.GetBottom()), (bb.GetX(), bb.GetBottom())):
            o.Append(px, py)
        board.Add(z)

    # silkscreen
    tx = (BOARD_LEFT + J2_PIN1_X - 24 * 2.54 - 5.6) / 2        # left of the J2 body
    for i, (txt, size, bold) in enumerate((("MSX SLOT", 1.3, True), ("-> 50P IDC", 1.3, True),
                                           ("ADAPTER", 1.3, True), ("for 4Slot", 0.9, False),
                                           ("Expander v2", 0.9, False), ("Daewoo rear", 0.9, False),
                                           ("slot pinout", 0.9, False), ("J2 on bottom", 0.9, False),
                                           ("rev 1.1", 0.9, False))):
        add_text(board, txt, tx, 38.0 + i * 2.0 + (0.6 if i > 2 else 0), size, bold=bold)
    ny, fy = J2_ORIGIN[1], J2_ORIGIN[1] - 2.54
    for txt, x, y in (("1", J2_PIN1_X, ny), ("2", J2_PIN1_X, fy),
                      ("49", J2_PIN1_X - 24 * 2.54, ny), ("50", J2_PIN1_X - 24 * 2.54, fy)):
        dx = 3.0 if x > CENTER_X else -3.2
        add_text(board, txt, x + dx, y, 1.0)                        # F side (J2 body is on B)
        add_text(board, txt, x + dx + (3.0 if dx > 0 else -3.0), y, 1.0, layer=pcbnew.B_SilkS)
    add_text(board, "LABEL SIDE / PINS 2-50", CENTER_X, 72.6, 0.9)
    add_text(board, "PINS 1-49", CENTER_X, 72.6, 0.9, layer=pcbnew.B_SilkS)
    add_text(board, "MSX4SlotExpander adapter - generated by gen_adapter_pcb.py", 75.2, 39.5, 0.9,
             layer=pcbnew.B_SilkS)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    print("wrote", PCB)
    export_fab()


def export_fab():
    """Gerbers + Excellon drill + zip (JLCPCB naming) in adapter/fab/."""
    import glob
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
    zpath = os.path.join(PROJ, "adapter_fab.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(glob.glob(os.path.join(fab, "*"))):
            z.write(f, os.path.basename(f))
    print("wrote", zpath)


if __name__ == "__main__":
    main()
