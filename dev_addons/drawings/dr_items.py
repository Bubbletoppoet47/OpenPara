"""dr_items.py - what is drawn on the sheet itself (no Qt here): notes (text, with a leader if wanted), balloons (a number in a circle, with a leader to a view) and plain drawing items
(line, rectangle, circle, arc: no constraints, just where they were put).  The geometry, the shapes the renderer paints and the canvas picks, the handles a person drags.

    A note:    {"id": "n1", "type": "note", "text": "...", "pos": [x, y] (the top-left corner of the text, sheet mm, y up), "size": points,
                "leader": None | {"kind": "straight" | "bent", "view": vid | None, "p": [x, y]},
                "pattern": None | {"a1", "s1", "c1", "a2", "s2", "c2"}}     a linear pattern: c1 notes (the note itself is the first) s1 mm apart along the direction a1 (degrees,
                                                                         0 = to the right, counter-clockwise), and c2 rows of them s2 mm apart along a2; every copy has its own copy of the leader
               the tip of the leader is a point in the frame of a view (so it follows the view when the view moves or changes scale), or a point of the sheet (view None)
    A balloon: {"id": "b1", "type": "balloon", "text": "1", "view": vid, "tip": [x, y] (in the view's frame), "snap": bool (the tip is on an edge: an arrow; else a dot),
                "pos": [x, y] (the middle of the circle, sheet mm)}
    An item:   {"id": "l1", "type": "line" | "rect" | "circle" | "arc", ...} in sheet mm:  line "p": [[x, y], [x, y]];  rect "p": [[xmin, ymin], [xmax, ymax]];  circle "c", "r";
               arc "c", "r", "a0", "a1" (counter-clockwise from a0 to a1, radians, a1 - a0 in (0, 2 pi])

    note_shape(n, tip, metrics) / balloon_shape(b, tip, metrics) / item_shape(it)     what is painted: "segs" (polylines), "heads" [(tip, direction away from the tip along the line, size)],
        "dots" [(point, radius)], "lines" [(text, (x, baseline y))], "size" (points), "box" (all of it), "boxes" (one for each copy of a note), "circle" (c, r), "arc" (c, r, a0, a1), "kind"
    distance(shape, p)                  how far a point is from it (0 on a note's text, inside a balloon)
    handles(item) / drag_handle(item, name, p) / translate(item, dx, dy)
    Metrics(size, width, cap, pitch)    how big text is (the renderer measures it with the real font; without one a plain estimate is used)
"""
import math

import dr_annot as A

TAU = 2.0 * math.pi
PT = 25.4 / 72.0                    # one point in mm
NOTE_SIZE = 14.0                    # points: the same height as the numbers of a dimension
NOTE_SIZES = (8, 10, 12, 14, 18, 24, 36)
BALLOON_SIZE = 14.0
LEAD_GAP = 1.2                      # the leader stops this far from the text
LAND = 6.0                          # the length of the level part of a bent leader
BALLOON_R = 4.5                     # the smallest balloon (mm); a longer number makes it bigger
BALLOON_PAD = 1.4
DOT_R = 0.8                         # the dot at the end of a leader that ends on a face
DRAW_W = 0.35                       # the weight of the lines that are drawn on the sheet (mm)
DRAW_TYPES = ("line", "rect", "circle", "arc")
MIN_R = 0.05
MAX_COPIES = 400                    # a pattern of notes is at most this many
MIN_SPACING = 0.1


# ---------------------------------------------------------------------------------------------------------------------------- text metrics
class Metrics:
    """How big text of a size (points) is, in mm: width(line), cap (a capital's height), pitch (one line to the next)."""

    def __init__(self, size, width=None, cap=None, pitch=None):
        em = size * PT
        self.size = size
        self.em = em
        self.cap = cap if cap is not None else 0.72 * em
        self.pitch = pitch if pitch is not None else 1.3 * em
        self._w = width

    def width(self, line):
        return self._w(line) if self._w is not None else 0.55 * self.em * len(line)


def default_metrics(size):
    return Metrics(size)


def _hyp(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(a, b):
    """The direction from a to b (a unit vector); (1, 0) when they are the same point."""
    d = math.hypot(b[0] - a[0], b[1] - a[1])
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d > 1e-12 else (1.0, 0.0)


# ---------------------------------------------------------------------------------------------------------------------------- making the records
def clean_size(size):
    try:
        s = float(size)
    except (TypeError, ValueError):
        return NOTE_SIZE
    return min(200.0, max(2.0, s)) if s == s else NOTE_SIZE


def new_note(text, pos, size=NOTE_SIZE, leader=None):
    n = {"type": "note", "text": str(text), "pos": [float(pos[0]), float(pos[1])], "size": clean_size(size), "leader": None}
    if leader:
        n["leader"] = {"kind": "bent" if leader.get("kind") == "bent" else "straight", "view": leader.get("view"), "p": [float(leader["p"][0]), float(leader["p"][1])]}
    return n


def new_balloon(text, view, tip, pos, snap=True):
    return {"type": "balloon", "text": str(text), "view": view, "tip": [float(tip[0]), float(tip[1])], "snap": bool(snap), "pos": [float(pos[0]), float(pos[1])]}


def new_item(kind, **g):
    """A drawing item from what was clicked: line (a, b), rect (a, b: opposite corners), circle (c, through: a point of the circle), arc (c, start, end); None when there is nothing to draw."""
    if kind == "line":
        a, b = g["a"], g["b"]
        return {"type": "line", "p": [[float(a[0]), float(a[1])], [float(b[0]), float(b[1])]]} if _hyp(a, b) > 1e-6 else None
    if kind == "rect":
        a, b = g["a"], g["b"]
        x0, x1, y0, y1 = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
        return {"type": "rect", "p": [[float(x0), float(y0)], [float(x1), float(y1)]]} if x1 - x0 > 1e-6 and y1 - y0 > 1e-6 else None
    if kind == "circle":
        r = _hyp(g["c"], g["through"])
        return {"type": "circle", "c": [float(g["c"][0]), float(g["c"][1])], "r": float(r)} if r > MIN_R else None
    if kind == "arc":
        c, s, e = g["c"], g["start"], g["end"]
        r = _hyp(c, s)
        if r <= MIN_R or _hyp(c, e) <= 1e-9:
            return None
        a0 = math.atan2(s[1] - c[1], s[0] - c[0])
        sweep = (math.atan2(e[1] - c[1], e[0] - c[0]) - a0) % TAU
        if sweep < 1e-3:
            return None
        return {"type": "arc", "c": [float(c[0]), float(c[1])], "r": float(r), "a0": float(a0), "a1": float(a0 + sweep)}
    return None


def valid(it):
    """True when a record read from a file has everything a note / balloon / drawing item needs (a damaged file must not break the window)."""
    try:
        if not isinstance(it.get("id"), str):
            return False
        t = it.get("type")
        pt = lambda q: (float(q[0]), float(q[1]))
        if t == "note":
            pt(it["pos"])
            str(it["text"])
            ld = it.get("leader")
            if ld:
                pt(ld["p"])
                if ld.get("kind") not in ("straight", "bent"):
                    return False
            return True
        if t == "balloon":
            pt(it["pos"])
            pt(it["tip"])
            return isinstance(it.get("view"), str)
        if t in ("line", "rect"):
            pt(it["p"][0])
            pt(it["p"][1])
            return True
        if t == "circle":
            pt(it["c"])
            return float(it["r"]) > 0
        if t == "arc":
            pt(it["c"])
            return float(it["r"]) > 0 and float(it["a1"]) > float(it["a0"])
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return False
    return False


# ---------------------------------------------------------------------------------------------------------------------------- linear note patterns
def pattern_offsets(pat):
    """Where the copies of a note are, relative to the note itself: [(dx, dy)], the note's own (0, 0) first, then along direction 1, then the next row."""
    a1, a2 = math.radians(pat["a1"]), math.radians(pat["a2"])
    u1, u2 = (math.cos(a1), math.sin(a1)), (math.cos(a2), math.sin(a2))
    return [(i * pat["s1"] * u1[0] + j * pat["s2"] * u2[0], i * pat["s1"] * u1[1] + j * pat["s2"] * u2[1]) for j in range(pat["c2"]) for i in range(pat["c1"])]


def default_pattern(box):
    """A first pattern for a note whose text fills `box`: three copies in a row, each a little way from the next."""
    return {"a1": 0.0, "s1": round(box[2] - box[0] + 5.0, 1), "c1": 3, "a2": 90.0, "s2": round(box[3] - box[1] + 3.0, 1), "c2": 1}


def clean_pattern(pat):
    """The pattern with every number in range: ValueError (in plain words) when it cannot be made one."""
    try:
        out = {"a1": float(pat["a1"]) % 360.0, "s1": float(pat["s1"]), "c1": int(pat["c1"]), "a2": float(pat["a2"]) % 360.0, "s2": float(pat["s2"]), "c2": int(pat["c2"])}
    except (KeyError, TypeError, ValueError):
        raise ValueError("A pattern needs a direction, a spacing and a number of notes for each direction.")
    if any(v != v or abs(v) == float("inf") for v in out.values()):
        raise ValueError("A pattern needs a direction, a spacing and a number of notes for each direction.")
    if out["c1"] < 1 or out["c2"] < 1:
        raise ValueError("A pattern has at least one note in each direction (the note itself).")
    if out["c1"] * out["c2"] > MAX_COPIES:
        raise ValueError(f"A pattern is at most {MAX_COPIES} notes.")
    for k in (("s1", "c1"), ("s2", "c2")):
        if out[k[1]] > 1 and abs(out[k[0]]) < MIN_SPACING:
            raise ValueError(f"The spacing must be at least {MIN_SPACING} mm.")
    return out


# ---------------------------------------------------------------------------------------------------------------------------- shapes
def _empty(kind, **kw):
    out = {"kind": kind, "segs": [], "heads": [], "dots": [], "lines": [], "size": 0.0, "box": None, "boxes": [], "circle": None, "arc": None}
    out.update(kw)
    return out


def note_shape(n, tip, mt=default_metrics):
    """The text of a note (the first line's capitals begin at the top-left corner) and its leader to `tip` (a sheet point, or None)."""
    m = mt(clean_size(n.get("size", NOTE_SIZE)))
    lines = str(n.get("text", "")).split("\n")
    x, y = n["pos"]
    w = max(m.width(t) for t in lines)
    h = m.cap + (len(lines) - 1) * m.pitch
    box = (x, y - h, x + w, y)
    out = _empty("note", size=m.size, box=box, boxes=[box], lines=[(t, (x, y - m.cap - i * m.pitch)) for i, t in enumerate(lines)])
    ld = n.get("leader")
    if tip is not None and ld:
        _leader(out, box, tip, ld)
    pat = n.get("pattern")
    if pat:
        try:
            offs = pattern_offsets(clean_pattern(pat))[1:]
        except ValueError:
            offs = []
        base = {k: list(v) if isinstance(v, list) else v for k, v in out.items()}      # the note as it is alone: every copy is made from this
        for dx, dy in offs:
            out["boxes"].append((box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))
            out["lines"] += [(t, (q[0] + dx, q[1] + dy)) for t, q in base["lines"]]
            out["segs"] += [[(q[0] + dx, q[1] + dy) for q in sg] for sg in base["segs"]]
            out["heads"] += [((tp[0] + dx, tp[1] + dy), d, sz) for tp, d, sz in base["heads"]]
        if offs:
            out["box"] = (min(b[0] for b in out["boxes"]), min(b[1] for b in out["boxes"]), max(b[2] for b in out["boxes"]), max(b[3] for b in out["boxes"]))
    return out


def _leader(out, box, tip, ld):
    """The leader of a note into `out`: the lines and the arrow."""
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    left, right = (box[0] - LEAD_GAP, cy), (box[2] + LEAD_GAP, cy)
    bent = ld.get("kind") == "bent"
    cands = [left, right] if bent else [left, right, (cx, box[3] + LEAD_GAP), (cx, box[1] - LEAD_GAP)]
    a = min(cands, key=lambda c: _hyp(c, tip))
    pts = [tuple(tip), a]
    if bent:
        side = -1.0 if a is left else 1.0                       # the level part goes on away from the text, towards the tip
        land = min(LAND, abs(a[0] - tip[0]) / 2.0) if (tip[0] - a[0]) * side > 0 else 0.0      # a tip on the wrong side of the text gets no level part
        if land > 1e-6:
            pts = [tuple(tip), (a[0] + side * land, cy), a]
    out["segs"].append(pts)
    L = _hyp(pts[0], pts[1])
    if L > 1e-6:
        out["heads"].append((pts[0], _unit(pts[0], pts[1]), min(A.ARROW, 0.45 * L)))


def balloon_shape(b, tip, mt=default_metrics):
    m = mt(BALLOON_SIZE)
    text = str(b.get("text", ""))
    w = m.width(text)
    r = max(BALLOON_R, w / 2.0 + BALLOON_PAD)
    c = (float(b["pos"][0]), float(b["pos"][1]))
    out = _empty("balloon", size=m.size, box=(c[0] - r, c[1] - r, c[0] + r, c[1] + r), circle=(c, r), lines=[(text, (c[0] - w / 2.0, c[1] - m.cap / 2.0))])
    if tip is not None:
        L = _hyp(c, tip)
        if L > r + 0.3:
            u = ((tip[0] - c[0]) / L, (tip[1] - c[1]) / L)
            out["segs"].append([(c[0] + u[0] * r, c[1] + u[1] * r), tuple(tip)])
            if b.get("snap", True):
                out["heads"].append((tuple(tip), (-u[0], -u[1]), min(A.ARROW, 0.5 * (L - r))))
            else:
                out["dots"].append((tuple(tip), DOT_R))
    return out


def _arc_pts(c, r, a0, a1, step_deg=3.75):
    n = max(2, int(math.ceil(math.degrees(abs(a1 - a0)) / step_deg)))
    return [(c[0] + r * math.cos(a0 + (a1 - a0) * k / n), c[1] + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def item_shape(it):
    t = it["type"]
    if t == "line":
        return _empty("line", segs=[[tuple(it["p"][0]), tuple(it["p"][1])]])
    if t == "rect":
        (x0, y0), (x1, y1) = it["p"]
        return _empty("rect", segs=[[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]], box=(x0, y0, x1, y1))
    if t == "circle":
        c, r = tuple(it["c"]), float(it["r"])
        return _empty("circle", segs=[_arc_pts(c, r, 0.0, TAU)], circle=(c, r), box=(c[0] - r, c[1] - r, c[0] + r, c[1] + r))
    if t == "arc":
        c, r = tuple(it["c"]), float(it["r"])
        return _empty("arc", segs=[_arc_pts(c, r, it["a0"], it["a1"])], arc=(c, r, it["a0"], it["a1"]))
    raise ValueError(f"unknown item {t}")


def distance(shp, p):
    """How far p is from what the shape draws (sheet mm): the lines, the outline of a circle, and 0 on the text of a note or inside a balloon."""
    kind = shp["kind"]
    if kind == "circle":                                           # exactly: the polygon the shape also carries is only an estimate of it
        c, r = shp["circle"]
        return abs(_hyp(c, p) - r)
    best = 1e9
    for sg in shp["segs"]:
        for i in range(len(sg) - 1):
            best = min(best, A._seg_dist(p, sg[i], sg[i + 1]))
    if kind == "note":
        for x0, y0, x1, y1 in shp["boxes"]:
            best = min(best, math.hypot(max(x0 - p[0], 0.0, p[0] - x1), max(y0 - p[1], 0.0, p[1] - y1)))
    elif kind == "balloon":
        c, r = shp["circle"]
        best = min(best, max(0.0, _hyp(c, p) - r))
    return best


# ---------------------------------------------------------------------------------------------------------------------------- moving and dragging
def translate(it, dx, dy):
    """Moves a note, a balloon (the circle, not the tip) or a drawing item."""
    t = it["type"]
    if t in ("note", "balloon"):
        it["pos"] = [it["pos"][0] + dx, it["pos"][1] + dy]
    elif t in ("line", "rect"):
        it["p"] = [[q[0] + dx, q[1] + dy] for q in it["p"]]
    else:
        it["c"] = [it["c"][0] + dx, it["c"][1] + dy]


def handles(it):
    """The points of a drawing item that can be dragged: [(name, (x, y))].  The first one moves the whole item when it has a centre."""
    t = it["type"]
    if t == "line":
        return [("a", tuple(it["p"][0])), ("b", tuple(it["p"][1]))]
    if t == "rect":
        (x0, y0), (x1, y1) = it["p"]
        return [("c0", (x0, y0)), ("c1", (x1, y0)), ("c2", (x1, y1)), ("c3", (x0, y1))]
    if t == "circle":
        c, r = it["c"], it["r"]
        return [("c", tuple(c)), ("r", (c[0] + r, c[1]))]
    if t == "arc":
        c, r = it["c"], it["r"]
        return [("c", tuple(c)), ("s", (c[0] + r * math.cos(it["a0"]), c[1] + r * math.sin(it["a0"]))), ("e", (c[0] + r * math.cos(it["a1"]), c[1] + r * math.sin(it["a1"])))]
    return []


def drag_handle(it, name, p):
    """Drags a handle of a drawing item to p; False when that would leave nothing to draw (the item is left as it was)."""
    t = it["type"]
    if t == "line":
        i = 0 if name == "a" else 1
        q = [list(it["p"][0]), list(it["p"][1])]
        q[i] = [float(p[0]), float(p[1])]
        if _hyp(q[0], q[1]) <= 1e-6:
            return False
        it["p"] = q
        return True
    if t == "rect":
        (x0, y0), (x1, y1) = it["p"]
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        i = int(name[1])
        new = new_item("rect", a=corners[(i + 2) % 4], b=p)
        if new is None:
            return False
        it["p"] = new["p"]
        return True
    if t == "circle":
        if name == "c":
            it["c"] = [float(p[0]), float(p[1])]
            return True
        r = _hyp(it["c"], p)
        if r <= MIN_R:
            return False
        it["r"] = float(r)
        return True
    if t == "arc":
        c = it["c"]
        if name == "c":
            it["c"] = [float(p[0]), float(p[1])]
            return True
        if _hyp(c, p) <= MIN_R:
            return False
        ang = math.atan2(p[1] - c[1], p[0] - c[0])
        if name == "s":
            end = it["a1"]
            a0 = ang
            sweep = (end - a0) % TAU
            it["r"], it["a0"], it["a1"] = float(_hyp(c, p)), float(a0), float(a0 + (sweep if sweep > 1e-3 else TAU))
        else:
            sweep = (ang - it["a0"]) % TAU
            if sweep < 1e-3:
                return False
            it["a1"] = float(it["a0"] + sweep)
        return True
    return False


def snap_on(ref, q):
    """Where a click at q (a view's frame) lands on the picked thing: the point, the nearest point of the line, the nearest point of the circle or arc."""
    k = ref["k"]
    if k == "pt":
        return tuple(ref["p"])
    if k == "line":
        a, b = ref["a"], ref["b"]
        ab = (b[0] - a[0], b[1] - a[1])
        n2 = ab[0] * ab[0] + ab[1] * ab[1]
        t = 0.0 if n2 < 1e-18 else min(1.0, max(0.0, ((q[0] - a[0]) * ab[0] + (q[1] - a[1]) * ab[1]) / n2))
        return (a[0] + ab[0] * t, a[1] + ab[1] * t)
    c, r = ref["c"], ref["r"]
    d = _hyp(c, q)
    if d < 1e-12:
        return (c[0] + r, c[1])
    ang = math.atan2(q[1] - c[1], q[0] - c[0])
    if k == "arc":
        a0, a1 = ref["a0"], ref["a1"]
        if (ang - a0) % TAU > (a1 - a0):                               # outside the arc: the nearer end
            e0, e1 = (c[0] + r * math.cos(a0), c[1] + r * math.sin(a0)), (c[0] + r * math.cos(a1), c[1] + r * math.sin(a1))
            return e0 if _hyp(e0, q) <= _hyp(e1, q) else e1
    return (c[0] + r * math.cos(ang), c[1] + r * math.sin(ang))


# ---------------------------------------------------------------------------------------------------------------------------- numbering and words
def next_balloon_text(balloons):
    """The number the next balloon gets: one over the biggest number that is on a balloon (1 for the first)."""
    top = 0
    for b in balloons:
        try:
            top = max(top, int(str(b.get("text", "")).strip()))
        except ValueError:
            continue
    return str(top + 1)


def bump_text(text):
    """'3' -> '4'; anything that is not a whole number stays."""
    try:
        return str(int(str(text).strip()) + 1)
    except ValueError:
        return str(text)


def label(it):
    """How an item reads in the Outline: the first line of a note, the number of a balloon, the kind of a drawing item."""
    t = it.get("type")
    if t == "note":
        first = str(it.get("text", "")).strip().split("\n")[0] if str(it.get("text", "")).strip() else "(empty)"
        return first if len(first) <= 28 else first[:27] + "…"
    if t == "balloon":
        return "Balloon  " + str(it.get("text", ""))
    return {"line": "Line", "rect": "Rectangle", "circle": "Circle", "arc": "Arc"}.get(t, "Item")


def pattern_text(pat):
    """A note pattern in words: '3 notes along 0°, 25 mm apart', '3 × 2 notes: 25 mm along 0°, 8 mm along 90°'."""
    n = A.number_text
    c1, c2 = int(pat["c1"]), int(pat["c2"])
    d1 = f"{n(abs(pat['s1']), 2)} mm along {n(pat['a1'] % 360.0 if pat['s1'] >= 0 else (pat['a1'] + 180.0) % 360.0, 1)}°"
    d2 = f"{n(abs(pat['s2']), 2)} mm along {n(pat['a2'] % 360.0 if pat['s2'] >= 0 else (pat['a2'] + 180.0) % 360.0, 1)}°"
    if c1 == 1 and c2 == 1:
        return "1 note (no copies)"
    if c2 == 1:
        return f"{c1} notes, {d1}"
    if c1 == 1:
        return f"{c2} notes, {d2}"
    return f"{c1} × {c2} notes: {d1}; {d2}"


def describe(it):
    """What a drawing item measures, in mm: 'length 40', 'width 30, height 20', 'diameter 12', 'radius 8, sweep 90°'."""
    t = it["type"]
    n = A.number_text
    if t == "line":
        return "length " + n(_hyp(*it["p"]), 2)
    if t == "rect":
        (x0, y0), (x1, y1) = it["p"]
        return f"width {n(x1 - x0, 2)}, height {n(y1 - y0, 2)}"
    if t == "circle":
        return "diameter " + n(2.0 * it["r"], 2)
    if t == "arc":
        return f"radius {n(it['r'], 2)}, sweep {n(math.degrees(it['a1'] - it['a0']), 1)}°"
    return ""
