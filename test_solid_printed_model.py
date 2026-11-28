"""Printed-part analysis (planning/design/slicer, PA-3): a printed material through the whole 3D setup -> mesh -> solve -> result, no window.

The toolpaths are made here (roads side by side along x, or along y, in a 100 x 10 x 10 mm bar), not by the slicer.  A bar pulled along x stretches by F L / (A E_x):
with the roads along x that is the modulus ALONG the road, with the roads along y the modulus ACROSS it, and with half the plastic (a sparser infill) twice as much.
Bad print data or constants are refused in words; the adaptive loop and an assembly say they do not include the material yet."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm
import print_fabric as pf

fails = []
def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)

LEN, WID, HGT = 100.0, 10.0, 10.0
RW, RH = 0.45, 0.2
class Paths:
    def __init__(self, polylines):
        self.points = np.concatenate([np.asarray(p, float) for p in polylines])
        self.start = np.concatenate([[0], np.cumsum([len(p) for p in polylines])])
        m = len(polylines)
        self.role, self.height, self.mm3_per_mm = np.full(m, 4), np.full(m, RH), np.full(m, RW * RH)

def bar_paths(direction, density):
    """Roads along x or along y, side by side, in every layer of the bar."""
    lines = []
    sp = RW / density
    for k in range(int(round(HGT / RH))):
        z = (k + 1) * RH
        if direction == "x":
            for y in np.arange(RW / 2, WID, sp):
                lines.append([(0.0, y, z), (LEN, y, z)])
        else:
            for x in np.arange(RW / 2, LEN, sp):
                lines.append([(x, 0.0, z), (x, WID, z)])
    return Paths(lines)

solid = b.Solid.make_box(LEN, WID, HGT)
g = sg.analyze(solid)
def face_at(axis, side):
    n = np.zeros(3); n[axis] = side
    return next(f["id"] for f in g["faces"] if np.dot(f["normal"], n) > 0.99)
xm, xp = face_at(0, -1), face_at(0, 1)
CONST = {"E1": 20000.0, "E2": 3000.0, "E3": 3000.0, "G12": 1200.0, "G23": 1100.0, "G13": 1200.0, "nu12": 0.30, "nu23": 0.35, "nu13": 0.30}
tmp = tempfile.mkdtemp()

def make(printed):
    setup = sm.default_setup()
    setup["h"] = 5.0
    setup["material"] = {"E": 3000.0, "nu": 0.3, "rho": 1250.0, "sy": 50.0, "su": 60.0}
    if printed:
        setup["material"]["printed"] = printed
    setup["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(g, xm)]}]
    setup["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [1000.0, 0.0, 0.0]}]
    return setup

def fabric_file(direction, density):
    fn = os.path.join(tmp, f"{direction}_{density}.npz")
    pf.Fabric.from_paths(bar_paths(direction, density)).save(fn)
    return fn

A, F = WID * HGT, 1000.0
cache = {}
out = {}
for name, direction, dens, Ex in (("roads along x", "x", 1.0, 20000.0), ("roads along y", "y", 1.0, 3000.0), ("roads along x, half the plastic", "x", 0.5, 10000.0)):
    setup = make({"fabric": fabric_file(direction, dens), "constants": CONST})
    ok(sm.check_ready(setup) is None, f"{name}: the setup is ready ({sm.check_ready(setup)})")
    r = sm.resolve(g, setup)
    o = sm.run(g, r, cache)
    out[name] = o
    expect = F * LEN / (A * Ex)
    ok(abs(o["umax"] - expect) / expect < 0.10, f"{name}: stretch {o['umax']:.4e}, F L / (A E_x) = {expect:.4e} (10 %: a fixed end blocks the contraction, the mesh is coarse)")
    ok(o["equilibrium"] < 1e-6 and abs(o["reaction"][0] + F) < 1e-3, f"{name}: equilibrium and reaction")
ratio = out["roads along y"]["umax"] / out["roads along x"]["umax"]
ok(abs(ratio / (20000.0 / 3000.0) - 1) < 0.10, f"the same bar stretches {ratio:.2f} times more with the roads across the load (modulus ratio {20000.0 / 3000.0:.2f})")
ratio = out["roads along x, half the plastic"]["umax"] / out["roads along x"]["umax"]
ok(abs(ratio - 2.0) < 0.15, f"with half the plastic it stretches {ratio:.2f} times as much (2 by the rule of mixtures)")

# the fabric can also be given as an object (the Workbench hands it over without a file)
fab = pf.Fabric.from_paths(bar_paths("x", 1.0))
o2 = sm.run(g, sm.resolve(g, make({"fabric": fab, "constants": CONST})), cache)
ok(abs(o2["umax"] - out["roads along x"]["umax"]) < 1e-9 * out["roads along x"]["umax"], "a Fabric object gives the same as its file")
# the plate position: a transform that moves the part onto where the bar was printed
shifted = pf.Fabric.from_paths(Paths([[(x + 200, y + 50, z) for x, y, z in p] for p in [bar_paths("x", 1.0).points[s:e] for s, e in zip(bar_paths("x", 1.0).start[:-1], bar_paths("x", 1.0).start[1:])]]))
T = np.eye(4); T[:3, 3] = [200.0, 50.0, 0.0]
o3 = sm.run(g, sm.resolve(g, make({"fabric": shifted, "constants": CONST, "transform": T.tolist()})), cache)
ok(abs(o3["umax"] - out["roads along x"]["umax"]) < 1e-6 * out["roads along x"]["umax"], "a part that stands elsewhere on the plate gives the same with its transform")
# the exponent
o4 = sm.run(g, sm.resolve(g, make({"fabric": fabric_file("x", 0.5), "constants": CONST, "phi_power": 2.0})), cache)
ok(abs(o4["umax"] / out["roads along x"]["umax"] - 4.0) < 0.4, f"with the exponent 2 and half the plastic it stretches {o4['umax'] / out['roads along x']['umax']:.2f} times as much (4)")

# refused, in words
good = {"fabric": fabric_file("x", 1.0), "constants": CONST}
for what, printed, words in (("a missing file", dict(good, fabric=os.path.join(tmp, "nothing.npz")), "could not be read"),
                             ("no print data", {"constants": CONST}, "print data"),
                             ("a negative modulus", dict(good, constants=dict(CONST, E2=-1.0)), "E2"),
                             ("a missing constant", dict(good, constants={k: v for k, v in CONST.items() if k != "G23"}), "incomplete"),
                             ("a bad transform", dict(good, transform=[[1, 0], [0, 1]]), "4 x 4"),
                             ("a zero exponent", dict(good, phi_power=0.0), "phi_power"),
                             ("a smoothing of zero", dict(good, sigma=0.0), "sigma")):
    why = sm.check_ready(make(printed))
    ok(bool(why) and words in why, f"{what} is refused: {why}")
both = make(good)
both["material"]["ortho"] = dict(CONST, axes=np.eye(3).tolist())
why = sm.check_ready(both)
ok(bool(why) and "not both" in why, f"orthotropic and printed together are refused: {why}")
setup = make(good)
setup["adapt"] = dict(setup["adapt"], on=True)
try:
    sm.run(g, sm.resolve(g, setup), {})
    ok(False, "the adaptive loop with a printed material is refused")
except fem.FemError as ex:
    ok("printed" in str(ex), f"the adaptive loop with a printed material is refused: {ex}")
# print data that does not cover the part: said in words, not a crash
far = make({"fabric": shifted, "constants": CONST})
try:
    sm.run(g, sm.resolve(g, far), {})
    ok(False, "print data far from the part is refused")
except fem.FemError as ex:
    ok("does not cover" in str(ex) and "transform" in str(ex), f"print data far from the part is refused: {ex}")

print()
print("PRINTED MODEL FAILED: " + "; ".join(fails) if fails else "PRINTED MODEL OK")
sys.exit(1 if fails else 0)
