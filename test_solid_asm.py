"""3D FEA of an assembly (no window): the bodies are bonded where faces lie within the bond distance, every body has its own material, the interface has
shared nodes, a part that touches nothing is reported, and the stress/deflection are right (two bars in series, a pin in a plate)."""
import faulthandler
faulthandler.dump_traceback_later(170, exit=True)
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm, solid_asm as sa

STEEL = {"name": "Steel", "density": 7850.0, "E_MPa": 200000.0, "nu": 0.3, "Sy_MPa": 250.0, "Su_MPa": 400.0}
ALU = {"name": "Aluminium", "density": 2700.0, "E_MPa": 70000.0, "nu": 0.33, "Sy_MPa": 100.0, "Su_MPa": 200.0}


def bar(z0, z1, w=20.0):
    return b.Pos(0, 0, (z0 + z1) / 2) * b.Box(w, w, z1 - z0)


def face(g, nz, body=None, at=None):
    """The outer face with the normal z * nz (of a body, or at a height)."""
    for f in g["faces"]:
        if f["interface"] or abs(f["normal"][2] - nz) > 1e-6 or (body is not None and f["body"] != body):
            continue
        if at is None or abs(f["center"][2] - at) < 1e-3:
            return f["id"]
    raise AssertionError("face not found")


# ---- two bars in series: steel 30 mm below, aluminium 20 mm above, a force pushes down on the top
g = sa.analyze_assembly([("Base", bar(0, 30), STEEL), ("Block", bar(30, 50), ALU)])
assert len(g["bodies"]) == 2 and len(g["bonds"]) == 1 and abs(g["bonds"][0]["area"] - 400) < 1e-6 and not g["floating"] and sa.check(g) is None
assert sum(f["interface"] for f in g["faces"]) == 1 and len(g["solids"]) == 2
assert g["bodies"][0]["material"]["E"] == 200000.0 and g["bodies"][1]["material"]["rho"] == 2700.0
assert abs(g["volume"] - 20000) < 1e-3
setup = sm.default_setup()
setup["h"] = 5.0
setup["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(g, face(g, -1, at=0.0))]}]
setup["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, face(g, 1, at=50.0))], "f": [0.0, 0.0, -10000.0]}]
assert sm.check_ready(setup, g) is None
r = sm.resolve(g, setup)
assert [m["E"] for m in r["materials"]] == [200000.0, 70000.0]
res = sm.run(g, r, {})
want = 10000.0 * (30 / 200000.0 + 20 / 70000.0) / 400.0
assert abs(res["umax"] - want) / want < 0.04, (res["umax"], want)
assert res["equilibrium"] < 1e-6 and abs(res["reaction"][2] - 10000) < 1e-3
bd = {x["name"]: x for x in res["bodies"]}
assert abs(bd["Base"]["volume"] - 12000) < 1e-3 and abs(bd["Block"]["volume"] - 8000) < 1e-3
assert abs(res["mass"] - (12000 * 7850 + 8000 * 2700) * 1e-9) < 1e-9
assert abs(np.median(res["vm_el"]) - 25.0) < 1.0                                          # 10000 N / 400 mm2 in both bars: the stress does not jump
assert abs(bd["Block"]["fos_y"] - 100.0 / bd["Block"]["vm_max"]) < 1e-9 and res["fos_y"] == min(bd["Block"]["fos_y"], bd["Base"]["fos_y"])
assert res["sy_node"].max() == 250.0 and res["sy_node"].min() == 100.0 and res["bonds"][0]["a"] == "Base"
print("series ok", res["umax"], want, "n_tets", res["n_tets"])

# shared nodes: no node of the interface belongs to one body only
q = sm.get_mesh(g, 5.0, {}, lambda: False, lambda t: None, None)
gb = [set(np.unique(x["conn"][:, :4])) for x in q["groups"]]
assert len(q["groups"]) == 2 and len(gb[0] & gb[1]) > 10, (len(q["groups"]), len(gb[0] & gb[1]))
assert np.allclose(q["conn"], np.concatenate([x["conn"] for x in q["groups"]]))
print("shared nodes", len(gb[0] & gb[1]))

# gravity uses each body's own density: the weight is carried by the reaction
setup["loads"] = [{"kind": "gravity", "g": 9.81, "dir": [0, 0, -1]}]
res = sm.run(g, sm.resolve(g, setup), {})
want_w = (12000 * 7850 + 8000 * 2700) * 1e-9 * 9.81
assert abs(res["reaction"][2] - want_w) / want_w < 1e-6, (res["reaction"], want_w)

# the body's material can be changed in the setup: the block as steel makes it stiffer
setup["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, face(g, 1, at=50.0))], "f": [0.0, 0.0, -10000.0]}]
setup["body_mats"] = {"Block": {"E": 200000.0, "nu": 0.3, "rho": 7850.0, "sy": 250.0, "su": 400.0}}
res2 = sm.run(g, sm.resolve(g, setup), {})
want2 = 10000.0 * (50 / 200000.0) / 400.0
assert abs(res2["umax"] - want2) / want2 < 0.04, (res2["umax"], want2)
setup["body_mats"] = {"Block": {"E": -5.0}}
assert "Block" in sm.check_ready(setup, g) and "E > 0" in sm.check_ready(setup, g)
setup["body_mats"] = {}
print("materials ok")

# ---- the bond distance
gap = lambda d, tol=0.0: sa.analyze_assembly([("Base", bar(0, 30), STEEL), ("Block", bar(30 + d, 50 + d), ALU)], tol)
g1 = gap(0.003)                                                  # a gap inside the automatic distance: bonded
assert len(g1["bonds"]) == 1 and not g1["floating"]
g2 = gap(0.4)                                                    # a gap of 0.4 mm: not bonded, and the message says how far to raise the distance
assert g2["bonds"] == [] and g2["floating"] == [1] and "0.42" in g2["hints"][0] and "Block" in sa.check(g2)
g3 = gap(0.4, 0.5)
assert len(g3["bonds"]) == 1 and not g3["floating"] and abs(g3["tol"] - 0.5) < 1e-12
res3 = None
s3 = sm.default_setup(); s3["h"] = 6.0
s3["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(g3, face(g3, -1, at=0.0))]}]
s3["loads"] = [{"kind": "force", "faces": [sg.face_sig(g3, face(g3, 1))], "f": [0.0, 0.0, -10000.0]}]
res3 = sm.run(g3, sm.resolve(g3, s3), {})
assert res3["equilibrium"] < 1e-6 and 0.9 * want < res3["umax"] < 1.1 * want, res3["umax"]
try:
    sm.run(g2, sm.resolve(g2, s3), {})
except Exception:
    pass
assert sm.check_ready(s3, g2) is not None and sm.check_ready(s3, g3) is None
print("bond distance ok")

# ---- a part on only a part of a face, and a part that overlaps another one
g4 = sa.analyze_assembly([("Base", bar(0, 30, 40.0), STEEL), ("Block", bar(30, 50, 20.0), ALU)])
assert len(g4["bonds"]) == 1 and abs(g4["bonds"][0]["area"] - 400) < 1e-6 and sum(1 for f in g4["faces"] if not f["interface"] and f["body"] == 0) == 6
g5 = sa.analyze_assembly([("Base", bar(0, 30), STEEL), ("Block", bar(28, 50), ALU)])
assert len(g5["overlaps"]) == 1 and abs(g5["overlaps"][0]["volume"] - 800) < 1e-3 and any("overlap" in n for n in g5["notes"]) and len(g5["bonds"]) == 1
print("pieces ok")

# ---- a pin in a hole of a plate (curved bond); the pin is pulled out sideways by a support on the plate edge
plate = b.Box(60, 60, 10) - b.Cylinder(5, 20)
g6 = sa.analyze_assembly([("Plate", plate, STEEL), ("Pin", b.Cylinder(5, 20), ALU)])
assert len(g6["bonds"]) == 1 and abs(g6["bonds"][0]["area"] - 2 * np.pi * 5 * 10) < 1e-3 and not g6["floating"]
print("pin ok")

# ---- a steel pin bonded in a steel plate behaves like the solid plate (the curved bond transfers everything): same stretch under tension
def stretch(bodies):
    gg = sa.analyze_assembly(bodies)
    left = next(f["id"] for f in gg["faces"] if not f["interface"] and f["normal"][0] < -0.99)
    right = next(f["id"] for f in gg["faces"] if not f["interface"] and f["normal"][0] > 0.99)
    st = sm.default_setup(); st["h"] = 6.0
    st["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(gg, left)]}]
    st["loads"] = [{"kind": "force", "faces": [sg.face_sig(gg, right)], "f": [6000.0, 0.0, 0.0]}]
    return sm.run(gg, sm.resolve(gg, st), {}), gg
solid_res, _ = stretch([("Plate", b.Box(60, 30, 10), STEEL)])
pinned_res, gp = stretch([("Plate", b.Box(60, 30, 10) - b.Cylinder(5, 10), STEEL), ("Pin", b.Cylinder(5, 10), STEEL)])
assert len(gp["bonds"]) == 1 and pinned_res["equilibrium"] < 1e-6
assert abs(pinned_res["umax"] - solid_res["umax"]) / solid_res["umax"] < 0.03, (pinned_res["umax"], solid_res["umax"])
holed_res, _ = stretch([("Plate", b.Box(60, 30, 10) - b.Cylinder(5, 10), STEEL)])
assert holed_res["umax"] > 1.03 * solid_res["umax"] and pinned_res["umax"] < holed_res["umax"]          # the empty hole is more flexible: the pin does carry load
print("bonded pin ok", solid_res["umax"], pinned_res["umax"], holed_res["umax"])

# ---- hex-dominant is asked for: an assembly is meshed with tetrahedra and says so
import solid_mesh as smesh
s7 = dict(setup); s7["mesh"] = dict(smesh.default_mesh(), advanced=True, type="hexdom")
r7 = sm.resolve(g, s7)
res7 = sm.run(g, r7, {})
assert res7["counts"]["hexes"] == 0 and "tetrahedra" in (res7.get("hexdom_note") or "")
print("all ok")
