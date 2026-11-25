"""
physics_cfd_heat.py - the temperature of the fluid in the 2D CFD (forced convection), no Qt.

The flow is solved first (physics_cfd.solve) and does not depend on the temperature: the fluid's properties are constant and there is no buoyancy, so the temperature is
a PASSIVE scalar that the converged velocity field carries,

        rho cp (u . grad T)  =  div (k grad T)

solved on the mesh of the flow with the same quadratic elements and streamline-diffusion stabilisation as the momentum equation, in one sparse solve.  A change of the
wall temperatures, of the inlet temperature or of the heat flux therefore costs one cheap solve, not a new flow - which is what the conjugate loop with a Thermal analysis
(coupled_engine) does again and again.  Because the equation is linear in T - T_inlet, the heat transfer coefficient h = q / (T_wall - T_inlet) of an isothermal wall is
a property of the flow alone (`heat_transfer_coefficient`).

Conditions
    inlet sides      the inlet temperature `T_in` (kelvin)
    outlet sides     nothing: the temperature is carried out (zero diffusive flux)
    slip sides       insulated
    body walls       insulated unless a condition says otherwise
        {"kind": "temp", "T": kelvin | callable(points in sketch units, (n, 2)) -> kelvin (n,)}      a fixed wall temperature [Dirichlet]
        {"kind": "flux", "q": W/m2 | callable(points) -> W/m2}                                          a heat flux INTO the fluid [Neumann]

Heat flows are in watts per metre of depth (the CFD is per unit depth) and heat fluxes in W/m2.  The heat that leaves a temperature wall is the REACTION of the discrete
equations at its nodes, so the sum over all walls is exactly the heat the fluid carries away (the energy balance in the result is the check of that, and of the flow's own
mass balance: a flow that is not divergence-free pollutes it).
"""
import math

import numpy as np

import physics_cfd as pcfd
import physics_solve as psolve


class HeatError(pcfd.ModelError):
    """A temperature problem the user can fix (in words)."""


def scalar_matrix(disc, a6, alpha):
    """Operator of  a . grad T - alpha lap T  (per unit rho cp): convection + diffusion + streamline diffusion, quadratic elements.  a6 = the velocity at the six nodes of every
    element (M, 6, 2); alpha = k / (rho cp)."""
    aq = np.einsum("qm,emc->eqc", disc.Nq, a6)
    adv = aq[:, :, 0, None] * disc.dNx + aq[:, :, 1, None] * disc.dNy
    Ce = np.einsum("eq,qm,eqn->emn", disc.wA, disc.Nq, adv, optimize=True)
    speed = np.sqrt((aq ** 2).sum(axis=2))
    h = disc.h[:, None]
    tau = 1.0 / np.sqrt((2.0 * speed / h) ** 2 + (4.0 * alpha / h ** 2) ** 2)
    Se = np.einsum("eq,eqm,eqn->emn", disc.wA * tau, adv, adv, optimize=True)
    return disc.scatter(alpha * disc.Ke + Ce + Se)


def scalar_solve(disc, A, dir_nodes, dir_vals, rhs=None):
    """T with T[dir_nodes] = dir_vals and  A T = rhs  at every other node.  -> (T (Nu,), reaction at the Dirichlet nodes  A T - rhs)."""
    import scipy.sparse as sp
    n = A.shape[0]
    rhs = np.zeros(n) if rhs is None else np.asarray(rhs, float)
    dir_nodes = np.asarray(dir_nodes, dtype=np.int64)
    fixed = np.zeros(n, dtype=bool)
    fixed[dir_nodes] = True
    T = np.zeros(n)
    T[dir_nodes] = dir_vals
    free = np.nonzero(~fixed)[0]
    if len(free):
        Af = A[free][:, free].tocsc()
        bf = rhs[free] - A[free][:, dir_nodes] @ np.asarray(dir_vals, float)
        T[free] = psolve.solve(Af, bf)
    if not np.all(np.isfinite(T)):
        raise HeatError("The temperature solve gave no finite result (the matrix is singular or ill-conditioned).")
    react = (A @ T - rhs)[dir_nodes]
    return T, react


# ----------------------------------------------------------------------------------------------------------------------------- the wall pieces
def _line_mass(L):
    """Mass matrix of a quadratic line element of length L (nodes a, mid, b): (3, 3)."""
    return (L / 30.0) * np.array([[4.0, 2.0, -1.0], [2.0, 16.0, 2.0], [-1.0, 2.0, 4.0]])


class _Wall:
    """The mesh segments of one wall edge: corner nodes, mid nodes, lengths in metres, and the matrices to turn a nodal reaction into a flux."""

    def __init__(self, disc, mesh, segs):
        arr = np.asarray(segs, dtype=np.int64)
        self.na, self.nb = arr[:, 0], arr[:, 1]
        self.nm = disc.mid_of(self.na, self.nb)
        self.L = np.hypot(*(disc.xy[self.nb] - disc.xy[self.na]).T)
        self.nodes = np.unique(np.concatenate([self.na, self.nb, self.nm]))
        pos = {int(n): i for i, n in enumerate(self.nodes)}
        self.idx = np.array([[pos[int(a)], pos[int(m)], pos[int(b)]] for a, m, b in zip(self.na, self.nm, self.nb)], dtype=np.int64)
        import scipy.sparse as sp
        k = len(self.nodes)
        rows = np.broadcast_to(self.idx[:, :, None], (len(self.na), 3, 3)).ravel()
        cols = np.broadcast_to(self.idx[:, None, :], (len(self.na), 3, 3)).ravel()
        Me = np.stack([_line_mass(L) for L in self.L])
        self.M = sp.coo_matrix((Me.ravel(), (rows, cols)), shape=(k, k)).tocsc()
        self.Me = Me

    def load(self, qn):
        """The load vector of a flux given at the wall nodes (len(self.nodes),) -> (Nu-sized contributions as (node numbers, values))."""
        q3 = qn[self.idx]                                                    # (E, 3)
        f = np.einsum("eij,ej->ei", self.Me, q3)
        out = np.zeros(len(self.nodes))
        np.add.at(out, self.idx.ravel(), f.ravel())
        return out

    def flux_from_reaction(self, react_nodes):
        """The nodal flux whose integral over the wall is the reaction at every node (the consistent flux): M q = R."""
        import scipy.sparse.linalg as spla
        return spla.splu(self.M).solve(react_nodes)


def _values_at(spec, pts_sketch, what):
    """A number, or a callable of the points in sketch units, evaluated at (n, 2) points -> (n,)."""
    if callable(spec):
        v = np.asarray(spec(np.asarray(pts_sketch, float)), float).reshape(-1)
        if len(v) != len(pts_sketch) or not np.all(np.isfinite(v)):
            raise HeatError(f"The {what} given for a wall is not a finite number at every point of it.")
        return v
    return np.full(len(pts_sketch), float(spec))


# ----------------------------------------------------------------------------------------------------------------------------- the solve
def solve_temperature(mesh, res, heat, cancel=None):
    """The temperature of the fluid for the converged flow `res` (physics_cfd.solve) on its mesh.

    heat = {"k": W/(m K), "cp": J/(kg K), "T_in": kelvin, "walls": {edge key (kind, id): {"kind": "temp", "T": ...} | {"kind": "flux", "q": ...}}}
    -> {"T": (Nu,) kelvin at every node (corners first, then the mid nodes: the layout of res["u"]), "alpha", "Pr", "Tmin", "Tmax", "T_in", "k", "cp",
        "walls": {key: {"kind", "T_a", "T_m", "T_b", "q_a", "q_m", "q_b" (per mesh segment, in the order of mesh["wall_segs"][key]), "Q" (W/m into the fluid), "T_min", "T_max"}},
        "balance": {"walls", "advected", "relative", "inlet"}, "notes": [...]}.
    Only the boundary quantities are added to res["walls"][key] (as "T_a", "T_b", "q_a", "q_b" ...) by `attach`."""
    k, cp, T_in = float(heat["k"]), float(heat["cp"]), float(heat["T_in"])
    rho = float(res["rho"])
    if k <= 0 or cp <= 0:
        raise HeatError("The conductivity and the specific heat of the fluid must be greater than zero.")
    if T_in <= 0:
        raise HeatError("The inlet temperature must be above 0 K.")
    alpha = k / (rho * cp)
    disc = pcfd.Disc(mesh["nodes"], mesh["tris"], res["lscale"])
    Nu, Nv = disc.Nu, disc.Nv
    u = np.asarray(res["u"], float)
    if u.shape[0] != Nu:
        raise HeatError("The flow result does not belong to this mesh (a different number of nodes): solve the flow again.")
    if cancel and cancel():
        raise pcfd.Cancelled()
    notes = []
    A = scalar_matrix(disc, u[disc.tri6], alpha)
    rhs = np.zeros(Nu)
    dir_val = {}                                                               # node -> value
    kinds = res["sides"]
    for side in pcfd.SIDES:
        if kinds[side] == "inlet":
            for n in disc.segment_nodes(mesh["box_segs"][side]):
                dir_val[int(n)] = T_in
    walls, wall_dir, wall_flux = {}, {}, {}
    for key, spec in (heat.get("walls") or {}).items():
        key = tuple(key)
        segs = mesh["wall_segs"].get(key)
        if not segs:
            notes.append(f"The condition on {key[0]} {key[1]} has no wall in the mesh (is that body switched on?).")
            continue
        walls[key] = _Wall(disc, mesh, segs)
        w = walls[key]
        pts = disc.xy_sketch[w.nodes]
        if spec["kind"] == "temp":
            Tn = _values_at(spec["T"], pts, "temperature")
            if np.any(Tn <= 0):
                raise HeatError("A wall temperature must be above 0 K.")
            wall_dir[key] = Tn
            for n, v in zip(w.nodes, Tn):
                dir_val[int(n)] = float(v)                                     # a wall that meets the inlet or another wall takes the later value
        elif spec["kind"] == "flux":
            qn = _values_at(spec["q"], pts, "heat flux")
            wall_flux[key] = qn
            rhs[w.nodes] += w.load(qn) / (rho * cp)
        else:
            raise HeatError(f"Unknown wall condition '{spec.get('kind')}'.")
    if not dir_val:
        raise HeatError("The fluid has no temperature condition: it needs an inlet (the wind) or a wall at a fixed temperature.")
    dn = np.array(sorted(dir_val), dtype=np.int64)
    dv = np.array([dir_val[int(n)] for n in dn])
    T, react = scalar_solve(disc, A, dn, dv, rhs)
    if cancel and cancel():
        raise pcfd.Cancelled()
    rpos = {int(n): i for i, n in enumerate(dn)}
    out_walls = {}
    allkeys = list(mesh["wall_segs"].keys())
    # The heat that the walls of fixed temperature give: the reaction at a node is what comes through the whole of its wall, and a node where two such walls meet (a corner) has the
    # reaction of both.  The flux is therefore found on all of them at once (M q = R on the union of their nodes) and every wall takes its own part of it: the heat of a wall is the
    # integral of its flux, and the walls add up to the sum of the reactions, with no corner counted twice.
    qdir = {}
    dkeys = [kk for kk in allkeys if kk in wall_dir and mesh["wall_segs"].get(kk)]
    if dkeys:
        import scipy.sparse as sp
        import scipy.sparse.linalg as spla
        un = np.unique(np.concatenate([walls[kk].nodes for kk in dkeys]))
        upos = {int(n): i for i, n in enumerate(un)}
        Mu = sp.csc_matrix((len(un), len(un)))
        for kk in dkeys:
            w = walls[kk]
            ix = np.array([upos[int(n)] for n in w.nodes], dtype=np.int64)
            C = sp.csc_matrix((np.ones(len(ix)), (ix, np.arange(len(ix)))), shape=(len(un), len(ix)))
            Mu = Mu + C @ w.M @ C.T
        Ru = np.array([react[rpos[int(n)]] for n in un]) * rho * cp                     # heat into the fluid at every node (W per metre of depth)
        qu = spla.splu(Mu.tocsc()).solve(Ru)
        for kk in dkeys:
            qdir[kk] = qu[np.array([upos[int(n)] for n in walls[kk].nodes], dtype=np.int64)]
    for key in allkeys:
        segs = mesh["wall_segs"].get(key)
        if not segs:
            continue
        w = walls.get(key) or _Wall(disc, mesh, segs)
        if key in wall_dir:
            qn = qdir[key]
            Q = float(w.load(qn).sum())
            kind = "temp"
        elif key in wall_flux:
            qn = wall_flux[key]
            Q = float(w.load(qn).sum())
            kind = "flux"
        else:
            qn = np.zeros(len(w.nodes))
            Q = 0.0
            kind = "insulated"
        Tn = T[w.nodes]
        idx = w.idx
        out_walls[key] = {"kind": kind, "T_a": Tn[idx[:, 0]], "T_m": Tn[idx[:, 1]], "T_b": Tn[idx[:, 2]],
                          "q_a": qn[idx[:, 0]], "q_m": qn[idx[:, 1]], "q_b": qn[idx[:, 2]], "Q": Q,
                          "T_min": float(Tn.min()), "T_max": float(Tn.max()), "L": w.L}
    # energy balance: the heat that the walls give to the fluid against the enthalpy that the flow carries out (relative to the inlet temperature)
    flux = 0.0
    inlet_heat = 0.0
    for side in pcfd.SIDES:
        segs = mesh["box_segs"][side]
        if not segs:
            continue
        arr = np.asarray(segs, dtype=np.int64)
        na, nb = arr[:, 0], arr[:, 1]
        mid = disc.mid_of(na, nb)
        n = np.array(pcfd.SIDE_NORMAL[side])
        L = np.hypot(*(mesh["nodes"][nb] - mesh["nodes"][na]).T) * res["lscale"]
        fa, fm, fb = [(T[i] - T_in) * (u[i] @ n) for i in (na, mid, nb)]
        flux += float(np.sum(L / 6.0 * (fa + 4.0 * fm + fb)))
    advected = rho * cp * flux
    walls_total = float(sum(v["Q"] for v in out_walls.values()))
    # the heat the inlet itself gives (a Dirichlet inlet whose temperature is the reference one gives none; a reaction there means the flow is not divergence-free)
    for side in pcfd.SIDES:
        if kinds[side] == "inlet":
            nn = disc.segment_nodes(mesh["box_segs"][side])
            inlet_heat += float(sum(react[rpos[int(i)]] for i in nn)) * rho * cp
    scale = max(abs(walls_total), abs(advected), 1e-300)
    bal = {"walls": walls_total, "advected": advected, "inlet": inlet_heat, "relative": (advected - walls_total) / scale if scale > 1e-290 else 0.0}
    # a temperature outside the given ones is what a mesh too coarse for the gradient does (a flux wall sets no bound, so this check is for fixed temperatures only)
    over = None
    if not wall_flux:
        lo, hi = float(dv.min()), float(dv.max())
        over = max(0.0, lo - float(T.min()), float(T.max()) - hi)
        if hi > lo and over > 0.02 * (hi - lo):
            notes.append(f"The temperature leaves the range of the given temperatures by {over:.3g} K ({100.0 * over / (hi - lo):.1f} % of that range): "
                         "the mesh is too coarse for this temperature gradient (make it finer at the walls).")
    return {"T": T, "alpha": alpha, "Pr": res["mu"] * cp / k, "Tmin": float(T.min()), "Tmax": float(T.max()), "T_in": T_in, "k": k, "cp": cp,
            "walls": out_walls, "balance": bal, "notes": notes, "overshoot": over}


def attach(res, hres):
    """Puts a temperature result into a flow result: res["heat"] and the wall tables' T and q (per segment ends), so that everything that reads the wall tables sees them."""
    res["heat"] = hres
    for key, tb in hres["walls"].items():
        t = res["walls"].get(key)
        if t is None:
            continue
        t["T_a"], t["T_b"], t["T_m"] = tb["T_a"], tb["T_b"], tb["T_m"]
        t["q_a"], t["q_b"], t["q_m"] = tb["q_a"], tb["q_b"], tb["q_m"]
        t["heat_kind"] = tb["kind"]
    return res


def heat_transfer_coefficient(mesh, res, heat, dT=1.0):
    """h(s) of the wet walls: the flow carries a unit temperature difference, every wall in `heat["walls"]`... is held at T_in + dT, every other wall is insulated, and
    h = q / dT.  -> {key: (h_a, h_m, h_b)} per mesh segment, W/(m2 K).  (Linear: dT does not matter.)  `heat["walls"]` names the walls that are wanted."""
    walls = {tuple(k): {"kind": "temp", "T": float(heat["T_in"]) + dT} for k in heat["walls"]}
    h2 = {"k": heat["k"], "cp": heat["cp"], "T_in": heat["T_in"], "walls": walls}
    r = solve_temperature(mesh, res, h2)
    return {k: (v["q_a"] / dT, v["q_m"] / dT, v["q_b"] / dT) for k, v in r["walls"].items() if k in walls}, r


# ----------------------------------------------------------------------------------------------------------------------------- a profile along the walls
class WallProfile:
    """A quantity known along the wall segments of a flow mesh (per segment: value at corner a, mid, corner b), evaluated at any point near the walls: the segment nearest
    to the point is found and the quadratic interpolation along it is used.  `points` are in sketch units (the mesh's), like the mesh.
    Used by the conjugate loop to hand the heat flux or the wall temperature to another mesh; the distance to the wall is reported so that a profile that does not fit is
    seen (a thermal edge that has no fluid wall near it)."""

    def __init__(self, mesh, keys, values):
        """keys = the wall edges to use; values = {key: (v_a, v_m, v_b)} (each (E,))."""
        from scipy.spatial import cKDTree
        P = np.asarray(mesh["nodes"], float)
        A, B, V0, V1, V2 = [], [], [], [], []
        for key in keys:
            segs = mesh["wall_segs"].get(tuple(key))
            if not segs:
                continue
            arr = np.asarray(segs, dtype=np.int64)
            va, vm, vb = values[tuple(key)]
            A.append(P[arr[:, 0]])
            B.append(P[arr[:, 1]])
            V0.append(np.asarray(va, float))
            V1.append(np.asarray(vm, float))
            V2.append(np.asarray(vb, float))
        if not A:
            raise HeatError("None of the walls has a segment in the mesh.")
        self.A, self.B = np.vstack(A), np.vstack(B)
        self.V0, self.V1, self.V2 = np.concatenate(V0), np.concatenate(V1), np.concatenate(V2)
        self.mid = 0.5 * (self.A + self.B)
        self.len = np.hypot(*(self.B - self.A).T)
        self.tree = cKDTree(self.mid)
        self.h = float(np.median(self.len))

    def at(self, points, k=8):
        """-> (values (n,), gap (n,) = distance from the point to the segment used, in sketch units)."""
        X = np.asarray(points, float).reshape(-1, 2)
        k = min(k, len(self.mid))
        _d, cand = self.tree.query(X, k=k)
        cand = np.asarray(cand).reshape(len(X), -1)
        best_gap = np.full(len(X), np.inf)
        best_t = np.zeros(len(X))
        best_i = np.zeros(len(X), dtype=np.int64)
        for j in range(cand.shape[1]):
            i = cand[:, j]
            ab = self.B[i] - self.A[i]
            ll = np.maximum((ab ** 2).sum(axis=1), 1e-300)
            t = np.clip(((X - self.A[i]) * ab).sum(axis=1) / ll, 0.0, 1.0)
            foot = self.A[i] + t[:, None] * ab
            gap = np.hypot(*(X - foot).T)
            better = gap < best_gap
            best_gap[better], best_t[better], best_i[better] = gap[better], t[better], i[better]
        t, i = best_t, best_i
        l0, l1, l2 = (1.0 - t) * (1.0 - 2.0 * t), 4.0 * t * (1.0 - t), t * (2.0 * t - 1.0)         # quadratic Lagrange on t = 0, 1/2, 1
        return l0 * self.V0[i] + l1 * self.V1[i] + l2 * self.V2[i], best_gap
