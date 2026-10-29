"""
Physics Calc - 2D linear-elastic finite elements.

  * 3-node constant-strain triangles (linear) or 6-node quadratic triangles (mid-edge nodes are added here, so every other
    part of the program keeps working with the corner-node mesh), plane stress or plane strain
  * one isotropic material for the whole mesh
  * supports: ux = 0, uy = 0 or both, on points or along curves; bolts and screws (a fixed patch of a given width on the edge,
    a screw holds one way only); frictionless one-way contact against a surface
  * a one-way support is found by an active-set iteration (supports that would have to pull are released)
  * loads: point forces, edge pressure (normal), edge traction (fixed direction)
  * direct sparse solve (no iteration, no tolerance), stresses are the raw element values - nothing is averaged

Units are whatever you use consistently: lengths in sketch units, E in force / length^2, thickness in sketch units,
point forces in force, pressure / traction in force / length^2.  A point force is the total force through the thickness.
"""
import time
import warnings

import numpy as np

import physics_solve as psolve


class Cancelled(Exception):
    pass


class ModelError(Exception):
    pass


def D_matrix(E, nu, mode):
    if mode == "strain":
        f = E / ((1 + nu) * (1 - 2 * nu))
        return f * np.array([[1 - nu, nu, 0.0], [nu, 1 - nu, 0.0], [0.0, 0.0, (1 - 2 * nu) / 2]])
    f = E / (1 - nu * nu)
    return f * np.array([[1.0, nu, 0.0], [nu, 1.0, 0.0], [0.0, 0.0, (1 - nu) / 2]])


def D_matrix_arr(E, nu, mode):
    """One D matrix per element: E and nu are arrays of length M -> (M, 3, 3)."""
    E, nu = np.asarray(E, float), np.asarray(nu, float)
    D = np.zeros((len(E), 3, 3))
    if mode == "strain":
        f = E / ((1 + nu) * (1 - 2 * nu))
        D[:, 0, 0] = D[:, 1, 1] = f * (1 - nu)
        D[:, 0, 1] = D[:, 1, 0] = f * nu
        D[:, 2, 2] = f * (1 - 2 * nu) / 2
    else:
        f = E / (1 - nu * nu)
        D[:, 0, 0] = D[:, 1, 1] = f
        D[:, 0, 1] = D[:, 1, 0] = f * nu
        D[:, 2, 2] = f * (1 - nu) / 2
    return D


def apply_D(D, eps):
    """Stress from strain: eps (M, 3); D is one 3x3 matrix or one per element (M, 3, 3)."""
    return eps @ D.T if D.ndim == 2 else np.einsum("mjk,mk->mj", D, eps)


def region_material_arrays(mat, mesh):
    """When the sketch has several materials (mat["region_mats"] = {region id: {"E","nu","sy","su"}}): per-triangle arrays
    (E, nu, sy, su), else None.  Regions that have no entry use the material of the tab (mat itself)."""
    rm = mat.get("region_mats")
    tf = mesh.get("tri_face")
    if not rm or tf is None:
        return None
    base = {"E": float(mat["E"]), "nu": float(mat["nu"]), "sy": float(mat.get("sy") or 0.0), "su": float(mat.get("su") or 0.0)}
    table = {}
    for fid, m_ in rm.items():
        table[int(fid)] = {k: float(m_.get(k) or 0.0) if k in ("sy", "su") else float(m_[k]) for k in base}
    if len({tuple(sorted(v.items())) for v in list(table.values()) + [base]}) <= 1:
        return None
    tf = np.asarray(tf)
    out = {k: np.array([table.get(int(f), base)[k] for f in tf], float) for k in base}
    return out


def tri_B(nodes, tris):
    p = nodes[tris]
    x, y = p[:, :, 0], p[:, :, 1]
    b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
    c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
    A = 0.5 * ((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
    if np.any(A <= 0):
        raise ModelError("The mesh has zero-area or inverted triangles.")
    B = np.zeros((len(tris), 3, 6))
    inv = 1.0 / (2 * A)
    for i in range(3):
        B[:, 0, 2 * i] = b[:, i] * inv
        B[:, 1, 2 * i + 1] = c[:, i] * inv
        B[:, 2, 2 * i] = c[:, i] * inv
        B[:, 2, 2 * i + 1] = b[:, i] * inv
    return B, A


# ----------------------------------------------------------------------------------------------
# supports and loads -> nodes
# ----------------------------------------------------------------------------------------------
def entity_nodes(mesh, kind, i, mid=None):
    """Mesh nodes that belong to a sketch point / line / arc / circle.  With `mid` (edge -> mid-edge node) those are included too."""
    if kind == "pt":
        n = mesh["point_node"].get(i)
        return [] if n is None else [n]
    segs = mesh["curve_segs"].get((kind, i), [])
    out = {n for s in segs for n in s}
    if mid:
        for a, b in segs:
            m_ = mid.get((min(a, b), max(a, b)))
            if m_ is not None:
                out.add(m_)
    return sorted(out)


def edge_owner(tris):
    owner = {}
    for t, (a, b, c) in enumerate(tris):
        for u, v in ((a, b), (b, c), (c, a)):
            owner.setdefault((min(u, v), max(u, v)), []).append(t)
    return owner


def out_normal(nodes, tris, owner, na, nb):
    """Outward unit normal of a boundary element edge, or None when the edge is inside the material."""
    ts = owner.get((min(na, nb), max(na, nb)), [])
    if len(ts) != 1:
        return None
    pa, pb = nodes[na], nodes[nb]
    d = pb - pa
    L = float(np.hypot(d[0], d[1]))
    nrm = np.array([d[1], -d[0]]) / L
    cen = nodes[tris[ts[0]]].mean(axis=0)
    if np.dot(nrm, cen - 0.5 * (pa + pb)) > 0:
        nrm = -nrm
    return nrm


def resolve(mesh, supports, loads, mid=None):
    """Turn supports / loads on sketch entities into node data.
    -> fixed {dof: 0.0}, point_forces [(node, fx, fy)], edge_loads [(na, nb, fx_total, fy_total)], notes [str],
       edge_nodal [(na, nb, fax, fay, fbx, fby)]   (CFD loads: force per unit thickness on each end node of an element edge)
       edge load totals are the resultant force of that element edge (already including thickness is done later).
    Bolts, screws and contact supports are handled by resolve_fasteners."""
    nodes, tris = mesh["nodes"], mesh["tris"]
    notes = []
    fixed = {}
    for s in supports:
        if s["mode"] not in ("fixed", "x", "y"):
            continue
        for kind, i in s["targets"]:
            ns = entity_nodes(mesh, kind, i, mid)
            if not ns:
                notes.append(f"Support on {kind} {i}: no mesh nodes there (is its region switched on?).")
            for n in ns:
                if s["mode"] in ("fixed", "x"):
                    fixed[2 * n] = 0.0
                if s["mode"] in ("fixed", "y"):
                    fixed[2 * n + 1] = 0.0
    point_forces = []
    for ld in loads:
        if ld["kind"] == "force":
            for kind, i in ld["targets"]:
                ns = entity_nodes(mesh, kind, i)
                if not ns:
                    notes.append(f"Force on {kind} {i}: no mesh node there.")
                for n in ns:
                    point_forces.append((n, ld["fx"], ld["fy"]))
    owner = edge_owner(tris)                      # edge -> triangles, to find the material side of a boundary segment
    edge_loads = []
    for ld in loads:
        if ld["kind"] not in ("pressure", "traction"):
            continue
        for kind, i in ld["targets"]:
            segs = mesh["curve_segs"].get((kind, i), [])
            if not segs:
                notes.append(f"{ld['kind'].title()} on {kind} {i}: no mesh edges there.")
            for na, nb in segs:
                key = (min(na, nb), max(na, nb))
                ts = owner.get(key, [])
                if len(ts) != 1:
                    notes.append(f"{ld['kind'].title()} on {kind} {i}: an element edge is shared by {len(ts)} triangles "
                                 "(inside the material), so it was skipped.")
                    continue
                pa, pb = nodes[na], nodes[nb]
                d = pb - pa
                L = float(np.hypot(d[0], d[1]))
                nrm = out_normal(nodes, tris, owner, na, nb)
                if ld["kind"] == "pressure":
                    f = -ld["p"] * nrm * L                       # positive pressure pushes into the body
                else:
                    f = np.array([ld["tx"], ld["ty"]]) * L
                edge_loads.append((na, nb, float(f[0]), float(f[1])))
    edge_nodal = []
    for ld in loads:
        if ld["kind"] == "cfd":
            for pair in ld["pairs"]:
                edge_nodal += cfd_edge_loads(mesh, owner, pair, ld["include_shear"], notes)
    return fixed, point_forces, edge_loads, notes, edge_nodal


# ----------------------------------------------------------------------------------------------
# bolts, screws and contact supports
# ----------------------------------------------------------------------------------------------
KINDS_FASTENER = ("bolt", "screw", "contact")


def walk_patch(mesh, start, half, mid=None):
    """Nodes within `half` (arc length along the sketch edge) of mesh node `start`, walking along every line / arc / circle that
    passes through it.  -> ({node: arc distance}, [element edges (na, nb) that touch the patch])."""
    nodes = mesh["nodes"]
    tol = 1e-6 * max(half, 1e-300)
    dist = {start: 0.0}
    used = []
    for key, segs in mesh["curve_segs"].items():
        if key[0] not in ("ln", "ar", "ci") or not any(start in sg for sg in segs):
            continue
        adj = {}
        for a, b in segs:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
        for first in adj.get(start, []):
            prev, cur, s = start, first, 0.0
            seen = {start}
            while True:
                L = float(np.hypot(*(nodes[cur] - nodes[prev])))
                ek = (min(prev, cur), max(prev, cur))
                if mid is not None and ek in mid and s + L / 2 <= half + tol:
                    dist[mid[ek]] = min(dist.get(mid[ek], 1e300), s + L / 2)
                    used.append((prev, cur))
                if s + L > half + tol:
                    break
                s += L
                dist[cur] = min(dist.get(cur, 1e300), s)
                used.append((prev, cur))
                seen.add(cur)
                nxt = [n for n in adj.get(cur, []) if n != prev and n not in seen]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
    return dist, used


def resolve_fasteners(mesh, supports, mid=None):
    """-> (list of groups, notes).  A group is one bolt / screw / contact object:
       {"idx", "mode", "label", "nodes": [..], "normals": {node: (nx, ny)} (the direction the head / the surface is on),
        "d", "target"}.  The normals are outward normals of the body (flipped when the support says so)."""
    nodes, tris = mesh["nodes"], mesh["tris"]
    owner = edge_owner(tris)
    groups, notes = [], []
    for idx, s in enumerate(supports):
        if s["mode"] not in KINDS_FASTENER:
            continue
        sign = -1.0 if s.get("flip") else 1.0
        for kind, i in s["targets"]:
            acc = {}
            nl = []
            if s["mode"] == "contact":
                if kind == "pt":
                    notes.append("A contact support goes on an edge (line / arc / circle), not on a point.")
                    continue
                segs = mesh["curve_segs"].get((kind, i), [])
                members = set()
                for a, b in segs:
                    nrm = out_normal(nodes, tris, owner, a, b)
                    if nrm is None:
                        continue
                    m_ = mid.get((min(a, b), max(a, b))) if mid else None
                    for n in (a, b) + ((m_,) if m_ is not None else ()):
                        acc[n] = acc.get(n, 0.0) + nrm
                        members.add(n)
                label = f"{kind} {i}"
                d = None
            else:
                if kind != "pt":
                    notes.append(f"A {s['mode']} goes on a sketch point, not on {kind} {i}.")
                    continue
                n0 = mesh["point_node"].get(i)
                if n0 is None:
                    notes.append(f"{s['mode'].title()} at point {i}: no mesh node there (is its region switched on?).")
                    continue
                d = float(s["d"])
                dist, used = walk_patch(mesh, n0, 0.5 * d, mid)
                for a, b in used:
                    nrm = out_normal(nodes, tris, owner, a, b)
                    if nrm is None:
                        continue
                    m_ = mid.get((min(a, b), max(a, b))) if mid else None
                    for n in (a, b) + ((m_,) if m_ is not None else ()):
                        if n in dist:
                            acc[n] = acc.get(n, 0.0) + nrm
                members = set(dist)
                label = f"point {i}"
                if len(members) < 3:
                    notes.append(f"{s['mode'].title()} at point {i}: the width {d:g} reaches only {len(members)} mesh node(s). "
                                 f"Use an element size of about {d / 4:g} or smaller near it (or a wider head).")
            normals = {}
            for n in members:
                v = acc.get(n)
                if v is None or float(np.hypot(*v)) < 1e-12:
                    continue
                v = v / float(np.hypot(*v)) * sign
                normals[n] = (float(v[0]), float(v[1]))
            if not normals:
                notes.append(f"{s['mode'].title()} on {label}: no boundary edge found there, so it does nothing.")
                continue
            groups.append({"idx": idx, "mode": s["mode"], "label": label, "nodes": sorted(normals), "normals": normals,
                           "d": d, "target": (kind, i), "flip": bool(s.get("flip"))})
    return groups, notes


def cfd_edge_loads(mesh, owner, pair, include_shear, notes):
    """Pressure (and optionally wall shear) from a CFD result on the mesh edges of one sketch edge.
    Both are interpolated by position along the edge - linear over each element edge, no averaging."""
    import physics_cfd as pcfd
    nodes, tris = mesh["nodes"], mesh["tris"]
    kind, i = pair["target"]
    segs = mesh["curve_segs"].get((kind, i), [])
    name = f"{kind} {i}"
    if not segs:
        notes.append(f"CFD load on {name}: no mesh edges there.")
        return []
    table, g, factor, closed = pair["table"], pair["fea_geom"], pair["factor"], pair["closed"]
    out = []
    tot_p = np.zeros(2)
    tot_s = np.zeros(2)
    skipped = 0
    for na, nb in segs:
        key = (min(na, nb), max(na, nb))
        ts = owner.get(key, [])
        if len(ts) != 1:
            skipped += 1
            continue
        pa, pb = nodes[na], nodes[nb]
        d = pb - pa
        L = float(np.hypot(d[0], d[1]))
        nrm = np.array([d[1], -d[0]]) / L
        cen = nodes[tris[ts[0]]].mean(axis=0)
        if np.dot(nrm, cen - 0.5 * (pa + pb)) > 0:
            nrm = -nrm                                            # outward normal of the body
        sa, sb = pcfd.wall_segments_param(g, nodes, [na], [nb])
        pr_a, tax, tay = pcfd.sample_wall(table, float(sa[0]), closed)
        pr_b, tbx, tby = pcfd.sample_wall(table, float(sb[0]), closed)
        pr_a, pr_b = pr_a * factor, pr_b * factor
        fa = -nrm * (L / 6.0) * (2 * pr_a + pr_b)                 # positive pressure pushes into the body
        fb = -nrm * (L / 6.0) * (pr_a + 2 * pr_b)
        tot_p += fa + fb
        if include_shear:
            sh_a = np.array([tax, tay]) * factor
            sh_b = np.array([tbx, tby]) * factor
            fsa = (L / 6.0) * (2 * sh_a + sh_b)
            fsb = (L / 6.0) * (sh_a + 2 * sh_b)
            tot_s += fsa + fsb
            fa, fb = fa + fsa, fb + fsb
        out.append((na, nb, float(fa[0]), float(fa[1]), float(fb[0]), float(fb[1])))
    msg = (f"CFD load on {name} (from CFD {pair['source'][0]} {pair['source'][1]}): {len(out)} element edge(s), "
           f"pressure resultant per unit thickness ({tot_p[0]:.6g}, {tot_p[1]:.6g})")
    if include_shear:
        msg += f", wall shear resultant ({tot_s[0]:.6g}, {tot_s[1]:.6g})"
    notes.append(msg)
    if skipped:
        notes.append(f"CFD load on {name}: {skipped} element edge(s) lie inside the material and were skipped.")
    return out


# ----------------------------------------------------------------------------------------------
# quadratic (6-node) triangles
# ----------------------------------------------------------------------------------------------
GAUSS3 = np.array([[1 / 6, 1 / 6, 2 / 3], [2 / 3, 1 / 6, 1 / 6], [1 / 6, 2 / 3, 1 / 6]])     # area coordinates, weights 1/3 each
SUB_CENTROIDS = np.array([[2 / 3, 1 / 6, 1 / 6], [1 / 6, 2 / 3, 1 / 6], [1 / 6, 1 / 6, 2 / 3], [1 / 3, 1 / 3, 1 / 3]])
SUB_TRIS = np.array([[0, 3, 5], [3, 1, 4], [5, 4, 2], [3, 4, 5]])      # the four little triangles of a 6-node triangle


def add_midnodes(nodes, tris):
    """-> all nodes (corners first, then one node in the middle of every element edge), conn (M, 6) with the local order
    corner 0, 1, 2, mid 0-1, mid 1-2, mid 2-0, and {(a, b): mid node} for a < b."""
    N = len(nodes)
    e = np.stack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=1)
    flat = np.sort(e, axis=2).reshape(-1, 2)
    uniq, inv = np.unique(flat, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    mids = 0.5 * (nodes[uniq[:, 0]] + nodes[uniq[:, 1]])
    conn = np.concatenate([tris, (N + inv).reshape(-1, 3)], axis=1)
    mid = {(int(a), int(b)): N + k for k, (a, b) in enumerate(uniq)}
    return np.vstack([nodes, mids]), conn, mid


def t6_dN(L):
    """d N_i / d L_k for the 6 shape functions at area coordinates L (3,) -> (6, 3)."""
    l1, l2, l3 = L
    return np.array([[4 * l1 - 1, 0, 0], [0, 4 * l2 - 1, 0], [0, 0, 4 * l3 - 1],
                     [4 * l2, 4 * l1, 0], [0, 4 * l3, 4 * l2], [4 * l3, 0, 4 * l1]])


def t6_B(nodes, tris, L):
    """Strain-displacement matrices (M, 3, 12) of the straight-sided 6-node triangles at area coordinates L, and the areas."""
    p = nodes[tris]
    x, y = p[:, :, 0], p[:, :, 1]
    b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
    c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
    A = 0.5 * ((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
    if np.any(A <= 0):
        raise ModelError("The mesh has zero-area or inverted triangles.")
    G = t6_dN(L)
    dNdx = np.einsum("ik,mk->mi", G, b) / (2 * A)[:, None]
    dNdy = np.einsum("ik,mk->mi", G, c) / (2 * A)[:, None]
    B = np.zeros((len(tris), 3, 12))
    B[:, 0, 0::2] = dNdx
    B[:, 1, 1::2] = dNdy
    B[:, 2, 0::2] = dNdy
    B[:, 2, 1::2] = dNdx
    return B, A


def display_mesh(mesh, nodes_all, conn, mid):
    """The mesh the quadratic result lives on: every 6-node triangle drawn as four small ones.  Corner nodes keep their numbers."""
    sub = conn[:, SUB_TRIS].reshape(-1, 3)
    segs = {}
    for key, ss in mesh["curve_segs"].items():
        out = []
        for a, b in ss:
            m_ = mid[(min(a, b), max(a, b))]
            out += [(a, m_), (m_, b)]
        segs[key] = out
    d = dict(mesh)
    d.update({"nodes": nodes_all, "tris": sub, "curve_segs": segs, "parent": np.repeat(np.arange(len(conn)), 4), "quadratic": True})
    return d


# ----------------------------------------------------------------------------------------------
# probe regions: the average stress over an area of the ORIGINAL geometry
# ----------------------------------------------------------------------------------------------
def probe_masks(probes, tri_nodes, tri_conn):
    """-> list of (boolean mask over the result triangles, their areas).  A triangle belongs to a probe when its centroid
    (in the original, undeformed geometry) lies inside the rectangle or circle."""
    xy = np.asarray(tri_nodes)[:, :2]
    c = xy[tri_conn].mean(axis=1)
    p0, p1, p2 = xy[tri_conn[:, 0]], xy[tri_conn[:, 1]], xy[tri_conn[:, 2]]
    area = 0.5 * np.abs((p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - (p2[:, 0] - p0[:, 0]) * (p1[:, 1] - p0[:, 1]))
    out = []
    for pr in probes:
        if pr.get("shape") == "circle":
            m = (c[:, 0] - pr["cx"]) ** 2 + (c[:, 1] - pr["cy"]) ** 2 <= pr["r"] ** 2
        else:
            x0, x1 = sorted((pr["x0"], pr["x1"]))
            y0, y1 = sorted((pr["y0"], pr["y1"]))
            m = (c[:, 0] >= x0) & (c[:, 0] <= x1) & (c[:, 1] >= y0) & (c[:, 1] <= y1)
        out.append((m, area))
    return out


def probe_stats(probes, masks, vm, peeq=None):
    """Area-weighted average and peak von Mises stress (and the largest plastic strain) in every probe."""
    res = []
    for pr, (m, area) in zip(probes, masks):
        n = int(m.sum())
        if n == 0 or float(area[m].sum()) <= 0:
            res.append({"name": pr["name"], "n": 0, "area": 0.0, "avg_vm": None, "max_vm": None, "peeq_max": None})
            continue
        a = area[m]
        res.append({"name": pr["name"], "n": n, "area": float(a.sum()), "avg_vm": float(np.sum(vm[m] * a) / a.sum()),
                    "max_vm": float(vm[m].max()), "peeq_max": (float(np.max(peeq[m])) if peeq is not None else 0.0)})
    return res


def effective_material(mat):
    """The material the solver really uses.  With a profile (ribbed panel idealised as a thin strip, see section_props.py):
    E_eff = rho E keeps EA and EI of the real panel, and the strengths are divided by the stress factor k, so that the strip's
    stress compared with the scaled strength equals the real extreme-fibre stress compared with the real strength."""
    pr = mat.get("profile")
    if not pr:
        return mat
    rho, h, c = float(pr["rho"]), float(pr["h"]), float(pr["c"])
    k = 2.0 * c / (rho * h)
    m = dict(mat)
    m["E"] = float(mat["E"]) * rho
    for key in ("sy", "su"):
        if mat.get(key):
            m[key] = float(mat[key]) / k
    if mat.get("eps_u"):
        m["eps_u"] = float(mat["eps_u"]) * h / (2.0 * c)      # same curvature at the same strain level (keeps the yield strain consistent)
    m["profile_k"] = k
    return m


def apply_probes(res, mesh, probes, fos_name, trig_name=None):
    """Recomputes the probe averages and the factors of safety of a finished result for new probes (no new solve)."""
    vmesh = res.get("mesh") or mesh
    probes = [dict(q) for q in probes]
    masks = probe_masks(probes, vmesh["nodes"], vmesh["tris"]) if probes else []
    ps = probe_stats(probes, masks, res["vm"], res.get("peeq"))
    mat = res["mat"]
    if res.get("multi_material"):                  # per-element strengths: the factors stay as the solve gave them
        res["probes"], res["fos_probe"] = ps, None
        mat["probes"], mat["probe_fos"], mat["probe_trig"] = probes, fos_name, trig_name
        return res
    me = effective_material(mat)
    sy_, su_ = float(me.get("sy") or 0.0), float(me.get("su") or 0.0)
    fp = next((q for q in ps if q["name"] == fos_name and q["avg_vm"]), None)
    vmax = float(np.max(res["vm"]))
    vf = fp["avg_vm"] if fp else vmax
    res["probes"], res["fos_probe"] = ps, (fp["name"] if fp else None)
    res["fos_yield"] = sy_ / vf if sy_ > 0 and vf > 0 else None
    res["fos_ult"] = su_ / vf if su_ > 0 and vf > 0 else None
    res["fos_yield_peak"] = sy_ / vmax if sy_ > 0 and vmax > 0 else None
    res["fos_ult_peak"] = su_ / vmax if su_ > 0 and vmax > 0 else None
    mat["probes"], mat["probe_fos"], mat["probe_trig"] = probes, fos_name, trig_name
    return res


# ----------------------------------------------------------------------------------------------
# solve
# ----------------------------------------------------------------------------------------------
def check_rigid_body(nodes, tris, fixed_idx, extra=()):
    """Raises ModelError when the supports leave a separate part of the mesh free to slide or turn as a rigid body
    (the displacement would then be arbitrary).  Rotation is taken about the centroid of each part.
    `extra` = [(node, dx, dy)]: a node that is held along the direction (dx, dy) only (one-way and sideways supports)."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    N = len(nodes)
    a = np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2]])
    b = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0]])
    nc, lab = connected_components(sp.coo_matrix((np.ones(len(a)), (a, b)), shape=(N, N)), directed=False)
    fixed = np.zeros(2 * N, dtype=bool)
    fixed[fixed_idx] = True
    ex = {}
    for n, dx, dy in extra:
        ex.setdefault(int(n), []).append((dx, dy))
    for c in range(nc):
        idx = np.nonzero(lab == c)[0]
        if len(idx) < 3:
            continue
        cx, cy = nodes[idx].mean(axis=0)
        size = max(float(np.ptp(nodes[idx, 0])), float(np.ptp(nodes[idx, 1])), 1e-12)
        rows = []
        for n in idx:
            if fixed[2 * n]:
                rows.append([1.0, 0.0, -(nodes[n, 1] - cy) / size])
            if fixed[2 * n + 1]:
                rows.append([0.0, 1.0, (nodes[n, 0] - cx) / size])
            for dx, dy in ex.get(int(n), ()):
                rows.append([dx, dy, (-dx * (nodes[n, 1] - cy) + dy * (nodes[n, 0] - cx)) / size])
        where = f"the part around ({cx:.4g}, {cy:.4g})" if nc > 1 else "the body"
        if not rows:
            raise ModelError(f"No support holds {where}: it is free to fly away. Add a support on it.")
        R = np.array(rows)
        sv = np.linalg.svd(R, compute_uv=False)
        rank = int(np.sum(sv > 1e-6 * sv[0]))
        if rank < 3:
            free = []
            if not np.any(np.abs(R[:, 0]) > 1e-12):
                free.append("slide in x")
            if not np.any(np.abs(R[:, 1]) > 1e-12):
                free.append("slide in y")
            if not free:
                free.append("turn (or slide) as a rigid body, for example about the only supported point or along a line of supports")
            raise ModelError(f"The supports do not stop rigid-body motion of {where}: it can still " + " and ".join(free) +
                             ". The displacement would be arbitrary. Hold it in x and in y and stop it turning, e.g. 'Fixed' on "
                             "an edge, or a point fixed plus a second support that is not in line with it.")


def _constrained_solve(K, f, N, fixed_global, rules, cancel=None, rb=None):
    """Solves K u = f with
         fixed_global : sorted array of dofs held at zero (ux or uy of a node);
         rules        : {node: {"n": (nx, ny), "normal": "fixed" | "oneway" | None, "tang": "fixed" | None}}
                        at those nodes the dofs are turned to (along n, along t = (-ny, nx)); "oneway" means u.n <= 0 (the node may
                        move away from the head / surface along -n, never along +n) and is found by an active-set iteration.
    -> u (global), react (global force of the supports on the body), info."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla
    nd = 2 * N
    if rules:
        rows, cols, vals = [], [], []
        rn = np.array(sorted(rules), dtype=np.int64)
        mask_rot = np.zeros(N, dtype=bool)
        mask_rot[rn] = True
        keep = np.nonzero(~mask_rot)[0]
        for k in (0, 1):
            rows.append(2 * keep + k)
            cols.append(2 * keep + k)
            vals.append(np.ones(len(keep)))
        nv = np.array([rules[int(n)]["n"] for n in rn])
        rows += [2 * rn, 2 * rn, 2 * rn + 1, 2 * rn + 1]
        cols += [2 * rn, 2 * rn + 1, 2 * rn, 2 * rn + 1]
        vals += [nv[:, 0], nv[:, 1], -nv[:, 1], nv[:, 0]]
        T = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(nd, nd)).tocsr()
        Kl = (T @ K @ T.T).tocsr()
        fl = T @ f
    else:
        rn = np.zeros(0, dtype=np.int64)
        T, Kl, fl = None, K, f
    base = set(int(d) for d in fixed_global)
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
    fscale = float(np.max(np.abs(fl))) or 1.0
    info = {"iterations": 0, "oneway": len(one), "released": 0, "cycled": False}
    u = np.zeros(nd)
    for it in range(80):
        if cancel and cancel():
            raise Cancelled()
        fix = np.array(sorted(base | active), dtype=np.int64)
        if one and rb is not None:                 # with some one-way nodes released, is the body still held?
            try:
                rb(fix)
            except ModelError:
                raise ModelError("The one-way supports (screws / contact) cannot hold the body for this load: with the nodes "
                                 "that would have to pull released, part of it is free to move away. Add a contact support on "
                                 "the other side, or a bolt, so the body is held in both directions.")
        mask = np.ones(nd, dtype=bool)
        mask[fix] = False
        free = np.nonzero(mask)[0]
        u = np.zeros(nd)
        Kff = Kl[free][:, free].tocsc()
        with warnings.catch_warnings():
            warnings.simplefilter("error", category=spla.MatrixRankWarning)
            try:
                u[free] = psolve.solve(Kff, fl[free])
            except spla.MatrixRankWarning:
                if one:
                    raise ModelError("The one-way supports (screws / contact) cannot hold the body for this load: with the nodes "
                                     "that would have to pull released, part of it is free to move away. Add a contact support on "
                                     "the other side, or a bolt, so the body is held in both directions.")
                raise ModelError("The stiffness matrix is singular: the supports do not stop rigid-body motion "
                                 "(or part of the mesh is not connected to a support).")
        info["iterations"] = it + 1
        if not one:
            break
        react = Kl @ u - fl
        tolR = 1e-9 * fscale
        umax = float(np.max(np.abs(u))) or 1.0
        tolU = 1e-9 * umax
        rel = {d for d in active if react[d] > tolR}
        cap = {d for d in one if d not in active and u[d] > tolU}
        if not rel and not cap:
            break
        active = (active - rel) | cap
        info["released"] = len(set(one) - active)
        if it == 79:
            info["cycled"] = True
    # soft or thin models are badly conditioned: polish the final solution with up to two steps of iterative refinement
    fix = np.array(sorted(base | active), dtype=np.int64)
    mask = np.ones(nd, dtype=bool)
    mask[fix] = False
    free = np.nonzero(mask)[0]
    Kff = Kl[free][:, free].tocsc()
    fn = float(np.linalg.norm(fl[free])) or 1.0
    info["refined"] = 0
    for _ in range(2):
        rr = fl[free] - Kff @ u[free]
        if float(np.linalg.norm(rr)) <= 1e-11 * fn:
            break
        try:
            du = psolve.solve(Kff, rr)
        except Exception:
            break
        if not np.all(np.isfinite(du)):
            break
        u[free] += du
        info["refined"] += 1
    react = Kl @ u - fl
    fixmask = np.zeros(nd, dtype=bool)
    fixmask[np.array(sorted(base | active), dtype=np.int64)] = True
    react[~fixmask] = 0.0
    if T is not None:
        u = T.T @ u
        react = T.T @ react
    info["released"] = len(set(one) - active)
    info["fixed_dofs"] = int(fixmask.sum())
    info["active_oneway_nodes"] = sorted(d // 2 for d in active)
    return u, react, info, fixmask


def solve(mesh, mat, supports, loads, progress=None, cancel=None):
    """Assemble, apply supports, solve, recover stresses.  -> result dict (everything the display and the report need).
    mat["order"] = 2 uses quadratic triangles (the stress is then given on the four small triangles of every element and
    result["mesh"] is the mesh to draw it on); 1 or missing uses the 3-node triangles."""
    import scipy.sparse as sp

    def tick(txt, f):
        if cancel and cancel():
            raise Cancelled()
        if progress:
            progress(txt, f)

    times = {}
    t0 = time.perf_counter()
    nodes, tris = mesh["nodes"], mesh["tris"]
    mat_in = mat
    mat = effective_material(mat)                         # a profile idealisation changes E and the strengths (see above)
    order = int(mat.get("order", 1))
    E, nu, th, mode = mat["E"], mat["nu"], mat["t"], mat["mode"]
    multi = region_material_arrays(mat, mesh)             # several materials in one sketch (an assembly slice): per element
    if multi is not None:
        if np.any(multi["E"] <= 0):
            raise ModelError("Every material needs E > 0.")
        lim = (-1, 0.5) if mode == "strain" else (-1, 1)
        if np.any(multi["nu"] <= lim[0]) or np.any(multi["nu"] >= lim[1]):
            raise ModelError(f"Poisson's ratio of a material is outside the allowed range ({lim[0]} .. {lim[1]}) for plane {mode}.")
    if E <= 0 or th <= 0:
        raise ModelError("E and the thickness must be positive.")
    if mode == "strain" and not (-1 < nu < 0.5):
        raise ModelError("Plane strain needs -1 < nu < 0.5.")
    if mode == "stress" and not (-1 < nu < 1):
        raise ModelError("Plane stress needs -1 < nu < 1.")
    for s in supports:
        if s["mode"] in ("bolt", "screw") and not float(s.get("d", 0)) > 0:
            raise ModelError("A bolt / screw needs a head width greater than zero.")

    tick("Resolving supports and loads", 0.02)
    if order == 2:
        nodes_all, conn, mid = add_midnodes(nodes, tris)
    else:
        nodes_all, conn, mid = nodes, tris, None
    N = len(nodes_all)
    M = len(tris)
    fixed, point_forces, edge_loads, notes, edge_nodal = resolve(mesh, supports, loads, mid)
    groups, fnotes = resolve_fasteners(mesh, supports, mid)
    notes += fnotes
    if mat.get("profile"):
        pr = mat["profile"]
        notes.append(f"PROFILE idealisation '{pr.get('name', '')}': the strip (thickness {pr['h']:.5g}) is given E x {pr['rho']:.4g} so that it "
                     f"has the stiffness of the real panel. The stresses shown are those of the strip: multiply by {mat['profile_k']:.4g} for the "
                     "real extreme-fibre stress. The strengths and the factors of safety already include this factor.")
    if not fixed and not groups:
        raise ModelError("No supports: the body is free to fly away. Add a support first.")
    if not point_forces and not edge_loads and not edge_nodal:
        raise ModelError("No loads. Add a force, pressure or traction first.")

    # bolts fix their nodes; screws and contact supports become rules (rotated dofs, one-way)
    rules = {}
    for g in groups:
        for n in g["nodes"]:
            nx, ny = g["normals"][n]
            if g["mode"] == "bolt":
                fixed[2 * n] = 0.0
                fixed[2 * n + 1] = 0.0
                continue
            if n in rules:
                if g["mode"] == "screw":
                    rules[n].update({"tang": "fixed", "mode": "screw"})       # a screw on a contact patch adds the sideways hold
                continue
            rules[n] = {"n": (nx, ny), "normal": "oneway", "tang": "fixed" if g["mode"] == "screw" else None, "mode": g["mode"]}
    for n in list(rules):                      # a node that is also held in x or y by an ordinary support
        r = rules[n]
        nx, ny = r["n"]
        if 2 * n in fixed and 2 * n + 1 in fixed:
            del rules[n]
            continue
        for comp in (0, 1):
            dof = 2 * n + comp
            if dof not in fixed:
                continue
            e = (1.0, 0.0) if comp == 0 else (0.0, 1.0)
            if abs(-ny * e[0] + nx * e[1]) > 0.999:           # the held direction is the sideways one
                r["tang"] = "fixed"
                del fixed[dof]
            elif abs(nx * e[0] + ny * e[1]) > 0.999:          # the held direction is across the surface
                r["normal"] = "fixed"
                del fixed[dof]
            else:
                notes.append(f"Node {n} has a one-way support at an angle and an x / y support: only the x / y support was used there.")
                del rules[n]
                break
    fixed_idx = np.array(sorted(fixed), dtype=np.int64)

    tick("Element matrices", 0.1)
    D = D_matrix(E, nu, mode) if multi is None else D_matrix_arr(multi["E"], multi["nu"], mode)
    eins = "mji,jk,mkl->mil" if D.ndim == 2 else "mji,mjk,mkl->mil"
    if multi is not None:
        notes.append("SEVERAL MATERIALS in this sketch: each region uses its own E and Poisson's ratio (regions are bonded where they touch). "
                     "The nonlinear solver is not used with several materials, and each element's factor of safety uses its own strengths.")
    if order == 2:
        Ke = np.zeros((M, 12, 12))
        for L in GAUSS3:
            B, A = t6_B(nodes_all, conn, L)
            Ke += (th / 3.0) * A[:, None, None] * np.einsum(eins, B, D, B)
        nd_el = 12
        dofs = (conn[:, np.repeat(np.arange(6), 2)] * 2 + np.tile([0, 1], 6)[None, :])
    else:
        B, A = tri_B(nodes, tris)
        Ke = th * A[:, None, None] * np.einsum(eins, B, D, B)
        nd_el = 6
        dofs = (tris[:, [0, 0, 1, 1, 2, 2]] * 2 + np.array([0, 1, 0, 1, 0, 1])[None, :])
    rows = np.broadcast_to(dofs[:, :, None], (M, nd_el, nd_el)).ravel()
    cols = np.broadcast_to(dofs[:, None, :], (M, nd_el, nd_el)).ravel()
    tick("Assembling the stiffness matrix", 0.25)
    K = sp.coo_matrix((Ke.ravel(), (rows, cols)), shape=(2 * N, 2 * N)).tocsr()
    times["assemble"] = time.perf_counter() - t0

    f = np.zeros(2 * N)
    for n, fx, fy in point_forces:
        f[2 * n] += fx
        f[2 * n + 1] += fy
    for na, nb, fx, fy in edge_loads:                             # edge loads: stress-like, so times the thickness
        if order == 2:
            m_ = mid[(min(na, nb), max(na, nb))]
            for n, w in ((na, 1 / 6), (nb, 1 / 6), (m_, 4 / 6)):
                f[2 * n] += w * fx * th
                f[2 * n + 1] += w * fy * th
        else:
            for n in (na, nb):
                f[2 * n] += 0.5 * fx * th
                f[2 * n + 1] += 0.5 * fy * th
    for na, nb, fax, fay, fbx, fby in edge_nodal:                 # CFD loads: already a force per unit thickness at each node
        if order == 2:
            m_ = mid[(min(na, nb), max(na, nb))]
            f[2 * na] += (2 * fax - fbx) / 3 * th
            f[2 * na + 1] += (2 * fay - fby) / 3 * th
            f[2 * nb] += (2 * fbx - fax) / 3 * th
            f[2 * nb + 1] += (2 * fby - fay) / 3 * th
            f[2 * m_] += 2 * (fax + fbx) / 3 * th
            f[2 * m_ + 1] += 2 * (fay + fby) / 3 * th
        else:
            f[2 * na] += fax * th
            f[2 * na + 1] += fay * th
            f[2 * nb] += fbx * th
            f[2 * nb + 1] += fby * th

    tick("Applying supports", 0.4)
    extra = []
    for n, r in rules.items():
        nx, ny = r["n"]
        extra.append((n, nx, ny))
        if r.get("tang") == "fixed":
            extra.append((n, -ny, nx))
    check_rigid_body(nodes_all, tris, fixed_idx, extra)
    tick("Solving K u = f (direct sparse solve)" + (", one-way supports iterated" if any(
        r["normal"] == "oneway" for r in rules.values()) else ""), 0.5)
    t1 = time.perf_counter()
    def rb(fix_local):
        plain = [d for d in fix_local if d // 2 not in rules]
        ex = []
        for d in fix_local:
            n = d // 2
            if n in rules:
                nx, ny = rules[n]["n"]
                ex.append((n, nx, ny) if d % 2 == 0 else (n, -ny, nx))
        check_rigid_body(nodes_all, tris, np.array(plain, dtype=np.int64), ex)
    u, react, info, fixmask = _constrained_solve(K, f, N, fixed_idx, rules, cancel, rb)
    times["solve"] = time.perf_counter() - t1
    if not np.all(np.isfinite(u)):
        raise ModelError("The solution contains NaN or infinity (singular or badly conditioned system).")
    if info["cycled"]:
        notes.append("WARNING: the one-way supports (screws / contact) did not settle after 80 iterations; the result may be "
                     "partly wrong. Try a finer mesh near them or a smaller load step.")
    if rules and info["oneway"]:
        notes.append(f"One-way supports: {info['oneway']} node(s), {info['oneway'] - info['released']} holding and "
                     f"{info['released']} released (they would have had to pull); {info['iterations']} iteration(s).")

    tick("Reactions and residual", 0.8)
    Rfull = react
    free_idx = np.nonzero(~fixmask)[0] if not rules else np.nonzero(np.abs(react) == 0)[0]
    Ku = K @ u
    r_free = (Ku - f)
    r_free[Rfull != 0] = 0.0                                      # supported dofs (global) carry the reaction
    # normwise backward error |K u - f| / (|K| |u| + |f|): a thin, soft model has |K||u| much larger than |f|, so comparing the
    # residual with |f| alone would call every rounding error a failure
    knorm = float(abs(K).sum(axis=0).max())
    denom = knorm * float(np.max(np.abs(u))) + float(np.max(np.abs(f)))
    residual = float(np.linalg.norm(r_free, np.inf) / (denom or 1.0))
    if residual > 1e-6:
        notes.append(f"WARNING: the solve residual is {residual:.2e} (should be about 1e-10). The result is not reliable: "
                     "check that the supports stop all rigid-body motion.")

    tick("Stresses (per element, not averaged)", 0.9)
    if order == 2:
        ue = u[dofs]
        cols_ = {k: [] for k in ("sx", "sy", "txy")}
        sx = np.zeros((M, 4)); sy = np.zeros((M, 4)); txy = np.zeros((M, 4))
        for j, L in enumerate(SUB_CENTROIDS):
            Bj, _ = t6_B(nodes_all, conn, L)
            sg = apply_D(D, np.einsum("mij,mj->mi", Bj, ue))
            sx[:, j], sy[:, j], txy[:, j] = sg[:, 0], sg[:, 1], sg[:, 2]
        sx, sy, txy = sx.reshape(-1), sy.reshape(-1), txy.reshape(-1)
        A = np.repeat(A, 4) / 4.0
        view = display_mesh(mesh, nodes_all, conn, mid)
    else:
        ue = u[dofs]
        eps = np.einsum("mij,mj->mi", B, ue)
        sig = apply_D(D, eps)
        sx, sy, txy = sig[:, 0], sig[:, 1], sig[:, 2]
        view = None
    # ---- automatic switch to the nonlinear solver (large displacements and yielding) when the linear result says it is needed
    f_lin_applied = f
    solver, nlinfo, trigger, peeq, energy_val, residual_nl = "linear", None, "", None, float(0.5 * u @ f), None
    sy_, su_ = float(mat.get("sy") or 0.0), float(mat.get("su") or 0.0)
    umax_lin = float(np.max(np.hypot(u.reshape(-1, 2)[:, 0], u.reshape(-1, 2)[:, 1])))
    vm_lin = np.sqrt(sx ** 2 - sx * sy + sy ** 2 + 3 * txy ** 2)
    lin_on = mat.get("lin_on", True)
    nl_wanted = bool(mat.get("nl_on")) and multi is None
    if multi is not None and mat.get("nl_on"):
        if not lin_on:
            raise ModelError("The nonlinear solver cannot be used with several materials in one sketch. Tick the linear solver.")
        notes.append("The nonlinear solver was requested, but it is not available with several materials: the LINEAR result is shown.")
    probes = [dict(q) for q in (mat.get("probes") or [])]
    pmasks = None
    if probes:
        if view is not None:
            pmasks = probe_masks(probes, nodes_all, view["tris"])
        else:
            pmasks = probe_masks(probes, mesh["nodes"], mesh["tris"])
    trig_probe = next((i for i, q in enumerate(probes) if q["name"] == mat.get("probe_trig")), None)
    if not lin_on and not nl_wanted:
        raise ModelError("Tick the linear solver, the nonlinear solver, or both.")
    if nl_wanted:
        why = []
        lim = mat.get("nl_disp")
        if not lin_on:
            why.append("nonlinear solver only")
        else:
            if lim and umax_lin > float(lim):
                why.append(f"largest displacement {umax_lin:.4g} > limit {float(lim):.4g}")
            frac = mat.get("nl_yield")
            vm_test, vm_what = float(np.max(vm_lin)), "largest von Mises stress"
            if trig_probe is not None:
                ps = probe_stats(probes, pmasks, vm_lin)[trig_probe]
                if ps["avg_vm"] is None:
                    notes.append(f"WARNING: the trigger probe '{ps['name']}' contains no mesh element, so the largest stress is used.")
                else:
                    vm_test, vm_what = ps["avg_vm"], f"average von Mises stress in probe '{ps['name']}'"
            if frac and sy_ > 0 and vm_test > float(frac) * sy_:
                why.append(f"{vm_what} {vm_test:.4g} > {100 * float(frac):.4g} % of the yield strength {sy_:.4g}")
        if why:
            if order != 2:
                notes.append(("The nonlinear solver was requested (" + "; ".join(why) + ") but it needs the quadratic elements: choose "
                              "'Quadratic' for the element order. The LINEAR result is shown."))
            else:
                import physics_nl as pnl
                tick("Nonlinear solve (large displacements / yielding)", 0.6)
                try:
                    nr = pnl.solve_nonlinear(nodes_all, conn, th, D, f, fixed_idx, rules, mat, u_lin=umax_lin, nl_disp=lim,
                                             cancel=cancel, progress=lambda t, fr: tick(t, fr), geom=True, plastic=(mode == "stress"))
                except RuntimeError:
                    raise Cancelled()
                except pnl.NLFailed as ex:
                    notes.append("WARNING: " + str(ex) + " The linear result is shown instead.")
                    nr = None
                if nr is not None:
                    ni = nr["info"]
                    solver, nlinfo, trigger = "nonlinear", ni, "; ".join(why)
                    u, Rfull_nl, f = nr["u"], nr["react"], nr["f_applied"]
                    sx, sy, txy, peeq = nr["sx"], nr["sy"], nr["txy"], nr["peeq"]
                    energy_val, residual_nl = nr["energy"], ni["residual"]
                    info["fixed_dofs"] = ni["fixed_dofs"]
                    notes.append("NONLINEAR solver used (" + trigger + "): large displacements" +
                                 (" and yielding" if mode == "stress" and sy_ > 0 else "") + f"; {ni['steps']} load steps, "
                                 f"{ni['iterations']} Newton iterations.")
                    if mode == "strain" and sy_ > 0:
                        notes.append("Yielding is not modelled in plane strain: only the large displacements were.")
                    if not ni["converged"]:
                        notes.append(f"WARNING: the nonlinear solve did NOT converge past {100 * ni['load_fraction']:.1f} % of the load. This is the "
                                     "state it reached at that load level, not the full load.")
                    if ni.get("eps_u_reached"):
                        notes.append("WARNING: the plastic strain reached the strain at the ultimate strength in some places: the material "
                                     "would be failing there.")
    Mout = len(sx)
    if multi is not None:
        rep_ = 4 if order == 2 else 1
        nu_o, sy_o, su_o = (np.repeat(multi[k], rep_) for k in ("nu", "sy", "su"))
    else:
        nu_o = nu
    szz = nu_o * (sx + sy) if mode == "strain" else np.zeros(Mout)
    vm = np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - szz) ** 2 + (szz - sx) ** 2) + 3 * txy ** 2)
    pstats = probe_stats(probes, pmasks, vm, peeq) if probes else []
    for ps in pstats:
        if ps["n"] == 0:
            notes.append(f"WARNING: probe '{ps['name']}' contains no mesh element (the centroid of an element must lie inside it).")
    fos_probe = next((ps for ps in pstats if ps["name"] == mat.get("probe_fos") and ps["avg_vm"]), None)
    vm_fos = fos_probe["avg_vm"] if fos_probe else (float(np.max(vm)) if len(vm) else 0.0)
    mid_s = 0.5 * (sx + sy)
    rad = np.sqrt((0.5 * (sx - sy)) ** 2 + txy ** 2)
    s1, s2 = mid_s + rad, mid_s - rad

    # equilibrium of the whole body: applied loads + support reactions must add up to zero
    if solver == "nonlinear":
        Rfull = Rfull_nl
        residual = residual_nl
    total = f + Rfull
    xs, ys = nodes_all[:, 0], nodes_all[:, 1]
    sum_fx, sum_fy = float(total[0::2].sum()), float(total[1::2].sum())
    moment = float(np.sum(xs * total[1::2] - ys * total[0::2]))
    applied = {"fx": float(f[0::2].sum()), "fy": float(f[1::2].sum()),
               "mz": float(np.sum(xs * f[1::2] - ys * f[0::2]))}
    reactions = {"fx": float(Rfull[0::2].sum()), "fy": float(Rfull[1::2].sum()),
                 "mz": float(np.sum(xs * Rfull[1::2] - ys * Rfull[0::2]))}

    # the force each bolt / screw / contact support carries
    fast = []
    for g in groups:
        Rx = Ry = Rn = Rt = 0.0
        held = 0
        for n in g["nodes"]:
            rx, ry = float(Rfull[2 * n]), float(Rfull[2 * n + 1])
            nx, ny = g["normals"][n]
            Rx += rx
            Ry += ry
            Rn += rx * nx + ry * ny
            Rt += -rx * ny + ry * nx
            if rx != 0.0 or ry != 0.0:
                held += 1
        fast.append({"idx": g["idx"], "mode": g["mode"], "label": g["label"], "d": g["d"], "n_nodes": len(g["nodes"]), "n_holding": held,
                     "Rx": Rx, "Ry": Ry, "axial": -Rn, "shear": Rt, "per_depth": {"axial": -Rn / th, "shear": Rt / th},
                     "flip": g["flip"]})
    tick("Done", 1.0)
    fos = {"fos_yield": (sy_ / vm_fos if sy_ > 0 and vm_fos > 0 else None), "fos_ult": (su_ / vm_fos if su_ > 0 and vm_fos > 0 else None),
           "fos_yield_peak": (sy_ / float(np.max(vm)) if sy_ > 0 and float(np.max(vm)) > 0 else None),
           "fos_ult_peak": (su_ / float(np.max(vm)) if su_ > 0 and float(np.max(vm)) > 0 else None)}
    if multi is not None:                                  # each element against its own material: the smallest ratio anywhere
        def worst(strength):
            ok = (strength > 0) & (vm > 0)
            return float(np.min(strength[ok] / vm[ok])) if np.any(ok) else None
        fos = {"fos_yield": worst(sy_o), "fos_ult": worst(su_o), "fos_yield_peak": worst(sy_o), "fos_ult_peak": worst(su_o)}
    return {
        "u": u.reshape(-1, 2), "sx": sx, "sy": sy, "txy": txy, "szz": szz, "vm": vm, "s1": s1, "s2": s2,
        "tmax": rad, "area": A, "mat": dict(mat_in), "f": f, "reaction_on_body": Rfull,
        "energy": float(energy_val), "residual": residual,
        "solver": solver, "trigger": trigger, "nl": nlinfo, "peeq": peeq if peeq is not None else np.zeros(Mout),
        **fos, "multi_material": multi is not None,
        "fos_probe": fos_probe["name"] if fos_probe else None, "probes": pstats,
        "equilibrium": {"sum_fx": sum_fx, "sum_fy": sum_fy, "sum_mz": moment, "applied": applied, "reactions": reactions},
        "n_dof": int(2 * N), "n_fixed": int(info["fixed_dofs"]), "nnz": int(K.nnz),
        "n_point_forces": len(point_forces), "n_edge_loads": len(edge_loads) + len(edge_nodal), "notes": notes, "times": times,
        "total_time": time.perf_counter() - t0,
        "order": order, "mesh": view, "fasteners": fast, "oneway": {k: info[k] for k in ("iterations", "oneway", "released")},
    }
