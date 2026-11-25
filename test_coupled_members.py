"""Coupled Physics members: the real 2D/3D Thermal and Static Structural windows driven through coupled_members + coupled_engine on a heated bar with known answers.
2D: 100 x 10 bar, 100 degC on the left end and 20 degC on the right (steady, nothing else), expansion alpha = 12e-6, reference 20 degC: the temperature runs linearly, its
mean is 60 degC, the right end moves alpha (Tmean - Tref) L = 0.048 mm, and the stress is small (the bar is free to grow).  3D the same with a block.
python test_coupled_members.py"""
import faulthandler
faulthandler.dump_traceback_later(480, exit=True)
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "thermal3d"),
                os.path.join(HERE, "dev_addons", "coupled"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
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
import coupled_engine as ce
import coupled_members as cm

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, rel, text, ab=0.0):
    ok(abs(a - b) <= rel * abs(b) + ab, f"{text}: {a:.6g} against {b:.6g}")


MM = "Metric (mm, kg, N, s, MPa)"
unitctl.set_units(MM, notify=False, persist=False)
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


def bar(W=100.0, Hh=10.0):
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (W, 0), (W, Hh), (0, Hh))]
    ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]       # 0 bottom, 1 right, 2 top, 3 left
    return m, p, ls


def answer(*vals):
    def f(parent, title, note, labels, defaults):
        return list(vals)
    tt.ask_values = f


def pick(t, fn, sel, *vals):
    t.canvas.sel = list(sel)
    answer(*vals)
    getattr(t, fn)()


# ------------------------------------------------------------------------------------------------------------------------------------------ 2D
m, p, ls = bar()
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
fe.add_support("x")                                       # the left end cannot move along the bar
fe.canvas.sel = [("pt", p[0])]
fe.add_support("y")                                       # and the lower left corner cannot move across it: nothing else holds the bar
fe.e_alpha.setText("1.2e-5")
fe.e_tref.setText("20")
fe.e_h.setText("2")
fe.cb_auto.setChecked(False)

mem = cm.pair({"thermal": th, "fea": fe})
ok(set(mem) == {"thermal", "structural"} and mem["thermal"].dim == 2 and mem["structural"].dim == 2, "pair(): a 2D thermal and a 2D structural window make one coupled pair")
res = ce.solve_coupled(mem)
ok(res["ok"], f"2D bar: the coupled solve is ok ({[c['name'] + ': ' + str(c['ok']) for c in res['checks']]})")
ok(all(c["ok"] for c in res["checks"]), "every check passes: " + "; ".join(f"{c['name']} - {c['detail']}" for c in res["checks"]))
near(res["thermal"]["T_mean"], 60.0 + K0, 1e-6, "mean temperature of the bar (K)")
near(res["thermal"]["T_min"], 20.0 + K0, 1e-6, "coldest")
near(res["thermal"]["T_max"], 100.0 + K0, 1e-6, "hottest")
fr = fe.result
u = np.asarray(fr["u"])
nodes = np.asarray(fe.mesh["nodes"], float)
xmax = nodes[:, 0].max()
right = np.where(np.abs(nodes[:, 0] - xmax) < 1e-9)[0]
near(float(u[right, 0].mean()), 12e-6 * 40.0 * 100.0, 0.01, "2D: the right end moves alpha (Tmean - Tref) L = 0.048 mm")
E = 200000.0
ok(float(np.max(fr["vm"])) < 0.12 * E * 12e-6 * 40.0, f"2D: the stress stays small, {float(np.max(fr['vm'])):.3g} MPa against the {E * 12e-6 * 40.0:.3g} MPa of a held bar")
ok(fr["thermal"] is not None and abs(fr["thermal"]["T_min"] - (20.0 + K0)) < 1e-6 and abs(fr["thermal"]["T_max"] - (100.0 + K0)) < 1e-6, "the stress result reports the temperature it was given")
ok(fe.coupled_in is None, "the structural window is left as it was (no temperature hook)")

# held bar: both ends fixed in x, the stress is E alpha (Tmean - Tref) (uniform part), about 96 MPa in x
fe.supports.clear()
fe.canvas.sel = [("ln", ls[3])]; fe.add_support("fixed")
fe.canvas.sel = [("ln", ls[1])]; fe.add_support("fixed")
res2 = ce.solve_coupled(cm.pair({"thermal": th, "fea": fe}))
ok(res2["ok"], "2D held bar: the coupled solve is ok")
sx = np.asarray(fe.result["sx"])
mat = fe.read_material()
E_mat = float(mat["E"]) if "E" in mat else E
near(float(np.median(sx)), -E_mat * 12e-6 * 40.0, 0.03, "2D held bar: the stress along the bar is -E alpha (Tmean - Tref), about -96 MPa (median over the bar)")
near(float(np.max(np.abs(np.asarray(fe.result["u"])[:, 0]))), 12e-6 * 80.0 * 100.0 / 8.0, 0.03, "2D held bar: the bar moves at most alpha (Tmax - Tmin) L / 8 = 0.012 mm along itself, at mid-length")

# what stops a solve is said in words
bad = ce.CoupledError
try:
    cm.pair({"thermal": th})
    ok(False, "pair(): a heat problem alone is refused")
except bad as ex:
    ok("stress problem" in str(ex), f"pair(): a heat problem alone is refused: '{ex}'")
try:
    cm.pair({"fea": fe})
    ok(False, "pair(): a stress problem alone is refused")
except bad as ex:
    ok("heat problem" in str(ex), f"pair(): a stress problem alone is refused: '{ex}'")

# ------------------------------------------------------------------------------------------------------------------------------------------ 3D
import solid_tab
import thermal3d_tab as t3
import thermal3d_example as ex

T = tempfile.mkdtemp(prefix="opara_cm_")
pf = os.path.join(T, "src")
os.makedirs(pf, exist_ok=True)
ex._part(os.path.join(pf, "bar.gpd"), [("rect", (0, 0), (100, 20))], 20, ex.AL)

wt = t3.ThermalWindow(threaded=False)
ok(wt.create_project(os.path.join(T, "bar.gpt")) is not False and wt.import_file(os.path.join(pf, "bar.gpd")) is not False, "3D: the thermal window has the block")
lo = ex.faces_of(wt.geom, normal=(-1, 0, 0))
hi = ex.faces_of(wt.geom, normal=(1, 0, 0))
ok(wt.add_condition("temps", {"T": 373.15}, lo, "Hot end") and wt.add_condition("temps", {"T": 293.15}, hi, "Cold end"), "3D: 100 degC on one end, 20 degC on the other")
wt.setup["analysis"] = "steady"
wt.refresh_lists()

ws = solid_tab.SolidWindow(threaded=False)
ok(ws.create_project(os.path.join(T, "bar.gps")) is not False and ws.import_file(os.path.join(pf, "bar.gpd")) is not False, "3D: the structural window has the same block")
sl = ex.faces_of(ws.geom, normal=(-1, 0, 0))
sy = ex.faces_of(ws.geom, normal=(0, -1, 0))
sz = ex.faces_of(ws.geom, normal=(0, 0, -1))
print("     faces:", len(sl), len(sy), len(sz))
ok(ws.add_support("disp", sl, {"ux": 0.0, "uy": None, "uz": None}) and ws.add_support("disp", sy, {"ux": None, "uy": 0.0, "uz": None})
   and ws.add_support("disp", sz, {"ux": None, "uy": None, "uz": 0.0}), "3D: three symmetry planes hold the block against rigid movement and nothing else")
ws.e_alpha.setText("1.2e-5")
ws.e_tref.setText("20")
ws.inputs_changed()

mem3 = cm.pair({"thermal3d": wt, "solid": ws})
ok(mem3["thermal"].dim == 3 and mem3["structural"].dim == 3, "pair(): a 3D thermal and a 3D structural window make one coupled pair")
try:
    cm.pair({"thermal": th, "solid": ws})
    ok(False, "pair(): a 2D heat problem with a 3D stress problem is refused")
except bad as ex_:
    ok("2D" in str(ex_) and "3D" in str(ex_), f"pair(): a 2D heat problem with a 3D stress problem is refused: '{ex_}'")
res3 = ce.solve_coupled(mem3)
print("     checks:", [(c["name"], c["ok"], c["detail"]) for c in res3["checks"]])
ok(res3["ok"] and all(c["ok"] for c in res3["checks"]), "3D bar: the coupled solve is ok and every check passes")
near(res3["thermal"]["T_mean"], 60.0 + K0, 1e-4, "3D: mean temperature (K)")
r3 = ws.result
n3, u3 = np.asarray(r3["nodes"], float), np.asarray(r3["u"], float)
end = np.abs(n3[:, 0] - n3[:, 0].max()) < 1e-6
near(float(u3[end, 0].mean()), 12e-6 * 40.0 * float(n3[:, 0].max() - n3[:, 0].min()), 0.02, "3D: the far end moves alpha (Tmean - Tref) L = 0.048 mm")
E3 = 68900.0
med3 = float(np.median(np.asarray(r3["vm_node"], float)))
print(f"     free block: median von Mises {med3:.3g} MPa, largest {float(r3['vm_max']):.3g} MPa (the end face is held along the block: a local stress at that end)")
ok(med3 < 0.1 * E3 * 12e-6 * 40.0, f"3D: the stress in the block stays small, median {med3:.3g} MPa against the {E3 * 12e-6 * 40.0:.3g} MPa of a held block")
ok(r3["thermal"] is not None and abs(r3["thermal"]["T_max"] - 373.15) < 1e-6, "3D: the stress result reports the temperature it was given")
ok(ws.coupled_in is None and wt.result is not None, "3D: the windows are left as they were")

ok(ws.add_support("disp", hi_s := ex.faces_of(ws.geom, normal=(1, 0, 0)), {"ux": 0.0, "uy": None, "uz": None}), "3D: the other end is held too")
res4 = ce.solve_coupled(cm.pair({"thermal3d": wt, "solid": ws}))
ok(res4["ok"], "3D held block: the coupled solve is ok")
vm4 = np.asarray(ws.result["vm_node"], float)
near(float(np.median(vm4)), E3 * 12e-6 * 40.0, 0.06, "3D held block: the stress is E alpha (Tmean - Tref), about 33 MPa (median over the block)")

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
