"""Made-up solids for checking the voxel and tetrahedral solvers (everything here has a known answer, or is a stand-in for trabecular bone)."""
import numpy as np


def cube(n):
    return np.ones((n, n, n), bool)


def columns(cells=3, m=9, k=5, length=24, axis=2):
    """cells x cells columns of k x k voxels, one every m voxels, running along `axis`.  Volume fraction is exactly (k/m)^2."""
    shape = [cells * m, cells * m, length]
    occ = np.zeros(shape, bool)
    for i in range(cells):
        for j in range(cells):
            a = i * m + (m - k) // 2
            b = j * m + (m - k) // 2
            occ[a:a + k, b:b + k, :] = True
    return np.moveaxis(occ, 2, axis)


def cubic_lattice(cells=3, m=14, k=5):
    """A cubic frame: bars of k x k voxels along x, y and z through every node of a grid with spacing m."""
    n = cells * m
    occ = np.zeros((n, n, n), bool)
    for i in range(cells):
        for j in range(cells):
            a = i * m + (m - k) // 2
            b = j * m + (m - k) // 2
            occ[a:a + k, b:b + k, :] = True
            occ[a:a + k, :, b:b + k] = True
            occ[:, a:a + k, b:b + k] = True
    return occ


def segments_to_voxels(shape, p0, p1, radius):
    """Voxels (centres at i + 0.5) within `radius` of any segment p0[i]-p1[i] (all in voxel units)."""
    occ = np.zeros(shape, bool)
    for a, b, r in zip(p0, p1, radius):
        lo = np.maximum(np.floor(np.minimum(a, b) - r - 1).astype(int), 0)
        hi = np.minimum(np.ceil(np.maximum(a, b) + r + 1).astype(int), shape)
        ii = [np.arange(lo[c], hi[c]) + 0.5 for c in range(3)]
        X, Y, Z = np.meshgrid(*ii, indexing="ij")
        P = np.stack([X, Y, Z], -1)
        ab = b - a
        t = np.clip(((P - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        d = np.linalg.norm(P - (a + t[..., None] * ab), axis=-1)
        sl = tuple(slice(lo[c], hi[c]) for c in range(3))
        occ[sl] |= d <= r
    return occ


def trabecular(n=48, spacing=11.0, radius=2.3, seed=1, stretch=1.0):
    """A random strut network: jittered points on a grid joined to their near neighbours by round struts, running through the whole box."""
    rng = np.random.default_rng(seed)
    g = np.arange(-1, int(n / spacing) + 2)
    P = np.array([[x, y, z] for x in g for y in g for z in g], float) * spacing
    P += rng.uniform(-0.3, 0.3, P.shape) * spacing
    P[:, 2] *= stretch
    from scipy.spatial import cKDTree
    tree = cKDTree(P)
    pairs = tree.query_pairs(spacing * 1.35, output_type="ndarray")
    keep = rng.random(len(pairs)) < 0.8
    pairs = pairs[keep]
    a, b = P[pairs[:, 0]], P[pairs[:, 1]]
    ok = (np.minimum(a, b) < n + 3).all(1) & (np.maximum(a, b) > -3).all(1)
    a, b = a[ok], b[ok]
    r = rng.uniform(0.75, 1.15, len(a)) * radius
    return segments_to_voxels((n, n, n), a, b, r)


TEST_MODELS = {
    "Solid cube (10 mm)": lambda: (cube(10), 1.0),
    "Bundle of bars (exact answer)": lambda: (columns(3, 9, 5, 24), 1.0),
    "Cubic frame of bars": lambda: (cubic_lattice(3, 14, 5), 1.0),
    "Random struts, small (40 mm)": lambda: (trabecular(40, 9.2, 1.9, 3), 1.0),
    "Random struts, larger (64 mm)": lambda: (trabecular(64, 14.0, 1.9, 2), 1.0),
}
