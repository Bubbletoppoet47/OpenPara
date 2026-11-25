"""The temperature of the fluid in the 2D CFD (physics_cfd_heat.py), against closed forms and against its own physics:

  * the operator: a temperature that varies only across a uniform flow is a solution (exact), and the one-dimensional advection-diffusion profile with a boundary layer
    (Peclet 4 and 40) is reproduced
  * the walls: a wall at the inlet temperature gives no heat and no change; a heat flux is carried away exactly; the heat of a hot wall is carried out by the flow (energy balance)
  * linearity: twice the temperature difference is twice the heat flux, and the transfer coefficient h does not depend on it
  * a heated body in a real flow: the flow is solved by the CFD itself, then the temperature
  * mutations: with the convection or the reaction broken the checks above must fail
python test_cfd_temperature.py"""
import faulthandler
faulthandler.dump_traceback_later(900, exit=True)
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
import numpy as np

import sketcher_core as sc
import physics_cfd as pcfd
import physics_cfd_heat as ph

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


# ------------------------------------------------------------------------------------------------------------------------------ a rectangular mesh by hand
def rect_mesh(L, H, nx, ny):
    xs, ys = np.linspace(0, L, nx + 1), np.linspace(0, H, ny + 1)
    X, Y = np.meshgrid(xs, ys)
    nodes = np.stack([X.ravel(), Y.ravel()], axis=1)
    idx = lambda i, j: j * (nx + 1) + i
    tris = []
    for j in range(ny):
        for i in range(nx):
            a, b, c, d = idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)
            tris += [(a, b, c), (a, c, d)] if (i + j) % 2 == 0 else [(a, b, d), (b, c, d)]
    return nodes, np.array(tris, dtype=np.int64)


def disc_of(L, H, nx, ny):
    nodes, tris = rect_mesh(L, H, nx, ny)
    return pcfd.Disc(nodes, tris, 1.0), nodes


def uniform(disc, U):
    u = np.zeros((disc.Nu, 2))
    u[:, 0] = U
    return u


# ------------------------------------------------------------------------------------------------------------------------------ the operator
L, H = 4.0, 1.0
alpha = 0.05
d, nodes = disc_of(L, H, 16, 8)
u = uniform(d, 2.0)
A = ph.scalar_matrix(d, u[d.tri6], alpha)
x, y = d.xy[:, 0], d.xy[:, 1]
eps = 1e-9
dn = np.nonzero((y < eps) | (y > H - eps) | (x < eps))[0]
exact = 300.0 + 40.0 * y / H
T, react = ph.scalar_solve(d, A, dn, exact[dn])
ok(float(np.abs(T - exact).max()) < 1e-8, f"a temperature that varies only across a uniform flow is reproduced exactly (max error {np.abs(T - exact).max():.2e} K)")

Lx = 1.0


def profile_error(Pe, nx):
    d, nodes = disc_of(Lx, 0.25, nx, 2)
    u = uniform(d, Pe * alpha / Lx)
    A = ph.scalar_matrix(d, u[d.tri6], alpha)
    x = d.xy[:, 0]
    dn = np.nonzero((x < eps) | (x > Lx - eps))[0]
    T, _ = ph.scalar_solve(d, A, dn, np.where(x[dn] < eps, 0.0, 1.0))
    ex = (np.exp(Pe * x / Lx) - 1.0) / (np.exp(Pe) - 1.0)
    return float(np.abs(T - ex).max()), float(T.min()), float(T.max())


e20, _, _ = profile_error(4.0, 20)
e40, lo, hi = profile_error(4.0, 40)
ok(e40 < 5e-3 and e20 / e40 > 1.8, f"one-dimensional advection-diffusion, Peclet 4: error {e40:.2e} on 40 elements, {e20:.2e} on 20 (it halves with the element size: first order, from the stabilisation)")
e40, lo40, hi40 = profile_error(20.0, 40)
e80, lo80, hi80 = profile_error(20.0, 80)
ok(e80 < 0.06 and e40 / e80 > 1.5, f"Peclet 20 (a boundary layer a few elements wide): error {e40:.2e} -> {e80:.2e} when the mesh is refined")
ok(min(lo40, lo80) >= -1e-9 and max(hi40, hi80) <= 1.0 + 1e-9, "and no undershoot or overshoot of the layer")
_, lo, hi = profile_error(40.0, 20)
ok(lo >= -1e-9 and hi <= 1.0 + 1e-9, f"no undershoot or overshoot even when the layer is narrower than an element (Peclet 40 on 20 elements: {lo:.1e} .. {hi - 1:+.1e})")

# the same with the convection left out (the mutation): the profile must be wrong, so the test above can tell
orig = ph.scalar_matrix


def no_convection(disc, a6, alpha_):
    return orig(disc, np.zeros_like(a6), alpha_)


ph.scalar_matrix = no_convection
try:
    d, nodes = disc_of(Lx, 0.25, 40, 2)
    u = uniform(d, 40.0 * alpha / Lx)
    A = ph.scalar_matrix(d, u[d.tri6], alpha)
    x = d.xy[:, 0]
    dn = np.nonzero((x < eps) | (x > Lx - eps))[0]
    T, _ = ph.scalar_solve(d, A, dn, np.where(x[dn] < eps, 0.0, 1.0))
    ex = (np.exp(40.0 * x / Lx) - 1.0) / (np.exp(40.0) - 1.0)
    ok(float(np.abs(T - ex).max()) > 0.3, "mutation: without the convection term the Peclet 40 profile is far off (the check can fail)")
finally:
    ph.scalar_matrix = orig

# ------------------------------------------------------------------------------------------------------------------------------ a body in a real flow
import physics_geom as pgm


def flow_of(shape, U, h_body, h_far, margins, steps=300, cfl=2.0):
    m = sc.Model()
    p = [m.add_point(*c) for c in shape]
    for i in range(len(p)):
        m.add_line(p[i], p[(i + 1) % len(p)])
    geom = pgm.analyze(m)
    face_ids = {f["id"] for f in pcfd.body_faces(geom)}
    mesh = pcfd.mesh_fluid(m, geom, face_ids, margins, h_body, h_far, 3.0)
    rho, mu = pcfd.FLUIDS["Air 20 C"]
    setup = {"lscale": 1.0e-3, "rho": rho, "mu": mu, "speed": U, "angle": 0.0, "cfl": cfl, "h_body": h_body, "max_steps": steps, "tol": 1e-6, "until": False,
             "ramp_steps": 5, "frame_every": 1000, "dt": None, "turb": False, "edge_geoms": {e["src"]: pcfd.edge_geometry(m, e) for e in geom["edges"]}}
    return m, geom, mesh, pcfd.solve(mesh, setup), setup


m, geom, mesh, res, setup = flow_of(((0, 0), (20, 0), (20, 20), (0, 20)), 0.03, 3.0, 12.0, (3.0, 8.0, 3.0, 3.0), steps=250)
ok(res["status"] == "converged" and abs(res["mass"]["relative"]) < 1e-6, f"the flow itself: a 20 mm square in a 0.03 m/s stream, Re {res['re']:.0f} ({res['status']}, {res['steps']} steps)")
keys = list(mesh["wall_segs"].keys())
kair, cpair = 0.0257, 1006.0
T_in = 293.15


def heat(walls, **kw):
    return {"k": kair, "cp": cpair, "T_in": T_in, "walls": walls, **kw}


# 1) a wall at the inlet temperature changes nothing
r0 = ph.solve_temperature(mesh, res, heat({k: {"kind": "temp", "T": T_in} for k in keys}))
ok(float(np.abs(r0["T"] - T_in).max()) < 1e-9 and abs(r0["balance"]["walls"]) < 1e-9, f"walls at the inlet temperature: T = T_in everywhere (max deviation {np.abs(r0['T'] - T_in).max():.1e} K, no heat)")
# 2) insulated walls (no condition at all) also change nothing
r1 = ph.solve_temperature(mesh, res, heat({}))
ok(float(np.abs(r1["T"] - T_in).max()) < 1e-9, "insulated walls: T = T_in everywhere")
# 3) a hot body: the heat of the walls is carried out by the flow
dT = 30.0
rh = ph.solve_temperature(mesh, res, heat({k: {"kind": "temp", "T": T_in + dT} for k in keys}))
b = rh["balance"]
ok(b["walls"] > 0 and abs(b["relative"]) < 0.01, f"hot body: the walls give {b['walls']:.4g} W/m, the flow carries out {b['advected']:.4g} W/m (balance {100 * b['relative']:.2g} %; counting a corner shared by two walls twice gave 8.6 %)")
ok(rh["Tmax"] <= T_in + dT + 1e-9 and rh["Tmin"] >= T_in - 1e-9, f"no value outside the wall and inlet temperatures: {rh['Tmin'] - 273.15:.4f} .. {rh['Tmax'] - 273.15:.4f} degC")
up, down = [], []
for k in keys:
    t = rh["walls"][k]
    ok(t["kind"] == "temp" and abs(t["T_a"] - (T_in + dT)).max() < 1e-9, f"the wall table of {k[0]} {k[1]} carries the wall temperature")
Qk = sum(rh["walls"][k]["Q"] for k in keys)
ok(abs(Qk - b["walls"]) < 1e-9 * max(1.0, abs(Qk)), "the heat of the walls is the sum over the edges")
# the flux profile integrates to the reaction (consistent flux): the integral of q over the wall segments equals Q
tot = 0.0
for k in keys:
    t = rh["walls"][k]
    tot += float(np.sum(t["L"] * (t["q_a"] + 4.0 * t["q_m"] + t["q_b"]) / 6.0))
ok(abs(tot - Qk) < 1e-6 * abs(Qk), f"the heat flux along the walls integrates to the heat of the walls ({tot:.5g} against {Qk:.5g} W/m)")
# the leading (upstream) side loses less heat per area than the sides, the wake side the least - a body in a stream cools unevenly: the flux is not uniform
qs = np.concatenate([np.concatenate([rh["walls"][k]["q_a"], rh["walls"][k]["q_b"]]) for k in keys])
ok(qs.max() / max(qs.min(), 1e-12) > 1.5, f"the wall flux is not uniform (largest / smallest {qs.max() / max(qs.min(), 1e-12):.2f}): the stream cools the body unevenly")

# 4) linearity: ten times the temperature difference gives ten times the heat flux, and h is the same
r10 = ph.solve_temperature(mesh, res, heat({k: {"kind": "temp", "T": T_in + 10 * dT} for k in keys}))
ok(abs(r10["balance"]["walls"] / b["walls"] - 10.0) < 1e-6, f"ten times the temperature difference gives ten times the heat ({r10['balance']['walls'] / b['walls']:.6f})")
hh, _r = ph.heat_transfer_coefficient(mesh, res, heat({k: 0 for k in keys}), dT=1.0)
hh2, _r2 = ph.heat_transfer_coefficient(mesh, res, heat({k: 0 for k in keys}), dT=25.0)
dev = max(float(np.abs(hh[k][0] - hh2[k][0]).max()) for k in keys)
ok(dev < 1e-6 * max(float(np.abs(hh[k][0]).max()) for k in keys), "the heat transfer coefficient does not depend on the temperature difference")
hm = np.mean(np.concatenate([hh[k][0] for k in keys]))
ok(1.0 < hm < 100.0, f"the mean coefficient of this body in this stream is {hm:.1f} W/(m2 K) (a plausible number for air at 0.03 m/s)")

# 5) a heat flux: carried away exactly; a uniform flux of q on all walls
qf = 50.0
rf = ph.solve_temperature(mesh, res, heat({k: {"kind": "flux", "q": qf} for k in keys}))
perim = sum(float(rf["walls"][k]["L"].sum()) for k in keys)
ok(abs(rf["balance"]["walls"] - qf * perim) < 1e-9 * qf * perim, f"a flux of {qf:g} W/m2 on the walls puts in {rf['balance']['walls']:.5g} W/m (perimeter {perim:.5g} m: {qf * perim:.5g})")
ok(abs(rf["balance"]["relative"]) < 0.01, f"the flux is carried out by the flow (balance {100 * rf['balance']['relative']:.2g} % on this coarse mesh)")
ok(rf["Tmax"] > T_in + 0.1 and all(rf["walls"][k]["T_a"].min() > T_in for k in keys), f"the body surface is warmer than the stream ({rf['Tmax'] - T_in:.2f} K above it at the warmest)")

# 6) a wall temperature given as a function of position
f = lambda pts: T_in + 0.5 * pts[:, 0]                              # sketch units (mm): 0 .. 20 mm -> up to 10 K
rp = ph.solve_temperature(mesh, res, heat({k: {"kind": "temp", "T": f} for k in keys}))
k0 = keys[0]
pts = mesh["nodes"][np.asarray(mesh["wall_segs"][k0])[:, 0]]
ok(float(np.abs(rp["walls"][k0]["T_a"] - f(pts)).max()) < 1e-9, "a wall temperature given as a function of the position is taken at the nodes of the wall")

# 7) the profile helper: nearest segment, quadratic along it
vals = {k: (rh["walls"][k]["q_a"], rh["walls"][k]["q_m"], rh["walls"][k]["q_b"]) for k in keys}
prof = ph.WallProfile(mesh, keys, vals)
seg = np.asarray(mesh["wall_segs"][k0])[3]
pa, pb = mesh["nodes"][seg[0]], mesh["nodes"][seg[1]]
v, gap = prof.at([pa, 0.5 * (pa + pb), pb])
ref = rh["walls"][k0]
ok(gap.max() < 1e-9 and abs(v[0] - ref["q_a"][3]) < 1e-9 * abs(ref["q_a"][3]) + 1e-12 and abs(v[2] - ref["q_b"][3]) < 1e-9 * abs(ref["q_b"][3]) + 1e-12
   and abs(v[1] - ref["q_m"][3]) < 1e-9 * abs(ref["q_m"][3]) + 1e-12, "the wall profile returns the segment's values at its ends and its middle")
v2, gap2 = prof.at([pa + np.array([0.0, 0.3])])
ok(gap2[0] > 0.0, "and reports how far a point is from the wall it was taken from")

# 8) attach(): the flow result carries the temperature
ph.attach(res, rh)
ok("heat" in res and "T_a" in res["walls"][k0] and "q_b" in res["walls"][k0], "attach puts the temperature and the wall tables into the flow result")

# 8b) a thin plate along the stream against the classical laminar result: Nu_L = 0.664 Re_L^(1/2) Pr^(1/3)  (Pohlhausen, isothermal plate; both sides)
Lp, tp, Up = 40.0, 2.0, 0.08
mp, gp, meshp, resp, setp = flow_of(((0, 0), (Lp, 0), (Lp, tp), (0, tp)), Up, 1.5, 8.0, (0.6, 2.0, 0.8, 0.8), steps=400, cfl=3.0)
ok(resp["status"] == "converged", f"the flow along the plate: Re_L {resp['rho'] * Up * Lp * 1e-3 / resp['mu']:.0f} ({resp['status']}, {resp['steps']} steps)")
kp = list(meshp["wall_segs"].keys())
dTp = 20.0
rp2 = ph.solve_temperature(meshp, resp, heat({kk: {"kind": "temp", "T": T_in + dTp} for kk in kp}))
long_keys = []
for kk in kp:
    e = next(e for e in gp["edges"] if e["src"] == kk)
    if abs(math.dist(mp.pts[e["a"]], mp.pts[e["b"]]) - Lp) < 1e-9:
        long_keys.append(kk)
Qlong = sum(rp2["walls"][kk]["Q"] for kk in long_keys)
ReL = resp["rho"] * Up * Lp * 1e-3 / resp["mu"]
NuL = 0.664 * math.sqrt(ReL) * rp2["Pr"] ** (1.0 / 3.0)
Qexact = 2.0 * NuL * kair * dTp                                          # 2 sides x h L dT with h = Nu k / L
ratio = Qlong / Qexact
ok(len(long_keys) == 2 and 0.95 < ratio < 1.05, f"plate along the stream: the two long sides give {Qlong:.4g} W/m, Pohlhausen {Qexact:.4g} W/m (ratio {ratio:.3f}; the plate is 2 mm thick, not a sharp edge)")
ok(abs(rp2["balance"]["relative"]) < 0.01, f"and the plate's heat is carried out by the flow (balance {100 * rp2['balance']['relative']:.2g} % on this coarse mesh)")
ok(rp2["Tmin"] >= T_in - 1e-9 and rp2["Tmax"] <= T_in + dTp + 1e-9, "no temperature below the stream or above the plate")

# 9) mutation: a reaction of the wrong sign breaks the energy balance and the flux integral
orig_solve = ph.scalar_solve


def wrong_reaction(disc, A_, dn_, dv_, rhs_=None):
    T_, r_ = orig_solve(disc, A_, dn_, dv_, rhs_)
    return T_, -r_


ph.scalar_solve = wrong_reaction
try:
    rw = ph.solve_temperature(mesh, res, heat({k: {"kind": "temp", "T": T_in + dT} for k in keys}))
    ok(abs(rw["balance"]["relative"]) > 0.5, f"mutation: with the sign of the reaction reversed the energy balance is off by {100 * rw['balance']['relative']:.0f} % (the check can fail)")
finally:
    ph.scalar_solve = orig_solve

# 10) errors in words
for bad, text in ((dict(k=0.0), "conductivity"), (dict(T_in=-1.0), "inlet temperature")):
    h = heat({k: {"kind": "temp", "T": T_in + 5} for k in keys})
    h.update(bad)
    try:
        ph.solve_temperature(mesh, res, h)
        ok(False, f"a bad {text} is refused")
    except ph.HeatError as ex:
        ok(text in str(ex), f"a bad {text} is refused in words ('{ex}')")
try:
    ph.solve_temperature(mesh, res, heat({}, T_in=T_in) | {"walls": {}})
    ok(True, "no wall conditions is fine (the inlet fixes the temperature)")
except ph.HeatError:
    ok(False, "no wall conditions is fine (the inlet fixes the temperature)")

print("\nall passed" if not FAILS else f"\nFAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
