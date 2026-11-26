"""The Viz tab of the Coupled Physics window for a 2D heat and stress solve with NO flow: the body coloured by its temperature, displacement or von Mises stress, the heat-flux tracers, the bent
outline.  Two parts.
(1) The numbers behind the tracers (coupled_viz_core, no Qt), on a bar whose heat flux is known (a uniform flux along x): the lines start along the edge where heat enters, evenly, and every one
stands for the same share of the heat that enters; they run straight with the flux and stop at the far edge; the 'time' along a line counts a stronger flux as faster (a flux four times as strong over
a third of the bar makes that third take a quarter of the time); a short line goes round more often than a long one so that the animation repeats without a jump; with no edge that heat enters
through (heat made inside) the lines start inside and go both ways; with no heat flowing there are no lines.
(2) The real 2D Thermal and 2D Static Structural windows of a 100 x 10 mm bar held at 100 degC at one end and 20 degC at the other, solved together in the Coupled Physics window: the picture is made,
the tracer lines are the straight lines of the 1D heat flow from the hot end to the cold end, the temperature runs 20 .. 100 degC, the body fields and the layers change the picture, the PNG is
the still picture at twice the size, the animation is written, the built-in checks say PASS and FAIL on deliberately wrong pictures, and nothing of the result changes.
Nothing here was looked at on a real screen.
python test_coupled_viz_heat.py"""
import faulthandler
faulthandler.dump_traceback_later(900, exit=True)
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
OUT = tempfile.mkdtemp(prefix="opara_vizheat_")
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "thermal3d"),
                os.path.join(HERE, "dev_addons", "coupled"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

import sketcher_core as sc
import sim_tab
import unitctl
import physics_tab
import thermal_tab as tt
import thermal_flow as tf
import coupled_tab as ctab
import coupled_viz as CV
import coupled_viz_core as V

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text, flush=True)
    if not cond:
        FAILS.append(text)


# ------------------------------------------------------------------------------------------------------------------------------ 1. the numbers (no Qt)
def bar_mesh(nx=20, ny=4, w=100.0, h=10.0):
    xs, ys = np.linspace(0, w, nx + 1), np.linspace(0, h, ny + 1)
    X, Y = np.meshgrid(xs, ys)
    nodes = np.column_stack([X.ravel(), Y.ravel()])
    idx = lambda i, j: j * (nx + 1) + i                                             # noqa: E731
    tris = []
    for j in range(ny):
        for i in range(nx):
            a, b, c, d = idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)
            tris += [[a, b, c], [a, c, d]]
    return nodes, np.array(tris)


nodes, tris = bar_mesh()
cen = nodes[tris].mean(axis=1)
Q0 = 50.0
fld = tf.FluxField(nodes, tris)
fld.set_flux(np.full(len(tris), Q0), np.zeros(len(tris)))
ok(abs(fld._inlet_w.sum() - Q0 * 10.0) < 1e-9, f"the heat entering the bar is the flux times the height of the hot edge ({fld._inlet_w.sum():g} = {Q0 * 10.0:g})")
seeds = fld.inlet_seeds(40)
ok(seeds.shape == (40, 2) and np.allclose(seeds[:, 0], seeds[0, 0]) and seeds[0, 0] < 1.0, "40 seeds, all on the hot edge (a little way in)")
ys = np.sort(seeds[:, 1])
ok(np.abs(np.diff(ys) - 10.0 / 40.0).max() < 0.06 and abs(ys[0] - 0.125) < 0.1 and abs(ys[-1] - 9.875) < 0.1,
   f"evenly spaced along it, 10 / 40 = 0.25 mm apart (the gaps are {np.diff(ys).min():.3f} .. {np.diff(ys).max():.3f}: each is moved a little way in, into its own triangle): every seed stands for the same share of the heat")
ok(np.array_equal(seeds, fld.inlet_seeds(40)), "and the same every time")
ok(fld.inlet_seeds(0) is None, "no seeds for no lines")
cold = tf.FluxField(nodes, tris)
cold.set_flux(np.zeros(len(tris)), np.zeros(len(tris)), qref=0.0)
ok(cold.inlet_seeds(10) is None, "and none where no heat flows")

lines, how = V.heat_lines(fld, 40)
ok(how == "edges" and len(lines) == 40, f"40 lines, starting at the edge where heat enters ({how})")
ok(all(np.allclose(l[:, 1], l[0, 1], atol=1e-9) for l in lines), "in a uniform flux along x every line is straight and keeps its height")
ok(all(l[0, 0] < 1.0 and l[-1, 0] > 99.0 for l in lines), "and runs the whole length of the bar, from the hot end to the cold end")
ok(max(l[:, 0].max() for l in lines) <= 100.0 and min(l[:, 0].min() for l in lines) >= 0.0, "with no point outside the bar")
lines8, _h = V.heat_lines(fld, 8)
ok(len(lines8) == 8, "another number of lines is made as asked")
cums = [V.time_coordinate(l, V.heat_ratio(fld, l)) for l in lines]
arc = [float(V.arc_lengths(l)[-1]) for l in lines]
ok(all(abs(c[-1] - a) < 1e-6 * a for c, a in zip(cums, arc)), "in a flux that is the strong one everywhere (ratio 1) the time along a line is its length")
ok(V.laps_for([c[-1] for c in cums]) == [1] * 40, "so every line is gone round once")

# a flux four times as strong over the middle third: the middle third takes a quarter of the time
strong = np.where((cen[:, 0] > 33.4) & (cen[:, 0] < 66.6), 4 * Q0, Q0)
fld.set_flux(strong, np.zeros(len(tris)), qref=Q0)
L2, _h = V.heat_lines(fld, 8)
c2 = V.time_coordinate(L2[0], V.heat_ratio(fld, L2[0]))
a2 = float(V.arc_lengths(L2[0])[-1])
mid_arc = float(np.sum(np.hypot(*np.diff(L2[0][(L2[0][:, 0] > 33.4) & (L2[0][:, 0] < 66.6)], axis=0).T)))
expect = a2 - mid_arc + mid_arc / 4.0
ok(abs(c2[-1] - expect) < 0.04 * expect, f"a flux four times as strong over the middle third makes it take a quarter of the time: {c2[-1]:.2f} against {expect:.2f} (line {a2:.2f} long)")
ok(c2[-1] < 0.9 * a2, "so the time along the line is shorter than its length")
r_slow = V.heat_ratio(fld, L2[0][:3])
ok(np.allclose(r_slow, 1.0), "where the flux is the strong one the ratio is 1")
fld.set_flux(strong * 1e-3, np.zeros(len(tris)), qref=Q0)
ok(np.allclose(V.heat_ratio(fld, L2[0][:5]), V.HEAT_DEFAULTS["ratio_min"]), "a very weak flux is held at the smallest ratio (0.1): a particle never stops")
fld.set_flux(strong * 100, np.zeros(len(tris)), qref=Q0)
ok(np.allclose(V.heat_ratio(fld, L2[0][:5]), V.HEAT_RATIO_MAX) and V.HEAT_RATIO_MAX == tf.MAX_RATIO, f"and a very strong one at the largest (the Thermal tab's {tf.MAX_RATIO:g})")
ok(V.heat_ratio(fld, np.array([[500.0, 500.0]]))[0] == 0.0, "outside the bar there is no ratio")

# laps
ok(V.laps_for([100.0, 50.0, 34.0, 10.0, 0.0]) == [1, 2, 3, 8, 1], f"a line half as long in time is gone round twice, a third as long three times, at most 8 ({V.laps_for([100.0, 50.0, 34.0, 10.0, 0.0])})")
data = {"options": dict(V.DEFAULTS), "lines": lines, "cum": cums, "length": [float(c[-1]) for c in cums], "starts": V.particle_starts([float(c[-1]) for c in cums]), "length_per_unit": 1.0,
        "rest": [np.array([[0.0, 0.0], [20.0, 0.0]])], "disp": [np.zeros((2, 2))], "laps": [1 + (i % 3) for i in range(40)]}
f0, f120 = V.frame_state(data, 0), V.frame_state(data, 120)
ok(np.allclose(np.array(f0["particles"]), np.array(f120["particles"]), atol=1e-9), "with whole numbers of laps every particle is back where it began at the last frame")
data["laps"] = [1.5] * 40
ok(not np.allclose(np.array(V.frame_state(data, 0)["particles"]), np.array(V.frame_state(data, 120)["particles"]), atol=1e-6), "check shown to FAIL with half a lap (a deliberately wrong answer)")
data["laps"] = [1] * 40
mid = np.array(V.frame_state(data, 30)["particles"])
ok(not np.allclose(mid, np.array(f0["particles"])), "in between they are somewhere else")
data["laps"] = [2] * 40
ok(not np.allclose(np.array(V.frame_state(data, 30)["particles"]), mid), "and with two laps they go round twice as fast")

# heat made inside: no edge has heat entering, the lines start inside and go both ways
out = cen - np.array([50.0, 5.0])
nn = np.hypot(out[:, 0], out[:, 1])
fld.set_flux(out[:, 0] / nn, out[:, 1] / nn)
ok(fld.inlet_seeds(10) is None, "heat made inside the bar: no edge has heat entering")
li, how_i = V.heat_lines(fld, 10)
ok(how_i == "inside" and len(li) >= 8, f"the lines then start inside ({how_i}, {len(li)} lines)")
ok(all(np.hypot(*(l[0] - np.array([50.0, 5.0]))) < np.hypot(*(l[-1] - np.array([50.0, 5.0]))) for l in li), "and run from the middle outwards: they go both ways from where they start")
ok(V.heat_lines(cold, 10) == ([], "inside"), "with no heat flowing there are no lines at all")

# the strong flux of a result, with the guard for a temperature that is the same everywhere
q = np.concatenate([np.full(95, 10.0), np.full(5, 100.0)])
ok(abs(V.reference_heat_flux(q, 20.0, 100.0) - tf.reference_flux(q)) < 1e-12, "the strong flux is the Thermal tab's (the 95th percentile)")
ok(V.reference_heat_flux(q, 300.0, 300.0 + 1e-9) == 0.0 and V.reference_heat_flux(np.zeros(5), 20.0, 100.0) == 0.0 and V.reference_heat_flux([], 0.0, 1.0) == 0.0,
   "a temperature that is the same everywhere (or no flux at all) is no heat flow")

# the layers of the heat picture
lh = V.LAYERS_HEAT_ON
l1 = V.set_layer(lh, "body_u", True)
ok(l1["body_u"] and not l1["body_T"] and l1["tracers"] and l1["bent"], "the displacement switches the temperature off (the body shows one field), tracers and outline stay")
l2 = V.set_layer(l1, "body_vm", True)
ok(l2["body_vm"] and not l2["body_u"] and not l2["body_T"], "and so does the von Mises stress")
ok(V.set_layer(l2, "body_T", True)["body_T"] and not V.set_layer(l2, "body_T", True)["body_vm"], "the temperature switches them off again")
ok("air_T" not in l1, "no air layer is added to the heat layers")
fl = V.set_layer(V.LAYERS_ON, "air_p", True)
ok(fl["air_p"] and not fl["air_T"] and fl["body_u"] and "body_T" not in fl, "the layers of a flow are as they were")

# ------------------------------------------------------------------------------------------------------------------------------ 2. the real windows
unitctl.set_units("Metric (mm, kg, N, s, MPa)", notify=False, persist=False)
K0 = 273.15


def host():
    h = sim_tab.SimHost.__new__(sim_tab.SimHost)
    h.doc = None
    h.m = sim_tab._HostModel()
    h._restoring = False
    h.status = lambda t: None
    h.sim = None
    h.sketch_list = lambda: []
    return h


def run_now(tab, title, fn):
    try:
        return "ok", fn(lambda *a, **k: None, lambda: False)
    except (tt.pg.Cancelled, tt.pf.Cancelled):
        return "cancelled", None
    except (tt.pg.GeometryError, tt.pf.ModelError) as ex:
        QMessageBox.warning(tab, title, str(ex))
        return "user", str(ex)


def answer(*vals):
    def f(parent, title, note, labels, defaults):
        return list(vals)
    tt.ask_values = f


def pick(t, fn, sel, *vals):
    t.canvas.sel = list(sel)
    answer(*vals)
    getattr(t, fn)()


m = sc.Model()
p = [m.add_point(*c) for c in ((0, 0), (100.0, 0), (100.0, 10.0), (0, 10.0))]
ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
th = tt.ThermalTab(host())
th.run_task = lambda title, fn: run_now(th, title, fn)
th.set_model(m, "bar")
pick(th, "add_temperature", [("ln", ls[3])], 100.0)
pick(th, "add_temperature", [("ln", ls[1])], 20.0)
th.e_h.setText("2")
fe = physics_tab.PhysicsTab(host())
fe.run_task = lambda title, fn: run_now(fe, title, fn)
fe.set_model(m, "bar")
fe.canvas.sel = [("ln", ls[3])]
fe.add_support("x")
fe.canvas.sel = [("pt", p[0])]
fe.add_support("y")
fe.e_alpha.setText("1.2e-5")
fe.e_tref.setText("20")
fe.e_h.setText("2")
fe.cb_auto.setChecked(False)

wc = ctab.make_coupled(None)
wc.members_source = lambda: {"windows": {"thermal": th, "fea": fe}, "labels": {"thermal": "Bar heating (2D)", "structural": "Bar growth (2D)"}, "show": {}, "problem": None, "note": ""}
wc.refresh()
pg = wc.viz
pg.refresh()
ok(pg.message() == CV.EMPTY and pg.data is None, "before the first solve the picture says there is no solve yet")
ok(wc.solve() is True and wc.result["ok"] and wc.result["dim"] == 2 and not wc.result.get("fluid"), "the 2D heat and stress solve with no flow runs")
res = wc.result
ok(pg.message() is None and pg.mode == "heat2d", f"and the Viz tab now has a picture to make (mode {pg.mode}); it used to say it was made for a flow")
ok(pg.ensure() and pg.data is not None and pg.data["kind"] == "heat2d", "the picture has its data")
d = pg.data
tr = d["thermal"]
ok(abs(tr["T_range"][0] - 20.0) < 0.01 and abs(tr["T_range"][1] - 100.0) < 0.01, f"the temperature runs 20 .. 100 degC ({tr['T_range'][0]:.3f} .. {tr['T_range'][1]:.3f})")
ok(d["heat"]["how"] == "edges" and len(d["lines"]) == 40, f"40 tracer lines, from the edge where the heat enters ({len(d['lines'])})")
ok(all(abs(l[0, 0]) < 1.5 and l[-1, 0] > 98.0 for l in d["lines"]), "they start at the hot end (x = 0) and reach the cold end (x = 100 mm)")
ok(all(np.ptp(l[:, 1]) < 0.05 for l in d["lines"]), "and are straight: the heat flows along the bar (1D)")
ys_ = np.sort([l[0, 1] for l in d["lines"]])
ok(abs(ys_[0] - 0.125) < 0.1 and abs(ys_[-1] - 9.875) < 0.1 and np.abs(np.diff(ys_) - 0.25).max() < 0.06, f"at evenly spaced heights over the 10 mm edge ({ys_[0]:.3f} .. {ys_[-1]:.3f})")
Tf = np.interp([l[0, 0] for l in d["lines"]], np.linspace(0, 100, 11), np.linspace(100, 20, 11))
Tl = np.interp([l[-1, 0] for l in d["lines"]], np.linspace(0, 100, 11), np.linspace(100, 20, 11))
ok(bool((Tf > Tl).all()) and abs(Tf.mean() - 100.0) < 1.5 and abs(Tl.mean() - 20.0) < 1.5, f"every line runs from about 100 degC down to about 20 degC ({Tf.mean():.1f} -> {Tl.mean():.1f})")
ok(d["laps"] == [1] * 40, "all the lines are equally long in time here, so each is gone round once")
ok(d["body"] is not None and abs(d["body"]["u_range"][1] - res["structural"]["umax"]) < 0.01 * res["structural"]["umax"] and abs(res["structural"]["umax"] - 0.048) < 0.003,
   f"the body's largest displacement is the one of the stress result ({d['body']['u_range'][1]:.5f} mm, the bar grows 100 mm x 1.2e-5 x 40 K = 0.048)")
ok(d["window"][0] < 0 < 100 < d["window"][1] and d["window"][2] < 0 < 10 < d["window"][3], "the window shows the whole bar with a margin")
ok(d["body"]["vm_unit"] == "MPa" and [b_[0] for b_ in V.colour_bars(d, pg.active_layers())] == ["Temperature (°C)"], "one colour bar: the temperature (the body shows one field at a time)")

# the picture
pg.view.resize(808, 520)
app.processEvents()
im120 = pg.view.render_image(120, 1.0)
im1 = pg.view.render_image(1, 1.0)
ok(im120 == pg.view.render_image(120, 1.0), "the same frame is drawn the same way twice")
ok(im120 != im1, "frame 1 and frame 120 are different pictures")
cn = lambda im: sum(1 for y in range(0, im.height(), 4) for x in range(0, im.width(), 4) if im.pixelColor(x, y).alpha() > 0 and im.pixelColor(x, y).red() + im.pixelColor(x, y).green() + im.pixelColor(x, y).blue() < 740)   # noqa: E731
ok(cn(im120) > 0.03 * (im120.width() // 4) * (im120.height() // 4), f"the picture has colour in it ({cn(im120)} of {(im120.width() // 4) * (im120.height() // 4)} sampled points)")
# the body is hot on the left and cold on the right
w_, h_ = im120.width(), im120.height()
fit = V.Fit(d["window"], int(w_ * (1.0 - CV.BAR_FRAC)), h_)
xL, yL = fit.px((6.0, 1.0))
xR, yR = fit.px((94.0, 1.0))
cL, cR = im120.pixelColor(int(xL), int(yL)), im120.pixelColor(int(xR), int(yR))
lum = lambda c: 0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue()                  # noqa: E731
ok(lum(cL) > lum(cR) + 40, f"the hot end is brighter than the cold end in the inferno colours (luminance {lum(cL):.0f} against {lum(cR):.0f})")

pg.layer_toggled("body_u", True)
ok(pg.layers_heat["body_u"] and not pg.layers_heat["body_T"] and not pg.boxes_heat["body_T"].isChecked() and pg.boxes_heat["body_u"].isChecked(), "ticking the displacement unticks the temperature in the Outline")
im_u = pg.view.render_image(120, 1.0)
ok(im_u != im120 and [b_[0] for b_ in V.colour_bars(d, pg.active_layers())] == ["Body displacement (mm)"], "the picture changes and has the displacement bar")
pg.layer_toggled("body_vm", True)
im_vm = pg.view.render_image(120, 1.0)
ok(im_vm != im_u and [b_[0] for b_ in V.colour_bars(d, pg.active_layers())] == ["Von Mises stress (MPa)"], "the von Mises stress is another picture, with its own bar")
pg.layer_toggled("tracers", False)
im_nt = pg.view.render_image(120, 1.0)
ok(im_nt != im_vm, "tracers off: the picture changes")
pg.layer_toggled("bent", False)
ok(pg.view.render_image(120, 1.0) != im_nt, "and so does the bent outline")
pg.layer_toggled("body_T", True)
pg.layer_toggled("tracers", True)
pg.layer_toggled("bent", True)
ok(pg.view.render_image(120, 1.0) == im120, "and back to the first picture with the first layers: nothing was changed by looking")
ok(pg.layers == V.LAYERS_ON, "the layers of the flow picture were not touched")

# the tracer controls
wc.role = "viz"                                                                     # (the window shows this tab: a change of the tracers makes the picture again at once)
pg.e_hlines.setValue(12)
ok(pg.opts_heat["lines"] == 12 and len(pg.data["lines"]) == 12, f"12 lines asked for: the picture is made again with 12 ({len(pg.data['lines'])})")
pg.e_hper.setValue(2)
ok(len(V.frame_state(pg.data, 120)["particles"]) == 24, "two particles on each line: 24 particles")
long_trail = float(np.ptp(np.array(V.frame_state(pg.data, 50)["tails"][0]), axis=0).max())
pg.e_htrail.setValue(40.0)
ok(abs(pg.data["options"]["trail"] - 0.4 * pg.data["heat"]["period"]) < 1e-9 and float(np.ptp(np.array(V.frame_state(pg.data, 50)["tails"][0]), axis=0).max()) > long_trail,
   "a longer trail (40 % of the longest line) is a longer tail")
pg.e_htrail.setValue(12.0)
pg.e_hper.setValue(3)
pg.e_hlines.setValue(40)
d = pg.data
tr = d["thermal"]
ok(len(d["lines"]) == 40 and pg.view.render_image(120, 1.0) == im120, "put back, it is the first picture again")

# the PNG is the still picture at twice the size
path = pg.save_png(os.path.join(OUT, "heat_still.png"))
back = QImage(path)
ok(path is not None and os.path.getsize(path) > 5000 and back.width() == 2 * 808 and back.height() == 2 * 520, f"Save image writes a PNG at twice the size ({back.width()} x {back.height()})")
ok(pg.player.frame == 120 and back.convertToFormat(QImage.Format.Format_ARGB32) == pg.view.render_image(120, 2.0).convertToFormat(QImage.Format.Format_ARGB32), "and it is the last frame, the same picture as drawn at that size")

# the checks of the picture against the solve, the right way and the wrong way
rows = pg.self_check()
by = {x["name"]: x for x in rows}
ok(len(rows) == 6 and all(x["ok"] for x in rows), "the built-in checks of the picture all say PASS: " + "; ".join(f"{x['name']} {x['got']}" for x in rows))
ok(V.particle_gap(d, 120, 0) < 1e-9 and V.particle_gap(d, 110, 0) > 1e-3, "every particle is back where it began after the last frame, and not ten frames before")
saved_lines, saved_c = d["lines"], d["cum"]
d["lines"] = [l[::-1] for l in saved_lines]                                         # the tracers drawn the wrong way round: from the cold end to the hot end
by = {x["name"]: x for x in pg.self_check()}
ok(not by["Tracer lines run from hot to cold"]["ok"] and by["Tracer lines inside the body"]["ok"], "lines that run from cold to hot are caught by their check (FAIL)")
d["lines"] = [l + np.array([0.0, 500.0]) for l in saved_lines]
by = {x["name"]: x for x in pg.self_check()}
ok(not by["Tracer lines inside the body"]["ok"], "lines that leave the body are caught (FAIL)")
d["lines"] = saved_lines
old_u = d["body"]["u_range"]
d["body"]["u_range"] = (0.0, 2.0 * old_u[1])
by = {x["name"]: x for x in pg.self_check()}
ok(not by["Displacement drawn"]["ok"], "a colour range that is not the displacement of the solve is caught (FAIL)")
d["body"]["u_range"] = old_u
old_T = tr["T_range"]
tr["T_range"] = (old_T[0] + 10.0, old_T[1])
by = {x["name"]: x for x in pg.self_check()}
ok(not by["Temperature range"]["ok"], "a temperature range that is not the heat analysis's is caught (FAIL)")
tr["T_range"] = old_T
saved = [x.copy() for x in d["disp"]]
d["disp"] = [10.0 * x for x in saved]
by = {x["name"]: x for x in pg.self_check()}
ok(not by["Bent outline within that displacement"]["ok"], "a body drawn bent ten times too far is caught (FAIL)")
d["disp"] = saved
ok(all(x["ok"] for x in pg.self_check()), "and with the numbers put back everything says PASS again")
txt = wc.diagnostics_text()
ok("== Viz ==" in txt and "PASS Tracer lines run from hot to cold" in txt and "FAIL" not in txt.split("== Viz ==")[1].split("==")[0], "the diagnostics report holds the checks of the picture")

# the animation file
pg.view.resize(360, 232)
app.processEvents()
pg.player = V.Player(n=12)
pg.data["options"]["frames"] = 12
pg.slider.setRange(1, 12)
gif = os.path.join(OUT, "heat_anim.gif")
outp = pg.save_animation(path_fmt=(gif, "gif"))
ok(outp == gif and os.path.getsize(gif) > 2000, f"Save animation writes a file ({outp})")

# nothing of the result changed
ok(wc.result is res and abs(wc.result["thermal"]["T_max"] - (100.0 + K0)) < 1e-6, "looking at the picture changed no result")

# the stress result going away, and a solve with no heat flowing
th.result = None
pg.refresh()
ok(pg.message() == CV.NO_HEAT and pg.data is None, "when the heat result is not there any more the tab says to solve again")

print("pictures in", OUT)
print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
