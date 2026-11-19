"""
solid_hexmesh.py - the hex-dominant mesh of the 3D FEA add-on (no window).

The surface of the part is meshed first by gmsh, patch by patch, so the borders of the split patches lie on mesh edges (that is what keeps the mesh
"patch dependent").  Then:
  1. a regular grid of cubes (edge = the element size) is laid over the part; a cube becomes a hexahedron when all eight corners are inside the part and
     at least `MARGIN` element sizes away from the surface and from the refined parts of it (small elements: curved surfaces, local sizes);
  2. thin bridges, edge-to-edge contacts and tiny islands of hexahedra are taken away (they would make the mesh non-manifold);
  3. gmsh fills what is left between the surface triangles and the outside quads of the hexahedron block with tetrahedra and pyramids: the shell.
A part (or a place of it) with no room for a hexahedron gets tetrahedra only; if nothing fits at all, or anything about the result is not conforming, `build`
raises NoHexes with the reason and the caller meshes with tetrahedra.

build(X, tri, h, opts) -> {"nodes", "tets", "pyrs", "hexes", "outer": final node of every surface node, "info": {...}}
"""
import numpy as np
from scipy.spatial import cKDTree

import solid_fem as fem

MARGIN = 1.0                # hexahedra stay this many element sizes away from the surface
MIN_CELLS = 8               # a block of fewer hexahedra than this is not worth it
FINE = 0.8                  # surface triangles smaller than this fraction of the element size count as refined
GRADE = 0.5                 # next to refined surface the strip without hexahedra is GRADE * (h - size) / (growth - 1) wide, beyond the margin
# gmsh options for the shell, by name: the sizes of the nodes come from the boundary triangles only ("sizes"), are also spread into the space ("spread"), or are gmsh's own
SHELL_OPTIONS = {"sizes": {"Mesh.MeshSizeExtendFromBoundary": 0, "Mesh.MeshSizeFromPoints": 0, "Mesh.MeshSizeFromCurvature": 0, "Mesh.MeshSizeMax": lambda h: 3 * h},
                 "spread": {"Mesh.MeshSizeExtendFromBoundary": 1, "Mesh.MeshSizeFromPoints": 0, "Mesh.MeshSizeFromCurvature": 0, "Mesh.MeshSizeMax": lambda h: 3 * h},
                 "plain": {}}
MARGINS = (1.0, 1.5)        # the gap between the surface and the block, tried in turn: a wider one gives the shell more room, but there are fewer hexahedra
# gmsh's tetrahedraliser sometimes leaves a few overlapping tetrahedra next to a fine curved surface; a different option set or a little more randomness in its ties
# often avoids that.  (option set, smooth the shell afterwards, random factor)
ATTEMPTS = (("sizes", True, None), ("spread", True, None), ("sizes", False, 1e-5), ("plain", True, None))
MAX_NODES = 12_000_000      # grid nodes (a grid this big would give a mesh nobody can solve anyway)


class NoHexes(Exception):
    """No hexahedra can be used (the reason is the message): the part is meshed with tetrahedra instead."""


# ------------------------------------------------------------------------------------------------------------------------ the grid
def _sizes(X, tri):
    P = X[tri]
    L = np.stack([np.linalg.norm(P[:, 0] - P[:, 1], axis=1), np.linalg.norm(P[:, 1] - P[:, 2], axis=1), np.linalg.norm(P[:, 2] - P[:, 0], axis=1)], axis=1)
    return L.mean(axis=1), L.max(axis=1)


def _samples(X, tri, h):
    """Points on the surface dense enough (about a third of an element size apart) to measure the distance to it: (points, triangle of each)."""
    P = X[tri]
    _s, lmax = _sizes(X, tri)
    m = np.clip(np.ceil(lmax / (0.35 * h)).astype(int), 1, 8)
    pts, owner = [], []
    for mm in np.unique(m):
        sel = np.where(m == mm)[0]
        for i in range(mm + 1):
            for j in range(mm + 1 - i):
                k = mm - i - j
                pts.append((i * P[sel, 0] + j * P[sel, 1] + k * P[sel, 2]) / mm)
                owner.append(sel)
    return np.vstack(pts), np.concatenate(owner)


def parity_inside(X, tri, o, h, n):
    """Which grid nodes are inside the closed surface: crossings of a line along +x with the triangles, counted (the lines are shifted by a tiny irrational
    amount so none runs exactly along an edge or through a vertex)."""
    ny, nz = int(n[1]), int(n[2])
    eps_y, eps_z = 1.2345e-6 * h, 2.3456e-6 * h
    P = X[tri]
    ymin, ymax = P[:, :, 1].min(1), P[:, :, 1].max(1)
    zmin, zmax = P[:, :, 2].min(1), P[:, :, 2].max(1)
    j0 = np.ceil((ymin - eps_y - o[1]) / h).astype(int)
    j1 = np.floor((ymax - eps_y - o[1]) / h).astype(int)
    k0 = np.ceil((zmin - eps_z - o[2]) / h).astype(int)
    k1 = np.floor((zmax - eps_z - o[2]) / h).astype(int)
    lines, xs = [], []
    span_j = int((j1 - j0).max()) + 1
    span_k = int((k1 - k0).max()) + 1
    for dj in range(max(span_j, 0)):
        for dk in range(max(span_k, 0)):
            j, k = j0 + dj, k0 + dk
            ok = (j <= j1) & (k <= k1) & (j >= 0) & (j < ny) & (k >= 0) & (k < nz)
            if not ok.any():
                continue
            idx = np.where(ok)[0]
            y = o[1] + j[idx] * h + eps_y
            z = o[2] + k[idx] * h + eps_z
            A, B, C = P[idx, 0], P[idx, 1], P[idx, 2]
            d = (B[:, 1] - A[:, 1]) * (C[:, 2] - A[:, 2]) - (C[:, 1] - A[:, 1]) * (B[:, 2] - A[:, 2])
            good = np.abs(d) > 1e-14
            dd = np.where(good, d, 1)
            l1 = ((y - A[:, 1]) * (C[:, 2] - A[:, 2]) - (C[:, 1] - A[:, 1]) * (z - A[:, 2])) / dd
            l2 = ((B[:, 1] - A[:, 1]) * (z - A[:, 2]) - (y - A[:, 1]) * (B[:, 2] - A[:, 2])) / dd
            l0 = 1 - l1 - l2
            hit = good & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
            sel = idx[hit]
            lines.append(j[sel] * nz + k[sel])
            xs.append(l0[hit] * A[hit, 0] + l1[hit] * B[hit, 0] + l2[hit] * C[hit, 0])
    inside = np.zeros(tuple(int(v) for v in n), bool)
    if not lines:
        return inside
    line = np.concatenate(lines)
    x = np.concatenate(xs)
    order = np.lexsort((x, line))
    line, x = line[order], x[order]
    gx = o[0] + np.arange(int(n[0])) * h
    starts = np.searchsorted(line, np.arange(ny * nz))
    ends = np.searchsorted(line, np.arange(ny * nz), side="right")
    for jk in np.where(ends > starts)[0]:
        cnt = np.searchsorted(x[starts[jk]:ends[jk]], gx)               # crossings to the left of every node of the line
        inside[:, jk // nz, jk % nz] = (cnt % 2) == 1
    return inside


def grid_cells(X, tri, h, growth=1.3, margin=None):
    """(origin o, node counts n, cell mask (n-1) of the cubes that may become hexahedra)."""
    margin = MARGIN if margin is None else margin
    lo, hi = X.min(0), X.max(0)
    # the grid is laid so that the nodes that may be used (at least MARGIN h from the surface) are spread evenly over the part's box: a part whose faces
    # are square to the axes then gets the most cubes
    slack = np.where(hi - lo > 2 * margin * h, np.mod(hi - lo - 2 * margin * h, h), 0.0)
    o = lo + margin * h + slack / 2 - 2 * h
    n = np.ceil((hi - o) / h).astype(int) + 3
    if int(n[0]) * int(n[1]) * int(n[2]) > MAX_NODES:
        raise NoHexes("The element size is so small for this part that the hexahedron grid would be huge: the part is meshed with tetrahedra.")
    inside = parity_inside(X, tri, o, h, n)
    if not inside.any():
        raise NoHexes("No grid point of the hexahedra falls inside the part (it is smaller than an element): the part is meshed with tetrahedra.")
    idx = np.argwhere(inside)
    pts = o + idx * h
    samp, owner = _samples(X, tri, h)
    size, _lmax = _sizes(X, tri)
    d, _ = cKDTree(samp).query(pts)
    keep = d >= margin * h * (1 - 1e-9)
    s_s = size[owner]                                                   # the size of the surface elements next to every sample
    classes = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.65), (0.65, FINE)]
    for a, b in classes:                                                # refined surface: a wider strip without hexahedra around it, wider the finer it is
        sel = (s_s >= a * h) & (s_s < b * h)
        if not sel.any():
            continue
        s_mid = float(s_s[sel].min())
        r = margin * h + min(4.0 * h, GRADE * (h - s_mid) / max(growth - 1.0, 0.05))
        k2 = np.where(keep)[0]
        if not len(k2):
            break
        far, _ = cKDTree(samp[sel]).query(pts[k2])
        keep[k2[far < r]] = False
    good = np.zeros(inside.shape, bool)
    good[tuple(idx[keep].T)] = True
    c = good
    cell = (c[:-1, :-1, :-1] & c[1:, :-1, :-1] & c[:-1, 1:, :-1] & c[1:, 1:, :-1] & c[:-1, :-1, 1:] & c[1:, :-1, 1:] & c[:-1, 1:, 1:] & c[1:, 1:, 1:])
    return o, n, cell


_CORNER = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1)]
_BAD_VERTEX = None


def _bad_vertex_table():
    """For the 256 ways the eight cubes around a grid point can be filled: True where the filled (or the empty) ones do not form ONE block, i.e. where
    two blocks touch only at that point (or along an edge, which the edge test catches) - the surface of the block would not be a manifold there."""
    global _BAD_VERTEX
    if _BAD_VERTEX is not None:
        return _BAD_VERTEX
    adj = [(a, b) for a in range(8) for b in range(a + 1, 8) if sum(abs(np.array(_CORNER[a]) - np.array(_CORNER[b]))) == 1]
    table = np.zeros(256, bool)
    for pat in range(256):
        occ = [(pat >> b) & 1 for b in range(8)]
        ok = True
        for val in (1, 0):
            nodes = [b for b in range(8) if occ[b] == val]
            if not nodes:
                continue
            seen = {nodes[0]}
            stack = [nodes[0]]
            while stack:
                u = stack.pop()
                for a, b in adj:
                    for s, t in ((a, b), (b, a)):
                        if s == u and t in nodes and t not in seen:
                            seen.add(t)
                            stack.append(t)
            if len(seen) != len(nodes):
                ok = False
        table[pat] = not ok
    _BAD_VERTEX = table
    return table


def clean(cell):
    """Takes away cubes until no two blocks of cubes touch along an edge or at a point only (the cube with the fewest neighbours goes first)."""
    cell = cell.copy()
    nx, ny, nz = cell.shape
    table = _bad_vertex_table()
    inb = lambda c: 0 <= c[0] < nx and 0 <= c[1] < ny and 0 <= c[2] < nz
    for _it in range(60):
        pad = np.pad(cell, 1)
        bad = []
        for ax in range(3):
            a = np.moveaxis(pad, ax, 0)
            q00, q01, q10, q11 = a[:, :-1, :-1], a[:, :-1, 1:], a[:, 1:, :-1], a[:, 1:, 1:]
            diag = ((q00 & q11) & ~q01 & ~q10) | ((q01 & q10) & ~q00 & ~q11)
            for (i, j, k) in np.argwhere(diag):
                cs = []
                for dj, dk in ((0, 0), (0, 1), (1, 0), (1, 1)):
                    idx = [i, j + dj, k + dk]
                    full = [0, 0, 0]
                    full[ax], full[(ax + 1) % 3], full[(ax + 2) % 3] = idx
                    cs.append(tuple(v - 1 for v in full))
                bad.append(cs)
        code = np.zeros((nx + 1, ny + 1, nz + 1), int)
        for b, (dx, dy, dz) in enumerate(_CORNER):
            code |= pad[dx:dx + nx + 1, dy:dy + ny + 1, dz:dz + nz + 1].astype(int) << b
        for (i, j, k) in np.argwhere(table[code]):
            bad.append([(i - 1 + dx, j - 1 + dy, k - 1 + dz) for dx, dy, dz in _CORNER])
        if not bad:
            break

        def nb(c):
            s = 0
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                q = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                if inb(q) and cell[q]:
                    s += 1
            return s
        for cs in bad:
            occ = [c for c in cs if inb(c) and cell[c]]
            if occ:
                cell[min(occ, key=nb)] = False
    else:
        raise NoHexes("The block of hexahedra could not be made clean (internal): the part is meshed with tetrahedra.")
    return cell


def drop_islands(cell, min_cells=MIN_CELLS):
    from scipy import ndimage
    lab, n = ndimage.label(cell)
    if n == 0:
        return cell
    cnt = np.bincount(lab.ravel())
    small = cnt < min_cells
    small[0] = False
    return cell & ~small[lab]


def hex_data(o, n, cell):
    """(hexahedra as grid node numbers (m, 8) in VTK order, outside quads (q, 4) as grid node numbers: counter-clockwise seen from OUTSIDE the block)."""
    cells = np.argwhere(cell)
    gid = lambda i, j, k: (i * int(n[1]) + j) * int(n[2]) + k
    off = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    hexg = np.stack([gid(cells[:, 0] + a, cells[:, 1] + b, cells[:, 2] + c) for a, b, c in off], 1)
    pad = np.pad(cell, 1)
    sides = {(-1, 0, 0): [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)], (1, 0, 0): [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)],
             (0, -1, 0): [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], (0, 1, 0): [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)],
             (0, 0, -1): [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)], (0, 0, 1): [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]}
    quads = []
    for d, cs in sides.items():
        free = ~pad[1 + cells[:, 0] + d[0], 1 + cells[:, 1] + d[1], 1 + cells[:, 2] + d[2]]
        sel = cells[free]
        quads.append(np.stack([gid(sel[:, 0] + a, sel[:, 1] + b, sel[:, 2] + c) for a, b, c in cs], 1))
    return hexg, np.vstack(quads)


def _components(n_nodes, faces):
    """Component number of every face (faces that share a node are one component)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    k = faces.shape[1]
    r = np.concatenate([faces[:, i] for i in range(k)])
    c = np.concatenate([faces[:, (i + 1) % k] for i in range(k)])
    g = coo_matrix((np.ones(len(r)), (r, c)), shape=(n_nodes, n_nodes))
    _n, lab = connected_components(g, directed=False)
    return lab[faces[:, 0]]


# ------------------------------------------------------------------------------------------------------------------------ the shell
def _shell(X, tri, GX, quads, h, cancel, options="sizes", optimize=True, jitter=None):
    """Fills the space between the surface triangles `tri` (nodes X) and the quads of the hexahedron block (nodes GX, quads index GX) with tetrahedra and
    pyramids with gmsh.  Returns (node coordinates, tets, pyramids) - the node numbers are gmsh's own, matched by position afterwards."""
    import gmsh
    if gmsh.isInitialized():
        gmsh.finalize()
    try:
        gmsh.initialize(interruptible=False)
    except TypeError:
        gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("shell")
        nout = len(X)
        s_out = gmsh.model.addDiscreteEntity(2)
        gmsh.model.mesh.addNodes(2, s_out, list(range(1, nout + 1)), X.ravel().tolist())
        gmsh.model.mesh.addElementsByType(s_out, 2, [], (tri + 1).ravel().tolist())
        loops = [gmsh.model.geo.addSurfaceLoop([s_out])]
        comp = _components(len(GX), quads)
        base = nout
        for c in np.unique(comp):
            qs = quads[comp == c]
            qn = np.unique(qs)
            s = gmsh.model.addDiscreteEntity(2)
            tags = base + 1 + np.arange(len(qn))
            gmsh.model.mesh.addNodes(2, s, tags.tolist(), GX[qn].ravel().tolist())
            gmsh.model.mesh.addElementsByType(s, 3, [], (base + 1 + np.searchsorted(qn, qs)).ravel().tolist())
            base += len(qn)
            loops.append(gmsh.model.geo.addSurfaceLoop([s]))
        gmsh.model.geo.addVolume(loops)
        gmsh.model.geo.synchronize()
        if cancel():
            raise fem.Cancelled()
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        if jitter is not None:                                           # the points on a cylinder are co-spherical: a larger random factor settles the ties differently
            gmsh.option.setNumber("Mesh.RandomFactor", jitter)
            gmsh.option.setNumber("Mesh.RandomFactor3D", jitter)
        for k, v in SHELL_OPTIONS[options].items():
            gmsh.option.setNumber(k, v(h) if callable(v) else v)
        gmsh.model.mesh.generate(3)
        if optimize:
            try:
                gmsh.model.mesh.optimize("Relocate3D", True)           # smooths the inner nodes of the shell; the boundary stays
            except Exception:
                pass
        types, _tg, cn = gmsh.model.mesh.getElements(3)
        types = [int(t) for t in types]
        if any(t not in (4, 7) for t in types) or 4 not in types:
            raise NoHexes("The mesher could not fill the space between the surface and the hexahedra: the part is meshed with tetrahedra.")
        nt, nc, _ = gmsh.model.mesh.getNodes()
        nt = np.asarray(nt, np.int64)
        XY = np.asarray(nc, float).reshape(-1, 3)
        pos = np.full(int(nt.max()) + 1, -1, np.int64)
        pos[nt] = np.arange(len(nt))
        tets = pos[np.asarray(cn[types.index(4)], np.int64).reshape(-1, 4)]
        pyrs = pos[np.asarray(cn[types.index(7)], np.int64).reshape(-1, 5)] if 7 in types else np.zeros((0, 5), np.int64)
    except NoHexes:
        raise
    except fem.Cancelled:
        raise
    except Exception as ex:
        raise NoHexes(f"The mesher could not fill the space between the surface and the hexahedra ({str(ex).splitlines()[0][:80] if str(ex) else 'error'}): "
                      "the part is meshed with tetrahedra.")
    finally:
        try:
            gmsh.clear()
            gmsh.finalize()
        except Exception:
            pass
    return XY, tets, pyrs



# ------------------------------------------------------------------------------------------------------------------------ the whole mesh
def _face_keys(tets, pyrs, hexes):
    rows = []
    if len(tets):
        for f in ((1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2)):
            rows.append(np.concatenate([np.full((len(tets), 1), -1), tets[:, list(f)]], axis=1))
    if len(pyrs):
        for f in ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)):
            rows.append(np.concatenate([np.full((len(pyrs), 1), -1), pyrs[:, list(f)]], axis=1))
        rows.append(pyrs[:, :4])
    if len(hexes):
        for f in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            rows.append(hexes[:, list(f)])
    return np.sort(np.vstack(rows).astype(np.int64), axis=1)


def build(X, tri, h, opts=None, cancel=lambda: False, progress=lambda t: None):
    """The hex-dominant mesh of the closed surface (X, tri) with the element size h.  See the module text; raises NoHexes."""
    opts = opts or {}
    X = np.asarray(X, float)
    tri = np.asarray(tri, np.int64)
    if len(np.unique(_components(len(X), tri))) > 1:
        raise NoHexes("The part has more than one closed surface (an inner cavity): it is meshed with tetrahedra.")
    first = None
    for mi, margin in enumerate(MARGINS):                               # the gap between surface and block: a wider one gives gmsh an easier shell, but fewer hexahedra
        try:
            progress("finding the hexahedra" if mi == 0 else "trying a wider gap between the hexahedra and the surface")
            o, n, cell = grid_cells(X, tri, h, float(opts.get("growth") or 1.3), margin)
            cell = drop_islands(clean(cell))
            cell = drop_islands(clean(cell))
            if int(cell.sum()) < MIN_CELLS:
                raise NoHexes("No room for hexahedra: the part is too thin, too small or too finely meshed for blocks of them (a block needs a few elements "
                              "between its surface and the part's). It is meshed with tetrahedra.")
            if cancel():
                raise fem.Cancelled()
            hexg, quads = hex_data(o, n, cell)
            gids = np.unique(hexg.ravel())
            qn = np.unique(quads.ravel())
            gm = np.full(int(gids.max()) + 1, -1, np.int64)
            gm[gids] = np.arange(len(gids))
            GX = o + np.stack(np.unravel_index(gids, tuple(int(v) for v in n)), 1) * h         # coordinates of the hexahedron nodes (grid points that are used)
            progress("filling the space next to the surface")
            for opts_name, opt, jit in ATTEMPTS:                                   # gmsh's tetrahedralisers are not all equally lucky with every shell: take the first that is valid
                try:
                    XY, tets, pyrs = _shell(X, tri, GX, gm[quads], h, cancel, opts_name, opt, jit)
                    out = _assemble(X, tri, h, o, n, gids, gm, qn, hexg, GX, XY, tets, pyrs)
                    check(out, tri)
                    return out
                except NoHexes as ex:
                    first = first or ex
        except NoHexes as ex:
            first = first or ex
            if "No room" in str(ex) or "huge" in str(ex) or "smaller than an element" in str(ex):
                break                                                   # a wider gap leaves even less room
    raise first


def _assemble(X, tri, h, o, n, gids, gm, qn, hexg, GX, XY, tets, pyrs):
    """The shell's own node numbers: the surface nodes and the block's outside nodes are found again by position; the block's inner nodes are added."""
    tree = cKDTree(XY)
    d_out, outer = tree.query(X)
    on_block = np.zeros(len(GX), bool)
    on_block[gm[qn]] = True
    d_blk, blk = tree.query(GX[on_block])
    if d_out.max() > 1e-6 * h or d_blk.max() > 1e-6 * h:
        raise NoHexes("The mesher moved nodes it should not have (internal): the part is meshed with tetrahedra.")
    node_of = np.full(len(GX), -1, np.int64)
    node_of[np.where(on_block)[0]] = blk
    inner = np.where(~on_block)[0]
    node_of[inner] = len(XY) + np.arange(len(inner))
    nodes = np.vstack([XY, GX[inner]])
    hexes = node_of[gm[hexg]]
    # orientation: tetrahedra with a positive volume, pyramids with the base normal toward the apex (VTK), hexahedra come out right from the grid
    import solid_elem as elem
    sv = lambda c: np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])) / 6.0
    tets = tets.copy()
    neg = sv(nodes[tets]) < 0
    tets[neg] = tets[neg][:, [0, 2, 1, 3]]
    pyrs = elem.orient_pyramids(nodes, pyrs)
    return {"nodes": nodes, "tets": tets.astype(np.int64), "pyrs": pyrs.astype(np.int64), "hexes": hexes.astype(np.int64), "outer": outer.astype(np.int64),
            "info": {"cells": int(len(hexes)), "h": float(h)}}


_FACES = {"tet": ((1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2)), "pyr": ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4), (0, 1, 2, 3)),
          "hex": ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))}


def _same_side_check(nodes, tets, pyrs, hexes, keys, inv, cnt):
    """The two elements that share an inner face must lie on opposite sides of it.  (Elements that overlap can have every volume positive and every face
    shared twice; a mesh like that has more volume than the part.)"""
    sgn = []
    for kind, c in (("tet", tets), ("pyr", pyrs), ("hex", hexes)):                  # the order of _face_keys
        if not len(c):
            continue
        cen = nodes[c].mean(axis=1)
        for f in _FACES[kind]:
            idx = c[:, list(f)]
            srt = np.sort(idx, axis=1)
            nc = np.cross(nodes[srt[:, 1]] - nodes[srt[:, 0]], nodes[srt[:, 2]] - nodes[srt[:, 0]])      # a normal that only depends on the face's nodes
            sgn.append(np.sign(np.einsum("ij,ij->i", nodes[idx].mean(axis=1) - cen, nc)))
    tot = np.zeros(len(cnt))
    np.add.at(tot, np.asarray(inv).ravel(), np.concatenate(sgn))
    if ((cnt == 2) & (tot != 0)).any():
        raise NoHexes("The shell next to the surface has overlapping elements: the part is meshed with tetrahedra.")


def check(m, tri):
    """The mesh must be conforming: every inner face of an element is shared by exactly two elements, the faces that are shared by one are exactly the
    surface triangles (and those are faces of tetrahedra), no element is flat or turned inside out."""
    nodes, tets, pyrs, hexes = m["nodes"], m["tets"], m["pyrs"], m["hexes"]
    sv = lambda c: np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])) / 6.0
    import solid_elem as elem
    vt = sv(nodes[tets])
    vp = elem.split_volume(nodes, pyrs) if len(pyrs) else np.zeros(0)
    h3 = m["info"]["h"] ** 3
    if (vt <= 1e-12 * h3).any() or (vp <= 1e-12 * h3).any():
        raise NoHexes("The shell next to the surface has flat or inverted elements: the part is meshed with tetrahedra.")
    keys = _face_keys(tets, pyrs, hexes)
    u, inv, cnt = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    if (cnt > 2).any():
        raise NoHexes("The mesh is not conforming (a face shared by more than two elements): the part is meshed with tetrahedra.")
    bnd = u[cnt == 1]
    outer = np.sort(np.concatenate([np.full((len(tri), 1), -1), m["outer"][tri]], axis=1), axis=1)
    ou = np.unique(outer, axis=0)
    if bnd.shape != ou.shape or not np.array_equal(bnd, ou):
        raise NoHexes("The mesh does not match the surface (internal): the part is meshed with tetrahedra.")
    # every surface triangle is the face of a tetrahedron; the volume the surface encloses (divergence theorem, outward normals from the tetrahedra
    # behind the triangles) must be the volume of the elements
    _same_side_check(nodes, tets, pyrs, hexes, keys, inv, cnt)
    tk = _face_keys(tets, np.zeros((0, 5), np.int64), np.zeros((0, 8), np.int64))
    u2, inv2 = np.unique(np.vstack([tk, outer]), axis=0, return_inverse=True)
    inv2 = np.asarray(inv2).ravel()
    first = np.full(len(u2), -1, np.int64)
    first[inv2[:len(tk)]] = np.arange(len(tk))
    src = first[inv2[len(tk):]]
    if (src < 0).any():
        raise NoHexes("A surface triangle is not the face of a tetrahedron (internal): the part is meshed with tetrahedra.")
    nt = len(tets)
    opp = nodes[tets[src % nt, src // nt]]
    a, b, c = (nodes[m["outer"][tri[:, i]]] for i in range(3))
    cr = np.cross(b - a, c - a)
    cen = (a + b + c) / 3.0
    sgn = np.where(np.einsum("ij,ij->i", cen - opp, cr) > 0, 1.0, -1.0)
    enclosed = float((sgn * np.einsum("ij,ij->i", cen, cr)).sum() / 6.0)
    total = float(vt.sum() + vp.sum() + len(hexes) * h3)
    if abs(total - enclosed) > 1e-6 * max(abs(enclosed), 1e-300):
        raise NoHexes("The elements do not fill the part exactly (internal): the part is meshed with tetrahedra.")
