"""
print_fabric.py - from toolpaths to the stiffness of every element of a 3D FEA mesh (PA-3, plan chapter 10.4).

A part that came off a 3D printer is plastic laid in roads.  This file takes the printed paths (what the slicer decided to extrude: the polylines
with their width, height and role) and works out, for every element of an analysis mesh, how much plastic is in it and in which directions it
runs, and from that the element's stiffness matrix (a (6, 6) matrix in the part's axes, in the form the solver takes: g["D21"]).

Conventions (they are the ones of the slicer module, plan 5.3):
  * the points of a path are in the PLATE's coordinates, in mm; z is the TOP of the road (Orca's print_z), the road fills z - height .. z;
  * a part's mesh is in the part's own axes; `transform` is the 4x4 matrix that puts the part where it stands on the plate (the object's transform);
  * the road frame: axis 1 along the road, axis 2 across it in the layer, axis 3 between the layers (global z).

The model (M1 of the plan; "the exact rule is the thing to be calibrated", so every number that is a model choice is a parameter):
  * every short piece of a path deposits its plastic volume V and its direction into a small cell (the FABRIC);
  * around each element, over a smooth neighbourhood (a Gaussian), the plastic volume is Vp and the mesh volume is Vm.  phi = Vp / Vm is the plastic fraction;
  * the roads there are averaged by volume (the Voigt, rule-of-mixtures, average): the stiffness of the roads along direction theta is the
    stiffness of the printed material turned by theta about z, and the average of those over the volume is  Dbar;
  * the stiffness of the element is  phi**p * Dbar,  with p = 1 the rule of mixtures (an upper bound for sparse infill) and p > 1 for a lattice that
    bends.  p is not known until the coupon tests (PA-5); it is a parameter, not a result.

Why a harmonic basis: turning a stiffness matrix by theta about z gives entries that are sums of 1, cos 2 theta, sin 2 theta, cos 4 theta and sin 4 theta
(the rotation is quadratic in cos and sin, the matrix has it twice).  So the volume-weighted average of the matrices of many roads needs only the five sums
V, sum V cos2t, sum V sin2t, sum V cos4t, sum V sin4t of the cell, and the average is exact for any mixture of directions.

What it does not do: steep (z-tilted) roads count as plastic but have no in-plane direction; the smoothing distance must be at least an element or two, and a
few infill lines, wide; supports, skirt, brim and the prime tower are left out.
"""
import numpy as np

import solid_fem as fem

# the roles of Orca (orca_core.roles.ROLES) that are part of the part: walls, infill, top and bottom, ironing, bridges, gap fill.
# (numbers, so that this file needs nothing from the slicer module; test_print_fabric.py checks them against it)
PART_ROLES = tuple(range(1, 12))
_K = 11                      # V, V*dxx, V*dyy, V*dzz, V*dxy, V*dyz, V*dxz, V*cos2t, V*sin2t, V*cos4t, V*sin4t
_CHUNK = 250_000             # segments handled at a time


class FabricError(Exception):
    """A sentence for the person."""


# ======================================================================================================== the road stiffness and its harmonics
def road_matrix(c):
    """(6, 6) stiffness of the printed material in the road frame from constants {"E1", "E2", "E3", "G12", "G23", "G13", "nu12", "nu23", "nu13"} (MPa)."""
    try:
        return fem.orthotropic_matrix(*(float(c[k]) for k in ("E1", "E2", "E3", "G12", "G23", "G13", "nu12", "nu23", "nu13")))
    except (KeyError, TypeError, ValueError) as ex:
        raise FabricError(f"The printed material is incomplete or has a value that is not a number ({ex}).")


def _Rz(t):
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def D_at(D0, theta):
    """The stiffness matrix of roads that run at the angle theta (rad, from x towards y) in the plate: axis 1 = (cos t, sin t, 0), 2 = (-sin t, cos t, 0), 3 = z."""
    return fem.rotate_D(D0, _Rz(theta))


def harmonic_basis(D0):
    """(5, 6, 6): C such that D_at(D0, t) = C[0] + C[1] cos 2t + C[2] sin 2t + C[3] cos 4t + C[4] sin 4t, exactly (fitted at five angles; the test checks other angles)."""
    th = np.arange(5) * np.pi / 5
    B = np.stack([np.ones(5), np.cos(2 * th), np.sin(2 * th), np.cos(4 * th), np.sin(4 * th)], axis=1)
    S = np.stack([D_at(D0, t) for t in th]).reshape(5, 36)
    return np.linalg.solve(B, S).reshape(5, 6, 6)


# ======================================================================================================== the fabric: plastic and direction in small cells
class Fabric:
    """Plastic volume and direction in a sparse grid of small cells.

    origin (3,), cell (3,), shape (3,)   the grid: cell (i, j, k) spans origin + (i, j, k) * cell, and is stored at the flat number (i * ny + j) * nz + k
    ids (n,)                              the numbers of the cells that hold plastic, ascending
    acc (n, 11) float32                   per cell: V (mm3); V d (x) d as xx yy zz xy yz xz; V cos2t, V sin2t, V cos4t, V sin4t  (t: the road's angle in the plate)"""

    def __init__(self, origin, cell, shape, ids, acc):
        self.origin = np.asarray(origin, float)
        self.cell = np.asarray(cell, float)
        self.shape = tuple(int(s) for s in shape)
        self.ids = np.asarray(ids, np.int64)
        self.acc = np.asarray(acc, np.float32).reshape(-1, _K)

    # ---- building
    @classmethod
    def from_paths(cls, paths, cell_xy=0.5, cell_z=None, roles=PART_ROLES):
        """paths: anything with points (N, 3), start (M + 1,), role, height and mm3_per_mm (M,) - an orca_core.Paths does.  Only the given roles are used."""
        pts = np.asarray(paths.points, np.float64).reshape(-1, 3)
        start = np.asarray(paths.start, np.int64)
        role, hgt, flow = (np.asarray(getattr(paths, k), np.float64) for k in ("role", "height", "mm3_per_mm"))
        m = len(start) - 1
        if m <= 0 or len(pts) < 2:
            raise FabricError("There are no printed paths to take the plastic from.")
        keep = np.isin(role, np.asarray(roles, float))
        if not keep.any():
            raise FabricError("None of the printed paths belongs to the part (walls, infill, top and bottom): only supports, skirt or prime tower?")
        pid = np.repeat(np.arange(m), np.diff(start))                 # path of every point
        seg = np.ones(len(pts) - 1, bool)                              # a segment joins two points of the same path
        seg[start[1:-1] - 1] = False
        seg &= keep[pid[:-1]]
        s0 = np.flatnonzero(seg)
        if len(s0) == 0:
            raise FabricError("The printed paths have no line in them (each path is a single point).")
        cz = float(cell_z) if cell_z else float(np.median(hgt[keep]))
        cell = np.array([cell_xy, cell_xy, cz], float)
        zc_lo = float((pts[s0, 2] - hgt[pid[s0]]).min())                # the bottom of the lowest road: layer k then fills cell k
        mins = np.minimum(pts[s0].min(axis=0), pts[s0 + 1].min(axis=0))
        maxs = np.maximum(pts[s0].max(axis=0), pts[s0 + 1].max(axis=0))
        origin = np.array([mins[0] - cell_xy, mins[1] - cell_xy, zc_lo])
        shape = np.ceil((np.array([maxs[0], maxs[1], maxs[2]]) - origin) / cell).astype(np.int64) + 2
        if int(np.prod(shape.astype(float))) > 2 ** 62:
            raise FabricError("The part is too large for the cell size.")
        ds = 0.5 * cell_xy
        ids_parts, acc_parts = [], []
        for a in range(0, len(s0), _CHUNK):
            sidx = s0[a:a + _CHUNK]
            p0, p1, pp = pts[sidx], pts[sidx + 1], pid[sidx]
            vec = p1 - p0
            L = np.linalg.norm(vec, axis=1)
            good = L > 1e-9
            p0, p1, pp, vec, L = p0[good], p1[good], pp[good], vec[good], L[good]
            if len(L) == 0:
                continue
            n = np.maximum(1, np.ceil(L / ds)).astype(np.int64)
            rep = np.repeat(np.arange(len(L)), n)
            first = np.cumsum(n) - n
            k = np.arange(len(rep)) - np.repeat(first, n)
            frac = (k + 0.5) / n[rep]
            pos = p0[rep] + vec[rep] * frac[:, None]
            d = vec[rep] / L[rep][:, None]
            vol = (L / n)[rep] * flow[pp][rep]
            pos[:, 2] -= 0.5 * hgt[pp][rep]                            # z is the top of the road: its centre is half a height lower
            cidx = np.floor((pos - origin) / cell).astype(np.int64)
            cidx = np.clip(cidx, 0, shape - 1)
            flat = (cidx[:, 0] * shape[1] + cidx[:, 1]) * shape[2] + cidx[:, 2]
            theta = np.arctan2(d[:, 1], d[:, 0])
            flat_ok = np.abs(d[:, 2]) < 0.5                            # a steep piece has no direction in the plate: plastic, but no harmonic
            hw = np.where(flat_ok, vol, 0.0)
            W = np.stack([vol, vol * d[:, 0] ** 2, vol * d[:, 1] ** 2, vol * d[:, 2] ** 2, vol * d[:, 0] * d[:, 1], vol * d[:, 1] * d[:, 2], vol * d[:, 0] * d[:, 2],
                          hw * np.cos(2 * theta), hw * np.sin(2 * theta), hw * np.cos(4 * theta), hw * np.sin(4 * theta)], axis=1)
            u, inv = np.unique(flat, return_inverse=True)
            acc = np.stack([np.bincount(inv, weights=W[:, j], minlength=len(u)) for j in range(_K)], axis=1)
            ids_parts.append(u)
            acc_parts.append(acc)
        if not ids_parts:
            raise FabricError("The printed paths have no length.")
        allid = np.concatenate(ids_parts)
        allacc = np.concatenate(acc_parts)
        u, inv = np.unique(allid, return_inverse=True)
        acc = np.stack([np.bincount(inv, weights=allacc[:, j], minlength=len(u)) for j in range(_K)], axis=1)
        return cls(origin, cell, shape, u, acc.astype(np.float32))

    # ---- reading
    def centres(self):
        """(n, 3) the centre of every stored cell."""
        nz, ny = self.shape[2], self.shape[1]
        k = self.ids % nz
        j = (self.ids // nz) % ny
        i = self.ids // (nz * ny)
        return self.origin + (np.stack([i, j, k], axis=1) + 0.5) * self.cell

    def total_volume(self):
        return float(self.acc[:, 0].astype(np.float64).sum())

    def bbox(self):
        c = self.centres()
        return c.min(axis=0) - 0.5 * self.cell, c.max(axis=0) + 0.5 * self.cell

    def coarse(self, origin, cell, shape):
        """The sums of the cells that fall in each cell of a coarser (or any) grid: dict(vol (n_cells,), tens (n_cells, 6), harm (n_cells, 4)) with the flat cell number
        (i * ny + j) * nz + k, for the grid  origin, cell, shape.  Cells of the fabric outside that grid are put at its edge."""
        origin, cell = np.asarray(origin, float), np.asarray(cell, float)
        shape = np.asarray(shape, np.int64)
        idx = np.clip(np.floor((self.centres() - origin) / cell).astype(np.int64), 0, shape - 1)
        flat = (idx[:, 0] * shape[1] + idx[:, 1]) * shape[2] + idx[:, 2]
        nc = int(np.prod(shape))
        out = np.stack([np.bincount(flat, weights=self.acc[:, j].astype(np.float64), minlength=nc) for j in range(_K)], axis=1)
        return {"vol": out[:, 0], "tens": out[:, 1:7], "harm": out[:, 7:11]}

    def save(self, path):
        np.savez_compressed(path, origin=self.origin, cell=self.cell, shape=np.asarray(self.shape), ids=self.ids, acc=self.acc)

    @classmethod
    def load(cls, path):
        with np.load(path) as z:
            return cls(z["origin"], z["cell"], z["shape"], z["ids"], z["acc"])


def orientation_tensor(tens, vol):
    """A = sum(V d (x) d) / sum(V): (n, 3, 3) from the sums of cells (tens (n, 6) as xx yy zz xy yz xz, vol (n,)); zero where there is no plastic.
    Its eigenvalues add up to 1; one near 1 means the roads there run one way, equal ones in the plane mean a crossed pattern."""
    v = np.where(vol > 0, vol, 1.0)
    t = tens / v[:, None]
    A = np.zeros((len(vol), 3, 3))
    A[:, 0, 0], A[:, 1, 1], A[:, 2, 2] = t[:, 0], t[:, 1], t[:, 2]
    A[:, 0, 1] = A[:, 1, 0] = t[:, 3]
    A[:, 1, 2] = A[:, 2, 1] = t[:, 4]
    A[:, 0, 2] = A[:, 2, 0] = t[:, 5]
    A[vol <= 0] = 0.0
    return A


# ======================================================================================================== from the fabric to the elements
def group_centroids_volumes(nodes, g):
    """(centroids (n, 3), volumes (n,)) of the elements of a mesh group {"kind": "tet" | "hex" | "pyr", "conn": ...}: by the corner nodes (the first 4, 8 or 5 columns)."""
    kind, conn = g["kind"], np.asarray(g["conn"])
    nc = {"tet": 4, "hex": 8, "pyr": 5}[kind]
    P = np.asarray(nodes, float)[conn[:, :nc]]
    cen = P.mean(axis=1)

    def tv(a, b, c, d):
        return np.abs(np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a)) / 6.0
    if kind == "tet":
        vol = tv(P[:, 0], P[:, 1], P[:, 2], P[:, 3])
    elif kind == "pyr":
        vol = tv(P[:, 0], P[:, 1], P[:, 2], P[:, 4]) + tv(P[:, 0], P[:, 2], P[:, 3], P[:, 4])
    else:                                                               # a brick: six tetrahedra round the diagonal 0 - 6
        vol = sum(tv(P[:, 0], P[:, a], P[:, b], P[:, 6]) for a, b in ((1, 2), (2, 3), (3, 7), (7, 4), (4, 5))) + tv(P[:, 0], P[:, 5], P[:, 1], P[:, 6])
    return cen, vol


def element_stiffness(fabric, centroids, volumes, constants, sigma=None, sigma_z=None, phi_power=1.0, transform=None, phi_min=1e-3, samples=None):
    """The stiffness matrix of every element of a mesh from the printed paths.

    centroids (n, 3), volumes (n,)   of the elements, in the part's axes; transform: the 4x4 matrix part -> plate (None: the part is in the plate's axes)
    samples      (n, k, 3) optional: k points inside every element (equal shares of its volume) that say where the element's volume is; without it the centroid does
    constants    {"E1", "E2", "E3", "G12", "G23", "G13", "nu12", "nu23", "nu13"} of fully dense printed material, in the road frame
    sigma, sigma_z   how far (mm) the plastic and its directions are averaged: a Gaussian of this standard deviation along x and y, and along z.  It should be at least
                 an element edge or two and a few infill lines wide; default  sigma = max(1 mm, 1.5 element edges),  sigma_z = max(sigma, two layers), so that layers that
                 alternate their directions are both seen.
    phi_power    p: the element is  phi**p * Dbar  (1 = rule of mixtures; see the top of this file)
    phi_min      the least plastic fraction used: an element that no road touches gets this fraction of the crossed in-plane material (never a zero matrix)

    The plastic and the mesh are smoothed in the same way and divided (a normalised convolution), so near the surface of the part the air outside does not thin the plastic.

    -> dict: D21 (n, 21) float32 (what the solver takes), phi (n,), A (n, 3, 3) orientation tensor of the plastic around the element, empty: the number of elements with no
    plastic around them, clipped: the number whose phi came out above 1 (the mesh is smaller than the print there, or roads overlap) and was set to 1."""
    from scipy import ndimage
    cen = np.asarray(centroids, float).reshape(-1, 3)
    vol = np.asarray(volumes, float).reshape(-1)
    if len(cen) != len(vol) or len(cen) == 0:
        raise FabricError("The mesh has no elements to give a stiffness to.")
    T = None if transform is None else np.asarray(transform, float)

    def to_plate(x):
        return x if T is None else x @ T[:3, :3].T + T[:3, 3]
    cen = to_plate(cen)
    pts = cen[:, None, :] if samples is None else to_plate(np.asarray(samples, float))
    if pts.ndim != 3 or len(pts) != len(cen):
        raise FabricError("samples must hold the same number of elements as the centroids: an array (n, k, 3).")
    edge = float(np.median(vol)) ** (1.0 / 3.0)
    sg = float(sigma) if sigma else max(1.0, 1.5 * edge)
    sgz = float(sigma_z) if sigma_z else max(sg, 2.0 * float(fabric.cell[2]))
    if sg <= 0 or sgz <= 0:
        raise FabricError("The smoothing distance must be greater than zero.")
    r = np.array([sg / 2, sg / 2, sgz / 2])                                  # the cells of the smoothing grid: two to a standard deviation
    pad = 3.0 * np.array([sg, sg, sgz]) + r
    flo, fhi = fabric.bbox()
    lo = np.minimum(flo, pts.reshape(-1, 3).min(axis=0)) - pad
    hi = np.maximum(fhi, pts.reshape(-1, 3).max(axis=0)) + pad
    shape = np.ceil((hi - lo) / r).astype(np.int64) + 1
    ncell = float(np.prod(shape.astype(float)))
    if ncell > 8e6:
        raise FabricError("The smoothing distance (%.3g mm) is too small for a part of this size: it would need %d cells. Use a larger smoothing distance."
                          % (sg, int(ncell)))
    nc = int(ncell)
    co = fabric.coarse(lo, r, shape)
    k = pts.shape[1]
    pi = np.clip(np.floor((pts.reshape(-1, 3) - lo) / r).astype(np.int64), 0, shape - 1)
    pflat = (pi[:, 0] * shape[1] + pi[:, 1]) * shape[2] + pi[:, 2]
    Mm = np.bincount(pflat, weights=np.repeat(vol / k, k), minlength=nc)    # mesh volume in each cell

    def smooth(a):
        return ndimage.gaussian_filter(a.reshape(shape), sigma=[2.0, 2.0, 2.0], mode="constant", truncate=3.0)
    Ms = smooth(Mm)
    Vs = smooth(co["vol"])
    Hs = [smooth(co["harm"][:, j]) for j in range(4)]
    Ts = [smooth(co["tens"][:, j]) for j in range(6)]
    xyz = ((cen - lo) / r - 0.5).T                                           # the centre of cell i is at i, in cell units

    def at(f):
        return ndimage.map_coordinates(f, xyz, order=1, mode="nearest")
    ms, vs = at(Ms), at(Vs)
    hs = np.stack([at(h) for h in Hs], axis=1)
    ts = np.stack([at(t) for t in Ts], axis=1)
    if np.any(ms <= 0):
        raise FabricError("Some elements are outside the part's printed region by more than the smoothing distance; check the transform that puts the part on the plate.")
    phi_raw = vs / ms
    has = vs > 1e-12 * np.maximum(ms, 1e-300)
    w = np.where(has[:, None], hs / np.where(has, vs, 1.0)[:, None], 0.0)    # volume-weighted mean of cos2t ...: 0 with no roads (= crossed in the plane)
    w = np.clip(w, -1.0, 1.0)
    D0 = road_matrix(constants)
    C = harmonic_basis(D0)
    Dbar = C[0][None] + np.einsum("nk,kij->nij", w, C[1:])
    phi = np.clip(phi_raw, phi_min, 1.0)
    D = (phi ** float(phi_power))[:, None, None] * Dbar
    A = orientation_tensor(ts, np.where(has, vs, 0.0))
    return {"D21": fem.pack_D(D), "phi": phi, "A": A, "empty": int((~has).sum()), "clipped": int((phi_raw > 1.0).sum())}


def group_samples(nodes, g):
    """(n, k, 3): k points inside every element of a mesh group, each halfway from the element's centroid to one of its corners (k = 4 for a tetrahedron, 8 for a brick, 5 for a
    pyramid).  Together with the volumes they say where the element's volume is, much better than the centroid alone."""
    kind, conn = g["kind"], np.asarray(g["conn"])
    nc = {"tet": 4, "hex": 8, "pyr": 5}[kind]
    P = np.asarray(nodes, float)[conn[:, :nc]]
    return P.mean(axis=1, keepdims=True) + 0.5 * (P - P.mean(axis=1, keepdims=True))
