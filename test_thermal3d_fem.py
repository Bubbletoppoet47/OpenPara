"""thermal3d_fem.py against closed-form answers: the exact element tensors, a linear field reproduced exactly, a slab, a two-body wall, a hollow cylinder with
convection, a hollow sphere, heat generation in a sphere, a fin with convection, radiation, lumped and series-solution transients, the heat balance, both
element orders, and the refusals.   python test_thermal3d_fem.py"""
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal3d"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg
import solid_model as sm
import solid_asm as sasm
import solid_fem as fem
import thermal3d_fem as tf

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b_, rel, what):
    err = abs(a - b_) / max(abs(b_), 1e-300)
    ok(err <= rel, f"{what}: {a:.6g} against {b_:.6g} ({err * 100:.3f} %, limit {rel * 100:g} %)")


NOCANCEL = lambda: False
SILENT = lambda t: None


def mesh(geom, h, order=2):
    if order == 2:
        return sm.get_mesh(geom, h, {}, NOCANCEL, SILENT, None)
    return fem.linear(fem.mesh_solid(geom, h, NOCANCEL, SILENT, None))


def part(solid, h, order=2):
    g = sg.analyze(solid, None)
    return g, mesh(g, h, order)


def fid(g, normal, where=None, bodies=None):
    n = np.asarray(normal, float)
    for f in g["faces"]:
        if np.dot(f["normal"], n) > 0.99 and not f.get("interface") and (bodies is None or f.get("bodies") == bodies):
            return f["id"]
    raise AssertionError(f"no face with normal {normal}")


MAT = {"k": 50.0, "rho": 7800.0, "cp": 500.0}


def run(q, spec, **kw):
    spec = dict({"lscale": 1e-3, "materials": [dict(MAT)]}, **spec)
    return tf.solve(q, spec, **kw)


def flow(res, name):
    return next(f for f in res["flows"] if f["name"] == name)


def refuses(q, spec, words, what):
    try:
        run(q, spec)
        ok(False, f"{what}: refused")
    except tf.ThermalError as ex:
        ok(all(w in str(ex) for w in words), f"{what}: refused with '{str(ex)[:90]}'")


# ------------------------------------------------------------------------------------------------------------------- the element tensors
for order in (1, 2):
    r = tf.reference(order)
    A, M, Ne = r["A"], r["M"], r["Ne"]
    ok(abs(M.sum() - 1) < 1e-13 and abs(Ne.sum() - 1) < 1e-13, f"order {order}: the heat capacity matrix and the generation vector add up to the volume")
    ok(np.abs(M - M.T).max() < 1e-15 and np.abs(A - A.transpose(1, 0, 3, 2)).max() < 1e-14, f"order {order}: the tensors are symmetric")
M2 = tf.reference(2)["M"]
ok(abs(M2[0, 0] - 6.0 / 420.0) < 1e-13 and abs(M2[4, 4] - 32.0 / 420.0) < 1e-13 and abs(M2[0, 4] + 4.0 / 420.0) < 1e-13 and abs(M2[0, 1] - 1.0 / 420.0) < 1e-13,
   f"the quadratic tetrahedron's consistent mass matrix has its known entries (6, 32, -4, 1 over 420): {M2[0, 0] * 420:.6f} {M2[4, 4] * 420:.6f} {M2[0, 4] * 420:.6f}")
Ne2 = tf.reference(2)["Ne"]
ok(np.allclose(Ne2[:4], -1 / 20) and np.allclose(Ne2[4:], 1 / 5), "the quadratic generation vector is -1/20 at the corners and 1/5 at the mid-edge nodes")
Ml = tf.reference(1)["M"]
ok(np.allclose(Ml, (np.eye(4) + 1) / 20), "the linear mass matrix is (1 + delta) / 20")
# the conduction tensor of a linear tetrahedron is the textbook one: K_ij = k V grad N_i . grad N_j
Al = tf.reference(1)["A"]
ok(np.allclose(Al, np.einsum("ik,jl->ijkl", np.eye(4), np.eye(4))), "the linear conduction tensor is the identity pairing")
# a quadratic element reproduces a linear temperature exactly: K T = 0 inside and the element's own gradient is the field's
nodes = np.array([[0, 0, 0], [0.02, 0, 0.001], [0.003, 0.015, 0], [0.002, 0.004, 0.012]], float)
from itertools import combinations
mids = np.array([(nodes[a] + nodes[b_]) / 2 for a, b_ in fem.EDGES])
allp = np.vstack([nodes, mids])
conn = np.arange(10)[None]
gx = np.array([30.0, -20.0, 70.0])
Tlin = 300 + allp @ gx
gr = tf.element_gradient(allp, conn, 2, Tlin)
ok(np.allclose(gr, gx[None, None, :], atol=1e-8) and gr.shape == (1, 4, 3), f"a linear temperature has its exact gradient in a quadratic element: {gr[0, 0]}")
gr1 = tf.element_gradient(allp, conn[:, :4], 1, Tlin)
ok(np.allclose(gr1, gx[None, None, :], atol=1e-8) and gr1.shape == (1, 1, 3), "and in a linear one")

# ------------------------------------------------------------------------------------------------------------------- a slab: 1D conduction
LX, LY, LZ = 100.0, 20.0, 10.0
slab = b.Box(LX, LY, LZ)
Aslab = LY * LZ * 1e-6
for order in (2, 1):
    g, q = part(slab, 8.0, order)
    left, right = fid(g, [-1, 0, 0]), fid(g, [1, 0, 0])
    res = run(q, {"temps": [{"name": "hot", "fids": [left], "T": 400.0}, {"name": "cold", "fids": [right], "T": 300.0}]})
    x = (res["nodes"][:, 0] + LX / 2) / LX
    ok(np.abs(res["T"] - (400 - 100 * x)).max() < 1e-7, f"order {order}: a slab between two fixed temperatures is linear to 1e-7 K: {np.abs(res['T'] - (400 - 100 * x)).max():.2e}")
    Q = 50.0 * Aslab * 100.0 / (LX * 1e-3)
    near(res["flows"][0]["Q"], Q, 1e-9, f"order {order}: the heat flow in at the hot face (k A dT / L = {Q:g} W)")
    near(res["flows"][1]["Q"], -Q, 1e-9, f"order {order}: and out at the cold one")
    ok(res["balance"]["relative_error"] < 1e-10, f"order {order}: the heat balance closes: {res['balance']['relative_error']:.2e}")
    near(float(np.abs(res["q"][:, 0]).mean()), Q / Aslab, 1e-8, f"order {order}: the heat flux in the elements is q = k dT / L")
    ok(np.abs(res["q"][:, 1:]).max() < 1e-4 * np.abs(res["q"][:, 0]).max(), f"order {order}: and has no sideways part")
    near(res["Tmean"], 350.0, 1e-9, f"order {order}: the mean temperature of the slab")
res_slab = res
ok(res["run"]["solver"] == "direct" and res["unknowns"] == len(q["nodes"]) - (len(np.unique(q["ftri"][left])) + len(np.unique(q["ftri"][right]))), "the unknowns are the nodes without a fixed temperature")

# a heat flux in and a fixed temperature out
g, q = part(slab, 8.0)
left, right = fid(g, [-1, 0, 0]), fid(g, [1, 0, 0])
res = run(q, {"fluxes": [{"name": "in", "fids": [left], "q": 20000.0}], "temps": [{"name": "cold", "fids": [right], "T": 300.0}]})
ok(abs(res["Tmax"] - (300 + 20000 * LX * 1e-3 / 50.0)) < 1e-6, f"a flux of 20 kW/m2 through the slab: the hot face is {res['Tmax']:.6f} K, k=50 gives {300 + 20000 * LX * 1e-3 / 50.0}")
near(flow(res, "in")["Q"], 20000.0 * Aslab, 1e-9, "the flux condition reports q A")
near(flow(res, "cold")["Q"], -20000.0 * Aslab, 1e-7, "and the cold face carries it away")
# the same heat as a heat flow in W spread over the face
res2 = run(q, {"powers": [{"name": "heater", "fids": [left], "P": 20000.0 * Aslab}], "temps": [{"name": "cold", "fids": [right], "T": 300.0}]})
ok(np.abs(res2["T"] - res["T"]).max() < 1e-9, "a heat flow of the same watts gives the same temperatures")
near(flow(res2, "heater")["Q"], 20000.0 * Aslab, 1e-12, "and reports its watts")
# an insulated face changes nothing, and says it is there
res3 = run(q, {"fluxes": [{"name": "in", "fids": [left], "q": 20000.0}], "temps": [{"name": "cold", "fids": [right], "T": 300.0}],
               "ins": [{"name": "top", "fids": [fid(g, [0, 0, 1])]}]})
ok(np.abs(res3["T"] - res["T"]).max() < 1e-12 and any(f["kind"] == "ins" for f in res3["flows"]), "an insulated face changes nothing and is listed")

# ------------------------------------------------------------------------------------------------------------------- a wall of two materials (an assembly)
b1 = b.Pos(20, 0, 0) * b.Box(40, 20, 10)
b2 = b.Pos(70, 0, 0) * b.Box(60, 20, 10)
ga = sasm.analyze_assembly([("A", b1, {}), ("B", b2, {})], 0.0, None)
qa = mesh(ga, 6.0)
fa, fb = fid(ga, [-1, 0, 0], bodies=[0]), fid(ga, [1, 0, 0], bodies=[1])
k1, k2 = 10.0, 100.0
mats = [dict(MAT, k=k1, name="A"), dict(MAT, k=k2, name="B")]
res = run(qa, {"materials": mats, "temps": [{"name": "hot", "fids": [fa], "T": 500.0}, {"name": "cold", "fids": [fb], "T": 300.0}]})
R = 0.04 / (k1 * Aslab) + 0.06 / (k2 * Aslab)
Qw = 200.0 / R
near(res["flows"][0]["Q"], Qw, 1e-8, f"a wall of two bodies: the heat through it (R = {R:.3f} K/W)")
Ti = 500.0 - Qw * 0.04 / (k1 * Aslab)
xs = res["nodes"][:, 0]
at_if = np.abs(xs - 40.0) < 1e-9
ok(at_if.any() and np.abs(res["T"][at_if] - Ti).max() < 1e-7, f"the temperature at the joint is the series-resistance one: {res['T'][at_if].mean():.5f} against {Ti:.5f}")
ok(res["balance"]["relative_error"] < 1e-10 and len(res["bodies"]) == 2, "the balance closes and the two bodies are reported")
ok(abs(res["bodies"][0]["Tmax"] - 500.0) < 1e-9 and abs(res["bodies"][1]["Tmin"] - 300.0) < 1e-9, "each body has its own temperature range")
q_a = res["qmag"][res["body"] == 0].mean()
q_b = res["qmag"][res["body"] == 1].mean()
near(q_a, Qw / Aslab, 1e-7, "the flux is the same in both materials")
near(q_b, Qw / Aslab, 1e-7, "the flux is the same in the other material")
# the same wall with the materials swapped in the list is a different wall: the order of the list is the order of the bodies
res_sw = run(qa, {"materials": [mats[1], mats[0]], "temps": [{"name": "hot", "fids": [fa], "T": 500.0}, {"name": "cold", "fids": [fb], "T": 300.0}]})
ok(abs(res_sw["flows"][0]["Q"] - Qw) > 1e-3 * Qw or abs(0.04 / (k2 * Aslab) + 0.06 / (k1 * Aslab) - R) < 1e-12, "the material list follows the order of the bodies")
R_sw = 0.04 / (k2 * Aslab) + 0.06 / (k1 * Aslab)
near(res_sw["flows"][0]["Q"], 200.0 / R_sw, 1e-8, "swapped: the other series resistance")

# ------------------------------------------------------------------------------------------------------------------- a hollow cylinder with convection
r1, r2, Lc = 10.0, 20.0, 30.0
cyl = b.Cylinder(r2, Lc) - b.Cylinder(r1, Lc)
g, q = part(cyl, 2.0)
inner = next(f["id"] for f in g["faces"] if f.get("cyl") and abs(f["cyl"]["radius"] - r1) < 1e-6)
outer = next(f["id"] for f in g["faces"] if f.get("cyl") and abs(f["cyl"]["radius"] - r2) < 1e-6)
kc, hc = 50.0, 200.0
res = run(q, {"temps": [{"name": "inner", "fids": [inner], "T": 400.0}], "convs": [{"name": "outer", "fids": [outer], "h": hc, "Tinf": 300.0}]})
Qc = 2 * math.pi * kc * (Lc * 1e-3) * 100.0 / (math.log(r2 / r1) + kc / (hc * r2 * 1e-3))
near(res["flows"][0]["Q"], Qc, 0.01, "a hollow cylinder cooled by convection: the heat flow (2 pi k L dT / (ln r2/r1 + k / h r2))")
near(-res["flows"][1]["Q"], res["flows"][0]["Q"], 1e-5, "the convection carries away what the inner wall delivers")
ok(res["balance"]["relative_error"] < 1e-9, f"the balance closes: {res['balance']['relative_error']:.2e}")
Tw = 300.0 + Qc / (2 * math.pi * (Lc * 1e-3) * (r2 * 1e-3) * hc)
ok(abs(res["T"][np.unique(q["ftri"][outer])].mean() - Tw) < 0.1, f"the temperature of the outer wall: {res['T'][np.unique(q['ftri'][outer])].mean():.3f} against {Tw:.3f}")
rr = np.hypot(res["nodes"][:, 0], res["nodes"][:, 1])
Tr = 400.0 - Qc * np.log(rr / r1) / (2 * math.pi * kc * Lc * 1e-3)
sel = (rr > 10.5) & (rr < 19.5)
ok(np.abs(res["T"][sel] - Tr[sel]).max() < 0.35, f"and the temperature through the wall follows the logarithm: largest difference {np.abs(res['T'][sel] - Tr[sel]).max():.3f} K")

# ------------------------------------------------------------------------------------------------------------------- a hollow sphere
rs1, rs2 = 10.0, 20.0
sph = b.Sphere(rs2) - b.Sphere(rs1)
g, q = part(sph, 2.0)
fa_, fb_ = sorted(g["faces"], key=lambda f: f["area"])
res = run(q, {"temps": [{"name": "in", "fids": [fa_["id"]], "T": 400.0}, {"name": "out", "fids": [fb_["id"]], "T": 300.0}]})
Qs = 4 * math.pi * 50.0 * 100.0 / (1 / (rs1 * 1e-3) - 1 / (rs2 * 1e-3))
near(res["flows"][0]["Q"], Qs, 0.01, "a hollow sphere between two temperatures: 4 pi k dT / (1/r1 - 1/r2)")
rr = np.linalg.norm(res["nodes"], axis=1)
Tsph = 300.0 + (400.0 - 300.0) * (1 / (rr * 1e-3) - 1 / (rs2 * 1e-3)) / (1 / (rs1 * 1e-3) - 1 / (rs2 * 1e-3))
sel = (rr > 10.8) & (rr < 19.2)
ok(np.abs(res["T"][sel] - Tsph[sel]).max() < 1.2, f"the temperature through the shell follows 1/r: largest difference {np.abs(res['T'][sel] - Tsph[sel]).max():.3f} K")

# a finer mesh is closer
g2, q2 = part(sph, 1.4)
fa2, fb2 = sorted(g2["faces"], key=lambda f: f["area"])
res_f = run(q2, {"temps": [{"name": "in", "fids": [fa2["id"]], "T": 400.0}, {"name": "out", "fids": [fb2["id"]], "T": 300.0}]})
ok(abs(res_f["flows"][0]["Q"] - Qs) < abs(res["flows"][0]["Q"] - Qs) * 1.05, f"the finer mesh is no further from the exact answer: {abs(res_f['flows'][0]['Q'] - Qs) / Qs * 100:.3f} % against {abs(res['flows'][0]['Q'] - Qs) / Qs * 100:.3f} %")

# ------------------------------------------------------------------------------------------------------------------- heat generation in a sphere
Rg = 20.0
ball = b.Sphere(Rg)
g, q = part(ball, 2.5)
skin = g["faces"][0]["id"]
qgen, kg = 1.0e6, 20.0
res = run(q, {"materials": [dict(MAT, k=kg, gen=qgen)], "temps": [{"name": "skin", "fids": [skin], "T": 300.0}]})
Tc = 300.0 + qgen * (Rg * 1e-3) ** 2 / (6 * kg)
near(res["Tmax"] - 300.0, Tc - 300.0, 0.02, "heat generation in a sphere: the temperature rise at the centre (q R2 / 6 k)")
V = 4.0 / 3.0 * math.pi * (Rg * 1e-3) ** 3
near(res["balance"]["generation"], qgen * V, 0.01, "the heat generated is q times the volume")
near(res["flows"][0]["Q"], -res["balance"]["generation"], 1e-8, "and the fixed skin takes all of it away")
ok(res["balance"]["relative_error"] < 1e-9, f"the balance closes: {res['balance']['relative_error']:.2e}")
rr = np.linalg.norm(res["nodes"], axis=1)
Tg = 300.0 + qgen * ((Rg * 1e-3) ** 2 - (rr * 1e-3) ** 2) / (6 * kg)
ok(np.abs(res["T"] - Tg).max() < 0.06, f"the whole parabola: largest difference {np.abs(res['T'] - Tg).max():.4f} K of a rise of {Tc - 300:.2f}")

# the heat flux: at the centre of every element it is q = q_gen r / 3 along the radius (the quadratic elements hold the parabola exactly)
cen = res["nodes"][res["conn"][:, :4]].mean(axis=1) * 1e-3
q_exact = qgen / 3.0 * cen
err = np.linalg.norm(res["q"] - q_exact, axis=1)
ok(err.max() < 0.03 * qgen / 3.0 * Rg * 1e-3 and np.median(err) < 0.005 * qgen / 3.0 * Rg * 1e-3,
   f"the heat flux at the centre of every element is q_gen r / 3 outward: largest error {err.max() / (qgen / 3.0 * Rg * 1e-3) * 100:.2f} % of the largest flux, median {np.median(err) / (qgen / 3.0 * Rg * 1e-3) * 100:.3f} %")
ok(np.all(np.einsum("ij,ij->i", res["q"], cen) > 0), "and it points outward everywhere (heat flows from the hot centre to the cold skin)")
near(float(res["qmag"].max()), qgen / 3.0 * Rg * 1e-3, 0.03, "the largest flux is at the skin: q_gen R / 3")

# ------------------------------------------------------------------------------------------------------------------- a fin with convection on its sides and tip
Lf, wf = 100.0, 10.0
fin = b.Pos(Lf / 2, 0, 0) * b.Box(Lf, wf, wf)
g, q = part(fin, 3.0)
base = fid(g, [-1, 0, 0])
sides = [fid(g, n) for n in ([1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1])]
kf, hf = 200.0, 20.0
res = run(q, {"materials": [dict(MAT, k=kf)], "temps": [{"name": "base", "fids": [base], "T": 400.0}],
              "convs": [{"name": "skin", "fids": sides, "h": hf, "Tinf": 300.0}]})
P_, A_ = 4 * wf * 1e-3, (wf * 1e-3) ** 2
m = math.sqrt(hf * P_ / (kf * A_))
Lm = Lf * 1e-3
Bi = hf / (m * kf)
Qf = math.sqrt(hf * P_ * kf * A_) * 100.0 * (math.sinh(m * Lm) + Bi * math.cosh(m * Lm)) / (math.cosh(m * Lm) + Bi * math.sinh(m * Lm))
near(res["flows"][0]["Q"], Qf, 0.005, "a fin with a convecting tip: the heat from the base (sqrt(h P k A) theta tanh-form)")
Ttip = 300.0 + 100.0 / (math.cosh(m * Lm) + Bi * math.sinh(m * Lm))
tip = res["nodes"][:, 0] > Lf - 1e-9
near(res["T"][tip].mean(), Ttip, 0.002, "and the temperature of its tip")
ok(res["balance"]["relative_error"] < 1e-9, f"the balance closes: {res['balance']['relative_error']:.2e}")

# ------------------------------------------------------------------------------------------------------------------- radiation: steady, against its closed form
eps, Ts_ = 0.8, 300.0
g, q = part(slab, 8.0)
left, right = fid(g, [-1, 0, 0]), fid(g, [1, 0, 0])
res = run(q, {"temps": [{"name": "hot", "fids": [left], "T": 600.0}], "rads": [{"name": "out", "fids": [right], "eps": eps, "Ts": Ts_}]})
# k A (T1 - Tr) / L = eps sigma A (Tr^4 - Ts^4): solve for Tr
Lm = LX * 1e-3
Tr = 450.0
for _ in range(60):
    f = 50.0 * (600.0 - Tr) / Lm - eps * tf.SIGMA * (Tr ** 4 - Ts_ ** 4)
    d = -50.0 / Lm - 4 * eps * tf.SIGMA * Tr ** 3
    Tr -= f / d
tipR = res["nodes"][:, 0] > LX / 2 - 1e-9
near(res["T"][tipR].mean(), Tr, 1e-7, f"radiation from the end of a slab to the surroundings: the end face's temperature ({Tr:.3f} K)")
ok(res["newton"] is not None and res["newton"]["converged"] and res["newton"]["iterations"] <= 12, f"Newton converged in {res['newton']['iterations']} iterations")
near(-res["flows"][1]["Q"], eps * tf.SIGMA * Aslab * (Tr ** 4 - Ts_ ** 4), 1e-6, "the radiated heat")
ok(res["balance"]["relative_error"] < 1e-8, f"the balance closes: {res['balance']['relative_error']:.2e}")
# a flux in and radiation out, nothing else holding the temperature: the radiation grounds the model
resq = run(q, {"fluxes": [{"name": "in", "fids": [left], "q": 2000.0}], "rads": [{"name": "out", "fids": [right], "eps": eps, "Ts": Ts_},
                                                                                  {"name": "sides", "fids": [fid(g, [0, 1, 0])], "eps": 0.0, "Ts": Ts_}]})
# the heat in leaves through the right face only (the other face has no emissivity): q = eps sigma (T^4 - Ts^4); the slab itself is isothermal to q L / k
Tq = (2000.0 / (eps * tf.SIGMA) + Ts_ ** 4) ** 0.25
near(resq["T"][resq["nodes"][:, 0] > LX / 2 - 1e-9].mean(), Tq, 1e-9, f"a flux in and radiation out with nothing else: the temperature of the radiating end ({Tq:.3f} K)")
ok(abs(resq["Tmax"] - (Tq + 2000.0 * LX * 1e-3 / 50.0)) < 1e-6, f"and the other end is hotter by q L / k = {2000.0 * LX * 1e-3 / 50.0:.3f} K")
# the Jacobian of the radiation is the derivative of its residual (a wrong one would still converge, slowly: check it itself)
mdl = tf.Model(q, {"lscale": 1e-3, "materials": [dict(MAT)], "temps": [{"name": "hot", "fids": [left], "T": 600.0}],
                   "rads": [{"name": "out", "fids": [right], "eps": eps, "Ts": Ts_}]})
Tt = np.random.default_rng(3).uniform(350.0, 650.0, mdl.N)
R0, J0 = mdl.radiation(Tt)
cols = np.unique(q["ftri"][right])[:6]
for c in cols:
    d = np.zeros(mdl.N)
    d[c] = 1e-3
    fd = (mdl.radiation(Tt + d, jac=False)[0] - mdl.radiation(Tt - d, jac=False)[0]) / 2e-3
    ok(np.abs(J0[:, c].toarray().ravel() - fd).max() < 1e-6 * np.abs(fd).max() + 1e-12, f"the radiation Jacobian column of node {c} is the derivative of the residual: {np.abs(J0[:, c].toarray().ravel() - fd).max():.2e}")
ok(res["newton"]["iterations"] <= 4, f"and Newton converges at once (quadratically): {res['newton']['iterations']} iterations")
# two fixed temperatures that meet along an edge: the later one holds there, and it is said
g2_, q2_ = part(slab, 8.0)
l2, t2 = fid(g2_, [-1, 0, 0]), fid(g2_, [0, 0, 1])
rcn = run(q2_, {"temps": [{"name": "first", "fids": [l2], "T": 400.0}, {"name": "second", "fids": [t2], "T": 350.0}]})
edge = np.intersect1d(np.unique(q2_["ftri"][l2]), np.unique(q2_["ftri"][t2]))
ok(len(edge) > 2 and np.allclose(rcn["T"][edge], 350.0) and any("Two fixed temperatures" in n for n in rcn["notes"]), f"two fixed temperatures meeting along an edge: the later one holds ({rcn['T'][edge].mean():.1f} K) and the result says so")
# radiation with a small difference is the same as convection with h = 4 eps sigma T^3
resr = run(q, {"temps": [{"name": "hot", "fids": [left], "T": 301.0}], "rads": [{"name": "out", "fids": [right], "eps": eps, "Ts": 300.0}]})
hlin = 4 * eps * tf.SIGMA * 300.5 ** 3
resc = run(q, {"temps": [{"name": "hot", "fids": [left], "T": 301.0}], "convs": [{"name": "out", "fids": [right], "h": hlin, "Tinf": 300.0}]})
ok(np.abs(resr["T"] - resc["T"]).max() < 1e-4, f"for a small temperature difference radiation is convection with h = 4 eps sigma T3: {np.abs(resr['T'] - resc['T']).max():.2e} K")

# ------------------------------------------------------------------------------------------------------------------- transient: a slab cooled from both ends (series solution)
Lt = 50.0
plate = b.Box(Lt, 20.0, 10.0)
g, q = part(plate, 4.0)
left, right = fid(g, [-1, 0, 0]), fid(g, [1, 0, 0])
alpha = 50.0 / (7800.0 * 500.0)
tau = (Lt * 1e-3) ** 2 / (math.pi ** 2 * alpha)


def series(x, t):
    s = 0.0
    for n in range(1, 400, 2):
        s += 4 / (n * math.pi) * math.sin(n * math.pi * x) * math.exp(-alpha * (n * math.pi / (Lt * 1e-3)) ** 2 * t)
    return 300.0 + 100.0 * s


for theta, steps, lim in ((1.0, 400, 0.006), (0.5, 100, 0.012)):
    res = run(q, {"analysis": "transient", "T0": 400.0, "t_end": 1.5 * tau, "steps": steps, "theta": theta, "frames": 10,
                  "temps": [{"name": "a", "fids": [left], "T": 300.0}, {"name": "b", "fids": [right], "T": 300.0}]})
    xc = (res["nodes"][:, 0] + Lt / 2) / Lt
    worst = 0.0
    for ti, Tf in zip(res["times"], res["frames"]):
        if ti < 0.2 * tau:
            continue
        exact = np.array([series(x, ti) for x in xc])
        worst = max(worst, float(np.abs(Tf - exact).max()) / 100.0)
    ok(worst < lim, f"transient slab, theta = {theta}, {steps} steps: the temperature against the series solution from 0.2 tau on: {worst * 100:.3f} % of the step (limit {lim * 100:g} %)")
    ok(len(res["times"]) == 10 and abs(res["times"][-1] - 1.5 * tau) < 1e-9 and res["frames"].shape[0] == 10, "ten pictures were kept, the last at the end time")
    ok(abs(res["frames"][0][np.abs(res["nodes"][:, 0]) < 1e-9].mean() - 400.0) < 1e-9 and res["frames"][0][np.unique(q["ftri"][left])].max() == 300.0, "the start is the uniform temperature, but the fixed faces hold theirs from the first picture")
ok(res["balance"]["relative_error"] < 5e-2, f"the end-of-run balance (the stored heat included) is within the Crank-Nicolson limit: {res['balance']['relative_error']:.2e}")
rbe = run(q, {"analysis": "transient", "T0": 400.0, "t_end": 1.5 * tau, "steps": 60, "theta": 1.0, "frames": 3,
              "temps": [{"name": "a", "fids": [left], "T": 300.0}, {"name": "b", "fids": [right], "T": 300.0}]})
ok(rbe["balance"]["relative_error"] < 1e-9 and rbe["balance"]["stored"] < 0, f"a slab cooled through its two fixed ends: the heat that leaves them is the stored heat, backward Euler closes it to {rbe['balance']['relative_error']:.1e}")
near(rbe["flows"][0]["Q"] + rbe["flows"][1]["Q"], rbe["balance"]["stored"], 1e-9, "the two ends' flows (negative: out) add up to the stored heat")

# lumped cooling: a copper cube in a fluid
cube = b.Box(10.0, 10.0, 10.0)
g, q = part(cube, 5.0)
allf = [f["id"] for f in g["faces"]]
kcu, rcu, ccu = 400.0, 8900.0, 390.0
hh = 25.0
Vc, Ac = (0.01) ** 3, 6 * (0.01) ** 2
tau_l = rcu * ccu * Vc / (hh * Ac)
res = run(q, {"materials": [dict(rho=rcu, cp=ccu, k=kcu)], "analysis": "transient", "T0": 400.0, "t_end": 2 * tau_l, "steps": 200, "theta": 0.5, "frames": 5,
              "convs": [{"name": "all", "fids": allf, "h": hh, "Tinf": 300.0}]})
exact = 300.0 + 100.0 * np.exp(-res["times"] / tau_l)
got = res["frames"].mean(axis=1)
ok(np.abs(res["frames"].max(axis=1) - res["frames"].min(axis=1)).max() < 0.05, "a small copper cube cools as one lump (the temperature differences inside stay below 0.05 K)")
ok(np.abs(got - exact).max() < 0.05, f"lumped cooling: {np.round(got, 3).tolist()} against {np.round(exact, 3).tolist()}")
near(res["T"].mean(), 300.0 + 100.0 * math.exp(-2), 5e-4, "after two time constants the cube is at 300 + 100 e^-2")
# the same cube cooled by radiation: the ODE
from scipy.integrate import solve_ivp
epsr = 0.9
tau_r = rcu * ccu * Vc / (epsr * tf.SIGMA * Ac * 400.0 ** 3)
res = run(q, {"materials": [dict(rho=rcu, cp=ccu, k=kcu)], "analysis": "transient", "T0": 600.0, "t_end": 3 * tau_r, "steps": 300, "theta": 0.5, "frames": 6,
              "rads": [{"name": "all", "fids": allf, "eps": epsr, "Ts": 300.0}]})
sol = solve_ivp(lambda t, T: -epsr * tf.SIGMA * Ac * (T ** 4 - 300.0 ** 4) / (rcu * ccu * Vc), [0, res["times"][-1]], [600.0], t_eval=res["times"], rtol=1e-10, atol=1e-10)
ok(np.abs(res["frames"].mean(axis=1) - sol.y[0]).max() < 0.15, f"radiation cooling of a lump against the ODE: largest difference {np.abs(res['frames'].mean(axis=1) - sol.y[0]).max():.4f} K")
ok(res["run"]["unconverged_steps"] == 0 and res["newton"]["max_iterations"] <= 8, f"every step converged ({res['newton']['max_iterations']} iterations at most)")

# two bodies with different heat capacities and different heat generation, as lumps (a conductivity so high that each assembly is isothermal)
gl = sasm.analyze_assembly([("A", b.Pos(5, 0, 0) * b.Box(10, 10, 10), {}), ("B", b.Pos(15, 0, 0) * b.Box(10, 10, 10), {})], 0.0, None)
ql = mesh(gl, 5.0)
outer = [f["id"] for f in gl["faces"] if not f.get("interface")]
Aexp = sum(f["area"] for f in gl["faces"] if not f.get("interface")) * 1e-6
Vb = 1e-6
mA = dict(rho=1000.0, cp=500.0, k=1.0e5, gen=3.0e6, name="A")
mB = dict(rho=4000.0, cp=900.0, k=1.0e5, gen=-1.0e6, name="B")
res = run(ql, {"materials": [mA, mB], "convs": [{"name": "all", "fids": outer, "h": 50.0, "Tinf": 300.0}]})
Tl = 300.0 + (3.0e6 + -1.0e6) * Vb / (50.0 * Aexp)
near(res["Tmean"], Tl, 1e-6, f"two lumps with their own heat generation: T_inf + (g1 V1 + g2 V2) / (h A) = {Tl:.4f} K")
near(res["balance"]["generation"], 2.0e6 * Vb, 1e-9, "the generated heat is the sum of the two bodies' own")
ok(abs(res["bodies"][0]["generation"] - 3.0e6 * Vb) < 1e-12 and abs(res["bodies"][1]["generation"] + 1.0e6 * Vb) < 1e-12, "and each body reports its own")
tauL = (1000.0 * 500.0 + 4000.0 * 900.0) * Vb / (50.0 * Aexp)
res = run(ql, {"materials": [dict(mA, gen=0.0), dict(mB, gen=0.0)], "analysis": "transient", "T0": 400.0, "t_end": 2 * tauL, "steps": 100, "theta": 0.5, "frames": 3,
               "convs": [{"name": "all", "fids": outer, "h": 50.0, "Tinf": 300.0}]})
near(res["Tmean"] - 300.0, 100.0 * math.exp(-2.0), 2e-3, "two lumps of different heat capacity cool together: the time constant is (rho cp V summed) / (h A)")

# the heat balance of a transient run has the stored heat in it: backward Euler closes it exactly
g, q = part(cube, 5.0)
allf = [f["id"] for f in g["faces"]]
rb = run(q, {"materials": [dict(rho=rcu, cp=ccu, k=kcu)], "analysis": "transient", "T0": 400.0, "t_end": tau_l, "steps": 50, "theta": 1.0, "frames": 3,
             "convs": [{"name": "all", "fids": allf, "h": hh, "Tinf": 300.0}]})
bb = rb["balance"]
ok(bb["stored"] < 0 and bb["relative_error"] < 1e-9, f"a cooling cube: the stored heat is negative ({bb['stored']:.4f} W) and in - out - stored closes to {bb['relative_error']:.1e}")
near(bb["stored"], -bb["out"], 1e-9, "the heat it gives off is the heat it loses from storage")
rb2 = run(ql, {"materials": [dict(mA, gen=3.0e6), dict(mB, gen=0.0)], "analysis": "transient", "T0": 300.0, "t_end": tauL, "steps": 40, "theta": 1.0, "frames": 3,
               "convs": [{"name": "all", "fids": outer, "h": 50.0, "Tinf": 300.0}]})
ok(rb2["balance"]["stored"] > 0 and rb2["balance"]["relative_error"] < 1e-6, f"a heating lump: generation = stored + convected, to {rb2['balance']['relative_error']:.1e}")
ok(abs(rb2["balance"]["generation"] - (rb2["balance"]["stored"] + rb2["balance"]["out"])) < 1e-6 * rb2["balance"]["generation"], "the three terms add up")

# a solve that does not satisfy its equations is refused, not shown
saved_solve = tf._Linear.solve
try:
    tf._Linear.solve = lambda self, b, x0=None: np.ones(self.n) * 310.0
    g3, q3 = part(slab, 8.0)
    refuses(q3, {"fluxes": [{"name": "in", "fids": [fid(g3, [-1, 0, 0])], "q": 1000.0}], "temps": [{"name": "t", "fids": [fid(g3, [1, 0, 0])], "T": 300.0}]},
            ["not reliable", "relative residual"], "a wrong solution")
finally:
    tf._Linear.solve = saved_solve

# a hex-dominant mesh is refused in words
hexq = dict(q3, groups=[{"kind": "tet", "conn": q3["conn"]}, {"kind": "hex", "conn": np.zeros((1, 8), np.int64)}])
refuses(hexq, {"temps": [{"name": "t", "fids": [fid(g3, [-1, 0, 0])], "T": 300.0}]}, ["hexahedra", "Tetrahedra"], "a mesh with hexahedra")

# a cancel is noticed in the middle of the assembly (asked once per piece of elements), not only before and after it
calls, said3 = [], []
saved_chunk = tf.CHUNK
try:
    tf.CHUNK = 50
    run(q3, {"temps": [{"name": "t", "fids": [fid(g3, [-1, 0, 0])], "T": 300.0}]}, cancel=lambda: (calls.append(1), len(calls) >= 3)[1], progress=said3.append)
    ok(False, "a cancel in the assembly stops the run")
except tf.Cancelled:
    ok(said3 == ["Assembling the matrices"], f"a cancel is noticed inside the assembly, before the solve begins: {said3}")
finally:
    tf.CHUNK = saved_chunk

# a steady state is where a transient run ends
g, q = part(slab, 8.0)
left, right = fid(g, [-1, 0, 0]), fid(g, [1, 0, 0])
conds = {"fluxes": [{"name": "in", "fids": [left], "q": 20000.0}], "convs": [{"name": "out", "fids": [right], "h": 500.0, "Tinf": 300.0}]}
st = run(q, conds)
tr = run(q, dict(conds, analysis="transient", T0=300.0, t_end=60000.0, steps=60, theta=1.0, frames=3))
ok(np.abs(tr["T"] - st["T"]).max() < 1e-3, f"a long transient run ends at the steady solution: {np.abs(tr['T'] - st['T']).max():.2e} K")
ok(tr["balance"]["stored"] < 1e-3 * abs(tr["balance"]["in"]) and abs(tr["balance"]["relative_error"]) < 1e-6, "with nothing left to store, and the balance closed")

# ------------------------------------------------------------------------------------------------------------------- mixed conditions: the balance on a body with everything at once
cb = b.Box(60.0, 40.0, 20.0) - b.Pos(0, 0, 0) * b.Cylinder(6.0, 20.0)
g, q = part(cb, 5.0)
holef = next(f["id"] for f in g["faces"] if f.get("cyl"))
left, right = fid(g, [-1, 0, 0]), fid(g, [1, 0, 0])
top, bottom, front, back = fid(g, [0, 0, 1]), fid(g, [0, 0, -1]), fid(g, [0, -1, 0]), fid(g, [0, 1, 0])
spec = {"materials": [dict(MAT, k=35.0, gen=2.0e5)],
        "temps": [{"name": "cold plate", "fids": [bottom], "T": 310.0}],
        "fluxes": [{"name": "sun", "fids": [top], "q": 800.0}],
        "powers": [{"name": "heater", "fids": [left], "P": 12.0}],
        "convs": [{"name": "air", "fids": [right, front], "h": 15.0, "Tinf": 295.0}],
        "rads": [{"name": "sky", "fids": [back], "eps": 0.7, "Ts": 260.0}],
        "ins": [{"name": "hole", "fids": [holef]}]}
res = run(q, spec)
b_ = res["balance"]
ok(b_["relative_error"] < 1e-9, f"six kinds of condition at once, heat generation too: the balance closes to {b_['relative_error']:.2e} of {b_['in']:.3f} W")
names = [f["name"] for f in res["flows"]]
ok(names == ["cold plate", "sun", "heater", "air", "sky", "hole"], f"the flows come back in the order of the conditions: {names}")
near([f for f in res["flows"] if f["name"] == "heater"][0]["Q"], 12.0, 1e-12, "the heater delivers its 12 W")
near(flow(res, "sun")["Q"], 800.0 * g["faces"][top]["area"] * 1e-6, 0.01, "the sun's flux over the top (the flux times the area of the face)")
ok(res["Tmax"] > 310.0 and res["notes"] == [], f"the temperatures are plausible ({res['Tmin']:.2f} to {res['Tmax']:.2f} K) and nothing was noted: {res['notes']}")
res_l = run(fem.linear(fem.mesh_solid(g, 5.0, NOCANCEL, SILENT, None)), spec)
ok(res_l["balance"]["relative_error"] < 1e-9 and abs(res_l["Tmax"] - res["Tmax"]) < 0.08 * (res["Tmax"] - 310.0) + 0.2, f"the same problem with linear elements: balance closes, hottest point {res_l['Tmax']:.3f} against {res['Tmax']:.3f} K")

# ------------------------------------------------------------------------------------------------------------------- refusals say what is wrong
g, q = part(slab, 8.0)
left, right = fid(g, [-1, 0, 0]), fid(g, [1, 0, 0])
refuses(q, {"fluxes": [{"name": "in", "fids": [left], "q": 1000.0}]}, ["fixed temperature, convection or radiation"], "a steady model with nothing to hold its temperature")
refuses(q, {"temps": [{"name": "t", "fids": [left], "T": -3.0}]}, ["above 0 K"], "a negative temperature")
refuses(q, {"temps": [{"name": "t", "fids": [], "T": 300.0}]}, ["no face is picked"], "a condition without a face")
refuses(q, {"temps": [{"name": "t", "fids": [999], "T": 300.0}]}, ["no elements"], "a face the mesh does not have")
refuses(q, {"materials": [dict(MAT, k=0.0)], "temps": [{"name": "t", "fids": [left], "T": 300.0}]}, ["conductivity"], "a conductivity of zero")
refuses(q, {"materials": [dict(MAT, cp=-1.0)], "temps": [{"name": "t", "fids": [left], "T": 300.0}]}, ["specific heat"], "a negative specific heat")
refuses(q, {"temps": [{"name": "t", "fids": [left], "T": 300.0}], "convs": [{"name": "c", "fids": [right], "h": -1.0, "Tinf": 300.0}]}, ["cannot be negative"], "a negative h")
refuses(q, {"temps": [{"name": "t", "fids": [left], "T": 300.0}], "rads": [{"name": "r", "fids": [right], "eps": 1.5, "Ts": 300.0}]}, ["between 0 and 1"], "an emissivity above 1")
refuses(q, {"analysis": "transient", "T0": 300.0, "t_end": 0.0, "steps": 10, "temps": [{"name": "t", "fids": [left], "T": 300.0}]}, ["end time"], "a transient run of no time")
refuses(q, {"analysis": "transient", "T0": -1.0, "t_end": 1.0, "steps": 10, "temps": [{"name": "t", "fids": [left], "T": 300.0}]}, ["starting temperature"], "a negative start")
refuses(q, {"materials": [], "temps": [{"name": "t", "fids": [left], "T": 300.0}]}, ["no material"], "a body without a material")
# bonded bodies are one piece: one fixed face holds both
ga2 = sasm.analyze_assembly([("A", b.Pos(20, 0, 0) * b.Box(40, 20, 10), {}), ("B", b.Pos(70, 0, 0) * b.Box(60, 20, 10), {})], 0.0, None)
qa2 = mesh(ga2, 8.0)
res = run(qa2, {"materials": mats, "temps": [{"name": "t", "fids": [fid(ga2, [-1, 0, 0], bodies=[0])], "T": 300.0}]})
ok(abs(res["Tmax"] - 300.0) < 1e-9 and abs(res["Tmin"] - 300.0) < 1e-9, f"bonded bodies are one piece: one fixed face holds both ({res['Tmin']:.9f} to {res['Tmax']:.9f} K)")
# two bodies that do not touch: the one without a condition is named
gap = sasm.analyze_assembly([("Block", b.Pos(20, 0, 0) * b.Box(40, 20, 10), {}), ("Loose", b.Pos(90, 0, 0) * b.Box(40, 20, 10), {})], 0.0, None)
qg = mesh(gap, 8.0)
refuses(qg, {"materials": [dict(MAT, name="Block"), dict(MAT, name="Loose")], "temps": [{"name": "t", "fids": [fid(gap, [-1, 0, 0], bodies=[0])], "T": 300.0}]},
        ["every separate piece", "Loose"], "a body that touches nothing and has no temperature, convection or radiation")
# a model too big for the free memory is refused in words, before the work
saved_mem = fem.available_memory
try:
    fem.available_memory = lambda: 2.0e8
    refuses(q, {"temps": [{"name": "t", "fids": [left], "T": 300.0}]}, ["GB of memory", "larger elements"], "a model that needs more memory than is free")
finally:
    fem.available_memory = saved_mem
# a cancel is honoured
try:
    run(q, {"temps": [{"name": "t", "fids": [left], "T": 300.0}]}, cancel=lambda: True)
    ok(False, "a cancel stops the run")
except tf.Cancelled:
    ok(True, "a cancel stops the run")
# a progress function is called, and a Tracker-like object is allowed
said = []
run(q, {"temps": [{"name": "t", "fids": [left], "T": 300.0}]}, progress=said.append)
ok(said[0].startswith("Assembling") and said[-1] == "Done", f"the progress texts: {said}")


class Tracker:
    def __init__(self):
        self.stages, self.parts = [], []

    def __call__(self, t):
        pass

    def stage(self, key, size):
        self.stages.append(key)

    def part(self, f):
        self.parts.append(f)


trk = Tracker()
run(q, {"temps": [{"name": "t", "fids": [left], "T": 300.0}, {"name": "u", "fids": [right], "T": 350.0}]}, progress=trk)
ok(trk.stages[:2] == ["assemble", "factor"] and trk.parts and abs(trk.parts[-1] - 1.0) < 1e-12, f"the progress bar is told about the assembly and the factorisation: {trk.stages}")

# ------------------------------------------------------------------------------------------------------------------- the iterative solver for large systems
saved = tf.DIRECT_LIMIT
try:
    tf.DIRECT_LIMIT = 500
    g, q = part(slab, 5.0)
    left, right = fid(g, [-1, 0, 0]), fid(g, [1, 0, 0])
    res = run(q, {"temps": [{"name": "hot", "fids": [left], "T": 400.0}, {"name": "cold", "fids": [right], "T": 300.0}]})
    x = (res["nodes"][:, 0] + LX / 2) / LX
    ok(res["run"]["solver"] == "iterative" and res["unknowns"] > 500, f"above the direct limit the multigrid-preconditioned solver is used ({res['unknowns']} unknowns, {res['run']['linear_iterations']} iterations)")
    ok(np.abs(res["T"] - (400 - 100 * x)).max() < 1e-5, f"and it gives the same linear field: {np.abs(res['T'] - (400 - 100 * x)).max():.2e} K")
    ok(res["run"]["linear_iterations"] <= 25, f"in a handful of iterations ({res['run']['linear_iterations']}): the multigrid knows that a constant temperature is the near-null vector")
    tr = run(q, {"analysis": "transient", "T0": 300.0, "t_end": 2000.0, "steps": 8, "theta": 1.0, "frames": 3,
                 "fluxes": [{"name": "in", "fids": [left], "q": 20000.0}], "convs": [{"name": "out", "fids": [right], "h": 500.0, "Tinf": 300.0}]})
    ok(tr["run"]["solver"] == "iterative" and tr["run"]["linear_iterations"] > 0 and tr["balance"]["relative_error"] < 1e-5, f"a transient run reuses the multigrid hierarchy: {tr['run']['linear_iterations']} iterations in 8 steps")
    rd = run(q, {"temps": [{"name": "hot", "fids": [left], "T": 400.0}], "rads": [{"name": "out", "fids": [right], "eps": 0.8, "Ts": 300.0}]})
    ok(rd["newton"]["converged"] and rd["balance"]["relative_error"] < 1e-6, "Newton with the iterative solver converges and closes the balance")
finally:
    tf.DIRECT_LIMIT = saved

print("\nFAILED:", FAILS) if FAILS else print("\nOK thermal3d fem")
sys.exit(1 if FAILS else 0)
