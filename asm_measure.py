"""
asm_measure.py - the Measure tool of the assembly: Minimum, Center and Maximum distance between two picked items (in assembly coordinates).

An item is what pick_item / world_pick return: {"cid", "kind": vertex | edge | face | plane | axis | origin, "idx", "ref"}.
Center means:   two round things (pipes, holes, circle edges, straight edges)  -> axis to axis (parallel axes: perpendicular distance,
                                                                                    skewed axes: closest approach)
                a round thing and a flat face                                  -> axis to the face's plane
                a round thing and anything else                                -> the other's center to the axis
                everything else                                                -> center to center (face centers, edge midpoints, points)
Minimum:        parallel flat faces -> the gap between the planes;  two parallel pipes / holes -> the gap between the surfaces (center - r1 - r2,
                or the clearance of one inside the other);  otherwise the closest points of the real shapes
Maximum:        two parallel pipes / holes -> center + r1 + r2;  otherwise the farthest points of the real shapes (sampled)
"""
import numpy as np

import asm_model as am

GREEN, BLUE, RED = (0.17, 0.63, 0.17), (0.12, 0.47, 0.71), (0.84, 0.15, 0.16)
AXIS_T = ("axis", "circle", "line")


def world_shape(shape, M):
    """A copy of a build123d shape moved by the 4x4 (rotation + translation) matrix M."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf
    t = gp_Trsf()
    t.SetValues(*[float(M[i][j]) for i in range(3) for j in range(4)])
    if type(shape).__name__ == "Vertex":
        from build123d import Vertex
        c = shape.center()
        p = np.asarray(M, float)[:3, :3] @ np.array([c.X, c.Y, c.Z]) + np.asarray(M, float)[:3, 3]
        return Vertex(float(p[0]), float(p[1]), float(p[2]))
    return type(shape)(BRepBuilderAPI_Transform(shape.wrapped, t, True).Shape())


def _c(v):
    return np.array([v.X, v.Y, v.Z], float)


def thing(asm, it):
    """The measurable description of one picked item:  {"it", "k", "label", "ent", "shape", "center"}  (shape is None for planes / axes of the
    assembly itself, which are infinite)."""
    k = it["kind"]
    ref = it["ref"]
    try:
        ent = asm.entity(ref)
    except am.MateError:
        ent = None
    out = {"it": it, "k": k, "ent": ent, "shape": None, "center": None, "label": it.get("label") or k}
    if it["cid"] == "@" or k in ("plane", "axis", "origin"):
        if ent is None:
            raise am.MateError("that item no longer exists")
        out["center"] = np.array(ent["p"], float)
        return out
    c = asm.comp(it["cid"])
    solid = asm.solid_fn(c) if (c is not None and asm.solid_fn) else None
    if solid is None:
        raise am.MateError("a component it refers to has no solid")
    M = asm.T4(c)
    subs = {"vertex": solid.vertices, "edge": solid.edges, "face": solid.faces}[k]()
    sh = world_shape(subs[it["idx"]], M)
    out["shape"] = sh
    out["name"] = c["name"]
    if k == "edge" and ent is not None and ent["t"] == "circle":
        out["center"] = np.array(ent["p"], float)
    else:
        out["center"] = _c(sh.center())
    return out


def kind_of(t):
    """point | axis (round or straight: has a direction) | plane | sphere | other"""
    e = t["ent"]
    if t["k"] == "vertex" or t["k"] == "origin":
        return "point"
    if e is None:
        return "other"
    if e["t"] == "plane":
        return "plane"
    if e["t"] in AXIS_T:
        return "axis"
    if e["t"] == "sphere":
        return "sphere"
    if e["t"] == "point":
        return "point"
    return "other"


def radius(t):
    e = t["ent"]
    return float(e.get("r", 0.0)) if e is not None and e["t"] in ("axis", "circle") else 0.0


def is_pipe(t):
    """A cylindrical FACE (a pipe or a hole), not just an edge."""
    return t["k"] == "face" and t["ent"] is not None and t["ent"]["t"] == "axis" and radius(t) > 0


def axis_point(t):
    """The point of the axis that is level with the item's center (so a pipe's axis point is at the middle of its length)."""
    e = t["ent"]
    d = e["d"]
    return e["p"] + d * float((t["center"] - e["p"]) @ d)


def line_line(p1, d1, p2, d2):
    """Closest points of two infinite lines; parallel lines: the perpendicular from p1 (-> parallel True)."""
    w = p1 - p2
    b = float(d1 @ d2)
    den = 1.0 - b * b
    if den < 1e-10:
        s = 0.0
        q = p2 + d2 * float((p1 - p2) @ d2)
        return p1, q, True
    s = (b * float(w @ d2) - float(w @ d1)) / den
    u = (float(w @ d2) - b * float(w @ d1)) / den
    return p1 + d1 * s, p2 + d2 * u, False


def sample_points(t, cap=4000):
    """World points on the shape for the maximum distance (vertices, points along an edge, a tessellation of a face)."""
    sh = t["shape"]
    if sh is None:
        return None
    k = t["k"]
    if k == "vertex":
        return np.array([t["center"]])
    if k == "edge":
        pts = np.array([tuple(sh.position_at(x)) for x in np.linspace(0, 1, 80)])
    else:
        pts = [tuple(_c(v.center())) for v in sh.vertices()]
        try:
            vs, _t = sh.tessellate(0.2)
            pts += [tuple(v) for v in vs]
        except Exception:
            pass
        pts = np.array(pts)
    if len(pts) > cap:                       # keep the extreme points in many directions: the farthest pair is always among them
        rng = np.random.default_rng(1)
        dirs = rng.normal(size=(900, 3))
        dirs /= np.linalg.norm(dirs, axis=1)[:, None]
        pr = pts @ dirs.T
        keep = np.unique(np.concatenate([pr.argmax(axis=0), pr.argmin(axis=0)]))
        pts = pts[keep]
    return pts


def farthest(pa, pb):
    best, bi = -1.0, (0, 0)
    for i0 in range(0, len(pa), 400):
        blk = pa[i0:i0 + 400]
        dm = np.linalg.norm(blk[:, None, :] - pb[None, :, :], axis=2)
        i, j = np.unravel_index(int(np.argmax(dm)), dm.shape)
        if dm[i, j] > best:
            best, bi = float(dm[i, j]), (i0 + i, j)
    return pa[bi[0]], pb[bi[1]]


# ---------------------------------------------------------------------------------------------- the three distances
def center_distance(a, b):
    """(p, q, label, note) for the Center distance."""
    ka, kb = kind_of(a), kind_of(b)
    if ka == "axis" and kb == "axis":
        ea, eb = a["ent"], b["ent"]
        pa, pb = axis_point(a), axis_point(b)
        p, q, par = line_line(pa, ea["d"], pb, eb["d"])
        if par:
            return p, q, "Center distance (axis to axis)", "the axes are parallel"
        return p, q, "Center distance (axis to axis)", "the axes are skewed: the closest approach between them"
    if "axis" in (ka, kb):
        ax, ot = (a, b) if ka == "axis" else (b, a)
        ea = ax["ent"]
        pa = axis_point(ax)
        if kind_of(ot) == "plane":
            n = ot["ent"]["n"]
            d = float((pa - ot["ent"]["p"]) @ n)
            q = pa - n * d
            note = "the axis is parallel to the face" if abs(float(ea["d"] @ n)) < 1e-6 else "the axis is not parallel to the face: measured from its middle point"
            return (pa, q, "Center distance (axis to face)", note) if ax is a else (q, pa, "Center distance (axis to face)", note)
        c = ot["center"]
        foot = ea["p"] + ea["d"] * float((c - ea["p"]) @ ea["d"])
        return (foot, c, "Center distance (axis to center)", "") if ax is a else (c, foot, "Center distance (axis to center)", "")
    return a["center"], b["center"], "Center distance", ""


def _cross_section(a, b):
    """Two parallel pipes / holes (cylindrical faces): (center c, unit u from A's axis to B's axis, pA, pB axis points on a common cross-section)."""
    ea, eb = a["ent"], b["ent"]
    pa = axis_point(a)
    pb = pb0 = eb["p"] + eb["d"] * float((pa - eb["p"]) @ eb["d"])
    v = pb - pa
    c = float(np.linalg.norm(v))
    if c > 1e-9:
        u = v / c
    else:
        u = np.cross(ea["d"], [1.0, 0, 0] if abs(ea["d"][0]) < 0.9 else [0, 1.0, 0])
        u = u / np.linalg.norm(u)
    return c, u, pa, pb


def parallel_pipes(a, b):
    return is_pipe(a) and is_pipe(b) and np.linalg.norm(np.cross(a["ent"]["d"], b["ent"]["d"])) < 1e-6


def min_distance(a, b):
    """(p, q, label, note) or None."""
    if parallel_pipes(a, b):
        c, u, pa, pb = _cross_section(a, b)
        ra, rb = radius(a), radius(b)
        if c >= ra + rb:
            return pa + u * ra, pb - u * rb, "Minimum distance (gap between the surfaces)", ""
        if rb + c <= ra:                         # B inside A (a pipe in a hole)
            return pa + u * ra, pb + u * rb, "Minimum distance (clearance, B inside A)", ""
        if ra + c <= rb:
            return pa - u * ra, pb - u * rb, "Minimum distance (clearance, A inside B)", ""
        return pa, pa, "Minimum distance", "the surfaces cross each other (0)"
    ka, kb = kind_of(a), kind_of(b)
    if ka == "plane" and kb == "plane" and abs(abs(float(a["ent"]["n"] @ b["ent"]["n"])) - 1.0) < 1e-6:
        n = a["ent"]["n"]
        d = float((b["ent"]["p"] - a["ent"]["p"]) @ n)
        p = a["center"]
        return p, p + n * d, "Minimum distance (gap between the parallel planes)", ""
    if a["shape"] is not None and b["shape"] is not None:
        _d, p, q = a["shape"].distance_to_with_closest_points(b["shape"])
        return np.array(tuple(p), float), np.array(tuple(q), float), "Minimum distance", ""
    return _analytic_min(a, b)


def _analytic_min(a, b):
    """The assembly's own planes / axes / origin (infinite things) against another item."""
    ka, kb = kind_of(a), kind_of(b)
    pts = lambda t: t["center"]
    if "plane" in (ka, kb):
        pl, ot = (a, b) if ka == "plane" else (b, a)
        n, p0 = pl["ent"]["n"], pl["ent"]["p"]
        if ot["shape"] is not None:
            P = sample_points(ot)
            i = int(np.argmin(np.abs((P - p0) @ n)))
            q = P[i]
        else:
            q = ot["center"] if kind_of(ot) != "axis" else axis_point(ot)
        d = float((q - p0) @ n)
        foot = q - n * d
        return (foot, q, "Minimum distance", "") if pl is a else (q, foot, "Minimum distance", "")
    if "axis" in (ka, kb) and kb != ka:
        ax, ot = (a, b) if ka == "axis" else (b, a)
        P = sample_points(ot) if ot["shape"] is not None else np.array([ot["center"]])
        e = ax["ent"]
        foot = e["p"][None, :] + np.outer((P - e["p"]) @ e["d"], e["d"])
        i = int(np.argmin(np.linalg.norm(P - foot, axis=1)))
        return (foot[i], P[i], "Minimum distance", "") if ax is a else (P[i], foot[i], "Minimum distance", "")
    p, q, _ = line_line(axis_point(a), a["ent"]["d"], axis_point(b), b["ent"]["d"]) if ka == kb == "axis" else (a["center"], b["center"], 0)
    return p, q, "Minimum distance", ""


def max_distance(a, b):
    if parallel_pipes(a, b):
        c, u, pa, pb = _cross_section(a, b)
        ra, rb = radius(a), radius(b)
        return pa - u * ra, pb + u * rb, "Maximum distance (center + both radii)", ""
    pa, pb = sample_points(a), sample_points(b)
    if pa is None or pb is None:
        return None
    p, q = farthest(pa, pb)
    return p, q, "Maximum distance", "found from points sampled along the shapes"


# ---------------------------------------------------------------------------------------------- report
def describe(t, L, lu):
    k, e = t["k"], t["ent"]
    who = f"   ({t['name']})" if t.get("name") else ""
    if k == "vertex" or k == "origin":
        c = t["center"]
        return f"{'Origin' if k == 'origin' else 'Point'}   X = {c[0] * L:.4f}   Y = {c[1] * L:.4f}   Z = {c[2] * L:.4f} {lu}{who}"
    if k in ("plane", "axis"):
        return f"{t['label']}   (of the assembly)"
    sh = t["shape"]
    if k == "edge":
        s = f"Edge   length = {sh.length * L:.4f} {lu}"
        if e is not None and e["t"] == "circle":
            s += f"   radius = {e['r'] * L:.4f}   diameter = {2 * e['r'] * L:.4f} {lu}"
        return s + who
    s = f"Face   area = {sh.area * L * L:.4f} {lu}2"
    if e is not None and e["t"] in ("axis", "sphere"):
        s = f"{'Pipe / hole' if e['t'] == 'axis' else 'Sphere'}   radius = {e['r'] * L:.4f}   diameter = {2 * e['r'] * L:.4f} {lu}"
    return s + who


def report(asm, items, opts, unit):
    """(text, [(p, q, colour)])  for the picked items; opts = dict(xyz, mn, cc, mx); distances in `unit`."""
    import unitctl
    L = 1.0 / unitctl.SUFFIX_MM.get(unit, 1.0)
    lu = unit
    if not items:
        return "Click a point, an edge, a face or a pipe in the view.\nClick a second item to measure between them.", []
    try:
        ts = [thing(asm, it) for it in items]
    except am.MateError as ex:
        return f"Cannot measure: {ex}", []
    lines = [f"{n + 1}:  " + describe(t, L, lu) for n, t in enumerate(ts)]
    segs = []
    if len(ts) == 2:
        a, b = ts

        def show(res, col):
            if res is None:
                return
            p, q, label, note = res
            d = np.array(q) - np.array(p)
            segs.append((np.array(p), np.array(q), col))
            lines.append("")
            lines.append(f"{label}:  {np.linalg.norm(d) * L:.4f} {lu}")
            if opts["xyz"]:
                lines.append(f"      dX = {d[0] * L:.4f}   dY = {d[1] * L:.4f}   dZ = {d[2] * L:.4f} {lu}")
            if note:
                lines.append(f"      ({note})")
        if not (opts["mn"] or opts["cc"] or opts["mx"]):
            lines += ["", "Turn on Minimum, Center or Maximum."]
        for key, fn, col in (("mn", min_distance, GREEN), ("cc", center_distance, BLUE), ("mx", max_distance, RED)):
            if opts[key]:
                try:
                    res = fn(a, b)
                    if res is None:
                        lines += ["", {"mn": "Minimum", "cc": "Center", "mx": "Maximum"}[key] + " distance:  not available (one item is infinite)"]
                    else:
                        show(res, col)
                except Exception as ex:                         # noqa: BLE001 - one number failing must not hide the others
                    lines += ["", f"{key} failed: {ex}"]
    return "\n".join(lines), segs
