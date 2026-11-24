"""Drawings (dev add-on drawings): the projection of a model into the lines of a view (dr_proj.py) and the standard sheets (dr_sheet.py) - the standard views look from the right side
(Front +X to the right, Top +X to the right with the back at the top, Right +Y to the right, Bottom with the front at the top), the three axonometric views shorten the axes as they
should (equal, two equal, all different), hidden lines are the ones that are really hidden, circles and arcs stay circles and arcs, the lines survive a round trip through JSON, and
the sheet list is the ANSI A-E and ISO A4-A0 sizes only.   python test_dr_proj.py"""
import faulthandler
faulthandler.dump_traceback_later(250, exit=True)
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "shared"), HERE]
import build123d as b
import numpy as np
import dr_proj as P
import dr_sheet as S

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ----------------------------------------------------------------------------------------------------------------------------------- the sheets
keys = [s[0] for s in S.SIZES]
ok(keys == ["ansi_a", "ansi_b", "ansi_c", "ansi_d", "ansi_e", "iso_a4", "iso_a3", "iso_a2", "iso_a1", "iso_a0"], f"the sheets are ANSI A-E and ISO A4-A0, nothing else ({keys})")
ok(all(w >= h for _k, _l, w, h in S.SIZES), "each is listed as a landscape sheet")
ok(S.DEFAULT == "ansi_a" and S.dims("ansi_a") == (11 * 25.4, 8.5 * 25.4) and S.dims("ansi_a", False) == (8.5 * 25.4, 11 * 25.4), "the default is Letter landscape (11 x 8.5 in); portrait turns it")
ok([round(S.dims(k)[0] / 25.4, 3) for k in keys[:5]] == [11, 17, 22, 34, 44] and [round(S.dims(k)[1] / 25.4, 3) for k in keys[:5]] == [8.5, 11, 17, 22, 34], "ANSI A, B, C, D, E: 11x8.5, 17x11, 22x17, 34x22, 44x34 inches")
ok([S.dims(k) for k in keys[5:]] == [(297.0, 210.0), (420.0, 297.0), (594.0, 420.0), (841.0, 594.0), (1189.0, 841.0)], "ISO A4, A3, A2, A1, A0 in millimetres")
ok(S.size("nonsense")[0] == "ansi_a", "an unknown key gives the default sheet")

# ----------------------------------------------------------------------------------------------------------------------------------- the standard views
ok(P.ORIENTATIONS == ("Front", "Back", "Left", "Right", "Top", "Bottom", "Isometric", "Trimetric", "Dimetric"), "the nine views of the Model View panel")
marker_x = b.Box(10, 10, 10).moved(b.Location((30, 0, 0)))
marker_y = b.Box(10, 10, 10).moved(b.Location((0, 30, 0)))
marker_z = b.Box(10, 10, 10).moved(b.Location((0, 0, 30)))


def box_of(shape, view):
    return P.project(shape, view).bbox()


for view, (axis_x, sign) in {"Front": ("x", 1), "Back": ("x", -1), "Right": ("y", 1), "Left": ("y", -1), "Top": ("x", 1), "Bottom": ("x", 1)}.items():
    shape = marker_x if axis_x == "x" else marker_y
    bb = box_of(shape, view)
    c = (bb[0] + bb[2]) / 2
    ok(near(c, 30.0 * sign) and near(bb[2] - bb[0], 10.0), f"{view}: the marker on +{axis_x.upper()} is {'to the right' if sign > 0 else 'to the left'} of the origin (x = {c:.1f})")
for view in ("Front", "Back", "Left", "Right"):
    bb = box_of(marker_z, view)
    ok(near((bb[1] + bb[3]) / 2, 30.0), f"{view}: Z is up (the marker on +Z is above the origin)")
bb = box_of(marker_y, "Top")
ok(near((bb[1] + bb[3]) / 2, 30.0), "Top: the back (+Y) is at the top of the view")
bb = box_of(marker_y, "Bottom")
ok(near((bb[1] + bb[3]) / 2, -30.0), "Bottom: seen from below, the back (+Y) is at the bottom: the front is at the top")
for view in P.ORIENTATIONS:
    e, u, r = P.view_axes(view)
    ok(near(float(np.linalg.norm(e)), 1) and near(float(e @ u), 0, 1e-9) and near(float(e @ r), 0, 1e-9) and near(float(np.cross(r, u) @ e), 1, 1e-9), f"{view}: right, up and the eye are a right-handed frame")

# a block with distinct sides: the size of the view
blk = b.Box(60, 20, 10)
exp = {"Front": (60, 10), "Back": (60, 10), "Left": (20, 10), "Right": (20, 10), "Top": (60, 20), "Bottom": (60, 20)}
for view, (w, h) in exp.items():
    bb = box_of(blk, view)
    ok(near(bb[2] - bb[0], w) and near(bb[3] - bb[1], h), f"{view} of a 60 x 20 x 10 block is {w} x {h}")

# ----------------------------------------------------------------------------------------------------------------------------------- the axonometric views
def shortening(view):
    e, u, r = P.view_axes(view)
    return [float(np.hypot(a @ r, a @ u)) for a in np.eye(3)]


iso, dim, tri = shortening("Isometric"), shortening("Dimetric"), shortening("Trimetric")
ok(max(iso) - min(iso) < 1e-6 and near(iso[0], math.sqrt(2.0 / 3.0), 1e-6), f"Isometric: the three axes are shortened alike (to {iso[0]:.4f})")
ok(near(dim[0], dim[2], 1e-5) and near(dim[1] / dim[0], 0.5, 1e-3), f"Dimetric: two axes alike, the third half as long (the ratio 1 : 1/2 : 1: {[round(x, 4) for x in dim]})")
ok(len({round(x, 3) for x in tri}) == 3, f"Trimetric: the three axes are shortened differently ({[round(x, 3) for x in tri]})")
e, _u, _r = P.view_axes("Isometric")
ok(e[0] > 0 and e[1] < 0 and e[2] > 0, "Isometric is seen from the front, the right and above")
pi = P.project(blk, "Isometric")
ok(len(pi.vis) == 9 and len(pi.hid) == 3, f"an isometric view of a block: 9 visible edges and 3 hidden ({len(pi.vis)} / {len(pi.hid)})")

# ----------------------------------------------------------------------------------------------------------------------------------- hidden lines
p = P.project(blk, "Top")
ok(len(p.vis) == 4 and len(p.hid) == 0, f"a block from above: 4 edges, and the bottom edges behind them are not 'hidden lines' ({len(p.vis)} / {len(p.hid)})")
plate = b.Box(60, 20, 10) - b.Rot(90, 0, 0) * b.Cylinder(4, 30)                           # a hole along Y
p = P.project(plate, "Front")
circ = [e for e in p.vis if e["t"] == "circle"]
ok(len(circ) == 1 and near(circ[0]["r"], 4.0) and near(circ[0]["c"][0], 0.0, 1e-6) and near(circ[0]["c"][1], 0.0, 1e-6), "the hole seen along its axis is a circle of radius 4 at the middle")
ok(len([e for e in p.vis if e["t"] == "line"]) == 4 and not p.hid, "with the four lines of the outline, and no hidden lines")
p = P.project(plate, "Right")
ok(len(p.hid) == 2 and all(e["t"] == "line" and near(e["a"][1], e["b"][1]) for e in p.hid), "seen from the side the hole is two hidden lines")
ys = sorted(round(e["a"][1], 6) for e in p.hid)
ok(near(ys[0], -4.0, 1e-6) and near(ys[1], 4.0, 1e-6), f"at +-4 from the middle, the radius of the hole ({ys})")
p2 = P.project(plate, "Right", hidden=False)
ok(len(p2.hid) == 0 and len(p2.vis) == len(p.vis), "hidden lines can be left out")
ok(p.bbox() == p.bbox(hidden=True) or p.bbox(hidden=True)[0] <= p.bbox()[0], "the view's size is that of the visible lines")

# ----------------------------------------------------------------------------------------------------------------------------------- circles, arcs, free-form lines
rounded = b.Box(40, 40, 10)
rounded = b.fillet(rounded.edges().filter_by(b.Axis.Z), 5)
p = P.project(rounded, "Top")
arcs = [e for e in p.vis if e["t"] == "arc"]
ok(len(arcs) == 4 and all(near(a["r"], 5.0, 1e-6) for a in arcs), f"the rounded corners seen from above are 4 arcs of radius 5 ({len(arcs)})")
ok(all(near(math.degrees(a["a1"] - a["a0"]), 90.0, 1e-3) for a in arcs), "each is a quarter turn, counter-clockwise from a0 to a1")
ok(all(near(math.hypot(a["pts"][0][0] - a["c"][0], a["pts"][0][1] - a["c"][1]), 5.0, 1e-6) and near(a["pts"][0][0], a["c"][0] + 5 * math.cos(a["a0"]), 1e-6) and near(a["pts"][-1][1], a["c"][1] + 5 * math.sin(a["a1"]), 1e-6) for a in arcs), "and its polyline starts and ends on the arc")
cyl = b.Cylinder(10, 30)
p = P.project(cyl, "Front")
ok(sorted(e["t"] for e in p.vis) == ["line", "line", "line", "line"], f"a cylinder from the side: its outline and its two flat ends, all straight lines ({[e['t'] for e in p.vis]})")
p = P.project(cyl, "Isometric")
ok(any(e["t"] in ("poly", "circle") for e in p.vis), "an ellipse (a circle seen at an angle) is a free-form polyline")
ells = [e for e in p.vis if e["t"] == "poly"]
ok(all(len(e["pts"]) >= 8 for e in ells), "with enough points to be drawn smoothly")

# ----------------------------------------------------------------------------------------------------------------------------------- JSON
p = P.project(plate, "Isometric")
txt = json.dumps(p.to_json())
q = P.Projection.from_json(json.loads(txt))
ok(q.name == "Isometric" and len(q.vis) == len(p.vis) and len(q.hid) == len(p.hid), "a projection goes through JSON")
ok(all(isinstance(pt, tuple) for e in q.vis for pt in e["pts"]) and np.allclose(q.bbox(), p.bbox()), "with its points as they were")
ok(sorted(e["n"] for e in q.vis + q.hid) == list(range(len(q.vis) + len(q.hid))), "and every line has its number in the view")
print()
if FAILS:
    print(f"FAILURES: {len(FAILS)}")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
