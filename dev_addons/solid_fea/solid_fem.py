"""
solid_fem.py - meshing and the linear elastic solver of the 3D FEA add-on (no window).

  mesh_solid(geom, h, cancel)       gmsh fills the part (a STEP of it) with tetrahedra -> {"nodes", "tets", "faces": {face id: triangles}, "verts": {vertex id: node}}
  quadratic(mesh)                   10-node tetrahedra with straight edges (VTK node order); the triangles of every face get their mid-edge nodes
  Problem(...).solve()              K u = f for a linear elastic isotropic material; supports and loads from the faces of the part

Units: mm, N, MPa (so a density of 7850 kg/m3 is 7.85e-9 t/mm3 and gravity 9810 mm/s2).
"""
import os
import tempfile
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl

EDGES = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]                      # VTK order of the mid-edge nodes of a 10-node tetrahedron
_A, _B = 0.5854101966249685, 0.1381966011250105
GAUSS = np.array([[_A, _B, _B, _B], [_B, _A, _B, _B], [_B, _B, _A, _B], [_B, _B, _B, _A]])         # 4 points, exact for degree 2
GW = np.full(4, 0.25)


class FemError(Exception):
    pass


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------------------------------------------------------------ mesh
def mesh_solid(geom, h, cancel=lambda: False, progress=lambda t: None):
    import gmsh
    if cancel():
        raise Cancelled()
    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(geom["step"])
    if gmsh.isInitialized():
        gmsh.finalize()
    try:
        gmsh.initialize(interruptible=False)
    except TypeError:
        gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("solid")
        gmsh.model.occ.importShapes(path)
        gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(3):
            raise FemError("gmsh found no solid in the part.")
        fmap = _match_surfaces(gmsh, geom)
        gmsh.option.setNumber("Mesh.MeshSizeMax", float(h))
        gmsh.option.setNumber("Mesh.MeshSizeMin", float(h) / 6.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 10)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        progress("meshing")
        err = []
        done = False
        for alg in (1, 4, 10):
            try:
                gmsh.model.mesh.clear()
                gmsh.option.setNumber("Mesh.Algorithm3D", alg)
                gmsh.model.mesh.generate(3)
                done = True
                break
            except Exception as ex:
                err.append(str(ex))
        if not done:
            raise FemError("gmsh could not mesh the part: " + "; ".join(err))
        if cancel():
            raise Cancelled()
        tags, coords, _ = gmsh.model.mesh.getNodes()
        tags = np.asarray(tags, np.int64)
        xyz = np.asarray(coords, float).reshape(-1, 3)
        remap = np.full(int(tags.max()) + 1, -1, np.int64)
        remap[tags] = np.arange(len(tags))
        _t, ent = gmsh.model.mesh.getElementsByType(4)
        tets = remap[np.asarray(ent, np.int64).reshape(-1, 4)]
        faces = {}
        for tag, fid in fmap.items():
            et, _et, en = gmsh.model.mesh.getElements(2, tag)
            if 2 in list(et):
                tri = remap[np.asarray(en[list(et).index(2)], np.int64).reshape(-1, 3)]
                faces[fid] = np.vstack([faces[fid], tri]) if fid in faces else tri
        verts = {}
        gv = np.asarray(geom["verts"], float)
        for (_d, tag) in gmsh.model.getEntities(0):
            nt, nc, _ = gmsh.model.mesh.getNodes(0, tag)
            if len(nt) and len(gv):
                p = np.asarray(nc, float).reshape(3)
                i = int(np.argmin(np.linalg.norm(gv - p, axis=1)))
                if np.linalg.norm(gv[i] - p) < 1e-6 * max(geom["diag"], 1.0) * 10:
                    verts[i] = int(remap[int(nt[0])])
    finally:
        try:
            gmsh.clear()
            gmsh.finalize()
        except Exception:
            pass
        try:
            os.remove(path)
        except OSError:
            pass
    used, inv = np.unique(tets.ravel(), return_inverse=True)           # only nodes that belong to tetrahedra
    new = np.full(len(xyz), -1, np.int64)
    new[used] = np.arange(len(used))
    xyz = xyz[used]
    tets = inv.reshape(-1, 4)
    faces = {k: new[v] for k, v in faces.items()}
    faces = {k: v[(v >= 0).all(axis=1)] for k, v in faces.items()}
    verts = {k: int(new[v]) for k, v in verts.items() if new[v] >= 0}
    V = _signed_vol(xyz[tets])
    flip = V < 0
    tets[flip] = tets[flip][:, [0, 2, 1, 3]]
    if (np.abs(V) < 1e-14 * max(np.abs(V).max(), 1e-300)).any():
        keep = np.abs(V) >= 1e-14 * np.abs(V).max()
        tets = tets[keep]
    return {"nodes": xyz, "tets": tets.astype(np.int64), "faces": faces, "verts": verts}


def _match_surfaces(gmsh, geom):
    """{gmsh surface tag: face id of the part}: the nearest face by centre of mass and area."""
    fm = {}
    used = set()
    cand = []
    for (_d, tag) in gmsh.model.getEntities(2):
        c = np.array(gmsh.model.occ.getCenterOfMass(2, tag))
        a = gmsh.model.occ.getMass(2, tag)
        for f in geom["faces"]:
            d = np.linalg.norm(c - f["center"]) / max(geom["diag"], 1e-12) + abs(a - f["area"]) / max(f["area"], 1e-12)
            cand.append((d, tag, f["id"]))
    for d, tag, fid in sorted(cand):
        if tag in fm or fid in used:
            continue
        if d > 0.05:
            continue
        fm[tag] = fid
        used.add(fid)
    return fm


def _signed_vol(c):
    return np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])) / 6.0


def quadratic(mesh):
    """Adds the mid-edge nodes: {"nodes", "conn" (ne, 10), "tri6": {face id: (k, 6)}, "vol", ...}."""
    nodes, tets = mesh["nodes"], mesh["tets"]
    nn, ne = len(nodes), len(tets)
    key = lambda a, b: np.minimum(a, b).astype(np.int64) * nn + np.maximum(a, b)
    keys = np.stack([key(tets[:, a], tets[:, b]) for a, b in EDGES], axis=1)
    uniq, inv = np.unique(keys.ravel(), return_inverse=True)
    mid = 0.5 * (nodes[uniq // nn] + nodes[uniq % nn])
    conn = np.concatenate([tets, nn + inv.reshape(ne, 6)], axis=1)
    tri6 = {}
    for fid, tr in mesh["faces"].items():
        ms = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            k = key(tr[:, a], tr[:, b])
            pos = np.searchsorted(uniq, k)
            ok = (pos < len(uniq)) & (uniq[np.minimum(pos, len(uniq) - 1)] == k)
            if not ok.all():
                raise FemError("A surface triangle is not an element face (the mesh is not conforming).")
            ms.append(nn + pos)
        tri6[fid] = np.stack([tr[:, 0], tr[:, 1], tr[:, 2], ms[0], ms[1], ms[2]], axis=1)
    out = dict(mesh)
    out.update({"nodes": np.vstack([nodes, mid]), "conn": conn, "tri6": tri6})
    return out


def outward_normals(mesh, tri):
    """Unit outward normals and areas of surface triangles (corner node ids) from the tetrahedra next to them."""
    nodes, tets = mesh["nodes"], mesh["tets"]
    n = len(nodes)
    f = tets[:, [[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]]]                 # face i is opposite node i
    opp = np.repeat(tets[:, :, None], 1, axis=2)[:, :, 0]
    fs = np.sort(f, axis=2).reshape(-1, 3).astype(np.int64)
    fk = fs[:, 0] * n * n + fs[:, 1] * n + fs[:, 2]
    order = np.argsort(fk)
    fk = fk[order]
    tk = np.sort(tri, axis=1).astype(np.int64)
    tk = tk[:, 0] * n * n + tk[:, 1] * n + tk[:, 2]
    pos = np.clip(np.searchsorted(fk, tk), 0, len(fk) - 1)
    hit = fk[pos] == tk
    if not hit.all():
        raise FemError("A surface triangle has no tetrahedron behind it.")
    src = order[pos]
    opposite = tets[src // 4, src % 4]
    a, b, c = (nodes[tri[:, i]] for i in range(3))
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    nv = cr / np.maximum(2 * area, 1e-300)[:, None]
    inward = np.einsum("ij,ij->i", nodes[opposite] - a, nv) > 0              # the opposite node lies on the inside: that side is not outward
    nv[inward] *= -1
    return nv, area


# ------------------------------------------------------------------------------------------------------------------------ elements
def _dNdL(L):
    """(10, 4): derivative of the 10 shape functions with respect to the 4 volume coordinates, at the point L."""
    d = np.zeros((10, 4))
    for i in range(4):
        d[i, i] = 4 * L[i] - 1
    for k, (a, b) in enumerate(EDGES):
        d[4 + k, a] = 4 * L[b]
        d[4 + k, b] = 4 * L[a]
    return d


def _N(L):
    n = np.zeros(10)
    for i in range(4):
        n[i] = L[i] * (2 * L[i] - 1)
    for k, (a, b) in enumerate(EDGES):
        n[4 + k] = 4 * L[a] * L[b]
    return n


def material_matrix(E, nu):
    c = E / ((1 + nu) * (1 - 2 * nu))
    D = np.zeros((6, 6))
    D[:3, :3] = c * nu
    for i in range(3):
        D[i, i] = c * (1 - nu)
    for i in range(3, 6):
        D[i, i] = c * (1 - 2 * nu) / 2
    return D


def _grad_L(nodes, conn, s, e):
    c = nodes[conn[s:e, :4]]
    A = np.ones((e - s, 4, 4))
    A[:, :, 1:] = c
    inv = np.linalg.inv(A)
    return np.transpose(inv[:, 1:, :], (0, 2, 1)), np.abs(_signed_vol(c))


def _bmat(g):
    """g (ne, 10, 3) physical gradients of the shape functions -> B (ne, 6, 30)."""
    ne = g.shape[0]
    B = np.zeros((ne, 6, 30))
    for i in range(10):
        gx, gy, gz = g[:, i, 0], g[:, i, 1], g[:, i, 2]
        B[:, 0, 3 * i] = gx
        B[:, 1, 3 * i + 1] = gy
        B[:, 2, 3 * i + 2] = gz
        B[:, 3, 3 * i], B[:, 3, 3 * i + 1] = gy, gx
        B[:, 4, 3 * i + 1], B[:, 4, 3 * i + 2] = gz, gy
        B[:, 5, 3 * i], B[:, 5, 3 * i + 2] = gz, gx
    return B


def assemble(nodes, conn, E, nu, cancel=lambda: False):
    nn, ne = len(nodes), len(conn)
    D = material_matrix(E, nu)
    dN = [_dNdL(L) for L in GAUSS]
    rows, cols, vals = [], [], []
    chunk = 4000
    K = None
    for s in range(0, ne, chunk):
        if cancel():
            raise Cancelled()
        e = min(s + chunk, ne)
        gL, V = _grad_L(nodes, conn, s, e)
        Ke = np.zeros((e - s, 30, 30))
        for d, w in zip(dN, GW):
            B = _bmat(np.einsum("ik,ekx->eix", d, gL))
            Ke += (w * V)[:, None, None] * (B.transpose(0, 2, 1) @ (D @ B))
        ed = (3 * conn[s:e, :, None] + np.arange(3)[None, None, :]).reshape(e - s, 30)
        part = sp.coo_matrix((Ke.ravel(), (np.repeat(ed, 30, axis=1).ravel(), np.tile(ed, (1, 30)).ravel())), shape=(3 * nn, 3 * nn)).tocsr()
        K = part if K is None else K + part
    return K, D


def stresses(nodes, conn, D, u):
    """Per element: von Mises at the 4 Gauss points (max), the mean stress tensor, and the element volume."""
    ne = len(conn)
    vm = np.zeros(ne)
    sig_mean = np.zeros((ne, 6))
    vol = np.zeros(ne)
    dN = [_dNdL(L) for L in GAUSS]
    chunk = 8000
    for s in range(0, ne, chunk):
        e = min(s + chunk, ne)
        gL, V = _grad_L(nodes, conn, s, e)
        vol[s:e] = V
        ed = (3 * conn[s:e, :, None] + np.arange(3)[None, None, :]).reshape(e - s, 30)
        ue = u[ed]
        vmax = np.zeros(e - s)
        for d in dN:
            B = _bmat(np.einsum("ik,ekx->eix", d, gL))
            sg = np.einsum("eri,ei->er", B, ue) @ D.T
            vmax = np.maximum(vmax, _vm(sg))
            sig_mean[s:e] += sg / 4.0
        vm[s:e] = vmax
    return vm, sig_mean, vol


def _vm(s):
    return np.sqrt(np.maximum(0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2) + 3 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2), 0))


def principal(sig):
    T = np.zeros((len(sig), 3, 3))
    T[:, 0, 0], T[:, 1, 1], T[:, 2, 2] = sig[:, 0], sig[:, 1], sig[:, 2]
    T[:, 0, 1] = T[:, 1, 0] = sig[:, 3]
    T[:, 1, 2] = T[:, 2, 1] = sig[:, 4]
    T[:, 0, 2] = T[:, 2, 0] = sig[:, 5]
    w = np.linalg.eigvalsh(T)
    return w[:, 2], w[:, 0]


def body_load(nodes, conn, b):
    """Consistent nodal forces of a uniform body force vector b (N/mm3)."""
    f = np.zeros(3 * len(nodes))
    Ns = [_N(L) for L in GAUSS]
    ne = len(conn)
    for s in range(0, ne, 8000):
        e = min(s + 8000, ne)
        V = np.abs(_signed_vol(nodes[conn[s:e, :4]]))
        for n, w in zip(Ns, GW):
            for i in range(10):
                for c in range(3):
                    np.add.at(f, 3 * conn[s:e, i] + c, w * V * n[i] * b[c])
    return f


# ------------------------------------------------------------------------------------------------------------------------ the problem
def rigid_modes(xyz):
    """(n*3, 6) translations and rotations of points."""
    n = len(xyz)
    M = np.zeros((3 * n, 6))
    for c in range(3):
        M[c::3, c] = 1
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    M[1::3, 3], M[2::3, 3] = -z, y
    M[0::3, 4], M[2::3, 4] = z, -x
    M[0::3, 5], M[1::3, 5] = -y, x
    return M


def solve(q, E, nu, constraints, force, cancel=lambda: False, progress=lambda t: None):
    """q = quadratic mesh.  constraints: [(node array, direction (3,) or None for all three)]; force: (3 nn,) vector.
    Returns u (nn, 3), reactions per constraint, info."""
    nodes, conn = q["nodes"], q["conn"]
    nn = len(nodes)
    progress("assembling")
    K, D = assemble(nodes, conn, E, nu, cancel)
    fixed = np.zeros(3 * nn, bool)
    pen = []
    rows = []                                                # (node, direction) pairs for the rigid-body check
    for nd, d in constraints:
        nd = np.unique(nd)
        if d is None:
            for c in range(3):
                fixed[3 * nd + c] = True
                e = np.zeros(3)
                e[c] = 1
                rows += [(int(n), e) for n in nd]
        else:
            d = np.asarray(d, float)
            d = d / np.linalg.norm(d)
            k = int(np.argmax(np.abs(d)))
            if abs(d[k]) > 0.999999:
                fixed[3 * nd + k] = True
            else:
                pen.append((nd, d))
            rows += [(int(n), d) for n in nd]
    if not rows:
        raise FemError("There is no support: the part is free to move.")
    # rigid body modes must all be stopped by the constraints
    nds = np.array(sorted({n for n, _ in rows}))
    pos = {int(n): i for i, n in enumerate(nds)}
    R = rigid_modes(nodes[nds])
    A = np.zeros((len(rows), 6))
    for r, (n, d) in enumerate(rows):
        i = pos[n]
        A[r] = d @ R[3 * i:3 * i + 3, :]
    sv = np.linalg.svd(A, compute_uv=False)
    if sv[-1] < 1e-9 * max(sv[0], 1e-300) or len(sv) < 6:
        raise FemError("The supports leave the part free to move or turn (a rigid-body motion is not stopped). Add or enlarge a support.")
    if pen:
        kk = 1e8 * float(K.diagonal().mean())
        P = sp.lil_matrix((3 * nn, 3 * nn))
        for nd, d in pen:
            for n in nd:
                P[3 * n:3 * n + 3, 3 * n:3 * n + 3] += kk * np.outer(d, d)
        K = K + P.tocsr()
    free = np.where(~fixed)[0]
    Kff = K[free][:, free].tocsc()
    ff = force[free]
    progress(f"solving {len(free):,} unknowns")
    if cancel():
        raise Cancelled()
    t0 = time.time()
    if len(free) <= 80000:
        try:
            uf = spl.splu(Kff).solve(ff)
            how = "direct"
        except RuntimeError as ex:
            raise FemError(f"The system is singular ({ex}). Check the supports.")
    else:
        ilu = spl.spilu(Kff, drop_tol=1e-4, fill_factor=15)
        uf, info = spl.cg(Kff, ff, rtol=1e-9, maxiter=3000, M=spl.LinearOperator(Kff.shape, ilu.solve))
        how = "iterative"
        if info != 0:
            raise FemError("The iterative solver did not converge. Use a larger element size.")
    u = np.zeros(3 * nn)
    u[free] = uf
    res = float(np.linalg.norm(Kff @ uf - ff) / max(np.linalg.norm(ff), 1e-300))
    if not np.isfinite(u).all() or res > 1e-6:
        raise FemError(f"The solution is not reliable (relative residual {res:.1e}). Check the supports: the part may be able to move freely.")
    r = K @ u - force
    reac = []
    allnodes = set()
    for nd, d in constraints:
        nd = np.unique(nd)
        allnodes.update(int(n) for n in nd)
        idx = (3 * nd[:, None] + np.arange(3)[None, :]).ravel()
        rr = r[idx].reshape(-1, 3)
        if d is None:
            reac.append(rr.sum(axis=0))
        else:
            dd = np.asarray(d, float) / np.linalg.norm(d)
            reac.append((rr @ dd).sum() * dd)                       # a one-direction support only carries load along its direction
    an = np.array(sorted(allnodes))
    total = r[(3 * an[:, None] + np.arange(3)[None, :]).ravel()].reshape(-1, 3).sum(axis=0)
    info = {"total_reaction": total.tolist(), "solver": how, "residual": res, "seconds": time.time() - t0, "unknowns": int(len(free))}
    return u.reshape(-1, 3), np.array(reac), info, K, D
