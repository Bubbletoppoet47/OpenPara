"""coupled_check3d.py - stand-in 3D analyses with known answers for the Coupled Physics self-check (coupled_check.run) and for the tests (no Qt, no meshing).

A square plate of 10 mm is the wall that a flowing fluid and a solid share.  The fluid has the film coefficient hf(x) = 5 + x W/(m2 K) and, with c > 0, a flux that also depends on the
node upstream (so the loop needs several passes); the solid brings heat through a conductance k_s from a bulk at T_b and conducts along the wall (lam).  Put together they are ONE
linear system  (k_s I + lam L + F) T = k_s T_b + F T_in 1  (F = the fluid's operator): `exact()` solves it, and the loop must end at its answer.  The two meshes the plate with a
different number of nodes, so the interpolation between them is part of what is tested.
"""
import numpy as np

import coupled_engine as ce
import coupled_fluid3d as cf
import coupled_surface as cs

K = 273.15


def plate(n, size=10.0):
    """n x n nodes on a square plate of `size` mm at z = 0: -> points (mm), triangles (rows of points), the area every node stands for (m2)."""
    g = np.linspace(0.0, size, n)
    P = np.array([[x, y, 0.0] for y in g for x in g])
    T = []
    for j in range(n - 1):
        for i in range(n - 1):
            a, b, c, d = j * n + i, j * n + i + 1, (j + 1) * n + i + 1, (j + 1) * n + i
            T += [[a, b, c], [a, c, d]]
    T = np.array(T, np.int64)
    ab, ac = P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]
    ta = 0.5 * np.linalg.norm(np.cross(ab, ac), axis=1) * 1e-6
    A = np.zeros(len(P))
    for k in range(3):
        np.add.at(A, T[:, k], ta / 3.0)
    return P, T, A


def grid_laplacian(n):
    """The graph Laplacian of an n x n grid of nodes (numbered as in plate())."""
    L = np.zeros((n * n, n * n))
    for j in range(n):
        for i in range(n):
            for di, dj in ((1, 0), (0, 1)):
                if i + di < n and j + dj < n:
                    a, c = j * n + i, (j + dj) * n + i + di
                    L[a, a] += 1.0
                    L[c, c] += 1.0
                    L[a, c] -= 1.0
                    L[c, a] -= 1.0
    return L


def film(P):
    return 5.0 + P[:, 0]


class StandInFluid3D(ce.Member):
    """A fluid with the film coefficient hf(P) (W/m2K) at the nodes of its plate.  With c > 0 the heat flux of a node also depends on the node upstream (x smaller):
    q = H (I - c S) (T_w - T_in), S the average of a node with its upstream neighbour.  `h_bias` scales the coefficient the isothermal pass reports (the loop linearises with it: it
    changes the speed, never the answer), `sign` flips the heat flux (a broken fluid), `status` is what the flow solve reports, `force`/`scale` the pressure force it pushes with."""
    role, dim, label = "fluid", 3, "3D fluid (stand-in)"

    def __init__(self, n=5, hf=film, T_in=293.15, keys=(3,), c=0.0, h_bias=1.0, sign=1.0, status="converged", force=(2.0, -0.5, 0.25), scale=5.0, faces=(0, 2, 3)):
        self.P, self.T, self.A = plate(n)
        self.hf, self.T_in, self.keys, self.c, self.h_bias, self.sign, self.status = hf, float(T_in), list(keys), c, h_bias, sign, status
        self.force, self.scale, self.faces = tuple(force), scale, list(faces)
        S = np.zeros((n * n, n * n))
        for j in range(n):
            for i in range(n):
                k = j * n + i
                S[k, k] = 1.0 if i == 0 else 0.5
                if i > 0:
                    S[k, k - 1] = 0.5
        self.S = S
        self.calls = {"flow": 0, "temp": 0}
        self.released = 0

    def release(self):
        self.released += 1

    def coupled_keys(self):
        return self.keys

    def solve_flow(self):
        self.calls["flow"] += 1
        return {"status": self.status}

    def flow_summary(self):
        return {"status": self.status, "steps": 100}

    def wall_surface(self):
        return {"points": self.P, "tris": self.T, "area": self.A}

    def operator(self):
        return np.diag(self.hf(self.P)) @ (np.eye(len(self.P)) - self.c * self.S)

    def solve_temperature(self, Tw_at):
        self.calls["temp"] += 1
        Tw = np.asarray(Tw_at(self.P), float)
        q = self.sign * (self.operator() @ (Tw - self.T_in))
        if np.allclose(Tw, self.T_in + 1.0):                                           # the pass for the heat transfer coefficient
            q = q * self.h_bias
        return {"T": Tw, "q": q, "area": self.A, "Q": float(np.sum(q * self.A))}

    def heat_summary(self):
        return {"Tmin": self.T_in, "Tmax": self.T_in + 1.0, "balance": {"relative": 0.0}, "notes": [], "Pr": 0.71}

    def pressure_info(self):
        return {"info": {"stand-in": True, "force": list(self.force)}, "edges": list(self.faces)}

    def pressure_force(self, edges, shear=False):
        return self.force, self.scale


class StandInSolid3D(ce.Member):
    """A solid with its own plate mesh: bulk at T_b behind the wall, conductance k_s (W/m2K) to it, lateral conduction lam between neighbouring nodes; the wall temperature is worked out at
    ITS nodes and read anywhere by interpolation.  `offset` asks the coefficient a little off the wall (the meshes do not coincide), `gap` is what it reports for how far its wall lies."""
    role, dim, label = "thermal", 3, "3D solid (stand-in)"

    def __init__(self, n=5, k_s=10.0, T_b=353.15, offset=0.0, gap=0.0, lam=0.0):
        self.P, self.T, self.A = plate(n)
        self.k_s, self.T_b, self.offset, self.gap, self.lam = k_s, T_b, offset, gap, lam
        self.L = grid_laplacian(n)
        self.loc = cs.SurfaceLocator(self.P, self.T)
        self.h_at = self.Tref_at = None
        self.fids = None
        self.Tw = None
        self.released = 0

    def release(self):
        self.released += 1

    def set_fluid(self, h_at, Tref_at, fids):
        self.h_at, self.Tref_at, self.fids = h_at, Tref_at, list(fids)

    def solve(self):
        Q = self.P + [0.0, 0.0, self.offset]
        h, Tref = self.h_at(Q), self.Tref_at(Q)
        M = self.k_s * np.eye(len(h)) + self.lam * self.L + np.diag(h)
        self.Tw = np.linalg.solve(M, self.k_s * self.T_b + h * Tref)
        self.q = h * (self.Tw - Tref)

    def wall_temperature_at(self, P):
        v, _info = self.loc.interpolate(self.Tw, P)
        return v, self.gap

    def heat_to_fluid(self):
        return float(np.sum(self.q * self.A))

    def temperature_field(self):
        """The plate as a solid 1 mm thick (its temperature does not change through the thickness): points, tetrahedra, values, the mean."""
        n = len(self.P)
        pts = np.vstack([self.P, self.P + [0.0, 0.0, -1.0]])
        tets = []
        for a, b, c in self.T:
            a2, b2, c2 = a + n, b + n, c + n                                                  # a prism split into three tetrahedra
            tets += [[a, b, c, a2], [b, c, a2, b2], [c, a2, b2, c2]]
        T = np.concatenate([self.Tw, self.Tw])
        return pts, np.array(tets, np.int64), T, float(np.sum(self.Tw * self.A) / np.sum(self.A))


class StandInStructural3D(ce.Member):
    """A stress analysis that is handed the fluid pressure and reports the force it carries: `lie` scales it (a stress analysis that loaded the pressure wrongly), `edges` are the faces it
    loaded, `same` False says the faces are not the faces of the fluid's part, `gap` is how far its walls lie from the flow's."""
    role, dim, label = "structural", 3, "3D stress (stand-in)"

    def __init__(self, lie=1.0, edges=(0, 2, 3), same=True, gap=0.0):
        self.lie, self.edges, self.same, self.gap = lie, tuple(edges), same, gap
        self.cfd_force = None
        self.released = 0

    def release(self):
        self.released += 1

    def solve(self, temperature_at=None, cfd=None):
        self.cfd_force = None if cfd is None else cfd["info"].get("force")
        return {}

    def pressure_report(self):
        F = np.asarray(self.cfd_force, float) if self.cfd_force is not None else np.zeros(3)
        return {"edges": list(self.edges), "force": tuple(self.lie * F), "same_geometry": self.same, "differs": [] if self.same else [2], "gap": self.gap, "points": 100}


def exact(fl, th):
    """The wall temperature the stand-in solid and fluid (on the same mesh) must end at."""
    F = fl.operator()
    return np.linalg.solve(th.k_s * np.eye(len(F)) + th.lam * th.L + F, th.k_s * th.T_b + F @ np.full(len(F), fl.T_in))


def _row(rows, name, expected, got, ok):
    rows.append({"name": name, "expected": expected, "got": got, "ok": bool(ok)})


def rows_fluid3d(progress=None):
    """The rows of the self-check for a 3D flow: heat exchange with a solid, pressure on a stress analysis, and the checks the wrong way round."""
    rows = []
    OPT = {"conj_tol": 1e-8, "conj_max": 60}
    if progress:
        progress("3D fluid and solid exchanging heat", 0.5)
    fl, th = StandInFluid3D(5, c=0.3), StandInSolid3D(5, lam=4.0)
    res = ce.solve_coupled({"fluid": fl, "thermal": th}, OPT)
    Tx = exact(fl, th)
    span = float(np.ptp(Tx))
    f = res["fluid"]
    err = float(np.abs(f["history"][-1]["Tw_max"] - Tx.max()) + np.abs(f["history"][-1]["Tw_min"] - Tx.min())) / span
    _row(rows, "3D fluid and solid exchanging heat: the loop reaches the answer of the two problems as one system", "error below 1e-6 of the temperature range", f"{err:.1e} in {f['iterations']} iterations", err < 1e-6)
    hard = [c for c in res["checks"] if c["hard"]]
    _row(rows, "3D fluid and solid: the loop passes its own checks", "every check passes", f"{sum(c['ok'] for c in res['checks'])} of {len(res['checks'])}", res["ok"] and all(c["ok"] for c in res["checks"]) and len(hard) >= 3)
    _row(rows, "3D fluid and solid: the heat that leaves the solid is the heat the fluid takes", "equal", f"{f['Q_solid']:.6g} W and {f['Q_fluid']:.6g} W", abs(f["Q_solid"] - f["Q_fluid"]) < 1e-6 * abs(f["Q_fluid"]))
    ref = cf.solve_fluid_thermal3d(StandInFluid3D(7, c=0.3), StandInSolid3D(7), OPT)
    for ns in (4, 11):
        r = cf.solve_fluid_thermal3d(StandInFluid3D(7, c=0.3), StandInSolid3D(ns), OPT)
        d = float(np.abs(r["Tw"] - ref["Tw"]).max()) / float(np.ptp(ref["Tw"]))
        _row(rows, f"3D fluid and solid on different meshes ({ns} x {ns} nodes against 7 x 7): the same wall temperature", "within 3 % of the temperature range", f"{100 * d:.2g} %", d < 0.03 and abs(r["Q_rel"]) < r["q_tol"])
    fl3, th3 = StandInFluid3D(5, c=0.3, h_bias=3.0), StandInSolid3D(5, lam=4.0)
    r3 = cf.solve_fluid_thermal3d(fl3, th3, OPT)
    err3 = float(np.abs(r3["Tw"] - exact(fl3, th3)).max()) / float(np.ptp(exact(fl3, th3)))
    _row(rows, "3D fluid and solid: a heat transfer coefficient three times too large changes the speed, not the answer", "error below 1e-5", f"{err3:.1e} in {r3['iterations']} iterations (against {f['iterations']})", err3 < 1e-5)
    rl = ce.solve_coupled({"fluid": StandInFluid3D(5, c=0.3), "thermal": StandInSolid3D(5, lam=4.0, gap=0.9)}, OPT)
    wp = next(c for c in rl["checks"] if c["name"] == "Every wall point found")
    _row(rows, "3D fluid and solid: a wall that lies far from the wall of the other mesh is reported", "the check 'Every wall point found' fails and the result is refused", "failed" if not wp["ok"] and not rl["ok"] else "passed", not wp["ok"] and not rl["ok"])
    try:
        ce.solve_coupled({"fluid": StandInFluid3D(5, hf=lambda P: np.zeros(len(P))), "thermal": StandInSolid3D(5)}, OPT)
        caught = False
    except ce.CoupledError:
        caught = True
    _row(rows, "A 3D flow that does not touch the walls (no heat transfer coefficient) is refused", "an error in words", "refused" if caught else "accepted", caught)
    try:
        ce.solve_coupled({"fluid": StandInFluid3D(5, keys=()), "thermal": StandInSolid3D(5)}, OPT)
        caught = False
    except ce.CoupledError as ex:
        caught = "Wall of the thermal analysis" in str(ex)
    _row(rows, "A 3D flow with no wall of the thermal analysis is refused", "an error in words that names the condition", "refused" if caught else "accepted", caught)
    so4 = StandInSolid3D(5, lam=4.0)
    so4.heat_to_fluid = lambda: 0.5 * float(np.sum(so4.q * so4.A))
    r4 = ce.solve_coupled({"fluid": StandInFluid3D(5, c=0.3), "thermal": so4}, OPT)
    bal = next(c for c in r4["checks"] if c["name"].startswith("Heat leaving the solid"))
    _row(rows, "A 3D solid that reports half of its heat is caught", "the check 'Heat leaving the solid = heat entering the fluid' fails", "failed" if not bal["ok"] else "passed", not bal["ok"])
    r5 = ce.solve_coupled({"fluid": StandInFluid3D(5, c=0.3, status="max_steps"), "thermal": StandInSolid3D(5, lam=4.0)}, OPT)
    fs = next(c for c in r5["checks"] if c["name"] == "Flow settled")
    _row(rows, "A 3D flow that did not settle is reported", "the check 'Flow settled' fails", "failed" if not fs["ok"] else "passed", not fs["ok"])
    r6 = ce.solve_coupled({"fluid": StandInFluid3D(5, c=0.3), "thermal": StandInSolid3D(5, lam=4.0)}, {"conj_tol": 1e-8, "conj_max": 1})
    cv = next(c for c in r6["checks"] if c["name"] == "Heat exchange converged")
    _row(rows, "A 3D heat exchange that does not settle is refused", "the check 'Heat exchange converged' fails and the result is refused", "failed" if not cv["ok"] and not r6["ok"] else "passed", not cv["ok"] and not r6["ok"])
    # the pressure on a 3D stress analysis
    if progress:
        progress("3D fluid pressure on a stress analysis", 0.6)
    rp = ce.solve_coupled({"fluid": StandInFluid3D(5), "structural": StandInStructural3D()})
    pc = next(c for c in rp["checks"] if c["name"] == "Pressure force handed over")
    _row(rows, "3D fluid pressure on a stress analysis: the force carried is the force pushed with", "difference below 2 % of the load", pc["detail"].split("(difference")[1].split(",")[0].strip() if "(difference" in pc["detail"] else pc["detail"][:60], pc["ok"] and rp["ok"])
    rl = ce.solve_coupled({"fluid": StandInFluid3D(5), "structural": StandInStructural3D(lie=0.5)})
    pl = next(c for c in rl["checks"] if c["name"] == "Pressure force handed over")
    _row(rows, "A 3D stress analysis that carries half of the pressure force is caught", "the check 'Pressure force handed over' fails and the result is refused", "failed" if not pl["ok"] and not rl["ok"] else "passed", not pl["ok"] and not rl["ok"])
    rs = ce.solve_coupled({"fluid": StandInFluid3D(5), "structural": StandInStructural3D(same=False)})
    sw = next((c for c in rs["checks"] if c["name"] == "Same walls in both analyses"), None)
    _row(rows, "A 3D stress analysis whose faces are not the fluid's faces is caught", "the check 'Same walls in both analyses' fails and the result is refused", "failed" if sw is not None and not sw["ok"] and not rs["ok"] else "passed", sw is not None and not sw["ok"] and not rs["ok"])
    rg = ce.solve_coupled({"fluid": StandInFluid3D(5), "structural": StandInStructural3D(gap=0.9)})
    gw = next(c for c in rg["checks"] if c["name"] == "Every wall point found")
    _row(rows, "A 3D stress analysis that lies away from the flow's wall is reported", "the check 'Every wall point found' fails and the result is refused", "failed" if not gw["ok"] and not rg["ok"] else "passed", not gw["ok"] and not rg["ok"])
    try:
        ce.solve_coupled({"fluid": StandInFluid3D(5), "structural": StandInStructural3D(edges=())})
        _row(rows, "A 3D stress analysis that got no pressure at all is refused", "an error in words", "accepted", False)
    except ce.CoupledError as ex:
        _row(rows, "A 3D stress analysis that got no pressure at all is refused", "an error in words", "refused: " + str(ex)[:60], True)
    try:
        from coupled_check import StandInStructural
        ce.solve_coupled({"fluid": StandInFluid3D(5), "structural": StandInStructural()})
        _row(rows, "A 3D flow with a 2D stress analysis is refused", "an error in words", "accepted", False)
    except ce.CoupledError as ex:
        _row(rows, "A 3D flow with a 2D stress analysis is refused", "an error in words", "refused: " + str(ex)[:60], True)
    return rows
