"""coupled_check.py - the SELF-CHECK of Coupled Physics: problems with known answers that run the hand-over and the loop (coupled_engine) on stand-in analyses, without windows,
and say PASS or FAIL beside the numbers.  It also runs the checks the wrong way round: a stress solve that was not given the field, a field that is extrapolated, a heat
problem and a stress problem of different dimension - the loop must catch each.  (The real windows are checked by the tests that come with the program and by the example
project in the Workbench.)  run() -> {"rows": [{"name", "expected", "got", "ok"}], "ok": bool, "seconds"}."""
import time

import numpy as np

import coupled_engine as ce

K = 273.15


class _Thermal(ce.Member):
    role = "thermal"

    def __init__(self, pts, simp, fn, dim, label="Heat (stand-in)"):
        self.dim, self.label, self.pts, self.simp, self.fn = dim, label, pts, simp, fn

    def solve(self):
        return {"T": self.fn(self.pts)}

    def temperature_field(self):
        T = self.fn(self.pts)
        w = ce.lumped_weights(self.pts, self.simp)
        return self.pts, self.simp, T, float(np.sum(w * T) / np.sum(w))


class _Structural(ce.Member):
    role = "structural"

    def __init__(self, pts, simp, dim, label="Stress (stand-in)", honest=True, shift=0.0):
        self.dim, self.label, self.pts, self.simp, self.honest, self.shift = dim, label, pts, simp, honest, shift
        self.last_weights = self.last_points = None
        self.got = None

    def solve(self, temperature_at):
        T = np.asarray(temperature_at(self.pts), float)
        self.last_points, self.last_weights = self.pts, ce.lumped_weights(self.pts, self.simp)
        self.got = T
        if not self.honest:
            return {"thermal": {"T_min": float(T.min()) + self.shift, "T_max": float(T.max()) + self.shift}}
        return {"thermal": {"T_min": float(T.min()), "T_max": float(T.max())}}


def _mesh(dim, n, seed):
    from scipy.spatial import Delaunay
    rs = np.random.RandomState(seed)
    b = np.linspace(0.0, 1.0, 7 if dim == 2 else 4)
    if dim == 2:
        g = np.array([[x, y] for x in b for y in b if min(x, y) == 0 or max(x, y) == 1])
    else:
        g = np.array([[x, y, z] for x in b for y in b for z in b if min(x, y, z) == 0 or max(x, y, z) == 1])
    P = np.vstack([g, rs.uniform(0.05, 0.95, (n, dim))])
    return P, Delaunay(P).simplices


def _row(rows, name, expected, got, ok):
    rows.append({"name": name, "expected": expected, "got": got, "ok": bool(ok)})


def run(progress=None):
    t0 = time.monotonic()
    rows = []
    for dim, n_src, n_dst in ((2, 60, 250), (3, 80, 300)):
        if progress:
            progress(f"{dim}D hand-over", 0.1 if dim == 2 else 0.4)
        Ps, Ss = _mesh(dim, n_src, 3)
        Pd, Sd = _mesh(dim, n_dst, 4)
        g = np.array([40.0, -25.0, 15.0][:dim])
        lin = lambda X, g=g: 300.0 + X @ g                            # a temperature that changes linearly: handed over exactly by linear elements
        th, st = _Thermal(Ps, Ss, lin, dim), _Structural(Pd, Sd, dim)
        res = ce.solve_coupled({"thermal": th, "structural": st})
        err = float(np.abs(st.got - lin(Pd)).max())
        _row(rows, f"{dim}D: a linear temperature reaches the other mesh exactly", "error below 1e-9 K", f"{err:.2e} K", err < 1e-9)
        _row(rows, f"{dim}D: the loop passes its own checks", "every check passes", f"{sum(c['ok'] for c in res['checks'])} of {len(res['checks'])}", res["ok"] and all(c["ok"] for c in res["checks"]))
        lo, hi = float(lin(Ps).min()), float(lin(Ps).max())
        _row(rows, f"{dim}D: no temperature outside the range of the heat problem", f"{lo - K:.4g} .. {hi - K:.4g} degC",
             f"{float(st.got.min()) - K:.4g} .. {float(st.got.max()) - K:.4g} degC", st.got.min() >= lo - 1e-9 and st.got.max() <= hi + 1e-9)
        w = ce.lumped_weights(Pd, Sd)
        mean_dst, mean_src = float(np.sum(w * st.got) / np.sum(w)), float(np.sum(ce.lumped_weights(Ps, Ss) * lin(Ps)) / np.sum(ce.lumped_weights(Ps, Ss)))
        span = hi - lo
        _row(rows, f"{dim}D: the average temperature is kept", f"within 2 % of the {span:.3g} K range", f"{mean_dst - mean_src:+.3g} K ({100 * abs(mean_dst - mean_src) / span:.2g} %)", abs(mean_dst - mean_src) <= 0.02 * span)
    # the loop must CATCH what is wrong
    if progress:
        progress("The checks must be able to fail", 0.7)
    P, S = _mesh(2, 60, 5)
    th = _Thermal(P, S, lambda X: 300.0 + 50.0 * X[:, 0], 2)
    bad = _Structural(P, S, 2, honest=False, shift=5.0)
    r = ce.solve_coupled({"thermal": th, "structural": bad})
    _row(rows, "A stress solve that did not use the field is caught", "the solve is refused (a hard check fails)", "refused" if not r["ok"] else "accepted", not r["ok"])
    try:
        ce.solve_coupled({"thermal": _Thermal(*_mesh(3, 40, 6), lambda X: 300.0 + X[:, 0], 3), "structural": _Structural(P, S, 2)})
        _row(rows, "A 3D heat problem with a 2D stress problem is refused", "an error in words", "accepted", False)
    except ce.CoupledError as ex:
        _row(rows, "A 3D heat problem with a 2D stress problem is refused", "an error in words", "refused: " + str(ex)[:60], True)
    far = _Structural(P + 10.0, S, 2)                                 # a stress mesh that is NOT where the heat problem is
    r = ce.solve_coupled({"thermal": th, "structural": far})
    outside = next(c for c in r["checks"] if c["name"] == "Every point found")
    _row(rows, "A stress mesh away from the heat mesh is reported", "the check 'Every point found' fails", "failed" if not outside["ok"] else "passed", not outside["ok"])
    if progress:
        progress("Done", 1.0)
    return {"rows": rows, "ok": all(x["ok"] for x in rows), "seconds": time.monotonic() - t0}
