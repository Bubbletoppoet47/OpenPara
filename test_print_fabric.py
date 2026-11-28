"""Printed-part analysis, PA-3 (planning/design/slicer, chapter 10.4; tests A5 and A6 of 10.7): from toolpaths to the stiffness of every element.

The paths here are MADE BY THIS TEST (a rectilinear infill at 45 and -45 degrees, a wall, roads along x), not by the slicer: they stand in for it so that the
mapping can be checked against numbers worked out by hand.  When the compiled engine runs, the same checks are to be repeated on its real paths (listed as
pending at the end, not as passed).

  harmonics   the stiffness of roads at any angle is the five-term sum the file uses (checked at angles that were not used to make it)
  A5          a 20 mm cube of 45 / -45 degree infill: equal in-plane eigenvalues of the orientation tensor, plastic fraction = the infill density
  A6          a wall: one dominant eigenvalue along the wall, plastic fraction near 1
  mapping     roads along x give the matrix of material 1 along x; the other layer directions and the plastic fraction scale it as the model says; an object that
              stands somewhere else on the plate (a transform) gives the same; a window with no plastic in it never gives a zero matrix
  interface   the group helper and the saved fabric
"""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "shared"),
                os.path.join(HERE, "engines", "orca_core", "python")]
import numpy as np
import solid_fem as fem
import print_fabric as pf

W, H = 0.45, 0.2                                    # road width and layer height, mm
FLOW = W * H                                        # mm3 per mm (a rectangle; Orca's own value is a little less because the road has rounded sides)
C = {"E1": 2400.0, "E2": 2000.0, "E3": 1500.0, "G12": 800.0, "G23": 600.0, "G13": 600.0, "nu12": 0.33, "nu23": 0.35, "nu13": 0.30}
D0 = pf.road_matrix(C)


class P:                                            # what an orca_core.Paths gives to Fabric.from_paths
    def __init__(self, polylines, role, layer):
        self.points = np.concatenate([np.asarray(p, float) for p in polylines])
        self.start = np.concatenate([[0], np.cumsum([len(p) for p in polylines])])
        m = len(polylines)
        self.role, self.height, self.mm3_per_mm = np.full(m, role), np.full(m, H), np.full(m, FLOW)
        self.layer = np.asarray(layer)


def clip_line(c, ang, size):
    """The part of the line  x cos(ang) + y sin(ang) = c  inside the square [0, size]^2, as two points (or None)."""
    d = np.array([-np.sin(ang), np.cos(ang)])
    n = np.array([np.cos(ang), np.sin(ang)])
    p0 = n * c
    ts = []
    for k in (0, 1):
        for b in (0.0, size):
            if abs(d[k]) > 1e-12:
                t = (b - p0[k]) / d[k]
                q = p0 + d * t
                if -1e-9 <= q[1 - k] <= size + 1e-9:
                    ts.append(t)
    if len(ts) < 2:
        return None
    return p0 + d * min(ts), p0 + d * max(ts)


def infill(size, nlayers, density, angles, role=4, x0=0.0, y0=0.0, z0=0.0):
    """Rectilinear infill: layer k uses angles[k % len(angles)]; the lines are spaced W / density apart."""
    lines = []
    sp = W / density
    for k in range(nlayers):
        ang = angles[k % len(angles)]
        z = z0 + (k + 1) * H
        nrm = np.array([np.cos(ang + np.pi / 2), np.sin(ang + np.pi / 2)])
        cs = [nrm @ q for q in ((0, 0), (size, 0), (0, size), (size, size))]
        for c in np.arange(min(cs) + sp / 2, max(cs), sp):
            seg = clip_line(c, ang + np.pi / 2, size)         # a line with normal at ang + 90 degrees runs along ang
            if seg is None:
                continue
            a, b = seg
            lines.append([(x0 + a[0], y0 + a[1], z), (x0 + b[0], y0 + b[1], z)])
    return P(lines, role, [0] * len(lines))


def bricks(x, y, z, size):
    """Centroids, volumes and 8 sample points of a lattice of bricks; x, y, z the centres, size the edge lengths."""
    cen = np.array([(a, b, c) for a in x for b in y for c in z], float)
    off = np.array([(i, j, k) for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)], float) * 0.25 * np.array(size)
    return cen, np.full(len(cen), float(np.prod(size))), cen[:, None, :] + off[None]


# ---------------------------------------------------------------------------------------------- the harmonic basis
Cb = pf.harmonic_basis(D0)
rng = np.random.default_rng(3)
for t in rng.uniform(-np.pi, np.pi, 12):
    series = Cb[0] + Cb[1] * np.cos(2 * t) + Cb[2] * np.sin(2 * t) + Cb[3] * np.cos(4 * t) + Cb[4] * np.sin(4 * t)
    assert np.abs(series - pf.D_at(D0, t)).max() < 1e-8 * np.abs(D0).max(), t
assert np.abs(pf.D_at(D0, 0.0) - D0).max() == 0 or np.abs(pf.D_at(D0, 0.0) - D0).max() < 1e-9, "roads along x: the matrix of material 1 along x"
# a turn by 90 degrees swaps the in-plane axes: D_xx(90) is D_yy(0)
assert abs(pf.D_at(D0, np.pi / 2)[0, 0] - D0[1, 1]) < 1e-6 and abs(pf.D_at(D0, np.pi)[0, 0] - D0[0, 0]) < 1e-6
print("harmonic basis: ok")

# ---------------------------------------------------------------------------------------------- A5: 45 / -45 infill in a 20 mm cube
size, nl = 20.0, 100                                        # 20 mm of layers
dens = 0.25
inf = infill(size, nl, dens, [np.pi / 4, -np.pi / 4])
fab = pf.Fabric.from_paths(inf)
vol_expected = size * size * nl * H * dens                  # plastic volume if the lines tile the square at that density
assert abs(fab.total_volume() / vol_expected - 1) < 0.03, (fab.total_volume(), vol_expected)
# the whole cube, in one window
lo, hi = fab.bbox()
co = fab.coarse(lo, hi - lo + 1e-6, (1, 1, 1))
A = pf.orientation_tensor(co["tens"], co["vol"])[0]
ev = np.sort(np.linalg.eigvalsh(A))[::-1]
assert abs(np.trace(A) - 1) < 1e-6 and abs(A[0, 0] - A[1, 1]) < 0.01 and abs(A[0, 1]) < 0.01 and A[2, 2] < 1e-6, A
assert abs(ev[0] - 0.5) < 0.01 and abs(ev[1] - 0.5) < 0.01 and ev[2] < 1e-6, ev
# phi, from the mesh: a cube of bricks of 2 mm
g = np.arange(1.0, size, 2.0)
cen, vol, smp = bricks(g, g, g, (2.0, 2.0, 2.0))
res = pf.element_stiffness(fab, cen, vol, C, sigma=2.5, sigma_z=2.5, samples=smp)
inner = np.all((cen > 5) & (cen < 15), axis=1)              # away from the edges where the lines end
assert abs(res["phi"][inner].mean() - dens) < 0.02, res["phi"][inner].mean()
assert abs(res["phi"].mean() - dens) < 0.03 and res["phi"].max() < 0.45, "the surface of the part does not thin the plastic: %.3f %.3f" % (res["phi"].mean(), res["phi"].max())
Ain = res["A"][inner].mean(axis=0)
assert abs(Ain[0, 0] - Ain[1, 1]) < 0.02 and abs(Ain[0, 1]) < 0.02, Ain
# and the matrices: the mean of the two directions, so xx = yy and the xy coupling to the shear is zero
Dm = fem.unpack_D(res["D21"])[inner].mean(axis=0)
want = dens * 0.5 * (pf.D_at(D0, np.pi / 4) + pf.D_at(D0, -np.pi / 4))
assert np.abs(Dm - want).max() < 0.03 * np.abs(want).max(), (np.abs(Dm - want).max(), np.abs(want).max())
assert abs(Dm[0, 0] - Dm[1, 1]) < 0.02 * Dm[0, 0] and abs(Dm[0, 3]) < 0.02 * Dm[0, 0] and abs(Dm[3, 5]) < 1e-3 * Dm[0, 0]
print("A5 (45 / -45 infill, plastic fraction %.3f for a density of %.2f, in-plane eigenvalues %.3f %.3f): ok" % (res["phi"][inner].mean(), dens, ev[0], ev[1]))

# ---------------------------------------------------------------------------------------------- A6: a wall
loops = []
for k in range(nl):
    z = (k + 1) * H
    for r in range(3):                                      # three loops, side by side, the outer one at the edge
        o = W * (r + 0.5)
        loops.append([(o, o, z), (size - o, o, z), (size - o, size - o, z), (o, size - o, z), (o, o, z)])
wall = P(loops, 2, [0] * len(loops))
fw = pf.Fabric.from_paths(wall)
# a window across the middle of the bottom side of the loop (y near 0): the roads there run along x
cen_w = np.array([[10.0, 0.5 * 3 * W, z] for z in np.arange(0.5, 19.5, 1.0)])
volw = np.full(len(cen_w), 1.0)
rw = pf.element_stiffness(fw, cen_w, volw, C, sigma=0.5, sigma_z=2.0)
Aw = rw["A"][5]
evw = np.sort(np.linalg.eigvalsh(Aw))[::-1]
assert evw[0] > 0.97 and Aw[0, 0] > 0.97, (Aw, evw)
assert abs(np.linalg.eigh(Aw)[1][:, -1][0]) > 0.99, "the dominant axis is along the wall (x)"
print("A6 (wall: dominant eigenvalue %.3f along x): ok" % evw[0])

# ---------------------------------------------------------------------------------------------- mapping: roads along x, solid, so the matrix is that of the material
solid = infill(10.0, 20, 1.0, [0.0])                         # lines along x, side by side; 4 mm high
fs = pf.Fabric.from_paths(solid)
cen, vol, smp = bricks(np.arange(1.0, 10.0, 2.0), np.arange(1.0, 10.0, 2.0), np.arange(0.5, 4.0, 1.0), (2.0, 2.0, 1.0))
KW = dict(sigma=2.0, sigma_z=1.0)
res = pf.element_stiffness(fs, cen, vol, C, samples=smp, **KW)
sel = np.all((cen[:, :2] > 2) & (cen[:, :2] < 8), axis=1)
Ds = fem.unpack_D(res["D21"])[sel]
assert res["phi"][sel].min() > 0.9 and res["phi"].min() > 0.8, (res["phi"][sel].min(), res["phi"].min())
assert np.abs(Ds / res["phi"][sel][:, None, None] - D0).max() < 0.01 * np.abs(D0).max(), "roads along x give the matrix of the material"
assert res["A"][sel][:, 0, 0].min() > 0.999
# roads along y: the in-plane axes are swapped
fy = pf.Fabric.from_paths(infill(10.0, 20, 1.0, [np.pi / 2]))
ry = pf.element_stiffness(fy, cen, vol, C, samples=smp, **KW)
Dy = fem.unpack_D(ry["D21"])[sel].mean(axis=0) / ry["phi"][sel].mean()
want = pf.D_at(D0, np.pi / 2)
assert np.abs(Dy - want).max() < 0.01 * np.abs(want).max() and abs(Dy[1, 1] - D0[0, 0]) < 0.01 * D0[0, 0], "roads along y"
# the model: phi to the power p (p = 1 is the rule of mixtures)
half = pf.Fabric.from_paths(infill(10.0, 20, 0.5, [0.0]))
r1 = pf.element_stiffness(half, cen, vol, C, samples=smp, phi_power=1.0, **KW)
r2 = pf.element_stiffness(half, cen, vol, C, samples=smp, phi_power=2.0, **KW)
phi = r1["phi"][sel].mean()
assert abs(phi - 0.5) < 0.03, phi
D1m, D2m = (fem.unpack_D(r["D21"])[sel].mean(axis=0) for r in (r1, r2))
assert np.abs(D1m / phi - D0).max() < 0.02 * np.abs(D0).max() and np.abs(D2m / (phi * phi) - D0).max() < 0.03 * np.abs(D0).max(), "D = phi**p * D0 for roads along x"
# an object that stands elsewhere on the plate: the same result with its transform
T = np.eye(4); T[:3, 3] = [120.0, 80.0, 0.0]
moved = infill(10.0, 20, 1.0, [0.0], x0=120.0, y0=80.0)
fm = pf.Fabric.from_paths(moved)
rm = pf.element_stiffness(fm, cen, vol, C, samples=smp, transform=T, **KW)
assert np.abs(rm["D21"] - res["D21"]).max() < 1e-3 * np.abs(res["D21"]).max(), "the transform puts the mesh where the object stands"
print("mapping: ok")

# ---------------------------------------------------------------------------------------------- a window with no plastic: never a zero matrix
far = np.array([[50.0, 50.0, 50.0]])
empty = pf.element_stiffness(fs, far, np.array([1.0]), C, sigma=2.0, sigma_z=1.0)
De = fem.unpack_D(empty["D21"])[0]
assert empty["empty"] == 1 and np.linalg.eigvalsh(De).min() > 0 and abs(De[0, 0] - De[1, 1]) < 1e-9 * De[0, 0], "in-plane the same both ways, positive"
assert abs(empty["phi"][0] - 1e-3) < 1e-12

# ---------------------------------------------------------------------------------------------- the interface
nodes = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.0]])
cen_g, vol_g = pf.group_centroids_volumes(nodes, {"kind": "tet", "conn": np.array([[0, 1, 2, 3]])})
assert np.allclose(cen_g, [[0.25, 0.25, 0.25]]) and abs(vol_g[0] - 1 / 6) < 1e-12
cube = np.array([[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0], [0, 0, 2], [2, 0, 2], [2, 2, 2], [0, 2, 2]], float)
cen_h, vol_h = pf.group_centroids_volumes(cube, {"kind": "hex", "conn": np.arange(8)[None]})
assert np.allclose(cen_h, [[1, 1, 1]]) and abs(vol_h[0] - 8.0) < 1e-12, vol_h
pyr = np.array([[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0], [1, 1, 3.0]])
assert abs(pf.group_centroids_volumes(pyr, {"kind": "pyr", "conn": np.arange(5)[None]})[1][0] - 4.0) < 1e-12
fn = os.path.join(tempfile.mkdtemp(), "fabric.npz")
fs.save(fn)
f2 = pf.Fabric.load(fn)
assert np.array_equal(f2.ids, fs.ids) and np.array_equal(f2.acc, fs.acc) and f2.shape == fs.shape and np.array_equal(f2.origin, fs.origin)
for bad, words in ((lambda: pf.Fabric.from_paths(P([[(0, 0, 1), (1, 0, 1)]], 14, [0])), "supports"),
                   (lambda: pf.element_stiffness(fs, np.zeros((0, 3)), np.zeros(0), C), "no elements"),
                   (lambda: pf.element_stiffness(fs, np.zeros((1, 3)), np.ones(1), dict(C, E1=-1.0)), "E1"),
                   (lambda: pf.element_stiffness(fs, np.zeros((1, 3)), np.ones(1), {"E1": 1.0}), "incomplete"),
                   (lambda: pf.element_stiffness(fs, np.zeros((1, 3)), np.ones(1), C, sigma=-1.0), "greater than zero"),
                   (lambda: pf.element_stiffness(fs, np.array([[0, 0, 0], [1e6, 1e6, 1e6]]), np.ones(2), C, sigma=1.0), "larger smoothing")):
    try:
        bad()
    except (pf.FabricError, fem.FemError) as e:
        assert words in str(e), (words, str(e))
    else:
        raise SystemExit("not refused: " + words)
# the roles used here are the engine's
import orca_core as oc
assert pf.PART_ROLES == tuple(oc.role_id(n) for n in ("Inner wall", "Outer wall", "Overhang wall", "Sparse infill", "Internal solid infill", "Top surface", "Bottom surface",
                                                       "Ironing", "Bridge", "Internal Bridge", "Gap infill")), "PART_ROLES is out of step with orca_core.roles"
print("interface: ok")
print("pending (need the compiled engine): A5 and A6 on the real paths of a sliced cube; the z of a real path (top of the road?); the mapping of a real mesh")
print("PRINT FABRIC OK")
