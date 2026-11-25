"""cfd3d_flow.py - steady laminar incompressible flow in 3D, with the temperature of the fluid, by finite elements on tetrahedra (no Qt).

  * linear (4-node) tetrahedra for the velocity AND the pressure, made stable by the standard stabilisation of that pair (Tezduyar's SUPG for the
    convection, PSPG for the pressure, and a least-squares term on the divergence): the equations are the incompressible Navier-Stokes equations with a
    constant density and viscosity
  * the steady state is reached by pseudo-time marching: backward Euler, the convection linearised with the velocity of the step before (Oseen), the step
    growing from a few cell-crossing times to very large ones; one coupled solve (velocity and pressure together) per step.  What it stops at is the
    steady state itself - the time terms of the equations vanish when nothing changes any more - so the result does not depend on the steps taken to get there
  * the coupled system is factorised (SuperLU) up to `DIRECT_LIMIT` unknowns; a larger one is solved by GMRES with an incomplete LU preconditioner
  * the temperature (optional, afterwards: the flow does not depend on it) by the same elements with SUPG: convection and conduction of the fluid, fixed
    temperatures and heat fluxes on the walls, a temperature or a function of the point on the inflow
  * forces and heat flows on a wall are the consistent ones (the residual of the equations tested with the nodes of the wall), which add up exactly
  * nothing is averaged or smoothed; what is returned is what the equations gave at the nodes

The mesh `q`:  {"nodes": (N, 3) in mesh units, "tets": (ne, 4), "patches": {name: (nt, 3) triangles of the boundary}}.  The patch names are the faces of the
part (integers) and anything else the mesher or a test gives them.  `spec` (SI inside; "lscale" = metres per mesh unit):
  "nu": m2/s   "rho": kg/m3   (and for the temperature "k": W/(m K), "cp": J/(kg K))
  "inlet":  {patch: vector m/s | callable(points m) -> (n, 3)}      the velocity is given there (the temperature: "T_in", see below)
  "outlet": [patch ...]                                              traction free, pressure 0
  "slip":   [patch ...]                                              a plane wall that does not hold the flow back (symmetry): only the normal velocity is zero
  "wall":   [patch ...]                                              no-slip: the velocity is zero
  "wall_T": {patch: K | callable(points mm) -> K}   "wall_q": {patch: W/m2 INTO the fluid | callable(points mm)}     the other walls, the slip planes and
                                                                     the outlet are insulated
  "T_in": K | callable(points mm) -> K,  "heat": True                 (the temperature is solved only with "heat")
  "x_ref": (N, 3) mm                                                 (optional) where the callables above are asked for the nodes: the places of the material points of a
                                                                     part that was moved (the mesh as drawn), instead of the nodes' own places
Pressure is the gauge pressure relative to the outlet.

Result:  {"u": (N, 3) m/s, "p": (N,) Pa, "status": "converged" | "stalled" | "not converged", "steps", "history": [change of the velocity per step],
          "disc": Disc, "boundary": Boundary, "mass": {...}, "T": (N,) K and "heat": {...} with the temperature, "seconds", ...}
"""
import time
import warnings

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl

import solid_fem as fem

FlowError = fem.FemError                    # the window shows these as messages, not as bugs
Cancelled = fem.Cancelled
REUSE_ITERS = 25                            # GMRES iterations allowed with the factorisation of an earlier step as the preconditioner
DIRECT_LIMIT = 70000                        # unknowns (4 per node) up to which the coupled system is factorised
TOL = 1.0e-7                                # the relative change of the velocity in one step at which the flow counts as steady
MAX_STEPS = 80
CFL0 = 4.0                                  # the first step crosses this many typical elements
GROWTH = 1.8                                # how much the step grows after a step that went well
DT_MAX_FACTOR = 1.0e6                       # the step never exceeds this times the first one
MAX_NODES = 2000000                         # (the keys of the faces are 64-bit integers of the node numbers)

_FACE = np.array([[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]])      # the face of a tetrahedron opposite to each of its nodes


def _stage(progress, key, size=0.0):
    fn = getattr(progress, "stage", None)
    if fn is not None:
        try:
            fn(key, size)
        except Exception:                                      # noqa: BLE001 - a progress bar is never a reason to fail
            pass


def _part(progress, fraction):
    fn = getattr(progress, "part", None)
    if fn is not None:
        try:
            fn(fraction)
        except Exception:                                      # noqa: BLE001
            pass


def _say(progress, text):
    if progress is None:
        return
    try:
        progress(text)
    except Exception:                                          # noqa: BLE001
        pass


# ------------------------------------------------------------------------------------------------------------------- the discretisation
class Disc:
    """The geometry of a mesh of linear tetrahedra and everything that is the same in every step: gradients, volumes, the sparsity pattern."""

    def __init__(self, nodes, tets, lscale=1.0):
        self.lscale = float(lscale)
        self.x = np.asarray(nodes, float) * self.lscale                # metres
        self.tets = np.asarray(tets, np.int64)
        self.N = len(self.x)
        self.ne = len(self.tets)
        if self.N > MAX_NODES:
            raise FlowError(f"The mesh has {self.N} nodes: too many for the flow solver (the limit is {MAX_NODES}). Use a coarser mesh.")
        P = self.x[self.tets]
        A = np.concatenate([np.ones((self.ne, 4, 1)), P], axis=2)
        det = np.linalg.det(A)
        scale = np.abs(det).max()
        if (np.abs(det) < 1e-12 * scale).any():
            raise FlowError("The mesh has a flat tetrahedron (almost zero volume): mesh the domain again, with a different element size.")
        Ainv = np.linalg.inv(A)
        self.g = np.ascontiguousarray(Ainv[:, 1:, :].transpose(0, 2, 1))          # (ne, 4, 3): the gradient of each shape function
        self.V = np.abs(det) / 6.0
        self.h = (6.0 * self.V / np.pi) ** (1.0 / 3.0)                          # the size of the element (the diameter of the sphere of its volume)
        I = np.repeat(self.tets[:, :, None], 4, axis=2).ravel()
        J = np.repeat(self.tets[:, None, :], 4, axis=1).ravel()
        key = I.astype(np.int64) * self.N + J
        uniq, self.inv = np.unique(key, return_inverse=True)
        self.indices = (uniq % self.N).astype(np.int32)
        rows = uniq // self.N
        self.indptr = np.searchsorted(rows, np.arange(self.N + 1)).astype(np.int32)
        self.nnz = len(uniq)
        self.gg = np.einsum("eik,ejk->eij", self.g, self.g)                     # (ne, 4, 4): grad N_i . grad N_j
        self.mass = (self.V / 20.0)[:, None, None] * (1.0 + np.eye(4))[None]    # consistent mass matrix of every element
        self._faces = None

    def csr(self, local):
        """The (N, N) sparse matrix of the element matrices `local` (ne, 4, 4)."""
        data = np.bincount(self.inv, weights=np.asarray(local).ravel(), minlength=self.nnz)
        return sp.csr_matrix((data, self.indices, self.indptr), shape=(self.N, self.N))

    def scatter(self, vals):
        """The sum over the elements of `vals` (ne, 4) per node: a right-hand side."""
        return np.bincount(self.tets.ravel(), weights=np.asarray(vals).ravel(), minlength=self.N)

    def element_mean(self, nodal):
        return np.asarray(nodal)[self.tets].mean(axis=1)

    def tau(self, a_norm, nu, dt=None):
        """The stabilisation parameter of every element (Tezduyar): small where the element is fine or the viscosity is large."""
        t = (2.0 * a_norm / self.h) ** 2 + (4.0 * nu / self.h ** 2) ** 2
        if dt is not None:
            t = t + (2.0 / dt) ** 2
        return 1.0 / np.sqrt(np.maximum(t, 1e-300))

    def boundary_faces(self, tri):
        """(element of every boundary triangle, its area vector pointing OUT of the domain (m2)): found by matching the triangle with a face of an element,
        so the orientation does not depend on how the mesher ordered its nodes."""
        tri = np.asarray(tri, np.int64)
        if self._faces is None:
            ef = np.sort(self.tets[:, _FACE], axis=2)                          # (ne, 4, 3)
            keys = ((ef[..., 0] * self.N + ef[..., 1]) * self.N + ef[..., 2]).ravel()
            order = np.argsort(keys, kind="stable")
            self._faces = (keys[order], order)
        ks, order = self._faces
        t = np.sort(tri, axis=1)
        tk = (t[:, 0] * self.N + t[:, 1]) * self.N + t[:, 2]
        pos = np.minimum(np.searchsorted(ks, tk), len(ks) - 1)
        if not (ks[pos] == tk).all():
            raise FlowError("A boundary triangle of the mesh is not a face of a tetrahedron (the mesh is not conforming).")
        flat = order[pos]
        ie, lf = flat // 4, flat % 4
        x = self.x[tri]
        a = 0.5 * np.cross(x[:, 1] - x[:, 0], x[:, 2] - x[:, 0])
        opp = self.x[self.tets[ie, lf]]
        inward = np.einsum("ij,ij->i", opp - x.mean(axis=1), a) > 0
        a[inward] *= -1.0
        return ie, a


# ------------------------------------------------------------------------------------------------------------------- the boundary
class Boundary:
    """Which nodes are held (velocity, pressure) and the boundary triangles of every role, from the patches of the mesh and the spec."""

    def __init__(self, disc, q, spec):
        self.disc = disc
        patches = {k: np.asarray(v, np.int64) for k, v in (q.get("patches") or {}).items() if len(v)}
        self.patches = patches
        roles = {}
        for role in ("inlet", "outlet", "slip", "wall"):
            val = spec.get(role) or ([] if role != "inlet" else {})
            names = list(val.keys()) if isinstance(val, dict) else list(val)
            for nm in names:
                if nm not in patches:
                    raise FlowError(f"The mesh has no boundary patch '{nm}' (used as {role}).")
                if nm in roles:
                    raise FlowError(f"The boundary patch '{nm}' is used twice ({roles[nm]} and {role}).")
                roles[nm] = role
        self.roles = roles
        N = disc.N
        self.nodes_of = {nm: np.unique(patches[nm].ravel()) for nm in patches}

        def nodes(role):
            return np.unique(np.concatenate([self.nodes_of[n] for n, r in roles.items() if r == role] or [np.zeros(0, np.int64)]))
        self.inlet_nodes, self.outlet_nodes, self.wall_nodes = nodes("inlet"), nodes("outlet"), nodes("wall")
        if not len(self.outlet_nodes):
            raise FlowError("The flow has no outlet: the pressure is not defined without one. Let the fluid leave the domain somewhere.")
        if not len(self.inlet_nodes):
            raise FlowError("The flow has no inlet: nothing drives it. Give the fluid a speed.")
        self.fixed_u = np.zeros((N, 3), bool)                              # velocity components that are given
        self.value_u = np.zeros((N, 3))
        self.fixed_p = np.zeros(N, bool)
        # the weakest first (slip: the normal component), then the inflow, then the walls: where two meet (an edge of the box and the body, the edge of the
        # inlet and a slip plane) the stronger one wins
        for nm, r in roles.items():
            if r != "slip":
                continue
            n = self.patch_normal(nm)
            ax = int(np.argmax(np.abs(n)))
            if abs(n[ax]) < 0.999:
                raise FlowError(f"The slip wall '{nm}' is not parallel to a coordinate plane: the free-slip condition is only for the planes of the box.")
            self.fixed_u[self.nodes_of[nm], ax] = True
        for nm, r in roles.items():
            if r != "inlet":
                continue
            nd = self.nodes_of[nm]
            v = spec["inlet"][nm]
            vals = np.asarray(v(disc.x[nd]), float).reshape(len(nd), 3) if callable(v) else np.tile(np.asarray(v, float).reshape(1, 3), (len(nd), 1))
            self.fixed_u[nd] = True
            self.value_u[nd] = vals
        self.fixed_u[self.wall_nodes] = True
        self.value_u[self.wall_nodes] = 0.0
        self.fixed_p[self.outlet_nodes] = True
        self._faces = {}

    def patch_normal(self, nm):
        tri = self.patches[nm]
        x = self.disc.x
        s = (0.5 * np.cross(x[tri[:, 1]] - x[tri[:, 0]], x[tri[:, 2]] - x[tri[:, 0]])).sum(axis=0)
        ln = np.linalg.norm(s)
        return s / ln if ln > 0 else np.array([1.0, 0.0, 0.0])

    def faces(self, nm):
        """(element, outward area vector) of every triangle of the patch (cached)."""
        if nm not in self._faces:
            self._faces[nm] = self.disc.boundary_faces(self.patches[nm])
        return self._faces[nm]

    def area(self, nm):
        return float(np.linalg.norm(self.faces(nm)[1], axis=1).sum())


# ------------------------------------------------------------------------------------------------------------------- the flow equations
def _blocks(d, u, nu, dt):
    a = d.element_mean(u)                                          # (ne, 3): the convecting velocity of every element
    an = np.linalg.norm(a, axis=1)
    tau = d.tau(an, nu, dt)
    ag = np.einsum("ek,ejk->ej", a, d.g)                           # a . grad N_j
    return an, tau, ag


def matrix(d, u, nu, dt):
    """The (4N, 4N) matrix of one step; unknowns [ux, uy, uz, p]; the pressure is the KINEMATIC pressure p / rho."""
    an, tau, ag = _blocks(d, u, nu, dt)
    V = d.V
    # momentum, one velocity component (all three have the same block): mass / dt + viscosity + convection + SUPG
    Auu = d.mass / dt + nu * V[:, None, None] * d.gg + (V / 4.0)[:, None, None] * ag[:, None, :] + (tau * V)[:, None, None] * ag[:, :, None] * ag[:, None, :]
    # the pressure gradient in the momentum equation (+ SUPG on it): [i, j] for the component k:  V/4 g_jk + tau V (a.g_i) g_jk
    Gk = ((V / 4.0)[:, None, None, None] + (tau * V)[:, None, None, None] * ag[:, :, None, None]) * d.g[:, None, :, :]
    # the continuity equation (test function q_i, velocity component k, shape function j): V/4 g_jk + PSPG: tau V g_ik (a.g_j) + tau V g_ik / (4 dt)
    Dk = (V / 4.0)[:, None, None, None] * d.g[:, None, :, :] * np.ones((1, 4, 1, 1)) \
        + (tau * V)[:, None, None, None] * d.g[:, :, None, :] * ag[:, None, :, None] \
        + (tau * V / (4.0 * dt))[:, None, None, None] * d.g[:, :, None, :] * np.ones((1, 1, 4, 1))
    Lp = (tau * V)[:, None, None] * d.gg                           # PSPG: the pressure's own Laplacian
    nuc = tau * an ** 2                                            # least squares on the divergence
    csr = d.csr
    rows = []
    for k in range(3):
        row = []
        for l in range(3):
            loc = (nuc * V)[:, None, None] * d.g[:, :, None, k] * d.g[:, None, :, l]
            if k == l:
                loc = loc + Auu
            row.append(csr(loc))
        row.append(csr(Gk[..., k]))
        rows.append(row)
    rows.append([csr(Dk[..., 0]), csr(Dk[..., 1]), csr(Dk[..., 2]), csr(Lp)])
    return sp.bmat(rows, format="csr")


def rhs_old(d, u, nu, dt):
    """The right-hand side that the velocity of the step before gives: the time terms of the momentum and (PSPG) of the continuity equation."""
    an, tau, ag = _blocks(d, u, nu, dt)
    V = d.V
    N = d.N
    Mt = d.mass / dt + (tau * V / (4.0 * dt))[:, None, None] * ag[:, :, None] * np.ones((1, 1, 4))
    r = np.zeros(4 * N)
    ue = u[d.tets]                                                 # (ne, 4, 3)
    for k in range(3):
        r[k * N:(k + 1) * N] = d.scatter(np.einsum("eij,ej->ei", Mt, ue[:, :, k]))
    um = ue.mean(axis=1)
    r[3 * N:] = d.scatter((tau * V / dt)[:, None] * np.einsum("eik,ek->ei", d.g, um))
    return r


def _apply_fixed(A, b, free, xfix):
    """The system with the fixed unknowns taken out (kept as rows of the identity, so that the matrix keeps its size and its pattern)."""
    s = free.astype(float)
    b2 = s * (b - A @ xfix) + (1.0 - s) * xfix
    D = sp.diags(s)
    A2 = (D @ A @ D + sp.diags(1.0 - s)).tocsr()
    return A2, b2


def _linear_solve(A, b, progress=None, previous=None, direct_limit=None, cache=None):
    """x for A x = b: factorised when the system is small enough, else GMRES with an incomplete LU preconditioner (which must reach a small residual,
    or the step is refused with a plain message).  `cache` keeps the last factorisation: the matrix changes little from one step to the next, so it
    serves as the preconditioner of the next one (a few GMRES iterations instead of a new factorisation) until it stops being good enough."""
    n = A.shape[0]
    lim = DIRECT_LIMIT if direct_limit is None else direct_limit
    nb = max(np.linalg.norm(b), 1e-300)
    if n <= lim:
        if cache is not None and cache.get("lu") is not None and cache.get("n") == n:
            count = [0]
            M = spl.LinearOperator(A.shape, cache["lu"].solve)
            x, _info = spl.gmres(A, b, x0=previous, M=M, rtol=1e-11, atol=0.0, restart=REUSE_ITERS, maxiter=1, callback=lambda _r: count.__setitem__(0, count[0] + 1),
                                 callback_type="pr_norm")
            if np.linalg.norm(A @ x - b) <= 1e-9 * nb:
                return x
        _stage(progress, "factor", float(n))
        with warnings.catch_warnings():
            warnings.simplefilter("error", spl.MatrixRankWarning)
            try:
                lu = spl.splu(A.tocsc(), permc_spec="COLAMD")
            except (RuntimeError, spl.MatrixRankWarning) as ex:
                raise FlowError("The flow equations could not be solved (the matrix is singular): " + str(ex) +
                                "  Check that the domain has an inlet and an outlet and that the mesh has no loose pieces.")
        if cache is not None:
            cache["lu"], cache["n"] = lu, n
        return lu.solve(b)
    _stage(progress, "ilu", float(A.nnz))
    try:
        ilu = spl.spilu(A.tocsc(), drop_tol=1e-4, fill_factor=12)
    except RuntimeError as ex:
        raise FlowError("The preconditioner of the flow solver could not be made (" + str(ex) + "). Use a coarser mesh.")
    M = spl.LinearOperator(A.shape, ilu.solve)
    x, _info = spl.gmres(A, b, x0=previous, M=M, rtol=1e-9, atol=0.0, restart=80, maxiter=60)
    if np.linalg.norm(A @ x - b) > 1e-6 * nb:
        raise FlowError("The iterative solver did not converge on this mesh. Use a coarser mesh.")
    return x


def solve_flow(q, spec, progress=None, cancel=None, direct_limit=None):
    """Steady flow.  See the header of the module for `q`, `spec` and the result."""
    cancel = cancel or (lambda: False)
    t0 = time.monotonic()
    d = Disc(q["nodes"], q["tets"], spec.get("lscale", 1e-3))
    bd = Boundary(d, q, spec)
    nu = float(spec["nu"])
    if not nu > 0:
        raise FlowError("The viscosity of the fluid must be greater than zero.")
    N = d.N
    free = np.ones(4 * N, bool)
    xfix = np.zeros(4 * N)
    for k in range(3):
        free[k * N:(k + 1) * N] = ~bd.fixed_u[:, k]
        xfix[k * N:(k + 1) * N] = np.where(bd.fixed_u[:, k], bd.value_u[:, k], 0.0)
    free[3 * N:] = ~bd.fixed_p
    uref = float(np.abs(bd.value_u).max())
    if not uref > 0:
        raise FlowError("The inflow has no speed: nothing drives the flow.")
    u = bd.value_u.copy()                                          # start: the inflow where it is given, half of it elsewhere
    inflow = bd.value_u[bd.inlet_nodes].mean(axis=0)
    u[~bd.fixed_u.any(axis=1)] = inflow * 0.5
    p = np.zeros(N)
    h_typ = float(np.median(d.h))
    dt0 = CFL0 * h_typ / uref
    dt = dt0
    hist = []
    status = "not converged"
    last = None
    sol_prev = None
    cache = {}
    best = np.inf
    stall = 0
    steps = 0
    for it in range(MAX_STEPS):
        if cancel():
            raise Cancelled()
        _part(progress, it / MAX_STEPS)
        _stage(progress, "assemble", float(d.ne))
        A = matrix(d, u, nu, dt)
        b = rhs_old(d, u, nu, dt)
        A2, b2 = _apply_fixed(A, b, free, xfix)
        x = _linear_solve(A2, b2, progress, sol_prev, direct_limit, cache)
        if not np.all(np.isfinite(x)):
            raise FlowError("The flow solution is not finite (the step was too large for this mesh). Use a finer mesh near the body or a lower speed.")
        sol_prev = x
        unew = np.stack([x[k * N:(k + 1) * N] for k in range(3)], axis=1)
        p = x[3 * N:]
        change = float(np.linalg.norm(unew - u) / max(np.linalg.norm(unew), 1e-30))
        u = unew
        steps += 1
        hist.append(change)
        _say(progress, f"flow: step {steps}, change {change:.2e}")
        if change < TOL:
            status = "converged"
            break
        if last is not None and change > 10.0 * last:             # the step was too bold: go back to a smaller one
            dt = max(dt * 0.25, dt0)
        elif last is None or change < last:
            dt = min(dt * GROWTH, dt0 * DT_MAX_FACTOR)
        last = change
        if change < best * 0.98:
            best, stall = change, 0
        else:
            stall += 1
            if stall >= 12 and dt >= dt0 * 1000:
                status = "stalled"
                break
    rho = float(spec.get("rho", 1.0))
    res = {"u": u, "p_kin": p, "p": p * rho, "status": status, "steps": steps, "history": hist, "disc": d, "boundary": bd, "nu": nu, "rho": rho,
           "unknowns": int(free.sum()), "tol": TOL, "dt_last": dt, "lscale": d.lscale,
           "solver": "direct" if 4 * N <= (DIRECT_LIMIT if direct_limit is None else direct_limit) else "gmres+ilu"}
    res["mass"] = mass_balance(res)
    if spec.get("heat"):
        solve_temperature(res, spec, progress, cancel)
    res["seconds"] = time.monotonic() - t0
    return res


# ------------------------------------------------------------------------------------------------------------------- the temperature
def _temperature_matrix(d, u, alpha):
    a = d.element_mean(u)
    an = np.linalg.norm(a, axis=1)
    tau = d.tau(an, alpha)
    ag = np.einsum("ek,ejk->ej", a, d.g)
    V = d.V
    loc = alpha * V[:, None, None] * d.gg + (V / 4.0)[:, None, None] * ag[:, None, :] + (tau * V)[:, None, None] * ag[:, :, None] * ag[:, None, :]
    return d.csr(loc)


def _eval(v, pts_mm):
    n = len(pts_mm)
    return np.asarray(v(pts_mm), float).reshape(n) if callable(v) else np.full(n, float(v))


def solve_temperature(res, spec, progress=None, cancel=None):
    """The temperature of the fluid on the flow in `res` (res["T"], K), and the heat that every fixed node gave to it (res["heat"]).  It can be called again
    with new wall temperatures: the flow is not solved again."""
    d, bd = res["disc"], res["boundary"]
    N = d.N
    k, cp, rho = float(spec["k"]), float(spec["cp"]), res["rho"]
    if not (k > 0 and cp > 0):
        raise FlowError("The conductivity and the heat capacity of the fluid must be greater than zero.")
    alpha = k / (rho * cp)
    A = _temperature_matrix(d, res["u"], alpha)
    fixed = np.zeros(N, bool)
    val = np.zeros(N)
    x_mm = d.x / d.lscale
    if spec.get("x_ref") is not None:
        x_mm = np.asarray(spec["x_ref"], float)
        if x_mm.shape != (N, 3):
            raise FlowError("The places the wall temperatures are asked for do not match the nodes of the mesh.")
    for nm, r in bd.roles.items():
        if r == "inlet":
            nodes = bd.nodes_of[nm]
            fixed[nodes] = True
            val[nodes] = _eval(spec.get("T_in", 293.15), x_mm[nodes])
    for nm, v in (spec.get("wall_T") or {}).items():
        if nm not in bd.nodes_of:
            raise FlowError(f"The mesh has no boundary patch '{nm}' (a wall temperature).")
        nodes = bd.nodes_of[nm]
        fixed[nodes] = True
        val[nodes] = _eval(v, x_mm[nodes])
    b = np.zeros(N)
    flux_in = 0.0
    for nm, q_in in (spec.get("wall_q") or {}).items():          # a heat flux into the fluid: the load of every node is its share of the area times q
        if nm not in bd.nodes_of:
            raise FlowError(f"The mesh has no boundary patch '{nm}' (a heat flux).")
        tri = bd.patches[nm]
        area = np.linalg.norm(bd.faces(nm)[1], axis=1)
        qv = _eval(q_in, x_mm[tri].mean(axis=1)) if callable(q_in) else np.full(len(tri), float(q_in))
        b += np.bincount(tri.ravel(), weights=np.repeat(area * qv / 3.0, 3), minlength=N) / (rho * cp)
        flux_in += float((area * qv).sum())
    s = (~fixed).astype(float)
    xf = np.where(fixed, val, 0.0)
    Df = sp.diags(s)
    A2 = (Df @ A @ Df + sp.diags(1.0 - s)).tocsc()
    rhs = s * (b - A @ xf) + (1.0 - s) * xf
    _stage(progress, "factor", float(N))
    with warnings.catch_warnings():
        warnings.simplefilter("error", spl.MatrixRankWarning)
        try:
            T = spl.splu(A2).solve(rhs)
        except (RuntimeError, spl.MatrixRankWarning) as ex:
            raise FlowError("The temperature could not be solved (" + str(ex) + "). Give the fluid an inflow temperature or a wall temperature.")
    if not np.all(np.isfinite(T)):
        raise FlowError("The temperature solution is not finite.")
    # the heat that the fixed nodes gave to the fluid (W): row i of (A T - b) is the heat conducted into the fluid at node i
    node_heat = np.where(fixed, (A @ T - b) * rho * cp, 0.0)
    owners = np.zeros(N)
    for nm in bd.nodes_of:
        if _is_thermal(bd, spec, nm):
            owners[bd.nodes_of[nm]] += 1.0
    res["T"] = T
    res["heat"] = {"fixed": fixed, "node_heat": node_heat, "owners": owners, "k": k, "cp": cp, "alpha": alpha, "flux_in": flux_in}
    res["T_range"] = (float(T.min()), float(T.max()))
    res["energy"] = heat_balance(res)
    return res


def _is_thermal(bd, spec, nm):
    return bd.roles.get(nm) == "inlet" or nm in (spec.get("wall_T") or {})


def patch_heat(res, nm):
    """The heat (W) that the nodes of the patch gave to the fluid (positive: the fluid is heated).  A node shared by two patches with a fixed temperature is
    split evenly between them, so the sum over the patches is the total."""
    h = res.get("heat")
    if h is None:
        return 0.0
    nodes = res["boundary"].nodes_of[nm]
    w = np.where(h["owners"][nodes] > 0, 1.0 / np.maximum(h["owners"][nodes], 1.0), 0.0)
    return float((h["node_heat"][nodes] * w).sum())


def _flux(res, role):
    """[(patch, its triangles, their area vectors OUT of the domain)] of the patches with the role."""
    bd = res["boundary"]
    return [(nm, bd.patches[nm], bd.faces(nm)[1]) for nm, r in bd.roles.items() if r == role]


def _face_product(av, tri, f, g):
    """The integral over every triangle of f * (g . n) dA for the nodal scalar f (N,) and the nodal vector g (N, 3): exact for linear fields.  `av` are the area
    vectors (so n dA = av)."""
    fe, ge = f[tri], g[tri]                                     # (nt, 3), (nt, 3, 3)
    return (1.0 / 12.0) * (fe.sum(axis=1) * np.einsum("tc,tc->t", av, ge.sum(axis=1)) + np.einsum("ti,tic,tc->t", fe, ge, av))


def heat_balance(res):
    """The energy balance the solution has to close: the enthalpy carried out through the outlet minus the one brought in through the inlet equals the heat
    that came in through the walls (the fixed temperatures and the fluxes).  {"enthalpy_out", "enthalpy_in", "gain", "walls", "mismatch", "T_ref"} in W.

    The enthalpies are measured from the mean inlet temperature T_ref: a mass balance that is not exact (and none is, on a mesh) would otherwise put
    rho cp T_ref times the leaked volume flow into the balance - with air at 293 K and a mass mismatch of 0.01 % that is more heat than a small heater makes."""
    h = res["heat"]
    rho, cp = res["rho"], h["cp"]
    bd = res["boundary"]
    inlet_nodes = [bd.nodes_of[nm] for nm, r in bd.roles.items() if r == "inlet"]
    t_ref = float(res["T"][np.unique(np.concatenate(inlet_nodes))].mean()) if inlet_nodes else 0.0
    out = inn = 0.0
    for role in ("outlet", "inlet"):
        for _nm, tri, av in _flux(res, role):
            e = rho * cp * _face_product(av, tri, res["T"] - t_ref, res["u"]).sum()
            if role == "outlet":
                out += float(e)
            else:
                inn += float(e)
    gain = out + inn                                           # the inflow flux is negative (u . outward normal)
    walls = float(h["node_heat"].sum()) + h["flux_in"]
    return {"enthalpy_out": out, "enthalpy_in": -inn, "gain": gain, "walls": walls, "T_ref": t_ref, "mismatch": abs(gain - walls) / max(abs(gain), abs(walls), 1e-30)}


# ------------------------------------------------------------------------------------------------------------------- post-processing
def mass_balance(res):
    """{"in": m3/s that comes in, "out": m3/s that goes out, "mismatch": relative difference}: what the discrete solution conserves (to within the mesh)."""
    q_in = q_out = 0.0
    for role in ("inlet", "outlet"):
        for _nm, tri, av in _flux(res, role):
            f = float(np.einsum("ij,ij->i", av, res["u"][tri].mean(axis=1)).sum())
            if role == "inlet":
                q_in -= f
            else:
                q_out += f
    return {"in": q_in, "out": q_out, "mismatch": abs(q_in - q_out) / max(abs(q_in), abs(q_out), 1e-30)}


def wall_force(res, patches):
    """The force (N, vectors) that the fluid puts on the wall made of the patches `patches`: {"total", "pressure", "viscous"}.

    "total" is the consistent one: the rows of the (steady) flow equations that belong to the nodes of the wall are what the wall has to carry for the rest
    of the equations to hold - so these reactions are exact for the discrete equations, they add up (with the ones of the other walls, the inlet and the
    outlet) to the momentum that passes through, and they need no gradient of the solution at the wall.
    "pressure" is the integral of the pressure over the wall; "viscous" is what is left of the total (the shear of the flow along the wall)."""
    d, bd = res["disc"], res["boundary"]
    nodes = []
    for nm in patches:
        if nm not in bd.nodes_of:
            raise FlowError(f"The mesh has no boundary patch '{nm}'.")
        nodes.append(bd.nodes_of[nm])
    nodes = np.unique(np.concatenate(nodes)) if nodes else np.zeros(0, np.int64)
    N = d.N
    A = res.get("_steady")
    if A is None:
        A = res["_steady"] = matrix(d, res["u"], res["nu"], 1.0e14).tocsr()            # (no time terms)
    x = np.concatenate([res["u"][:, k] for k in range(3)] + [res["p_kin"]])
    r = A @ x
    rho = res["rho"]
    total = np.array([-rho * r[k * N + nodes].sum() for k in range(3)])
    pres = np.zeros(3)
    for nm in patches:
        tri = bd.patches[nm]
        av = bd.faces(nm)[1]
        pres += (res["p"][tri].mean(axis=1)[:, None] * av).sum(axis=0)             # p times the area vector out of the fluid = the push on the wall
    return {"total": total, "pressure": pres, "viscous": total - pres}
