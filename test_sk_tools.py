import math
import numpy as np
import sk_tools as T

def fresh(): return T.new_model()
def check(name, m, expect_dof=None, regions=None):
    rep = T.solve_model(m)
    ok = rep.ok and not rep.conflicts
    nreg = len(T.regions(m))
    print(f"{name:28s} ok={ok} dof={rep.dof} conflicts={rep.conflicts} regions={nreg}")
    assert ok, (name, rep.messages)
    if expect_dof is not None: assert rep.dof == expect_dof, (name, rep.dof, expect_dof)
    if regions is not None: assert nreg == regions, (name, nreg)
    return rep

m = fresh(); T.add_rect_corner(m, (0, 0), (40, 20)); check("rect corner", m, 4 + 0, 1)   # 4 dof with origin free? (x,y,w,h)
m = fresh(); T.add_rect_center(m, (0, 0), (20, 10)); check("rect center", m, None, 1)
m = fresh(); T.add_rect_3pt(m, (0, 0), (30, 10), (25, 30)); check("rect 3pt", m, 5, 1)
m = fresh(); T.add_rect_3pt_center(m, (0, 0), (20, 5), (10, 15)); check("rect 3pt centre", m, None, 1)
m = fresh(); T.add_parallelogram(m, (0, 0), (30, 0), (40, 15)); check("parallelogram", m, 6, 1)
m = fresh(); T.add_circle(m, (0, 0), (10, 0)); check("circle", m, 3, 1)
m = fresh(); T.add_circle_3pt(m, (0, 10), (10, 0), (0, -10)); r = check("perimeter circle", m, None, 1)
m = fresh(); T.add_arc_center(m, (0, 0), (10, 0), (0, 10)); check("arc centre", m)
a = T.add_arc_center(m, (0, 0), (10, 0), (0, 10), clockwise=True)
m = fresh(); T.add_arc_3pt(m, (10, 0), (-10, 0), (0, 10)); check("arc 3pt", m)
# the 3-point arc passes through the third point: it is the upper half
(c, r, t0, sw) = T.arc_span(m, list(m.ars)[0]); print("   arc sweep deg", round(math.degrees(sw), 1)); assert abs(math.degrees(sw) - 180) < 1e-6
# tangent arc
m = fresh(); l = T.add_line(m, (0, 0), (20, 0)); T.add_arc_tangent(m, m.lns[l][1], ("ln", l), (30, 10)); check("tangent arc", m)
m = fresh(); T.add_slot_straight(m, (0, 0), (30, 0), (10, 5)); r = check("slot straight", m, None, 1); print("   slot dof", r.dof)
m = fresh(); T.add_slot_center(m, (0, 0), (15, 0), (5, 4)); check("slot centre", m, None, 1)
m = fresh(); T.add_slot_arc_center(m, (0, 0), (30, 0), (0, 30), (35, 0)); check("slot arc centre", m, None, 1)
m = fresh(); T.add_slot_arc_3pt(m, (30, 0), (0, 30), (21.2, 21.2), (36, 0)); check("slot arc 3pt", m, None, 1)
m = fresh(); T.add_polygon(m, (0, 0), (10, 0), 6); check("polygon", m, 4, 1)
# fillet
m = fresh(); T.add_rect_corner(m, (0, 0), (40, 20)); T.solve_model(m)
corner = [p for p, xy in m.pts.items() if xy == [40.0, 20.0] or (abs(xy[0]-40) < 1e-6 and abs(xy[1]-20) < 1e-6)][0]
res = T.fillet_corner(m, corner, 5); print("fillet ->", res); assert isinstance(res, int)
check("rect with filleted corner", m, None, 1)
# trim: a cross of two lines, trim one arm
m = fresh(); T.add_line(m, (-10, 0), (10, 0)); T.add_line(m, (0, -10), (0, 10)); T.solve_model(m)
l_h = [i for i, (a, b) in m.lns.items() if m.pts[a][1] == m.pts[b][1]][0]
n0 = len(m.lns); msg = T.trim(m, ("ln", [i for i, (a, b) in m.lns.items() if m.pts[a][0] == m.pts[b][0]][0]), (0, 7)); print("trim:", msg, "lines", n0, "->", len(m.lns)); check("trim", m)
# trim middle piece of a line between two crossing lines -> 2 lines + 2 verticals
m = fresh(); T.add_line(m, (-20, 0), (20, 0)); T.add_line(m, (-5, -8), (-5, 8)); T.add_line(m, (5, -8), (5, 8)); T.solve_model(m)
hor = [i for i, (a, b) in m.lns.items() if m.pts[a][1] == m.pts[b][1] and abs(m.pts[a][0] - m.pts[b][0]) > 30][0]
T.trim(m, ("ln", hor), (0, 0)); T.solve_model(m); print("trim middle: lines", len(m.lns)); assert len(m.lns) == 4
# circle trim by two lines -> an arc
m = fresh(); T.add_circle(m, (0, 0), (10, 0)); T.add_line(m, (-15, 4), (15, 4)); T.add_line(m, (-15, -4), (15, -4)); T.solve_model(m)
T.trim(m, ("ci", list(m.cis)[0]), (10, 0)); print("circle trimmed -> arcs", len(m.ars), "circles", len(m.cis)); assert len(m.ars) == 1 and not m.cis
# mirror
m = fresh(); T.add_line(m, (0, 0), (10, 0)); T.add_line(m, (10, 0), (10, 5)); axis = T.add_line(m, (20, -10), (20, 10), construction=True, auto=True); T.solve_model(m)
new = T.mirror(m, [("ln", i) for i in list(m.lns) if i != axis], axis); rep = check("mirror", m)
mp = [k for k in new if k[0] == "pt"]; print("   mirrored pts", [m.pts[p] for _, p in mp][:3])
# drag the original: copy follows
for p in list(m.pts):
    if m.pts[p] == [10.0, 5.0]: m.pts[p] = [12.0, 7.0]
T.solve_model(m)
# patterns
m = fresh(); T.add_circle(m, (0, 0), (3, 0)); T.solve_model(m)
T.linear_pattern(m, [("ci", list(m.cis)[0])], 3, 10, 0); T.solve_model(m); assert len(m.cis) == 4
T.circular_pattern(m, [("ci", list(m.cis)[0])], 3, 90, 0, 0); assert len(m.cis) == 7
print("regions with holes:")
m = fresh(); T.add_rect_corner(m, (-20, -10), (20, 10)); T.add_circle(m, (0, 0), (5, 0)); T.add_circle(m, (10, 0), (12, 0)); T.add_rect_corner(m, (-3, -3), (3, 3)); T.solve_model(m)
rg = T.regions(m); print("   regions", len(rg), [len(r["holes"]) for r in rg])
print("OK")
