"""Nonlinear plane-frame solver for the 1D FEA tab: large displacements and yielding.

  * elements: co-rotational Euler-Bernoulli beams (the element follows its chord, so rotations of any size are exact; the strains inside an
    element stay small, so cut members into several elements - the Mesh section does)
  * section: horizontal strips (fibres) of the real outline; every strip has its own stress.  A strip is linear elastic up to the yield strength,
    then the stress rises in a straight line to the ultimate strength over `eu` plastic strain and stays flat (the same law as the 2D solver);
    sections known only by numbers (A, I) stay elastic
  * loads: dead (they keep their size and direction), applied in steps; each step is solved by Newton iterations, the step is halved when an
    iteration diverges.  If the loads cannot be carried (a plastic mechanism or buckling), the last equilibrium found is returned and flagged.
  * Euler-Bernoulli: no shear deformation here, joints stay rigid / pinned as in the linear solve.
Sign conventions are those of beam1d (axial tension +, bending moment sagging +, fibre y positive toward the member's +y side).
"""
import math

import numpy as np

import beam1d
import profiles1d as pr1

try:
    import scipy.sparse as sps
    import scipy.sparse.linalg as spl
except Exception:                                # noqa: BLE001 - dense fallback
    sps = spl = None

GP = np.array([0.0, 0.5 - math.sqrt(3.0 / 7.0) / 2, 0.5, 0.5 + math.sqrt(3.0 / 7.0) / 2, 1.0])      # 5-point Lobatto stations along an element
GW = np.array([1 / 20, 49 / 180, 16 / 45, 49 / 180, 1 / 20])
TOL = 1e-7


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _fibres_of(m):
    """(y, dA, can_yield) of a piece."""
    prof = m.get("prof")
    fb = pr1.fibres(prof) if prof else None
    if fb is not None:
        return fb[0], fb[1], True
    A, I, ct, cb = float(m["A"]), float(m["I"]), float(m["c_top"]), float(m["c_bottom"])     # numbers only: three fibres, elastic
    a1, a2 = I / (ct * (ct + cb)), I / (cb * (ct + cb))
    return np.array([0.0, ct, -cb]), np.array([max(A - a1 - a2, 0.0), a1, a2]), False


def _material(eps, eps_p, alpha, E, sy, su, eu):
    """Uniaxial elastic / hardening plastic update, vectorised.  eps, eps_p, alpha: (..., nf); E, sy, su, eu broadcast.
    -> stress, tangent modulus, new plastic strain, new accumulated plastic strain.  The yield stress rises from sy to su over the plastic
    strain eu, then stays at su (an elastic fibre has sy = 1e30)."""
    sig_tr = E * (eps - eps_p)
    H = np.where(eu > 0, (su - sy) / np.where(eu > 0, eu, 1.0), 0.0)
    f = np.abs(sig_tr) - (sy + H * np.minimum(alpha, eu))
    pl = f > 0
    if not pl.any():
        return sig_tr, np.broadcast_to(E, sig_tr.shape).copy(), eps_p, alpha
    room = np.maximum(eu - alpha, 0.0)                     # plastic strain left on the hardening branch
    f_end = f - (E + H) * room
    hard = pl & (room > 0) & (f_end <= 0)
    dg = np.where(hard, f / (E + H), np.where(room > 0, room + np.maximum(f_end, 0.0) / E, f / E))
    dg = np.where(pl, dg, 0.0)
    sgn = np.sign(sig_tr)
    sig = sig_tr - E * dg * sgn
    Et = np.where(pl, np.where(hard, np.maximum(E * H / (E + H), 1e-6 * E), 1e-6 * E), E)
    return sig, Et, eps_p + dg * sgn, alpha + dg


class Model:
    """Everything the iterations need, set up once."""

    def __init__(self, nodes, members, supports, nodal, eu_pct):
        self.ids = list(nodes)
        self.index = {nid: i for i, nid in enumerate(self.ids)}
        nn = len(self.ids)
        self.X0 = np.array([nodes[n] for n in self.ids], dtype=float)
        self.members = members
        nel = len(members)
        self.nel = nel
        extra = 3 * nn
        edof, ia_, ib_ = [], [], []
        self.L0 = np.zeros(nel)
        self.beta0 = np.zeros(nel)
        self.E = np.zeros(nel)
        self.sy = np.full(nel, 1e30)
        self.su = np.full(nel, 1e30)
        self.eu = np.full(nel, max(float(eu_pct), 0.0) / 100.0)
        shared = np.zeros(nn, dtype=bool)
        fib = []
        for e, m in enumerate(members):
            ia, ib = self.index[m["a"]], self.index[m["b"]]
            ra, rb = 3 * ia + 2, 3 * ib + 2
            if m.get("rel_a"):
                ra, extra = extra, extra + 1
            else:
                shared[ia] = True
            if m.get("rel_b"):
                rb, extra = extra, extra + 1
            else:
                shared[ib] = True
            edof.append([3 * ia, 3 * ia + 1, ra, 3 * ib, 3 * ib + 1, rb])
            ia_.append(ia)
            ib_.append(ib)
            d = self.X0[ib] - self.X0[ia]
            self.L0[e] = math.hypot(d[0], d[1])
            self.beta0[e] = math.atan2(d[1], d[0])
            self.E[e] = float(m["E"])
            y, dA, can = _fibres_of(m)
            fib.append((y, dA))
            sy, su = m.get("sy"), m.get("su")
            if can and sy and sy > 0:
                self.sy[e] = float(sy)
                self.su[e] = float(su) if su and su > sy else float(sy)
        self.ndof = extra
        self.edof = np.array(edof, dtype=int)
        self.ia, self.ib = np.array(ia_), np.array(ib_)
        nf = max(len(y) for y, _ in fib)
        self.y = np.zeros((nel, nf))
        self.dA = np.zeros((nel, nf))
        for e, (y, dA) in enumerate(fib):
            self.y[e, :len(y)] = y
            self.dA[e, :len(dA)] = dA
        self.nf = nf
        shp = (nel, len(GP), nf)
        self.eps_p = np.zeros(shp)
        self.alpha = np.zeros(shp)
        # reference loads (dead): nodal + the consistent loads of the line loads
        P = np.zeros(self.ndof)
        for nid, (fx, fy, mz) in nodal.items():
            if nid in self.index:
                i = self.index[nid]
                P[3 * i:3 * i + 3] += (fx, fy, mz)
        for e, m in enumerate(members):
            L, c, s = self.L0[e], math.cos(self.beta0[e]), math.sin(self.beta0[e])
            qg, ql = m.get("qg", (0.0, 0.0)), m.get("ql", (0.0, 0.0))
            px = qg[0] * c + qg[1] * s + ql[0]
            py = -qg[0] * s + qg[1] * c + ql[1]
            fl = np.array([px * L / 2, py * L / 2, py * L * L / 12, px * L / 2, py * L / 2, -py * L * L / 12])
            R = np.array([[c, -s], [s, c]])
            fg = np.concatenate([R @ fl[:2], [fl[2]], R @ fl[3:5], [fl[5]]])
            P[self.edof[e]] += fg
        self.P = P
        fixed = set()
        for nid, flags in supports.items():
            if nid in self.index:
                for j in range(3):
                    if flags[j]:
                        fixed.add(3 * self.index[nid] + j)
        for i in range(nn):
            if not shared[i]:
                fixed.add(3 * i + 2)
        self.fixed = np.array(sorted(fixed), dtype=int)
        self.free = np.array([d for d in range(self.ndof) if d not in fixed], dtype=int)

    # ---------------------------------------------------------------------------------------------------------------------------
    def kinematics(self, u):
        ua = np.stack([u[3 * self.ia], u[3 * self.ia + 1]], axis=1)
        ub = np.stack([u[3 * self.ib], u[3 * self.ib + 1]], axis=1)
        pa, pb = self.X0[self.ia] + ua, self.X0[self.ib] + ub
        d = pb - pa
        Ln = np.hypot(d[:, 0], d[:, 1])
        beta = np.arctan2(d[:, 1], d[:, 0])
        al = np.array([_wrap(b) for b in beta - self.beta0])
        t1 = u[self.edof[:, 2]] - al
        t2 = u[self.edof[:, 5]] - al
        return pa, pb, Ln, beta, t1, t2, Ln - self.L0

    def sections(self, ubar, t1, t2, trial=True):
        """Stresses and section tangents at the stations for the deformation (ubar, t1, t2)."""
        L0 = self.L0
        a_g, b_g = (-4 + 6 * GP)[None, :], (-2 + 6 * GP)[None, :]
        kap = (a_g * t1[:, None] + b_g * t2[:, None]) / L0[:, None]                         # (nel, ng)
        eps0 = (ubar / L0)[:, None]
        eps = eps0[:, :, None] - self.y[:, None, :] * kap[:, :, None]
        E = self.E[:, None, None]
        sig, Et, ep, al = _material(eps, self.eps_p, self.alpha, E, self.sy[:, None, None],
                                    self.su[:, None, None], self.eu[:, None, None])
        dA, y = self.dA[:, None, :], self.y[:, None, :]
        N = np.sum(sig * dA, axis=2)
        M = -np.sum(sig * y * dA, axis=2)
        EA = np.sum(Et * dA, axis=2)
        ES = np.sum(Et * y * dA, axis=2)
        EI = np.sum(Et * y * y * dA, axis=2)
        return {"sig": sig, "N": N, "M": M, "EA": EA, "ES": ES, "EI": EI, "ep": ep, "al": al, "kap": kap, "eps0": eps0}

    def internal(self, u, want_k=True):
        pa, pb, Ln, beta, t1, t2, ub = self.kinematics(u)
        sec = self.sections(ub, t1, t2)
        L0 = self.L0
        Nb = np.sum(GW[None, :] * sec["N"], axis=1)
        M1 = np.sum(GW[None, :] * sec["M"] * (-4 + 6 * GP)[None, :], axis=1)
        M2 = np.sum(GW[None, :] * sec["M"] * (-2 + 6 * GP)[None, :], axis=1)
        c, s = np.cos(beta), np.sin(beta)
        z = np.stack([s, -c, np.zeros_like(c), -s, c, np.zeros_like(c)], axis=1)
        r = np.stack([-c, -s, np.zeros_like(c), c, s, np.zeros_like(c)], axis=1)
        Bc = np.zeros((self.nel, 3, 6))
        Bc[:, 0, :] = r
        Bc[:, 1, 2] = 1.0
        Bc[:, 2, 5] = 1.0
        Bc[:, 1, :] -= z / Ln[:, None]
        Bc[:, 2, :] -= z / Ln[:, None]
        pbar = np.stack([Nb, M1, M2], axis=1)
        fint = np.einsum("eij,ei->ej", Bc, pbar)
        F = np.zeros(self.ndof)
        np.add.at(F, self.edof.ravel(), fint.ravel())
        if not want_k:
            return F, None, sec
        # local tangent  K = sum_g w L0 B^T D B
        a_g, b_g = (-4 + 6 * GP)[None, :], (-2 + 6 * GP)[None, :]
        Kb = np.zeros((self.nel, 3, 3))
        w = GW[None, :] * L0[:, None]
        EA, ES, EI = sec["EA"], sec["ES"], sec["EI"]
        Kb[:, 0, 0] = np.sum(w * EA, axis=1) / L0 ** 2
        for j, bj in ((1, a_g), (2, b_g)):
            v = -np.sum(w * ES * bj, axis=1) / L0 ** 2
            Kb[:, 0, j] = v
            Kb[:, j, 0] = v
            for k, bk in ((1, a_g), (2, b_g)):
                Kb[:, j, k] = np.sum(w * EI * bj * bk, axis=1) / L0 ** 2
        Kg = np.einsum("eji,ejk,ekl->eil", Bc, Kb, Bc)
        zz = np.einsum("ei,ej->eij", z, z)
        rz = np.einsum("ei,ej->eij", r, z)
        Kg += (Nb / Ln)[:, None, None] * zz + ((M1 + M2) / Ln ** 2)[:, None, None] * (rz + np.transpose(rz, (0, 2, 1)))
        rows = np.repeat(self.edof, 6, axis=1).ravel()
        cols = np.tile(self.edof, (1, 6)).ravel()
        return F, (rows, cols, Kg.reshape(self.nel, 36).ravel()), sec

    def commit(self, sec):
        self.eps_p = sec["ep"]
        self.alpha = sec["al"]


def _solve_lin(K, rhs, free, n):
    rows, cols, vals = K
    if sps is not None:
        A = sps.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()[free][:, free]
        return spl.spsolve(A.tocsc(), rhs)
    A = np.zeros((n, n))
    np.add.at(A, (rows, cols), vals)
    return np.linalg.solve(A[np.ix_(free, free)], rhs)


MAX_ATTEMPTS = 250


def solve(nodes, members, supports, nodal, opts, n_st=41):
    """-> the result dict of beam1d.solve, plus "nl": {"lambda": load fraction carried, "converged", "steps", "iterations", "yielded": [...]}"""
    mdl = Model(nodes, members, supports, nodal, opts.get("eu_pct", 10.0))
    free, P = mdl.free, mdl.P
    nref = float(np.linalg.norm(P[free])) + 1e-30
    u = np.zeros(mdl.ndof)
    lam, dlam, steps, iters = 0.0, 1.0 / float(opts.get("nl_steps", 10)), 0, 0
    reason = None
    attempts = 0
    state_ok = (mdl.eps_p.copy(), mdl.alpha.copy())
    while lam < 1.0 - 1e-12:
        attempts += 1
        if attempts > MAX_ATTEMPTS:                        # creeping towards a limit load: stop, keep the last equilibrium
            reason = (f"The load could not be raised beyond {100 * lam:.1f}% within {MAX_ATTEMPTS} load steps: the structure is at its "
                      "limit load (a plastic mechanism, or buckling).")
            break
        dl = min(dlam, 1.0 - lam)
        ut = u.copy()
        mdl.eps_p, mdl.alpha = state_ok[0].copy(), state_ok[1].copy()
        ok = False
        last = np.inf
        for it in range(30):
            F, K, sec = mdl.internal(ut)
            R = F - (lam + dl) * P
            nr = float(np.linalg.norm(R[free]))
            if not np.isfinite(nr):
                break
            iters += 1
            if nr < TOL * nref:
                ok = True
                break
            if it > 3 and nr > 10 * last:
                break
            last = nr if it == 0 else min(last, nr)
            try:
                du = _solve_lin(K, -R[free], free, mdl.ndof)
            except Exception:                                  # noqa: BLE001 - singular tangent
                break
            if not np.all(np.isfinite(du)):
                break
            ut[free] += du
        if ok:
            mdl.commit(sec)
            state_ok = (mdl.eps_p.copy(), mdl.alpha.copy())
            u, lam, steps = ut, lam + dl, steps + 1
            dlam = min(dlam * 1.5, 0.25) if it <= 4 else dlam
        else:
            dlam /= 2.0
            if dlam < 1e-5:
                reason = (f"No equilibrium was found beyond {100 * lam:.1f}% of the loads: the structure cannot carry more "
                          "(a plastic mechanism, or buckling).")
                break
    mdl.eps_p, mdl.alpha = state_ok[0].copy(), state_ok[1].copy()
    F, _K, sec = mdl.internal(u, want_k=False)
    lam_f = lam
    Rv = F - lam_f * P
    return _result(mdl, u, sec, Rv, lam_f, steps, iters, reason, supports, nodes, n_st)


def _result(mdl, u, sec, Rv, lam, steps, iters, reason, supports, nodes, n_st):
    pa, pb, Ln, beta, t1, t2, ub = mdl.kinematics(u)
    out, yielded = [], []
    for e, m in enumerate(mdl.members):
        L0 = mdl.L0[e]
        c0, s0 = math.cos(mdl.beta0[e]), math.sin(mdl.beta0[e])
        c, s = math.cos(beta[e]), math.sin(beta[e])
        xi = GP
        x = xi * L0
        N, M = sec["N"][e].copy(), sec["M"][e].copy()
        Vs = np.gradient(M, x) if len(x) > 1 else np.zeros_like(M)
        v_loc = Ln[e] * (xi * (1 - xi) ** 2 * t1[e] - xi ** 2 * (1 - xi) * t2[e])
        P0 = mdl.X0[mdl.ia[e]][None, :] + xi[:, None] * (mdl.X0[mdl.ib[e]] - mdl.X0[mdl.ia[e]])[None, :]
        Pc = pa[e][None, :] + np.stack([c * xi * Ln[e] - s * v_loc, s * xi * Ln[e] + c * v_loc], axis=1)
        dxy = Pc - P0
        u_ax = dxy[:, 0] * c0 + dxy[:, 1] * s0
        v_tr = -dxy[:, 0] * s0 + dxy[:, 1] * c0
        top, bot = int(np.argmax(mdl.y[e])), int(np.argmin(mdl.y[e]))
        sig_ext = []
        for fi, y_ext in ((top, float(m["c_top"])), (bot, -float(m["c_bottom"]))):      # the stress right at the outer edge of the section
            eps_x = sec["eps0"][e] - y_ext * sec["kap"][e]
            sg, *_r = _material(eps_x, mdl.eps_p[e][:, fi], mdl.alpha[e][:, fi], mdl.E[e], mdl.sy[e], mdl.su[e], mdl.eu[e])
            sig_ext.append(np.asarray(sg, dtype=float).copy())
        sig_top, sig_bot = sig_ext
        sig = np.maximum(np.abs(sig_top), np.abs(sig_bot))
        sy, su = m.get("sy"), m.get("su")
        smax = float(sig.max())
        pk = lambda arr: float(arr[int(np.argmax(np.abs(arr)))])
        n_min = float(N.min())
        E, A, I = float(m["E"]), float(m["A"]), float(m["I"])
        pcr = math.pi ** 2 * E * I / L0 ** 2
        ep_max = float(np.max(sec["al"][e]))
        if ep_max > 0 and m.get("name", str(m["id"])) not in yielded:
            yielded.append(m.get("name", str(m["id"])))
        du_a = np.array([dxy[0, 0] * c0 + dxy[0, 1] * s0, -dxy[0, 0] * s0 + dxy[0, 1] * c0, u[mdl.edof[e, 2]]])
        du_b = np.array([dxy[-1, 0] * c0 + dxy[-1, 1] * s0, -dxy[-1, 0] * s0 + dxy[-1, 1] * c0, u[mdl.edof[e, 5]]])
        out.append({
            "id": m["id"], "name": m.get("name", str(m["id"])), "a": m["a"], "b": m["b"], "L": L0, "c": c0, "s": s0, "E": E, "A": A, "I": I,
            "c_top": float(m["c_top"]), "c_bottom": float(m["c_bottom"]), "sy": sy, "su": su, "rel_a": bool(m.get("rel_a")),
            "rel_b": bool(m.get("rel_b")), "group": m.get("group"),
            "F": np.array([-N[0], Vs[0], -M[0], N[-1], -Vs[-1], M[-1]]), "d": np.concatenate([du_a, du_b]), "x": x, "N": N, "V": Vs, "M": M,
            "u": u_ax, "v": v_tr, "sig_top": sig_top, "sig_bot": sig_bot, "sig": sig, "xy0": P0, "dxy": dxy,
            "N_peak": pk(N), "V_peak": pk(Vs), "M_peak": pk(M), "sigma_max": smax, "umax": float(np.max(np.hypot(dxy[:, 0], dxy[:, 1]))),
            "fos_y": float(sy) / smax if sy and sy > 0 and smax > 0 else None, "fos_u": float(su) / smax if su and su > 0 and smax > 0 else None,
            "pcr": pcr, "euler_ratio": (-n_min / pcr) if n_min < 0 else 0.0, "px": 0.0, "py": 0.0, "bounds": [0.0, L0], "As": m.get("As"),
            "phi": 0.0, "eps_p_max": ep_max})
    node_disp = {nid: (float(u[3 * i]), float(u[3 * i + 1]), float(u[3 * i + 2])) for i, nid in enumerate(mdl.ids)}
    xy_nodes = {nid: (float(nodes[nid][0]), float(nodes[nid][1])) for nid in mdl.ids}
    reactions = {}
    for nid, flags in supports.items():
        if nid in mdl.index:
            i = mdl.index[nid]
            reactions[nid] = tuple(float(Rv[3 * i + j]) if flags[j] else 0.0 for j in range(3))
    tr = np.arange(len(mdl.ids))
    fa = np.array([lam * mdl.P[3 * tr].sum(), lam * mdl.P[3 * tr + 1].sum()])
    fr = np.array([sum(r[0] for r in reactions.values()), sum(r[1] for r in reactions.values())])
    resid = fa + fr
    scale = max(float(np.abs(fa).max()), float(np.abs(fr).max()), 1e-300)
    eq = {"applied": (float(fa[0]), float(fa[1]), 0.0), "reactions": (float(fr[0]), float(fr[1]), 0.0),
          "residual": (float(resid[0]), float(resid[1]), 0.0), "relative": float(np.abs(resid).max() / scale)}
    notes = []
    if reason:
        notes.append(reason)
    res = beam1d._assemble_result(out, node_disp, xy_nodes, reactions, eq, notes, n_st)
    res["nl"] = {"lambda": float(lam), "converged": reason is None, "steps": int(steps), "iterations": int(iters), "yielded": yielded, "reason": reason}
    return res
