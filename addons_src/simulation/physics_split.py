"""
physics_split.py - split one edge of the 2D FEA geometry in two (and merge two back).  No Qt here, so it is testable.

All of it works on the tab's own COPY of the sketch (a sketcher_core.Model): the sketch itself is never touched.

  edge_length(m, src)                  length of a line / arc (a circle: its circumference)
  point_at(m, src, dist)               the point `dist` along the edge from its start
  nearest_dist(m, src, x, y)           how far along the edge the point nearest to (x, y) lies
  split_edge(m, src, dist)             line / arc -> two edges that share a new point.  Returns a dict (see there)
  split_circle(m, cid, ang1, ang2)     circle -> two arcs that share two new points
  can_merge(m, pid)  /  merge_at(m, pid)   the opposite: a point shared by exactly two lines on one straight line (or two arcs of one circle)
  eval_length(text)                    a number or a plain arithmetic expression ("12.5", "100/3 + 2") -> float, ValueError otherwise

Ids: the edge keeps its id for the first half (start -> split point); the second half is a NEW edge.  Constraints of the sketch copy that
refer to the split edge are dropped (the copy is only used for analysis, never re-solved).
"""
import ast
import math
import operator


class SplitError(ValueError):
    pass


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg,
        ast.UAdd: operator.pos, ast.Pow: operator.pow}


def eval_length(text):
    """'12.5', '100/3', '(40 + 2) / 2' -> float.  Anything but numbers and + - * / ** ( ) raises ValueError."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("Type a number or a simple calculation, for example 12.5 or 100/3.")
    try:
        v = ev(ast.parse(str(text).strip().replace(",", "."), mode="eval"))
    except (SyntaxError, ZeroDivisionError, OverflowError) as ex:
        raise ValueError("Type a number or a simple calculation, for example 12.5 or 100/3.") from ex
    if not math.isfinite(v):
        raise ValueError("That is not a usable number.")
    return v


def _arc(m, aid):
    ar = m.ars[aid]
    c, s, e = m.pts[ar["c"]], m.pts[ar["s"]], m.pts[ar["e"]]
    a0 = math.atan2(s[1] - c[1], s[0] - c[0])
    a1 = math.atan2(e[1] - c[1], e[0] - c[0])
    while a1 <= a0:
        a1 += 2 * math.pi
    return c, a0, a1, math.hypot(s[0] - c[0], s[1] - c[1])


def edge_length(m, src):
    kind, i = src
    if kind == "ln":
        a, b = m.pts[m.lns[i][0]], m.pts[m.lns[i][1]]
        return math.hypot(b[0] - a[0], b[1] - a[1])
    if kind == "ar":
        _, a0, a1, r = _arc(m, i)
        return r * (a1 - a0)
    if kind == "ci":
        return 2 * math.pi * m.cis[i]["r"]
    raise SplitError("Only lines, arcs and circles can be split.")


def point_at(m, src, dist):
    kind, i = src
    L = edge_length(m, src)
    if kind == "ln":
        a, b = m.pts[m.lns[i][0]], m.pts[m.lns[i][1]]
        f = dist / L
        return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
    if kind == "ar":
        c, a0, a1, r = _arc(m, i)
        ang = a0 + (a1 - a0) * dist / L
        return c[0] + r * math.cos(ang), c[1] + r * math.sin(ang)
    raise SplitError("A circle is split at two points (split_circle).")


def nearest_dist(m, src, x, y):
    """Distance along the edge (from its start) of the point of the edge nearest to (x, y).  A circle: the angle in radians from +x."""
    kind, i = src
    if kind == "ln":
        a, b = m.pts[m.lns[i][0]], m.pts[m.lns[i][1]]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
        return t * math.sqrt(L2)
    if kind == "ar":
        c, a0, a1, r = _arc(m, i)
        ang = math.atan2(y - c[1], x - c[0])
        rel = (ang - a0) % (2 * math.pi)
        sweep = a1 - a0
        if rel > sweep:                                   # outside the arc: the nearer end
            rel = sweep if (rel - sweep) < (2 * math.pi - rel) else 0.0
        return rel * r
    c = m.pts[m.cis[i]["c"]]
    return math.atan2(y - c[1], x - c[0]) % (2 * math.pi)


def _drop_constraints(m, refs):
    refs = set(refs)
    m.cons = [c for c in m.cons if c.get("origin") or not (refs & {tuple(r) for r in c.get("refs", [])})]


def split_edge(m, src, dist):
    """Splits the line / arc `src` at `dist` along it from its start.  -> {"first": src, "second": src2, "pt": point id, "frac": dist / length}.
    The two edges share the new point `pt`; `first` keeps the id (and the start point), `second` is new and ends where the original did."""
    kind, i = src
    if kind not in ("ln", "ar") or (kind == "ln" and i not in m.lns) or (kind == "ar" and i not in m.ars):
        raise SplitError("Only a line or an arc can be split with one point.")
    L = edge_length(m, src)
    if not (dist > 1e-9 * max(L, 1e-300) and dist < L * (1 - 1e-9)):
        raise SplitError(f"The split point must lie inside the edge: between 0 and {L:.6g} from its end.")
    x, y = point_at(m, src, dist)
    pid = m.add_point(x, y)
    if kind == "ln":
        a, b = m.lns[i]
        m.lns[i] = [a, pid]
        j = m.add_line(pid, b)
    else:
        ar = m.ars[i]
        m.ars[i] = {"c": ar["c"], "s": ar["s"], "e": pid}
        j = m.add_arc(ar["c"], pid, ar["e"])
    _drop_constraints(m, [src])
    return {"first": (kind, i), "second": (kind, j), "pt": pid, "frac": dist / L}


def split_circle(m, cid, ang1, ang2):
    """A circle becomes two arcs (counter-clockwise from the point at ang1 to the point at ang2, and back).  -> {"arcs": [src, src], "pts": [p1, p2],
    "angles": (a1, a2)}.  The circle itself disappears."""
    if cid not in m.cis:
        raise SplitError("That circle does not exist.")
    two_pi = 2 * math.pi
    a1, a2 = ang1 % two_pi, ang2 % two_pi
    if min(abs(a1 - a2), two_pi - abs(a1 - a2)) < 1e-6:
        raise SplitError("Pick two different points on the circle.")
    c, r = m.cis[cid]["c"], m.cis[cid]["r"]
    cx, cy = m.pts[c]
    p1 = m.add_point(cx + r * math.cos(a1), cy + r * math.sin(a1))
    p2 = m.add_point(cx + r * math.cos(a2), cy + r * math.sin(a2))
    del m.cis[cid]
    m.lock_cis.pop(cid, None)
    s1 = m.add_arc(c, p1, p2)                              # counter-clockwise p1 -> p2
    s2 = m.add_arc(c, p2, p1)
    _drop_constraints(m, [("ci", cid)])
    return {"arcs": [("ar", s1), ("ar", s2)], "pts": [p1, p2], "angles": (a1, a2)}


# ----------------------------------------------------------------------------------------------
# merging
# ----------------------------------------------------------------------------------------------
def _edges_at(m, pid):
    out = []
    for lid, (a, b) in m.lns.items():
        if ("ln", lid) in m.constr:
            continue
        if pid in (a, b) and a != b:
            out.append(("ln", lid))
    for aid, ar in m.ars.items():
        if ("ar", aid) in m.constr:
            continue
        if pid in (ar["s"], ar["e"]):
            out.append(("ar", aid))
    return out


def can_merge(m, pid):
    """-> (True, (src1, src2)) when the point joins exactly two lines on one straight line, or two arcs of one circle (src1 comes first along the
    direction of travel); (False, reason) otherwise."""
    if pid not in m.pts:
        return False, "That point does not exist."
    es = _edges_at(m, pid)
    if len(es) != 2:
        return False, "Merge needs a point where exactly two edges meet."
    (k1, i1), (k2, i2) = es
    if k1 != k2:
        return False, "A line and an arc cannot be merged."
    if k1 == "ln":
        # direction of travel: edge whose END is the point first, the one whose START is the point second; else flip is impossible without
        # changing the model, so merging only joins edges that already run the same way
        first, second = sorted(es, key=lambda s: 0 if m.lns[s[1]][1] == pid else 1)
        if not (m.lns[first[1]][1] == pid and m.lns[second[1]][0] == pid):
            return False, "The two lines run in opposite directions at that point (they cannot be joined)."
        a, b = m.pts[m.lns[first[1]][0]], m.pts[pid]
        c = m.pts[m.lns[second[1]][1]]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        L = math.hypot(c[0] - a[0], c[1] - a[1]) or 1.0
        if abs(cross) / L > 1e-6 * L or (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) <= 0:
            return False, "The two lines are not on one straight line."
        return True, (first, second)
    first, second = sorted(es, key=lambda s: 0 if m.ars[s[1]]["e"] == pid else 1)
    if not (m.ars[first[1]]["e"] == pid and m.ars[second[1]]["s"] == pid):
        return False, "The two arcs run in opposite directions at that point (they cannot be joined)."
    A, B = m.ars[first[1]], m.ars[second[1]]
    ca, cb = m.pts[A["c"]], m.pts[B["c"]]
    ra = math.hypot(m.pts[A["s"]][0] - ca[0], m.pts[A["s"]][1] - ca[1])
    rb = math.hypot(m.pts[B["e"]][0] - cb[0], m.pts[B["e"]][1] - cb[1])
    if math.hypot(ca[0] - cb[0], ca[1] - cb[1]) > 1e-6 * max(ra, 1e-300) or abs(ra - rb) > 1e-6 * max(ra, 1e-300):
        return False, "The two arcs are not on one circle."
    return True, (first, second)


def merge_at(m, pid):
    """Joins the two edges that meet at `pid` into one (the first keeps its id) and deletes the point.  -> {"kept": src, "removed": src,
    "pt": pid, "frac": length of the first part / length of the merged edge}.  SplitError if they cannot be merged."""
    ok, what = can_merge(m, pid)
    if not ok:
        raise SplitError(what)
    first, second = what
    L1, L2 = edge_length(m, first), edge_length(m, second)
    if first[0] == "ln":
        m.lns[first[1]] = [m.lns[first[1]][0], m.lns[second[1]][1]]
        del m.lns[second[1]]
    else:
        m.ars[first[1]] = {"c": m.ars[first[1]]["c"], "s": m.ars[first[1]]["s"], "e": m.ars[second[1]]["e"]}
        del m.ars[second[1]]
    _drop_constraints(m, [first, second, ("pt", pid)])
    if pid not in {p for ab in m.lns.values() for p in ab} and not any(pid in (a["c"], a["s"], a["e"]) for a in m.ars.values()):
        m.pts.pop(pid, None)
        m.lock_pts.pop(pid, None)
    return {"kept": first, "removed": second, "pt": pid, "frac": L1 / (L1 + L2)}
