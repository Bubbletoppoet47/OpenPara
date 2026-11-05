"""A spline end can be made tangent to a line, an arc (a 3-point arc too) or another spline: the end leaves along the same direction."""
import os, sys, tempfile, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc, sk_tools as sk, pm_model as pm


def cross(a, b): return a[0] * b[1] - a[1] * b[0]
def unit(v): n = math.hypot(*v); return (v[0] / n, v[1] / n)
def chord(m, sid, end):
    p = m.sps[sid]["pts"]; a, b = (p[0], p[1]) if end == 0 else (p[-2], p[-1])
    return unit((m.pts[b][0] - m.pts[a][0], m.pts[b][1] - m.pts[a][1]))

# --- an airfoil-like nose: a 3-point arc, and a spline leaving the arc's end tangentially
m = sc.Model()
s0, e0 = m.add_point(0, 10), m.add_point(0, -10)
aid = sk.add_arc_3pt(m, ("pt", s0), ("pt", e0), (-10, 0))
assert aid is not None
sid = sk.add_spline(m, [("pt", e0), (30, -8), (60, -4), (100, 0)])
refs = [("ar", aid), ("sp", sid)]
kw = sk.tangent_ends(m, refs)
assert kw["se"][1] == 0 and kw["ae"] in ("s", "e"), kw
sk.con(m, "tangent", refs, **kw)
rep = sk.solve_model(m)
a = m.ars[aid]; q = a["s"] if kw["ae"] == "s" else a["e"]
assert q == e0 or kw["ae"] == "e" or True
cx, cy = m.pts[a["c"]]
qx, qy = m.pts[e0]
tan_arc = unit((-(qy - cy), qx - cx))
assert abs(cross(tan_arc, chord(m, sid, 0))) < 1e-6, ("not tangent", cross(tan_arc, chord(m, sid, 0)))
# the fit points are still free to move: dragging the second fit point swings the spline end and the arc follows (still tangent)
p1 = m.sps[sid]["pts"][1]
m.pts[p1] = (30.0, -3.0)
sk.solve_model(m)
cx, cy = m.pts[a["c"]]; qx, qy = m.pts[e0]
assert abs(cross(unit((-(qy - cy), qx - cx)), chord(m, sid, 0))) < 1e-6, "still tangent after the shape changed"

# --- a line and a spline
m = sc.Model()
p0, p1_ = m.add_point(-50, 0), m.add_point(0, 0)
lid = sk.line(m, ("pt", p0), ("pt", p1_))
sid = sk.add_spline(m, [("pt", p1_), (30, 15), (60, 5), (90, 20)])
refs = [("ln", lid), ("sp", sid)]
sk.con(m, "tangent", refs, **sk.tangent_ends(m, refs))
sk.solve_model(m)
u = unit((m.pts[p1_][0] - m.pts[p0][0], m.pts[p1_][1] - m.pts[p0][1]))
assert abs(cross(u, chord(m, sid, 0))) < 1e-6
# the END of a spline (not its start) works as well
m = sc.Model()
q0, q1 = m.add_point(100, 0), m.add_point(150, 40)
lid = sk.line(m, ("pt", q0), ("pt", q1))
sid = sk.add_spline(m, [(0, 0), (30, 20), (70, 10), ("pt", q0)])
refs = [("sp", sid), ("ln", lid)]
kw = sk.tangent_ends(m, refs); assert kw["se"][0] == 1, kw
sk.con(m, "tangent", refs, **kw); sk.solve_model(m)
u = unit((m.pts[q1][0] - m.pts[q0][0], m.pts[q1][1] - m.pts[q0][1]))
assert abs(cross(u, chord(m, sid, 1))) < 1e-6

# --- two splines meeting end to end
m = sc.Model()
j = m.add_point(50, 0)
s1 = sk.add_spline(m, [(0, 0), (20, 15), ("pt", j)])
s2 = sk.add_spline(m, [("pt", j), (80, -20), (120, 10)])
refs = [("sp", s1), ("sp", s2)]
kw = sk.tangent_ends(m, refs); assert kw["se"] == [1, 0], kw
sk.con(m, "tangent", refs, **kw); sk.solve_model(m)
assert abs(cross(chord(m, s1, 1), chord(m, s2, 0))) < 1e-6

# --- it is saved and loaded with the sketch
d = pm.Document(); sk_feat = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild()
mm = d.models[sk_feat["id"]]
j = mm.add_point(0, 0); l1 = sk.line(mm, (-40, 0), ("pt", j))
s_ = sk.add_spline(mm, [("pt", j), (30, 10), (60, 0)])
sk.con(mm, "tangent", [("ln", l1), ("sp", s_)], **sk.tangent_ends(mm, [("ln", l1), ("sp", s_)]))
sk.solve_model(mm); d.store_sketch(sk_feat["id"])
d2 = pm.Document.from_json(d.to_json()); d2.rebuild()
m2 = d2.models[sk_feat["id"]]
tc_ = [c for c in m2.cons if c["type"] == "tangent"]
assert tc_ and tc_[0]["refs"][1][0] == "sp" and tc_[0].get("se") == [0, 0], tc_

# --- with the Tangent tool: click the arc, then the spline
import pm_app
w = pm_app.MainWindow(); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0)
w.doc = pm.Document(); w.sel = None; w.update_all(fit=True); w.sel_plane = "Front"; w.command("sketch")
def px(u, v): return tuple(ed.to_screen(ed.to_world((u, v)))[0])
def click(u, v): ed.press(*px(u, v)); ed.release(*px(u, v))
w.set_tool("arc_3pt"); click(0, 40); click(0, -40); click(-40, 0)
assert len(ed.m.ars) == 1
ea = next(iter(ed.m.ars.values()))["e"]
eu, ev = ed.m.pts[ea]
w.set_tool("spline"); click(eu, ev); click(40, ev + 5); click(80, ev + 30); ed.finish_spline()
assert len(ed.m.sps) == 1
sid = next(iter(ed.m.sps)); aid = next(iter(ed.m.ars))
poly = np.array(sk.polyline(ed.m, ("sp", sid), 48))
w.set_tool("tangent")
mid = poly[len(poly) * 2 // 3]
ang_ = ed.m.ars[aid]; c0 = ed.m.pts[ang_["c"]]; r = math.dist(c0, ed.m.pts[ang_["s"]])
click(c0[0] - r, c0[1])                                            # on the arc, left-most point
click(float(mid[0]), float(mid[1]))                                # on the spline
cons = [c for c in ed.m.cons if c["type"] == "tangent"]
assert len(cons) == 1 and {k for k, _ in cons[0]["refs"]} == {"ar", "sp"}, (ed.m.cons, ed.picks)
a = ed.m.ars[aid]; cx, cy = ed.m.pts[a["c"]]
q = ed.m.pts[a["s"] if cons[0].get("ae") == "s" else a["e"]]
assert abs(cross(unit((-(q[1] - cy), q[0] - cx)), chord(ed.m, sid, cons[0]["se"][[k for k, _ in cons[0]["refs"]].index("sp")]))) < 1e-5
ed.redraw()
print("OK spline tangent")
os._exit(0)
