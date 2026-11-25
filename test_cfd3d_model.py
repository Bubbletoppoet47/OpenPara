"""cfd3d_model.py (the setup of a 3D Fluid Flow run, no Qt): the box around the part, the roles of its faces, the sizes, the estimate of the mesh, what stops a run and
what only warns, the shadow of a part, the verdicts of a result, and one run of a cube through the same path as the window.   python test_cfd3d_model.py"""
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

FAILS = []
T0 = time.time()


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b_, rel, what):
    err = abs(a - b_) / max(abs(b_), 1e-300)
    ok(err <= rel, f"{what}: {a:.6g} against {b_:.6g} ({err * 100:.3f} %, limit {rel * 100:g} %)")


cube = sg.analyze(b.Box(10, 10, 10), None)
block = sg.analyze(b.Pos(15, 10, 8) * b.Box(30, 20, 16) - b.Pos(15, 10, 8) * b.Cylinder(5, 16), None)

# ------------------------------------------------------------------------------------------------------------------- the default setup, the box, the roles
print("-- the setup and the box")
s = cm.default_setup()
ok(s["fluid"]["name"] == "Air 20 C" and s["fluid"]["rho"] > 1.0 and s["fluid"]["k"] > 0.02, "the default fluid is air with its conductivity and specific heat")
ok(s["flow"]["speed"] == 0.05 and s["flow"]["dir"] == "+x" and not s["flow"]["heat"], "a slow flow toward +x, no temperature")
ok(all(s[k] == [] for k in cm.KEYS) and s["mesh"]["order"] == 1, "no conditions, linear elements")
lo, hi = cm.domain_box(cube, s)
ok(np.allclose(lo, [-15, -20, -20]) and np.allclose(hi, [35, 20, 20]), f"the box of a 10 mm cube (centred on the origin) toward +x: 1 part upstream, 3 downstream, 1.5 at the sides ({lo.tolist()} {hi.tolist()})")
s2 = cm.default_setup()
s2["flow"]["dir"] = "-y"
lo2, hi2 = cm.domain_box(cube, s2)
ok(np.allclose(lo2, [-20, -35, -20]) and np.allclose(hi2, [20, 15, 20]), "toward -y the long side is at the low end of y")
ok(cm.box_roles("+x") == ("x-", "x+", ["y-", "y+", "z-", "z+"]), "toward +x: in on x-, out on x+, slip planes on the other four")
ok(cm.box_roles("-z") == ("z+", "z-", ["x-", "x+", "y-", "y+"]), "toward -z: in on z+, out on z-")
ok(cm.part_size(block) == 30.0, "the size of the part is its longest side")
hn, hf = cm.sizes_mm(cube, s)
ok(abs(hn - 10 / cm.NEAR_DIVISOR) < 1e-3 and abs(hf - 50 / cm.FAR_DIVISOR) < 1e-2, f"automatic sizes: {hn:.3f} on the part, {hf:.3f} far away")
s["h"] = 2.0
ok(cm.sizes_mm(cube, s)[0] == 2.0, "a typed size on the part is used")
s["domain"]["h_far"] = 1.0
ok(cm.sizes_mm(cube, s) == (2.0, 2.0), "a far size smaller than the near one is lifted to it")
a, share = cm.frontal_area(cube, cm.default_setup())
near(a, 100.0, 1e-9, "the box around the cube seen from the flow, mm2")
near(share, 100.0 / (40 * 40), 1e-9, "the share of the cross-section of the box")

# ------------------------------------------------------------------------------------------------------------------- the estimate of the mesh
print("-- the estimate of the number of nodes (against real meshes)")
for nm, geom, h in (("cube", cube, 0.0), ("cube, fine", cube, 1.25), ("cube, coarse", cube, 2.5), ("block with a hole", block, 0.0), ("block, coarse", block, 3.75)):
    st = cm.default_setup()
    st["h"] = h
    r = cm.resolve(geom, st)
    q = cm.get_mesh(geom, r, {})
    e = cm.estimate_nodes(geom, st)
    ok(0.75 <= e / len(q["nodes"]) <= 1.3, f"{nm}: estimate {e:,} against {len(q['nodes']):,} nodes (ratio {e / len(q['nodes']):.2f})")
    ok(q["quality"]["elements"] == len(q["tets"]) if "elements" in q["quality"] else True, f"{nm}: the quality is reported")

# ------------------------------------------------------------------------------------------------------------------- what stops a run, what only warns
print("-- ready to run, and the warnings")
s = cm.default_setup()
ok(cm.check_ready(s, cube) is None, "a cube in the default setup is ready")
ok("single part" in cm.check_ready(s, dict(cube, bodies=[{"name": "a"}, {"name": "b"}])), "an assembly is refused with the reason")
for key, val, text in (("speed", 0.0, "speed"), ("dir", "up", "direction")):
    t = cm.default_setup()
    t["flow"][key] = val
    ok(text in cm.check_ready(t, cube).lower(), f"flow {key} {val!r}: '{cm.check_ready(t, cube)}'")
t = cm.default_setup()
t["fluid"]["mu"] = 0.0
ok("viscosity" in cm.check_ready(t, cube), "no viscosity")
t = cm.default_setup()
t["fluid"]["rho"] = -1.0
ok("density" in cm.check_ready(t, cube), "negative density")
t = cm.default_setup()
t["domain"]["up"] = 0.0
ok("room" in cm.check_ready(t, cube), "no room upstream")
t["domain"]["up"] = -1.0
ok("negative" in cm.check_ready(t, cube), "a negative margin")
t = cm.default_setup()
t["flow"]["heat"] = True
t["fluid"]["k"] = 0.0
ok("conductivity" in cm.check_ready(t, cube), "temperature without a conductivity")
t["fluid"]["k"], t["flow"]["T_in"] = 0.02, 0.0
ok("0 K" in cm.check_ready(t, cube), "an inflow temperature of zero kelvin")
t = cm.default_setup()
t["h"] = 0.002
why = cm.check_ready(t, cube)
ok(why is not None and "nodes" in why, f"a size that would make a huge mesh is refused: '{why}'")
t["h"] = -1.0
ok("negative" in cm.check_ready(t, cube), "a negative element size")
t = cm.default_setup()
t["flow"]["speed"] = 5.0
n = cm.notes(t, cube)
ok(len(n) == 1 and "Reynolds number is 3," in n[0] or "Reynolds number is 2," in n[0], f"a fast flow warns about the Reynolds number: '{n[0][:70] if n else ''}'")
t = cm.default_setup()
t["domain"].update({"side": 0.1, "up": 0.5, "down": 1.0})
n = cm.notes(t, cube)
ok(any("cross-section" in x for x in n), "a box that is hardly wider than the part warns about blockage")
ok(cm.notes(cm.default_setup(), cube) == [], "the default has no warning")
ok(cm.notes(cm.default_setup(), dict(cube, bodies=[1])) == [], "an assembly has none (it is refused instead)")
t = cm.default_setup()
t["h"] = 0.0
t["mesh"] = dict(t["mesh"], advanced=True, hmin=9.0)
try:
    cm.resolve(cube, t)
    ok(False, "a minimum size larger than the element size was not refused")
except fem.FemError as ex:
    ok("minimum size" in str(ex), f"a minimum size larger than the element size is refused: '{ex}'")
t["mesh"] = dict(t["mesh"], type="hexdom", hmin=0.0)
try:
    cm.resolve(cube, t)
    ok(False, "hexahedra were not refused")
except fem.FemError as ex:
    ok("tetrahedra" in str(ex).lower(), f"a hexahedral mesh type is refused: '{ex}'")
t = cm.default_setup()
t["temps"].append({"name": "x", "faces": [{"kind": "plane", "center": [99, 99, 99], "normal": [1, 0, 0], "area": 1.0}]})
try:
    cm.resolve(cube, t)
    ok(False, "a lost face was not refused")
except fem.FemError as ex:
    ok(True, f"a condition on a face that is gone is refused: '{str(ex)[:80]}'")

# ------------------------------------------------------------------------------------------------------------------- the shadow of a part
print("-- the shadow (the area the flow sees)")
q = cm.get_mesh(block, cm.resolve(block, cm.default_setup()), {})
tris = np.vstack([q["patches"][i] for i in range(7)])
for axis, want, what in ((0, 20 * 16, "along x: the 20 x 16 face; the hole does not change the shadow"), (1, 30 * 16, "along y: 30 x 16"),
                         (2, 30 * 20 - np.pi * 25, "along z, down the hole: 30 x 20 less the hole you can see through")):
    near(cm.silhouette_area(q["nodes"], tris, axis) * 1e6, want, 0.02, f"the shadow of the block {what} (mm2)")
ok(cm.silhouette_area(q["nodes"], np.zeros((0, 3), np.int64), 0) == 0.0, "no surface, no shadow")
sph = sg.analyze(b.Sphere(5), None)
qs = cm.get_mesh(sph, cm.resolve(sph, dict(cm.default_setup(), h=0.8)), {})
ts = np.vstack(list(qs["patches"][i] for i in qs["patches"] if isinstance(i, int)))
near(cm.silhouette_area(qs["nodes"], ts, 1) * 1e6, np.pi * 25, 0.03, "a sphere of radius 5 casts pi r2 (the facets cut a little off)")

# ------------------------------------------------------------------------------------------------------------------- the verdicts
print("-- verdicts")
ok(cm.energy_verdict(0.02) == ("ok", "OK") and cm.energy_verdict(0.2)[0] == "warn" and cm.energy_verdict(0.5) == ("bad", "CHECK"), "the energy mismatch is OK below 10 %, COARSE to 35 %, CHECK above")
fake = {"status": "converged", "summary": {"mass": {"mismatch": 0.001}, "energy": {"mismatch": 0.02}}}
ok(cm.result_notes(fake) == [], "a result that settled, balanced in mass and in energy needs no remark")
ok(any("did not settle" in x for x in cm.result_notes(dict(fake, status="stalled"))), "a flow that did not settle says so")
bad = {"status": "converged", "summary": {"mass": {"mismatch": 0.05}, "energy": {"mismatch": 0.2}}}
ok(len(cm.result_notes(bad)) == 2, "a bad mass balance and a coarse energy balance each get a remark")

# ------------------------------------------------------------------------------------------------------------------- a run through the whole path
print("-- a cube in air through the model (Re 40)")
s = cm.default_setup()
s["flow"].update({"speed": 0.0606, "heat": True, "T_in": 293.15})
s["h"] = 1.25
s["temps"].append({"name": "Hot", "faces": [sg.face_sig(cube, f["id"]) for f in cube["faces"] if abs(f["normal"][2] - 1) < 1e-6]})
s["temps"][0]["T"] = 323.15
cache = {}
r = cm.resolve(cube, s)
ok(r["inlet"] == "x-" and r["outlet"] == "x+" and r["temps"][0]["fids"] and r["heat"], "resolved: the inlet and outlet of the box, the face of the condition")
t = time.time()
res = cm.run(cube, r, cache)
sm_ = res["summary"]
ok(res["status"] == "converged" and sm_["mass"]["mismatch"] < 0.01, f"converged in {res['steps']} steps ({time.time() - t:.1f} s), mass {sm_['mass']['mismatch'] * 100:.3f} %")
near(sm_["Re"], 40.0, 0.01, "the Reynolds number of the cube")
near(sm_["area_front_m2"], 1e-4, 0.01, "the area the flow sees of the cube (m2)")
ok(sm_["drag"] > 0 and abs(np.linalg.norm(sm_["side"])) < 0.02 * sm_["drag"], f"drag {sm_['drag']:.3e} N, side force {np.linalg.norm(sm_['side']):.1e}")
near(sm_["drag_pressure"] + sm_["drag_viscous"], sm_["drag"], 1e-9, "pressure + friction = total")
ok(sm_["Cd"] > 0.5 and sm_["Cd"] < 3.0, f"the drag coefficient is of the order of one ({sm_['Cd']:.3f}; first order, mesh dependent)")
ok(sm_["p_max"] > 0 > sm_["p_min"] or sm_["p_max"] > sm_["p_min"], f"the pressure on the part ranges {sm_['p_min']:.3e} to {sm_['p_max']:.3e} Pa")
ok(res["T_range"][1] <= 323.15 + 1e-9 and res["T_range"][0] > 293.15 - 0.08 * 30.0, f"the temperature stays between the inflow and the wall (to 8 %): {res['T_range']}")
hot = next(f for f in sm_["flows"] if f["name"] == "Hot")
ok(hot["Q"] > 0 and abs(hot["area_m2"] - 1e-4) < 1e-6, f"the hot face heats the air: {hot['Q']:.4f} W over {hot['area_m2'] * 1e6:.1f} mm2")
ok(sm_["energy"]["mismatch"] < 0.35, f"energy balance within the COARSE limit ({sm_['energy']['mismatch'] * 100:.1f} %)")
ok(cm.mesh_key(cube, r) in cache and len([k for k in cache if str(k).startswith("air:")]) == 1, "the air mesh is cached")
q1 = cache[cm.mesh_key(cube, r)]
res2 = cm.run(cube, r, cache)
ok(res2["mesh"] is q1, "a second run with the same mesh options does not mesh again")
tris_part, ids_part = cm.part_surface(res)
ok(len(tris_part) == len(ids_part) > 100 and set(ids_part.tolist()) == set(range(6)), f"the surface of the part: {len(tris_part)} triangles with their six face ids")
ok(np.allclose(cm.speed_of(res), np.linalg.norm(res["u"], axis=1)), "the speed at every node")
# the temperature does not depend on the level of the temperature scale: the energy of the same problem in kelvin offsets
s_off = cm.default_setup()
s_off.update({k: s[k] for k in ("h",)})
s_off["flow"].update({"speed": 0.0606, "heat": True, "T_in": 393.15})
s_off["temps"] = [dict(s["temps"][0], T=423.15)]
res_off = cm.run(cube, cm.resolve(cube, s_off), cache)
near(res_off["summary"]["energy"]["walls"], sm_["energy"]["walls"], 0.02, "the same problem 100 K hotter: the heat from the wall is the same")
near(res_off["summary"]["energy"]["mismatch"], sm_["energy"]["mismatch"], 0.1, "and so is the energy mismatch (the enthalpy is counted from the inflow temperature)")
# a direction and a speed that cannot be right
s3 = cm.default_setup()
s3["flow"]["dir"] = "-z"
r3 = cm.resolve(cube, s3)
ok((r3["inlet"], r3["outlet"]) == ("z+", "z-"), "toward -z the fluid comes in on z+")

print(f"\n{len(FAILS)} failed, {time.time() - T0:.0f} s")
for f in FAILS:
    print("   FAIL:", f)
sys.exit(1 if FAILS else 0)
