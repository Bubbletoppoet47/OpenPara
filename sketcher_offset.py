"""
sketcher_offset.py - the geometry behind the Offset tool (no Qt, no window).

  find_chains(m, keys)     lines / arcs that share end points, as ordered chains (open or closed loops)
  loop_rest(m, keys)       edges of closed loops that the selection only partly covers
  plan_offset(m, ...)      where the offset copies go: corners joined, collapsed pieces dropped  -> plan dict
  plan_paths(plan)         what to draw as a preview
  apply_plan(m, ...)       create the copies (and the linked "offset" dimension) in the model

Sign convention of the distance d: for a closed loop POSITIVE = outward, for a circle / single arc positive = bigger radius,
for a line or an open chain positive = to the left of its drawing direction.
"""
import math

TWO_PI = 2 * math.pi


def _xy(m, pid):
    p = m.pts[pid]
    return (p[0], p[1])


def edge_ends(m, key):
    k, i = key
    if k == "ln":
        a, b = m.lns[i]
        return a, b
    a = m.ars[i]
    return a["s"], a["e"]


def ccw(a0, a1):
    """Counter-clockwise angle from a0 to a1 in [0, 2 pi)."""
    return (a1 - a0) % TWO_PI


# ----------------------------------------------------------------------------------------------
# chains
# ----------------------------------------------------------------------------------------------
def find_chains(m, keys):
    """-> [{"items": [(key, forward)], "verts": [point id], "closed": bool}].
    verts[j] is the point where item j starts (in the direction the chain is walked); an open chain has one more vertex
    (the far end of the last item).  Edges only join where exactly two of the given edges meet at a point."""
    keys = sorted({k for k in keys if (k[0] == "ln" and k[1] in m.lns) or (k[0] == "ar" and k[1] in m.ars)})
    ends = {k: edge_ends(m, k) for k in keys}
    at = {}
    for k, (s, e) in ends.items():
        if s == e:
            continue
        at.setdefault(s, []).append((k, 0))
        at.setdefault(e, []).append((k, 1))

    def partner(k, end):
        lst = at.get(ends[k][end], [])
        if len(lst) != 2:
            return None
        other = [x for x in lst if x[0] != k]
        return other[0] if len(other) == 1 else None

    seen, chains = set(), []

    def walk(start, fwd):
        items, verts = [(start, fwd)], [ends[start][0 if fwd else 1]]
        cur, f = start, fwd
        closed = False
        while True:
            seen.add(cur)
            ex = 1 if f else 0
            verts.append(ends[cur][ex])
            pr = partner(cur, ex)
            if pr is None:
                break
            k2, e2 = pr
            if k2 == start:
                closed = True
                break
            if k2 in seen:
                break
            f = (e2 == 0)
            items.append((k2, f))
            cur = k2
        if closed:
            verts = verts[:-1]
        return {"items": items, "verts": verts, "closed": closed}

    for k in keys:                                   # open chains first: they begin at a free end
        if k in seen:
            continue
        if partner(k, 0) is None:
            chains.append(walk(k, True))
        elif partner(k, 1) is None:
            chains.append(walk(k, False))
    for k in keys:                                   # what is left are closed loops
        if k not in seen:
            chains.append(walk(k, True))
    return chains


def loop_rest(m, keys):
    """Edges that complete a closed loop through the given edges but are not in `keys` (to offer 'the whole loop')."""
    keys = set(keys)
    every = [("ln", i) for i in m.lns if ("ln", i) not in m.constr] + [("ar", i) for i in m.ars if ("ar", i) not in m.constr]
    extra = []
    for ch in find_chains(m, every):
        if not ch["closed"]:
            continue
        ks = [k for k, _ in ch["items"]]
        if any(k in keys for k in ks) and not all(k in keys for k in ks):
            extra += [k for k in ks if k not in keys]
    return extra


# ----------------------------------------------------------------------------------------------
# curves
# ----------------------------------------------------------------------------------------------
def _info(m, key, fwd):
    k, i = key
    if k == "ln":
        a, b = m.lns[i]
        pa, pb = _xy(m, a), _xy(m, b)
        if not fwd:
            pa, pb = pb, pa
        dx, dy = pb[0] - pa[0], pb[1] - pa[1]
        L = math.hypot(dx, dy) or 1e-12
        return {"t": "ln", "p0": pa, "p1": pb, "u": (dx / L, dy / L), "L": L}
    ar = m.ars[i]
    c, s, e = _xy(m, ar["c"]), _xy(m, ar["s"]), _xy(m, ar["e"])
    return {"t": "ar", "c": c, "r": math.hypot(s[0] - c[0], s[1] - c[1]), "fwd": fwd, "s": s, "e": e}


def _tangent(info, which):
    """Direction of travel at the start (which=0) or end (which=1) of an item."""
    if info["t"] == "ln":
        return info["u"]
    c, r = info["c"], info["r"] or 1e-12
    p = info["s"] if (which == 0) == info["fwd"] else info["e"]       # the stored end point at that end of the walk
    t = (-(p[1] - c[1]) / r, (p[0] - c[0]) / r)                        # counter-clockwise direction
    return t if info["fwd"] else (-t[0], -t[1])


def _curve(info, dl):
    """The infinite line / full circle of an item moved dl to the LEFT of its direction of travel."""
    if info["t"] == "ln":
        u = info["u"]
        n = (-u[1], u[0])
        return {"t": "L", "p": (info["p0"][0] + dl * n[0], info["p0"][1] + dl * n[1]), "u": u}
    return {"t": "C", "c": info["c"], "r": info["r"] - dl if info["fwd"] else info["r"] + dl}


def _nearest(cands, est):
    return min(cands, key=lambda q: (q[0] - est[0]) ** 2 + (q[1] - est[1]) ** 2)


def _line_line(A, B, est, tol):
    (px, py), (ux, uy), (qx, qy), (vx, vy) = A["p"], A["u"], B["p"], B["u"]
    den = ux * vy - uy * vx
    if abs(den) < 1e-9:                                       # parallel: they only meet if they are the same line
        if abs(ux * (qy - py) - uy * (qx - px)) > tol:
            return None
        t = (est[0] - px) * ux + (est[1] - py) * uy
        return (px + t * ux, py + t * uy)
    t = ((qx - px) * vy - (qy - py) * vx) / den
    return (px + t * ux, py + t * uy)


def _line_circle(L, C, est, tol):
    (px, py), (ux, uy) = L["p"], L["u"]
    (cx, cy), r = C["c"], C["r"]
    if r <= 0:
        return None
    t0 = (cx - px) * ux + (cy - py) * uy
    fx, fy = px + t0 * ux, py + t0 * uy
    h = math.hypot(cx - fx, cy - fy)
    if h > r + tol:
        return None
    if abs(h - r) <= tol:
        return (fx, fy)
    w = math.sqrt(max(r * r - h * h, 0.0))
    return _nearest([(fx + w * ux, fy + w * uy), (fx - w * ux, fy - w * uy)], est)


def _circle_circle(A, B, est, tol):
    (ax, ay), r1 = A["c"], A["r"]
    (bx, by), r2 = B["c"], B["r"]
    if r1 <= 0 or r2 <= 0:
        return None
    d = math.hypot(bx - ax, by - ay)
    if d < 1e-12:
        return None
    if d > r1 + r2 + tol or d < abs(r1 - r2) - tol:
        return None
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    ex, ey = (bx - ax) / d, (by - ay) / d
    mx, my = ax + a * ex, ay + a * ey
    if h <= tol:
        return (mx, my)
    return _nearest([(mx - h * ey, my + h * ex), (mx + h * ey, my - h * ex)], est)


def _join(A, B, est, tol):
    if A["t"] == "L" and B["t"] == "L":
        return _line_line(A, B, est, tol)
    if A["t"] == "L":
        return _line_circle(A, B, est, tol)
    if B["t"] == "L":
        return _line_circle(B, A, est, tol)
    return _circle_circle(A, B, est, tol)


def _end_point(cur, v):
    """Where the offset curve ends if nothing joins it: the point of the curve straight across from vertex v."""
    if cur["t"] == "L":
        px, py = cur["p"]
        ux, uy = cur["u"]
        t = (v[0] - px) * ux + (v[1] - py) * uy
        return (px + t * ux, py + t * uy)
    cx, cy = cur["c"]
    d = math.hypot(v[0] - cx, v[1] - cy) or 1e-12
    return (cx + (v[0] - cx) / d * cur["r"], cy + (v[1] - cy) / d * cur["r"])


def _signed_area(m, chain, infos):
    pts = []
    for (key, fwd), inf in zip(chain["items"], infos):
        if inf["t"] == "ln":
            pts.append(inf["p0"])
        else:
            c, r = inf["c"], inf["r"]
            a_s = math.atan2(inf["s"][1] - c[1], inf["s"][0] - c[0])
            span = ccw(a_s, math.atan2(inf["e"][1] - c[1], inf["e"][0] - c[0])) or TWO_PI
            for q in range(12):
                t = q / 12
                ang = a_s + span * t if fwd else a_s + span * (1 - t)
                pts.append((c[0] + r * math.cos(ang), c[1] + r * math.sin(ang)))
    s = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        s += x0 * y1 - x1 * y0
    return s / 2


def side_factor(m, chain, infos):
    """dl = factor * d : how a distance (positive = outward for loops / bigger arcs) turns into 'left of the walking direction'."""
    if chain["closed"]:
        return -1.0 if _signed_area(m, chain, infos) > 0 else 1.0
    if len(chain["items"]) == 1 and infos[0]["t"] == "ar":
        return -1.0 if infos[0]["fwd"] else 1.0
    return 1.0


# ----------------------------------------------------------------------------------------------
# the plan
# ----------------------------------------------------------------------------------------------
def _plan_chain(m, chain, d, tol, out):
    items, closed = chain["items"], chain["closed"]
    n = len(items)
    infos = [_info(m, k, f) for k, f in items]
    dl = side_factor(m, chain, infos) * d
    curves = [_curve(inf, dl) for inf in infos]
    verts = [_xy(m, p) for p in chain["verts"]]
    if closed:
        v_end = [verts[(j + 1) % n] for j in range(n)]
        v_start = [verts[j] for j in range(n)]
    else:
        v_end = [verts[j + 1] for j in range(n)]
        v_start = [verts[j] for j in range(n)]
    active = list(range(n))
    dropped = []
    result = None
    for _ in range(n + 1):
        k = len(active)
        if k == 0 or (closed and k < 2):
            active = []
            break
        joins = []
        last = k if closed else k - 1
        for j in range(last):
            a, b = active[j], active[(j + 1) % k]
            t = _tangent(infos[a], 1)
            v = v_end[a]
            est = (v[0] + dl * -t[1], v[1] + dl * t[0])
            joins.append(_join(curves[a], curves[b], est, tol))
        if closed and dropped and any(j is None for j in joins):      # pieces vanished and the rest no longer meets: the loop is gone
            dropped += [items[a][0] for a in active]
            active = []
            break
        bad = []
        # corners of every active item (start, end)
        sc, ec = [None] * k, [None] * k
        for j in range(last):
            p = joins[j]
            if p is not None:
                ec[j] = p
                sc[(j + 1) % k] = p
            else:
                ec[j] = _end_point(curves[active[j]], v_end[active[j]])
                sc[(j + 1) % k] = _end_point(curves[active[(j + 1) % k]], v_end[active[j]])
        if not closed:
            sc[0] = _end_point(curves[active[0]], v_start[active[0]])
            ec[k - 1] = _end_point(curves[active[k - 1]], v_end[active[k - 1]])
        for j, a in enumerate(active):
            inf, cur = infos[a], curves[a]
            S, E = sc[j], ec[j]
            if inf["t"] == "ln":
                u = inf["u"]
                if (E[0] - S[0]) * u[0] + (E[1] - S[1]) * u[1] <= tol:
                    bad.append(j)
            else:
                if cur["r"] <= tol:
                    bad.append(j)
                    continue
                c = inf["c"]
                s_, e_ = (S, E) if inf["fwd"] else (E, S)
                old = ccw(math.atan2(inf["s"][1] - c[1], inf["s"][0] - c[0]), math.atan2(inf["e"][1] - c[1], inf["e"][0] - c[0]))
                new = ccw(math.atan2(s_[1] - c[1], s_[0] - c[0]), math.atan2(e_[1] - c[1], e_[0] - c[0]))
                if abs(new - old) > math.pi or new <= 1e-12:
                    bad.append(j)
        if not bad:
            result = (active, joins, sc, ec)
            break
        for j in sorted(bad, reverse=True):
            dropped.append(items[active[j]][0])
            del active[j]
    if result is None:
        out["dropped"] += [items[a][0] for a in active] if active else []
        out["dropped"] += dropped
        return
    active, joins, sc, ec = result
    out["dropped"] += dropped
    k = len(active)
    last = k if closed else k - 1
    base = len(out["edges"])

    def adjacent(a, b):                                       # were these two items neighbours in the original drawing?
        return (a + 1) % n == b if closed else b == a + 1

    tangent, straight = [False] * k, [False] * k              # per junction j (between position j and j + 1)
    for j in range(last):
        a, b = active[j], active[(j + 1) % k]
        if joins[j] is None or not adjacent(a, b):
            continue
        t1, t2 = _tangent(infos[a], 1), _tangent(infos[b], 0)
        if abs(t1[0] * t2[1] - t1[1] * t2[0]) > 1e-6:
            continue
        if infos[a]["t"] != infos[b]["t"]:
            tangent[j] = True                                  # a line running tangentially into an arc
        elif infos[a]["t"] == "ln":
            straight[j] = True                                 # two lines in a row
    pool = out["corners"]
    start_i, end_i = [None] * k, [None] * k
    free_s, free_e = [False] * k, [False] * k

    def add(xy):
        pool.append(xy)
        return len(pool) - 1
    for j in range(last):
        nxt = (j + 1) % k
        if joins[j] is not None:
            ci = add(joins[j])
            end_i[j], start_i[nxt] = ci, ci
            if straight[j]:                                    # the corner could slide along the line: hold it straight across
                free_e[j] = True
        else:
            end_i[j], start_i[nxt] = add(ec[j]), add(sc[nxt])
            free_e[j] = free_s[nxt] = True
            out["unjoined"] += 1
    if not closed:
        start_i[0], end_i[k - 1] = add(sc[0]), add(ec[k - 1])
        free_s[0] = free_e[k - 1] = True
    for j, a in enumerate(active):
        key, fwd = items[a]
        inf, cur = infos[a], curves[a]
        S, E = pool[start_i[j]], pool[end_i[j]]
        # stored orientation: a line's a -> b, an arc's start -> end
        if fwd:
            si, ei, fs, fe = start_i[j], end_i[j], free_s[j], free_e[j]
        else:
            si, ei, fs, fe = end_i[j], start_i[j], free_e[j], free_s[j]
        align = [x for x, fl in ((0, fs), (1, fe)) if fl]
        if key[0] == "ln":
            sign = (1 if dl > 0 else -1) * (1 if fwd else -1)       # +1: the copy is on the left of a -> b
            ts = base + (j - 1) % k if (closed or j > 0) and tangent[(j - 1) % k] else None     # arc met at the walk's start
            te = base + (j + 1) % k if (closed or j < k - 1) and tangent[j] else None           # arc met at the walk's end
            tan = [ts, te] if fwd else [te, ts]
            out["edges"].append({"key": key, "sc": si, "ec": ei, "align": align, "sign": sign, "tan": tan})
        else:
            sign = 1 if cur["r"] > inf["r"] else -1
            out["edges"].append({"key": key, "sc": si, "ec": ei, "align": align, "sign": sign,
                                 "c": inf["c"], "r": cur["r"]})


def plan_offset(m, chains, circles, d, tol):
    """The copies for one signed distance d.  chains from find_chains, circles = [circle ids].
    -> {"corners": [xy], "edges": [...], "circles": [{"key","c","r","sign"}], "dropped": [keys], "unjoined": n, "d": d}"""
    out = {"corners": [], "edges": [], "circles": [], "dropped": [], "unjoined": 0, "d": d}
    for ch in chains:
        _plan_chain(m, ch, d, tol, out)
    for i in circles:
        if i not in m.cis:
            continue
        r = m.cis[i]["r"] + d
        if r <= tol:
            out["dropped"].append(("ci", i))
            continue
        out["circles"].append({"key": ("ci", i), "c": _xy(m, m.cis[i]["c"]), "r": r, "sign": 1 if d > 0 else -1})
    return out


def plan_paths(plan):
    """Drawing list: ("ln", a, b) / ("ar", c, r, start angle, ccw span) / ("ci", c, r)."""
    paths = []
    pool = plan["corners"]
    for e in plan["edges"]:
        if e["key"][0] == "ln":
            paths.append(("ln", pool[e["sc"]], pool[e["ec"]]))
        else:
            c, s, t = e["c"], pool[e["sc"]], pool[e["ec"]]
            a0 = math.atan2(s[1] - c[1], s[0] - c[0])
            paths.append(("ar", c, e["r"], a0, ccw(a0, math.atan2(t[1] - c[1], t[0] - c[0]))))
    for ci in plan["circles"]:
        paths.append(("ci", ci["c"], ci["r"]))
    return paths


def apply_plan(m, plans, link=True, name=None, group=None):
    """Create the copies of every plan in the model.  With link=True each copy gets an "offset" dimension (type dim_off) to
    its original; all of them use the one symbol `name`.  -> (new items [(kind, id)], lead dimension or None)"""
    new = []
    lead = group
    if link and name and name not in m.params and plans:
        m.add_param(name, abs(plans[0]["d"]))
    for plan in plans:
        pids = [m.add_point(x, y) for x, y in plan["corners"]]
        made = []
        for e in plan["edges"]:
            k, i = e["key"]
            if k == "ln":
                nid = m.add_line(pids[e["sc"]], pids[e["ec"]])
            else:
                cp = m.add_point(*e["c"])
                new.append(("pt", cp))
                nid = m.add_arc(cp, pids[e["sc"]], pids[e["ec"]])
            made.append((e, (k, i), (k, nid)))
        for ci in plan["circles"]:
            cp = m.add_point(*ci["c"])
            new.append(("pt", cp))
            nid = m.add_circle(cp, ci["r"])
            made.append((ci, ci["key"], ("ci", nid)))
        for rec, old, nw in made:
            new.append(nw)
            if old in m.constr:
                m.constr.add(nw)
            if not link:
                continue
            kw = {"value": abs(plan["d"]), "sign": rec["sign"], "expr": name, "name": name}
            if "align" in rec and rec["align"]:
                kw["align"] = list(rec["align"])
            refs = [old, nw]
            if any(t is not None for t in rec.get("tan", ())):
                tan = [made[t][2][1] if t is not None else None for t in rec["tan"]]
                kw["tan"] = tan
                refs += [("ar", t) for t in tan if t is not None]
            if lead is None:
                c = m.add_con("dim_off", refs, **kw)
                c["grp"] = c["id"]
                lead = c
            else:
                kw["grp"] = lead["id"]
                kw["hide"] = True
                m.add_con("dim_off", refs, **kw)
        new += [("pt", p) for p in pids]
    return new, lead
