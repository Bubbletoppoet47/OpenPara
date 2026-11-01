"""Turns the outlines cut from a 3D model (fc_slice.py) into sketch geometry, constraints and key dimensions.  No Qt, no FreeCAD.

build(model, loops, scale) adds to a sketcher_core.Model:
  geometry    points shared where outlines meet, lines, arcs (counter-clockwise), circles; curves that are not lines, arcs or circles
              (splines, ellipses) become short lines whose points are fixed
  constraints horizontal / vertical lines, tangent line-arc joints, equal radii
  dimensions  KEY dimensions only: hole / circle diameters, arc radii, the position of the first corner and of each hole centre
              from it, the length of each line (or its horizontal / vertical size when it is sloped).  Every dimension is a named
              symbol, so it can be an input of the Parameterization tab.  Dimensions the sketch does not need (the solver says they
              are redundant) are not kept.  The overall width and height are added as driven (output) dimensions.
loops: [{"part": i, "closed": bool, "edges": [edge, ...]}], edge as written by fc_slice.py, all lengths in mm.
scale: sketch units per mm.
"""
import math

import sketcher_core as sc

ANG_TOL = 1e-5            # a line is horizontal / vertical / tangent when its direction is that close (radians)
MAX_POINTS_FOR_DIMS = 1500


class _Merger:
    def __init__(self, tol):
        self.tol = tol
        self.cells = {}

    def _key(self, x, y):
        return (int(math.floor(x / self.tol)), int(math.floor(y / self.tol)))

    def find(self, x, y):
        kx, ky = self._key(x, y)
        for i in (kx - 1, kx, kx + 1):
            for j in (ky - 1, ky, ky + 1):
                for pid, px, py in self.cells.get((i, j), ()):
                    if abs(px - x) <= self.tol and abs(py - y) <= self.tol:
                        return pid
        return None

    def add(self, pid, x, y):
        self.cells.setdefault(self._key(x, y), []).append((pid, x, y))


def polygon_of(loop, n_arc=24, n_circle=48):
    """Points of an outline (for the inside / outside test only)."""
    pts = []
    for e in loop["edges"]:
        t = e["t"]
        if t == "line":
            pts += [tuple(e["a"]), tuple(e["b"])]
        elif t == "poly":
            pts += [tuple(p) for p in e["pts"]]
        elif t == "circle":
            cx, cy = e["c"]
            pts += [(cx + e["r"] * math.cos(2 * math.pi * i / n_circle), cy + e["r"] * math.sin(2 * math.pi * i / n_circle))
                    for i in range(n_circle)]
        elif t == "arc":
            cx, cy = e["c"]
            a0 = math.atan2(e["s"][1] - cy, e["s"][0] - cx)
            am = math.atan2(e["m"][1] - cy, e["m"][0] - cx)
            a1 = math.atan2(e["e"][1] - cy, e["e"][0] - cx)
            ccw = ((am - a0 + math.pi) % (2 * math.pi) - math.pi) > 0
            sweep = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
            pts += [(cx + e["r"] * math.cos(a0 + sweep * i / n_arc), cy + e["r"] * math.sin(a0 + sweep * i / n_arc))
                    for i in range(n_arc + 1)]
    return pts


def _inside(pt, poly):
    x, y = pt
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi:
            c = not c
        j = i
    return c


def count_loops(loops):
    """-> (outlines, holes): a loop inside an odd number of other loops of the same part is a hole."""
    polys = [(l["part"], polygon_of(l)) for l in loops]
    outer = holes = 0
    for i, (part, poly) in enumerate(polys):
        if len(poly) < 3:
            continue
        probe = poly[0]
        depth = sum(1 for j, (pj, other) in enumerate(polys) if j != i and pj == part and len(other) >= 3 and _inside(probe, other))
        if depth % 2:
            holes += 1
        else:
            outer += 1
    return outer, holes


def _arc_extremes(c, r, s, e):
    """Points of an arc (counter-clockwise from s to e) that matter for its bounding box: the ends and the axis extremes inside it."""
    a0 = math.atan2(s[1] - c[1], s[0] - c[0])
    a1 = math.atan2(e[1] - c[1], e[0] - c[0])
    sweep = (a1 - a0) % (2 * math.pi)
    pts = [tuple(s), tuple(e)]
    for k in range(4):
        ak = k * math.pi / 2
        if (ak - a0) % (2 * math.pi) <= sweep:
            pts.append((c[0] + r * math.cos(ak), c[1] + r * math.sin(ak)))
    return pts


class _Builder:
    def __init__(self, m, loops, scale):
        self.m, self.k, self.loops = m, scale, loops
        xs = [p for l in loops for e in l["edges"] for p in _edge_points(e)]
        if not xs:
            raise ValueError("The cut has no geometry.")
        x0, x1 = min(p[0] for p in xs), max(p[0] for p in xs)
        y0, y1 = min(p[1] for p in xs), max(p[1] for p in xs)
        self.diag = math.hypot(x1 - x0, y1 - y0) or 1.0
        self.tol = max(5e-6 * self.diag, 1e-5)                 # mm
        self.pm = _Merger(self.tol)
        self.xy = {0: (0.0, 0.0)}                              # point id -> (x, y) in mm
        self.new_pts = set()
        self.lines, self.arcs, self.circles = [], [], []
        self.pairs, self.seen_arcs, self.seen_circles = set(), set(), set()
        self.interior = []                                     # points of approximated curves: they get fixed
        self.mine = set()                                      # ids of the constraints made here
        self.sym_of = {}                                       # constraint id -> its symbol
        self.taken = set(m.params)
        self.notes = []
        self.dups = 0
        self.approx_edges = 0

    # ----- names / geometry ------------------------------------------------------------------
    def symbol(self, base):
        name, i = base, 2
        while name in self.taken:
            name = f"{base}_{i}"
            i += 1
        self.taken.add(name)
        return name

    def point(self, x, y):
        pid = self.pm.find(x, y)
        if pid is not None:
            return pid
        pid = self.m.add_point(x * self.k, y * self.k)
        self.pm.add(pid, x, y)
        self.xy[pid] = (x, y)
        self.new_pts.add(pid)
        return pid

    def add_line(self, a, b, approx):
        if a == b:
            return None
        key = (min(a, b), max(a, b))
        if key in self.pairs:
            self.dups += 1
            return None
        self.pairs.add(key)
        lid = self.m.add_line(a, b)
        self.lines.append({"id": lid, "a": a, "b": b, "approx": approx})
        return lid

    def make_geometry(self):
        for loop in self.loops:
            for e in loop["edges"]:
                t = e["t"]
                if t == "line":
                    self.add_line(self.point(*e["a"]), self.point(*e["b"]), False)
                elif t == "circle":
                    c = self.point(*e["c"])
                    key = (c, round(e["r"] / self.tol))
                    if key in self.seen_circles:
                        self.dups += 1
                        continue
                    self.seen_circles.add(key)
                    cid = self.m.add_circle(c, e["r"] * self.k)
                    self.circles.append({"id": cid, "c": c, "r": e["r"]})
                elif t == "arc":
                    c = self.point(*e["c"])
                    s, en = self.point(*e["s"]), self.point(*e["e"])
                    if s == en:
                        continue
                    cx, cy = e["c"]
                    cross = (e["s"][0] - cx) * (e["m"][1] - cy) - (e["s"][1] - cy) * (e["m"][0] - cx)
                    S, E = (s, en) if cross >= 0 else (en, s)
                    if (c, S, E) in self.seen_arcs:
                        self.dups += 1
                        continue
                    self.seen_arcs.add((c, S, E))
                    aid = self.m.add_arc(c, S, E)
                    self.arcs.append({"id": aid, "c": c, "s": S, "e": E, "r": e["r"]})
                elif t == "poly":
                    pts = e["pts"]
                    if len(pts) < 2:
                        continue
                    self.approx_edges += 1
                    ids = [self.point(*p) for p in pts]
                    for p in ids[1:-1]:
                        if p in self.new_pts and p not in self.interior:
                            self.interior.append(p)
                    for a, b in zip(ids[:-1], ids[1:]):
                        self.add_line(a, b, True)

    # ----- constraints and dimensions ---------------------------------------------------------
    def con(self, typ, refs, **kw):
        c = self.m.add_con(typ, refs, **kw)
        self.mine.add(c["id"])
        return c

    def dim(self, typ, refs, value, base, sign=None):
        sym = self.symbol(base)
        self.m.add_param(sym, value)
        kw = {"value": value, "expr": sym}
        if sign is not None:
            kw["sign"] = sign
        c = self.con(typ, refs, **kw)
        self.sym_of[c["id"]] = sym
        return c

    def remove(self, ids):
        ids = set(ids) & self.mine
        if not ids:
            return 0
        n = 0
        for c in list(self.m.cons):
            if c["id"] in ids:
                self.m.cons.remove(c)
                n += 1
                sym = self.sym_of.pop(c["id"], None)
                if sym and sym in self.m.params and not any(d.get("expr") == sym for d in self.m.cons):
                    del self.m.params[sym]
                    self.taken.discard(sym)
                self.mine.discard(c["id"])
        return n

    def geometric_constraints(self):
        m, xy = self.m, self.xy
        for l in self.lines:
            if l["approx"]:
                continue
            (ax, ay), (bx, by) = xy[l["a"]], xy[l["b"]]
            L = math.hypot(bx - ax, by - ay)
            if L < self.tol:
                continue
            if abs(by - ay) / L < ANG_TOL:
                self.con("horizontal", [("ln", l["id"])])
                l["dir"] = "h"
            elif abs(bx - ax) / L < ANG_TOL:
                self.con("vertical", [("ln", l["id"])])
                l["dir"] = "v"
        rounds = sorted([("ci", c["id"], c["r"]) for c in self.circles] + [("ar", a["id"], a["r"]) for a in self.arcs],
                        key=lambda t: t[2])
        group = []
        for item in rounds + [None]:
            if item is not None and group and abs(item[2] - group[0][2]) <= 1e-5 * max(group[0][2], 1e-3) + self.tol:
                group.append(item)
                continue
            if len(group) >= 2:
                self.con("equal", [(k, i) for k, i, _ in group])
            group = [item] if item is not None else []
        for a in self.arcs:                                     # a line leaving an arc along its tangent
            cx, cy = xy[a["c"]]
            for end in (a["s"], a["e"]):
                qx, qy = xy[end]
                rx, ry = qx - cx, qy - cy
                rl = math.hypot(rx, ry) or 1.0
                for l in self.lines:
                    if l["approx"] or end not in (l["a"], l["b"]):
                        continue
                    (ax, ay), (bx, by) = xy[l["a"]], xy[l["b"]]
                    L = math.hypot(bx - ax, by - ay)
                    if L < self.tol:
                        continue
                    if abs(((bx - ax) * rx + (by - ay) * ry) / (L * rl)) < ANG_TOL:
                        self.con("tangent", [("ln", l["id"]), ("ar", a["id"])])
        for p in self.interior:
            self.con("fixed", [("pt", p)], xy=tuple(self.m.pts[p]))

    def offset_dims(self, p, q, bx, by):
        """Dimensions (or same-x / same-y constraints) locating point q from point p."""
        (px, py), (qx, qy) = self.xy[p], self.xy[q]
        dx, dy = qx - px, qy - py
        if abs(dx) <= 2 * self.tol:
            self.con("vertical", [("pt", p), ("pt", q)])
        else:
            self.dim("dim_h", [("pt", p), ("pt", q)], abs(dx) * self.k, bx, 1 if dx > 0 else -1)
        if abs(dy) <= 2 * self.tol:
            self.con("horizontal", [("pt", p), ("pt", q)])
        else:
            self.dim("dim_v", [("pt", p), ("pt", q)], abs(dy) * self.k, by, 1 if dy > 0 else -1)

    def reference_point(self):
        ends = set()
        for l in self.lines:
            if not l["approx"]:
                ends |= {l["a"], l["b"]}
        for a in self.arcs:
            ends |= {a["s"], a["e"]}
        if ends:
            return min(ends, key=lambda p: (round(self.xy[p][0] / self.tol), round(self.xy[p][1] / self.tol)))
        if self.circles:
            return min((c["c"] for c in self.circles), key=lambda p: self.xy[p])
        return None

    def key_dimensions(self):
        R = self.reference_point()
        self.ref = R
        if R is not None:
            self.offset_dims(0, R, "x0", "y0")
        for j, c in enumerate(self.circles, 1):
            self.dim("dim_dia", [("ci", c["id"])], 2 * c["r"] * self.k, f"hole{j}_d")
        for j, a in enumerate(self.arcs, 1):
            self.dim("dim_rad", [("ar", a["id"])], a["r"] * self.k, f"r{j}")
        for j, c in enumerate(self.circles, 1):
            if R is not None and c["c"] != R:
                self.offset_dims(R, c["c"], f"hole{j}_x", f"hole{j}_y")
        for j, l in enumerate(self.lines, 1):
            if l["approx"]:
                continue
            (ax, ay), (bx, by) = self.xy[l["a"]], self.xy[l["b"]]
            L = math.hypot(bx - ax, by - ay)
            if L < self.tol:
                continue
            ref = [("ln", l["id"])]
            if l.get("dir") == "h":
                self.dim("dim_h", ref, abs(bx - ax) * self.k, f"w{j}", 1 if bx >= ax else -1)
            elif l.get("dir") == "v":
                self.dim("dim_v", ref, abs(by - ay) * self.k, f"h{j}", 1 if by >= ay else -1)
            else:
                self.dim("dim_len", ref, L * self.k, f"l{j}")
                self.dim("dim_h", ref, abs(bx - ax) * self.k, f"w{j}", 1 if bx >= ax else -1)
                self.dim("dim_v", ref, abs(by - ay) * self.k, f"h{j}", 1 if by >= ay else -1)

    def settle(self, max_rounds=400):
        """Solve, drop what the solver calls redundant or conflicting, add dimensions for what is still free; until nothing changes."""
        m = self.m
        stuck = 0
        last = None
        rep = None
        for _ in range(max_rounds):
            rep = m.solve()
            bad = [cid for cid in list(rep.redundant) + list(rep.conflicts) if cid in self.mine]
            if bad:
                self.remove(bad)
                continue
            free = [p for p in rep.free_pts if p in self.new_pts]
            if rep.dof <= 0 or not free:
                break
            if last is not None and rep.dof >= last:
                stuck += 1
                if stuck >= 3:
                    break
            else:
                stuck = 0
            last = rep.dof
            freeset = set(rep.free_pts)
            done = [p for p in self.xy if p not in freeset and (p == 0 or p in self.new_pts)]
            for p in sorted(free)[:40]:
                px, py = self.xy[p]
                q = min(done, key=lambda t: (self.xy[t][0] - px) ** 2 + (self.xy[t][1] - py) ** 2)
                self.offset_dims(q, p, f"dx{p}", f"dy{p}")
        return rep

    def overall_dims(self):
        pts = []
        for l in self.lines:
            pts += [self.xy[l["a"]], self.xy[l["b"]]]
        for c in self.circles:
            cx, cy = self.xy[c["c"]]
            pts += [(cx - c["r"], cy - c["r"]), (cx + c["r"], cy + c["r"])]
        for a in self.arcs:
            pts += _arc_extremes(self.xy[a["c"]], a["r"], self.xy[a["s"]], self.xy[a["e"]])
        if not pts:
            return
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        verts = {}
        for l in self.lines:
            verts[l["a"]] = self.xy[l["a"]]
            verts[l["b"]] = self.xy[l["b"]]
        for a in self.arcs:
            verts[a["s"]] = self.xy[a["s"]]
            verts[a["e"]] = self.xy[a["e"]]
        for typ, idx, lo, hi, base in (("dim_h", 0, x0, x1, "W_total"), ("dim_v", 1, y0, y1, "H_total")):
            pmin = next((p for p, xy in verts.items() if abs(xy[idx] - lo) <= 2 * self.tol), None)
            pmax = next((p for p, xy in verts.items() if abs(xy[idx] - hi) <= 2 * self.tol), None)
            if pmin is None or pmax is None or pmin == pmax:
                continue
            sym = self.symbol(base)
            val = (hi - lo) * self.k
            self.m.params[sym] = {"vals": [val] * len(self.m.configs), "input": False, "expr": None}
            c = self.con(typ, [("pt", pmin), ("pt", pmax)], value=val, expr=sym, sign=1)
            self.sym_of[c["id"]] = sym


def _edge_points(e):
    t = e["t"]
    if t == "line":
        return [tuple(e["a"]), tuple(e["b"])]
    if t == "poly":
        return [tuple(p) for p in e["pts"]]
    if t == "circle":
        return [(e["c"][0] - e["r"], e["c"][1] - e["r"]), (e["c"][0] + e["r"], e["c"][1] + e["r"])]
    if t == "arc":
        return _arc_extremes(e["c"], e["r"], e["s"], e["e"])
    return []


def build(m, loops, scale):
    """Adds the outlines to model m (which may already hold a sketch).  -> dict with counts and notes for the user."""
    if not loops:
        raise ValueError("The plane does not cut any of the chosen parts.")
    b = _Builder(m, loops, scale)
    b.make_geometry()
    outlines, holes = count_loops(loops)
    n_ent = len(b.new_pts)
    info = {"outlines": outlines, "holes": holes, "lines": len(b.lines), "arcs": len(b.arcs), "circles": len(b.circles),
            "points": n_ent, "duplicates": b.dups, "approximated": b.approx_edges, "dims": 0, "dof": None, "notes": b.notes}
    b.geometric_constraints()
    if n_ent > MAX_POINTS_FOR_DIMS:
        b.notes.append(f"The outline has {n_ent} points, so no dimensions were made (it would take very long). "
                       "Lock or fix what you need.")
        rep = m.solve()
    else:
        b.key_dimensions()
        rep = b.settle()
        b.overall_dims()
        rep = m.solve()
    info["dims"] = sum(1 for c in m.cons if c["id"] in b.mine and c["type"] in sc.DIMENSIONS and not c.get("driven"))
    info["driven"] = sum(1 for c in m.cons if c["id"] in b.mine and c["type"] in sc.DIMENSIONS and c.get("driven"))
    info["constraints"] = sum(1 for c in m.cons if c["id"] in b.mine and c["type"] not in sc.DIMENSIONS)
    info["dof"] = rep.dof if rep is not None else None
    info["status"] = rep.status if rep is not None else ""
    if info["dof"]:
        b.notes.append(f"{info['dof']} degree(s) of freedom are left; the free points are shown in the Warnings panel. "
                       "Add dimensions for them.")
    if b.dups:
        b.notes.append(f"{b.dups} duplicate line(s)/arc(s)/circle(s) (the same edge from two parts) were left out.")
    if b.approx_edges:
        b.notes.append(f"{b.approx_edges} curve(s) that are not lines, arcs or circles were replaced by short lines whose points are fixed.")
    return info
