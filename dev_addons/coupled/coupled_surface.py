"""coupled_surface.py - a field known at the nodes of a TRIANGULATED SURFACE in 3D, asked for at any points near it (no Qt).

The two analyses of a Coupled Physics solve mesh the same part with their own meshes, so the pressure or the temperature of the wall that one has at its surface nodes is worked
out at the surface nodes (or the centres of the surface triangles) of the other: every asked point is projected on the nearest triangle of the first surface and the field is
interpolated linearly there (barycentric weights, never negative: nothing outside the range of the source can appear).  How far the point lies from that triangle is reported (`gap`,
in the same units as the points, and in element sizes through `h`): a curved wall that the two meshes cut differently makes a small gap, a point that belongs to no wall of the first
surface makes a big one, and the callers count and report both.
"""
import numpy as np


class SurfaceLocator:
    def __init__(self, points, tris):
        from scipy.spatial import cKDTree
        self.P = np.asarray(points, float)
        self.T = np.asarray(tris, np.int64).reshape(-1, 3)
        if not len(self.T):
            raise ValueError("The surface has no triangle.")
        a, b, c = (self.P[self.T[:, i]] for i in range(3))
        self.a, self.ab, self.ac = a, b - a, c - a
        self.centre = (a + b + c) / 3.0
        self.tree = cKDTree(self.centre)
        e = np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], axis=1)
        self.h = float(np.median(e))
        self._memo = None

    def locate(self, targets, k=10):
        """-> (triangle index (n,), barycentric weights (n, 3), distance (n,)): for every target the nearest triangle (the nearest point of any of the k triangles with the nearest centres).
        The last answer is kept: a heat exchange asks for the coefficient, the temperature and the flux at the same points one after the other, and finding them is the expensive part."""
        X = np.ascontiguousarray(np.asarray(targets, float).reshape(-1, 3))
        key = (X.shape, int(k), hash(X.tobytes()))
        if self._memo is not None and self._memo[0] == key:
            return self._memo[1]
        out = self._locate(X, k)
        self._memo = (key, out)
        return out

    def _locate(self, X, k):
        n = len(X)
        k = min(int(k), len(self.T))
        _d, cand = self.tree.query(X, k=k)
        cand = np.asarray(cand).reshape(n, k)
        a, ab, ac = self.a[cand], self.ab[cand], self.ac[cand]                         # (n, k, 3)
        w, dist = _closest(X[:, None, :], a, ab, ac)                                   # (n, k, 3), (n, k)
        best = np.argmin(dist, axis=1)
        rows = np.arange(n)
        return cand[rows, best], w[rows, best], dist[rows, best]

    def interpolate(self, values, targets, k=10):
        """-> (values at the targets, info {"points", "max_gap", "mean_gap"}).  `values` is one number per point of the surface, or (npoints, c) for a vector."""
        v = np.asarray(values, float)
        if len(v) != len(self.P):
            raise ValueError(f"The field has {len(v)} values but its surface has {len(self.P)} points.")
        t, w, dist = self.locate(targets, k)
        vt = v[self.T[t]]                                                              # (n, 3) or (n, 3, c)
        out = np.einsum("nk,nk...->n...", w, vt)
        return out, {"points": int(len(out)), "max_gap": float(dist.max()) if len(dist) else 0.0, "mean_gap": float(dist.mean()) if len(dist) else 0.0}


def _closest(X, a, ab, ac):
    """The point of the triangles (a, a+ab, a+ac) nearest to X (broadcast): -> barycentric weights (..., 3) and the distance (Ericson, 'Real-Time Collision Detection', 5.1.5)."""
    ap = X - a
    d1, d2 = np.einsum("...i,...i->...", ab, ap), np.einsum("...i,...i->...", ac, ap)
    bp = X - (a + ab)
    d3, d4 = np.einsum("...i,...i->...", ab, bp), np.einsum("...i,...i->...", ac, bp)
    cp = X - (a + ac)
    d5, d6 = np.einsum("...i,...i->...", ab, cp), np.einsum("...i,...i->...", ac, cp)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    with np.errstate(divide="ignore", invalid="ignore"):
        # inside the face
        den = va + vb + vc
        v_in, w_in = vb / den, vc / den
        # on an edge or at a vertex
        t_ab = d1 / (d1 - d3)
        t_ac = d2 / (d2 - d6)
        t_bc = (d4 - d3) / ((d4 - d3) + (d5 - d6))
    shape = d1.shape
    v = np.zeros(shape)
    w = np.zeros(shape)
    done = np.zeros(shape, bool)

    def put(mask, vv, ww):
        nonlocal done
        m = mask & ~done
        v[m] = vv[m] if np.ndim(vv) else vv
        w[m] = ww[m] if np.ndim(ww) else ww
        done |= m
    put((d1 <= 0) & (d2 <= 0), 0.0, 0.0)                                              # vertex a
    put((d3 >= 0) & (d4 <= d3), 1.0, 0.0)                                              # vertex b
    put((d6 >= 0) & (d5 <= d6), 0.0, 1.0)                                              # vertex c
    put((vc <= 0) & (d1 >= 0) & (d3 <= 0), t_ab, 0.0)                                  # edge ab
    put((vb <= 0) & (d2 >= 0) & (d6 <= 0), 0.0, t_ac)                                  # edge ac
    put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), 1.0 - t_bc, t_bc)             # edge bc
    put(np.ones(shape, bool), v_in, w_in)                                              # inside
    u = 1.0 - v - w
    q = a + v[..., None] * ab + w[..., None] * ac
    dist = np.linalg.norm(X - q, axis=-1)
    return np.stack([u, v, w], axis=-1), dist


def same_faces(faces_a, faces_b, ids, diag=None, tol=1e-6):
    """Do two analyses of the same part number their faces the same way?  faces_a, faces_b: [{"id", "center", "area"}] (solid_geom.analyze); ids: the faces to compare.
    -> (True, []) or (False, [the ids that differ or are missing in one of them]).  Two faces are the same when their areas agree to `tol` (relative) and their centres lie within
    `tol` of the size of the part (`diag`, by default the largest distance between two centres)."""
    a = {int(f["id"]): f for f in faces_a}
    b = {int(f["id"]): f for f in faces_b}
    if diag is None:
        C = np.array([f["center"] for f in list(a.values()) + list(b.values())], float).reshape(-1, 3)
        diag = float(np.ptp(C, axis=0).max()) if len(C) else 1.0
    bad = []
    for i in (int(x) for x in ids):
        fa, fb = a.get(i), b.get(i)
        if fa is None or fb is None:
            bad.append(i)
            continue
        same_area = abs(float(fa["area"]) - float(fb["area"])) <= tol * max(float(fa["area"]), 1e-12) + 1e-12
        same_spot = float(np.linalg.norm(np.asarray(fa["center"], float) - np.asarray(fb["center"], float))) <= tol * max(diag, 1e-12)
        if not (same_area and same_spot):
            bad.append(i)
    return (not bad), bad


def split_triangles(tris):
    """The triangles of a mesh's surface as 3-node triangles: 3-node ones as they are; the 6-node ones of a quadratic mesh (three corners, then the mid-nodes of the sides 1-2, 2-3,
    3-1) are cut into four through their mid-nodes, so that a field that is quadratic along the surface is followed by the pieces and not only at the corners."""
    t = np.asarray(tris, np.int64)
    if t.ndim != 2 or t.shape[1] == 3:
        return t.reshape(-1, 3)
    if t.shape[1] != 6:
        raise ValueError("A surface triangle has 3 or 6 nodes.")
    a, b, c, ab, bc, ca = (t[:, i] for i in range(6))
    return np.vstack([np.stack(x, 1) for x in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))])


def faces_triangles(q, fids):
    """The 3-node triangles (split_triangles) of the faces `fids` of a mesh of the 3D windows (q["ftri"], else q["faces"]); an empty (0, 3) array when it has none of them."""
    src = q.get("ftri") or q.get("faces") or {}
    parts = [split_triangles(src[f]) for f in fids if f in src]
    return np.vstack(parts) if parts else np.zeros((0, 3), np.int64)
