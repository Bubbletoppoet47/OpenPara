"""coupled_check.py - the SELF-CHECK of Coupled Physics: problems with known answers that run the hand-over and the loop (coupled_engine) on stand-in analyses, without windows,
and say PASS or FAIL beside the numbers.  It also runs the checks the wrong way round: a stress solve that was not given the field, a field that is extrapolated, a heat
problem and a stress problem of different dimension, a heat exchange that does not settle, a pressure that is not the fluid's - the loop must catch each.  (The real windows are
checked by the tests that come with the program and by the example project in the Workbench.)  run() -> {"rows": [{"name", "expected", "got", "ok"}], "ok": bool, "seconds"}.
The stand-ins of the fluid (StandInFluid, StandInSolid, StandInStructural, reference) are shared with the tests."""
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


# ------------------------------------------------------------------------------------------------------------------------------ stand-ins with a fluid
KEY = ("ln", 1)


class _Prof:
    """What the heat exchange loop needs of a wall profile: .at(points) -> (values, gap) and .h (a segment length)."""

    def __init__(self, x, v):
        self.x, self.v, self.h = np.asarray(x, float), np.asarray(v, float), float(x[1] - x[0])

    def at(self, P):
        P = np.asarray(P, float)
        return np.interp(P[:, 0], self.x, self.v), np.zeros(len(P))


class StandInFluid(ce.Member):
    """A fluid whose wall heat flux depends on the whole wall temperature (a non-local operator, like the real one): q = D (T - T_in), D = hf (I + beta L) with L a graph
    Laplacian, so that a uniform wall temperature gives h = hf.  `h_bias` scales the coefficient the loop linearises with, `sign` flips the heat flux (a broken fluid),
    `status` is what the flow solve reports, `force`/`scale` the pressure force it pushes with."""
    role, dim, label = "fluid", 2, "Fluid (stand-in)"

    def __init__(self, N, hf, beta, T_in, h_bias=1.0, sign=1.0, status="converged", force=(2.0, -0.5), scale=5.0):
        self.N, self.T_in, self.h_bias, self.sign, self.status, self.force, self.scale = N, T_in, h_bias, sign, status, tuple(force), scale
        self.x = np.linspace(0.0, 1.0, N)
        L = 2.0 * np.eye(N) - np.eye(N, k=1) - np.eye(N, k=-1)
        L[0, 0] = L[-1, -1] = 1.0
        self.D = hf * (np.eye(N) + beta * L)
        self.hf = hf
        self.released = 0

    def release(self):
        self.released += 1

    def coupled_keys(self):
        return [KEY]

    def solve_flow(self):
        return {"status": self.status}

    def flow_summary(self):
        return {"status": self.status, "steps": 100}

    @staticmethod
    def _seg(v):
        v = np.asarray(v, float)
        return (v[:-1], 0.5 * (v[:-1] + v[1:]), v[1:])

    def h_iso(self):
        h = self.D @ np.ones(self.N) * self.h_bias
        return {KEY: self._seg(h)}, _Prof(self.x, h)

    def profile(self, values):
        a, _m, b = values[KEY]
        return _Prof(self.x, np.concatenate([np.asarray(a, float), [float(np.asarray(b)[-1])]]))

    def solve_temperature(self, Tw_at):
        P = np.stack([self.x, np.zeros(self.N)], axis=1)
        Tw = Tw_at(P)
        q = self.sign * (self.D @ (Tw - self.T_in))
        Q = float(np.trapezoid(q, self.x)) if hasattr(np, "trapezoid") else float(np.trapz(q, self.x))
        sa, sm, sb = self._seg(Tw)
        qa, qm, qb = self._seg(q)
        return {"walls": {KEY: {"T_a": sa, "T_m": sm, "T_b": sb, "q_a": qa, "q_m": qm, "q_b": qb, "Q": Q, "kind": "temp"}}, "T_in": self.T_in, "Tmin": float(min(Tw.min(), self.T_in)),
                "Tmax": float(max(Tw.max(), self.T_in)), "Pr": 0.71, "balance": {"relative": 0.0}, "notes": [], "overshoot": None}

    def pressure_info(self):
        return {"info": {"stand-in": True, "force": list(self.force)}, "edges": [KEY]}

    def pressure_force(self, edges, shear=False):
        return self.force, self.scale


class StandInSolid(ce.Member):
    """A solid with one wall of N nodes: held at T_hot through a conductance g, conducting along the wall (c), exchanging heat with the fluid through q = h (T - Tref)."""
    role, dim, label = "thermal", 2, "Solid (stand-in)"
    thickness = 1.0

    def __init__(self, N, g, c, T_hot):
        self.N = N
        self.x = np.linspace(0.0, 1.0, N)
        self.g = np.asarray(g, float) * np.ones(N)
        self.T_hot = np.asarray(T_hot, float) * np.ones(N)
        K = c * (2.0 * np.eye(N) - np.eye(N, k=1) - np.eye(N, k=-1))
        K[0, 0] = K[-1, -1] = c
        self.Kc = K
        w = np.full(N, 1.0 / (N - 1))
        w[0] = w[-1] = 0.5 / (N - 1)
        self.w = w
        self.calls = 0
        self.released = 0
        self.T = None

    def release(self):
        self.released += 1

    def set_fluid(self, h_at, Tref_at, keys):
        self.h_at, self.Tref_at = h_at, Tref_at

    def solve(self):
        P = np.stack([self.x, np.zeros(self.N)], axis=1)
        self.h, self.Tref = self.h_at(P), self.Tref_at(P)
        A = self.Kc + np.diag(self.g) + np.diag(self.h * self.w)
        b = self.g * self.T_hot + self.h * self.w * self.Tref
        self.T = np.linalg.solve(A, b)
        self.calls += 1
        return {"T": self.T}

    def wall_temperature_at(self, P):
        return np.interp(np.asarray(P, float)[:, 0], self.x, self.T), 0.0

    def heat_to_fluid(self):
        return float(np.sum(self.h * (self.T - self.Tref) * self.w))

    def temperature_field(self):
        """The temperature of the strip [0, 1] x [0, 1] that the wall belongs to (the wall temperature on both of its sides)."""
        from scipy.spatial import Delaunay
        pts = np.array([[x, 0.0] for x in self.x] + [[x, 1.0] for x in self.x])
        T = np.concatenate([self.T, self.T])
        w = ce.lumped_weights(pts, Delaunay(pts).simplices)
        return pts, Delaunay(pts).simplices, T, float(np.sum(w * T) / np.sum(w))


class StandInStructural(ce.Member):
    """A stress analysis that takes the temperature on the strip and the pressure force of the fluid.  `lie` scales the pressure force it reports it carried, `edges` are the edges it
    reports."""
    role, dim, label = "structural", 2, "Stress (stand-in)"

    def __init__(self, lie=1.0, edges=(KEY,), honest=True):
        self.lie, self.edges, self.honest = lie, tuple(edges), honest
        self.pts, self.simp = _mesh(2, 40, 11)
        self.last_weights = self.last_points = None
        self.cfd = None
        self.released = 0

    def release(self):
        self.released += 1

    def solve(self, temperature_at=None, cfd=None):
        self.cfd = cfd
        self.cfd_force = None if cfd is None else cfd["info"].get("force")
        out = {}
        if temperature_at is not None:
            T = np.asarray(temperature_at(self.pts), float)
            self.last_points, self.last_weights = self.pts, ce.lumped_weights(self.pts, self.simp)
            out["thermal"] = {"T_min": float(T.min()), "T_max": float(T.max())}
        return out

    def pressure_report(self):
        F = np.asarray(self.cfd_force, float) if getattr(self, "cfd_force", None) is not None else np.zeros(2)
        return {"edges": list(self.edges), "force": tuple(self.lie * F), "same_geometry": True}


class StandInMovingFluid(StandInFluid):
    """A fluid whose pressure load depends on where the body is: the body's outline has M points, each moved by d (y direction only); the load on them is f = f0 + A d (A the answer of
    the flow to the shape).  `set_shape(D)` moves it, `solve_flow()` finds the load.  Heat (the parent) works as before."""

    def __init__(self, f0, A, N=41, hf=25.0, beta=3.0, T_in=300.0, size=100.0, **kw):
        super().__init__(N, hf, beta, T_in, **kw)
        self.size = size
        self.f0, self.A = np.asarray(f0, float), np.asarray(A, float)
        self.M = len(self.f0)
        self.P = np.stack([np.linspace(0.0, 1.0, self.M), np.zeros(self.M)], axis=1)
        self.shape = None
        self.shapes_seen = []
        self.flows = 0
        self.load = self.f0.copy()

    def check_movable(self):
        pass

    def boundary_points(self):
        return {"P": self.P}

    def length_scale(self):
        return self.size

    def set_shape(self, D):
        self.shape = None if D is None else np.array(D, float)
        self.shapes_seen.append(None if D is None else np.array(D, float))

    def solve_flow(self):
        d = np.zeros(self.M) if self.shape is None else self.shape[:, 1]
        self.load = self.f0 + self.A @ d
        self.flows += 1
        return {"status": self.status}

    def mesh_summary(self):
        return {"triangles": 100, "angle_min": 30.0, "aspect_max": 2.0, "moved": self.shape is not None}

    def release(self):
        super().release()
        self.shape = None

    def pressure_info(self):
        return {"info": {"stand-in": True, "force": [0.0, float(self.load.sum())], "load": self.load.copy()}, "edges": [KEY]}

    def pressure_force(self, edges, shear=False):
        return (0.0, float(self.load.sum())), float(np.abs(self.load).sum())


class StandInSoftStructural(StandInStructural):
    """A structure that is pushed by the load of the fluid and moves: K d = f (K the stiffness).  `gap` is how far from its mesh it says the outline points are."""

    def __init__(self, K, gap=0.0, **kw):
        super().__init__(**kw)
        self.K = np.asarray(K, float)
        self.gap = gap
        self.d = None

    def solve(self, temperature_at=None, cfd=None):
        out = super().solve(temperature_at, cfd)
        if cfd is not None:
            self.d = np.linalg.solve(self.K, np.asarray(cfd["info"]["load"], float))
        return out

    def displacement_at(self, P):
        D = np.zeros((len(P), 2))
        D[:, 1] = self.d
        return D, self.gap


def fixed_point(f0, A, K):
    """The displacement the structure and the flow agree on: d = K^-1 (f0 + A d)."""
    return np.linalg.solve(np.asarray(K, float) - np.asarray(A, float), np.asarray(f0, float))


def reference(fl, so):
    """The fluid and the solid as ONE linear system: (Kc + g + w D) T = g T_hot + w D T_in."""
    A = so.Kc + np.diag(so.g) + np.diag(so.w) @ fl.D
    b = so.g * so.T_hot + so.w * (fl.D @ np.full(fl.N, fl.T_in))
    return np.linalg.solve(A, b)


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
    # a flowing fluid: heat exchange with a solid, pressure on a stress analysis
    if progress:
        progress("Fluid and solid exchanging heat", 0.8)
    N = 41
    xs = np.linspace(0.0, 1.0, N)
    T_in = 300.0
    hot = 330.0 + 120.0 * np.sin(np.pi * xs) ** 2

    def loop(**kw):
        fl, so = StandInFluid(N, 25.0, 3.0, T_in, **{k: v for k, v in kw.items() if k in ("h_bias", "sign")}), StandInSolid(N, 40.0, 5.0, hot)
        return fl, so, ce.solve_coupled({"fluid": fl, "thermal": so}, {"conj_tol": 1e-8, "conj_max": kw.get("conj_max", 60)})
    fl, so, res = loop()
    ref = reference(fl, so)
    err = float(np.abs(so.T - ref).max()) / float(ref.max() - T_in)
    _row(rows, "Fluid and solid exchanging heat: the loop reaches the answer of the two problems as one system", "error below 1e-6 of the temperature rise", f"{err:.1e}", err < 1e-6)
    _row(rows, "Fluid and solid: the loop passes its own checks", "every check passes", f"{sum(c['ok'] for c in res['checks'])} of {len(res['checks'])}", res["ok"] and all(c["ok"] for c in res["checks"]))
    f = res["fluid"]
    _row(rows, "Fluid and solid: the heat that leaves the solid is the heat the fluid takes", "equal", f"{f['Q_solid']:.6g} W and {f['Q_fluid']:.6g} W", abs(f["Q_solid"] - f["Q_fluid"]) < 1e-6 * abs(f["Q_fluid"]))
    fl3, so3, res3 = loop(h_bias=3.0)
    err3 = float(np.abs(so3.T - reference(fl3, so3)).max()) / float(ref.max() - T_in)
    _row(rows, "Fluid and solid: a heat transfer coefficient three times too large changes the speed, not the answer", "error below 1e-5", f"{err3:.1e} in {res3['fluid']['iterations']} iterations", err3 < 1e-5)
    try:
        loop(h_bias=0.0)
        caught = False
    except ce.CoupledError:
        caught = True
    _row(rows, "A flow that does not touch the walls (no heat transfer coefficient) is refused", "an error in words", "refused" if caught else "accepted", caught)
    fl4, so4 = StandInFluid(N, 25.0, 3.0, T_in), StandInSolid(N, 40.0, 5.0, hot)
    so4.heat_to_fluid = lambda: 0.5 * float(np.sum(so4.h * (so4.T - so4.Tref) * so4.w))
    r4 = ce.solve_coupled({"fluid": fl4, "thermal": so4}, {"conj_tol": 1e-8, "conj_max": 60})
    bal = next(c for c in r4["checks"] if c["name"].startswith("Heat leaving the solid"))
    _row(rows, "A solid that reports half of its heat is caught", "the check 'Heat leaving the solid = heat entering the fluid' fails", "failed" if not bal["ok"] else "passed", not bal["ok"])
    fl5 = StandInFluid(N, 25.0, 3.0, T_in, status="max_steps")
    so5 = StandInSolid(N, 40.0, 5.0, hot)
    r5 = ce.solve_coupled({"fluid": fl5, "thermal": so5}, {"conj_tol": 1e-8, "conj_max": 60})
    fs = next(c for c in r5["checks"] if c["name"] == "Flow settled")
    _row(rows, "A flow that did not settle is reported", "the check 'Flow settled' fails", "failed" if not fs["ok"] else "passed", not fs["ok"])
    if progress:
        progress("Fluid pressure on a stress analysis", 0.92)
    flp, stp = StandInFluid(N, 25.0, 3.0, T_in, force=(2.0, -0.5), scale=5.0), StandInStructural()
    rp = ce.solve_coupled({"fluid": flp, "structural": stp})
    pc = next(c for c in rp["checks"] if c["name"] == "Pressure force handed over")
    _row(rows, "Fluid pressure on a stress analysis: the force carried is the force pushed with", "difference below 2 % of the load", pc["detail"].split("(difference")[1].split(",")[0].strip() if "(difference" in pc["detail"] else pc["detail"][:60], pc["ok"])
    rl = ce.solve_coupled({"fluid": StandInFluid(N, 25.0, 3.0, T_in, force=(2.0, -0.5), scale=5.0), "structural": StandInStructural(lie=0.5)})
    pl = next(c for c in rl["checks"] if c["name"] == "Pressure force handed over")
    _row(rows, "A stress analysis that carries half of the pressure force is caught", "the check 'Pressure force handed over' fails and the result is refused", "failed" if not pl["ok"] and not rl["ok"] else "passed", not pl["ok"] and not rl["ok"])
    try:
        ce.solve_coupled({"fluid": StandInFluid(N, 25.0, 3.0, T_in), "structural": StandInStructural(edges=())})
        _row(rows, "A stress analysis that got no pressure at all is refused", "an error in words", "accepted", False)
    except ce.CoupledError as ex:
        _row(rows, "A stress analysis that got no pressure at all is refused", "an error in words", "refused: " + str(ex)[:60], True)
    # the structure moves the flow: a loop with a known fixed point
    if progress:
        progress("The structure moves the flow", 0.96)
    M = 21
    xm = np.linspace(0.0, 1.0, M)
    f0 = 1.0 + 0.5 * np.sin(np.pi * xm)
    Kst = 4.0 * np.eye(M) + 1.0 * (2.0 * np.eye(M) - np.eye(M, k=1) - np.eye(M, k=-1))
    def fsi(A, relax=1.0, tol=1e-7, nmax=60, aitken=True, **kw):
        fl_, st_ = StandInMovingFluid(f0, A, **kw), StandInSoftStructural(Kst)
        return fl_, st_, ce.solve_coupled({"fluid": fl_, "structural": st_}, {"moves_flow": True, "fsi_tol": tol, "fsi_max": nmax, "fsi_relax": relax, "fsi_aitken": aitken, "pressure_tol": 0.5})
    A1 = 0.8 * np.eye(M) + 0.3 * (np.eye(M, k=1) + np.eye(M, k=-1))
    d_star = fixed_point(f0, A1, Kst)
    fl_, st_, r_ = fsi(A1)
    err = float(np.abs(st_.d - d_star).max() / np.abs(d_star).max())
    _row(rows, "The structure moves the flow: the loop reaches the displacement the two agree on", "error below 1e-6", f"{err:.1e} in {r_['fsi']['iterations']} passes", err < 1e-6 and r_["fsi"]["converged"])
    _row(rows, "The structure moves the flow: the loop passes its own checks", "every check passes", f"{sum(c['ok'] for c in r_['checks'])} of {len(r_['checks'])}", r_["ok"] and all(c["ok"] for c in r_["checks"]))
    fl_h, st_h, r_h = fsi(A1, relax=0.5, aitken=False)
    err_h = float(np.abs(st_h.d - d_star).max() / np.abs(d_star).max())
    _row(rows, "The structure moves the flow: a fixed relaxation of 0.5 changes the speed, not the answer", "error below 1e-6", f"{err_h:.1e} in {r_h['fsi']['iterations']} passes (against {r_['fsi']['iterations']})", err_h < 1e-6 and r_h["fsi"]["iterations"] > r_["fsi"]["iterations"])
    A2 = -12.0 * np.eye(M)                                             # a flow that pushes back harder than the structure holds (negative feedback): a full step overshoots
    fl_s, st_s, r_s = fsi(A2)
    err_s = float(np.abs(st_s.d - fixed_point(f0, A2, Kst)).max() / np.abs(fixed_point(f0, A2, Kst)).max())
    _row(rows, "The structure moves the flow: a step that overshoots is relaxed until it settles", "error below 1e-6", f"{err_s:.1e} in {r_s['fsi']['iterations']} passes, relaxation {r_s['fsi']['history'][-1]['omega']:g}", err_s < 1e-6 and r_s["fsi"]["converged"] and r_s["fsi"]["history"][-1]["omega"] < 1.0)
    A3 = 6.0 * np.eye(M)                                               # the load grows faster with the displacement than the structure resists: there is no steady state
    fl_u, st_u, r_u = fsi(A3, nmax=15)
    cu = next(c for c in r_u["checks"] if c["name"] == "Moved flow converged")
    _row(rows, "The structure moves the flow: a loop with no steady state is refused", "the check 'Moved flow converged' fails and the result is refused", "failed" if not cu["ok"] and not r_u["ok"] else "passed", not cu["ok"] and not r_u["ok"])
    import coupled_check3d
    rows += coupled_check3d.rows_fluid3d(progress)
    if progress:
        progress("Done", 1.0)
    return {"rows": rows, "ok": all(x["ok"] for x in rows), "seconds": time.monotonic() - t0}
