"""The heat-flux tracers of the 3D picture of the Viz tab of the Coupled Physics window, on stand-in results: a 100 x 20 x 20 mm bar of tetrahedra whose heat flux is known (a uniform flux along x, hot
at x = 0, 100 degC to 20 degC).  (1) The page: the tracers are made from the heat result (40 lines from the face where heat enters, straight along the bar, every one the same share of the heat
that enters), the part is drawn faded while they are on, the layer box and the three controls (lines, particles, trail) do what they say and rebuild the tracers only, not the part.  (2) The animation:
the particles are back where they began in the last frame (it repeats without a jump), the lines are carried with the bend and never further than the displacement of the part, a PNG at twice the size
and a GIF are written.  (3) The checks of the picture: three about the tracers say PASS, and each says FAIL on a deliberately wrong picture.  (4) A heat result that is the same everywhere (no
heat flows), a heat that is made inside the part (lines start inside), a heat result with no flux in it (no tracers, as before) and a flux field that cannot be made.
Nothing here was looked at on a real screen.
python test_coupled_viz3d_tracers.py"""
import faulthandler
faulthandler.dump_traceback_later(900, exit=True)
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
OUT = tempfile.mkdtemp(prefix="opara_viz3t_")
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "coupled"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "thermal3d"),
                os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "shared")]
from types import SimpleNamespace as NS

import numpy as np
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import coupled_viz as CV
import coupled_viz3d_core as C3
import coupled_viz_core as V

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text, flush=True)
    if not cond:
        FAILS.append(text)


# ------------------------------------------------------------------------------------------------------------------------------ stand-in results: a bar of tetrahedra
def box_tets(nx, ny, nz, size=(100.0, 20.0, 20.0)):
    xs, ys, zs = (np.linspace(0, size[i], n + 1) for i, n in enumerate((nx, ny, nz)))
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    nodes = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    idx = lambda i, j, k: (i * (ny + 1) + j) * (nz + 1) + k                        # noqa: E731
    tets = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                for pm in ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)):      # six tetrahedra along the diagonal of each cube
                    p, chain = [0, 0, 0], [(0, 0, 0)]
                    for ax in pm:
                        p[ax] = 1
                        chain.append(tuple(p))
                    tets.append([idx(i + a, j + b, k + c) for a, b, c in chain])
    return nodes, np.array(tets, np.int64)


def boundary_triangles(tets):
    corners = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))
    F = np.concatenate([tets[:, c] for c in corners])
    key = np.sort(F, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return F[cnt[inv.reshape(-1)] == 1].astype(np.int32)


nodes, tets = box_tets(10, 2, 2)
tris = boundary_triangles(tets)
surface = {1: tris}
u = np.zeros((len(nodes), 3))
u[:, 2] = 0.002 * nodes[:, 0]                                                           # the far end moves up by 0.2 mm
vm = nodes[:, 0] * 3.0
K0 = 273.15
T_hot, T_cold = 100.0 + K0, 20.0 + K0
Tn = T_hot - (T_hot - T_cold) * nodes[:, 0] / 100.0
Q = 50.0                                                                                 # W/m2 along +x: from the hot end (x = 0) to the cold one


def heat_result(q=None, T=None, **extra):
    q = np.tile([Q, 0.0, 0.0], (len(tets), 1)) if q is None else q
    T = Tn if T is None else T
    r = {"nodes": nodes, "conn": tets, "q": q, "qmag": np.linalg.norm(q, axis=1), "T": T, "Tmin": float(T.min()), "Tmax": float(T.max()), "lscale": 1e-3, "mesh": {"ftri": surface}}
    r.update(extra)
    return r


solid = NS(result={"nodes": nodes, "surface": surface, "u": u, "un": np.linalg.norm(u, axis=1), "vm_node": vm, "umax": 0.2, "vm_max": float(vm.max())})
thermal = NS(result=heat_result())
solve = {"dim": 3, "ok": True, "fluid": None, "thermal": {}, "structural": {}}
fake = NS(result=solve, hosted={}, role="viz", say=lambda t: None, src={"windows": lambda: {"solid": solid, "thermal3d": thermal}})

pg = CV.VizPage(fake)
pg.view.resize(700, 460)
pg.refresh()
app.processEvents()
d = pg.data
tr = d["tracers"]
ok(pg.message() is None and pg.mode == "body3d" and tr is not None and d["field3"] is not None, "a 3D solve whose heat result holds the heat flux: the picture has tracers")
ok(len(tr["lines"]) == 40 and tr["heat"]["how"] == "edges" and pg.tracers3_shown(), f"40 lines, from the face where heat enters ({tr['heat']['how']})")
x0 = np.array([ln[0, 0] for ln in tr["lines"]])
x1 = np.array([ln[-1, 0] for ln in tr["lines"]])
ok(x0.max() < 3.0 and x1.min() > 97.0, f"they start at the hot end and run to the cold one (starts at most {x0.max():.2f} mm, ends at least {x1.min():.2f} mm)")
ok(max(float(np.ptp(ln[:, 1])) for ln in tr["lines"]) < 1e-6 and max(float(np.ptp(ln[:, 2])) for ln in tr["lines"]) < 1e-6, "straight along x, where the heat goes")
yz = np.array([ln[0, 1:] for ln in tr["lines"]])
quad = np.histogram2d(yz[:, 0], yz[:, 1], bins=2, range=[[0, 20], [0, 20]])[0].ravel()
ok(quad.min() >= 6 and quad.max() <= 14, f"spread over the end face, each line the same share of the heat ({quad.astype(int).tolist()} lines in its four quarters)")
ok(abs(tr["heat"]["qref"] - Q) < 1e-9 and tr["heat"]["wanted"] == 40, "the strong flux is the 50 W/m2 of the result")

# the panel
ok(not pg.grp_trace_heat.isHidden() and pg.grp_trace2d.isHidden() and not pg.lbl_trace3.isHidden(), "the Tracers part of the panel shows the heat-flux controls, not the 2D flow ones")
ok("faded" in pg.lbl_trace3.text() and "no flow" not in pg.lbl_trace3.text(), f"and says that the part is drawn faded ({pg.lbl_trace3.text()[:60]}...)")
ok(pg.boxes3["tracers"].isEnabled() and pg.boxes3["tracers"].isChecked() and pg.e_hlines.isEnabled() and pg.e_hper.isEnabled() and pg.e_htrail.isEnabled(), "the Heat-flux tracers box and the three controls are on")
ok("Tracers: the heat flux of the last heat solve, 40 lines" in pg.notes.text(), f"the picture says what the tracers are ({pg.notes.text()})")


def ink(img):
    a = np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint8).reshape(img.height(), img.width(), 4)
    return a[:, :int(img.width() * 0.78), :]


def ink_region(img):
    return ink(img).astype(int)


# the picture: faded part, the lines on it
on = ink_region(pg.view.render_image(120, 1.0))
pg.layers3["tracers"] = False
pg.boxes3["tracers"].setChecked(False)
ok(not pg.tracers3_shown(), "the box takes the tracers away")
off = ink_region(pg.view.render_image(120, 1.0))
pg.boxes3["tracers"].setChecked(True)
ok(pg.layers3["tracers"] and pg.tracers3_shown() and np.array_equal(on, ink_region(pg.view.render_image(120, 1.0))), "and back: the same picture as before")
ok(not np.array_equal(on, off), "the picture with the tracers is not the picture without them")
pg.e_hlines.setValue(3)                                                                  # three lines: nearly all of the change from the 40 is the lines and their particles
app.processEvents()
on3 = ink_region(pg.view.render_image(120, 1.0))
many = int((np.abs(on - on3).max(axis=2) > 25).sum())
ok(many > 300, f"the lines are in the picture: {many} pixels differ between 40 lines and 3")
covered = (off[..., :3].min(axis=2) < 235)
ok(on3[covered][..., :3].mean() > off[covered][..., :3].mean() + 3.0, f"with the tracers on the surface is drawn faded (mean brightness {off[covered][..., :3].mean():.0f} -> {on3[covered][..., :3].mean():.0f})")
pg.e_hlines.setValue(40)
app.processEvents()

# the controls: the tracers are made again, the part is not
X_before, tris_before = d["X"], d["tris"]
pg.e_hlines.setValue(12)
app.processEvents()
ok(pg.data is d and d["X"] is X_before and d["tris"] is tris_before and len(d["tracers"]["lines"]) == 12, "12 lines asked for: 12 lines, and the part was not made again")
pg.e_hper.setValue(2)
app.processEvents()
st = C3.tracer_state(d["tracers"], 60, pg.exaggeration3(), d["options"]["frames"])
ok(len(d["tracers"]["lines"]) == 12 and len(st["particles"]) == 24 and len(st["tails"]) == 24, f"2 particles on each line: {len(st['particles'])} particles with a trail each")
period = d["tracers"]["heat"]["period"]
trail_before = d["tracers"]["options"]["trail"]
pg.e_htrail.setValue(30.0)
app.processEvents()
ok(abs(d["tracers"]["options"]["trail"] - 0.30 * period) < 1e-9 and d["tracers"]["options"]["trail"] > trail_before, "the trail length is a share of the longest line, and 30 % is longer than 12 %")
ok(pg.opts_heat["lines"] == 12 and pg.opts_heat["per_line"] == 2, "the page keeps what was asked for, for the next solve")
pg.e_hlines.setValue(40)
pg.e_hper.setValue(3)
pg.e_htrail.setValue(12.0)
app.processEvents()

# ------------------------------------------------------------------------------------------------------------------------------ the animation
tr = d["tracers"]
ex = pg.exaggeration3()
gap = C3.tracer_gap(tr, d["options"]["frames"], 0, ex, d["options"]["frames"])
ok(gap < 1e-9, f"the last frame has every particle where the first has it: the animation repeats without a jump ({gap:.2g} mm)")
s1 = C3.tracer_state(tr, 1, ex, d["options"]["frames"])
s30 = C3.tracer_state(tr, 30, ex, d["options"]["frames"])
s60 = C3.tracer_state(tr, 60, ex, d["options"]["frames"])
s120 = C3.tracer_state(tr, 120, ex, d["options"]["frames"])
moved = max(float(np.abs(a - b).max()) for a, b in zip(s1["lines"], s120["lines"]))
ok(0.0 < moved <= 0.2 * ex * (1 + 1e-6) and max(float(np.abs(a - b).max()) for a, b in zip(s1["lines"], s30["lines"])) < moved, f"the lines are carried with the bend, never further than the part ({moved:.3g} mm at x{ex:g}; the part's own is {0.2 * ex:.3g})")
ok(not np.allclose(s1["particles"], s60["particles"]), "and the particles move between the frames")
ok(len(set(tr["laps"])) >= 1 and all(1 <= lp <= V.HEAT_DEFAULTS["max_laps"] for lp in tr["laps"]), f"every line is gone along a whole number of times ({sorted(set(tr['laps']))})")
a1 = ink_region(pg.view.render_image(1, 1.0))
a60 = ink_region(pg.view.render_image(60, 1.0))
ok(not np.array_equal(a1, a60), "the frames differ (the bend, the particles)")
png = pg.save_png(os.path.join(OUT, "tracers3.png"))
ok(png and QImage(png).width() == 2 * pg.view.width(), "the PNG is written at twice the size of the picture")
pg.slider.setRange(1, 12)
gif = os.path.join(OUT, "tracers3.gif")
out = pg.save_animation(path_fmt=(gif, "gif"))
ok(out == gif and os.path.getsize(gif) > 3000, f"Save animation writes a file ({out})")
pg.slider.setRange(1, pg.player.n)

# ------------------------------------------------------------------------------------------------------------------------------ the checks of the picture
rows = pg.self_check()
names = [r["name"] for r in rows]
ok(len(rows) == 8 and all(r["ok"] for r in rows), "eight checks, all PASS: " + "; ".join(f"{r['name']} {r['got']}" for r in rows))
ok(names[-3:] == ["Tracer lines inside the part", "Tracer lines run from hot to cold", "Tracer lines bend within the displacement of the part"], "the last three are about the tracers")

keep_line = tr["lines"][0].copy()
tr["lines"][0] = keep_line + np.array([500.0, 0.0, 0.0])
bad = {r["name"]: r for r in pg.self_check()}
ok(not bad["Tracer lines inside the part"]["ok"], f"a line that lies outside the part FAILS the first ({bad['Tracer lines inside the part']['got']})")
tr["lines"][0] = keep_line
T_keep = thermal.result["T"]
thermal.result["T"] = (T_hot + T_cold) - T_keep                                           # a result in which the heat would flow uphill
bad = {r["name"]: r for r in pg.self_check()}
ok(not bad["Tracer lines run from hot to cold"]["ok"], f"a line that ends hotter than it starts FAILS the second ({bad['Tracer lines run from hot to cold']['got']})")
thermal.result["T"] = T_keep
disp_keep = tr["disp"][0].copy()
tr["disp"][0] = disp_keep * 50.0
bad = {r["name"]: r for r in pg.self_check()}
ok(not bad["Tracer lines bend within the displacement of the part"]["ok"], f"a line bent further than the part FAILS the third ({bad['Tracer lines bend within the displacement of the part']['got']})")
tr["disp"][0] = disp_keep
ok(all(r["ok"] for r in pg.self_check()), "and with the numbers put back every check says PASS again")
txt = "\n".join(f"{'PASS' if r['ok'] else 'FAIL'} {r['name']}" for r in pg.self_check())
ok("PASS Tracer lines inside the part" in txt, "the report lists them")

# ------------------------------------------------------------------------------------------------------------------------------ other results
def fresh(result_for_heat, fluid=None):
    thermal.result = result_for_heat
    fake.result = dict(solve, fluid=fluid)
    pg.stale = True
    pg.refresh()
    pg.ensure()
    app.processEvents()


fresh(heat_result(q=np.zeros((len(tets), 3)), T=np.full(len(nodes), 300.0)))
ok(pg.mode == "body3d" and pg.data["field3"] is not None and pg.data["tracers"] is not None and not pg.data["tracers"]["lines"], "a heat result with no heat flowing: the part is drawn, with no tracer lines")
ok(not pg.boxes3["tracers"].isEnabled() and not pg.tracers3_shown() and CV.NO_FLUX in pg.notes.text(), f"the box is off and the picture says so ({pg.notes.text()})")
ok(pg.self_check_tracers3() == [], "and there are no tracer checks to make")
pg.view.render_image(120, 1.0)                                                          # (it draws)

out_q = np.array([c - np.array([50.0, 10.0, 10.0]) for c in nodes[tets].mean(axis=1)])
out_q = out_q / np.linalg.norm(out_q, axis=1)[:, None] * 30.0
Tin = T_cold + 80.0 - 60.0 * np.linalg.norm(nodes - np.array([50.0, 10.0, 10.0]), axis=1) / 60.0
fresh(heat_result(q=out_q, T=Tin))
t_in = pg.data["tracers"]
ok(t_in and t_in["heat"]["how"] == "inside" and "through the part" in pg.notes.text(), f"heat made inside the part (no face it enters through): the lines start inside ({t_in['heat']['how'] if t_in else None})")
ok(all(r["ok"] for r in pg.self_check()), "and its checks pass: " + "; ".join(r["name"] + " " + r["got"] for r in pg.self_check_tracers3()))

fresh({k: v for k, v in heat_result().items() if k not in ("conn", "q", "qmag")})
ok(pg.data["tracers"] is None and pg.data["field3"] is None and pg.grp_trace_heat.isHidden() and "no flow" in pg.lbl_trace3.text() and not pg.boxes3["tracers"].isEnabled(),
   "a heat result with no flux in it (as the stand-in of the other test): no tracers, the controls are off, and the panel says there is no flow")
ok(pg.self_check_tracers3() == [] and len(pg.self_check()) == 5, "and the checks are the five of the part")

fresh(heat_result(), fluid={"steps": 10})
ok(pg.data["tracers"] and "not drawn" in pg.lbl_trace3.text() and "faded" in pg.lbl_trace3.text(), "with a 3D flow in the solve the heat tracers are still drawn, and the picture says the air is not")

fresh(heat_result(conn=tets[:, :3]))                                                    # a mesh the flux field cannot be made from (three corners)
ok(pg.mode == "body3d" and pg.data["tracers"] is None and "could not be made" in pg.notes.text(), f"a flux field that cannot be made is said, and the part is still drawn ({pg.notes.text()})")
pg.view.render_image(120, 1.0)

fresh(heat_result())
ok(pg.data["tracers"] and len(pg.data["tracers"]["lines"]) == 40 and pg.boxes3["tracers"].isEnabled(), "and a good result brings the tracers back")

print()
print("pictures in", OUT)
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
