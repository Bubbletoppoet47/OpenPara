"""What a Coupled Physics block asks of the 3D Fluid Flow model (cfd3d_model, cfd3d_morph; no Qt): the faces that exchange heat with a thermal analysis, the pressure on the walls of the part and
its force, the temperature of the fluid for wall temperatures that are given as functions of the place (the flow is not solved again), and the air mesh moved with the part.
A 10 mm cube in air at Reynolds number 40.   python test_cfd3d_couple.py"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "cfd3d"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_fem as fem
import solid_geom as sg
import cfd3d_flow as cf
import cfd3d_model as cm
import cfd3d_morph as mo

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b_, rel, what, ab=0.0):
    err = abs(a - b_)
    ok(err <= rel * abs(b_) + ab, f"{what}: {a:.6g} against {b_:.6g}")


cube = sg.analyze(b.Box(10, 10, 10), None)
sigs = [sg.face_sig(cube, f["id"]) for f in cube["faces"]]
FIDS = [int(f["id"]) for f in cube["faces"]]

# ------------------------------------------------------------------------------------------------------------------- the condition 'Wall of the thermal analysis'
print("-- the faces that exchange heat")
ok(("Wall of the thermal analysis", "exch") in cm.CONDITION_KINDS and cm.VALUES["exch"] == () and "exch" in cm.KEYS, "'Wall of the thermal analysis' is a kind of condition with no value")
s = cm.default_setup()
s["flow"].update({"speed": 0.0606, "heat": True, "T_in": 293.15})
s["h"] = 2.5
s["exch"] = [{"name": "Wall", "faces": sigs}]
r = cm.resolve(cube, s)
ok(cm.exch_fids(r) == sorted(FIDS), f"the faces of the exchange are the six faces of the cube: {cm.exch_fids(r)}")
ok(any("thermal analysis" in n for n in cm.notes(s, cube)), "the window says that those faces are insulated until a Coupled Physics block exchanges heat there")
cache = {}
t0 = time.time()
res = cm.run(cube, r, cache)
ok(res["status"] == "converged", f"the flow converges ({res['steps']} steps, {time.time() - t0:.1f} s)")
ok(not res["spec"]["wall_T"] and not res["spec"]["wall_q"], "faces of the exchange are adiabatic on their own: no wall temperature, no flux in the spec")
ok(np.abs(res["T"] - 293.15).max() < 1e-9, f"and the fluid stays at the inflow temperature ({np.abs(res['T'] - 293.15).max():.1e} K)")

# ------------------------------------------------------------------------------------------------------------------- the wall as a surface
q = res["mesh"]
tris = cm.wall_triangles(q, FIDS)
near(float(cm.node_areas(q["nodes"], tris, len(q["nodes"])).sum()), 6e-4, 1e-9, "the area the wall nodes stand for, m2")
ok(len(cm.wall_triangles(q, [])) == 0 and len(cm.wall_triangles(q, [999])) == 0, "no faces, no triangles")
wp = cm.wall_pressure(res, FIDS)
ok(wp["tris"].max() == len(wp["points"]) - 1 and np.allclose(wp["p"], res["p"][wp["nodes"]]) and np.allclose(wp["points"], q["nodes"][wp["nodes"]]), "the wall pressure is a triangulated surface with its field")
F, S = cm.pressure_force(res, FIDS)
Fw = cf.wall_force(res, FIDS)
ok(np.allclose(F, Fw["pressure"], rtol=1e-9, atol=1e-18), f"the force of the pressure is the one the solver reports: {F}")
ok(S >= np.linalg.norm(F) and S > 0, f"the sum of the sizes of the forces of the triangles ({S:.3e} N) is at least the resultant")
ok(F[0] > 0 and abs(F[1]) < 0.02 * F[0] and abs(F[2]) < 0.02 * F[0], "the pressure pushes the cube downstream and not sideways")
Fa = cm.pressure_force(res, [FIDS[0]])[0]
Fb = cm.pressure_force(res, [f for f in FIDS if f != FIDS[0]])[0]
ok(np.allclose(Fa + Fb, F, rtol=1e-9, atol=1e-18), "the force on all the faces is the sum of the force on one face and on the others")

# ------------------------------------------------------------------------------------------------------------------- the temperature for wall temperatures that are given
print("-- the temperature of the fluid for given wall temperatures")
T_before = res["T"].copy()
hot, wall = cm.solve_wall_heat(res, FIDS, 323.15)
ok(np.array_equal(res["T"], T_before) and "T" in res, "the flow's own result is not changed")
ok(np.abs(wall["T"] - 323.15).max() < 1e-9, "the wall nodes are at the temperature they were given")
near(float(np.sum(wall["q"] * wall["area"])), wall["Q"], 1e-9, "the flux of the nodes times their areas is the heat of the faces (W)")
ok(wall["Q"] > 0 and float(wall["q"].min()) > -0.05 * float(wall["q"].max()), f"a hot cube heats the air: {wall['Q']:.4e} W")
Q1 = wall["Q"]
hot2, wall2 = cm.solve_wall_heat(res, FIDS, lambda P: 293.15 + 60.0 * np.ones(len(P)))
near(wall2["Q"], 2.0 * Q1, 1e-6, "twice the temperature difference, twice the heat (a passive scalar)")
hot3, wall3 = cm.solve_wall_heat(res, FIDS, lambda P: 293.15 + 30.0 * (1.0 + P[:, 0] / 5.0 * 0.5))
want = 293.15 + 30.0 * (1.0 + np.asarray(q["nodes"], float)[wall3["nodes"], 0] / 5.0 * 0.5)
ok(np.allclose(wall3["T"], want, atol=1e-9), "a wall temperature given as a function of the place (mm) is evaluated at the wall nodes")
ok(wall["nodes"].tolist() == wall2["nodes"].tolist() == cm.np.unique(tris.ravel()).tolist(), "the wall nodes are the sorted nodes of the triangles of the faces")
one, w1 = cm.solve_wall_heat(res, FIDS[:1], 323.15)
ok(0 < w1["Q"] < Q1 and set(w1["nodes"].tolist()) < set(wall["nodes"].tolist()), f"one face alone: {w1['Q']:.4e} W of {Q1:.4e} W")
ok(hot["energy"]["mismatch"] < 0.35, f"the energy balance of the heated flow is inside the COARSE limit ({hot['energy']['mismatch'] * 100:.1f} %)")

# ------------------------------------------------------------------------------------------------------------------- a face with its own condition gives way
sx = cm.default_setup()
sx["flow"].update({"speed": 0.0606, "heat": True, "T_in": 293.15})
sx["h"] = 2.5
top = [sg.face_sig(cube, f["id"]) for f in cube["faces"] if abs(f["normal"][2] - 1) < 1e-6]
sx["temps"] = [{"name": "Hot top", "faces": top, "T": 350.0}]
sx["exch"] = [{"name": "Wall", "faces": sigs}]
rx = cm.resolve(cube, sx)
resx = cm.run(cube, rx, cache)
topid = next(int(f["id"]) for f in cube["faces"] if abs(f["normal"][2] - 1) < 1e-6)
ok(topid in resx["spec"]["wall_T"], "a face with a temperature of its own has it in the window's own solve")
hx, wx = cm.solve_wall_heat(resx, FIDS, 323.15)
ok(abs(hx["T"][np.unique(cm.wall_triangles(resx["mesh"], [topid]).ravel())] - 323.15).max() < 1e-9, "and takes the exchange temperature when a coupled block exchanges heat there")
ok(resx["spec"]["wall_T"][topid] == 350.0, "without changing the spec of the window")

# ------------------------------------------------------------------------------------------------------------------- the air mesh moved with the part
print("-- the air mesh follows the part")
part = cm.part_nodes(q)
box = cm.box_nodes(q)
ok(len(part) > 100 and len(box) > 100 and not set(part.tolist()) & set(box.tolist()), f"{len(part)} nodes on the part, {len(box)} on the box, none on both")
D0 = np.zeros((len(part), 3))
ok(np.allclose(cm.moved_nodes(q, D0), q["nodes"]), "no movement leaves every node where it was")
D1 = np.tile([0.0, 0.3, 0.0], (len(part), 1))
new = cm.moved_nodes(q, D1)
nn = np.asarray(q["nodes"], float)
ok(np.allclose(new[part], nn[part] + D1) and np.allclose(new[box], nn[box]), "the part's nodes take the movement, the box stays")
vr = mo.tet_volumes(new, q["tets"]) / mo.tet_volumes(nn, q["tets"])
ok(vr.min() > 0.5 and vr.max() < 2.0 and abs(mo.shrink(nn, new, q["tets"]) - vr.min()) < 1e-12, f"no tetrahedron is turned inside out; the smallest keeps {vr.min():.2f} of its volume")
far = np.setdiff1d(np.arange(len(nn)), np.concatenate([part, box]))
dfar = np.linalg.norm(new[far] - nn[far], axis=1)
ok(dfar.max() <= 0.3 + 1e-9 and dfar.mean() > 0, f"the nodes between them move by up to {dfar.max():.3f} mm (the part moved 0.3 mm)")
t0 = time.time()
res_m = cm.run(cube, r, cache, nodes=lambda qq: cm.moved_nodes(qq, D1))
ok(res_m["status"] == "converged" and np.allclose(res_m["mesh"]["nodes"][part], nn[part] + D1), f"the flow is solved on the moved mesh ({time.time() - t0:.1f} s) and its mesh is the moved one")
ok(np.allclose(q["nodes"], nn), "the mesh in the cache is not changed")
near(res_m["summary"]["drag"], res["summary"]["drag"], 0.03, "the drag of the cube moved 0.3 mm sideways (the box is wide: it hardly matters)")
res_n = cm.run(cube, r, cache, nodes=cm.moved_nodes(q, D1))
ok(np.allclose(res_n["u"], res_m["u"]), "the nodes can be given as an array as well")
seen = []


def recorder(P):
    seen.append(np.array(P, float))
    return np.full(len(P), 323.15)


_h, _w = cm.solve_wall_heat(res_m, FIDS, recorder, x_ref=nn)
pts = np.vstack(seen)
as_drawn = {tuple(np.round(p_, 9)) for p_ in nn}
moved_pos = {tuple(np.round(p_, 9)) for p_ in res_m["mesh"]["nodes"][part]}
ok(all(tuple(np.round(p_, 9)) in as_drawn for p_ in pts), f"with the nodes of the mesh as drawn given, the wall temperature is asked for the places of the material points ({len(pts)} places)")
ok(not moved_pos <= as_drawn, "and not for where the moved flow has them")
_h2, _w2 = cm.solve_wall_heat(res_m, FIDS, 323.15, x_ref=nn)
near(_w2["Q"], cm.solve_wall_heat(res_m, FIDS, 323.15)[1]["Q"], 1e-9, "a wall temperature that is the same everywhere gives the same heat wherever it is asked for (W)")
try:
    cm.solve_wall_heat(res_m, FIDS, 323.15, x_ref=np.zeros((5, 3)))
    ok(False, "places that do not match the mesh were not refused")
except cf.FlowError as ex:
    ok("do not match" in str(ex), f"places that do not match the mesh are refused: '{ex}'")
try:
    cm.run(cube, r, cache, nodes=np.zeros((5, 3)))
    ok(False, "nodes of the wrong number were not refused")
except fem.FemError as ex:
    ok("nodes of the air mesh" in str(ex), f"nodes of the wrong number are refused: '{ex}'")
try:
    cm.moved_nodes(q, np.tile([0.0, 40.0, 0.0], (len(part), 1)))
    ok(False, "a movement that folds the mesh was not refused")
except fem.FemError as ex:
    ok("inside out" in str(ex), f"a movement that folds the mesh is refused in words: '{str(ex)[:100]}'")

print("\nFAILED:", FAILS) if FAILS else print("\nOK cfd3d couple")
sys.exit(1 if FAILS else 0)
