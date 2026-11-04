"""Node groups (supports, prescribed displacements, forces) and the general 3D solve, for voxel models and tetrahedral models alike.

A *region* is a place in space, not a list of node numbers, so a group survives a change of voxel or element size:
    box(lo, hi)                       an axis-aligned block (infinite limits allowed)
    view(M, rect, direction, depth)   what a rectangle drawn on screen covers, through the whole model (or a depth slab)
A *group* is: regions added / subtracted in order, a kind ('fixed', 'disp', 'force'), which of X Y Z it acts on, and values.
    fixed  the chosen directions cannot move             disp   the chosen directions are moved by `values` (mm)
    force  `values` (N) is the total force in the chosen directions, shared equally among the nodes

Model protocol (VX.Model and tet.TetModel): nn, ndof, conn, diag, matvec(u), node_xyz(), fields(u).
"""
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph

import voxel as VX
from tasks import sub, tick

AXES = "XYZ"
KINDS = {"fixed": "Support (fixed)", "disp": "Prescribed displacement", "force": "Force"}
COLOURS = {"fixed": "#2b7de9", "disp": "#1a9a50", "force": "#d6336c"}


class Region:
    def __init__(self, kind, **kw):
        self.kind = kind
        self.__dict__.update(kw)

    @staticmethod
    def box(lo, hi):
        return Region("box", lo=np.asarray(lo, float), hi=np.asarray(hi, float))

    @staticmethod
    def view(M, rect, direction=None, depth=None):
        """M: 4x4 camera matrix (world -> clip); rect: (x0, y0, x1, y1) in normalised screen coordinates -1..1;
        direction: unit view direction; depth: (t0, t1) limits of p . direction (None = through everything)."""
        x0, y0, x1, y1 = rect
        return Region("view", M=np.asarray(M, float), rect=(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)),
                      direction=None if direction is None else np.asarray(direction, float), depth=depth)

    def contains(self, xyz):
        xyz = np.asarray(xyz, float)
        if self.kind == "box":
            return ((xyz >= self.lo) & (xyz <= self.hi)).all(axis=1)
        hom = np.c_[xyz, np.ones(len(xyz))] @ self.M.T
        w = hom[:, 3]
        ok = w > 1e-12
        ndc = hom[:, :2] / np.where(ok, w, 1.0)[:, None]
        x0, y0, x1, y1 = self.rect
        m = ok & (ndc[:, 0] >= x0) & (ndc[:, 0] <= x1) & (ndc[:, 1] >= y0) & (ndc[:, 1] <= y1)
        if self.depth is not None and self.direction is not None:
            t = xyz @ self.direction
            m &= (t >= self.depth[0]) & (t <= self.depth[1])
        return m


def apply_ops(ops, xyz):
    m = np.zeros(len(xyz), bool)
    for mode, reg in ops:
        r = reg.contains(xyz)
        m = (m | r) if mode == "add" else (m & ~r)
    return m


class Group:
    def __init__(self, name, kind="fixed", axes=(True, True, True), values=(0.0, 0.0, 0.0), ops=None):
        self.name, self.kind = name, kind
        self.axes = list(axes)
        self.values = list(values)
        self.ops = list(ops or [])

    def mask(self, xyz):
        return apply_ops(self.ops, xyz)

    def describe(self):
        ax = "".join(a for a, on in zip(AXES, self.axes) if on) or "-"
        return f"{self.name}: {KINDS[self.kind]} ({ax})"


# ---------------------------------------------------------------------------------------------------------------- presets
def plate_groups(lo, hi, axis, strain, bonded=False, thickness=None, h=None):
    """The compression test as two groups: the bottom plate cannot move along `axis`, the top plate is pushed in by strain x length.
    Sliding plates leave the sides free (the solver pins the rigid motion); bonded plates hold the sides too.
    thickness: depth of the layer taken as the plate (default: a hair, i.e. the end layer of nodes of a grid)."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    t = thickness if thickness is not None else 1e-3 * (h if h else (hi[axis] - lo[axis]) / 100)
    L = hi[axis] - lo[axis]
    big = np.full(3, np.inf)
    b_lo, b_hi = -big.copy(), big.copy()
    b_hi[axis] = lo[axis] + t
    t_lo, t_hi = -big.copy(), big.copy()
    t_lo[axis] = hi[axis] - t
    axes = [True, True, True] if bonded else [a == axis for a in range(3)]
    vals = [0.0, 0.0, 0.0]
    vals[axis] = -strain * L
    return [Group("Bottom plate", "fixed", axes, [0, 0, 0], [("add", Region.box(b_lo - 1e-9, b_hi + 1e-9))]),
            Group("Top plate", "disp", axes, vals, [("add", Region.box(t_lo - 1e-9, t_hi + 1e-9))])]


# ---------------------------------------------------------------------------------------------------------------- the solve
def rigid_basis(xyz):
    c = xyz.mean(0)
    s = max(float(np.ptp(xyz, axis=0).max()), 1e-12)
    p = (xyz - c) / s
    R = np.zeros((3 * len(xyz), 6))
    for a in range(3):
        R[a::3, a] = 1
    R[1::3, 3], R[2::3, 3] = -p[:, 2], p[:, 1]
    R[0::3, 4], R[2::3, 4] = p[:, 2], -p[:, 0]
    R[0::3, 5], R[1::3, 5] = -p[:, 1], p[:, 0]
    return R


def components(model):
    """Label of the connected piece of each node."""
    if hasattr(model, "components"):
        return model.components()
    ne, k = model.conn.shape
    rows = np.repeat(np.arange(ne), k)
    cols = ne + model.conn.ravel()
    n = ne + model.nn
    g = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    _nc, lab = csgraph.connected_components(g, directed=False)
    return lab[ne:]


def solve(model, groups, method="auto", tol=1e-8, auto_pin=True, progress=None, maxit=4000):
    tick(progress, "Applying supports and loads", 0.0)
    xyz = model.node_xyz()
    nn, ndof = model.nn, model.ndof
    fixed = np.zeros(ndof, bool)
    val = np.zeros(ndof)
    b = np.zeros(ndof)
    masks = []
    for g in groups:
        m = g.mask(xyz)
        if not m.any():
            raise ValueError(f"The group '{g.name}' has no nodes. Select nodes and assign them, or check the voxel / element size.")
        masks.append(m)
    for g, m in zip(groups, masks):
        idx = np.nonzero(m)[0]
        for a in range(3):
            if not g.axes[a]:
                continue
            if g.kind in ("fixed", "disp"):
                fixed[3 * idx + a] = True
                val[3 * idx + a] = g.values[a] if g.kind == "disp" else 0.0
            else:
                b[3 * idx + a] += g.values[a] / len(idx)
    if not fixed.any():
        raise ValueError("There is no support. Add a group of kind 'Support (fixed)'.")
    notes = []
    lab = components(model)
    cons_nodes = np.unique(np.nonzero(fixed)[0] // 3)
    supported = np.isin(lab, np.unique(lab[cons_nodes]))
    loose = ~supported
    if loose.any():
        loaded = np.nonzero(b.reshape(-1, 3).any(1))[0]
        if loose[loaded].any():
            raise ValueError("A force acts on a piece that is not held by any support.")
        for a in range(3):
            fixed[3 * np.nonzero(loose)[0] + a] = True
        notes.append(f"{int(loose.sum()):,} nodes ({loose.mean() * 100:.1f} %) belong to pieces with no support; they are held still and carry nothing.")
    # rigid motions of each piece
    pins = []
    R = rigid_basis(xyz)
    for c in np.unique(lab[supported]):
        nodes = np.nonzero(lab == c)[0]
        dofs = np.nonzero(fixed.reshape(-1, 3)[nodes].ravel())[0]
        rows = (3 * nodes[dofs // 3] + dofs % 3)
        C = R[rows]
        rank = np.linalg.matrix_rank(C, tol=1e-9) if len(C) else 0
        if rank >= 6:
            continue
        if not auto_pin:
            raise ValueError(f"The model can still move as a rigid body ({6 - rank} free motions). Add supports.")
        cand_nodes = nodes if len(nodes) <= 600 else nodes[np.unique(np.linspace(0, len(nodes) - 1, 600).astype(int))]
        cand = np.array([[3 * n_ + a, n_, a] for n_ in cand_nodes for a in range(3)])
        for _ in range(6 - rank):
            u_, s_, vt = np.linalg.svd(C, full_matrices=True) if len(C) else (None, np.zeros(0), np.eye(6))
            r = int((s_ > 1e-9 * max(s_.max(), 1e-30)).sum()) if len(s_) else 0
            Nv = vt[r:].T
            if Nv.shape[1] == 0:
                break
            score = np.linalg.norm(R[cand[:, 0]] @ Nv, axis=1)
            j = int(np.argmax(score))
            if score[j] < 1e-9:
                break
            d, n_, a = cand[j]
            fixed[d] = True
            val[d] = 0.0
            pins.append((int(n_), int(a)))
            C = np.vstack([C, R[d]])
    if pins:
        notes.append(f"{len(pins)} extra pin(s) added to stop the model from sliding or turning freely (they should carry no force).")
    free = ~fixed
    tick(progress, "Setting up the equations", 0.05)
    rhs = (b - model.matvec(val)) * free
    x, it, rel, used = VX.solve_free(model, free, rhs, method, tol, maxit, sub(progress, 0.05, 0.95))
    u = x + val
    f = model.matvec(u)
    react = {}
    for g, m in zip(groups, masks):
        idx = np.nonzero(m)[0]
        if g.kind in ("fixed", "disp"):
            react[g.name] = np.array([f[3 * idx + a].sum() if g.axes[a] else 0.0 for a in range(3)])
    pin_load = float(sum(abs(f[3 * n_ + a]) for n_, a in pins))
    ref = max([np.abs(v).max() for v in react.values()] + [1e-30])
    if pins and pin_load > 1e-3 * ref + 1e-12:
        notes.append(f"WARNING: the extra pins carry {pin_load:.3g} N - the model is not fully supported, so the result depends on where they sit.")
    tick(progress, "Done", 1.0)
    fr, fm = f.reshape(-1, 3), fixed.reshape(-1, 3)
    equilibrium = {"reaction": [float(fr[:, a][fm[:, a]].sum()) for a in range(3)], "applied": [float(v) for v in b.reshape(-1, 3).sum(0)]}
    return {"u": u, "f": f, "fixed": fixed, "equilibrium": equilibrium, "pins": pins, "notes": notes, "reactions": react, "iterations": it, "residual": rel, "method": used, "tol": tol,
            "masks": masks, "groups": groups, "loose": int(loose.sum())}


def auto_axis(groups):
    """The direction of the test: the first of Z, X, Y that has both a support and a loaded group acting along it (None if none)."""
    for a in (2, 0, 1):
        sup = any(g.axes[a] and (g.kind == "fixed" or (g.kind == "disp" and g.values[a] == 0)) for g in groups)
        load = any(g.axes[a] and g.kind in ("disp", "force") and g.values[a] != 0 for g in groups)
        if sup and load:
            return a
    return None


def apparent(model, groups, res, axis, area=None, length=None):
    """Apparent modulus along `axis` from the reaction at the support and the movement of the loaded group.
    E = (F / A) / (d / L): F reaction force, A cross-section (default: bounding rectangle of the two groups), d the relative movement of
    the groups, L the distance between them."""
    xyz = model.node_xyz()
    u3, f3 = res["u"].reshape(-1, 3), res["f"].reshape(-1, 3)
    sup = load = None
    for g, m in zip(groups, res["masks"]):
        if not g.axes[axis]:
            continue
        if sup is None and (g.kind == "fixed" or (g.kind == "disp" and g.values[axis] == 0)):
            sup = (g, m)
        elif load is None and ((g.kind == "disp" and g.values[axis] != 0) or (g.kind == "force" and g.values[axis] != 0)):
            load = (g, m)
    if sup is None or load is None:
        raise ValueError(f"For the apparent modulus along {AXES[axis]} there must be a support and a loaded group (displacement or force) acting along {AXES[axis]}.")
    ms, ml = sup[1], load[1]
    L = length if length else abs(xyz[ml, axis].mean() - xyz[ms, axis].mean())
    d = u3[ml, axis].mean() - u3[ms, axis].mean()
    F = abs(f3[ms, axis].sum())
    lat = [a for a in range(3) if a != axis]
    both = ms | ml
    A = area if area else float(np.ptp(xyz[both, lat[0]]) * np.ptp(xyz[both, lat[1]]))
    strain = abs(d) / L
    stress = F / A
    return {"E_app": stress / strain if strain > 0 else float("nan"), "F": F, "d": abs(d), "L": L, "A": A, "strain": strain, "stress": stress,
            "support": sup[0].name, "load": load[0].name}


# ---------------------------------------------------------------------------------------------------------------- refinement
def fill_voxel_size(volume, box_size, make_volume, tol=0.05, start=None, factor=0.8, limit_elements=None, max_steps=14, progress=None):
    """Shrink the voxel until the voxel bone volume is within `tol` of the true volume.
    make_volume(h) -> (voxel volume, element count).  Returns (h, rows [(h, volume, error, elements)], reached)."""
    h = start if start else min(box_size) / 12.0
    rows = []
    for k in range(max_steps):
        tick(progress, f"Voxel size {h:.4g}: checking the volume", k / max_steps)
        v, n = make_volume(h)
        err = (v - volume) / volume
        rows.append((h, v, err, n))
        if abs(err) <= tol:
            return h, rows, True
        if limit_elements and n * (1 / factor) ** 3 > limit_elements:
            return h, rows, False
        h *= factor
    return rows[-1][0], rows, False


def converge(run, sizes, tol=0.02, progress=None):
    """Run at each size in turn (coarse to fine) until the apparent modulus changes by less than tol between two sizes.
    run(size) -> (E_app, elements); may raise ValueError (limit) to stop.  Returns rows [(size, elements, E_app, change)], converged, stop_reason."""
    rows = []
    reason = "ran out of sizes"
    sizes = list(sizes)
    for k, s in enumerate(sizes):
        tick(progress, f"Size {s:.4g}: solving", k / max(len(sizes), 1))
        try:
            E, n = run(s)
        except ValueError as ex:
            reason = str(ex)
            break
        change = None if not rows else (E - rows[-1][2]) / rows[-1][2]
        rows.append((s, n, E, change))
        if change is not None and abs(change) < tol:
            return rows, True, f"changed by {change * 100:+.2f} %, below {tol * 100:g} %"
    return rows, False, reason
