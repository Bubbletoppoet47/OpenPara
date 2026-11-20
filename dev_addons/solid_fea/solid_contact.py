"""
solid_contact.py - the JOINT of an assembly as contact and screws instead of full bonding.  No window.

In an assembly the parts can be fully bonded (see solid_asm: faces that touch share their nodes) or they can be JOINED BY SCREWS.  With screws the faces
between two parts are NOT bonded; they are frictionless contact (the parts press on each other but slide and may open), except for the screw patches:
the patches (faces between two parts that carry a screw) stay bonded, and the force that passes through each of them is the force on the screw.

  split_interfaces(q, geom, bonded, h, mats, sizes)   the mesh with its nodes duplicated on the faces between two parts (one copy for each part, a shared one on
                                               the bonded patches) -> (new mesh, contact), where contact has the node pairs of the contact, the screw patches
                                               and the bodies that hold together
  check_held(nodes, rows, contact)             every group of parts that hold together must be held by a support
  solve_contact(K, free, fixed, force, contact, ...)   an active-set solution: the pairs that press are active (a stiff spring that stops
                                               the penetration), those that would pull are left out, until the set no longer changes
  patch_forces(contact, u, force_body)         the force that every screw patch passes on: the free-body force of the part on its upper side

A contact pair is two nodes at the same place, one of each part, with the normal that points from the first part into the second.  Every pair carries the share
of the face area that belongs to its node (the lumped weights of a 6-node triangle: 1/19 of the area at a corner, 16/57 at a mid-edge node).
Units: mm, N, MPa.
"""
import numpy as np
import scipy.sparse as sp

import solid_fem as fem

PENALTY = 1000.0           # the stiffness of a closed contact, per area: PENALTY x E / h  (the elements around it are about 1000 times softer)
GAP_TOL = 1e-9             # a pair is closed when its gap is below this fraction of the element size
MAX_ITER = 60


def _weights(order):
    """The share of a triangle's area that each of its nodes carries (they add up to 1)."""
    return np.array([1 / 19] * 3 + [16 / 57] * 3) if order == 2 else np.full(3, 1 / 3)


def _union(parent, a, b):
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[max(ra, rb)] = min(ra, rb)


def _find(parent, a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]
        a = parent[a]
    return a


def _normals_into(nodes, tets, tri):
    """(unit normals of the triangles `tri` (corner node ids) pointing into the tetrahedron that has the triangle as a face, areas)."""
    n = len(nodes)
    f = tets[:, [[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]]]
    fs = np.sort(f, axis=2).reshape(-1, 3).astype(np.int64)
    fk = (fs[:, 0] * n + fs[:, 1]) * n + fs[:, 2]
    order = np.argsort(fk)
    fk = fk[order]
    tk = np.sort(tri[:, :3], axis=1).astype(np.int64)
    tk = (tk[:, 0] * n + tk[:, 1]) * n + tk[:, 2]
    pos = np.clip(np.searchsorted(fk, tk), 0, len(fk) - 1)
    if not (fk[pos] == tk).all():
        raise fem.FemError("A triangle on the face between two parts has no element behind it (the mesh of the joint is not conforming).")
    src = order[pos]
    opp = tets[src // 4, src % 4]
    a, b, c = (nodes[tri[:, i]] for i in range(3))
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    nv = cr / np.maximum(2 * area, 1e-300)[:, None]
    away = np.einsum("ij,ij->i", nodes[opp] - a, nv) < 0                     # the opposite node lies on the other side: turn the normal into the element
    nv[away] *= -1
    return nv, area


def bonded_faces(geom, bonded):
    """The face ids of `bonded` that really are faces between two bodies (the others cannot carry a screw)."""
    return [f for f in sorted(bonded) if geom["faces"][f].get("interface") and len(geom["faces"][f]["bodies"]) >= 2]


def split_interfaces(q, geom, bonded, h, mats, sizes=None):
    """q = a quadratic or linear mesh of an assembly (see solid_fem), bonded = the face ids of the screw patches, h = element size, mats = the material of
    every body, sizes = the element size of every body when they differ (the mesh at a face between two bodies has the finer of the two).  Returns
    (q2, contact): q2 is q with the nodes of the faces between two bodies duplicated (q itself is not changed: it is cached), contact is the dict
    described at the top of the file."""
    nodes = np.asarray(q["nodes"], float)
    nn = len(nodes)
    groups = q["groups"]
    faces = geom["faces"]
    order = int(q["order"])
    ftri = q["ftri"]
    nbod = len(geom["bodies"])
    bonded = set(bonded_faces(geom, bonded))
    # --- which bodies use which nodes; the nodes that more than one body uses lie on the faces between bodies
    pn = [np.unique(g["conn"]) for g in groups]
    PN = np.concatenate(pn)
    PB = np.concatenate([np.full(len(u), g["body"]) for u, g in zip(pn, groups)])
    cnt = np.bincount(PN, minlength=nn)
    keep = cnt[PN] > 1
    SN, SB = PN[keep], PB[keep]
    idx = np.lexsort((SB, SN))
    SN, SB = SN[idx], SB[idx]
    # --- ties: the nodes of a bonded patch hold its two bodies together
    ties = {}
    for fid in bonded:
        a, b = faces[fid]["bodies"][:2]
        for n in np.unique(ftri[fid]):
            ties.setdefault(int(n), []).append((a, b))
    src, bod, new = [], [], []
    nxt = nn
    if len(SN):
        cuts = np.flatnonzero(np.diff(SN)) + 1
        for s, e in zip(np.r_[0, cuts], np.r_[cuts, len(SN)]):
            n = int(SN[s])
            bs = [int(x) for x in SB[s:e]]
            t = ties.get(n)
            if not t:
                for b in bs[1:]:
                    src.append(n)
                    bod.append(b)
                    new.append(nxt)
                    nxt += 1
                continue
            parent = {b: b for b in bs}
            for a, b in t:
                if a in parent and b in parent:
                    _union(parent, a, b)
            clusters = {}
            for b in bs:
                clusters.setdefault(_find(parent, b), []).append(b)
            for k, (_r, members) in enumerate(sorted(clusters.items(), key=lambda kv: min(kv[1]))):
                if k == 0:
                    continue                                                  # the cluster of the lowest body keeps the node
                for b in members:
                    src.append(n)
                    bod.append(b)
                    new.append(nxt)
                nxt += 1
    rm = {}
    for b in sorted(set(bod)):
        r = np.arange(nn, dtype=np.int64)
        for s_, b_, n_ in zip(src, bod, new):
            if b_ == b:
                r[s_] = n_
        rm[b] = r
    ident = np.arange(nn, dtype=np.int64)
    rmap = lambda b: rm.get(b, ident)
    nsrc = np.zeros(nxt - nn, np.int64)
    for s_, n_ in zip(src, new):
        nsrc[n_ - nn] = s_
    nodes2 = np.vstack([nodes, nodes[nsrc]]) if len(nsrc) else nodes.copy()
    # --- the contact pairs: every triangle of a face between two bodies that is not a screw patch
    W = _weights(order)
    ncol = len(W)
    pa, pb, pn_, pw, pf, pbd = [], [], [], [], [], []
    tets_of = {g["body"]: g["conn"][:, :4] for g in groups}
    for f in faces:
        fid = f["id"]
        if not f.get("interface") or len(f["bodies"]) < 2 or fid in bonded or fid not in ftri:
            continue
        a, b = f["bodies"][:2]
        tri = np.asarray(ftri[fid])
        nv, area = _normals_into(nodes, tets_of[b], tri[:, :3])
        na, nb = rmap(a)[tri[:, :ncol]].ravel(), rmap(b)[tri[:, :ncol]].ravel()
        w = (area[:, None] * W[None, :ncol]).ravel()
        nrm = np.repeat(nv, ncol, axis=0) * w[:, None]
        sep = na != nb                                                          # a node that is tied (on the border of a patch) has no contact
        if not sep.any():
            continue
        key = np.stack([na[sep], nb[sep]], axis=1)
        uk, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.ravel()
        ws = np.bincount(inv, weights=w[sep], minlength=len(uk))
        ns = np.stack([np.bincount(inv, weights=nrm[sep][:, c], minlength=len(uk)) for c in range(3)], axis=1)
        ln = np.linalg.norm(ns, axis=1)
        ns = ns / np.maximum(ln, 1e-300)[:, None]
        pa.append(uk[:, 0])
        pb.append(uk[:, 1])
        pn_.append(ns)
        pw.append(ws)
        pf.append(np.full(len(uk), fid))
        pbd.append(np.tile([a, b], (len(uk), 1)))
    if pa:
        na_, nb_, nrm_, w_, fid_, bd_ = (np.concatenate(x) for x in (pa, pb, pn_, pw, pf, pbd))
    else:
        na_ = nb_ = fid_ = np.zeros(0, np.int64)
        nrm_ = np.zeros((0, 3))
        w_ = np.zeros(0)
        bd_ = np.zeros((0, 2), np.int64)
    Em = np.array([float(m["E"]) for m in mats])
    hb = np.asarray(sizes, float) if sizes is not None and len(sizes) == nbod else np.full(nbod, float(h))
    h = float(hb.min())                                                              # the finest size is the one the gap tolerance is measured in
    if len(w_):
        hp = np.minimum(hb[bd_[:, 0]], hb[bd_[:, 1]])                                # the element size at a joint: the finer of its two parts
        k_ = PENALTY * np.minimum(Em[bd_[:, 0]], Em[bd_[:, 1]]) / np.maximum(hp, 1e-12) * w_
    else:
        k_ = np.zeros(0)
    # --- the screw patches: the nodes (shared by both bodies) with the share of every patch of a node
    patches = {}
    for fid in sorted(bonded):
        f = faces[fid]
        a, b = f["bodies"][:2]
        tri = np.asarray(ftri[fid])
        nv, area = _normals_into(nodes, tets_of[b], tri[:, :3])
        nd = rmap(b)[tri[:, :ncol]].ravel()
        w = (area[:, None] * W[None, :ncol]).ravel()
        un, inv = np.unique(nd, return_inverse=True)
        ws = np.bincount(inv.ravel(), weights=w, minlength=len(un))
        nsum = (nv * area[:, None]).sum(axis=0)
        patches[fid] = {"a": a, "b": b, "nodes": un, "w": ws, "n": nsum / max(np.linalg.norm(nsum), 1e-300), "area": float(area.sum())}
    tot = {}
    for p in patches.values():
        for n, w in zip(p["nodes"], p["w"]):
            tot[int(n)] = tot.get(int(n), 0.0) + float(w)
    for p in patches.values():
        p["share"] = np.array([w / tot[int(n)] for n, w in zip(p["nodes"], p["w"])])
    # --- which bodies hold together (a screw patch ties its two bodies)
    parent = list(range(nbod))
    for p in patches.values():
        _union(parent, p["a"], p["b"])
    comp = {}
    for b in range(nbod):
        comp.setdefault(_find(parent, b), []).append(b)
    components = sorted(comp.values(), key=lambda c: c[0])
    # --- the new mesh
    groups2 = [dict(g, conn=rmap(g["body"])[g["conn"]]) for g in groups]
    node_body = np.full(len(nodes2), -1, np.int64)
    for g in groups2:
        node_body[np.unique(g["conn"])] = g["body"]
    q2 = dict(q)
    face_body = {f["id"]: f["body"] for f in faces}
    interface = {f["id"] for f in faces if f.get("interface")}

    def remap(d):
        return {fid: (np.asarray(t) if fid in interface else rmap(face_body.get(fid, 0))[np.asarray(t)]) for fid, t in d.items()}
    tet_groups = [g for g in groups2 if g["kind"] == "tet"]
    conn2 = np.vstack([g["conn"] for g in tet_groups])
    q2.update({"nodes": nodes2, "groups": groups2, "conn": conn2, "tets": conn2[:, :4].astype(np.int64), "faces": remap(q["faces"]), "ftri": remap(ftri)})
    if "tri6" in q:
        q2["tri6"] = q2["ftri"]
    contact = {"na": na_, "nb": nb_, "n": nrm_, "w": w_, "k": k_, "fid": fid_, "bodies": bd_, "patches": patches, "components": components,
               "node_body": node_body, "body_names": [b["name"] for b in geom["bodies"]], "h": float(h), "n_orig": nn}
    return q2, contact


def check_held(nodes, rows, contact):
    """Every group of bodies that hold together (through screws) must be held by the supports: rows = [(node, direction)].  A body that only touches
    the others has nothing to stop it sliding (the contact has no friction)."""
    comps = contact["components"]
    of = {b: i for i, c in enumerate(comps) for b in c}
    nb = contact["node_body"]
    by = {}
    for n, d in rows:
        b = int(nb[n])
        if b >= 0:
            by.setdefault(of[b], []).append((n, d))
    names = contact["body_names"]
    for i, c in enumerate(comps):
        r = by.get(i)
        who = ", ".join(names[b] for b in c)
        if not r:
            raise fem.FemError(f"{who} {'has' if len(c) == 1 else 'have'} no support and no screw to a part that is held: with frictionless contact "
                               f"{'it' if len(c) == 1 else 'they'} would slide away. Add a support, or a screw that ties {'it' if len(c) == 1 else 'them'} to a held part.")
        try:
            fem._rigid_check(nodes, r)
        except fem.FemError:
            raise fem.FemError(f"The supports do not hold {who} against every motion (the contact between parts has no friction, so only the supports and "
                               "the screws hold). Add or enlarge a support, or tie it with a screw.")


def _penalty(na, nb, nrm, k, nn):
    """The stiffness matrix k (u_b - u_a) . n  of the contact pairs given (3 nn x 3 nn)."""
    m = len(na)
    if not m:
        return sp.csr_matrix((3 * nn, 3 * nn))
    nn_t = nrm[:, :, None] * nrm[:, None, :] * k[:, None, None]                   # (m, 3, 3)
    ia = 3 * na[:, None] + np.arange(3)[None, :]
    ib = 3 * nb[:, None] + np.arange(3)[None, :]
    rows, cols, vals = [], [], []
    for r_, c_, sgn in ((ia, ia, 1.0), (ib, ib, 1.0), (ia, ib, -1.0), (ib, ia, -1.0)):
        rows.append(np.repeat(r_, 3, axis=1).ravel())
        cols.append(np.tile(c_, (1, 3)).ravel())
        vals.append((sgn * nn_t).ravel())
    return sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(3 * nn, 3 * nn)).tocsr()


def gaps(u, contact):
    """The opening of every contact pair: (u_b - u_a) . n  (negative = the parts overlap)."""
    U = u.reshape(-1, 3)
    return np.einsum("ij,ij->i", U[contact["nb"]] - U[contact["na"]], contact["n"])


def solve_contact(K, free, fixed, force, contact, cancel, progress):
    """The solution with the contact pairs that press (u, K with the final contact springs added, how).  Starts with every pair closed; a pair that would
    pull (a positive gap) is opened, one that overlaps (a negative gap) is closed, until nothing changes.  contact["out"] gets what happened."""
    na, nb, nrm, k = contact["na"], contact["nb"], contact["n"], contact["k"]
    nn = K.shape[0] // 3
    m = len(na)
    active = np.ones(m, bool)
    tol = GAP_TOL * contact["h"]
    seen = {}
    it = 0
    cycled = False
    while True:
        it += 1
        if cancel():
            raise fem.Cancelled()
        Kt = K + _penalty(na[active], nb[active], nrm[active], k[active], nn) if active.any() else K
        Kff = Kt[free][:, free].tocsc()
        progress(f"solving the contact (round {it}, {int(active.sum()):,} of {m:,} node pairs closed)")
        uf, how = fem.solve_system(Kff, force[free], symmetric=True, progress=progress, cancel=cancel, extent=contact.get("extent"))
        u = np.zeros(3 * nn)
        u[free] = uf
        if not m:
            break
        g = gaps(u, contact)
        new = g < tol
        if (new == active).all():
            break
        sig = hash(new.tobytes())
        if sig in seen or it >= MAX_ITER:
            cycled = True                                                          # the set goes round in a circle: keep the last one
            break
        seen[sig] = it
        active = new
    g = gaps(u, contact) if m else np.zeros(0)
    closed = active
    w = contact["w"]
    force_n = float((k[closed] * -g[closed] if closed.any() else np.zeros(0)).sum())      # the contact force (N) carried by the closed pairs
    by = {}
    for (a, b), wi, c, gi, ki in zip(map(tuple, contact["bodies"]), w, closed, g, k):
        r = by.setdefault((int(a), int(b)), {"a": int(a), "b": int(b), "area": 0.0, "closed_area": 0.0, "force": 0.0, "gap_max": 0.0})
        r["area"] += float(wi)
        if c:
            r["closed_area"] += float(wi)
            r["force"] += float(ki * -gi)
        else:
            r["gap_max"] = max(r["gap_max"], float(gi))
    contact["out"] = {"iterations": it, "converged": not cycled, "pairs": int(m), "closed": int(closed.sum()), "force": force_n, "gap": g, "active": closed,
                      "joints": [by[k_] for k_ in sorted(by)]}
    Kfinal = Kt if m else K
    return u, Kfinal, how


def patch_forces(contact, u, force_body):
    """{face id: {"F": force (N) that the screw patch passes on from the first body to the second, as a vector, "n": normal (into the second body),
    "T": tension (N, positive when the patch pulls the two bodies together), "V": shear (N), "a", "b", "area"}}.
    It is the free-body force on the second body at the patch nodes: what its elements push on the nodes minus the loads that are on those nodes.
    force_body = {body: nodal load vector (3 nn) of that body's own loads}."""
    Kb = contact["K_body"]
    out = {}
    cache = {}
    for fid, p in contact["patches"].items():
        b = p["b"]
        if b not in cache:
            cache[b] = Kb[b] @ u - force_body.get(b, 0.0)
        r = cache[b].reshape(-1, 3)[p["nodes"]]
        F = (r * p["share"][:, None]).sum(axis=0)                                 # what the patch exerts on body b
        n = p["n"]
        t = -float(F @ n)                                                           # F toward the first body (-n) = the patch pulls b back = tension
        v = float(np.linalg.norm(F - (F @ n) * n))
        out[fid] = {"F": F, "n": n, "T": t, "V": v, "a": p["a"], "b": b, "area": p["area"]}
    return out
