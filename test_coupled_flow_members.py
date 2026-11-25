"""Coupled Physics with a flow, through the real windows: the 2D Fluid Flow window with a 2D Thermal window (they exchange heat) and a 2D Static Structural window (it takes the
pressure), driven by coupled_members + coupled_engine on a 20 mm square in a slow air stream (0.03 m/s, Re 40).  The answers that are known:
  * a body so conductive that it is at one temperature: the wall temperature of the coupled edges is the temperature it is held at, and the heat they give is the heat of the
    same walls held at that temperature in the fluid window on its own (the limit of the conjugate problem);
  * a poor conductor: the heat falls with the conductivity (400 > 2 > 0.2 W/(m K)), the wall cools away from the heated edge, the heat that leaves the solid is the heat the fluid
    takes, the loop converges;
  * the pressure: the force the stress analysis carries is the force the fluid pushes with (two different meshes), in newtons once the thickness is in; the supported edge gets none;
  * the three together, the refusals in words, a cancelled solve, and the windows left as they were.
python test_coupled_flow_members.py"""
import faulthandler
faulthandler.dump_traceback_later(1700, exit=True)
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
import physics_cfd_heat as pheat
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


def square():
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (20, 0), (20, 20), (0, 20))]
    ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]       # 0 bottom, 1 right, 2 top, 3 left
    return m, ls


m, ls = square()
LEFT = ("ln", ls[3])

# ------------------------------------------------------------------------------------------------------------------------------------------ the windows
cf = cfd_tab.CFDTab(host())
cf.run_task = lambda title, fn: run_now(cf, title, fn)
cf.set_model(m, "a 20 mm square")
cf.e_speed.setText(f"{units.speed_from_si(0.03, cf.unit_name()):.6g}")
for e, v in ((cf.e_hb, "3"), (cf.e_hf, "12"), (cf.e_ml, "3"), (cf.e_mr, "8"), (cf.e_mb, "3"), (cf.e_mt, "3"), (cf.e_cfl, "2"), (cf.e_steps, "250"),
             (cf.e_tol, "1e-6"), (cf.e_ramp, "5"), (cf.e_every, "1000")):
    e.setText(v)
cf.cb_until.setChecked(False)
cf.cb_auto.setChecked(False)
cf.cb_heat.setChecked(True)
keys = sorted({e["src"] for e in cf.geom["edges"]})
others = [k for k in keys if k != LEFT]
cf.set_wall_condition([LEFT], "temp", "50")
cf.set_wall_condition(others, "coupled", "")
ok(cf.coupled_keys() == sorted(others) and len(others) == 3, f"the CFD window has three walls of the thermal analysis and one at 50 degC ({cf.coupled_keys()})")
cf.run_mesh()
ok(cf.mesh is not None, "the CFD window is meshed")

answers = []


def pick(t, fn, sel, *vals):
    t.canvas.sel = list(sel)
    tt.ask_values = lambda parent, title, note, labels, defaults: list(vals)
    getattr(t, fn)()


def new_thermal(k):
    th = tt.ThermalTab(host())
    th.run_task = lambda title, fn: run_now(th, title, fn)
    th.set_model(m, "a 20 mm square")
    pick(th, "add_temperature", [LEFT], 50.0)
    th.e_h.setText("2")
    th.e_t.setText("1")
    th.ensure_region_materials()
    for f in th.region_mats:
        th.region_mats[f]["k"] = k
    return th


def new_structural(held=(LEFT,)):
    fe = physics_tab.PhysicsTab(host())
    fe.run_task = lambda title, fn: run_now(fe, title, fn)
    fe.set_model(m, "a 20 mm square")
    for k in held:
        fe.canvas.sel = [k]
        fe.add_support("fixed")
    fe.e_alpha.setText("1.2e-5")
    fe.e_tref.setText("20")
    fe.e_h.setText("2")
    fe.cb_auto.setChecked(False)
    return fe


def untouched(th=None, fe=None, why=""):
    good = cf.coupled_flow_only is False and cf.worker is None
    if th is not None:
        good = good and th.coupled_fluid is None
    if fe is not None:
        good = good and fe.coupled_in is None and fe.coupled_cfd is None
    ok(good, f"the windows are left as they were {why}")


def checks_text(res):
    return "; ".join(f"{c['name']}: {c['ok']} ({c['detail']})" for c in res["checks"])


# ------------------------------------------------------------------------------------------------------------------------------------------ pair()
try:
    cm.pair({"cfd": cf})
    ok(False, "a fluid alone is refused")
except ce.CoupledError as ex:
    ok("Thermal" in str(ex) and "Structural" in str(ex), f"pair(): a fluid alone is refused in words: '{ex}'")
try:
    cm.pair({"cfd": cf, "thermal3d": object()})
    ok(False, "a 2D fluid with a 3D thermal analysis is refused")
except ce.CoupledError as ex:
    ok("2D" in str(ex) and "3D" in str(ex), f"pair(): a 2D fluid with a 3D thermal analysis is refused: '{ex}'")
th0 = new_thermal(400.0)
mem = cm.pair({"cfd": cf, "thermal": th0})
ok(set(mem) == {"fluid", "thermal"} and mem["fluid"].dim == 2, "pair(): a fluid and a thermal window make a fluid/thermal pair")
fe0 = new_structural()
mem = cm.pair({"cfd": cf, "fea": fe0, "thermal": th0})
ok(set(mem) == {"fluid", "thermal", "structural"}, "pair(): the three together")
mem = cm.pair({"thermal": th0, "fea": fe0})
ok(set(mem) == {"thermal", "structural"}, "pair(): without the fluid it is the pair of before")

# ------------------------------------------------------------------------------------------------------------------------------------------ A. a body that conducts so well it is one temperature
th = new_thermal(400.0)
t0 = time.time()
resA = ce.solve_coupled({"fluid": cm.Fluid2D(cf), "thermal": cm.Thermal2D(th)})
print(f"     {time.time() - t0:.0f} s")
ok(resA["ok"], "conductive body: the coupled solve is ok")
ok(all(c["ok"] for c in resA["checks"]), "conductive body: every check passes: " + checks_text(resA))
fA = resA["fluid"]
ok(fA["iterations"] <= 4, f"conductive body: the heat exchange converges in {fA['iterations']} iterations")
near(fA["Tw_min"], 50.0 + K0, 1e-4, "conductive body: the coldest wall point is at the temperature the body is held at (K)")
near(fA["Tw_max"], 50.0 + K0, 1e-6, "conductive body: and the hottest (K)")
res_flow = cf.result
base = cf.read_heat(allow_coupled=True)
allw = {k: {"kind": "temp", "T": 323.15} for k in keys}
ref = pheat.solve_temperature(cf.mesh, res_flow, dict(base, walls=allw))
Q_ref = sum(ref["walls"][k]["Q"] for k in others)
near(fA["Q_fluid"] / 1e-3, Q_ref, 2e-3, "conductive body: the heat the three walls give is that of the same walls held at 50 degC in the fluid window on its own (W per metre)")
near(fA["Q_solid"], fA["Q_fluid"], 0.02, "conductive body: the heat that leaves the solid is the heat the fluid takes (W)")
ok(abs(fA["balance"]["relative"]) < 0.01, f"conductive body: the fluid's energy balance closes ({100 * fA['balance']['relative']:.3f} %)")
ok(cf.result.get("heat") is not None and "Temperature" in cf.res_lbl.text(), "conductive body: the CFD window shows the temperature of the last pass")
tr = [t for t in resA["transfers"] if t["name"].startswith("Fluid")][0]
ok(tr["what"] == "heat exchange" and "degC" in tr["src_text"], f"conductive body: the transfer is listed with its numbers ({tr['src_text']} -> {tr['dst_text']})")
untouched(th=th, why="after the heat exchange")
QA = fA["Q_fluid"]

# ------------------------------------------------------------------------------------------------------------------------------------------ B. poorer conductors
Qs = {400.0: QA}
for k in (2.0, 0.2):
    th = new_thermal(k)
    res = ce.solve_coupled({"fluid": cm.Fluid2D(cf), "thermal": cm.Thermal2D(th)})
    f = res["fluid"]
    ok(res["ok"] and all(c["ok"] for c in res["checks"]), f"k = {k:g}: the coupled solve is ok, every check passes ({f['iterations']} iterations, mismatch {f['mismatch']:.1e})")
    ok(f["Tw_min"] < 50.0 + K0 - 0.5 and f["Tw_max"] <= 50.0 + K0 + 1e-6 and f["Tw_min"] > 20.0 + K0, f"k = {k:g}: the wall cools away from the heated edge ({f['Tw_min'] - K0:.2f} .. {f['Tw_max'] - K0:.2f} degC)") if k < 1 else \
        ok(f["Tw_min"] <= 50.0 + K0 + 1e-6 and f["Tw_min"] > 20.0 + K0, f"k = {k:g}: the wall is between the inlet and the held temperature ({f['Tw_min'] - K0:.2f} .. {f['Tw_max'] - K0:.2f} degC)")
    near(f["Q_solid"], f["Q_fluid"], 0.05, f"k = {k:g}: the heat that leaves the solid is the heat the fluid takes (W)")
    Qs[k] = f["Q_fluid"]
    untouched(th=th, why=f"after k = {k:g}")
    if k == 0.2:
        # the top edge (ln 6 is the third of the coupled keys in order): hotter near the heated left edge than at the far end
        Tw_top, _ = cm.Thermal2D(th).wall_temperature_at(np.array([[2.0, 20.0], [18.0, 20.0]]))
        ok(Tw_top[0] > Tw_top[1] + 0.5, f"k = {k:g}: along the top edge the wall is warmer near the heated edge ({Tw_top[0] - K0:.2f} degC) than at the far end ({Tw_top[1] - K0:.2f} degC)")
ok(Qs[400.0] > Qs[2.0] > Qs[0.2] > 0, f"the heat given to the fluid falls with the conductivity of the body: {Qs[400.0]:.4g} > {Qs[2.0]:.4g} > {Qs[0.2]:.4g} W")
ok(Qs[0.2] < 0.85 * Qs[400.0], f"and a body that conducts 2000 times worse (Biot number about 0.5) gives clearly less, {Qs[0.2] / Qs[400.0]:.2f} of it: its rear walls sit in the warmed wake")

# ------------------------------------------------------------------------------------------------------------------------------------------ C. the pressure on a stress analysis
fe = new_structural()
resC = ce.solve_coupled({"fluid": cm.Fluid2D(cf), "structural": cm.Structural2D(fe)})
ok(resC["ok"], "pressure: the coupled solve is ok")
ok(all(c["ok"] for c in resC["checks"]), "pressure: every check passes: " + checks_text(resC))
trp = [t for t in resC["transfers"] if t["what"] == "pressure"][0]
ok(sorted(trp["edges"]) == sorted(others), f"pressure: the three free edges got it, the supported edge did not ({trp['edges']})")
rep = cm.Structural2D(fe).pressure_report()
F_cfd, S_cfd = cm.Fluid2D(cf).pressure_force(rep["edges"])
dev = float(np.hypot(rep["force"][0] - F_cfd[0], rep["force"][1] - F_cfd[1])) / S_cfd
ok(dev < 0.02, f"pressure: the force the stress analysis carries ({rep['force'][0]:.4g}, {rep['force'][1]:.4g}) N/m is the fluid's ({F_cfd[0]:.4g}, {F_cfd[1]:.4g}); difference {100 * dev:.2f} % of the load")
ok(S_cfd > 0 and float(np.hypot(*F_cfd)) > 0, f"pressure: there is a force to carry ({S_cfd:.4g} N/m of pressure on the walls)")
eq = fe.result["equilibrium"]
th_m = 1e-3
tol_N = 0.03 * S_cfd * th_m
ok(abs(eq["applied"]["fx"] - F_cfd[0] * th_m) < tol_N and abs(eq["applied"]["fy"] - F_cfd[1] * th_m) < tol_N,
   f"pressure: in newtons (1 mm thick) the applied force is ({eq['applied']['fx']:.4g}, {eq['applied']['fy']:.4g}) against the fluid's ({F_cfd[0] * th_m:.4g}, {F_cfd[1] * th_m:.4g})")
ok(abs(eq["sum_fx"]) < 1e-6 * S_cfd * th_m + 1e-12 and abs(eq["sum_fy"]) < 1e-6 * S_cfd * th_m + 1e-12, "pressure: the plate is in equilibrium with its support (the reaction balances the load)")
ok(fe.result.get("thermal") is None, "pressure: no temperature was handed over (there is no thermal analysis)")
untouched(fe=fe, why="after the pressure solve")
ok(cf.result["status"] == "converged", "pressure: the CFD window keeps its flow result")

# shear on or off is the user's choice: with the shear the force is the fluid's pressure and shear
F_s, _ = cm.Fluid2D(cf).pressure_force(rep["edges"], shear=True)
ok(abs(F_s[0] - F_cfd[0]) > 1e-12 or abs(F_s[1] - F_cfd[1]) > 1e-12, "the wall shear adds its own force to the pressure force")

# every edge held: nothing for the fluid to push on
feall = new_structural(held=keys)
try:
    ce.solve_coupled({"fluid": cm.Fluid2D(cf), "structural": cm.Structural2D(feall)})
    ok(False, "a stress analysis with every edge held gets no pressure and says so")
except ce.CoupledError as ex:
    ok("no fluid pressure" in str(ex), f"every edge held: refused in words: '{ex}'")
untouched(fe=feall, why="after the refusal")

# ------------------------------------------------------------------------------------------------------------------------------------------ D. the three together
th = new_thermal(2.0)
fe = new_structural()
resD = ce.solve_coupled({"fluid": cm.Fluid2D(cf), "thermal": cm.Thermal2D(th), "structural": cm.Structural2D(fe)})
ok(resD["ok"] and all(c["ok"] for c in resD["checks"]), "three together: the coupled solve is ok, every check passes: " + checks_text(resD))
names = [c["name"] for c in resD["checks"]]
ok("Stress solve used the field" in names and "Pressure force handed over" in names and "Heat exchange converged" in names, f"three together: the checks of the heat, the temperature hand-over and the pressure are all there ({names})")
ok(fe.result["thermal"] is not None and fe.result.get("cfd_tally"), "three together: the stress result has the temperature field and the pressure")
fD = resD["fluid"]
ok(abs(fe.result["thermal"]["T_max"] - resD["thermal"]["T_max"]) < 1e-6, f"three together: the stress analysis was given the temperature of the solid ({resD['thermal']['T_min'] - K0:.1f} .. {resD['thermal']['T_max'] - K0:.1f} degC)")
um = float(np.max(np.hypot(fe.result["u"][:, 0], fe.result["u"][:, 1])))
ok(um > 0, f"three together: the plate moves, {um:.3g} mm at most (expansion 1.2e-5 per K and a few kelvin; the pressure is of the order of a millipascal)")
untouched(th=th, fe=fe, why="after the three")

# ------------------------------------------------------------------------------------------------------------------------------------------ E. what stops a solve is said in words
cf.remove_wall_conditions(others)
th = new_thermal(400.0)
try:
    ce.solve_coupled({"fluid": cm.Fluid2D(cf), "thermal": cm.Thermal2D(th)})
    ok(False, "no wall of the thermal analysis is refused")
except ce.CoupledError as ex:
    ok("no wall of the thermal analysis" in str(ex), f"no coupled wall is refused in words: '{ex}'")
untouched(th=th, why="after that refusal")
cf.set_wall_condition(others, "coupled", "")
cf.cb_heat.setChecked(False)
try:
    ce.solve_coupled({"fluid": cm.Fluid2D(cf), "thermal": cm.Thermal2D(th)})
    ok(False, "heat transfer off is refused")
except ce.CoupledError as ex:
    ok("heat transfer is switched off" in str(ex) or "no wall of the thermal analysis" in str(ex), f"heat transfer switched off is refused in words: '{ex}'")
cf.cb_heat.setChecked(True)
untouched(th=th, why="after the second refusal")

# ------------------------------------------------------------------------------------------------------------------------------------------ F. a cancelled solve
flag = {"stop": False}


def progress(text, frac):
    if "solving the flow" in text:
        flag["stop"] = True


th = new_thermal(400.0)
try:
    ce.solve_coupled({"fluid": cm.Fluid2D(cf), "thermal": cm.Thermal2D(th)}, progress=progress, cancel=lambda: flag["stop"])
    ok(False, "a cancelled solve raises Cancelled")
except ce.Cancelled:
    ok(True, "a cancelled solve raises Cancelled")
ok(cf.worker is None, "the flow solver was stopped, not left running")
untouched(th=th, why="after the cancel")

# ------------------------------------------------------------------------------------------------------------------------------------------ G. mutation: a stress window that gets nothing from the fluid fails the pressure check
fe = new_structural()


class Lying(cm.Structural2D):
    def pressure_report(self):
        r = super().pressure_report()
        r["force"] = (0.5 * r["force"][0], 0.5 * r["force"][1])
        return r


resG = ce.solve_coupled({"fluid": cm.Fluid2D(cf), "structural": Lying(fe)})
ok(not resG["ok"] and any(c["name"] == "Pressure force handed over" and not c["ok"] for c in resG["checks"]),
   "mutation: a stress window that reports half the force fails the pressure check (the check can fail)")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    for f_ in FAILS:
        print("  -", f_)
    sys.exit(1)
print("all ok")
