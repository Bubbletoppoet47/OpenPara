"""The structure moves the flow (coupled_engine._fsi_loop), on stand-in analyses with a known answer: a flow whose load on M points of the outline is f = f0 + A d (d: how far the
outline has moved), a structure that moves K d = f.  The loop must reach the displacement the two agree on, d = (K - A)^-1 f0, whatever the relaxation; it must say so when there is no
such steady state or when it was cut short; it must stop at the first pass when the structure does not move; it must work with a heat exchange as well; every member is released.
python test_coupled_fsi.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "coupled"), HERE]
import numpy as np

import coupled_check as cc
import coupled_engine as ce

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


M = 21
xm = np.linspace(0.0, 1.0, M)
F0 = 1.0 + 0.5 * np.sin(np.pi * xm)
K = 4.0 * np.eye(M) + (2.0 * np.eye(M) - np.eye(M, k=1) - np.eye(M, k=-1))
A1 = 0.8 * np.eye(M) + 0.3 * (np.eye(M, k=1) + np.eye(M, k=-1))
OPT = {"moves_flow": True, "fsi_tol": 1e-7, "fsi_max": 60, "pressure_tol": 0.5}


def run(A=A1, opt=None, f0=F0, Kst=K, fl=None, st=None, **kw):
    fl = fl or cc.StandInMovingFluid(f0, A, **kw)
    st = st or cc.StandInSoftStructural(Kst)
    return fl, st, ce.solve_coupled({"fluid": fl, "structural": st}, dict(OPT, **(opt or {})))


def check(res, name):
    return next(c for c in res["checks"] if c["name"].startswith(name))


# ---------------------------------------------------------------------------------------------------------------------------------- the known answer
d_star = cc.fixed_point(F0, A1, K)
fl, st, res = run()
err = float(np.abs(st.d - d_star).max() / np.abs(d_star).max())
ok(res["ok"] and res["fsi"]["converged"] and err < 1e-6, f"the loop reaches the displacement the flow and the structure agree on (error {err:.1e}, {res['fsi']['iterations']} passes)")
ok(all(c["ok"] for c in res["checks"]), "every check passes: " + "; ".join(c["name"] for c in res["checks"]))
ok(fl.flows == res["fsi"]["iterations"] == len(res["fsi"]["history"]), f"one flow solve per pass ({fl.flows})")
ok(fl.shapes_seen[0] is None and all(x is not None for x in fl.shapes_seen[1:]), "pass 1 solves the flow round the body as drawn, the others round the moved body")
ok(float(np.abs(fl.shapes_seen[-1][:, 1] - d_star).max() / np.abs(d_star).max()) < 1e-4, "and the last flow was solved round the body moved by (nearly) the displacement it gave")
ok(fl.released == 1 and st.released == 1 and fl.shape is None, "both members were released, the body in the fluid window is the one as drawn again")
h = res["fsi"]["history"]
ok(all(h[i + 1]["step"] < h[i]["step"] for i in range(len(h) - 1)), "the change from one pass to the next falls at every pass")
ok(len(res["passes"]) == len(h), "the passes are listed one by one for the report")
ok("fluid" in res and "structural" in res and "thermal" not in res, "the result has the fluid and the structure")
ok(check(res, "Pressure force handed over")["ok"], "and the pressure force check of the last pass")

# the answer is the one of the load on the last body: (K - A) d = f0 as an equation
resid = float(np.abs(K @ st.d - (F0 + A1 @ fl.shapes_seen[-1][:, 1])).max())
ok(resid < 1e-9 * float(np.abs(F0).max()), f"the structure carries the load of the flow round the last body (residual {resid:.1e})")

# ---------------------------------------------------------------------------------------------------------------------------------- relaxation
fl2, st2, res2 = run(opt={"fsi_relax": 0.5, "fsi_aitken": False})
err2 = float(np.abs(st2.d - d_star).max() / np.abs(d_star).max())
ok(err2 < 1e-6 and res2["fsi"]["iterations"] > res["fsi"]["iterations"], f"a fixed relaxation of 0.5 gives the same answer, slower ({err2:.1e}, {res2['fsi']['iterations']} passes against {res['fsi']['iterations']})")
ok(all(abs(x["omega"] - 0.5) < 1e-12 for x in res2["fsi"]["history"]), "and the factor stays 0.5")
A2 = -12.0 * np.eye(M)
fl3, st3, res3 = run(A=A2)
d2 = cc.fixed_point(F0, A2, K)
err3 = float(np.abs(st3.d - d2).max() / np.abs(d2).max())
ok(res3["fsi"]["converged"] and err3 < 1e-6, f"a flow that pushes back harder than the structure holds: Aitken's rule finds the factor that converges ({err3:.1e}, {res3['fsi']['iterations']} passes, last factor {res3['fsi']['history'][-1]['omega']:.3g})")
fl3b, st3b, res3b = run(A=A2, opt={"fsi_aitken": False, "fsi_max": 25})
ok(not res3b["ok"] and not check(res3b, "Moved flow converged")["ok"], "the same with a fixed factor of 1 does not converge, and is refused")

# ---------------------------------------------------------------------------------------------------------------------------------- what must be refused
fl4, st4, res4 = run(A=6.0 * np.eye(M), opt={"fsi_max": 15})
c4 = check(res4, "Moved flow converged")
ok(not res4["ok"] and not c4["ok"] and c4["hard"] and "still changes" in c4["detail"], f"no steady state (the load grows faster than the structure resists): refused in words: '{c4['detail'][:120]}'")
fl5, st5, res5 = run(opt={"fsi_max": 3, "fsi_tol": 1e-9})
c5 = check(res5, "Moved flow converged")
ok(not res5["ok"] and not c5["ok"] and res5["fsi"]["iterations"] == 3, "a loop that is cut short by the number of passes is refused")
fl6, st6, res6 = run(st=cc.StandInSoftStructural(K, gap=3.0))
ok(not res6["ok"] and not check(res6, "Outline found")["ok"], "an outline that does not lie on the stress mesh is refused")
fl7, st7, res7 = run(size=5.0)
c7 = check(res7, "Displacement small")
ok(res7["ok"] and not c7["ok"] and not c7["hard"], f"a displacement that is a large part of the body fails a soft check, not the result: '{c7['detail'][:110]}'")
try:
    ce.solve_coupled({"fluid": cc.StandInMovingFluid(F0, A1)}, dict(OPT))
    ok(False, "a fluid alone is refused")
except ce.CoupledError as ex:
    ok("Thermal" in str(ex) or "thermal" in str(ex), f"a fluid alone is refused in words: '{ex}'")
try:
    ce.solve_coupled({"fluid": cc.StandInMovingFluid(F0, A1), "thermal": cc.StandInSolid(41, 40.0, 5.0, 340.0)}, dict(OPT))
    ok(False, "the structure cannot move the flow without a structural analysis")
except ce.CoupledError as ex:
    ok("Static Structural" in str(ex), f"the structure cannot move the flow without a structural analysis: '{ex}'")


class Immovable(cc.StandInMovingFluid):
    def check_movable(self):
        raise ce.CoupledError("2D Fluid Flow: automatic refinement is on.")


try:
    ce.solve_coupled({"fluid": Immovable(F0, A1), "structural": cc.StandInSoftStructural(K)}, dict(OPT))
    ok(False, "a window that cannot move its body refuses")
except ce.CoupledError as ex:
    ok("automatic refinement" in str(ex), f"a window that cannot move its body says why: '{ex}'")

# ---------------------------------------------------------------------------------------------------------------------------------- a structure that does not move
fl8, st8, res8 = run(Kst=1e12 * np.eye(M))
ok(res8["ok"] and res8["fsi"]["converged"] and res8["fsi"]["iterations"] == 1 and fl8.flows == 1, f"a structure that does not move (a millionth of the body or less) stops at pass 1 with ONE flow solve ({fl8.flows})")
ok("does not move the flow" in check(res8, "Moved flow converged")["detail"], "and says so")

# ---------------------------------------------------------------------------------------------------------------------------------- without the option
fl9 = cc.StandInMovingFluid(F0, A1)
st9 = cc.StandInSoftStructural(K)
res9 = ce.solve_coupled({"fluid": fl9, "structural": st9}, {"pressure_tol": 0.5})
ok("fsi" not in res9 and fl9.flows == 1 and fl9.shapes_seen == [], "without 'the structure moves the flow' the flow is solved once, round the body as drawn")

# ---------------------------------------------------------------------------------------------------------------------------------- with a heat exchange
N = 41
xs = np.linspace(0.0, 1.0, N)
hot = 330.0 + 120.0 * np.sin(np.pi * xs) ** 2
flh = cc.StandInMovingFluid(F0, A1, N=N)
soh = cc.StandInSolid(N, 40.0, 5.0, hot)
sth = cc.StandInSoftStructural(K)
resh = ce.solve_coupled({"fluid": flh, "thermal": soh, "structural": sth}, dict(OPT, conj_tol=1e-8, conj_max=60))
ref = cc.reference(flh, soh)
ok(resh["ok"] and resh["fsi"]["converged"] and all(c["ok"] for c in resh["checks"]), "with a heat exchange as well: every check passes: " + "; ".join(c["name"] for c in resh["checks"]))
ok(float(np.abs(soh.T - ref).max()) < 1e-6 * float(ref.max() - 300.0), "the heat exchange of the last pass is the answer of the two problems as one system")
ok(float(np.abs(sth.d - d_star).max() / np.abs(d_star).max()) < 1e-6, "and the displacement is the same as without the heat (the heat does not move the flow here)")
ok(flh.released == 1 and soh.released == 1 and sth.released == 1, "all three were released")
ok(soh.calls >= resh["fsi"]["iterations"], f"the heat exchange was solved on every pass ({soh.calls} solid solves in {resh['fsi']['iterations']} passes)")

# ---------------------------------------------------------------------------------------------------------------------------------- cancel
fl10, st10 = cc.StandInMovingFluid(F0, A1), cc.StandInSoftStructural(K)
n = {"k": 0}


def stop_in_third_pass():
    n["k"] += 1
    return fl10.flows >= 3


try:
    ce.solve_coupled({"fluid": fl10, "structural": st10}, dict(OPT), cancel=stop_in_third_pass)
    ok(False, "a cancelled solve raises Cancelled")
except ce.Cancelled:
    ok(fl10.flows >= 3 and fl10.released == 1 and st10.released == 1 and fl10.shape is None, "a solve cancelled in the third pass raises Cancelled, and the members are released")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    for f_ in FAILS:
        print("  -", f_)
    sys.exit(1)
print("OK coupled fsi")
