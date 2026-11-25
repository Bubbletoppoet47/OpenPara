"""thermal_fem.py - 2D heat conduction by finite elements (no Qt).  Steady or transient; conduction, convection and radiation.

  * 6-node (quadratic) or 3-node (linear) triangles on the gmsh mesh of physics_geom (the mid-edge nodes are added here, as in the 2D FEA)
  * the body is a plate of thickness t (the depth): every heat flow in the results is in watts through that depth
  * one material per region (conductivity k, density rho, specific heat cp), isotropic and constant: nothing depends on the temperature
  * heat generation per region (W/m3)
  * conditions on points and sketch edges:
        temp   a fixed temperature (points or edges)                    [Dirichlet]
        flux   a heat flux INTO the body on edges, W/m2                  [Neumann]; zero everywhere else = insulated
        ins    insulated edges: no heat through them (the same as a heat flux of zero; it only makes the choice visible and checked)
        power  a heat flow into the body at points, W (total through the depth)
        conv   convection to a fluid at T_inf with coefficient h:   q_out = h (T - T_inf)
        fluid  the same with h and T_inf given at every point of the edge by functions of the point (the exchange with a flowing fluid in Coupled Physics)
        rad    radiation to surroundings at T_s with emissivity eps: q_out = eps sigma (T^4 - T_s^4)      (NOT between surfaces of the model:
               that needs view factors, which this version does not have)
  * optional heat loss from the two flat faces of the plate: convection and / or radiation, both faces, over the whole area
  * steady: one solve, or Newton's method when there is radiation (the line search keeps every temperature above zero kelvin)
  * transient: the theta method (theta = 1 backward Euler, 1/2 Crank-Nicolson) with a constant step, Newton inside each step when there is radiation;
    the conditions are constant in time and the start is one uniform temperature
  * nothing is averaged: the heat flux is the raw element value, at the four stress points of a quadratic triangle (as the 2D FEA does)

Everything inside is SI and ABSOLUTE temperature (kelvin).  Sketch lengths are converted with `lscale` (metres per sketch unit).
Heat flow signs: a temperature condition's flow is positive when it feeds heat INTO the body.

The checks behind the numbers (test_thermal_fem.py): exact integration rules, a linear temperature field reproduced exactly, 1-D slab, layered wall, hollow
cylinder, fin, 2-D rectangle and a transient slab against their closed forms, radiation against its closed form and against the linearised
convection, energy balance, and the same problem in either element order and any refinement.
"""
import time
import warnings

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.sparse.csgraph import connected_components

import physics_fea as pf
import physics_solve as psolve

SIGMA = 5.670374419e-8                      # W/(m2 K4)
ModelError = pf.ModelError                  # the shared task thread (physics_tab.TaskWorker) shows these as messages, not as bugs
Cancelled = pf.Cancelled

SUB_TRIS = pf.SUB_TRIS
STRESS_POINTS = np.array([[2 / 3, 1 / 6, 1 / 6], [1 / 6, 2 / 3, 1 / 6], [1 / 6, 1 / 6, 2 / 3], [1 / 3, 1 / 3, 1 / 3]])   # centres of the 4 small triangles

# ------------------------------------------------------------------------------------------------------------------- integration rules
_A4, _B4 = 0.445948490915965, 0.091576213509771
RULE2 = (np.array([[1 / 6, 1 / 6, 2 / 3], [1 / 6, 2 / 3, 1 / 6], [2 / 3, 1 / 6, 1 / 6]]), np.full(3, 1.0 / 3.0))               # exact to degree 2
RULE4 = (np.array([[_A4, _A4, 1 - 2 * _A4], [_A4, 1 - 2 * _A4, _A4], [1 - 2 * _A4, _A4, _A4],
                   [_B4, _B4, 1 - 2 * _B4], [_B4, 1 - 2 * _B4, _B4], [1 - 2 * _B4, _B4, _B4]]),
         np.array([0.223381589678011] * 3 + [0.109951743655322] * 3))                                                             # exact to degree 4
RULE1 = (np.array([[1 / 3, 1 / 3, 1 / 3]]), np.array([1.0]))
_gx, _gw = np.polynomial.legendre.leggauss(6)
GAUSS_EDGE = ((_gx + 1.0) / 2.0, _gw / 2.0)                                                                                         # on [0, 1]; exact to degree 11


def shape(order, L):
    """Shape functions (n,) and their derivatives with respect to the three area coordinates (n, 3) at area coordinates L."""
    l1, l2, l3 = L
    if order == 1:
        return np.array([l1, l2, l3]), np.eye(3)
    return np.array([l1 * (2 * l1 - 1), l2 * (2 * l2 - 1), l3 * (2 * l3 - 1), 4 * l1 * l2, 4 * l2 * l3, 4 * l3 * l1]), pf.t6_dN(L)


def edge_shape(order, xi):
    """Shape functions along a boundary edge at xi in [0, 1] (node a at 0, node b at 1): (len(xi), n) in the order a, b[, mid]."""
    xi = np.asarray(xi, float)
    if order == 1:
        return np.stack([1 - xi, xi], axis=1)
    return np.stack([(1 - xi) * (1 - 2 * xi), xi * (2 * xi - 1), 4 * xi * (1 - xi)], axis=1)


class _Geo:
    """Areas and the gradient operators of the straight-sided triangles (corner nodes only), in metres."""

    def __init__(self, nodes_m, conn):
        p = nodes_m[conn[:, :3]]
        x, y = p[:, :, 0], p[:, :, 1]
        self.b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
        self.c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
        self.A = 0.5 * ((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
        if np.any(self.A <= 0):
            raise ModelError("The mesh has zero-area or inverted triangles.")

    def grads(self, dN):
        inv = 1.0 / (2.0 * self.A)
        return (dN @ self.b.T).T * inv[:, None], (dN @ self.c.T).T * inv[:, None]


def _csr(conn, Ke, n):
    k = conn.shape[1]
    I = np.repeat(conn[:, :, None], k, axis=2).ravel()
    J = np.repeat(conn[:, None, :], k, axis=1).ravel()
    return sp.coo_matrix((Ke.ravel(), (I, J)), shape=(n, n)).tocsr()


def _rule_for(order, degree):
    if order == 1 and degree <= 1:
        return RULE1
    return RULE2 if degree <= 2 else RULE4


def stiffness(geo, conn, order, kt, n):
    """The conduction matrix: integral of k t grad N . grad N over every triangle."""
    pts, w = RULE1 if order == 1 else RULE2
    Ke = np.zeros((len(conn), conn.shape[1], conn.shape[1]))
    for L, wg in zip(pts, w):
        gx, gy = geo.grads(shape(order, L)[1])
        Ke += wg * (gx[:, :, None] * gx[:, None, :] + gy[:, :, None] * gy[:, None, :])
    return _csr(conn, Ke * (geo.A * kt)[:, None, None], n)


def area_matrix(geo, conn, order, c, n):
    """Integral of c N N^T over every triangle (c per element): the heat capacity (c = rho cp t) and the flat-face convection (c = 2 h)."""
    pts, w = RULE2 if order == 1 else RULE4
    Me = np.zeros((conn.shape[1], conn.shape[1]))
    for L, wg in zip(pts, w):
        N = shape(order, L)[0]
        Me += wg * np.outer(N, N)
    return _csr(conn, (geo.A * c)[:, None, None] * Me[None], n)


def area_vector(geo, conn, order, c, n):
    """Integral of c N over every triangle (c per element): heat generation (c = q''' t) and the flat-face ambient term (c = 2 h T_inf)."""
    pts, w = RULE2 if order == 1 else RULE4
    Ne = np.zeros(conn.shape[1])
    for L, wg in zip(pts, w):
        Ne += wg * shape(order, L)[0]
    fe = (geo.A * c)[:, None] * Ne[None]
    out = np.zeros(n)
    np.add.at(out, conn.ravel(), fe.ravel())
    return out


class _Edges:
    """The boundary element edges of one condition: corner nodes a, b, the mid node (quadratic), the lengths in metres."""

    def __init__(self, segs, nodes_m, mid, order):
        a = np.array([s[0] for s in segs], dtype=np.int64)
        b = np.array([s[1] for s in segs], dtype=np.int64)
        self.order = order
        self.L = np.hypot(*(nodes_m[b] - nodes_m[a]).T)
        cols = [a, b]
        if order == 2:
            cols.append(np.array([mid[(min(int(x), int(y)), max(int(x), int(y)))] for x, y in zip(a, b)], dtype=np.int64))
        self.conn = np.stack(cols, axis=1)
        xi, w = GAUSS_EDGE
        self.Ng = edge_shape(order, xi)                     # (G, n)
        self.wg = w
        self.n = self.conn.shape[1]
        # the integral of N over the edge divided by L, and of N N^T divided by L
        xi2, w2 = GAUSS_EDGE
        N2 = edge_shape(order, xi2)
        self.int_N = w2 @ N2
        self.int_NN = np.einsum("g,gi,gj->ij", w2, N2, N2)

    def __len__(self):
        return len(self.L)

    def interp(self, T):
        """Temperature at the Gauss points of every edge: (E, G)."""
        return T[self.conn] @ self.Ng.T


# ------------------------------------------------------------------------------------------------------------------- the model
class Model:
    """Everything that does not change during the solve: matrices K (conduction + convection), M (heat capacity), the load vector F,
    and the radiating edges / faces."""

    def __init__(self, mesh, setup, cancel=None, progress=None):
        self.notes = []
        self._owner = None
        self.setup = setup
        self.order = 2 if setup.get("order", 2) == 2 else 1
        ls = float(setup["lscale"])
        self.t = float(setup["t"])
        if not (self.t > 0):
            raise ModelError("The thickness (depth) must be greater than zero.")
        nodes, tris = np.asarray(mesh["nodes"], float), np.asarray(mesh["tris"])
        if self.order == 2:
            nodes_all, conn, mid = pf.add_midnodes(nodes, tris)
        else:
            nodes_all, conn, mid = nodes, tris, None
        self.nodes_all, self.conn, self.mid, self.mesh = nodes_all, conn, mid, mesh
        self.nodes_m = nodes_all * ls
        self.N = len(nodes_all)
        self.geo = _Geo(self.nodes_m, conn)
        M_ = len(conn)
        tf = np.asarray(mesh.get("tri_face", np.zeros(M_, dtype=np.int64)))
        base = setup["mat"]
        rm = setup.get("region_mats") or {}
        qv = setup.get("region_q") or {}
        self.k_el = np.array([float((rm.get(int(f)) or base)["k"]) for f in tf])
        self.rho_el = np.array([float((rm.get(int(f)) or base)["rho"]) for f in tf])
        self.cp_el = np.array([float((rm.get(int(f)) or base)["cp"]) for f in tf])
        self.qv_el = np.array([float(qv.get(int(f), 0.0) or 0.0) for f in tf])
        if np.any(self.k_el <= 0):
            raise ModelError("The conductivity must be greater than zero (every region).")
        if np.any(self.rho_el <= 0) or np.any(self.cp_el <= 0):
            raise ModelError("The density and the specific heat must be greater than zero (every region).")
        t = self.t
        n = self.N
        self.K = stiffness(self.geo, conn, self.order, self.k_el * t, n)
        self.M = area_matrix(self.geo, conn, self.order, self.rho_el * self.cp_el * t, n)
        self.F = area_vector(self.geo, conn, self.order, self.qv_el * t, n)
        self.region_gen = float(np.sum(self.qv_el * t * self.geo.A))                  # total heat generated, W
        self.ground = np.zeros(n, dtype=bool)               # nodes that a convection / radiation condition ties to the surroundings
        self.dirichlet = {}                                  # node -> (K, condition index)
        self.conds = []                                      # per condition: dict with what is needed to report it afterwards
        self.rad = []                                        # [(edges, coef (E,), Ts)]
        self.face_rad = None
        self._conditions(mesh, setup)
        self._faces(setup)
        self.dir_nodes = np.array(sorted(self.dirichlet), dtype=np.int64)
        self.dir_vals = np.array([self.dirichlet[i][0] for i in self.dir_nodes])
        self.free = np.setdiff1d(np.arange(n), self.dir_nodes)
        self.has_rad = bool(self.rad) or self.face_rad is not None

    # ---- conditions
    def _edges(self, kind, targets, mesh):
        if self._owner is None:
            self._owner = pf.edge_owner(mesh["tris"])
        owner = self._owner
        segs, notes = [], []
        for tk, ti in targets:
            ss = mesh["curve_segs"].get((tk, ti), [])
            if not ss:
                notes.append(f"{kind} on {tk} {ti}: no mesh edges there (is its region switched on?).")
            for na, nb in ss:
                if len(owner.get((min(na, nb), max(na, nb)), [])) != 1:
                    notes.append(f"{kind} on {tk} {ti}: an element edge inside the material (shared by two regions) was skipped.")
                    continue
                segs.append((na, nb))
        self.notes += list(dict.fromkeys(notes))
        return segs

    def _conditions(self, mesh, setup):
        for ci, c in enumerate(setup.get("conds") or []):
            kind = c["kind"]
            rec = {"index": ci, "kind": kind, "name": c.get("name") or f"{kind} {ci + 1}"}
            targets = [tuple(x) for x in c["targets"]]
            if kind == "temp":
                nds = set()
                for tk, ti in targets:
                    ns = pf.entity_nodes(mesh, tk, ti, self.mid)
                    if not ns:
                        self.notes.append(f"Temperature on {tk} {ti}: no mesh nodes there (is its region switched on?).")
                    nds |= set(ns)
                for nd in sorted(nds):
                    prev = self.dirichlet.get(nd)
                    if prev is not None and abs(prev[0] - c["T"]) > 1e-9:
                        self.notes.append("Two temperature conditions with different values meet at a node: the later one is used there.")
                    self.dirichlet[nd] = (float(c["T"]), ci)
                rec["T"] = float(c["T"])
            elif kind == "power":
                nds = []
                for tk, ti in targets:
                    nds += pf.entity_nodes(mesh, tk, ti)
                if not nds:
                    self.notes.append("Heat flow on a point: no mesh node there.")
                for nd in nds:
                    self.F[nd] += float(c["P"])
                rec.update(P=float(c["P"]) * len(nds))
            else:
                segs = self._edges({"flux": "Heat flux", "conv": "Convection", "fluid": "Fluid exchange", "rad": "Radiation", "ins": "Insulated"}[kind], targets, mesh)
                if not segs:
                    rec["edges"] = None
                    self.conds.append(rec)
                    continue
                ed = _Edges(segs, self.nodes_m, self.mid, self.order)
                rec["edges"] = ed
                tt = self.t
                if kind == "ins":
                    pass                                                  # nothing is added: an edge without a condition is insulated already
                elif kind == "flux":
                    rec["q"] = float(c["q"])
                    np.add.at(self.F, ed.conn.ravel(), ((float(c["q"]) * tt * ed.L)[:, None] * ed.int_N[None]).ravel())
                elif kind == "conv":
                    h, Ti = float(c["h"]), float(c["Tinf"])
                    if h < 0 or Ti <= 0:
                        raise ModelError("The convection coefficient cannot be negative and the fluid temperature must be above 0 K.")
                    rec.update(h=h, Tinf=Ti)
                    if h > 0:
                        Ke = (h * tt * ed.L)[:, None, None] * ed.int_NN[None]
                        self.K = self.K + _csr(ed.conn, Ke, self.N)
                        np.add.at(self.F, ed.conn.ravel(), ((h * Ti * tt * ed.L)[:, None] * ed.int_N[None]).ravel())
                        self.ground[ed.conn.ravel()] = True
                elif kind == "fluid":
                    # exchange with a flowing fluid (Coupled Physics): the coefficient h and the fluid temperature are functions of the point on the edge, given in sketch units
                    X = np.einsum("gn,enj->egj", ed.Ng, self.nodes_m[ed.conn]) / float(setup["lscale"])            # (E, G, 2)
                    flat = X.reshape(-1, 2)
                    hg = np.asarray(c["h"](flat) if callable(c["h"]) else np.full(len(flat), float(c["h"])), float).reshape(X.shape[:2])
                    Tg = np.asarray(c["Tinf"](flat) if callable(c["Tinf"]) else np.full(len(flat), float(c["Tinf"])), float).reshape(X.shape[:2])
                    # (a linearised exchange, as Coupled Physics iterates it, has a reference that is only the other half of q = h (T - Tref): it need not be a temperature)
                    if np.any(hg < 0) or (not c.get("linearised") and np.any(Tg <= 0)) or not (np.all(np.isfinite(hg)) and np.all(np.isfinite(Tg))):
                        raise ModelError("The fluid exchange needs a coefficient that is not negative and a fluid temperature above 0 K, finite everywhere on the edge.")
                    rec.update(hg=hg, Tg=Tg)
                    Ke = np.einsum("e,g,eg,gi,gj->eij", tt * ed.L, ed.wg, hg, ed.Ng, ed.Ng)
                    Fe = np.einsum("e,g,eg,gi->ei", tt * ed.L, ed.wg, hg * Tg, ed.Ng)
                    self.K = self.K + _csr(ed.conn, Ke, self.N)
                    np.add.at(self.F, ed.conn.ravel(), Fe.ravel())
                    if np.any(hg > 0):
                        self.ground[ed.conn.ravel()] = True
                else:
                    eps, Ts = float(c["eps"]), float(c["Ts"])
                    if not (0 <= eps <= 1) or Ts <= 0:
                        raise ModelError("The emissivity must be between 0 and 1 and the surroundings temperature above 0 K.")
                    rec.update(eps=eps, Ts=Ts)
                    if eps > 0:
                        self.rad.append((ed, eps * SIGMA * tt * ed.L, Ts))
                        self.ground[ed.conn.ravel()] = True
            self.conds.append(rec)

    def _faces(self, setup):
        f = setup.get("plate") or {}
        h, eps = float(f.get("h", 0.0) or 0.0), float(f.get("eps", 0.0) or 0.0)
        Ti, Ts = float(f.get("Tinf", 293.15)), float(f.get("Ts", 293.15))
        self.plate = {"h": h, "eps": eps, "Tinf": Ti, "Ts": Ts}
        if h < 0 or not (0 <= eps <= 1) or Ti <= 0 or Ts <= 0:
            raise ModelError("The plate-face values are not valid (h >= 0, 0 <= emissivity <= 1, temperatures above 0 K).")
        if h > 0:
            c = np.full(len(self.conn), 2.0 * h)
            self.K = self.K + area_matrix(self.geo, self.conn, self.order, c, self.N)
            self.F = self.F + area_vector(self.geo, self.conn, self.order, c * Ti, self.N)
            self.ground[:] = True
        if eps > 0:
            self.face_rad = (2.0 * eps * SIGMA, Ts)
            self.ground[:] = True

    # ---- radiation: residual and Jacobian
    def radiation(self, T, jac=True):
        """-> R (N,), J (csr or None): the radiated heat (leaving, per node) and its derivative with respect to the temperatures."""
        R = np.zeros(self.N)
        rows, cols, vals = [], [], []
        for ed, coef, Ts in self.rad:
            Tg = ed.interp(T)                                                  # (E, G)
            R_e = coef[:, None] * np.einsum("g,eg,gi->ei", ed.wg, Tg ** 4 - Ts ** 4, ed.Ng)
            np.add.at(R, ed.conn.ravel(), R_e.ravel())
            if jac:
                J_e = coef[:, None, None] * 4.0 * np.einsum("g,eg,gi,gj->eij", ed.wg, Tg ** 3, ed.Ng, ed.Ng)
                k = ed.n
                rows.append(np.repeat(ed.conn[:, :, None], k, axis=2).ravel())
                cols.append(np.repeat(ed.conn[:, None, :], k, axis=1).ravel())
                vals.append(J_e.ravel())
        if self.face_rad is not None:
            c2, Ts = self.face_rad
            pts, w = RULE2 if self.order == 1 else RULE4
            Te = T[self.conn]
            Re = np.zeros(self.conn.shape)
            Je = np.zeros((len(self.conn), self.conn.shape[1], self.conn.shape[1])) if jac else None
            for L, wg in zip(pts, w):
                N = shape(self.order, L)[0]
                Tg = Te @ N
                Re += wg * (Tg ** 4 - Ts ** 4)[:, None] * N[None]
                if jac:
                    Je += wg * 4.0 * (Tg ** 3)[:, None, None] * np.outer(N, N)[None]
            Re *= (self.geo.A * c2)[:, None]
            np.add.at(R, self.conn.ravel(), Re.ravel())
            if jac:
                Je *= (self.geo.A * c2)[:, None, None]
                k = self.conn.shape[1]
                rows.append(np.repeat(self.conn[:, :, None], k, axis=2).ravel())
                cols.append(np.repeat(self.conn[:, None, :], k, axis=1).ravel())
                vals.append(Je.ravel())
        J = None
        if jac:
            if rows:
                J = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(self.N, self.N)).tocsr()
            else:
                J = sp.csr_matrix((self.N, self.N))
        return R, J

    def residual(self, T):
        """Heat leaving minus heat arriving at every node (steady): K T + R(T) - F."""
        r = self.K @ T - self.F
        if self.has_rad:
            r = r + self.radiation(T, jac=False)[0]
        return r

    # ---- checks
    def check_grounded(self):
        """A steady problem needs every connected piece of the model to be tied to a temperature or to the surroundings."""
        k = self.conn.shape[1]
        rows = np.concatenate([self.conn[:, 0]] * (k - 1))
        cols = np.concatenate([self.conn[:, j] for j in range(1, k)])
        adj = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(self.N, self.N))
        ncomp, lab = connected_components(adj, directed=False)
        tied = self.ground.copy()
        if len(self.dir_nodes):
            tied[self.dir_nodes] = True
        for c in range(ncomp):
            m = lab == c
            if not np.any(tied[m]):
                tf = np.asarray(self.mesh.get("tri_face", []))
                regs = sorted({int(tf[i]) + 1 for i in np.nonzero(m[self.conn[:, 0]])[0]}) if len(tf) else []
                where = (" (region " + ", ".join(str(r) for r in regs) + ")") if regs else ""
                raise ModelError("A steady-state solution needs a temperature, convection or radiation condition on every separate piece of the model, "
                                 f"and one piece has none{where}. Its temperature would be undefined. Add one, or use a transient analysis.")


# ------------------------------------------------------------------------------------------------------------------- solving
def _lin_solve(A, b):
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=spla.MatrixRankWarning)
        try:
            x = psolve.solve(A, b)
        except (spla.MatrixRankWarning, RuntimeError) as ex:
            raise ModelError("The matrix is singular: some part of the model has no temperature, convection or radiation condition.") from ex
    if not np.all(np.isfinite(x)):
        raise ModelError("The solution is not finite: the matrix is singular (a part of the model is not tied to any temperature).")
    return x


def _newton(T, free, fun, tol=1e-9, max_iter=40, cancel=None, positive=True):
    """Newton's method on the free nodes.  fun(T) -> (r (N,), J csr).  Returns (T, info).  Never raises for lack of convergence: the last
    iterate is returned with info["converged"] False.  A step that would take a temperature to 1 K or below is shortened, and a step that does not
    reduce the residual is halved (down to a small fraction)."""
    info = {"iterations": 0, "converged": False, "residual": None}
    r, J = fun(T)
    for it in range(1, max_iter + 1):
        if cancel is not None and cancel():
            raise Cancelled()
        rf = r[free]
        rn = float(np.linalg.norm(rf))
        dT = _lin_solve(J[free][:, free], -rf)
        full = float(np.max(np.abs(dT))) if len(dT) else 0.0
        a = 1.0
        while True:
            Tn = T.copy()
            Tn[free] += a * dT
            if (not positive) or float(Tn[free].min()) > 1.0:
                rnew, Jnew = fun(Tn)
                nn = float(np.linalg.norm(rnew[free]))
                if nn <= (1.0 - 1e-4 * a) * rn or a < 1e-3 or nn <= 1e-14 * max(1.0, rn):
                    break
            a *= 0.5
            if a < 1e-6:                                      # nothing helps: stay where we are and say so
                Tn, rnew, Jnew = T, r, J
                break
        T, r, J = Tn, rnew, Jnew
        info["iterations"] = it
        info["residual"] = float(np.linalg.norm(r[free]))
        if full <= tol * max(1.0, float(np.max(np.abs(T)))):
            info["converged"] = True
            break
    return T, info


def solve_steady(mdl, T_start=None, cancel=None):
    mdl.check_grounded()
    N = mdl.N
    T = np.zeros(N)
    T[mdl.dir_nodes] = mdl.dir_vals
    free = mdl.free
    info = {"iterations": 1, "converged": True, "residual": 0.0}
    if len(free) == 0:
        return T, info
    if not mdl.has_rad:
        Kff = mdl.K[free][:, free]
        rhs = mdl.F[free] - mdl.K[free][:, mdl.dir_nodes] @ mdl.dir_vals if len(mdl.dir_nodes) else mdl.F[free]
        T[free] = _lin_solve(Kff, rhs)
        return T, info
    ref = _reference_temperature(mdl)
    T[free] = ref if T_start is None else T_start[free]

    def fun(Tv):
        R, J = mdl.radiation(Tv)
        return mdl.K @ Tv - mdl.F + R, mdl.K + J
    return _newton(T, free, fun, cancel=cancel)


def _reference_temperature(mdl):
    """A starting temperature for the Newton iteration: the mean of the temperatures the conditions mention."""
    vals = list(mdl.dir_vals)
    for rec in mdl.conds:
        for key in ("Tinf", "Ts"):
            if key in rec:
                vals.append(rec[key])
    if mdl.plate["h"] > 0:
        vals.append(mdl.plate["Tinf"])
    if mdl.plate["eps"] > 0:
        vals.append(mdl.plate["Ts"])
    return float(np.mean(vals)) if vals else 293.15


def solve_transient(mdl, T0, t_end, steps, theta=1.0, frames=40, progress=None, cancel=None):
    """-> (T final, times (F,), frames (F, N), info).  The temperature conditions hold from the start; the rest starts at T0."""
    if not (t_end > 0 and steps >= 1):
        raise ModelError("The end time must be positive and there must be at least one time step.")
    theta = float(theta)
    N, free = mdl.N, mdl.free
    dt = t_end / steps
    T = np.full(N, float(T0))
    T[mdl.dir_nodes] = mdl.dir_vals
    npic = max(2, min(int(frames), steps + 1))                   # the pictures kept, the first (time 0) and the last included, at equal steps
    keep = sorted(set(int(round(x)) for x in np.linspace(0, steps, npic)))
    times, snaps = [0.0], [T.copy()]
    info = {"iterations": 0, "converged": True, "residual": 0.0, "max_iterations": 0, "steps": steps, "dt": dt, "theta": theta, "unconverged_steps": 0}
    Mdt = mdl.M / dt
    t0 = time.monotonic()
    lu = None
    if not mdl.has_rad and len(free):
        A = (Mdt + theta * mdl.K).tocsc()
        Aff = A[free][:, free].tocsc()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            try:
                lu = spla.splu(Aff)
            except (RuntimeError, spla.MatrixRankWarning) as ex:
                raise ModelError("The transient matrix is singular.") from ex
        Afd = A[free][:, mdl.dir_nodes] if len(mdl.dir_nodes) else None
    Mfree = Mdt[free][:, :]
    last_rate = None
    for n in range(1, steps + 1):
        if cancel is not None and cancel():
            raise Cancelled()
        Told = T
        if len(free) == 0:                                   # every node has a fixed temperature: nothing changes
            Tn = Told.copy()
        elif lu is not None:
            rhs = Mfree @ Told - (1.0 - theta) * (mdl.K[free] @ Told) + mdl.F[free]
            if len(mdl.dir_nodes):
                rhs = rhs - Afd @ mdl.dir_vals
            Tn = Told.copy()
            Tn[free] = lu.solve(rhs)
            Tn[mdl.dir_nodes] = mdl.dir_vals
        else:
            if mdl.has_rad:
                R_old = mdl.radiation(Told, jac=False)[0] if theta < 1.0 else 0.0
            old_part = (1.0 - theta) * (mdl.K @ Told - mdl.F + (R_old if mdl.has_rad else 0.0))

            def fun(Tv, Told=Told, old_part=old_part):
                if mdl.has_rad:
                    R, J = mdl.radiation(Tv)
                    r = Mdt @ (Tv - Told) + theta * (mdl.K @ Tv - mdl.F + R) + old_part
                    return r, Mdt + theta * (mdl.K + J)
                r = Mdt @ (Tv - Told) + theta * (mdl.K @ Tv - mdl.F) + old_part
                return r, Mdt + theta * mdl.K
            Tn, ni = _newton(Told.copy(), free, fun, cancel=cancel)
            info["iterations"] += ni["iterations"]
            info["max_iterations"] = max(info["max_iterations"], ni["iterations"])
            if not ni["converged"]:
                info["unconverged_steps"] += 1
                info["converged"] = False
        T = Tn
        if n in keep:
            times.append(n * dt)
            snaps.append(T.copy())
        if progress is not None and (n % max(1, steps // 50) == 0 or n == steps):
            progress(f"Time step {n} of {steps}", n / steps)
    info["rate"] = (mdl.M @ (T - Told)) / dt
    info["seconds"] = time.monotonic() - t0
    return T, np.array(times), np.array(snaps), info


# ------------------------------------------------------------------------------------------------------------------- results
def element_flux(mdl_or_res, T):
    """Heat flux q = -k grad T of every triangle: (qx, qy) with shape (M,) for linear elements and (M, 4) at the four stress points of a quadratic one,
    in W/m2.  `mdl_or_res` is a Model or a result dict (it only needs conn, order, nodes in metres and k)."""
    geo = mdl_or_res.geo if hasattr(mdl_or_res, "geo") else _Geo(mdl_or_res["nodes_m"], mdl_or_res["conn"])
    conn = mdl_or_res.conn if hasattr(mdl_or_res, "conn") else mdl_or_res["conn"]
    order = mdl_or_res.order if hasattr(mdl_or_res, "order") else mdl_or_res["order"]
    k = mdl_or_res.k_el if hasattr(mdl_or_res, "k_el") else mdl_or_res["k_el"]
    Te = T[conn]
    pts = RULE1[0] if order == 1 else STRESS_POINTS
    qx, qy = [], []
    for L in pts:
        gx, gy = geo.grads(shape(order, L)[1])
        qx.append(-k * np.sum(gx * Te, axis=1))
        qy.append(-k * np.sum(gy * Te, axis=1))
    qx, qy = np.stack(qx, axis=1), np.stack(qy, axis=1)
    return (qx[:, 0], qy[:, 0]) if order == 1 else (qx, qy)


def _display(mdl):
    if mdl.order == 2:
        return pf.display_mesh(mdl.mesh, mdl.nodes_all, mdl.conn, mdl.mid)
    d = dict(mdl.mesh)
    d["nodes"] = mdl.nodes_all
    d["parent"] = np.arange(len(mdl.conn))
    d["quadratic"] = False
    return d


def _balance(mdl, T, storage):
    """Heat in, heat out and what is stored, in watts (through the depth).  Every term is integrated on its own; the temperature conditions' flows
    come from the nodal residual."""
    t = mdl.t
    r = mdl.K @ T - mdl.F
    if mdl.has_rad:
        r = r + mdl.radiation(T, jac=False)[0]
    if storage is not None:
        r = r + storage
    flows = []
    node_cond = {nd: ci for nd, (_v, ci) in mdl.dirichlet.items()}
    per_cond = {}
    for nd, ci in node_cond.items():
        per_cond[ci] = per_cond.get(ci, 0.0) + float(r[nd])
    inn = out = 0.0
    parts = {}
    for rec in mdl.conds:
        kind, ci = rec["kind"], rec["index"]
        item = {"index": ci, "kind": kind, "name": rec["name"], "Q": 0.0}
        ed = rec.get("edges")
        if ed is not None and kind in ("flux", "conv", "fluid", "rad"):
            item["area"] = t * float(ed.L.sum())                       # m2: the heat flow over it is the average flux
        if kind == "temp":
            item["Q"] = per_cond.get(ci, 0.0)                          # into the body
            inn += item["Q"]
        elif kind == "power":
            item["Q"] = rec.get("P", 0.0)
            inn += item["Q"]
        elif ed is not None and kind == "flux":
            item["Q"] = rec["q"] * t * float(ed.L.sum())
            inn += item["Q"]
        elif ed is not None and kind == "conv" and rec["h"] > 0:
            Tg = ed.interp(T)
            item["Q"] = -rec["h"] * t * float(np.sum(ed.L * (ed.wg @ (Tg - rec["Tinf"]).T)))       # negative = leaving
            out += -item["Q"]
        elif ed is not None and kind == "fluid":
            Tg = ed.interp(T)
            item["Q"] = -t * float(np.sum(ed.L * np.einsum("g,eg->e", ed.wg, rec["hg"] * (Tg - rec["Tg"]))))
            out += -item["Q"]
        elif ed is not None and kind == "rad" and rec["eps"] > 0:
            Tg = ed.interp(T)
            item["Q"] = -rec["eps"] * SIGMA * t * float(np.sum(ed.L * (ed.wg @ (Tg ** 4 - rec["Ts"] ** 4).T)))
            out += -item["Q"]
        flows.append(item)
    gen = mdl.region_gen
    inn += gen
    parts["generation"] = gen
    face_conv = face_rad = 0.0
    if mdl.plate["h"] > 0:
        ones = np.ones(len(mdl.conn))
        Kf = area_matrix(mdl.geo, mdl.conn, mdl.order, ones * 2.0 * mdl.plate["h"], mdl.N)
        ff = area_vector(mdl.geo, mdl.conn, mdl.order, ones * 2.0 * mdl.plate["h"] * mdl.plate["Tinf"], mdl.N)
        face_conv = float(np.sum(Kf @ T - ff))
    if mdl.face_rad is not None:
        c2, Ts = mdl.face_rad
        pts, w = RULE2 if mdl.order == 1 else RULE4
        Te = T[mdl.conn]
        s = 0.0
        for L, wg in zip(pts, w):
            Tg = Te @ shape(mdl.order, L)[0]
            s += wg * float(np.sum(mdl.geo.A * (Tg ** 4 - Ts ** 4)))
        face_rad = c2 * s
    out += face_conv + face_rad
    stored = float(np.sum(storage)) if storage is not None else 0.0
    scale = max(abs(inn), abs(out), abs(stored), sum(abs(f["Q"]) for f in flows), 1e-300)
    bal = {"in": inn, "out": out, "stored": stored, "generation": gen, "face_conv": face_conv, "face_rad": face_rad,
           "error": inn - out - stored, "relative_error": abs(inn - out - stored) / scale}
    return flows, bal


def solve(mesh, setup, progress=None, cancel=None):
    """The whole job: the model, the steady or transient solution, the fields and the energy balance.  -> result dict (plain Python and NumPy)."""
    def tick(text, frac):
        if cancel is not None and cancel():
            raise Cancelled()
        if progress is not None:
            progress(text, frac)
    tick("Building the matrices", 0.05)
    mdl = Model(mesh, setup, cancel=cancel)
    analysis = setup.get("analysis", "steady")
    times = frames = None
    storage = None
    tick("Solving", 0.2)
    if analysis == "transient":
        T, times, frames, info = solve_transient(mdl, float(setup["T0"]), float(setup["t_end"]), int(setup["steps"]), float(setup.get("theta", 1.0)),
                                                  int(setup.get("frames", 40)), progress=lambda t, f: tick(t, 0.2 + 0.7 * f), cancel=cancel)
        storage = info.pop("rate")
        newton = info if mdl.has_rad else None
    else:
        T, info = solve_steady(mdl, cancel=cancel)
        newton = info if mdl.has_rad else None
    run = dict(info)
    tick("Finding the heat flux and the heat balance", 0.92)
    qx, qy = element_flux(mdl, T)
    flows, bal = _balance(mdl, T, storage)
    disp = _display(mdl)
    qx_d, qy_d = (qx.reshape(-1), qy.reshape(-1))
    area_el = mdl.geo.A
    Tc = T[mdl.conn[:, :3]].mean(axis=1)
    notes = list(mdl.notes)
    if newton is not None and not newton["converged"]:
        notes.append("The radiation iteration did not converge (Newton's method stopped after its limit). The result shown is the last one: do not trust it. "
                     "Check the emissivity, the temperatures and the mesh, or add a convection condition.")
    cn = analysis == "transient" and float(setup.get("theta", 1.0)) < 1.0
    if bal["relative_error"] > (5e-2 if cn else 1e-6):
        notes.append(f"The heat balance is off by {bal['relative_error']:.2g} of the heat flowing: check the conditions.")
    res = {"T": T, "times": times, "frames": frames, "mesh": disp, "order": mdl.order, "conn": mdl.conn, "nodes_m": mdl.nodes_m, "k_el": mdl.k_el,
           "qx": qx_d, "qy": qy_d, "qmag": np.hypot(qx_d, qy_d), "Tmin": float(T.min()), "Tmax": float(T.max()),
           "Tmean": float(np.sum(Tc * area_el) / np.sum(area_el)), "area_m2": float(np.sum(area_el)), "t_m": mdl.t, "lscale": float(setup["lscale"]),
           "flows": flows, "balance": bal, "newton": newton, "run": run, "notes": notes, "analysis": analysis, "dofs": mdl.N,
           "elements": len(mdl.conn), "heat_in": bal["in"], "heat_out": bal["out"],
           "setup": {k: setup[k] for k in ("analysis", "T0", "t_end", "steps", "theta") if k in setup}}
    tick("Done", 1.0)
    return res


def flux_of(res, T):
    """Flux arrays (qx, qy, qmag) for the display triangles of a stored result and ANY temperature vector of it (a frame of a transient run)."""
    qx, qy = element_flux(res, T)
    qx, qy = qx.reshape(-1), qy.reshape(-1)
    return qx, qy, np.hypot(qx, qy)


def tri_temperature(res, T=None):
    """The temperature at the three corners of every display triangle: (M, 3)."""
    T = res["T"] if T is None else T
    return T[res["mesh"]["tris"]]


def probe_stats(res, probes, T=None):
    """Area-weighted average, smallest and largest temperature and the average heat flux in every probe region (original geometry)."""
    mesh = res["mesh"]
    masks = pf.probe_masks(probes, mesh["nodes"], mesh["tris"])
    T = res["T"] if T is None else T
    tt = T[mesh["tris"]]
    qm = res["qmag"] if T is res["T"] else flux_of(res, T)[2]
    out = []
    for pr, (m, area) in zip(probes, masks):
        n = int(m.sum())
        if n == 0 or float(area[m].sum()) <= 0:
            out.append({"name": pr["name"], "n": 0, "area": 0.0, "avg": None, "min": None, "max": None, "q_avg": None})
            continue
        a = area[m]
        out.append({"name": pr["name"], "n": n, "area": float(a.sum()), "avg": float(np.sum(tt[m].mean(axis=1) * a) / a.sum()),
                    "min": float(tt[m].min()), "max": float(tt[m].max()), "q_avg": float(np.sum(qm[m] * a) / a.sum())})
    return out
