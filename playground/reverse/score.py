"""How close is a rebuilt shape to the original?  Volume, the volume that is in one and not the other, and surface distances."""
import numpy as np
from build123d import Compound, Solid
from scipy.spatial import cKDTree


def safe_vol(s):
    try:
        return float(s.volume)
    except Exception:
        return 0.0


def xor_volume(a, b):
    """Volume of (a - b) plus (b - a): zero when the two shapes are the same."""
    try:
        return safe_vol(a - b) + safe_vol(b - a)
    except Exception:
        return float("nan")


def surface_points(s, n=3000, seed=0):
    """Points spread over the surface of a shape (from its triangulation)."""
    rng = np.random.default_rng(seed)
    tris, areas = [], []
    for f in s.faces():
        try:
            v, t = f.tessellate(0.02 * max(1.0, _diag(s)) / 10, 0.3)
        except Exception:
            continue
        if not v or not t:
            continue
        V = np.array([[p.X, p.Y, p.Z] for p in v])
        for i, j, k in t:
            tris.append((V[i], V[j], V[k]))
    if not tris:
        return np.zeros((0, 3))
    T = np.array(tris)
    area = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    idx = rng.choice(len(T), size=n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    flip = r1 + r2 > 1
    r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
    a, b, c = T[idx, 0], T[idx, 1], T[idx, 2]
    return a + (b - a) * r1[:, None] + (c - a) * r2[:, None]


def _diag(s):
    bb = s.bounding_box()
    return float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z]))


def _dist_to(shape, pts):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    out = []
    for p in pts:
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(float(p[0]), float(p[1]), float(p[2]))).Vertex()
        e = BRepExtrema_DistShapeShape(v, shape.wrapped)
        e.Perform()
        out.append(e.Value() if e.IsDone() else float("inf"))
    return np.array(out)


def surface_distance(a, b, n=700):
    """(largest, 95th percentile) of the distances between the surfaces of two shapes (points of each against the other, exact)."""
    pa, pb = surface_points(a, n), surface_points(b, n, seed=1)
    if len(pa) == 0 or len(pb) == 0:
        return float("inf"), float("inf")
    d = np.concatenate([_dist_to(b, pa), _dist_to(a, pb)])
    return float(d.max()), float(np.percentile(d, 95))


def score(orig, new):
    """{'vol', 'vol_new', 'xor_pct', 'hd_max', 'hd_p95', 'ok'}; ok = rebuilt within 0.5 % of the volume and 0.3 % of the size."""
    vo, vn = safe_vol(orig), safe_vol(new)
    x = xor_volume(orig, new)
    hmax, h95 = surface_distance(orig, new)
    diag = _diag(orig)
    pct = 100.0 * x / vo if vo > 0 else float("inf")
    return {"vol": vo, "vol_new": vn, "xor_pct": pct, "hd_max": hmax, "hd_p95": h95, "diag": diag,
            "ok": bool(pct == pct and pct < 0.5 and h95 < 0.003 * diag)}
