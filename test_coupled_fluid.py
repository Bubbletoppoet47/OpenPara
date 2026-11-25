"""The fluid <-> solid heat exchange loop (coupled_fluid.py) on stand-in analyses with a known answer: a wall of N nodes, a solid that holds it at a given temperature through a
conductance and conducts along it, a fluid whose heat flux depends on the whole wall temperature (a non-local operator, like the real one).  The loop's answer must be the one of
the two problems written as ONE linear system, whatever the heat transfer coefficient it linearises with; and the checks that must fail when something is wrong must fail.
python test_coupled_fluid.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "coupled"), HERE]
import numpy as np

import coupled_fluid as cf

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


from coupled_check import KEY, StandInFluid, StandInSolid, reference                 # (the stand-ins are those of the self-check)


def run(fl, so, **opt):
    return cf.solve_fluid_thermal(fl, so, opt)


N = 41
T_in = 300.0
x = np.linspace(0, 1, N)

# ------------------------------------------------------------------------------------------------------ 1. the loop reaches the one-system answer
for name, T_hot in (("a uniform hot side", 400.0), ("a hot side that varies along the wall", 330.0 + 120.0 * np.sin(np.pi * x) ** 2)):
    fl, so = StandInFluid(N, 25.0, 3.0, T_in), StandInSolid(N, 40.0, 5.0, T_hot)
    out = run(fl, so, conj_tol=1e-8, conj_max=60)
    ref = reference(fl, so)
    err = float(np.abs(so.T - ref).max()) / float(ref.max() - T_in)
    ok(out["converged"] and err < 1e-6, f"{name}: the loop gives the one-system answer (error {err:.1e} of the temperature rise) in {out['iterations']} iterations")
    ok(abs(out["Q_rel"]) < 1e-9 + 1e-3, f"{name}: the heat that leaves the solid is the heat the fluid takes ({out['Q_solid']:.6g} W, {out['Q_fluid']:.6g} W)")
    ok(out["gap_fluid"] == 0.0 and out["gap_solid"] == 0.0, f"{name}: every wall point found its place on the other side")

# ------------------------------------------------------------------------------------------------------ 2. the linearisation only sets the speed, not the answer
T_hot = 330.0 + 120.0 * np.sin(np.pi * x) ** 2
counts = {}
for bias in (0.3, 1.0, 3.0):
    fl, so = StandInFluid(N, 25.0, 3.0, T_in, h_bias=bias), StandInSolid(N, 40.0, 5.0, T_hot)
    out = run(fl, so, conj_tol=1e-8, conj_max=200)
    err = float(np.abs(so.T - reference(fl, so)).max()) / 100.0
    counts[bias] = out["iterations"]
    ok(out["converged"] and err < 1e-5, f"a heat transfer coefficient {bias:g} times the right one still gives the answer (error {err:.1e}, {out['iterations']} iterations)")
ok(counts[1.0] <= counts[0.3] and counts[1.0] <= counts[3.0], f"and the right one is the fastest ({counts})")

# ------------------------------------------------------------------------------------------------------ 3. the stop rule, the iteration cap and the history
fl, so = StandInFluid(N, 25.0, 3.0, T_in), StandInSolid(N, 40.0, 5.0, T_hot)
out = run(fl, so, conj_tol=1e-2, conj_max=60)
ok(out["converged"] and out["mismatch"] <= 1e-2 and out["history"][-1]["it"] == out["iterations"], f"it stops when the flux mismatch is below the tolerance ({out['mismatch']:.1e} after {out['iterations']})")
fl, so = StandInFluid(N, 25.0, 3.0, T_in, h_bias=0.05), StandInSolid(N, 40.0, 5.0, T_hot)
out = run(fl, so, conj_tol=1e-12, conj_max=3)
ok(not out["converged"] and out["iterations"] == 3 and len(out["history"]) == 3, "a cap on the iterations stops it and says it did not converge")
m = [h["mismatch"] for h in out["history"]]
ok(m[-1] < m[0], f"the mismatch falls from one iteration to the next ({m[0]:.2e} -> {m[-1]:.2e})")

# ------------------------------------------------------------------------------------------------------ 4. refusals and mutations
fl, so = StandInFluid(N, 25.0, 3.0, T_in), StandInSolid(N, 40.0, 5.0, T_hot)
fl.coupled_keys = lambda: []
try:
    run(fl, so)
    ok(False, "no coupled wall is refused")
except cf.FluidThermalError as ex:
    ok("no wall of the thermal analysis" in str(ex), f"no coupled wall is refused in words: {ex}")
fl, so = StandInFluid(N, 25.0, 3.0, T_in, h_bias=0.0), StandInSolid(N, 40.0, 5.0, T_hot)
try:
    run(fl, so)
    ok(False, "a wall with no heat transfer coefficient is refused")
except cf.FluidThermalError as ex:
    ok("zero everywhere" in str(ex), f"a wall without any coefficient is refused: {ex}")
# a fluid that gives the heat flux with the wrong sign cannot reach the one-system answer
fl, so = StandInFluid(N, 25.0, 3.0, T_in, sign=-1.0), StandInSolid(N, 40.0, 5.0, T_hot)
out = run(fl, so, conj_tol=1e-8, conj_max=40)
ref = reference(StandInFluid(N, 25.0, 3.0, T_in), StandInSolid(N, 40.0, 5.0, T_hot))
ok((not out["converged"]) or float(np.abs(so.T - ref).max()) > 1.0, "mutation: a fluid with the wrong sign of the heat flux does not give the right answer (the check can fail)")
# the heat balance check can fail: a solid that reports another heat
fl, so = StandInFluid(N, 25.0, 3.0, T_in), StandInSolid(N, 40.0, 5.0, T_hot)
so.heat_to_fluid = lambda: 0.5 * float(np.sum(so.h * (so.T - so.Tref) * so.w))
out = run(fl, so, conj_tol=1e-8, conj_max=60)
ok(abs(out["Q_rel"]) > 0.2, f"mutation: a solid that reports half the heat shows in the balance ({100 * out['Q_rel']:.0f} %)")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("OK coupled fluid")
