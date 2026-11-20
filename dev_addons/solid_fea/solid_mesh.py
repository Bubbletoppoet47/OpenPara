"""
solid_mesh.py - the mesh OPTIONS of the 3D FEA (what "Advanced mesh options" of the panel edits) and the quality report of a mesh.  No window.

setup["mesh"] = {
  "advanced": bool,        the options below are used only when this is True (off = the plain automatic mesh: quadratic, minimum size h/6, curvature 10)
  "type":     "tets" | "hexdom",   tetrahedra only, or hex-dominant: a block of hexahedra inside the part, tetrahedra (and the pyramids that join them)
                           between it and the surface.  The surface is meshed patch by patch either way.  A part with no room for hexahedra gets tetrahedra.
  "order":    2 | 1,       2 = quadratic (10-node tetrahedra, 20-node hexahedra), 1 = linear (4-node tetrahedra, 8-node hexahedra)
  "hmin":     mm | 0,      the smallest element edge gmsh may make; 0 = automatic (a sixth of the element size)
  "growth":   > 1,         how fast the elements grow away from a locally refined face (1.3 = each layer of elements 30 % longer than the one before)
  "curv":     0 | 3..100,  refine at curved surfaces: the number of elements around a full circle; 0 = off
  "face_sizes": [{"face": face signature, "h": mm}],    a smaller element size on single faces (a patch of a split face counts as a face)
  "follows":  "patches",   what the mesh follows: the split patches (the mesh edges lie on the patch borders); the only choice so far
}
`options(setup)` is the validated, complete version; `resolve(geom, setup)` also turns the face signatures into face ids of the (rebuilt) part;
`quality(q)` measures a mesh.

The ELEMENT SIZE is not one of these options: a single part has setup["h"] (mm, 0 = automatic), and every part of an assembly can have a size of its own in
setup["body_h"] = {body name: mm} (a part without one gets setup["h"], or the automatic size).  The parts are still meshed as ONE mesh, so the nodes of a face
that two parts share stay shared (bonded): that face gets the finer of the two sizes and the coarser part grows away
from it.  `body_sizes` turns the names into body indexes; `resolve` puts them in the options as "body_h": {body index: mm}.
"""
import copy

import numpy as np

import solid_fem as fem
import solid_geom as sg

DEFAULTS = {"advanced": False, "type": "tets", "order": 2, "hmin": 0.0, "growth": 1.3, "curv": 10, "face_sizes": [], "follows": "patches"}
ORDERS = {2: "Quadratic (mid-edge nodes)", 1: "Linear (corner nodes only)"}
TYPES = {"tets": "Tetrahedra", "hexdom": "Hex-dominant"}
FOLLOWS = {"patches": "The split patches"}
GROWTH_RANGE = (1.05, 3.0)
CURV_RANGE = (3, 100)


def default_mesh():
    return copy.deepcopy(DEFAULTS)


def complete(mesh):
    """A stored mesh dict (maybe from an older file: missing, or without some keys) with every key present."""
    m = default_mesh()
    m.update({k: v for k, v in (mesh or {}).items() if k in DEFAULTS})
    m["face_sizes"] = [dict(x) for x in (m.get("face_sizes") or [])]
    return m


def body_sizes(geom, setup, h):
    """{body index: mm} of the parts of an assembly that have an element size of their own in setup["body_h"] (a size that is the default `h` anyway
    is not counted, so the same mesh has the same key); {} for a single part.  A size that is not positive is a fem.FemError."""
    if not geom or not geom.get("bodies"):
        return {}
    mine = setup.get("body_h") or {}
    out = {}
    for i, b in enumerate(geom["bodies"]):
        v = mine.get(b["name"])
        if v is None or v == "":
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise fem.FemError(f"{b['name']}: the element size is not a number.")
        if v == 0:
            continue                                                               # 0 = the automatic size, like a blank box
        if not v > 0:
            raise fem.FemError(f"{b['name']}: the element size must be positive (or blank for the automatic size).")
        if abs(v - h) > 1e-9 * max(h, 1e-9):
            out[i] = v
    return out


def face_refs(geom, fids_list, body_h, h):
    """For every local size (the list of face ids it covers, or None when the face is gone): the element size of the part(s) it lies on - the finer one
    for a face between two parts.  That is the size the local one has to be smaller than."""
    eff = fem.element_sizes(geom, h, {"body_h": body_h})
    out = []
    for ids in fids_list:
        sizes = []
        for f in ids or ():
            bs = geom["faces"][f].get("bodies") or ()
            sizes += [eff[b] for b in bs if b < len(eff)] or [eff[0]]
        out.append(min(sizes) if sizes else h)
    return out


def validate(mesh, h, refs=None):
    """The reason why the options cannot be used, or None.  `h` is the element size (mm) the mesh will have: the smallest one when the parts of an
    assembly have sizes of their own.  `refs` = the size of the part under each local size (see face_refs); without it the local sizes are compared with `h`."""
    m = complete(mesh)
    if m["order"] not in (1, 2):
        return "The element order must be linear or quadratic."
    if m["type"] not in TYPES:
        return "The mesh type must be tetrahedra or hex-dominant."
    if m["hmin"] < 0:
        return "The minimum size must be positive (or blank for automatic)."
    if m["hmin"] and h and m["hmin"] >= h:
        return "The minimum size must be smaller than the element size."
    if not GROWTH_RANGE[0] <= m["growth"] <= GROWTH_RANGE[1]:
        return f"The growth rate must be between {GROWTH_RANGE[0]:g} and {GROWTH_RANGE[1]:g}."
    if m["curv"] and not CURV_RANGE[0] <= m["curv"] <= CURV_RANGE[1]:
        return f"Elements around a circle: use {CURV_RANGE[0]} to {CURV_RANGE[1]} (or switch the refinement at curved surfaces off)."
    for k, x in enumerate(m["face_sizes"]):
        ref = refs[k] if refs is not None and k < len(refs) else h
        if not x["h"] > 0:
            return "A local element size must be positive."
        if ref and x["h"] >= ref:
            return ("A local element size must be smaller than the element size of its part (it refines that face)." if refs is not None
                    else "A local element size must be smaller than the element size (it refines that face).")
        if m["hmin"] and x["h"] < m["hmin"]:
            return "A local element size must not be smaller than the minimum size."
    return None


def options(setup):
    """The options a mesh is made with: the plain automatic ones unless Advanced is on."""
    m = complete(setup.get("mesh"))
    if not m["advanced"]:
        d = default_mesh()
        d["advanced"] = False
        return d
    return m


def resolve(geom, setup, h):
    """-> None for the plain automatic mesh, else the options with the local sizes as face ids:
    {"order", "hmin", "growth", "curv", "face_sizes": [{"fids": [...], "h": mm, "name": text}], "body_h": {body index: mm}}.  `h` is the element size (mm)
    the parts without a size of their own get.  An assembly whose parts have sizes of their own is not the plain mesh even with Advanced off (the options
    are then the plain ones).  A face that is not in the part any more, or a number that cannot be used, is a fem.FemError."""
    m = options(setup)
    bs = body_sizes(geom, setup, h)
    if not m["advanced"] and not bs:
        return None
    eff = fem.element_sizes(geom, h, {"body_h": bs})
    if m["advanced"]:
        found = [sg.match_faces(geom, x["face"]) for x in m["face_sizes"]]
        why = validate(m, min(eff), face_refs(geom, found, bs, h) if bs else None)
        if why:
            raise fem.FemError(why)
    else:
        found = []
    out = {"type": m["type"], "order": int(m["order"]), "hmin": float(m["hmin"]), "growth": float(m["growth"]), "curv": int(m["curv"]), "face_sizes": [],
           "body_h": dict(bs)}
    for i, (x, ids) in enumerate(zip(m["face_sizes"] if m["advanced"] else [], found)):
        if ids is None:
            raise fem.FemError(f"Local size {i + 1}: its face is not in the part any more (the geometry changed too much, or the face was split again). "
                               "Set it again.")
        out["face_sizes"].append({"fids": list(ids), "h": float(x["h"]), "name": f"local size {i + 1}"})
    return out


def key_text(opts):
    """A short text for the mesh cache key; the plain automatic options give an empty text (so the key stays what it always was)."""
    if not opts:
        return ""
    bh = {int(k): float(v) for k, v in (opts.get("body_h") or {}).items()}
    if opts["order"] == 2 and not opts["hmin"] and opts["curv"] == 10 and not opts["face_sizes"] and opts.get("type", "tets") == "tets" and not bh:
        return ""                                                          # the same mesh as the plain automatic one (the growth rate only matters near local sizes)
    fs = ";".join(f"{','.join(str(f) for f in sorted(x['fids']))}={x['h']:.8g}" for x in sorted(opts["face_sizes"], key=lambda x: sorted(x["fids"])))
    hexdom = opts.get("type", "tets") == "hexdom"
    g = f"{opts['growth']:.8g}" if (opts["face_sizes"] or hexdom) else "-"
    bt = ("|b" + ";".join(f"{i}={v:.8g}" for i, v in sorted(bh.items()))) if bh else ""
    return f"{'|hx2' if hexdom else ''}|o{opts['order']}|m{opts['hmin']:.8g}|g{g}|c{opts['curv']}|f{fs}{bt}"


# ------------------------------------------------------------------------------------------------------------------------ quality
def _tet_measures(nodes, tets):
    """Edge lengths (ne, 6), radius ratios (ne,), dihedral angles (ne, 6) in degrees, absolute volumes and signed volumes of tetrahedra."""
    c = nodes[tets]                                                         # (ne, 4, 3)
    edges = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    L = np.stack([np.linalg.norm(c[:, a] - c[:, b], axis=1) for a, b in edges], axis=1)           # (ne, 6)
    sv = np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])) / 6.0
    V = np.abs(sv)
    fa = []                                                                  # areas and outward normals of the four faces (face i is opposite node i)
    fn = []
    for i, (a, b, d) in enumerate(((1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2))):
        cr = np.cross(c[:, b] - c[:, a], c[:, d] - c[:, a])
        ar = 0.5 * np.linalg.norm(cr, axis=1)
        n = cr / np.maximum(2 * ar, 1e-300)[:, None]
        opp = c[:, i] - c[:, a]
        out = np.einsum("ij,ij->i", opp, n) > 0                             # the opposite node lies on the inside: that normal points inward
        n[out] *= -1
        fa.append(ar)
        fn.append(n)
    area = np.sum(fa, axis=0)
    r_in = 3.0 * V / np.maximum(area, 1e-300)
    x, y, z = L[:, 0] * L[:, 5], L[:, 1] * L[:, 4], L[:, 2] * L[:, 3]        # products of the three pairs of opposite edges
    R = np.sqrt(np.maximum((x + y + z) * (x + y - z) * (x - y + z) * (-x + y + z), 0.0)) / np.maximum(24.0 * V, 1e-300)
    ratio = np.clip(3.0 * r_in / np.maximum(R, 1e-300), 0.0, 1.0)
    dih = []
    for i in range(4):
        for j in range(i + 1, 4):
            dih.append(np.degrees(np.arccos(np.clip(-np.einsum("ij,ij->i", fn[i], fn[j]), -1.0, 1.0))))
    return L, ratio, np.stack(dih, axis=1), V, sv


def quality(q):
    """Measures the elements of a mesh (the corner nodes: the elements have straight edges).  Returns
    {"order", "elements" (all of them), "tets", "hexes", "pyramids" (counts), "hex_share" (of the elements), "hex_volume_share" (of the volume),
     "nodes", "edge_min", "edge_mean", "edge_max" (mm), "ratio_min", "ratio_mean", "ratio_worst" (tetrahedron index),
     "below_02", "below_01" (counts), "dihedral_min", "dihedral_max" (degrees), "vol_min", "vol_max" (mm3), "volume" (mm3), "inverted": 0,
     "hex_jacobian_min" (1 = a perfect cube, None without hexahedra)}
    The radius ratio 3 r_inscribed / R_circumscribed is 1 for a regular tetrahedron and 0 for a flat one; a pyramid counts with the worst of its four
    corner tetrahedra.  In a hex-dominant mesh the ratios, angles and volumes are those of the tetrahedra and pyramids (the hexahedra have their own number)."""
    nodes, tets = np.asarray(q["nodes"], float), np.asarray(q["tets"])
    hexes, pyrs = q.get("hexes"), q.get("pyrs")
    hexes = np.zeros((0, 8), np.int64) if hexes is None else np.asarray(hexes)
    pyrs = np.zeros((0, 5), np.int64) if pyrs is None else np.asarray(pyrs)
    L, ratio, dih, V, sv = _tet_measures(nodes, tets)
    ne_t = len(tets)
    edge = L.ravel()
    ratios = ratio
    vol_t = float(V.sum())
    vol_p = vol_h = 0.0
    jac = None
    if len(pyrs):
        corner = np.vstack([pyrs[:, [0, 1, 2, 4]], pyrs[:, [0, 2, 3, 4]], pyrs[:, [1, 2, 3, 4]], pyrs[:, [0, 1, 3, 4]]])
        Lp, rp, _d, Vp, _s = _tet_measures(nodes, corner)
        ratios = np.concatenate([ratio, rp.reshape(4, -1).min(axis=0)])
        edge = np.concatenate([edge, np.linalg.norm(nodes[pyrs[:, [0, 1, 2, 3, 0, 1, 2, 3]]] - nodes[pyrs[:, [1, 2, 3, 0, 4, 4, 4, 4]]], axis=2).ravel()])
        vol_p = float(split_volume(nodes, pyrs))
    if len(hexes):
        P = nodes[hexes]
        he = np.stack([np.linalg.norm(P[:, a] - P[:, b], axis=1) for a, b in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))], axis=1)
        edge = np.concatenate([edge, he.ravel()])
        jmin = np.ones(len(hexes))
        for a, b, c, d in ((0, 1, 3, 4), (1, 2, 0, 5), (2, 3, 1, 6), (3, 0, 2, 7), (4, 7, 5, 0), (5, 4, 6, 1), (6, 5, 7, 2), (7, 6, 4, 3)):         # right-handed at every corner
            e1, e2, e3 = P[:, b] - P[:, a], P[:, c] - P[:, a], P[:, d] - P[:, a]
            j = np.einsum("ij,ij->i", e1, np.cross(e2, e3)) / np.maximum(np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) * np.linalg.norm(e3, axis=1), 1e-300)
            jmin = np.minimum(jmin, j)
        jac = float(jmin.min())
        vol_h = float(_hex_volume(P).sum())
    total = ne_t + len(hexes) + len(pyrs)
    vol_all = vol_t + vol_p + vol_h
    inverted = int((sv < 0).sum()) + (int((jmin <= 0).sum()) if len(hexes) else 0)
    return {"order": int(q.get("order", 2)), "elements": int(total), "tets": int(ne_t), "hexes": int(len(hexes)), "pyramids": int(len(pyrs)),
            "hex_share": float(len(hexes) / max(total, 1)), "hex_volume_share": float(vol_h / max(vol_all, 1e-300)), "nodes": int(len(nodes)),
            "edge_min": float(edge.min()), "edge_mean": float(edge.mean()), "edge_max": float(edge.max()),
            "ratio_min": float(ratios.min()), "ratio_mean": float(ratios.mean()), "ratio_worst": int(np.argmin(ratio)),
            "below_02": int((ratios < 0.2).sum()), "below_01": int((ratios < 0.1).sum()),
            "dihedral_min": float(dih.min()), "dihedral_max": float(dih.max()),
            "vol_min": float(V.min()), "vol_max": float(V.max()), "volume": float(vol_all), "inverted": inverted, "hex_jacobian_min": jac}


def split_volume(nodes, pyr):
    """The total volume of straight-sided pyramids (each as two tetrahedra)."""
    P = nodes[pyr[:, :5]]
    sv = lambda c: np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])) / 6.0
    return (sv(P[:, [0, 1, 2, 4]]) + sv(P[:, [0, 2, 3, 4]])).sum()


def _hex_volume(P):
    """Volumes of hexahedra (corner nodes, VTK order) with straight edges: the exact integral of the trilinear map (2 x 2 x 2 Gauss points)."""
    g = 1.0 / np.sqrt(3.0)
    v = np.zeros(len(P))
    for sx in (-g, g):
        for sy in (-g, g):
            for sz in (-g, g):
                dN = 0.125 * np.array([[a * (1 + b * sy) * (1 + c * sz), b * (1 + a * sx) * (1 + c * sz), c * (1 + a * sx) * (1 + b * sy)]
                                       for a, b, c in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))])
                J = np.einsum("ia,eib->eab", dN, P)
                v += np.linalg.det(J)
    return v


def verdict(qr):
    """'good' / 'acceptable' / 'poor' for a quality report: a few very flat elements spoil a result, so the worst one counts."""
    if qr["ratio_min"] < 0.02 or qr["dihedral_max"] > 170.0:
        return "poor"
    if qr["ratio_min"] < 0.1 or qr["dihedral_max"] > 160.0 or qr["below_02"] > 0.02 * max(qr["elements"], 1):
        return "acceptable"
    return "good"
