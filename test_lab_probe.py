"""Constraint Lab Drag Recorder and view guard (dev_addons/constraint_lab/lab_probe.py).
The guard puts the empty interactor style back when something has switched the view to an orbiting style (so a left-drag cannot orbit the camera while a
part is dragged); the recorder logs presses, drag steps, renders, the camera (with the stack of whoever changed it) and the view size, reports them in words,
saves the report, and leaves the window exactly as it was when it is switched off."""
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
os.symlink(os.path.join(HERE, "dev_addons", "constraint_lab"), os.path.join(DEV, "constraint_lab"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
import numpy as np
import addons
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
import pm_model as pm, sk_tools as sk, gpd_app, ext, assembly, settings
addons.startup(); addons.register_extensions(ext); addons.activate()
import lab_tab, lab_probe

settings.set_many({"outline_mode": "baked", "hover": True}, persist=False)


def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(UD, name); open(p, "w").write(d.to_json()); return p
pa = make_part("base.gpd", ((0, 0), (60, 60)), 10); pb = make_part("block.gpd", ((0, 0), (20, 20)), 20)
sh = gpd_app.AppShell([pa]); w = sh.new_addon_tab("constraint_lab")
w.insert_files([pa, pb]); base, blk = w.asm.components
blk["fixed"] = False; blk["pos"] = [20.0, 20.0, 10.0]; w.update_all(fit=True)
pl = w.plotter
def size_view(W, H): pl.resize(W, H); pl.window_size = [W, H]; [app.processEvents() for _ in range(10)]      # the widget and the VTK window the same size, as on screen
size_view(600, 450); assert (pl.width(), pl.height()) == (600, 450)
pl.camera_position = [(160, -140, 120), (30, 30, 15), (0, 0, 1)]; pl.render(); app.processEvents()
USER = "vtkInteractorStyleUser"


def cam(): return lab_probe.camera_snapshot(pl.camera)
def send(t, pt, btn, buttons):
    QApplication.sendEvent(pl, QMouseEvent(t, QPointF(*pt), pl.mapToGlobal(QPointF(*pt)), btn, buttons, Qt.KeyboardModifier.NoModifier))
def screen_pt(world):
    s = w.ed.to_screen(world)[0]; r = pl.devicePixelRatioF(); return (s[0] / r, pl.height() - 1 - s[1] / r)
def drag(start, dx=60, dy=-24, btn=Qt.MouseButton.LeftButton, n=12):
    send(QEvent.Type.MouseButtonPress, start, btn, btn)
    for i in range(1, n + 1):
        send(QEvent.Type.MouseMove, (start[0] + dx * i / n, start[1] + dy * i / n), Qt.MouseButton.NoButton, btn)
    send(QEvent.Type.MouseButtonRelease, (start[0] + dx, start[1] + dy), btn, Qt.MouseButton.NoButton)
    app.processEvents()
on_part = screen_pt(np.array(blk["pos"]) + [10, 10, 20.0]); empty = (30.0, pl.height() / 2)

# ---- 1. the guard is there, the view starts on the empty style and pyvista agrees with it
assert isinstance(w.guard, lab_probe.ViewGuard) and w.guard.enabled and w.guard.fired == 0
assert lab_probe.style_name(pl) == USER and pl.iren.style is w.guard.user, (lab_probe.style_name(pl), pl.iren.style)
assert w.act["lab_rec"].isCheckable() and not w.act["lab_rec"].isChecked()
# anything that makes pyvista apply its own style again (here: update_style, and enable_trackball_style) keeps the empty one: it is the style pyvista holds
pl.iren.update_style(); assert lab_probe.style_name(pl) == USER

# ---- 2. the style is switched to an orbiting one behind the app's back: the next press puts the empty one back, and a left-drag on empty space does not orbit
pl.enable_trackball_style(); assert lab_probe.style_name(pl) != USER, "the test setup: the view is on pyvista's orbit style now"
c0 = cam(); drag(empty)
assert lab_probe.style_name(pl) == USER and w.guard.fired == 1 and w.guard.log and np.allclose(cam(), c0), "guard: put back at the press, camera untouched"
assert pl.iren.style is w.guard.user, "pyvista is told too"
drag(empty); assert w.guard.fired == 1, "nothing to correct the second time"

# ---- 3. without the guard the same switch DOES orbit the camera (this is the symptom), and the recorder shows who did it
w.guard.enabled = False
pl.enable_trackball_style()
w.act["lab_rec"].setChecked(True); w.rec_toggle()
pr = w.probe; assert isinstance(pr, lab_probe.DragProbe) and pr.active
c0 = cam(); drag(empty, n=16)
w.act["lab_rec"].setChecked(False); w.rec_toggle()
assert w.probe is None and not pr.active
moved = not np.allclose(cam(), c0)
print("unguarded orbit style: camera moved:", moved, " camera modifications recorded:", len(pr.cam_mods))
txt = pr.text
assert "Drag Recorder report" in txt and "1 press-to-release run" in txt and "InteractorStyleTrackballCamera" in txt, txt
if moved:
    assert pr.cam_mods and any(m["down"] for m in pr.cam_mods), "camera changes are recorded while the button is down"
    assert "The camera WAS changed" in txt and "mouseMoveEvent" in txt, "the stack names the Qt mouse handler that forwarded the event to VTK:\n" + txt
w.guard.enabled = True
pl.iren.style = w.guard.user; assert lab_probe.style_name(pl) == USER

# ---- 4. a normal part drag with the recorder on: the camera is not touched, steps and renders are counted, the file is written, nothing is left behind
pl.camera_position = [(160, -140, 120), (30, 30, 15), (0, 0, 1)]; pl.render(); app.processEvents()      # step 3 orbited the camera on purpose
on_part = screen_pt(np.array(blk["pos"]) + [10, 10, 20.0])
w.set_mode("move", quiet=True)
w.act["lab_rec"].setChecked(True); w.rec_toggle(); pr = w.probe
assert "drag_move" in w.__dict__ and "render" in pl.__dict__
c0, p0, size0 = cam(), np.array(blk["pos"]), (pl.width(), pl.height())
drag(on_part, n=20)
assert np.abs(np.array(blk["pos"]) - p0).max() > 1.0, "the part moved"
w.act["lab_rec"].setChecked(False); w.rec_toggle()
assert np.allclose(cam(), c0) and (pl.width(), pl.height()) == size0
txt = pr.text
assert "1 press-to-release run" in txt and "The camera was NOT touched during any drag" in txt and "The 3D view did not change size." in txt, txt
assert pr.steps and len(pr.renders) >= len(pr.steps) and sum(1 for r in pr.rows if r[1] == "move") == 20 and len(pr.drags) == 1
assert pr.drags[0]["steps"] == len(pr.steps) and pr.drags[0]["btn"] == "LeftButton" and "Drag steps" in txt and "Time between steps" in txt
assert "drag_move" not in w.__dict__ and w.drag_move.__func__ is assembly.AssemblyWindow.drag_move, "the method is the class's own again"
n_cam = len(pr.cam_mods); n_rows = len(pr.rows)
pl.camera.Azimuth(3.0); drag(on_part, n=3)
assert len(pr.cam_mods) == n_cam and len(pr.rows) == n_rows, "nothing is recorded after it is switched off"
f1, f2 = os.path.join(UD, "drag_record.txt"), os.path.join(UD, "drag_record_raw.csv")
assert os.path.exists(f1) and open(f1, encoding="utf-8").read() == txt and os.path.exists(f2) and "step_ms" in open(f2, encoding="utf-8").read()
assert w.report_win.windowTitle() == "Drag Recorder" and w.report_win.text.toPlainText() == txt
w.report_win.close()

# ---- 5. a camera change made on purpose shows where it came from, and a resized view is reported
w.act["lab_rec"].setChecked(True); w.rec_toggle(); pr = w.probe
def fake_culprit(): pl.camera.Azimuth(7.0)
send(QEvent.Type.MouseButtonPress, on_part, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
fake_culprit()
w0 = pl.width(); size_view(660, 450); assert pl.width() != w0
send(QEvent.Type.MouseButtonRelease, on_part, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
w.act["lab_rec"].setChecked(False); w.rec_toggle()
txt = pr.text
assert "The camera WAS changed" in txt and "fake_culprit" in txt and "position" in txt, txt
assert "The 3D view changed size:" in txt and "while a button was down" in txt, txt
assert "Recorded" in txt and "pyvistaqt" in txt and "interactor style now" in txt

print("OK lab probe")
os._exit(0)
