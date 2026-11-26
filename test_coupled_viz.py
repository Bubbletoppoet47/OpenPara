"""The Viz tab of the Coupled Physics window: the rendered picture of the last coupled solve.  Three parts.
(1) The numbers behind it (coupled_viz_core, no Qt): the layers that are shown one at a time, the bend ramp, the playback counter, tracer lines on a field whose streamlines are known,
the particles (the same every time; the last frame has them where the first has them, so the loop is seamless), a triangle filled with known values, the colour bars and their labels.
(2) The page with no solve, with a 3D solve and with a solve that has no flow in it: what it says, and that its controls are off.
(3) In the real program window with the example project, solved: the air temperature runs 20 .. 50 degC; the largest displacement is the one the coupled solve reported; every tracer line
stays inside the air mesh; the dashed outline is the displacement of the stress analysis times the exaggeration; the layers change the picture; the PNG is the still picture at twice the size
and is the last frame; an animation file is written with every frame; nothing of the result changes.  Checks that must be able to fail are shown to fail on a deliberately wrong answer.
Nothing here was looked at on a real screen.
python test_coupled_viz.py"""
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
OUT = tempfile.mkdtemp(prefix="opara_viz_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "coupled"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in (UD, DEV, OUT)])

from types import SimpleNamespace as NS

import numpy as np
from PyQt6.QtGui import QImage
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


import coupled_viz_core as V

# ------------------------------------------------------------------------------------------------------------------------------ 1. the numbers (no Qt)
lay = V.set_layer(V.LAYERS_ON, "air_p", True)
ok(lay["air_p"] and not lay["air_T"] and lay["body_u"], "switching the air pressure on switches the air temperature off, and leaves the body alone")
lay2 = V.set_layer(lay, "body_vm", True)
ok(lay2["body_vm"] and not lay2["body_u"] and lay2["tracers"] and lay2["bent"], "the same for the body: von Mises replaces displacement; tracers and outline are free")
ok(V.set_layer(lay2, "tracers", False)["tracers"] is False and V.set_layer(lay2, "air_p", False)["air_T"] is False, "switching a layer off switches nothing on")
try:
    V.set_layer(lay, "nonsense", True)
    ok(False, "a layer that does not exist is refused")
except KeyError:
    ok(True, "a layer that does not exist is refused")

b = [V.bend_at(k) for k in range(0, 121)]
ok(b[0] == 0.0 and all(b[i] <= b[i + 1] + 1e-12 for i in range(120)) and b[60] == 1.0 and b[120] == 1.0, "the body bends from nothing to its final shape over the first half and stays: 0 -> 1 at frame 60, 1 at frame 120")
ok(abs(V.bend_at(30) - 0.5) < 1e-9 and V.bend_at(1) < 0.01, "a smooth ease: half way at frame 30, hardly moving at frame 1")


def bend_verdict(values):
    return values[0] == 0.0 and values[-1] == 1.0 and all(values[i] <= values[i + 1] + 1e-12 for i in range(len(values) - 1))


ok(bend_verdict(b) and not bend_verdict(b[::-1]), "check shown to FAIL on a ramp that runs backwards (a deliberately wrong answer)")

pl = V.Player()
ok(pl.n == 120 and pl.fps == 24 and pl.frame == 120 and not pl.playing, "the playback has 120 frames at 24 per second and rests on the last frame (the still picture)")
pl.seek(1)
pl.play()
ok(pl.advance(1.0) and pl.frame == 25, f"one second at 1x is 24 frames ({pl.frame})")
pl.speed = 4.0
pl.advance(0.25)
ok(pl.frame == 25 + 24, f"at 4x a quarter of a second is 24 frames ({pl.frame})")
pl.seek(118)
pl.advance(0.25)
ok(pl.playing and pl.frame == (118 + 24 - 1) % 120 + 1, f"with Loop it goes on from the first frame after the last ({pl.frame})")
pl.loop = False
pl.seek(118)
pl.advance(1.0)
ok(pl.frame == 120 and not pl.playing, "without Loop it stops on the last frame")
pl.speed = 1.0
pl.play()
ok(pl.frame == 1 and pl.playing, "Play from the last frame without Loop starts again")
pl.pause()
ok(pl.advance(5.0) is False, "paused, it does not move")

# a field whose streamlines are known: a uniform flow along x
vel = lambda P: (np.column_stack([np.ones(len(P)), np.zeros(len(P))]), P[:, 0] < 60.0)      # noqa: E731
ys = np.linspace(-26, 46, 31)
L = V.tracer_lines(vel, ys, -18.0, 98.0)
ok(len(L) == 31 and all(np.allclose(l[:, 1], l[0, 1]) for l in L), "in a uniform flow the tracer lines are straight and keep their height")
ok(all(abs(l[0, 0] + 18.0) < 1e-12 and np.allclose(np.diff(l[:, 0]), 0.5) for l in L), "they start at the inlet and go on in steps of half a millimetre")
ok(max(l[:, 0].max() for l in L) <= 60.0 and max(l[:, 0].max() for l in L) > 59.0, "they stop where the mesh ends (the field says 'outside' from x = 60), with no point outside it")
vel2 = lambda P: (np.column_stack([np.ones(len(P)), np.zeros(len(P))]), P[:, 0] < -17.0)     # noqa: E731
ok(V.tracer_lines(vel2, ys, -18.0, 98.0) == [], "a line of fewer than five points is dropped")
vel3 = lambda P: (np.zeros((len(P), 2)), np.ones(len(P), bool))                              # noqa: E731
ok(V.tracer_lines(vel3, ys, -18.0, 98.0) == [], "and a line that starts where the air does not move")
vel4 = lambda P: (np.column_stack([np.ones(len(P)), np.zeros(len(P))]), np.ones(len(P), bool))   # noqa: E731
L4 = V.tracer_lines(vel4, [0.0], -18.0, 10.0)
ok(len(L4) == 1 and L4[0][-1, 0] >= 10.0 and L4[0][-2, 0] < 10.0, "a line ends when it passes the last x")

lens = [float(V.arc_lengths(l)[-1]) for l in L]
s1, s2 = V.particle_starts(lens), V.particle_starts(lens)
ok(all(np.array_equal(a, b_) for a, b_ in zip(s1, s2)), "the particles start where they started the last time (a fixed series)")
ok(all(len(a) == 3 and (a >= 0).all() and (a < L_).all() for a, L_ in zip(s1, lens)), "three on every line, each inside its line")

data = {"options": dict(V.DEFAULTS), "lines": L, "cum": [V.arc_lengths(l) for l in L], "length": lens, "starts": s1, "length_per_unit": 1.0,
        "rest": [np.array([[0.0, 0.0], [20.0, 0.0]]), np.array([[20.0, 0.0], [20.0, 20.0]])], "disp": [np.array([[0.0, 0.0], [0.1, 0.0]]), np.array([[0.1, 0.0], [0.1, 0.05]])]}
f0, f120, f60 = V.frame_state(data, 0), V.frame_state(data, 120), V.frame_state(data, 60)
ok(np.allclose(np.array(f0["particles"]), np.array(f120["particles"]), atol=1e-9), "the last frame has the particles where the first has them: the loop is seamless for the air")
ok(not np.allclose(np.array(V.frame_state(data, 30)["particles"]), np.array(f0["particles"])), "in between they are somewhere else")
ok(len(f0["particles"]) == 93 and all(len(t) == 12 for t in f0["tails"]), "31 lines x 3 particles, a tail of 12 points behind each")
ok(np.allclose(f0["outline"][0], data["rest"][0]) and np.allclose(f120["outline"][0], data["rest"][0] + 30.0 * data["disp"][0]) and np.allclose(f60["outline"][1], f120["outline"][1]),
   "the outline is the body at the start and the displacement x 30 at the end (and stays so from frame 60)")
ok(np.allclose(V.frame_state(data, 120, exaggeration=60.0)["outline"][0], data["rest"][0] + 60.0 * data["disp"][0]), "another exaggeration scales the outline")
tail = np.array(V.frame_state(data, 100)["tails"][0])
ok(np.all(np.hypot(*np.diff(tail, axis=0).T) <= 6.0 / 11.0 + 1e-9), "a tail is 6 mm long, in 12 points")

# a triangle with known values
fit = V.Fit((0.0, 10.0, 0.0, 10.0), 100, 100)
xy = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
img = V.raster(xy, [[0, 1, 2]], np.array([0.0, 1.0, 0.5]), fit, 0.0, 1.0, "viridis")
ok(img[95, 5, 3] == 255 and img[5, 95, 3] == 0, "a triangle is filled and the corner outside it is left transparent")
ok(np.array_equal(img[95, 2, :3], V.lut("viridis")[int(round((0.0 * 0.96 + 1.0 * 0.02 + 0.5 * 0.02) * 255))]) or abs(int(img[95, 2, 0]) - int(V.lut("viridis")[3, 0])) <= 6,
   "the colour at a corner is the colour of its value (smooth between the corners)")
flat = V.raster(xy, [[0, 1, 2]], np.array([0.5]), fit, 0.0, 1.0, "viridis")
ok(np.array_equal(flat[90, 5, :3], V.lut("viridis")[128]), "a value per triangle fills it with one colour")
ok(np.array_equal(V.colours([0.0, 1.0, 5.0, -3.0], 0.0, 1.0, "inferno")[[0, 1, 2, 3]], V.lut("inferno")[[0, 255, 255, 0]]), "values outside the range get the end colours")
ok(V.ticks(20.0, 50.0, "Air temperature (°C)") == [20.0, 30.0, 40.0, 50.0] and V.ticks(0.0, 0.12, "Body displacement (mm)") == [0.0, 0.06, 0.12],
   "the colour bars are labelled every 10 degrees, or at the lowest, middle and highest value")
ok(V.view_window((0, 0, 20, 20), (-60, -60, 180, 80)) == (-20.0, 100.0, -35.0, 55.0), "the picture shows -20 .. 100 mm by -35 .. 55 mm round a 20 mm body")

# ------------------------------------------------------------------------------------------------------------------------------ 2. the page without something to show
import coupled_viz as CV
app = QApplication([])
fake = NS(result=None, hosted={}, role="viz", say=lambda t: None)
pg = CV.VizPage(fake)
pg.refresh()
ok(pg.message() == CV.EMPTY and pg.data is None, "no solve yet: the picture says so")
ok(not any(w.isEnabled() for w in pg.controls), "and the play button, the slider and the two Save buttons are off")
pg.view.resize(500, 320)
im = pg.view.render_image(120, 1.0)
ok(im.width() == 500 and any(im.pixelColor(x, y).red() < 200 for x in range(0, 500, 3) for y in range(100, 220, 3)), "the empty picture is drawn with its text")
ok(pg.save_png(os.path.join(OUT, "none.png")) is None and not os.path.exists(os.path.join(OUT, "none.png")), "and there is nothing to save")
fake.result = {"dim": 3, "ok": True, "fluid": None}
pg.refresh()
ok(pg.message() == CV.NO_3D, "a 3D solve: the tab says that Viz of 3D results is not here yet")
fake.result = {"dim": 2, "ok": True, "fluid": None}
pg.refresh()
ok(pg.message() == CV.NO_FLUID, "a 2D solve with no flow in it: the tab says what it is made for")

# ------------------------------------------------------------------------------------------------------------------------------ 3. in the program window
import gpd_app
import coupled_members as cm
import physics_cfd as pcfd
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
W.load_example()
P = W.project
byt = {n.title: n for n in P.nodes.values()}
nC = byt["Air, heat and bending"]
W.open_cell(nC.id, "physics")
app.processEvents()
cw = W.editor_of(nC.id)
cw.refresh()
cw.show_role("viz")
app.processEvents()
ok(cw.viz.message() == CV.EMPTY and cw.strip.marks().get("viz") == "update", f"the example before its first solve: the empty picture and a bolt on the Viz button ({cw.strip.marks().get('viz')})")
done, failed = W.update_project(only={byt["Air flow"].id, byt["Square heat"].id, byt["Square bending"].id, nC.id})
ok(not failed and cw.result is not None and cw.result["ok"], f"the example solves ({failed})")
res = cw.result
cw.show_role("viz")
app.processEvents()
pg = cw.viz
ok(pg.ensure() and pg.data is not None, "after the solve the picture has its data")
d = pg.data
a, bd = d["air"], d["body"]
ok(abs(a["T_range"][0] - 20.0) < 0.05 and abs(a["T_range"][1] - 50.0) < 0.05, f"the air temperature runs 20 .. 50 degC ({a['T_range'][0]:.3f} .. {a['T_range'][1]:.3f})")
umax = res["fsi"]["umax"]
ok(abs(bd["u_range"][1] - umax) <= 1e-3 * umax and abs(bd["u_range"][1] - 0.11994) < 2e-4, f"the largest displacement is the one the solve reported ({bd['u_range'][1]:.5f} mm, solve: {umax:.5f})")
ok(len(d["lines"]) == 31 and all(len(l) >= 5 for l in d["lines"]), f"31 tracer lines ({len(d['lines'])})")
flr = cw.hosted["fluid"].win.tab.result
ff = pcfd.FlowField(flr)
pts = np.vstack(d["lines"])
_v, inside = ff.velocity(pts)
ok(bool(inside.all()), f"every point of every tracer line is inside the air mesh ({int(inside.sum())} of {len(inside)} points)")
ok(pts[:, 0].max() <= 98.0 + 0.5 + 1e-9 and np.isclose(min(l[0, 0] for l in d["lines"]), -18.0), "they start at x = -18 mm and stop by x = 98 mm")
body_box = cw.hosted["fluid"].win.tab.mesh["body_box"]
ok(not any((0.0 + 1e-6 < x < 20.0 - 1e-6) and (0.0 + 1e-6 < y < 20.0 - 1e-6) for x, y in pts), "and no line goes through the body")

# the dashed outline is the displacement of the stress analysis times the exaggeration
st_tab = cw.hosted["structural"].win.tab
disp = cm.Structural2D(st_tab).displacement_at
fs = V.frame_state(d, 120, 30.0)


def outline_error(state, ex):
    worst = 0.0
    for q, rest in zip(state["outline"], d["rest"]):
        U = np.asarray(disp(rest)[0], float)
        worst = max(worst, float(np.abs(q - (rest + ex * U)).max()))
    return worst


ok(outline_error(fs, 30.0) < 1e-9, f"the outline is the body moved by 30 times the displacement of the stress analysis ({outline_error(fs, 30.0):.2e})")
ok(outline_error(fs, 31.0) > 1e-3, "check shown to FAIL against a different exaggeration (a deliberately wrong answer)")
ok(float(np.abs(fs["outline"][0] - d["rest"][0]).max()) > 0.3, "and it is a visible movement on the picture: more than 0.3 mm of the 20 mm body")

# the picture
pg.view.resize(808, 520)
app.processEvents()
r = res["fluid"]["Q_fluid"]
im120 = pg.view.render_image(120, 1.0)
im1 = pg.view.render_image(1, 1.0)
im120b = pg.view.render_image(120, 1.0)
ok(im120 == im120b, "the same frame is drawn the same way twice")
ok(im120 != im1, "frame 1 and frame 120 are different pictures")
cn = lambda im: sum(1 for y in range(0, im.height(), 4) for x in range(0, im.width(), 4) if im.pixelColor(x, y).alpha() > 0 and im.pixelColor(x, y).red() + im.pixelColor(x, y).green() + im.pixelColor(x, y).blue() < 740)   # noqa: E731
ok(cn(im120) > 0.5 * (im120.width() // 4) * (im120.height() // 4), f"the picture is full of colour ({cn(im120)} of {(im120.width() // 4) * (im120.height() // 4)} sampled points)")
blank = NS(data=None, why=CV.EMPTY)
before = pg.layers.copy()
pg.layer_toggled("air_p", True)
im_p = pg.view.render_image(120, 1.0)
ok(pg.layers["air_p"] and not pg.layers["air_T"] and not pg.boxes["air_T"].isChecked() and pg.boxes["air_p"].isChecked(), "ticking the air pressure unticks the air temperature in the Outline")
ok(im_p != im120, "and the picture changes")
ok([b_[0] for b_ in V.colour_bars(d, pg.layers)] == ["Air pressure (Pa)", "Body displacement (mm)"], "with its own colour bar")
pg.layer_toggled("tracers", False)
im_nt = pg.view.render_image(120, 1.0)
ok(im_nt != im_p, "tracers off: the picture changes")
pg.layer_toggled("air_T", True)
pg.layer_toggled("tracers", True)
ok(pg.view.render_image(120, 1.0) == im120, "and back to the first picture with the first layers: nothing was changed by looking")

# the PNG is the still picture, at twice the size
path = pg.save_png(os.path.join(OUT, "still.png"))
back = QImage(path)
ok(path is not None and os.path.getsize(path) > 5000 and back.width() == 2 * 808 and back.height() == 2 * 520, f"Save image writes a PNG at twice the size ({back.width()} x {back.height()})")
st2 = pg.view.render_image(120, 2.0)
ok(pg.player.frame == 120 and back.convertToFormat(QImage.Format.Format_ARGB32) == st2.convertToFormat(QImage.Format.Format_ARGB32), "and it is the last frame, the same picture as drawn at that size")
ok(back.convertToFormat(QImage.Format.Format_ARGB32) != pg.view.render_image(1, 2.0).convertToFormat(QImage.Format.Format_ARGB32), "check shown to FAIL against frame 1 (a deliberately wrong answer)")

# playback drives the frame and the picture
pg.player.seek(36)
pg.slider_moved(36)
ok(pg.lbl_frame.text() == "Frame 36 of 120", f"the bar says which frame it is on ({pg.lbl_frame.text()})")
pg.toggle_play()
ok(pg.player.playing and pg.b_play.text() == "Pause", "Play starts the animation and the button says Pause")
pg.last_tick -= 0.5
pg.tick()
ok(pg.player.frame > 36, f"a tick moves the frame on ({pg.player.frame})")
pg.toggle_play()
ok(not pg.player.playing and pg.b_play.text() == "Play" and not pg.timer.isActive(), "Pause stops it")
pg.slider.setValue(120)

# the checks of the picture against the solve, the right way and the wrong way
rows = pg.self_check()
by = {x["name"]: x for x in rows}
ok(len(rows) == 4 and all(x["ok"] for x in rows), "the built-in checks of the picture all say PASS: " + "; ".join(f"{x['name']} {x['got']}" for x in rows))
ok(V.particle_gap(d, 120, 0) < 1e-9 and V.particle_gap(d, 110, 0) > 1e-3, f"every particle is back where it began after the last frame ({V.particle_gap(d, 120, 0):.2g}), and not ten frames before ({V.particle_gap(d, 110, 0):.3g})")
ok(abs(V.bend_reach(d) - umax) <= 0.005 * umax and V.bend_reach(d, k=1) < V.bend_reach(d, k=30) < V.bend_reach(d, k=120) + 1e-12, f"the bend of the outline reaches the displacement of the solve ({V.bend_reach(d):.5f} mm) and grows with the frame")
saved = [x.copy() for x in d["disp"]]
d["disp"] = [10.0 * x for x in saved]                                     # a picture that bends the body ten times too much
by = {x["name"]: x for x in pg.self_check()}
ok(not by["Bent outline within that displacement"]["ok"] and by["Displacement drawn"]["ok"], "a body drawn bent ten times too far is caught by its check (FAIL)")
d["disp"] = saved
old_u = bd["u_range"]
bd["u_range"] = (0.0, 2.0 * old_u[1])
by = {x["name"]: x for x in pg.self_check()}
ok(not by["Displacement drawn"]["ok"], "a colour range that is not the displacement of the solve is caught (FAIL)")
bd["u_range"] = old_u
old_T = a["T_range"]
a["T_range"] = (old_T[0] + 10.0, old_T[1])
by = {x["name"]: x for x in pg.self_check()}
ok(not by["Air temperature range"]["ok"], "an air temperature range that is not the heat exchange's is caught (FAIL)")
a["T_range"] = old_T
ok(all(x["ok"] for x in pg.self_check()), "and with the numbers put back everything says PASS again")
txt = cw.diagnostics_text()
ok("== The window ==" in txt and "== Viz ==" in txt and "PASS Displacement drawn" in txt and "FAIL" not in txt.split("== Viz ==")[1].split("==")[0], "the diagnostics report has the window and the checks of the picture")
ok("3D analyses keep their own tabs" in txt and "fluid: " in txt, "and says which analyses are in the window and which are not")

# the animation file
pg.view.resize(360, 232)
app.processEvents()
pg.player = V.Player(n=12)
pg.data["options"]["frames"] = 12
pg.slider.setRange(1, 12)
gif = os.path.join(OUT, "anim.gif")
out = pg.save_animation(path_fmt=(gif, "gif"))
ok(out == gif and os.path.getsize(gif) > 2000, f"Save animation writes a file ({out})")
try:
    from PIL import Image
    nf = Image.open(gif).n_frames
    ok(nf == 12, f"with every frame of the animation in it ({nf} frames)")
except ImportError:
    ok(True, "(the frames of the file were not counted: no PIL here)")

# nothing of the result changed
ok(cw.result is res and abs(cw.result["fsi"]["umax"] - umax) == 0.0 and cw.result["fluid"]["Q_fluid"] == r, "looking at the picture changed no result")
ok(cw.strip.marks().get("viz") in ("ok", "update"), "the Viz button has a mark")
cw.shutdown()

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
