"""
solid_mesh.py - the mesh OPTIONS of the 3D FEA (what "Advanced mesh options" of the panel edits) and the quality report of a mesh.  No window.

setup["mesh"] = {
  "advanced": bool,        the options below are used only when this is True (off = the plain automatic mesh: quadratic, minimum size h/6, curvature 10)
  "order":    2 | 1,       2 = quadratic (10-node) tetrahedra, 1 = linear (4-node) tetrahedra
  "hmin":     mm | 0,      the smallest element edge gmsh may make; 0 = automatic (a sixth of the element size)
  "growth":   > 1,         how fast the elements grow away from a locally refined face (1.3 = each layer of elements 30 % longer than the one before)
  "curv":     0 | 3..100,  refine at curved surfaces: the number of elements around a full circle; 0 = off
  "face_sizes": [{"face": face signature, "h": mm}],    a smaller element size on single faces (a patch of a split face counts as a face)
  "follows":  "patches",   what the mesh follows: the split patches (the mesh edges lie on the patch borders); the only choice so far
}
`options(setup)` is the validated, complete version; `resolve(geom, setup)` also turns the face signatures into face ids of the (rebuilt) part;
`quality(q)` measures a mesh.
"""
import copy

import numpy as np

import solid_fem as fem
import solid_geom as sg

DEFAULTS = {"advanced": False, "order": 2, "hmin": 0.0, "growth": 1.3, "curv": 10, "face_sizes": [], "follows": "patches"}
ORDERS = {2: "Quadratic (10-node tetrahedra)", 1: "Linear (4-node tetrahedra)"}
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


def validate(mesh, h):
    """The reason why the options cannot be used, or None.  `h` is the element size (mm) the mesh will have."""
    m = complete(mesh)
    if m["order"] not in (1, 2):
        return "The element order must be linear or quadratic."
    if m["hmin"] < 0:
        return "The minimum size must be positive (or blank for automatic)."
    if m["hmin"] and h and m["hmin"] >= h:
        return "The minimum size must be smaller than the element size."
    if not GROWTH_RANGE[0] <= m["growth"] <= GROWTH_RANGE[1]:
        return f"The growth rate must be between {GROWTH_RANGE[0]:g} and {GROWTH_RANGE[1]:g}."
    if m["curv"] and not CURV_RANGE[0] <= m["curv"] <= CURV_RANGE[1]:
        return f"Elements around a circle: use {CURV_RANGE[0]} to {CURV_RANGE[1]} (or switch the refinement at curved surfaces off)."
    for x in m["face_sizes"]:
        if not x["h"] > 0:
            return "A local element size must be positive."
        if h and x["h"] >= h:
            return "A local element size must be smaller than the element size (it refines that face)."
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
    {"order", "hmin", "growth", "curv", "face_sizes": [{"fids": [...], "h": mm, "name": text}]}.  `h` is the element size (mm) the mesh gets.
    A face that is not in the part any more, or a number that cannot be used, is a fem.FemError."""
    m = options(setup)
    if not m["advanced"]:
        return None
    why = validate(m, h)
    if why:
        raise fem.FemError(why)
    out = {"order": int(m["order"]), "hmin": float(m["hmin"]), "growth": float(m["growth"]), "curv": int(m["curv"]), "face_sizes": []}
    for i, x in enumerate(m["face_sizes"]):
        ids = sg.match_faces(geom, x["face"])
        if ids is None:
            raise fem.FemError(f"Local size {i + 1}: its face is not in the part any more (the geometry changed too much, or the face was split again). "
                               "Set it again.")
        out["face_sizes"].append({"fids": list(ids), "h": float(x["h"]), "name": f"local size {i + 1}"})
    return out


def key_text(opts):
    """A short text for the mesh cache key; the plain automatic options give an empty text (so the key stays what it always was)."""
    if not opts or (opts["order"] == 2 and not opts["hmin"] and opts["curv"] == 10 and not opts["face_sizes"]):
        return ""                                                          # the same mesh as the plain automatic one (the growth rate only matters near local sizes)
    fs = ";".join(f"{','.join(str(f) for f in sorted(x['fids']))}={x['h']:.8g}" for x in sorted(opts["face_sizes"], key=lambda x: sorted(x["fids"])))
    g = f"{opts['growth']:.8g}" if opts["face_sizes"] else "-"
    return f"|o{opts['order']}|m{opts['hmin']:.8g}|g{g}|c{opts['curv']}|f{fs}"


# ------------------------------------------------------------------------------------------------------------------------ quality
def quality(q):
    """Measures the tetrahedra of a mesh (the corner nodes: the elements have straight edges).  Returns
    {"order", "elements", "nodes", "edge_min", "edge_mean", "edge_max" (mm), "ratio_min", "ratio_mean", "ratio_worst" (element index),
     "below_02", "below_01" (counts), "dihedral_min", "dihedral_max" (degrees), "vol_min", "vol_max" (mm3), "volume" (mm3), "inverted": 0}
    The radius ratio 3 r_inscribed / R_circumscribed is 1 for a regular tetrahedron and 0 for a flat one."""
    nodes, tets = np.asarray(q["nodes"], float), np.asarray(q["tets"])
    c = nodes[tets]                                                         # (ne, 4, 3)
    ne = len(tets)
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
    dih = np.stack(dih, axis=1)
    return {"order": int(q.get("order", 2)), "elements": int(ne), "nodes": int(len(nodes)),
            "edge_min": float(L.min()), "edge_mean": float(L.mean()), "edge_max": float(L.max()),
            "ratio_min": float(ratio.min()), "ratio_mean": float(ratio.mean()), "ratio_worst": int(np.argmin(ratio)),
            "below_02": int((ratio < 0.2).sum()), "below_01": int((ratio < 0.1).sum()),
            "dihedral_min": float(dih.min()), "dihedral_max": float(dih.max()),
            "vol_min": float(V.min()), "vol_max": float(V.max()), "volume": float(V.sum()), "inverted": int((sv < 0).sum())}


def verdict(qr):
    """'good' / 'acceptable' / 'poor' for a quality report: a few very flat elements spoil a result, so the worst one counts."""
    if qr["ratio_min"] < 0.02 or qr["dihedral_max"] > 170.0:
        return "poor"
    if qr["ratio_min"] < 0.1 or qr["dihedral_max"] > 160.0 or qr["below_02"] > 0.02 * max(qr["elements"], 1):
        return "acceptable"
    return "good"
