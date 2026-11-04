"""2D FEA Split edge / Merge edges (Simulation add-on): the geometry (physics_split), the tab (supports, loads, regions follow the halves, the .gps state
round-trips) and a real solve with a load that covers only part of an edge."""
import os, sys, math, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc
import physics_split as ps, physics_geom as pg, physics_tab, physics_fea as pf


def rect(w=100, h=20):
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (w, 0), (w, h), (0, h))]
    ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
    return m, p, ls


# ---------------- geometry
assert ps.eval_length("100/3 + 2") == 100 / 3 + 2 and ps.eval_length("1,5") == 1.5
for bad in ("__import__('os')", "1+", "abc", "2**9999999999"):
    try:
        ps.eval_length(bad); raise SystemExit("accepted " + bad)
    except ValueError:
        pass
m, p, ls = rect()
area0 = pg.analyze(m)["faces"][0]["net_area"]
r = ps.split_edge(m, ("ln", ls[0]), 30)
assert r["first"] == ("ln", ls[0]) and r["second"][0] == "ln" and abs(r["frac"] - .3) < 1e-12
assert m.pts[r["pt"]] == [30.0, 0.0] and m.lns[ls[0]] == [p[0], r["pt"]] and m.lns[r["second"][1]] == [r["pt"], p[1]]
g = pg.analyze(m)
assert len(g["edges"]) == 5 and len(g["faces"]) == 1 and abs(g["faces"][0]["net_area"] - area0) < 1e-9
for bad in (0, 100, -1, 150):
    try:
        ps.split_edge(m, ("ln", ls[1]), bad); raise SystemExit("split at " + str(bad))
    except ps.SplitError:
        pass
assert ps.can_merge(m, r["pt"])[0] and not ps.can_merge(m, p[0])[0] and not ps.can_merge(m, p[2])[0]
ps.merge_at(m, r["pt"])
assert len(pg.analyze(m)["edges"]) == 4 and r["pt"] not in m.pts and m.lns[ls[0]] == [p[0], p[1]]
# arcs and circles
m = sc.Model(); c = m.add_point(0, 0); s = m.add_point(10, 0); e = m.add_point(0, 10); a = m.add_arc(c, s, e)
assert abs(ps.edge_length(m, ("ar", a)) - 5 * math.pi) < 1e-9 and abs(ps.nearest_dist(m, ("ar", a), 7, 7) - 5 * math.pi / 2) < 1e-9
r = ps.split_edge(m, ("ar", a), 5 * math.pi / 2)
x, y = m.pts[r["pt"]]
assert abs(x - math.sqrt(50)) < 1e-9 and abs(y - math.sqrt(50)) < 1e-9 and ps.can_merge(m, r["pt"])[0]
ps.merge_at(m, r["pt"]); assert len(m.ars) == 1
m = sc.Model(); c = m.add_point(0, 0); ci = m.add_circle(c, 5)
try:
    ps.split_circle(m, ci, 1.0, 1.0); raise SystemExit("same point twice")
except ps.SplitError:
    pass
res = ps.split_circle(m, ci, 0, math.pi)
g = pg.analyze(m)
assert len(m.cis) == 0 and len(g["edges"]) == 2 and len(g["faces"]) == 1 and abs(g["faces"][0]["net_area"] - math.pi * 25) < 0.5

# ---------------- the tab
class Win:
    doc = None
    def sketch_list(self): return []
    def status(self, t): pass


def new_tab(m):
    t = physics_tab.PhysicsTab(Win())
    t.set_model(m, "rect")
    t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
    return t


m, p, ls = rect()
t = new_tab(m)
assert t.b_split.text() == "Split edge" and t.b_merge.text() == "Merge edges"
top = ("ln", ls[2])
t.supports = [{"mode": "fixed", "targets": [("ln", ls[3])]}, {"mode": "y", "targets": [top, ("ln", ls[0])]}]
t.loads = [{"kind": "pressure", "p": 5.0, "targets": [top]}, {"kind": "force", "fx": 0, "fy": -10, "targets": [("pt", p[2])]}]
t.geom["faces"][0]["included"] = True
t.region_names = {0: "Slab"}
info = t.apply_split(top, 25)                       # 25 from the start of the top edge (100,20) -> (0,20): x = 75
assert abs(t.model.pts[info["pt"]][0] - 75) < 1e-9
assert t.supports[1]["targets"] == [top, info["second"], ("ln", ls[0])], t.supports[1]["targets"]
assert t.loads[0]["targets"] == [top, info["second"]] and t.loads[1]["targets"] == [("pt", p[2])]
assert t.supports[0]["targets"] == [("ln", ls[3])]
assert len(t.geom["edges"]) == 5 and t.mesh is None and t.region_names == {0: "Slab"} and t.geom["faces"][0]["included"]
assert t.canvas.sel == [("pt", info["pt"])]
# merge refused when only one half carries something
t.loads[0]["targets"] = [top]
t.canvas.sel = [("pt", info["pt"])]
assert t.merge_at(info["pt"]) is None and len(t.geom["edges"]) == 5
t.loads[0]["targets"] = [top, info["second"]]
back = t.merge_at(info["pt"])
assert back is not None and len(t.geom["edges"]) == 4 and t.loads[0]["targets"] == [top] and t.supports[1]["targets"] == [top, ("ln", ls[0])]
# a support on the point itself blocks the merge
info = t.apply_split(top, 40)
t.supports.append({"mode": "fixed", "targets": [("pt", info["pt"])]})
assert t.merge_at(info["pt"]) is None
t.supports.pop()
# not parallel (a corner) cannot be merged
assert t.merge_at(p[1]) is None
# save / restore (.gps state)
st = t.export_state()
t2 = physics_tab.PhysicsTab(Win()); t2.import_state(st)
assert len(t2.geom["edges"]) == 5 and t2.loads[0]["targets"] == t.loads[0]["targets"] and info["pt"] in t2.model.pts

# ---------------- the click: split mode, the box, circle needs two clicks
from PyQt6.QtCore import QPointF
m, p, ls = rect()
t = new_tab(m); t.resize(1000, 700); t.show(); app.processEvents(); t.canvas.fit()
t.set_tool("split"); assert t.canvas.mode == "split" and t.b_split.isChecked()
asked = []
t.ask_split_length = lambda src, L, d: (asked.append((src, round(L, 6), round(d, 6))) or 25.0)
sp = t.canvas.w2s(60, 0)                                        # a click on the bottom edge at x = 60
t.split_click(sp)
assert asked == [(("ln", ls[0]), 100.0, 60.0)], asked
assert len(t.geom["edges"]) == 5 and abs(t.model.pts[max(t.model.pts)][0] - 25.0) < 1e-9
t.split_click(QPointF(3, 3))                                    # empty space: nothing happens
assert len(t.geom["edges"]) == 5
t.set_tool("select"); assert t.canvas.mode == "select" and not t.b_split.isChecked()
m = sc.Model(); c = m.add_point(0, 0); ci = m.add_circle(c, 5)
t = new_tab(m); t.resize(1000, 700); t.show(); app.processEvents(); t.canvas.fit(); t.set_tool("split")
t.split_click(t.canvas.w2s(5, 0))
assert t.canvas.split_mark is not None and len(t.geom["edges"]) == 1
t.split_click(t.canvas.w2s(-5, 0))
assert len(t.geom["edges"]) == 2 and t.canvas.split_mark is None

# ---------------- a circle
m = sc.Model(); c = m.add_point(0, 0); ci = m.add_circle(c, 5)
t = new_tab(m)
t.supports = [{"mode": "fixed", "targets": [("ci", ci)]}]
info = t.apply_split_circle(("ci", ci), 0, math.pi)
assert t.supports[0]["targets"] == info["arcs"] and len(t.geom["edges"]) == 2 and len(t.geom["faces"]) == 1
t.supports = []; t.loads = [{"kind": "cfd", "include_shear": False, "pairs": [{"target": ("ar", info["arcs"][0][1]), "source": ("ci", 1)}], "live": True,
                              "targets": [info["arcs"][0]], "converged": True}]
m2 = sc.Model(); c2 = m2.add_point(0, 0); ci2 = m2.add_circle(c2, 5); t3 = new_tab(m2)
t3.loads = [{"kind": "cfd", "include_shear": False, "pairs": [{"target": ("ci", ci2), "source": ("ci", 1)}], "live": True, "targets": [("ci", ci2)], "converged": True}]
try:
    t3.apply_split_circle(("ci", ci2), 0, 1.0); raise SystemExit("circle with a CFD link was split")
except ps.SplitError:
    pass

# ---------------- CFD link on a split line: the pieces take their share of the CFD edge
m, p, ls = rect()
t = new_tab(m)
t.loads = [{"kind": "cfd", "include_shear": False, "live": True, "converged": True,
            "pairs": [{"target": ("ln", ls[0]), "source": ("ln", 7)}], "targets": [("ln", ls[0])]}]
info = t.apply_split(("ln", ls[0]), 25)
pr = t.loads[0]["pairs"]
assert [tuple(x["target"]) for x in pr] == [("ln", ls[0]), info["second"]] and pr[0]["span"] == [0.0, 0.25] and pr[1]["span"] == [0.25, 1.0]
assert all(tuple(x["source"]) == ("ln", 7) for x in pr)
info2 = t.apply_split(info["second"], 37.5)                   # a piece split again: spans compose (the piece 25..100 of the line, cut at 62.5)
sp = [x["span"] for x in t.loads[0]["pairs"]]
assert sp[0] == [0.0, 0.25] and abs(sp[1][0] - .25) < 1e-12 and abs(sp[1][1] - .625) < 1e-12 and abs(sp[2][0] - .625) < 1e-12 and sp[2][1] == 1.0, sp
assert t.merge_at(info2["pt"]) is not None
assert t.loads[0]["pairs"][1]["span"] == [0.25, 1.0]
assert t.merge_at(info["pt"]) is not None and "span" not in t.loads[0]["pairs"][0] or t.loads[0]["pairs"][0].get("span") is None

# ---------------- a real solve: a pressure on only the first 30 of the top edge (small, so the solution stays linear)
m, p, ls = rect(100, 20)
t = new_tab(m)
info = t.apply_split(("ln", ls[2]), 30)                      # top edge runs (100,20) -> (0,20): the first 30 units are x = 70 .. 100 (the free end)
t.supports = [{"mode": "fixed", "targets": [("ln", ls[3])]}]
t.e_h.setText("5")
t.run_mesh()
assert t.mesh is not None
mat = t.read_material()
def umax(targets):
    ld = [{"kind": "pressure", "p": 0.5, "targets": targets}]
    r = pf.solve(t.mesh, mat, t.supports, ld, lambda *a, **k: None, lambda: False)
    assert not r.get("nonlinear"), "this check needs the linear solution"
    return float(np.max(np.abs(r["u"])))
a_, b_, ab = umax([("ln", ls[2])]), umax([info["second"]]), umax([("ln", ls[2]), info["second"]])
assert 0 < a_ < ab and 0 < b_ < ab and abs(ab - (a_ + b_)) < 0.02 * ab, (a_, b_, ab)
# the same load on the two pieces equals the load on the unsplit edge
m2, p2, ls2 = rect(100, 20)
t2 = new_tab(m2); t2.supports = [{"mode": "fixed", "targets": [("ln", ls2[3])]}]; t2.e_h.setText("5"); t2.run_mesh()
r2 = pf.solve(t2.mesh, t2.read_material(), t2.supports, [{"kind": "pressure", "p": 0.5, "targets": [("ln", ls2[2])]}], lambda *a, **k: None, lambda: False)
assert abs(float(np.max(np.abs(r2["u"]))) - ab) < 0.02 * ab
print("OK sim split", round(a_, 5), round(b_, 5), round(ab, 5))
os._exit(0)
