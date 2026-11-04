"""Voxel finite elements for porous / organic shapes (trabecular bone and the like).

Units: mm, N, MPa.  Every solid voxel is one 8-node brick (trilinear, plus incompatible modes so it does not stiffen in bending).
The system is never assembled: the solver multiplies element by element ("matrix free") and uses conjugate gradients with a diagonal
preconditioner.  Memory is about 300 bytes per element.

    occ  = voxelise(mesh, h)                         # closed mesh -> boolean array occ[i, j, k]
    res  = compress(occ, h, axis=2, strain=0.01, E=10000, nu=0.3)
    res["E_app"], res["F"], res["bvtv"] ...
    grid = to_grid(res)                               # pyvista grid with stress / displacement for display
"""
import time

import numpy as np
from scipy import ndimage

from tasks import Cancelled, sub, tick

CORNERS = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]])   # VTK hexahedron order
BYTES_PER_ELEMENT = 330
LATERAL = {0: (1, 2), 1: (0, 2), 2: (0, 1)}


# ---------------------------------------------------------------------------------------------------------------- the element
def material_matrix(E, nu):
    """Stress = D @ strain, strain order [xx, yy, zz, xy, yz, xz] (engineering shear strains)."""
    lam = E * nu / ((1 + nu) * (1 - 2 * nu))
    mu = E / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[0, 0] = D[1, 1] = D[2, 2] = lam + 2 * mu
    D[3, 3] = D[4, 4] = D[5, 5] = mu
    return D


def _shape_grads(xi, eta, zeta):
    """d N_i / d(xi, eta, zeta) of the 8 trilinear shape functions, shape (8, 3)."""
    s = 2.0 * CORNERS - 1.0
    g = np.zeros((8, 3))
    g[:, 0] = s[:, 0] * (1 + s[:, 1] * eta) * (1 + s[:, 2] * zeta) / 8
    g[:, 1] = s[:, 1] * (1 + s[:, 0] * xi) * (1 + s[:, 2] * zeta) / 8
    g[:, 2] = s[:, 2] * (1 + s[:, 0] * xi) * (1 + s[:, 1] * eta) / 8
    return g


def _B(xi, eta, zeta, h):
    g = _shape_grads(xi, eta, zeta) * (2.0 / h)             # d N / d(x, y, z)
    B = np.zeros((6, 24))
    for i in range(8):
        gx, gy, gz = g[i]
        c = 3 * i
        B[0, c] = gx
        B[1, c + 1] = gy
        B[2, c + 2] = gz
        B[3, c], B[3, c + 1] = gy, gx
        B[4, c + 1], B[4, c + 2] = gz, gy
        B[5, c], B[5, c + 2] = gz, gx
    return B


def _G(xi, eta, zeta, h):
    """Strain from the nine incompatible modes (phi = 1 - xi^2 etc. in each of x, y, z)."""
    gx, gy, gz = -4 * xi / h, -4 * eta / h, -4 * zeta / h
    G = np.zeros((6, 9))                                    # columns: ax1 ax2 ax3 ay1 ay2 ay3 az1 az2 az3
    G[0, 0] = gx
    G[1, 4] = gy
    G[2, 8] = gz
    G[3, 1], G[3, 3] = gy, gx
    G[4, 5], G[4, 7] = gz, gy
    G[5, 2], G[5, 6] = gz, gx
    return G


_cache = {}


def element(E, nu, h, incompatible=True):
    """Stiffness matrix (24 x 24) of one cube of side h, and the strain-from-displacement matrix at its centre."""
    key = (round(E, 9), round(nu, 9), round(h, 12), incompatible)
    if key in _cache:
        return _cache[key]
    D = material_matrix(E, nu)
    gp = 1 / np.sqrt(3)
    dv = (h / 2) ** 3
    Kuu = np.zeros((24, 24))
    Kua = np.zeros((24, 9))
    Kaa = np.zeros((9, 9))
    for a in (-gp, gp):
        for b in (-gp, gp):
            for c in (-gp, gp):
                B, G = _B(a, b, c, h), _G(a, b, c, h)
                Kuu += B.T @ D @ B * dv
                Kua += B.T @ D @ G * dv
                Kaa += G.T @ D @ G * dv
    K = Kuu - Kua @ np.linalg.solve(Kaa, Kua.T) if incompatible else Kuu
    K = 0.5 * (K + K.T)
    out = (K, _B(0, 0, 0, h), D)
    _cache[key] = out
    return out


# ---------------------------------------------------------------------------------------------------------------- voxelising
def grid_for(bounds, h, snap=False):
    """Origin and cell counts of a grid of size h over bounds (xmin, xmax, ymin, ymax, zmin, zmax).  snap: the grid is as close as
    possible to the box (rounding), otherwise it covers it (rounding up)."""
    lo = np.array(bounds[0::2], float)
    hi = np.array(bounds[1::2], float)
    q = (hi - lo) / h
    n = np.maximum(np.round(q - 1e-9).astype(int) if snap else np.ceil(q - 1e-9).astype(int), 1)
    return lo, n


def node_positions(occ, h, origin):
    """Corners of the solid voxels (the nodes of the model), without building the model."""
    cells = np.argwhere(occ)
    corner = (cells[:, None, :] + CORNERS[None, :, :]).reshape(-1, 3)
    shape = np.array(occ.shape) + 1
    flat = np.unique(np.ravel_multi_index(corner.T, shape))
    return np.asarray(origin, float) + np.array(np.unravel_index(flat, shape)).T * h


def estimate(mesh, h):
    """What a voxel size would cost, before doing it: cells in the box, solid elements (from the mesh volume), memory."""
    import solid
    lo, n = grid_for(mesh.bounds, h)
    cells = int(np.prod(n))
    vol = abs(solid.mesh_volume(mesh))
    elems = int(min(cells, vol / h ** 3))
    return {"n": tuple(int(x) for x in n), "cells": cells, "elements": elems, "dof": int(3 * elems * 1.25), "bytes": int(elems * BYTES_PER_ELEMENT + cells)}


def voxelise(mesh, h, progress=None, max_cells=400_000_000, box=None):
    """Closed triangle mesh -> (occ, origin).  A voxel is solid when its centre is inside the surface.
    box=(lo, hi): only that block of space is voxelised (the grid is snapped to it)."""
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy
    if box is not None:
        lo, n = grid_for(np.column_stack([box[0], box[1]]).ravel(), h, snap=True)
    else:
        lo, n = grid_for(mesh.bounds, h)
    if int(np.prod(n)) > max_cells:
        raise ValueError(f"The grid would have {int(np.prod(n)):,} cells - use a larger voxel size.")
    tick(progress, "Voxelising", None)
    import pyvista as pv
    poly = mesh if isinstance(mesh, pv.PolyData) else mesh.extract_surface()
    img = vtk.vtkImageData()
    img.SetDimensions(*[int(x) for x in n])
    img.SetSpacing(h, h, h)
    img.SetOrigin(*(lo + 0.5 * h))
    img.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    img.GetPointData().GetScalars().Fill(1)
    st = vtk.vtkPolyDataToImageStencil()
    st.SetInputData(poly)
    st.SetOutputOrigin(img.GetOrigin())
    st.SetOutputSpacing(img.GetSpacing())
    st.SetOutputWholeExtent(img.GetExtent())
    st.Update()
    cut = vtk.vtkImageStencil()
    cut.SetInputData(img)
    cut.SetStencilConnection(st.GetOutputPort())
    cut.ReverseStencilOff()
    cut.SetBackgroundValue(0)
    cut.Update()
    arr = vtk_to_numpy(cut.GetOutput().GetPointData().GetScalars()).reshape(int(n[2]), int(n[1]), int(n[0]))
    occ = np.ascontiguousarray(arr.transpose(2, 1, 0)) > 0
    return occ, lo


def keep_spanning(occ, axis):
    """Remove every piece of solid that does not connect (corner-to-corner counts, as the elements share nodes) the two end faces
    along `axis`.  Returns (new occ, labels of the kept pieces or None, fraction of solid removed)."""
    lab, n = ndimage.label(occ, structure=np.ones((3, 3, 3), int))
    if n == 0:
        return occ, lab, 0.0
    first = np.take(lab, 0, axis=axis)
    last = np.take(lab, occ.shape[axis] - 1, axis=axis)
    both = np.intersect1d(np.unique(first[first > 0]), np.unique(last[last > 0]))
    keep = np.isin(lab, both) if len(both) else np.zeros_like(occ)
    lab = np.where(keep, lab, 0)
    removed = 1.0 - keep.sum() / max(occ.sum(), 1)
    return keep, lab, float(removed)


# ---------------------------------------------------------------------------------------------------------------- the model
class Model:
    """Which elements exist, how they connect, and the matrix-free operator."""

    def __init__(self, occ, h, E, nu, origin=(0, 0, 0), incompatible=True):
        self.occ, self.h, self.E, self.nu = occ, float(h), float(E), float(nu)
        self.origin = np.asarray(origin, float)
        self.Ke, self.B0, self.D = element(E, nu, h, incompatible)
        self.cells = np.argwhere(occ)                                   # (ne, 3) element indices
        ne = len(self.cells)
        self.ne = ne
        shape = np.array(occ.shape) + 1
        corner = (self.cells[:, None, :] + CORNERS[None, :, :])        # (ne, 8, 3)
        flat = np.ravel_multi_index(corner.reshape(-1, 3).T, shape)
        used, inv = np.unique(flat, return_inverse=True)
        self.node_flat = used
        self.nn = len(used)
        self.node_ijk = np.array(np.unravel_index(used, shape)).T       # (nn, 3)
        self.conn = inv.reshape(ne, 8).astype(np.int32)
        self.edof = (3 * self.conn[:, :, None] + np.arange(3)[None, None, :]).reshape(ne, 24).astype(np.int32)
        self.ndof = 3 * self.nn
        self.diag = np.zeros(self.ndof)
        d = np.diag(self.Ke)
        for c in range(24):
            self.diag += np.bincount(self.edof[:, c], minlength=self.ndof) * d[c]

    def matvec(self, u):
        Fe = u[self.edof] @ self.Ke
        out = np.zeros(self.ndof)
        for c in range(24):
            out += np.bincount(self.edof[:, c], weights=Fe[:, c], minlength=self.ndof)
        return out

    def node_xyz(self):
        return self.origin + self.node_ijk * self.h

    def layer_nodes(self, axis, which):
        k = 0 if which == 0 else self.occ.shape[axis]
        return np.nonzero(self.node_ijk[:, axis] == k)[0]

    def element_stress(self, u):
        eps = (u[self.edof] @ self.B0.T)                                # B0 already carries 1/h
        sig = eps @ self.D.T
        return eps, sig

    def fields(self, u):
        """Per-element results: von Mises, normal and shear stresses, principal stresses, strain energy density."""
        eps, sig = self.element_stress(u)
        return stress_fields(eps, sig, np.full(self.ne, self.h))

    def full(self, u):
        return u

    def node_xyz_all(self):
        return self.node_xyz()

    def centres(self):
        return self.origin + (self.cells + 0.5) * self.h

    def element_size(self):
        return np.full(self.ne, self.h)

    def grid(self, u=None, scale=0.0):
        return model_grid(self, u, scale)

    def components(self):
        from scipy import sparse
        from scipy.sparse import csgraph
        ne, k = self.conn.shape
        rows = np.repeat(np.arange(ne), k)
        cols = ne + self.conn.ravel()
        g = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(ne + self.nn, ne + self.nn))
        return csgraph.connected_components(g, directed=False)[1][ne:]


def stress_fields(eps, sig, size):
    t = np.zeros((len(sig), 3, 3))
    t[:, 0, 0], t[:, 1, 1], t[:, 2, 2] = sig[:, 0], sig[:, 1], sig[:, 2]
    t[:, 0, 1] = t[:, 1, 0] = sig[:, 3]
    t[:, 1, 2] = t[:, 2, 1] = sig[:, 4]
    t[:, 0, 2] = t[:, 2, 0] = sig[:, 5]
    w = np.linalg.eigvalsh(t)
    return {"von Mises": von_mises(sig), "sxx": sig[:, 0], "syy": sig[:, 1], "szz": sig[:, 2], "txy": sig[:, 3], "tyz": sig[:, 4], "txz": sig[:, 5],
            "s1": w[:, 2], "s3": w[:, 0], "tmax": 0.5 * (w[:, 2] - w[:, 0]), "strain energy": 0.5 * (eps * sig).sum(1), "brick size": np.asarray(size, float)}


def von_mises(sig):
    sx, sy, sz, txy, tyz, txz = sig.T
    return np.sqrt(np.maximum(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (txy ** 2 + tyz ** 2 + txz ** 2), 0))


# ---------------------------------------------------------------------------------------------------------------- the solver
def cg(model, free, rhs, tol=1e-6, maxit=4000, progress=None, x0=None):
    """Conjugate gradients on the free degrees of freedom (full-length vectors, fixed ones stay zero)."""
    M = np.where(free, 1.0 / np.maximum(model.diag, 1e-30), 0.0)
    x = np.zeros(model.ndof) if x0 is None else x0.copy()
    r = rhs.copy()
    if x0 is not None:
        r -= model.matvec(x) * free
    r *= free
    b0 = np.linalg.norm(rhs * free)
    if b0 == 0:
        return x, 0, 0.0
    z = M * r
    p = z.copy()
    rz = r @ z
    r0 = np.linalg.norm(r)
    hist = np.log(max(r0 / b0, 1e-300))
    it = 0
    t0 = time.time()
    rel = r0 / b0
    for it in range(1, maxit + 1):
        Ap = model.matvec(p) * free
        a = rz / (p @ Ap)
        x += a * p
        r -= a * Ap
        rel = np.linalg.norm(r) / b0
        if it % 5 == 0 and progress is not None:
            done = np.log(max(rel, 1e-300))
            frac = min(max((0.0 - done) / (0.0 - np.log(tol)), 0.0), 1.0)
            tick(progress, f"Solving: iteration {it}, residual {rel:.1e}", frac)
        if rel < tol:
            break
        z = M * r
        rz_new = r @ z
        p = z + (rz_new / rz) * p
        rz = rz_new
    return x, it, float(rel)


def have(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def assemble(model, progress=None, chunk=25000):
    """The stiffness matrix as a scipy CSR matrix (built in pieces so the temporary memory stays small)."""
    import scipy.sparse as sp
    if hasattr(model, "K"):
        return model.K
    K = None
    Ke = model.Ke.ravel()
    for s in range(0, model.ne, chunk):
        ed = model.edof[s:s + chunk]
        rows = np.repeat(ed, 24, axis=1).ravel()
        cols = np.tile(ed, (1, 24)).ravel()
        Kc = sp.csr_matrix((np.tile(Ke, len(ed)), (rows, cols)), shape=(model.ndof, model.ndof))
        K = Kc if K is None else K + Kc
        tick(progress, "Assembling the stiffness matrix", min((s + chunk) / model.ne, 1.0))
    return K


def rigid_modes(model):
    """The six rigid-body motions as columns (a good coarse space for algebraic multigrid on elasticity)."""
    xyz = model.node_xyz()
    xyz = xyz - xyz.mean(0)
    B = np.zeros((model.ndof, 6))
    for c in range(3):
        B[c::3, c] = 1
    B[1::3, 3], B[2::3, 3] = -xyz[:, 2], xyz[:, 1]
    B[0::3, 4], B[2::3, 4] = xyz[:, 2], -xyz[:, 0]
    B[0::3, 5], B[1::3, 5] = -xyz[:, 1], xyz[:, 0]
    return B


def choose_method(model, method):
    if method != "auto":
        return method
    if have("pypardiso") and model.ndof < 350_000:
        return "direct"
    if have("pyamg"):
        return "amg"
    if have("pypardiso") and model.ndof < 700_000:
        return "direct"
    return "cg"


def solve_free(model, free, rhs, method="auto", tol=1e-6, maxit=4000, progress=None):
    """Solve K_ff x = rhs.  method: 'amg' (algebraic multigrid + CG, needs pyamg), 'direct' (PARDISO or SuperLU),
    'cg' (matrix free, slow on thin struts) or 'auto'.  Returns (x with zeros on fixed dofs, iterations, residual, method used)."""
    method = choose_method(model, method)
    if method in ("gmg", "dd") and not hasattr(model, "occ"):
        method = "amg" if have("pyamg") else "cg"             # these two work on the plain voxel grid; other meshes use the older solvers
    if method == "gmg":
        import gmg
        x, it, rel, info = gmg.solve(model, free, rhs, max(tol, 1e-10), min(maxit, 400), progress)
        return x, it, rel, f"parallel multigrid (Numba, {info['threads']} threads, {info['levels']} levels)"
    if method == "dd":
        import dd
        x, it, rel, info = dd.solve(model, free, rhs, tol, maxit, progress)
        return x, it, rel, info["name"]
    if method == "cg":
        x, it, rel = cg(model, free, rhs, tol, maxit, progress)
        return x, it, rel, "cg"
    import scipy.sparse.linalg as spl
    K = assemble(model, sub(progress, 0.0, 0.3) if progress else None)
    fi = np.nonzero(free)[0]
    tick(progress, "Selecting the free equations", 0.3)
    Kff = K[fi][:, fi].tocsr()
    del K
    b = rhs[fi]
    x = np.zeros(model.ndof)
    if method == "direct":
        tick(progress, "Factorising (direct solver)", 0.4)
        if have("pypardiso"):
            import pypardiso
            x[fi] = pypardiso.spsolve(Kff, b)
            name = "direct (PARDISO)"
        else:
            x[fi] = spl.splu(Kff.tocsc()).solve(b)
            name = "direct (SuperLU)"
        r = np.linalg.norm(Kff @ x[fi] - b) / max(np.linalg.norm(b), 1e-300)
        return x, 1, float(r), name
    import pyamg
    tick(progress, "Setting up multigrid", 0.4)
    ml = pyamg.smoothed_aggregation_solver(Kff, B=rigid_modes(model)[fi], max_coarse=500)
    count = [0]

    def cb(_xk):
        count[0] += 1
        tick(progress, f"Solving: multigrid iteration {count[0]}", min(0.6 + 0.4 * count[0] / 40, 0.99))
    x[fi] = ml.solve(b, tol=tol, maxiter=max(maxit, 100), accel="cg", callback=cb)
    r = np.linalg.norm(Kff @ x[fi] - b) / max(np.linalg.norm(b), 1e-300)
    return x, count[0], float(r), "multigrid + CG"


def _pins(model, axis, bottom_nodes, labels):
    """Lateral pins that stop sliding / turning of each separate piece (sliding supports leave these free otherwise)."""
    l1, l2 = LATERAL[axis]
    xyz = model.node_xyz()
    pins = []
    node_label = np.zeros(model.nn, int)
    for c in range(8):                                                  # label of a node: label of any element touching it
        node_label[model.conn[:, c]] = labels[tuple(model.cells.T)]
    for lab in np.unique(node_label[bottom_nodes]):
        nodes = bottom_nodes[node_label[bottom_nodes] == lab]
        a = nodes[0]
        d = xyz[nodes][:, [l1, l2]] - xyz[a][[l1, l2]]
        b = nodes[np.argmax((d ** 2).sum(1))]
        pins.append((a, l1))
        pins.append((a, l2))
        dd = xyz[b][[l1, l2]] - xyz[a][[l1, l2]]
        if np.abs(dd).max() > 0:
            pins.append((b, l2 if abs(dd[0]) >= abs(dd[1]) else l1))
    return pins


def compress(occ, h, axis=2, strain=0.01, E=10000.0, nu=0.3, bonded=False, tol=1e-8, maxit=4000, origin=(0, 0, 0),
             remove_islands=True, incompatible=True, method="auto", progress=None):
    """Compression test.  The bottom face (index 0 along `axis`) cannot move along `axis`, the top face is pushed down by
    strain * length.  Sliding (default): the faces may slide sideways.  Bonded: the faces cannot move sideways at all.
    Returns a dict with the apparent modulus E_app, reaction force F, stresses and the model."""
    t0 = time.time()
    tick(progress, "Removing floating pieces", 0.0)
    solid_all = int(occ.sum())
    if solid_all == 0:
        raise ValueError("There is no solid in the grid.")
    if remove_islands:
        occ, labels, removed = keep_spanning(occ, axis)
        if not occ.any():
            raise ValueError("No piece of solid reaches both end faces of the box, so nothing can carry the load. Cut a flat-ended block from the middle (Block from the middle < 100 %) or pick another load direction.")
    else:
        labels, _n = ndimage.label(occ, structure=np.ones((3, 3, 3), int))
        removed = 0.0
    tick(progress, "Building elements", 0.05)
    m = Model(occ, h, E, nu, origin, incompatible)
    bottom, top = m.layer_nodes(axis, 0), m.layer_nodes(axis, 1)
    L = occ.shape[axis] * h
    d = strain * L
    fixed = np.zeros(m.ndof, bool)
    val = np.zeros(m.ndof)
    fixed[3 * bottom + axis] = True
    fixed[3 * top + axis] = True
    val[3 * top + axis] = -d
    l1, l2 = LATERAL[axis]
    if bonded:
        for nodes in (bottom, top):
            fixed[3 * nodes + l1] = True
            fixed[3 * nodes + l2] = True
    else:
        for node, comp in _pins(m, axis, bottom, labels):
            fixed[3 * node + comp] = True
    free = ~fixed
    f0 = m.matvec(val)                                                  # force the prescribed displacements cause
    rhs = -f0 * free
    u, it, rel, used = solve_free(m, free, rhs, method, tol, maxit, sub(progress, 0.1, 0.95) if progress else None)
    u += val
    f = m.matvec(u)
    F = float(-f[3 * top + axis].sum())                                 # compressive force, positive
    area = float(np.prod([occ.shape[i] for i in LATERAL[axis]])) * h * h
    stress = F / area
    eps, sig = m.element_stress(u)
    vm = von_mises(sig)
    res = {
        "model": m, "u": u, "axis": axis, "h": h, "strain": strain, "d": d, "L": L, "area": area, "F": F, "stress": stress,
        "E_app": stress / strain, "iterations": it, "residual": rel, "bonded": bonded, "method": used,
        "bvtv": float(occ.sum()) / occ.size, "bvtv_input": solid_all / occ.size, "removed": removed,
        "vm": vm, "sig_axis": sig[:, axis], "sed": 0.5 * (eps * sig).sum(1), "seconds": time.time() - t0, "occ": occ,
        "elements": m.ne, "dof": m.ndof,
    }
    tick(progress, "Done", 1.0)
    return res


def solve_bc(occ, h, fixed_dofs, loads, E=10000.0, nu=0.3, tol=1e-9, maxit=20000, incompatible=True, method="auto", progress=None):
    """General solve for tests: fixed_dofs {(i, j, k, comp): value} on node indices, loads {(i, j, k, comp): force}.  Returns (model, u)."""
    m = Model(occ, h, E, nu, (0, 0, 0), incompatible)
    shape = np.array(occ.shape) + 1
    lookup = {int(f): n for n, f in enumerate(m.node_flat)}
    fixed = np.zeros(m.ndof, bool)
    val = np.zeros(m.ndof)
    for (i, j, k, c), v in fixed_dofs.items():
        n = lookup[int(np.ravel_multi_index((i, j, k), shape))]
        fixed[3 * n + c] = True
        val[3 * n + c] = v
    b = np.zeros(m.ndof)
    for (i, j, k, c), v in loads.items():
        n = lookup[int(np.ravel_multi_index((i, j, k), shape))]
        b[3 * n + c] += v
    free = ~fixed
    rhs = (b - m.matvec(val)) * free
    u, it, rel, used = solve_free(m, free, rhs, method, tol, maxit, progress)
    return m, u + val


# ---------------------------------------------------------------------------------------------------------------- display
def to_grid(res, scale=0.0):
    """A pyvista grid of the solid voxels: cell data 'von Mises', 'axial stress', 'strain energy'; point data 'displacement'."""
    import pyvista as pv
    m = res["model"]
    pts = m.node_xyz()
    u = res["u"].reshape(-1, 3)
    cells = np.hstack([np.full((m.ne, 1), 8, np.int64), m.conn.astype(np.int64)]).ravel()
    g = pv.UnstructuredGrid(cells, np.full(m.ne, 12, np.uint8), pts + scale * u)
    g.cell_data["von Mises"] = res["vm"]
    g.cell_data["axial stress"] = res["sig_axis"]
    g.cell_data["strain energy"] = res["sed"]
    g.point_data["displacement"] = np.linalg.norm(u, axis=1)
    g.point_data["u"] = u
    return g


def model_grid(model, u=None, scale=0.0):
    """Display grid of a voxel model (one hexahedron per element)."""
    import pyvista as pv
    pts = model.node_xyz()
    if u is not None and scale:
        pts = pts + scale * np.asarray(u).reshape(-1, 3)
    cells = np.hstack([np.full((model.ne, 1), 8, np.int64), model.conn.astype(np.int64)]).ravel()
    return pv.UnstructuredGrid(cells, np.full(model.ne, 12, np.uint8), pts)
