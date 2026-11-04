"""Change how many facets a mesh has, everywhere or only in chosen zones.

    sizes(mesh, base, zones=[...])     -> a target edge length for each point (base length, made smaller inside the zones)
    remesh(mesh, base, zones=[...])    -> a new mesh whose facets have about those lengths (gmsh, surface re-triangulated)
    reduce(mesh, fraction)             -> fewer facets (quadric decimation; fraction = share of triangles to remove)
    subdivide(mesh, n)                 -> n rounds of splitting each triangle in four (smooth = round the surface a little)
    deviation(a, b)                    -> how far apart two meshes are (max and 95 % distance)

A zone is a dict: {"kind": "sphere", "center": (x,y,z), "radius": r, "size": s}   (size inside the sphere; it grows back to the base
size over `blend` further out)   also "box" (lo, hi), "point" (size grows with distance from a point), "line" (size grows with distance
from a line a-b), and "curvature" (smaller facets where the surface bends: size = clamp(angle_step / curvature)).
"""
import numpy as np
import pyvista as pv

import compat  # noqa: F401  (adds extract_surface_compat to pyvista objects)
from scipy.spatial import cKDTree

import repair as R
from tasks import Cancelled, sub, tick


def _blend(dist, size, base, blend):
    t = np.clip(dist / max(blend, 1e-9), 0, 1)
    return size + (base - size) * t


def adjacency(n, T):
    """Sparse 0/1 vertex-vertex adjacency of a triangle mesh."""
    import scipy.sparse as sp
    r = np.concatenate([T[:, 0], T[:, 1], T[:, 2], T[:, 1], T[:, 2], T[:, 0]])
    c = np.concatenate([T[:, 1], T[:, 2], T[:, 0], T[:, 0], T[:, 1], T[:, 2]])
    A = sp.coo_matrix((np.ones(len(r)), (r, c)), shape=(n, n)).tocsr()
    A.data[:] = 1.0
    return A


def curvature(mesh, smooth=2):
    """Approximate absolute mean curvature at each point (1/length), from the angle between neighbouring point normals, then averaged over
    the neighbours `smooth` times so that scan noise does not look like a sharp bend."""
    P, T = R.arrays(mesh)
    pm = R.to_mesh(P, T)
    nrm = pm.compute_normals(point_normals=True, cell_normals=False, auto_orient_normals=False).point_data["Normals"]
    e = np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    L = np.linalg.norm(P[e[:, 0]] - P[e[:, 1]], axis=1)
    cosang = np.clip(np.einsum("ij,ij->i", nrm[e[:, 0]], nrm[e[:, 1]]), -1, 1)
    k = np.arccos(cosang) / np.maximum(L, 1e-12)
    out = np.zeros(len(P))
    cnt = np.zeros(len(P))
    np.add.at(out, e[:, 0], k)
    np.add.at(out, e[:, 1], k)
    np.add.at(cnt, e[:, 0], 1)
    np.add.at(cnt, e[:, 1], 1)
    out = out / np.maximum(cnt, 1)
    if smooth:
        A = adjacency(len(P), T)
        deg = np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1)
        for _ in range(smooth):
            out = 0.5 * out + 0.5 * (A @ out) / deg
    return out


def sizes(mesh, base, zones=(), pts=None, _tree=None, _curv=None):
    """Target edge length at each point of `pts` (default the mesh points)."""
    pts = np.asarray(mesh.points if pts is None else pts, float)
    s = np.full(len(pts), float(base))
    for z in zones:
        k, size = z["kind"], float(z.get("size", base))
        blend = float(z.get("blend", 2 * base))
        if k == "sphere":
            d = np.maximum(np.linalg.norm(pts - np.asarray(z["center"], float), axis=1) - z["radius"], 0)
        elif k == "box":
            lo, hi = np.asarray(z["lo"], float), np.asarray(z["hi"], float)
            d = np.linalg.norm(np.maximum(np.maximum(lo - pts, pts - hi), 0), axis=1)
        elif k == "point":
            d = np.linalg.norm(pts - np.asarray(z["center"], float), axis=1)
            blend = float(z.get("blend", z.get("radius", 4 * base)))
        elif k == "line":
            a, b = np.asarray(z["a"], float), np.asarray(z["b"], float)
            ab = b - a
            t = np.clip(((pts - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
            d = np.linalg.norm(pts - (a + t[:, None] * ab), axis=1)
            blend = float(z.get("blend", z.get("radius", 4 * base)))
        elif k == "curvature":
            kap = _curv_at(mesh, pts, _tree, _curv)
            step = float(z.get("angle", 0.35))                              # radians turned across one facet
            s = np.minimum(s, np.clip(step / np.maximum(kap, 1e-9), size, base))
            continue
        else:
            raise ValueError(f"unknown zone kind {k!r}")
        s = np.minimum(s, _blend(d, size, base, blend))
    return s


def _curv_at(mesh, pts, tree=None, cache=None):
    if cache is None:
        cache = {}
    if "k" not in cache:
        cache["k"] = curvature(mesh)
        cache["tree"] = tree if tree is not None else cKDTree(R.arrays(mesh)[0])
    _d, i = cache["tree"].query(pts)
    return cache["k"][i]


def _split_once(P, T, size_fn, ratio):
    """Split every edge longer than ratio * (target size at its middle), in all triangles that share it (so no hanging points)."""
    e = np.stack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=1)             # (n,3,2): edge i of a triangle
    key = np.sort(e, axis=2).reshape(-1, 2)
    nv = len(P)
    ucode, inv = np.unique(key[:, 0].astype(np.int64) * nv + key[:, 1], return_inverse=True)
    uniq = np.stack([ucode // nv, ucode % nv], axis=1)
    inv = inv.ravel().reshape(-1, 3)
    L = np.linalg.norm(P[uniq[:, 0]] - P[uniq[:, 1]], axis=1)
    mid = 0.5 * (P[uniq[:, 0]] + P[uniq[:, 1]])
    marked = L > ratio * size_fn(mid)
    if not marked.any():
        return P, T, 0
    nid = np.full(len(uniq), -1, np.int64)
    nid[marked] = len(P) + np.arange(int(marked.sum()))
    P2 = np.vstack([P, mid[marked]])
    mk = marked[inv]
    k = mk.sum(axis=1)
    m = np.where(mk, nid[inv], -1)                                              # new vertex on each edge of each triangle
    out = [T[k == 0]]
    t3 = np.where(k == 3)[0]
    if len(t3):
        v0, v1, v2 = T[t3, 0], T[t3, 1], T[t3, 2]
        m01, m12, m20 = m[t3, 0], m[t3, 1], m[t3, 2]
        out += [np.stack(x, 1) for x in ((v0, m01, m20), (m01, v1, m12), (m20, m12, v2), (m01, m12, m20))]
    t1 = np.where(k == 1)[0]
    if len(t1):
        r = np.argmax(mk[t1], axis=1)
        a_, b_, c_ = (T[t1, (r + i) % 3] for i in range(3))
        mm = m[t1, r]
        out += [np.stack((a_, mm, c_), 1), np.stack((mm, b_, c_), 1)]
    t2 = np.where(k == 2)[0]
    if len(t2):
        u = np.argmin(mk[t2], axis=1)
        p, q, r_ = (T[t2, (u + i) % 3] for i in range(3))
        mqr, mrp = m[t2, (u + 1) % 3], m[t2, (u + 2) % 3]
        out.append(np.stack((mqr, r_, mrp), 1))
        short = np.linalg.norm(P2[p] - P2[mqr], axis=1) < np.linalg.norm(P2[q] - P2[mrp], axis=1)
        out += [np.where(short[:, None], np.stack((p, q, mqr), 1), np.stack((p, q, mrp), 1)),
                np.where(short[:, None], np.stack((p, mqr, mrp), 1), np.stack((q, mqr, mrp), 1))]
    return P2, np.vstack(out), int(marked.sum())


def refine(mesh, base, zones=(), ratio=1.4, max_rounds=12, progress=None):
    """Make facets smaller where the target size (base, or smaller inside a zone) is smaller than they are.  Edges are split at their
    middle, which lies on the surface, so the shape does not change at all; coarser places are left as they are."""
    P, T = R.arrays(mesh)
    ref = R.to_mesh(P, T)
    tree = cKDTree(P)
    cache = {}

    def size_fn(pts):
        return sizes(ref, base, zones, pts, _tree=tree, _curv=cache)
    for i in range(max_rounds):
        tick(progress, f"Splitting facets (round {i + 1})", i / max_rounds)
        P, T, n = _split_once(P, T, size_fn, ratio)
        if n == 0:
            break
    return R.to_mesh(P, T)


def coarsen(mesh, base, zones=(), ratio=1.25, max_stretch=1.6, progress=None):
    """Make facets larger where the target size is larger than they are: edges shorter than target/ratio are collapsed, cheapest first
    (cost = quadric error, so flat places go before detail).  A collapse is refused if it would fold the surface, pinch it, or make an
    edge longer than max_stretch * target.  Open edges (the border of a mesh with holes) are never moved."""
    import heapq
    P0, T0 = R.arrays(mesh)
    ref = R.to_mesh(P0, T0)
    tree0 = cKDTree(P0)
    cache = {}
    P = P0.copy()
    nP = len(P)
    tris = {i: tuple(t) for i, t in enumerate(T0.tolist())}
    vt = [set() for _ in range(nP)]
    for i, t in tris.items():
        for v in t:
            vt[v].add(i)
    # quadrics (4x4) from the planes of the triangles around each vertex
    a_, b_, c_ = P[T0[:, 0]], P[T0[:, 1]], P[T0[:, 2]]
    nrm = np.cross(b_ - a_, c_ - a_)
    area = np.linalg.norm(nrm, axis=1)
    nn = nrm / np.maximum(area, 1e-300)[:, None]
    pl = np.hstack([nn, -np.einsum("ij,ij->i", nn, a_)[:, None]])
    Kt = (pl[:, :, None] * pl[:, None, :]) * (0.5 * area)[:, None, None]
    Q = np.zeros((nP, 4, 4))
    for k in range(3):
        np.add.at(Q, T0[:, k], Kt)
    e, owner, key, uniq, inv, cnt = R.edge_table(T0)
    fixed = np.zeros(nP, bool)
    fixed[np.unique(uniq[cnt == 1])] = True

    def tgt_at(pt):
        return float(sizes(ref, base, zones, pt[None, :], _tree=tree0, _curv=cache)[0])

    def err(q, p):
        h = np.append(p, 1.0)
        return float(h @ q @ h)

    def cost_of(u, v):
        """(cost, position) of merging u into v: best of v's place, u's place and the middle."""
        q = Q[u] + Q[v]
        best = None
        for p in (P[v], P[u], 0.5 * (P[u] + P[v])):
            c = err(q, p)
            if best is None or c < best[0]:
                best = (c, p)
        return best

    heap, stamp, version = [], [0] * nP, 0
    def push(u, v):
        if fixed[u] and fixed[v]:
            return
        L = float(np.linalg.norm(P[u] - P[v]))
        t = tgt_at(0.5 * (P[u] + P[v]))
        if L * ratio < t:
            c, _p = cost_of(u, v)
            heapq.heappush(heap, (c / max(t * t, 1e-12), u, v, stamp[u], stamp[v]))
    tick(progress, "Preparing (measuring edges)", None)
    U, V = uniq[:, 0], uniq[:, 1]
    mid = 0.5 * (P[U] + P[V])
    Ls = np.linalg.norm(P[U] - P[V], axis=1)
    tg = sizes(ref, base, zones, mid, _tree=tree0, _curv=cache)
    cand = np.where((Ls * ratio < tg) & ~(fixed[U] & fixed[V]))[0]
    if len(cand):
        Uc, Vc = U[cand], V[cand]
        q = Q[Uc] + Q[Vc]

        def err_all(pts):
            h = np.c_[pts, np.ones(len(pts))]
            return np.einsum("ij,ijk,ik->i", h, q, h)
        cost = np.minimum(np.minimum(err_all(P[Vc]), err_all(P[Uc])), err_all(0.5 * (P[Uc] + P[Vc])))
        heap = list(zip((cost / np.maximum(tg[cand] ** 2, 1e-12)).tolist(), Uc.tolist(), Vc.tolist(), [0] * len(cand), [0] * len(cand)))
        heapq.heapify(heap)
    alive = np.ones(nP, bool)
    done = 0
    pops = 0
    tick(progress, "Merging facets", 0.0)
    while heap:
        pops += 1
        if progress and pops % 500 == 0:
            progress("Merging facets", min(0.99, pops / (pops + len(heap))))
        c, u, v, su, sv = heapq.heappop(heap)
        if not (alive[u] and alive[v]) or su != stamp[u] or sv != stamp[v]:
            continue
        if fixed[u]:
            u, v = v, u                      # the fixed end stays
        if fixed[u]:
            continue
        shared = vt[u] & vt[v]
        if len(shared) != 2:
            continue
        nu = {w for i in vt[u] for w in tris[i]} - {u}
        nv = {w for i in vt[v] for w in tris[i]} - {v}
        if len((nu & nv) - {w for i in shared for w in tris[i]}) > 0 or len(nu & nv) != 2:
            continue                                                        # link condition: only the two opposite corners are common
        _c, pos = cost_of(u, v)
        if fixed[v]:
            pos = P[v]
        tg = tgt_at(pos)
        ok = True
        for i in (vt[u] | vt[v]) - shared:                                  # every triangle that changes: not folded, not too stretched
            t = tris[i]
            q0 = [P[w] for w in t]
            q1 = [pos if w in (u, v) else P[w] for w in t]
            n0 = np.cross(q0[1] - q0[0], q0[2] - q0[0])
            n1 = np.cross(q1[1] - q1[0], q1[2] - q1[0])
            if np.linalg.norm(n1) < 1e-12 * max(np.linalg.norm(n0), 1e-12) or n0 @ n1 <= 0.2 * np.linalg.norm(n0) * np.linalg.norm(n1):
                ok = False
                break
            if max(np.linalg.norm(q1[j] - q1[(j + 1) % 3]) for j in range(3)) > max_stretch * tg:
                ok = False
                break
        if not ok:
            continue
        P[v] = pos
        Q[v] = Q[u] + Q[v]
        for i in shared:
            for w in tris.pop(i):
                vt[w].discard(i)
        for i in list(vt[u]):
            tris[i] = tuple(v if w == u else w for w in tris[i])
            vt[v].add(i)
        vt[u] = set()
        alive[u] = False
        stamp[v] += 1
        done += 1
        for w in {x for i in vt[v] for x in tris[i]} - {v}:
            stamp[w] += 0
            push(v, w)
    keep = np.array(list(tris.values()), np.int64) if tris else np.zeros((0, 3), np.int64)
    P2, T2 = R.drop_unused(P, keep)
    return R.to_mesh(P2, T2)


def remesh(mesh, base, zones=(), ratio=1.4, progress=None):
    """Facets of about `base` mm everywhere and about the zone sizes inside zones: larger ones are merged, smaller ones split."""
    return refine(coarsen(mesh, base, zones, progress=sub(progress, 0.0, 0.8)), base, zones, ratio, progress=sub(progress, 0.8, 1.0))


def _min_angle_of(A, B, C):
    """Smallest angle (radians) of triangles A,B,C (arrays of points)."""
    def ang(p, q, r):
        u, v = q - p, r - p
        cs = np.einsum("ij,ij->i", u, v) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1), 1e-300)
        return np.arccos(np.clip(cs, -1, 1))
    return np.minimum(np.minimum(ang(A, B, C), ang(B, C, A)), ang(C, A, B))


def flip_edges(P, T, crease_deg=40.0, rounds=4):
    """Flip an inner edge when that raises the smaller of the two triangles' smallest angle, as long as it does not fold the surface, cut
    across a crease sharper than crease_deg, or leave a point with fewer than 3 neighbours.  -> T, number of flips."""
    total = 0
    n = len(P)
    cos_c = np.cos(np.radians(crease_deg))
    for _ in range(rounds):
        e, owner, key, uniq, inv, cnt = R.edge_table(T)
        two = np.where(cnt[inv] == 2)[0]
        if len(two) == 0:
            break
        order = two[np.argsort(inv[two], kind="stable")]
        ia, ib = order[0::2], order[1::2]
        ta, tb = owner[ia], owner[ib]
        u, v = e[ia, 0], e[ia, 1]                                        # shared edge as walked by triangle a
        c = T[ta][np.arange(len(ta))[:, None], (np.argmax(T[ta] == u[:, None], axis=1)[:, None] + 2) % 3].ravel()   # vertex of a opposite the edge
        d = T[tb][np.arange(len(tb))[:, None], (np.argmax(T[tb] == v[:, None], axis=1)[:, None] + 2) % 3].ravel()   # vertex of b opposite the edge
        # current triangles (u,v,c) and (v,u,d); after the flip (c,d,v)... keep orientation: (u,d,c) and (d,v,c)
        before = np.minimum(_min_angle_of(P[u], P[v], P[c]), _min_angle_of(P[v], P[u], P[d]))
        after = np.minimum(_min_angle_of(P[u], P[d], P[c]), _min_angle_of(P[d], P[v], P[c]))
        n_old_a = np.cross(P[v] - P[u], P[c] - P[u])
        n_old_b = np.cross(P[u] - P[v], P[d] - P[v])
        n_new_a = np.cross(P[d] - P[u], P[c] - P[u])
        n_new_b = np.cross(P[v] - P[d], P[c] - P[d])
        nrm = lambda x: x / np.maximum(np.linalg.norm(x, axis=1), 1e-300)[:, None]
        n_old = nrm(n_old_a + n_old_b)
        ok = (np.einsum("ij,ij->i", nrm(n_new_a), n_old) > 0.5) & (np.einsum("ij,ij->i", nrm(n_new_b), n_old) > 0.5)
        ok &= np.einsum("ij,ij->i", nrm(n_old_a), nrm(n_old_b)) > cos_c                                   # not across a crease
        deg = np.bincount(T.ravel(), minlength=n)
        ok &= (deg[u] > 3) & (deg[v] > 3) & (c != d)
        existing = set((uniq[:, 0].astype(np.int64) * n + uniq[:, 1]).tolist())
        lo, hi = np.minimum(c, d), np.maximum(c, d)
        ok &= np.array([(int(a) * n + int(b)) not in existing for a, b in zip(lo, hi)])
        gain = after - before
        cand = np.where(ok & (gain > 1e-3))[0]
        if len(cand) == 0:
            break
        used, flips = set(), 0
        T = T.copy()
        for i in cand[np.argsort(-gain[cand])]:
            a, b = int(ta[i]), int(tb[i])
            if a in used or b in used:
                continue
            used.update((a, b))
            T[a] = (u[i], d[i], c[i])
            T[b] = (d[i], v[i], c[i])
            flips += 1
        total += flips
        if flips == 0:
            break
    return T, total


def regularize(mesh, iterations=5, strength=0.5, crease_deg=40.0, flips=True, reference=None, progress=None):
    """Make the triangles more even without changing the shape: edge flips for better angles, then each point is moved sideways towards
    the middle of its neighbours and put back onto the original surface.  Points on a crease sharper than crease_deg and on open borders
    stay where they are, so edges and corners keep their sharpness.  reference = the surface to stay on (default: the mesh as given)."""
    P, T = R.arrays(mesh)
    ref = R.to_mesh(P, T) if reference is None else R.to_mesh(*R.arrays(reference))
    n = len(P)
    e, owner, key, uniq, inv, cnt = R.edge_table(T)
    fixed = np.zeros(n, bool)
    fixed[np.unique(uniq[cnt[:] != 2])] = True                          # borders and fins
    total_flips = 0
    for it in range(iterations):
        tick(progress, f"Evening out triangles (pass {it + 1} of {iterations})", it / iterations)
        if flips:
            T, nf = flip_edges(P, T, crease_deg)
            total_flips += nf
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        fn = np.cross(b - a, c - a)
        vn = np.zeros((n, 3))
        for k in range(3):
            np.add.at(vn, T[:, k], fn)                                   # area weighted point normals
        vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-300)[:, None]
        fnu = fn / np.maximum(np.linalg.norm(fn, axis=1), 1e-300)[:, None]
        dev = np.zeros(n)
        for k in range(3):
            np.maximum.at(dev, T[:, k], np.einsum("ij,ij->i", fnu, vn[T[:, k]]) * -1 + 1)      # 1 - cos(angle to a triangle normal)
        feature = dev > 1 - np.cos(np.radians(crease_deg))
        A = adjacency(n, T)
        deg = np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1)
        move = (A @ P) / deg[:, None] - P
        move -= np.einsum("ij,ij->i", move, vn)[:, None] * vn             # sideways only
        free = ~(fixed | feature)
        newP = P.copy()
        newP[free] = P[free] + strength * move[free]
        idx = np.where(free)[0]
        if len(idx):
            _cell, closest = ref.find_closest_cell(newP[idx], return_closest_point=True)
            newP[idx] = closest
        P = newP
    out = R.to_mesh(P, T)
    out.field_data["flips"] = np.array([total_flips])
    return out


def reduce(mesh, fraction=0.5):
    """Remove `fraction` of the triangles (0.5 = half), keeping the shape as well as quadric decimation can."""
    m = R.to_mesh(*R.arrays(mesh))
    return m.decimate(fraction, volume_preservation=True).extract_surface_compat().triangulate()


def subdivide(mesh, n=1, smooth=False, progress=None):
    """n rounds of splitting every triangle in four (4**n times the triangles).  smooth=True uses Loop subdivision, which also rounds the surface."""
    m = R.to_mesh(*R.arrays(mesh))
    for i in range(int(n)):
        tick(progress, f"Subdividing (level {i + 1} of {int(n)}, {m.n_cells * 4:,} triangles)", i / max(int(n), 1))
        m = (m.subdivide(1, subfilter="loop") if smooth else m.subdivide(1, subfilter="linear")).extract_surface_compat().triangulate()
    return m


def subdivide_count(triangles, n):
    return int(triangles) * 4 ** int(n)


def local_counts(mesh, zone_center, radius):
    P, T = R.arrays(mesh)
    c = P[T].mean(axis=1)
    return int((np.linalg.norm(c - np.asarray(zone_center, float), axis=1) <= radius).sum())


def deviation(a, b, n=4000, seed=0):
    """(largest, 95th percentile, mean) distance from points on mesh a to the surface of mesh b, and the other way round."""
    def sample(m):
        P, T = R.arrays(m)
        ar = R.tri_areas(P, T)
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(T), size=n, p=ar / ar.sum())
        r1, r2 = rng.random(n), rng.random(n)
        f = r1 + r2 > 1
        r1[f], r2[f] = 1 - r1[f], 1 - r2[f]
        A, B, C = P[T[idx, 0]], P[T[idx, 1]], P[T[idx, 2]]
        return A + (B - A) * r1[:, None] + (C - A) * r2[:, None]

    def dist(pts, m):
        return pts_to_mesh(pts, m)
    d = np.concatenate([dist(sample(a), b), dist(sample(b), a)])
    return float(d.max()), float(np.percentile(d, 95)), float(d.mean())


def pts_to_mesh(pts, mesh, progress=None):
    """Distance from each point to the nearest point of the surface (exact, through pyvista's cell locator)."""
    m = R.to_mesh(*R.arrays(mesh))
    out = np.empty(len(pts))
    step = 50000
    for i in range(0, len(pts), step):
        tick(progress, "Measuring distances", i / max(len(pts), 1))
        ids = m.find_closest_cell(pts[i:i + step], return_closest_point=True)
        out[i:i + step] = np.linalg.norm(pts[i:i + step] - ids[1], axis=1)
    return out
