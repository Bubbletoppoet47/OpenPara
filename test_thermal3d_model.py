"""thermal3d_model.py: the setup of a 3D Thermal analysis - its defaults, the faces turned into face ids (a whole face, a patch of a split face, a face that is gone),
the material of every body, what stops a run before it starts, and the run itself against a closed form.   python test_thermal3d_model.py"""
import os
import sys
import tempfile

os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "thermal3d"),
                os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg
import solid_model as sm
import solid_asm as sasm
import solid_fem as fem
import thermal_mat
import thermal3d_model as tm

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def fid(g, normal):
    n = np.asarray(normal, float)
    return next(f["id"] for f in g["faces"] if np.dot(f["normal"], n) > 0.99 and not f.get("interface"))


def raises(fn, words, what):
    try:
        fn()
        ok(False, f"{what}: refused")
    except fem.FemError as ex:
        ok(all(w in str(ex) for w in words), f"{what}: '{str(ex)[:100]}'")


# ------------------------------------------------------------------------------------------------------------------- the defaults
s = tm.default_setup()
ok(set(s) >= {"dims", "splits", "bond_tol", "body_mats", "body_h", "h", "mesh"}, "a new setup has every key of the 3D base window")
ok(all(s[k] == [] for k in tm.KEYS) and s["analysis"] == "steady" and s["theta"] == 1.0, "no conditions, a steady analysis")
m = s["material"]
ok(m["name"] == thermal_mat.DEFAULT and m["k"] == 167.0 and m["gen"] == 0.0, f"the material is the library's default: {m}")
ok(abs(s["T0"] - 293.15) < 1e-12 and s["t_end"] > 0 and s["steps"] >= 1, "a transient run starts at 20 degC and has a time and steps")
ok([k for _n, k in tm.CONDITION_KINDS] == list(tm.KEYS) and set(tm.KIND_OF.values()) == set(tf_kinds := ("temp", "flux", "power", "conv", "rad", "ins")),
   "the condition lists and the solver's kinds match")

# ------------------------------------------------------------------------------------------------------------------- one part: faces to ids, the run
bar = b.Box(100.0, 20.0, 10.0)
g = sg.analyze(bar, None)
left, right, top = fid(g, [-1, 0, 0]), fid(g, [1, 0, 0]), fid(g, [0, 0, 1])
setup = tm.default_setup()
setup["fluxes"].append({"faces": [sg.face_sig(g, left)], "q": 20000.0})
setup["convs"].append({"name": "Cooling", "faces": [sg.face_sig(g, right)], "h": 500.0, "Tinf": 300.0})
ok(tm.check_ready(setup, g) is None, "a flux in and a convection out is ready")
r = tm.resolve(g, setup)
ok(r["fluxes"][0]["fids"] == [left] and r["fluxes"][0]["name"] == "Heat flux 1", f"a condition without a name is called by its kind and number: {r['fluxes'][0]['name']}")
ok(r["convs"][0]["name"] == "Cooling" and r["convs"][0]["fids"] == [right], "and one with a name keeps it")
ok(r["materials"] == [setup["material"]] and r["materials"][0] is not setup["material"], "the material is a copy")
ok(r["analysis"] == "steady" and r["h"] == 0.0 and r["mesh"] is None, "the plain automatic mesh and a steady run")
cache = {}
res = tm.run(g, dict(r, h=8.0), cache)
kal = 167.0
Tout = 300.0 + 20000.0 / 500.0
ok(abs(res["T"][res["nodes"][:, 0] > 49.999].mean() - Tout) < 1e-6, f"the cooled end is at T_inf + q / h = {Tout} K: {res['T'][res['nodes'][:, 0] > 49.999].mean():.6f}")
ok(abs(res["Tmax"] - (Tout + 20000.0 * 0.1 / kal)) < 1e-6, f"and the hot end is hotter by q L / k (k = {kal}): {res['Tmax']:.6f}")
ok(res["names"]["fluxes"] == ["Heat flux 1"] and res["names"]["convs"] == ["Cooling"] and res["h_used"] == 8.0, "the result knows the names of the conditions and the element size")
ok(len(cache) == 1, "the mesh is kept in the cache")
res2 = tm.run(g, dict(r, h=8.0, convs=[dict(r["convs"][0], h=1000.0)]), cache)
ok(res2["mesh"] is res["mesh"] and len(cache) == 1, "a second run with other numbers uses the same mesh")
ok(res["mesh"]["order"] == 2 and res["balance"]["relative_error"] < 1e-9, "quadratic elements, and the heat balance closes")
res_auto = tm.run(g, r, {})
ok(abs(res_auto["h_used"] - sm.auto_h(g)) < 1e-12 and res_auto["h_used"] > 0, f"with no element size the automatic one is used: {res_auto['h_used']}")

# no name for a kind whose name has a space: the same words as the panel will use
ok(tm.NAMES["temps"] == "Fixed temperature" and tm.NAMES["powers"] == "Heat flow", "the kinds are named for the panel")

# a fixed temperature alone holds a steady problem; the transient settings reach the solver and give a transient result
only_t = tm.default_setup()
only_t["temps"].append({"faces": [sg.face_sig(g, left)], "T": 350.0})
ok(tm.check_ready(only_t, g) is None, "one fixed temperature is enough for a steady run")
tr_s = tm.default_setup()
tr_s.update({"analysis": "transient", "T0": 350.0, "t_end": 5.0, "steps": 5, "theta": 0.5, "frames": 3})
tr_s["temps"].append({"faces": [sg.face_sig(g, left)], "T": 300.0})
rt = tm.resolve(g, tr_s)
ok([rt[k] for k in ("analysis", "T0", "t_end", "steps", "theta", "frames")] == ["transient", 350.0, 5.0, 5, 0.5, 3], f"the transient settings reach the solver's setup: {[rt[k] for k in ('analysis', 'T0', 't_end', 'steps', 'theta', 'frames')]}")
res_t = tm.run(g, dict(rt, h=10.0))
ok(res_t["analysis"] == "transient" and len(res_t["times"]) == 3 and abs(res_t["times"][-1] - 5.0) < 1e-12 and res_t["run"]["theta"] == 0.5,
   f"and the result is a transient one with its three pictures and theta = 0.5: times {res_t['times']}")

# ------------------------------------------------------------------------------------------------------------------- what stops a run before it starts
e = tm.default_setup()
ok("fixed temperature, convection or radiation" in tm.check_ready(e, g), "a steady setup with nothing to hold its temperature is refused in words")
e["rads"].append({"faces": [sg.face_sig(g, right)], "eps": 0.0, "Ts": 300.0})
ok(tm.check_ready(e, g) is not None, "a radiation with no emissivity does not hold it")
e["rads"][0]["eps"] = 0.8
ok(tm.check_ready(e, g) is None, "one with an emissivity does")
e["rads"].clear()
e["convs"].append({"faces": [sg.face_sig(g, right)], "h": 0.0, "Tinf": 300.0})
ok(tm.check_ready(e, g) is not None, "and a convection with no coefficient does not")
e["convs"][0]["h"] = 5.0
ok(tm.check_ready(e, g) is None, "a coefficient does")
e["convs"].clear()
e["analysis"] = "transient"
ok(tm.check_ready(e, g) is None, "a transient run does not need one: the part just heats up")
for key, bad, words in (("T0", 0.0, "starting temperature"), ("t_end", 0.0, "end time"), ("steps", 0, "time step")):
    keep = e[key]
    e[key] = bad
    ok(words in tm.check_ready(e, g), f"a transient run with {key} = {bad}: {tm.check_ready(e, g)}")
    e[key] = keep
e["material"]["k"] = 0.0
ok("conductivity" in tm.check_ready(e, g), "a conductivity of zero is refused")
e["material"]["k"] = 10.0
e["material"]["cp"] = -1.0
ok("specific heat" in tm.check_ready(e, g), "and a negative specific heat")
raises(lambda: tm.resolve(g, e), ["specific heat"], "resolve says the same")
e["material"]["cp"] = 900.0
e["material"].pop("rho")
ok("needs a conductivity" in tm.check_ready(e, g), "a material that lacks a number is refused in words")
e["material"]["rho"] = 2700.0

# ------------------------------------------------------------------------------------------------------------------- faces that moved, and faces that are gone
other = sg.analyze(b.Cylinder(8.0, 30.0), None)
bad = tm.default_setup()
bad["temps"].append({"faces": [sg.face_sig(g, left)], "T": 300.0})
raises(lambda: tm.resolve(other, bad), ["Fixed temperature 1", "not in the part any more"], "a condition whose face is not in the part")
longer = sg.analyze(b.Box(120.0, 20.0, 10.0), None)
rr = tm.resolve(longer, bad)
ok(rr["temps"][0]["fids"] == [fid(longer, [-1, 0, 0])], "a longer part: the condition follows its face")

# ------------------------------------------------------------------------------------------------------------------- patches of a split face
sp = tm.default_setup()
gs = sg.analyze(bar, None)
topf = fid(gs, [0, 0, 1])
changed = sm.set_split(sp, gs, topf, 2, 1, tm.CONDITION_KINDS)
gs = sg.analyze(bar, sp["splits"])
ok(len(gs["faces"]) == 7 and changed == [], "the top face is split into two patches")
patches = [f["id"] for f in gs["faces"] if f.get("cell") is not None]
sp["fluxes"].append({"faces": [sg.face_sig(gs, patches[0])], "q": 1000.0})
sp["temps"].append({"faces": [sg.face_sig(gs, fid(gs, [0, 0, -1]))], "T": 300.0})
rs = tm.resolve(gs, sp)
ok(rs["fluxes"][0]["fids"] == [patches[0]], "a condition on one patch resolves to that patch")
res = tm.run(gs, dict(rs, h=8.0))
patch_area = gs["faces"][patches[0]]["area"] * 1e-6
ok(abs([f for f in res["flows"] if f["kind"] == "flux"][0]["Q"] - 1000.0 * patch_area) < 1e-9, f"and its heat flow is q times the area of the patch ({1000.0 * patch_area:.4f} W)")
ok(sm.patch_conditions(sp, gs, patches[0], tm.CONDITION_KINDS) == ["Heat flux 1"], "a split that would cut the patch again says which condition it removes")
sm.set_split(sp, gs, patches[0], 1, 2, tm.CONDITION_KINDS)
ok(sp["fluxes"] == [] and len(sp["temps"]) == 1, "splitting again removes the condition on that patch and keeps the others")

# ------------------------------------------------------------------------------------------------------------------- the materials of the bodies of an assembly
steel = {"name": "Steel AISI 1018", "density": 7870.0, "E_MPa": 205000.0, "nu": 0.29, "Sy_MPa": 370.0, "Su_MPa": 440.0}
alu = {"name": "Aluminum 6061", "density": 2650.0, "E_MPa": 68900.0, "nu": 0.33}
mystery = {"name": "Unobtainium", "density": 1234.0, "E_MPa": 1000.0, "nu": 0.3}
ga = sasm.analyze_assembly([("Plate", b.Pos(20, 0, 0) * b.Box(40, 20, 10), steel), ("Block", b.Pos(70, 0, 0) * b.Box(60, 20, 10), alu),
                            ("Odd", b.Pos(130, 0, 0) * b.Box(60, 20, 10), mystery)], 0.0, None)
sa = tm.default_setup()
sa["material"] = {"name": "Mine", "k": 77.0, "rho": 5000.0, "cp": 600.0, "gen": 0.0}
mats = tm.body_materials(ga, sa)
ok(mats[0]["k"] == 51.9 and mats[0]["cp"] == 486.0 and mats[0]["rho"] == 7870.0, f"a body takes the library's values for the name of its material: {mats[0]}")
ok(mats[1]["name"] == "Aluminum 6061" and mats[1]["k"] == 167.0 and mats[1]["rho"] == 2650.0, f"with its own density: {mats[1]}")
ok(mats[2]["k"] == 77.0 and mats[2]["cp"] == 600.0 and mats[2]["name"] == "Unobtainium", f"a name the library does not know gets the material of the tab: {mats[2]}")
ok(all(m["gen"] == 0.0 for m in mats), "and no heat generation")
sa["body_mats"] = {"Block": {"k": 5.0, "gen": 1.0e6}, "Plate": {"name": "Lined steel", "k": None}}
mats = tm.body_materials(ga, sa)
ok(mats[1]["k"] == 5.0 and mats[1]["gen"] == 1.0e6 and mats[1]["cp"] == 896.0, f"a body's own values over the found ones: {mats[1]}")
ok(mats[0]["name"] == "Lined steel" and mats[0]["k"] == 51.9, "a value that is None is not an override")
sa["temps"].append({"faces": [sg.face_sig(ga, fid(ga, [-1, 0, 0]))], "T": 400.0})
sa["convs"].append({"faces": [sg.face_sig(ga, next(f["id"] for f in ga["faces"] if f["normal"][0] > 0.99))], "h": 100.0, "Tinf": 300.0})
ra = tm.resolve(ga, sa)
ok(len(ra["materials"]) == 3 and ra["materials"][1]["k"] == 5.0, "resolve gives one material per body")
sa["body_mats"]["Odd"] = {"k": -1.0}
ok("Odd" in tm.check_ready(sa, ga) and "conductivity" in tm.check_ready(sa, ga), f"a bad material names its body: {tm.check_ready(sa, ga)}")
raises(lambda: tm.resolve(ga, sa), ["Odd", "conductivity"], "resolve names it too")
del sa["body_mats"]["Odd"]
res = tm.run(ga, dict(ra, h=10.0))
ok(len(res["bodies"]) == 3 and abs(res["bodies"][1]["generation"] - 1.0e6 * 60e-3 * 20e-3 * 10e-3) < 1e-9, f"the generation of a body is in its report: {res['bodies'][1]['generation']:.4f} W")
ok(res["balance"]["relative_error"] < 1e-9 and res["balance"]["generation"] > 0, "and the balance, with the generation in it, closes")

# ------------------------------------------------------------------------------------------------------------------- the mesh types
hx = tm.default_setup()
hx["mesh"].update({"advanced": True, "type": "hexdom"})
hx["temps"].append({"faces": [sg.face_sig(g, left)], "T": 300.0})
raises(lambda: tm.resolve(g, hx), ["tetrahedra"], "a hex-dominant mesh")
lin = tm.default_setup()
lin["mesh"].update({"advanced": True, "order": 1})
lin["temps"].append({"faces": [sg.face_sig(g, left)], "T": 400.0})
lin["temps"].append({"faces": [sg.face_sig(g, right)], "T": 300.0})
rl = tm.resolve(g, lin)
resl = tm.run(g, dict(rl, h=10.0))
ok(resl["mesh"]["order"] == 1 and abs(resl["flows"][0]["Q"] - 167.0 * 2e-4 * 100.0 / 0.1) < 1e-8, f"linear elements through the same setup: {resl['flows'][0]['Q']:.6f} W")

print("\nFAILED:", FAILS) if FAILS else print("\nOK thermal3d model")
sys.exit(1 if FAILS else 0)
