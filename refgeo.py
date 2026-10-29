"""
refgeo.py - the maths of reference planes and axes, shared by parts and assemblies (no GUI in here).

Entities (all numpy, in one common frame):
    plane  {"t": "plane", "p": point on it, "n": unit normal, "x": unit in-plane direction (optional)}
    line   {"t": "line" | "axis" | "circle", "p": point on it, "d": unit direction}     (an axis / circle has "r" too)
    point  {"t": "point" | "sphere", "p": point}
"""
import math

import numpy as np

PLANE_TYPES = [
    ("offset", "Offset distance", "a plane or flat face", "Parallel to it, moved by a distance"),
    ("angle", "At angle", "a plane or face, then an edge or axis", "Turn the plane about the edge / axis by an angle"),
    ("parallel", "Parallel at point", "a plane or face, then a point", "Parallel to the plane and through the point"),
    ("perp", "Perpendicular", "an edge or axis (then a point)", "Square to the edge / axis (through the point)"),
    ("mid", "Mid plane", "two parallel planes or faces", "Half way between the two"),
    ("three", "Through 3 points", "three points", "The plane through the three points"),
    ("coincident", "Coincident", "a plane / face, or an edge and a point", "On a plane, or through an edge and a point"),
]
AXIS_TYPES = [
    ("line", "One line / edge / axis", "an edge, a circle or an axis", "On that line"),
    ("planes", "Two planes", "two planes or flat faces", "Where the two planes cross"),
    ("points", "Two points / vertices", "two points", "Through both points"),
    ("cyl", "Cylindrical face", "a cylindrical face", "Along the centre line of the cylinder"),
    ("pointplane", "Point and face / plane", "a point, then a plane or face", "Square to the plane, through the point"),
]
NEEDS = {"offset": 1, "angle": 2, "parallel": 2, "perp": 1, "mid": 2, "three": 3, "coincident": 1,
         "line": 1, "planes": 2, "points": 2, "cyl": 1, "pointplane": 2}


class RefError(Exception):
    pass


def unit(v):
    n = float(np.linalg.norm(v))
    return np.asarray(v, float) / n if n > 1e-12 else np.asarray(v, float)


def kind_of(e):
    t = e["t"]
    if t == "plane":
        return "plane"
    if t in ("line", "axis", "circle"):
        return "line"
    return "point"


def frame_x(n, hint=None):
    """An in-plane x direction for a plane with normal n (the global X projected onto it, else Y)."""
    n = unit(n)
    for h in ([hint] if hint is not None else []) + [np.array([1.0, 0, 0]), np.array([0, 1.0, 0])]:
        v = np.asarray(h, float) - float(np.asarray(h, float) @ n) * n
        if float(np.linalg.norm(v)) > 1e-6:
            return unit(v)
    return unit(np.cross(n, [0, 0, 1.0]))


def _rot(v, k, th):
    k = unit(k)
    return v * math.cos(th) + np.cross(k, v) * math.sin(th) + k * float(k @ v) * (1 - math.cos(th))


def _plane(p, n, x=None):
    n = unit(n)
    return {"t": "plane", "p": np.asarray(p, float), "n": n, "x": frame_x(n, x)}


def infer_plane_type(ents):
    ks = [kind_of(e) for e in ents]
    if not ks:
        return "offset"
    if ks == ["plane"]:
        return "offset"
    if ks[0] == "plane" and len(ks) >= 2:
        return {"plane": "mid", "line": "angle", "point": "parallel"}[ks[1]]
    if ks[0] == "line":
        return "coincident" if (len(ks) >= 2 and ks[1] == "point" and False) else "perp"
    if ks[0] == "point":
        return "three" if len(ks) >= 2 else "three"
    return "offset"


def infer_axis_type(ents):
    ks = [kind_of(e) for e in ents]
    if not ks:
        return "line"
    if ks[0] == "line":
        return "cyl" if (ents[0]["t"] == "axis" and ents[0].get("r", 0) > 0) else "line"
    if ks[0] == "plane":
        return "planes" if len(ks) >= 2 and ks[1] == "plane" else "planes"
    if ks[0] == "point":
        return "pointplane" if len(ks) >= 2 and ks[1] == "plane" else "points"
    return "line"


def _need(ents, kinds, what):
    if len(ents) < len(kinds):
        raise RefError(f"pick {what}")
    for e, k in zip(ents, kinds):
        if kind_of(e) != k:
            raise RefError(f"pick {what} (a {k} is needed in this place, you picked a {kind_of(e)})")


def compute_plane(ptype, ents, dist=10.0, ang=45.0, flip=False):
    ptype = ptype or infer_plane_type(ents)
    if not ents:
        raise RefError("pick the references for the plane")
    sg = -1.0 if flip else 1.0
    if ptype == "offset":
        _need(ents, ["plane"], "a plane or flat face")
        a = ents[0]
        return _plane(a["p"] + a["n"] * sg * dist, a["n"], a.get("x"))
    if ptype == "angle":
        _need(ents, ["plane", "line"], "a plane or face, then an edge or axis")
        a, ln = ents[0], ents[1]
        th = math.radians(ang) * sg
        n = _rot(a["n"], ln["d"], th)
        x = _rot(a["x"], ln["d"], th) if a.get("x") is not None else None
        return _plane(ln["p"], n, x)
    if ptype == "parallel":
        _need(ents, ["plane", "point"], "a plane or face, then a point")
        return _plane(ents[1]["p"], ents[0]["n"] * sg, ents[0].get("x"))
    if ptype == "perp":
        _need(ents, ["line"], "an edge or axis")
        ln = ents[0]
        p = ents[1]["p"] if len(ents) > 1 and kind_of(ents[1]) == "point" else ln["p"]
        return _plane(p, ln["d"] * sg)
    if ptype == "mid":
        _need(ents, ["plane", "plane"], "two parallel planes or faces")
        a, b = ents[0], ents[1]
        if float(np.linalg.norm(np.cross(a["n"], b["n"]))) > 1e-5:
            raise RefError("the two planes are not parallel")
        return _plane(a["p"] + 0.5 * float((b["p"] - a["p"]) @ a["n"]) * a["n"], a["n"] * sg, a.get("x"))
    if ptype == "three":
        _need(ents, ["point", "point", "point"], "three points")
        a, b, c = ents[0]["p"], ents[1]["p"], ents[2]["p"]
        n = np.cross(b - a, c - a)
        if float(np.linalg.norm(n)) < 1e-9:
            raise RefError("the three points lie on one line")
        return _plane(a, n * sg, b - a)
    if ptype == "coincident":
        if kind_of(ents[0]) == "plane":
            a = ents[0]
            return _plane(a["p"], a["n"] * sg, a.get("x"))
        _need(ents, ["line", "point"], "a plane or face, or an edge and a point")
        ln, pt = ents[0], ents[1]
        n = np.cross(ln["d"], pt["p"] - ln["p"])
        if float(np.linalg.norm(n)) < 1e-9:
            raise RefError("the point lies on the line - the plane is not defined")
        return _plane(ln["p"], n * sg, ln["d"])
    raise RefError(f"unknown plane type {ptype}")


def _axis(p, d):
    return {"t": "axis", "p": np.asarray(p, float), "d": unit(d), "r": 0.0}


def compute_axis(atype, ents):
    atype = atype or infer_axis_type(ents)
    if not ents:
        raise RefError("pick the references for the axis")
    if atype in ("line", "cyl"):
        _need(ents, ["line"], "an edge, circle or axis" if atype == "line" else "a cylindrical face")
        if atype == "cyl" and not (ents[0]["t"] == "axis" and ents[0].get("r", 0) > 0):
            raise RefError("pick a cylindrical face")
        return _axis(ents[0]["p"], ents[0]["d"])
    if atype == "planes":
        _need(ents, ["plane", "plane"], "two planes or flat faces")
        a, b = ents[0], ents[1]
        d = np.cross(a["n"], b["n"])
        if float(np.linalg.norm(d)) < 1e-6:
            raise RefError("the two planes are parallel - they do not cross")
        A = np.array([a["n"], b["n"], d])
        rhs = np.array([float(a["n"] @ a["p"]), float(b["n"] @ b["p"]), 0.0])
        return _axis(np.linalg.solve(A, rhs), d)
    if atype == "points":
        _need(ents, ["point", "point"], "two points")
        d = ents[1]["p"] - ents[0]["p"]
        if float(np.linalg.norm(d)) < 1e-9:
            raise RefError("the two points are the same")
        return _axis(ents[0]["p"], d)
    if atype == "pointplane":
        _need(ents, ["point", "plane"], "a point, then a plane or face")
        return _axis(ents[0]["p"], ents[1]["n"])
    raise RefError(f"unknown axis type {atype}")


def to_jsonable(e):
    return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in e.items()}
