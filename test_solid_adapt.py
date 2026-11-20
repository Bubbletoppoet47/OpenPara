"""3D FEA, adaptive mesh (h-type): the settings, the error estimate (exact where the stress is constant, its energy adds up), loops that settle on known
answers (a cantilever, a thick cylinder under pressure, two bonded bars) with fewer elements than a uniform mesh, the reasons they stop (converged, most
loops, size limit, smallest size, cancel), what is refused (hex-dominant), the window (tick box, menu, report, error colours, save and
open) and the parametric study (inputs and outputs).   python test_solid_adapt.py"""
import faulthandler; faulthandler.dump_traceback_later(590, exit=True)
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, ext
import solid_adapt as sad, solid_asm as sa, solid_fem as fem, solid_geom as sg, solid_mesh as smesh, solid_model as sm, solid_progress
import solid_tab, study_ext


ALU = {"name": "Aluminium 6061-T6", "density": 2700.0, "E_MPa": 68900.0, "nu": 0.33, "Sy_MPa": 276.0, "Su_MPa": 310.0}


def ok(c, m):
    print(("  ok   " if c else "  FAIL ") + str(m))
    assert c, m


def settings(g, loads, supports, h, order=2, **adapt):
    s = sm.default_setup()
    s["h"] = h
    s["supports"], s["loads"] = supports, loads
    s["mesh"] = dict(smesh.default_mesh(), advanced=True, order=order)
    s["adapt"] = dict(sad.default_adapt(), on=True, **adapt)
    return s


def plane(g, n):
    return next(f["id"] for f in g["faces"] if f["kind"] == "plane" and np.dot(f["normal"], n) > 0.99)


# ------------------------------------------------------------------------------------------------ the settings
print("settings")
d = sad.default_adapt()
ok(d == {"on": False, "crit": "vm", "tol": 1.0, "loops": 5, "cap": 0, "strength": "normal", "hmin": 0.0}, "defaults: off, von Mises, 1 %, 5 loops, automatic size limit")
ok(sad.complete(None) == d and sad.complete({"tol": 2.0})["loops"] == 5 and "junk" not in sad.complete({"junk": 1}), "a missing or old dict is completed")
ok(sad.validate(d) is None, "the defaults are valid")
for name, bad in (("criterion", dict(d, crit="x")), ("tolerance 0", dict(d, tol=0)), ("tolerance 60", dict(d, tol=60)), ("loops 0", dict(d, loops=0)),
                  ("loops 21", dict(d, loops=21)), ("a 50 element limit", dict(d, cap=50)), ("negative smallest size", dict(d, hmin=-1.0)), ("strength", dict(d, strength="x"))):
    ok(sad.validate(bad), f"refused: {name}")
box = b.Solid.make_box(100, 10, 10)
g = sg.analyze(box)
xm, xp = plane(g, [-1, 0, 0]), plane(g, [1, 0, 0])
sup = [{"mode": "fixed", "faces": [sg.face_sig(g, xm)]}]
tip = [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [0.0, 0.0, -100.0]}]
off = sm.default_setup(); off.update(supports=sup, loads=tip)
ok(sm.resolve(g, off)["adapt"] is None and sad.options(off)["on"] is False, "off: one mesh, as before")
old = dict(off); old.pop("adapt")
ok(sm.resolve(g, old)["adapt"] is None, "a setup from an older file (no 'adapt') works")
on = settings(g, tip, sup, 8.0)
r = sm.resolve(g, on)
ok(r["adapt"]["crit"] == "vm" and r["adapt"]["reduce"] == 0.5 and r["adapt"]["loops"] == 5, "on: the settings are resolved")
hx = settings(g, tip, sup, 8.0); hx["mesh"]["type"] = "hexdom"
try:
    sm.resolve(g, hx); ok(False, "hex-dominant must be refused")
except fem.FemError as ex:
    ok("tetrahedra" in str(ex), f"hex-dominant is refused: {ex}")
try:
    sm.resolve(g, settings(g, tip, sup, 8.0, tol=0.0)); ok(False, "a bad tolerance must be refused")
except fem.FemError as ex:
    ok("tolerance" in str(ex), f"a bad number is refused when the setup is resolved: {ex}")

# ------------------------------------------------------------------------------------------------ the error estimate
print("error estimate")
bar_sym = [{"mode": "slide", "faces": [sg.face_sig(g, xm)]}, {"mode": "slide", "faces": [sg.face_sig(g, plane(g, [0, -1, 0]))]},
           {"mode": "slide", "faces": [sg.face_sig(g, plane(g, [0, 0, -1]))]}]
pull = [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [1000.0, 0.0, 0.0]}]
for order in (2, 1):
    s = settings(g, pull, bar_sym, 5.0, order)
    s["adapt"]["on"] = False
    rr = sm.resolve(g, s)
    q = sm.get_mesh(g, 5.0, {}, lambda: False, lambda t: None, rr["mesh"])
    res = sm.solve_mesh(g, rr, 5.0, q)
    ind = sad.indicator(q, rr, res["u"])
    ok(ind["theta"] < 1e-6, f"order {order}: a bar in tension (constant stress) has no estimated error ({ind['theta']:.1e})")
    ok(abs(ind["norm"] - 2 * res["energy"]) < 1e-6 * 2 * res["energy"], f"order {order}: the energy of the stresses is twice the strain energy ({ind['norm']:.6g})")
fine = []
for h in (10.0, 6.0, 3.5):
    s = settings(g, tip, sup, h)
    s["adapt"]["on"] = False
    rr = sm.resolve(g, s)
    q = sm.get_mesh(g, h, {}, lambda: False, lambda t: None, rr["mesh"])
    res = sm.solve_mesh(g, rr, h, q)
    ind = sad.indicator(q, rr, res["u"])
    fine.append(ind["theta"])
    ne = sad.node_error(q, ind)
    ok(len(ne) == len(res["nodes"]) and np.isfinite(ne).all() and (ne >= 0).all(), f"the error at the nodes: one value per node ({len(ne)})")
ok(fine[0] > fine[1] > fine[2], f"a cantilever: the estimated error falls as the mesh gets finer ({fine[0]:.1%}, {fine[1]:.1%}, {fine[2]:.1%})")
for order in (2, 1):
    s = settings(g, tip, sup, 8.0, order)
    s["adapt"]["on"] = False
    rr = sm.resolve(g, s)
    q = sm.get_mesh(g, 8.0, {}, lambda: False, lambda t: None, rr["mesh"])
    res = sm.solve_mesh(g, rr, 8.0, q)
    ind = sad.indicator(q, rr, res["u"])
    ok(abs(ind["norm"] - 2 * res["energy"]) < 1e-6 * 2 * res["energy"], f"order {order}: the energy adds up on a bent beam too")

# ------------------------------------------------------------------------------------------------ cantilever: the loops settle on the right answer
print("cantilever")
REF = {}
s = sm.default_setup(); s.update(h=1.5, supports=sup, loads=tip)
ref = sm.run(g, sm.resolve(g, s), {})
REF.update(umax=ref["umax"], energy=ref["energy"], n=ref["n_tets"])
for crit, key in (("umax", "umax"), ("energy", "energy")):
    res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 20.0, crit=crit, tol=0.5)), {})
    a = res["adapt"]
    ok(a["converged"] and a["loops"] >= 1 and a["change"] <= 0.5, f"{crit}: converged after {a['loops']} loop(s), last change {a['change']:.3g} %")
    ok(abs(a["history"][-1]["value"] - REF[key]) / REF[key] < 0.02, f"{crit}: {a['history'][-1]['value']:.5g} is within 2 % of the uniform fine mesh ({REF[key]:.5g})")
    ok(res["n_tets"] < REF["n"] / 5, f"{crit}: with {res['n_tets']:,} elements instead of {REF['n']:,}")
    ok(res["node_err"].shape == (res["n_nodes"],) and res["n_tets"] == a["history"][-1]["elements"], "the result is that of the last mesh, with its error at the nodes")
    ok([h_["loop"] for h_ in a["history"]] == list(range(len(a["history"]))) and a["history"][0]["change"] is None and a["history"][0]["refined"] is None,
       "the history has one row per loop, loop 0 is your own mesh")
    ok(a["history"][1]["elements"] > a["history"][0]["elements"] and a["history"][1]["err"] < a["history"][0]["err"], "a loop makes more elements and a smaller estimated error")
# linear elements need a much finer mesh: the loops go on and are stopped by the smallest size rather than called converged
res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 10.0, order=1, crit="umax", tol=1.0)), {})
a = res["adapt"]
ok(res["order"] == 1 and a["loops"] >= 3 and a["history"][-1]["elements"] > 10 * a["history"][0]["elements"], f"linear elements: {a['loops']} loops, {a['history'][0]['elements']:,} -> {a['history'][-1]['elements']:,} elements")
ok(not a["converged"] and "smallest element size" in a["reason"], f"a stalled refinement is not called converged: {a['reason'][:90]}...")
# strengths: all settle, the aggressive one makes the larger meshes
sizes = {}
for st in ("gentle", "normal", "strong"):
    res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.2, loops=3, strength=st)), {})
    sizes[st] = res["adapt"]["history"][1]["elements"]
ok(sizes["gentle"] <= sizes["normal"] <= sizes["strong"] and sizes["gentle"] < sizes["strong"], f"refinement strength: the first loop makes {sizes}")
# a peak von Mises at the fixed edge never settles: it is not called converged when its elements cannot get smaller
res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=1.0, loops=8)), {})
a = res["adapt"]
ok(not a["converged"] and ("smallest size" in a["reason"] or "most loops" in a["reason"]), f"the peak stress at a fixed face: not converged ({a['reason'][:80]}...)")
ok(a["history"][-1]["value"] > 1.15 * a["history"][0]["value"], f"and it keeps growing: {a['history'][0]['value']:.4g} -> {a['history'][-1]['value']:.4g} MPa")

# ------------------------------------------------------------------------------------------------ a thick cylinder under pressure (Lame)
print("thick cylinder")
cyl = b.Pos(0, 0, 10) * b.Cylinder(20, 20) - b.Pos(0, 0, 10) * b.Cylinder(10, 20)
quarter = (cyl & (b.Pos(12.5, 12.5, 10) * b.Box(25, 25, 20))).solids()[0]
gc = sg.analyze(quarter)
inner = next(f["id"] for f in gc["faces"] if f["kind"] == "cylinder" and abs(f["area"] - 314.159) < 1)
sl = lambda n: {"mode": "slide", "faces": [sg.face_sig(gc, plane(gc, n))]}
quarter_sup = [sl([-1, 0, 0]), sl([0, -1, 0]), sl([0, 0, -1]), sl([0, 0, 1])]                     # symmetry planes, and both ends held in z: plane strain
press = [{"kind": "pressure", "faces": [sg.face_sig(gc, inner)], "p": 100.0}]
A = 100.0 * (400 + 100) / (400 - 100)
sz = 0.3 * (A - 100.0)
vm_a = float(np.sqrt(0.5 * ((A + 100) ** 2 + (-100 - sz) ** 2 + (sz - A) ** 2)))
ur_a = (1 + 0.3) / 200000.0 * 100.0 * 100.0 / 300.0 * ((1 - 0.6) * 10.0 + 400.0 / 10.0)
res = sm.run(gc, sm.resolve(gc, settings(gc, press, quarter_sup, 6.0, crit="vm", tol=1.0)), {})
a = res["adapt"]
ok(a["converged"] and a["loops"] >= 1, f"von Mises at the bore: converged after {a['loops']} loops ({a['history'][-1]['elements']:,} elements)")
ok(abs(res["vm_max"] - vm_a) / vm_a < 0.04, f"peak von Mises {res['vm_max']:.1f} MPa against {vm_a:.1f} MPa from Lame")
ok(abs(res["umax"] - ur_a) / ur_a < 0.03, f"radial displacement {res['umax']:.5f} mm against {ur_a:.5f} mm from Lame")
ok(res["equilibrium"] < 1e-6, "equilibrium holds on the last mesh")
ne = res["node_err"]
ok(float(ne.max()) > 0 and float(ne.std()) > 0, "the error field is not flat: it shows where the mesh was coarse")

# ------------------------------------------------------------------------------------------------ a plate with a hole (stress concentration at a curved edge)
print("plate with a hole")
plate = (b.Pos(25, 12.5, 1.25) * b.Box(50, 25, 2.5) - b.Pos(0, 0, 1.25) * b.Cylinder(5, 2.5)).solids()[0]          # a quarter of 100 x 50 x 5 with a 10 mm hole
gp = sg.analyze(plate)
pf = lambda n: next(f["id"] for f in gp["faces"] if f["kind"] == "plane" and np.dot(f["normal"], n) > 0.99 and (n[0] != 1 or f["center"][0] > 49))
psup = [{"mode": "slide", "faces": [sg.face_sig(gp, pf(n))]} for n in ([-1, 0, 0], [0, -1, 0], [0, 0, -1])]
pull_p = [{"kind": "pressure", "faces": [sg.face_sig(gp, pf([1, 0, 0]))], "p": -100.0}]                                 # 100 MPa on the gross section
kt = 3.0 - 3.14 * 0.2 + 3.667 * 0.04 - 1.527 * 0.008                                                                   # Peterson, d / W = 0.2, on the net section (125 MPa)
res = sm.run(gp, sm.resolve(gp, settings(gp, pull_p, psup, 5.0, crit="vm", tol=1.0)), {})
a = res["adapt"]
ok(a["converged"] and a["loops"] >= 1, f"converged after {a['loops']} loops with {a['history'][-1]['elements']:,} elements: {a['reason'][:60]}")
ok(abs(res["vm_max"] - 125.0 * kt) / (125.0 * kt) < 0.03, f"peak stress at the hole {res['vm_max']:.1f} MPa against {125.0 * kt:.1f} MPa from the stress concentration factor")
ok(a["history"][0]["value"] < a["history"][-1]["value"], f"the coarse first mesh underestimates it ({a['history'][0]['value']:.1f} MPa)")

# ------------------------------------------------------------------------------------------------ why the loops stop
print("stop reasons")
res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=2)), {})
a = res["adapt"]
ok(not a["converged"] and a["loops"] == 2 and "most loops (2)" in a["reason"], f"most loops: {a['reason'][:70]}")
res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=5, cap=300)), {})
a = res["adapt"]
ok(not a["converged"] and a["loops"] == 0 and a["reason"].startswith("Reached your maximum of 300 elements") and a["limit"] == "max", f"size limit: {a['reason']}")
res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=5, hmin=20.0)), {})
a = res["adapt"]
ok(not a["converged"] and a["loops"] == 0 and "smallest size" in a["reason"], f"nothing can be refined: {a['reason']}")

# ------------------------------------------------------------------------------------------------ the largest mesh: never crossed, landed under
print("the largest mesh")
free_run = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=1)), {})["adapt"]
n0, n1 = free_run["history"][0]["elements"], free_run["history"][1]["elements"]
u0 = free_run["history"][0]["unknowns"]
ok(n1 > 1.5 * n0 and free_run["limit"] is None, f"without a maximum the first loop goes from {n0:,} to {n1:,} elements")
cap = int(n0 + 0.5 * (n1 - n0))
res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=5, cap=cap)), {})
a = CAPPED = res["adapt"]
last_n = a["history"][-1]["elements"]
ok(a["loops"] == 1 and n0 < last_n <= cap and last_n >= 0.85 * cap, f"a maximum of {cap:,} between the two: the loop refines less and lands at {last_n:,} elements, just under it")
ok(max(h_["elements"] for h_ in a["history"]) <= cap, "no mesh is above the maximum")
ok(not a["converged"] and a["limit"] == "max" and a["reason"].startswith(f"Reached your maximum of {cap:,} elements") and "converge" not in a["reason"].split("The ")[0],
   f"it says it reached the maximum, not that it did not converge: {a['reason'][:110]}")
ok(sad.outcome(a) == "max" and sad.OUTCOME_TEXT[sad.outcome(a)] == "reached maximum", "the outcome in one word")
ok(res["n_tets"] == last_n and res["equilibrium"] < 1e-6, "the result is that of the last mesh, and equilibrium holds")
res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=5, cap=int(n0 * 1.1))), {})
a = res["adapt"]
ok(a["loops"] == 0 and a["limit"] == "max" and "Reached your maximum" in a["reason"], f"a maximum so close to the first mesh that a loop could add nothing: stops at once ({a['reason'][:70]})")
big_cap = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=1, cap=50 * n0)), {})["adapt"]
ok(big_cap["history"][1]["elements"] == n1 and big_cap["limit"] is None, "a maximum that is not reached changes nothing")
# automatic: no maximum typed; the limit of the program, and the loops stop by themselves
real_auto = sad.AUTO_UNKNOWNS
sad.AUTO_UNKNOWNS = int(2.0 * u0)
try:
    res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=5)), {})
    a = res["adapt"]
    ok(a["limit"] == "auto" and not a["converged"] and "automatic size limit" in a["reason"] and a["history"][-1]["unknowns"] <= sad.AUTO_UNKNOWNS * 1.02
       and a["history"][-1]["unknowns"] > 0.85 * sad.AUTO_UNKNOWNS, f"automatic: the loops stop at the limit ({a['history'][-1]['unknowns']:,} of {sad.AUTO_UNKNOWNS:,} unknowns): {a['reason'][:70]}")
    ok(sad.outcome(a) == "auto", "and the outcome says so")
    sad.AUTO_UNKNOWNS = int(1.3 * u0)
    res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=1, cap=50 * n0)), {})
    a = res["adapt"]
    ok(a["history"][-1]["unknowns"] > 1.2 * sad.AUTO_UNKNOWNS and a["limit"] is None, f"a typed maximum is honoured above the automatic limit ({a['history'][-1]['unknowns']:,} unknowns, the automatic limit is {sad.AUTO_UNKNOWNS:,})")
finally:
    sad.AUTO_UNKNOWNS = real_auto
# the memory of this computer
real_free = fem.available_memory
fem.available_memory = lambda: (fem.MEM_PER_UNKNOWN * 2.0 * u0 + fem.MEM_BASE) / fem.MEM_SHARE
try:
    res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=5)), {})
    a = res["adapt"]
    ok(a["limit"] == "memory" and "more memory" in a["reason"] and a["history"][-1]["unknowns"] <= 2.0 * u0 * 1.02 and not a["converged"],
       f"memory: the loops stop where the free memory ends ({a['history'][-1]['unknowns']:,} unknowns): {a['reason']}")
    res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=5, cap=50 * n0)), {})
    a = res["adapt"]
    ok(a["limit"] == "memory" and a["warning"] and f"{50 * n0:,}" in a["warning"] and "GB" in a["warning"], f"a typed maximum the memory cannot hold is said at the start: {a['warning']}")
    ok(sad.outcome(a) == "memory", "and the outcome is the memory")
finally:
    fem.available_memory = real_free
ok(sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=1, cap=50 * n0)), {})["adapt"]["warning"] is None, "with enough memory there is no warning")
# a loop that lands under the maximum makes extra trial meshes: the progress bar and its messages take them in their stride
trk_l = solid_progress.Tracker()
say = []
trk_l.attach(say.append)
res = sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=3, cap=cap)), {}, progress=trk_l)
snap = trk_l.snapshot()
ok(res["adapt"]["limit"] == "max" and any("refining" in t for t in say), f"a run that lands under the maximum, with a real progress tracker, says so: {[t for t in say if 'refining' in t][:1]}")
ok(res["adapt"]["history"][-1]["elements"] <= cap and 0.0 <= snap[0] <= 1.0, f"and the bar stays between 0 and 1 ({snap[0]:.2f})")
try:
    sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", loops=3)), {}, cancel=lambda: True)
    ok(False, "cancel must stop the loops")
except fem.Cancelled:
    ok(True, "cancel stops the loops")
count = {"n": 0}
def cancel_late():
    count["n"] += 1
    return count["n"] > 12
try:
    sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="vm", tol=0.001, loops=6)), {}, cancel=cancel_late)
    ok(False, "cancel in the middle must stop the loops")
except fem.Cancelled:
    ok(True, "cancel in the middle of the loops stops them")
# the progress text says which loop
texts = []
sm.run(g, sm.resolve(g, settings(g, tip, sup, 8.0, crit="umax", tol=5.0, loops=3)), {}, progress=texts.append)
ok(any(t.startswith("Loop 0 of 3: ") for t in texts) and any(t.startswith("Loop 1 of 3: ") for t in texts), "the progress text names the loop")
# the progress bar's plan stays whole through the loops (a cyclic plan keeps the later loops)
trk = solid_progress.Tracker()
trk.expect([("mesh", 100), ("assemble", 100), ("factor", 1e6), ("stress", 100), ("mesh", 200), ("assemble", 200), ("factor", 2e6), ("stress", 200)], cyclic=True)
trk.stage("mesh", 100); trk.stage("assemble", 100)
ok([k for k, _s in trk.future].count("mesh") == 1 and len(trk.future) == 6, "a cyclic plan keeps the later loops when a stage begins")
trk2 = solid_progress.Tracker()
trk2.expect([("mesh", 100), ("assemble", 100), ("factor", 1e6), ("stress", 100), ("mesh", 200)])
trk2.stage("mesh", 100); trk2.stage("assemble", 100)
ok([k for k, _s in trk2.future].count("mesh") == 0, "a plan that is not cyclic drops them, as it always did")
pl = sad.plan(g, sm.resolve(g, settings(g, tip, sup, 8.0, loops=3)), 8.0)
ok([k for k, _s in pl].count("mesh") == 4 and [k for k, _s in pl].count("stress") == 4, f"the plan of a run: a mesh and a solve per loop ({len(pl)} stages)")

# ------------------------------------------------------------------------------------------------ bonded parts
print("assembly")
STEEL = {"name": "Steel", "density": 7850.0, "E_MPa": 200000.0, "nu": 0.3, "Sy_MPa": 250.0, "Su_MPa": 400.0}
ALU = {"name": "Aluminium", "density": 2700.0, "E_MPa": 70000.0, "nu": 0.33, "Sy_MPa": 100.0, "Su_MPa": 200.0}
bar = lambda z0, z1: b.Pos(0, 0, (z0 + z1) / 2) * b.Box(20, 20, z1 - z0)
ga = sa.analyze_assembly([("Base", bar(0, 30), STEEL), ("Block", bar(30, 50), ALU)])
fz = lambda nz, at: next(f["id"] for f in ga["faces"] if not f["interface"] and abs(f["normal"][2] - nz) < 1e-6 and abs(f["center"][2] - at) < 1e-3)
asup = [{"mode": "fixed", "faces": [sg.face_sig(ga, fz(-1, 0.0))]}]
aload = [{"kind": "force", "faces": [sg.face_sig(ga, fz(1, 50.0))], "f": [0.0, 0.0, -10000.0]}]
want = 10000.0 * (30 / 200000.0 + 20 / 70000.0) / 400.0
sa_ = settings(ga, aload, asup, 10.0, crit="umax", tol=1.0)
res = sm.run(ga, sm.resolve(ga, sa_), {})
a = res["adapt"]
ok(a["loops"] >= 1 and abs(res["umax"] - want) / want < 0.03, f"two bonded bars: {res['umax']:.6f} mm against {want:.6f} mm in series, {a['loops']} loop(s)")
ok(res["bodies"] and res["equilibrium"] < 1e-6, "the result still has its bodies, and equilibrium holds")
ok(not sad.unsupported(ga, sa_) and not sad.unsupported(g, on), "unsupported(): a bonded assembly and a single part are both fine")

# ------------------------------------------------------------------------------------------------ the window
print("window")
T = tempfile.mkdtemp(prefix="opara_adapt_")
dd = pm.Document(); dd.params = {"T": "10"}
s0 = dd.add(pm.new_feature("sketch", plane={"base": "Top"})); dd.rebuild(); m = dd.models[s0["id"]]
rr_ = sk.add_rect_corner(m, (0, 0), (100, 10))
m.add_con("dim_h", [("ln", rr_["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", rr_["lns"][1])], value=10.0)
sk.solve_model(m); dd.store_sketch(s0["id"])
dd.add(pm.new_feature("extrude", sketch=s0["id"], depth="T")); dd.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(dd.to_json())
w = solid_tab.SolidWindow(threaded=False)
ok(hasattr(w, "cb_adapt") and not w.cb_adapt.isChecked() and w.adapt_box.isHidden(), "the tick box is there, off, and its menu hidden")
ok(w.create_project(os.path.join(T, "bar_adapt")) and w.import_file(part), MSGS)
fc = lambda n: next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], n) > 0.99)
w.select_faces([fc([-1, 0, 0])]); w.add_support("fixed")
w.select_faces([fc([1, 0, 0])]); w.add_load("force", {"f": [0.0, 0.0, -100.0]})
w.set_size("8"); w.inputs_changed()
ok(w.cb_adapt.isEnabled(), "with a part imported the tick box can be used")
w.cb_adapt.setChecked(True)
ok(not w.adapt_box.isHidden() and w.setup["adapt"]["on"] and w.setup["adapt"]["crit"] == "vm" and w.setup["adapt"]["tol"] == 1.0 and w.setup["adapt"]["loops"] == 5, "ticking it shows the menu and puts the settings in the setup")
w.ad_crit.setCurrentIndex(w.ad_crit.findData("umax")); w.ad_tol.setText("0.5"); w.ad_loops.setValue(4); w.ad_strength.setCurrentIndex(w.ad_strength.findData("strong"))
w.ad_cap.setText("20000"); w.ad_hmin.setText("0.9")
w.inputs_changed()
a = w.setup["adapt"]
ok(a["crit"] == "umax" and a["tol"] == 0.5 and a["loops"] == 4 and a["strength"] == "strong" and a["cap"] == 20000 and abs(a["hmin"] - 0.9) < 1e-9, f"the boxes are read: {a}")
w.ad_tol.setText("abc"); MSGS.clear()
w.inputs_changed()
ok("Tolerance" in w.status_lbl.text() or "number" in w.status_lbl.text().lower(), "a bad number is said in the status line")
w.ad_tol.setText("0.5"); w.ad_cap.setText(""); w.ad_hmin.setText(""); w.inputs_changed()
ok(w.run_solve() and w.result is not None and w.result.get("adapt"), w.status_lbl.text())
res = w.result
a = res["adapt"]
ok(a["converged"] and "Adaptive mesh" in w.res_lbl.text() and "Converged" in w.res_lbl.text() and "your mesh" in w.res_lbl.text(), "the report says what the loops did, one row per loop")
rep = w.adapt_report(dict(CAPPED, warning="Your maximum would need more memory than there is."))
ok("Reached your maximum" in rep and "Not converged" not in rep and "more memory than there is" in rep, "a run that reached the maximum says so in the report, with its warning")
ok("largest mesh you allow" in w.ad_cap.toolTip().lower() and "lands just under" in w.ad_cap.toolTip(), "the box for the largest mesh explains what it does")
ok(f"{res['n_tets']:,}" in w.mesh_lbl.text() and w.mesh_q is not None and len(w.mesh_q["conn"]) == res["n_tets"], "the mesh label and picture are those of the last mesh")
ok(w.cb_field.findData("err") >= 0 and w.cb_field.itemText(w.cb_field.findData("err")).startswith("Estimated mesh error"), "the 'Estimated mesh error' result is offered")
w.cb_field.setCurrentIndex(w.cb_field.findData("err")); w.show_field()
vals, leg = w.field_values()
ok(len(vals) == res["n_nodes"] and "error" in leg["title"].lower(), "and it colours the nodes with the error")
w.cb_field.setCurrentIndex(0); w.show_field()
w.set_size("6"); w.inputs_changed()
ok(w.result is None, "a change of the setup clears the result")
ok(w.run_solve(), w.status_lbl.text())
w.cb_adapt.setChecked(False)
ok(w.adapt_box.isHidden() and not w.setup["adapt"]["on"], "unticking hides the menu")
ok(w.run_solve() and not w.result.get("adapt") and "not refined by itself" in w.res_lbl.text() and w.cb_field.findData("err") < 0, "with it off: one mesh, no error result, and the note points at the tick box")
# hex-dominant switches it off, with a message
w.cb_adapt.setChecked(True)
w.cb_adv.setChecked(True)
w.type_combo.setCurrentIndex(w.type_combo.findData("hexdom")); w.inputs_changed()
ok(not w.cb_adapt.isChecked() and not w.setup["adapt"]["on"] and "tetrahedra" in w.status_lbl.text(), f"hex-dominant: the adaptive mesh is switched off, with a message ({w.status_lbl.text()[:70]})")
ok(not w.cb_adapt.isEnabled() and "tetrahedra" in w.cb_adapt.toolTip().lower(), "and the tick box is greyed out, its tip saying why")
w.type_combo.setCurrentIndex(w.type_combo.findData("tets")); w.inputs_changed()
ok(w.cb_adapt.isEnabled() and not w.cb_adapt.toolTip().startswith("Not available"), "back to tetrahedra it can be used again")
# save and open: the settings come back
w.cb_adapt.setChecked(True); w.ad_crit.setCurrentIndex(w.ad_crit.findData("energy")); w.ad_tol.setText("2"); w.ad_loops.setValue(3); w.inputs_changed()
ok(w.save(), "saved")
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
ok(w2.cb_adapt.isChecked() and w2.ad_crit.currentData() == "energy" and w2.ad_tol.text() == "2" and w2.ad_loops.value() == 3 and not w2.adapt_box.isHidden(), "opened: the tick box, the menu and its numbers are back")
ok(w2.run_solve() and w2.result["adapt"]["crit"] == "energy" and w2.result["adapt"]["loops_max"] == 3, "and it solves the same way")
w2.units_changed()
ok(w2.ad_hmin_label.text().startswith("Smallest element ("), "the unit of the smallest size follows File > Units")

# ------------------------------------------------------------------------------------------------ the parametric study
print("study")
ext.HOOKS.clear(); study_ext.register(ext)
w2.refresh_study_button()
tab = w2.open_study()
tab.threaded = False
ad = tab.adapter
ids = {p_["id"]: p_ for p_ in ad.params()}
ok(all(k in ids for k in ("sf.ad.on", "sf.ad.crit", "sf.ad.tol", "sf.ad.loops")), "the study offers the adaptive mesh as inputs")
ok(ids["sf.ad.on"]["kind"] == "bool" and ids["sf.ad.on"]["now"] == "yes" and ids["sf.ad.crit"]["kind"] == "choice" and "Strain energy" in ids["sf.ad.crit"]["choices"]
   and ids["sf.ad.tol"]["now"] == "2" and ids["sf.ad.loops"]["now"] == "3", "their values are those of the window")
outs = {o["id"]: o for o in ad.outputs()}
ok(all(k in outs for k in ("sf.adapt", "sf.converged", "sf.loops", "sf.change", "sf.err")) and outs["sf.converged"]["numeric"] and not outs["sf.adapt"]["numeric"], "and the outcome as outputs")
ctx = {}
spec = ad.prepare({"sf.ad.on": "yes", "sf.ad.crit": "Displacement (peak)", "sf.ad.tol": "1", "sf.ad.loops": "4"}, ctx)
ok(spec["error"] is None, spec["error"])
case = spec["run"](lambda t: None, lambda: False)
o = ad.case_outputs(case, ["sf.status", "sf.adapt", "sf.converged", "sf.loops", "sf.change", "sf.err", "sf.tets", "sf.umax"])
ok(case["status"] == "ok" and o["sf.adapt"] == "converged" and o["sf.converged"] == 1.0 and o["sf.loops"] >= 1 and o["sf.change"] <= 1.0 and o["sf.err"] > 0, f"a case: {o}")
ok(case["result"]["adapt"]["crit"] == "umax", "the criterion of the case is the one that was typed")
spec = ad.prepare({"sf.ad.on": "yes", "sf.ad.crit": "Von Mises stress (peak)", "sf.ad.tol": "0.001", "sf.ad.loops": "1"}, ctx)
case = spec["run"](lambda t: None, lambda: False)
o = ad.case_outputs(case, ["sf.adapt", "sf.converged", "sf.loops"])
ok(o["sf.adapt"] == "not converged" and o["sf.converged"] == 0.0 and o["sf.loops"] == 1, f"a case that does not converge says so: {o}")
spec = ad.prepare({"sf.ad.on": "no"}, ctx)
case = spec["run"](lambda t: None, lambda: False)
o = ad.case_outputs(case, ["sf.adapt", "sf.converged", "sf.loops", "sf.tets"])
ok(o["sf.adapt"] == "off" and o["sf.converged"] is None and o["sf.tets"] > 0, f"adaptive off in a case: one mesh, outputs blank ({o})")
ok(ad.prepare({"sf.ad.on": "yes", "sf.ad.crit": "Nonsense"}, ctx)["error"] and ad.prepare({"sf.ad.on": "yes", "sf.ad.tol": "x"}, ctx)["error"], "a bad criterion or number is an error of that case")
ok(ad.prepare({"sf.ad.on": "yes", "sf.ad.tol": "0"}, ctx)["error"], "a tolerance of 0 is refused")
# a study grid over the tolerance, run through the tab
from PyQt6.QtCore import Qt
tab.items["sf.ad.tol"].setCheckState(0, Qt.CheckState.Checked)
ok(tab.fill_grid({"sf.ad.tol": "5, 0.05"}) and len(tab.data.rows) == 2, "a grid over the tolerance")
tab.data.out_checked = ["sf.adapt", "sf.converged", "sf.loops", "sf.err", "sf.tets"]; tab.fill_outputs()
ok(tab.run_all(), "run")
cs = tab.data.cases
ok(len(cs) == 2 and all(c["status"] == "ok" for c in cs), [(c["status"], c.get("error")) for c in cs])
ok(all(c["outputs"]["sf.converged"] in (0.0, 1.0) and c["outputs"]["sf.adapt"] in ("converged", "not converged") for c in cs)
   and cs[1]["outputs"]["sf.loops"] > cs[0]["outputs"]["sf.loops"], f"a tighter tolerance takes more loops: {[c['outputs'] for c in cs]}")
ok(tab.show_case(0) and w2.result is not None and w2.result.get("adapt") and w2.cb_field.findData("err") >= 0, "a case on the screen shows its adaptive result")

# ------------------------------------------------------------------------------------------------ the window with an assembly
print("assembly window")
import asm_model as am


def make_part(path, wd, depth, material=None):
    d_ = pm.Document(); d_.params = {"H": str(depth)}
    s_ = d_.add(pm.new_feature("sketch", plane={"base": "Top"})); d_.rebuild(); m_ = d_.models[s_["id"]]
    r_ = sk.add_rect_corner(m_, (0, 0), (wd, wd))
    m_.add_con("dim_h", [("ln", r_["lns"][0])], value=wd); m_.add_con("dim_v", [("ln", r_["lns"][1])], value=wd)
    sk.solve_model(m_); d_.store_sketch(s_["id"])
    d_.add(pm.new_feature("extrude", sketch=s_["id"], depth="H")); d_.rebuild()
    if material:
        d_.material = material
    open(path, "w", encoding="utf-8").write(d_.to_json())


ad_ = os.path.join(T, "asm"); os.makedirs(ad_)
make_part(os.path.join(ad_, "base.gpd"), 20.0, 30.0)
make_part(os.path.join(ad_, "cap.gpd"), 20.0, 20.0, ALU)
asm_ = am.Assembly(); asm_.add_component("base.gpd", fixed=True, pos=(0, 0, 0)); asm_.add_component("cap.gpd", fixed=False, pos=(0, 0, 30))
asm_path = os.path.join(ad_, "stack.gpa"); open(asm_path, "w").write(asm_.to_json())
wa = solid_tab.SolidWindow(threaded=False)
ok(wa.create_project(os.path.join(T, "stack_study")) and wa.import_file(asm_path) and wa.is_asm(), MSGS)
ga_ = wa.geom
bot = next(f["id"] for f in ga_["faces"] if not f["interface"] and f["normal"][2] < -0.99)
topf = next(f["id"] for f in ga_["faces"] if not f["interface"] and f["normal"][2] > 0.99)
wa.select_faces([bot]); wa.add_support("fixed")
wa.select_faces([topf]); wa.add_load("force", {"f": [0.0, 0.0, -10000.0]})
wa.set_size("10"); wa.inputs_changed()
wa.cb_adapt.setChecked(True); wa.ad_crit.setCurrentIndex(wa.ad_crit.findData("umax")); wa.inputs_changed()
ok(wa.cb_adapt.isChecked() and wa.cb_adapt.isEnabled(), "an assembly of bonded parts can use the adaptive mesh")
ok(wa.run_solve() and wa.result.get("adapt") and wa.result["bodies"], wa.status_lbl.text())
txt = wa.res_lbl.text()
want = 10000.0 * (30 / 200000.0 + 20 / 68900.0) / 400.0
ok("Bodies (fully bonded)" in txt and "Adaptive mesh" in txt and abs(wa.result["umax"] - want) / want < 0.05, f"the report has the bodies and the loops; {wa.result['umax']:.6f} mm against {want:.6f} mm")
counts = [int(wa.size_table.item(i, 2).text().replace(",", "")) for i in range(wa.size_table.rowCount())]
ok(sum(counts) == wa.result["n_tets"] and len(counts) == 2, f"the element count of every part is that of the last mesh ({counts})")
ok(wa.cb_adapt.isEnabled(), "the tick box stays available for the assembly (every assembly is bonded now)")

shutil.rmtree(T, ignore_errors=True)
print("OK solid adapt")
os._exit(0)
