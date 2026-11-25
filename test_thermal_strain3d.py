"""Thermal strain in the 3D structural solver (solid_model.run(..., thermal=...), solid_fem.thermal_load / stresses, solid_elem.thermal_forces / recover).

Elements (tetrahedra, 8- and 20-node bricks, 5- and 13-node pyramids):  a body that grows by the uniform thermal strain e in every direction (u = e x) is in equilibrium with
NO force from the supports and NO stress: K u = f_thermal, the stress is zero, the elastic energy is zero.  A temperature that rises linearly (T = g y) has the exact
free-body field u = (g x y, g (y^2 - x^2 - z^2) / 2, g y z): the 20-node brick holds it exactly.
Whole models (a box 96 x 36 x 36, tetrahedra and hex-dominant, linear and quadratic):  held only by three symmetry planes the box grows by alpha dT everywhere and carries
no stress; held between two walls it carries sigma_x = -E alpha dT, the wall reaction is that times the section, the elastic energy half sigma^2 / E times the volume.
An assembly of two bodies with different alpha; the readiness check; a missing alpha is refused in words; no temperature gives the result it always gave."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_elem as el, solid_fem as fem, solid_geom as sg, solid_model as sm, solid_mesh as smesh

E_, NU, ALPHA, DT, TREF = 200000.0, 0.3, 12e-6, 100.0, 293.15
SIG = E_ * ALPHA * DT                                                  # 240 MPa
D = fem.material_matrix(E_, NU)
rs = np.random.RandomState(5)

# ============================================================================================================ the elements
e = ALPHA * DT
for kind, order in (("hex", 1), ("hex", 2)):                           # a distorted brick: uniform growth is stress free
    base = np.vstack([el.CORNERS, el.MIDS])[:8 if order == 1 else 20]
    c = el.CORNERS * np.array([10.0, 6.0, 4.0]) + rs.uniform(-0.8, 0.8, (8, 3))
    X = np.zeros_like(base); X[:8] = c
    if order == 2:
        for k, (a, bb) in enumerate(el.HEX_EDGES):
            X[8 + k] = 0.5 * (c[a] + c[bb])
    X = X[None]
    u = (e * X[0]).reshape(1, -1)
    K = el.stiffness(kind, X, D)[0]
    f = el.thermal_forces(kind, X, D, np.full((1, X.shape[1]), e))[0].ravel()
    assert np.abs(K @ u[0] - f).max() < 1e-9 * np.abs(f).max(), (kind, order, np.abs(K @ u[0] - f).max(), np.abs(f).max())
    _v, mean, vol, en = el.recover(kind, X, D, u, np.full((1, X.shape[1]), e), True)
    assert np.abs(mean).max() < 1e-9 * SIG and en[0] < 1e-12, (kind, order, np.abs(mean).max(), en)
    _v, mean0, _vol = el.recover(kind, X, D, u)                        # without the temperature the same displacement IS a stress
    assert abs(mean0[0, 0]) > 0.5 * E_ * e
    assert abs(f.reshape(-1, 3).sum(axis=0)).max() < 1e-9 * np.abs(f).max(), "the thermal forces of an element add up to nothing"
    print(f"ok   {kind}{8 if order == 1 else 20}: uniform growth is in equilibrium with the thermal forces, without stress, without elastic energy")
P5 = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [5, 5, 6.0]])
for order in (1, 2):
    pc = P5 if order == 1 else np.vstack([P5] + [0.5 * (P5[a] + P5[bb])[None] for a, bb in el.PYR_EDGES])
    hx = el.as_hex("pyr", np.arange(len(pc))[None])[0]
    X = pc[hx][None]
    u = (e * X[0]).reshape(1, -1)
    K = el.stiffness("pyr", X, D)[0]
    f = el.thermal_forces("pyr", X, D, np.full((1, X.shape[1]), e))[0].ravel()
    assert np.abs(K @ u[0] - f).max() < 1e-9 * np.abs(f).max(), ("pyramid", order)
    _v, mean, vol, en = el.recover("pyr", X, D, u, np.full((1, X.shape[1]), e), True)
    assert np.abs(mean).max() < 1e-9 * SIG and en[0] < 1e-12
    print(f"ok   pyramid{5 if order == 1 else 13}: the same")

# the exact free-body field of a linear temperature, in an affine 20-node brick
g_ = 1e-4                                                              # the thermal strain at height y is g y
A = np.diag([12.0, 8.0, 6.0]) + np.array([[0, 1.0, 0.5], [0.3, 0, 0.7], [0.2, 0.4, 0]])      # a skewed box (parallelepiped): the brick map is affine, so the quadratic field is in the space
c = el.CORNERS @ A.T * 0.5
X = np.zeros((20, 3)); X[:8] = c
for k, (a, bb) in enumerate(el.HEX_EDGES):
    X[8 + k] = 0.5 * (c[a] + c[bb])
x, y, z = X[:, 0], X[:, 1], X[:, 2]
u = np.stack([g_ * x * y, 0.5 * g_ * (y ** 2 - x ** 2 - z ** 2), g_ * y * z], axis=1)
K = el.stiffness("hex", X[None], D)[0]
f = el.thermal_forces("hex", X[None], D, (g_ * y)[None, :])[0].ravel()
assert np.abs(K @ u.ravel() - f).max() < 1e-9 * np.abs(f).max(), np.abs(K @ u.ravel() - f).max() / np.abs(f).max()
_v, mean, vol, en = el.recover("hex", X[None], D, u.reshape(1, -1), (g_ * y)[None, :], True)
assert np.abs(mean).max() < 1e-9 * E_ * g_ * 10 and en[0] < 1e-14 * E_, (np.abs(mean).max(), en)
print("ok   hex20: a temperature that rises linearly has the exact free field (g x y, g (y^2 - x^2 - z^2) / 2, g y z): no stress")

# tetrahedra: the same uniform-growth check through the assembly and the load of solid_fem
pts = np.array([[0, 0, 0], [10, 0, 0], [0, 8, 0], [0, 0, 6], [10, 8, 6.0]]) + rs.uniform(-0.3, 0.3, (5, 3))
conn = np.array([[0, 1, 2, 3], [1, 2, 3, 4]])
Kt, _D = fem.assemble(pts, conn, E_, NU)
th = {"T": np.full(len(pts), TREF + DT), "alpha": ALPHA, "Tref": TREF}
ft = fem.thermal_load(pts, [{"kind": "tet", "conn": conn}], E_, NU, th)
ut = (e * pts).ravel()
assert np.abs(Kt @ ut - ft).max() < 1e-9 * np.abs(ft).max()
vm_el, sg_, vol, en = fem.stresses(pts, conn, D, ut, th, True)
assert vm_el.max() < 1e-9 * SIG and en < 1e-12
print("ok   tetrahedra: uniform growth is stress free")

# ============================================================================================================ whole models
L_, W_, H_ = 96.0, 36.0, 36.0
solid = b.Solid.make_box(L_, W_, H_)
g = sg.analyze(solid)


def face_at(axis, side):
    n = np.zeros(3); n[axis] = side
    return sg.face_sig(g, next(f_["id"] for f_ in g["faces"] if np.dot(f_["normal"], n) > 0.99))


SYM = [{"mode": "disp", "faces": [face_at(0, -1)], "ux": 0.0, "uy": None, "uz": None, "name": "Left"},
       {"mode": "disp", "faces": [face_at(1, -1)], "ux": None, "uy": 0.0, "uz": None, "name": "Front"},
       {"mode": "disp", "faces": [face_at(2, -1)], "ux": None, "uy": None, "uz": 0.0, "name": "Bottom"}]
WALL = {"mode": "disp", "faces": [face_at(0, 1)], "ux": 0.0, "uy": None, "uz": None, "name": "Right"}


def setup_for(supports, order, typ, alpha=ALPHA):
    s = sm.default_setup()
    s["h"] = 6.0 if order == 2 else 3.0
    s["mesh"] = dict(smesh.default_mesh(), advanced=True, order=order, type=typ)
    s["supports"] = [dict(x_) for x_ in supports]
    s["loads"] = []
    s["material"] = dict(s["material"], E=E_, nu=NU)
    if alpha is not None:
        s["material"]["alpha"] = alpha
    s["material"]["Tref"] = TREF
    return s


def heated(dT=DT):
    return lambda q: {"T": np.full(len(q["nodes"]), TREF + dT)}


for order, typ in ((2, "tets"), (1, "tets"), (2, "hexdom"), (1, "hexdom")):
    label = f"{'quadratic' if order == 2 else 'linear'} {typ}"
    # grows freely from the corner: u = alpha dT x, no stress, no elastic energy
    r = sm.run(g, sm.resolve(g, setup_for(SYM, order, typ)), {}, thermal=heated())
    assert (r["counts"]["hexes"] > 0) == (typ == "hexdom"), (label, r["counts"])
    nodes, u = np.asarray(r["nodes"]), np.asarray(r["u"])
    assert np.abs(u - e * nodes).max() < 1e-8, (label, np.abs(u - e * nodes).max())
    assert r["vm_max"] < 1e-6 * SIG and abs(r["energy"]) < 1e-9, (label, r["vm_max"], r["energy"])
    assert r["thermal"] == {"T_min": TREF + DT, "T_max": TREF + DT, "alpha_min": ALPHA, "alpha_max": ALPHA, "Tref_min": TREF, "Tref_max": TREF} and r["equilibrium"] < 1e-6
    # held between two walls: sigma_x = -E alpha dT, nothing sideways
    r = sm.run(g, sm.resolve(g, setup_for(SYM + [WALL], order, typ)), {}, thermal=heated())
    # the same state from a movement instead of a temperature: the right wall pushed back by the free growth, no temperature at all
    rm = sm.run(g, sm.resolve(g, setup_for(SYM + [dict(WALL, ux=-e * L_)], order, typ)), {})
    assert rm["thermal"] is None
    assert np.abs(r["vm_el"] - rm["vm_el"]).max() < 1e-8 * SIG, (label, np.abs(r["vm_el"] - rm["vm_el"]).max())              # same stress, element by element
    F = SIG * W_ * H_
    reac = dict(r["support_reactions"])
    reac_m = dict(rm["support_reactions"])
    assert abs(reac["Right"][0] - reac_m["Right"][0]) < 1e-8 * F and abs(reac["Left"][0] - reac_m["Left"][0]) < 1e-8 * F, (label, reac, reac_m)
    assert abs(r["energy"] - rm["energy"]) < 1e-8 * abs(rm["energy"]), (label, r["energy"], rm["energy"])
    assert r["equilibrium"] < 1e-6 and np.abs(r["reaction"]).max() < 1e-6 * F
    if not (order == 2 and typ == "hexdom"):                      # (the quadratic hex-dominant mesh does not reproduce a uniform stress state exactly under a movement either: see rm)
        assert abs(r["vm_max"] - SIG) < 1e-6 * SIG and abs(np.median(r["vm_el"]) - SIG) < 1e-6 * SIG, (label, r["vm_max"], np.median(r["vm_el"]))
        assert abs(r["s3_min"] + SIG) < 1e-6 * SIG and abs(r["s1_max"]) < 1e-6 * SIG, (label, r["s3_min"], r["s1_max"])           # compression along x only
        assert abs(reac["Right"][0] + F) < 1e-6 * F and abs(reac["Left"][0] - F) < 1e-6 * F, (label, reac["Right"], reac["Left"], F)
        en = 0.5 * SIG ** 2 / E_ * L_ * W_ * H_
        assert abs(r["energy"] - en) < 1e-6 * en, (label, r["energy"], en)
    else:
        assert abs(np.median(r["vm_el"]) - SIG) < 1e-2 * SIG, (label, np.median(r["vm_el"]))
        assert abs(abs(reac["Left"][0]) - F) < 5e-2 * F, (label, reac["Left"], F)
    print(f"ok   {label}: free growth u = alpha dT x with no stress; held between walls it gives the stress, reaction and energy of the equivalent movement"
          + ("" if (order == 2 and typ == "hexdom") else f" (sigma = -E alpha dT = {-SIG:.4g}, reaction {F:.5g} N)"))

# cooling shrinks
r = sm.run(g, sm.resolve(g, setup_for(SYM, 2, "tets")), {}, thermal=heated(-DT))
assert np.abs(np.asarray(r["u"]) + e * np.asarray(r["nodes"])).max() < 1e-8 and np.asarray(r["u"])[:, 0].min() < -0.99 * e * L_
print("ok   a cooled box shrinks")

# ---------------------------------------------------------------------------------------------------------------- readiness, errors, the old behaviour
s_ = setup_for(SYM, 2, "tets")
assert "load" in sm.check_ready(s_).lower() and sm.check_ready(s_, None, thermal=True) is None
print("ok   with a temperature the setup needs no load of its own")
try:
    sm.run(g, sm.resolve(g, setup_for(SYM, 2, "tets", alpha=None)), {}, thermal=heated())
    assert False, "alpha is needed"
except fem.FemError as ex:
    assert "expansion coefficient" in str(ex), str(ex)
sad_ = setup_for(SYM, 2, "tets"); sad_["adapt"] = dict(sad_["adapt"], on=True)
try:
    sm.run(g, sm.resolve(g, sad_), {}, thermal=heated())
    assert False, "the adaptive loop is refused with a temperature"
except fem.FemError as ex:
    assert "Adaptive mesh (h)" in str(ex), str(ex)
try:
    sm.run(g, sm.resolve(g, setup_for(SYM, 2, "tets")), {}, thermal={"T": np.zeros(3)})
    assert False
except fem.FemError as ex:
    assert "temperature field" in str(ex), str(ex)
print("ok   a material without alpha, a field of the wrong size and the adaptive loop with a temperature are refused in words")
r0 = sm.run(g, sm.resolve(g, setup_for(SYM + [WALL, {"mode": "disp", "faces": [face_at(0, 1)], "ux": 0.05, "uy": None, "uz": None, "name": "Pull"}], 2, "tets")), {})
assert r0["thermal"] is None and r0["vm_max"] > 0
print("OK")
