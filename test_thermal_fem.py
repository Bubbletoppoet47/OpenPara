"""The 2D thermal solver (thermal_fem.py, no window) against closed forms: the integration rules, a linear field (patch test) in both element orders, slab,
slab with convection / flux, layered wall, heat generation, hollow cylinder (gmsh), a fin and a lumped plate through the flat faces, the transient slab
(backward Euler and Crank-Nicolson), radiation (closed form, the linearised convection, lumped cooling, flat-face radiation with generation), the heat
balance in every case, the refusal of a problem that is not tied to a temperature, and a stopped run."""
import math
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "shared")]
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

import physics_fea as pf
import thermal_fem as tf

SIG = 5.670374419e-8                                    # the Stefan-Boltzmann constant (CODATA 2018), typed here so the module's own is checked
assert tf.SIGMA == SIG
CU = {"k": 400.0, "rho": 8000.0, "cp": 400.0}


def rect_mesh(W, H, nx, ny, split_x=None):
    """A structured mesh of the rectangle [0, W] x [0, H] in the format of physics_geom.mesh_faces.  Sides: ln 0 bottom, ln 1 right, ln 2 top, ln 3 left.
    split_x: the region id is 1 right of it, 0 left of it."""
    xs, ys = np.linspace(0, W, nx + 1), np.linspace(0, H, ny + 1)
    nodes = np.array([(x, y) for y in ys for x in xs])
    idx = lambda i, j: j * (nx + 1) + i
    tris, face = [], []
    for j in range(ny):
        for i in range(nx):
            a, b, c, d = idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)
            for t in ((a, b, c), (a, c, d)):
                tris.append(t)
                cx = nodes[list(t)][:, 0].mean()
                face.append(1 if (split_x is not None and cx > split_x) else 0)
    segs = {("ln", 0): [(idx(i, 0), idx(i + 1, 0)) for i in range(nx)], ("ln", 1): [(idx(nx, j), idx(nx, j + 1)) for j in range(ny)],
            ("ln", 2): [(idx(i + 1, ny), idx(i, ny)) for i in range(nx)], ("ln", 3): [(idx(0, j + 1), idx(0, j)) for j in range(ny)]}
    return {"nodes": nodes, "tris": np.array(tris), "tri_face": np.array(face), "curve_segs": segs,
            "point_node": {0: idx(0, 0), 1: idx(nx, 0), 2: idx(nx, ny), 3: idx(0, ny)}}


def setup(**kw):
    s = {"lscale": 1.0, "t": 1.0, "order": 2, "mat": dict(CU), "analysis": "steady", "conds": []}
    s.update(kw)
    return s


def T_(c):
    return c + 273.15


def run(mesh, **kw):
    r = tf.solve(mesh, setup(**kw))
    assert r["balance"]["relative_error"] < 1e-8 or kw.get("rad_ok"), ("heat balance", r["balance"])
    return r


def at(mesh, r, x, y):
    """The temperature of the corner node nearest to (x, y)."""
    n = mesh["nodes"]
    return float(r["T"][int(np.argmin((n[:, 0] - x) ** 2 + (n[:, 1] - y) ** 2))])


# ---------------------------------------------------------------------------------------------------------------- 1. the rules and shape functions
def mono(rule, a, b, c):
    pts, w = rule
    return sum(wg * L[0] ** a * L[1] ** b * L[2] ** c for L, wg in zip(pts, w))


def exact(a, b, c):                                   # integral over the triangle divided by its area (the weights sum to 1)
    return math.factorial(a) * math.factorial(b) * math.factorial(c) * 2.0 / math.factorial(a + b + c + 2)


for rule, deg in ((tf.RULE1, 1), (tf.RULE2, 2), (tf.RULE4, 4)):
    assert abs(rule[1].sum() - 1) < 1e-12 and np.allclose(rule[0].sum(axis=1), 1)
    for a in range(deg + 1):
        for b in range(deg + 1 - a):
            for c in range(deg + 1 - a - b):
                assert abs(mono(rule, a, b, c) - exact(a, b, c)) < 1e-12, (deg, a, b, c)
xi, w = tf.GAUSS_EDGE
for p in range(12):
    assert abs(np.sum(w * xi ** p) - 1.0 / (p + 1)) < 1e-12
NODE_L = {1: np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], float),
          2: np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [.5, .5, 0], [0, .5, .5], [.5, 0, .5]])}
for order in (1, 2):
    for L in ([.2, .3, .5], [1, 0, 0], [.1, .1, .8]):
        N, dN = tf.shape(order, L)
        assert abs(N.sum() - 1) < 1e-12
        assert np.allclose(N @ NODE_L[order], L, atol=1e-12)                                    # a linear field is reproduced
        if order == 2:
            assert np.allclose(N @ NODE_L[order] ** 2, np.array(L) ** 2, atol=1e-12)            # and a quadratic one
        assert np.allclose(dN.sum(axis=0), 3.0 if order == 2 else 1.0)                           # d(sum N)/dL_j of the unconstrained forms
        # the derivatives against a finite difference
        for j in range(3):
            e = np.zeros(3)
            e[j] = 1e-6
            assert np.allclose((tf.shape(order, np.array(L) + e)[0] - tf.shape(order, np.array(L) - e)[0]) / 2e-6, dN[:, j], atol=1e-6)
    xs = np.linspace(0, 1, 7)
    assert np.allclose(tf.edge_shape(order, xs).sum(axis=1), 1)
# the edge matrices of the quadratic edge, in the order a, b, mid
ed2 = tf._Edges([(0, 1)], np.array([[0., 0.], [1., 0.]]), {(0, 1): 2}, 2)
assert np.allclose(ed2.int_N, [1 / 6, 1 / 6, 2 / 3]) and np.allclose(ed2.int_NN, np.array([[4, -1, 2], [-1, 4, 2], [2, 2, 16]]) / 30.0)
# the displacement of a quadratic shape function: the 4 stress points are the centres of the 4 small triangles
conn6 = np.array([[0, 1, 2, 3, 4, 5]])
for k in range(4):
    sub = pf.SUB_TRIS[k]
    cen = np.mean([[(1, 0, 0), (0, 1, 0), (0, 0, 1), (.5, .5, 0), (0, .5, .5), (.5, 0, .5)][i] for i in sub], axis=0)
    assert np.allclose(cen, tf.STRESS_POINTS[k]), k
print("ok  rules, shape functions and edge matrices")

# ---------------------------------------------------------------------------------------------------------------- 2. patch test: a linear field
mesh = rect_mesh(4.0, 2.0, 6, 3)
# distort the interior nodes so that the elements are not regular (the boundary stays on the rectangle)
rng = np.random.default_rng(1)
n = mesh["nodes"]
inner = (n[:, 0] > 1e-9) & (n[:, 0] < 4 - 1e-9) & (n[:, 1] > 1e-9) & (n[:, 1] < 2 - 1e-9)
mesh["nodes"] = n + inner[:, None] * rng.uniform(-0.08, 0.08, n.shape)
a0, bx, cy = 320.0, 7.0, -3.0
for order in (1, 2):
    # a linear field is imposed on the four sides by four temperature conditions on... one value per condition: use a single condition per side
    # whose value is only constant along it, so impose the field on the left and right sides (constant in y) is NOT linear in general -> use the exact
    # nodal route instead: build the model and overwrite the fixed temperatures with the field
    mdl = tf.Model(mesh, setup(order=order, conds=[{"kind": "temp", "T": 300.0, "targets": [("ln", 0), ("ln", 1), ("ln", 2), ("ln", 3)]}]))
    mdl.dir_vals = a0 + bx * mdl.nodes_all[mdl.dir_nodes, 0] + cy * mdl.nodes_all[mdl.dir_nodes, 1]
    T, info = tf.solve_steady(mdl)
    exact_T = a0 + bx * mdl.nodes_all[:, 0] + cy * mdl.nodes_all[:, 1]
    assert np.max(np.abs(T - exact_T)) < 1e-9, (order, np.max(np.abs(T - exact_T)))
    qx, qy = tf.element_flux(mdl, T)
    assert np.allclose(qx, -CU["k"] * bx, atol=1e-6) and np.allclose(qy, -CU["k"] * cy, atol=1e-6)
print("ok  patch test: a linear temperature field is reproduced exactly (distorted mesh, both orders)")

# ---------------------------------------------------------------------------------------------------------------- 3. slab
W, H, k, t = 0.2, 0.05, 50.0, 0.1
for order in (1, 2):
    for ls in (1.0, 1000.0):                           # sketch units: metres, millimetres
        mesh = rect_mesh(W * ls, H * ls, 8, 2)
        r = run(mesh, order=order, lscale=1.0 / ls, t=t, mat={"k": k, "rho": 7800.0, "cp": 500.0},
                conds=[{"kind": "temp", "T": T_(100.0), "targets": [("ln", 3)]}, {"kind": "temp", "T": T_(20.0), "targets": [("ln", 1)]}])
        Q = k * t * H * 80.0 / W
        assert abs(r["flows"][0]["Q"] - Q) < 1e-9 * Q and abs(r["flows"][1]["Q"] + Q) < 1e-9 * Q, (order, ls, r["flows"], Q)
        assert abs(at(mesh, r, W * ls / 2, 0) - T_(60.0)) < 1e-9 and abs(r["Tmax"] - T_(100.0)) < 1e-9
        assert np.allclose(r["qx"], Q / (t * H)) and np.allclose(r["qy"], 0, atol=1e-6)        # the flux points from hot to cold, +x
print("ok  slab: temperature, heat flow and flux (both orders, metres and millimetres)")

# slab with convection on the right: q = (T1 - Tinf) / (L/k + 1/h)
h, Tinf = 80.0, T_(20.0)
mesh = rect_mesh(W, H, 8, 2)
for order in (1, 2):
    r = run(mesh, order=order, t=t, mat={"k": k, "rho": 7800.0, "cp": 500.0},
            conds=[{"kind": "temp", "T": T_(200.0), "targets": [("ln", 3)]}, {"kind": "conv", "h": h, "Tinf": Tinf, "targets": [("ln", 1)]}])
    qpp = (T_(200.0) - Tinf) / (W / k + 1.0 / h)
    Ts = Tinf + qpp / h
    assert abs(at(mesh, r, W, H / 2) - Ts) < 1e-8, (at(mesh, r, W, H / 2), Ts)
    assert abs(r["flows"][0]["Q"] - qpp * t * H) < 1e-8 * qpp * t * H and abs(r["flows"][1]["Q"] + qpp * t * H) < 1e-8 * qpp * t * H
# a heat flux on the left, convection on the right: the flux is the heat flow
qin = 3000.0
r = run(mesh, t=t, mat={"k": k, "rho": 7800.0, "cp": 500.0},
        conds=[{"kind": "flux", "q": qin, "targets": [("ln", 3)]}, {"kind": "conv", "h": h, "Tinf": Tinf, "targets": [("ln", 1)]}])
assert abs(at(mesh, r, W, 0) - (Tinf + qin / h)) < 1e-8 and abs(at(mesh, r, 0, 0) - (Tinf + qin / h + qin * W / k)) < 1e-8
assert abs(r["flows"][0]["Q"] - qin * t * H) < 1e-8 and abs(r["balance"]["in"] - qin * t * H) < 1e-8
print("ok  slab with convection and with a heat flux")

# ---------------------------------------------------------------------------------------------------------------- 4. layered wall
mesh = rect_mesh(0.3, 0.1, 12, 2, split_x=0.1)
k1, k2 = 1.0, 0.04                                     # brick and insulation
for order in (1, 2):
    r = run(mesh, order=order, t=1.0, region_mats={0: {"k": k1, "rho": 1900.0, "cp": 800.0}, 1: {"k": k2, "rho": 20.0, "cp": 1300.0}},
            conds=[{"kind": "temp", "T": T_(20.0), "targets": [("ln", 3)]}, {"kind": "temp", "T": T_(-10.0), "targets": [("ln", 1)]}])
    q = 30.0 / (0.1 / k1 + 0.2 / k2)
    assert abs(r["flows"][0]["Q"] - q * 0.1) < 1e-9 * q, (r["flows"][0]["Q"], q * 0.1)
    assert abs(at(mesh, r, 0.1, 0.05) - (T_(20.0) - q * 0.1 / k1)) < 1e-8
print("ok  layered wall: the heat flow through two materials in series")

# ---------------------------------------------------------------------------------------------------------------- 5. heat generation
qv = 2.0e6
mesh = rect_mesh(W, H, 10, 1)
for order, tol in ((2, 1e-9), (1, 6e-3)):
    r = run(mesh, order=order, t=t, mat={"k": k, "rho": 7800.0, "cp": 500.0}, region_q={0: qv},
            conds=[{"kind": "temp", "T": T_(25.0), "targets": [("ln", 3), ("ln", 1)]}])
    exact_max = T_(25.0) + qv * W ** 2 / (8 * k)
    assert abs(r["Tmax"] - exact_max) <= tol * (exact_max - T_(25.0)), (order, r["Tmax"], exact_max)
    assert abs(r["balance"]["generation"] - qv * W * H * t) < 1e-9 * qv * W * H * t
    assert abs(sum(f["Q"] for f in r["flows"]) + r["balance"]["generation"]) < 1e-6        # the generated heat leaves through the two ends
print("ok  heat generation: the parabola (exact with quadratic elements) and the generated heat")

# ---------------------------------------------------------------------------------------------------------------- 6. the plate faces: fin and lumped plate
L_f, w_f, kf, tf_, hf = 0.1, 0.01, 200.0, 0.002, 25.0
mesh = rect_mesh(L_f, w_f, 40, 1)
m = math.sqrt(2 * hf / (kf * tf_))
r = run(mesh, t=tf_, mat={"k": kf, "rho": 2700.0, "cp": 900.0}, plate={"h": hf, "Tinf": T_(20.0)},
        conds=[{"kind": "temp", "T": T_(100.0), "targets": [("ln", 3)]}])
Qfin = kf * tf_ * w_f * m * 80.0 * math.tanh(m * L_f)
assert abs(r["flows"][0]["Q"] - Qfin) < 2e-4 * Qfin, (r["flows"][0]["Q"], Qfin)
assert abs(at(mesh, r, L_f, 0) - (T_(20.0) + 80.0 / math.cosh(m * L_f))) < 2e-3
assert abs(r["balance"]["face_conv"] - Qfin) < 2e-4 * Qfin
print("ok  fin: heat flow and tip temperature from the convection of the two flat faces")

# ---------------------------------------------------------------------------------------------------------------- 7. transient
alpha = k / (7800.0 * 500.0)
mesh = rect_mesh(W, H, 20, 1)
Tw, T0 = T_(20.0), T_(200.0)


def slab_T(x, tt, nterms=200):
    s = 0.0
    for nn in range(1, 2 * nterms, 2):
        s += 4 / (nn * math.pi) * math.sin(nn * math.pi * x / W) * math.exp(-nn ** 2 * math.pi ** 2 * alpha * tt / W ** 2)
    return Tw + (T0 - Tw) * s


tau = W ** 2 / (math.pi ** 2 * alpha)
tend = 0.8 * tau
for theta, steps, tol in ((1.0, 400, 0.02), (0.5, 100, 0.002)):
    r = run(mesh, t=t, mat={"k": k, "rho": 7800.0, "cp": 500.0}, analysis="transient", T0=T0, t_end=tend, steps=steps, theta=theta, frames=10,
            conds=[{"kind": "temp", "T": Tw, "targets": [("ln", 3), ("ln", 1)]}], rad_ok=theta < 1)
    mid = int(np.argmin((mesh["nodes"][:, 0] - W / 2) ** 2 + (mesh["nodes"][:, 1]) ** 2))
    err = abs(r["T"][mid] - slab_T(W / 2, tend))
    assert err < tol * (T0 - Tw) and r["frames"].shape == (len(r["times"]), len(r["T"])) and abs(r["times"][-1] - tend) < 1e-9, (theta, err)
    for tt, Tf in zip(r["times"][1:], r["frames"][1:]):
        assert abs(Tf[mid] - slab_T(W / 2, tt)) < (0.04 if theta == 1 else 0.004) * (T0 - Tw), (theta, tt)
    # the pictures kept: exactly the number asked for, the first at time 0 and the last at the end, the times (almost) equally spaced
    assert len(r["times"]) == 10 and r["times"][0] == 0.0 and abs(np.diff(r["times"]) - tend / 9).max() <= tend / steps, (theta, r["times"])
    # the heat that left through the two faces equals the heat the slab lost (checked from the end state of the first run)
print("ok  transient slab: backward Euler and Crank-Nicolson against the series solution")

# the lumped plate: uniform start, convection from the two flat faces -> exactly exponential whatever the conductivity
tp, hp = 0.005, 30.0
mesh = rect_mesh(0.1, 0.05, 4, 2)
tau_l = 7800.0 * 500.0 * tp / (2 * hp)
for kk in (1.0, 400.0):
    r = run(mesh, t=tp, mat={"k": kk, "rho": 7800.0, "cp": 500.0}, plate={"h": hp, "Tinf": T_(20.0)}, analysis="transient", T0=T_(120.0),
            t_end=1.5 * tau_l, steps=60, theta=0.5, frames=6, rad_ok=True)
    exp_T = T_(20.0) + 100.0 * math.exp(-1.5)
    assert np.max(np.abs(r["T"] - exp_T)) < 2e-3, (kk, np.max(np.abs(r["T"] - exp_T)), exp_T)
    for tt, Tf in zip(r["times"], r["frames"]):
        assert np.max(np.abs(Tf - (T_(20.0) + 100.0 * math.exp(-tt / tau_l)))) < 2e-3
print("ok  lumped plate cooled through its flat faces: exponential decay (both conductivities)")

# ---------------------------------------------------------------------------------------------------------------- 8. radiation
# (a) a slab: left side held, right side radiating to the surroundings: k (T1 - T2) / L = eps sigma (T2^4 - Ts^4)
T1, Ts_, eps = 900.0, 300.0, 0.8
kr, Wr = 30.0, 0.1
f = lambda T2: kr * (T1 - T2) / Wr - eps * SIG * (T2 ** 4 - Ts_ ** 4)
T2x = brentq(f, 300.0, 900.0, xtol=1e-12)
mesh = rect_mesh(Wr, 0.02, 5, 1)
for order in (1, 2):
    r = run(mesh, order=order, t=1.0, mat={"k": kr, "rho": 7800.0, "cp": 500.0}, rad_ok=True,
            conds=[{"kind": "temp", "T": T1, "targets": [("ln", 3)]}, {"kind": "rad", "eps": eps, "Ts": Ts_, "targets": [("ln", 1)]}])
    assert r["newton"]["converged"] and r["newton"]["iterations"] <= 6, r["newton"]       # quadratic convergence: the Jacobian is exact
    assert abs(at(mesh, r, Wr, 0.01) - T2x) < 1e-6, (order, at(mesh, r, Wr, 0.01), T2x)
    assert abs(r["flows"][1]["Q"] + eps * SIG * (T2x ** 4 - Ts_ ** 4) * 0.02) < 1e-6 and r["balance"]["relative_error"] < 1e-9
print("ok  radiation: a slab radiating to the surroundings against the closed form (Newton converged)")

# (b) small temperature differences: radiation equals convection with h_r = 4 eps sigma T^3
Ts_b = 400.0
hr = 4 * eps * SIG * Ts_b ** 3
r_rad = run(mesh, t=1.0, mat={"k": kr, "rho": 7800.0, "cp": 500.0}, rad_ok=True,
            conds=[{"kind": "temp", "T": Ts_b + 0.5, "targets": [("ln", 3)]}, {"kind": "rad", "eps": eps, "Ts": Ts_b, "targets": [("ln", 1)]}])
r_cv = run(mesh, t=1.0, mat={"k": kr, "rho": 7800.0, "cp": 500.0},
           conds=[{"kind": "temp", "T": Ts_b + 0.5, "targets": [("ln", 3)]}, {"kind": "conv", "h": hr, "Tinf": Ts_b, "targets": [("ln", 1)]}])
assert abs(r_rad["flows"][1]["Q"] / r_cv["flows"][1]["Q"] - 1) < 3e-3, (r_rad["flows"][1]["Q"], r_cv["flows"][1]["Q"])
r_big = run(mesh, t=1.0, mat={"k": kr, "rho": 7800.0, "cp": 500.0}, rad_ok=True,
            conds=[{"kind": "temp", "T": 1500.0, "targets": [("ln", 3)]}, {"kind": "rad", "eps": eps, "Ts": Ts_b, "targets": [("ln", 1)]}])
r_big_cv = run(mesh, t=1.0, mat={"k": kr, "rho": 7800.0, "cp": 500.0},
               conds=[{"kind": "temp", "T": 1500.0, "targets": [("ln", 3)]}, {"kind": "conv", "h": hr, "Tinf": Ts_b, "targets": [("ln", 1)]}])
assert abs(r_big["flows"][1]["Q"] / r_big_cv["flows"][1]["Q"] - 1) > 0.3            # at large differences the linearised version is wrong, as it must be
assert r_big["newton"]["converged"]
print("ok  radiation matches the linearised convection for small differences and not for large ones")

# (c) the flat faces with heat generation: q''' t = 2 eps sigma (T^4 - Ts^4), uniform whatever the conductivity
qg, tg, eg = 5.0e5, 0.004, 0.6
Tg_exact = (Ts_ ** 4 + qg * tg / (2 * eg * SIG)) ** 0.25
mesh = rect_mesh(0.1, 0.05, 4, 2)
for kk in (0.5, 300.0):
    r = run(mesh, t=tg, mat={"k": kk, "rho": 7800.0, "cp": 500.0}, region_q={0: qg}, plate={"eps": eg, "Ts": Ts_}, rad_ok=True, conds=[])
    assert np.max(np.abs(r["T"] - Tg_exact)) < 1e-6 and r["newton"]["converged"] and r["newton"]["iterations"] <= 8, (kk, r["T"].min(), r["T"].max(), Tg_exact, r["newton"])
    assert r["balance"]["relative_error"] < 1e-9 and abs(r["balance"]["face_rad"] - qg * tg * 0.1 * 0.05) < 1e-6 * qg * tg * 0.005
print("ok  flat-face radiation balances heat generation exactly (uniform temperature)")

# (d) lumped radiative cooling (both faces): rho cp t dT/dt = -2 eps sigma (T^4 - Ts^4)
tr, Tstart = 0.003, 1000.0
rho_cp_t = 7800.0 * 500.0 * tr
sol = solve_ivp(lambda tt, T: -2 * 0.7 * SIG * (T ** 4 - Ts_ ** 4) / rho_cp_t, (0, 600.0), [Tstart], rtol=1e-11, atol=1e-9, dense_output=True)
mesh = rect_mesh(0.1, 0.05, 3, 2)
r = run(mesh, t=tr, mat={"k": 100.0, "rho": 7800.0, "cp": 500.0}, plate={"eps": 0.7, "Ts": Ts_}, analysis="transient", T0=Tstart, t_end=600.0,
        steps=120, theta=0.5, frames=6, rad_ok=True, conds=[])
assert abs(r["T"].mean() - sol.y[0, -1]) < 0.2 and np.ptp(r["T"]) < 1e-6, (r["T"].mean(), sol.y[0, -1])
for tt, Tf in zip(r["times"], r["frames"]):
    assert abs(Tf.mean() - float(sol.sol(tt)[0])) < 0.2
print("ok  radiative cooling of a lumped plate against the ODE (Crank-Nicolson, Newton in every step)")

# (e) a very hot surface: the line search keeps the iteration alive
r = run(mesh, t=1.0, mat={"k": 30.0, "rho": 7800.0, "cp": 500.0}, rad_ok=True,
        conds=[{"kind": "temp", "T": 3000.0, "targets": [("ln", 3)]}, {"kind": "rad", "eps": 1.0, "Ts": 100.0, "targets": [("ln", 1)]}])
assert r["newton"]["converged"] and r["Tmin"] > 100.0
print("ok  strongly nonlinear radiation still converges")

# ---------------------------------------------------------------------------------------------------------------- 9. hollow cylinder (gmsh)
import physics_geom as pg
import sketcher_core as sc


def annulus(ri, ro):
    m = sc.Model()
    c = m.add_point(0.0, 0.0)
    ci = m.add_circle(c, ri)
    co = m.add_circle(c, ro)
    return m, ci, co


def mesh_of(m, h):
    geom = pg.analyze(m)
    ids = {f["id"] for f in geom["faces"]}
    return pg.mesh_faces(m, geom, ids, h), geom


ri, ro, kc, Ti_, To_ = 0.02, 0.05, 15.0, T_(150.0), T_(30.0)
errs = []
for hsize in (0.008, 0.004):
    m, ci, co = annulus(ri, ro)
    mesh, geom = mesh_of(m, hsize)
    inner = [x for x in mesh["curve_segs"] if True]
    keys = sorted(mesh["curve_segs"])
    # the circle ids are the sources of the two circles
    srcs = {tuple(e["src"]) for e in geom["edges"]}
    cs = sorted(srcs)
    rad_of = {s: float(np.mean([np.hypot(*mesh["nodes"][a]) for a, _ in mesh["curve_segs"][s]])) for s in cs}
    s_in = min(cs, key=lambda s: rad_of[s])
    s_out = max(cs, key=lambda s: rad_of[s])
    r = tf.solve(mesh, setup(t=1.0, mat={"k": kc, "rho": 7800.0, "cp": 500.0}, conds=[{"kind": "temp", "T": Ti_, "targets": [s_in]},
                                                                                       {"kind": "temp", "T": To_, "targets": [s_out]}]))
    Qx = 2 * math.pi * kc * (Ti_ - To_) / math.log(ro / ri)
    rr = np.hypot(r["mesh"]["nodes"][:, 0], r["mesh"]["nodes"][:, 1])
    Tex = Ti_ + (To_ - Ti_) * np.log(np.maximum(rr, ri) / ri) / math.log(ro / ri)
    inside = (rr > ri * 1.02) & (rr < ro * 0.98)
    errs.append((float(np.max(np.abs(r["T"][inside] - Tex[inside]))), abs(r["flows"][0]["Q"] / Qx - 1)))
    assert r["balance"]["relative_error"] < 1e-9 and abs(r["flows"][0]["Q"] + r["flows"][1]["Q"]) < 1e-9 * abs(Qx)
# the sides of a circle are straight chords (the mesh is straight-sided), so the error is geometric and falls with the square of the element size
assert errs[0][0] < 2.0 and errs[1][0] < 0.6 and errs[0][0] / errs[1][0] > 2.5, errs
assert errs[0][1] < 0.02 and errs[1][1] < 0.005 and errs[0][1] / errs[1][1] > 2.5, errs
print(f"ok  hollow cylinder from a sketch with gmsh: error in the temperature {errs[0][0]:.3g} K -> {errs[1][0]:.3g} K, heat flow {errs[0][1]:.2g} -> {errs[1][1]:.2g}")

# ---------------------------------------------------------------------------------------------------------------- 10. a square: the centre is a quarter
mesh = rect_mesh(1.0, 1.0, 24, 24)
r = run(mesh, t=1.0, mat={"k": 10.0, "rho": 1.0, "cp": 1.0},
        conds=[{"kind": "temp", "T": 0.5 + 100.0, "targets": [("ln", 2)]}, {"kind": "temp", "T": 0.5, "targets": [("ln", 0), ("ln", 1), ("ln", 3)]}])
# (the corners belong to the later condition; the centre is smooth, so the quarter still holds to a small fraction of the 100 K jump)
assert abs(at(mesh, r, 0.5, 0.5) - 0.5 - 25.0) < 0.15, at(mesh, r, 0.5, 0.5)
print("ok  square plate: the centre temperature is a quarter of the jump")

# ---------------------------------------------------------------------------------------------------------------- 11. refusals, notes, stop
mesh = rect_mesh(1.0, 1.0, 4, 4)
for bad, why in (([], "no condition"), ([{"kind": "flux", "q": 10.0, "targets": [("ln", 3)]}], "only a flux")):
    try:
        tf.solve(mesh, setup(conds=bad))
        raise SystemExit("a steady problem with nothing tying it to a temperature must be refused: " + why)
    except tf.ModelError as ex:
        assert "temperature, convection or radiation" in str(ex)
# two pieces, only one tied
two = rect_mesh(1.0, 1.0, 2, 2)
shift = rect_mesh(1.0, 1.0, 2, 2)
nn = len(two["nodes"])
joined = {"nodes": np.vstack([two["nodes"], shift["nodes"] + [3.0, 0.0]]), "tris": np.vstack([two["tris"], shift["tris"] + nn]),
          "tri_face": np.concatenate([np.zeros(len(two["tris"]), int), np.ones(len(shift["tris"]), int)]),
          "curve_segs": {("ln", 3): two["curve_segs"][("ln", 3)], ("ln", 7): [(a + nn, b + nn) for a, b in shift["curve_segs"][("ln", 3)]]},
          "point_node": {}}
try:
    tf.solve(joined, setup(conds=[{"kind": "temp", "T": 300.0, "targets": [("ln", 3)]}]))
    raise SystemExit("a piece with no condition must be refused")
except tf.ModelError as ex:
    assert "region 2" in str(ex), str(ex)
r = tf.solve(joined, setup(conds=[{"kind": "temp", "T": 300.0, "targets": [("ln", 3)]}], analysis="transient", T0=300.0, t_end=1.0, steps=2))
assert r["T"].shape[0] == len(joined["nodes"]) + len(pf.add_midnodes(joined["nodes"], joined["tris"])[0]) - len(joined["nodes"])
# a transient run does not need the tie
# conflicting temperatures and an edge inside the material
mesh = rect_mesh(1.0, 1.0, 4, 4)
r = tf.solve(mesh, setup(conds=[{"kind": "temp", "T": 300.0, "targets": [("ln", 0), ("ln", 3)]}, {"kind": "temp", "T": 350.0, "targets": [("ln", 3), ("ln", 1)]}]))
assert any("later one" in n for n in r["notes"])
# a stopped run
calls = {"n": 0}


def stopper():
    calls["n"] += 1
    return calls["n"] > 3


try:
    tf.solve(rect_mesh(1.0, 1.0, 6, 6), setup(analysis="transient", T0=300.0, t_end=1.0, steps=50, conds=[{"kind": "temp", "T": 320.0, "targets": [("ln", 3)]}]),
             cancel=stopper)
    raise SystemExit("a stopped run must raise Cancelled")
except tf.Cancelled:
    pass
# every node has a fixed temperature in a transient run
r = tf.solve(rect_mesh(1.0, 1.0, 2, 2), setup(order=1, analysis="transient", T0=300.0, t_end=1.0, steps=3,
                                              conds=[{"kind": "temp", "T": 310.0, "targets": [("ln", 0), ("ln", 1), ("ln", 2), ("ln", 3)]}]))
assert np.allclose(r["T"][[0, 1, 2]], 310.0)
# bad values
for conds in ([{"kind": "rad", "eps": 1.5, "Ts": 300.0, "targets": [("ln", 1)]}], [{"kind": "conv", "h": 5.0, "Tinf": -3.0, "targets": [("ln", 1)]}]):
    try:
        tf.solve(rect_mesh(1.0, 1.0, 2, 2), setup(conds=[{"kind": "temp", "T": 300.0, "targets": [("ln", 3)]}] + conds))
        raise SystemExit("bad condition values must be refused")
    except tf.ModelError:
        pass
try:
    tf.solve(rect_mesh(1.0, 1.0, 2, 2), setup(mat={"k": -1.0, "rho": 1.0, "cp": 1.0}, conds=[{"kind": "temp", "T": 300.0, "targets": [("ln", 3)]}]))
    raise SystemExit("a negative conductivity must be refused")
except tf.ModelError:
    pass
print("ok  refusals (nothing tied to a temperature, one piece untied, bad values), notes and a stopped run")

# ---------------------------------------------------------------------------------------------------------------- 12. the result
mesh = rect_mesh(0.2, 0.05, 8, 2)
r = run(mesh, t=0.1, mat={"k": 50.0, "rho": 7800.0, "cp": 500.0}, order=2,
        conds=[{"kind": "temp", "T": 400.0, "targets": [("ln", 3)]}, {"kind": "conv", "h": 100.0, "Tinf": 300.0, "targets": [("ln", 1)]}])
M = len(mesh["tris"])
assert len(r["qx"]) == 4 * M == len(r["mesh"]["tris"]) and r["mesh"]["quadratic"] and r["T"].shape == (len(r["mesh"]["nodes"]),)
qx, qy, qm = tf.flux_of(r, r["T"])
assert np.allclose(qx, r["qx"]) and np.allclose(qm, r["qmag"])
st = tf.probe_stats(r, [{"name": "all", "shape": "rect", "x0": -1, "y0": -1, "x1": 5, "y1": 5}, {"name": "none", "shape": "rect", "x0": 9, "y0": 9, "x1": 10, "y1": 10}])
assert abs(st[0]["avg"] - r["Tmean"]) < 1e-9 and st[0]["min"] == r["Tmin"] and st[1]["n"] == 0
r1 = run(mesh, t=0.1, mat={"k": 50.0, "rho": 7800.0, "cp": 500.0}, order=1,
         conds=[{"kind": "temp", "T": 400.0, "targets": [("ln", 3)]}, {"kind": "conv", "h": 100.0, "Tinf": 300.0, "targets": [("ln", 1)]}])
assert len(r1["qx"]) == M and not r1["mesh"]["quadratic"] and abs(r1["Tmax"] - r["Tmax"]) < 1e-9
import pickle
pickle.dumps(r)
print("ok  result: fields on the display mesh, flux of a stored temperature, probes, pickling")
print("OK thermal solver")
