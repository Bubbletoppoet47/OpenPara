"""Coupled Physics engine without a window: handing a field from one mesh to another (2D triangles, 3D tetrahedra) and the loop that runs a heat problem and a stress
problem in order.  Known answers: a linear field is handed over exactly, a quadratic one with an error that falls as h squared, nothing outside the range of the source can
appear, the points that no element holds are counted, the average of a field is kept, and the checks fail when they should."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "coupled")]
import numpy as np
from scipy.spatial import Delaunay
import coupled_engine as ce

rs = np.random.RandomState(11)


def square_mesh(n):
    """A Delaunay mesh of the unit square with n random interior points plus the corners and a ring of boundary points."""
    b = np.linspace(0, 1, 9)
    ring = np.concatenate([np.stack([b, 0 * b], 1), np.stack([b, 0 * b + 1], 1), np.stack([0 * b[1:-1], b[1:-1]], 1), np.stack([0 * b[1:-1] + 1, b[1:-1]], 1)])
    P = np.vstack([ring, rs.uniform(0.02, 0.98, (n, 2))])
    return P, Delaunay(P).simplices


def cube_mesh(n):
    b = np.linspace(0, 1, 5)
    g = np.array([[x, y, z] for x in b for y in b for z in b if min(x, y, z) == 0 or max(x, y, z) == 1])
    P = np.vstack([g, rs.uniform(0.05, 0.95, (n, 3))])
    return P, Delaunay(P).simplices


# ------------------------------------------------------------------------------------------------------------------- 2D: exact for a linear field
P, S = square_mesh(120)
loc = ce.Locator(P, S)
lin = lambda X: 300.0 + 40.0 * X[:, 0] - 25.0 * X[:, 1]
X = rs.uniform(0.0, 1.0, (400, 2))
v, info = loc.interpolate(lin(P), X)
assert np.abs(v - lin(X)).max() < 1e-10 and info["outside"] == 0, (np.abs(v - lin(X)).max(), info)
Q, _ = square_mesh(500)                                                    # the nodes of another, finer mesh
v, info = ce.hand_over(P, S, lin(P), Q)
assert np.abs(v - lin(Q)).max() < 1e-10 and info["outside"] == 0 and not info["direct"]
assert v.min() >= lin(P).min() - 1e-12 and v.max() <= lin(P).max() + 1e-12, "no value outside the range of the source"
print("ok   2D: a linear field is handed over exactly, to random points and to the nodes of another mesh, and stays inside its range")

# nodes and edges themselves (on the boundary of elements, weights zero)
v, info = loc.interpolate(lin(P), P)
assert np.abs(v - lin(P)).max() < 1e-10 and info["outside"] == 0, "a node of the mesh is found"
mid = 0.5 * (P[S[:, 0]] + P[S[:, 1]])
v, info = loc.interpolate(lin(P), mid)
assert np.abs(v - lin(mid)).max() < 1e-10 and info["outside"] == 0, "the middle of an edge is found"

# a quadratic field: second order
errs = []
quad = lambda X: X[:, 0] ** 2 + 0.5 * X[:, 0] * X[:, 1] + 2 * X[:, 1] ** 2
for n in (60, 240, 960):
    P2, S2 = square_mesh(n)
    X = rs.uniform(0.05, 0.95, (500, 2))
    v, _ = ce.Locator(P2, S2).interpolate(quad(P2), X)
    errs.append(np.abs(v - quad(X)).max())
rate = np.log(errs[0] / errs[2]) / np.log(2.0 * 2.0)                      # four times the points: h halves twice -> 4x in the error per halving
assert errs[2] < errs[0] / 4 and errs[1] < errs[0], errs
print(f"ok   2D: a quadratic field is handed over with an error that falls with the mesh ({errs[0]:.2e} -> {errs[1]:.2e} -> {errs[2]:.2e})")

# outside points are counted and clamped; nothing is extrapolated
Xo = np.array([[1.3, 0.5], [0.5, -0.2], [0.4, 0.4]])
v, info = loc.interpolate(lin(P), Xo)
assert info["outside"] == 2 and info["max_gap"] > 0.1, info
assert v.min() >= lin(P).min() - 1e-12 and v.max() <= lin(P).max() + 1e-12, "an outside point takes a value from inside the range"
assert abs(v[2] - lin(Xo[2:])[0]) < 1e-10
print("ok   2D: points outside the mesh are counted, how far is reported, and they take the value of the nearest point (never extrapolated)")

# the same points in the same order are handed over untouched (not even a locator is needed)
Pd = P.copy()
v, info = ce.hand_over(P, S[:0], lin(P) + 1.0, Pd)
assert info["direct"] and np.array_equal(v, lin(P) + 1.0)

# a collapsed element does not break the search
Pz = np.vstack([P, [[0.5, 0.5]]])
Sz = np.vstack([S, [[len(P), len(P), len(P)]]])
v, info = ce.Locator(Pz, Sz).interpolate(np.concatenate([lin(P), [0.0]]), X[:50] * 0 + 0.3)
assert np.abs(v - lin(X[:50] * 0 + 0.3)).max() < 1e-10, "a zero-area triangle is never chosen"

# the weights of an average
w = ce.lumped_weights(P, S)
assert abs(w.sum() - 1.0) < 1e-12 and np.all(w > 0)
assert abs(float(w @ lin(P)) - (300.0 + 20.0 - 12.5)) < 1e-9, "the average of a linear field over the unit square is its value at the centre"
print("ok   2D: a zero-area element is skipped; the lumped weights add up to the area and average a linear field exactly")

# ------------------------------------------------------------------------------------------------------------------- 3D
P3, S3 = cube_mesh(300)
loc3 = ce.Locator(P3, S3)
lin3 = lambda X: 300.0 + 40.0 * X[:, 0] - 25.0 * X[:, 1] + 10.0 * X[:, 2]
X = rs.uniform(0.0, 1.0, (500, 3))
v, info = loc3.interpolate(lin3(P3), X)
assert np.abs(v - lin3(X)).max() < 1e-9 and info["outside"] == 0, (np.abs(v - lin3(X)).max(), info)
Q3, _ = cube_mesh(800)
v, info = ce.hand_over(P3, S3, lin3(P3), Q3)
assert np.abs(v - lin3(Q3)).max() < 1e-9 and info["outside"] == 0 and v.min() >= lin3(P3).min() - 1e-9 and v.max() <= lin3(P3).max() + 1e-9
Xo = np.array([[1.4, 0.5, 0.5], [0.3, 0.3, 0.3]])
v, info = loc3.interpolate(lin3(P3), Xo)
assert info["outside"] == 1 and abs(v[1] - lin3(Xo[1:])[0]) < 1e-9
w3 = ce.lumped_weights(P3, S3)
assert abs(w3.sum() - 1.0) < 1e-10 and abs(float(w3 @ lin3(P3)) - (300 + 20 - 12.5 + 5)) < 1e-8
# quadratic elements: the corner nodes come first and the mid-nodes after, only the corners are used
S10 = np.hstack([S3, np.zeros((len(S3), 6), dtype=int)])
assert np.abs(ce.Locator(P3, S10).interpolate(lin3(P3), X)[0] - lin3(X)).max() < 1e-9
print("ok   3D: a linear field is handed over exactly (random points, another mesh), an outside point is counted, the weights add up to the volume, a 10-node connectivity is read by its corners")

# ------------------------------------------------------------------------------------------------------------------- the loop
class Thermal:
    role, label, dim = "thermal", "Thermal", 2
    def __init__(self, P, S, f, mean=None):
        self.P, self.S, self.f, self.n, self.mean = P, S, f, 0, mean
    def solve(self):
        self.n += 1
        return {}
    def temperature_field(self):
        T = self.f(self.P)
        m = ce.lumped_weights(self.P, self.S) @ T if self.mean is None else self.mean
        return self.P, self.S, T, m


class Struct:
    role, label, dim = "structural", "Structural", 2
    def __init__(self, Q, SQ, report="honest", ask=True):
        self.Q, self.SQ, self.report, self.ask, self.got = Q, SQ, report, ask, None
        self.last_weights, self.last_points = ce.lumped_weights(Q, SQ), Q
    def solve(self, temperature_at):
        if not self.ask:
            return {}
        T = temperature_at(self.Q)
        self.got = T
        lo, hi = float(T.min()), float(T.max())
        if self.report == "lie":
            lo, hi = lo + 5.0, hi
        return {"thermal": {"T_min": lo, "T_max": hi}}


Pt, St = square_mesh(80)
Ps, Ss = square_mesh(300)
f = lambda X: 293.15 + 80.0 * X[:, 0] + 20.0 * X[:, 1]
prog = []
r = ce.solve_coupled({"thermal": Thermal(Pt, St, f), "structural": Struct(Ps, Ss)}, progress=lambda t, x: prog.append((t, x)))
assert r["ok"] and r["error"] is None and r["dim"] == 2 and all(c["ok"] for c in r["checks"]), r["checks"]
assert [c["name"] for c in r["checks"]] == ["Nothing extrapolated", "Every point found", "Average temperature kept", "Stress solve used the field"], [c["name"] for c in r["checks"]]
tr = r["transfers"][0]
assert tr["name"] == "Thermal → Structural" and tr["outside"] == 0 and not tr["direct"] and tr["points"] == len(Ps)
assert abs(r["thermal"]["T_min"] - f(Pt).min()) < 1e-12 and abs(r["thermal"]["T_mean"] - (293.15 + 40 + 10)) < 1e-9
assert r["passes"][0]["pass"] == 1 and "one pass" in r["passes"][0]["note"] and prog[-1] == ("Done", 1.0) and len(prog) >= 4
print("ok   the loop: heat problem, hand-over, stress problem; every check passes, one pass for a one-way coupling")

# the same mesh in both: the field is copied
th = Thermal(Pt, St, f)
sm_ = Struct(Pt.copy(), St)
r = ce.solve_coupled({"thermal": th, "structural": sm_})
assert r["transfers"][0]["direct"] and np.array_equal(sm_.got, f(Pt)) and r["ok"]

# the checks that fail when they should
r = ce.solve_coupled({"thermal": Thermal(Pt, St, f), "structural": Struct(Ps, Ss, report="lie")})
assert not r["ok"] and [c["name"] for c in r["checks"] if not c["ok"]] == ["Stress solve used the field"], r["checks"]
r = ce.solve_coupled({"thermal": Thermal(Pt, St, f, mean=293.15 + 10.0), "structural": Struct(Ps, Ss)})
bad = [c for c in r["checks"] if not c["ok"]]
assert r["ok"] and [c["name"] for c in bad] == ["Average temperature kept"], "a soft check: said, but the solve is still good"
Pshift = Ps * 1.4                                                         # a stress mesh that sticks out of the thermal mesh
r = ce.solve_coupled({"thermal": Thermal(Pt, St, f), "structural": Struct(Pshift, Delaunay(Pshift).simplices)})
bad = [c for c in r["checks"] if not c["ok"]]
assert r["ok"] and any(c["name"] == "Every point found" for c in bad) and r["transfers"][0]["outside"] > 0
print("ok   a field the receiver misreports fails a hard check; a wrong average and nodes outside the thermal mesh are said, not hidden")

# a hand-over that did extrapolate (a broken interpolation) is a hard failure
orig_hand = ce.hand_over
ce.hand_over = lambda *a, **k: (lambda v, i: (v + 40.0, i))(*orig_hand(*a, **k))
r = ce.solve_coupled({"thermal": Thermal(Pt, St, f), "structural": Struct(Ps, Ss)})
ce.hand_over = orig_hand
assert not r["ok"] and "Nothing extrapolated" in [c["name"] for c in r["checks"] if not c["ok"] and c["hard"]], r["checks"]

# errors in words
def raises(fn, word, exc=ce.CoupledError):
    try:
        fn()
    except exc as ex:
        assert word in str(ex), str(ex)
        return
    raise AssertionError("no error")
raises(lambda: ce.solve_coupled({"thermal": Thermal(Pt, St, f)}), "needs a Thermal analysis and a Structural")
t3 = Thermal(Pt, St, f); t3.dim = 3
raises(lambda: ce.solve_coupled({"thermal": t3, "structural": Struct(Ps, Ss)}), "same dimension")
raises(lambda: ce.solve_coupled({"thermal": Thermal(Pt, St, f), "structural": Struct(Ps, Ss, ask=False)}), "did not ask for the temperature")
raises(lambda: ce.solve_coupled({"thermal": Thermal(Pt, St, lambda X: np.where(X[:, 0] > 0.5, np.nan, 300.0)), "structural": Struct(Ps, Ss)}), "not finite")
raises(lambda: ce.solve_coupled({"thermal": Thermal(Pt, St, f), "structural": Struct(Ps, Ss)}, cancel=lambda: True), "", ce.Cancelled)
raises(lambda: ce.Locator(Pt, St).interpolate(f(Pt)[:5], Ps), "values but its mesh has")
print("ok   a missing member, mixed dimensions, a receiver that ignores the field, a thermal field that is not finite and cancelling are each refused or stopped in words")
print("OK")
