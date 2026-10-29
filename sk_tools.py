"""
sk_tools.py - the geometry behind the sketch tools (no Qt, no 3D): every tool builds entities and constraints in a sketcher_core.Model.

Specs for points: a point is given either as an existing point ("pt", id) or as plain coordinates (x, y); new coordinates make a new point.
All functions return what they made (ids), they never solve: the caller runs solve_model() afterwards.
Constraints made on the user's behalf (horizontal / vertical from a drawn line, ...) carry "auto": True so that solve_model() can drop the
ones that fight the constraints the user put there.
"""
import math

import numpy as np

import sketcher_core as sc

TWO_PI = 2 * math.pi
AUTO_DEG = 2.0                      # a drawn line this close to horizontal / vertical gets that constraint


# ---------------------------------------------------------------------------------------------------- basics
def new_model(unit="Metric (mm, kg, N, s, MPa)"):
    m = sc.Model()
    m.unit_system = unit
    return m


def is_ref(p):
    return isinstance(p, (tuple, list)) and len(p) == 2 and p[0] == "pt"


def xy(m, p):
    return tuple(m.pts[p[1]]) if is_ref(p) else (float(p[0]), float(p[1]))


def pid(m, p):
    return p[1] if is_ref(p) else m.add_point(p[0], p[1])


def con(m, typ, refs, auto=False, **kw):
    c = m.add_con(typ, refs, **kw)
    if auto:
        c["auto"] = True
    return c


def line(m, a, b, construction=False):
    lid = m.add_line(pid(m, a), pid(m, b))
    if construction:
        m.constr.add(("ln", lid))
    return lid


def auto_hv(m, lid, deg=AUTO_DEG):
    (ax, ay), (bx, by) = m.line_pts(lid)
    dx, dy = bx - ax, by - ay
    if math.hypot(dx, dy) < 1e-9:
        return None
    t = math.tan(math.radians(deg))
    if abs(dy) <= t * abs(dx):
        return con(m, "horizontal", [("ln", lid)], auto=True)
    if abs(dx) <= t * abs(dy):
        return con(m, "vertical", [("ln", lid)], auto=True)
    return None


def add_line(m, a, b, construction=False, auto=True):
    lid = line(m, a, b, construction)
    if auto and not construction:
        auto_hv(m, lid)
    return lid


def tangent_join(m, lid, aid, p):
    """Line `lid` meets arc `aid` tangentially at their shared end point `p`: a construction radius from the arc's centre to `p` is
    perpendicular to the line.  (A plain 'tangent' row together with the end point sitting on the arc is degenerate to first order, which
    would make the sketch report freedom that is not there.)"""
    rad = m.add_line(m.ars[aid]["c"], p)
    m.constr.add(("ln", rad))
    con(m, "perpendicular", [("ln", rad), ("ln", lid)])
    return rad


def add_midpoint_line(m, mid, end, construction=False):
    """A line given by its middle and one end: the far end is the mirror image, a midpoint constraint keeps it in the middle."""
    mx, my = xy(m, mid)
    ex, ey = xy(m, end)
    a = (2 * mx - ex, 2 * my - ey)
    pm = pid(m, mid)
    lid = line(m, a, end, construction)
    con(m, "midpoint", [("pt", pm), ("ln", lid)])
    return lid


def unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 1e-12 else (1.0, 0.0)


def perp(u):
    return (-u[1], u[0])


# ---------------------------------------------------------------------------------------------------- rectangles
def _loop(m, pts, close=True):
    ids = [pid(m, p) for p in pts]
    n = len(ids)
    return ids, [m.add_line(ids[i], ids[(i + 1) % n]) for i in range(n if close else n - 1)]


def add_rect_corner(m, p0, p2):
    (x0, y0), (x2, y2) = xy(m, p0), xy(m, p2)
    ids, ls = _loop(m, [p0, (x2, y0), p2, (x0, y2)])
    for i in (0, 2):
        con(m, "horizontal", [("ln", ls[i])], auto=True)
    for i in (1, 3):
        con(m, "vertical", [("ln", ls[i])], auto=True)
    return {"pts": ids, "lns": ls}


def _centre_marks(m, centre, ids):
    """Two construction diagonals with the centre point on both middles (a centre rectangle stays centred)."""
    cp = pid(m, centre)
    d = [line(m, ("pt", ids[0]), ("pt", ids[2]), True), line(m, ("pt", ids[1]), ("pt", ids[3]), True)]
    for lid in d:
        con(m, "midpoint", [("pt", cp), ("ln", lid)])
    return cp, d


def add_rect_center(m, c, corner):
    (cx, cy), (qx, qy) = xy(m, c), xy(m, corner)
    ox, oy = 2 * cx - qx, 2 * cy - qy
    ids, ls = _loop(m, [(ox, oy), (qx, oy), corner, (ox, qy)])
    for i in (0, 2):
        con(m, "horizontal", [("ln", ls[i])], auto=True)
    for i in (1, 3):
        con(m, "vertical", [("ln", ls[i])], auto=True)
    cp, d = _centre_marks(m, c, ids)
    return {"pts": ids + [cp], "lns": ls + d}


def _perp_rect(m, ids, ls):
    for i in range(3):
        con(m, "perpendicular", [("ln", ls[i]), ("ln", ls[i + 1])])


def add_rect_3pt(m, p0, p1, p2):
    """Corner, the next corner (fixes the angle), then a point that sets the width: a turned rectangle."""
    a, b, q = xy(m, p0), xy(m, p1), xy(m, p2)
    u = unit((b[0] - a[0], b[1] - a[1]))
    n = perp(u)
    w = (q[0] - b[0]) * n[0] + (q[1] - b[1]) * n[1]
    ids, ls = _loop(m, [p0, p1, (b[0] + n[0] * w, b[1] + n[1] * w), (a[0] + n[0] * w, a[1] + n[1] * w)])
    _perp_rect(m, ids, ls)
    return {"pts": ids, "lns": ls}


def add_rect_3pt_center(m, c, p1, p2):
    """Centre, the middle of one side (axis and half length), then a point that sets the half width: a turned centred rectangle."""
    cc, s, q = xy(m, c), xy(m, p1), xy(m, p2)
    u = unit((s[0] - cc[0], s[1] - cc[1]))
    hl = math.hypot(s[0] - cc[0], s[1] - cc[1])
    n = perp(u)
    hw = abs((q[0] - cc[0]) * n[0] + (q[1] - cc[1]) * n[1])
    pts = [(cc[0] - u[0] * hl - n[0] * hw, cc[1] - u[1] * hl - n[1] * hw), (cc[0] + u[0] * hl - n[0] * hw, cc[1] + u[1] * hl - n[1] * hw),
           (cc[0] + u[0] * hl + n[0] * hw, cc[1] + u[1] * hl + n[1] * hw), (cc[0] - u[0] * hl + n[0] * hw, cc[1] - u[1] * hl + n[1] * hw)]
    ids, ls = _loop(m, pts)
    _perp_rect(m, ids, ls)
    cp, d = _centre_marks(m, c, ids)
    return {"pts": ids + [cp], "lns": ls + d}


def add_parallelogram(m, p0, p1, p2):
    a, b, q = xy(m, p0), xy(m, p1), xy(m, p2)
    ids, ls = _loop(m, [p0, p1, p2, (a[0] + q[0] - b[0], a[1] + q[1] - b[1])])
    con(m, "parallel", [("ln", ls[0]), ("ln", ls[2])])
    con(m, "parallel", [("ln", ls[1]), ("ln", ls[3])])
    return {"pts": ids, "lns": ls}


# ---------------------------------------------------------------------------------------------------- circles and arcs
def add_circle(m, c, q):
    (cx, cy), (qx, qy) = xy(m, c), xy(m, q)
    r = math.hypot(qx - cx, qy - cy)
    if r < 1e-9:
        return None
    return m.add_circle(pid(m, c), r)


def circumcircle(a, b, c):
    """(centre, radius) of the circle through three points, or None when they are in a line."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def add_circle_3pt(m, p0, p1, p2):
    cc = circumcircle(xy(m, p0), xy(m, p1), xy(m, p2))
    if cc is None:
        return None
    return m.add_circle(m.add_point(*cc[0]), cc[1])


def ang(c, p):
    return math.atan2(p[1] - c[1], p[0] - c[0])


def add_arc_center(m, c, s, e, clockwise=False):
    """Centre, start point, then a point that gives the end angle.  The arc runs counter-clockwise from start to end (the model's
    convention); `clockwise` swaps the two so that it is the arc drawn the other way round."""
    cc, ss, ee = xy(m, c), xy(m, s), xy(m, e)
    r = math.hypot(ss[0] - cc[0], ss[1] - cc[1])
    if r < 1e-9 or abs(((ang(cc, ee) - ang(cc, ss)) + math.pi) % TWO_PI - math.pi) < 1e-9:
        return None
    a = ang(cc, ee)
    pe = m.add_point(cc[0] + r * math.cos(a), cc[1] + r * math.sin(a)) if not is_ref(e) else e[1]
    ps = pid(m, s)
    pc = pid(m, c)
    return m.add_arc(pc, pe, ps) if clockwise else m.add_arc(pc, ps, pe)


def add_arc_3pt(m, s, e, mid):
    """Start point, end point, then a point on the arc."""
    S, E, M = xy(m, s), xy(m, e), xy(m, mid)
    cc = circumcircle(S, M, E)
    if cc is None:
        return None
    c = m.add_point(*cc[0])
    turn = (M[0] - S[0]) * (E[1] - M[1]) - (M[1] - S[1]) * (E[0] - M[0])
    ps, pe = pid(m, s), pid(m, e)
    return m.add_arc(c, ps, pe) if turn > 0 else m.add_arc(c, pe, ps)


def tangent_at(m, start_pid, host):
    """Direction in which a tangent arc leaves `host` (a line or an arc) at its end `start_pid`; None if that point is not an end of it."""
    k, i = host
    if k == "ln":
        a, b = m.lns[i]
        if start_pid == b:
            return unit((m.pts[b][0] - m.pts[a][0], m.pts[b][1] - m.pts[a][1]))
        if start_pid == a:
            return unit((m.pts[a][0] - m.pts[b][0], m.pts[a][1] - m.pts[b][1]))
        return None
    ar = m.ars[i]
    c = m.pts[ar["c"]]
    p = m.pts[start_pid]
    r = (p[0] - c[0], p[1] - c[1])
    if start_pid == ar["e"]:
        return unit(perp(r))
    if start_pid == ar["s"]:
        return unit((-perp(r)[0], -perp(r)[1]))
    return None


def add_arc_tangent(m, start_pid, host, end):
    """An arc that leaves the end `start_pid` of a line (or arc) tangentially and ends at `end`."""
    t = tangent_at(m, start_pid, host)
    if t is None:
        return None
    P, Q = m.pts[start_pid], xy(m, end)
    n = perp(t)
    d = (Q[0] - P[0], Q[1] - P[1])
    den = 2 * (d[0] * n[0] + d[1] * n[1])
    if abs(den) < 1e-9:
        return None
    r = (d[0] ** 2 + d[1] ** 2) / den                           # signed: > 0 centre on the left of the direction of travel
    C = (P[0] + n[0] * r, P[1] + n[1] * r)
    pc = m.add_point(*C)
    pe = pid(m, end)
    aid = m.add_arc(pc, start_pid, pe) if r > 0 else m.add_arc(pc, pe, start_pid)
    if host[0] == "ln":
        tangent_join(m, host[1], aid, start_pid)
    return aid


# ---------------------------------------------------------------------------------------------------- slots
def _slot_straight(m, A, B, r, centre_marks=None):
    a, b = xy(m, A), xy(m, B)
    u = unit((b[0] - a[0], b[1] - a[1]))
    n = perp(u)
    pa, pb = pid(m, A), pid(m, B)
    a1, b1 = m.add_point(a[0] + n[0] * r, a[1] + n[1] * r), m.add_point(b[0] + n[0] * r, b[1] + n[1] * r)
    b2, a2 = m.add_point(b[0] - n[0] * r, b[1] - n[1] * r), m.add_point(a[0] - n[0] * r, a[1] - n[1] * r)
    top, bot = m.add_line(a1, b1), m.add_line(b2, a2)
    capB, capA = m.add_arc(pb, b2, b1), m.add_arc(pa, a1, a2)
    for ln_, ends in ((top, ((capA, a1), (capB, b1))), (bot, ((capA, a2), (capB, b2)))):
        for ar_, p in ends:
            tangent_join(m, ln_, ar_, p)
    con(m, "equal", [("ar", capA), ("ar", capB)])
    cl = m.add_line(pa, pb)
    m.constr.add(("ln", cl))
    return {"lns": [top, bot], "ars": [capA, capB], "centre_line": cl, "pts": [pa, pb, a1, b1, b2, a2]}


def add_slot_straight(m, A, B, W):
    a, b, w = xy(m, A), xy(m, B), xy(m, W)
    u = unit((b[0] - a[0], b[1] - a[1]))
    r = abs((w[0] - a[0]) * perp(u)[0] + (w[1] - a[1]) * perp(u)[1])
    if r < 1e-9 or math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9:
        return None
    return _slot_straight(m, A, B, r)


def add_slot_center(m, C, E, W):
    c, e, w = xy(m, C), xy(m, E), xy(m, W)
    u = unit((e[0] - c[0], e[1] - c[1]))
    r = abs((w[0] - c[0]) * perp(u)[0] + (w[1] - c[1]) * perp(u)[1])
    if r < 1e-9 or math.hypot(e[0] - c[0], e[1] - c[1]) < 1e-9:
        return None
    res = _slot_straight(m, (2 * c[0] - e[0], 2 * c[1] - e[1]), E, r)
    cp = pid(m, C)
    con(m, "midpoint", [("pt", cp), ("ln", res["centre_line"])])
    return res


def _slot_arc(m, O, R, ts, te, r):
    """Arc slot on the centre arc (centre point id O, radius R, from angle ts counter-clockwise to te), half width r."""
    cx, cy = m.pts[O]
    dirs = lambda t: (math.cos(t), math.sin(t))
    ws, we = dirs(ts), dirs(te)
    A = m.add_point(cx + R * ws[0], cy + R * ws[1])
    B = m.add_point(cx + R * we[0], cy + R * we[1])
    oS = m.add_point(cx + (R + r) * ws[0], cy + (R + r) * ws[1])
    iS = m.add_point(cx + (R - r) * ws[0], cy + (R - r) * ws[1])
    oE = m.add_point(cx + (R + r) * we[0], cy + (R + r) * we[1])
    iE = m.add_point(cx + (R - r) * we[0], cy + (R - r) * we[1])
    outer, inner = m.add_arc(O, oS, oE), m.add_arc(O, iS, iE)
    capA, capB = m.add_arc(A, iS, oS), m.add_arc(B, oE, iE)
    centre = m.add_arc(O, A, B)
    m.constr.add(("ar", centre))
    # a cap is centred on the middle of the chord between the two rim points, and that chord lies on a radius (tangent joint)
    for cp, p1, p2 in ((A, iS, oS), (B, oE, iE)):
        chord = m.add_line(p1, p2)
        m.constr.add(("ln", chord))
        con(m, "midpoint", [("pt", cp), ("ln", chord)])
        con(m, "coincident", [("pt", O), ("ln", chord)])
    con(m, "equal", [("ar", capA), ("ar", capB)])
    return {"ars": [outer, inner, capA, capB], "centre_arc": centre, "pts": [A, B, oS, iS, oE, iE]}


def add_slot_arc_center(m, O, S, E, W):
    c, s, e, w = xy(m, O), xy(m, S), xy(m, E), xy(m, W)
    R = math.hypot(s[0] - c[0], s[1] - c[1])
    r = abs(math.hypot(w[0] - c[0], w[1] - c[1]) - R)
    ts, te = ang(c, s), ang(c, e)
    if r < 1e-9 or R < 1e-9 or r >= R or abs(((te - ts) + math.pi) % TWO_PI - math.pi) < 1e-9:
        return None
    return _slot_arc(m, pid(m, O), R, ts, te, r)


def add_slot_arc_3pt(m, S, E, M, W):
    s, e, mid, w = xy(m, S), xy(m, E), xy(m, M), xy(m, W)
    cc = circumcircle(s, mid, e)
    if cc is None:
        return None
    c, R = cc
    turn = (mid[0] - s[0]) * (e[1] - mid[1]) - (mid[1] - s[1]) * (e[0] - mid[0])
    ts, te = (ang(c, s), ang(c, e)) if turn > 0 else (ang(c, e), ang(c, s))
    r = abs(math.hypot(w[0] - c[0], w[1] - c[1]) - R)
    if r < 1e-9 or r >= R:
        return None
    return _slot_arc(m, m.add_point(*c), R, ts, te, r)


# ---------------------------------------------------------------------------------------------------- polygon, point, fillet
def add_polygon(m, c, v, n):
    cc, vv = xy(m, c), xy(m, v)
    R = math.hypot(vv[0] - cc[0], vv[1] - cc[1])
    if R < 1e-9 or n < 3:
        return None
    a0 = ang(cc, vv)
    pc = pid(m, c)
    ids = [pid(m, v)] + [m.add_point(cc[0] + R * math.cos(a0 + TWO_PI * k / n), cc[1] + R * math.sin(a0 + TWO_PI * k / n)) for k in range(1, n)]
    ls = [m.add_line(ids[k], ids[(k + 1) % n]) for k in range(n)]
    circ = m.add_circle(pc, R)
    m.constr.add(("ci", circ))
    for p in ids:
        con(m, "coincident", [("pt", p), ("ci", circ)])
    con(m, "equal", [("ln", i) for i in ls])
    return {"pts": ids, "lns": ls, "circle": circ}


def fillet_corner(m, p, radius):
    """Round the corner point `p` shared by exactly two lines: the lines are shortened, a tangent arc is added (radius dimension too).
    -> arc id, or a string that says why not."""
    lns = [i for i, (a, b) in m.lns.items() if p in (a, b)]
    if len(lns) != 2 or any(("ln", i) in m.constr for i in lns):
        return "a fillet needs a corner where exactly two lines meet"
    ends = []
    for i in lns:
        a, b = m.lns[i]
        ends.append(b if a == p else a)
    P = np.array(m.pts[p])
    A, B = np.array(m.pts[ends[0]]), np.array(m.pts[ends[1]])
    la, lb = np.linalg.norm(A - P), np.linalg.norm(B - P)
    u1, u2 = (A - P) / la, (B - P) / lb
    cos = float(np.clip(u1 @ u2, -1, 1))
    th = math.acos(cos)
    if th < 1e-3 or abs(th - math.pi) < 1e-3:
        return "the two lines are in a line"
    d = radius / math.tan(th / 2)
    if d >= la - 1e-9 or d >= lb - 1e-9:
        return "the radius is too big for these lines"
    T1, T2 = P + u1 * d, P + u2 * d
    w = (u1 + u2) / np.linalg.norm(u1 + u2)
    C = P + w * (radius / math.sin(th / 2))
    t1, t2, cp = m.add_point(*T1), m.add_point(*T2), m.add_point(*C)
    cross = (T1[0] - C[0]) * (T2[1] - C[1]) - (T1[1] - C[1]) * (T2[0] - C[0])
    aid = m.add_arc(cp, t1, t2) if cross > 0 else m.add_arc(cp, t2, t1)
    for i, t in zip(lns, (t1, t2)):
        m.lns[i] = [t if x == p else x for x in m.lns[i]]
        tangent_join(m, i, aid, t)
    m.cons = [c for c in m.cons if ("pt", p) not in c["refs"]]
    if not any(p in (a, b) for a, b in m.lns.values()) and not any(p in (a["c"], a["s"], a["e"]) for a in m.ars.values()):
        m.pts.pop(p, None)
    nm = m.next_dim_name("dim_rad")
    m.add_con("dim_rad", [("ar", aid)], value=float(radius), name=nm)
    return aid


# ---------------------------------------------------------------------------------------------------- reading geometry
def arc_span(m, aid):
    a = m.ars[aid]
    c, s, e = m.pts[a["c"]], m.pts[a["s"]], m.pts[a["e"]]
    t0 = ang(c, s)
    sweep = (ang(c, e) - t0) % TWO_PI
    return c, math.hypot(s[0] - c[0], s[1] - c[1]), t0, sweep if sweep > 1e-12 else TWO_PI


def polyline(m, key, n=48):
    """Points (N, 2) along an entity."""
    k, i = key
    if k == "ln":
        a, b = m.line_pts(i)
        return np.array([a, b], float)
    if k == "ci":
        c, r = m.pts[m.cis[i]["c"]], m.cis[i]["r"]
        t = np.linspace(0, TWO_PI, n + 1)
        return np.column_stack([c[0] + r * np.cos(t), c[1] + r * np.sin(t)])
    if k == "ar":
        c, r, t0, sw = arc_span(m, i)
        t = t0 + np.linspace(0, sw, max(4, int(n * sw / TWO_PI) + 2))
        return np.column_stack([c[0] + r * np.cos(t), c[1] + r * np.sin(t)])
    return np.array([m.pts[i]], float)


def all_keys(m):
    return [("ln", i) for i in m.lns] + [("ci", i) for i in m.cis] + [("ar", i) for i in m.ars]


def regions(m):
    """The closed regions of the sketch (construction geometry left out) with holes decided by nesting (even-odd).
    -> list of {"outer": loop, "holes": [loop, ...]}, a loop = list of pieces ("ln", id, forward) / ("ar", id, forward) / ("ci", id)."""
    # points that a "coincident" constraint joins count as one
    parent = {p: p for p in m.pts}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for c in m.cons:
        if c["type"] == "coincident" and all(k == "pt" for k, _ in c["refs"]):
            a, b = find(c["refs"][0][1]), find(c["refs"][1][1])
            if a != b:
                parent[a] = b
    segs = []
    for i, (a, b) in m.lns.items():
        if ("ln", i) not in m.constr:
            segs.append((("ln", i), find(a), find(b)))
    for i, a in m.ars.items():
        if ("ar", i) not in m.constr:
            segs.append((("ar", i), find(a["s"]), find(a["e"])))
    adj = {}
    for s in segs:
        adj.setdefault(s[1], []).append(s)
        adj.setdefault(s[2], []).append(s)
    used, loops = set(), []
    for s in segs:
        if s[0] in used:
            continue
        chain, cur, start = [], s, s[1]
        node = s[1]
        ok = True
        while True:
            fwd = cur[1] == node
            chain.append((cur[0][0], cur[0][1], fwd))
            used.add(cur[0])
            node = cur[2] if fwd else cur[1]
            if node == start:
                break
            nxt = [t for t in adj.get(node, []) if t[0] != cur[0]]
            if len(adj.get(node, [])) != 2 or not nxt:
                ok = False
                break
            cur = nxt[0]
            if cur[0] in used:
                ok = False
                break
        if ok and len(chain) >= 2:
            loops.append(chain)
    for i in m.cis:
        if ("ci", i) not in m.constr:
            loops.append([("ci", i)])

    def sample(loop):
        pts = []
        for it in loop:
            p = polyline(m, (it[0], it[1]), 24)
            if len(it) == 3 and not it[2]:
                p = p[::-1]
            pts += p.tolist() if not pts else p[1:].tolist()
        return np.array(pts)

    def area(poly):
        x, y = poly[:, 0], poly[:, 1]
        return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))

    polys = [sample(l) for l in loops]
    order = sorted(range(len(loops)), key=lambda i: -abs(area(polys[i])))

    def inside(pt, poly):
        x, y = pt
        n, c = len(poly), False
        for i in range(n):
            x1, y1, x2, y2 = poly[i][0], poly[i][1], poly[(i + 1) % n][0], poly[(i + 1) % n][1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
        return c
    depth, parent_of = {}, {}
    for pos, i in enumerate(order):
        cont = [j for j in order[:pos] if inside(polys[i][len(polys[i]) // 3], polys[j])]
        depth[i] = len(cont)
        parent_of[i] = max(cont, key=lambda j: depth[j]) if cont else None
    out = []
    for i in order:
        if depth[i] % 2 == 0:
            out.append({"outer": loops[i], "holes": [loops[j] for j in order if parent_of.get(j) == i and depth[j] % 2 == 1]})
    return out


# ---------------------------------------------------------------------------------------------------- solving with automatic relations
def solve_model(m):
    """Solve; automatic relations that fight the user's constraints are dropped.  -> the report."""
    rep = m.solve()
    for _ in range(8):
        bad = [c for c in m.cons if c["id"] in rep.conflicts and c.get("auto")]
        if not bad:
            break
        ids = {c["id"] for c in bad}
        m.cons = [c for c in m.cons if c["id"] not in ids]
        rep = m.solve()
    return rep


# ---------------------------------------------------------------------------------------------------- intersections and trim
def _cands(m, skip=None):
    return [k for k in all_keys(m) if k != skip and k not in m.constr]


def _circ_of(m, key):
    k, i = key
    if k == "ci":
        return m.pts[m.cis[i]["c"]], m.cis[i]["r"]
    c, r, _t0, _sw = arc_span(m, i)
    return c, r


def _on_arc(m, aid, p):
    c, r, t0, sw = arc_span(m, aid)
    return ((ang(c, p) - t0) % TWO_PI) <= sw + 1e-9


def intersections(m, ka, kb):
    """Points where two entities cross (each inside its own extent): list of (x, y)."""
    out = []
    if ka[0] == "ln" and kb[0] == "ln":
        (a, b), (c, d) = m.line_pts(ka[1]), m.line_pts(kb[1])
        r, s = (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1])
        den = r[0] * s[1] - r[1] * s[0]
        if abs(den) > 1e-12:
            t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
            u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
            if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
                out.append((a[0] + t * r[0], a[1] + t * r[1]))
        return out
    if kb[0] == "ln":
        ka, kb = kb, ka
    if ka[0] == "ln":
        (a, b) = m.line_pts(ka[1])
        c, r = _circ_of(m, kb)
        d = (b[0] - a[0], b[1] - a[1])
        f = (a[0] - c[0], a[1] - c[1])
        A, B, C = d[0] ** 2 + d[1] ** 2, 2 * (f[0] * d[0] + f[1] * d[1]), f[0] ** 2 + f[1] ** 2 - r * r
        disc = B * B - 4 * A * C
        if A < 1e-18 or disc < 0:
            return out
        for sg in ((-1, 1) if disc > 1e-18 else (0,)):
            t = (-B + sg * math.sqrt(disc)) / (2 * A)
            p = (a[0] + t * d[0], a[1] + t * d[1])
            if -1e-9 <= t <= 1 + 1e-9 and (kb[0] == "ci" or _on_arc(m, kb[1], p)):
                out.append(p)
        return out
    (c1, r1), (c2, r2) = _circ_of(m, ka), _circ_of(m, kb)
    d = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
    if d < 1e-12 or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return out
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    mx, my = c1[0] + a * (c2[0] - c1[0]) / d, c1[1] + a * (c2[1] - c1[1]) / d
    pts = [(mx + h * (c2[1] - c1[1]) / d, my - h * (c2[0] - c1[0]) / d)]
    if h > 1e-9:
        pts.append((mx - h * (c2[1] - c1[1]) / d, my + h * (c2[0] - c1[0]) / d))
    for p in pts:
        if all(k[0] == "ci" or _on_arc(m, k[1], p) for k in (ka, kb)):
            out.append(p)
    return out


def _snap_on(m, p, key):
    """Add a point at p and tie it to the entity it was cut at."""
    q = m.add_point(*p)
    con(m, "coincident", [("pt", q), key])
    return q


def trim(m, key, click):
    """Trim the piece of a line / arc / circle under `click` (x, y) back to the nearest crossings.  -> message or None when done."""
    k, i = key
    others = _cands(m, key)
    hits = []                                   # (parameter, point, other entity)
    if k == "ln":
        a, b = m.line_pts(i)
        d = (b[0] - a[0], b[1] - a[1])
        L2 = d[0] ** 2 + d[1] ** 2
        par = lambda p: ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / L2
        tc = min(1.0, max(0.0, par(click)))
        for o in others:
            for p in intersections(m, key, o):
                t = par(p)
                if 1e-7 < t < 1 - 1e-7:
                    hits.append((t, p, o))
    else:
        c, r, t0, sw = arc_span(m, i) if k == "ar" else (m.pts[m.cis[i]["c"]], m.cis[i]["r"], 0.0, TWO_PI)
        full = k == "ci"
        par = lambda p: ((ang(c, p) - t0) % TWO_PI)
        tc = par(click)
        for o in others:
            for p in intersections(m, key, o):
                t = par(p)
                if full or 1e-7 < t < sw - 1e-7:
                    hits.append((t, p, o))
    hits.sort(key=lambda h: h[0])
    uniq = []
    for h in hits:
        if not uniq or abs(h[0] - uniq[-1][0]) > 1e-7:
            uniq.append(h)
    hits = uniq
    if not hits:
        m.delete([key])
        return None
    if k == "ci":
        if len(hits) < 2:
            return "a circle needs two crossings to trim it"
        lo = max((h for h in hits if h[0] < tc), key=lambda h: h[0], default=hits[-1])
        hi = min((h for h in hits if h[0] > tc), key=lambda h: h[0], default=hits[0])
        cp = m.cis[i]["c"]
        pl, ph = _snap_on(m, lo[1], lo[2]), _snap_on(m, hi[1], hi[2])
        m.delete([key])
        m.add_arc(cp, ph, pl)                   # what is left: counter-clockwise from the far crossing round to the near one
        return None
    lo = max((h for h in hits if h[0] < tc), key=lambda h: h[0], default=None)
    hi = min((h for h in hits if h[0] > tc), key=lambda h: h[0], default=None)
    keep_hv = [c["type"] for c in m.cons if c["type"] in ("horizontal", "vertical") and c["refs"] == [("ln", i)]]
    if k == "ln":
        pa, pb = m.lns[i]
        if lo and hi:
            q1, q2 = _snap_on(m, lo[1], lo[2]), _snap_on(m, hi[1], hi[2])
            m.delete([key])
            n1, n2 = m.add_line(pa, q1), m.add_line(q2, pb)
            for t in keep_hv:
                con(m, t, [("ln", n1)])
                con(m, t, [("ln", n2)])
            return None
        h = lo or hi
        q = _snap_on(m, h[1], h[2])
        old = pb if lo else pa
        m.lns[i] = [pa, q] if lo else [q, pb]
        m.cons = [c for c in m.cons if ("pt", old) not in c["refs"] and not (c["type"] in sc.DIMENSIONS and ("ln", i) in c["refs"])]
        if not any(old in v for v in m.lns.values()) and not any(old in (a["c"], a["s"], a["e"]) for a in m.ars.values()) \
                and not any(old == x["c"] for x in m.cis.values()):
            m.pts.pop(old, None)
        return None
    ar = m.ars[i]
    if lo and hi:
        q1, q2 = _snap_on(m, lo[1], lo[2]), _snap_on(m, hi[1], hi[2])
        s, e, cp = ar["s"], ar["e"], ar["c"]
        m.delete([key])
        m.add_arc(cp, s, q1)
        m.add_arc(cp, q2, e)
        return None
    h = lo or hi
    q = _snap_on(m, h[1], h[2])
    old = ar["e"] if lo else ar["s"]
    ar["e" if lo else "s"] = q
    m.cons = [c for c in m.cons if ("pt", old) not in c["refs"]]
    if not any(old in v for v in m.lns.values()) and not any(old in (a["c"], a["s"], a["e"]) for a in m.ars.values()):
        m.pts.pop(old, None)
    return None


# ---------------------------------------------------------------------------------------------------- mirror, copies, move
def entity_points(m, keys):
    pts = set()
    for k, i in keys:
        if k == "pt":
            pts.add(i)
        elif k == "ln":
            pts |= set(m.lns[i])
        elif k == "ci":
            pts.add(m.cis[i]["c"])
        elif k == "ar":
            pts |= {m.ars[i]["c"], m.ars[i]["s"], m.ars[i]["e"]}
    return pts


def _copy(m, keys, tf, flip=False):
    """Copy entities through the point map tf((x, y)) -> (x, y).  `flip` = the map turns the plane over (mirror): arcs swap ends.
    Constraints whose references are all inside the copied set are repeated on the copies (types that survive a turn / mirror)."""
    keys = [k for k in keys if k[0] != "pt" or k[1] != 0]
    pts = entity_points(m, keys)
    pmap = {p: m.add_point(*tf(m.pts[p])) for p in pts}
    new = {}
    for k, i in keys:
        if k == "ln":
            new[(k, i)] = ("ln", m.add_line(pmap[m.lns[i][0]], pmap[m.lns[i][1]]))
        elif k == "ci":
            new[(k, i)] = ("ci", m.add_circle(pmap[m.cis[i]["c"]], m.cis[i]["r"]))
        elif k == "ar":
            a = m.ars[i]
            new[(k, i)] = ("ar", m.add_arc(pmap[a["c"]], pmap[a["e"]], pmap[a["s"]]) if flip else m.add_arc(pmap[a["c"]], pmap[a["s"]], pmap[a["e"]]))
        if (k, i) in m.constr:
            m.constr.add(new[(k, i)])
    for p in pts:
        new[("pt", p)] = ("pt", pmap[p])
    keep = ("coincident", "parallel", "perpendicular", "collinear", "equal", "tangent", "concentric", "midpoint")
    for c in list(m.cons):
        if c["type"] in keep and all(tuple(r) in new for r in c["refs"]) and not c.get("origin"):
            con(m, c["type"], [new[tuple(r)] for r in c["refs"]])
        elif c["type"] in ("horizontal", "vertical") and all(tuple(r) in new for r in c["refs"]):
            con(m, c["type"], [new[tuple(r)] for r in c["refs"]])
    return new, pmap


def mirror(m, keys, axis):
    """Mirror the entities about the line `axis` (a line id).  Every point is tied to its mirror image (the connecting construction line is
    crossed at its middle by the axis, at right angles), circles keep equal radii, so the copy follows when the original changes."""
    (ax, ay), (bx, by) = m.line_pts(axis)
    u = unit((bx - ax, by - ay))

    def refl(p):
        d = (p[0] - ax, p[1] - ay)
        t = d[0] * u[0] + d[1] * u[1]
        fx, fy = ax + u[0] * t, ay + u[1] * t
        return (2 * fx - p[0], 2 * fy - p[1])
    keys = [k for k in keys if k != ("ln", axis)]
    new, pmap = _copy(m, keys, refl, flip=True)
    ax_pts = set(m.lns[axis])
    for p, q in pmap.items():
        if p in ax_pts or math.dist(m.pts[p], m.pts[q]) < 1e-9:
            m.cons = [c for c in m.cons if ("pt", q) not in c["refs"]]
            continue
        link = m.add_line(p, q)
        m.constr.add(("ln", link))
        mid = m.add_point((m.pts[p][0] + m.pts[q][0]) / 2, (m.pts[p][1] + m.pts[q][1]) / 2)
        con(m, "midpoint", [("pt", mid), ("ln", link)])
        con(m, "coincident", [("pt", mid), ("ln", axis)])
        con(m, "perpendicular", [("ln", link), ("ln", axis)])
    for k, i in keys:
        if k == "ci":
            con(m, "equal", [("ci", i), new[(k, i)]])
    return list(new.values())


def linear_pattern(m, keys, count, dx, dy):
    """`count` extra copies, each (dx, dy) further along.  (Plain copies: they do not follow the original afterwards.)"""
    out = []
    for n in range(1, count + 1):
        new, _ = _copy(m, keys, lambda p, n=n: (p[0] + dx * n, p[1] + dy * n))
        out += list(new.values())
    return out


def circular_pattern(m, keys, count, step_deg, cx, cy):
    out = []
    for n in range(1, count + 1):
        a = math.radians(step_deg * n)
        ca, sa = math.cos(a), math.sin(a)
        new, _ = _copy(m, keys, lambda p, ca=ca, sa=sa: (cx + (p[0] - cx) * ca - (p[1] - cy) * sa, cy + (p[0] - cx) * sa + (p[1] - cy) * ca))
        out += list(new.values())
    return out


def move(m, keys, dx, dy):
    for p in entity_points(m, keys):
        if p != 0:
            m.pts[p] = [m.pts[p][0] + dx, m.pts[p][1] + dy]
    for k, i in keys:
        if k == "pt" and i != 0:
            pass
