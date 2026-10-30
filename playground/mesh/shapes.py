"""Test shapes for the mesh playground: smooth organic surfaces, and ways to damage them the way real STL files are damaged.

Every shape is a pyvista PolyData of triangles with outward normals.  Sizes are millimetres.
"""
import numpy as np
import pyvista as pv


def _field_mesh(fn, lo, hi, n):
    xs = np.linspace(lo[0], hi[0], n)
    ys = np.linspace(lo[1], hi[1], n)
    zs = np.linspace(lo[2], hi[2], n)
    g = pv.ImageData(dimensions=(n, n, n), spacing=(xs[1] - xs[0], ys[1] - ys[0], zs[1] - zs[0]), origin=(xs[0], ys[0], zs[0]))
    P = g.points
    g["f"] = fn(P[:, 0], P[:, 1], P[:, 2])
    m = g.contour([0.0], scalars="f").triangulate().clean()
    m = m.compute_normals(consistent_normals=True, auto_orient_normals=True, split_vertices=False)
    return m.extract_surface(algorithm=None).triangulate()


def blob(n=64, seed=0):
    """A smooth lumpy body (about 80 mm), a union of a few soft spheres."""
    rng = np.random.default_rng(seed)
    centres = rng.uniform(-18, 18, (5, 3)) * np.array([1.4, 1.0, 0.8])
    radii = rng.uniform(16, 26, 5)

    def fn(x, y, z):
        v = np.zeros_like(x)
        for c, r in zip(centres, radii):
            v += np.exp(-(((x - c[0]) ** 2 + (y - c[1]) ** 2 + (z - c[2]) ** 2) / (r * r)) * 1.6)
        return 0.9 - v
    return _field_mesh(fn, (-70, -60, -60), (70, 60, 60), n)


def torus(n=44, R=30.0, r=9.0):
    def fn(x, y, z):
        return (np.hypot(np.hypot(x, y) - R, z)) - r
    return _field_mesh(fn, (-R - r - 4,) * 2 + (-r - 4,), (R + r + 4,) * 2 + (r + 4,), n)


def bone(n=56):
    """Two knobbly ends joined by a shaft - an organic 'long bone' about 120 mm long."""
    def fn(x, y, z):
        shaft = np.maximum(np.hypot(y, z) - (8.0 + 1.5 * np.sin(x / 9.0)), np.abs(x) - 52.0)
        knob = lambda cx: np.sqrt((x - cx) ** 2 + (1.0 * y) ** 2 + (z * 1.1) ** 2) - 17.0
        k = np.minimum(knob(-52), knob(52))
        return -np.log(np.exp(-shaft / 4.0) + np.exp(-k / 4.0)) * 4.0     # a smooth union: no sharp crease where they meet
    return _field_mesh(fn, (-75, -25, -25), (75, 25, 25), n)


def scan(noise=0.5, n=64, seed=1):
    """A blob with the fine roughness of a scan: displaced along the normals by smooth random noise."""
    m = blob(n, seed)
    rng = np.random.default_rng(seed)
    f = rng.uniform(0.15, 0.5, (4, 3))
    ph = rng.uniform(0, 6.28, 4)
    P = m.points
    nz = sum(np.sin(P @ f[i] + ph[i]) for i in range(4)) / 4.0
    nz += rng.normal(0, 0.35, len(P))
    nrm = m.compute_normals(point_normals=True, cell_normals=False).point_data["Normals"]
    out = m.copy()
    out.points = P + nrm * (noise * nz)[:, None]
    return out


def box_bar(L=100.0, h=10.0, w=10.0, div=24):
    """A straight rectangular bar (exact corners): used to check the section -> FEA chain against beam theory."""
    b = pv.Box(bounds=(0, L, 0, w, 0, h), level=0, quads=False).triangulate()
    return b.subdivide(3, subfilter="linear").clean()


# ------------------------------------------------------------------------------------------------------ damage
def unmerge(mesh):
    """As an STL file stores it: every triangle with its own three vertices (no shared points)."""
    f = mesh.faces.reshape(-1, 4)[:, 1:]
    pts = mesh.points[f.ravel()]
    return pv.PolyData(pts, np.hstack([np.full((len(f), 1), 3), np.arange(len(pts)).reshape(-1, 3)]).ravel())


def _tris(mesh):
    return mesh.faces.reshape(-1, 4)[:, 1:].copy()


def _mk(points, tris):
    return pv.PolyData(np.asarray(points, float), np.hstack([np.full((len(tris), 1), 3), np.asarray(tris, np.int64)]).ravel())


def punch_holes(mesh, n=3, size=6.0, seed=0):
    """Delete the triangles around n random points (holes of about `size` mm)."""
    rng = np.random.default_rng(seed)
    f = _tris(mesh)
    c = mesh.points[f].mean(axis=1)
    keep = np.ones(len(f), bool)
    for i in rng.choice(len(f), n, replace=False):
        keep &= np.linalg.norm(c - c[i], axis=1) > size
    return _mk(mesh.points, f[keep])


def flip_some(mesh, frac=0.15, seed=0):
    rng = np.random.default_rng(seed)
    f = _tris(mesh)
    sel = rng.random(len(f)) < frac
    f[sel] = f[sel][:, ::-1]
    return _mk(mesh.points, f)


def spikes(mesh, n=6, height=8.0, seed=0):
    rng = np.random.default_rng(seed)
    out = mesh.copy()
    nrm = mesh.compute_normals(point_normals=True, cell_normals=False).point_data["Normals"]
    idx = rng.choice(len(mesh.points), n, replace=False)
    P = out.points.copy()
    P[idx] += nrm[idx] * height
    out.points = P
    return out


def fin(mesh, seed=0):
    """A flap glued to one edge: that edge is then shared by three triangles (non-manifold)."""
    rng = np.random.default_rng(seed)
    f = _tris(mesh)
    t = f[rng.integers(len(f))]
    P = mesh.points
    mid = P[t].mean(axis=0)
    nrm = np.cross(P[t[1]] - P[t[0]], P[t[2]] - P[t[0]])
    nrm /= np.linalg.norm(nrm)
    tip = mid + nrm * 7.0
    pts = np.vstack([P, tip])
    return _mk(pts, np.vstack([f, [t[0], t[1], len(P)]]))


def degenerate(mesh, n=20, seed=0):
    """Zero-area triangles and exact duplicate triangles."""
    rng = np.random.default_rng(seed)
    f = _tris(mesh)
    P = mesh.points
    z = [(a, a, b) for a, b in rng.integers(len(P), size=(n, 2))]
    d = f[rng.choice(len(f), n, replace=False)]
    return _mk(P, np.vstack([f, np.array(z), d]))


def floaters(mesh, n=3, seed=0):
    """Tiny loose shells (stray scan fragments)."""
    rng = np.random.default_rng(seed)
    P, f = mesh.points, _tris(mesh)
    lo, hi = P.min(0), P.max(0)
    pts, tr = [P], [f]
    base = len(P)
    for _ in range(n):
        c = rng.uniform(lo, hi) + (hi - lo) * 0.7
        t = np.array([[0, 0, 0], [1.2, 0, 0], [0, 1.2, 0], [0, 0, 1.2]]) + c
        pts.append(t)
        tr.append(np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]) + base)
        base += 4
    return _mk(np.vstack(pts), np.vstack(tr))


DAMAGE = {
    "holes": punch_holes, "flipped": flip_some, "spikes": spikes, "fin": fin, "degenerate": degenerate, "floaters": floaters,
}


def damaged(mesh, kinds, seed=0):
    """Apply the named damages in turn, then store it the way an STL does (unmerged vertices)."""
    m = mesh
    for k in kinds:
        m = DAMAGE[k](m, seed=seed)
    return unmerge(m)


def corpus():
    """{name: mesh}: the clean shapes and a damaged version of each kind of fault."""
    out = {"blob": blob(), "torus": torus(), "bone": bone(), "scan": scan(), "bar": box_bar()}
    base = out["blob"]
    for k in DAMAGE:
        out[f"blob_{k}"] = damaged(base, [k])
    out["blob_all"] = damaged(base, list(DAMAGE))
    out["scan_all"] = damaged(out["scan"], ["holes", "flipped", "degenerate", "floaters"])
    return out
