"""Coupled Physics with a 3D flow, through the real windows: the 3D Fluid Flow window with a 3D Thermal window (they exchange heat) and a 3D Static Structural window (it takes the
pressure), driven by coupled_members + coupled_engine on an aluminium block of 30 x 10 x 10 mm in a slow air stream (0.06 m/s, Reynolds number about 40).  The answers that are known:
  * a body so conductive that it is at one temperature: the wall temperature of the coupled faces is the temperature it is held at, and the heat they give is the heat of the same walls
    held at that temperature in the fluid window on its own (the limit of the conjugate problem);
  * a poor conductor: the heat falls with the conductivity, the wall cools away from the hot end, the heat that leaves the solid is the heat the fluid takes, the loop converges;
  * the pressure: the force the stress analysis carries is the force the fluid pushes with (two different meshes), the supported face gets none, the body is in equilibrium;
  * the three together, a structure that moves the flow, the refusals in words, a cancelled solve, a check that can fail, and the windows left as they were.
The checks that depend on the mesh of the flow (its energy balance, the small undershoot of the temperature) are soft by design: they are expected to be the only ones that fail on the
coarse fluid mesh used here, and a test of that is below.      python test_coupled_flow3d_members.py"""
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
sys.path[:0] = [HERE, SIM] + [os.path.join(HERE, "dev_addons", d) for d in ("solid_fea", "thermal2d", "thermal3d", "cfd3d", "coupled")] + [os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
MSGS = []
for _n in ("warning", "information", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: MSGS.append(str(a[2]) if len(a) > 2 else "")))

import unitctl
import thermal3d_tab as t3
import thermal3d_example as tex
import cfd3d_tab as ft
import cfd3d_model as cfm
import solid_tab
import coupled_engine as ce
import coupled_members as cm

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, rel, text, ab=0.0):
    ok(abs(a - b) <= rel * abs(b) + ab, f"{text}: {a:.6g} against {b:.6g}")


unitctl.set_units("Metric (mm, kg, N, s, MPa)", notify=False, persist=False)
K0 = 273.15
T = tempfile.mkdtemp(prefix="opara_c3_")
SRC = os.path.join(T, "src")
os.makedirs(SRC)
PART = os.path.join(SRC, "blk.gpd")
tex._part(PART, [("rect", (0, 0), (30, 10))], 10, tex.AL)
PART2 = os.path.join(SRC, "tall.gpd")
tex._part(PART2, [("rect", (0, 0), (30, 10))], 14, tex.AL)
_n = [0]


def path(ext):
    _n[0] += 1
    return os.path.join(T, f"w{_n[0]}.{ext}")


def face(win, normal):
    return next(int(f["id"]) for f in win.geom["faces"] if np.allclose(f["normal"], normal, atol=1e-6))


def new_fluid(exch=True, heat=True, size="2.5", part=PART):
    w = ft.FluidWindow(threaded=False)
    assert w.create_project(path("gpw")) is not False and w.import_file(part) is not False
    w.setup["flow"].update({"speed": 0.06, "dir": "+x", "heat": heat, "T_in": 293.15})
    if exch:
        w.add_condition("exch", {}, [i for i in range(6) if i != face(w, [-1, 0, 0])], "Wall of the thermal analysis")
    w.fill_part_sizes()
    w.set_size(size)
    w.put_physics()
    w.refresh_lists()
    return w


def new_thermal(k, size=None, part=PART):
    w = t3.ThermalWindow(threaded=False)
    assert w.create_project(path("gpt")) is not False and w.import_file(part) is not False
    w.add_condition("temps", {"T": 343.15}, [face(w, [-1, 0, 0])], "Hot end")
    w.setup["analysis"] = "steady"
    w.e_k.setText(str(k))
    w.inputs_changed()
    if size:
        w.set_size(size)
    w.refresh_lists()
    return w


def new_solid(held=None, E=None, part=PART):
    w = solid_tab.SolidWindow(threaded=False)
    assert w.create_project(path("gps")) is not False and w.import_file(part) is not False
    for f in (held if held is not None else [face(w, [1, 0, 0])]):
        w.add_support("fixed", [f])
    w.e_alpha.setText("2.3e-5")
    w.e_tref.setText("20")
    if E is not None:
        w.e_E.setText(str(E))
    w.inputs_changed()
    return w


def untouched(wf=None, wt=None, ws=None, why=""):
    good = True
    if wf is not None:
        good = good and wf.coupled_nodes is None and getattr(wf, "job", None) is None
    if wt is not None:
        good = good and wt.coupled_fluid is None
    if ws is not None:
        good = good and ws.coupled_in is None and ws.coupled_fluid is None
    ok(good, f"the windows are left as they were {why}")


def checks_text(res):
    return "; ".join(f"{c['name']}: {c['ok']} ({c['detail']})" for c in res["checks"])


def hard_ok(res):
    return all(c["ok"] for c in res["checks"] if c["hard"])


SOFT = {"Fluid energy balance", "Temperature inside the given range"}          # the checks that depend on the mesh of the flow: they may fail on a coarse one


def only_soft_fail(res):
    return {c["name"] for c in res["checks"] if not c["ok"]} <= SOFT


def solve(members, **kw):
    t0 = time.time()
    res = ce.solve_coupled(members, **kw)
    print(f"     {time.time() - t0:.0f} s")
    return res


# ------------------------------------------------------------------------------------------------------------------------------------------ the windows, and pair()
wf = new_fluid()
HOT = face(wf, [-1, 0, 0])
SIDES = [i for i in range(6) if i != HOT]
ok(not wf.ready(), "the 3D Fluid Flow window is ready")
ok(cm.Fluid3D(wf).coupled_keys() == SIDES, f"the fluid window has five faces of the thermal analysis and the hot end free ({cm.Fluid3D(wf).coupled_keys()})")
wt0, ws0 = new_thermal(400.0), new_solid()
try:
    cm.pair({"fluid3d": wf})
    ok(False, "a fluid alone is refused")
except ce.CoupledError as ex:
    ok("3D Thermal" in str(ex) and "Static Structural" in str(ex), f"pair(): a fluid alone is refused in words: '{ex}'")
for kw, label in (({"fluid3d": wf, "thermal": object()}, "a 3D fluid with a 2D thermal analysis"), ({"fluid3d": wf, "fea": object()}, "a 3D fluid with a 2D structural analysis"),
                  ({"cfd": object(), "thermal3d": wt0}, "a 2D fluid with a 3D thermal analysis"), ({"cfd": object(), "solid": ws0}, "a 2D fluid with a 3D structural analysis")):
    try:
        cm.pair(kw)
        ok(False, f"{label} is refused")
    except ce.CoupledError as ex:
        ok("same dimension" in str(ex), f"pair(): {label} is refused in words: '{str(ex)[:110]}'")
mem = cm.pair({"fluid3d": wf, "thermal3d": wt0})
ok(set(mem) == {"fluid", "thermal"} and mem["fluid"].dim == 3 and mem["thermal"].dim == 3 and mem["fluid"].label == "3D Fluid Flow", "pair(): a 3D fluid and a 3D thermal window make a fluid/thermal pair")
ok(set(cm.pair({"fluid3d": wf, "solid": ws0})) == {"fluid", "structural"}, "pair(): a 3D fluid and a 3D structural window make a fluid/structural pair")
ok(set(cm.pair({"fluid3d": wf, "solid": ws0, "thermal3d": wt0})) == {"fluid", "thermal", "structural"}, "pair(): the three together")
ok(set(cm.pair({"thermal3d": wt0, "solid": ws0})) == {"thermal", "structural"}, "pair(): without the fluid it is the pair of before")
ok(cm.wrap("fluid3d", wf).role == "fluid" and cm.wrap("fluid3d", wf).dim == 3, "wrap(): a 3D fluid window is a fluid member of dimension 3")

# ------------------------------------------------------------------------------------------------------------------------------------------ the fluid on its own: the reference
print("-- the flow on its own")
wf.run_solve()
r0 = wf.result
ok(r0 is not None and r0["status"] == "converged", f"the flow converges on its own ({r0['steps']} steps, {len(r0['mesh']['nodes'])} nodes)")
Q_ref, Q_wall = None, None
hot_ref, wall_ref = cfm.solve_wall_heat(r0, SIDES, 343.15)
Q_ref = float(wall_ref["Q"])
ok(Q_ref > 0, f"five faces of the block held at 70 degC give the air {Q_ref:.4f} W")
F_ref, S_ref = cfm.pressure_force(r0, SIDES)
ok(F_ref[0] > 0 and S_ref > 0, f"and the pressure pushes it downstream with {F_ref[0]:.4g} N")
wf.result = None                                                                    # (the windows below solve again)

# ------------------------------------------------------------------------------------------------------------------------------------------ A. a body that conducts so well it is one temperature
print("-- a conductive body")
wt = new_thermal(400.0)
resA = solve({"fluid": cm.Fluid3D(wf), "thermal": cm.Thermal3D(wt)})
fA = resA["fluid"]
ok(resA["ok"] and hard_ok(resA), "conductive body: the coupled solve is ok, every hard check passes: " + checks_text(resA))
ok(only_soft_fail(resA), f"conductive body: only checks that depend on the fluid mesh may fail ({[c['name'] for c in resA['checks'] if not c['ok']]})")
ok(fA["iterations"] <= 3, f"conductive body: the heat exchange converges in {fA['iterations']} iterations")
near(fA["Tw_max"], 343.15, 1e-5, "conductive body: the hottest wall point is the temperature the end is held at (K)")
ok(fA["Tw_max"] - fA["Tw_min"] < 0.5, f"conductive body: the whole wall is within {fA['Tw_max'] - fA['Tw_min']:.3f} K of it")
near(fA["Q_fluid"], Q_ref, 0.03, "conductive body: the heat the five faces give is that of the same faces held at 70 degC in the fluid window on its own (W)")
near(fA["Q_solid"], fA["Q_fluid"], 0.02, "conductive body: the heat that leaves the solid is the heat the fluid takes (W)")
tr = [t for t in resA["transfers"] if t["what"] == "heat exchange"][0]
ok("degC" in tr["src_text"] and "wall" in tr["dst_text"], f"conductive body: the transfer is listed with its numbers ({tr['src_text']} -> {tr['dst_text']})")
ok(tr["max_gap"] < 1e-6, f"conductive body: the two meshes have the same wall: the largest gap is {tr['max_gap']:.1e} mm")
ok(wf.result is not None and wf.result.get("heat") is not None and abs(float(np.max(wf.result["T"])) - 343.15) < 1e-6, "conductive body: the fluid window shows the temperature of the last pass")
untouched(wf, wt, why="after the heat exchange")
QA = fA["Q_fluid"]

# ------------------------------------------------------------------------------------------------------------------------------------------ B. poorer conductors
print("-- poorer conductors")
Qs = {400.0: QA}
Tmin = {400.0: fA["Tw_min"]}
for k in (5.0, 0.5):
    wt = new_thermal(k)
    res = solve({"fluid": cm.Fluid3D(wf), "thermal": cm.Thermal3D(wt)})
    f = res["fluid"]
    ok(res["ok"] and hard_ok(res) and only_soft_fail(res), f"k = {k:g}: the coupled solve is ok, the hard checks pass ({f['iterations']} iterations, mismatch {f['mismatch']:.1e})")
    ok(f["Tw_min"] > 293.15 and f["Tw_max"] <= 343.15 + 1e-6, f"k = {k:g}: the wall is between the inlet and the held temperature ({f['Tw_min'] - K0:.2f} .. {f['Tw_max'] - K0:.2f} degC)")
    near(f["Q_solid"], f["Q_fluid"], 0.05, f"k = {k:g}: the heat that leaves the solid is the heat the fluid takes (W)")
    Qs[k], Tmin[k] = f["Q_fluid"], f["Tw_min"]
    untouched(wf, wt, why=f"after k = {k:g}")
    if k == 0.5:
        rr = wt.result
        Pn, Tn = np.asarray(rr["nodes"], float), np.asarray(rr["T"], float)
        on_top = Pn[:, 2] > 10.0 - 1e-6
        band = [Tn[on_top & (Pn[:, 0] >= lo) & (Pn[:, 0] <= hi)].mean() for lo, hi in ((0, 8), (8, 16), (16, 24), (24, 30))]
        ok(np.all(np.diff(band) < 0) and band[0] - band[-1] > 5.0, f"k = {k:g}: along the top face the wall cools away from the hot end ({', '.join(f'{t - K0:.1f}' for t in band)} degC in four bands from the hot end)")
ok(Qs[400.0] > Qs[5.0] > Qs[0.5] > 0, f"the heat given to the fluid falls with the conductivity of the body: {Qs[400.0]:.4g} > {Qs[5.0]:.4g} > {Qs[0.5]:.4g} W")
ok(Tmin[400.0] > Tmin[5.0] > Tmin[0.5], f"and so does the coldest wall point: {Tmin[400.0] - K0:.1f} > {Tmin[5.0] - K0:.1f} > {Tmin[0.5] - K0:.1f} degC")

# ------------------------------------------------------------------------------------------------------------------------------------------ C. the pressure on a stress analysis
print("-- the pressure on a structure")
ws = new_solid()
fmC, smC = cm.Fluid3D(wf), cm.Structural3D(ws)
resC = solve({"fluid": fmC, "structural": smC})
ok(resC["ok"] and hard_ok(resC), "pressure: the coupled solve is ok, every hard check passes: " + checks_text(resC))
trp = [t for t in resC["transfers"] if t["what"] == "pressure"][0]
SUP = face(ws, [1, 0, 0])
ok(sorted(trp["edges"]) == sorted(i for i in range(6) if i != SUP), f"pressure: five faces got it, the supported one did not ({trp['edges']})")
rep = smC.pressure_report()
F_cfd, S_cfd = fmC.pressure_force(rep["edges"])
dev = float(np.linalg.norm(np.array(rep["force"]) - np.array(F_cfd))) / S_cfd
ok(dev < 0.02, f"pressure: the force the stress analysis carries ({rep['force'][0]:.4g}, {rep['force'][1]:.3g}, {rep['force'][2]:.3g}) N is the fluid's ({F_cfd[0]:.4g}, {F_cfd[1]:.3g}, {F_cfd[2]:.3g}); difference {100 * dev:.2f} % of the load")
ok(rep["same_geometry"] and not rep["differs"] and rep["gap"] < 0.1, f"pressure: the two analyses number the faces the same way and their walls lie on each other ({rep['gap']:.3f} element sizes)")
ok(F_cfd[0] > 0 and abs(F_cfd[1]) < 0.05 * F_cfd[0] and abs(F_cfd[2]) < 0.05 * F_cfd[0], "pressure: the force pushes the block downstream and hardly sideways")
r = ws.result
res_sum = np.array(r["applied"]) + np.array(r["reaction"])
ok(np.linalg.norm(res_sum) < 2e-3 * np.linalg.norm(r["applied"]), f"pressure: the block is in equilibrium with its support (load {np.linalg.norm(r['applied']):.3g} N, left over {np.linalg.norm(res_sum):.2g} N)")
ok(r.get("thermal") is None and r.get("fluid") is not None, "pressure: no temperature was handed over (there is no thermal analysis), the pressure was")
ok(float(r["fluid"]["p_max"]) > float(r["fluid"]["p_min"]), f"pressure: it is a field and not a number ({r['fluid']['p_min']:.3g} .. {r['fluid']['p_max']:.3g} Pa)")
untouched(wf, ws=ws, why="after the pressure solve")
ok(wf.result is not None and wf.result["status"] == "converged", "pressure: the fluid window keeps its flow result")
F_s = None
try:
    fmC.pressure_force(rep["edges"], shear=True)
    ok(False, "the friction cannot be handed over yet")
except ce.CoupledError as ex:
    ok("friction" in str(ex), f"the friction of the flow is refused in words: '{ex}'")

# every face held: nothing for the fluid to push on
wsall = new_solid(held=list(range(6)))
try:
    solve({"fluid": cm.Fluid3D(wf), "structural": cm.Structural3D(wsall)})
    ok(False, "a stress analysis with every face held gets no pressure and says so")
except ce.CoupledError as ex:
    ok("no fluid pressure" in str(ex) and "CoupledError" not in str(ex) and str(ex).count("3D Static Structural") == 1, f"every face held: refused in words: '{ex}'")
untouched(wf, ws=wsall, why="after the refusal")

# the structure of another shape than the fluid's part
wsx = new_solid(part=PART2)
try:
    resX = solve({"fluid": cm.Fluid3D(wf), "structural": cm.Structural3D(wsx)})
    bad = [c for c in resX["checks"] if not c["ok"] and c["hard"]]
    ok(not resX["ok"] and bad, f"a body of another height than the one the fluid flows round is not accepted: {[c['name'] for c in bad]}")
except ce.CoupledError as ex:
    ok(True, f"a body of another height than the one the fluid flows round is refused: '{str(ex)[:120]}'")
untouched(wf, ws=wsx, why="after the other body")

# ------------------------------------------------------------------------------------------------------------------------------------------ D. the three together
print("-- the three together")
wt = new_thermal(5.0)
ws = new_solid()
smD = cm.Structural3D(ws)
resD = solve({"fluid": cm.Fluid3D(wf), "thermal": cm.Thermal3D(wt), "structural": smD})
ok(resD["ok"] and hard_ok(resD) and only_soft_fail(resD), "three together: the coupled solve is ok, the hard checks pass: " + checks_text(resD))
names = [c["name"] for c in resD["checks"]]
ok("Stress solve used the field" in names and "Pressure force handed over" in names and "Heat exchange converged" in names, f"three together: the checks of the heat, the temperature hand-over and the pressure are all there ({names})")
r = ws.result
ok(r["thermal"] is not None and r.get("fluid") is not None, "three together: the stress result has the temperature field and the pressure")
ok(abs(r["thermal"]["T_max"] - resD["thermal"]["T_max"]) < 1e-6, f"three together: the stress analysis was given the temperature of the solid ({resD['thermal']['T_min'] - K0:.1f} .. {resD['thermal']['T_max'] - K0:.1f} degC)")
nn, uu = np.asarray(r["nodes"], float), np.asarray(r["u"], float)
free = nn[:, 0] < 1e-6                                                              # the end that is not held (the held one is the downstream end)
grow = -float(uu[free, 0].mean())
want = 2.3e-5 * 30.0 * (resD["thermal"]["T_mean"] - (20.0 + K0))
ok(abs(grow - want) < 0.05 * want, f"three together: the free end of the block moves back by {grow:.5f} mm; alpha L (Tmean - Tref) = 2.3e-5 x 30 x {resD['thermal']['T_mean'] - 20.0 - K0:.2f} = {want:.5f} mm (the pressure is a few nanonewtons)")
untouched(wf, wt, ws, why="after the three")

# ------------------------------------------------------------------------------------------------------------------------------------------ E. a structure that moves the flow
print("-- a structure that moves the flow")
ws = new_solid(E=4e-7)
t0 = time.time()
resE = solve({"fluid": cm.Fluid3D(wf), "structural": cm.Structural3D(ws)}, options={"moves_flow": True})
fs = resE.get("fsi")
ok(resE["ok"] and hard_ok(resE) and fs is not None, "moved flow: the coupled solve is ok, the hard checks pass: " + checks_text(resE))
ok(fs["converged"] and 2 <= len(fs["history"]) <= 8, f"moved flow: the structure and the flow settle ({len(fs['history'])} passes)")
h = fs["history"]
ok(h[0]["it"] == 1 and h[0]["umax"] > 0 and [row["it"] for row in h] == list(range(1, len(h) + 1)), "moved flow: pass 1 is the flow round the body as drawn, the passes are listed")
ok(all(row["mesh"]["cells"] == h[0]["mesh"]["cells"] for row in h), f"moved flow: every pass is on the same {h[0]['mesh']['cells']} tetrahedra (nothing is meshed again)")
ok(not h[0]["mesh"]["moved"] and all(row["mesh"]["moved"] for row in h[1:]), "moved flow: the first pass is on the mesh as drawn, the others on the moved one")
um = float(np.max(np.linalg.norm(ws.result["u"], axis=1)))
ok(um > 0.01 and abs(um - fs["umax"]) < 0.2 * um, f"moved flow: the soft body moves, {um:.3g} mm at most (E = 4e-7 MPa; the pressure of a slow stream is a few millipascal, so a body that moves visibly has to be this soft)")
shr = min(row["mesh"]["shrink"] for row in h[1:])
ok(shr > 0.5, f"moved flow: the air mesh follows without a tetrahedron losing more than half its volume ({shr:.3f} of the smallest)")
ok(fs["umax"] <= 0.05 * fs["size"] and fs["gap"] < 0.5, f"moved flow: the displacement is {100 * fs['umax'] / fs['size']:.3g} % of the body (small enough for the linear stress analysis) and the outline lies on the stress mesh")
untouched(wf, ws=ws, why="after the moved flow")
print(f"     {time.time() - t0:.0f} s")
wsr = new_solid(E=70000.0)
resR = solve({"fluid": cm.Fluid3D(wf), "structural": cm.Structural3D(wsr)}, options={"moves_flow": True})
ok(resR["ok"] and resR["fsi"]["converged"] and len(resR["fsi"]["history"]) <= len(resE["fsi"]["history"]), f"moved flow: an aluminium body hardly moves the flow and settles at once ({len(resR['fsi']['history'])} passes)")
untouched(wf, ws=wsr, why="after the stiff body")

# ------------------------------------------------------------------------------------------------------------------------------------------ E2. the heat exchange on a flow that was moved
print("-- heat exchange on a flow solved round a moved part")
import coupled_fluid3d as cf3
wt = new_thermal(400.0)
fmv, tmv = cm.Fluid3D(wf), cm.Thermal3D(wt)
bp = fmv.boundary_points()
Pb = bp["P"]
fmv.set_shape(None)
r_as = cf3.solve_fluid_thermal3d(fmv, tmv)
tmv.release()
ref_nodes = np.asarray(bp["q"]["nodes"], float)
for name, D, lim in (("shifted sideways by 0.2 mm", np.tile([0.0, 0.2, 0.0], (len(Pb), 1)), 0.01),
                     ("shortened by 0.18 mm (the upstream end moves in)", np.stack([0.18 * (1.0 - Pb[:, 0] / 30.0), 0.0 * Pb[:, 0], 0.0 * Pb[:, 0]], axis=1), 0.02)):
    fmv.set_shape(D)
    rm = cf3.solve_fluid_thermal3d(fmv, tmv)
    surf = fmv.wall_surface()
    ok(np.allclose(surf["points"], ref_nodes[surf["nodes"]]), f"{name}: the wall is handed over at the places of the material points (the part as drawn)")
    ok(not np.allclose(np.asarray(fmv._res["mesh"]["nodes"], float)[surf["nodes"]], surf["points"]), f"{name}: the flow itself has the part moved")
    ok(abs(rm["Q_rel"]) < lim, f"{name}: the heat that leaves the solid and the heat the fluid takes differ by {100 * abs(rm['Q_rel']):.2f} % (limit {100 * lim:g} %)")
    ok(rm["gap_fluid"] < 0.02 and rm["gap_solid"] < 0.02, f"{name}: no gap between the walls ({rm['gap_fluid']:.3f} and {rm['gap_solid']:.3f} element sizes)")
    near(rm["Q_fluid"], r_as["Q_fluid"], 0.01, f"{name}: the heat of the fluid hardly changes (W)")
    tmv.release()
    fmv.release()
untouched(wf, wt, why="after the moved heat exchange")

# ------------------------------------------------------------------------------------------------------------------------------------------ F. what stops a solve is said in words
print("-- refusals")
wf_no = new_fluid(exch=False)
wt = new_thermal(400.0)
try:
    solve({"fluid": cm.Fluid3D(wf_no), "thermal": cm.Thermal3D(wt)})
    ok(False, "no wall of the thermal analysis is refused")
except ce.CoupledError as ex:
    ok("wall of the thermal analysis" in str(ex), f"no coupled wall is refused in words: '{ex}'")
untouched(wf_no, wt, why="after that refusal")
wf_off = new_fluid(heat=False)
try:
    solve({"fluid": cm.Fluid3D(wf_off), "thermal": cm.Thermal3D(wt)})
    ok(False, "heat transfer off is refused")
except ce.CoupledError as ex:
    ok("heat transfer is switched off" in str(ex), f"heat transfer switched off is refused in words: '{ex}'")
untouched(wf_off, wt, why="after the second refusal")
wf_x = new_fluid()
wf_x.geom = None
try:
    solve({"fluid": cm.Fluid3D(wf_x), "thermal": cm.Thermal3D(wt)})
    ok(False, "no part is refused")
except ce.CoupledError as ex:
    ok("no part" in str(ex), f"a fluid window with no part is refused in words: '{ex}'")
wt_tall = new_thermal(400.0, part=PART2)
try:
    r_ = solve({"fluid": cm.Fluid3D(wf), "thermal": cm.Thermal3D(wt_tall)})
    bad = [c for c in r_["checks"] if not c["ok"] and c["hard"]]
    ok(not r_["ok"] and bad, f"a thermal body of another height than the one in the flow is not accepted: {[c['name'] for c in bad]}")
except ce.CoupledError as ex:
    ok(True, f"a thermal body of another height than the one in the flow is refused: '{str(ex)[:120]}'")
untouched(wf, wt_tall, why="after the other body")

# ------------------------------------------------------------------------------------------------------------------------------------------ G. a cancelled solve
print("-- cancel")
flag = {"stop": False}


def progress(text, frac):
    if "solving the flow" in text:
        flag["stop"] = True


wt = new_thermal(400.0)
try:
    ce.solve_coupled({"fluid": cm.Fluid3D(wf), "thermal": cm.Thermal3D(wt)}, progress=progress, cancel=lambda: flag["stop"])
    ok(False, "a cancelled solve raises Cancelled")
except ce.Cancelled:
    ok(True, "a cancelled solve raises Cancelled")
untouched(wf, wt, why="after the cancel")
flag["stop"] = False


def progress2(text, frac):
    if "iteration 1" in text and "the fluid" in text:
        flag["stop"] = True


try:
    ce.solve_coupled({"fluid": cm.Fluid3D(wf), "thermal": cm.Thermal3D(wt)}, progress=progress2, cancel=lambda: flag["stop"])
    ok(False, "a solve cancelled in the middle of the heat exchange raises Cancelled")
except ce.Cancelled:
    ok(True, "a solve cancelled in the middle of the heat exchange raises Cancelled")
untouched(wf, wt, why="after the second cancel")

# ------------------------------------------------------------------------------------------------------------------------------------------ H. mutation: the checks can fail
print("-- the checks can fail")
ws = new_solid()


class LyingStructure(cm.Structural3D):
    def pressure_report(self):
        r = super().pressure_report()
        r["force"] = tuple(0.5 * v for v in r["force"])
        return r


resH = solve({"fluid": cm.Fluid3D(wf), "structural": LyingStructure(ws)})
ok(not resH["ok"] and any(c["name"] == "Pressure force handed over" and not c["ok"] for c in resH["checks"]), "mutation: a stress window that reports half the force fails the pressure check")
wt = new_thermal(400.0)


class LyingThermal(cm.Thermal3D):
    def heat_to_fluid(self):
        return 0.5 * super().heat_to_fluid()


resI = solve({"fluid": cm.Fluid3D(wf), "thermal": LyingThermal(wt)})
ok(not resI["ok"] and any(c["name"].startswith("Heat leaving the solid") and not c["ok"] for c in resI["checks"]), "mutation: a thermal window that reports half the heat fails the heat balance between the two")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    for f_ in FAILS:
        print("  -", f_)
    sys.exit(1)
print("all ok")
