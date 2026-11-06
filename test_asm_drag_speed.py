"""A drag step must not redo the slow bounding box of every part: each size is computed once per solid.  Also the dev-build frame-rate read-out."""
import faulthandler; faulthandler.dump_traceback_later(200, exit=True)
import os, sys, time, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
import numpy as np
from build123d import Box, Cylinder, Pos
import asm_model as am
class Counted:
    n = 0
    def __init__(self, s): self.s = s
    def bounding_box(self): Counted.n += 1; return self.s.bounding_box()
    def __getattr__(self, k): return getattr(self.s, k)
parts = {"P": Counted(Box(100, 100, 20) - Cylinder(5, 30)), "Q": Counted(Cylinder(5, 30)), "R": Counted(Box(20, 20, 10))}
A = am.Assembly(); A.solid_fn = lambda c: parts[c["path"]]
p = A.add_component("P", fixed=True); q = A.add_component("Q", pos=(3, 2, 10), fixed=False); r = A.add_component("R", pos=(40, 0, 10), fixed=False)
cyl = lambda s: [f for f in s.faces() if f.geom_type.name == "CYLINDER"][0]
R = lambda c, f: {"c": c["id"], "k": "face", "r": am.face_ref(f)}
m = A.add_mate("concentric", [R(p, cyl(parts["P"])), R(q, cyl(parts["Q"]))]); A.prepare(m)
m2 = A.add_mate("distance", [R(q, cyl(parts["Q"])), R(r, cyl(parts["R"]).__class__ and cyl(parts["Q"]))] if False else [{"c": q["id"], "k": "origin"}, {"c": r["id"], "k": "origin"}]); A.prepare(m2)
assert A.solve()
Counted.n = 0
cl = A.cluster(q["id"]); Rm, t = A.pose(q)
for i in range(30):
    A.solve(drag={q["id"]: (Rm, t + np.array([0, 0, 0.3 * (i + 1)]))}, limit=cl, grab={q["id"]: np.zeros(3)})
assert Counted.n <= len(A.components), f"bounding boxes computed {Counted.n} times in 30 drag steps"
# a new solid for a component (the part was edited) gets a fresh size
Counted.n = 0; parts["Q"] = Counted(Cylinder(8, 60)); A._comp_scale(q); assert Counted.n == 1
# the frame-rate read-out: only in the dev (playground) build
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import gpd_app
for chan, want in (("playground", True), ("release", False)):
    os.environ["OPARA_CHANNEL"] = chan
    sh = gpd_app.AppShell([]); w = sh.new_assembly()
    assert (getattr(w, "fps_label", None) is not None) == want, (chan, getattr(w, "fps_label", None))
    if want:
        w.plotter.render(); w.plotter.render(); w.fps_timer.timeout.emit(); app.processEvents()
        assert w.fps_label.text().endswith("fps") and w.fps_label.text() != "-- fps", w.fps_label.text()
print("PASS"); os._exit(0)
