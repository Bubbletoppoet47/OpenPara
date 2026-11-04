"""Plane-frame (beam) solver for the 1D FEA tab: Euler-Bernoulli beams, rigid or pinned member ends, linear elastic.

Run  python beam1d.py  to check the solver against textbook results (cantilever, simply supported beam, truss, portal frame).

Conventions (used everywhere, in any consistent unit system):
  * a node has three displacements: ux, uy (global x, y) and rz (rotation, counter-clockwise positive)
  * a member runs from node a to node b; its local x axis points a -> b and its local y axis is 90 degrees counter-clockwise from it
    (the "left" of the direction of travel)
  * axial force N: tension positive
  * shear force V: the sum of the forces on the left piece of the member in local +y, so a simply supported beam under a downward
    load has +V at its left end (the textbook sign)
  * bending moment M: sagging positive (the member bends concave toward its local +y side), so tension is on the -y side
  * fibre stress at the +y fibre:  N/A - M c_top / I      at the -y fibre:  N/A + M c_bottom / I
  * a "release" (pinned member end) means the member transmits no bending moment at that end
  * line loads are uniform along the member: "qg" = (qx, qy) in global axes, "ql" = (qt, qn) along and normal to the member
    (force per length)
"""
import math

import numpy as np


class BeamError(Exception):
    """A problem the user can fix (a mechanism, a bad number...).  `.members` = ids of the members involved, `.nodes` = point ids."""

    def __init__(self, msg, members=None, nodes=None):
        super().__init__(msg)
        self.members = list(members or [])
        self.nodes = list(nodes or [])


def local_k(E, A, I, L):
    a, b, c, d, e = E * A / L, 12 * E * I / L ** 3, 6 * E * I / L ** 2, 4 * E * I / L, 2 * E * I / L
    return np.array([[a, 0, 0, -a, 0, 0],
                     [0, b, c, 0, -b, c],
                     [0, c, d, 0, -c, e],
                     [-a, 0, 0, a, 0, 0],
                     [0, -b, -c, 0, b, -c],
                     [0, c, e, 0, -c, d]], dtype=float)


def _geometry(nodes, m):
    xa, ya = nodes[m["a"]]
    xb, yb = nodes[m["b"]]
    dx, dy = xb - xa, yb - ya
    L = math.hypot(dx, dy)
    if not L > 0:
        raise BeamError(f"Member '{m.get('name', m['id'])}' has zero length.")
    return xa, ya, xb, yb, L, dx / L, dy / L


def _release_split(k, f0, rel):
    """Static condensation of the released rotations.  -> (condensed stiffness, condensed fixed-end forces, pieces for recovery)."""
    if not rel:
        return k, f0, None
    con = [i for i in range(6) if i not in rel]
    Krr = k[np.ix_(rel, rel)]
    Krc = k[np.ix_(rel, con)]
    Kcr = k[np.ix_(con, rel)]
    Kcc = k[np.ix_(con, con)]
    Ri = np.linalg.inv(Krr)
    Kc = Kcc - Kcr @ Ri @ Krc
    fc = f0[con] - Kcr @ Ri @ f0[rel]
    K6 = np.zeros((6, 6))
    f6 = np.zeros(6)
    K6[np.ix_(con, con)] = Kc
    f6[con] = fc
    return K6, f6, (rel, con, Ri, Krc)


def _merge_pieces(out):
    """Members the tab split at tie points (pieces carry the same "group") become one member again, with continuous diagrams."""
    if not any(r.get("group") is not None for r in out):
        return out
    res, seen = [], {}
    for r in out:
        g = r.get("group")
        if g is None:
            res.append(r)
        elif g not in seen:
            seen[g] = [r]
            res.append(g)
        else:
            seen[g].append(r)
    final = []
    for item in res:
        if isinstance(item, dict):
            final.append(item)
            continue
        rs = seen[item]
        r0, r1 = rs[0], rs[-1]
        off, xs = 0.0, []
        for r in rs:
            xs.append(r["x"] + off)
            off += r["L"]
        cat = lambda k: np.concatenate([r[k] for r in rs])
        m = dict(r0)
        N, V, M = cat("N"), cat("V"), cat("M")
        sig = cat("sig")
        dxy = np.concatenate([r["dxy"] for r in rs])
        pk = lambda arr: float(arr[int(np.argmax(np.abs(arr)))])
        smax = float(sig.max())
        sy, su = r0["sy"], r0["su"]
        pcr = math.pi ** 2 * r0["E"] * r0["I"] / off ** 2
        n_min = float(N.min())
        m.update({"id": item, "b": r1["b"], "L": off, "rel_b": r1["rel_b"], "group": None,
                  "F": np.concatenate([r0["F"][:3], r1["F"][3:]]), "d": np.concatenate([r0["d"][:3], r1["d"][3:]]),
                  "x": np.concatenate(xs), "N": N, "V": V, "M": M, "u": cat("u"), "v": cat("v"), "sig_top": cat("sig_top"),
                  "sig_bot": cat("sig_bot"), "sig": sig, "xy0": np.concatenate([r["xy0"] for r in rs]), "dxy": dxy,
                  "N_peak": pk(N), "V_peak": pk(V), "M_peak": pk(M), "sigma_max": smax,
                  "umax": float(np.max(np.hypot(dxy[:, 0], dxy[:, 1]))),
                  "fos_y": float(sy) / smax if sy and sy > 0 and smax > 0 else None,
                  "fos_u": float(su) / smax if su and su > 0 and smax > 0 else None,
                  "pcr": pcr, "euler_ratio": (-n_min / pcr) if n_min < 0 else 0.0, "pieces": len(rs)})
        final.append(m)
    return final


def solve(nodes, members, supports, nodal, n_st=41):
    """nodes {id: (x, y)}; members [dict]; supports {node id: (fix_ux, fix_uy, fix_rz)}; nodal {node id: (fx, fy, mz)}.
    Returns the result dict (see the end of this function).  Raises BeamError."""
    if not members:
        raise BeamError("There are no members to solve.")
    ids = list(nodes)
    index = {nid: i for i, nid in enumerate(ids)}
    ndof = 3 * len(ids)
    K = np.zeros((ndof, ndof))
    P = np.zeros(ndof)
    notes = []
    rot_stiff = [False] * len(ids)
    work = []
    for m in members:
        if m["a"] not in index or m["b"] not in index:
            raise BeamError(f"Member '{m.get('name', m['id'])}' uses a point that is not part of the model.")
        xa, ya, xb, yb, L, c, s = _geometry(nodes, m)
        E, A, I = float(m["E"]), float(m["A"]), float(m["I"])
        if not (E > 0 and A > 0 and I > 0):
            raise BeamError(f"Member '{m.get('name', m['id'])}' needs a positive E, area and moment of inertia.")
        k = local_k(E, A, I, L)
        qg = m.get("qg", (0.0, 0.0))
        ql = m.get("ql", (0.0, 0.0))
        px = qg[0] * c + qg[1] * s + ql[0]
        py = -qg[0] * s + qg[1] * c + ql[1]
        f0 = np.array([-px * L / 2, -py * L / 2, -py * L * L / 12, -px * L / 2, -py * L / 2, py * L * L / 12])
        rel = [i for i, on in ((2, bool(m.get("rel_a"))), (5, bool(m.get("rel_b")))) if on]
        K6, f6, rec = _release_split(k, f0, rel)
        R = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
        T = np.zeros((6, 6))
        T[:3, :3] = R
        T[3:, 3:] = R
        ia, ib = index[m["a"]], index[m["b"]]
        dofs = [3 * ia, 3 * ia + 1, 3 * ia + 2, 3 * ib, 3 * ib + 1, 3 * ib + 2]
        K[np.ix_(dofs, dofs)] += T.T @ K6 @ T
        P[dofs] -= T.T @ f6
        if not m.get("rel_a"):
            rot_stiff[ia] = True
        if not m.get("rel_b"):
            rot_stiff[ib] = True
        work.append({"m": m, "xa": xa, "ya": ya, "xb": xb, "yb": yb, "L": L, "c": c, "s": s, "E": E, "A": A, "I": I, "k": k, "f0": f0,
                     "rel": rel, "rec": rec, "T": T, "dofs": dofs, "px": px, "py": py})
    for nid, (fx, fy, mz) in nodal.items():
        if nid in index:
            P[3 * index[nid]: 3 * index[nid] + 3] += (fx, fy, mz)
    fixed = set()
    user_fixed = set()
    for nid, flags in supports.items():
        if nid not in index:
            continue
        for j in range(3):
            if flags[j]:
                fixed.add(3 * index[nid] + j)
                user_fixed.add(3 * index[nid] + j)
    for i, nid in enumerate(ids):                     # a node where every member end is pinned has no rotational stiffness at all
        if not rot_stiff[i] and (3 * i + 2) not in fixed:
            fixed.add(3 * i + 2)
            mz = nodal.get(nid, (0, 0, 0))[2]
            if mz:
                notes.append(f"A moment applied at a node where every member is pinned cannot be carried and is ignored (node {nid}).")
    free = np.array([d for d in range(ndof) if d not in fixed], dtype=int)
    d = np.zeros(ndof)
    if free.size:
        Kff = K[np.ix_(free, free)]
        dg = np.sqrt(np.abs(np.diag(Kff)))
        dg[dg <= 0] = 1.0
        try:
            w, V = np.linalg.eigh(Kff / np.outer(dg, dg))
            if w[0] < 1e-12 * max(w[-1], 1e-300):
                v = np.abs(V[:, 0] / dg)
                big = sorted({int(free[i]) // 3 for i in np.nonzero(v > 0.3 * v.max())[0]})
                where = ", ".join(str(ids[i]) for i in big[:8])
                vfull = np.zeros(ndof)
                vfull[free] = V[:, 0] / dg
                score = []
                for w_ in work:                       # how far each member moves in the free mode (rotations count where they are stiff)
                    u_ = vfull[w_["dofs"]]
                    rot = [abs(u_[2]) * w_["L"] if 2 not in w_["rel"] else 0.0, abs(u_[5]) * w_["L"] if 5 not in w_["rel"] else 0.0]
                    score.append((max(abs(u_[0]), abs(u_[1]), abs(u_[3]), abs(u_[4]), *rot), w_["m"]))
                top = max((x for x, _ in score), default=0.0)
                moving = [m_ for x, m_ in sorted(score, key=lambda t: -t[0]) if top > 0 and x > 0.3 * top]
                moving = list({m_.get("group", m_["id"]): m_ for m_ in moving}.values())
                names = ", ".join(f"'{m_.get('name', m_['id'])}'" for m_ in moving[:10])
                raise BeamError("The structure is unstable: it can move without deforming (a mechanism, or too few supports). "
                                + (f"Members that move freely: {names}. " if names else "")
                                + "Check the supports, and whether pinned joints leave a member free to swing. "
                                f"Points that move most: {where}. The members and points involved are highlighted in orange on the drawing.",
                                members=[m_.get("group", m_["id"]) for m_ in moving], nodes=[ids[i] for i in big])
        except np.linalg.LinAlgError:
            pass
        try:
            d[free] = np.linalg.solve(Kff, P[free])
        except np.linalg.LinAlgError:
            raise BeamError("The equations could not be solved (the structure is unstable).")
        if not np.all(np.isfinite(d)):
            raise BeamError("The solution is not finite: check the supports and the member properties.")
    Rv = K @ d - P
    reactions = {}
    for nid, flags in supports.items():
        if nid in index:
            i = index[nid]
            reactions[nid] = tuple(float(Rv[3 * i + j]) if flags[j] else 0.0 for j in range(3))
    # --- member results
    out_members = []
    xs_frac = np.linspace(0.0, 1.0, n_st)
    for w_ in work:
        m, L, c, s, E, A, I = w_["m"], w_["L"], w_["c"], w_["s"], w_["E"], w_["A"], w_["I"]
        dl = w_["T"] @ d[w_["dofs"]]
        if w_["rec"] is not None:
            rel, con, Ri, Krc = w_["rec"]
            dl = dl.copy()
            dl[rel] = -Ri @ (Krc @ dl[con] + w_["f0"][rel])
        F = w_["k"] @ dl + w_["f0"]
        for i in w_["rel"]:
            F[i] = 0.0
        px, py = w_["px"], w_["py"]
        x = xs_frac * L
        N = -F[0] - px * x
        Vs = F[1] + py * x
        M = F[1] * x + py * x * x / 2 - F[2]
        xi = xs_frac
        v = (dl[1] * (1 - 3 * xi ** 2 + 2 * xi ** 3) + dl[2] * L * (xi - 2 * xi ** 2 + xi ** 3) + dl[4] * (3 * xi ** 2 - 2 * xi ** 3)
             + dl[5] * L * (-xi ** 2 + xi ** 3) + py * x ** 2 * (L - x) ** 2 / (24 * E * I))
        u = dl[0] * (1 - xi) + dl[3] * xi + px * x * (L - x) / (2 * E * A)
        sig_top = N / A - M * float(m["c_top"]) / I
        sig_bot = N / A + M * float(m["c_bottom"]) / I
        sig = np.maximum(np.abs(sig_top), np.abs(sig_bot))
        xy0 = np.stack([w_["xa"] + c * x, w_["ya"] + s * x], axis=1)
        dxy = np.stack([c * u - s * v, s * u + c * v], axis=1)
        sy, su = m.get("sy"), m.get("su")
        smax = float(sig.max())
        fos_y = float(sy) / smax if sy and sy > 0 and smax > 0 else None
        fos_u = float(su) / smax if su and su > 0 and smax > 0 else None
        pk = lambda arr: float(arr[int(np.argmax(np.abs(arr)))])
        n_min = float(N.min())
        pcr = math.pi ** 2 * E * I / L ** 2
        out_members.append({
            "id": m["id"], "name": m.get("name", str(m["id"])), "a": m["a"], "b": m["b"], "L": L, "c": c, "s": s, "E": E, "A": A, "I": I,
            "c_top": float(m["c_top"]), "c_bottom": float(m["c_bottom"]), "sy": sy, "su": su, "rel_a": bool(m.get("rel_a")),
            "rel_b": bool(m.get("rel_b")), "group": m.get("group"), "F": F, "d": dl, "x": x, "N": N, "V": Vs, "M": M, "u": u, "v": v, "sig_top": sig_top,
            "sig_bot": sig_bot, "sig": sig, "xy0": xy0, "dxy": dxy, "N_peak": pk(N), "V_peak": pk(Vs), "M_peak": pk(M),
            "sigma_max": smax, "umax": float(np.max(np.hypot(dxy[:, 0], dxy[:, 1]))), "fos_y": fos_y, "fos_u": fos_u,
            "pcr": pcr, "euler_ratio": (-n_min / pcr) if n_min < 0 else 0.0, "px": px, "py": py})
    out_members = _merge_pieces(out_members)
    # --- global checks and summaries
    fa = np.zeros(3)
    for nid, (fx, fy, mz) in nodal.items():
        if nid in index:
            x_, y_ = nodes[nid]
            fa += (fx, fy, mz + x_ * fy - y_ * fx)
    for w_ in work:
        L, c, s = w_["L"], w_["c"], w_["s"]
        Fx = (w_["px"] * c - w_["py"] * s) * L
        Fy = (w_["px"] * s + w_["py"] * c) * L
        xm, ym = (w_["xa"] + w_["xb"]) / 2, (w_["ya"] + w_["yb"]) / 2
        fa += (Fx, Fy, xm * Fy - ym * Fx)
    fr = np.zeros(3)
    for nid, (rx, ry, mz) in reactions.items():
        x_, y_ = nodes[nid]
        fr += (rx, ry, mz + x_ * ry - y_ * rx)
    resid = fa + fr
    scale = max(float(np.abs(fa).max()), float(np.abs(fr).max()), 1e-300)
    eq = {"applied": tuple(float(v) for v in fa), "reactions": tuple(float(v) for v in fr),
          "residual": tuple(float(v) for v in resid), "relative": float(np.abs(resid).max() / scale)}
    node_disp = {nid: (float(d[3 * i]), float(d[3 * i + 1]), float(d[3 * i + 2])) for i, nid in enumerate(ids)}
    xy_nodes = {nid: (float(nodes[nid][0]), float(nodes[nid][1])) for nid in ids}
    best = lambda key: max(out_members, key=lambda r: abs(r[key]))
    fy = [r["fos_y"] for r in out_members if r["fos_y"] is not None]
    fu = [r["fos_u"] for r in out_members if r["fos_u"] is not None]
    mem_umax = max(out_members, key=lambda r: r["umax"])
    mem_sig = max(out_members, key=lambda r: r["sigma_max"])
    return {"members": out_members, "nodes": node_disp, "xy": xy_nodes, "reactions": reactions, "equilibrium": eq, "notes": notes,
            "umax": mem_umax["umax"], "umax_member": mem_umax["name"], "sigma_max": mem_sig["sigma_max"], "sigma_member": mem_sig["name"],
            "fos_y": min(fy) if fy else None, "fos_u": min(fu) if fu else None,
            "fos_y_member": next((r["name"] for r in out_members if fy and r["fos_y"] == min(fy)), None),
            "fos_u_member": next((r["name"] for r in out_members if fu and r["fos_u"] == min(fu)), None),
            "N_peak": best("N_peak")["N_peak"], "V_peak": best("V_peak")["V_peak"], "M_peak": best("M_peak")["M_peak"],
            "N_member": best("N_peak")["name"], "V_member": best("V_peak")["name"], "M_member": best("M_peak")["name"],
            "euler_max": max(r["euler_ratio"] for r in out_members), "n_st": n_st}


def scale_result(res, lf, sf, ff):
    """The result in another unit system: lf = new length per old length, sf = stress factor, ff = force factor."""
    if res is None:
        return None
    r = dict(res)
    ml = []
    for m in res["members"]:
        m = dict(m)
        for k in ("L", "c_top", "c_bottom", "umax"):
            m[k] = m[k] * lf
        m["E"], m["sigma_max"] = m["E"] * sf, m["sigma_max"] * sf
        if m.get("sy"):
            m["sy"] = m["sy"] * sf
        if m.get("su"):
            m["su"] = m["su"] * sf
        m["A"], m["I"] = m["A"] * lf ** 2, m["I"] * lf ** 4
        for k in ("x", "u", "v"):
            m[k] = m[k] * lf
        for k in ("xy0", "dxy"):
            m[k] = m[k] * lf
        for k in ("N", "V"):
            m[k] = m[k] * ff
        m["M"] = m["M"] * ff * lf
        for k in ("sig_top", "sig_bot", "sig"):
            m[k] = m[k] * sf
        m["N_peak"], m["V_peak"], m["M_peak"] = m["N_peak"] * ff, m["V_peak"] * ff, m["M_peak"] * ff * lf
        m["pcr"] = m["pcr"] * ff
        F = np.array(m["F"], dtype=float)
        F[[0, 1, 3, 4]] *= ff
        F[[2, 5]] *= ff * lf
        m["F"] = F
        dd = np.array(m["d"], dtype=float)
        dd[[0, 1, 3, 4]] *= lf
        m["d"] = dd
        m["px"], m["py"] = m["px"] * ff / lf, m["py"] * ff / lf
        ml.append(m)
    r["members"] = ml
    r["nodes"] = {k: (v[0] * lf, v[1] * lf, v[2]) for k, v in res["nodes"].items()}
    r["xy"] = {k: (v[0] * lf, v[1] * lf) for k, v in res["xy"].items()}
    r["reactions"] = {k: (v[0] * ff, v[1] * ff, v[2] * ff * lf) for k, v in res["reactions"].items()}
    eq = dict(res["equilibrium"])
    for k in ("applied", "reactions", "residual"):
        a = eq[k]
        eq[k] = (a[0] * ff, a[1] * ff, a[2] * ff * lf)
    r["equilibrium"] = eq
    r["umax"] = res["umax"] * lf
    r["sigma_max"] = res["sigma_max"] * sf
    r["N_peak"], r["V_peak"], r["M_peak"] = res["N_peak"] * ff, res["V_peak"] * ff, res["M_peak"] * ff * lf
    return r


# ----------------------------------------------------------------------------------------------
# self check against textbook results:  python beam1d.py
# ----------------------------------------------------------------------------------------------
def _member(i, a, b, E=200000.0, A=100.0, I=1000.0, **kw):
    d = {"id": i, "name": f"m{i}", "a": a, "b": b, "E": E, "A": A, "I": I, "c_top": 10.0, "c_bottom": 10.0, "sy": 250.0, "su": 400.0}
    d.update(kw)
    return d


def selftest():
    bad = []

    def check(name, got, want, tol=1e-6):
        ok = abs(got - want) <= tol * max(1.0, abs(want))
        print(("ok   " if ok else "FAIL ") + f"{name}: {got:.8g}  (expected {want:.8g})")
        if not ok:
            bad.append(name)
    E, I, A, L = 200000.0, 1000.0, 100.0, 100.0
    # 1. cantilever, tip load P down:  tip deflection P L^3 / 3 E I, reaction moment P L
    P = 1000.0
    r = solve({1: (0, 0), 2: (L, 0)}, [_member(1, 1, 2)], {1: (True, True, True)}, {2: (0.0, -P, 0.0)})
    check("cantilever tip deflection", r["nodes"][2][1], -P * L ** 3 / (3 * E * I))
    check("cantilever tip rotation", r["nodes"][2][2], -P * L ** 2 / (2 * E * I))
    check("cantilever reaction Ry", r["reactions"][1][1], P)
    check("cantilever reaction Mz", r["reactions"][1][2], P * L)
    check("cantilever root moment (sagging +)", r["members"][0]["M"][0], -P * L)
    check("cantilever equilibrium", r["equilibrium"]["relative"], 0.0, 1e-9)
    # 2. simply supported beam, uniform load w down:  mid deflection 5 w L^4 / 384 E I, mid moment w L^2 / 8
    w = 10.0
    r = solve({1: (0, 0), 2: (L, 0)}, [_member(1, 1, 2, qg=(0.0, -w))], {1: (True, True, False), 2: (False, True, False)}, {})
    mem = r["members"][0]
    mid = (len(mem["x"]) - 1) // 2
    check("simply supported mid deflection", mem["v"][mid], -5 * w * L ** 4 / (384 * E * I))
    check("simply supported mid moment", mem["M"][mid], w * L ** 2 / 8)
    check("simply supported end shear", mem["V"][0], w * L / 2)
    check("simply supported reaction", r["reactions"][1][1], w * L / 2)
    # 3. fixed-fixed beam, uniform load: end moment w L^2 / 12 (hogging), mid moment w L^2 / 24, mid deflection w L^4 / 384 E I
    r = solve({1: (0, 0), 2: (L, 0)}, [_member(1, 1, 2, qg=(0.0, -w))], {1: (True, True, True), 2: (True, True, True)}, {})
    mem = r["members"][0]
    mid = (len(mem["x"]) - 1) // 2
    check("fixed-fixed end moment", mem["M"][0], -w * L ** 2 / 12)
    check("fixed-fixed mid moment", mem["M"][mid], w * L ** 2 / 24)
    check("fixed-fixed mid deflection", mem["v"][mid], -w * L ** 4 / (384 * E * I))
    # 4. two-bar truss, all joints pinned: apex load P down at (0, h) over supports at (-a, 0) and (a, 0)
    a_, h_ = 100.0, 100.0
    nodes = {1: (-a_, 0.0), 2: (a_, 0.0), 3: (0.0, h_)}
    ms = [_member(1, 1, 3, rel_a=True, rel_b=True), _member(2, 2, 3, rel_a=True, rel_b=True)]
    r = solve(nodes, ms, {1: (True, True, False), 2: (False, True, False)}, {3: (0.0, -P, 0.0)})
    f_bar = P / 2 * math.hypot(a_, h_) / h_
    check("truss bar 1 axial force (compression)", r["members"][0]["N"][0], -f_bar)
    check("truss bar 2 axial force (compression)", r["members"][1]["N"][0], -f_bar)
    check("truss bar bending moment is zero", abs(r["members"][0]["M"]).max(), 0.0, 1e-6)
    # 5. portal frame under a horizontal load H at the top left, fixed bases, rigid corners, equal columns, stiff beam:
    #    each column carries H/2 and the sway is H h^3 / (24 E I) for an infinitely stiff beam
    hh, ww = 100.0, 200.0
    nodes = {1: (0.0, 0.0), 2: (0.0, hh), 3: (ww, hh), 4: (ww, 0.0)}
    col = dict(I=1000.0, A=1.0e6)                     # a huge area keeps the columns from shortening, so the beam does not rotate
    ms = [_member(1, 1, 2, **col), _member(2, 2, 3, I=1.0e9, A=1.0e6), _member(3, 3, 4, **col)]
    H = 500.0
    r = solve(nodes, ms, {1: (True, True, True), 4: (True, True, True)}, {2: (H, 0.0, 0.0)})
    check("portal frame sway", r["nodes"][2][0], H * hh ** 3 / (24 * E * 1000.0), 1e-4)
    check("portal frame base shear", r["reactions"][1][0], -H / 2, 1e-4)
    # 6. a hinge in the middle of a beam: a pinned-pinned beam made of two members with a pinned joint between them is a mechanism
    nodes = {1: (0.0, 0.0), 2: (L, 0.0), 3: (2 * L, 0.0)}
    ms = [_member(1, 1, 2, rel_b=True), _member(2, 2, 3, rel_a=True)]
    try:
        solve(nodes, ms, {1: (True, True, False), 3: (False, True, False)}, {2: (0.0, -1.0, 0.0)})
        print("FAIL mechanism not detected")
        bad.append("mechanism")
    except BeamError:
        print("ok   mechanism detected")
    # 7. a member split at a tie point (pieces with one "group") gives the same answer as the unsplit member, as ONE member
    nodes = {1: (0.0, 0.0), 2: (0.4 * L, 0.0), 3: (L, 0.0)}
    pieces = [_member((1, 0), 1, 2, group=1, name="beam", qg=(0.0, -w)), _member((1, 1), 2, 3, group=1, name="beam", qg=(0.0, -w))]
    r = solve(nodes, pieces, {1: (True, True, False), 3: (False, True, False)}, {})
    check("tied member count", len(r["members"]), 1)
    mem = r["members"][0]
    check("tied member length", mem["L"], L)
    check("tied member peak moment", mem["M_peak"], w * L ** 2 / 8, 2e-3)
    check("tied member id", mem["id"], 1)
    print("ALL OK" if not bad else "FAILED: " + ", ".join(bad))
    return not bad


if __name__ == "__main__":
    raise SystemExit(0 if selftest() else 1)
