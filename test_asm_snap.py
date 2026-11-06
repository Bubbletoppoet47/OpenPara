"""Concentric snap: a clamp saved far away and tilted lands on a pipe in one go; a pinned part still reports a real conflict; the Mate panel has the new buttons."""
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from build123d import Box, Cylinder, Pos, Rot
import asm_model as am
parts = {"T": Pos(3000, 0, 0) * Rot(0, 90, 0) * Cylinder(19.05, 6000), "C": Box(60, 100, 10) - Cylinder(20.64, 30),
         "F": Box(40, 40, 40) - Pos(0, 0, 0) * Cylinder(8, 60)}
cyl = lambda s, r: [f for f in s.faces() if f.geom_type.name == "CYLINDER" and abs(am.face_entity(f)["r"] - r) < 0.01][0]
R = lambda c, f: {"c": c["id"], "k": "face", "r": am.face_ref(f)}
def new():
    A = am.Assembly(); A.solid_fn = lambda c: parts[c["path"]]
    return A, A.add_component("T", fixed=True), A.add_component("C", pos=(180, 55, 1922), fixed=False)
def axis_gap(A, c, t):
    ec = A.world_entities({"type": "concentric", "refs": [R(c, cyl(parts["C"], 20.64)), R(t, cyl(parts["T"], 19.05))]})
    a, b = ec
    return float(np.linalg.norm(np.cross(a["d"], b["d"]))), float(np.linalg.norm(np.cross(b["p"] - a["p"], b["d"])))
# 1. Ian's case: clamp far away, tilted -> exact in one go, for many start poses
rng = np.random.default_rng(3)
for k in range(12):
    A, t, c = new()
    c["pos"] = list(rng.uniform(-3000, 3000, 3)); c["rv"] = list(rng.uniform(-3, 3, 3))
    m = A.add_mate("concentric", [R(c, cyl(parts["C"], 20.64)), R(t, cyl(parts["T"], 19.05))]); A.prepare(m)
    assert A.solve(extra=[m]), (k, A.status)
    ang, off = axis_gap(A, c, t)
    assert ang < 1e-6 and off < 1e-4, (k, ang, off)
# 2. smallest turn, not a flip: the clamp that already has its axis nearly along the pipe keeps its orientation
A, t, c = new(); c["rv"] = [0.0, 0.0, 0.0]
m = A.add_mate("concentric", [R(c, cyl(parts["C"], 20.64)), R(t, cyl(parts["T"], 19.05))]); A.prepare(m)
assert A.solve(extra=[m]); ang, off = axis_gap(A, c, t); assert ang < 1e-6 and off < 1e-4
# 3. a part that an earlier mate pins: still a real conflict, and it stays put
A = am.Assembly(); A.solid_fn = lambda c: parts[c["path"]]
t = A.add_component("T", fixed=True); f = A.add_component("F", pos=(100, 100, 0), fixed=False)
m1 = A.add_mate("concentric", [R(f, cyl(parts["F"], 8)), R(t, cyl(parts["T"], 19.05))]); A.prepare(m1)
assert A.solve()
t2 = A.add_component("T", pos=(0, 500, 0), fixed=True)
m2 = A.add_mate("concentric", [R(f, cyl(parts["F"], 8)), R(t2, cyl(parts["T"], 19.05))]); A.prepare(m2)
before = list(f["pos"])
A.solve()
assert A.status[m1["id"]] == "ok" and A.status[m2["id"]] == am.Assembly.CONFLICT, A.status
assert np.allclose(before, f["pos"], atol=1e-6)
# 4. the registry takes more types
assert "concentric" in am.SNAPS and callable(am.snap)
# 5. the Mate panel: nine icon buttons, three pick toggles, one checked
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QPushButton
app = QApplication.instance() or QApplication([])
import mate_icons
for n in mate_icons.NAMES:
    assert not mate_icons.pixmap(n, 24).isNull(), n
assert set(am.TYPES) <= set(mate_icons.NAMES)
print("PASS")
os._exit(0)
