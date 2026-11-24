"""Tests of the heat-flow display of the 2D Thermal tab: thermal_flow.py (no Qt) and the Heat flow control of the Results section.

  A  thermal_flow with exact numbers: finding the triangle of a point, the flux of a triangle, the reference flux, the direction and speed ratio, the
     movement of a tracer per step (closed form), the constants shared with the 2D CFD tracers (read from cfd_tab.py), a tracer that leaves or gets
     too old and starts again where heat enters, trails, the spread of random points, the arrows.
  B  the tab: Off / Moving lines / Arrows, the message before there is a result, a steady bar (heat goes from the hot edge to the cold one with the flux
     k * dT / L), what is drawn, the number of tracers drawn, a uniform temperature (no flow), a new result, a transient run (the flux of the picture
     shown, also while the animation plays), the note where Animate is off for a steady result.
"""
import copy
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
TH = os.path.join(HERE, "dev_addons", "thermal2d")
sys.path[:0] = [HERE, SIM, TH, os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

import sketcher_core as sc
import physics_store as pstore
import sim_tab
import unitctl
import thermal_fem as tfem
import thermal_mat as tmat
import thermal_tab as tt
import thermal_units as tu

MM = "Metric (mm, kg, N, s, MPa)"
INCH = "US (in, lbf, psi)"
T_ = tempfile.mkdtemp(prefix="opara_thr_")
STEEL, COPPER, AIR = "Structural steel (A36)", "Copper", "Air (still)"


def close(a, b, rel=1e-6, ab=0.0):
    return abs(a - b) <= rel * max(abs(a), abs(b)) + ab


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


def new_tab(unit=MM):
    unitctl.set_units(unit, notify=False, persist=False)
    t = tt.ThermalTab(host())
    t.run_task = lambda title, fn: run_now(t, title, fn)
    return t


def answer(*vals):
    tt.ask_values = lambda parent, title, note, labels, defaults: list(vals)


def add(t, fn, sel, *vals):
    t.canvas.sel = list(sel)
    answer(*vals)
    getattr(t, fn)()


def mesh_solve(t, h):
    t.e_h.setText(str(h))
    t.run_mesh()
    assert t.mesh is not None, MSGS
    t.run_solve()
    assert t.result is not None, MSGS
    return t.result


def flow(res, name):
    return next(f["Q"] for f in res["flows"] if f["name"] == name)



import thermal_flow as tflow

# ================================================================================================================ A. thermal_flow
SQ_NODES = [(0, 0), (10, 0), (10, 10), (0, 10)]
SQ_TRIS = [(0, 1, 2), (0, 2, 3)]                        # the lower right triangle and the upper left one
f = tflow.FluxField(SQ_NODES, SQ_TRIS)
assert f.size == 10.0 and np.allclose(f.lo, [0, 0]) and np.allclose(f.hi, [10, 10]) and np.allclose(f.area, [50, 50])
assert list(f.locate([[9, 1], [1, 9], [15, 5], [5, -1], [-1, 5], [10.5, 10.5]])) == [0, 1, -1, -1, -1, -1]
assert f.locate([[5.0, 5.0]])[0] in (0, 1) and f.locate([[10.0, 0.0]])[0] == 0 and f.locate([[0.0, 10.0]])[0] == 1, "points on an edge or a corner are inside"
assert len(f.locate(np.zeros((0, 2)))) == 0
thin = tflow.FluxField([(0, 0), (100, 0), (100, 1), (0, 1)], [(0, 1, 2), (0, 2, 3)])          # the nearest centre is not always the triangle that holds the point
assert list(thin.locate([[90, 0.95], [90, 0.85], [10, 0.05], [10, 0.15]])) == [1, 0, 0, 1]
flat = tflow.FluxField(SQ_NODES + [(5, 5)], SQ_TRIS + [(0, 4, 2)])                           # the last triangle lies on the diagonal: no area, holds nothing
assert flat.locate([[5.0, 5.0], [5.0, 5.0 + 1e-9]])[0] in (0, 1) and flat.locate([[5.0, 5.0]])[0] != 2 and list(flat.locate([[2.5, 2.5]])) != [2]
f.set_flux([1.0, 0.0], [0.0, 2.0])
q, ins = f.flux_at([[9, 1], [1, 9], [20, 20]])
assert np.allclose(q, [[1, 0], [0, 2], [0, 0]]) and list(ins) == [True, True, False]
assert close(f.qref, 1.95)                              # the 95th percentile of the two fluxes 1 and 2
try:
    f.set_flux([1.0], [0.0])
    raise AssertionError("one flux for every triangle is required")
except ValueError:
    pass
assert tflow.reference_flux([0.0] * 99 + [7.0]) == 7.0, "a flux in less than 5 % of the triangles: the 95th percentile is 0, the reference is the largest"
assert tflow.reference_flux([]) == 0.0 and tflow.reference_flux([0.0, 0.0]) == 0.0 and close(tflow.reference_flux(np.arange(101.0)), 95.0)
assert tflow.reference_flux([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 7.0]) == float(np.percentile([0.0] * 9 + [7.0], 95))

# the direction and the speed ratio: a unit vector times flux / reference flux (as the CFD: speed over free-stream speed), at most MAX_RATIO;
# nothing below NO_FLOW of the reference
f.set_flux([3.0, 0.0], [4.0, 0.0], qref=20.0)            # triangle 0: flux (3, 4) = 5; triangle 1: nothing
d, ins = f.direction([[9, 1], [1, 9], [20, 20]])
assert np.allclose(d[0], np.array([0.6, 0.8]) * (5.0 / 20.0)) and np.allclose(d[1], 0) and np.allclose(d[2], 0) and list(ins) == [True, True, False]
f.set_flux([30.0, 0.0], [40.0, 0.0], qref=20.0)          # 2.5 times the reference: 2.5
assert np.allclose(f.direction([[9, 1]])[0][0], np.array([0.6, 0.8]) * 2.5)
f.set_flux([300.0, 0.0], [400.0, 0.0], qref=20.0)        # 25 times: the ratio stops at MAX_RATIO
assert np.allclose(f.direction([[9, 1]])[0][0], np.array([0.6, 0.8]) * tflow.MAX_RATIO)
f.set_flux([1e-4, 0.0], [0.0, 0.0], qref=1.0)            # 1e-4 of the reference is below NO_FLOW (1e-3): no motion
assert np.allclose(f.direction([[9, 1]])[0], 0)
f.set_flux([2e-3, 0.0], [0.0, 0.0], qref=1.0)            # 2e-3 is above it
assert np.allclose(f.direction([[9, 1]])[0][0], [2e-3, 0])
f.set_flux([5.0, 0.0], [0.0, 0.0], qref=0.0)             # no reference flux: nothing moves
assert np.allclose(f.direction([[9, 1]])[0], 0)

# a tracer moves by size / CROSS_SECONDS * dt * strength per step, in the direction of the flux
def tracers_at(field, pts, seed=1):
    tr = tflow.Tracers(field, n=len(pts), seed=seed)
    tr.p = np.array(pts, float)
    tr.age = np.zeros(len(pts))
    tr.trail = [[tuple(q)] for q in tr.p]
    return tr


step = 10.0 / tflow.CROSS_SECONDS * 0.03                 # 0.025
for fx, fy, qref, want in ((1.0, 0.0, 1.0, (step, 0.0)), (-1.0, 0.0, 1.0, (-step, 0.0)), (0.0, 1.0, 1.0, (0.0, step)), (0.0, -1.0, 1.0, (0.0, -step)),
                           (1.0, 0.0, 4.0, (step * 0.25, 0.0)), (3.0, 4.0, 5.0, (step * 0.6, step * 0.8)), (3.0, 4.0, 20.0, (step * 0.6 * 0.25, step * 0.8 * 0.25)),
                           (100.0, 0.0, 1.0, (step * tflow.MAX_RATIO, 0.0))):
    ff = tflow.FluxField(SQ_NODES, SQ_TRIS)
    ff.set_flux([fx, fx], [fy, fy], qref=qref)
    tr = tracers_at(ff, [[5.0, 5.0], [4.0, 6.0]])
    before = tr.p.copy()
    tr.step(0.03)
    assert np.allclose(tr.p - before, want, atol=1e-12), (fx, fy, qref, tr.p - before)
    assert np.allclose(tr.age, 0.03) and all(len(t_) == 2 for t_ in tr.trail)
ff = tflow.FluxField(SQ_NODES, SQ_TRIS)
ff.set_flux([0.0, 0.0], [0.0, 0.0], qref=1.0)            # no flux: they stay (and get older)
tr = tracers_at(ff, [[5.0, 5.0]])
tr.step(0.03)
assert np.allclose(tr.p, [[5.0, 5.0]]) and close(tr.age[0], 0.03)
# the midpoint rule: along a flux that turns, the step is not a plain Euler step; check with a two-triangle field that changes direction at the diagonal
ff = tflow.FluxField(SQ_NODES, SQ_TRIS)
ff.set_flux([0.0, 1.0], [1.0, 0.0], qref=1.0)            # lower right triangle: +y (towards the diagonal); upper left: +x
tr = tracers_at(ff, [[5.0 + 1e-3, 5.0 - 1e-3]])          # lower triangle, 1e-3 from the diagonal: the half step (0.025 up) is already in the other one
tr.step(0.03)
assert np.allclose(tr.p, [[5.001 + step, 4.999]]), tr.p   # so the whole step goes by the flux found there (+x); a plain Euler step would go up
ff = tflow.FluxField(SQ_NODES, SQ_TRIS)
ff.set_flux([0.0, 1.0], [1.0, 0.0], qref=1.0)            # lower right triangle: +y; upper left: +x
tr = tracers_at(ff, [[5.0, 4.98]])                       # the half step (0.0125 up) is still in the lower one, the whole step (0.025) would not be
tr.step(0.03)
assert np.allclose(tr.p, [[5.0, 4.98 + step]]), tr.p     # so the step goes by the flux of the lower one: up
# a tracer whose half step lands outside the drawing starts again (it is not left standing at the edge)
ff.set_flux([1.0, 1.0], [0.0, 0.0], qref=1.0)
tr = tracers_at(ff, [[9.995, 0.5]])                      # half step: 10.0075, outside
tr.step(0.03)
assert np.isclose(tr.p[0, 0], tflow.INLET_BLEND * 10.0 / 3.0) and len(tr.trail[0]) == 1
# a tracer that leaves the drawing is put back inside, with a new trail and age 0; the others keep their trail
ff = tflow.FluxField(SQ_NODES, SQ_TRIS)
ff.set_flux([1.0, 1.0], [0.0, 0.0], qref=1.0)
tr = tracers_at(ff, [[9.985, 0.5], [2.0, 8.0]])          # the first one is inside after the half step (9.9975) but out after the whole one (10.01)
tr.step(0.03)
assert np.all(ff.locate(tr.p) >= 0) and len(tr.trail[0]) == 1 and np.allclose(tr.p[1], [2.0 + step, 8.0]) and len(tr.trail[1]) == 2
assert len(tr.p) == 2 and tflow.RESTART_AGE[0] <= tr.age[0] <= tflow.RESTART_AGE[1] and np.isclose(tr.age[1], 0.03)
assert np.isclose(tr.p[0, 0], tflow.INLET_BLEND * 10.0 / 3.0), "it starts again where the heat enters: the left edge (a little way in, 0.1 of the way to the middle of its triangle)"
# one that is too old comes back, too
tr = tracers_at(ff, [[2.0, 8.0]])
tr.age[:] = tflow.MAX_AGE - 0.01
tr.step(0.03)
assert tflow.RESTART_AGE[0] <= tr.age[0] <= tflow.RESTART_AGE[1] and len(tr.trail[0]) == 1 and np.isclose(tr.p[0, 0], tflow.INLET_BLEND * 10.0 / 3.0)
tr = tracers_at(ff, [[2.0, 8.0]])
tr.age[:] = tflow.MAX_AGE - 0.05                          # not yet 14 s old after the step (13.98): it goes on
tr.step(0.03)
assert np.isclose(tr.age[0], tflow.MAX_AGE - 0.02) and np.allclose(tr.p, [[2.0 + step, 8.0]])
# the trail is at most TRAIL points long and is the way the tracer went
tr = tracers_at(ff, [[1.0, 8.0]])
for i in range(12):
    tr.step(0.03)
assert len(tr.trail[0]) == tflow.TRAIL == 7 and np.allclose(tr.trail[0][-1], tr.p[0]) and np.allclose(np.diff([q[0] for q in tr.trail[0]]), step)
# the same seed gives the same tracers; random points are spread evenly over the area
t1, t2 = tflow.Tracers(ff, n=50, seed=3), tflow.Tracers(ff, n=50, seed=3)
assert np.array_equal(t1.p, t2.p) and not np.array_equal(t1.p, tflow.Tracers(ff, n=50, seed=4).p)
assert tflow.START_AGE[0] <= t1.age.min() and t1.age.max() <= tflow.START_AGE[1] and t1.age.max() > 5.0, "the first tracers have ages of 0 to 10 s"
pts = ff.random_points(20000, np.random.default_rng(5))
assert np.all(ff.locate(pts) >= 0) and abs(pts[:, 0].mean() - 5.0) < 0.1 and abs(pts[:, 1].mean() - 5.0) < 0.1
assert abs(float(np.mean(ff.locate(pts) == 0)) - 0.5) < 0.02, "half the points in each of two triangles of the same area"
big = tflow.FluxField([(0, 0), (30, 0), (30, 10), (0, 10), (10, 0), (10, 10)], [(0, 4, 5), (0, 5, 3), (4, 1, 2), (4, 2, 5)])   # areas 50, 50, 100, 100
pb = big.random_points(20000, np.random.default_rng(6))
share = np.bincount(big.locate(pb), minlength=4) / 20000.0
assert np.allclose(share, [1 / 6, 1 / 6, 1 / 3, 1 / 3], atol=0.02), share
# the constants are the ones of the 2D CFD tracers (read from cfd_tab.py, so they cannot drift apart)
cfd = open(os.path.join(SIM, "cfd_tab.py"), encoding="utf-8").read()
assert "n = 700" in cfd and "self.trace_timer.start(30)" in cfd and "* 0.03" in cfd and "/ 12.0" in cfd and 'P["age"] > 14.0' in cfd
assert "rng.uniform(0, 10, len(pts))" in cfd and "rng.uniform(0, 3," in cfd and 'len(P["trail"][k]) > 7' in cfd
assert "QColor(255, 255, 255, 190), 1.5" in cfd and "QColor(10, 10, 10), 3.2" in cfd
assert tflow.CROSS_SECONDS == 12.0 and tflow.MAX_AGE == 14.0 and tflow.START_AGE == (0.0, 10.0) and tflow.RESTART_AGE == (0.0, 3.0) and tflow.TRAIL == 7
assert len(tflow.Tracers(ff).p) == 700

# the outline edges (one triangle only) with their inward normals; the inlets: edges where heat enters, in proportion to the heat entering
assert len(f.b_len) == 4 and np.allclose(sorted(f.b_len), [10.0] * 4) and sorted(map(tuple, np.abs(np.round(f.b_n)))) == [(0, 1), (0, 1), (1, 0), (1, 0)]
for k in range(4):
    assert np.dot(f.b_n[k], f.b_cen[k] - 0.5 * (f.b_a[k] + f.b_b[k])) > 0 and abs(np.hypot(*f.b_n[k]) - 1.0) < 1e-12
big = tflow.FluxField([(0, 0), (30, 0), (30, 10), (0, 10), (10, 0), (10, 10)], [(0, 4, 5), (0, 5, 3), (4, 1, 2), (4, 2, 5)])
assert len(big.b_len) == 6 and close(float(big.b_len.sum()), 80.0), "the outline of the 30 x 10 piece (the edge between two triangles is not on it)"
ring = tflow.FluxField([(0, 0), (30, 0), (30, 30), (0, 30), (10, 10), (20, 10), (20, 20), (10, 20)],
                       [(0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)])           # a square with a square hole
assert len(ring.b_len) == 8 and close(float(ring.b_len.sum()), 120.0 + 40.0), "the outline and the hole"
ff2 = tflow.FluxField(SQ_NODES, SQ_TRIS)
ff2.set_flux([1.0, 1.0], [2.0, 2.0], qref=2.0)           # flux (1, 2): 1 enters through the left edge, 2 through the bottom one (equal lengths)
pts = ff2.inlet_points(6000, np.random.default_rng(9))
left = np.isclose(pts[:, 0], tflow.INLET_BLEND * 10.0 / 3.0)
bottom = np.isclose(pts[:, 1], tflow.INLET_BLEND * 10.0 / 3.0)
assert np.all(ff2.locate(pts) >= 0) and np.all(left | bottom), "on the edges where heat enters, a little way in"
assert abs(float(left.mean()) - 1 / 3) < 0.02 and abs(float(bottom.mean()) - 2 / 3) < 0.02, (left.mean(), bottom.mean())
big.set_flux([1.0] * 4, [1.0] * 4, qref=1.0)             # flux (1, 1): it enters through the left edge (10 long) and the bottom ones (10 + 20 long): by length
pb = big.inlet_points(8000, np.random.default_rng(12))
left_b = np.isclose(pb[:, 0], tflow.INLET_BLEND * 10.0 / 3.0)
bottom_b = np.isclose(pb[:, 1], tflow.INLET_BLEND * 10.0 / 3.0)
assert np.all(left_b | bottom_b) and abs(float(left_b.mean()) - 0.25) < 0.02 and abs(float(bottom_b.mean()) - 0.75) < 0.02, (left_b.mean(), bottom_b.mean())
ff2.set_flux([1e-4, 1e-4], [0.0, 0.0], qref=1.0)         # a flux that is no flow: no inlet, so anywhere
pts = ff2.inlet_points(4000, np.random.default_rng(10))
assert abs(pts[:, 0].mean() - 5.0) < 0.2 and abs(pts[:, 1].mean() - 5.0) < 0.2 and len(ff2.inlet_points(0, np.random.default_rng(1))) == 0
ff2.set_flux([1.0, 1.0], [0.0, 0.0], qref=1.0)           # heat goes +x: it enters through the left edge only
assert np.all(np.isclose(ff2.inlet_points(50, np.random.default_rng(11))[:, 0], tflow.INLET_BLEND * 10.0 / 3.0))

# the arrows: the points of a grid in the drawing where heat flows; unit direction and strength sqrt(flux / reference)
ff.set_flux([1.0, 1.0], [0.0, 0.0], qref=1.0)
pts, d, st, spacing = tflow.arrow_samples(ff, across=5)
assert spacing == 2.0 and len(pts) == 25 and sorted(set(pts[:, 0])) == [1, 3, 5, 7, 9] and sorted(set(pts[:, 1])) == [1, 3, 5, 7, 9]
assert np.allclose(d, [1, 0]) and np.allclose(st, 1.0)
ff.set_flux([4.0, 1e-6], [0.0, 0.0], qref=16.0)          # triangle 0: strength sqrt(4/16) = 0.5; triangle 1: below NO_FLOW of the reference: no arrows
pts, d, st, spacing = tflow.arrow_samples(ff, across=5)
assert len(pts) == 10 and np.all(pts[:, 0] > pts[:, 1]) and np.allclose(st, 0.5) and np.allclose(d, [1, 0]), (pts, st)
ff.set_flux([0.0, 0.0], [0.0, 0.0], qref=0.0)
assert len(tflow.arrow_samples(ff)[0]) == 0
pts, d, st, spacing = tflow.arrow_samples(tflow.FluxField(SQ_NODES, SQ_TRIS), across=3)       # a field that never got its flux: nothing to draw (qref 0)
print("A ok: thermal_flow")

# ================================================================================================================ B. the tab
W_, H_ = 100.0, 20.0                                    # the bar, in mm
K_AL = 167.0                                            # the default material: Aluminium 6061-T6


def bar_tab(left=100.0, right=20.0, transient=False, vertical=False):
    t = new_tab()
    m = sc.Model()
    pp = [m.add_point(*c) for c in ((0, 0), (W_, 0), (W_, H_), (0, H_))]
    ls = [m.add_line(pp[i], pp[(i + 1) % 4]) for i in range(4)]          # 0 bottom, 1 right, 2 top, 3 left
    t.set_model(m, "bar")
    t.e_t.setText("1")
    a_, b_ = (ls[0], ls[2]) if vertical else (ls[3], ls[1])          # the hot edge and the cold one: left and right, or bottom and top
    add(t, "add_temperature", [("ln", a_)], left)
    add(t, "add_temperature", [("ln", b_)], right)
    if transient:
        t.analysis_combo.setCurrentIndex(1)
        t.e_T0.setText("20")
        t.e_tend.setText("20")
        t.time_combo.setCurrentText("s")
        t.e_steps.setText("40")
        t.e_nframes.setText("11")
    return t, ls


def dark_pixels(t, rgb=(10, 10, 10), tol=3):
    t.canvas.resize(700, 420)
    t.canvas.fit()
    img = t.canvas.grab().toImage()
    pts = []
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            if abs(c.red() - rgb[0]) <= tol and abs(c.green() - rgb[1]) <= tol and abs(c.blue() - rgb[2]) <= tol:
                pts.append((x, y))
    return pts


t, ls = bar_tab()
assert t.flow_combo.currentIndex() == 0 and [t.flow_combo.itemText(i) for i in range(3)] == ["Off", "Moving tracer particles", "Arrows"] and not t.flow_timer.isActive()
n_msg = len(MSGS)
t.flow_combo.setCurrentIndex(1)                         # nothing solved yet: said, and back to Off
assert len(MSGS) == n_msg + 1 and "Solve first" in MSGS[-1] and t.flow_combo.currentIndex() == 0 and not t.flow_timer.isActive()
t.flow_combo.setCurrentIndex(2)
assert len(MSGS) == n_msg + 2 and t.flow_combo.currentIndex() == 0
mesh_solve(t, 4)
t.field.setCurrentIndex(t.field.findData("T"))
t.resize(1100, 700)
t.show()
app.processEvents()
assert not t.cb_anim.isEnabled() and not t.steady_note.isHidden() and "Heat flow" in t.steady_note.text() and "steady" in t.steady_note.text().lower()
assert t.flow_mode() == 0
BASE_DOTS, BASE_ARROWS = set(dark_pixels(t)), set(dark_pixels(t, (20, 20, 20), 70))      # what is dark anyway (the legend text, lines)

# a steady bar: the heat goes from the hot edge (x = 0) to the cold one, with the flux k * dT / L
Q = K_AL * (100.0 - 20.0) / (W_ / 1000.0)
assert close(float(np.max(t.result["qmag"])), Q, 1e-6) and np.all(t.result["qx"] > 0.99 * Q)
t.flow_combo.setCurrentIndex(1)
assert t.flow_timer.isActive() and t.flow_timer.interval() == 30 and t.flow_tracers is not None and t.flow_field.qref > 0 and close(t.flow_field.qref, Q, 1e-6)
assert t.flow_field is not None and len(t.flow_tracers.p) == 700 and t._flow_k is None, "a steady result has no picture index"
v, ins = t.flow_field.direction(t.flow_tracers.p)
assert np.all(ins) and np.allclose(v[:, 0], 1.0, atol=1e-6) and np.allclose(v[:, 1], 0.0, atol=1e-6), "every tracer goes towards the cold edge"
before, ages = t.flow_tracers.p.copy(), t.flow_tracers.age.copy()
t.flow_step()
moved = t.flow_tracers.age > ages                       # (the ones that were put back have a new age)
assert np.allclose(t.flow_tracers.age[moved] - ages[moved], 0.03)
live = np.isclose(t.flow_tracers.age, ages + 0.03)
step_mm = W_ / tflow.CROSS_SECONDS * 0.03
assert live.sum() > 600 and np.allclose((t.flow_tracers.p - before)[live], [step_mm, 0.0], atol=1e-6), "0.25 mm per step along +x (100 mm in 12 s)"
# those that start again come in at the hot edge (x = 0) and are then carried towards the cold one
for i in range(100):                                     # 3 s of display time
    t.flow_step()
fresh = t.flow_tracers.age < 2.9                         # started again since the run began
assert fresh.sum() >= 20 and t.flow_tracers.p[fresh, 0].max() < 0.3 + 3.0 * (W_ / 12.0) + 1.0, "they come in at the hot edge, not anywhere"
assert t.flow_tracers.p[fresh, 0].mean() < 20.0
# what is drawn: all 700 tracers, as the CFD draws them: dark dots (and white trails); nothing for the arrows
t.canvas.resize(700, 420)
t.canvas.fit()
sc_px = t.canvas.scale
dots = [q for q in dark_pixels(t) if q not in BASE_DOTS]
assert len(t.flow_tracers.p) == 700 and len(dots) > 2000, len(dots)
img_with = t.canvas.grab().toImage()                     # the white trails: the picture changes when they are taken away
trails_saved = t.flow_tracers.trail
t.flow_tracers.trail = [[tuple(q)] for q in t.flow_tracers.p]
img_without = t.canvas.grab().toImage()
t.flow_tracers.trail = trails_saved
changed = sum(1 for y in range(img_with.height()) for x in range(img_with.width()) if img_with.pixel(x, y) != img_without.pixel(x, y))
assert changed > 500, changed
sx = lambda mmx: t.canvas.w2s(mmx, 0).x()
assert all(sx(-1) <= x <= sx(W_ + 1) for x, _y in dots), "the dots are on the drawing"
t.flow_combo.setCurrentIndex(0)
assert not t.flow_timer.isActive() and set(dark_pixels(t)) == BASE_DOTS
t.flow_step()                                           # a tick that comes after it was turned off does nothing
assert not t.flow_timer.isActive()

# arrows: a regular grid, all pointing to the cold edge, drawn dark with the head on the right
t.flow_combo.setCurrentIndex(2)
assert not t.flow_timer.isActive()
pts, d, st, spacing = t.flow_arrows()
assert np.allclose(d, [1, 0], atol=1e-6) and np.allclose(st, 1.0, atol=1e-6) and close(spacing, W_ / 24.0) and len(pts) == 24 * 5 and t.flow_arrows() is t.flow_arrows()
arrows = [q for q in dark_pixels(t, (20, 20, 20), 70) if q not in BASE_ARROWS]
assert len(arrows) > 800
a0 = pts[np.argmin(np.abs(pts[:, 0] - W_ / 2) + np.abs(pts[:, 1] - H_ / 2))]       # the arrow nearest the middle
c0 = t.canvas.w2s(float(a0[0]), float(a0[1]))
half = max(6.0, min(40.0, spacing * sc_px * 0.9)) / 2
box = [(x, y) for x, y in arrows if abs(y - c0.y()) <= 6 and abs(x - c0.x()) <= half + 1]
right = sum(1 for x, y in box if x > c0.x() + 1)
left = sum(1 for x, y in box if x < c0.x() - 1)
assert right > left + 4, (left, right)                  # the head makes the right half heavier: the arrow points to the right (the cold edge)
t.flow_combo.setCurrentIndex(0)
assert set(dark_pixels(t, (20, 20, 20), 70)) == BASE_ARROWS

# a new result replaces what the tracers follow; no result turns the display off
t.flow_combo.setCurrentIndex(1)
old_field, old_tr = t.flow_field, t.flow_tracers
mesh_solve(t, 5)
t.flow_step()
assert t.flow_field is not old_field and t.flow_tracers is not old_tr and t._flow_key == id(t.result) and len(t.flow_tracers.p) == 700
t.result = None
t.flow_step()
assert t.flow_mode() == 0 and not t.flow_timer.isActive()
# the heat goes up: hot bottom edge, cold top edge (the screen's y axis points down: the arrows point to smaller y)
tv, _ = bar_tab(vertical=True)
mesh_solve(tv, 4)
tv.field.setCurrentIndex(tv.field.findData("T"))
tv.resize(1100, 700)
tv.show()
app.processEvents()
Qv = K_AL * 80.0 / (H_ / 1000.0)
assert close(float(np.max(tv.result["qmag"])), Qv, 1e-6) and np.all(tv.result["qy"] > 0.99 * Qv) and np.all(np.abs(tv.result["qx"]) < 1e-6 * Qv)
base_v = set(dark_pixels(tv, (20, 20, 20), 70))
tv.flow_combo.setCurrentIndex(2)
pv, dv, sv, spv = tv.flow_arrows()
assert np.allclose(dv, [0, 1], atol=1e-6) and len(pv) == 24 * 5
arr_v = [q for q in dark_pixels(tv, (20, 20, 20), 70) if q not in base_v]
a1 = pv[np.argmin(np.abs(pv[:, 0] - W_ / 2) + np.abs(pv[:, 1] - H_ / 2))]
c1 = tv.canvas.w2s(float(a1[0]), float(a1[1]))
half_v = max(6.0, min(40.0, spv * tv.canvas.scale * 0.9)) / 2
box_v = [(x, y) for x, y in arr_v if abs(x - c1.x()) <= 6 and abs(y - c1.y()) <= half_v + 1]
up = sum(1 for x, y in box_v if y < c1.y() - 1)
down = sum(1 for x, y in box_v if y > c1.y() + 1)
assert up > down + 4, (up, down)
tv.flow_combo.setCurrentIndex(1)
vv, insv = tv.flow_field.direction(tv.flow_tracers.p)
assert np.allclose(vv[:, 1], 1.0, atol=1e-6) and np.allclose(vv[:, 0], 0.0, atol=1e-6)
tv.flow_combo.setCurrentIndex(0)
print("B1 ok: steady bar")

# the tab not shown (another tab is on top): the timer ticks, nothing moves
t2, _ = bar_tab()
mesh_solve(t2, 6)
t2.flow_combo.setCurrentIndex(1)
p0 = t2.flow_tracers.p.copy()
assert not t2.isVisible()
t2.flow_step()
assert np.array_equal(t2.flow_tracers.p, p0)
t2.show()
t2.flow_step()
assert not np.array_equal(t2.flow_tracers.p, p0)
t2.flow_combo.setCurrentIndex(0)

# the same temperature on both edges: only rounding noise, so no heat flows and nothing moves
t3, _ = bar_tab(left=50.0, right=50.0)
mesh_solve(t3, 5)
t3.show()
assert float(np.max(t3.result["qmag"])) < 1e-3
t3.flow_combo.setCurrentIndex(1)
assert t3.flow_field.qref == 0.0 and "No heat flows" in t3.status_lbl.text()
p0, a0 = t3.flow_tracers.p.copy(), t3.flow_tracers.age.copy()
t3.flow_step()
live = np.isclose(t3.flow_tracers.age, a0 + 0.03)         # (one that got too old is put somewhere else)
assert live.sum() > 600 and np.allclose(t3.flow_tracers.p[live], p0[live])
t3.flow_combo.setCurrentIndex(2)
assert len(t3.flow_arrows()[0]) == 0
print("B2 ok: nothing visible, nothing flowing")

# a transient run: the heat flow follows the picture shown (the slider, and the animation while it plays); one reference flux for the whole run
tr1, ls1 = bar_tab(transient=True)
mesh_solve(tr1, 5)
tr1.show()
app.processEvents()
n = tr1.frame_count()
assert n == 11 and not tr1.cb_anim.isHidden() and tr1.cb_anim.isEnabled() and tr1.steady_note.isHidden(), "a transient run animates; the steady note goes"
tr1.field.setCurrentIndex(tr1.field.findData("T"))
tr1.flow_combo.setCurrentIndex(2)
assert tr1.flow_frame() == n - 1 and tr1._flow_k == n - 1
ref = tr1.flow_field.qref
ks = sorted({int(round(i * (n - 1) / 7.0)) for i in range(8)})
assert close(ref, max(tflow.reference_flux(tfem.flux_of(tr1.result, tr1.result["frames"][k])[2]) for k in ks)) and ref > 0
q_end = tr1.flux_for(n - 1)
assert np.allclose(tr1.flow_field.qx, q_end[0])
tr1.time_slider.setValue(2)                              # the slider moves to another picture: its flux
tr1.flow_arrows()
assert tr1.flow_frame() == 2 and tr1._flow_k == 2 and np.allclose(tr1.flow_field.qx, tr1.flux_for(2)[0]) and tr1.flow_field.qref == ref
assert not np.allclose(tr1.flux_for(2)[0], tr1.flux_for(n - 1)[0])
tr1.flow_combo.setCurrentIndex(1)                        # tracers: the same, and their strength is that picture's flux over the run's reference
tr1.flow_step()
mid = np.array([[W_ / 2, H_ / 2]])
e_mid = tr1.flow_field.locate(mid)[0]
qx2, qy2 = tr1.flux_for(2)[:2]
qm = float(np.hypot(qx2[e_mid], qy2[e_mid]))
want = min(tflow.MAX_RATIO, qm / ref) if qm > 1e-3 * ref else 0.0
assert close(float(np.hypot(*tr1.flow_field.direction(mid)[0][0])), want, 1e-9), (qm, ref)
# while the animation plays, the flux of the picture it shows
tr1.cb_anim.setChecked(True)
tr1.e_frames.setText("5")
assert tr1.render_frames(5)
tr1.canvas.anim_idx = 2
assert tr1.flow_frame() == tr1.frame_of(0.5) == 5
tr1.flow_step()
assert tr1._flow_k == 5 and np.allclose(tr1.flow_field.qx, tr1.flux_for(5)[0])
tr1.canvas.anim_idx = 4
tr1.flow_step()
assert tr1._flow_k == n - 1
tr1.cb_anim.setChecked(False)
tr1.canvas.invalidate()
assert tr1.flow_frame() == tr1.frame_of(None) == tr1.frame_idx
tr1.flow_combo.setCurrentIndex(0)
print("B3 ok: transient run")
print("OK thermal heat flow")
