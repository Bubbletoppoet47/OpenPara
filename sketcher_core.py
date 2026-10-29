"""
sketcher_core.py - geometry model and constraint solver for the 2D sketcher.

Entities : points, lines, circles, arcs (arc = centre + start point + end point, counter-clockwise).
Relations: 'constraints' (geometric) and 'dimensions' (a constraint that carries a number).
Solver   : damped least squares (Levenberg-Marquardt) with a sparse numeric Jacobian, numpy only.
Report   : degrees of freedom, which entities are still free, conflicting and redundant constraints.
"""
import pose_math
import units
import copy
import json
import math
import re

import numpy as np

import ast
import itertools
import operator

_FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sqrt": math.sqrt, "abs": abs,
    "sind": lambda a: math.sin(math.radians(a)), "cosd": lambda a: math.cos(math.radians(a)),
    "tand": lambda a: math.tan(math.radians(a)), "atand": lambda a: math.degrees(math.atan(a)),
    "asind": lambda a: math.degrees(math.asin(a)), "acosd": lambda a: math.degrees(math.acos(a)),
}
# friendly aliases:  arctan(x) = atan(x) (radians),  arctand(x) = atand(x) (degrees), ...
for _n in ("sin", "cos", "tan"):
    _FUNCS["arc" + _n] = _FUNCS["a" + _n]
    _FUNCS["arc" + _n + "d"] = _FUNCS["a" + _n + "d"] if "a" + _n + "d" in _FUNCS else None
_FUNCS = {k: v for k, v in _FUNCS.items() if v is not None}
_FUNCS["arctand"] = _FUNCS["atand"]
_CONSTS = {"pi": math.pi}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow}


def _parse(text):
    return ast.parse(text.replace("^", "**").strip(), mode="eval")


def expr_symbols(text):
    """Names used in an expression (functions and constants excluded)."""
    names = set()
    for n in ast.walk(_parse(text)):
        if isinstance(n, ast.Name) and n.id not in _FUNCS and n.id not in _CONSTS:
            names.add(n.id)
    return names


def safe_eval(text, ns):
    """Evaluate a small arithmetic expression: numbers, names from ns, + - * / ^, sin cos tan atan sqrt, sind ..."""
    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id in ns:
                return ns[n.id]
            if n.id in _CONSTS:
                return _CONSTS[n.id]
            raise KeyError(n.id)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -ev(n.operand) if isinstance(n.op, ast.USub) else ev(n.operand)
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and len(n.args) == 1:
            return _FUNCS[n.func.id](ev(n.args[0]))
        raise ValueError("unsupported expression")
    return ev(_parse(text).body)


TOL = 1e-6

# --- constraint / dimension catalogue ------------------------------------------------------------
GEOMETRIC = ("coincident", "horizontal", "vertical", "parallel", "perpendicular", "collinear",
             "equal", "concentric", "tangent", "fixed", "midpoint",
             "rigid_pt", "rigid_len", "rigid_rad",      # these hold the outline of a placed part rigid (see Solver.rigid)
             "proj_pt")                                # a point of a 3D placed part, projected into an assembly sketch (see Solver.proj)
DIMENSIONS = ("dim_h", "dim_v", "dim_len", "dim_rad", "dim_dia", "dim_ang", "dim_off")
DIM_PREFIX = {"dim_h": "H", "dim_v": "V", "dim_len": "L", "dim_rad": "R", "dim_dia": "D", "dim_ang": "A", "dim_off": "O"}
LABEL = {"coincident": "Coincident", "horizontal": "Horizontal", "vertical": "Vertical", "parallel": "Parallel",
         "perpendicular": "Perpendicular", "collinear": "Collinear", "equal": "Equal", "concentric": "Concentric",
         "tangent": "Tangent", "fixed": "Fixed", "midpoint": "Midpoint", "dim_h": "Horizontal dim",
         "dim_v": "Vertical dim", "dim_len": "Length dim", "dim_rad": "Radius dim", "dim_dia": "Diameter dim",
         "dim_ang": "Angle dim", "dim_off": "Offset dim", "rigid_pt": "Part point", "rigid_len": "Part size",
         "rigid_rad": "Part radius", "proj_pt": "3D part point"}


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def fix_p3(v):
    v = dict(v)
    v["keys"] = dict(v.get("keys", {}))
    v["ents"] = {k: [int(i) for i in ids] for k, ids in v.get("ents", {}).items()}
    v["sig"] = list(v.get("sig", []))
    return v


def fix_inst(v):
    """A placed-part record as it comes back from JSON (integer keys, tuples)."""
    v = dict(v)
    v["loc"] = {int(k): (float(a), float(b)) for k, (a, b) in v.get("loc", {}).items()}
    v["rad"] = {int(k): float(r) for k, r in v.get("rad", {}).items()}
    v["A_loc"] = (float(v["A_loc"][0]), float(v["A_loc"][1]))
    v["B"], v["A"] = int(v["B"]), int(v["A"])
    v["name"] = str(v.get("name", ""))
    v["keys"] = dict(v.get("keys", {}))
    v["ents"] = {k: [int(i) for i in ids] for k, ids in v.get("ents", {}).items()}
    return v


class Cancelled(Exception):
    """Raised inside a solve when the user pressed Cancel."""


class Model:
    """All sketch data.  Plain dicts/lists so it can be saved as JSON and snapshotted for undo."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.pts = {}      # id -> [x, y]
        self.lns = {}      # id -> [pid_a, pid_b]
        self.cis = {}      # id -> {"c": pid, "r": radius}
        self.ars = {}      # id -> {"c": pid, "s": pid, "e": pid}
        self.lock_pts = {}   # point id -> [x, y]  frozen position (locked geometry)
        self.lock_cis = {}   # circle id -> radius frozen
        self.p3 = {}         # 3D placed parts seen in this assembly sketch: id -> {"sig", "keys": {"pt12": "v3"}, "ents": {"pt": [], "ln": []}}
        self.ctx3d = None    # assembly sketch: {"view": plane name, "k": mm per unit, "poses": {part id: pose}} (not saved)
        self.insts = {}      # placed parts: id -> {"src", "view", "flip", "B", "A", "A_loc", "loc", "rad", "keys", "ents"}  (see INSTANCES)
        self.constr = set()  # construction geometry: {(kind,id)} for ln / ci / ar
        self.cons = []     # dicts: id, type, refs [(kind,id)...], value?, name?, sign?, xy?, off?
        self.nid = 1
        self.ncon = 1
        self.ndim = 1
        self.params = {}            # symbol -> {"vals": [one value per configuration], "input": bool, "expr": str|None}
        self.configs = ["Config 1"]
        self.active = 0
        self.cancel_check = None   # callable -> True when the user wants to stop (checked inside the solver)
        self.progress = None       # callable(text, fraction 0..1) used by the progress bar
        self.span = (0.0, 1.0)     # the part of the progress bar the current stage covers
        self.local = None          # {"pts": set, "cis": set}: only these may move (a local rebuild); everything else is pinned
        self.value_override = {}   # constraint id -> value used instead of its symbol value (continuation steps)
        self.quick_fail = False    # True: a failed solve returns at once (no search for the conflicting constraint)
        self.ignore_locks = False  # True while a configuration is solved for new inputs: locked positions belong to the drawn shape
        self.shapes = {}           # configuration name -> last clean solved shape {"pts", "cis", "vals"} (not saved)
        self.unit_system = units.DEFAULT   # the unit system the numbers of this sketch are in (see units.py)
        self.report = Report()
        self.ensure_origin()

    def ensure_origin(self):
        """Point 0 is the sketch origin: always present, fixed at (0,0), can be referenced but not changed or deleted."""
        self.pts[0] = [0.0, 0.0]
        self.cons = [c for c in self.cons if not c.get("origin")]
        self.cons.insert(0, {"id": 0, "type": "fixed", "refs": [("pt", 0)], "xy": (0.0, 0.0), "origin": True})

    # ----- creation helpers -------------------------------------------------------------------
    def _id(self):
        i = self.nid
        self.nid += 1
        return i

    def add_point(self, x, y):
        i = self._id()
        self.pts[i] = [float(x), float(y)]
        return i

    def add_line(self, a, b):
        i = self._id()
        self.lns[i] = [a, b]
        return i

    def add_circle(self, c, r):
        i = self._id()
        self.cis[i] = {"c": c, "r": float(r)}
        return i

    def add_arc(self, c, s, e):
        i = self._id()
        self.ars[i] = {"c": c, "s": s, "e": e}
        return i

    def add_con(self, typ, refs, **kw):
        c = {"id": self.ncon, "type": typ, "refs": [tuple(r) for r in refs]}
        self.ncon += 1
        if typ in DIMENSIONS:
            c["name"] = self.next_dim_name(typ)
            self.ndim += 1
        c.update(kw)
        self.cons.append(c)
        return c

    def next_dim_name(self, typ, extra=()):
        """The default name of a new dimension: the prefix of its type with the LOWEST number that is not used yet (not by a symbol, a
        dimension, or a name in `extra`, e.g. the symbols of the sketches linked to this one)."""
        pre = DIM_PREFIX[typ]
        taken = set(self.params) | set(extra) | {c.get("name") for c in self.cons if c["type"] in DIMENSIONS}
        n = 1
        while f"{pre}{n}" in taken:
            n += 1
        return f"{pre}{n}"

    def con_by_id(self, cid):
        return next((c for c in self.cons if c["id"] == cid), None)

    # ----- geometry queries ------------------------------------------------------------------
    def P(self, pid):
        return self.pts[pid]

    def line_pts(self, lid):
        a, b = self.lns[lid]
        return self.pts[a], self.pts[b]

    def radius(self, kind, i):
        if kind == "ci":
            return self.cis[i]["r"]
        a = self.ars[i]
        c, s = self.pts[a["c"]], self.pts[a["s"]]
        return math.hypot(s[0] - c[0], s[1] - c[1])

    def center(self, kind, i):
        return self.pts[(self.cis if kind == "ci" else self.ars)[i]["c"]]

    # ----- angle dimensions: which of the four sectors between two lines is measured ---------------
    def line_intersection(self, refs):
        """Where the two (infinite) lines of an angle dimension cross, or None when they are parallel."""
        (ax, ay), (bx, by) = self.line_pts(refs[0][1])
        (cx, cy), (dx, dy) = self.line_pts(refs[1][1])
        d1, d2 = (bx - ax, by - ay), (dx - cx, dy - cy)
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-12 * max(1.0, math.hypot(*d1) * math.hypot(*d2)):
            return None
        t = ((cx - ax) * d2[1] - (cy - ay) * d2[0]) / den
        return (ax + t * d1[0], ay + t * d1[1])

    def _sector(self, refs, s1, s2):
        d1, d2 = self._dir(refs[0][1]), self._dir(refs[1][1])
        u, w = (s1 * d1[0], s1 * d1[1]), (s2 * d2[0], s2 * d2[1])
        cr = u[0] * w[1] - u[1] * w[0]
        dt = u[0] * w[0] + u[1] * w[1]
        return math.degrees(math.atan2(abs(cr), dt)), (1 if cr >= 0 else -1)

    def angle_default(self, refs, hint=None):
        """(s1, s2, eps, value): the two rays that bound the measured sector (s = which way along each line)
        and the angle between them.  With a hint point (the cursor) the sector that contains it is used,
        like SolidWorks; otherwise the acute one."""
        combos = [(s1, s2) for s1 in (1, -1) for s2 in (1, -1)]
        pick = None
        I = self.line_intersection(refs) if hint is not None else None
        if I is not None:
            mx, my = hint[0] - I[0], hint[1] - I[1]
            d1, d2 = self._dir(refs[0][1]), self._dir(refs[1][1])
            for s1, s2 in combos:
                r1, r2 = (s1 * d1[0], s1 * d1[1]), (s2 * d2[0], s2 * d2[1])
                cr = r1[0] * r2[1] - r1[1] * r2[0]
                if abs(cr) < 1e-12:
                    continue
                a = (r1[0] * my - r1[1] * mx) * cr
                b = (mx * r2[1] - my * r2[0]) * cr
                if a > 0 and b > 0:
                    pick = (s1, s2)
                    break
        if pick is None:
            pick = min(combos, key=lambda c: (self._sector(refs, *c)[0] > 90.0 + 1e-9, c != (1, 1) and c != (1, -1)))
        v, eps = self._sector(refs, *pick)
        return pick[0], pick[1], eps, v

    def ensure_angle(self, c):
        """Old / hand-written angle dimensions get their sector from the current drawing and their value."""
        if "s1" in c and "s2" in c and "eps" in c:
            return
        combos = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        target = c.get("value", 0.0)
        best = min(combos, key=lambda cb: (abs(self._sector(c["refs"], *cb)[0] - target), cb[0] != 1))
        v, eps = self._sector(c["refs"], *best)
        c["s1"], c["s2"], c["eps"] = best[0], best[1], eps

    def measure(self, typ, refs, c=None):
        """Current value of a dimension (used as the default when it is created)."""
        if typ == "dim_ang":
            if c is not None and "s1" in c:
                return self._sector(refs, c["s1"], c["s2"])[0]
            return self.angle_default(refs)[3]
        pa, pb = self._two_points(refs)
        if typ == "dim_h":
            return abs(pb[0] - pa[0])
        if typ == "dim_v":
            return abs(pb[1] - pa[1])
        if typ == "dim_len":
            return math.hypot(pb[0] - pa[0], pb[1] - pa[1])
        if typ == "dim_rad":
            return self.radius(*refs[0])
        if typ == "dim_dia":
            return 2 * self.radius(*refs[0])
        if typ == "dim_off":
            (k1, i1), (k2, i2) = refs[0], refs[1]
            if k1 == "ln":
                (ax, ay), (bx, by) = self.line_pts(i1)
                px, py = self.pts[self.lns[i2][0]]
                L = math.hypot(bx - ax, by - ay) or 1e-12
                return abs(((px - ax) * (by - ay) - (py - ay) * (bx - ax)) / L)
            return abs(self.radius(k2, i2) - self.radius(k1, i1))
        return 0.0

    def _dir(self, lid):
        a, b = self.line_pts(lid)
        return (b[0] - a[0], b[1] - a[1])

    def _two_points(self, refs):
        if refs and refs[0][0] == "ln":
            return self.line_pts(refs[0][1])
        if len(refs) >= 2 and refs[0][0] == "pt" and refs[1][0] == "pt":
            return self.pts[refs[0][1]], self.pts[refs[1][1]]
        return None, None

    # ----- delete -----------------------------------------------------------------------------
    def delete(self, items, force3d=False):
        """Delete entities (and everything that depends on them) or constraints/dimensions.  The projected points and lines of 3D placed
        parts are not deleted one by one (they follow the part) unless force3d."""
        dead = set(items) - {("pt", 0), ("con", 0)}
        if self.p3 and not force3d:
            dead = {x for x in dead if x[0] == "con" or not self.p3_owner(*x)}
        gone = {i for k, i in dead if k == "con"}
        for iid, ins in list(self.insts.items()):              # a placed part is removed as a whole
            if any(f"{k}{i}" in ins["keys"] for k, i in dead):
                dead |= {(k, i) for k, ids in ins["ents"].items() for i in ids}
                self.insts.pop(iid, None)
        grps = {c["grp"] for c in self.cons if c["id"] in gone and c.get("grp") is not None}
        if grps:                                              # an offset dimension goes with all the ones sharing its symbol
            dead |= {("con", c["id"]) for c in self.cons if c.get("grp") in grps}
        changed = True
        while changed:
            changed = False
            for lid, (a, b) in list(self.lns.items()):
                if ("pt", a) in dead or ("pt", b) in dead:
                    changed |= ("ln", lid) not in dead
                    dead.add(("ln", lid))
            for cid, c in list(self.cis.items()):
                if ("pt", c["c"]) in dead:
                    changed |= ("ci", cid) not in dead
                    dead.add(("ci", cid))
            for aid, a in list(self.ars.items()):
                if ("pt", a["c"]) in dead or ("pt", a["s"]) in dead or ("pt", a["e"]) in dead:
                    changed |= ("ar", aid) not in dead
                    dead.add(("ar", aid))
        for k, i in dead:
            if k == "ln":
                self.lns.pop(i, None)
            elif k == "ci":
                self.cis.pop(i, None)
            elif k == "ar":
                self.ars.pop(i, None)
        for k, i in dead:
            if k == "pt":
                self.pts.pop(i, None)
        self.constr -= dead
        for k, i in dead:
            if k == "pt":
                self.lock_pts.pop(i, None)
            elif k == "ci":
                self.lock_cis.pop(i, None)
        deadcons = {i for k, i in dead if k == "con"}
        self.cons = [c for c in self.cons if c["id"] not in deadcons and not any(r in dead for r in c["refs"])]
        self.fix_offset_groups()

    def fix_offset_groups(self):
        """Of the offset dimensions that share one symbol, exactly one (the lead) is drawn; keep that true after deletions."""
        by = {}
        for c in self.cons:
            if c.get("grp") is not None:
                by.setdefault(c["grp"], []).append(c)
        for lst in by.values():
            if all(c.get("hide") for c in lst):
                lst[0]["hide"] = False

    def extent(self):
        """Overall size of the sketch (largest side of the box around its points)."""
        xs = [p[0] for p in self.pts.values()]
        ys = [p[1] for p in self.pts.values()]
        return max(max(xs) - min(xs), max(ys) - min(ys), 1e-12) if xs else 1.0

    def weld_plan(self, groups, tol, progress=None, cancel=None):
        """Which points would be merged: {new point id: older point id it joins}.  Nothing is changed.
        groups = [[point ids of one new copy], ...]; points of one group are never merged with each other.
        progress(fraction) / cancel() -> True raise Cancelled."""
        if tol <= 0:
            return {}
        group_of = {p: gi for gi, g in enumerate(groups) for p in g if p in self.pts}
        new_ids = sorted(group_of)
        grid = {}                                                  # cell -> [(point id, group or None)]

        def cell(x, y):
            return (math.floor(x / tol), math.floor(y / tol))
        for i, (x, y) in self.pts.items():
            if i not in group_of:
                grid.setdefault(cell(x, y), []).append((i, None))
        remap = {}
        total = max(len(new_ids), 1)
        for step, n in enumerate(new_ids):
            if step % 200 == 0:
                if cancel and cancel():
                    raise Cancelled()
                if progress:
                    progress(step / total)
            x, y = self.pts[n]
            cx, cy = cell(x, y)
            best, bd = None, tol
            for ix in (cx - 1, cx, cx + 1):
                for iy in (cy - 1, cy, cy + 1):
                    for k, kg in grid.get((ix, iy), ()):
                        if kg == group_of[n]:
                            continue
                        kx, ky = self.pts[k]
                        d = math.hypot(kx - x, ky - y)
                        if d <= bd:
                            best, bd = k, d
            if best is None:
                grid.setdefault((cx, cy), []).append((n, group_of[n]))
            else:
                remap[n] = best
        if progress:
            progress(1.0)
        return remap

    def weld_preview(self, groups, tol):
        """-> (points that would be merged, edges that would become duplicates / vanish).  Nothing is changed."""
        remap = self.weld_plan(groups, tol)
        if not remap:
            return 0, 0
        seen, dup = set(), 0
        for l in self.lns.values():
            a, b = remap.get(l[0], l[0]), remap.get(l[1], l[1])
            key = frozenset((a, b))
            if a == b or key in seen:
                dup += 1
            else:
                seen.add(key)
        return len(remap), dup

    def weld_points(self, groups, tol, progress=None, cancel=None):
        """Join points that lie within `tol` of each other.  groups = [[point ids of one new copy], ...]: every point of a
        group is merged into an older point (or into a point of an earlier group) that it touches; points of one group are
        never merged with each other.  Lines / circles / arcs that become identical are dropped, and so are constraints that
        become duplicates.  -> {"merged", "lines", "circles", "arcs", "constraints"} counts.
        Cancelling (only possible while the matching is scanned) leaves the sketch untouched and raises Cancelled."""
        stats = {"merged": 0, "lines": 0, "circles": 0, "arcs": 0, "constraints": 0}
        remap = self.weld_plan(groups, tol, progress, cancel)
        if not remap:
            return stats
        stats["merged"] = len(remap)
        for l in self.lns.values():
            l[0], l[1] = remap.get(l[0], l[0]), remap.get(l[1], l[1])
        for c in self.cis.values():
            c["c"] = remap.get(c["c"], c["c"])
        for a in self.ars.values():
            for k in ("c", "s", "e"):
                a[k] = remap.get(a[k], a[k])
        for n, k in remap.items():
            self.pts.pop(n, None)
            if n in self.lock_pts and k not in self.lock_pts:
                self.lock_pts[k] = list(self.pts[k])
            self.lock_pts.pop(n, None)
        for c in self.cons:
            c["refs"] = [("pt", remap[i]) if (kind == "pt" and i in remap) else (kind, i) for kind, i in c["refs"]]
        dead = set()
        seen = {}
        for lid in sorted(self.lns):                                  # a line shrunk to a point, or a second copy of a line
            a, b = self.lns[lid]
            key = ("ln", frozenset((a, b)))
            if a == b or key in seen:
                dead.add(("ln", lid))
                stats["lines"] += 1
            else:
                seen[key] = lid
        for cid in sorted(self.cis):
            key = ("ci", self.cis[cid]["c"], round(self.cis[cid]["r"], 9))
            if key in seen:
                dead.add(("ci", cid))
                stats["circles"] += 1
            else:
                seen[key] = cid
        for aid in sorted(self.ars):
            a = self.ars[aid]
            key = ("ar", a["c"], a["s"], a["e"])
            if key in seen:
                dead.add(("ar", aid))
                stats["arcs"] += 1
            else:
                seen[key] = aid
        for k, i in dead:
            {"ln": self.lns, "ci": self.cis, "ar": self.ars}[k].pop(i, None)
            self.lock_cis.pop(i, None) if k == "ci" else None
        self.constr -= dead
        symmetric = {"parallel", "perpendicular", "equal", "coincident", "collinear", "concentric", "tangent"}
        keep, have = [], set()
        for c in self.cons:
            if any(r in dead for r in c["refs"]):
                stats["constraints"] += 1
                continue
            refs = tuple(c["refs"])
            key = (c["type"], tuple(sorted(refs)) if c["type"] in symmetric else refs, c.get("sign"))
            if c["type"] == "coincident" and len({r for r in refs}) < len(refs):
                stats["constraints"] += 1                              # a point "on itself" after the merge
                continue
            if key in have and not c.get("origin"):
                stats["constraints"] += 1
                continue
            have.add(key)
            keep.append(c)
        self.cons = keep
        return stats

    # ----- save / load -----------------------------------------------------------------------
    # ----- split lines / arcs (the midpoint tool) ------------------------------------------------
    def split_segments(self, items, fracs, equal=False):
        """Split each selected line / arc at the fractions `fracs` (ascending, strictly between 0 and 1; measured along the
        line, or in angle round the arc from its start).  The geometry does not change.  The piece that keeps the old id is the
        first one, so anything that points at the old line (FEA supports, loads) still finds its start.  New pieces get
        coincident (shared point) + collinear (lines) or concentric + equal radius (arcs) constraints; with `equal` the pieces
        are also kept equal.  Constraints that cannot survive a split (equal / midpoint on a line) make that segment skipped.
        -> {"done": n, "points": [new pids], "skipped": [(kind, id, why)]}"""
        out = {"done": 0, "points": [], "skipped": []}
        fr = sorted(f for f in fracs if 1e-6 < f < 1 - 1e-6)
        if not fr:
            return out
        for kind, i in items:
            if kind == "ln" and i in self.lns:
                bad = next((c for c in self.cons if (kind, i) in c["refs"] and (
                    (c["type"] == "equal") or (c["type"] == "midpoint"))), None)
                if bad:
                    out["skipped"].append((kind, i, f"it has an '{bad['type']}' constraint, which a split would change - remove it first"))
                    continue
                a, b = self.lns[i]
                (ax, ay), (bx, by) = self.pts[a], self.pts[b]
                chain, ids = [a], [i]
                for f in fr:
                    pid = self.add_point(ax + f * (bx - ax), ay + f * (by - ay))
                    out["points"].append(pid)
                    chain.append(pid)
                chain.append(b)
                self.lns[i] = [a, chain[1]]
                for k in range(1, len(chain) - 1):
                    nl = self.add_line(chain[k], chain[k + 1])
                    ids.append(nl)
                    if (kind, i) in self.constr:
                        self.constr.add(("ln", nl))
                for c in self.cons:                      # a dimension of the whole line becomes a dimension between its end points
                    if c["type"] in ("dim_h", "dim_v", "dim_len") and c["refs"] and c["refs"][0] == (kind, i):
                        c["refs"] = [("pt", a), ("pt", b)]
                for k in range(len(ids) - 1):
                    self.add_con("collinear", [("ln", ids[k + 1]), ("ln", ids[k])])
                if equal:
                    self.add_con("equal", [("ln", j) for j in ids])
                out["done"] += 1
            elif kind == "ar" and i in self.ars:
                ar = self.ars[i]
                c, s_, e_ = self.pts[ar["c"]], self.pts[ar["s"]], self.pts[ar["e"]]
                a0 = math.atan2(s_[1] - c[1], s_[0] - c[0])
                a1 = math.atan2(e_[1] - c[1], e_[0] - c[0])
                while a1 <= a0:
                    a1 += 2 * math.pi
                r = math.hypot(s_[0] - c[0], s_[1] - c[1])
                chain, ids = [ar["s"]], [i]
                for f in fr:
                    an = a0 + f * (a1 - a0)
                    pid = self.add_point(c[0] + r * math.cos(an), c[1] + r * math.sin(an))
                    out["points"].append(pid)
                    chain.append(pid)
                chain.append(ar["e"])
                self.ars[i] = {"c": ar["c"], "s": ar["s"], "e": chain[1]}
                for k in range(1, len(chain) - 1):
                    na = self.add_arc(ar["c"], chain[k], chain[k + 1])
                    ids.append(na)
                    if (kind, i) in self.constr:
                        self.constr.add(("ar", na))
                for k in range(len(ids) - 1):
                    self.add_con("concentric", [("ar", ids[k]), ("ar", ids[k + 1])])
                self.add_con("equal", [("ar", j) for j in ids])        # all pieces on the same circle
                out["done"] += 1
        return out

    def to_json(self):
        return json.dumps({"pts": self.pts, "lns": self.lns, "cis": self.cis, "ars": self.ars, "cons": self.cons,
                           "nid": self.nid, "ncon": self.ncon, "ndim": self.ndim, "params": self.params,
                           "configs": self.configs, "active": self.active,
                           "constr": sorted(self.constr),
                           "lock_pts": self.lock_pts, "lock_cis": self.lock_cis, "unit": self.unit_system, "insts": self.insts,
                           "p3": self.p3})

    def from_json(self, text):
        d = json.loads(text)
        self.pts = {int(k): v for k, v in d["pts"].items()}
        self.lns = {int(k): v for k, v in d["lns"].items()}
        self.cis = {int(k): v for k, v in d["cis"].items()}
        self.ars = {int(k): v for k, v in d["ars"].items()}
        self.cons = d["cons"]
        for c in self.cons:
            c["refs"] = [tuple(r) for r in c["refs"]]
        self.nid, self.ncon, self.ndim = d["nid"], d["ncon"], d["ndim"]
        self.params = d.get("params", {})
        self.configs = d.get("configs", ["Config 1"])
        self.active = d.get("active", 0)
        self.constr = {(k, i) for k, i in d.get("constr", [])}
        self.lock_pts = {int(k): list(v) for k, v in d.get("lock_pts", {}).items()}
        self.lock_cis = {int(k): float(v) for k, v in d.get("lock_cis", {}).items()}
        self.unit_system = d.get("unit") if units.valid(d.get("unit")) else units.DEFAULT
        self.insts = {k: fix_inst(v) for k, v in (d.get("insts") or {}).items()}
        self.p3 = {k: fix_p3(v) for k, v in (d.get("p3") or {}).items()}
        self.report = Report()
        self.ensure_origin()

    def p3_owner(self, kind, i):
        """The id of the 3D placed part a projected point or line belongs to (or None)."""
        key = f"{kind}{i}"
        for pid, d in self.p3.items():
            if key in d["keys"]:
                return pid
        return None

    def inst_owner(self, kind, i):
        """The id of the placed part an entity belongs to (or None)."""
        key = f"{kind}{i}"
        for iid, ins in self.insts.items():
            if key in ins["keys"]:
                return iid
        return None

    def snapshot(self):
        return self.to_json()

    def restore(self, snap):
        self.from_json(snap)

    # ----- description -----------------------------------------------------------------------
    def describe(self, c):
        names = []
        for k, i in c["refs"]:
            names.append({"pt": "Point", "ln": "Line", "ci": "Circle", "ar": "Arc"}[k] + str(i))
        txt = f"{c.get('name', LABEL[c['type']])}"
        if c["type"] in DIMENSIONS:
            if c.get("expr"):
                txt = c["expr"]
            txt += f" = {c['value']:.4g}" + (" deg" if c["type"] == "dim_ang" else "")
        else:
            txt = LABEL[c["type"]]
        return txt + "  (" + ", ".join(names) + ")"

    # ----- changing the unit system -------------------------------------------------------------
    def plan_unit_change(self):
        """Which symbols are lengths, so that a change of unit can rescale them.  -> (set of names or None, problem text).
        A set of base symbols is accepted when scaling exactly those by k scales every length dimension by k and leaves every
        angle dimension alone.  If no set, or more than one set, does that, the change cannot be done safely."""
        vals = self.param_values()
        base = [k for k, p in self.params.items() if not p.get("expr")]
        lens = [c for c in self.cons if c["type"] in DIMENSIONS and c["type"] != "dim_ang" and c.get("expr")]
        angs = [c for c in self.cons if c["type"] == "dim_ang" and c.get("expr")]
        if not lens:
            return set(), ""
        reach = set()

        def reach_of(name, seen):
            if name in seen or name not in self.params:
                return
            seen.add(name)
            p = self.params[name]
            if p.get("expr"):
                for s in expr_symbols(p["expr"]):
                    reach_of(s, seen)
        for c in lens + angs:
            for s in expr_symbols(c["expr"]):
                reach_of(s, reach)
        cand = [b for b in base if b in reach]
        if len(cand) > 14:
            return None, "there are too many symbols to work out which are lengths"

        def evaluate(scale, subset):
            ns = {k: (v * scale if k in subset else v) for k, v in vals.items() if k in base}
            for k, p in self.params.items():
                if p.get("expr"):
                    ns[k] = None
            pend = {k: p["expr"] for k, p in self.params.items() if p.get("expr")}
            for _ in range(len(pend) + 1):
                for k, e in list(pend.items()):
                    try:
                        ns[k] = safe_eval(e, ns)
                        del pend[k]
                    except (KeyError, ValueError, ZeroDivisionError, SyntaxError, TypeError):
                        pass
            out = {}
            for c in lens + angs:
                try:
                    out[c["id"]] = safe_eval(c["expr"], ns)
                except (KeyError, ValueError, ZeroDivisionError, SyntaxError, TypeError):
                    out[c["id"]] = float("nan")
            return out
        base0 = evaluate(1.0, set())
        good = []
        for mask in range(1 << len(cand)):
            sub = {cand[i] for i in range(len(cand)) if mask >> i & 1}
            ok = True
            for k in (2.0, 3.7):
                r = evaluate(k, sub)
                for c in lens:
                    a, b = base0[c["id"]], r[c["id"]]
                    if not (abs(b - k * a) <= 1e-9 * max(1.0, abs(k * a))):
                        ok = False
                for c in angs:
                    a, b = base0[c["id"]], r[c["id"]]
                    if not (abs(b - a) <= 1e-9 * max(1.0, abs(a))):
                        ok = False
                if not ok:
                    break
            if ok:
                good.append(sub)
        if not good:
            bad = [c["expr"] for c in lens if c.get("expr") and not c["expr"].strip().isidentifier()]
            return None, ("a formula mixes lengths with fixed numbers or unitless symbols that would not scale"
                          + (": " + ", ".join(sorted(set(bad))[:5]) if bad else ""))
        if len(good) > 1:
            # symbols no length dimension depends on do not matter, so only differing choices are ambiguous
            return None, ("I cannot tell which of these symbols are lengths: " + ", ".join(sorted(set().union(*good))[:8]))
        return good[0], ""

    def convert_units(self, new, convert=True):
        """Switch to the unit system `new`.  convert=True rescales every length (a 25.4 mm part becomes 1 in);
        convert=False only changes the label.  Raises ValueError (and changes nothing) when a conversion is not possible."""
        old = self.unit_system
        if new == old:
            return
        if convert:
            k = units.length_factor(old, new)
            lensyms, why = self.plan_unit_change()
            if lensyms is None:
                raise ValueError(why)
            for pid, xy in self.pts.items():
                xy[0] *= k
                xy[1] *= k
            for pid, xy in self.lock_pts.items():
                xy[0] *= k
                xy[1] *= k
            for ci in self.cis.values():
                ci["r"] *= k
            for ins in self.insts.values():
                ins["loc"] = {p: (x * k, y * k) for p, (x, y) in ins["loc"].items()}
                ins["rad"] = {c: r * k for c, r in ins["rad"].items()}
                ins["A_loc"] = (ins["A_loc"][0] * k, ins["A_loc"][1] * k)
            for cid in list(self.lock_cis):
                self.lock_cis[cid] *= k
            for c in self.cons:
                if c.get("origin"):
                    continue
                if c["type"] == "fixed" and "xy" in c:
                    c["xy"] = (c["xy"][0] * k, c["xy"][1] * k)
                if c["type"] in DIMENSIONS and c["type"] != "dim_ang":
                    c["value"] = c["value"] * k
                if "offw" in c:
                    c["offw"] = c["offw"] * k
            for name in lensyms:
                self.params[name]["vals"] = [v * k for v in self.params[name]["vals"]]
            for name, p in self.params.items():           # measured (output) symbols that are lengths
                if not p.get("expr") and not p.get("input", True) and name not in lensyms:
                    if any(c.get("expr") == name and c["type"] in DIMENSIONS and c["type"] != "dim_ang" for c in self.cons):
                        p["vals"] = [v * k for v in p["vals"]]
            self.shapes = {}
        self.unit_system = new

    # ----- symbols / parameters ---------------------------------------------------------------
    def add_param(self, name, value, is_input=True, expr=None):
        self.params[name] = {"vals": [float(value)] * len(self.configs), "input": is_input, "expr": expr}

    def set_configs(self, names, active=None):
        """Give the model exactly these configuration names (values of a new name are copied from its active configuration)."""
        old = list(self.configs)
        cur = old[self.active] if 0 <= self.active < len(old) else None
        for p in self.params.values():
            vals = p["vals"]
            fill = vals[min(self.active, len(vals) - 1)]
            p["vals"] = [vals[old.index(cn)] if (cn in old and old.index(cn) < len(vals)) else fill for cn in names]
        self.configs = list(names)
        self.shapes = {k: v for k, v in self.shapes.items() if k in names}
        tgt = active if active in names else (cur if cur in names else names[0])
        self.active = names.index(tgt)

    def add_config(self, name=None):
        name = name or f"Config {len(self.configs) + 1}"
        self.configs.append(name)
        for p in self.params.values():
            p["vals"].append(p["vals"][self.active])
        self.active = len(self.configs) - 1

    def base_values(self):
        return {k: p["vals"][self.active] for k, p in self.params.items() if not p.get("expr")}

    def param_values(self):
        """Numeric value of every symbol in the active configuration (defined symbols are evaluated)."""
        vals = self.base_values()
        pending = {k: p["expr"] for k, p in self.params.items() if p.get("expr")}
        for _ in range(len(pending) + 1):
            for k, e in list(pending.items()):
                try:
                    vals[k] = safe_eval(e, vals)
                    del pending[k]
                except (KeyError, ValueError, ZeroDivisionError, SyntaxError):
                    pass
        for k in pending:
            vals[k] = float("nan")
        return vals

    def rename_symbol(self, old, new):
        """Rename a symbol everywhere: its declaration, every dimension / formula that uses it, the Report flag.
        Raises ValueError (and changes nothing) when the new name cannot be used."""
        if old not in self.params:
            raise ValueError(f"no symbol '{old}'")
        new = new.strip()
        if new == old:
            return
        if not new.isidentifier():
            raise ValueError(f"'{new}' is not a valid name (letters, digits and _, not starting with a digit)")
        if new in self.params:
            raise ValueError(f"a symbol called '{new}' already exists")
        if new in _FUNCS or new in _CONSTS:
            raise ValueError(f"'{new}' is a built-in function / constant")
        pat = re.compile(r"(?<![\w.])" + re.escape(old) + r"(?![\w(])")

        def sub(text):
            return pat.sub(new, text)
        self.params = {(new if k == old else k): v for k, v in self.params.items()}
        for p in self.params.values():
            if p.get("expr"):
                p["expr"] = sub(p["expr"])
        for c in self.cons:
            if c.get("expr"):
                c["expr"] = sub(c["expr"])

    def has_derived(self):
        return any(self.is_output(n) or (p.get("expr") is None and not p.get("input", True)) for n, p in self.params.items())

    def solve_all_configs(self):
        """Solve every other configuration so that derived (output / formula) symbols have a value in every column.
        The drawing itself ends up exactly as it was for the active configuration."""
        if len(self.configs) < 2 or not self.has_derived():
            return False
        for j in range(len(self.configs)):
            if j != self.active:
                self.solve_config(j, settle=False)
        return True

    # ----- solving a configuration robustly (inputs may have changed a lot) --------------------
    def input_names(self):
        return [k for k, p in self.params.items() if not p.get("expr") and p.get("input", True)]

    def snap_shape(self):
        """Geometry of the active configuration together with the input values it belongs to."""
        return {"pts": {k: list(v) for k, v in self.pts.items()}, "cis": {k: v["r"] for k, v in self.cis.items()},
                "vals": {n: self.params[n]["vals"][self.active] for n in self.input_names()}}

    def record_shape(self):
        """Remember the (clean) drawn shape of the active configuration: later solves start from the nearest one."""
        if self.report.ok and not self.report.conflicts:
            self.shapes[self.configs[self.active]] = self.snap_shape()

    def put_shape(self, shape):
        for k, v in shape["pts"].items():
            if k in self.pts:
                self.pts[k] = list(v)
        for k, r in shape["cis"].items():
            if k in self.cis:
                self.cis[k]["r"] = r

    @staticmethod
    def input_distance(a, b):
        return sum(abs(a[n] - b[n]) / (abs(a[n]) + abs(b[n]) + 1e-9) for n in a if n in b)

    def orientation(self):
        """Sine of the turn at every pair of lines that share a point - it changes sign when the shape folds over."""
        ends, res = {}, {}
        for lid, (a, b) in self.lns.items():
            ends.setdefault(a, []).append((lid, b))
            ends.setdefault(b, []).append((lid, a))
        for p, lst in ends.items():
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    (l1, q1), (l2, q2) = lst[i], lst[j]
                    P, A, B = self.pts[p], self.pts[q1], self.pts[q2]
                    cr = (A[0] - P[0]) * (B[1] - P[1]) - (A[1] - P[1]) * (B[0] - P[0])
                    L = math.hypot(A[0] - P[0], A[1] - P[1]) * math.hypot(B[0] - P[0], B[1] - P[1]) or 1.0
                    res[(p, l1, l2)] = cr / L
        return res

    @staticmethod
    def count_flips(a, b):
        return sum(1 for k, v in a.items() if k in b and abs(v) > 0.1 and abs(b[k]) > 0.1 and v * b[k] < 0)

    def report_progress(self, text, f):
        if self.progress:
            lo, hi = self.span
            self.progress(text, lo + (hi - lo) * max(0.0, min(1.0, f)))

    def relock(self):
        """Locked geometry follows the shape that is drawn now."""
        for p in self.lock_pts:
            self.lock_pts[p] = list(self.pts[p])
        for ci in self.lock_cis:
            self.lock_cis[ci] = self.cis[ci]["r"]

    def solve_config(self, idx=None, settle=True, explain=True):
        """Solve configuration `idx` (default: the active one) from its stored input values.
        When the inputs differ from the last solved shape, start from the nearest solved shape and walk to the new
        values in small steps (locks pin the drawn shape, so they are ignored while it moves and re-set afterwards).
        The drawing stays on the active configuration.  -> (ok, folded)"""
        keep = self.active
        idx = keep if idx is None else idx
        ins = self.input_names()
        target = {n: self.params[n]["vals"][idx] for n in ins}
        if idx != keep:
            self.record_shape()
        cands = [(self.input_distance(target, s["vals"]), c) for c, s in self.shapes.items()
                 if c in self.configs and set(s["pts"]) == set(self.pts)]
        d, start = (min(cands)[0], self.shapes[min(cands)[1]]) if cands else (0.0, None)
        if idx == keep and (start is None or d < 1e-9):          # same inputs as before: an ordinary solve
            rep = self.solve()
            ok = bool(rep.ok) and not rep.conflicts
            self.record_shape()
            return ok, False
        keep_shape, keep_rep = self.snap_shape(), self.report
        self.active = idx
        base = start["vals"] if start is not None else target
        before = None
        if start is not None:
            self.put_shape(start)
        before = self.orientation()

        def walk(steps):
            if start is not None:
                self.put_shape(start)
            r = None
            for s in range(1, steps + 1):
                t = s / steps
                for n in ins:
                    a = base.get(n, target[n])
                    self.params[n]["vals"][idx] = a + (target[n] - a) * t
                self.report_progress(f"Solving step {s} of {steps}", s / steps)
                r = self.solve()
                if not (bool(r.ok) and not r.conflicts):
                    return False, r
            return True, r
        first = max(1, min(40, math.ceil(d / 0.01))) if start is not None else 1
        self.ignore_locks, self.quick_fail = True, True
        ok, rep = walk(first)
        if not ok and start is not None:
            ok, rep = walk(min(160, first * 4))
        self.quick_fail = False
        if not ok and not explain:                               # caller will try something else: leave the inputs set
            self.ignore_locks = False
            for n in ins:
                self.params[n]["vals"][idx] = target[n]
            if start is not None:
                self.put_shape(start)
            if idx != keep:
                self.put_shape(keep_shape)
                self.active = keep
                self.report = keep_rep
            return False, False
        if not ok:                                               # one full solve to learn which constraint is the problem
            for n in ins:
                self.params[n]["vals"][idx] = target[n]
            if start is not None:
                self.put_shape(start)
            rep = self.solve()
            ok = bool(rep.ok) and not rep.conflicts
        self.ignore_locks = False
        for n in ins:
            self.params[n]["vals"][idx] = target[n]
        folded = False
        if ok:
            folded = self.count_flips(before, self.orientation()) > 0
            self.shapes[self.configs[idx]] = self.snap_shape()
            if idx == keep:                                      # the drawn shape moved: keep its locks where they now are
                for p in self.lock_pts:
                    self.lock_pts[p] = list(self.pts[p])
                for ci in self.lock_cis:
                    self.lock_cis[ci] = self.cis[ci]["r"]
                if folded:
                    self.report.messages.append("The shape may have folded over (a corner turned the other way). "
                                                "Check the drawing before you use these numbers.")
        if idx != keep:
            self.put_shape(keep_shape)
            self.active = keep
            self.report = keep_rep
            if settle:
                self.solve()                                     # settle the drawn configuration again
        return ok, folded

    def full_rebuild(self, progress=None):
        """The whole rebuild: solve the active configuration for the current inputs (whatever the size of the change),
        retry from shaken starting shapes if needed, explain a failure once, then solve the other configurations.
        Locked geometry is ignored while the shape moves and re-locked at its new place.
        progress(text, fraction) is called as it goes; raises Cancelled when cancel_check() says so."""
        self.progress = progress
        others = [j for j in range(len(self.configs)) if j != self.active] if self.has_derived() else []
        total = 1 + len(others)
        self.span = (0.0, 1.0 / total)
        self.report_progress("Solving the active configuration", 0.0)
        ok, folded = self.solve_config(explain=False)
        shaken = 0
        if not ok:
            import random
            ins = self.input_names()
            cands = [(self.input_distance({n: self.params[n]["vals"][self.active] for n in ins}, s["vals"]), c)
                     for c, s in self.shapes.items() if c in self.configs and set(s["pts"]) == set(self.pts)]
            start = self.shapes[min(cands)[1]] if cands else self.snap_shape()
            span = max([abs(c) for p in start["pts"].values() for c in p] + [1.0])
            rng = random.Random(1)
            self.ignore_locks, self.quick_fail = True, True
            tries = 8
            for t in range(tries):
                self.report_progress(f"Trying another starting shape ({t + 1} of {tries})", 0.5 + 0.5 * t / tries)
                self.put_shape(start)
                for k, v in self.pts.items():
                    if k:
                        v[0] += rng.uniform(-1, 1) * 0.02 * span * (t + 1) / tries
                        v[1] += rng.uniform(-1, 1) * 0.02 * span * (t + 1) / tries
                shaken = t + 1
                rep = self.solve()
                if bool(rep.ok) and not rep.conflicts:
                    ok = True
                    break
            self.quick_fail = False
            if ok:
                self.relock()
                self.shapes[self.configs[self.active]] = self.snap_shape()
            else:                                                # explain the failure once, from the nearest good shape
                self.report_progress("Looking for the conflicting constraint", 0.9)
                self.put_shape(start)
                self.solve()
            self.ignore_locks = False
        failed = []
        for k, j in enumerate(others):
            self.span = ((k + 1) / total, (k + 2) / total)
            self.report_progress(f"Configuration {k + 2} of {total}: {self.configs[j]}", 0.0)
            okj, _ = self.solve_config(j, settle=False, explain=False)
            if not okj:
                failed.append(self.configs[j])
        self.span = (0.0, 1.0)
        if others:
            self.report_progress("Finishing", 0.97)
            self.solve()
        self.progress = None
        rep = self.report
        return {"ok": ok and not rep.conflicts, "folded": folded, "shaken": shaken, "failed": failed, "report": rep}

    def local_rebuild(self, free_pts, free_cis=(), progress=None):
        """Rebuild only the chosen points / circles: everything else stays exactly where it is.
        The constraints that involve a chosen item are applied in full, so a dimension that needs a large jump is
        reached by walking its value from what it measures now to its target (continuation), and if that is not
        enough, from larger and larger random restarts of the chosen items only.  Locks on the chosen items are
        lifted for the solve and put back at their new place.  -> same dict as full_rebuild"""
        import random
        self.progress = progress
        self.span = (0.0, 1.0)
        free_pts = {p for p in free_pts if p in self.pts and p != 0}
        free_cis = {c for c in free_cis if c in self.cis}
        start = {"pts": {k: list(v) for k, v in self.pts.items()}, "cis": {k: v["r"] for k, v in self.cis.items()}}
        before = self.orientation()
        self.local = {"pts": free_pts, "cis": free_cis}
        self.ignore_locks, self.quick_fail = True, True
        self.value_override = {}
        ok, shaken, msgs, confl = False, 0, [], []
        try:
            self.report_progress("Solving the selected vertices", 0.0)
            rep = self.solve()
            ok = bool(rep.ok) and not rep.conflicts
            if not ok:                                           # continuation on every dimension that involves them
                self.update_values()
                probe = Solver(self)
                dims = [c for c in self.cons if c["type"] in DIMENSIONS and not c.get("driven") and probe.touches_free(c)]
                targets = {c["id"]: c["value"] for c in dims}
                for steps in (30, 120):
                    self.put_start(start)
                    starts = {}
                    for c in dims:
                        try:
                            starts[c["id"]] = self.measure(c["type"], c["refs"], c)
                        except Exception:
                            starts[c["id"]] = targets[c["id"]]
                    okw = True
                    for s_ in range(1, steps + 1):
                        t = s_ / steps
                        self.value_override = {cid: starts[cid] + (targets[cid] - starts[cid]) * t for cid in targets}
                        self.report_progress(f"Moving the dimensions gradually (step {s_} of {steps})", 0.1 + 0.3 * s_ / steps)
                        rep = self.solve()
                        if not (bool(rep.ok) and not rep.conflicts):
                            okw = False
                            break
                    self.value_override = {}
                    if okw:
                        rep = self.solve()
                        ok = bool(rep.ok) and not rep.conflicts
                    if ok:
                        break
            if not ok:                                           # random restarts of the chosen items only
                span = max([abs(c) for p in start["pts"].values() for c in p] + [1.0])
                rng = random.Random(7)
                tries = 40
                for t in range(tries):
                    self.report_progress(f"Trying another starting position ({t + 1} of {tries})", 0.45 + 0.5 * t / tries)
                    self.put_start(start)
                    rad = 0.02 * span + 0.35 * span * (t + 1) / tries
                    for k in free_pts:
                        self.pts[k][0] += rng.uniform(-1, 1) * rad
                        self.pts[k][1] += rng.uniform(-1, 1) * rad
                    shaken = t + 1
                    rep = self.solve()
                    if bool(rep.ok) and not rep.conflicts:
                        ok = True
                        break
        finally:
            self.value_override = {}
            self.quick_fail = False
        if not ok:                                               # explain once, then put everything back as it was
            self.report_progress("Looking for the conflicting constraint", 0.97)
            self.put_start(start)
            rep = self.solve()
            msgs, confl = list(rep.messages), list(rep.conflicts)
        self.local = None
        self.ignore_locks = False
        if ok:
            for p in free_pts:
                if p in self.lock_pts:
                    self.lock_pts[p] = list(self.pts[p])
            for c in free_cis:
                if c in self.lock_cis:
                    self.lock_cis[c] = self.cis[c]["r"]
        else:
            self.put_start(start)
        rep = self.solve()                                       # honest status for the whole sketch
        folded = ok and self.count_flips(before, self.orientation()) > 0
        if ok:
            self.record_shape()
            if folded:
                rep.messages.append("The shape may have folded over (a corner turned the other way). Check the drawing.")
        else:
            rep.messages = msgs + [m_ for m_ in rep.messages if m_ not in msgs]
            rep.conflicts, rep.ok = confl, False
        self.progress = None
        return {"ok": ok and not rep.conflicts, "folded": folded, "shaken": shaken, "failed": [], "report": rep}

    def put_start(self, start):
        for k, v in start["pts"].items():
            self.pts[k] = list(v)
        for k, r in start["cis"].items():
            self.cis[k]["r"] = r

    def wiggle_test(self, progress=None):
        """How can each free (blue, unlocked) point still move?  The directions come from the free motions of the
        constraint system; every one is then checked with a real drag (the way the mouse drags a point, with every
        constraint still applied), which also weeds out motions that exist only to first order.
        Works on this model only (call it on a copy).
        -> {"marks": {pid: {"kind": "line"|"free"|"arc", "dir": (x, y), "center": pid|None}}, "tested": n}"""
        import numpy as np
        self.progress = progress
        self.span = (0.0, 1.0)
        self.quick_fail = True               # a pull that cannot be satisfied just counts as no movement
        self.ignore_locks = True             # locks only pin the drawn position; they must not hide what the constraints leave free
        try:
            rep = self.solve()
            flagged = [p for p in sorted(rep.free_pts) if p != 0]
            cands = [p for p in flagged if p not in self.lock_pts]
            skipped = len(flagged) - len(cands)
            if not cands or rep.dof <= 0:
                return {"marks": {}, "tested": len(cands), "locked_skipped": skipped}
            base = {k: list(v) for k, v in self.pts.items()}
            base_r = {k: v["r"] for k, v in self.cis.items()}
            xs = [v[0] for v in base.values()] + [0.0]
            ys = [v[1] for v in base.values()] + [0.0]
            span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
            nb = {}
            for a, b in self.lns.values():
                nb.setdefault(a, set()).add(b)
                nb.setdefault(b, set()).add(a)
            for a in self.ars.values():
                nb.setdefault(a["s"], set()).add(a["c"])
                nb.setdefault(a["e"], set()).add(a["c"])
                nb.setdefault(a["c"], set()).update((a["s"], a["e"]))

            def put_back():
                for k, v in base.items():
                    self.pts[k] = list(v)
                for k, r in base_r.items():
                    self.cis[k]["r"] = r
            # 1. the free motions (null space of the constraint Jacobian)
            self.report_progress("Finding the free motions", 0.0)
            S = Solver(self)
            eqs = [e for e in S.equations([c for c in self.cons if not c.get("driven")])
                   if e[1]["type"] not in ("_pin", "_lock", "_lockr")]
            _, J = S.jacobian(eqs, S.x, central=True)
            _, _, Vt = np.linalg.svd(J if J.shape[0] else np.zeros((1, S.n)))
            N = Vt[S.n - rep.dof:]                                    # rep.dof free motions
            pre = {}
            for p in cands:
                i = S.pidx[p]
                A = N[:, i:i + 2]                                     # (motions x 2)
                U, sv, vt = np.linalg.svd(A, full_matrices=False)
                pre[p] = (sv, vt, U)
            top = max((float(v[0][0]) for v in pre.values()), default=0.0)
            marks = {}
            todo = [p for p in cands if pre[p][0][0] > 1e-3 * max(top, 1e-12)]
            for n, p in enumerate(todo):
                self.report_progress(f"Dragging vertex {n + 1} of {len(todo)}", (n + 1) / (len(todo) + 1))
                sv, vt, U = pre[p]
                d = (float(vt[0][0]), float(vt[0][1]))
                two_d = len(sv) > 1 and sv[1] >= 0.25 * sv[0]
                x0, y0 = base[p]
                lens = [math.hypot(base[q][0] - x0, base[q][1] - y0) for q in nb.get(p, ())]
                D = min(0.03 * span, 0.3 * sum(lens) / len(lens)) if lens else 0.03 * span
                D = max(D, 1e-3 * span)
                best = 0.0
                runs = []
                dirs = [d, (-d[1], d[0])] if two_d else [d]
                for ux, uy in dirs:
                    put_back()
                    self.solve(pin=(p, x0 + ux * D, y0 + uy * D))
                    mv = math.hypot(self.pts[p][0] - x0, self.pts[p][1] - y0)
                    best = max(best, mv)
                    runs.append((mv, {q: list(self.pts[q]) for q in nb.get(p, ())}, list(self.pts[p])))
                put_back()
                if best < 0.3 * D:
                    continue                                          # moves to first order only: not really free
                kind, centre = ("free" if two_d else "line"), None
                if not two_d:
                    w = U[:, 0]
                    mot = w @ N                                       # the free motion that moves this point most
                    for q in nb.get(p, ()):
                        vq = np.hypot(mot[S.pidx[q]], mot[S.pidx[q] + 1])
                        vp = np.hypot(mot[S.pidx[p]], mot[S.pidx[p] + 1])
                        r0 = math.hypot(base[q][0] - x0, base[q][1] - y0)
                        if r0 < 1e-9 or vq > 0.1 * vp:
                            continue                                  # the neighbour moves with it: a group slide
                        along = abs(d[0] * (x0 - base[q][0]) + d[1] * (y0 - base[q][1])) / r0
                        mv, qs, pos = runs[0]
                        if along < 0.05 and abs(math.hypot(pos[0] - qs[q][0], pos[1] - qs[q][1]) - r0) <= 0.01 * max(mv, 1e-12):
                            kind, centre = "arc", q
                            break
                marks[p] = {"kind": kind, "dir": d, "center": centre}
            put_back()
            return {"marks": marks, "tested": len(cands), "locked_skipped": skipped}
        finally:
            self.progress = None
            self.ignore_locks = False
            self.quick_fail = False

    def is_output(self, name, _seen=()):
        """An output symbol is solved from the others; defined symbols are outputs if they use one."""
        p = self.params.get(name)
        if p is None or name in _seen:
            return False
        if p.get("expr"):
            return any(self.is_output(s, _seen + (name,)) for s in expr_symbols(p["expr"]))
        return not p.get("input", True)

    def update_values(self):
        """Refresh each dimension's numeric value from its symbol expression, and mark driven dimensions."""
        vals = self.param_values()
        for c in self.cons:
            if c["type"] not in DIMENSIONS:
                continue
            if c["type"] == "dim_ang":
                try:
                    self.ensure_angle(c)
                except Exception:
                    pass
            e = c.get("expr")
            if not e:
                c["driven"] = False
                continue
            try:
                syms = expr_symbols(e)
                c["driven"] = any(self.is_output(x) for x in syms)
                v = safe_eval(e, vals)
                if not (isinstance(v, float) and math.isnan(v)):
                    c["value"] = v
            except (KeyError, ValueError, ZeroDivisionError, SyntaxError):
                c["driven"] = False
        for cid, v in self.value_override.items():
            c = self.con_by_id(cid)
            if c is not None and not c.get("driven"):
                c["value"] = v

    def refresh_driven(self):
        """After a solve: driven dimensions show what the geometry measures; output symbols take those values."""
        for c in self.cons:
            if c["type"] in DIMENSIONS and c.get("driven"):
                try:
                    v = self.measure(c["type"], c["refs"], c)
                except Exception:
                    continue
                e = c.get("expr", "")
                if e in self.params and not self.params[e].get("expr"):
                    self.params[e]["vals"][self.active] = v
                c["value"] = v

    def analyze_inputs(self, max_sets=12):
        return analyze_inputs(self, max_sets)

    # ----- solving ---------------------------------------------------------------------------
    def solve(self, pin=None):
        """Solve all constraints.  pin = (point_id, x, y) adds a soft pull used while dragging.
        Updates geometry in place and stores self.report."""
        self.update_values()
        rep = Solver(self).run(pin)
        self.refresh_driven()
        return rep

    # ----- construction / overhead symbols ----------------------------------------------------
    def construction_only(self):
        """(points, circles) that exist only as part of construction geometry.  Their freedom is not counted."""
        normal_pts, con_pts, con_cis = set(), set(), set()
        for k, tab in (("ln", self.lns), ("ci", self.cis), ("ar", self.ars)):
            for i in tab:
                if k == "ln":
                    ps = list(self.lns[i])
                elif k == "ci":
                    ps = [self.cis[i]["c"]]
                else:
                    ps = [self.ars[i]["c"], self.ars[i]["s"], self.ars[i]["e"]]
                if (k, i) in self.constr:
                    con_pts |= set(ps)
                    if k == "ci":
                        con_cis.add(i)
                else:
                    normal_pts |= set(ps)
        return con_pts - normal_pts - {0}, con_cis

    def geometry_symbols(self):
        """Symbols that reach the geometry: used by a dimension, or by a formula that is itself used."""
        used = set()
        for c in self.cons:
            if c["type"] in DIMENSIONS and c.get("expr"):
                used |= expr_symbols(c["expr"])
        changed = True
        while changed:
            changed = False
            for k, p in self.params.items():
                if k in used and p.get("expr"):
                    new = expr_symbols(p["expr"]) - used
                    if new:
                        used |= new
                        changed = True
        return used

    def overhead_symbols(self):
        """Declared symbols the geometry does not use - kept as inputs/results for later (e.g. the Excel sheet)."""
        used = self.geometry_symbols()
        return [k for k in self.params if k not in used]

    # ----- locking ----------------------------------------------------------------------------
    def _lock_targets(self, items):
        pts, cis = set(), set()
        for k, i in items:
            if k == "pt":
                pts.add(i)
            elif k == "ln":
                pts |= set(self.lns[i])
            elif k == "ci":
                cis.add(i)
                pts.add(self.cis[i]["c"])
            elif k == "ar":
                a = self.ars[i]
                pts |= {a["c"], a["s"], a["e"]}
        pts.discard(0)
        return pts, cis

    def lock(self, items):
        pts, cis = self._lock_targets(items)
        for p in pts:
            self.lock_pts[p] = list(self.pts[p])
        for c in cis:
            self.lock_cis[c] = self.cis[c]["r"]

    def unlock(self, items):
        pts, cis = self._lock_targets(items)
        for p in pts:
            self.lock_pts.pop(p, None)
        for c in cis:
            self.lock_cis.pop(c, None)

    def is_locked(self, kind, i):
        if kind == "pt":
            return i == 0 or i in self.lock_pts
        if kind == "ln":
            return all(self.is_locked("pt", p) for p in self.lns[i])
        if kind == "ci":
            return i in self.lock_cis and self.is_locked("pt", self.cis[i]["c"])
        if kind == "ar":
            a = self.ars[i]
            return all(self.is_locked("pt", a[k]) for k in ("c", "s", "e"))
        return False

    def residual(self):
        """Largest remaining constraint error (length units / radians) of the current geometry."""
        sv = Solver(self)
        eqs = [e for e in sv.equations([c for c in self.cons if not c.get("driven")])
               if e[1]["type"] not in ("_pin", "_lock", "_lockr")]
        worst = 0.0
        for e in eqs:
            r = np.atleast_1d(sv.eq_res(e[1], sv.x))
            if r.size:
                worst = max(worst, float(np.max(np.abs(r))))
        return worst

    def rebuild(self, tries=8):
        """Recompute everything from the constraints: symbol values, formulas, then solve again until nothing
        moves.  If the solver is stuck (conflict / wrong branch) retry from slightly shaken starting positions.
        Returns a dict with what happened."""
        import random
        before = {k: list(v) for k, v in self.pts.items()}
        before_r = {k: v["r"] for k, v in self.cis.items()}
        rep = self.solve()
        for _ in range(6):                                    # iterate until stable
            prev = {k: list(v) for k, v in self.pts.items()}
            rep = self.solve()
            if max((abs(self.pts[k][0] - v[0]) + abs(self.pts[k][1] - v[1]) for k, v in prev.items()), default=0) < 1e-10:
                break
        shaken = 0
        if rep.conflicts:
            span = max([abs(c) for p in self.pts.values() for c in p] + [1.0])
            rng = random.Random(1)
            for n in range(tries):
                for k, v in self.pts.items():
                    if k and k not in self.lock_pts:
                        v[0] += rng.uniform(-1, 1) * 0.02 * span * (n + 1) / tries
                        v[1] += rng.uniform(-1, 1) * 0.02 * span * (n + 1) / tries
                shaken = n + 1
                rep = self.solve()
                if not rep.conflicts:
                    break
            if rep.conflicts:                                  # give up: put the geometry back as it was
                for k, v in before.items():
                    self.pts[k] = v
                for k, r in before_r.items():
                    self.cis[k]["r"] = r
                rep = self.solve()
        moved = max((math.hypot(self.pts[k][0] - v[0], self.pts[k][1] - v[1]) for k, v in before.items()), default=0.0)
        return {"report": rep, "residual": self.residual(), "moved": moved, "shaken": shaken}


def symbol_kind(p):
    """'defined' (has a formula), 'input' (you supply it) or 'output' (solved from the others)."""
    return "defined" if p.get("expr") else ("input" if p.get("input", True) else "output")


class Report:
    def __init__(self):
        self.dof = 0
        self.ok = True
        self.conflicts = []      # constraint ids that cannot be satisfied
        self.redundant = []      # constraint ids that add nothing new
        self.free_pts = set()    # point ids not fully determined
        self.free_circles = set()
        self.dof_constr = 0      # freedom that exists only in construction geometry (not counted in dof)
        self.messages = []

    @property
    def status(self):
        if self.conflicts:
            return "CONFLICT"
        if self.dof == 0:
            return "Fully defined"
        return f"Under defined ({self.dof} DOF)"


class Solver:
    def __init__(self, m):
        self.m = m
        self.pidx = {}
        n = 0
        for pid in sorted(m.pts):
            self.pidx[pid] = n
            n += 2
        self.cidx = {}
        for cid in sorted(m.cis):
            self.cidx[cid] = n
            n += 1
        self.n = n
        self.x = np.zeros(n)
        for pid, i in self.pidx.items():
            self.x[i], self.x[i + 1] = m.pts[pid]
        for cid, i in self.cidx.items():
            self.x[i] = m.cis[cid]["r"]

    # ----- residual functions -------------------------------------------------------------
    def pt(self, x, pid):
        i = self.pidx[pid]
        return x[i], x[i + 1]

    def rad(self, x, kind, i):
        if kind == "ci":
            return x[self.cidx[i]]
        a = self.m.ars[i]
        cx, cy = self.pt(x, a["c"])
        sx, sy = self.pt(x, a["s"])
        return math.hypot(sx - cx, sy - cy)

    def cen(self, x, kind, i):
        d = self.m.cis if kind == "ci" else self.m.ars
        return self.pt(x, d[i]["c"])

    def ln(self, x, lid):
        a, b = self.m.lns[lid]
        return self.pt(x, a), self.pt(x, b)

    def unit(self, x, lid):
        (ax, ay), (bx, by) = self.ln(x, lid)
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) + 1e-12
        return dx / L, dy / L

    def dist_to_line(self, x, p, lid):
        (ax, ay), (bx, by) = self.ln(x, lid)
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) + 1e-12
        return ((p[0] - ax) * dy - (p[1] - ay) * dx) / L

    def two_pts(self, x, refs):
        if refs[0][0] == "ln":
            return self.ln(x, refs[0][1])
        return self.pt(x, refs[0][1]), self.pt(x, refs[1][1])

    def res(self, c, x):
        t, refs = c["type"], c["refs"]
        if t == "coincident":
            (k1, i1), (k2, i2) = refs
            if k1 == "pt" and k2 == "pt":
                a, b = self.pt(x, i1), self.pt(x, i2)
                return [a[0] - b[0], a[1] - b[1]]
            if k1 != "pt":
                (k1, i1), (k2, i2) = (k2, i2), (k1, i1)
            p = self.pt(x, i1)
            if k2 == "ln":
                return [self.dist_to_line(x, p, i2)]
            cx, cy = self.cen(x, k2, i2)
            return [math.hypot(p[0] - cx, p[1] - cy) - self.rad(x, k2, i2)]
        if t == "horizontal":
            a, b = self.two_pts(x, refs)
            return [a[1] - b[1]]
        if t == "vertical":
            a, b = self.two_pts(x, refs)
            return [a[0] - b[0]]
        if t in ("parallel", "perpendicular", "collinear"):
            u, v = self.unit(x, refs[0][1]), self.unit(x, refs[1][1])
            if t == "parallel":
                return [u[0] * v[1] - u[1] * v[0]]
            if t == "perpendicular":
                return [u[0] * v[0] + u[1] * v[1]]
            a2 = self.ln(x, refs[1][1])[0]
            return [u[0] * v[1] - u[1] * v[0], self.dist_to_line(x, a2, refs[0][1])]
        if t == "equal":                                  # any number of objects: all equal to the first
            if refs[0][0] == "ln":
                lens = []
                for _, i in refs:
                    (a, b) = self.ln(x, i)
                    lens.append(math.hypot(b[0] - a[0], b[1] - a[1]))
            else:
                lens = [self.rad(x, k, i) for k, i in refs]
            return [v - lens[0] for v in lens[1:]]
        if t == "concentric":
            a, b = self.cen(x, *refs[0]), self.cen(x, *refs[1])
            return [a[0] - b[0], a[1] - b[1]]
        if t == "tangent":
            ln_ref = refs[0] if refs[0][0] == "ln" else refs[1]
            ci_ref = refs[1] if refs[0][0] == "ln" else refs[0]
            cx = self.cen(x, *ci_ref)
            return [abs(self.dist_to_line(x, cx, ln_ref[1])) - self.rad(x, *ci_ref)]
        if t == "fixed":
            p = self.pt(x, refs[0][1])
            return [p[0] - c["xy"][0], p[1] - c["xy"][1]]
        if t == "midpoint":
            p = self.pt(x, refs[0][1])
            a, b = self.ln(x, refs[1][1])
            return [p[0] - (a[0] + b[0]) / 2, p[1] - (a[1] + b[1]) / 2]
        if t in ("rigid_pt", "rigid_len", "rigid_rad"):
            return self.rigid(c, x)
        if t == "proj_pt":
            return self.proj(c, x)
        # dimensions
        v = c["value"]
        if t == "dim_h":
            a, b = self.two_pts(x, refs)
            return [(b[0] - a[0]) * c.get("sign", 1) - v]
        if t == "dim_v":
            a, b = self.two_pts(x, refs)
            return [(b[1] - a[1]) * c.get("sign", 1) - v]
        if t == "dim_len":
            a, b = self.two_pts(x, refs)
            return [math.hypot(b[0] - a[0], b[1] - a[1]) - v]
        if t == "dim_rad":
            return [self.rad(x, *refs[0]) - v]
        if t == "dim_dia":
            return [2 * self.rad(x, *refs[0]) - v]
        if t == "dim_off":                                # the copy (refs[1]) is `value` away from its original (refs[0])
            (k1, i1), (k2, i2) = refs[0], refs[1]
            sv = c.get("sign", 1) * v
            al = c.get("align", ())
            if k1 == "ln":
                u = self.unit(x, i1)
                la, lb = self.m.lns[i1], self.m.lns[i2]
                tan = c.get("tan") or (None, None)
                out = []
                for k in (0, 1):                              # one row per end of the copy
                    p1 = self.pt(x, lb[k])
                    if tan[k] is not None and tan[k] in self.m.ars:
                        # the end is where the copy meets a copied arc tangentially: it is the foot of the arc's centre on the line
                        # (a point-on-line row would be degenerate there, a tangent point is only fixed to second order)
                        cc = self.cen(x, "ar", tan[k])
                        out.append((p1[0] - cc[0]) * u[0] + (p1[1] - cc[1]) * u[1])
                    else:
                        out.append(-self.dist_to_line(x, p1, i1) - sv)               # on the line `value` to the left of the original
                for k in al:                                  # an end with no neighbour stays straight across from the original's
                    q0, q1 = self.pt(x, la[k]), self.pt(x, lb[k])
                    out.append((q1[0] - q0[0]) * u[0] + (q1[1] - q0[1]) * u[1])
                return out
            c0, c1 = self.cen(x, k1, i1), self.cen(x, k2, i2)
            out = [self.rad(x, k2, i2) - self.rad(x, k1, i1) - sv, c1[0] - c0[0], c1[1] - c0[1]]
            if k1 == "ar":
                for k in al:
                    key = ("s", "e")[k]
                    a0, a1 = self.pt(x, self.m.ars[i1][key]), self.pt(x, self.m.ars[i2][key])
                    v0 = (a0[0] - c0[0], a0[1] - c0[1])
                    v1 = (a1[0] - c1[0], a1[1] - c1[1])
                    out.append((v0[0] * v1[1] - v0[1] * v1[0]) / ((math.hypot(*v0) * math.hypot(*v1)) or 1e-12))
            return out
        if t == "dim_ang":
            (a1, b1), (a2, b2) = self.ln(x, refs[0][1]), self.ln(x, refs[1][1])
            d1 = (b1[0] - a1[0], b1[1] - a1[1])
            d2 = (b2[0] - a2[0], b2[1] - a2[1])
            ang = math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])
            # the signed angle from line 1 to line 2 must equal  eps * value  (lines have no direction, so mod 180);
            # eps remembers on which side line 2 lies, which is what stops the sketch flipping into a mirror image
            dlt = ang - c.get("eps", 1) * math.radians(v)
            return [(dlt + math.pi / 2) % math.pi - math.pi / 2]
        raise ValueError(t)

    def proj(self, c, x):
        """A vertex (or circle centre) of a 3D placed part, projected into this assembly sketch: the point sits where the pose puts it.
        In a sketch's own solve the pose is a given (m.ctx3d); the joint solve of all assembly sketches (asm_solve.py) moves the poses."""
        ctx = self.m.ctx3d
        if ctx is None or c["part"] not in ctx["poses"]:
            return [0.0, 0.0]
        u, v = pose_math.project(ctx["poses"][c["part"]], c["q"], ctx["view"])
        px, py = self.pt(x, c["refs"][0][1])
        return [1e3 * (px - u / ctx["k"]), 1e3 * (py - v / ctx["k"])]        # stiff: a part's projection is rigid

    def rigid(self, c, x):
        """A placed part is one rigid body, held by two anchor points: B (the part's origin) and A (a second point at A_loc in the part's
        frame).  With d = A - B and a = A_loc (as complex numbers) every other point P of the part is  B + (loc_P / a) * d  - the part
        turned and moved but not stretched (|d| = |a| is its own row).  The body has 3 DOF: the two points minus that one distance."""
        ins = self.m.insts[c["inst"]]
        bx, by = self.pt(x, ins["B"])
        ax, ay = self.pt(x, ins["A"])
        d = complex(ax - bx, ay - by)
        a = complex(*ins["A_loc"])
        t = c["type"]
        if t == "rigid_len":
            return [abs(d) - abs(a)]
        if t == "rigid_rad":
            return [self.rad(x, "ci", c["refs"][0][1]) - ins["rad"][c["refs"][0][1]]]
        pid = c["refs"][0][1]                              # rigid_pt: the point sits where the rigid body puts it
        px, py = self.pt(x, pid)
        e = complex(bx, by) + complex(*ins["loc"][pid]) / a * d
        return [px - e.real, py - e.imag]

    def touched(self, c):
        """Variable indices a constraint depends on (keeps the Jacobian cheap)."""
        vi = []
        pids = set()
        for k, i in c["refs"]:
            if k == "pt":
                pids.add(i)
            elif k == "ln":
                pids |= set(self.m.lns[i])
            elif k == "ci":
                pids.add(self.m.cis[i]["c"])
                vi.append(self.cidx[i])
            elif k == "ar":
                a = self.m.ars[i]
                pids |= {a["c"], a["s"], a["e"]}
        for p in pids:
            vi += [self.pidx[p], self.pidx[p] + 1]
        return vi

    # ----- equation set -----------------------------------------------------------------------
    def equations(self, cons):
        """List of (owner_id, constraint_dict_or_special, touched_vars).  Arc rim consistency is internal."""
        eqs = []
        for aid, a in self.m.ars.items():
            if self.m.local and not (self.m.local["pts"] & {a["c"], a["s"], a["e"]}):
                continue
            eqs.append((None, {"type": "_arc", "arc": aid}, [self.pidx[a["c"]], self.pidx[a["c"]] + 1,
                                                              self.pidx[a["s"]], self.pidx[a["s"]] + 1,
                                                              self.pidx[a["e"]], self.pidx[a["e"]] + 1]))
        for pid, xy in ({} if self.m.ignore_locks else self.m.lock_pts).items():
            if pid in self.pidx:
                eqs.append((None, {"type": "_lock", "pid": pid, "xy": xy}, [self.pidx[pid], self.pidx[pid] + 1]))
        for cid, r in ({} if self.m.ignore_locks else self.m.lock_cis).items():
            if cid in self.cidx:
                eqs.append((None, {"type": "_lockr", "cid": cid, "r": r}, [self.cidx[cid]]))
        for c in cons:
            eqs.append((c["id"], c, self.touched(c)))
        if self.m.local:                                  # local rebuild: everything that may not move is pinned where it is
            owner = {}
            for pid, i in self.pidx.items():
                owner[i] = owner[i + 1] = ("pt", pid)
            for cid, i in self.cidx.items():
                owner[i] = ("ci", cid)
            seen = set()
            for _, _, vi in eqs:
                for j in vi:
                    k = owner.get(j)
                    if k is None or k in seen or not self.is_pinned(k):
                        continue
                    seen.add(k)
                    if k[0] == "pt":
                        eqs.append((None, {"type": "_lock", "pid": k[1], "xy": list(self.m.pts[k[1]])},
                                    [self.pidx[k[1]], self.pidx[k[1]] + 1]))
                    else:
                        eqs.append((None, {"type": "_lockr", "cid": k[1], "r": self.m.cis[k[1]]["r"]}, [self.cidx[k[1]]]))
        return eqs

    def is_pinned(self, key):
        loc = self.m.local
        return bool(loc) and key[1] not in (loc["pts"] if key[0] == "pt" else loc["cis"])

    def touches_free(self, c):
        """Does this constraint involve anything that may move in a local rebuild?"""
        loc = self.m.local
        for k, i in c["refs"]:
            if k == "pt" and i in loc["pts"]:
                return True
            if k == "ln" and loc["pts"] & set(self.m.lns[i]):
                return True
            if k == "ci" and (i in loc["cis"] or self.m.cis[i]["c"] in loc["pts"]):
                return True
            if k == "ar" and loc["pts"] & {self.m.ars[i]["c"], self.m.ars[i]["s"], self.m.ars[i]["e"]}:
                return True
        return False

    def eq_res(self, c, x):
        if c["type"] == "_arc":
            a = self.m.ars[c["arc"]]
            cx, cy = self.pt(x, a["c"])
            sx, sy = self.pt(x, a["s"])
            ex, ey = self.pt(x, a["e"])
            return [math.hypot(sx - cx, sy - cy) - math.hypot(ex - cx, ey - cy)]
        if c["type"] == "_lock":
            p = self.pt(x, c["pid"])
            return [p[0] - c["xy"][0], p[1] - c["xy"][1]]
        if c["type"] == "_lockr":
            return [x[self.cidx[c["cid"]]] - c["r"]]
        if c["type"] == "_pin":
            p = self.pt(x, c["pid"])
            return [0.05 * (p[0] - c["xy"][0]), 0.05 * (p[1] - c["xy"][1])]   # weak pull: constraints win
        return self.res(c, x)

    def residual(self, eqs, x):
        out = []
        for _, c, _ in eqs:
            out.extend(self.eq_res(c, x))
        return np.array(out, dtype=float)

    def jacobian(self, eqs, x, rows=None, central=False):
        """Numeric Jacobian.  central=True is slower but accurate enough to tell real freedom from noise."""
        if central:
            return self.residual(eqs, x), self.jacobian_central(eqs, x)
        r0 = self.residual(eqs, x)
        m = len(r0)
        J = np.zeros((m, self.n))
        row = 0
        for _, c, vi in eqs:
            k = len(self.eq_res(c, x))
            base = r0[row:row + k]
            for j in vi:
                old = x[j]
                h = 1e-7 * max(1.0, abs(old))
                x[j] = old + h
                J[row:row + k, j] = (np.array(self.eq_res(c, x)) - base) / h
                x[j] = old
            row += k
        J[np.abs(J) < 1e-8] = 0.0   # finite-difference noise would otherwise be amplified by the solver
        return r0, J

    def jacobian_central(self, eqs, x, h=1e-6):
        r0 = self.residual(eqs, x)
        J = np.zeros((len(r0), self.n))
        row = 0
        for _, c, vi in eqs:
            k = len(self.eq_res(c, x))
            for j in vi:
                old = x[j]
                hh = h * max(1.0, abs(old))
                x[j] = old + hh
                rp = np.array(self.eq_res(c, x), dtype=float)
                x[j] = old - hh
                rm = np.array(self.eq_res(c, x), dtype=float)
                x[j] = old
                J[row:row + k, j] = (rp - rm) / (2 * hh)
            row += k
        J[np.abs(J) < 1e-9] = 0.0
        return J

    def lm(self, eqs, x, soft=()):
        """Damped least squares.  soft: when truthy, the drag pull ('_pin') may stay unsatisfied."""
        x = x.copy()
        lam = 1e-3
        r = self.residual(eqs, x)
        cost = r @ r
        cc = getattr(self.m, "cancel_check", None)
        for _ in range(300):
            if cc and cc():
                raise Cancelled()
            if not soft and self.hard_max(eqs, x, soft) < 1e-10:
                break
            _, J = self.jacobian(eqs, x)
            A = J.T @ J
            g = J.T @ r
            if len(g) and np.max(np.abs(g)) < 1e-12:
                break
            d = np.maximum(np.diag(A), 1.0)
            improved = False
            for _ in range(30):
                try:
                    step = np.linalg.solve(A + lam * np.diag(d), -g)
                except np.linalg.LinAlgError:
                    lam *= 10
                    continue
                xn = x + step
                rn = self.residual(eqs, xn)
                cn = rn @ rn
                if cn < cost:
                    stag = (cost - cn) < 1e-16 * max(cost, 1e-30)
                    x, r, cost = xn, rn, cn
                    lam = max(lam / 3, 1e-12)
                    improved = True
                    if stag:
                        return x, self.hard_max(eqs, x, soft) < TOL
                    break
                lam *= 4
            if not improved:
                break
        return x, self.hard_max(eqs, x, soft) < TOL

    def hard_max(self, eqs, x, soft):
        """Largest residual among the real constraints (the drag pull is ignored when soft)."""
        mx = 0.0
        for _, c, _ in eqs:
            if soft and c["type"] == "_pin":
                continue
            v = self.eq_res(c, x)
            if v:
                mx = max(mx, max(abs(t) for t in v))
        return mx

    # ----- main entry ---------------------------------------------------------------------------
    def run(self, pin=None):
        m = self.m
        rep = Report()
        cons = [c for c in m.cons if not c.get("driven")]
        if m.local:
            cons = [c for c in cons if self.touches_free(c)]
        eqs = self.equations(cons)
        x0 = self.x
        if pin:
            pid, px, py = pin
            pull = (None, {"type": "_pin", "pid": pid, "xy": (px, py)}, [self.pidx[pid], self.pidx[pid] + 1])
            x0, _ = self.lm(eqs + [pull], self.x, soft=True)     # drift towards the mouse ...
        x, ok = self.lm(eqs, x0)                                   # ... then satisfy the real constraints exactly
        if not ok and pin:
            x, ok = self.lm(eqs, self.x)
        if not ok and getattr(m, "quick_fail", False):             # caller will retry / explain: skip the slow conflict search
            rep.ok = False
            rep.messages.append("Did not converge.")
            m.report = rep
            return rep
        if not ok:
            # find which constraints fight the earlier ones: add them one at a time in creation order
            good = []
            xs = self.x.copy()
            base = self.equations([])
            xs, _ = self.lm(base, xs)
            for c in cons:
                trial = self.equations(good + [c])
                xt, okt = self.lm(trial, xs)
                if okt:
                    good.append(c)
                    xs = xt
                else:
                    rep.conflicts.append(c["id"])
            x = xs
            eqs = self.equations(good)
            rep.ok = False
            for cid in rep.conflicts:
                rep.messages.append("Conflict: " + m.describe(m.con_by_id(cid)) +
                                    " cannot be satisfied together with the constraints before it" +
                                    ((" and the points you did not select, which are held in place (select more points around it)." if m.local else
                                     " and the locked geometry (unlock it, or lock less)." if m.lock_pts or m.lock_cis else ".")))
        # write back
        for pid, i in self.pidx.items():
            m.pts[pid] = [float(x[i]), float(x[i + 1])]
        for cid, i in self.cidx.items():
            m.cis[cid]["r"] = float(x[i])
        self.x = x
        # degrees of freedom from the Jacobian of the satisfied equations (without the drag pull)
        eqs_nopin = [e for e in eqs if e[1]["type"] not in ("_pin", "_lock", "_lockr")]
        _, J = self.jacobian(eqs_nopin, x, central=True)
        if J.shape[0]:
            sv = np.linalg.svd(J, compute_uv=False)
            rank = int(np.sum(sv > 1e-6 * max(sv[0], 1.0)))
        else:
            rank = 0
        rep.dof = self.n - rank
        cpts, ccis = m.construction_only()
        if self.n:
            _, s, vt = np.linalg.svd(J if J.shape[0] else np.zeros((1, self.n)))
            nullity = vt[rank:] if rank < vt.shape[0] else np.zeros((0, self.n))
            free = np.any(np.abs(nullity) > 1e-5, axis=0) if len(nullity) else np.zeros(self.n, bool)
            rep.free_pts = {pid for pid, i in self.pidx.items() if (free[i] or free[i + 1]) and pid not in cpts}
            rep.free_circles = {cid for cid, i in self.cidx.items() if free[i] and cid not in ccis}
            if (cpts or ccis) and len(nullity):
                keep = np.ones(self.n, bool)
                for pid in cpts:
                    keep[self.pidx[pid]:self.pidx[pid] + 2] = False
                for cid in ccis:
                    keep[self.cidx[cid]] = False
                sub = nullity[:, keep]
                rel = int(np.linalg.matrix_rank(sub, tol=1e-6)) if sub.size else 0
                rep.dof_constr = rep.dof - rel
                rep.dof = rel
        # redundant constraints: a constraint whose rows add nothing to the rows before it.  One incremental pass
        # (orthogonalise each new row against the rows kept so far) instead of re-factoring a growing matrix.
        user_eqs = [e for e in eqs_nopin if e[0] is not None]
        if user_eqs and J.shape[0] > rank:
            ks = [len(self.eq_res(e[1], x)) for e in eqs_nopin]
            off = np.concatenate([[0], np.cumsum(ks)])
            tol = 1e-6 * max(float(sv[0]) if len(sv) else 1.0, 1.0)
            Q = np.zeros((0, self.n))
            for i, e in enumerate(eqs_nopin):
                gain = 0
                for r in J[off[i]:off[i + 1]]:
                    v = r - Q.T @ (Q @ r)
                    v = v - Q.T @ (Q @ v)                       # second pass keeps the basis orthogonal
                    nv = float(np.linalg.norm(v))
                    if nv > tol:
                        Q = np.vstack([Q, v / nv])
                        gain += 1
                if e[0] is not None and ks[i] and gain == 0:
                    rep.redundant.append(e[0])
                    rep.messages.append("Redundant: " + m.describe(m.con_by_id(e[0])) +
                                        " does not add anything new (already implied).")
        m.report = rep
        return rep


# =====================================================================================================
#  Input analysis ("pre-solver" step 1): how many inputs does this sketch need, and which sets work?
# =====================================================================================================
def off_value_rows(m, c, nrows):
    """For an offset dimension: which of its residual rows contain the distance (1) and which do not (0)."""
    (k1, _), _ = c["refs"][0], c["refs"][1]
    if k1 == "ln":
        tan = c.get("tan") or (None, None)
        rows = [0 if (tan[k] is not None and tan[k] in m.ars) else 1 for k in (0, 1)]
    else:
        rows = [1, 0, 0]
    return (rows + [0] * nrows)[:nrows]


def analyze_inputs(m, max_sets=12):
    m.update_values()
    S = Solver(m)
    eqs = [e for e in S.equations(list(m.cons)) if e[1]["type"] not in ("_lock", "_lockr")]   # every constraint, driven dimensions included
    r0, Jx = S.jacobian(eqs, S.x.copy(), central=True)
    owners, coefs = [], []
    for _, c, _ in eqs:
        nr = len(S.eq_res(c, S.x))
        owners += [c] * nr
        coefs += off_value_rows(m, c, nr) if c.get("type") == "dim_off" else [1] * nr
    used = m.geometry_symbols()                          # overhead symbols never need to be inputs of the geometry
    pnames = [k for k, p in m.params.items() if not p.get("expr") and k in used]
    nx, nP = Jx.shape[1], len(pnames)
    Jp = np.zeros((len(owners), nP))
    v0 = {}
    for ri, c in enumerate(owners):
        if c.get("type") in DIMENSIONS and c.get("expr") and coefs[ri]:
            v0[ri] = safe_eval(c["expr"], m.param_values())
    for j, pn in enumerate(pnames):
        vals = m.params[pn]["vals"]
        old = vals[m.active]
        h = 1e-6 * max(1.0, abs(old))
        vals[m.active] = old + h
        pv = m.param_values()
        vals[m.active] = old - h
        pm = m.param_values()
        vals[m.active] = old
        for ri, c in enumerate(owners):
            if ri in v0:
                dv = (safe_eval(c["expr"], pv) - safe_eval(c["expr"], pm)) / (2 * h)
                Jp[ri, j] = -dv * (c.get("eps", 1) * math.pi / 180 if c["type"] == "dim_ang" else
                                   c.get("sign", 1) if c["type"] == "dim_off" else 1.0)
    J = np.hstack([Jx, Jp]) if len(owners) else np.zeros((1, nx + nP))
    n = nx + nP
    sv = np.linalg.svd(J, compute_uv=False)
    rank = int(np.sum(sv > 1e-7 * max(sv[0], 1.0))) if len(sv) else 0
    _, _, Vt = np.linalg.svd(J)
    null = Vt[rank:].T if Vt.shape[0] > rank else np.zeros((n, 0))
    cpts, ccis = m.construction_only()
    relx = np.ones(nx, bool)                              # construction-only freedom does not need an input
    for pid in cpts:
        relx[S.pidx[pid]:S.pidx[pid] + 2] = False
    for cid in ccis:
        relx[S.cidx[cid]] = False
    Nfull = null
    Nx_rel = Nfull[:nx][relx] if nx else np.zeros((0, Nfull.shape[1]))
    k = int(np.linalg.matrix_rank(np.vstack([Nx_rel, Nfull[nx:]]), tol=1e-7)) if Nfull.shape[1] else 0
    out = {"k": k, "params": pnames, "current": [p for p in pnames if m.params[p].get("input", True)],
           "free_geometry": False, "free_points": [], "sets": [], "current_ok": False}
    # points that can still move even with every symbol held fixed (nothing controls them)
    if nx:
        svx = np.linalg.svd(Jx, compute_uv=False) if Jx.shape[0] else np.array([0.0])
        rx = int(np.sum(svx > 1e-7 * max(svx[0], 1.0)))
        _, _, Vx = np.linalg.svd(Jx if Jx.shape[0] else np.zeros((1, nx)))
        nullx = Vx[rx:]
        if len(nullx):
            free = np.any(np.abs(nullx) > 1e-5, axis=0)
            out["free_points"] = sorted(pid for pid, i in S.pidx.items() if (free[i] or free[i + 1]) and pid not in cpts)
    if k == 0:
        out["sets"] = [[]]
        out["current_ok"] = len(out["current"]) == 0
        return out
    Np = null[nx:, :]
    if nP == 0 or np.linalg.matrix_rank(Np, tol=1e-7) < k:
        out["free_geometry"] = True
        return out

    def valid(idx):
        if len(idx) != k:
            return False
        sub = Np[list(idx), :]
        if np.linalg.matrix_rank(sub, tol=1e-6) != k:
            return False
        return np.linalg.matrix_rank(np.vstack([sub, Nx_rel]), tol=1e-6) == k
    cur_idx = {pnames.index(p) for p in out["current"]}
    order = sorted(range(nP), key=lambda i: (i not in cur_idx, i))
    sets, checked = [], 0
    for combo in itertools.combinations(order, k):
        checked += 1
        if checked > 4000:
            break
        if valid(combo):
            sets.append([pnames[i] for i in combo])
            if len(sets) >= max_sets:
                break
    out["sets"] = sets
    out["current_ok"] = len(out["current"]) == k and valid([pnames.index(p) for p in out["current"]])
    return out
