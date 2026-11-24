"""thermal3d_fem.py - 3D heat conduction by finite elements on tetrahedra (no Qt).  Steady or transient; conduction, convection and radiation.

  * 10-node (quadratic) or 4-node (linear) tetrahedra: the mesh of the 3D FEA (solid_model.get_mesh), straight-sided, one body or an assembly of bodies
  * one material per body (conductivity k, density rho, specific heat cp), isotropic and constant: nothing depends on the temperature
  * the bodies of an assembly share the nodes of the faces they touch (the mesh is conforming): the contact is perfect, no resistance
  * heat generation per body (W/m3)
  * conditions on the faces of the part (ids of the faces of the mesh, as the 3D FEA's supports and loads):
        temp   a fixed temperature                                            [Dirichlet]
        flux   a heat flux INTO the body, W/m2                                [Neumann]; zero everywhere else = insulated
        power  a heat flow INTO the body, W, spread evenly over the area of the faces
        conv   convection to a fluid at T_inf with coefficient h:   q_out = h (T - T_inf)
        rad    radiation to surroundings at T_s with emissivity eps: q_out = eps sigma (T^4 - T_s^4)      (NOT between surfaces of the model:
               that needs view factors, which this version does not have)
        ins    insulated faces: no heat through them (the same as a flux of zero; it only makes the choice visible and checked)
  * steady: one solve, or Newton's method when there is radiation (the line search keeps every temperature above zero kelvin)
  * transient: the theta method (theta = 1 backward Euler, 1/2 Crank-Nicolson) with a constant step, Newton inside each step when there is radiation;
    the conditions are constant in time and the start is one uniform temperature
  * systems up to solid_fem.DIRECT_LIMIT unknowns are factorised (once for a transient run); larger ones by conjugate gradients with an algebraic
    multigrid preconditioner built once
  * nothing is averaged: the heat flux is the raw element value (the temperature gradient is not continuous across elements)

Everything inside is SI and ABSOLUTE temperature (kelvin).  Mesh lengths are converted with `lscale` (metres per mesh unit; the 3D FEA's mesh is in mm).
Heat flow signs: a temperature condition's flow is positive when it feeds heat INTO the body.

The checks behind the numbers (test_thermal3d_fem.py): the element matrices against exact integrals, a linear temperature field reproduced exactly, a slab,
a layered wall, a hollow cylinder and a hollow sphere against their closed forms, heat generation in a sphere, a fin with convection, radiation against its
closed form, a transient slab and lumped cooling against their closed forms, the energy balance, and the same problem in either element order.
"""
import time
import warnings

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl
from scipy.sparse.csgraph import connected_components

import solid_fem as fem

SIGMA = 5.670374419e-8                      # W/(m2 K4)
ThermalError = fem.FemError                 # the window shows these as messages, not as bugs
Cancelled = fem.Cancelled
DIRECT_LIMIT = fem.DIRECT_LIMIT
KINDS = {"temp": "Fixed temperature", "flux": "Heat flux", "power": "Heat flow", "conv": "Convection", "rad": "Radiation", "ins": "Insulated"}
CHUNK = 6000                                # elements per piece of the assembly

# ------------------------------------------------------------------------------------------------------------------- reference elements
_A4, _B4 = 0.445948490915965, 0.091576213509771
RULE4 = (np.array([[_A4, _A4, 1 - 2 * _A4], [_A4, 1 - 2 * _A4, _A4], [1 - 2 * _A4, _A4, _A4],
                   [_B4, _B4, 1 - 2 * _B4], [_B4, 1 - 2 * _B4, _B4], [1 - 2 * _B4, _B4, _B4]]),
         np.array([0.223381589678011] * 3 + [0.109951743655322] * 3))              # on a triangle, exact to degree 4; the weights add up to 1


def _tet_rule(n=5):
    """An exact rule on the tetrahedron (the unit cube collapsed onto it, Gauss-Legendre in each direction): points as volume coordinates (P, 4) and
    weights that add up to 1 (the volume is taken out).  Exact for every polynomial the element matrices need (degree 4) and well beyond."""
    x, w = np.polynomial.legendre.leggauss(n)
    x, w = (x + 1.0) / 2.0, w / 2.0
    pts, wts = [], []
    for a, wa in zip(x, w):
        for b, wb in zip(x, w):
            for c, wc in zip(x, w):
                X, Y, Z = a, b * (1 - a), c * (1 - a) * (1 - b)
                pts.append([1 - X - Y - Z, X, Y, Z])
                wts.append(wa * wb * wc * (1 - a) ** 2 * (1 - b) * 6.0)
    return np.array(pts), np.array(wts)


_REF = {}


def reference(order):
    """The constant tensors of the straight-sided tetrahedron of this order, per unit volume:
         A (n, n, 4, 4)  mean of dN_i/dL_k dN_j/dL_l      the conduction matrix is  k V sum_kl A_ijkl (grad L_k . grad L_l)
         M (n, n)        mean of N_i N_j                    the heat capacity matrix  rho cp V M
         Ne (n,)         mean of N_i                        heat generation, per unit q'''  V Ne
       n = 4 or 10."""
    if order in _REF:
        return _REF[order]
    pts, w = _tet_rule()
    if order == 1:
        N = pts                                                           # (P, 4)
        dN = np.broadcast_to(np.eye(4), (len(pts), 4, 4))
    else:
        N = np.stack([fem._N(L) for L in pts])
        dN = np.stack([fem._dNdL(L) for L in pts])
    A = np.einsum("p,pik,pjl->ijkl", w, dN, dN)
    M = np.einsum("p,pi,pj->ij", w, N, N)
    Ne = w @ N
    _REF[order] = {"A": A, "M": M, "Ne": Ne, "n": N.shape[1]}
    return _REF[order]


def _tri_shape(order_nodes, L):
    l1, l2, l3 = L
    if order_nodes == 3:
        return np.array([l1, l2, l3])
    return np.array([l1 * (2 * l1 - 1), l2 * (2 * l2 - 1), l3 * (2 * l3 - 1), 4 * l1 * l2, 4 * l2 * l3, 4 * l3 * l1])


class _Faces:
    """The triangles of one condition: node numbers (3 or 6 per triangle), the areas in square metres and the shape functions at the integration points."""

    def __init__(self, tris, nodes_m):
        tris = np.asarray(tris, np.int64)
        p = nodes_m[tris[:, :3]]
        self.A = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
        self.conn = tris
        self.n = tris.shape[1]
        pts, w = RULE4
        self.Ng = np.stack([_tri_shape(self.n, L) for L in pts])           # (G, n)
        self.wg = w
        self.int_N = w @ self.Ng                                           # integral of N over a triangle of area 1
        self.int_NN = np.einsum("g,gi,gj->ij", w, self.Ng, self.Ng)

    def area(self):
        return float(self.A.sum())

    def interp(self, T):
        """The temperature at the integration points of every triangle: (E, G)."""
        return T[self.conn] @ self.Ng.T


def _csr_local(conn, Ke, n):
    return fem._coo(Ke, conn, n)


# ------------------------------------------------------------------------------------------------------------------- the model
class Model:
    """Everything that does not change during the solve: the matrices K (conduction + convection), M (heat capacity), the load vector F, the radiating faces.

    q     the mesh from solid_model.get_mesh: q["nodes"] (mm), q["groups"] (one group of tetrahedra per body), q["ftri"] (the triangles of every face id)
    spec  {"lscale": metres per mesh unit, "materials": [{"k", "rho", "cp", "gen", "name"} per body], "temps"/"fluxes"/"powers"/"convs"/"rads"/"ins":
           [{"name", "fids", ...}] (see the top of the file), "analysis", "T0", "t_end", "steps", "theta", "frames"}"""

    def __init__(self, q, spec, cancel=None, progress=None):
        self.notes = []
        self.spec = spec
        self.cancel = cancel or (lambda: False)
        self.progress = progress
        ls = float(spec.get("lscale", 1e-3))
        self.lscale = ls
        nodes = np.asarray(q["nodes"], float)
        self.nodes = nodes
        self.nodes_m = nodes * ls
        self.N = len(nodes)
        self.order = 2 if q.get("order", 2) == 2 else 1
        groups = list(q.get("groups") or [{"kind": "tet", "conn": q["conn"]}])
        for g in groups:
            if g["kind"] != "tet":
                raise ThermalError("The 3D Thermal solver works on tetrahedra. This mesh has hexahedra: use the Tetrahedra mesh type.")
        self.conn = np.concatenate([np.asarray(g["conn"]) for g in groups]).astype(np.int64)
        self.body = np.concatenate([np.full(len(g["conn"]), int(g.get("body", 0)), np.int64) for g in groups])
        mats = spec["materials"]
        if int(self.body.max()) >= len(mats):
            raise ThermalError("A body of the mesh has no material.")
        for i, m in enumerate(mats):
            nm = m.get("name") or f"body {i + 1}"
            if not float(m["k"]) > 0:
                raise ThermalError(f"{nm}: the thermal conductivity must be greater than zero.")
            if not (float(m["rho"]) > 0 and float(m["cp"]) > 0):
                raise ThermalError(f"{nm}: the density and the specific heat must be greater than zero.")
        self.materials = mats
        self.k_el = np.array([float(m["k"]) for m in mats])[self.body]
        self.rc_el = np.array([float(m["rho"]) * float(m["cp"]) for m in mats])[self.body]
        self.gen_el = np.array([float(m.get("gen") or 0.0) for m in mats])[self.body]
        self.vol = self._volumes()
        self.generation = float(np.sum(self.gen_el * self.vol))                   # total heat generated, W
        used = np.zeros(self.N, bool)
        used[self.conn] = True
        self.used = used
        self.ground = np.zeros(self.N, bool)                 # nodes that a convection / radiation condition ties to the surroundings
        self.dirichlet = {}                                   # node -> (T, condition index)
        self.conds = []                                       # per condition: what is needed to report it afterwards
        self.rad = []                                         # [(faces, coef (E,), Ts)]
        self.K, self.M, self.F = self._assemble()
        self._conditions(q, spec)
        self.dir_nodes = np.array(sorted(self.dirichlet), dtype=np.int64)
        self.dir_vals = np.array([self.dirichlet[i][0] for i in self.dir_nodes])
        isdir = np.zeros(self.N, bool)
        isdir[self.dir_nodes] = True
        self.free = np.where(used & ~isdir)[0]
        self.has_rad = bool(self.rad)

    # ---- the matrices
    def _volumes(self):
        v = np.empty(len(self.conn))
        for s in range(0, len(self.conn), 20000):
            e = min(s + 20000, len(self.conn))
            c = self.nodes_m[self.conn[s:e, :4]]
            v[s:e] = np.abs(fem._signed_vol(c))
        if np.any(v <= 0):
            raise ThermalError("The mesh has flat or inverted tetrahedra.")
        return v

    def _assemble(self):
        ref = reference(self.order)
        n = ref["n"]
        A2 = ref["A"].reshape(n * n, 16)
        Mref, Ne = ref["M"], ref["Ne"]
        N = self.N
        accK, accM = fem._Sum(), fem._Sum()
        F = np.zeros(N)
        ne = len(self.conn)
        for s in range(0, ne, CHUNK):
            if self.cancel():
                raise Cancelled()
            e = min(s + CHUNK, ne)
            gL, V = fem._grad_L(self.nodes_m, self.conn, s, e)
            G = np.einsum("ekx,elx->ekl", gL, gL).reshape(e - s, 16)
            Ke = (G @ A2.T).reshape(e - s, n, n) * (self.k_el[s:e] * V)[:, None, None]
            Me = Mref[None] * (self.rc_el[s:e] * V)[:, None, None]
            ed = self.conn[s:e]
            accK.add(_csr_local(ed, Ke, N))
            accM.add(_csr_local(ed, Me, N))
            F += np.bincount(ed.ravel(), weights=((self.gen_el[s:e] * V)[:, None] * Ne[None]).ravel(), minlength=N)
            self._part((e) / ne)
        return accK.total(), accM.total(), F

    def _part(self, fraction):
        fem._part(self.progress, fraction)

    # ---- conditions
    def _tris(self, q, c, label):
        ftri = q["ftri"]
        parts = []
        for fid in c.get("fids") or []:
            if fid not in ftri:
                raise ThermalError(f"{label}: the mesh has no elements on one of its faces.")
            parts.append(np.asarray(ftri[fid]))
        if not parts:
            raise ThermalError(f"{label}: no face is picked.")
        return np.concatenate(parts)

    def _conditions(self, q, spec):
        order_of_kinds = (("temps", "temp"), ("fluxes", "flux"), ("powers", "power"), ("convs", "conv"), ("rads", "rad"), ("ins", "ins"))
        ci = 0
        for key, kind in order_of_kinds:
            for k, c in enumerate(spec.get(key) or []):
                label = c.get("name") or f"{KINDS[kind]} {k + 1}"
                rec = {"index": ci, "kind": kind, "name": label, "fids": list(c.get("fids") or [])}
                ci += 1
                tris = self._tris(q, c, label)
                if kind == "temp":
                    T = float(c["T"])
                    if not T > 0:
                        raise ThermalError(f"{label}: the temperature must be above 0 K.")
                    for nd in np.unique(tris):
                        nd = int(nd)
                        prev = self.dirichlet.get(nd)
                        if prev is not None and abs(prev[0] - T) > 1e-9:
                            self.notes.append("Two fixed temperatures with different values meet along an edge: the later one is used there.")
                        self.dirichlet[nd] = (T, rec["index"])
                    rec["T"] = T
                    rec["area"] = _Faces(tris, self.nodes_m).area()
                else:
                    fc = _Faces(tris, self.nodes_m)
                    rec["faces"] = fc
                    rec["area"] = fc.area()
                    if kind == "flux":
                        rec["q"] = float(c["q"])
                        self.F += self._face_vector(fc, rec["q"])
                    elif kind == "power":
                        if not rec["area"] > 0:
                            raise ThermalError(f"{label}: the faces have no area.")
                        rec["P"] = float(c["P"])
                        rec["q"] = rec["P"] / rec["area"]
                        self.F += self._face_vector(fc, rec["q"])
                    elif kind == "conv":
                        h, Ti = float(c["h"]), float(c["Tinf"])
                        if h < 0 or Ti <= 0:
                            raise ThermalError(f"{label}: the convection coefficient cannot be negative and the fluid temperature must be above 0 K.")
                        rec.update(h=h, Tinf=Ti)
                        if h > 0:
                            Ke = (h * fc.A)[:, None, None] * fc.int_NN[None]
                            self.K = self.K + _csr_local(fc.conn, Ke, self.N)
                            self.F += self._face_vector(fc, h * Ti)
                            self.ground[fc.conn.ravel()] = True
                    elif kind == "rad":
                        eps, Ts = float(c["eps"]), float(c["Ts"])
                        if not (0 <= eps <= 1) or Ts <= 0:
                            raise ThermalError(f"{label}: the emissivity must be between 0 and 1 and the surroundings temperature above 0 K.")
                        rec.update(eps=eps, Ts=Ts)
                        if eps > 0:
                            self.rad.append((fc, eps * SIGMA * fc.A, Ts))
                            self.ground[fc.conn.ravel()] = True
                self.conds.append(rec)

    def _face_vector(self, fc, value):
        """The load vector of a surface load `value` (W/m2) on the triangles of fc."""
        fe = (value * fc.A)[:, None] * fc.int_N[None]
        return np.bincount(fc.conn.ravel(), weights=fe.ravel(), minlength=self.N)

    # ---- radiation: residual and Jacobian
    def radiation(self, T, jac=True):
        """-> R (N,), J (csr or None): the radiated heat (leaving, per node) and its derivative with respect to the temperatures."""
        R = np.zeros(self.N)
        rows, cols, vals = [], [], []
        for fc, coef, Ts in self.rad:
            Tg = fc.interp(T)                                                  # (E, G)
            R_e = coef[:, None] * np.einsum("g,eg,gi->ei", fc.wg, Tg ** 4 - Ts ** 4, fc.Ng)
            R += np.bincount(fc.conn.ravel(), weights=R_e.ravel(), minlength=self.N)
            if jac:
                J_e = coef[:, None, None] * 4.0 * np.einsum("g,eg,gi,gj->eij", fc.wg, Tg ** 3, fc.Ng, fc.Ng)
                k = fc.n
                rows.append(np.repeat(fc.conn[:, :, None], k, axis=2).ravel())
                cols.append(np.repeat(fc.conn[:, None, :], k, axis=1).ravel())
                vals.append(J_e.ravel())
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
            if not np.any(m & self.used):
                continue
            if not np.any(tied[m]):
                bodies = sorted({int(self.body[i]) for i in np.nonzero(m[self.conn[:, 0]])[0]})
                names = [self.materials[b].get("name") or f"body {b + 1}" for b in bodies]
                where = (" (" + ", ".join(names) + ")") if names and len(self.materials) > 1 else ""
                raise ThermalError("A steady-state solution needs a fixed temperature, convection or radiation on every separate piece of the model, "
                                   f"and one piece has none{where}. Its temperature would be undefined. Add one, or use a transient analysis.")

    def check_memory(self):
        n = len(self.free)
        need = fem.memory_estimate(n / 3.0)                        # a scalar unknown costs about a third of an elasticity unknown
        free = fem.available_memory()
        if need > fem.MEM_SHARE * free:
            raise ThermalError(f"This model has about {n:,} unknowns and needs about {need / 1e9:.1f} GB of memory to solve; this computer has about "
                               f"{free / 1e9:.1f} GB free. Use larger elements, or close other programs and try again.")


# ------------------------------------------------------------------------------------------------------------------- linear solves
def _amg():
    return fem._amg()


class _Linear:
    """A symmetric positive definite system A x = b to be solved once or many times (a transient run): a sparse factorisation up to DIRECT_LIMIT unknowns,
    above that conjugate gradients with an algebraic multigrid cycle as the preconditioner, built once."""

    def __init__(self, A, progress=None, cancel=None, extent=None):
        self.n = A.shape[0]
        self.cancel = cancel
        self.progress = progress
        self.how = "direct" if self.n <= DIRECT_LIMIT else "iterative"
        self.iterations = 0
        if self.n == 0:
            self.how = "direct"
            return
        if self.how == "direct":
            try:
                import solid_progress as spg
                fem._stage(progress, "factor", spg.factor_cost(3.0 * self.n, extent))
            except Exception:
                pass
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                try:
                    self.lu = spl.splu(A.tocsc(), permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0, options=dict(SymmetricMode=True))
                except (RuntimeError, spl.MatrixRankWarning):
                    try:
                        self.lu = spl.splu(A.tocsc())
                    except (RuntimeError, spl.MatrixRankWarning) as ex:
                        raise ThermalError("The matrix is singular: some part of the model has no temperature, convection or radiation condition.") from ex
        else:
            amg = _amg()
            if amg is None:
                raise ThermalError(f"This mesh has {self.n:,} unknowns, more than the {DIRECT_LIMIT:,} that are solved exactly, and the multigrid solver for larger "
                                   "ones (the package pyamg) is not installed. Reinstall the 3D FEA add-on, which installs it, or use a larger element size.")
            self.A = A.tocsr()
            fem._stage(progress, "ilu", float(self.A.nnz))
            B = np.ones((self.n, 1))
            self.ml = amg.smoothed_aggregation_solver(self.A, B=B, max_coarse=500)
            self.M = self.ml.aspreconditioner(cycle="V")

    def solve(self, b, x0=None):
        if self.n == 0:
            return np.zeros(0)
        if self.how == "direct":
            x = self.lu.solve(b)
        else:
            fem._stage(self.progress, "cg", float(self.n))
            bn = max(float(np.linalg.norm(b)), 1e-300)
            count = [0]

            def cb(xk):
                count[0] += 1
                if self.cancel is not None and self.cancel():
                    raise Cancelled()
            x, info = spl.cg(self.A, b, x0=x0, rtol=1e-10, maxiter=500, M=self.M, callback=cb)
            self.iterations += count[0]
            if info != 0:
                raise ThermalError(f"The iterative solver could not solve this model ({self.n:,} unknowns) within its iteration limit. Check the conditions, "
                                   "the materials (very different conductivities next to each other), or try a different element size.")
        if not np.all(np.isfinite(x)):
            raise ThermalError("The solution is not finite: the matrix is singular (a part of the model is not tied to any temperature).")
        return x


def _newton(T, free, fun, solver_args, tol=1e-9, max_iter=40, cancel=None, positive=True):
    """Newton's method on the free nodes.  fun(T) -> (r (N,), J csr).  Returns (T, info).  Never raises for lack of convergence: the last iterate is returned
    with info["converged"] False.  A step that would take a temperature to 1 K or below is shortened, and a step that does not reduce the residual is halved
    (down to a small fraction)."""
    info = {"iterations": 0, "converged": False, "residual": None}
    r, J = fun(T)
    for it in range(1, max_iter + 1):
        if cancel is not None and cancel():
            raise Cancelled()
        rf = r[free]
        rn = float(np.linalg.norm(rf))
        dT = _Linear(J[free][:, free], **solver_args).solve(-rf)
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


def _reference_temperature(mdl):
    """A starting temperature for the Newton iteration: the mean of the temperatures the conditions mention."""
    vals = list(mdl.dir_vals)
    for rec in mdl.conds:
        for key in ("Tinf", "Ts"):
            if key in rec:
                vals.append(rec[key])
    return float(np.mean(vals)) if vals else 293.15


def _extent(mdl):
    return np.ptp(mdl.nodes_m, axis=0).tolist()


def solve_steady(mdl, T_start=None, progress=None, cancel=None):
    """-> T (N,), info {"iterations", "converged", "residual", "solver", "linear_iterations"}."""
    mdl.check_grounded()
    mdl.check_memory()
    N = mdl.N
    T = np.zeros(N)
    T[mdl.dir_nodes] = mdl.dir_vals
    free = mdl.free
    info = {"iterations": 1, "converged": True, "residual": 0.0, "solver": "direct", "linear_iterations": 0}
    if len(free) == 0:
        return T, info
    args = {"progress": progress, "cancel": cancel, "extent": _extent(mdl)}
    if not mdl.has_rad:
        rhs = mdl.F[free] - (mdl.K[free][:, mdl.dir_nodes] @ mdl.dir_vals if len(mdl.dir_nodes) else 0.0)
        lin = _Linear(mdl.K[free][:, free], **args)
        T[free] = lin.solve(rhs)
        info.update(solver=lin.how, linear_iterations=lin.iterations)
    else:
        ref = _reference_temperature(mdl)
        T[free] = ref if T_start is None else T_start[free]

        def fun(Tv):
            R, J = mdl.radiation(Tv)
            return mdl.K @ Tv - mdl.F + R, mdl.K + J
        T, info = _newton(T, free, fun, args, cancel=cancel)
        info["solver"] = "direct" if len(free) <= DIRECT_LIMIT else "iterative"
        info["linear_iterations"] = 0
    res = mdl.residual(T)[free]
    terms = float(np.linalg.norm(abs(mdl.K[free]) @ np.abs(T))) + float(np.linalg.norm(mdl.F[free]))      # the size of the heat flows that cancel in the residual
    info["residual_rel"] = float(np.linalg.norm(res)) / max(terms, 1e-300)
    if info["residual_rel"] > 1e-6 and (not mdl.has_rad or info.get("converged")):
        raise ThermalError(f"The solution is not reliable (relative residual {info['residual_rel']:.1e}). Check the conditions and the materials.")
    return T, info


def solve_transient(mdl, T0, t_end, steps, theta=1.0, frames=40, progress=None, cancel=None, say=None):
    """-> (T final, times (F,), frames (F, N), info).  The fixed temperatures hold from the start; the rest starts at T0."""
    if not (t_end > 0 and steps >= 1):
        raise ThermalError("The end time must be positive and there must be at least one time step.")
    if not float(T0) > 0:
        raise ThermalError("The starting temperature must be above 0 K.")
    mdl.check_memory()
    theta = float(theta)
    N, free = mdl.N, mdl.free
    dt = t_end / steps
    T = np.full(N, float(T0))
    T[mdl.dir_nodes] = mdl.dir_vals
    npic = max(2, min(int(frames), steps + 1))                   # the pictures kept, the first (time 0) and the last included, at equal steps
    keep = set(int(round(x)) for x in np.linspace(0, steps, npic))
    times, snaps = [0.0], [T.copy()]
    info = {"iterations": 0, "converged": True, "residual": 0.0, "max_iterations": 0, "steps": int(steps), "dt": dt, "theta": theta, "unconverged_steps": 0,
            "solver": "direct", "linear_iterations": 0}
    Mdt = (mdl.M / dt).tocsr()
    t0 = time.monotonic()
    args = {"progress": progress, "cancel": cancel, "extent": _extent(mdl)}
    lin = None
    Told = T
    if not mdl.has_rad and len(free):
        A = (Mdt + theta * mdl.K).tocsr()
        lin = _Linear(A[free][:, free], **args)
        info["solver"] = lin.how
        Afd = A[free][:, mdl.dir_nodes] if len(mdl.dir_nodes) else None
    elif len(free):
        info["solver"] = "direct" if len(free) <= DIRECT_LIMIT else "iterative"
    Mfree = Mdt[free]
    Kfree = mdl.K[free]
    for n in range(1, steps + 1):
        if cancel is not None and cancel():
            raise Cancelled()
        Told = T
        if len(free) == 0:                                   # every node has a fixed temperature: nothing changes
            Tn = Told.copy()
        elif lin is not None:
            rhs = Mfree @ Told - (1.0 - theta) * (Kfree @ Told) + mdl.F[free]
            if len(mdl.dir_nodes):
                rhs = rhs - Afd @ mdl.dir_vals
            Tn = Told.copy()
            Tn[free] = lin.solve(rhs, x0=Told[free])
            Tn[mdl.dir_nodes] = mdl.dir_vals
        else:
            R_old = mdl.radiation(Told, jac=False)[0] if theta < 1.0 else 0.0
            old_part = (1.0 - theta) * (mdl.K @ Told - mdl.F + R_old)

            def fun(Tv, Told=Told, old_part=old_part):
                R, J = mdl.radiation(Tv)
                r = Mdt @ (Tv - Told) + theta * (mdl.K @ Tv - mdl.F + R) + old_part
                return r, Mdt + theta * (mdl.K + J)
            Tn, ni = _newton(Told.copy(), free, fun, args, cancel=cancel)
            info["iterations"] += ni["iterations"]
            info["max_iterations"] = max(info["max_iterations"], ni["iterations"])
            if not ni["converged"]:
                info["unconverged_steps"] += 1
                info["converged"] = False
        T = Tn
        if n in keep:
            times.append(n * dt)
            snaps.append(T.copy())
        if say is not None and (n % max(1, steps // 50) == 0 or n == steps):
            say(f"Time step {n} of {steps}")
    if lin is not None:
        info["linear_iterations"] = lin.iterations
    info["rate"] = (mdl.M @ (T - Told)) / dt
    info["seconds"] = time.monotonic() - t0
    return T, np.array(times), np.array(snaps), info


# ------------------------------------------------------------------------------------------------------------------- results
def element_gradient(nodes_m, conn, order, T, pts=None):
    """The temperature gradient of every tetrahedron, K/m: (ne, P, 3), P = 1 for linear elements (constant), 4 for quadratic ones at the four points of
    the element's own integration rule (`fem.GAUSS`) - or at the points `pts` (P, 4) in volume coordinates."""
    ne = len(conn)
    if pts is None:
        pts = np.full((1, 4), 0.25) if order == 1 else fem.GAUSS
    out = np.empty((ne, len(pts), 3))
    for s in range(0, ne, 20000):
        e = min(s + 20000, ne)
        gL, _V = fem._grad_L(nodes_m, conn, s, e)
        Te = T[conn[s:e]]
        for p, L in enumerate(pts):
            dN = np.eye(4) if order == 1 else fem._dNdL(L)
            out[s:e, p] = np.einsum("ek,ekx->ex", Te @ dN, gL)
    return out


def element_flux(mdl_or_res, T):
    """The heat flux q = -k grad T of every tetrahedron: (ne, P, 3) W/m2 (P as in element_gradient).  A Model or a result dict."""
    get = (lambda k: getattr(mdl_or_res, k)) if hasattr(mdl_or_res, "conn") else (lambda k: mdl_or_res[k])
    g = element_gradient(get("nodes_m"), get("conn"), get("order"), T)
    return -get("k_el")[:, None, None] * g


def _volume_mean(mdl, T, sel=None):
    ref = reference(mdl.order)
    Te = T[mdl.conn] @ ref["Ne"]
    v = mdl.vol if sel is None else mdl.vol[sel]
    t = Te if sel is None else Te[sel]
    return float(np.sum(t * v) / np.sum(v))


def _balance(mdl, T, storage):
    """Heat in, heat out and what is stored, in watts.  Every term is integrated on its own; the fixed temperatures' flows come from the nodal residual."""
    r = mdl.K @ T - mdl.F
    if mdl.has_rad:
        r = r + mdl.radiation(T, jac=False)[0]
    if storage is not None:
        r = r + storage
    per_cond = {}
    for nd, (_v, ci) in mdl.dirichlet.items():
        per_cond[ci] = per_cond.get(ci, 0.0) + float(r[nd])
    inn = out = 0.0
    flows = []
    for rec in mdl.conds:
        kind, ci = rec["kind"], rec["index"]
        item = {"index": ci, "kind": kind, "name": rec["name"], "Q": 0.0, "area": rec.get("area", 0.0)}
        fc = rec.get("faces")
        if kind == "temp":
            item["Q"] = per_cond.get(ci, 0.0)                          # into the body
            inn += item["Q"]
        elif kind in ("flux", "power"):
            item["Q"] = rec["q"] * rec["area"]
            inn += item["Q"]
        elif kind == "conv" and rec["h"] > 0:
            Tg = fc.interp(T)
            item["Q"] = -rec["h"] * float(np.sum(fc.A * (fc.wg @ (Tg - rec["Tinf"]).T)))      # negative = leaving
            out += -item["Q"]
        elif kind == "rad" and rec["eps"] > 0:
            Tg = fc.interp(T)
            item["Q"] = -rec["eps"] * SIGMA * float(np.sum(fc.A * (fc.wg @ (Tg ** 4 - rec["Ts"] ** 4).T)))
            out += -item["Q"]
        flows.append(item)
    inn += mdl.generation
    stored = float(np.sum(storage)) if storage is not None else 0.0
    scale = max(abs(inn), abs(out), abs(stored), sum(abs(f["Q"]) for f in flows), 1e-300)
    bal = {"in": inn, "out": out, "stored": stored, "generation": mdl.generation, "error": inn - out - stored, "relative_error": abs(inn - out - stored) / scale}
    return flows, bal


def _body_stats(mdl, T, qmag_el):
    out = []
    for b, m in enumerate(mdl.materials):
        sel = mdl.body == b
        if not sel.any():
            continue
        tt = T[mdl.conn[sel][:, :4]]
        out.append({"name": m.get("name") or f"body {b + 1}", "volume_m3": float(mdl.vol[sel].sum()), "Tmean": _volume_mean(mdl, T, sel),
                    "Tmin": float(T[np.unique(mdl.conn[sel])].min()), "Tmax": float(T[np.unique(mdl.conn[sel])].max()),
                    "generation": float(np.sum(mdl.gen_el[sel] * mdl.vol[sel])), "k": float(m["k"]), "q_max": float(qmag_el[sel].max())})
    return out


def solve(q, spec, progress=None, cancel=None):
    """The whole job: the model, the steady or transient solution, the fluxes and the energy balance.  -> result dict (plain Python and NumPy).
    `progress` is the progress bar of the 3D FEA window (solid_progress.Tracker: a function of one text with the extra methods stage() and part()) or any
    function of one text, or None."""
    def say(text):
        if cancel is not None and cancel():
            raise Cancelled()
        if progress is not None:
            progress(text)
    t_start = time.monotonic()
    say("Assembling the matrices")
    fem._stage(progress, "assemble", float(len(q["conn"])))
    mdl = Model(q, spec, cancel=cancel, progress=progress)
    t_asm = time.monotonic() - t_start
    analysis = spec.get("analysis", "steady")
    times = frames = None
    storage = None
    say(f"Solving {len(mdl.free):,} unknowns")
    t_solve = time.monotonic()
    if analysis == "transient":
        T, times, frames, info = solve_transient(mdl, float(spec["T0"]), float(spec["t_end"]), int(spec["steps"]), float(spec.get("theta", 1.0)),
                                                  int(spec.get("frames", 40)), progress=progress, cancel=cancel, say=say)
        storage = info.pop("rate")
    else:
        T, info = solve_steady(mdl, progress=progress, cancel=cancel)
    t_solve = time.monotonic() - t_solve
    newton = info if mdl.has_rad else None
    say("Finding the heat flux and the heat balance")
    notes = list(mdl.notes)
    unused = ~mdl.used
    if unused.any():
        T = T.copy()
        T[unused] = float(np.mean(T[mdl.used]))
    flux = element_flux(mdl, T)
    qc = flux.mean(axis=1)                                         # at the centre of the element (the gradient is linear in a quadratic element: the mean of the four points)
    qmag = np.linalg.norm(qc, axis=1)
    flows, bal = _balance(mdl, T, storage)
    if newton is not None and not newton["converged"]:
        notes.append("The radiation iteration did not converge (Newton's method stopped after its limit). The result shown is the last one: do not trust it. "
                     "Check the emissivity, the temperatures and the mesh, or add a convection condition.")
    cn = analysis == "transient" and float(spec.get("theta", 1.0)) < 1.0
    if bal["relative_error"] > (5e-2 if cn else 1e-6):
        notes.append(f"The heat balance is off by {bal['relative_error']:.2g} of the heat flowing: check the conditions.")
    res = {"T": T, "times": times, "frames": frames, "order": mdl.order, "conn": mdl.conn, "nodes": mdl.nodes, "nodes_m": mdl.nodes_m, "k_el": mdl.k_el,
           "body": mdl.body, "q": qc, "qmag": qmag, "Tmin": float(T[mdl.used].min()), "Tmax": float(T[mdl.used].max()), "Tmean": _volume_mean(mdl, T),
           "volume_m3": float(mdl.vol.sum()), "lscale": mdl.lscale, "flows": flows, "balance": bal, "newton": newton, "run": dict(info), "notes": notes,
           "analysis": analysis, "dofs": int(mdl.N), "unknowns": int(len(mdl.free)), "elements": int(len(mdl.conn)), "heat_in": bal["in"], "heat_out": bal["out"],
           "bodies": _body_stats(mdl, T, qmag), "seconds": {"assemble": t_asm, "solve": t_solve, "total": time.monotonic() - t_start},
           "setup": {k: spec[k] for k in ("analysis", "T0", "t_end", "steps", "theta") if k in spec}}
    say("Done")
    return res


def flux_of(res, T):
    """The heat flux of every element for ANY temperature vector of a stored result (a frame of a transient run): (q (ne, 3), |q| (ne,)), W/m2."""
    f = element_flux(res, T).mean(axis=1)
    return f, np.linalg.norm(f, axis=1)
