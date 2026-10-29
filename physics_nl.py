"""Nonlinear FEA: large displacements and yielding (plane stress), for the 6-node triangles of physics_fea.

Total Lagrangian formulation.  Strain: Green-Lagrange, stress: 2nd Piola-Kirchhoff with a linear elastic law (St Venant-Kirchhoff, so large
rotations are exact and the strains are expected to stay small, as for steel).  Yielding: von Mises, isotropic hardening that rises in a
straight line from the yield strength (at zero plastic strain) to the ultimate strength (at the plastic strain `eps_u`) and then stays flat;
plane-stress return mapping with a consistent tangent.  Loads are "dead": they keep their size and direction.  The supports are those of
the linear solver (fixed dofs, bolts, one-way screws and contact); the one-way ones are found by an active-set iteration inside the Newton
iteration and their directions stay those of the undeformed mesh.

Only the pieces the linear solver does not have are here; physics_fea.solve calls solve_nonlinear() and does the reporting.
"""
import time
import warnings

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

import physics_solve as psolve

SUBC = np.array([[2 / 3, 1 / 6, 1 / 6], [1 / 6, 2 / 3, 1 / 6], [1 / 6, 1 / 6, 2 / 3], [1 / 3, 1 / 3, 1 / 3]])
GP = SUBC[:3]                                   # the 3 Gauss points (weights 1/3 of the area): also three of the four stress points
P = np.array([[2.0, -1.0, 0.0], [-1.0, 2.0, 0.0], [0.0, 0.0, 6.0]])


class NLFailed(Exception):
    pass


def _dN(L):
    l1, l2, l3 = L
    return np.array([[4 * l1 - 1, 0, 0], [0, 4 * l2 - 1, 0], [0, 0, 4 * l3 - 1],
                     [4 * l2, 4 * l1, 0], [0, 4 * l3, 4 * l2], [4 * l3, 0, 4 * l1]])


def _grads(nodes, conn, L):
    p = nodes[conn[:, :3]]
    x, y = p[:, :, 0], p[:, :, 1]
    b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
    c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
    A = 0.5 * ((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
    G = _dN(L)
    dNdx = np.einsum("ik,mk->mi", G, b) / (2 * A)[:, None]
    dNdy = np.einsum("ik,mk->mi", G, c) / (2 * A)[:, None]
    return dNdx, dNdy, A


def _veq(S):
    return np.sqrt(np.maximum(S[:, 0] ** 2 - S[:, 0] * S[:, 1] + S[:, 1] ** 2 + 3.0 * S[:, 2] ** 2, 0.0))


class Material:
    def __init__(self, D, sy, su, eps_u, plastic):
        self.D = D
        self.sy, self.su = float(sy or 0.0), float(su or 0.0)
        self.eps_u = float(eps_u) if eps_u else 0.1
        if self.su <= self.sy:
            self.su = self.sy                        # perfectly plastic
        self.plastic = bool(plastic) and self.sy > 0
        if self.plastic:
            lam, V = np.linalg.eig(D @ P)
            self.lam = lam.real
            self.V = V.real
            self.Vinv = np.linalg.inv(self.V)

    def sigy(self, kap):
        return self.sy + (self.su - self.sy) * np.minimum(kap / self.eps_u, 1.0)

    def map(self, S_tr, kap):
        """Return mapping for trial stresses (n, 3) at plastic strain kap (n,): -> S (n, 3), dg (n,) (0 where elastic)."""
        n = len(S_tr)
        S = S_tr.copy()
        dg = np.zeros(n)
        seq = _veq(S_tr)
        pl = np.nonzero(seq > self.sigy(kap) * (1 + 1e-12))[0]
        if len(pl) == 0:
            return S, dg
        St, kp = S_tr[pl], kap[pl]
        Z = St @ self.Vinv.T

        def state(g):
            Zs = Z / (1.0 + g[:, None] * self.lam[None, :])
            Sg = Zs @ self.V.T
            return Sg, _veq(Sg)

        def gfun(g):
            Sg, q = state(g)
            return q - self.sigy(kp + 2.0 * q * g)

        lo = np.zeros(len(pl))
        hi = np.full(len(pl), 1e-6 / float(np.max(self.lam)))
        for _ in range(100):
            bad = gfun(hi) > 0
            if not bad.any():
                break
            hi = np.where(bad, hi * 4.0, hi)
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            pos = gfun(mid) > 0
            lo = np.where(pos, mid, lo)
            hi = np.where(pos, hi, mid)
        g = 0.5 * (lo + hi)
        Sg, _ = state(g)
        S[pl] = Sg
        dg[pl] = g
        return S, dg

    def update(self, E, ep, kap):
        """E (n, 3) total strain (engineering shear), ep (n, 3), kap (n,) -> S, ep_new, kap_new, C (n, 3, 3)."""
        D = self.D
        S_tr = (E - ep) @ D.T
        n = len(E)
        if not self.plastic:
            return S_tr, ep, kap, np.broadcast_to(D, (n, 3, 3))
        S, dg = self.map(S_tr, kap)
        pl = np.nonzero(dg > 0)[0]
        ep_new, kap_new = ep.copy(), kap.copy()
        C = np.broadcast_to(D, (n, 3, 3)).copy()
        if len(pl):
            q = _veq(S[pl])
            ep_new[pl] = ep[pl] + dg[pl, None] * (S[pl] @ P.T)
            kap_new[pl] = kap[pl] + 2.0 * q * dg[pl]
            h = 1e-7
            for j in range(3):                                   # consistent tangent by differencing the return mapping
                Ep = E[pl].copy()
                Ep[:, j] += h
                Sp, _ = self.map((Ep - ep[pl]) @ D.T, kap[pl])
                C[pl, :, j] = (Sp - S[pl]) / h
        return S, ep_new, kap_new, C


def _rotation(N, rules):
    nd = 2 * N
    if not rules:
        return None, np.zeros(0, dtype=np.int64)
    rn = np.array(sorted(rules), dtype=np.int64)
    mask = np.zeros(N, dtype=bool)
    mask[rn] = True
    keep = np.nonzero(~mask)[0]
    rows, cols, vals = [], [], []
    for k in (0, 1):
        rows.append(2 * keep + k)
        cols.append(2 * keep + k)
        vals.append(np.ones(len(keep)))
    nv = np.array([rules[int(n)]["n"] for n in rn])
    rows += [2 * rn, 2 * rn, 2 * rn + 1, 2 * rn + 1]
    cols += [2 * rn, 2 * rn + 1, 2 * rn, 2 * rn + 1]
    vals += [nv[:, 0], nv[:, 1], -nv[:, 1], nv[:, 0]]
    T = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(nd, nd)).tocsr()
    return T, rn


class Model:
    def __init__(self, nodes, conn, th, mat, geom):
        self.nodes, self.conn, self.th, self.mat, self.geom = nodes, conn, th, mat, geom
        self.M = len(conn)
        self.nd = 2 * len(nodes)
        self.dofs = conn[:, np.repeat(np.arange(6), 2)] * 2 + np.tile([0, 1], 6)[None, :]
        self.gp = []
        for L in GP:
            dx, dy, A = _grads(nodes, conn, L)
            self.gp.append((dx, dy))
        self.A = A
        self.rows = np.broadcast_to(self.dofs[:, :, None], (self.M, 12, 12)).ravel()
        self.cols = np.broadcast_to(self.dofs[:, None, :], (self.M, 12, 12)).ravel()
        self.sub = [_grads(nodes, conn, L)[:2] for L in SUBC]

    def kin(self, ue, dx, dy):
        ux, uy = ue[:, 0::2], ue[:, 1::2]
        return ((dx * ux).sum(1), (dy * ux).sum(1), (dx * uy).sum(1), (dy * uy).sum(1))

    def strain_B(self, H, dx, dy):
        H11, H12, H21, H22 = H
        M = len(H11)
        if self.geom:
            E = np.stack([H11 + 0.5 * (H11 ** 2 + H21 ** 2), H22 + 0.5 * (H12 ** 2 + H22 ** 2),
                          H12 + H21 + H11 * H12 + H21 * H22], axis=1)
            a, b, c, d = 1.0 + H11, H21, H12, 1.0 + H22
        else:
            E = np.stack([H11, H22, H12 + H21], axis=1)
            a, b, c, d = np.ones(M), np.zeros(M), np.zeros(M), np.ones(M)
        B = np.zeros((M, 3, 12))
        B[:, 0, 0::2] = a[:, None] * dx
        B[:, 0, 1::2] = b[:, None] * dx
        B[:, 1, 0::2] = c[:, None] * dy
        B[:, 1, 1::2] = d[:, None] * dy
        B[:, 2, 0::2] = a[:, None] * dy + c[:, None] * dx
        B[:, 2, 1::2] = d[:, None] * dx + b[:, None] * dy
        return E, B

    def assemble(self, u, ep, kap):
        ue = u[self.dofs]
        fint = np.zeros(self.nd)
        Ke = np.zeros((self.M, 12, 12))
        epn, kapn = np.empty_like(ep), np.empty_like(kap)
        w = self.th * self.A / 3.0
        for g, (dx, dy) in enumerate(self.gp):
            H = self.kin(ue, dx, dy)
            E, B = self.strain_B(H, dx, dy)
            S, epn[:, g], kapn[:, g], C = self.mat.update(E, ep[:, g], kap[:, g])
            fe = np.einsum("mji,mj->mi", B, S) * w[:, None]
            fint += np.bincount(self.dofs.ravel(), weights=fe.ravel(), minlength=self.nd)
            Ke += w[:, None, None] * np.einsum("mji,mjk,mkl->mil", B, C, B)
            if self.geom:
                Sxx, Syy, Sxy = S[:, 0][:, None, None], S[:, 1][:, None, None], S[:, 2][:, None, None]
                kg = (dx[:, :, None] * Sxx * dx[:, None, :] + dx[:, :, None] * Sxy * dy[:, None, :] +
                      dy[:, :, None] * Sxy * dx[:, None, :] + dy[:, :, None] * Syy * dy[:, None, :])
                Ke[:, 0::2, 0::2] += w[:, None, None] * kg
                Ke[:, 1::2, 1::2] += w[:, None, None] * kg
        K = sp.coo_matrix((Ke.ravel(), (self.rows, self.cols)), shape=(self.nd, self.nd)).tocsr()
        return fint, K, epn, kapn

    def stresses(self, u, ep, kap):
        """Cauchy stresses, equivalent plastic strain and elastic strain energy at the four stress points of every element."""
        ue = u[self.dofs]
        M = self.M
        sx, sy, txy, pe = (np.zeros((M, 4)) for _ in range(4))
        energy = 0.0
        w = self.th * self.A / 3.0
        for j in range(4):
            dx, dy = self.sub[j]
            H = self.kin(ue, dx, dy)
            E, _ = self.strain_B(H, dx, dy)
            if j < 3:
                e_p, k_p = ep[:, j], kap[:, j]
            else:
                e_p, k_p = ep.mean(axis=1), kap.mean(axis=1)
            S, _, k_new, _ = self.mat.update(E, e_p, k_p)
            pe[:, j] = k_p
            if self.geom:
                H11, H12, H21, H22 = H
                F11, F12, F21, F22 = 1 + H11, H12, H21, 1 + H22
                J = F11 * F22 - F12 * F21
                Sxx, Syy, Sxy = S[:, 0], S[:, 1], S[:, 2]
                sx[:, j] = (F11 ** 2 * Sxx + 2 * F11 * F12 * Sxy + F12 ** 2 * Syy) / J
                sy[:, j] = (F21 ** 2 * Sxx + 2 * F21 * F22 * Sxy + F22 ** 2 * Syy) / J
                txy[:, j] = (F11 * F21 * Sxx + (F11 * F22 + F12 * F21) * Sxy + F12 * F22 * Syy) / J
            else:
                sx[:, j], sy[:, j], txy[:, j] = S[:, 0], S[:, 1], S[:, 2]
            if j < 3:
                el = E - e_p
                energy += float(np.sum(w * 0.5 * (S * el).sum(axis=1)))
        return sx.reshape(-1), sy.reshape(-1), txy.reshape(-1), pe.reshape(-1), energy


def solve_nonlinear(nodes_all, conn, th, D, f_full, fixed_idx, rules, mat, u_lin=None, nl_disp=None, cancel=None, progress=None,
                    geom=True, plastic=True, max_iter=25):
    """Load-stepped Newton solve.  -> dict(u, react, sx, sy, txy, peeq, energy, info).  Never raises for lack of convergence: the
    last converged load level is returned with info['converged'] = False and info['load_fraction'] < 1."""
    t0 = time.perf_counter()
    N = len(nodes_all)
    nd = 2 * N
    mt = Material(D, mat.get("sy"), mat.get("su"), mat.get("eps_u"), plastic)
    mdl = Model(nodes_all, conn, th, mt, geom)
    M = mdl.M
    T, rn = _rotation(N, rules)
    base = set(int(d) for d in fixed_idx)
    one = []
    for n in rn:
        r = rules[int(n)]
        if r.get("tang") == "fixed":
            base.add(2 * int(n) + 1)
        if r.get("normal") == "fixed":
            base.add(2 * int(n))
        elif r.get("normal") == "oneway":
            one.append(2 * int(n))
    active = set(one)
    Fmax = float(np.max(np.abs(f_full))) or 1.0
    tolF = 1e-7 * Fmax
    tolR = 1e-9 * Fmax
    ep = np.zeros((M, 3, 3))
    kap = np.zeros((M, 3))
    u = np.zeros(nd)                                          # global dofs; the rotated copy is T u
    lam = 0.0
    n0 = 10
    if u_lin is not None and nl_disp and nl_disp > 0:
        n0 = int(np.clip(np.ceil(4.0 * u_lin / nl_disp), 5, 40))
    dlam = 1.0 / n0
    info = {"steps": 0, "iterations": 0, "cuts": 0, "converged": True, "load_fraction": 1.0, "active_changes": 0}
    rot = (lambda v: v) if T is None else (lambda v: T @ v)
    unrot = (lambda v: v) if T is None else (lambda v: T.T @ v)
    last = {"R": None}

    one_set = set(one)

    def attempt(lam_new, u0, ep0, kap0, active0):
        """Newton at load level lam_new from state u0.  -> (ok, u, ep, kap, active, iterations, reaction in rotated dofs)"""
        fail = (False, None, None, None, None, 0, None)
        ur = rot(u0)
        act = set(active0)
        fext = rot(f_full * lam_new)
        n_newton = n_switch = 0
        while True:
            if cancel and cancel():
                raise RuntimeError("cancelled")
            uu = unrot(ur)
            fint, K, epn, kapn = mdl.assemble(uu, ep0, kap0)
            R = rot(fint) - fext
            fix = np.array(sorted(base | act), dtype=np.int64)
            mask = np.ones(nd, dtype=bool)
            mask[fix] = False
            free = np.nonzero(mask)[0]
            rnorm = float(np.max(np.abs(R[free]))) if len(free) else 0.0
            if not np.isfinite(rnorm):
                return fail
            if rnorm <= tolF:
                rel = {d for d in act if d in one_set and R[d] > tolR}
                umaxl = float(np.max(np.abs(ur))) or 1.0
                cap = {d for d in one if d not in act and ur[d] > 1e-9 * umaxl}
                if not rel and not cap:
                    reac = np.zeros(nd)
                    reac[fix] = R[fix]
                    return True, uu, epn, kapn, act, n_newton, reac
                act = (act - rel) | cap
                info["active_changes"] += 1
                n_switch += 1
                if n_switch > 60:
                    return fail
                continue
            if n_newton >= max_iter:
                return fail
            Kr = K if T is None else (T @ K @ T.T).tocsr()
            du = np.zeros(nd)
            du[fix] = -ur[fix]                                   # constrained dofs go to zero (a newly captured one-way node is pushed back)
            rhs = -R[free]
            if len(fix):
                rhs = rhs - Kr[free][:, fix] @ du[fix]
            Kff = Kr[free][:, free].tocsc()
            with warnings.catch_warnings():
                warnings.simplefilter("error", category=spla.MatrixRankWarning)
                try:
                    du[free] = psolve.solve(Kff, rhs)
                except Exception:
                    return fail
            if not np.all(np.isfinite(du)):
                return fail
            ur = ur + du
            n_newton += 1

    nsteps = 0
    reac = np.zeros(nd)
    while lam < 1.0 - 1e-12:
        step = min(dlam, 1.0 - lam)
        ok, u_new, ep_new, kap_new, act_new, its, rc = attempt(lam + step, u, ep, kap, active)
        info["iterations"] += its
        if ok:
            lam += step
            u, ep, kap, active, reac = u_new, ep_new, kap_new, act_new, rc
            nsteps += 1
            if progress:
                progress(f"Nonlinear solve: load {100 * lam:.0f} % (step {nsteps})", 0.5 + 0.4 * lam)
            if its <= 5:
                dlam = min(dlam * 1.5, 0.25)
            elif its > 12:
                dlam *= 0.7
        else:
            info["cuts"] += 1
            dlam = step * 0.5
            if dlam < 1e-4 or nsteps + info["cuts"] > 600:
                info["converged"] = False
                break
    info["steps"] = nsteps
    info["load_fraction"] = lam
    if lam == 0.0:                                               # not even the first load step converged: nothing to show
        raise NLFailed("The nonlinear solve did not converge at the smallest load step.")
    react_rot = reac
    react = unrot(react_rot)
    fixmask = np.zeros(nd, dtype=bool)
    fixmask[np.array(sorted(base | active), dtype=np.int64)] = True
    sx, sy, txy, pe, energy = mdl.stresses(u, ep, kap)
    info["fixed_dofs"] = int(fixmask.sum())
    info["peeq_max"] = float(np.max(pe)) if len(pe) else 0.0
    info["plastic_points"] = int(np.sum(kap > 0))
    info["eps_u_reached"] = bool(mt.plastic and np.any(kap >= mt.eps_u))
    info["time"] = time.perf_counter() - t0
    info["active_oneway_nodes"] = sorted(d // 2 for d in active)
    # residual at the end (relative to the force scale) for the report
    fint, K, _, _ = mdl.assemble(u, ep, kap)
    Rg = fint - f_full * lam
    Rg = Rg.copy()
    Rg[np.abs(react) > 0] = 0.0
    info["residual"] = float(np.linalg.norm(Rg, np.inf) / Fmax)
    return {"u": u, "react": react, "fixmask": fixmask, "f_applied": f_full * lam, "sx": sx, "sy": sy, "txy": txy, "peeq": pe, "energy": energy, "info": info,
            "lam": lam}
