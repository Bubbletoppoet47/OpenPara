"""
sim_mesh2d.py - the mesh OPTIONS of the 2D FEA and the 2D Thermal (what "Advanced mesh options" of the Mesh page edits), the element quality report of a 2D mesh, and the same
options as one text for a cache key.  No window.  The 3D windows have the same options (dev_addons/solid_fea/solid_mesh.py); the panel that edits them is shared (sim_meshui).

mesh options = {
  "advanced": bool,      the options below are used only when this is True (off = the plain automatic mesh: quadratic elements, no minimum size, no curvature refinement)
  "order":    2 | 1,     2 = quadratic (6-node triangles), 1 = linear (3-node triangles).  The mesh itself is always made of 3-node triangles; the order is what the solver makes of them
  "hmin":     length | 0,   the smallest element edge the mesher may make; 0 = automatic (no limit)
  "growth":   > 1,       how fast the elements grow away from a locally refined edge, point or region (1.3 = each layer 30 % longer than the one before)
  "curv":     0 | 3..100,   refine at curved edges: the number of elements around a full circle; 0 = off (the plain mesh does not refine at curves)
  "local":    [{"targets": [("ln" | "ar" | "sp" | "ci" | "pt" | "rg", id), ...], "h": length}]
                         a smaller element size on single edges (sketch lines, arcs, splines, circles), points, or regions (a region is a closed area of the sketch)
}
Lengths are in the unit system of the tab (the sketch's), like the element size.  `options(mesh)` is what physics_geom.mesh_faces takes (None = the plain mesh).
"""
import copy

import numpy as np

DEFAULTS = {"advanced": False, "order": 2, "hmin": 0.0, "growth": 1.3, "curv": 0, "local": []}
ORDERS = {2: "Quadratic (6-node triangles)", 1: "Linear (3-node triangles)"}
GROWTH_RANGE = (1.05, 3.0)
CURV_RANGE = (3, 100)
EDGE_KINDS = ("ln", "ar", "sp", "ci")
KIND_WORD = {"ln": "Line", "ar": "Arc", "sp": "Spline", "ci": "Circle", "pt": "Point", "rg": "Region"}


class MeshOptionError(ValueError):
    pass


def default_mesh():
    return copy.deepcopy(DEFAULTS)


def _targets(ts):
    return [(str(k), int(i)) for k, i in (ts or [])]


def complete(mesh):
    """A stored options dict (maybe from an older file: missing, or without some keys) with every key present, the targets as tuples."""
    m = default_mesh()
    m.update({k: v for k, v in (mesh or {}).items() if k in DEFAULTS})
    m["local"] = [{"targets": _targets(x.get("targets")), "h": float(x.get("h") or 0.0)} for x in (m.get("local") or [])]
    m["advanced"], m["order"] = bool(m["advanced"]), (1 if int(m["order"]) == 1 else 2)
    m["hmin"], m["growth"], m["curv"] = float(m["hmin"] or 0.0), float(m["growth"] or 1.3), int(m["curv"] or 0)
    return m


def validate(mesh, h):
    """The reason why the options cannot be used with the element size `h`, or None."""
    m = complete(mesh)
    if m["hmin"] < 0:
        return "The minimum size must be positive (or blank for automatic)."
    if m["hmin"] and h and m["hmin"] >= h:
        return "The minimum size must be smaller than the element size."
    if not GROWTH_RANGE[0] <= m["growth"] <= GROWTH_RANGE[1]:
        return f"The growth rate must be between {GROWTH_RANGE[0]:g} and {GROWTH_RANGE[1]:g}."
    if m["curv"] and not CURV_RANGE[0] <= m["curv"] <= CURV_RANGE[1]:
        return f"Elements around a circle: use {CURV_RANGE[0]} to {CURV_RANGE[1]} (or switch the refinement at curved edges off)."
    for x in m["local"]:
        if not x["h"] > 0:
            return "A local element size must be positive."
        if h and x["h"] >= h:
            return "A local element size must be smaller than the element size (it refines that edge, point or region)."
        if m["hmin"] and x["h"] < m["hmin"]:
            return "A local element size must not be smaller than the minimum size."
    return None


def options(mesh):
    """What the mesher is given: None for the plain automatic mesh (Advanced off, or on with nothing that changes the mesh), else {"hmin", "growth", "curv", "local"}."""
    m = complete(mesh)
    if not m["advanced"]:
        return None
    if not m["hmin"] and not m["curv"] and not m["local"]:
        return None
    return {"hmin": m["hmin"], "growth": m["growth"], "curv": m["curv"], "local": [{"targets": list(x["targets"]), "h": x["h"]} for x in m["local"]]}


def order_of(mesh):
    """The element order the solver uses: 1 (linear) only when Advanced is on and says so."""
    m = complete(mesh)
    return m["order"] if m["advanced"] else 2


def key_text(opts):
    """The options as a short text for a mesh cache key; the plain mesh gives an empty text, so the keys of the meshes made without options stay what they were."""
    if not opts:
        return ""
    loc = ";".join(f"{','.join(f'{k}{i}' for k, i in sorted(x['targets']))}={x['h']:.8g}" for x in sorted(opts["local"], key=lambda x: sorted(x["targets"])))
    g = f"{opts['growth']:.8g}" if opts["local"] else "-"
    return f"|m{opts['hmin']:.8g}|g{g}|c{opts['curv']}|l{loc}"


def target_text(targets, names=None):
    """'Line 3, Point 5, Region 1' for a local size's targets (`names`: {(kind, id): name} when the sketch has names for them)."""
    out = []
    for k, i in targets:
        nm = (names or {}).get((k, i))
        out.append(nm or (f"{KIND_WORD.get(k, k)} {i + 1}" if k == "rg" else f"{KIND_WORD.get(k, k)} {i}"))
    return ", ".join(out)


def convert_lengths(mesh, f):
    """The options with every length multiplied by `f` (the program's unit system changed)."""
    m = complete(mesh)
    m["hmin"] *= f
    for x in m["local"]:
        x["h"] *= f
    return m


# ------------------------------------------------------------------------------------------------------------------------ quality
def quality(mesh, order=2):
    """Measures the triangles of a 2D mesh (the corner nodes: the elements have straight edges).  Returns
    {"order", "elements", "nodes", "edge_min", "edge_mean", "edge_max" (lengths), "ratio_min", "ratio_mean", "ratio_worst" (triangle index),
     "below_02", "below_01" (counts), "angle_min", "angle_max" (degrees), "area_min", "area_max", "area" (areas), "inverted" (counts)}.
    The radius ratio 2 r_inscribed / R_circumscribed is 1 for an equilateral triangle and 0 for a flat one."""
    nodes, tris = np.asarray(mesh["nodes"], float), np.asarray(mesh["tris"])
    p = nodes[tris]
    e = np.stack([np.linalg.norm(p[:, 1] - p[:, 0], axis=1), np.linalg.norm(p[:, 2] - p[:, 1], axis=1), np.linalg.norm(p[:, 0] - p[:, 2], axis=1)], axis=1)
    sa = 0.5 * ((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
    A = np.abs(sa)
    a, b, c = e[:, 0], e[:, 1], e[:, 2]
    s = e.sum(axis=1) / 2.0
    with np.errstate(divide="ignore", invalid="ignore"):
        r_in = np.where(s > 0, A / s, 0.0)
        R = np.where(A > 0, a * b * c / (4.0 * A), np.inf)
        ratio = np.where(np.isfinite(R) & (R > 0), np.clip(2.0 * r_in / R, 0.0, 1.0), 0.0)
        ang = np.degrees(np.stack([np.arccos(np.clip((b ** 2 + c ** 2 - a ** 2) / (2 * b * c), -1, 1)),
                                   np.arccos(np.clip((a ** 2 + c ** 2 - b ** 2) / (2 * a * c), -1, 1)),
                                   np.arccos(np.clip((a ** 2 + b ** 2 - c ** 2) / (2 * a * b), -1, 1))], axis=1))
    return {"order": int(order), "elements": int(len(tris)), "nodes": int(len(nodes)),
            "edge_min": float(e.min()), "edge_mean": float(e.mean()), "edge_max": float(e.max()),
            "ratio_min": float(ratio.min()), "ratio_mean": float(ratio.mean()), "ratio_worst": int(np.argmin(ratio)),
            "below_02": int((ratio < 0.2).sum()), "below_01": int((ratio < 0.1).sum()),
            "angle_min": float(np.nanmin(ang)), "angle_max": float(np.nanmax(ang)),
            "area_min": float(A.min()), "area_max": float(A.max()), "area": float(A.sum()), "inverted": int((sa <= 0).sum())}


def verdict(qr):
    """'good' / 'acceptable' / 'poor' for a quality report: a few very flat elements spoil a result, so the worst one counts."""
    if qr["ratio_min"] < 0.02 or qr["angle_max"] > 170.0 or qr["inverted"]:
        return "poor"
    if qr["ratio_min"] < 0.1 or qr["angle_max"] > 160.0 or qr["below_02"] > 0.02 * max(qr["elements"], 1):
        return "acceptable"
    return "good"
