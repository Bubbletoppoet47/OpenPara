"""3D FEA, assembly joined by SCREWS (no window): the faces between two parts are cut into patches, the parts touch with frictionless contact except on the
patches that carry a screw, the force through each patch is read (shear and tension), and the AISI S100-16 J4 checks are made on it.  Exact things: the
shear through the screws adds up to the load, the tension is the pull plus the contact force (prying), a part that nothing holds is refused, the checks come
from the Sheets equations, and a change of the screw numbers alone is checked again without a new solution."""
import faulthandler
faulthandler.dump_traceback_later(175, exit=True)
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "addons_src", "simulation"),
                os.path.join(HERE, "shared")]
import math
import numpy as np
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm, solid_asm as sa, solid_screw as screw, solid_contact as scon

STEEL = {"name": "Steel", "density": 7850.0, "E_MPa": 200000.0, "nu": 0.3, "Sy_MPa": 250.0, "Su_MPa": 400.0}


def box(x0, x1, y0, y1, z0, z1):
    return b.Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * b.Box(x1 - x0, y1 - y0, z1 - z0)


BODIES = [("A", box(0, 100, 0, 40, 0, 10), STEEL), ("B", box(0, 100, 0, 40, 10, 20), STEEL)]     # two plates, 10 mm each, one on the other
g0 = sa.analyze_assembly(BODIES)
iface = [f for f in g0["faces"] if f["interface"]]
assert len(iface) == 1 and iface[0]["area"] == 4000.0 and set(iface[0]["bodies"]) == {0, 1}
SPLIT = [{"face": sg.face_sig(g0, iface[0]["id"]), "cols": 5, "rows": 3, "u": None}]       # 5 columns x 3 rows of 20 x 13.3 mm patches
g = sa.analyze_assembly(BODIES, 0.0, SPLIT)
assert not g["notes"], g["notes"]
patches = {f["cell"]: f["id"] for f in g["faces"] if f["interface"]}
assert len(patches) == 15 and abs(sum(g["faces"][i]["area"] for i in patches.values()) - 4000.0) < 1e-6


def outer(nrm, axis, val, body):
    return next(f["id"] for f in g["faces"] if not f["interface"] and f["body"] == body and abs(f["normal"][axis] - nrm) < 1e-6 and abs(f["center"][axis] - val) < 1e-6)


def setup_for(cells, load, load_face, name="S"):
    st = sm.default_setup()
    st["h"] = 7.0
    st["joint"] = "contact"
    st["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(g, outer(-1, 2, 0.0, 0))]}]
    st["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, load_face)], "f": list(load)}]
    sc = screw.default_screw()
    sc.update({"name": name, "faces": [sg.face_sig(g, patches[c]) for c in cells]})
    st["screws"] = [sc] if cells else []
    return st


def solve(st):
    r = sm.resolve(g, st)
    return r, sm.run(g, r, {}, lambda: False, lambda t: None)


# ---- 1. a shear load carried by one screw: the screw takes all of it, the tension is the prying (what the contact pushes with)
st = setup_for([(2, 1)], (1000.0, 0.0, 0.0), outer(1, 0, 100.0, 1))
r, res = solve(st)
assert res["joint"] == "contact" and res["equilibrium"] < 1e-9, res["equilibrium"]
assert len(res["screws"]) == 1 and res["contact"]["converged"], res["contact"]
s1 = res["screws"][0]
assert abs(s1["V"] - 1000.0) < 1e-6, s1["V"]                                        # all the shear goes through the one screw (exact)
assert abs(s1["T"] - res["contact"]["force"]) < 1e-6 * 1000, (s1["T"], res["contact"]["force"])   # prying: the screw holds against the contact force
assert s1["T"] > 0 and res["contact"]["closed"] < res["contact"]["pairs"], res["contact"]       # the plate lifts off on part of the joint
assert abs(s1["F"][0] + 1000.0) < 1e-6                                              # the patch pushes the upper plate back with the load
print("one screw ok: V", s1["V"], "T", s1["T"], "iterations", res["contact"]["iterations"])

# ---- 2. the checks are those of the Sheets equations (J4.3.1: tilting and bearing), and the ratios are demand / strength
import std_aisi16
f431 = next(f for f in std_aisi16.SCREW_FUNCS if f.name == "J4_3_1")
cap = screw._call(f431.impl, "ASD", t1=10 / 25.4, t2=10 / 25.4, d=4.8 / 25.4, Fu1=400 * screw.PSI_PER_MPA, Fu2=400 * screw.PSI_PER_MPA) * screw.LBF_N
ck = {c["clause"]: c for c in s1["checks"]}
assert abs(ck["J4.3.1"]["capacity"] - cap) < 1e-6 * cap and abs(ck["J4.3.1"]["ratio"] - 1000.0 / cap) < 1e-9, (ck["J4.3.1"], cap)
assert s1["through"] and abs(s1["tc"] - 10.0) < 1e-9 and "right through" in " ".join(s1["notes"]), s1["notes"]      # a 25 mm screw through two 10 mm sheets
assert ck["J4.2"]["unit"] == "mm" and "here 20 mm" in ck["J4.2"]["note"], ck["J4.2"]["note"]        # the edge: 20 mm from the side of the 40 mm width
assert not ck["J4.3.2"]["applies"] and s1["status"] == "incomplete"                  # the screw's own strengths were not typed
print("checks ok:", s1["worst_name"], round(s1["worst"], 3))

# ---- 3. the screw length decides the pull-out: 15 mm reaches 5 mm into the base sheet
sc15 = dict(screw.default_screw(), length=15.0)
rec = screw.evaluate(g, sc15, patches[(2, 1)], {"V": 100.0, "T": 100.0, "a": 0, "b": 1, "area": 266.7, "n": [0, 0, 1]}, sm.body_materials(g, st), "ASD")
assert not rec["through"] and abs(rec["tc"] - 5.0) < 1e-9 and abs(rec["reach"] - 5.0) < 1e-9, (rec["tc"], rec["reach"])
f441 = next(f for f in std_aisi16.SCREW_FUNCS if f.name == "J4_4_1")
cap441 = screw._call(f441.impl, "ASD", tc=5 / 25.4, d=4.8 / 25.4, Fu2=400 * screw.PSI_PER_MPA) * screw.LBF_N
pull = next(c for c in rec["checks"] if c["clause"] == "J4.4.1")
assert abs(pull["capacity"] - cap441) < 1e-6 * cap441, (pull["capacity"], cap441)
short = screw.evaluate(g, dict(screw.default_screw(), length=8.0), patches[(2, 1)], {"V": 1.0, "T": 1.0, "a": 0, "b": 1, "area": 266.7, "n": [0, 0, 1]}, sm.body_materials(g, st), "ASD")
assert short["reach"] == 0.0 and "does not reach" in " ".join(short["notes"]), short["notes"]
print("length ok")

# ---- 4. another design method or other numbers: checked again from the same forces, no new solution
sc2 = dict(st["screws"][0], Pnvs=2500.0, Pnts=2000.0)
st2 = dict(st, screws=[sc2], design="LRFD")
r2 = sm.resolve(g, st2)
assert sm.recheck(g, r2, res) and res["design"] == "LRFD" and res["screws"][0]["method"] == "LRFD"
c2 = {c["clause"]: c for c in res["screws"][0]["checks"]}
assert c2["J4.3.2"]["applies"] and abs(c2["J4.3.2"]["ratio"] - 1000.0 / c2["J4.3.2"]["capacity"]) < 1e-12 and abs(res["screws"][0]["V"] - 1000.0) < 1e-6
st3 = dict(st2, screws=[dict(sc2, faces=[sg.face_sig(g, patches[(1, 1)])])])
assert not sm.recheck(g, sm.resolve(g, st3), res)                                    # another patch: that needs a new solution
print("recheck ok")

# ---- 5. two screws placed symmetrically about the load line share the shear, and it adds up to the load
st = setup_for([(2, 0), (2, 2)], (1000.0, 0.0, 0.0), outer(1, 0, 100.0, 1))
r, res = solve(st)
assert res["equilibrium"] < 1e-9 and len(res["screws"]) == 2
v = [s_["V"] for s_ in res["screws"]]
Fs = [s_["F"] for s_ in res["screws"]]
assert abs(sum(f[0] for f in Fs) + 1000.0) < 1e-6 and abs(sum(f[1] for f in Fs)) < 1e-6, Fs          # the x forces add up to the load, the y forces cancel (exact)
assert abs(v[0] - v[1]) < 0.05 * 500 and all(abs(x - 500.0) < 0.1 * 500 for x in v), v               # each about half (the mesh is not exactly symmetric)
print("   V", v, [s_["F"] for s_ in res["screws"]])
print("two screws ok", v)

# ---- 6. a pull on the upper plate goes through the screw as tension: the pull plus what the contact pushes with
st = setup_for([(2, 1)], (0.0, 0.0, 1000.0), outer(1, 2, 20.0, 1))
r, res = solve(st)
s3 = res["screws"][0]
assert res["equilibrium"] < 1e-9 and abs(s3["T"] - (1000.0 + res["contact"]["force"])) < 1e-6 * 1000, (s3["T"], res["contact"]["force"])
print("   V in a symmetric pull", s3["V"])
print("tension ok", s3["T"])

# ---- 7. nothing holds the upper plate: refused, not solved
st = setup_for([], (1000.0, 0.0, 0.0), outer(1, 0, 100.0, 1))
try:
    solve(st)
    raise SystemExit("a plate that nothing holds was solved")
except fem.FemError as ex:
    assert "slide away" in str(ex) and "B" in str(ex), str(ex)
print("held check ok")

# ---- 8. the same screw on many patches at once: the model gives one record per patch, and a patch cannot carry two screws
cells = [(1, 0), (1, 2), (3, 0), (3, 2)]
st = setup_for(cells, (0.0, 0.0, 1000.0), outer(1, 2, 20.0, 1))
r, res = solve(st)
assert len(res["screws"]) == 4 and {s_["screw"] for s_ in res["screws"]} == {"S"} and res["equilibrium"] < 1e-9
assert abs(sum(s_["T"] for s_ in res["screws"]) - (1000.0 + res["contact"]["force"])) < 1e-3, (sum(s_["T"] for s_ in res["screws"]), res["contact"]["force"])
assert all(any(c["clause"] == "J4.1" for c in s_["checks"]) for s_ in res["screws"])          # the spacing to the nearest screw is checked
st["screws"].append(dict(screw.default_screw(), name="again", faces=[sg.face_sig(g, patches[(1, 0)])]))
try:
    sm.resolve(g, st)
    raise SystemExit("one patch took two screws")
except fem.FemError as ex:
    assert "same patch" in str(ex), str(ex)
print("many patches ok")

# ---- 9. a bolt: shear and tension only, the bearing of both parts, no pull-out of a nut
bolt = dict(screw.default_screw("bolt"), Fnv=372.0, Fnt=620.0)
recb = screw.evaluate(g, bolt, patches[(2, 1)], {"V": 100.0, "T": 50.0, "a": 0, "b": 1, "area": 266.7, "n": [0, 0, 1]}, sm.body_materials(g, st), "ASD")
cl = {c["clause"] + c["name"] for c in recb["checks"]}
assert any(c["clause"] == "J3.3.1" for c in recb["checks"]) and any(c["clause"] == "J3.4" for c in recb["checks"]) and not any("J4.4" in c["clause"] for c in recb["checks"]), cl
assert recb["status"] in ("ok", "fails") and recb["worst"] is not None
print("bolt ok", recb["worst_name"])

# ---- 10. a patch that is far bigger than the screw is reported (it bonds more than a screw holds)
big = screw.evaluate(g, screw.default_screw(), patches[(2, 1)], {"V": 1.0, "T": 0.0, "a": 0, "b": 1, "area": 4000.0, "n": [0, 0, 1]}, sm.body_materials(g, st), "ASD")
assert any("times the area of the screw" in n for n in big["notes"]), big["notes"]
print("all ok")
