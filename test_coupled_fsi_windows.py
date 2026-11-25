"""The structure moves the flow, through the real windows: a 20 mm square in a slow air stream (0.03 m/s, Re 40), held at its windward edge, in the 2D Fluid Flow window and the 2D Static
Structural window, driven by coupled_members + coupled_engine.
  * a body that is steel-stiff moves a few times 1e-14 mm: it does not move the flow, the loop says so after ONE flow solve;
  * a body so soft that the flow bends it by a few percent of its size: the loop converges (the displacement changes by under 1 % from one pass to the next), every check passes, the
    flow of the last pass is round the body where the stress analysis put it (the nodes of the right edge of the fluid mesh lie where the displacement of the stress analysis says,
    to the tolerance of the loop) and the pressure the stress analysis carries is the pressure of that flow;
  * the answer does not depend on how the loop is relaxed (a fixed factor of 0.5 gives the same displacement within the tolerance);
  * the windows are left as they were: the fluid window shows the moved body, a plain Solve on it is refused, Mesh gives the sketch as drawn again.
python test_coupled_fsi_windows.py"""
import faulthandler
faulthandler.dump_traceback_later(2400, exit=True)
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "coupled"), os.path.join(HERE, "shared")]
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
import physics_tab
import physics_geom as pg
import physics_cfd as pcfd
import coupled_engine as ce
import coupled_members as cm

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


m = sc.Model()
pts = [m.add_point(*c) for c in ((0, 0), (20, 0), (20, 20), (0, 20))]
ls = [m.add_line(pts[i], pts[(i + 1) % 4]) for i in range(4)]       # 0 bottom, 1 right, 2 top, 3 left
LEFT, RIGHT = ("ln", ls[3]), ("ln", ls[1])

cf = cfd_tab.CFDTab(host())
cf.run_task = run_now
cf.set_model(m, "a 20 mm square")
cf.e_speed.setText(f"{units.speed_from_si(0.03, cf.unit_name()):.6g}")
for e, v in ((cf.e_hb, "3"), (cf.e_hf, "12"), (cf.e_ml, "3"), (cf.e_mr, "8"), (cf.e_mb, "3"), (cf.e_mt, "3"), (cf.e_cfl, "2"), (cf.e_steps, "300"),
             (cf.e_tol, "1e-6"), (cf.e_ramp, "5"), (cf.e_every, "1000")):
    e.setText(v)
cf.cb_until.setChecked(False)
cf.cb_auto.setChecked(False)
cf.cb_heat.setChecked(False)


def structural(E):
    fe = physics_tab.PhysicsTab(host())
    fe.run_task = run_now
    fe.set_model(m, "a 20 mm square")
    fe.canvas.sel = [LEFT]
    fe.add_support("fixed")
    fe.e_E.setText(f"{E:.6g}")
    fe.e_h.setText("2")
    fe.cb_auto.setChecked(False)
    return fe


def untouched(fe, why=""):
    ok(cf.coupled_flow_only is False and cf.worker is None and cf.deformed_shapes is None and fe.coupled_in is None and fe.coupled_cfd is None, f"the windows are left as they were {why}")


def checks_text(res):
    return "; ".join(f"{c['name']}: {c['ok']} ({c['detail'][:90]})" for c in res["checks"])


def solve(fe, **opt):
    members = cm.pair({"cfd": cf, "fea": fe})
    t0 = time.time()
    res = ce.solve_coupled(members, dict({"moves_flow": True, "fsi_tol": 0.01, "fsi_max": 8, "pressure_tol": 0.02}, **opt))
    print(f"   ({time.time() - t0:.0f} s)")
    return res


# ------------------------------------------------------------------------------------------------------------------------------ a stiff body: nothing moves
fe = structural(200000.0)
res = solve(fe)
ok(res["ok"] and res["fsi"]["converged"] and res["fsi"]["iterations"] == 1, f"a steel-stiff body does not move the flow: ONE pass ({res['fsi']['iterations']}), umax {res['fsi']['umax']:.2e} mm; " + checks_text(res))
untouched(fe, "(stiff)")

# ------------------------------------------------------------------------------------------------------------------------------ a soft body that the flow bends
E_SOFT = 2e-8                                                          # MPa: the pressure of this flow (a few 1e-4 Pa) bends a 20 mm body by a few percent of its size
fe = structural(E_SOFT)
res = solve(fe)
f = res["fsi"]
print("history:", [(h["it"], round(h["umax"], 5), round(h["change"], 5), round(h["omega"], 3)) for h in f["history"]])
ok(res["ok"] and f["converged"], f"the loop converges in {f['iterations']} passes; every check: " + checks_text(res))
ok(2 <= f["iterations"] <= 8, f"after more than one pass (the body does move the flow) and within the limit ({f['iterations']})")
ok(0.002 * 20.0 < f["umax"] < 0.05 * 20.0, f"the body is bent by a visible, small part of its size: the largest displacement is {f['umax']:.4g} mm ({100 * f['umax'] / 20.0:.2g} % of 20 mm)")
ok(all(c["ok"] for c in res["checks"]), "every check passes")
ok(cf.mesh.get("deformed") and cf.result is not None and cf.result["status"] == "converged", "the fluid window shows the flow round the moved body")
# where the fluid mesh puts the right edge, against where the stress analysis says it moved
nodes = cf.mesh["nodes"]
right_nodes = np.unique(np.asarray(cf.mesh["wall_segs"][RIGHT]))
P = np.column_stack([np.full(len(right_nodes), 20.0), nodes[right_nodes, 1]])        # (the body as drawn: x = 20; y is nearly the same: moves little along the edge)
Dfea, _gap = cm.Structural2D(fe).displacement_at(P)
x_cfd = nodes[right_nodes, 0]
dev_x = float(np.abs((x_cfd - 20.0) - Dfea[:, 0]).max())
ok(dev_x <= 2.0 * 0.01 * f["umax"] + 0.02 * f["umax"], f"the right edge of the fluid mesh lies where the stress analysis moved it: largest difference {dev_x:.2e} mm of {f['umax']:.3g} mm")
ok(float(np.ptp(x_cfd - 20.0)) > 0.0 or abs(float((x_cfd - 20.0).mean())) > 1e-3 * f["umax"], f"and it did move (the edge is at x = {x_cfd.mean():.5f}, not 20)")
untouched(fe, "(soft)")
msg0 = len(MSGS)
cf.run_solve()
ok(len(MSGS) == msg0 + 1 and "Press Mesh" in MSGS[-1] and cf.worker is None, "a plain Solve on the moved mesh is refused in words")
u1 = np.asarray(fe.result["u"], float).copy()
n1 = np.asarray(fe.result["mesh"]["nodes"], float).copy()

# ------------------------------------------------------------------------------------------------------------------------------ the relaxation does not change the answer
fe2 = structural(E_SOFT)
res2 = solve(fe2, fsi_aitken=False, fsi_relax=0.5, fsi_tol=0.005, fsi_max=14)
f2 = res2["fsi"]
print("history:", [(h["it"], round(h["umax"], 5), round(h["change"], 5), round(h["omega"], 3)) for h in f2["history"]])
ok(res2["ok"] and f2["converged"], f"a fixed relaxation of 0.5 also converges ({f2['iterations']} passes)")
u2 = np.asarray(fe2.result["u"], float)
ok(np.allclose(n1, np.asarray(fe2.result["mesh"]["nodes"], float)), "(the same stress mesh)")
dev_u = float(np.abs(u2 - u1).max())
ok(dev_u <= 0.02 * f["umax"], f"and gives the same displacement: the two differ by {dev_u:.2e} mm of {f['umax']:.3g} mm ({100 * dev_u / f['umax']:.2g} %)")
cf.run_mesh()
ok(not cf.mesh["deformed"], "Mesh in the fluid window gives the sketch as drawn again")

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
