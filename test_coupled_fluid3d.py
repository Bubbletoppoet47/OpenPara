"""The heat exchange of a 3D fluid and a 3D solid (coupled_fluid3d; no Qt) with plain stand-in members whose answer is known: a plate whose wall meets a fluid with a film coefficient
h_f(x) (heat into the fluid  q = h_f (T_w - T_in)) and a solid that brings heat through the wall with a conductance k_s from a bulk at T_b:   k_s (T_b - T_w) = h_f (T_w - T_in), so
T_w = (k_s T_b + h_f T_in) / (k_s + h_f) at every point.  The two members mesh the plate differently, so the interpolation between the meshes is part of what is tested.
python test_coupled_fluid3d.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "coupled"), os.path.join(HERE, "shared")]
import numpy as np
import coupled_surface as cs
import coupled_fluid3d as cf
import coupled_check3d as cc3
import coupled_check

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


Fluid, Solid, exact_ = cc3.StandInFluid3D, cc3.StandInSolid3D, cc3.exact
plate = cc3.plate


def exact(fl, th):
    return exact_(fl, th)


# ------------------------------------------------------------------------------------------------------------------- the same mesh on both sides
print("-- one mesh on both sides")
fl, th = Fluid(5, c=0.3), Solid(5, lam=4.0)
ticks = []
r = cf.solve_fluid_thermal3d(fl, th, tick=lambda t, f: ticks.append((t, f)))
Tx = exact(fl, th)
ok(r["converged"] and r["mismatch"] <= r["tol"] == 0.01 and r["iterations"] >= 2, f"the loop converges: {r['iterations']} iterations, the two disagree on {r['mismatch'] * 100:.3f} % of the heat")
ok(np.abs(r["Tw"] - Tx).max() < 0.03 * np.ptp(Tx), f"the wall temperature is the known one at every node: {np.abs(r['Tw'] - Tx).max():.2e} K off (from {Tx.min():.2f} to {Tx.max():.2f} K)")
Qx = float(np.sum((fl.operator() @ (Tx - fl.T_in)) * fl.A))
ok(abs(r["Q_fluid"] - Qx) < 2e-2 * Qx and abs(r["Q_solid"] - Qx) < 2e-2 * Qx and abs(r["Q_rel"]) < 1e-2, f"the heat is the known one: fluid {r['Q_fluid']:.5f} W, solid {r['Q_solid']:.5f} W, known {Qx:.5f} W")
iso = fl.operator() @ np.ones(25)
ok(np.allclose(r["h"], iso, rtol=1e-9) and np.allclose(r["h_lin"], r["h"]) and abs(r["h_max"] - iso.max()) < 1e-9, "the coefficient found by the pass at a constant wall temperature is the flux for 1 K")
ok(fl.calls["flow"] == 1, "the flow is solved once (it does not depend on the temperature)")
ok(fl.calls["temp"] == r["iterations"] + 1, f"the temperature of the fluid is solved once for the coefficient and once per iteration ({fl.calls['temp']})")
ok(r["keys"] == [3] and th.fids == [3], "the faces of the exchange are handed to the solid")
ok(r["wall_points"] == 25 and len(r["Tw"]) == 25 and len(r["q_wall"]) == 25, "the answer is given at the wall nodes of the fluid")
ok(r["T_in"] == 293.15 and r["flow"]["status"] == "converged" and r["heat"]["Pr"] == 0.71, "the flow and heat summaries of the fluid are passed on")
ok(len(r["history"]) == r["iterations"] and all(h["mismatch"] >= 0 and h["omega"] > 0 for h in r["history"]) and r["history"][-1]["mismatch"] == r["mismatch"], "the history has one row per iteration")
ok(r["history"][-1]["mismatch"] < r["history"][0]["mismatch"], f"and the disagreement falls ({r['history'][0]['mismatch']:.3g} to {r['history'][-1]['mismatch']:.3g})")
ok(abs(r["history"][-1]["Tw_max"] - r["Tw"].max()) < 1e-12 and abs(r["history"][-1]["Tw_min"] - r["Tw"].min()) < 1e-12, "the history keeps the range of the wall temperature")
ok(r["gap_fluid"] < 1e-9 and r["gap_solid"] == 0.0, "no gap between the surfaces when they are the same")
ok(ticks and ticks[0][1] < ticks[-1][1] <= 1.0 and all(isinstance(t, str) and t for t, _f in ticks), f"progress is reported in words and rises ({len(ticks)} messages)")
ok(any("iteration 1" in t for t, _f in ticks) and any("heat transfer coefficient" in t for t, _f in ticks), "the messages name the step")

print("-- a fluid that is local needs one pass")
fl, th = Fluid(5), Solid(5)
r = cf.solve_fluid_thermal3d(fl, th)
Tx = exact(fl, th)
ok(r["converged"] and r["iterations"] == 1 and np.abs(r["Tw"] - Tx).max() < 1e-9, f"a fluid whose flux depends on the wall temperature of the same node only: the first pass is the answer ({np.abs(r['Tw'] - Tx).max():.1e} K off)")

print("-- another temperature, another conductance")
for k_s, T_b, lam in ((1.0, 373.15, 2.0), (500.0, 303.15, 0.5), (10.0, 293.15, 4.0)):
    fl, th = Fluid(5, c=0.3), Solid(5, k_s, T_b, lam=lam)
    r = cf.solve_fluid_thermal3d(fl, th)
    Tx = exact(fl, th)
    ok(r["converged"] and np.abs(r["Tw"] - Tx).max() < 0.03 * max(np.ptp(Tx), 1.0) + 1e-6, f"k_s {k_s:g}, bulk {T_b - 273.15:.0f} C: converged in {r['iterations']}, {np.abs(r['Tw'] - Tx).max():.2e} K off")
ok(abs(r["Q_fluid"]) < 1e-9 and r["converged"], "a solid at the temperature of the fluid exchanges no heat")

# ------------------------------------------------------------------------------------------------------------------- different meshes
print("-- two different meshes")
ref = cf.solve_fluid_thermal3d(Fluid(7, c=0.3), Solid(7))
for ns in (4, 11):
    fl, th = Fluid(7, c=0.3), Solid(ns)
    r = cf.solve_fluid_thermal3d(fl, th)
    err = np.abs(r["Tw"] - ref["Tw"]).max()
    ok(r["converged"] and err < 0.03 * np.ptp(ref["Tw"]), f"a solid of {ns} x {ns} nodes against a fluid of 7 x 7: the wall temperature is within {err:.3f} K of {np.ptp(ref['Tw']):.2f} K of the run on one mesh ({r['iterations']} iterations)")
    ok(abs(r["Q_rel"]) < r["q_tol"], f"the heat leaving the solid and the heat entering the fluid differ by {r['Q_rel'] * 100:.2f} % (limit {r['q_tol'] * 100:.0f} %)")

print("-- gaps are counted")
fl, th = Fluid(5), Solid(5, offset=0.4)
r = cf.solve_fluid_thermal3d(fl, th)
hh = cs.SurfaceLocator(fl.P, fl.T).h
ok(abs(r["gap_fluid"] - 0.4 / hh) < 1e-9, f"the solid asked 0.4 mm off the wall of a fluid whose elements are {hh:.2f} mm: the gap is {r['gap_fluid']:.3f} element sizes")
th = Solid(5, gap=0.7)
r = cf.solve_fluid_thermal3d(Fluid(5), th)
ok(abs(r["gap_solid"] - 0.7) < 1e-12, "the gap of the solid's wall is the worst one it reported")

# ------------------------------------------------------------------------------------------------------------------- the linearisation
print("-- the linearisation does not change the answer")
fl, th = Fluid(5, hf=lambda P: np.where((P[:, 0] < 1e-9) & (P[:, 1] < 1e-9), 0.01, 5.0 + P[:, 0]), c=0.3), Solid(5, lam=4.0)
r = cf.solve_fluid_thermal3d(fl, th)
ok(r["h_lin"].min() > r["h"].min() and r["h_lin"].min() > 0.05 * np.abs(r["h"]).mean() - 1e-12, f"a node with almost no film coefficient is linearised with a floor ({r['h_lin'].min():.3g} against {r['h'].min():.3g} W/m2K)")
Tx = exact(fl, th)
Qx = float(np.sum((fl.operator() @ (Tx - fl.T_in)) * fl.A))
ok(r["converged"] and abs(r["Q_fluid"] - Qx) < 0.02 * Qx, f"and the loop still ends at the known heat ({r['Q_fluid']:.5f} W against {Qx:.5f} W)")
fl, th = Fluid(5, hf=lambda P: 2000.0 + 100 * P[:, 1], c=0.3), Solid(5, 3.0, lam=1.0)
r = cf.solve_fluid_thermal3d(fl, th)
Tx = exact(fl, th)
ok(r["converged"] and np.abs(r["Tw"] - Tx).max() < 1e-3, f"a fluid that takes the heat away much faster than the solid brings it: the wall stays near the fluid ({r['Tw'].mean() - 293.15:.3f} K above it)")
r2 = cf.solve_fluid_thermal3d(Fluid(5, c=0.3), Solid(5, lam=4.0), {"conj_max": 1})
ok(not r2["converged"] and r2["iterations"] == 1 and r2["mismatch"] > r2["tol"], "one iteration is not enough: not converged, and the result says so")
r3 = cf.solve_fluid_thermal3d(Fluid(5, c=0.3), Solid(5, lam=4.0), {"conj_tol": 1e-5, "conj_max": 60})
r0 = cf.solve_fluid_thermal3d(Fluid(5, c=0.3), Solid(5, lam=4.0))
ok(r3["converged"] and r3["mismatch"] <= 1e-5 and r3["iterations"] > r0["iterations"], f"a tighter limit takes more iterations ({r3['iterations']} against {r0['iterations']})")

# ------------------------------------------------------------------------------------------------------------------- refusals
print("-- what the loop refuses, in words")
for fl, th, want in ((Fluid(5, keys=()), Solid(5), "Wall of the thermal analysis"),
                     (Fluid(5, hf=lambda P: np.zeros(len(P))), Solid(5), "zero everywhere")):
    try:
        cf.solve_fluid_thermal3d(fl, th)
        ok(False, f"'{want}' was not refused")
    except cf.FluidThermalError as ex:
        ok(want in str(ex), f"refused: '{str(ex)[:100]}'")
fl = Fluid(5)
fl.A = np.zeros_like(fl.A)
try:
    cf.solve_fluid_thermal3d(fl, Solid(5))
    ok(False, "a wall without area was not refused")
except cf.FluidThermalError as ex:
    ok("no mesh" in str(ex), f"a wall with no area is refused: '{str(ex)[:90]}'")

print("-- the stand-ins are the ones of the self-check")
rows = cc3.rows_fluid3d()
ok(len(rows) >= 18 and all(r["ok"] for r in rows), f"the rows of the self-check for a 3D flow pass ({sum(r['ok'] for r in rows)} of {len(rows)})")
ok(all(set(r) == {"name", "expected", "got", "ok"} for r in rows) and len({r["name"] for r in rows}) == len(rows), "every row has a name, an expected and a found value, and the names differ")
full = coupled_check.run()
names = {r["name"] for r in full["rows"]}
ok(all(r["name"] in names for r in rows) and full["ok"], f"the self-check of Coupled Physics includes them ({len(full['rows'])} rows in all, all pass)")
# the rows must be able to fail: a stand-in solid that lies about its heat, a loop with a wrong answer
fl, th = Fluid(5, c=0.3), Solid(5, lam=4.0)
th.heat_to_fluid = lambda: 2.0 * float(np.sum(th.q * th.A))
import coupled_engine as ce
r = ce.solve_coupled({"fluid": fl, "thermal": th}, {"conj_tol": 1e-8, "conj_max": 60})
ok(not r["ok"] and any(c["name"].startswith("Heat leaving the solid") and not c["ok"] for c in r["checks"]), "mutation: a solid that reports twice its heat makes the coupled solve fail")
fl = Fluid(5, c=0.3, sign=-1.0)
r = None
try:
    r = ce.solve_coupled({"fluid": fl, "thermal": Solid(5, lam=4.0)}, {"conj_tol": 1e-8, "conj_max": 8})
except ce.CoupledError as ex:
    r = ex
ok(isinstance(r, ce.CoupledError) or not r["ok"], "mutation: a fluid whose heat flux has the wrong sign does not give an accepted answer")

print("-- the field of the wall")
P, T, A = plate(4)
wf = cf.WallField({"points": P, "tris": T})
v, d = wf.at(2.0 + P[:, 0] - 3.0 * P[:, 1], P + [0.0, 0.0, 0.5])
ok(np.allclose(v, 2.0 + P[:, 0] - 3.0 * P[:, 1]) and np.allclose(d, 0.5), "a linear field is read back exactly at the nodes, 0.5 mm away from the wall")
Q = np.array([[1.234, 5.678, 0.0], [9.99, 0.01, 0.0]])
v, d = wf.at(2.0 + P[:, 0] - 3.0 * P[:, 1], Q)
ok(np.allclose(v, 2.0 + Q[:, 0] - 3.0 * Q[:, 1]) and d.max() < 1e-12, "and at any point of the wall")
v, d = wf.at(np.arange(len(P), dtype=float), np.array([[50.0, 50.0, 0.0]]))
ok(0 <= v[0] <= len(P) - 1 and d[0] > 30, "a point far outside the wall gets a value from inside the range of the field, and a big gap")

print("\nFAILED:", FAILS) if FAILS else print("\nOK coupled fluid3d")
sys.exit(1 if FAILS else 0)
