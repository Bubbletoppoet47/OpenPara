"""Drawings (dev add-on drawings): dimensions, center marks and centerlines (dr_annot.py, and how the drawing document keeps them) - picking points / lines / circles / arcs on a view,
what a pick sequence measures (a length, a distance, a diameter, a radius, an angle), the value is the MODEL's (it does not change with the scale of the view), the lines of a dimension
on the sheet (extension lines with a gap, a dimension line with arrows, numbers above the line and never upside down, a leader for a circle, an arc for an angle), placing by the pointer,
finding the geometry again when the model changes (and calling a dimension lost when it is gone), the file and undo.   python test_dr_annot.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import math
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
import numpy as np
import dr_annot as A
import dr_model as M
import dr_proj as P
import wb_example as ex

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, c, tol=1e-6):
    return abs(a - c) <= tol


def nearp(p, q, tol=1e-6):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def line(a, c):
    return {"t": "line", "a": a, "b": c, "pts": [a, c], "n": 0}


def circle(c, r):
    pts = [(c[0] + r * math.cos(t), c[1] + r * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 49)]
    return {"t": "circle", "c": c, "r": r, "pts": pts, "n": 0}


def arc(c, r, a0, a1):
    ts = np.linspace(a0, a1, 12)
    return {"t": "arc", "c": c, "r": r, "a0": a0, "a1": a1, "pts": [(c[0] + r * math.cos(t), c[1] + r * math.sin(t)) for t in ts], "n": 0}


def proj_of(*ents):
    return P.Projection("x", list(ents), [])


# ----------------------------------------------------------------------------------------------------------------------------------- picking
box = proj_of(line((0, 0), (100, 0)), line((100, 0), (100, 10)), line((100, 10), (0, 10)), line((0, 10), (0, 0)), circle((30, 5), 3))
r = A.pick(box, (0.4, 0.3), 2.0)
ok(r == {"k": "pt", "p": (0, 0)}, "a click near a corner picks the POINT (the corner), not one of the lines that meet there")
r = A.pick(box, (50, 0.8), 2.0)
ok(r["k"] == "line" and r["a"] == (0, 0) and r["b"] == (100, 0), "a click near the middle of a line picks the line")
r = A.pick(box, (33.0, 5.2), 1.0)
ok(r["k"] == "circle" and r["r"] == 3 and r["c"] == (30, 5), "a click on the circle picks the circle")
r = A.pick(box, (30.0, 5.2), 1.0)
ok(r == {"k": "pt", "p": (30, 5)}, "a click at its centre picks the centre point")
ok(A.pick(box, (50, 5), 2.0) is None, "a click in empty space picks nothing")
ok(A.pick(box, (50, 0.8), 2.0, edges=False) is None and A.pick(box, (0.4, 0.3), 2.0, points=False)["k"] == "line", "points only / edges only")
a_ = arc((0, 0), 10, 0.0, math.pi / 2)
bx = proj_of(a_)
ok(A.pick(bx, (7.07, 7.07), 1.0)["k"] == "arc" and A.pick(bx, (-7.07, -7.07), 1.0) is None, "an arc is picked on its sweep only (not on the rest of its circle)")

# ----------------------------------------------------------------------------------------------------------------------------------- what a pick sequence measures
L1, L2 = A.ref_of(line((0, 0), (100, 0))), A.ref_of(line((0, 10), (100, 10)))
L3 = A.ref_of(line((0, 0), (10, 10)))
C1, AR = A.ref_of(circle((30, 5), 3)), A.ref_of(arc((0, 0), 10, 0, 1.5))
P1, P2 = {"k": "pt", "p": (0, 0)}, {"k": "pt", "p": (100, 10)}
ok(A.kind_for([L1]) == "linear" and A.kind_for([C1]) == "diameter" and A.kind_for([AR]) == "radius", "one line is a length, one circle a diameter, one arc a radius")
ok(A.kind_for([P1]) is None and A.more_picks([P1]) and A.more_picks([L1]) and not A.more_picks([C1]), "one point measures nothing yet: another pick is needed")
ok(A.kind_for([P1, P2]) == "linear" and A.kind_for([P1, L2]) == "linear" and A.kind_for([C1, P1]) == "linear", "two points, a point and a line, a circle and a point: a distance")
ok(A.kind_for([L1, L2]) == "linear" and A.kind_for([L1, L3]) == "angle", "two parallel lines: a distance; two lines that meet: an angle")
ok(A.kind_for([L1, L1]) is None and A.kind_for([P1, P1]) is None and A.kind_for([L1, L2, L3]) is None, "the same thing twice, or three things: no dimension")
ok(A.mark_kind_for([C1]) == "center_mark" and A.mark_kind_for([AR]) == "center_mark" and A.mark_kind_for([L1, L2]) == "centerline", "a center mark on a circle or an arc, a centerline between two parallel lines")
ok(A.mark_kind_for([L1, L3]) is None and A.mark_kind_for([L1]) is None and A.mark_kind_for([P1]) is None, "not on two lines that meet, one line, a point")

# ----------------------------------------------------------------------------------------------------------------------------------- the numbers
d_len = A.new_dim([L1], (0, 0, 100, 10))
ok(near(A.value(d_len), 100.0) and A.text(d_len) == "100", "the length of a line: 100")
ok(A.text(d_len, lambda mm: f"{mm / 25.4:.3f}") == "3.937", "shown in the program's units (inches)")
d_h = A.new_dim([P1, P2], (0, 0, 100, 10))
ok(near(A.value(d_h), math.hypot(100, 10)) and d_h["mode"] == "a", "two points: the distance along the line between them")
d_h["mode"] = "h"
ok(near(A.value(d_h), 100.0), "horizontally: 100")
d_h["mode"] = "v"
ok(near(A.value(d_h), 10.0), "vertically: 10")
d_par = A.new_dim([L1, L2], (0, 0, 100, 10))
ok(near(A.value(d_par), 10.0), "two parallel lines: the distance between them (10)")
d_pl = A.new_dim([P2, L1], (0, 0, 100, 10))
ok(near(A.value(d_pl), 10.0), "a point and a line: the distance from the point to the line (10)")
d_di, d_ra = A.new_dim([C1], (0, 0, 100, 10)), A.new_dim([AR], (0, 0, 100, 10))
ok(A.text(d_di) == "⌀6" and A.text(d_ra) == "R10", f"a diameter says ⌀6, a radius says R10 ({A.text(d_di)}, {A.text(d_ra)})")
d_an = A.new_dim([L1, L3], (0, 0, 100, 10))
ok(near(A.value(d_an), 45.0) and A.text(d_an) == "45°", "the angle between two lines: 45°")
L4 = A.ref_of(line((0, 0), (0, 10)))
d_an2 = A.new_dim([L1, L4], (0, 0, 100, 10))
ok(near(A.value(d_an2), 90.0) and A.text(d_an2) == "90°", "a right angle: 90°")
d_an3 = A.new_dim([A.ref_of(line((0, 0), (10, 0))), A.ref_of(line((0, 0), (-10, 10)))], (0, 0, 10, 10))
ok(near(A.value(d_an3), 45.0) or near(A.value(d_an3), 135.0), f"the other way round the corner: 135 or 45 ({A.value(d_an3):.2f})")
ok(A.number_text(33.690067) == "33.6901" and A.number_text(12.0) == "12" and A.number_text(-0.0) == "0", "numbers without trailing zeros")

# ----------------------------------------------------------------------------------------------------------------------------------- the lines on the sheet
d = A.new_dim([L1], (0, 0, 100, 10))
d["side"], d["dist"], d["t"] = 1, 10.0, 0.0
sh = A.shape(d, 1.0, (0.0, 0.0))
ok(sh["kinds"] == ["ext", "ext", "dim"], f"two extension lines and a dimension line ({sh['kinds']})")
e0, e1, dl = sh["segs"]
ok(nearp(e0[0], (0, A.GAP)) and nearp(e0[1], (0, 10 + A.OVER)) and nearp(e1[0], (100, A.GAP)) and nearp(e1[1], (100, 10 + A.OVER)),
   "the extension lines start a gap off the geometry and go a little past the dimension line")
ok(nearp(dl[0], (0, 10)) and nearp(dl[1], (100, 10)), "the dimension line is 10 mm from the geometry")
ok(len(sh["heads"]) == 2 and nearp(sh["heads"][0][0], (0, 10)) and nearp(sh["heads"][0][1], (1, 0)) and nearp(sh["heads"][1][0], (100, 10)) and nearp(sh["heads"][1][1], (-1, 0)),
   "an arrow at each end, pointing outward at the extension lines")
ok(nearp(sh["at"], (50, 10 + A.TEXT_LIFT + A.TEXT_H / 2)) and sh["dir"] == (1.0, 0.0) and sh["anchor"] == "center", "the number is centred above the line")
sh2 = A.shape(d, 2.0, (5.0, 7.0))
dl2 = sh2["segs"][-1]
ok(nearp(dl2[0], (5, 7 + 10)) and nearp(dl2[1], (205, 7 + 10)), "at scale 2 the dimension is twice as long on the sheet and the distance from the geometry is still 10 paper mm")
ok(A.text(d) == "100", "and it still says 100 (the model's value, not the size on paper)")
d["side"] = -1
sh3 = A.shape(d, 1.0, (0.0, 0.0))
ok(nearp(sh3["segs"][-1][0], (0, -10)) and sh3["at"][1] > -10, "on the other side: below the geometry, the number still above its line")
d["side"], d["t"] = 1, 20.0
ok(nearp(A.shape(d, 1.0, (0, 0))["at"], (70, 10 + A.TEXT_LIFT + A.TEXT_H / 2)), "the number can be slid along the dimension line")

# a short dimension: the arrows go outside
ds = A.new_dim([A.ref_of(line((0, 0), (5, 0)))], (0, 0, 5, 5))
ssh = A.shape(ds, 1.0, (0, 0))
ok(nearp(ssh["heads"][0][1], (-1, 0)) and nearp(ssh["heads"][1][1], (1, 0)), "too short for arrows between the lines: they point in from outside")
ok(ssh["segs"][-1][0][0] < 0 and ssh["segs"][-1][-1][0] > 5, "and the dimension line goes on past the extension lines")

# a vertical line: the number reads bottom to top, never upside down
dv = A.new_dim([L4], (0, 0, 10, 10))
dv["side"], dv["dist"] = -1, 8.0
shv = A.shape(dv, 1.0, (0, 0))
ok(shv["dir"][1] > 0 and abs(shv["dir"][0]) < 1e-9, f"the number of a vertical dimension reads upward ({shv['dir']})")
dd = A.new_dim([A.ref_of(line((10, 10), (0, 0)))], (0, 0, 10, 10))
ok(A.shape(dd, 1.0, (0, 0))["dir"][0] > 0, "a line drawn from the right to the left still gets a number that reads left to right")

# two parallel lines: the extension lines start at the near end of each line; none where the dimension line crosses them
dp = A.new_dim([A.ref_of(line((0, 0), (100, 0))), A.ref_of(line((0, 10), (100, 10)))], (0, 0, 100, 10))
dp["side"], dp["dist"] = -1, 20.0
sp = A.shape(dp, 1.0, (0.0, 0.0))
ok(sp["kinds"] == ["ext", "ext", "dim"], f"two parallel lines: two extension lines and the dimension line ({sp['kinds']})")
ok(nearp(sp["segs"][2][0], (120, 0)) and nearp(sp["segs"][2][1], (120, 10)), "placed 20 mm beyond the right ends: the dimension line is at x = 120, from one line to the other")
ok(nearp(sp["segs"][0][0], (100 + A.GAP, 0)) and nearp(sp["segs"][0][1], (120 + A.OVER, 0)) and nearp(sp["segs"][1][0], (100 + A.GAP, 10)) and nearp(sp["segs"][1][1], (120 + A.OVER, 10)),
   "the extension lines start a gap past the END of each line and go on past the dimension line")
dp["dist"] = -50.0
spi = A.shape(dp, 1.0, (0, 0))
ok(spi["kinds"] == ["dim"] and nearp(spi["segs"][0][0], (50, 0)) and nearp(spi["segs"][0][1], (50, 10)), "placed between the lines (x = 50): just the dimension line, no extension lines")

# a circle: diameter and radius
dc = A.new_dim([C1], (0, 0, 100, 10))
dc["lab"] = [20.0, 0.0]
sc = A.shape(dc, 1.0, (0.0, 0.0))
ok(sc["kinds"] == ["dim"] and len(sc["heads"]) == 2, "a diameter: one dimension line with an arrow at each end of the circle")
seg = sc["segs"][0]
ok(nearp(seg[0], (27, 5)) and nearp(seg[1], (50, 5)), "from the far side of the circle, through the centre, out to the label (horizontal here)")
ok(sc["anchor"] == "left" and sc["at"][0] > 50, "the number sits at the end of the leader")
dc["lab"] = [1.0, 1.5]
sc2 = A.shape(dc, 1.0, (0, 0))
ok(sc2["anchor"] == "center" and all(math.hypot(p[0] - 30, p[1] - 5) <= 3.0 + 1e-9 for p in sc2["segs"][0]), "a label inside the circle: the number is centred, the line stays inside")
dr_ = A.new_dim([AR], (0, 0, 10, 10))
dr_["lab"] = [0.0, 20.0]
sr = A.shape(dr_, 1.0, (0.0, 0.0))
ok(len(sr["heads"]) == 1 and nearp(sr["heads"][0][0], (0, 10)) and nearp(sr["segs"][0][0], (0, 0)), "a radius: from the centre out to the arc, one arrow at the arc")
sr2 = A.shape(dr_, 2.0, (0, 0))
ok(nearp(sr2["heads"][0][0], (0, 20)) and A.text(dr_) == "R10", "at scale 2 the arc is twice as far out; the number is still R10")

# an angle
dn = A.new_dim([A.ref_of(line((0, 0), (30, 0))), A.ref_of(line((0, 0), (30, 30)))], (0, 0, 30, 30))
dn["rho"] = 12.0
sn = A.shape(dn, 1.0, (0.0, 0.0))
arc_ = sn["segs"][0]
ok(all(abs(math.hypot(p[0], p[1]) - 12.0) < 1e-9 for p in arc_), "the dimension of an angle is an arc round the corner")
ok(nearp(arc_[0], (12, 0)) and nearp(arc_[-1], (12 / math.sqrt(2), 12 / math.sqrt(2))), "from one line to the other")
ok(sn["kinds"] == ["dim"], f"the lines are longer than the arc: no extension lines needed ({sn['kinds']})")
dn2 = A.new_dim([A.ref_of(line((0, 0), (6, 0))), A.ref_of(line((0, 0), (6, 6)))], (0, 0, 6, 6))
dn2["rho"] = 12.0
sn2 = A.shape(dn2, 1.0, (0, 0))
ok(sn2["kinds"] == ["dim", "ext", "ext"], f"lines shorter than the arc get extension lines ({sn2['kinds']})")
ok(nearp(sn2["segs"][1][0], (6 + A.GAP, 0)) and nearp(sn2["segs"][1][1], (12 + A.OVER, 0)), "from a gap past the end of the line out past the arc")
th = math.radians(22.5)
rr_ = 12 + A.TEXT_LIFT + abs(math.cos(th)) * A.TEXT_W * len("45°") / 2 + abs(math.sin(th)) * A.TEXT_H / 2
ok(nearp(sn["at"], (rr_ * math.cos(th), rr_ * math.sin(th)), 1e-6), "the number is outside the arc, on the middle of the angle")
hw_, hh_ = A.TEXT_W * len("45°") / 2, A.TEXT_H / 2
ok(not any(abs(p[0] - sn["at"][0]) < hw_ and abs(p[1] - sn["at"][1]) < hh_ for p in arc_), "and the box of the number does not touch the arc")
for ang in (30, 45, 90, 135, 170):                                  # whatever the angle, the box stays clear of the arc and the number is where it should be
    lb = A.new_dim([A.ref_of(line((0, 0), (20, 0))), A.ref_of(line((0, 0), (20 * math.cos(math.radians(ang)), 20 * math.sin(math.radians(ang)))))], (0, 0, 20, 20))
    lb["rho"] = 10.0
    sb = A.shape(lb, 1.0, (0.0, 0.0))
    hw_, hh_ = A.TEXT_W * len(A.text(lb)) / 2, A.TEXT_H / 2
    ok(not any(abs(p[0] - sb["at"][0]) < hw_ and abs(p[1] - sb["at"][1]) < hh_ for p in sb["segs"][0]), f"{ang} degrees: the number clears the arc")
ok(len(sn["heads"]) == 2 and nearp(sn["heads"][0][0], (12, 0)) and sn["heads"][0][1][1] > 0 and sn["heads"][1][1][1] < 0, "an arrow at each end of the arc, pointing along it")

# ----------------------------------------------------------------------------------------------------------------------------------- placing with the pointer
p = A.new_dim([L1], (0, 0, 100, 10))
A.place(p, 1.0, (0, 0), (50, 25))
ok(p["side"] == 1 and near(p["dist"], 25.0) and near(p["t"], 0.0) and p["mode"] == "h", "the pointer above the line: the dimension goes above, as far as the pointer is")
A.place(p, 1.0, (0, 0), (80, -12))
ok(p["side"] == -1 and near(p["dist"], 12.0) and near(p["t"], 30.0), "below: on the other side; where the pointer is along the line decides where the number is")
pa = A.new_dim([P1, P2], (0, 0, 100, 10))
A.place(pa, 1.0, (0, 0), (50, 30))
ok(pa["mode"] == "h" and near(A.value(pa), 100.0), "two points, the pointer above them: measured horizontally")
A.place(pa, 1.0, (0, 0), (130, 5))
ok(pa["mode"] == "v" and near(A.value(pa), 10.0), "the pointer beside them: vertically")
A.place(pa, 1.0, (0, 0), (150, 80))
ok(pa["mode"] == "a" and near(A.value(pa), math.hypot(100, 10)), "away from both: along the line between them")
pp = A.new_dim([L1, L2], (0, 0, 100, 10))
A.place(pp, 1.0, (0, 0), (130, 5))
ok(near(pp["dist"], 30.0) and A.shape(pp, 1.0, (0, 0))["segs"][-1][0][0] == 130, "two parallel lines: the dimension line goes where the pointer is, 30 mm beyond their ends")
A.place(pp, 1.0, (0, 0), (40, 5))
ok(near(pp["dist"], -40.0) and nearp(A.shape(pp, 1.0, (0, 0))["segs"][-1][0], (40, 0)), "or between them")
pc = A.new_dim([C1], (0, 0, 100, 10))
A.place(pc, 2.0, (10.0, 20.0), (50.0, 40.0))
ok(near(pc["lab"][0], 50 - (10 + 2 * 30)) and near(pc["lab"][1], 40 - (20 + 2 * 5)), "a circle: the label goes where the pointer is, kept from the centre")
pn = A.new_dim([A.ref_of(line((0, 0), (30, 0))), A.ref_of(line((0, 0), (30, 30)))], (0, 0, 30, 30))
A.place(pn, 1.0, (0, 0), (-10, 3))
ok(near(A.value(pn), 135.0), f"an angle: the pointer on the other side of the corner takes the other quadrant (135°: {A.value(pn):.1f})")
A.place(pn, 1.0, (0, 0), (20, 5))
ok(near(A.value(pn), 45.0) and near(pn["rho"], math.hypot(20, 5)), "inside the first quadrant: 45°, the arc as far out as the pointer")
A.place(pn, 1.0, (0, 0), (5, -20))
ok(near(A.value(pn), 135.0), "below the first line: the supplement (135°)")

# ----------------------------------------------------------------------------------------------------------------------------------- picking an annotation back
ok(A.distance(sh, (50, 10)) < 1e-9 and A.distance(sh, (50, 60)) > 15, "the distance from a dimension: on its line, and away from it")
ok(A.distance(sh, sh["at"]) < 1e-9, "its number counts too")

# ----------------------------------------------------------------------------------------------------------------------------------- center marks and centerlines
cm = A.new_mark("center_mark", [A.ref_of(circle((30, 5), 3))], (0, 0, 100, 10))
ms = A.mark_shape(cm, 1.0, (0, 0))
ok(ms["style"] == "solid" and len(ms["segs"]) == 2, "a center mark is a cross")
ok(nearp(ms["segs"][0][0], (30 - 3 - A.MARK_OVER, 5)) and nearp(ms["segs"][0][1], (30 + 3 + A.MARK_OVER, 5)) and nearp(ms["segs"][1][0], (30, 5 - 3 - A.MARK_OVER)), "it reaches a little beyond the circle")
ms2 = A.mark_shape(cm, 2.0, (0, 0))
ok(nearp(ms2["segs"][0][1], (60 + 6 + A.MARK_OVER, 10)), "at scale 2 the circle is twice as big and the overhang is the same")
cl = A.new_mark("centerline", [A.ref_of(line((0, 0), (100, 0))), A.ref_of(line((0, 10), (100, 10)))], (0, 0, 100, 10))
cs = A.mark_shape(cl, 1.0, (0, 0))
ok(cs["style"] == "dashdot" and len(cs["segs"]) == 1, "a centerline is one dash-dot line")
ok(nearp(cs["segs"][0][0], (-A.MARK_OVER, 5)) and nearp(cs["segs"][0][1], (100 + A.MARK_OVER, 5)), "midway between the two lines, a little longer than they are")
clv = A.new_mark("centerline", [A.ref_of(line((0, 0), (0, 10))), A.ref_of(line((20, 0), (20, 10)))], (0, 0, 20, 10))
csv = A.mark_shape(clv, 1.0, (0, 0))
ok(all(abs(p[0] - 10.0) < 1e-9 for p in csv["segs"][0]) and abs(abs(csv["segs"][0][1][1] - csv["segs"][0][0][1]) - (10 + 2 * A.MARK_OVER)) < 1e-9, "a vertical pair gets a vertical centerline")
clr = A.new_mark("centerline", [A.ref_of(line((0, 10), (0, 0))), A.ref_of(line((20, 10), (20, 0)))], (0, 0, 20, 10))
csr = A.mark_shape(clr, 1.0, (0, 0))
ok(csr["segs"][0][0][1] < csr["segs"][0][1][1] and near(csr["segs"][0][0][1], -A.MARK_OVER), "lines made from the top down give the same centerline: it begins at the bottom, so the dashes begin there")

# ----------------------------------------------------------------------------------------------------------------------------------- finding the geometry again
ents0 = [line((0, 0), (100, 0)), line((100, 0), (100, 10)), line((100, 10), (0, 10)), line((0, 10), (0, 0)), circle((30, 5), 3)]
ents1 = [line((0, 0), (150, 0)), line((150, 0), (150, 10)), line((150, 10), (0, 10)), line((0, 10), (0, 0)), circle((30, 5), 3)]
top = A.new_dim([A.ref_of(ents0[2])], (0, 0, 100, 10))
corner = A.new_dim([{"k": "pt", "p": (0, 0)}, {"k": "pt", "p": (100, 0)}], (0, 0, 100, 10))
hole = A.new_dim([A.ref_of(ents0[4])], (0, 0, 100, 10))
cmk = A.new_mark("center_mark", [A.ref_of(ents0[4])], (0, 0, 100, 10))
ann = [top, corner, hole, cmk]
n_lost = A.rematch(ann, proj_of(*ents1), (0, 0, 150, 10))
ok(n_lost == 0 and not any(a["lost"] for a in ann), "a part that grew from 100 to 150: nothing is lost")
ok(near(A.value(top), 150.0) and near(A.value(corner), 150.0), "the dimensions on its edges say 150 now")
ok(near(A.value(hole), 6.0) and tuple(cmk["refs"][0]["c"]) == (30, 5), "the hole did not change: its diameter and its center mark are still there")
ok(top["bb"] == [0.0, 0.0, 150.0, 10.0], "(and they remember the new box of the view)")
ents2 = [line((0, 0), (150, 0)), line((150, 0), (150, 10)), line((150, 10), (0, 10)), line((0, 10), (0, 0))]
n_lost = A.rematch(ann, proj_of(*ents2), (0, 0, 150, 10))
ok(n_lost == 2 and hole["lost"] and cmk["lost"] and not top["lost"] and not corner["lost"], "the hole is gone: the dimension of it and its center mark are LOST, the others are fine")
ok(tuple(hole["refs"][0]["c"]) == (30, 5) and near(A.value(hole), 6.0), "a lost dimension keeps what it had (the person decides what to do with it)")
n_lost = A.rematch(ann, proj_of(*ents1), (0, 0, 150, 10))
ok(n_lost == 0 and not hole["lost"], "the hole comes back: the dimension is found again")
tall = [line((0, 0), (100, 0)), line((100, 0), (100, 40)), line((100, 40), (0, 40)), line((0, 40), (0, 0))]
v_dim = A.new_dim([A.ref_of(ents0[1])], (0, 0, 100, 10))
A.rematch([v_dim], proj_of(*tall), (0, 0, 100, 40))
ok(near(A.value(v_dim), 40.0) and not v_dim["lost"], "a part that grew higher: the dimension on its right edge says 40")
two = A.new_dim([{"k": "pt", "p": (50, 5)}, {"k": "pt", "p": (100, 0)}], (0, 0, 100, 10))
A.rematch([two], proj_of(*ents1), (0, 0, 150, 10))
ok(two["lost"], "a point that is nowhere near any point of the new lines: lost")
same = A.new_dim([{"k": "pt", "p": (0, 0)}, {"k": "pt", "p": (5, 0)}], (0, 0, 100, 10))
A.rematch([same], proj_of(*ents0), (0, 0, 100, 10))
ok(same["lost"], "two references that would land on the same point do not make a dimension: lost")

# ----------------------------------------------------------------------------------------------------------------------------------- in a drawing with a real part
bar, _sid = ex.part_doc(100, 20, 10)
long_bar, _s2 = ex.part_doc(150, 20, 10)
d = M.Drawing()
mid = d.add_model("Bar", "part", bar, src="n1")
v = d.add_view(mid, "Front", (100, 100), scale=1.0)
pr = d.projection(v)
bb = pr.bbox()
ok(near(bb[2] - bb[0], 100.0) and near(bb[3] - bb[1], 10.0), "(the Front view of the bar: 100 x 10)")
top_ref = A.pick(pr, ((bb[0] + bb[2]) / 2.0, bb[3]), 1.0)
ok(top_ref and top_ref["k"] == "line", f"the top edge of the bar is picked ({top_ref})")
dm = d.add_dim(v["id"], [top_ref])
ok(dm["id"] == "d1" and dm["view"] == v["id"] and dm["type"] == "linear" and d.counter["dim"] == 1 and d.dims == [dm], "a dimension is added to the view, with an id")
ok(near(A.value(dm), 100.0), "of 100")
d.place_annot("d1", (150, 130))
ok(dm["side"] == 1 and dm["dist"] > 0, "placed from the pointer")
v["scale"] = 2.0
ok(near(A.value(dm), 100.0), "the view at 2:1 - the dimension still says 100")
d.set_scale(v["id"], 0.5)
ok(near(A.value(dm), 100.0), "at 1:2 - 100")
d.set_scale(v["id"], 1.0)
ids = d.refresh_model(mid, long_bar)
ok(ids == [v["id"]] and near(A.value(d.dims[0]), 150.0) and not d.dims[0]["lost"], "the model changed to 150 long: the dimension follows it and says 150")
ok(d.lost_annots() == [], "nothing lost")
tr = d.projection(v)
horiz = [A.ref_of(e) for e in tr.vis if e["t"] == "line" and abs(e["a"][1] - e["b"][1]) < 1e-9]
mk = d.add_mark(v["id"], horiz[:2])
ok(mk["type"] == "centerline" and mk["id"] == "k1" and d.marks == [mk], "a centerline between the top and bottom edges")
try:
    d.add_mark(v["id"], [horiz[0]])
    ok(False, "one line is not a mark")
except M.DrawingError as e:
    ok("center" in str(e).lower(), f"one line is no mark ({e})")
try:
    d.add_dim(v["id"], [{"k": "pt", "p": (0, 0)}])
    ok(False, "one point is not a dimension")
except M.DrawingError as e:
    ok("dimension" in str(e), f"one point is no dimension ({e})")
shp = d.dim_shape(d.dims[0])
ok(len(shp["segs"]) == 3 and d.dim_shape(mk)["style"] == "dashdot", "the lines of a dimension and a mark on the sheet")
ok(len(d.annots(v["id"])) == 2 and len(d.annots("none")) == 0 and len(d.annots()) == 2, "the dimensions and marks of a view")

# the file
text_ = d.to_json()
e = M.Drawing.from_json(text_)
ok(len(e.dims) == 1 and len(e.marks) == 1 and e.counter["dim"] == 1 and e.counter["mark"] == 1, "they are in the file")
ok(near(A.value(e.dims[0]), 150.0) and e.dim_shape(e.dims[0])["kinds"] == d.dim_shape(d.dims[0])["kinds"], "and work again after opening (lists instead of tuples)")
ok(all(np.allclose(a, c) for a, c in zip(e.dim_shape(e.dims[0])["segs"], d.dim_shape(d.dims[0])["segs"])), "drawn the same")
e.refresh_model(e.models[0]["id"], bar)
ok(near(A.value(e.dims[0]), 100.0), "and still follow the model after opening")

# undo
snap = d.snapshot()
d.remove_annot("d1")
ok(d.dims == [] and len(d.marks) == 1, "a dimension can be removed")
d.restore(snap)
ok(len(d.dims) == 1 and d.dims[0]["id"] == "d1" and near(A.value(d.dims[0]), 150.0), "undo brings it back")
try:
    d.remove_annot("d99")
    ok(False, "unknown id")
except M.DrawingError:
    ok(True, "a dimension that is not there is refused")

# a model that cannot be built: the dimensions stay as they were
before = json.dumps(d.dims, default=list, sort_keys=True)
try:
    d.refresh_model(d.models[0]["id"], {"nonsense": True})
    ok(False, "bad data")
except Exception:
    ok(json.dumps(d.dims, default=list, sort_keys=True) == before, "a model that cannot be built is refused and the dimensions are as they were")

# a view that looks another way: its dimensions have nothing to hold on to
d.set_orient(v["id"], "Top")
ok(d.dims == [] and d.marks == [], "the view now looks from the top: its dimensions and center marks are gone")
d.restore(snap)
v = d.view("v1")
# projected views: the dimensions are of the view
pv = d.add_projected(v["id"], "up", (100, 150))
pr2 = d.projection(pv)
ref2 = A.pick(pr2, (pr2.bbox()[0] + 0.1, pr2.bbox()[1] + 0.1), 1.0)
dm2 = d.add_dim(pv["id"], [ref2, A.pick(pr2, (pr2.bbox()[2] - 0.1, pr2.bbox()[1] + 0.1), 1.0)])
ok(dm2["view"] == pv["id"] and near(A.value(dm2), 150.0), "a dimension on a projected view (the Top view of the bar, 150 long by now): 150")
d.set_sheet(first_angle=True)
ok(all(a["view"] != pv["id"] for a in d.dims), "first angle: the projected view looks from the other side - its dimensions are gone; the parent's stay")
ok(any(a["view"] == "v1" for a in d.dims), "(the parent's are still there)")
d.set_sheet(first_angle=False)
d.remove_view("v1")
ok(d.dims == [] and d.marks == [], "removing a view removes what is dimensioned on it")

# every dimension of an assembly view is on the lines the view shows
fr = ex.frame_asm(100, 20, 20)
d2 = M.Drawing()
am = d2.add_model("Frame", "assembly", fr, src="a")
av = d2.add_view(am, "Front", (100, 100))
apr = d2.projection(av)
lines_ = [A.ref_of(e) for e in apr.vis if e["t"] == "line"]
ok(len(lines_) > 3, f"(an assembly view has lines: {len(lines_)})")
dd_ = d2.add_dim(av["id"], [lines_[0]])
ok(near(A.value(dd_), math.hypot(lines_[0]["b"][0] - lines_[0]["a"][0], lines_[0]["b"][1] - lines_[0]["a"][1])), "a dimension of an assembly view takes the length of the line")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
