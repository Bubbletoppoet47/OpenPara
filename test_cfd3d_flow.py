"""cfd3d_flow.py and cfd3d_mesh.py against closed-form answers: the mesh itself (volumes, patches, outward area vectors), the boundary conditions, a uniform
flow reproduced exactly, plane Poiseuille flow (pressure gradient, centre-line speed, wall force), Poiseuille flow in a round pipe, the mass balance, a
uniform temperature, the energy balance with a heat flux on the walls, a cube in a channel (convergence with the mesh, the force from the reactions against
the force from the surface, the energy balance), the air around a real part (the faces matched to the part's faces), and the refusals.
python test_cfd3d_flow.py"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "cfd3d"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg
import cfd3d_flow as cf
import cfd3d_mesh as cm

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b_, rel, what):
    err = abs(a - b_) / max(abs(b_), 1e-300)
    ok(err <= rel, f"{what}: {a:.6g} against {b_:.6g} ({err * 100:.3f} %, limit {rel * 100:g} %)")


def raises(fn, text, what):
    try:
        fn()
    except cf.FlowError as ex:
        ok(text.lower() in str(ex).lower(), f"{what}: refused with '{ex}'")
        return
    except Exception as ex:                                    # noqa: BLE001
        ok(False, f"{what}: raised {type(ex).__name__}: {ex}")
        return
    ok(False, f"{what}: was not refused")


T0 = time.time()
L, W, H = 4.0, 1.0, 1.0
NU, U = 0.1, 1.0


def poiseuille(pts):
    z = pts[:, 2] / H
    out = np.zeros((len(pts), 3))
    out[:, 0] = 6.0 * U * z * (1.0 - z)
    return out


def channel_spec(**kw):
    s = {"lscale": 1.0, "nu": NU, "rho": 1.0, "inlet": {"x-": poiseuille}, "outlet": ["x+"], "slip": ["y-", "y+"], "wall": ["z-", "z+"]}
    s.update(kw)
    return s


def slab(res, x0, tol):
    return np.abs(res["disc"].x[:, 0] - x0) < tol


# ------------------------------------------------------------------------------------------------------------------- the mesh
print("-- the mesh")
q = cm.channel(L, W, H, 0.125)
d = cf.Disc(q["nodes"], q["tets"], 1.0)
near(d.V.sum(), L * W * H, 1e-9, "the volume of the tetrahedra is the volume of the box")
ok(set(q["patches"]) == {"x-", "x+", "y-", "y+", "z-", "z+"}, "the six faces of the box are patches")
bd = cf.Boundary(d, q, channel_spec())
tot = np.zeros(3)
for nm in q["patches"]:
    tot += bd.faces(nm)[1].sum(axis=0)
ok(np.abs(tot).max() < 1e-12, f"the outward area vectors of the whole boundary add up to zero ({np.abs(tot).max():.1e})")
areas = {nm: bd.area(nm) for nm in q["patches"]}
near(areas["x-"], W * H, 1e-9, "the inlet area")
near(areas["z+"], L * W, 1e-9, "the area of a long face")
ok(all(np.dot(bd.faces(nm)[1].sum(axis=0), n) > 0 for nm, n in (("x-", [-1, 0, 0]), ("x+", [1, 0, 0]), ("y-", [0, -1, 0]), ("z+", [0, 0, 1]))),
   "the area vectors point out of the domain")
ok((d.V > 0).all(), "every tetrahedron has a positive volume")

# ------------------------------------------------------------------------------------------------------------------- a uniform flow is reproduced exactly
print("-- a uniform flow")
spec = {"lscale": 1.0, "nu": NU, "rho": 1.0, "inlet": {"x-": [1.0, 0, 0]}, "outlet": ["x+"], "slip": ["y-", "y+", "z-", "z+"]}
res = cf.solve_flow(q, spec)
ok(res["status"] == "converged", f"converged in {res['steps']} steps")
ok(np.abs(res["u"] - [1.0, 0, 0]).max() < 1e-5, f"the velocity is uniform to the steady-state tolerance ({np.abs(res['u'] - [1.0, 0, 0]).max():.1e})")
ok(np.abs(res["p"]).max() < 1e-5, f"the pressure is zero to the same tolerance ({np.abs(res['p']).max():.1e})")
near(res["mass"]["in"], W * H, 1e-9, "the flow rate that comes in")

# ------------------------------------------------------------------------------------------------------------------- plane Poiseuille flow
print("-- plane Poiseuille flow (the developed profile on the inflow)")
spec = channel_spec()
t = time.time()
res = cf.solve_flow(q, spec)
ok(res["status"] == "converged", f"converged in {res['steps']} steps ({time.time() - t:.1f} s, {res['unknowns']} unknowns, {res['solver']})")
x, y, z = res["disc"].x.T
u, p = res["u"], res["p"]
ok(np.abs(u[np.isin(np.arange(len(x)), res["boundary"].wall_nodes)]).max() == 0.0, "the velocity is exactly zero on the no-slip walls")
sl = np.concatenate([res["boundary"].nodes_of["y-"], res["boundary"].nodes_of["y+"]])
ok(np.abs(u[sl[~np.isin(sl, res["boundary"].wall_nodes)], 1]).max() == 0.0, "the velocity normal to a slip wall is exactly zero")
ok(np.abs(p[res["boundary"].outlet_nodes]).max() == 0.0, "the pressure is exactly zero on the outlet")
near(res["mass"]["in"], U * W * H * 0.9994, 0.02, "the flow rate that comes in (the profile is zero at the corners)")
ok(res["mass"]["mismatch"] < 0.02, f"mass balance: in {res['mass']['in']:.5f}, out {res['mass']['out']:.5f} m3/s ({res['mass']['mismatch'] * 100:.2f} %)")
m1, m2 = np.abs(x - 1.0) < 0.05, np.abs(x - 3.0) < 0.05
dpdx = (p[m2].mean() - p[m1].mean()) / 2.0
near(dpdx, -12.0 * NU * U / H ** 2, 0.03, "the pressure gradient, -12 nu U / H^2")
near(u[slab(res, 2.0, 0.05), 0].max(), 1.5 * U, 0.04, "the speed on the centre line, 1.5 U")
F = cf.wall_force(res, ["z-", "z+"])
near(F["total"][0], 12.0 * NU * U / H ** 2 * L * W * H, 0.03, "the drag on the two walls, dp/dx L W H")
ok(abs(F["total"][2]) < 0.01 * F["total"][0] and abs(F["total"][1]) < 0.01 * F["total"][0], f"the two walls push each other away with the same force across the channel (net {F['total'][2]:.1e}, {F['total'][1]:.1e})")
ok(abs(F["pressure"][0]) < 0.05 * abs(F["total"][0]), "the pressure does not push the walls along (it acts across them)")
near(cf.wall_force(res, ["z-"])["total"][0], F["total"][0] / 2.0, 0.02, "each wall carries half of it")

# ------------------------------------------------------------------------------------------------------------------- round pipe
print("-- Poiseuille flow in a round pipe")
R, LP = 0.5, 4.0


def pipe_profile(pts):
    out = np.zeros((len(pts), 3))
    out[:, 0] = 2.0 * U * np.maximum(1.0 - (pts[:, 1] ** 2 + pts[:, 2] ** 2) / R ** 2, 0.0)
    return out


qp = cm.pipe(R, LP, 0.1)
resp = cf.solve_flow(qp, {"lscale": 1.0, "nu": NU, "rho": 1.0, "inlet": {"inlet": pipe_profile}, "outlet": ["outlet"], "wall": ["wall"]})
ok(resp["status"] == "converged", f"converged in {resp['steps']} steps ({len(qp['nodes'])} nodes)")
xp = resp["disc"].x[:, 0]
dpp = (resp["p"][np.abs(xp - 3.0) < 0.04].mean() - resp["p"][np.abs(xp - 1.0) < 0.04].mean()) / 2.0
near(dpp, -8.0 * NU * U / R ** 2, 0.06, "the pressure gradient, -8 mu U / R^2 (5 elements across the radius)")
Fp = cf.wall_force(resp, ["wall"])["total"]
near(Fp[0], 8.0 * NU * U / R ** 2 * LP * np.pi * R ** 2, 0.07, "the drag on the pipe wall, dp/dx L pi R^2")
ok(abs(Fp[1]) < 0.01 * abs(Fp[0]) and abs(Fp[2]) < 0.01 * abs(Fp[0]), "no sideways force on the pipe wall")
ok(resp["mass"]["mismatch"] < 0.05, f"mass balance in the pipe ({resp['mass']['mismatch'] * 100:.2f} %)")

# ------------------------------------------------------------------------------------------------------------------- the temperature
print("-- the temperature")
res_t = cf.solve_flow(q, channel_spec(heat=True, k=0.2, cp=1.0, T_in=5.0, wall_T={"z-": 5.0, "z+": 5.0}))
ok(np.abs(res_t["T"] - 5.0).max() < 1e-9, f"a fluid at the temperature of its walls stays there ({np.abs(res_t['T'] - 5.0).max():.1e})")
ok(abs(res_t["energy"]["walls"]) < 1e-9, "and no heat flows")
Q, QHEAT = 1.0, 2.0                                                    # W/m2 into the fluid through each of the two walls
res_q = cf.solve_flow(q, channel_spec(heat=True, k=0.2, cp=1.0, T_in=0.0, wall_q={"z-": QHEAT, "z+": QHEAT}))
en = res_q["energy"]
ok(en["mismatch"] < 0.03, f"energy balance: the walls gave {en['walls']:.5f} W, the fluid carries {en['gain']:.5f} W away ({en['mismatch'] * 100:.2f} %)")
near(res_q["heat"]["flux_in"], QHEAT * 2 * L * W, 1e-9, "the heat flux times the area of the two walls")
res_k = cf.solve_flow(q, channel_spec(heat=True, k=0.2, cp=1.0, T_in=300.0, wall_q={"z-": QHEAT, "z+": QHEAT}))
ok(abs(res_k["energy"]["T_ref"] - 300.0) < 1e-9 and abs(en["T_ref"]) < 1e-9, f"the enthalpy is counted from the inflow temperature ({res_k['energy']['T_ref']:g} K and {en['T_ref']:g} K here)")
near(res_k["energy"]["gain"], en["gain"], 1e-4, "the heat carried away is the same at 300 degrees higher (a mass balance that is 1.5 % off must not leak 300 degrees of it)")
inlet_heat = cf.patch_heat(res_q, "x-")
ok(-0.15 * QHEAT * 2 * L * W < inlet_heat < 0.0, f"a little heat is conducted back out through the inflow ({inlet_heat:.3f} W of {QHEAT * 2 * L * W:g}): the flow is slow enough (Peclet 5) for that")
tri_o = res_q["boundary"].patches["x+"]
av_o = res_q["boundary"].faces("x+")[1]
mixed = cf._face_product(av_o, tri_o, res_q["T"], res_q["u"]).sum() / cf._face_product(av_o, tri_o, np.ones(len(res_q["T"])), res_q["u"]).sum()
near(mixed, en["walls"] / (res_q["mass"]["out"] * 1.0 * 1.0), 0.03, "the mixed-cup temperature at the outlet is the heat divided by m cp")
ok(res_q["T"].min() > -0.05 * mixed, f"no large undershoot of the temperature (lowest {res_q['T'].min():.4f}, mixed outlet {mixed:.4f})")

# ------------------------------------------------------------------------------------------------------------------- a cube in a channel
print("-- a cube in a channel (Re 10)")
body = ["b-x", "b+x", "b-y", "b+y", "b-z", "b+z"]
results = []
for h, hn in ((0.3, 0.12), (0.2, 0.08)):
    qc = cm.channel(5.0, 2.0, 2.0, h, hole=(1.8, 1.0, 1.0, 0.5), h_near=hn)
    spec = {"lscale": 1.0, "nu": 0.05, "rho": 1.0, "inlet": {"x-": [1.0, 0, 0]}, "outlet": ["x+"], "slip": ["y-", "y+", "z-", "z+"], "wall": body,
            "heat": True, "k": 0.05, "cp": 1.0, "T_in": 0.0, "wall_T": {nm: 1.0 for nm in body}}
    t = time.time()
    rc = cf.solve_flow(qc, spec)
    Fc = cf.wall_force(rc, body)
    results.append((len(qc["nodes"]), rc, Fc))
    ok(rc["status"] == "converged", f"{len(qc['nodes'])} nodes: converged in {rc['steps']} steps ({time.time() - t:.1f} s)")
    ok(rc["mass"]["mismatch"] < 0.01, f"{len(qc['nodes'])} nodes: mass balance ({rc['mass']['mismatch'] * 100:.3f} %)")
    ok(abs(Fc["total"][1]) < 0.02 * Fc["total"][0] and abs(Fc["total"][2]) < 0.02 * Fc["total"][0], f"{len(qc['nodes'])} nodes: the symmetric flow pushes the cube only along the flow")
    # the same force from the surface: the pressure and the shear from the gradient of the velocity of the element at the face
    bdc, dc = rc["boundary"], rc["disc"]
    fs = np.zeros(3)
    for nm in body:
        ie, av = bdc.faces(nm)
        gu = np.einsum("tjk,tjc->tck", dc.g[ie], rc["u"][dc.tets[ie]])
        mu = rc["nu"] * rc["rho"]
        fs += (rc["p"][bdc.patches[nm]].mean(axis=1)[:, None] * av).sum(axis=0) - mu * (np.einsum("tck,tk->tc", gu, av) + np.einsum("tkc,tk->tc", gu, av)).sum(axis=0)
    near(Fc["total"][0], fs[0], 0.15, f"{len(qc['nodes'])} nodes: the force from the reactions against the force from the surface (the surface one is the cruder)")
    en = rc["energy"]
    ok(en["mismatch"] < 0.10, f"{len(qc['nodes'])} nodes: energy balance ({en['mismatch'] * 100:.2f} %, walls {en['walls']:.4f} W, carried away {en['gain']:.4f} W)")
(n1, r1, F1), (n2, r2, F2) = results
near(F1["total"][0], F2["total"][0], 0.15, "the drag on the cube changes by less than 15 % from the coarse to the fine mesh")
e1, e2 = r1["energy"]["mismatch"], r2["energy"]["mismatch"]
ok(e2 < e1, f"the energy mismatch falls with the mesh ({e1 * 100:.1f} % to {e2 * 100:.1f} %)")
hq = sum(cf.patch_heat(r2, nm) for nm in body)
near(hq, r2["heat"]["node_heat"][np.unique(np.concatenate([r2["boundary"].nodes_of[nm] for nm in body]))].sum(), 1e-9, "the heat of the patches adds up to the heat of the cube's nodes")
ok(hq > 0, f"the cube heats the fluid ({hq:.4f} W)")

# ------------------------------------------------------------------------------------------------------------------- the air around a real part
print("-- the air around a part")
part = b.Box(10, 10, 10)
geom = sg.analyze(part, None)
lo, hi = [-25.0, -15.0, -15.0], [45.0, 15.0, 15.0]
t = time.time()
qa = cm.air_domain(geom, lo, hi, 2.5, 6.0, 1.3)
da = cf.Disc(qa["nodes"], qa["tets"], 1e-3)
near(da.V.sum(), 70 * 30 * 30 * 1e-9 - 1000e-9, 1e-6, f"the air has the volume of the box less the part ({len(qa['nodes'])} nodes, {time.time() - t:.1f} s)")
ok(set(qa["patches"]) == {"x-", "x+", "y-", "y+", "z-", "z+", 0, 1, 2, 3, 4, 5}, f"the patches are the box faces and the six faces of the part ({sorted(map(str, qa['patches']))})")
bda = cf.Boundary(da, qa, {"nu": 1e-3, "inlet": {"x-": [0.1, 0, 0]}, "outlet": ["x+"], "slip": ["y-", "y+", "z-", "z+"], "wall": [0, 1, 2, 3, 4, 5]})
for fid in range(6):
    near(bda.area(fid) * 1e6, geom["faces"][fid]["area"], 1e-9, f"face {fid} of the part has its own area")
    n_part = np.array(geom["faces"][fid]["normal"])
    n_air = bda.faces(fid)[1].sum(axis=0)
    ok(np.dot(n_air, n_part) < 0, f"the area vector of face {fid} points into the part (out of the air)")
spec = {"lscale": 1e-3, "nu": 2e-4, "rho": 1.2, "inlet": {"x-": [0.2, 0, 0]}, "outlet": ["x+"], "slip": ["y-", "y+", "z-", "z+"], "wall": [0, 1, 2, 3, 4, 5],
        "heat": True, "k": 0.24, "cp": 1005.0, "T_in": 293.15, "wall_T": {fid: 323.15 for fid in range(6)}}      # Prandtl number 1, so that the heat is as well resolved as the flow
t = time.time()
ra = cf.solve_flow(qa, spec)
ok(ra["status"] == "converged", f"the flow past the cube converged in {ra['steps']} steps ({time.time() - t:.1f} s)")
Fa = cf.wall_force(ra, [0, 1, 2, 3, 4, 5])["total"]
ok(Fa[0] > 0 and abs(Fa[1]) < 0.03 * Fa[0] and abs(Fa[2]) < 0.03 * Fa[0], f"the air pushes the part along the flow ({Fa[0]:.3e} N, sideways {abs(Fa[1]):.1e}, {abs(Fa[2]):.1e})")
under = 293.15 - ra["T_range"][0]
ok(under < 0.08 * 30.0 and ra["T_range"][1] < 323.15 + 0.6, f"the air is between the inflow and the wall temperature, to 8 % of the range on this coarse mesh (below the inflow by {under:.2f} K)")
ok(ra["energy"]["mismatch"] < 0.15, f"energy balance around the part ({ra['energy']['mismatch'] * 100:.1f} %)")
qa2 = cm.air_domain(geom, lo, hi, 1.6, 5.0, 1.3)
t = time.time()
ra2 = cf.solve_flow(qa2, spec)
Fa2 = cf.wall_force(ra2, [0, 1, 2, 3, 4, 5])["total"]
ok(ra2["status"] == "converged", f"{len(qa2['nodes'])} nodes: converged in {ra2['steps']} steps ({time.time() - t:.1f} s)")
under2 = 293.15 - ra2["T_range"][0]
ok(under2 < 0.5 * under, f"a finer mesh shrinks the undershoot of the temperature ({under:.2f} K to {under2:.2f} K)")
ok(ra2["energy"]["mismatch"] < ra["energy"]["mismatch"], f"and the energy mismatch ({ra['energy']['mismatch'] * 100:.1f} % to {ra2['energy']['mismatch'] * 100:.1f} %)")
near(Fa2[0], Fa[0], 0.30, "the drag on the part: coarse against fine mesh (a first-order method: it still moves with the mesh)")
near(ra2["energy"]["walls"], ra["energy"]["walls"], 0.20, "the heat from the part: coarse against fine mesh")

# ------------------------------------------------------------------------------------------------------------------- the options of the air mesh
print("-- the options of the air mesh")
cyl = sg.analyze(b.Cylinder(5, 12), None)
lo_c, hi_c = [-30.0, -20.0, -20.0], [50.0, 20.0, 20.0]
side = max(cyl["faces"], key=lambda f: f["area"])["id"]
plain = cm.air_domain(cyl, lo_c, hi_c, 2.5, 7.0, 1.3)
curved = cm.air_domain(cyl, lo_c, hi_c, 2.5, 7.0, 1.3, curv=24)
local = cm.air_domain(cyl, lo_c, hi_c, 2.5, 7.0, 1.3, curv=24, face_sizes=[{"fids": [side], "h": 1.0}])
ok(len(curved["patches"][side]) > 2 * len(plain["patches"][side]), f"curvature refinement: the curved face gets {len(curved['patches'][side])} surface triangles instead of {len(plain['patches'][side])}")
ok(len(local["patches"][side]) > 1.4 * len(curved["patches"][side]), f"a local size on a face makes it finer ({len(curved['patches'][side])} to {len(local['patches'][side])} surface triangles)")
ends = [f["id"] for f in cyl["faces"] if f["id"] != side]
ok(all(len(local["patches"][e]) >= len(curved["patches"][e]) for e in ends), "and the other faces get no coarser")
fine = cm.air_domain(cyl, lo_c, hi_c, 2.5, 7.0, 1.3, hmin=2.0)
ok(len(fine["nodes"]) > 0 and cf.Disc(fine["nodes"], fine["tets"], 1e-3).h.min() > 0, "a minimum element size is accepted")
nofaces = dict(cyl, faces=[])
lost = cm.air_domain(nofaces, lo_c, hi_c, 2.5, 7.0, 1.3)
ok(len(lost["unmatched"]) == 3 and all(n in lost["patches"] for n in lost["unmatched"]), f"surfaces that cannot be matched to a face become patches of their own ({lost['unmatched']})")
bdl = cf.Boundary(cf.Disc(lost["nodes"], lost["tets"], 1e-3), lost, {"nu": 1e-3, "inlet": {"x-": [0.1, 0, 0]}, "outlet": ["x+"], "slip": ["y-", "y+", "z-", "z+"], "wall": lost["unmatched"]})
ok(sum(bdl.area(n) for n in lost["unmatched"]) > 0, "and they can be walls")
raises(lambda: cm.air_domain(cyl, lo_c, hi_c, 8.0, 2.0, 1.3), "must be positive", "a size on the part larger than the one far away")

# ------------------------------------------------------------------------------------------------------------------- the refusals
print("-- the refusals")
raises(lambda: cf.solve_flow(q, channel_spec(outlet=[])), "no outlet", "no outlet")
raises(lambda: cf.solve_flow(q, channel_spec(inlet={})), "no inlet", "no inlet")
raises(lambda: cf.solve_flow(q, channel_spec(outlet=["nothing"])), "no boundary patch 'nothing'", "an unknown patch")
raises(lambda: cf.solve_flow(q, channel_spec(wall=["z-", "z+", "x+"])), "used twice", "a patch with two roles")
raises(lambda: cf.solve_flow(q, channel_spec(inlet={"x-": [0, 0, 0]})), "no speed", "an inflow without speed")
raises(lambda: cf.solve_flow(q, channel_spec(nu=0.0)), "viscosity", "no viscosity")
raises(lambda: cf.solve_flow(q, channel_spec(heat=True, k=0.0, cp=1.0)), "conductivity", "no conductivity")
raises(lambda: cf.wall_force(res, ["nothing"]), "no boundary patch", "the force on an unknown patch")
try:
    cf.solve_flow(q, channel_spec(), cancel=lambda: True)
    ok(False, "a cancelled solve was not stopped")
except cf.Cancelled:
    ok(True, "a cancelled solve stops")

# ------------------------------------------------------------------------------------------------------------------- the iterative solver
print("-- the iterative solver (GMRES with an incomplete LU)")
t = time.time()
res_i = cf.solve_flow(q, channel_spec(), direct_limit=1000)
ok(res_i["solver"] == "gmres+ilu" and res_i["status"] == "converged", f"{res_i['solver']}, {res_i['status']} in {res_i['steps']} steps ({time.time() - t:.1f} s)")
ok(np.abs(res_i["u"] - res["u"]).max() < 1e-4, f"it gives the same flow as the direct solver ({np.abs(res_i['u'] - res['u']).max():.1e} m/s apart)")

print(f"\n{len(FAILS)} failed, {time.time() - T0:.0f} s")
for f in FAILS:
    print("   FAIL:", f)
sys.exit(1 if FAILS else 0)
