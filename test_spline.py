"""Splines in the sketcher: a smooth curve through fit points (centripetal Catmull-Rom), saved and loaded, deleted with its points, closed regions
made of splines (also a closed spline alone), extruded to a solid, the icon, the ribbon button and the draw tool."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc, sk_tools as sk, pm_model as pm, icons

# the curve itself
P = [(0, 0), (10, 8), (20, -4), (35, 6)]
C = sc.spline_curve(P, 12)
assert len(C) == 3 * 12 + 1 and np.allclose(C[0], P[0]) and np.allclose(C[-1], P[-1])
for q in P:
    assert np.min(np.hypot(*(C - np.array(q)).T)) < 1e-9, "the curve passes through every fit point"
assert np.abs(C[:, 1]).max() < 14, "no wild overshoot between the points"
assert np.allclose(sc.spline_curve([(0, 0), (4, 2)], 4)[2], (2, 1))
Cc = sc.spline_curve([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)], 10)
assert np.allclose(Cc[0], Cc[-1]) and abs(float(Cc[:, 0].mean()) - 5) < 1.0

# in a model: points, a spline, saved and loaded, deleted with its points
m = sc.Model()
ids = [m.add_point(*q) for q in P]
sid = m.add_spline(ids)
assert ("sp", sid) in sk.all_keys(m) and sk.polyline(m, ("sp", sid), 48).shape[1] == 2
m2 = sc.Model(); m2.from_json(m.to_json())
assert m2.sps == m.sps and len(sk.polyline(m2, ("sp", sid), 48)) == len(sk.polyline(m, ("sp", sid), 48))
old = sc.Model(); old.from_json(sc.Model().to_json().replace('"sps": {}, ', ""))        # a file from before splines has no 'sps'
assert old.sps == {}
m3 = sc.Model(); m3.from_json(m.to_json()); n_before = len(m3.pts)
m3.delete([("pt", ids[1])])
assert not m3.sps and ids[1] not in m3.pts, "a spline goes with any of its points"
m4 = sc.Model(); m4.from_json(m.to_json()); m4.delete([("sp", sid)], orphans=True)
assert not m4.sps and len([p for p in m4.pts if p in ids]) == 0, "its own fit points go with it when nothing else uses them"
assert sk.add_spline(sc.Model(), [(0, 0), (1, 1), (2, 0)]) is not None
try:
    sk.add_spline(sc.Model(), [(0, 0)]); raise SystemExit("one point accepted")
except ValueError:
    pass

# a region bounded by a spline and a line
r = sc.Model()
a, b = r.add_point(0, 0), r.add_point(40, 0)
mid = r.add_point(20, 15)
r.add_line(a, b)
r.add_spline([a, mid, b])
regs = sk.regions(r)
assert len(regs) == 1 and {k for k, _, *_ in regs[0]["outer"]} == {"ln", "sp"}
# a closed spline alone is a region
cl = sc.Model()
q = [cl.add_point(*p) for p in ((0, 0), (20, 0), (20, 20), (0, 20))]
cl.add_spline(q + [q[0]])
rg = sk.regions(cl); assert len(rg) == 1 and rg[0]["outer"][0][0] == "sp"
# the construction flag leaves a spline out
r.constr.add(("sp", next(iter(r.sps)))); assert sk.regions(r) == []

# extruded to a solid: the area of a spline-and-line shape against its sampled outline
d = pm.Document(); d.params = {"T": "5"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild()
mm = d.models[s["id"]]
a, b, c = mm.add_point(0, 0), mm.add_point(40, 0), mm.add_point(20, 15)
mm.add_line(a, b); mm.add_spline([a, c, b])
d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
assert d.solid is not None, "the spline profile extrudes"
poly = np.vstack([sk.polyline(mm, ("sp", next(iter(mm.sps))), 96), [[0, 0]]])
area = 0.5 * abs(np.sum(poly[:, 0] * np.roll(poly[:, 1], -1) - np.roll(poly[:, 0], -1) * poly[:, 1]))
assert abs(d.solid.volume - area * 5) / (area * 5) < 0.02, (d.solid.volume, area * 5)
# a closed spline alone extrudes too
d2 = pm.Document(); d2.params = {"T": "5"}
s2 = d2.add(pm.new_feature("sketch", plane={"base": "Top"})); d2.rebuild()
m5 = d2.models[s2["id"]]
q = [m5.add_point(*p) for p in ((0, 0), (20, 0), (20, 20), (0, 20))]
m5.add_spline(q + [q[0]])
d2.store_sketch(s2["id"])
d2.add(pm.new_feature("extrude", sketch=s2["id"], depth="T")); d2.rebuild()
assert d2.solid is not None and d2.solid.volume > 1000, "a closed spline extrudes"

# the icon, the ribbon button, and the draw tool
assert icons.icon("spline") is not None and not icons.icon("spline").isNull()
import sketch_edit
assert "spline" in sketch_edit.ALL_TOOLS
src = open(os.path.join(HERE, "pm_app.py"), encoding="utf-8").read()
assert 'T("spline")' in src
# the draw tool, through the sketch editor and its mouse handlers
import pm_app
w = pm_app.MainWindow(); ed = w.ed
ed.size_fn = lambda: (1000.0, 700.0)
w.doc = pm.Document(); w.sel = None; w.update_all(fit=True)
w.sel_plane = "Front"; w.command("sketch")
def px(u, v): return tuple(ed.to_screen(ed.to_world((u, v)))[0])
def click(u, v): ed.press(*px(u, v)); ed.release(*px(u, v))
assert w.act.get("tool_spline") is not None, "a Spline button in the ribbon"
w.set_tool("spline"); assert ed.tool == "spline"
click(-40, 0); click(-15, 20); click(10, -15)
assert len(ed.pending) == 3 and not ed.m.sps, "points are collected until the spline is finished"
click(40, 10); ed.double_click(*px(40, 10))
assert len(ed.m.sps) == 1 and ed.pending == []
sp = next(iter(ed.m.sps.values())); assert len(sp["pts"]) == 4, sp
# a closed one: click the first point again
click(-40, -60); click(0, -60); click(0, -100); click(-40, -100); click(-40, -60)
assert len(ed.m.sps) == 2
cl = [v for v in ed.m.sps.values() if len(v["pts"]) == 5]
assert cl and cl[0]["pts"][0] == cl[0]["pts"][-1], "clicking the first point closes the spline"
# select it by clicking on the curve
ed.reset_tool("select"); ed.sel = []
mid = sk.polyline(ed.m, ("sp", next(iter(ed.m.sps))), 48); q = mid[len(mid) // 2]
click(float(q[0]), float(q[1])); assert any(k[0] == "sp" for k in ed.sel), ed.sel
# .skt text file round trip
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path.insert(0, SIM)
import sketcher_script as scr
txt = scr.to_script(mm)
if txt is not None:
    back = sc.Model(); scr.from_script(back, txt)
    assert back is not None and back.sps == mm.sps and "SPLINE" in txt

# 2D FEA on a part with a spline edge: a bar with a curved top, fixed on the left, pressed from above
import physics_tab, physics_fea as pf
class Win:
    doc = None
    def sketch_list(self): return []
    def status(self, t): pass
fm = sc.Model()
p0, p1, p2, p3 = fm.add_point(0, 0), fm.add_point(100, 0), fm.add_point(100, 20), fm.add_point(0, 20)
mid = fm.add_point(50, 30)
l_bot, l_r, l_l = fm.add_line(p0, p1), fm.add_line(p1, p2), fm.add_line(p3, p0)
sid = fm.add_spline([p2, mid, p3])
t = physics_tab.PhysicsTab(Win()); t.set_model(fm, "curved"); t.resize(900, 600); t.show(); app.processEvents()
assert t.geom is not None and any(e["kind"] == "sp" for e in t.geom["edges"]), "the spline is an edge of the 2D FEA geometry"
assert len(t.geom["faces"]) == 1, "the spline closes the outline"
t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
t.supports = [{"mode": "fixed", "targets": [("ln", l_l)]}]
t.loads = [{"kind": "pressure", "p": 0.5, "targets": [("sp", sid)]}]
t.e_h.setText("5"); t.run_mesh()
assert t.mesh is not None and len(t.mesh["tris"]) > 50
N, Tr = t.mesh["nodes"], t.mesh["tris"][:, :3]
d1, d2 = N[Tr[:, 1]] - N[Tr[:, 0]], N[Tr[:, 2]] - N[Tr[:, 0]]
A = float(0.5 * np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]).sum())
edge_poly = np.vstack([[[0, 0], [100, 0], [100, 20]], sk.polyline(fm, ("sp", sid), 96)[:], [[0, 0]]])
area = 0.5 * abs(np.sum(edge_poly[:, 0] * np.roll(edge_poly[:, 1], -1) - np.roll(edge_poly[:, 0], -1) * edge_poly[:, 1]))
assert abs(A - area) / area < 0.03, (A, area)
t.show_solution(pf.solve(t.mesh, t.read_material(), t.supports, t.loads, lambda *a, **k: None, lambda: False))
assert t.result is not None and float(np.max(np.hypot(t.result["u"][:, 0], t.result["u"][:, 1]))) > 0, "the spline edge carries the pressure load"
print("OK spline")
