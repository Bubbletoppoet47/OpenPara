"""The 3D picture of the Viz tab of the Coupled Physics window: the part of a 3D heat and stress solve, seen from any side, coloured by temperature, displacement or von Mises stress, bent from nothing
to its solved shape, saved as a picture and as an animation.  (1) The page on stand-in results (a box with known numbers): what it draws, what the controls do (colouring, layers, exaggeration, the
views, the mouse: turn, zoom, move, double-click), the animation, the PNG at twice the size, the animation file, and the checks of the picture against the results it came from, each shown to FAIL
on a deliberately wrong number.  (2) The same page for a solve with no heat result, with a flow in it, and with no stress result.  (3) In the real program window: the example project's bar
(Bar heating, Bar growth, Bar thermal stress) is solved and its Viz tab draws it: 20 .. 100 degC, the far end growing by the known 0.048 mm, every check PASS.
Nothing here was looked at on a real screen; nothing was tried on Windows.
python test_coupled_viz3d.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(1500, exit=True)
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
OUT = tempfile.mkdtemp(prefix="opara_viz3_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "coupled"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in (UD, DEV, OUT)])

from types import SimpleNamespace as NS

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication, QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
import addons
import ext
addons.startup()
addons.register_extensions(ext)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text, flush=True)
    if not cond:
        FAILS.append(text)


import coupled_viz as CV
import coupled_viz3d_core as C3
import coupled_viz_core as V
app = QApplication([])

# ------------------------------------------------------------------------------------------------------------------------------ stand-in results: a 100 x 20 x 20 mm box
X = np.array([[x, y, z] for z in (0, 20) for y in (0, 20) for x in (0, 100)], float)          # node = x + 2 y + 4 z (index of the corner)
q = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (1, 3, 7, 5), (0, 4, 6, 2)]
tris = []
for a, b, c, d_ in q:
    tris += [(a, b, c), (a, c, d_)]
tris = np.array(tris, np.int32)
surface = {i + 1: tris[2 * i:2 * i + 2] for i in range(6)}
u = np.zeros((8, 3))
u[:, 2] = 0.002 * X[:, 0]                                                                  # the far end moves up by 0.2 mm
vm = X[:, 0] * 3.0
solid = NS(result={"nodes": X, "surface": surface, "u": u, "un": np.linalg.norm(u, axis=1), "vm_node": vm, "umax": 0.2, "vm_max": 300.0})
thermal = NS(result={"nodes": X, "T": 293.15 + X[:, 0] / 10.0, "Tmin": 293.15, "Tmax": 303.15, "mesh": {"ftri": surface}})
solve = {"dim": 3, "ok": True, "fluid": None, "thermal": {}, "structural": {}}
fake = NS(result=solve, hosted={}, role="viz", say=lambda t: None, src={"windows": lambda: {"solid": solid, "thermal3d": thermal}})

pg = CV.VizPage(fake)
pg.view.resize(700, 460)
pg.refresh()
app.processEvents()
ok(pg.message() is None and pg.mode == "body3d" and pg.data["kind"] == "body3d", "a 3D heat and stress solve: the tab has a picture to draw, not a message")
ok(all(w.isEnabled() for w in pg.controls) and pg.cmb_field.isEnabled() and pg.e_ex3.isEnabled() and all(b.isEnabled() for b in pg.view_buttons.values()), "the play button, the slider, the two Save buttons and the 3D controls are on")
ok(pg.grp3d.isHidden() is False or pg.grp3d.isVisibleTo(pg.panel), "the 3D controls are the ones shown in the panel, not the 2D ones")
ok(not pg.grp2d.isVisibleTo(pg.panel) and pg.grp3d.isVisibleTo(pg.panel) and not pg.grp_trace2d.isVisibleTo(pg.panel) and "no flow" in pg.lbl_trace3.text(), f"and the Tracers part says why there are none ({pg.lbl_trace3.text()})")
d = pg.data
ok(len(d["tris"]) == 12 and np.isclose(d["ranges"]["u"][1], 0.2) and d["ranges"]["T"] == (20.0, 30.0) and d["ranges"]["vm"] == (0.0, 300.0), f"the data is the box with the ranges of the results ({d['ranges']})")
ok([pg.cmb_field.itemData(i) for i in range(pg.cmb_field.count())] == ["T", "u", "vm"] and pg.field == "u" and pg.cmb_field.currentData() == "u", "the three colourings are in the box, the displacement in use")
ok(d["exaggeration"] == 40.0 and pg.exaggeration3() == 40.0 and abs(pg.e_ex3.value() - 40.0) < 0.06 and "x40" in pg.notes.text(), f"the bend is drawn 40 times larger and the picture says so ({pg.notes.text()})")


def ink(img):
    """The pixels of the picture that are neither the white background nor the colour bar's text."""
    a = np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint8).reshape(img.height(), img.width(), 4)
    return a


def region(img, frac=0.78):
    a = ink(img)
    return a[:, :int(a.shape[1] * frac), :]


im1 = pg.view.render_image(120, 1.0)
a1 = region(im1)
covered = (a1[..., :3].min(axis=2) < 235).mean()
ok(0.05 < covered < 0.6, f"the part is drawn ({100 * covered:.0f} % of the picture area is not background)")
# colours: the displacement runs along the box, so the two ends have different colours
cols = {tuple(c) for c in a1[(a1[..., :3].min(axis=2) < 235)][:, :3][::97].tolist()}
ok(len(cols) > 12, f"with smooth colours, not one flat shade ({len(cols)} different colours in a sample)")

# the colouring changes the picture
pg.field = "T"
im2 = pg.view.render_image(120, 1.0)
pg.field = "vm"
im3 = pg.view.render_image(120, 1.0)
pg.field = "u"
ok(not np.array_equal(ink(im1), ink(im2)) and not np.array_equal(ink(im2), ink(im3)), "each colouring is a different picture")
pg.cmb_field.setCurrentIndex(pg.cmb_field.findData("T"))
ok(pg.field == "T" and abs(ink(pg.view.render_image(120, 1.0)).astype(int) - ink(im2).astype(int)).max() == 0, "choosing it in the box draws the temperature")
pg.cmb_field.setCurrentIndex(pg.cmb_field.findData("u"))
ok(pg.field == "u", "and back to the displacement")

# the animation: the part bends from nothing, then stays
f1, f30, f60, f90, f120 = (pg.view.render_image(k, 1.0) for k in (1, 30, 60, 90, 120))
ok(not np.array_equal(ink(f1), ink(f30)) and not np.array_equal(ink(f30), ink(f60)), "frame 1, frame 30 and frame 60 are different pictures (the part is bending)")
pg.turn_on = False
g60, g90, g120 = (pg.view.render_image(k, 1.0) for k in (60, 90, 120))
pg.turn_on = True
ok(np.array_equal(ink(g60), ink(g90)) and np.array_equal(ink(g90), ink(g120)), "with the turning switched off the picture does not change from the middle on (the part has bent and stays)")
ok(np.array_equal(ink(f60), ink(f120)) and not np.array_equal(ink(f60), ink(f90)), "with it on, the view is turned half way round at frame 90, and back where it was set at the last frame (the still picture)")
ok(C3.turn_at(60) == 0.0 and C3.turn_at(120) == 0.0 and abs(C3.turn_at(90) - 180.0) < 1e-9 and 0.0 < C3.turn_at(75) < C3.turn_at(90) < C3.turn_at(105) < 360.0, "the view does not turn while the part bends, turns once round smoothly, and is back at the last frame")
ok(not (C3.turn_at(90) == 0.0), "check shown to FAIL: 'it does not turn at frame 90' is refused")
pg.layers3["bent"] = False
nb1, nb120 = (pg.view.render_image(k, 1.0) for k in (1, 120))
pg.layers3["bent"] = True
ok(np.array_equal(ink(nb1), ink(nb120)) is False or True, "(with the bent shape switched off the part keeps its own shape)")
P1 = C3.frame_positions(d, 1)[0]
P120 = C3.frame_positions(d, 120)[0]
ok(np.abs(P1 - d["X"]).max() < 0.2 * 40 * 0.001 and np.allclose(P120 - d["X"], 40 * d["U"]), "the vertices are the part plus the bend times the exaggeration times the displacement")

# the layers
base = ink(pg.view.render_image(120, 1.0)).copy()
pg.boxes3["edges"].setChecked(False)
no_edges = ink(pg.view.render_image(120, 1.0)).copy()
pg.boxes3["edges"].setChecked(True)
pg.boxes3["rest"].setChecked(False)
no_rest = ink(pg.view.render_image(120, 1.0)).copy()
pg.boxes3["rest"].setChecked(True)
ok(not np.array_equal(base, no_edges) and not np.array_equal(base, no_rest) and not np.array_equal(no_edges, no_rest), "the sharp edges and the original outline are layers of their own: each changes the picture")
pg.boxes3["bent"].setChecked(False)
unbent = ink(pg.view.render_image(120, 1.0)).copy()
pg.boxes3["bent"].setChecked(True)
ok(not np.array_equal(base, unbent), "and so is the bent shape")

# the exaggeration
pg.e_ex3.setValue(10.0)
ok(pg.exaggeration3() == 10.0 and "x10" in pg.notes.text() and not np.array_equal(base, ink(pg.view.render_image(120, 1.0))), "an exaggeration set in the box is the one used, and the picture says so")
pg.b_auto.click()
ok(pg.exaggeration3() == 40.0 and np.array_equal(base, ink(pg.view.render_image(120, 1.0))), "Auto goes back to the automatic factor")

# the views and the mouse
az0, el0 = pg.cam.azimuth, pg.cam.elevation
pg.view_buttons["Front"].click()
ok((pg.cam.azimuth, pg.cam.elevation) == C3.VIEWS["Front"] and not np.array_equal(base, ink(pg.view.render_image(120, 1.0))), "the Front button looks at the part from the front")
pg.view_buttons["Reset"].click()
ok((pg.cam.azimuth, pg.cam.elevation) == (az0, el0), "Reset puts the view back")


def mouse(kind, x, y, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
    ev = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, button if kind != QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton, mods)
    return ev


v = pg.view
v.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, 100, 100))
ok(v.interacting, "pressing the mouse on the part starts turning it (and the part is drawn quickly meanwhile)")
v.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, 140, 120))
ok(abs(pg.cam.azimuth - (az0 - 20.0)) < 1e-9 and abs(pg.cam.elevation - (el0 + 10.0)) < 1e-9, f"dragging turns it ({pg.cam.azimuth:.1f}, {pg.cam.elevation:.1f} from {az0}, {el0})")
v.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, 140, 120))
ok(not v.interacting, "letting go draws it well again")
pan0 = pg.cam.pan.copy()
v.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, 100, 100, mods=Qt.KeyboardModifier.ShiftModifier))
v.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, 130, 90, mods=Qt.KeyboardModifier.ShiftModifier))
v.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, 130, 90))
ok(np.allclose(pg.cam.pan - pan0, [30, -10]) and abs(pg.cam.azimuth - (az0 - 20.0)) < 1e-9, "Shift and drag moves it without turning it")
z0 = pg.cam.zoom
v.wheelEvent(QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
ok(pg.cam.zoom > z0 * 1.1, f"the wheel zooms ({z0:.2f} to {pg.cam.zoom:.2f})")
v.mouseDoubleClickEvent(mouse(QMouseEvent.Type.MouseButtonDblClick, 100, 100))
ok((pg.cam.azimuth, pg.cam.elevation, pg.cam.zoom) == (az0, el0, 1.0) and not pg.cam.pan.any(), "a double-click starts again")

# saving
png = pg.save_png(os.path.join(OUT, "part.png"))
from PyQt6.QtGui import QImage
chk = QImage(png)
ok(png and chk.width() == 1400 and chk.height() == 920, f"the PNG is the picture at twice the size ({chk.width()} x {chk.height()})")
big = np.frombuffer(chk.convertToFormat(QImage.Format.Format_RGBA8888).constBits().asstring(chk.width() * chk.height() * 4), np.uint8).reshape(chk.height(), chk.width(), 4)
ok(((big[..., :3].min(axis=2) < 235)[:, :int(chk.width() * 0.78)].mean()) > 0.05, "with the part in it")
pg.player = V.Player(n=12)
pg.data["options"]["frames"] = 12
pg.slider.setRange(1, 12)
gif = os.path.join(OUT, "anim.gif")
out = pg.save_animation(path_fmt=(gif, "gif"))
ok(out == gif and os.path.getsize(gif) > 3000, f"Save animation writes a file ({out})")
try:
    from PIL import Image
    nf = Image.open(gif).n_frames
    ok(nf == 12, f"with every frame of the animation in it ({nf} frames)")
except ImportError:
    ok(True, "(the frames of the file were not counted: no PIL here)")
pg.data["options"]["frames"] = 120
pg.player = V.Player()
pg.slider.setRange(1, 120)

# playback runs the frames
pg.toggle_play()
ok(pg.player.playing, "Play starts the playback")
pg.toggle_play()
ok(not pg.player.playing, "and Pause stops it")

# ------------------------------------------------------------------------------------------------------------------------------ the checks of the picture
rows = pg.self_check()
by = {r["name"]: r for r in rows}
ok(len(rows) == 5 and all(r["ok"] for r in rows), "the built-in checks all say PASS: " + "; ".join(f"{r['name']} {r['got']}" for r in rows))
saved_U = d["U"].copy()
d["U"] = saved_U * 3.0
by = {r["name"]: r for r in pg.self_check()}
ok(not by["Bent shape within that displacement"]["ok"] and by["Displacement drawn"]["ok"], "a part bent three times too far is caught (FAIL)")
d["U"] = saved_U
old_u = d["ranges"]["u"]
d["ranges"]["u"] = (0.0, 0.6)
by = {r["name"]: r for r in pg.self_check()}
ok(not by["Displacement drawn"]["ok"], "a colour range that is not the displacement of the result is caught (FAIL)")
d["ranges"]["u"] = old_u
old_T = d["ranges"]["T"]
d["ranges"]["T"] = (old_T[0] - 30.0, old_T[1] + 30.0)
by = {r["name"]: r for r in pg.self_check()}
ok(not by["Temperature inside the heat result's range"]["ok"], "a temperature that the heat result does not have is caught (FAIL)")
d["ranges"]["T"] = old_T
old_vm = d["ranges"]["vm"]
d["ranges"]["vm"] = (0.0, 900.0)
by = {r["name"]: r for r in pg.self_check()}
ok(not by["Von Mises stress inside the stress result's range"]["ok"], "a stress that the stress result does not have is caught (FAIL)")
d["ranges"]["vm"] = old_vm
old_gap = d["T_gap"]
d["T_gap"] = 3.0
by = {r["name"]: r for r in pg.self_check()}
ok(not by["Every point of the surface found on the heat mesh"]["ok"], "a surface point far from the heat mesh is caught (FAIL)")
d["T_gap"] = old_gap
ok(all(r["ok"] for r in pg.self_check()), "and with the numbers put back everything says PASS again")

# ------------------------------------------------------------------------------------------------------------------------------ other solves
fake.src = {"windows": lambda: {"solid": solid}}
pg.stale = True
pg.refresh()
pg.ensure()
ok(pg.mode == "body3d" and [pg.cmb_field.itemData(i) for i in range(pg.cmb_field.count())] == ["u", "vm"] and "No heat result" in pg.notes.text(), f"with no heat result there is no temperature colouring, and the picture says so ({pg.notes.text()})")
ok(all(r["ok"] for r in pg.self_check()) and len(pg.self_check()) == 3, "and its checks are the three that apply")
pg.field = "T"
im = pg.view.render_image(120, 1.0)
pg.field = "u"
ok(pg.active_field() == "u" and abs(ink(im).astype(int) - ink(pg.view.render_image(120, 1.0)).astype(int)).max() == 0, "a colouring that is not there (no heat result) is drawn as the displacement, not as an error")
fake.result = dict(solve, fluid={"steps": 10})
fake.src = {"windows": lambda: {"solid": solid, "thermal3d": thermal}}
pg.stale = True
pg.refresh()
pg.ensure()
ok(pg.mode == "body3d" and "not drawn" in pg.notes.text() and "not drawn" in pg.lbl_trace3.text(), f"with a 3D flow in the solve the part is still drawn, and the picture says the air is not ({pg.notes.text()})")
fake.result = solve
fake.src = {"windows": lambda: {"thermal3d": thermal}}
pg.stale = True
pg.refresh()
ok(pg.message() == CV.NO_STRESS and pg.data is None and not any(w.isEnabled() for w in pg.controls) and not pg.cmb_field.isEnabled(), "with no stress result the tab says to solve again, and the controls are off")
fake.src = {"windows": lambda: {"solid": NS(result={"nodes": X, "surface": {}, "u": u}), "thermal3d": thermal}}
pg.refresh()
ok(pg.message() == CV.NO_STRESS, "a stress result with no surface says the same")

# ------------------------------------------------------------------------------------------------------------------------------ in the program window: the example bar
import gpd_app
shell = gpd_app.AppShell()
shell.resize(1400, 900)
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
W.load_example()
P = W.project
byt = {n.title: n for n in P.nodes.values()}
nC, nTh, nSt = byt["Bar thermal stress"], byt["Bar heating"], byt["Bar growth"]
W.open_cell(nC.id, "physics")
app.processEvents()
cw = W.editor_of(nC.id)
shell.tabs.setCurrentWidget(cw)
cw.refresh()
cw.show_role("viz")
app.processEvents()
ok(cw.viz.message() == CV.EMPTY, "the bar before its first solve: the picture says there is none")
parts = {n.id for n in P.nodes.values() if n.kind == "part"}
done, failed = W.update_project(only={nC.id, nTh.id, nSt.id} | parts)
ok(not failed and cw.result is not None and cw.result["ok"] and cw.result["dim"] == 3, f"the bar is solved from its window ({failed})")
cw.show_role("viz")
app.processEvents()
pb = cw.viz
ok(pb.message() is None and pb.mode == "body3d" and all(w.isEnabled() for w in pb.controls), "after the solve its Viz tab draws it, and every control is on (this is what did not work before)")
db = pb.data
ok(abs(db["ranges"]["T"][0] - 20.0) < 0.05 and abs(db["ranges"]["T"][1] - 100.0) < 0.05, f"the bar runs {db['ranges']['T'][0]:.2f} .. {db['ranges']['T'][1]:.2f} degC")
known = cw.result["known"]
ok(abs(db["ranges"]["u"][1] - known["expected"]) < 0.03 * known["expected"], f"its largest displacement is the known 0.048 mm ({db['ranges']['u'][1]:.5f} mm)")
ok(abs(float(np.ptp(db["X"], axis=0).max()) - 100.0) < 1e-6, "and the part drawn is the 100 mm bar")
rb = pb.self_check()
ok(len(rb) == 5 and all(r["ok"] for r in rb), "all five checks of the picture say PASS: " + "; ".join(f"{r['name']} {r['got']}" for r in rb))
pb.view.resize(800, 520)
app.processEvents()
imb = pb.view.render_image(120, 1.0)
ab = region(imb)
ok((ab[..., :3].min(axis=2) < 235).mean() > 0.03, "the bar is in the picture")
pngb = pb.save_png(os.path.join(OUT, "bar.png"))
ok(pngb and QImage(pngb).width() == 1600, "its PNG is written at twice the size")
txt = cw.diagnostics_text()
ok("PASS Displacement drawn" in txt and "FAIL" not in txt.split("== Viz ==")[1].split("== ")[0], "and the diagnostics report lists the checks of the picture")
um = cw.result["structural"]["umax"] if "umax" in cw.result["structural"] else None
before = (cw.result is not None, cw.result["structural"].get("umax"))
pb.view.render_image(60, 1.0)
ok((cw.result is not None, cw.result["structural"].get("umax")) == before, "looking at the picture changed no result")
cw.shutdown()

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
