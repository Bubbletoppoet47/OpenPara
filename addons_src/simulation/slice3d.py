"""
slice3d.py - cut solids with a plane and turn the cut into a sketch (for the 1D / 2D simulations).

  plane_specs(kind, ...)          the planes you can cut with (the model's base planes and its reference planes)
  shifted(spec, offset, flip)     a plane moved along its normal (and turned over)
  slice_bodies(bodies, spec)      -> loops   the outlines the plane cuts from the bodies (lengths in mm, in the plane's own 2D axes)
  region_parts(geom, loops)       -> {face id: body index} which body each closed region of the sketch came from

A plane spec is {"o": origin, "n": normal, "u": 2D x axis, "v": 2D y axis} (numpy 3-vectors, millimetres).  The 2D axes are the ones a
sketch drawn on that plane would have, so a slice of the Front plane looks like a sketch on the Front plane.
The loops have the form slice_sketch.build() reads:  [{"part": index, "closed": bool, "edges": [edge, ...]}],
edge = {"t": "line", "a", "b"} | {"t": "circle", "c", "r"} | {"t": "arc", "c", "r", "s", "m", "e"} | {"t": "poly", "pts"}.
"""
import math

import numpy as np
from build123d import Face, Plane, Location

import refgeo

BASE = {"Front": Plane.XZ, "Top": Plane.XY, "Right": Plane.YZ}


def _vec(v):
    return np.array([v.X, v.Y, v.Z], float)


def base_spec(name):
    p = BASE[name]
    return {"o": np.zeros(3), "n": _vec(p.z_dir), "u": _vec(p.x_dir), "v": _vec(p.y_dir)}


def spec_from_entity(e):
    """A refgeo plane entity {"p", "n", "x"} -> a plane spec (sketch origin = the model origin projected on the plane)."""
    n = np.array(e["n"], float)
    n /= np.linalg.norm(n)
    p = np.array(e["p"], float)
    x = np.array(e.get("x", (1.0, 0.0, 0.0)), float)
    x = x - np.dot(x, n) * n
    if np.linalg.norm(x) < 1e-9:
        x = np.array(refgeo.frame_x(n), float)
    x /= np.linalg.norm(x)
    v = np.cross(n, x)
    return {"o": n * float(np.dot(n, p)), "n": n, "u": x, "v": v / np.linalg.norm(v)}


def shifted(spec, offset=0.0, flip=False):
    n, u, v = spec["n"], spec["u"], spec["v"]
    o = spec["o"] + n * float(offset)
    if flip:
        n, v = -n, -v
    return {"o": o, "n": n, "u": u, "v": v}


def part_plane_specs(doc):
    """[(name, spec)] for a part: Front / Top / Right and its reference planes."""
    out = [(nm, base_spec(nm)) for nm in ("Front", "Top", "Right")]
    for f in doc.features:
        e = doc.refgeo.get(f["id"]) if hasattr(doc, "refgeo") else None
        if e is not None and e.get("t") == "plane" and not f.get("suppressed"):
            out.append((f["name"], spec_from_entity(e)))
    return out


def asm_plane_specs(asm, poses=None):
    """[(name, spec)] for an assembly: its Front / Top / Right planes and its own reference planes."""
    out = [(nm, base_spec(nm)) for nm in ("Front", "Top", "Right")]
    for r in asm.refs:
        if r.get("kind") == "refplane":
            try:
                out.append((r["name"], spec_from_entity(asm.ref_entity(r["id"], poses))))
            except Exception:
                continue
    return out


# ---------------------------------------------------------------------------------------------- the cut
def _uv(spec, p):
    q = np.array(p, float) - spec["o"]
    return [float(q @ spec["u"]), float(q @ spec["v"])]


def _edge_json(spec, e):
    t = e.geom_type.name
    if t == "LINE":
        return {"t": "line", "a": _uv(spec, _vec(e.start_point())), "b": _uv(spec, _vec(e.end_point()))}
    if t == "CIRCLE":
        c = _uv(spec, _vec(e.arc_center))
        r = float(e.radius)
        s, en = e.start_point(), e.end_point()
        if _vec(s).tolist() == _vec(en).tolist() or float(np.linalg.norm(_vec(s) - _vec(en))) < 1e-7 * max(1.0, r):
            return {"t": "circle", "c": c, "r": r}
        return {"t": "arc", "c": c, "r": r, "s": _uv(spec, _vec(s)), "m": _uv(spec, _vec(e.position_at(0.5))), "e": _uv(spec, _vec(en))}
    n = 32
    return {"t": "poly", "pts": [_uv(spec, _vec(e.position_at(i / (n - 1)))) for i in range(n)]}


def _ends(e):
    t = e["t"]
    if t == "line":
        return tuple(e["a"]), tuple(e["b"])
    if t == "arc":
        return tuple(e["s"]), tuple(e["e"])
    if t == "poly":
        return tuple(e["pts"][0]), tuple(e["pts"][-1])
    return None, None


def _reversed(e):
    t = e["t"]
    if t == "line":
        return {"t": "line", "a": e["b"], "b": e["a"]}
    if t == "arc":
        return dict(e, s=e["e"], e=e["s"])
    if t == "poly":
        return {"t": "poly", "pts": list(reversed(e["pts"]))}
    return e


def _chain(edges, tol):
    """Edges of one wire -> in order, each starting where the one before ends (circles stand alone)."""
    close = lambda p, q: abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol
    rest = [e for e in edges if e["t"] != "circle"]
    out = [[e] for e in edges if e["t"] == "circle"]
    while rest:
        cur = [rest.pop(0)]
        grow = True
        while grow and rest:
            grow = False
            head, tail = _ends(cur[0])[0], _ends(cur[-1])[1]
            for i, e in enumerate(rest):
                a, b = _ends(e)
                if close(tail, a):
                    cur.append(rest.pop(i)); grow = True; break
                if close(tail, b):
                    cur.append(_reversed(rest.pop(i))); grow = True; break
                if close(head, b):
                    cur.insert(0, rest.pop(i)); grow = True; break
                if close(head, a):
                    cur.insert(0, _reversed(rest.pop(i))); grow = True; break
        out.append(cur)
    return out


def _section_faces(solid, spec):
    """The faces cut from a shape by the plane (a big square face lying in the plane, intersected with the shape)."""
    bb = solid.bounding_box()
    size = 2.0 * float(np.linalg.norm([bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z])) + 10.0
    cen = np.array([(bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, (bb.min.Z + bb.max.Z) / 2])
    n = spec["n"]
    c = cen - n * (float(np.dot(cen - spec["o"], n)))            # the centre of the shape projected onto the plane
    pl = Plane(origin=tuple(c), x_dir=tuple(spec["u"]), z_dir=tuple(n))
    big = Face.make_rect(size, size, plane=pl)
    res = solid.intersect(big)
    return list(res.faces()) if res is not None else []


def slice_bodies(bodies, spec, tol=1e-4):
    """bodies = [(index, solid)] (solids already in their place) -> list of loops (see the module doc)."""
    loops = []
    for idx, solid in bodies:
        if solid is None:
            continue
        try:
            faces = _section_faces(solid, spec)
        except Exception:
            continue
        for f in faces:
            wires = [f.outer_wire()] + list(f.inner_wires())
            for w in wires:
                edges = []
                for e in w.edges():
                    try:
                        edges.append(_edge_json(spec, e))
                    except Exception:
                        pass
                for chain in _chain(edges, 1e-5):
                    loops.append({"part": idx, "closed": True, "edges": chain})
    return loops


# ---------------------------------------------------------------------------------------------- which body is a region
def _crossings(polys, y, x):
    """How many times the horizontal ray from (x, y) to +x crosses the polygons (even-odd rule)."""
    n = 0
    for pts in polys:
        for i in range(len(pts)):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % len(pts)]
            if (y0 > y) != (y1 > y):
                xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                if xc > x:
                    n += 1
    return n


def interior_point(polys):
    """A point inside the region bounded by these loops (the outer one first, the holes after), by scanning a few horizontal lines."""
    ys = [p[1] for pts in polys for p in pts]
    xs = [p[0] for pts in polys for p in pts]
    y0, y1 = min(ys), max(ys)
    for frac in (0.5, 0.37, 0.63, 0.25, 0.75, 0.13, 0.87, 0.07, 0.93):
        y = y0 + (y1 - y0) * frac
        xv = []
        for pts in polys:
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                if (a[1] > y) != (b[1] > y):
                    xv.append(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
        xv.sort()
        best = None
        for i in range(0, len(xv) - 1, 2):
            w = xv[i + 1] - xv[i]
            if best is None or w > best[0]:
                best = (w, 0.5 * (xv[i] + xv[i + 1]))
        if best is not None and best[0] > 1e-9:
            return (best[1], y)
    return (0.5 * (min(xs) + max(xs)), 0.5 * (y0 + y1))


def region_parts(geom, loops):
    """{face id: body index}: the body whose cut outlines contain an inner point of the region (None when no body does)."""
    import slice_sketch as ss
    by_body = {}
    for lp in loops:
        by_body.setdefault(lp["part"], []).append(ss.polygon_of(lp))
    out = {}
    for f in geom["faces"]:
        polys = [f["poly"]] + [h["poly"] if isinstance(h, dict) else h for h in f.get("holes", [])]
        try:
            x, y = interior_point([p for p in polys if len(p) >= 3])
        except ValueError:
            out[f["id"]] = None
            continue
        hit = None
        for b, pl in by_body.items():
            if _crossings(pl, y, x) % 2 == 1:
                hit = b
                break
        out[f["id"]] = hit
    return out
