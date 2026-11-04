"""Parallel geometric multigrid for voxel models (Numba), used as the preconditioner of conjugate gradients.

Nothing is assembled: the stiffness operator is applied element by element straight from the voxel grid, in eight colours so that
the elements handled at the same moment never share a node (no locks, so all cores work).  Coarse levels are the same grid with
cubes of twice the size; a coarse cube is as stiff as the share of solid in it (that is what lets it follow thin, complicated shapes).
The answer is the same finite-element answer as the other solvers, to the solver tolerance.

Public: solve(model, free, rhs, tol, maxit, progress) -> (x, iterations, residual)   (x in the model's own dof order)
"""
import math
import time

import numpy as np
from numba import get_num_threads, njit, prange, set_num_threads

from tasks import tick

OX = np.array([0, 1, 1, 0, 0, 1, 1, 0], np.int64)
OY = np.array([0, 0, 1, 1, 0, 0, 1, 1], np.int64)
OZ = np.array([0, 0, 0, 0, 1, 1, 1, 1], np.int64)
FLOOR = 1e-6                                   # a coarse cube is never exactly empty (keeps the coarse matrices invertible)


def threads(n=None):
    """Number of threads the kernels use (default: all logical cores)."""
    if n:
        set_num_threads(int(n))
    return get_num_threads()


@njit(parallel=True, fastmath=True, cache=True)
def apply_k(u, y, w, Ke, ox, oy, oz):
    """y = K u  (y is zeroed first).  u, y: (nx+1, ny+1, nz+1, 3); w: (nx, ny, nz) stiffness weights."""
    nx, ny, nz = w.shape
    y[:] = 0.0
    for col in range(8):
        ci, cj, ck = col & 1, (col >> 1) & 1, (col >> 2) & 1
        ni = (nx - ci + 1) // 2
        for a in prange(ni):
            i = ci + 2 * a
            ue = np.empty(24)
            fe = np.empty(24)
            for j in range(cj, ny, 2):
                for k in range(ck, nz, 2):
                    wt = w[i, j, k]
                    if wt == 0.0:
                        continue
                    for c in range(8):
                        for d in range(3):
                            ue[3 * c + d] = u[i + ox[c], j + oy[c], k + oz[c], d]
                    for r in range(24):
                        s = 0.0
                        for q in range(24):
                            s += Ke[r, q] * ue[q]
                        fe[r] = s * wt
                    for c in range(8):
                        for d in range(3):
                            y[i + ox[c], j + oy[c], k + oz[c], d] += fe[3 * c + d]


@njit(parallel=True, fastmath=True, cache=True)
def diag_k(w, Ke, ox, oy, oz, out):
    nx, ny, nz = w.shape
    out[:] = 0.0
    for col in range(8):
        ci, cj, ck = col & 1, (col >> 1) & 1, (col >> 2) & 1
        ni = (nx - ci + 1) // 2
        for a in prange(ni):
            i = ci + 2 * a
            for j in range(cj, ny, 2):
                for k in range(ck, nz, 2):
                    wt = w[i, j, k]
                    if wt == 0.0:
                        continue
                    for c in range(8):
                        for d in range(3):
                            out[i + ox[c], j + oy[c], k + oz[c], d] += wt * Ke[3 * c + d, 3 * c + d]


@njit(parallel=True, fastmath=True, cache=True)
def prolong(ec, out):
    """Trilinear interpolation of a coarse-grid field to the fine grid (out is overwritten)."""
    NI, NJ, NK = out.shape[0], out.shape[1], out.shape[2]
    for I in prange(NI):
        i0 = I // 2
        i1 = i0 + (I & 1)
        for J in range(NJ):
            j0 = J // 2
            j1 = j0 + (J & 1)
            for K in range(NK):
                k0 = K // 2
                k1 = k0 + (K & 1)
                for d in range(3):
                    s = 0.0
                    for ii in range(i0, i1 + 1):
                        for jj in range(j0, j1 + 1):
                            for kk in range(k0, k1 + 1):
                                s += ec[ii, jj, kk, d]
                    out[I, J, K, d] = s / (((i1 - i0) + 1) * ((j1 - j0) + 1) * ((k1 - k0) + 1))


@njit(parallel=True, fastmath=True, cache=True)
def restrict(rf, out):
    """Transpose of `prolong`: each coarse node gathers its 27 fine neighbours (weights 1, 1/2, 1/4, 1/8)."""
    NI, NJ, NK = out.shape[0], out.shape[1], out.shape[2]
    FI, FJ, FK = rf.shape[0], rf.shape[1], rf.shape[2]
    for C in prange(NI):
        for D_ in range(NJ):
            for E in range(NK):
                for d in range(3):
                    s = 0.0
                    for a in range(-1, 2):
                        i = 2 * C + a
                        if i < 0 or i >= FI:
                            continue
                        wa = 1.0 if a == 0 else 0.5
                        for b in range(-1, 2):
                            j = 2 * D_ + b
                            if j < 0 or j >= FJ:
                                continue
                            wb = 1.0 if b == 0 else 0.5
                            for c in range(-1, 2):
                                k = 2 * E + c
                                if k < 0 or k >= FK:
                                    continue
                                wc = 1.0 if c == 0 else 0.5
                                s += wa * wb * wc * rf[i, j, k, d]
                    out[C, D_, E, d] = s


@njit(parallel=True, fastmath=True, cache=True)
def coarse_weights(w, out):
    nx, ny, nz = out.shape
    for i in prange(nx):
        for j in range(ny):
            for k in range(nz):
                s = 0.0
                for a in range(2):
                    for b in range(2):
                        for c in range(2):
                            s += w[2 * i + a, 2 * j + b, 2 * k + c]
                out[i, j, k] = s / 8.0


@njit(parallel=True, fastmath=True, cache=True)
def coarse_free(f, used, out, used_out):
    """Constraints on the next coarser grid.  A coarse node sits on a fine node: if that fine node is a real node of the model it is
    fixed exactly when the fine one is (so a pushed face stays a pushed face); if it is empty space the coarse node is free when
    any fine node around it (27 of them) is free.  used_out marks coarse nodes that have any real fine node around them."""
    NI, NJ, NK = out.shape[0], out.shape[1], out.shape[2]
    FI, FJ, FK = f.shape[0], f.shape[1], f.shape[2]
    for C in prange(NI):
        for D_ in range(NJ):
            for E in range(NK):
                anyused = 0.0
                for a in range(-1, 2):
                    i = 2 * C + a
                    if i < 0 or i >= FI:
                        continue
                    for b in range(-1, 2):
                        j = 2 * D_ + b
                        if j < 0 or j >= FJ:
                            continue
                        for c in range(-1, 2):
                            k = 2 * E + c
                            if k < 0 or k >= FK:
                                continue
                            if used[i, j, k, 0] > 0.5:
                                anyused = 1.0
                used_out[C, D_, E, :] = anyused
                if used[2 * C, 2 * D_, 2 * E, 0] > 0.5:
                    for d in range(3):
                        out[C, D_, E, d] = f[2 * C, 2 * D_, 2 * E, d]
                else:
                    for d in range(3):
                        s = 0.0
                        for a in range(-1, 2):
                            i = 2 * C + a
                            if i < 0 or i >= FI:
                                continue
                            for b in range(-1, 2):
                                j = 2 * D_ + b
                                if j < 0 or j >= FJ:
                                    continue
                                for c in range(-1, 2):
                                    k = 2 * E + c
                                    if k < 0 or k >= FK:
                                        continue
                                    if f[i, j, k, d] > 0.5:
                                        s = 1.0
                        out[C, D_, E, d] = s


@njit(parallel=True, fastmath=True, cache=True)
def jacobi(x, r, dinv, free, omega):
    """x += omega * D^-1 r on the free dofs (flat views)."""
    for i in prange(x.size):
        x[i] += omega * dinv[i] * r[i] * free[i]


class Level:
    def __init__(self, w, free, Ke, used):
        self.w, self.free, self.Ke, self.used = w, free, Ke, used
        self.shape = free.shape
        d = np.zeros(free.shape)
        diag_k(w, Ke, OX, OY, OZ, d)
        self.dinv = np.where(free > 0.5, 1.0 / np.maximum(d, 1e-300), 0.0)
        self.u = np.zeros(free.shape)
        self.b = np.zeros(free.shape)
        self.r = np.zeros(free.shape)
        self.t = np.zeros(free.shape)

    def matvec(self, u, y):
        apply_k(u * self.free, y, self.w, self.Ke, OX, OY, OZ)
        y *= self.free
        return y


class Multigrid:
    def __init__(self, w0, free0, used0, Ke0, coarsest=6, omega=0.4, nu=2):
        self.omega, self.nu = omega, nu
        self.levels = [Level(w0, free0, Ke0, used0)]
        while min(self.levels[-1].w.shape) > coarsest and all(s % 2 == 0 for s in self.levels[-1].w.shape):
            L = self.levels[-1]
            wc = np.empty(tuple(s // 2 for s in L.w.shape))
            coarse_weights(L.w, wc)
            wc = np.maximum(wc, FLOOR)
            fc = np.empty(tuple(s // 2 + 1 for s in L.w.shape) + (3,))
            uc = np.empty_like(fc)
            coarse_free(L.free, L.used, fc, uc)
            self.levels.append(Level(wc, fc, L.Ke * 2.0, uc))
        C = self.levels[-1]                                     # dense coarsest problem
        n = C.free.size
        A = np.zeros((n, n))
        e = np.zeros(C.free.shape)
        y = np.zeros(C.free.shape)
        for i in np.nonzero(C.free.ravel() > 0.5)[0]:
            e.ravel()[i] = 1.0
            C.matvec(e, y)
            A[:, i] = y.ravel()
            e.ravel()[i] = 0.0
        fi = np.nonzero(C.free.ravel() > 0.5)[0]
        self.cidx = fi
        self.cinv = np.linalg.pinv(A[np.ix_(fi, fi)], hermitian=True) if len(fi) else np.zeros((0, 0))

    def smooth(self, L, x, b, sweeps):
        for _ in range(sweeps):
            L.matvec(x, L.t)
            np.subtract(b, L.t, out=L.r)
            jacobi(x.ravel(), L.r.ravel(), L.dinv.ravel(), L.free.ravel(), self.omega)

    def vcycle(self, k, b, x):
        """x <- one V-cycle for A x = b on level k (x starts at zero)."""
        L = self.levels[k]
        if k == len(self.levels) - 1:
            x[:] = 0.0
            x.ravel()[self.cidx] = self.cinv @ b.ravel()[self.cidx]
            return
        x[:] = 0.0
        self.smooth(L, x, b, self.nu)
        L.matvec(x, L.t)
        np.subtract(b, L.t, out=L.r)
        C = self.levels[k + 1]
        restrict(L.r * L.free, C.b)
        C.b *= C.free
        self.vcycle(k + 1, C.b, C.u)
        prolong(C.u, L.t)
        x += L.t * L.free
        self.smooth(L, x, b, self.nu)


def _grid_dims(occ, levels_wanted=None):
    nmin = min(occ.shape)
    L = 0
    while nmin / 2 ** (L + 1) >= 4:
        L += 1
    if levels_wanted is not None:
        L = min(L, levels_wanted)
    mult = 2 ** L
    return tuple(int(math.ceil(s / mult) * mult) for s in occ.shape), L


def solve(model, free, rhs, tol=1e-6, maxit=300, progress=None, omega=0.4, nu=2):
    """Conjugate gradients on the free dofs, preconditioned by one multigrid V-cycle.  Returns (x, iterations, relative residual, info)."""
    t0 = time.time()
    dims, nlev = _grid_dims(model.occ)
    shape_nodes = tuple(s + 1 for s in dims)
    w0 = np.zeros(dims)
    w0[:model.occ.shape[0], :model.occ.shape[1], :model.occ.shape[2]] = model.occ
    ijk = model.node_ijk

    def to_grid(v):
        g = np.zeros(shape_nodes + (3,))
        g[ijk[:, 0], ijk[:, 1], ijk[:, 2], :] = v.reshape(-1, 3)
        return g

    f0 = to_grid(free.astype(float))
    used0 = to_grid(np.ones(model.ndof))
    mg = Multigrid(w0, f0, used0, model.Ke, omega=omega, nu=nu)
    L0 = mg.levels[0]
    b = to_grid(rhs) * L0.free
    x = np.zeros_like(b)
    r = b.copy()
    b0 = float(np.linalg.norm(b))
    if b0 == 0:
        return np.zeros(model.ndof), 0, 0.0, {"levels": len(mg.levels)}
    z = np.zeros_like(b)
    mg.vcycle(0, r, z)
    p = z.copy()
    rz = float((r * z).sum())
    Ap = np.zeros_like(b)
    t_setup = time.time() - t0
    rel, it = 1.0, 0
    for it in range(1, maxit + 1):
        L0.matvec(p, Ap)
        a = rz / float((p * Ap).sum())
        x += a * p
        r -= a * Ap
        rel = float(np.linalg.norm(r)) / b0
        tick(progress, f"Solving: multigrid iteration {it}, residual {rel:.1e}", min(max(math.log10(max(rel, 1e-300)) / math.log10(tol), 0.0), 1.0))
        if rel < tol:
            break
        mg.vcycle(0, r, z)
        rz_new = float((r * z).sum())
        p = z + (rz_new / rz) * p
        rz = rz_new
    out = x[ijk[:, 0], ijk[:, 1], ijk[:, 2], :].reshape(-1)
    return out, it, rel, {"levels": len(mg.levels), "setup_s": t_setup, "threads": get_num_threads()}
