"""The 2D Fluid Flow window with a body that a structure has moved (what Coupled Physics does when 'the structure moves the flow' is on): the mesh follows the moved outline, the flow
is solved round it, and the wall tables put the pressure back on the edges AS DRAWN.  The answers that are known:
  * a 20 mm square stretched by 10 % along x is a 22 x 20 rectangle: the flow round it is the flow round a rectangle drawn at 22 x 20 (the same domain, the same element sizes), and
    is NOT the flow round the square (the drag differs by well over the tolerance);
  * a circle of radius 10 grown to radius 11 is a circle of radius 11: the same, for the two half-circle curves of the moved circle;
  * a body that is 'moved' by nothing gives the flow of the body as drawn (within the noise of two meshes);
  * the position along each edge of a wall segment is the position of its material point on the edge AS DRAWN (x / 20 on the stretched edge although it now ends at x = 22), and the
    segments of an edge together cover it from 0 to 1;
  * the window: the mesh is flagged as moved, a plain Solve on it is refused in words, Mesh gives the sketch as drawn again, the moved geometry is not kept in the saved setup.
python test_cfd_moved_mesh.py"""
import faulthandler
faulthandler.dump_traceback_later(1500, exit=True)
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
MSGS = []
for _n in ("warning", "information", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: MSGS.append(str(a[2]) if len(a) > 2 else "")))

import sketcher_core as sc
import sim_tab
import unitctl
import units
import cfd_tab
import physics_cfd as pcfd
import physics_geom as pg

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


MM = "Metric (mm, kg, N, s, MPa)"
unitctl.set_units(MM, notify=False, persist=False)


def host():
    h = sim_tab.SimHost.__new__(sim_tab.SimHost)
    h.doc = None
    h.m = sim_tab._HostModel()
    h._restoring = False
    h.status = lambda t: None
    h.sim = None
    h.sketch_list = lambda: []
    return h


def run_now(title, fn):
    try:
        return "ok", fn(lambda *a, **k: None, lambda: False)
    except (pg.Cancelled, pcfd.Cancelled):
        return "cancelled", None
    except (pg.GeometryError, pcfd.ModelError) as ex:
        QMessageBox.warning(None, title, str(ex))
        return "user", str(ex)


def rectangle(w, h):
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (w, 0), (w, h), (0, h))]
    ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
    return m, ls


def disc(r):
    m = sc.Model()
    c = m.add_point(0, 0)
    m.add_circle(c, r)
    return m


def window(m, margins, hb=3.0, steps=300):
    cf = cfd_tab.CFDTab(host())
    cf.run_task = run_now
    cf.set_model(m, "a body")
    cf.e_speed.setText(f"{units.speed_from_si(0.03, cf.unit_name()):.6g}")
    for e, v in ((cf.e_hb, str(hb)), (cf.e_hf, "12"), (cf.e_ml, f"{margins[0]:.8g}"), (cf.e_mr, f"{margins[1]:.8g}"), (cf.e_mb, f"{margins[2]:.8g}"), (cf.e_mt, f"{margins[3]:.8g}"),
                 (cf.e_cfl, "2"), (cf.e_steps, str(steps)), (cf.e_tol, "1e-6"), (cf.e_ramp, "5"), (cf.e_every, "1000")):
        e.setText(v)
    cf.cb_until.setChecked(False)
    cf.cb_auto.setChecked(False)
    cf.cb_heat.setChecked(False)
    return cf


def solve(cf, shape=None, shapes=None):
    """Meshes (round the moved body when `shape` is given) and solves, waiting for the worker."""
    import time
    cf.run_mesh(shape=shape)
    assert cf.mesh is not None
    cf.deformed_shapes = shapes
    cf.run_solve()
    t0 = time.time()
    while cf.worker is not None and time.time() - t0 < 600:
        app.processEvents()
        time.sleep(0.01)
    cf.deformed_shapes = None
    assert cf.result is not None, MSGS[-1:]
    return cf.result


def moved(cf, fn):
    """The shape and the moved geometry of every edge of the outline of the window, each point of the outline sampled and moved by fn(points) -> points."""
    faces = [f for f in cf.geom["faces"] if f["id"] in cf.body_on and f["depth"] == 0]
    used = sorted({k for loop in pcfd.body_loops(cf.geom, faces) for k, _ in loop})
    shape, shapes = {}, {}
    for k in used:
        e = cf.geom["edges"][k]
        pts, s = pcfd.sample_edge(cf.model, e, 24)
        new = fn(pts)
        shape[k] = new
        shapes[e["src"]] = pcfd.poly_geometry(new, s, closed=e["kind"] == "ci")
    return {"edges": shape}, shapes


def drag(res):
    return res["forces"]["along"]


# ------------------------------------------------------------------------------------------------------------------------------ the square, as drawn and stretched
SQ, _ = rectangle(20, 20)
size = 20.0
M_SQ = (3.0, 8.0, 3.0, 3.0)
cf = window(SQ, M_SQ)
r_ref = solve(cf)
ok(r_ref["status"] == "converged" and not cf.mesh["deformed"], f"the square as drawn: converged in {r_ref['steps']} steps, drag {drag(r_ref):.6g} N/m")

# identity: the body 'moved' by nothing
shape0, shapes0 = moved(cf, lambda p: p.copy())
r_id = solve(cf, shape0, shapes0)
ok(cf.mesh["deformed"] and r_id["status"] == "converged", "a body moved by nothing: the mesh is flagged as moved, the flow converges")
ok(abs(drag(r_id) - drag(r_ref)) <= 0.03 * abs(drag(r_ref)), f"and it is the flow of the body as drawn (drag {drag(r_id):.6g} against {drag(r_ref):.6g} N/m)")
ok(not cf.setup_used.get("edge_shapes"), "the moved geometry is not kept in the setup the window saves")
n_ok = True
for src, tb in r_id["walls"].items():
    lo, hi = float(min(tb["s_a"].min(), tb["s_b"].min())), float(max(tb["s_a"].max(), tb["s_b"].max()))
    n_ok = n_ok and abs(lo) < 1e-9 and abs(hi - 1.0) < 1e-9
ok(n_ok, "the segments of every edge cover it from 0 to 1")
msg0 = len(MSGS)
cf.run_solve()
ok(len(MSGS) == msg0 + 1 and "Press Mesh" in MSGS[-1] and cf.worker is None, f"a plain Solve on the moved mesh is refused in words: '{MSGS[-1][:110]}'")
cf.run_mesh()
ok(not cf.mesh["deformed"], "Mesh gives the sketch as drawn again")

# stretched by 10 % along x
shape1, shapes1 = moved(cf, lambda p: np.column_stack([1.1 * p[:, 0], p[:, 1]]))
r_st = solve(cf, shape1, shapes1)
xs = cf.mesh["nodes"][np.unique(np.asarray([i for segs in cf.mesh["wall_segs"].values() for sg in segs for i in sg]))][:, 0]
ok(abs(float(xs.max()) - 22.0) < 1e-6 and r_st["status"] == "converged", f"the moved body reaches x = 22 ({float(xs.max()):.6g}) and the flow converges")
# the same shape drawn directly, in the same domain
box = cf.mesh["box"]                                                                    # (x0, y0, x1, y1) of the domain of the square as drawn
RC, _ = rectangle(22, 20)
sz = 22.0
margins = ((0 - box[0]) / sz, (box[2] - 22.0) / sz, (0 - box[1]) / sz, (box[3] - 20.0) / sz)
cd = window(RC, margins)
r_dir = solve(cd)
ok(np.allclose(cd.mesh["box"], box), f"the 22 x 20 rectangle is meshed in the same domain {tuple(round(v, 6) for v in cd.mesh['box'])}")
dev = abs(drag(r_st) - drag(r_dir)) / abs(drag(r_dir))
dev_sq = abs(drag(r_st) - drag(r_ref)) / abs(drag(r_ref))
ok(dev <= 0.03, f"the flow round the stretched square is the flow round the 22 x 20 rectangle (drag {drag(r_st):.6g} against {drag(r_dir):.6g} N/m, {100 * dev:.2g} % apart)")
ok(dev <= 0.03, "(the stretch along the flow changes the drag very little: the next one is across it)")
# where each material point is: the top edge of the square, s = x_ref / 20 although the segments now lie at x_def = 1.1 x_ref
top = next(src for src in r_st["walls"] if abs(np.mean([cf.model.pts[p][1] for p in cf.model.lns[src[1]][:2]]) - 20.0) < 1e-9)
tb = r_st["walls"][top]
ends = np.concatenate([tb["s_a"], tb["s_b"]])
ok(abs(float(ends.min())) < 1e-9 and abs(float(ends.max()) - 1.0) < 1e-9, f"on the stretched top edge the positions run from 0 to 1 ({ends.min():.6g} .. {ends.max():.6g}), as on the edge as drawn")
nodes = cf.mesh["nodes"]
seg = np.asarray(cf.mesh["wall_segs"][top])
g_ref = pcfd.edge_geometry(cf.model, next(e for e in cf.geom["edges"] if e["src"] == top))
want = np.array([pcfd.edge_param(g_ref, nodes[i, 0] / 1.1, nodes[i, 1]) for i in seg[:, 0]])          # the material point of a node at x is the one that was at x / 1.1
ok(np.allclose(tb["s_a"], want, atol=1e-9) and float(np.ptp(want)) > 0.05, "a segment on the moved edge has the position of its material point on the edge as drawn (not the position of where it lies now)")
ok(not np.allclose(np.array([pcfd.edge_param(g_ref, nodes[i, 0], nodes[i, 1]) for i in seg[:, 0]]), want, atol=1e-3), "(and that is not what the plain projection on the edge as drawn would give: the test can tell them apart)")
# the pressure goes back on the edge as drawn, by that position
p_mid = 0.5 * (tb["p_a"] + tb["p_b"])
ok(np.all(np.isfinite(p_mid)) and float(np.ptp(tb["s_a"])) > 0.9, "the table of the edge is complete")

# stretched by 20 % across the flow: 20 x 24, which has a clearly different drag
shape2, shapes2 = moved(cf, lambda p: np.column_stack([p[:, 0], 1.2 * p[:, 1]]))
r_st2 = solve(cf, shape2, shapes2)
RC2, _ = rectangle(20, 24)
sz2 = 24.0
margins2 = ((0 - box[0]) / sz2, (box[2] - 20.0) / sz2, (0 - box[1]) / sz2, (box[3] - 24.0) / sz2)
cd2_ = window(RC2, margins2)
r_dir2 = solve(cd2_)
ok(np.allclose(cd2_.mesh["box"], box), "the 20 x 24 rectangle is meshed in the same domain")
dev2 = abs(drag(r_st2) - drag(r_dir2)) / abs(drag(r_dir2))
dev2_sq = abs(drag(r_st2) - drag(r_ref)) / abs(drag(r_ref))
ok(dev2 <= 0.03, f"the flow round the square stretched across the flow is the flow round the 20 x 24 rectangle (drag {drag(r_st2):.6g} against {drag(r_dir2):.6g} N/m, {100 * dev2:.2g} % apart)")
ok(dev2_sq > 0.05 and dev2_sq > 3 * dev2, f"and it is not the flow round the square ({100 * dev2_sq:.2g} % from it): the test can tell them apart")

# ------------------------------------------------------------------------------------------------------------------------------ the disc: two half circles
CD = disc(10.0)
M_CD = (3.0, 8.0, 3.0, 3.0)
cc_ = window(CD, M_CD, hb=2.0)
r_c = solve(cc_)
sh_c, shs_c = moved(cc_, lambda p: 1.1 * p)                                             # (the circle is centred on the origin)
r_cm = solve(cc_, sh_c, shs_c)
box_c = cc_.mesh["box"]
CD2 = disc(11.0)
cd2 = window(CD2, ((0 - box_c[0] - 11.0) / 22.0, (box_c[2] - 11.0) / 22.0, (0 - box_c[1] - 11.0) / 22.0, (box_c[3] - 11.0) / 22.0), hb=2.0)
r_c2 = solve(cd2)
ok(np.allclose(cd2.mesh["box"], box_c, atol=1e-6), "the circle of radius 11 is meshed in the domain of the circle of radius 10")
dev_c = abs(drag(r_cm) - drag(r_c2)) / abs(drag(r_c2))
dev_c0 = abs(drag(r_cm) - drag(r_c)) / abs(drag(r_c))
ok(dev_c <= 0.03 and dev_c0 > 0.05, f"a circle moved out to radius 11 gives the flow round a circle of radius 11 ({100 * dev_c:.2g} % apart), not round the one of radius 10 ({100 * dev_c0:.2g} %)")
tbc = next(iter(r_cm["walls"].values()))
ok(abs(float(min(tbc["s_a"].min(), tbc["s_b"].min()))) < 0.05 and float(max(tbc["s_a"].max(), tbc["s_b"].max())) > 0.95, "the positions on the moved circle run round it once")

# ------------------------------------------------------------------------------------------------------------------------------ an arc and a line (a half disc), meshed only
mh = sc.Model()
c0, s0, e0 = mh.add_point(0, 0), mh.add_point(10, 0), mh.add_point(-10, 0)
mh.add_arc(c0, s0, e0)
mh.add_line(e0, s0)
gh = pg.analyze(mh)
ids_h = {f["id"] for f in pcfd.body_faces(gh)}
faces_h = [f for f in gh["faces"] if f["id"] in ids_h]
used_h = sorted({k for loop in pcfd.body_loops(gh, faces_h) for k, _ in loop})
shape_h = {"edges": {}}
for k in used_h:
    pts, _s = pcfd.sample_edge(mh, gh["edges"][k], 24)
    shape_h["edges"][k] = 1.1 * pts
mesh_h = pcfd.mesh_fluid(mh, gh, ids_h, (3.0, 8.0, 3.0, 3.0), 2.0, 12.0, 0.3, shape=shape_h)
arc_src = next(gh["edges"][k]["src"] for k in used_h if gh["edges"][k]["kind"] == "ar")
ids_arc = np.unique(np.asarray(mesh_h["wall_segs"][arc_src]))
r_arc = np.hypot(mesh_h["nodes"][ids_arc, 0], mesh_h["nodes"][ids_arc, 1])
ok(mesh_h["deformed"] and float(np.abs(r_arc - 11.0).max()) < 0.02, f"an arc moved out by 10 % is meshed on the circle of radius 11 (radii {r_arc.min():.4f} .. {r_arc.max():.4f})")
ln_src = next(gh["edges"][k]["src"] for k in used_h if gh["edges"][k]["kind"] == "ln")
xl = mesh_h["nodes"][np.unique(np.asarray(mesh_h["wall_segs"][ln_src])), 0]
ok(abs(float(xl.min()) + 11.0) < 1e-6 and abs(float(xl.max()) - 11.0) < 1e-6, f"and the line it closes with runs from x = -11 to 11 ({xl.min():.4f} .. {xl.max():.4f}): the two share their ends")

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
