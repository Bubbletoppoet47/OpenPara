"""Look at an STL mesh and fix what is wrong with it.

    load(path)               read an STL (binary or ASCII) -> pyvista PolyData
    diagnose(mesh)           -> dict of facts: closed?, open edges, non-manifold edges, flipped triangles, degenerate / duplicate
                             triangles, loose shells, volume, worst triangle
    repair(mesh, ...)        -> (fixed mesh, report): merge points, remove bad triangles, remove fins, orient consistently,
                             drop tiny shells, fill holes, flatten spikes.  The report lists what was done and what is left.

Work is done on plain arrays (points, triangle indices), so it does not depend on VTK's cleaning filters.
"""
import numpy as np
import pyvista as pv
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree


def load(path):
    m = pv.read(path)
    return m.extract_surface(algorithm=None).triangulate()


def arrays(mesh):
    m = mesh.triangulate() if not mesh.is_all_triangles else mesh
    return np.asarray(m.points, float).copy(), m.faces.reshape(-1, 4)[:, 1:].astype(np.int64)


def to_mesh(P, T):
    T = np.asarray(T, np.int64).reshape(-1, 3)
    return pv.PolyData(np.asarray(P, float), np.hstack([np.full((len(T), 1), 3), T]).ravel())


def diag_of(P):
    return float(np.linalg.norm(P.max(0) - P.min(0))) if len(P) else 0.0


def merge_points(P, T, tol):
    """Points closer than tol become one (as an STL needs: it stores every triangle's corners separately)."""
    if len(P) == 0:
        return P, T
    tree = cKDTree(P)
    pairs = tree.query_pairs(tol, output_type="ndarray")
    n = len(P)
    g = sp.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n)) if len(pairs) else sp.coo_matrix((n, n))
    _k, lab = connected_components(g, directed=False)
    first = np.zeros(lab.max() + 1, np.int64)
    first[lab[::-1]] = np.arange(n)[::-1]                       # the lowest old index of each group
    newP = P[first]
    return newP, lab[T]


def tri_areas(P, T):
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def drop_unused(P, T):
    used = np.unique(T)
    remap = -np.ones(len(P), np.int64)
    remap[used] = np.arange(len(used))
    return P[used], remap[T]


def edge_table(T):
    """(directed edges, owner triangle) -> arrays; undirected edge ids and their triangle counts."""
    e = np.stack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=1).reshape(-1, 2)      # directed: triangle k owns rows 3k..3k+2
    owner = np.repeat(np.arange(len(T)), 3)
    key = np.sort(e, axis=1)
    uniq, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return e, owner, key, uniq, inv.ravel(), cnt


def components(T, n):
    if len(T) == 0:
        return 0, np.zeros(0, np.int64)
    rows = np.repeat(np.arange(len(T)), 3)
    g = sp.coo_matrix((np.ones(len(rows)), (rows, T.ravel())), shape=(len(T), n)).tocsr()
    adj = g @ g.T
    k, lab = connected_components(adj, directed=False)
    return k, lab


def signed_volume(P, T):
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def flipped_count(T):
    """Triangles that disagree with a neighbour about direction: an edge shared by two triangles must be walked in opposite directions."""
    e, owner, key, uniq, inv, cnt = edge_table(T)
    two = np.where(cnt[inv] == 2)[0]
    if len(two) == 0:
        return 0
    order = two[np.argsort(inv[two], kind="stable")]
    a, b = order[0::2], order[1::2]
    same = np.all(e[a] == e[b], axis=1)                          # both walk the edge the same way: they disagree
    bad = np.unique(np.concatenate([owner[a[same]], owner[b[same]]])) if same.any() else np.array([], np.int64)
    return int(len(bad)), int(same.sum())


def quality(P, T):
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    ea, eb, ec = np.linalg.norm(b - c, axis=1), np.linalg.norm(c - a, axis=1), np.linalg.norm(a - b, axis=1)
    area = tri_areas(P, T)
    with np.errstate(divide="ignore", invalid="ignore"):
        ang = lambda x, y, z: np.degrees(np.arccos(np.clip((y * y + z * z - x * x) / (2 * y * z), -1, 1)))
        angs = np.stack([ang(ea, eb, ec), ang(eb, ec, ea), ang(ec, ea, eb)], axis=1)
        ar = (np.maximum(np.maximum(ea, eb), ec) ** 2) / (4 * np.sqrt(3) * np.maximum(area, 1e-300))     # 1 = equilateral
    ok = np.isfinite(angs).all(axis=1) & np.isfinite(ar)
    return {"min_angle": float(np.nanmin(angs[ok])) if ok.any() else 0.0, "p5_min_angle": float(np.percentile(angs[ok].min(axis=1), 5)) if ok.any() else 0.0,
            "max_aspect": float(ar[ok].max()) if ok.any() else float("inf"), "median_aspect": float(np.median(ar[ok])) if ok.any() else float("inf"),
            "edge_min": float(min(ea.min(), eb.min(), ec.min())), "edge_max": float(max(ea.max(), eb.max(), ec.max())),
            "edge_mean": float((ea.mean() + eb.mean() + ec.mean()) / 3)}


def diagnose(mesh, tol=None):
    """Facts about a mesh.  Points are first merged (tol, default 1e-6 of the size), so an STL's unshared corners are not 'open edges'."""
    P0, T0 = arrays(mesh)
    d = diag_of(P0)
    tol = 1e-6 * d if tol is None else tol
    P, T = merge_points(P0, T0, tol)
    n_merged = len(P0) - len(np.unique(T))
    ar = tri_areas(P, T)
    small = 1e-10 * d * d
    degenerate = (T[:, 0] == T[:, 1]) | (T[:, 1] == T[:, 2]) | (T[:, 2] == T[:, 0]) | (ar < small)
    srt = np.sort(T, axis=1)
    _u, first, cnt3 = np.unique(srt, axis=0, return_index=True, return_counts=True)
    duplicates = int((cnt3 - 1).sum())
    good = T[~degenerate]
    e, owner, key, uniq, inv, cnt = edge_table(good) if len(good) else (None,) * 6
    open_edges = int((cnt == 1).sum()) if len(good) else 0
    nonman = int((cnt > 2).sum()) if len(good) else 0
    flips = flipped_count(good) if len(good) else (0, 0)
    k, lab = components(good, len(P)) if len(good) else (0, np.zeros(0, np.int64))
    areas = np.bincount(lab, weights=tri_areas(P, good), minlength=k) if k else np.zeros(0)
    closed = open_edges == 0 and nonman == 0 and len(good) > 0
    out = {"points": int(len(P0)), "points_merged": int(len(np.unique(good))) if len(good) else 0, "triangles": int(len(T0)),
           "degenerate": int(degenerate.sum()), "duplicates": duplicates, "open_edges": open_edges, "non_manifold_edges": nonman,
           "flipped_triangles": flips[0], "shells": int(k), "closed": bool(closed), "size": d,
           "shell_areas": sorted(areas.tolist(), reverse=True)[:6],
           "volume": abs(signed_volume(P, good)) if closed and flips[0] == 0 else None,
           "area": float(tri_areas(P, good).sum()) if len(good) else 0.0}
    out.update(quality(P, good) if len(good) else {})
    out["ok"] = bool(closed and flips[0] == 0 and not degenerate.any() and duplicates == 0 and k == 1)
    return out


# ------------------------------------------------------------------------------------------------------------- repair
def remove_nonmanifold(P, T, notes, limit=50):
    """Edges with three or more triangles: remove the largest triangles on them until every edge has at most two."""
    removed = 0
    for _ in range(limit):
        e, owner, key, uniq, inv, cnt = edge_table(T)
        bad = np.where(cnt > 2)[0]
        if len(bad) == 0:
            break
        ar = tri_areas(P, T)
        kill = set()
        for b in bad:
            tris = np.unique(owner[inv == b])
            order = tris[np.argsort(-ar[tris])]                 # the flap sticks out, so it is the odd, larger one
            for t in order[: len(tris) - 2]:
                kill.add(int(t))
        keep = np.ones(len(T), bool)
        keep[list(kill)] = False
        removed += len(kill)
        T = T[keep]
    if removed:
        notes.append(f"removed {removed} triangle(s) that made an edge shared by more than two triangles (fins)")
    return T


def orient(P, T, notes):
    """Make neighbouring triangles agree on direction (by walking across shared edges), then point every closed shell outward."""
    if len(T) == 0:
        return T
    e, owner, key, uniq, inv, cnt = edge_table(T)
    two = np.where(cnt[inv] == 2)[0]
    order = two[np.argsort(inv[two], kind="stable")]
    a, b = order[0::2], order[1::2]
    ta, tb = owner[a], owner[b]
    same = np.all(e[a] == e[b], axis=1)                         # True: the pair wants opposite orientation to be flipped relative to each other
    nT = len(T)
    adj = [[] for _ in range(nT)]
    for x, y, s in zip(ta.tolist(), tb.tolist(), same.tolist()):
        adj[x].append((y, s))
        adj[y].append((x, s))
    flip = -np.ones(nT, np.int8)
    lab = np.zeros(nT, np.int64)
    ncomp = 0
    for s0 in range(nT):
        if flip[s0] != -1:
            continue
        flip[s0] = 0
        lab[s0] = ncomp
        stack = [s0]
        while stack:
            x = stack.pop()
            for y, s in adj[x]:
                if flip[y] == -1:
                    flip[y] = flip[x] ^ (1 if s else 0)
                    lab[y] = ncomp
                    stack.append(y)
        ncomp += 1
    n_flip = int((flip == 1).sum())
    T = T.copy()
    T[flip == 1] = T[flip == 1][:, ::-1]
    n_out = 0
    for c in range(ncomp):                                      # a closed shell with negative volume is inside out
        sel = lab == c
        Tc = T[sel]
        ee, oo, kk, uu, ii, cc = edge_table(Tc)
        if (cc == 2).all() and signed_volume(P, Tc) < 0:
            T[sel] = Tc[:, ::-1]
            n_out += 1
    if n_flip or n_out:
        notes.append(f"turned {n_flip} triangle(s) to agree with their neighbours" + (f" and {n_out} shell(s) outward" if n_out else ""))
    return T


def boundary_loops(T):
    """The open edges chained into loops of vertices, each edge used once (a vertex where two loops touch is handled)."""
    e, owner, key, uniq, inv, cnt = edge_table(T)
    ob = np.where(cnt[inv] == 1)[0]
    out = {}
    for i in ob:
        out.setdefault(int(e[i][0]), []).append(int(e[i][1]))
    loops = []
    for s in list(out):
        while out.get(s):
            loop, v = [s], out[s].pop()
            while v != s:
                loop.append(v)
                nx = out.get(v)
                if not nx:
                    break
                v = nx.pop()
            loops.extend(split_simple(loop))
    return loops


def split_simple(loop):
    """A loop that passes through the same vertex twice is two loops touching there."""
    out, stack, pos = [], [], {}
    for v in loop:
        if v in pos:
            i = pos[v]
            sub = stack[i:]
            for w in sub[1:]:
                pos.pop(w, None)
            del stack[i + 1:]
            out.append(sub)
        else:
            pos[v] = len(stack)
            stack.append(v)
    out.append(stack)
    return [l for l in out if len(l) >= 3]


def collapse_slivers(P, T, d, notes, rounds=4):
    """A triangle with (almost) no area is removed by joining the two ends of its shortest edge, so no hole is left behind."""
    total = 0
    for _ in range(rounds):
        ar = tri_areas(P, T)
        bad = np.where((ar < 1e-10 * d * d) | (T[:, 0] == T[:, 1]) | (T[:, 1] == T[:, 2]) | (T[:, 2] == T[:, 0]))[0]
        if len(bad) == 0:
            break
        parent = np.arange(len(P))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for t in bad:
            a, b, c = (find(v) for v in T[t])
            pr = [(np.linalg.norm(P[x] - P[y]), x, y) for x, y in ((a, b), (b, c), (c, a)) if x != y]
            if pr:
                _l, x, y = min(pr)
                parent[max(x, y)] = min(x, y)
        T = np.array([[find(v) for v in t] for t in T]) if len(T) < 0 else parent_map(parent)[T]
        keep = (T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 2] != T[:, 0])
        total += int((~keep).sum())
        T = T[keep]
    if total:
        notes.append(f"removed {total} zero-area triangle(s) by joining their corners")
    return T


def parent_map(parent):
    r = parent.copy()
    while True:
        n = r[r]
        if (n == r).all():
            return r
        r = n


def fill_holes(P, T, max_diameter, notes):
    """Close each open loop smaller than max_diameter with a flat fan to its centre (kept to loops of up to 400 edges); returns P, T."""
    loops = boundary_loops(T)
    newP, newT, filled, left = [P], [T], 0, 0
    base = len(P)
    for loop in loops:
        pts = P[loop]
        if len(loop) < 3 or len(loop) > 400 or np.linalg.norm(pts.max(0) - pts.min(0)) > max_diameter:
            left += 1
            continue
        if len(loop) == 3:
            newT.append(np.array([[loop[1], loop[0], loop[2]]]))
            filled += 1
            continue
        c = pts.mean(axis=0)
        newP.append(c[None, :])
        # the open edge (a -> b) belongs to a triangle that walks it a->b, so the filling triangle walks it b->a
        tri = [(loop[(i + 1) % len(loop)], loop[i], base) for i in range(len(loop))]
        newT.append(np.array(tri))
        base += 1
        filled += 1
    if filled:
        notes.append(f"filled {filled} hole(s)")
    if left:
        notes.append(f"{left} open loop(s) were left (larger than the hole limit, or too long)")
    return np.vstack(newP), np.vstack(newT)


def despike(P, T, notes, k=2.0, rounds=3):
    """A point that sticks out of the mean of its neighbours by much more than the typical edge length is moved back to that mean."""
    moved = 0
    for _ in range(rounds):
        n = len(P)
        rows = np.concatenate([T[:, 0], T[:, 1], T[:, 2], T[:, 1], T[:, 2], T[:, 0]])
        cols = np.concatenate([T[:, 1], T[:, 2], T[:, 0], T[:, 0], T[:, 1], T[:, 2]])
        A = sp.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n)).tocsr()
        A.data[:] = 1.0
        deg = np.asarray(A.sum(axis=1)).ravel()
        mean = (A @ P) / np.maximum(deg, 1)[:, None]
        dev = np.linalg.norm(P - mean, axis=1)
        e = np.linalg.norm(P[T[:, 0]] - P[T[:, 1]], axis=1)
        med = float(np.median(e))
        # a spike lies far from a ring of neighbours that is itself flat (a box corner's ring is bent, so it is not a spike)
        m2 = (A @ (P[:, :, None] * P[:, None, :]).reshape(n, 9)).reshape(n, 3, 3) / np.maximum(deg, 1)[:, None, None]
        cov = m2 - mean[:, :, None] * mean[:, None, :]
        w, V = np.linalg.eigh(cov + 1e-12 * np.eye(3))
        off = np.abs(np.einsum("ij,ij->i", P - mean, V[:, :, 0]))                  # height above the plane fitted to the ring
        flat = np.sqrt(np.maximum(w[:, 0], 0)) < 0.2 * off
        bad = (off > k * med) & (deg > 0) & flat
        if not bad.any():
            break
        P = P.copy()
        P[bad] = mean[bad]
        moved += int(bad.sum())
    if moved:
        notes.append(f"flattened {moved} spike(s)")
    return P


def repair(mesh, hole_fraction=0.25, shell_fraction=0.01, spikes=True, tol=None):
    """-> (mesh, report).  hole_fraction: fill open loops up to this fraction of the model size.  shell_fraction: drop separate shells
    whose area is below this fraction of the largest."""
    before = diagnose(mesh, tol)
    P, T = arrays(mesh)
    d = diag_of(P)
    tol = 1e-6 * d if tol is None else tol
    notes = []
    P, T = merge_points(P, T, tol)
    idx_bad = (T[:, 0] == T[:, 1]) | (T[:, 1] == T[:, 2]) | (T[:, 2] == T[:, 0])
    if idx_bad.any():
        notes.append(f"removed {int(idx_bad.sum())} triangle(s) that use one corner twice")
        T = T[~idx_bad]
    T = collapse_slivers(P, T, d, notes)
    srt = np.sort(T, axis=1)
    _u, first = np.unique(srt, axis=0, return_index=True)
    if len(first) != len(T):
        notes.append(f"removed {len(T) - len(first)} duplicate triangle(s)")
        T = T[np.sort(first)]
    T = remove_nonmanifold(P, T, notes)
    k, lab = components(T, len(P))
    if k > 1:
        areas = np.bincount(lab, weights=tri_areas(P, T), minlength=k)
        keep = areas[lab] >= shell_fraction * areas.max()
        if (~keep).any():
            notes.append(f"removed {int(k - np.unique(lab[keep]).size)} small loose shell(s) ({int((~keep).sum())} triangles)")
        T = T[keep]
    P, T = drop_unused(P, T)
    if spikes:
        P = despike(P, T, notes)
    T = orient(P, T, notes)
    P, T = fill_holes(P, T, hole_fraction * d, notes)
    T = orient(P, T, [])
    P, T = drop_unused(P, T)
    out = to_mesh(P, T)
    after = diagnose(out)
    report = {"before": before, "after": after, "notes": notes}
    return out, report


def describe(d):
    """One line for a diagnose() result."""
    bits = [f"{d['triangles']} triangles", "closed" if d["closed"] else f"OPEN ({d['open_edges']} open edges)"]
    if d["non_manifold_edges"]:
        bits.append(f"{d['non_manifold_edges']} non-manifold edges")
    if d["flipped_triangles"]:
        bits.append(f"{d['flipped_triangles']} flipped")
    if d["degenerate"]:
        bits.append(f"{d['degenerate']} zero-area")
    if d["duplicates"]:
        bits.append(f"{d['duplicates']} duplicates")
    if d["shells"] != 1:
        bits.append(f"{d['shells']} shells")
    if d.get("volume") is not None:
        bits.append(f"volume {d['volume']:.1f}")
    return ", ".join(bits)
