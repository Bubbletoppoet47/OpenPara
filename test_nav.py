import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QWheelEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, nav, sk_tools as sk
w = pm_app.MainWindow(); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0)
nv = w.nav; cube = nv.cube
print("cube:", cube is not None, "box", cube.box)
cam = w.plotter.camera
# --- wheel: rolling toward you (negative delta) zooms in
def wheel(delta, x=500, y=350):
    ev = QWheelEvent(QPointF(x, y), QPointF(x, y), __import__("PyQt6.QtCore", fromlist=["QPoint"]).QPoint(0, 0), __import__("PyQt6.QtCore", fromlist=["QPoint"]).QPoint(0, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    nv.eventFilter(w.plotter, ev)
d0 = np.linalg.norm(np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint()))
nv.zoom(1.2); d1 = np.linalg.norm(np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint())); print("zoom in", d0, "->", d1); assert d1 < d0
nv.zoom(1 / 1.2); nv.zoom(1 / 1.2); d2 = np.linalg.norm(np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint())); assert d2 > d1
# --- rotate / pan
p0 = np.array(cam.GetPosition()); nv.rotate(40, 10); assert np.linalg.norm(np.array(cam.GetPosition()) - p0) > 0.1
f0 = np.array(cam.GetFocalPoint()); nv.pan(30, 0); assert np.linalg.norm(np.array(cam.GetFocalPoint()) - f0) > 0.01
# --- cube: hit test of the middle of the cube and snapping
cx, cy = (cube.box[0] + cube.box[2]) / 2, (cube.box[1] + cube.box[3]) / 2
cube.click(("face", "Top")); r_, u_, t_ = nav.view_dirs(cam); print("top view toward viewer", t_.round(3)); assert abs(t_[2] - 1) < 1e-6
cube.click(("face", "Front")); r_, u_, t_ = nav.view_dirs(cam); assert abs(t_[1] + 1) < 1e-6 and abs(u_[2] - 1) < 1e-6
cube.click(("face", "Right")); r_, u_, t_ = nav.view_dirs(cam); assert abs(t_[0] - 1) < 1e-6
cube.click(("home",)); r_, u_, t_ = nav.view_dirs(cam); print("home", t_.round(3))
cube.click(("corner", 7)); r_, u_, t_ = nav.view_dirs(cam); print("corner", t_.round(3)); assert np.allclose(np.abs(t_), 1 / np.sqrt(3), atol=1e-6)
cube.click(("edge", 0)); cube.click(("arrow", "left"))
# hit testing at the cube centre returns a face when looking at a face
cube.click(("face", "Front")); h = cube.hit(cx, cy); print("centre hit", h); assert h == ("face", "Front")
# project a face centre and hit it
r_, u_, t_ = nav.view_dirs(cam)
cube.click(("corner", 7)); r_, u_, t_ = nav.view_dirs(cam)
for nm, n in nav.FACES:
    if np.dot(n, t_) > 0.4:
        p = cube.project(np.array(n, float) * 0.8, r_, u_); print("face hit", nm, cube.hit(*p)); assert cube.hit(*p) == ("face", nm)
# hover redraw
cube.set_hover(("face", "Top")); cube.set_hover(None)
# --- sketch: construction toggle and origin
w.sel_plane = "Front"; w.command("sketch"); m = ed.m
sk.add_rect_corner(m, (10, 10), (30, 20)); w.doc.reports[w.sel] = sk.solve_model(m); w.doc.store_sketch(w.sel); w.update_all()
ed.sel = [("ln", list(ed.m.lns)[0])]; ed.command_construction(); print("construction:", ed.m.constr); assert ("ln", list(ed.m.lns)[0]) in ed.m.constr
ed.sel = [("ln", list(ed.m.lns)[0])]; ed.command_construction(); assert not ed.m.constr
print("context actions:", [a for a, _ in ed.context_actions(*ed.to_screen(ed.to_world((20, 10)))[0])])
# origin: dimension from origin to a corner
import sketch_edit as se
se.ask_dim = lambda *a: "15"
ed.reset_tool("dim_h"); ed.picks = [("pt", 0)]
corner = [i for i, p in ed.m.pts.items() if i and abs(p[0] - 30) < 1e-6 and abs(p[1] - 20) < 1e-6][0]
ed.picks.append(("pt", corner)); ed.try_apply(); print("dims", [(c["type"], c["value"]) for c in ed.m.cons if c["type"].startswith("dim")], "dof", ed.rep.dof)
w.leave_sketch(); print("OK")
