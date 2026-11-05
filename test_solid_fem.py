"""3D FEA numerics (no window): tension bar exact, cantilever against beam theory, pressure, gravity, point force, slide support, errors."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm

def box(L=100.0, w=10.0, t=10.0):
    return b.Box(L, w, t, align=(b.Align.MIN, b.Align.MIN, b.Align.MIN)).solid() if hasattr(b.Box(1, 1, 1), "solid") else b.Box(L, w, t)

solid = b.Solid.make_box(100, 10, 10)
g = sg.analyze(solid)
assert len(g["faces"]) == 6 and len(g["verts"]) == 8 and abs(g["volume"] - 10000) < 1e-6
def face_at(axis, side):
    n = np.zeros(3); n[axis] = side
    return next(f["id"] for f in g["faces"] if np.dot(f["normal"], n) > 0.99)
xm, xp = face_at(0, -1), face_at(0, 1)
setup = sm.default_setup()
setup["h"] = 5.0
setup["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(g, xm)]}]
setup["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [1000.0, 0.0, 0.0]}]
assert sm.check_ready(setup) is None
cache = {}
r = sm.resolve(g, setup)
res = sm.run(g, r, cache)
E_, A, L, F = 200000.0, 100.0, 100.0, 1000.0
# tension: stress F/A = 10 MPa. Fixed face blocks the Poisson contraction there, so away from the ends it is uniform
assert abs(res["umax"] - F * L / (A * E_)) / (F * L / (A * E_)) < 0.02, (res["umax"], F * L / (A * E_))
assert abs(np.median(res["vm_el"]) - 10.0) < 0.5, np.median(res["vm_el"])
assert res["equilibrium"] < 1e-6 and abs(res["reaction"][0] + 1000) < 1e-3, (res["reaction"], res["equilibrium"])
assert abs(res["volume"] - 10000) < 1e-3 and abs(res["mass"] - 10000 * 7850e-9) < 1e-6
assert res["fos_y"] == 250.0 / res["vm_max"]
n_el = res["n_tets"]
print("tension ok", res["n_tets"], "tets", res["info"])
# the mesh is cached: a second run with other loads does not mesh again
setup2 = dict(setup); setup2["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [2000.0, 0, 0]}]
res2 = sm.run(g, sm.resolve(g, setup2), cache)
assert len(cache) == 1 and abs(res2["umax"] / res["umax"] - 2) < 1e-6

# cantilever: tip load 100 N down on the free end, beam theory delta = P L^3 / (3 E I) (+ shear). Use a finer mesh
setup["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [0.0, 0.0, -100.0]}]
setup["h"] = 3.0
res = sm.run(g, sm.resolve(g, setup), cache)
I = 10 * 10 ** 3 / 12.0
beam = 100.0 * 100 ** 3 / (3 * E_ * I)
tip = res["u"][:, 2].min()
assert abs(abs(tip) - beam) / beam < 0.08, (tip, beam)       # includes shear deformation and the clamped-end effect
smax = 100.0 * 100 * 5 / I
assert 0.7 * smax < res["vm_max"] < 1.4 * smax, (res["vm_max"], smax)
print("cantilever ok", tip, beam, res["vm_max"], smax)

# pressure on the end face: 10 MPa pushing in = compression -10 MPa; stress 10 MPa
setup["h"] = 5.0
setup["loads"] = [{"kind": "pressure", "faces": [sg.face_sig(g, xp)], "p": 10.0}]
res = sm.run(g, sm.resolve(g, setup), cache)
assert res["u"][:, 0].min() < 0 and abs(np.median(res["vm_el"]) - 10.0) < 0.5 and abs(res["reaction"][0] - 10.0 * 100) < 1e-3, res["reaction"]
# gravity along -z on a cantilever: the reaction carries the weight
setup["loads"] = [{"kind": "gravity", "g": 9.81, "dir": [0, 0, -1]}]
res = sm.run(g, sm.resolve(g, setup), cache)
w = 10000 * 7850e-9 * 9.81
assert abs(res["reaction"][2] - w) / w < 1e-3 and res["u"][:, 2].min() < 0, (res["reaction"], w)
# a point force at a vertex
vid = int(np.argmax([v[0] + v[1] + v[2] for v in g["verts"]]))
setup["loads"] = [{"kind": "point", "vertex": sg.vert_sig(g, vid), "f": [0, 0, -50.0]}]
res = sm.run(g, sm.resolve(g, setup), cache)
assert abs(res["reaction"][2] - 50) < 1e-6
# slide support: the end face may only slide in x? (normal direction is fixed, the face can slide in y/z) with a sideways load -> needs more support
setup["supports"] = [{"mode": "slide", "faces": [sg.face_sig(g, xm)]}]
setup["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [1000.0, 0, 0]}]
try:
    sm.run(g, sm.resolve(g, setup), cache); raise SystemExit("one slide support leaves rigid motions free")
except fem.FemError as ex:
    assert "free to move" in str(ex), ex
ym, zm = face_at(1, -1), face_at(2, -1)
setup["supports"] = [{"mode": "slide", "faces": [sg.face_sig(g, xm)]}, {"mode": "slide", "faces": [sg.face_sig(g, ym)]}, {"mode": "slide", "faces": [sg.face_sig(g, zm)]}]
res = sm.run(g, sm.resolve(g, setup), cache)           # symmetry supports: uniaxial tension, free to contract
print("slide", np.median(res["vm_el"]), res["umax"], res["equilibrium"], res["reaction"])
assert abs(np.median(res["vm_el"]) - 10.0) < 0.2 and abs(res["umax"] - 0.005) / 0.005 < 0.02 and res["equilibrium"] < 1e-6, (res["vm_el"].max(), res["umax"])
# errors
setup["supports"] = []
assert sm.check_ready(setup) == "Add at least one support."
setup["supports"] = [{"mode": "fixed", "faces": [{"type": "face", "kind": "plane", "center": [500, 500, 500], "normal": [1, 0, 0], "area": 100}]}]
try:
    sm.resolve(g, setup); raise SystemExit("a lost face must be reported")
except fem.FemError as ex:
    assert "not in the part any more" in str(ex)
# a face moves with the geometry: a longer bar finds the same end face
g2 = sg.analyze(b.Solid.make_box(150, 10, 10))
fid2 = sg.match_face(g2, sg.face_sig(g, xp))
assert fid2 is not None and abs(g2["faces"][fid2]["center"][0] - 150) < 1e-6
# a cylinder hole
cyl = b.Solid.make_box(60, 40, 10) - b.Solid.make_cylinder(6, 10, b.Plane.XY.offset(0)).moved(b.Location((30, 20, 0)))
g3 = sg.analyze(cyl)
kinds = sorted(f["kind"] for f in g3["faces"])
assert "cylinder" in kinds, kinds
hole = next(f["id"] for f in g3["faces"] if f["kind"] == "cylinder")
left = next(f["id"] for f in g3["faces"] if np.dot(f["normal"], [-1, 0, 0]) > 0.99)
right = next(f["id"] for f in g3["faces"] if np.dot(f["normal"], [1, 0, 0]) > 0.99)
s3 = sm.default_setup(); s3["h"] = 4.0
s3["supports"] = [{"mode": "bolt", "faces": [sg.face_sig(g3, hole)]}]
s3["loads"] = [{"kind": "pressure", "faces": [sg.face_sig(g3, right)], "p": 5.0}]
r3 = sm.run(g3, sm.resolve(g3, s3), {})
assert r3["equilibrium"] < 1e-6 and r3["vm_max"] > 5.0
print("OK solid fem")
os._exit(0)
