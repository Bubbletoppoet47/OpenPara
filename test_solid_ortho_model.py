"""Printed-part analysis (planning/design/slicer, PA-2): an orthotropic material through the whole 3D setup -> mesh -> solve -> result, no window.
A bar pulled along x with the material's strong direction along x, along y and along z: the stretch follows the modulus along x each time; an isotropic setup is as before;
a bad constant or axes are refused in words; the adaptive loop says it does not include the material yet."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm

fails = []
def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)

solid = b.Solid.make_box(100, 10, 10)
g = sg.analyze(solid)
def face_at(axis, side):
    n = np.zeros(3); n[axis] = side
    return next(f["id"] for f in g["faces"] if np.dot(f["normal"], n) > 0.99)
xm, xp = face_at(0, -1), face_at(0, 1)

def make(ortho=None, E=200000.0):
    setup = sm.default_setup()
    setup["h"] = 5.0
    setup["material"] = {"E": E, "nu": 0.3, "rho": 1250.0, "sy": 50.0, "su": 60.0}
    if ortho:
        setup["material"]["ortho"] = ortho
    setup["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(g, xm)]}]
    setup["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [1000.0, 0.0, 0.0]}]
    return setup

# strong 20000 MPa direction, 3000 MPa the others (a printed bar: along the road, across it, between layers), all shear moduli 1200
def mat_with(axes):
    return {"E1": 20000.0, "E2": 3000.0, "E3": 3000.0, "G12": 1200.0, "G23": 1100.0, "G13": 1200.0, "nu12": 0.30, "nu23": 0.35, "nu13": 0.30, "axes": axes}

A, L, F = 100.0, 100.0, 1000.0
cache = {}
res = {}
for name, axes, Ex in (("1 along x", [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 20000.0),
                       ("1 along y", [[0, 1, 0], [1, 0, 0], [0, 0, 1]], 3000.0),
                       ("1 along z", [[0, 0, 1], [0, 1, 0], [1, 0, 0]], 3000.0)):
    setup = make(mat_with(axes))
    ok(sm.check_ready(setup) is None, f"{name}: the setup is ready")
    r = sm.resolve(g, setup)
    out = sm.run(g, r, cache)
    res[name] = out
    expect = F * L / (A * Ex)
    ok(abs(out["umax"] - expect) / expect < 0.06, f"{name}: stretch {out['umax']:.4e}, F L / (A E_x) = {expect:.4e} (fixed end blocks the contraction: 6 %)")
    ok(out["equilibrium"] < 1e-6 and abs(out["reaction"][0] + F) < 1e-3, f"{name}: equilibrium and reaction")
ok(res["1 along x"]["umax"] * 4 < res["1 along y"]["umax"], "the same bar stretches several times less with the strong direction along the load")
ok(abs(res["1 along y"]["umax"] - res["1 along z"]["umax"]) / res["1 along y"]["umax"] < 0.15, "and about the same with the strong direction across the bar, either way")

# an isotropic setup gives what it gave: the result carries no printed-material entry and equals a run of the same setup with ortho equal moduli
iso = sm.run(g, sm.resolve(g, make(None, 3000.0)), cache)
Gi = 3000.0 / (2 * 1.3)
eq = sm.run(g, sm.resolve(g, make({"E1": 3000.0, "E2": 3000.0, "E3": 3000.0, "G12": Gi, "G23": Gi, "G13": Gi, "nu12": .3, "nu23": .3, "nu13": .3, "axes": np.eye(3).tolist()}, 3000.0)), cache)
ok(abs(iso["umax"] - eq["umax"]) / iso["umax"] < 1e-9 and abs(iso["vm_max"] - eq["vm_max"]) / iso["vm_max"] < 1e-9, "equal moduli through the whole run: the isotropic result")

# refused, in words
for what, ortho in (("a negative modulus", dict(mat_with(np.eye(3).tolist()), E2=-1.0)),
                    ("a Poisson ratio too large", dict(mat_with(np.eye(3).tolist()), nu12=3.0)),
                    ("axes that are not perpendicular", mat_with([[1, 0, 0], [1, 1, 0], [0, 0, 1]])),
                    ("a zero axis", mat_with([[1, 0, 0], [0, 0, 0], [0, 0, 1]])),
                    ("a missing constant", {k: v for k, v in mat_with(np.eye(3).tolist()).items() if k != "G23"})):
    why = sm.check_ready(make(ortho))
    ok(bool(why) and len(why) > 20, f"{what} is refused: {why}")
# the adaptive loop
setup = make(mat_with(np.eye(3).tolist()))
setup["adapt"] = dict(setup["adapt"], on=True)
try:
    r = sm.resolve(g, setup)
    sm.run(g, r, {})
    ok(False, "the adaptive loop with a printed material is refused")
except fem.FemError as ex:
    ok("orthotropic" in str(ex), f"the adaptive loop with a printed material is refused: {ex}")

print()
print("FAILED: " + "; ".join(fails) if fails else "all passed")
sys.exit(1 if fails else 0)
