"""
sketch_ext.py - geometry of OTHER sketches used inside a sketch (SolidWorks: external references / pierce relation).

A sketch keeps a list  m.ext  of references.  Each one makes ordinary, fixed points (and for a line a construction line) in this sketch that
follow a point, line, arc or circle of an EARLIER sketch of the same part, so the normal relations (coincident, on line, distance, ...) can be put
on them.  Whenever the part is rebuilt the points are moved to where the referenced geometry now is, so editing the path of a sweep moves the
profile that is tied to it.  Kinds:
    "pt"      a point of the other sketch, projected straight onto this sketch's plane
    "ln"      a line of the other sketch, projected onto this plane (two points and a construction line between them)
    "pierce"  the point where a line / arc / circle of the other sketch passes through this sketch's plane (the sweep profile case)
A reference whose source is gone or does not reach the plane keeps its last position and is reported; nothing else breaks.
"""
import math

import numpy as np

import sk_tools as sk

TOL = 1e-6


def frame(plane):
    """(origin, x, y, normal) of a build123d Plane as numpy arrays."""
    return (np.array(tuple(plane.origin), float), np.array(tuple(plane.x_dir), float), np.array(tuple(plane.y_dir), float),
            np.array(tuple(plane.z_dir), float))


def lift(fr, uv):
    o, xd, yd, _ = fr
    return o + uv[0] * xd + uv[1] * yd


def project(fr, w):
    o, xd, yd, _ = fr
    d = np.asarray(w, float) - o
    return (float(d @ xd), float(d @ yd))


class Lost(Exception):
    pass


def _arc_hits(sm, key, sfr, tfr, near):
    """World points where the arc / circle `key` of sketch model `sm` (frame `sfr`) meets the plane `tfr`, nearest to `near` first."""
    o2, x2, y2, z2 = sfr
    o, _, _, zd = tfr
    u = np.cross(z2, zd)
    uu = float(u @ u)
    if uu < 1e-12:
        raise Lost("the curve lies parallel to the sketch plane")
    d1, d2 = float(z2 @ o2), float(zd @ o)
    p0 = (d1 * np.cross(zd, u) + d2 * np.cross(u, z2)) / uu
    q0 = np.array([(p0 - o2) @ x2, (p0 - o2) @ y2])
    e = np.array([u @ x2, u @ y2])
    e = e / np.linalg.norm(e)
    k, i = key
    if k == "ci":
        c, r = sm.pts[sm.cis[i]["c"]], sm.cis[i]["r"]
        t0, sw = 0.0, 2 * math.pi
    else:
        c, r, t0, sw = sk.arc_span(sm, i)
    c = np.array(c, float)
    w = q0 - c
    b = float(w @ e)
    disc = b * b - (float(w @ w) - r * r)
    if disc < -1e-12:
        raise Lost("the curve does not reach the sketch plane")
    disc = max(disc, 0.0)
    out = []
    for s in sorted({-b - math.sqrt(disc), -b + math.sqrt(disc)}):
        q = q0 + s * e
        a = math.atan2(q[1] - c[1], q[0] - c[0])
        if k == "ar" and ((a - t0) % (2 * math.pi)) > sw + 1e-9:
            continue
        out.append(o2 + q[0] * x2 + q[1] * y2)
    if not out:
        raise Lost("the arc does not reach the sketch plane")
    near = np.asarray(near, float)
    return sorted(out, key=lambda p: float(np.linalg.norm(p - near)))


def pierce_points(sm, key, sfr, tfr, near=None):
    """World points where the line / arc / circle `key` of sketch model `sm` passes through plane `tfr` (nearest to `near` first)."""
    k, i = key
    o, _, _, zd = tfr
    if k == "ln":
        a, b = sm.line_pts(i)
        A, B = lift(sfr, a), lift(sfr, b)
        d = B - A
        den = float(d @ zd)
        if abs(den) < 1e-12 * max(1.0, float(np.linalg.norm(d))):
            raise Lost("the line is parallel to the sketch plane")
        t = float((o - A) @ zd) / den
        if t < -TOL or t > 1 + TOL:
            raise Lost("the line stops before the sketch plane")
        return [A + t * d]
    if k in ("ar", "ci"):
        return _arc_hits(sm, key, sfr, tfr, near if near is not None else o)
    raise Lost("this kind of geometry cannot be pierced")


def source(doc, rec):
    sm, sp = doc.models.get(rec["sketch"]), doc.planes.get(rec["sketch"])
    if sm is None or sp is None:
        raise Lost("the sketch it refers to is not built before this one")
    return sm, frame(sp)


def resolve(doc, rec, tfr):
    """The new plane coordinates of the points of reference `rec`: [(pid, (u, v)), ...]  (raises Lost)."""
    sm, sfr = source(doc, rec)
    k, i = rec["ent"]
    kind = rec["kind"]
    if kind == "pt":
        if i not in sm.pts:
            raise Lost("the point is gone")
        return [(rec["pt"], project(tfr, lift(sfr, sm.pts[i])))]
    if kind == "ln":
        if i not in sm.lns:
            raise Lost("the line is gone")
        a, b = sm.line_pts(i)
        return [(rec["pts"][0], project(tfr, lift(sfr, a))), (rec["pts"][1], project(tfr, lift(sfr, b)))]
    if kind == "pierce":
        if not ((k == "ln" and i in sm.lns) or (k == "ar" and i in sm.ars) or (k == "ci" and i in sm.cis)):
            raise Lost("the curve is gone")
        hits = pierce_points(sm, (k, i), sfr, tfr, rec.get("last"))
        rec["last"] = [float(x) for x in hits[0]]
        return [(rec["pt"], project(tfr, hits[0]))]
    raise Lost("unknown kind of reference")


def _fix(m, pid, uv):
    """Put reference point `pid` at `uv` and hold it there. True when that is a different place than before."""
    old = m.pts.get(pid)
    moved = old is None or abs(old[0] - uv[0]) > 1e-9 or abs(old[1] - uv[1]) > 1e-9
    m.pts[pid] = [uv[0], uv[1]]
    for c in m.cons:
        if c["type"] == "fixed" and c["refs"] == [("pt", pid)]:
            moved = moved or tuple(c.get("xy", ())) != tuple(uv)
            c["xy"] = tuple(uv)
            return moved
    sk.con(m, "fixed", [("pt", pid)], xy=tuple(uv))
    return True


def apply(doc, fid, m):
    """Move the points of every reference of sketch `fid` to where the geometry they follow is now.
    Returns (problems as texts, True when a point moved - the sketch should then be stored again so the new places are kept)."""
    if not m.ext:
        return [], False
    plane = doc.planes.get(fid)
    if plane is None:
        return [], False
    tfr = frame(plane)
    keep, problems, changed = [], [], False
    for rec in m.ext:
        ids = [rec["pt"]] if rec["kind"] in ("pt", "pierce") else list(rec["pts"])
        if any(p not in m.pts for p in ids):                  # the user deleted its points: the reference goes with them
            continue
        if rec["kind"] == "ln" and rec["ln"] not in m.lns:
            continue
        try:
            for pid, uv in resolve(doc, rec, tfr):
                changed = _fix(m, pid, uv) or changed
            rec.pop("lost", None)
        except Lost as ex:
            rec["lost"] = str(ex)
            problems.append(f"Reference to {rec.get('label', 'another sketch')}: {ex} (it keeps its last position).")
        keep.append(rec)
    changed = changed or len(keep) != len(m.ext)
    m.ext = keep
    return problems, changed


# ------------------------------------------------------------------------------------------------ making references
def add_reference(doc, fid, m, kind, sketch, ent, near_world=None, label=None):
    """Add a reference to entity `ent` ("pt"|"ln"|"ar"|"ci", id) of earlier sketch `sketch` into model `m` of sketch `fid`.
    Returns a text when it cannot be made, else None (the points are placed at once)."""
    plane = doc.planes.get(fid)
    if plane is None:
        return "The sketch plane is not built."
    sm, sp = doc.models.get(sketch), doc.planes.get(sketch)
    if sm is None or sp is None:
        return "That sketch is not built before this one."
    tfr = frame(plane)
    rec = {"kind": kind, "sketch": sketch, "ent": [ent[0], ent[1]], "label": label or "sketch"}
    if near_world is not None:
        rec["last"] = [float(x) for x in near_world]
    try:
        if kind == "pt":
            rec["pt"] = m.add_point(0.0, 0.0)
        elif kind == "ln":
            a, b = m.add_point(0.0, 0.0), m.add_point(0.0, 0.0)
            rec["pts"], rec["ln"] = [a, b], m.add_line(a, b)
            m.constr.add(("ln", rec["ln"]))
        elif kind == "pierce":
            rec["pt"] = m.add_point(0.0, 0.0)
        for pid, uv in resolve(doc, rec, tfr):
            _fix(m, pid, uv)
    except Lost as ex:
        ids = [rec["pt"]] if "pt" in rec else list(rec.get("pts", []))
        if "ln" in rec:
            m.delete([("ln", rec["ln"])])
        m.delete([("pt", p) for p in ids if p in m.pts])
        return str(ex).capitalize() + "."
    m.ext.append(rec)
    return None


def ext_keys(m):
    """The point and line keys that belong to references (the editor draws them in their own colour)."""
    out = set()
    for rec in m.ext:
        for p in ([rec["pt"]] if "pt" in rec else rec.get("pts", [])):
            out.add(("pt", p))
        if "ln" in rec:
            out.add(("ln", rec["ln"]))
    return out
