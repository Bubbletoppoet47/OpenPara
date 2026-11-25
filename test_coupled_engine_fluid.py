"""The Coupled Physics engine with a fluid member (coupled_engine._solve_with_fluid), on the stand-in analyses of the self-check (no windows): a fluid and a solid exchanging heat, a
fluid and a stress analysis taking its pressure, the three together.  The checks that must pass pass; the ones that must be able to fail fail when the analyses are made wrong;
every member is released whatever happens (done, refused, cancelled).
python test_coupled_engine_fluid.py"""
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


N = 41
T_IN = 300.0
x = np.linspace(0, 1, N)
HOT = 330.0 + 120.0 * np.sin(np.pi * x) ** 2
OPT = {"conj_tol": 1e-8, "conj_max": 60}


def fluid(**kw):
    return cc.StandInFluid(N, 25.0, 3.0, T_IN, **kw)


def solid():
    return cc.StandInSolid(N, 40.0, 5.0, HOT)


def check(res, name):
    return next(c for c in res["checks"] if c["name"].startswith(name))


# --------------------------------------------------------------------------------------------------------------------------- fluid + thermal
fl, so = fluid(), solid()
res = ce.solve_coupled({"fluid": fl, "thermal": so}, OPT)
ok(res["ok"] and all(c["ok"] for c in res["checks"]), "fluid + heat: the solve is ok and every check passes: " + "; ".join(c["name"] for c in res["checks"]))
ok("structural" not in res and "thermal" in res and "fluid" in res, "fluid + heat: the result has the fluid and the heat parts only")
ref = cc.reference(fl, so)
ok(float(np.abs(so.T - ref).max()) < 1e-6 * float(ref.max() - T_IN), "fluid + heat: the answer is that of the two problems as one system")
ok(res["fluid"]["iterations"] == res["passes"][0]["pass"] and res["fluid"]["iterations"] > 1, f"fluid + heat: the loop's iterations are reported ({res['fluid']['iterations']})")
tr = res["transfers"][0]
ok(tr["what"] == "heat exchange" and "src_text" in tr and "dst_text" in tr, f"fluid + heat: the transfer is described in words ({tr['src_text']} -> {tr['dst_text']})")
ok(fl.released == 1 and so.released == 1, "fluid + heat: both members were released at the end")

# the checks can fail
fl, so = fluid(), solid()
res = ce.solve_coupled({"fluid": fl, "thermal": so}, {"conj_tol": 1e-12, "conj_max": 2})
ok(not res["ok"] and not check(res, "Heat exchange converged")["ok"] and check(res, "Heat exchange converged")["hard"], "a loop that is cut short is refused (a hard check)")
fl, so = fluid(), solid()
so.heat_to_fluid = lambda: 0.5 * float(np.sum(so.h * (so.T - so.Tref) * so.w))
res = ce.solve_coupled({"fluid": fl, "thermal": so}, OPT)
ok(not res["ok"] and not check(res, "Heat leaving the solid")["ok"], "a solid that reports half of its heat is refused")
res = ce.solve_coupled({"fluid": fluid(status="max_steps"), "thermal": solid()}, OPT)
ok(res["ok"] and not check(res, "Flow settled")["ok"] and not check(res, "Flow settled")["hard"], "a flow that did not settle fails its check without stopping the result (a soft check)")


class Gap(cc.StandInSolid):
    def wall_temperature_at(self, P):
        v, g = super().wall_temperature_at(P)
        return v, 3.0                                              # the wall points lie three element sizes from the solid


res = ce.solve_coupled({"fluid": fluid(), "thermal": Gap(N, 40.0, 5.0, HOT)}, OPT)
ok(not res["ok"] and not check(res, "Every wall point found")["ok"], "wall points that do not lie on the wall of the solid are refused")

# --------------------------------------------------------------------------------------------------------------------------- fluid + structural
fl, st = fluid(force=(2.0, -0.5), scale=5.0), cc.StandInStructural()
res = ce.solve_coupled({"fluid": fl, "structural": st})
ok(res["ok"] and all(c["ok"] for c in res["checks"]), "fluid + stress: the solve is ok and every check passes: " + "; ".join(c["name"] for c in res["checks"]))
ok("thermal" not in res and "structural" in res and st.cfd is not None and st.cfd["edges"] == [cc.KEY], "fluid + stress: the stress analysis was given the pressure of the fluid on its edges")
ok(fl.released == 1 and st.released == 1, "fluid + stress: both members were released")
for lie in (0.5, 1.5):
    res = ce.solve_coupled({"fluid": fluid(force=(2.0, -0.5), scale=5.0), "structural": cc.StandInStructural(lie=lie)})
    ok(not res["ok"] and not check(res, "Pressure force handed over")["ok"] and check(res, "Pressure force handed over")["hard"], f"a stress analysis that carries {lie:g} times the fluid's force is refused")
res = ce.solve_coupled({"fluid": fluid(force=(0.0, 0.0), scale=5.0), "structural": cc.StandInStructural()})
ok(res["ok"], "no net force with a pressure load on the walls (a closed body) is judged against the load carried, not against zero")
res = ce.solve_coupled({"fluid": fluid(force=(2.0, -0.5), scale=5.0), "structural": cc.StandInStructural(lie=1.01)}, {"pressure_tol": 0.001})
ok(not res["ok"], "the tolerance of the pressure force is an option (0.1 %: a 1 % difference fails)")
try:
    ce.solve_coupled({"fluid": fluid(), "structural": cc.StandInStructural(edges=())})
    ok(False, "a stress analysis that got no pressure is refused")
except ce.CoupledError as ex:
    ok("no fluid pressure" in str(ex), f"a stress analysis that got no pressure is refused in words: '{ex}'")

# --------------------------------------------------------------------------------------------------------------------------- the three together
fl, so, st = fluid(force=(2.0, -0.5), scale=5.0), solid(), cc.StandInStructural()
res = ce.solve_coupled({"fluid": fl, "thermal": so, "structural": st}, OPT)
names = [c["name"] for c in res["checks"]]
ok(res["ok"] and all(c["ok"] for c in res["checks"]), "three together: the solve is ok and every check passes")
ok("Heat exchange converged" in names and "Stress solve used the field" in names and "Pressure force handed over" in names, "three together: the checks of the heat exchange, the temperature hand-over and the pressure are all there")
ok(fl.released == so.released == st.released == 1, "three together: all three members were released")
ok(st.cfd is not None, "three together: the stress analysis was given the pressure as well as the temperature")

# --------------------------------------------------------------------------------------------------------------------------- refusals, cancel and release
try:
    ce.solve_coupled({"fluid": fluid()})
    ok(False, "a fluid alone is refused")
except ce.CoupledError as ex:
    ok("thermal analysis or a structural analysis" in str(ex), f"a fluid alone is refused in words: '{ex}'")


class Solid3D(cc.StandInSolid):
    dim = 3


try:
    ce.solve_coupled({"fluid": fluid(), "thermal": Solid3D(N, 40.0, 5.0, HOT)})
    ok(False, "a 3D solid with a 2D fluid is refused")
except ce.CoupledError as ex:
    ok("2D" in str(ex) and "3D" in str(ex), f"a 3D solid with a 2D fluid is refused in words: '{ex}'")

fl, so = fluid(), solid()
count = {"n": 0}


def stop_after_two():
    count["n"] += 1
    return count["n"] > 3


try:
    ce.solve_coupled({"fluid": fl, "thermal": so}, OPT, cancel=stop_after_two)
    ok(False, "a cancelled solve raises Cancelled")
except ce.Cancelled:
    ok(True, "a cancelled solve raises Cancelled")
ok(fl.released == 1 and so.released == 1, "and the members are released after a cancel")
fl = fluid()
fl.solve_flow = lambda: (_ for _ in ()).throw(ce.CoupledError("the flow could not be solved"))
so = solid()
try:
    ce.solve_coupled({"fluid": fl, "thermal": so}, OPT)
except ce.CoupledError:
    pass
ok(fl.released == 1 and so.released == 1, "and after an error")

# the solve without a fluid is as before
res = ce.solve_coupled({"thermal": cc._Thermal(*cc._mesh(2, 60, 3), lambda X: 300.0 + 40.0 * X[:, 0], 2), "structural": cc._Structural(*cc._mesh(2, 200, 4), 2)})
ok(res["ok"] and "fluid" not in res, "without a fluid the solve is the heat -> stress solve of before")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    for f_ in FAILS:
        print("  -", f_)
    sys.exit(1)
print("OK coupled engine fluid")
