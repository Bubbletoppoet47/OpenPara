"""Tetrahedral (mesh based) FEA: STL -> reduced closed surface -> tetrahedra inside -> stiffness matrix.

NOT YET RUN by its author: this module was written without being executed.  Run  python test_tet.py  first (see the README).

    surface_problems(mesh)          open / non-manifold edges of a surface (must be 0 for a solid)
    crop_block(mesh, crop)          a flat-ended block cut from the middle of a closed surface (capped)
    reduce_surface(mesh, target)    adaptive triangle regularisation: quadric error decimation, flat areas lose triangles first, curved and thin
                                    areas keep them.  Returns (surface, info)
    Reference(mesh).deviation(new)  how far the reduced surface is from the original (both directions), plus the volume change
    tetrahedralise(surface, ...)    gmsh: uniform, or graded (small elements at the surface, bigger inside)  ->  nodes, tets
    to_quadratic(nodes, tets)       10-node tetrahedra (straight sided) from 4-node ones
    TetModel(nodes, conn)           what fem3d.solve needs (nn, ndof, conn, diag, matvec, node_xyz, fields, ...) with a sparse stiffness matrix

Units are whatever the mesh is in (the playground uses mm and N/mm^2)."""
import time

import numpy as np
import pyvista as pv

import cfea
import repair as R
import voxel as VX
from tasks import sub, tick

EDGES = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]        # VTK order of the 6 mid-edge nodes of a 10-node tetrahedron
# a rough guide for the size estimates only (measured on a lattice-like test shape, not on bone): tets per surface triangle
TETS_PER_TRI = {"uniform": 2.0, "graded": 1.5}
# stiffness matrix memory per element in bytes (rough: nodes ~ 1.45 x tets for 10-node, 0.15 x for 4-node; ~180 / ~42 non-zeros per row, 12 bytes each)
BYTES_PER_TET = {2: 9500.0, 1: 250.0}


# ---------------------------------------------------------------------------------------------------------------- the surface
def edge_lengths(P, T):
    e = np.concatenate([P[T[:, 0]] - P[T[:, 1]], P[T[:, 1]] - P[T[:, 2]], P[T[:, 2]] - P[T[:, 0]]])
    return np.linalg.norm(e, axis=1)


def surface_problems(mesh):
    """(open edges, non-manifold edges): both must be 0 before a solid can be made."""
    try:
        op = mesh.extract_feature_edges(boundary_edges=True, non_manifold_edges=False, feature_edges=False, manifold_edges=False).n_cells
        nm = mesh.extract_feature_edges(boundary_edges=False, non_manifold_edges=True, feature_edges=False, manifold_edges=False).n_cells
    except Exception:
        return 0, 0
    return int(op), int(nm)


def plain(mesh):
    """The surface as bare triangles (no arrays attached, so decimation and clipping are quick)."""
    P, T = R.arrays(mesh)
    return R.to_mesh(P, T)


def _clip_keep(mesh, axis, pos, keep_above):
    """Clip a closed surface at a plane, keeping the side above (or below) `pos` along `axis`, with the cut closed by a cap."""
    for sign in ((1.0, -1.0) if keep_above else (-1.0, 1.0)):
        n = [0.0, 0.0, 0.0]
        n[axis] = sign
        o = [0.0, 0.0, 0.0]
        o[axis] = pos
        try:
            out = mesh.clip_closed_surface(normal=n, origin=o)
        except TypeError:
            out = mesh.clip_closed_surface(n, o)
        if out.n_cells == 0:
            continue
        b = out.bounds
        lo, hi = b[2 * axis], b[2 * axis + 1]
        tol = 1e-4 * max(mesh.bounds[2 * axis + 1] - mesh.bounds[2 * axis], 1e-12)
        if (keep_above and lo >= pos - tol) or (not keep_above and hi <= pos + tol):
            return out
    raise ValueError("Cutting the block out of the surface left nothing (is the surface closed?).")


def crop_block(mesh, crop, progress=None):
    """A block cut from the middle: crop = (fx, fy, fz) fractions of the size.  Six clips with caps; the surface must be closed."""
    if min(crop) >= 0.999:
        return mesh
    b = np.asarray(mesh.bounds, float)
    lo, hi = b[0::2], b[1::2]
    mid, half = (lo + hi) / 2, (hi - lo) / 2 * np.asarray(crop, float)
    cur = mesh
    k = 0
    for ax in range(3):
        if crop[ax] >= 0.999:
            continue
        for keep_above, pos in ((True, mid[ax] - half[ax]), (False, mid[ax] + half[ax])):
            tick(progress, "Cutting the block out of the surface", k / 6.0)
            cur = _clip_keep(cur, ax, float(pos), keep_above)
            k += 1
    out = plain(cur.triangulate().clean())
    return out


def reduce_surface(mesh, target, engine="vtk", keep_volume=True, progress=None):
    """Adaptive triangle regularisation to about `target` triangles.  Quadric error decimation collapses the edges that change the shape least,
    so flat regions lose their triangles first and curved or thin regions keep them.  A result that is no longer a closed manifold is retried
    with a smaller reduction.  Returns (surface, info)."""
    P, T = R.arrays(mesh)
    n0 = len(T)
    t0 = time.time()
    info = {"triangles_in": n0, "engine": "none", "seconds": 0.0, "retries": 0}
    if target >= 0.98 * n0:
        info.update(triangles_out=n0, points_out=len(P), median_edge=float(np.median(edge_lengths(P, T))))
        return R.to_mesh(P, T), info
    red = float(np.clip(1.0 - target / n0, 0.0, 0.9995))
    base = R.to_mesh(P, T)
    out = None
    for attempt in range(4):
        tick(progress, f"Reducing the surface from {n0:,} to about {int(n0 * (1 - red)):,} triangles", 0.1 + 0.8 * attempt / 4.0)
        out, used = _decimate(base, red, engine, keep_volume)
        info["engine"] = used
        op, nm = surface_problems(out)
        if op == 0 and nm == 0:
            break
        red *= 0.8                                              # collapsed through itself / pinched a thin gap: ask for less
        info["retries"] += 1
    Q, U = R.arrays(out)
    op, nm = surface_problems(out)
    info.update(triangles_out=len(U), points_out=len(Q), open_edges=op, nonmanifold_edges=nm, median_edge=float(np.median(edge_lengths(Q, U))),
                min_edge=float(edge_lengths(Q, U).min()), max_edge=float(edge_lengths(Q, U).max()), seconds=time.time() - t0)
    return R.to_mesh(Q, U), info


def _decimate(base, red, engine, keep_volume):
    if engine == "fast":
        try:
            import fast_simplification as fs
            P, T = R.arrays(base)
            Q, U = fs.simplify(P, T.astype(np.int32), target_reduction=red, agg=7)
            return R.to_mesh(Q, np.asarray(U, np.int64)), "fast_simplification"
        except Exception:
            pass                                               # not installed or failed: the VTK decimator below
    try:
        out = base.decimate(red, volume_preservation=bool(keep_volume))
    except TypeError:
        out = base.decimate(red)
    return plain(out.triangulate().clean()), "VTK quadric"


class Reference:
    """The original surface, kept so that reduced versions can be compared with it (the distance tree is built once per call)."""

    def __init__(self, mesh):
        self.mesh = mesh
        self.P, self.T = R.arrays(mesh)
        self.volume = abs(R.signed_volume(self.P, self.T))

    @staticmethod
    def _dist(points, surface):
        pts = pv.PolyData(np.asarray(points, float))
        try:
            out = pts.compute_implicit_distance(surface, inplace=False)
            return np.abs(np.asarray(out["implicit_distance"]))
        except Exception:
            from vtkmodules.vtkFiltersCore import vtkImplicitPolyDataDistance
            f = vtkImplicitPolyDataDistance()
            f.SetInput(surface)
            return np.abs(np.array([f.EvaluateFunction(tuple(p)) for p in np.asarray(points, float)]))

    def deviation(self, new, progress=None, cap_new=100_000, cap_old=800_000, seed=0):
        """Distances (same length unit as the mesh) from the new surface's points to the original, and from the original's points to the new surface.
        Sampled when the surfaces are large, so 'max' is a close estimate, not a proof."""
        rng = np.random.default_rng(seed)
        Q, U = R.arrays(new)
        tick(progress, "Measuring the deviation: reduced surface against the original", 0.1)
        qi = np.arange(len(Q)) if len(Q) <= cap_new else rng.choice(len(Q), cap_new, replace=False)
        d1 = self._dist(Q[qi], self.mesh)
        tick(progress, "Measuring the deviation: original against the reduced surface", 0.6)
        pi = np.arange(len(self.P)) if len(self.P) <= cap_old else rng.choice(len(self.P), cap_old, replace=False)
        d2 = self._dist(self.P[pi], new)
        d = np.concatenate([d1, d2])
        v1 = abs(R.signed_volume(Q, U))
        return {"max": float(d.max()), "p99": float(np.percentile(d, 99)), "p999": float(np.percentile(d, 99.9)), "mean": float(d.mean()),
                "volume": v1, "volume_change": (v1 - self.volume) / max(self.volume, 1e-300), "samples": int(len(d))}


def count_for_deviation(ref, tol, start=8000, factor=2.0, bisect=2, engine="vtk", keep_volume=True, progress=None):
    """Fewest triangles (about) whose surface stays within `tol` of the original.  Doubles the count until the maximum deviation is
    below tol, then halves the last step `bisect` times.  Returns (count, rows [(target, triangles, max, p99, volume change)], reached)."""
    n0 = len(ref.T)
    rows = []
    fail_n, ok_n = None, None
    n = min(start, n0)
    steps = 0
    while True:
        steps += 1
        tick(progress, f"Trying {n:,} triangles", min(0.9, 0.05 * steps))
        s, info = reduce_surface(ref.mesh, n, engine, keep_volume)
        dv = ref.deviation(s)
        rows.append((n, info["triangles_out"], dv["max"], dv["p99"], dv["volume_change"]))
        if dv["max"] <= tol:
            ok_n = n
            break
        fail_n = n
        if n >= n0:
            break
        n = min(int(n * factor), n0)
    if ok_n is not None and fail_n is not None:
        lo, hi = fail_n, ok_n
        for _ in range(bisect):
            n = int((lo * hi) ** 0.5)
            if n <= lo * 1.05:
                break
            tick(progress, f"Trying {n:,} triangles", 0.9)
            s, info = reduce_surface(ref.mesh, n, engine, keep_volume)
            dv = ref.deviation(s)
            rows.append((n, info["triangles_out"], dv["max"], dv["p99"], dv["volume_change"]))
            if dv["max"] <= tol:
                hi = n
            else:
                lo = n
        ok_n = hi
    return (ok_n if ok_n is not None else n0), rows, ok_n is not None


# ---------------------------------------------------------------------------------------------------------------- tetrahedra
def _gmsh_start():
    import gmsh
    if gmsh.isInitialized():
        gmsh.finalize()
    try:
        gmsh.initialize(interruptible=False)                    # a worker thread cannot install gmsh's own Ctrl-C handler
    except TypeError:
        gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    return gmsh


def _gmsh_run(P, T, mode, s0, smax, growth, algorithm):
    gmsh = _gmsh_start()
    try:
        gmsh.model.add("tets")
        s = gmsh.model.addDiscreteEntity(2)
        gmsh.model.mesh.addNodes(2, s, list(range(1, len(P) + 1)), P.ravel().tolist())
        gmsh.model.mesh.addElementsByType(s, 2, list(range(1, len(T) + 1)), (T + 1).ravel().tolist())
        gmsh.model.geo.addSurfaceLoop([s], 1)
        gmsh.model.geo.addVolume([1], 1)
        gmsh.model.geo.synchronize()
        gmsh.option.setNumber("Mesh.Algorithm3D", algorithm)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        if mode == "graded":
            # size grows linearly with the distance from the surface: s0 within one element of it, then `growth` per unit of distance up to smax
            f = gmsh.model.mesh.field
            f.add("Distance", 1)
            f.setNumbers(1, "SurfacesList", [s])
            try:
                f.setNumber(1, "Sampling", 20)
            except Exception:
                pass                                            # older gmsh names this option differently; the default is fine
            f.add("Threshold", 2)
            f.setNumber(2, "InField", 1)
            f.setNumber(2, "SizeMin", s0)
            f.setNumber(2, "SizeMax", smax)
            f.setNumber(2, "DistMin", s0)
            f.setNumber(2, "DistMax", s0 + (smax - s0) / max(growth, 1e-3))
            f.setAsBackgroundMesh(2)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            gmsh.option.setNumber("Mesh.MeshSizeMin", 0.0)
            gmsh.option.setNumber("Mesh.MeshSizeMax", smax)
        gmsh.model.mesh.generate(3)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        et, _t, en = gmsh.model.mesh.getElements(3)
        if 4 not in list(et):
            raise RuntimeError("gmsh made no tetrahedra (the surface cuts through itself or is not closed)")
        tet = np.asarray(en[list(et).index(4)], np.int64).reshape(-1, 4)
        tags = np.asarray(tags, np.int64)
        xyz = np.asarray(coords, float).reshape(-1, 3)
        remap = np.full(int(tags.max()) + 1, -1, np.int64)
        remap[tags] = np.arange(len(tags))
        return xyz, remap[tet]
    finally:
        try:
            gmsh.clear()
            gmsh.finalize()
        except Exception:
            pass


def tet_quality(nodes, tets):
    """Per tetrahedron: 12 (3V)^(2/3) / sum(edge^2): 1 for a regular tetrahedron, near 0 for slivers.  Also the signed volumes."""
    a, b, c, d = (nodes[tets[:, i]] for i in range(4))
    V = np.einsum("ij,ij->i", b - a, np.cross(c - a, d - a)) / 6.0
    s = sum(np.einsum("ij,ij->i", x, x) for x in (b - a, c - a, d - a, c - b, d - b, d - c))
    q = 12.0 * (3.0 * np.abs(V)) ** (2.0 / 3.0) / np.maximum(s, 1e-300)
    return q, V


def tetrahedralise(surface, mode="uniform", biggest=4.0, growth=0.5, order=2, progress=None):
    """Fill a closed surface with tetrahedra.  mode 'uniform': elements about the size of the surface triangles everywhere (gmsh extends the boundary
    size inwards).  mode 'graded': elements the size of the surface triangles within one element of the surface, growing by `growth` per unit of
    distance up to `biggest` times that size.  order 2: 10-node tetrahedra.  Returns (nodes, conn, info)."""
    t0 = time.time()
    P, T = R.arrays(surface)
    op, nm = surface_problems(surface)
    if op or nm:
        raise ValueError(f"The surface is not closed: {op:,} open edges and {nm:,} non-manifold edges. Repair it in a Mesh tab first (or reduce less).")
    s0 = float(np.median(edge_lengths(P, T)))
    smax = s0 * float(biggest)
    errors = []
    xyz = tet = None
    used = ""
    for alg, name in ((1, "Delaunay"), (4, "Frontal-Delaunay"), (10, "HXT")):
        tick(progress, f"gmsh is meshing the inside ({name}; it cannot report progress or be cancelled)", 0.1)
        try:
            xyz, tet = _gmsh_run(P, T, mode, s0, smax, growth, alg)
            used = name
            break
        except Exception as ex:
            errors.append(f"{name}: {ex}")
    if tet is None:
        raise RuntimeError("gmsh could not fill the surface.  " + "  ".join(errors) + "  A surface that cuts through itself (typical of raw scans) needs repair in a Mesh tab first.")
    tick(progress, "Cleaning the tetrahedra", 0.8)
    q, V = tet_quality(xyz, tet)
    neg = V < 0
    if neg.any():
        tet[neg] = tet[neg][:, [0, 2, 1, 3]]
    keep = np.abs(V) > 1e-14 * max(float(np.abs(V).max()), 1e-300)
    tet = tet[keep]
    q = q[keep]
    used_nodes, inv = np.unique(tet.ravel(), return_inverse=True)
    xyz = xyz[used_nodes]
    tet = inv.reshape(-1, 4)
    vol = float(np.abs(V[keep]).sum())
    info = {"mode": mode, "algorithm": used, "tets": len(tet), "linear_nodes": len(xyz), "surface_size": s0, "biggest_size": smax, "volume": vol,
            "q_min": float(q.min()), "q_p1": float(np.percentile(q, 1)), "slivers": int((q < 0.02).sum()), "seconds": time.time() - t0, "retries": errors,
            "flipped": int(neg.sum()), "dropped": int((~keep).sum())}
    if order == 2:
        tick(progress, "Adding the mid-edge nodes (10-node tetrahedra)", 0.9)
        xyz, conn = to_quadratic(xyz, tet)
    else:
        conn = tet.astype(np.int32)
    info["nodes"] = len(xyz)
    info["order"] = order
    return xyz, conn, info


def to_quadratic(nodes, tets):
    """10-node tetrahedra with straight edges: the 4 corners, then the mid-edge nodes in VTK order (01, 12, 20, 03, 13, 23)."""
    nn, ne = len(nodes), len(tets)
    pairs = np.stack([np.sort(tets[:, [a, b]], axis=1) for a, b in EDGES], axis=1)
    key = pairs[..., 0].astype(np.int64) * nn + pairs[..., 1]
    uniq, inv = np.unique(key.ravel(), return_inverse=True)
    mid = 0.5 * (nodes[uniq // nn] + nodes[uniq % nn])
    conn = np.concatenate([tets, nn + inv.reshape(ne, 6)], axis=1).astype(np.int32)
    return np.vstack([nodes, mid]), conn


def box_tets(div, size, origin=(0.0, 0.0, 0.0)):
    """A box filled with tetrahedra without gmsh: each cube of a div[0] x div[1] x div[2] grid is cut into 6 tetrahedra along its main diagonal
    (the same diagonal in every cube, so neighbours fit).  Returns (nodes, tets).  Used by the built-in checks."""
    import itertools
    nx, ny, nz = (int(d) for d in div)
    ax = [origin[i] + np.linspace(0.0, size[i], n + 1) for i, n in enumerate((nx, ny, nz))]
    X, Y, Z = np.meshgrid(*ax, indexing="ij")
    nodes = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    idx = np.arange((nx + 1) * (ny + 1) * (nz + 1)).reshape(nx + 1, ny + 1, nz + 1)
    i, j, k = (a.ravel() for a in np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij"))
    tets = []
    for perm in itertools.permutations(range(3)):
        d = [0, 0, 0]
        verts = [idx[i, j, k]]
        for a in perm:
            d[a] = 1
            verts.append(idx[i + d[0], j + d[1], k + d[2]])
        tets.append(np.stack(verts, axis=1))
    return nodes, np.concatenate(tets).astype(np.int64)


def estimate(n_tris, mode, order):
    """Rough size of the model from the surface triangle count: (tets, unknowns, matrix GB).  A guide only."""
    nt = n_tris * TETS_PER_TRI[mode]
    nodes = nt * (1.45 if order == 2 else 0.18)
    return int(nt), int(3 * nodes), nt * BYTES_PER_TET[order] / 1e9


# ---------------------------------------------------------------------------------------------------------------- the finite element model
def _gauss():
    a, b = 0.1381966011250105, 0.5854101966249685
    pts = np.array([[b, a, a, a], [a, b, a, a], [a, a, b, a], [a, a, a, b]])
    return pts, np.full(4, 0.25)


def _dNdL(L, order):
    """Derivatives of the shape functions with respect to the 4 volume coordinates, at the point L: (nodes, 4)."""
    if order == 1:
        return np.eye(4)
    d = np.zeros((10, 4))
    for i in range(4):
        d[i, i] = 4 * L[i] - 1
    for k, (a, b) in enumerate(EDGES):
        d[4 + k, a] = 4 * L[b]
        d[4 + k, b] = 4 * L[a]
    return d


def _bmatrix(g):
    """Strain-displacement matrices (e, 6, 3 n) from shape function gradients g (e, n, 3); strain order xx yy zz xy yz xz (engineering shear)."""
    e, n, _ = g.shape
    B = np.zeros((e, 6, 3 * n))
    gx, gy, gz = g[:, :, 0], g[:, :, 1], g[:, :, 2]
    B[:, 0, 0::3] = gx
    B[:, 1, 1::3] = gy
    B[:, 2, 2::3] = gz
    B[:, 3, 0::3] = gy
    B[:, 3, 1::3] = gx
    B[:, 4, 1::3] = gz
    B[:, 4, 2::3] = gy
    B[:, 5, 0::3] = gz
    B[:, 5, 2::3] = gx
    return B


class TetModel:
    """Linear (4-node) or quadratic (10-node) tetrahedra.  Make it with the geometry, then assemble(E, nu).  Every node is used by some element."""

    def __init__(self, nodes, conn):
        self.nodes = np.ascontiguousarray(nodes, float)
        self.conn = np.ascontiguousarray(conn, np.int32)
        self.order = 2 if self.conn.shape[1] == 10 else 1
        self.ne, self.npe = self.conn.shape
        self.nn = len(self.nodes)
        self.ndof = 3 * self.nn
        self.K = None
        self.diag = None
        corner = self.nodes[self.conn[:, :4]]
        self.vol = np.abs(self._signed_volume(corner))
        d = [np.linalg.norm(corner[:, a] - corner[:, b], axis=1) for a, b in EDGES]
        self.h = np.mean(d, axis=0)
        self.dmin = np.min(d, axis=0)

    @staticmethod
    def _signed_volume(c):
        return np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])) / 6.0

    def _grad_L(self, s, e):
        """Gradients of the 4 volume coordinates for elements s:e, (n, 4, 3), and their volumes."""
        c = self.nodes[self.conn[s:e, :4]]
        A = np.ones((e - s, 4, 4))
        A[:, :, 1:] = c
        inv = np.linalg.inv(A)                                  # column i holds the coefficients of volume coordinate i
        return np.transpose(inv[:, 1:, :], (0, 2, 1)), self.vol[s:e]

    def _chunk(self):
        return 5000 if self.order == 2 else 20000

    def assemble(self, E, nu, progress=None, scale=None, native=True):
        """Stiffness matrix.  With the native library (fea3d/native, see cfea.py) the elements are assembled in C straight into CSR on all
        cores; without it the numpy code below does the same.  `scale` (one factor per element) is for nonlinear / damage updates."""
        import scipy.sparse as sp
        self.E, self.nu = float(E), float(nu)
        self.D = VX.material_matrix(E, nu)
        if native and cfea.available():
            if getattr(self, "_pattern", None) is None:
                tick(progress, "Finding the matrix pattern", 0.0)
                self._pattern = cfea.node_pattern(self.conn, self.nn)
            K, bad, _p = cfea.assemble(self.nodes, self.conn, self.order, self.D, self.nn, scale, self._pattern)
            if bad:
                raise ValueError(f"{bad} degenerate (zero-volume) tetrahedra")
            self.K = K
            self.diag = self.K.diagonal().copy()
            tick(progress, "Assembling the stiffness matrix", 1.0)
            return self
        npe, ne = self.npe, self.ne
        pts, w = _gauss() if self.order == 2 else (np.full((1, 4), 0.25), np.ones(1))
        dN = [_dNdL(L, self.order) for L in pts]
        chunk = self._chunk()
        acc, pile = None, []
        for s in range(0, ne, chunk):
            e = min(s + chunk, ne)
            gL, V = self._grad_L(s, e)
            if scale is not None:
                V = V * np.asarray(scale)[s:e]
            Ke = np.zeros((e - s, 3 * npe, 3 * npe))
            for dn, wt in zip(dN, w):
                g = np.einsum("ik,ekx->eix", dn, gL)
                B = _bmatrix(g)
                Ke += (wt * V)[:, None, None] * (B.transpose(0, 2, 1) @ (self.D @ B))
            ed = (3 * self.conn[s:e, :, None] + np.arange(3)[None, None, :]).reshape(e - s, 3 * npe)
            rows = np.repeat(ed, 3 * npe, axis=1).ravel()
            cols = np.tile(ed, (1, 3 * npe)).ravel()
            pile.append(sp.coo_matrix((Ke.ravel(), (rows, cols)), shape=(self.ndof, self.ndof)).tocsr())
            if len(pile) >= 6:
                acc = sum(pile) if acc is None else acc + sum(pile)
                pile = []
            tick(progress, "Assembling the stiffness matrix", e / ne)
        if pile:
            acc = sum(pile) if acc is None else acc + sum(pile)
        self.K = acc.tocsr()
        self.diag = self.K.diagonal().copy()
        return self

    # ---- what fem3d.solve / voxel.solve_free use
    def matvec(self, u):
        return self.K @ u

    def node_xyz(self):
        return self.nodes

    def node_xyz_all(self):
        return self.nodes

    def full(self, u):
        return u

    def centres(self):
        return self.nodes[self.conn[:, :4]].mean(axis=1)

    def element_size(self):
        return self.h

    def components(self):
        from scipy import sparse
        from scipy.sparse import csgraph
        ne, k = self.conn.shape
        rows = np.repeat(np.arange(ne), k)
        cols = ne + self.conn.ravel()
        g = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(ne + self.nn, ne + self.nn))
        return csgraph.connected_components(g, directed=False)[1][ne:]

    def fields(self, u):
        """Strain and stress at the centre of each element (the average of its Gauss points), then the usual stress measures."""
        if cfea.available():
            eps = cfea.centre_strain(self.nodes, self.conn, self.order, u)
            sig = eps @ self.D.T
            return VX.stress_fields(eps, sig, self.h)
        eps = np.zeros((self.ne, 6))
        L = np.full(4, 0.25)
        dn = _dNdL(L, self.order)
        chunk = self._chunk()
        for s in range(0, self.ne, chunk):
            e = min(s + chunk, self.ne)
            gL, _V = self._grad_L(s, e)
            B = _bmatrix(np.einsum("ik,ekx->eix", dn, gL))
            ed = (3 * self.conn[s:e, :, None] + np.arange(3)[None, None, :]).reshape(e - s, 3 * self.npe)
            eps[s:e] = np.einsum("eri,ei->er", B, u[ed])
        sig = eps @ self.D.T
        return VX.stress_fields(eps, sig, self.h)

    def grid(self, u=None, scale=0.0):
        """Display grid: one linear tetrahedron per element on the corner nodes (mid-edge nodes stay in the point list, unused)."""
        pts = self.nodes
        if u is not None and scale:
            pts = pts + scale * np.asarray(u).reshape(-1, 3)
        cells = np.hstack([np.full((self.ne, 1), 4, np.int64), self.conn[:, :4].astype(np.int64)]).ravel()
        g = pv.UnstructuredGrid(cells, np.full(self.ne, pv.CellType.TETRA, np.uint8), pts)
        g.cell_data["element size"] = self.h
        return g

    def summary(self):
        kind = "10-node" if self.order == 2 else "4-node"
        return (f"{self.ne:,} {kind} tetrahedra, {self.nn:,} nodes, {self.ndof:,} unknowns; element edge {self.dmin.min():.3g} to {self.h.max():.3g} "
                f"(mean {self.h.mean():.3g})")
