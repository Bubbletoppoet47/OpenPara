"""dr_annot.py - what is drawn on a view: dimensions (length, diameter, radius, angle), center marks and centerlines.  No Qt here; the lines come out as numbers (sheet millimetres, y up)
and dr_render.py draws them.

A dimension / mark belongs to a VIEW and is attached to the GEOMETRY of the model, not to the paper: it keeps references in the view's own frame (a line's end points, a circle's centre
and radius), so the value it shows is the model's (never the size on the sheet: change the scale and it still says 100), and when the model changes the references are found again in
the new lines (rematch).  Where it is drawn is kept in paper millimetres (how far the dimension line is from what it measures), so it keeps its look at every scale.

    pick(proj, p, tol)               the point or edge of a view nearest to p (view frame): {"k": "pt", "p"} | {"k": "line", "a", "b"} | {"k": "circle", "c", "r"} | {"k": "arc", ...}
    DIM_TYPES                        the types of the Dimension tool, the ones of the Part sketcher's Dimension menu: Horizontal, Vertical, Length / distance, Diameter, Radius, Angle
    dim_check(dtype, refs)           do the picks fit the type the person chose?  "ok" | "more" (one more pick is needed) | "bad"; dim_make(dtype, refs) -> (kind, mode)
    kind_for(refs)                   what a pick sequence measures when no type is given: "linear" | "diameter" | "radius" | "angle" | None
    more_picks(refs)                 True when one more pick would still make a (different) dimension
    new_dim(refs, bbox, kind, mode)  a dimension record from what was picked; None when the picks do not make a dimension.  A linear dimension measures horizontally ("h"), vertically
                                     ("v") or along the two points ("a") as the person chose: nothing guesses it from where the pointer is
    value(dim)                       the measured number, in the model's units (mm) or degrees
    text(dim, fmt)                   what the dimension says: "100", "⌀12", "R6", "45°"  (fmt shows a length in the units of the program)
    shape(dim, s, o)                 {"segs": [(N, 2) arrays], "kinds", "heads": [(tip, inward, size)], "at", "dir", "anchor"} on the sheet for a view of scale s with its origin at o
    place(dim, s, o, pointer)        sets where the dimension is drawn from where the pointer is (sheet mm); what it measures does not change
    new_mark(kind, refs, bbox) / mark_kind_for(refs) / mark_shape(mark, s, o)    center marks (a circle) and centerlines (two parallel lines)
    rematch(annots, proj, bbox)      finds the references again in a view's new lines; the ones that cannot be found are marked "lost"
    distance(shp, p)                 how far p is from the drawn lines of a dimension / mark (sheet mm), for picking it
"""
import math

import numpy as np

ARROW = 3.0                  # mm on paper
GAP = 1.0                    # the space between the geometry and the start of an extension line
OVER = 1.6                   # how far an extension line goes past the dimension line
TEXT_H = 3.5                 # height of the numbers (ISO 3.5)
TEXT_LIFT = 0.9              # the numbers sit this far above their line
TEXT_W = 2.8                 # the width of one character of a number (for keeping a number clear of a line that is not straight under it)
MARK_OVER = 3.0              # a center mark / centerline reaches this far beyond the circle / the lines
TAU = 2 * math.pi


def _unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 1e-12 else (1.0, 0.0)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _wrap(a):
    return (a + math.pi) % TAU - math.pi


def _T(p, s, o):
    return (o[0] + s * p[0], o[1] + s * p[1])


# ---------------------------------------------------------------------------------------------------------------------------- picking
def _seg_dist(p, a, b):
    ab = _sub(b, a)
    L2 = _dot(ab, ab)
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, _dot(_sub(p, a), ab) / L2))
    return math.hypot(p[0] - (a[0] + ab[0] * t), p[1] - (a[1] + ab[1] * t))


def _in_arc(a0, a1, ang):
    return (ang - a0) % TAU <= (a1 - a0) % TAU + 1e-9


def _arc_dist(p, e):
    c, r = e["c"], e["r"]
    ang = math.atan2(p[1] - c[1], p[0] - c[0])
    if _in_arc(e["a0"], e["a1"], ang):
        return abs(math.hypot(p[0] - c[0], p[1] - c[1]) - r)
    pts = e["pts"]
    return min(math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]), math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]))


def ref_of(e):
    """The reference an entity of a projection is kept as (view frame); None for a free-form line (nothing to measure on it)."""
    t = e["t"]
    if t == "line":
        return {"k": "line", "a": tuple(e["a"]), "b": tuple(e["b"])}
    if t == "circle":
        return {"k": "circle", "c": tuple(e["c"]), "r": float(e["r"])}
    if t == "arc":
        return {"k": "arc", "c": tuple(e["c"]), "r": float(e["r"]), "a0": float(e["a0"]), "a1": float(e["a1"])}
    return None


def points_of(proj):
    """Every point a dimension can hold on to: the ends of the lines and arcs, the centres of the circles and arcs."""
    out = []
    for e in proj.vis:
        t = e["t"]
        if t == "line":
            out += [tuple(e["a"]), tuple(e["b"])]
        elif t == "arc":
            out += [tuple(e["pts"][0]), tuple(e["pts"][-1]), tuple(e["c"])]
        elif t == "circle":
            out.append(tuple(e["c"]))
    return out


def pick(proj, p, tol, edges=True, points=True):
    """The thing nearest to p (view frame) within tol: a point wins over an edge when it is within 0.6 tol of the pointer; None when nothing is near."""
    if points:
        best_pt, bd = None, tol * 0.6
        for q in points_of(proj):
            d = math.hypot(p[0] - q[0], p[1] - q[1])
            if d <= bd:
                best_pt, bd = q, d
        if best_pt is not None:
            return {"k": "pt", "p": best_pt}
    if not edges:
        return None
    best, bd = None, tol
    for e in proj.vis:
        t = e["t"]
        if t == "line":
            d = _seg_dist(p, e["a"], e["b"])
        elif t == "circle":
            d = abs(math.hypot(p[0] - e["c"][0], p[1] - e["c"][1]) - e["r"])
        elif t == "arc":
            d = _arc_dist(p, e)
        else:
            continue
        if d <= bd:
            best, bd = e, d
    return ref_of(best) if best is not None else None


def same_ref(a, b, tol=1e-6):
    if a["k"] != b["k"]:
        return False
    k = a["k"]
    if k == "pt":
        return math.hypot(a["p"][0] - b["p"][0], a["p"][1] - b["p"][1]) <= tol
    if k == "line":
        return all(math.hypot(a[x][0] - b[x][0], a[x][1] - b[x][1]) <= tol for x in ("a", "b"))
    return math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1]) <= tol and abs(a["r"] - b["r"]) <= tol


def _parallel(l1, l2, tol=1e-6):
    u, v = _unit(_sub(l1["b"], l1["a"])), _unit(_sub(l2["b"], l2["a"]))
    return abs(u[0] * v[1] - u[1] * v[0]) < tol


def kind_for(refs):
    """What a sequence of picks measures: one circle -> "diameter", one arc -> "radius", one line -> "linear" (its length); two points, a point and an edge, two circles, two parallel
    lines -> "linear" (the distance); two lines that are not parallel -> "angle".  None when the picks do not make a dimension (yet)."""
    ks = [r["k"] for r in refs]
    if len(refs) == 1:
        return {"circle": "diameter", "arc": "radius", "line": "linear"}.get(ks[0])
    if len(refs) == 2:
        if same_ref(refs[0], refs[1]):
            return None
        if ks == ["line", "line"]:
            return "linear" if _parallel(*refs) else "angle"
        return "linear"
    return None


def more_picks(refs):
    """True when one more pick is still meant to count (a line or a point may be measured against a second thing)."""
    return len(refs) < 2 and refs[0]["k"] in ("pt", "line")


def mark_kind_for(refs):
    """A center mark goes on one circle or arc; a centerline between two parallel lines."""
    ks = [r["k"] for r in refs]
    if len(refs) == 1 and ks[0] in ("circle", "arc"):
        return "center_mark"
    if len(refs) == 2 and ks == ["line", "line"] and not same_ref(refs[0], refs[1]) and _parallel(*refs):
        return "centerline"
    return None


# ---------------------------------------------------------------------------------------------------------------------------- the Dimension tool: the person picks the type
DIM_TYPES = [("h", "Horizontal"), ("v", "Vertical"), ("a", "Length / distance"), ("dia", "Diameter"), ("rad", "Radius"), ("ang", "Angle")]
DIM_LABEL = dict(DIM_TYPES)
DIM_NEED = {"h": "click a line, two points, a point and a vertical line, or two vertical lines",
            "v": "click a line, two points, a point and a horizontal line, or two horizontal lines",
            "a": "click a line, two points, a point and a line, or two parallel lines",
            "dia": "click a circle or an arc",
            "rad": "click an arc or a circle",
            "ang": "click two lines that meet"}
DIM_NEXT = {"h": "Click a second point or line to measure across to.", "v": "Click a second point or line to measure up to.", "a": "Click a second point or line to measure to.",
            "ang": "Click the second line."}
DIM_KIND = {"h": ("linear", "h"), "v": ("linear", "v"), "a": ("linear", "a"), "dia": ("diameter", None), "rad": ("radius", None), "ang": ("angle", None)}


def dim_check(dtype, refs):
    """Do the picks fit the type of dimension the person chose?  "ok": they make that dimension; "more": one more pick is needed; "bad": they cannot make it."""
    ks = [r["k"] for r in refs]
    n = len(refs)
    if dtype not in DIM_KIND:
        return "bad"
    if n == 0:
        return "more"
    if dtype in ("dia", "rad"):
        return "ok" if n == 1 and ks[0] in ("circle", "arc") else "bad"
    if dtype == "ang":
        if n == 1:
            return "more" if ks[0] == "line" else "bad"
        return "ok" if n == 2 and ks == ["line", "line"] and not same_ref(refs[0], refs[1]) and not _parallel(*refs) else "bad"
    if n == 1:                                                     # Horizontal, Vertical, Length / distance
        if ks[0] != "line":
            return "more"
        if dtype != "a":                                           # a line that has no width (no height) has nothing to measure alone: it asks for a second pick
            a, b = refs[0]["a"], refs[0]["b"]
            return "ok" if abs(b[0] - a[0] if dtype == "h" else b[1] - a[1]) > 1e-9 else "more"
    elif n != 2 or same_ref(refs[0], refs[1]):
        return "bad"
    lines = [r for r in refs if r["k"] == "line"]
    if len(lines) == 2 and not _parallel(*lines):
        return "bad"                                               # two lines that meet make an angle
    if dtype != "a" and n == 2:
        for ln in lines:                                           # across a line, horizontally: the line has to be vertical (vertically: horizontal)
            u = _unit(_sub(ln["b"], ln["a"]))
            if abs(u[0] if dtype == "h" else u[1]) > 1e-6:
                return "bad"
    return "ok" if value(new_dim(refs, (0.0, 0.0, 0.0, 0.0), "linear", dtype)) > 1e-9 else "bad"


def dim_make(dtype, refs):
    """(kind, mode) of the dimension the picks make with the type: ("linear", "h"), ("diameter", None) ...; None when they do not fit."""
    return DIM_KIND[dtype] if dim_check(dtype, refs) == "ok" else None


# ---------------------------------------------------------------------------------------------------------------------------- the dimension record
def new_dim(refs, bbox, kind=None, mode=None):
    kind = kind or kind_for(refs)
    if kind is None:
        return None
    d = {"type": kind, "refs": [dict(r) for r in refs], "bb": [float(x) for x in bbox], "lost": False}
    if kind == "linear":
        d.update({"mode": mode if mode in ("h", "v", "a") else "a", "side": 1, "dist": 8.0, "t": 0.0})
    elif kind in ("diameter", "radius"):
        d.update({"lab": [6.0, 6.0]})
    else:
        d.update({"s1": 1, "s2": 1, "rho": 14.0})
    return d


def _item_of(r):
    if r["k"] == "line":
        return ("l", tuple(r["a"]), tuple(r["b"]))
    if r["k"] == "pt":
        return ("p", tuple(r["p"]))
    return ("p", tuple(r["c"]))


def measure(dim):
    """(items, u, A, B) of a linear dimension, in the view's frame: the things it measures between (("p", P) a point, ("l", P0, P1) a line), the unit direction it measures along, and the
    two points the number is taken between.  A line against anything is measured at right angles to the line; the rest along the line between the points, or horizontally /
    vertically (dim["mode"] "a", "h", "v")."""
    refs = dim["refs"]
    if len(refs) == 1:
        items = [("p", tuple(refs[0]["a"])), ("p", tuple(refs[0]["b"]))]
    else:
        items = [_item_of(r) for r in refs]
    lines = [it for it in items if it[0] == "l"]
    A, B = items[0][1], items[1][1]
    if lines:
        d = _unit(_sub(lines[0][2], lines[0][1]))
        return items, (-d[1], d[0]), A, B
    mode = dim.get("mode", "a")
    if mode == "h":
        u = (1.0, 0.0)
    elif mode == "v":
        u = (0.0, 1.0)
    else:
        u = _unit(_sub(B, A))
    return items, u, A, B


def angle_frame(dim, s1=None, s2=None):
    """(I, a1, da) of an angle dimension, view frame: the corner, the direction of the first ray and the signed sweep to the second ray; None for lines that never meet."""
    l1, l2 = dim["refs"]
    s1 = dim["s1"] if s1 is None else s1
    s2 = dim["s2"] if s2 is None else s2
    p, r = l1["a"], _sub(l1["b"], l1["a"])
    q, s = l2["a"], _sub(l2["b"], l2["a"])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / den
    I = (p[0] + r[0] * t, p[1] + r[1] * t)
    d1, d2 = _unit(r), _unit(s)
    a1 = math.atan2(s1 * d1[1], s1 * d1[0])
    a2 = math.atan2(s2 * d2[1], s2 * d2[0])
    da = _wrap(a2 - a1)
    return (I, a1, da) if abs(da) > 1e-9 else None


def value(dim):
    """The number the dimension measures, in the model's own units (mm) or degrees: the model's, whatever the scale of the view."""
    t = dim["type"]
    if t == "linear":
        _items, u, A, B = measure(dim)
        return abs(_dot(_sub(B, A), u))
    if t == "diameter":
        return 2.0 * dim["refs"][0]["r"]
    if t == "radius":
        return dim["refs"][0]["r"]
    fr = angle_frame(dim)
    return math.degrees(abs(fr[2])) if fr else 0.0


def number_text(x, digits=4):
    s = f"{x:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def text(dim, fmt=None):
    """What the dimension says.  `fmt(mm)` shows a length in the units of the program (File > Units); without it, millimetres."""
    v = value(dim)
    t = dim["type"]
    if t == "angle":
        return number_text(v, 2) + "°"
    show = fmt or number_text
    if t == "diameter":
        return "⌀" + show(v)
    if t == "radius":
        return "R" + show(v)
    return show(v)


# ---------------------------------------------------------------------------------------------------------------------------- the lines of a dimension
def _head(tip, inward, size=ARROW):
    return (tuple(tip), tuple(inward), size)


def shape(dim, s, o):
    t = dim["type"]
    if t == "linear":
        return _linear(dim, s, o)
    if t in ("diameter", "radius"):
        return _round(dim, s, o)
    return _angle(dim, s, o)


def _sheet_items(dim, s, o):
    items, u, _A, _B = measure(dim)
    return [(it[0],) + tuple(_T(p, s, o) for p in it[1:]) for it in items], u


def _linear(dim, s, o):
    sit, u = _sheet_items(dim, s, o)
    n = (-u[1], u[0])
    side, dist = dim.get("side", 1), dim.get("dist", 8.0)
    q = lambda P: _dot(P, n)
    tt = lambda P: _dot(P, u)
    qs = [q(P) for it in sit for P in it[1:]]
    base = max(qs) if side > 0 else min(qs)
    qL = base + side * dist
    pt = lambda t_, q_=qL: (u[0] * t_ + n[0] * q_, u[1] * t_ + n[1] * q_)
    ts = [tt(it[1]) for it in sit]
    lo, hi = min(ts), max(ts)
    segs, kinds, heads = [], [], []
    for it, t_ in zip(sit, ts):
        if it[0] == "p":
            e = q(it[1])
        else:
            qa, qb = q(it[1]), q(it[2])
            qlo, qhi = min(qa, qb), max(qa, qb)
            if qlo <= qL <= qhi:
                continue                                           # the dimension line crosses the line itself: nothing to extend
            e = qhi if qL > qhi else qlo
        d = qL - e
        if abs(d) > GAP:
            sg = 1.0 if d > 0 else -1.0
            segs.append(np.array([pt(t_, e + sg * GAP), pt(t_, qL + sg * OVER)]))
            kinds.append("ext")
    if hi - lo > 1e-9:
        if hi - lo > 2.2 * ARROW:
            heads += [_head(pt(lo), u), _head(pt(hi), (-u[0], -u[1]))]
            segs.append(np.array([pt(lo), pt(hi)]))
        else:                                                      # too short for the arrows between the lines: they point in from outside
            heads += [_head(pt(lo), (-u[0], -u[1])), _head(pt(hi), u)]
            segs.append(np.array([pt(lo - 2.2 * ARROW), pt(hi + 2.2 * ARROW)]))
        kinds.append("dim")
    tm = (lo + hi) / 2.0 + dim.get("t", 0.0)
    ud = u
    if ud[0] < -1e-9 or (abs(ud[0]) <= 1e-9 and ud[1] < 0):        # the numbers read left to right (or bottom to top), never upside down
        ud = (-u[0], -u[1])
    nd = (-ud[1], ud[0])
    lift = TEXT_LIFT + TEXT_H / 2.0
    m = pt(tm)
    return {"segs": segs, "kinds": kinds, "heads": heads, "at": (m[0] + nd[0] * lift, m[1] + nd[1] * lift), "dir": ud, "anchor": "center", "ang": math.atan2(ud[1], ud[0]),
            "span": (lo, hi), "q": qL, "u": u, "n": n}


def _round(dim, s, o):
    r = dim["refs"][0]
    C = _T(r["c"], s, o)
    rs = s * r["r"]
    lab = dim.get("lab", [6.0, 6.0])
    e = _unit(lab)
    L = (C[0] + lab[0], C[1] + lab[1])
    far = math.hypot(lab[0], lab[1]) > rs
    P = (C[0] + e[0] * rs, C[1] + e[1] * rs)
    segs, heads = [], []
    size = min(ARROW, max(rs * 0.8, 0.6))
    if dim["type"] == "diameter":
        Q = (C[0] - e[0] * rs, C[1] - e[1] * rs)
        segs.append(np.array([Q, L if far else P]))
        heads.append(_head(Q, e, size))
    else:
        segs.append(np.array([C, L if far else P]))
    heads.append(_head(P, (-e[0], -e[1]), size))
    lift = TEXT_LIFT + TEXT_H / 2.0
    if far:                                                        # the label is outside the circle: it follows the end of the leader
        k = TEXT_H * 0.5 + 1.0
        at, anchor = (L[0] + e[0] * k, L[1] + e[1] * k), ("left" if e[0] >= -1e-9 else "right")
    else:
        mid = C if dim["type"] == "diameter" else ((C[0] + P[0]) / 2.0, (C[1] + P[1]) / 2.0)
        at, anchor = (mid[0] - e[1] * lift, mid[1] + e[0] * lift), "center"
    return {"segs": segs, "kinds": ["dim"], "heads": heads, "at": at, "dir": (1.0, 0.0), "anchor": anchor, "ang": 0.0, "c": C, "r": rs}


def _angle(dim, s, o):
    fr = angle_frame(dim)
    if fr is None:
        return {"segs": [], "kinds": [], "heads": [], "at": (0.0, 0.0), "dir": (1.0, 0.0), "anchor": "center", "ang": 0.0}
    I, a1, da = fr
    Is = _T(I, s, o)
    rho = max(dim.get("rho", 14.0), 2.0)
    n = max(8, int(abs(da) / TAU * 96))
    arc = np.array([(Is[0] + rho * math.cos(a1 + da * k / n), Is[1] + rho * math.sin(a1 + da * k / n)) for k in range(n + 1)])
    segs, kinds, heads = [arc], ["dim"], []
    l1, l2 = dim["refs"]
    for a, ln in ((a1, l1), (a1 + da, l2)):
        e = (math.cos(a), math.sin(a))
        reach = max(0.0, _dot(_sub(_T(ln["a"], s, o), Is), e), _dot(_sub(_T(ln["b"], s, o), Is), e))
        if reach < rho:                                            # the line stops short of the arc: an extension line takes over
            lo = reach + GAP
            segs.append(np.array([(Is[0] + e[0] * lo, Is[1] + e[1] * lo), (Is[0] + e[0] * (rho + OVER), Is[1] + e[1] * (rho + OVER))]))
            kinds.append("ext")
    sg = 1.0 if da > 0 else -1.0
    sz = min(ARROW, 0.25 * rho)
    for a, d in ((a1, 1.0), (a1 + da, -1.0)):
        tip = (Is[0] + rho * math.cos(a), Is[1] + rho * math.sin(a))
        heads.append(_head(tip, (-math.sin(a) * sg * d, math.cos(a) * sg * d), sz))
    th = a1 + da / 2.0
    w = TEXT_W * len(text(dim))                                    # the number is a box: keep its nearest corner, not its middle, clear of the arc
    rr = rho + TEXT_LIFT + abs(math.cos(th)) * w / 2.0 + abs(math.sin(th)) * TEXT_H / 2.0
    return {"segs": segs, "kinds": kinds, "heads": heads, "at": (Is[0] + rr * math.cos(th), Is[1] + rr * math.sin(th)), "dir": (1.0, 0.0), "anchor": "center", "ang": 0.0,
            "corner": Is}


# ---------------------------------------------------------------------------------------------------------------------------- placing
def place(dim, s, o, pointer):
    """Puts the dimension where the pointer is (sheet mm): how far the dimension line is from what it measures, on which side, where along it; the quadrant and the radius of an angle;
    the label of a circle.  What it measures (horizontally, vertically, along the line) was chosen with the type and stays."""
    t = dim["type"]
    if t == "linear":
        sit, u = _sheet_items(dim, s, o)
        n = (-u[1], u[0])
        q = lambda P: _dot(P, n)
        qs = [q(P) for it in sit for P in it[1:]]
        hi, lo = max(qs), min(qs)
        qp = _dot(pointer, n)
        if qp >= (hi + lo) / 2.0:
            dim["side"], dim["dist"] = 1, qp - hi
        else:
            dim["side"], dim["dist"] = -1, lo - qp
        ts = [_dot(it[1], u) for it in sit]
        dim["t"] = _dot(pointer, u) - (min(ts) + max(ts)) / 2.0
    elif t in ("diameter", "radius"):
        C = _T(dim["refs"][0]["c"], s, o)
        lab = [pointer[0] - C[0], pointer[1] - C[1]]
        dim["lab"] = lab if math.hypot(*lab) > 1e-6 else [1.0, 1.0]
    else:
        fr = angle_frame(dim, 1, 1)
        if fr is None:
            return
        I = _T(fr[0], s, o)
        d = (pointer[0] - I[0], pointer[1] - I[1])
        theta = math.atan2(d[1], d[0])
        for s1 in (1, -1):
            for s2 in (1, -1):
                f = angle_frame(dim, s1, s2)
                if f is None:
                    continue
                a1, da = f[1], f[2]
                lo, hi = (a1, a1 + da) if da > 0 else (a1 + da, a1)
                if _in_arc(lo, hi, theta):
                    dim["s1"], dim["s2"] = s1, s2
        dim["rho"] = max(2.0, math.hypot(*d))


# ---------------------------------------------------------------------------------------------------------------------------- marks
def new_mark(kind, refs, bbox):
    return {"type": kind, "refs": [dict(r) for r in refs], "bb": [float(x) for x in bbox], "lost": False}


def mark_shape(mark, s, o):
    """The lines of a center mark (a cross a little larger than the circle) or of a centerline (dash-dot, midway between two parallel lines and a little longer than they are):
    {"segs": [(2, 2) arrays], "style": "solid" | "dashdot"}."""
    if mark["type"] == "center_mark":
        r = mark["refs"][0]
        C = _T(r["c"], s, o)
        R = s * r["r"] + MARK_OVER
        return {"segs": [np.array([(C[0] - R, C[1]), (C[0] + R, C[1])]), np.array([(C[0], C[1] - R), (C[0], C[1] + R)])], "style": "solid"}
    l1, l2 = mark["refs"]
    u = _unit(_sub(l1["b"], l1["a"]))
    if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):            # drawn from left to right (bottom to top): the dashes begin at the same end whichever way the line was made
        u = (-u[0], -u[1])
    n = (-u[1], u[0])
    pts = [_T(p, s, o) for p in (l1["a"], l1["b"], l2["a"], l2["b"])]
    ts = [_dot(p, u) for p in pts]
    q = (_dot(pts[0], n) + _dot(pts[2], n)) / 2.0
    lo, hi = min(ts) - MARK_OVER, max(ts) + MARK_OVER
    return {"segs": [np.array([(u[0] * lo + n[0] * q, u[1] * lo + n[1] * q), (u[0] * hi + n[0] * q, u[1] * hi + n[1] * q)])], "style": "dashdot"}


# ---------------------------------------------------------------------------------------------------------------------------- finding the references again
def _norm(p, bb):
    return ((p[0] - bb[0]) / max(bb[2] - bb[0], 1e-9), (p[1] - bb[1]) / max(bb[3] - bb[1], 1e-9))


def _pdist(p, q, bb_old, bb_new):
    """How far apart two points are, as a fraction of the view's box: the smaller of the distance measured in the box (a feature that keeps its place in the part) and the distance
    in model units (a feature that keeps its size and place while the part grows)."""
    a, b = _norm(p, bb_old), _norm(q, bb_new)
    rel = math.hypot(a[0] - b[0], a[1] - b[1])
    size = max(bb_new[2] - bb_new[0], bb_new[3] - bb_new[1], 1e-9)
    return min(rel, math.hypot(p[0] - q[0], p[1] - q[1]) / size)


def _best(ref, cands, bb_old, bb_new):
    best, bd = None, 1e9
    for c in cands:
        if c["k"] != ref["k"]:
            continue
        if ref["k"] == "pt":
            d = _pdist(ref["p"], c["p"], bb_old, bb_new)
        elif ref["k"] == "line":
            d = min(_pdist(ref["a"], c["a"], bb_old, bb_new) + _pdist(ref["b"], c["b"], bb_old, bb_new),
                    _pdist(ref["a"], c["b"], bb_old, bb_new) + _pdist(ref["b"], c["a"], bb_old, bb_new)) / 2.0
        else:
            d = _pdist(ref["c"], c["c"], bb_old, bb_new) + abs(math.log(max(c["r"], 1e-9) / max(ref["r"], 1e-9))) * 0.25
        if d < bd:
            best, bd = c, d
    return best, bd


def rematch(annots, proj, bbox, tol=0.12):
    """The view's lines changed (the model did): every reference of the dimensions / marks in `annots` is found again - the nearest entity of its kind, measured against the view's own
    box, so a part that grew longer keeps its dimensions on the same edges.  A reference that is not found within `tol` of the box (or two that would become the same one) marks its
    dimension "lost" and leaves it as it was.  -> the number of annotations that are lost now."""
    cands = [{"k": "pt", "p": p} for p in points_of(proj)] + [r for r in (ref_of(e) for e in proj.vis) if r]
    lost = 0
    for a in annots:
        old = a.get("bb") or bbox
        new = []
        for r in a["refs"]:
            c, d = _best(r, cands, old, bbox)
            if c is None or d > tol:
                new = None
                break
            new.append(c)
        if new is not None and len(new) == 2 and same_ref(new[0], new[1]):
            new = None
        if new is None:
            a["lost"] = True
            lost += 1
        else:
            a["refs"], a["lost"], a["bb"] = [dict(r) for r in new], False, [float(x) for x in bbox]
    return lost


# ---------------------------------------------------------------------------------------------------------------------------- hit test
def distance(shp, p):
    """How far p is from the lines of a dimension / mark (and from its number): sheet mm."""
    best = 1e9
    for sg in shp.get("segs", []):
        for i in range(len(sg) - 1):
            best = min(best, _seg_dist(p, sg[i], sg[i + 1]))
    at = shp.get("at")
    if at is not None:
        best = min(best, max(0.0, math.hypot(p[0] - at[0], p[1] - at[1]) - TEXT_H))
    return best
