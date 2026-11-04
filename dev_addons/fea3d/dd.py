"""Domain decomposition (substructuring) for voxel / hex models.

The stiffness matrix of the free unknowns is cut into slabs along the longest axis.  The unknowns split into
  interior unknowns of each slab (they only touch their own slab and the cut layer next to them), and
  interface unknowns (one layer of nodes on the side of each cut).
Because the interiors of different slabs never touch each other, each slab can be factorised and solved on its own, at the same time
as the others.  What is left is the small interface problem  S x_B = g  with the Schur complement
  S = K_BB - K_BI K_II^-1 K_IB ,   g = b_B - K_BI K_II^-1 b_I
which is solved here by conjugate gradients without ever forming S: every application of S is one back-substitution per slab.
Afterwards each slab recovers its interior unknowns.  The result is the exact finite-element solution (to the CG tolerance).

Public: solve(model, free, rhs, tol, maxit, progress, parts=None) -> (x, iterations, residual, info)
        build(Kff, node_of_dof, ...) / Substructure for tests;  solve_dense_interface(...) for a direct check on small cases.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl

from tasks import tick


def split_slabs(coord, dof_weight, P):
    """Slab number (0..P-1) for each node: equal numbers of unknowns per slab along the coordinate `coord`."""
    order = np.argsort(coord, kind="stable")
    cum = np.cumsum(dof_weight[order])
    part_sorted = np.minimum((cum - 1e-9) * P // cum[-1], P - 1).astype(int)
    part = np.empty(len(coord), int)
    part[order] = part_sorted
    return part


class Substructure:
    """The cut-up system for K x = b on the free dofs (Kff: CSR).  part_of_dof gives the slab of each unknown."""

    def __init__(self, Kff, part_of_dof, workers=None, progress=None):
        t0 = time.time()
        n = Kff.shape[0]
        P = int(part_of_dof.max()) + 1
        Kff = Kff.tocsr()
        # an unknown is an interface unknown if it touches an unknown of a HIGHER slab (one layer on the lower side of each cut)
        nbr_max = np.maximum.reduceat(part_of_dof[Kff.indices], Kff.indptr[:-1])
        is_b = nbr_max > part_of_dof
        self.B = np.nonzero(is_b)[0]
        self.nB = len(self.B)
        self.P, self.n = P, n
        self.I = [np.nonzero((part_of_dof == p) & ~is_b)[0] for p in range(P)]
        self.workers = workers or min(P, os.cpu_count() or 1)
        Kb = Kff[self.B][:, self.B].tocsc()
        self.KBB = Kb
        self.blocks = []
        rows_by_part = [Kff[idx] for idx in self.I]                       # CSR rows of each slab's interior
        for p in range(P):
            R = rows_by_part[p]
            KII = R[:, self.I[p]].tocsc()
            KIB = R[:, self.B].tocsr()
            cols = np.unique(KIB.indices)                                 # the interface unknowns this slab actually touches
            KIBc = KIB[:, cols].tocsc()
            self.blocks.append({"KII": KII, "cols": cols, "KIB": KIBc, "KBI": KIBc.T.tocsr()})
        tick(progress, "Cutting the matrix into slabs", 0.1)
        # factorise all slabs at the same time
        with ThreadPoolExecutor(self.workers) as ex:
            lus = list(ex.map(lambda b: spl.splu(b["KII"]), self.blocks))
        for b, lu in zip(self.blocks, lus):
            b["lu"] = lu
        self.pool = ThreadPoolExecutor(self.workers)
        self.prec = spl.splu(Kb) if self.nB else None
        self.setup_s = time.time() - t0
        self.sizes = [len(i) for i in self.I]

    def _each(self, fn):
        return list(self.pool.map(fn, self.blocks))

    def S_matvec(self, v):
        """S v = K_BB v - sum_p K_BI_p K_II_p^-1 K_IB_p v   (the slabs are done at the same time)."""
        def one(b):
            w = b["KIB"] @ v[b["cols"]]
            return b["KBI"] @ b["lu"].solve(w)
        out = self.KBB @ v
        for cols_b, contrib in zip(self.blocks, self._each(one)):
            out[cols_b["cols"]] -= contrib
        return out

    def solve(self, b, tol=1e-8, maxit=2000, progress=None):
        """x for K x = b (b full length over the free unknowns).  Returns x, interface CG iterations, relative residual of the interface problem."""
        bI = [b[idx] for idx in self.I]
        bB = b[self.B]
        # g = b_B - K_BI K_II^-1 b_I
        def cond(args):
            blk, bi = args
            return blk["KBI"] @ blk["lu"].solve(bi)
        parts = list(self.pool.map(cond, zip(self.blocks, bI)))
        g = bB.copy()
        for blk, c in zip(self.blocks, parts):
            g[blk["cols"]] -= c
        xB = np.zeros(self.nB)
        it, rel = 0, 0.0
        gn = np.linalg.norm(g)
        if self.nB and gn > 0:
            r = g.copy()
            z = self.prec.solve(r)
            p = z.copy()
            rz = r @ z
            for it in range(1, maxit + 1):
                Sp = self.S_matvec(p)
                a = rz / (p @ Sp)
                xB += a * p
                r -= a * Sp
                rel = np.linalg.norm(r) / gn
                tick(progress, f"Interface iteration {it}, residual {rel:.1e}", min(max(np.log10(max(rel, 1e-300)) / np.log10(tol), 0.0), 1.0))
                if rel < tol:
                    break
                z = self.prec.solve(r)
                rz_new = r @ z
                p = z + (rz_new / rz) * p
                rz = rz_new
        # every slab recovers its own interior
        def back(args):
            blk, bi = args
            rhs = bi - blk["KIB"] @ xB[blk["cols"]]
            return blk["lu"].solve(rhs)
        xI = list(self.pool.map(back, zip(self.blocks, bI)))
        x = np.zeros(self.n)
        x[self.B] = xB
        for idx, xi in zip(self.I, xI):
            x[idx] = xi
        return x, it, rel

    def solve_dense_interface(self, b):
        """Same answer with the interface problem formed explicitly and solved directly (only for small interfaces; used as a check)."""
        S = self.KBB.toarray()
        gl = b[self.B].copy()
        for blk, idx in zip(self.blocks, self.I):
            X = blk["lu"].solve(blk["KIB"].toarray())
            S[np.ix_(blk["cols"], blk["cols"])] -= blk["KBI"] @ X
            gl[blk["cols"]] -= blk["KBI"] @ blk["lu"].solve(b[idx])
        xB = np.linalg.solve(S, gl)
        x = np.zeros(self.n)
        x[self.B] = xB
        for blk, idx in zip(self.blocks, self.I):
            x[idx] = blk["lu"].solve(b[idx] - blk["KIB"] @ xB[blk["cols"]])
        return x

    def close(self):
        self.pool.shutdown(wait=False)


def partition_of(model, free, P):
    """Slab of every free dof for a voxel model (cut along the longest extent of the solid)."""
    import voxel as VX
    ijk = model.node_ijk.astype(float)
    axis = int(np.argmax(ijk.max(0) - ijk.min(0)))
    fi = np.nonzero(free)[0]
    node_dofs = np.bincount(fi // 3, minlength=model.nn).astype(float)
    node_part = split_slabs(ijk[:, axis], np.maximum(node_dofs, 1e-9), P)
    return node_part[fi // 3], fi, axis


def solve(model, free, rhs, tol=1e-8, maxit=2000, progress=None, parts=None, workers=None):
    import voxel as VX
    P = int(parts or max(2, min(8, os.cpu_count() or 2)))
    K = VX.assemble(model, None)
    part_of_dof, fi, axis = partition_of(model, free, P)
    tick(progress, "Selecting the free equations", 0.05)
    Kff = K[fi][:, fi].tocsr()
    del K
    sub = Substructure(Kff, part_of_dof, workers, progress)
    xf, it, rel = sub.solve(rhs[fi], max(tol, 1e-12), maxit, progress)
    sub.close()
    x = np.zeros(model.ndof)
    x[fi] = xf
    res = np.linalg.norm(Kff @ xf - rhs[fi]) / max(np.linalg.norm(rhs[fi]), 1e-300)
    info = {"name": f"domain decomposition ({P} slabs along {'xyz'[axis]}, {sub.nB} interface unknowns, {sub.workers} workers)",
            "interface": sub.nB, "sizes": sub.sizes, "setup_s": sub.setup_s, "axis": axis, "parts": P}
    return x, it, float(res), info
