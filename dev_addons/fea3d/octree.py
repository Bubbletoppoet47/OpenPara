"""Adaptive voxels: small bricks near the surface and in thin struts, big bricks deep inside thick material.

Leaves of an octree on the fine voxel grid (a brick of side 2^k fine voxels, k = 0..levels).  Rules:
  * a brick of side s (in fine voxels) is allowed only where it is completely solid and every voxel in it is at least grade x s
    voxels away from the outside (so thin struts and the skin stay fine, thick cores get big bricks);
  * neighbouring bricks (faces, edges and corners) differ by at most one level (2:1), so a node of a small brick lies at the
    middle of an edge or face of a big one;
  * those "hanging" nodes are tied to the corners of the big brick (displacement interpolated), which keeps the model continuous.
The tied nodes are not unknowns: the model works on the remaining nodes ("masters"), P maps their displacements to every node.
It offers what voxel.Model offers to fem3d.solve (nn, ndof, K, diag, matvec, node_xyz, fields), plus full(u), grid(u), centres()."""
import numpy as np
from scipy import ndimage, sparse
from scipy.sparse import csgraph

import voxel as VX
from tasks import sub, tick

EDGES = np.array([(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)])
FACES = np.array([(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])


def block_view(a, s):
    n = a.shape
    return a.reshape(n[0] // s, s, n[1] // s, s, n[2] // s, s)


def levels_for(occ, levels, grade):
    """Level (0..levels) of the brick each solid voxel belongs to; -1 for empty.  The grid must be a multiple of 2^levels."""
    pad = np.pad(occ, 1)
    dist = ndimage.distance_transform_edt(pad)[1:-1, 1:-1, 1:-1].astype(np.float32)
    lev = np.where(occ, 0, -1).astype(np.int8)
    for k in range(1, levels + 1):
        s = 2 ** k
        full = block_view(occ, s).all(axis=(1, 3, 5), keepdims=True)
        mind = block_view(dist, s).min(axis=(1, 3, 5), keepdims=True)
        ok = full & (mind >= grade * s)
        l6 = block_view(lev, s)
        lev = np.where(np.broadcast_to(ok, l6.shape), np.int8(k), l6).reshape(occ.shape)
    return lev


def balance(lev, levels):
    """Make neighbouring bricks differ by at most one level, keeping every brick a whole aligned block."""
    for _ in range(3 * levels + 3):
        big = np.where(lev >= 0, lev, 127).astype(np.int8)
        mn = ndimage.minimum_filter(big, size=3, mode="constant", cval=127)
        cap = np.where(lev >= 0, np.minimum(lev, mn + 1), -1).astype(np.int8)
        for k in range(levels, 0, -1):
            s = 2 ** k
            c6 = block_view(cap, s)
            bm = c6.min(axis=(1, 3, 5), keepdims=True)
            cap = np.where(bm < k, np.minimum(c6, np.int8(k - 1)), c6).reshape(lev.shape).astype(np.int8)
        if np.array_equal(cap, lev):
            break
        lev = cap
    return lev


class AdaptiveModel:
    def __init__(self, occ, h, origin=(0, 0, 0), levels=2, grade=1.0, progress=None):
        """The bricks and ties only (enough to pick nodes and draw); call assemble(E, nu) before solving."""
        self.h = float(h)
        self.origin = np.asarray(origin, float)
        self.levels = int(levels)
        s0 = 2 ** self.levels
        shape = np.array(occ.shape)
        padded = ((shape + s0 - 1) // s0) * s0
        o = np.zeros(tuple(padded), bool)
        o[:shape[0], :shape[1], :shape[2]] = occ
        tick(progress, "Choosing brick sizes", 0.0)
        lev = balance(levels_for(o, self.levels, grade), self.levels)
        tick(progress, "Collecting bricks", 0.2)
        origins, sizes = [], []
        for k in range(self.levels + 1):
            s = 2 ** k
            l6 = block_view(lev, s)
            leaf = (l6.min(axis=(1, 3, 5)) == k) & (l6.max(axis=(1, 3, 5)) == k)
            idx = np.argwhere(leaf) * s
            origins.append(idx)
            sizes.append(np.full(len(idx), s))
        self.count_by_level = [len(x) for x in origins]
        self.ijk0 = np.vstack(origins)                                  # brick origin, in fine voxels
        self.size = np.concatenate(sizes)                               # brick side, in fine voxels
        self.ne = len(self.ijk0)
        if self.ne == 0:
            raise ValueError("There is no solid in the grid.")
        self.uniform_elements = int(occ.sum())
        gshape = padded + 1
        corner = self.ijk0[:, None, :] + self.size[:, None, None] * VX.CORNERS[None, :, :]       # (ne, 8, 3)
        key = np.ravel_multi_index(corner.reshape(-1, 3).T, gshape)
        used, inv = np.unique(key, return_inverse=True)
        self.nn_all = len(used)
        self.node_ijk = np.array(np.unravel_index(used, gshape)).T
        self.conn = inv.reshape(self.ne, 8).astype(np.int32)
        tick(progress, "Tying the hanging nodes", 0.4)
        self._hanging(used, gshape, corner)
        self.nn = int(self.master.sum())
        self.ndof = 3 * self.nn
        tick(progress, "Done", 1.0)

    def assemble(self, E, nu, incompatible=True, progress=None):
        self.E, self.nu = float(E), float(nu)
        self._assemble(incompatible, progress)
        self.diag = self.K.diagonal().copy()
        return self

    def _hanging(self, used, gshape, corner):
        nn = self.nn_all
        rows, cols, w = [], [], []
        seen = np.zeros(nn, bool)
        for sl_edge, pairs in ((True, EDGES), (False, FACES)):
            big = np.nonzero(self.size >= 2)[0]
            if len(big) == 0:
                continue
            c = corner[big]
            for grp in pairs:
                pts = c[:, grp, :].sum(axis=1) // len(grp)
                ok_even = ((c[:, grp, :].sum(axis=1) % len(grp)) == 0).all(axis=1)
                k = np.ravel_multi_index(pts[ok_even].T, gshape)
                pos = np.searchsorted(used, k)
                pos[pos >= len(used)] = len(used) - 1
                hit = used[pos] == k
                el = big[ok_even][hit]
                node = pos[hit]
                for e_, n_ in zip(el, node):
                    if seen[n_]:
                        continue
                    seen[n_] = True
                    par = self.conn[e_, list(grp)]
                    for p in par:
                        rows.append(n_)
                        cols.append(p)
                        w.append(1.0 / len(grp))
        self.hanging = seen
        self.master = ~seen
        C = sparse.csr_matrix((w, (rows, cols)), shape=(nn, nn))
        mi = np.cumsum(self.master) - 1
        Sel = sparse.csr_matrix((np.ones(int(self.master.sum())), (np.nonzero(self.master)[0], np.arange(int(self.master.sum())))), shape=(nn, int(self.master.sum())))
        P = Sel.copy()
        for _ in range(12):
            Pn = (Sel + C @ P).tocsr()
            if abs(Pn - P).sum() < 1e-12:
                break
            P = Pn
        self.P = P.tocsr()
        self.C = C
        self.P3 = sparse.kron(self.P, sparse.identity(3), format="csr")
        self.master_index = np.nonzero(self.master)[0]

    def _assemble(self, incompatible, progress):
        tick(progress, "Building the stiffness matrix", 0.0)
        self.Ke_by_size = {}
        self.B0_by_size = {}
        self.D = VX.material_matrix(self.E, self.nu)
        for s in np.unique(self.size):
            Ke, B0, D = VX.element(self.E, self.nu, self.h * s, incompatible)
            self.Ke_by_size[int(s)], self.B0_by_size[int(s)] = Ke, B0
        self.edof = (3 * self.conn[:, :, None] + np.arange(3)[None, None, :]).reshape(self.ne, 24).astype(np.int32)
        n3 = 3 * self.nn_all
        K = None
        chunk = 25000
        for s, Ke in self.Ke_by_size.items():
            idx = np.nonzero(self.size == s)[0]
            Kf = Ke.ravel()
            for a in range(0, len(idx), chunk):
                ed = self.edof[idx[a:a + chunk]]
                r = np.repeat(ed, 24, axis=1).ravel()
                c = np.tile(ed, (1, 24)).ravel()
                Kc = sparse.csr_matrix((np.tile(Kf, len(ed)), (r, c)), shape=(n3, n3))
                K = Kc if K is None else K + Kc
        tick(progress, "Applying the ties", 0.9)
        self.K_full = K
        self.K = (self.P3.T @ K @ self.P3).tocsr()
        self.K = 0.5 * (self.K + self.K.T)

    # ---- what fem3d.solve and voxel.solve_free need
    def matvec(self, u):
        return self.K @ u

    def node_xyz(self):
        return self.origin + self.node_ijk[self.master_index] * self.h

    def node_xyz_all(self):
        return self.origin + self.node_ijk * self.h

    def full(self, u):
        return self.P3 @ u

    def components(self):
        ne, k = self.conn.shape
        rows = np.repeat(np.arange(ne), k)
        cols = ne + self.conn.ravel()
        n = ne + self.nn_all
        C = self.C.tocoo()
        rows = np.concatenate([rows, ne + C.row])
        cols = np.concatenate([cols, ne + C.col])
        g = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
        _nc, lab = csgraph.connected_components(g, directed=False)
        return lab[ne:][self.master_index]

    def element_size(self):
        return self.size * self.h

    def centres(self):
        return self.origin + (self.ijk0 + 0.5 * self.size[:, None]) * self.h

    def fields(self, u):
        uf = self.full(u)
        eps = np.zeros((self.ne, 6))
        for s, B0 in self.B0_by_size.items():
            idx = np.nonzero(self.size == s)[0]
            eps[idx] = uf[self.edof[idx]] @ B0.T
        sig = eps @ self.D.T
        return VX.stress_fields(eps, sig, self.element_size())

    def grid(self, u=None, scale=0.0):
        import pyvista as pv
        pts = self.node_xyz_all()
        if u is not None and scale:
            pts = pts + scale * self.full(u).reshape(-1, 3)
        cells = np.hstack([np.full((self.ne, 1), 8, np.int64), self.conn.astype(np.int64)]).ravel()
        g = pv.UnstructuredGrid(cells, np.full(self.ne, 12, np.uint8), pts)
        g.cell_data["brick size"] = self.element_size()
        return g

    def summary(self):
        by = ", ".join(f"{n:,} of {self.h * 2 ** k:.4g}" for k, n in enumerate(self.count_by_level) if n)
        return f"{self.ne:,} bricks ({by}) instead of {self.uniform_elements:,}; {int(self.hanging.sum()):,} tied nodes"
