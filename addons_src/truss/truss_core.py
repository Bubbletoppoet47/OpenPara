"""truss_core.py - the Truss Generator's engine (no Qt): the members of a truss from the lines of a sketch, with the cuts worked out from how
the members meet.

A project is one JSON-able dict (the folder `<name>.truss/` holds it as project.json next to the sketch part it was made from):

    {"format": "openpara-truss", "version": 2, "name": "Roof truss",
     "sketch": {"doc": <the part document as JSON text>, "sid": <sketch feature id>, "name": "Sketch1"},
     "profile": {"kind": "rect_tube", "params": {"w": 50.8, "h": 50.8, "t": 3.0}},          # the default for every member
     "members": [member, ...],  "names": {config: {member id: part name}},  "place": {config: {member id: {"dx","dy","dz","rot"}}}, "next": 1}
    member = {"id": "m1", "name": "Top chord", "line": <sketch line id>, "profile": None | {...},
              "ref": "center" | "left" | "right",     # what the sketch line is: the centreline, or the left / right face (looking start -> end)
              "offset": "0",                          # the line is this far from that reference, across the member (mm, + = to the left)
              "roll": 0.0, "ends": {"start": joint, "end": joint}}
    joint  = {"kind": "auto"}                                          # worked out from the sketch (see resolve_end)
           | {"kind": "free"}                                          # a square end at the joint point
           | {"kind": "butt" | "conform", "to": member id, "face": None | "left" | "right" | "start" | "end", "gap": "0"}   # Butt Connect (flat) / Conform Connect (fits the curve)
                                                                       # the end sits on that face of the other member (None: the long side nearest)
           | {"kind": "miter", "with": member id}                      # a clean corner: both members cut on the bisector

Nothing is cut by hand.  A member is its profile extruded along its line; each end that meets another member is extended and trimmed:
butt = extended to the chosen face of the other member and cut flat on that face's plane (on round pipe: minus the pipe, the curved saddle, and
everything beyond its axis);  miter = minus the far side of the bisecting plane.  The stock length (the longest extrusion) is read from the finished shape.
Every sketch configuration builds its own set of members.  A formula in a field can use the sketch's variables and dimensions, `len_<line id>`,
`angle_<line id>` and `joint_<id>_<id>` (the angle between two lines that meet).
"""
import json
import math
import re

SKETCH_FILE = "sketch.gpd"
FORMAT = "openpara-truss"
SEP = "_"

# ---------------------------------------------------------------------------------------------------- expressions
_FUNCS = {"sin": lambda a: math.sin(math.radians(a)), "cos": lambda a: math.cos(math.radians(a)), "tan": lambda a: math.tan(math.radians(a)),
          "asin": lambda a: math.degrees(math.asin(a)), "acos": lambda a: math.degrees(math.acos(a)), "atan": lambda a: math.degrees(math.atan(a)),
          "atan2": lambda a, b: math.degrees(math.atan2(a, b)), "sqrt": math.sqrt, "abs": abs, "min": min, "max": max, "pi": math.pi,
          "radians": math.radians, "degrees": math.degrees, "round": round}


class TrussError(Exception):
    pass


def num(text, names=None):
    """A number or a formula (variables from `names`) -> float."""
    if isinstance(text, (int, float)):
        return float(text)
    t = str(text).strip().replace("^", "**")
    if not t:
        raise TrussError("an empty field")
    try:
        return float(eval(t, {"__builtins__": {}}, {**_FUNCS, **(names or {})}))
    except NameError as ex:
        raise TrussError(f"'{text}': unknown name ({ex})")
    except Exception as ex:
        raise TrussError(f"'{text}': {ex}")


# ---------------------------------------------------------------------------------------------------- profiles
PROFILES = {
    "rect_tube": ("Rectangular / square tube", {"w": 50.8, "h": 50.8, "t": 3.0}, lambda p: (p["w"], p["h"])),
    "rounded_tube": ("Rounded square / rectangular tube", {"w": 50.8, "h": 50.8, "t": 3.0, "r": 6.0}, lambda p: (p["w"], p["h"])),
    "round_tube": ("Round tube", {"d": 48.3, "t": 3.0}, lambda p: (p["d"], p["d"])),
    "rect_bar": ("Solid rectangle", {"w": 50.8, "h": 12.7}, lambda p: (p["w"], p["h"])),
    "round_bar": ("Solid round", {"d": 25.4}, lambda p: (p["d"], p["d"])),
    "angle": ("Angle (L)", {"a": 50.8, "b": 50.8, "t": 4.8}, lambda p: (p["a"], p["b"])),
    "flat_bar": ("Flat bar", {"w": 50.8, "t": 6.35}, lambda p: (p["w"], p["t"])),
}


def default_profile():
    return {"kind": "rect_tube", "params": dict(PROFILES["rect_tube"][1])}


def profile_extent(prof, names=None):
    """(size across y, size across z) of a profile dict, in mm.  y lies in the plane of the truss."""
    kind = prof["kind"]
    if kind not in PROFILES:
        raise TrussError(f"unknown profile {kind}")
    p = {k: num(v, names) for k, v in {**PROFILES[kind][1], **prof.get("params", {})}.items()}
    return PROFILES[kind][2](p)


def _face(prof, names, filled=False):
    """The profile as a build123d face in the YZ plane (centred), normal along +X.  filled: a tube without its hollow (what another member butts against)."""
    from build123d import BuildSketch, Circle, Mode, Plane, Polygon, Rectangle, fillet
    kind = prof["kind"]
    p = {k: num(v, names) for k, v in {**PROFILES[kind][1], **prof.get("params", {})}.items()}
    if kind == "rounded_tube":
        r = min(max(p["r"], 0.0), min(p["w"], p["h"]) / 2 - 0.05)
        with BuildSketch(Plane.YZ) as so:
            Rectangle(p["w"], p["h"])
            if r > 0.01:
                fillet(so.vertices(), radius=r)
        face = so.sketch
        if not filled and p["t"] > 0 and p["w"] - 2 * p["t"] > 0 and p["h"] - 2 * p["t"] > 0:
            with BuildSketch(Plane.YZ) as si:
                Rectangle(p["w"] - 2 * p["t"], p["h"] - 2 * p["t"])
                if r - p["t"] > 0.01:
                    fillet(si.vertices(), radius=r - p["t"])
            face = face - si.sketch
        return face
    with BuildSketch(Plane.YZ) as s:
        if kind == "rect_tube":
            Rectangle(p["w"], p["h"])
            if not filled and p["t"] > 0 and p["w"] - 2 * p["t"] > 0 and p["h"] - 2 * p["t"] > 0:
                Rectangle(p["w"] - 2 * p["t"], p["h"] - 2 * p["t"], mode=Mode.SUBTRACT)
        elif kind == "round_tube":
            Circle(p["d"] / 2)
            if not filled and p["t"] > 0 and p["d"] - 2 * p["t"] > 0:
                Circle(p["d"] / 2 - p["t"], mode=Mode.SUBTRACT)
        elif kind == "rect_bar":
            Rectangle(p["w"], p["h"])
        elif kind == "round_bar":
            Circle(p["d"] / 2)
        elif kind == "flat_bar":
            Rectangle(p["w"], p["t"])
        elif kind == "angle":
            a, b, t = p["a"], p["b"], p["t"]
            x0, z0 = -a / 2, -b / 2
            Polygon([(x0, z0), (x0 + a, z0), (x0 + a, z0 + t), (x0 + t, z0 + t), (x0 + t, z0 + b), (x0, z0 + b)], align=None)
        else:
            raise TrussError(f"unknown profile {kind}")
    return s.sketch


# ---------------------------------------------------------------------------------------------------- the sketch
class SketchSource:
    """The sketch of a project: its part document (with the configurations) and, per configuration, the lines and the variables."""

    def __init__(self, doc_json, sid):
        import pm_model as pm
        self.pm = pm
        self.text = doc_json
        self.sid = sid
        self.doc = pm.Document.from_json(doc_json)
        if self.doc.feature(sid) is None:
            raise TrussError("the sketch is not in the part any more")
        self._cache = {}

    def configs(self):
        return list(self.doc.cfg["names"])

    def active(self):
        return self.doc.cfg["active"]

    def _built(self, config):
        if config in self._cache:
            return self._cache[config]
        d = self.pm.Document.from_json(self.text)
        d.cfg_apply(config if config in d.cfg["names"] else d.cfg["active"])
        d.rebuild()
        m = d.models.get(self.sid)
        if m is None:
            raise TrussError("the sketch could not be built in configuration " + config)
        self._cache[config] = (d, m)
        return d, m

    def lines(self, config):
        """{line id: {"p0": (x, y), "p1": (x, y), "length": mm, "angle": degrees}} - construction lines are left out."""
        d, m = self._built(config)
        out = {}
        for lid, (a, b) in m.lns.items():
            if ("ln", lid) in m.constr:
                continue
            (x0, y0), (x1, y1) = m.line_pts(lid)
            out[lid] = {"p0": (x0, y0), "p1": (x1, y1), "length": math.hypot(x1 - x0, y1 - y0), "angle": math.degrees(math.atan2(y1 - y0, x1 - x0))}
        return out

    def names(self, config):
        """The variables a formula can use: the globals, the named dimensions, and len_/angle_<line id> of every line, joint_<a>_<b> of lines that meet."""
        d, m = self._built(config)
        n = dict(d.values)
        n.update(d.dimvals)
        L = self.lines(config)
        for lid, ln in L.items():
            n[f"len_{lid}"] = ln["length"]
            n[f"angle_{lid}"] = ln["angle"]
        ids = sorted(L)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                try:
                    n[f"joint_{a}_{b}"] = self.joint_angle(config, a, b)
                except TrussError:
                    pass
        return n

    def joint_angle(self, config, l1, l2):
        """The angle in degrees between two lines that share an end point, measured between the two members (0..180)."""
        L = self.lines(config)
        a, b = L[l1], L[l2]
        for pa, qa in ((a["p0"], a["p1"]), (a["p1"], a["p0"])):
            for pb, qb in ((b["p0"], b["p1"]), (b["p1"], b["p0"])):
                if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) < 1e-6:
                    u = (qa[0] - pa[0], qa[1] - pa[1])
                    v = (qb[0] - pb[0], qb[1] - pb[1])
                    c = (u[0] * v[0] + u[1] * v[1]) / (math.hypot(*u) * math.hypot(*v))
                    return math.degrees(math.acos(max(-1.0, min(1.0, c))))
        raise TrussError("those two lines do not meet")


# ---------------------------------------------------------------------------------------------------- the project
def new_project(name="Truss"):
    return {"format": FORMAT, "version": 2, "name": name, "sketch": None, "profile": default_profile(), "members": [], "names": {}, "place": {},
            "next": 1}


def to_json(p):
    return json.dumps(p, indent=1)


def from_json(text):
    p = json.loads(text)
    if p.get("format") != FORMAT:
        raise TrussError("not a truss project")
    for m in p.get("members", []):                         # a project from before the joints: the hand cuts are gone, the joints are automatic
        m.pop("cuts", None)
        m.pop("len", None)
        m.setdefault("ref", "center")
        m.setdefault("offset", "0")
        m.setdefault("ends", {})
    for m in p.get("members", []):                         # before Conform Connect existed a butt on a round tube was cut to its curve: it is a conform now
        for e, j in m["ends"].items():
            if j.get("kind") == "butt":
                o = next((x for x in p["members"] if x["id"] == j.get("to")), None)
                if o is not None and member_curved(o, p):
                    j["kind"] = "conform"
    for m in p.get("members", []):                         # a crimped end (an option that was removed) is automatic again
        for e, j in list(m["ends"].items()):
            if j.get("kind") == "crimp":
                m["ends"][e] = {"kind": "auto"}
    p["version"] = 3
    return p


def _nid(p, prefix):
    n = p["next"]
    p["next"] = n + 1
    return f"{prefix}{n}"


def add_member(p, line, name=None):
    for m in p["members"]:
        if m["line"] == line:
            return m
    m = {"id": _nid(p, "m"), "name": name or f"Member {len(p['members']) + 1}", "line": line, "profile": None, "ref": "center", "offset": "0",
         "roll": 0.0, "ends": {"start": {"kind": "auto"}, "end": {"kind": "auto"}}}
    p["members"].append(m)
    return m


def remove_member(p, mid):
    p["members"] = [m for m in p["members"] if m["id"] != mid]
    for m in p["members"]:                                  # a joint that pointed at it goes back to automatic
        for e, j in m["ends"].items():
            if j.get("to") == mid or j.get("with") == mid:
                m["ends"][e] = {"kind": "auto"}
    for d in (p["names"], p["place"]):
        for c in d.values():
            c.pop(mid, None)


def member(p, mid):
    return next((m for m in p["members"] if m["id"] == mid), None)


def set_end(p, mid, end, kind, other=None, gap="0", face=None):
    """Set the joint at one end.  A miter is a pair: the other member's matching end becomes a miter with this one."""
    m = member(p, mid)
    if kind == "auto" or kind == "free":
        m["ends"][end] = {"kind": kind}
    elif kind in ("butt", "conform"):
        m["ends"][end] = {"kind": kind, "to": other, "face": face, "gap": str(gap)}
    elif kind == "miter":
        m["ends"][end] = {"kind": "miter", "with": other}
    else:
        raise TrussError(f"unknown joint {kind}")


def set_config_names(p, config, prefix=None):
    """Give every member a part name for this configuration (kept when it has one): <project>_<configuration>_<member>."""
    d = p["names"].setdefault(config, {})
    for m in p["members"]:
        if m["id"] not in d:
            d[m["id"]] = SEP.join(_clean(x) for x in (prefix or p["name"], config, m["name"]))
    return d


def _clean(s):
    return re.sub(r"[^\w\-.]+", "_", str(s)).strip("_") or "x"


# ---------------------------------------------------------------------------------------------------- geometry helpers (2D, in the truss plane)
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _unit(a):
    n = math.hypot(*a)
    if n < 1e-12:
        raise TrussError("a line has no length")
    return (a[0] / n, a[1] / n)


def _on_segment(pt, p0, p1, tol):
    """(is the point on the segment, is it at one of its ends)"""
    d = _sub(p1, p0)
    L2 = _dot(d, d)
    if L2 < 1e-18:
        return False, False
    t = _dot(_sub(pt, p0), d) / L2
    if t < -tol / math.sqrt(L2) or t > 1 + tol / math.sqrt(L2):
        return False, False
    q = (p0[0] + t * d[0], p0[1] + t * d[1])
    if math.hypot(pt[0] - q[0], pt[1] - q[1]) > tol:
        return False, False
    at_end = math.hypot(pt[0] - p0[0], pt[1] - p0[1]) <= tol or math.hypot(pt[0] - p1[0], pt[1] - p1[1]) <= tol
    return True, at_end


def _resolve_end(project, lines, m, end, names=None):
    """What an 'auto' joint means at this end of member m: {"kind": free | butt | miter, "to"/"with": member id}.
    Another member's end at the same point, or its line passing through that point, makes a joint.  One member through: this end butts against it.
    Two members ending at the point: a miter (a collinear pair: a square end).  Three or more: the longest stays whole, the rest butt against it."""
    ln = lines.get(m["line"])
    if ln is None:
        return {"kind": "free"}
    node = ln["p0"] if end == "start" else ln["p1"]
    span = max([v["length"] for v in lines.values()] + [1.0])
    tol = 1e-6 * span + 1e-4
    through, ending = [], []
    for o in project["members"]:
        if o["id"] == m["id"] or o["line"] not in lines:
            continue
        lo = lines[o["line"]]
        hit, at_end = _on_segment(node, lo["p0"], lo["p1"], tol)
        if hit:
            (ending if at_end else through).append(o)
    if through:
        return {"kind": "butt", "to": through[0]["id"], "gap": "0"}
    if not ending:
        return {"kind": "free"}
    if len(ending) == 1:
        o = ending[0]
        lo = lines[o["line"]]
        a = _unit(_sub(ln["p1"], ln["p0"]) if end == "start" else _sub(ln["p0"], ln["p1"]))              # leaving the joint along m
        b = _unit(_sub(lo["p1"], lo["p0"]) if math.hypot(*_sub(node, lo["p0"])) <= tol else _sub(lo["p0"], lo["p1"]))
        if abs(_cross(a, b)) < 1e-9:                         # in line: nothing to cut
            return {"kind": "free"}
        try:
            same = section_key(m, project, names) == section_key(o, project, names)
        except TrussError:
            same = True
        if not same:                                         # a flat miter of two different sections leaves them not touching: the larger runs through, the other butts on it
            am, ao = section_area(m, project, names), section_area(o, project, names)
            order = {x["id"]: i for i, x in enumerate(project["members"])}
            if (am, -order[m["id"]]) > (ao, -order[o["id"]]):
                return {"kind": "free"}
            return {"kind": "butt", "to": o["id"], "gap": "0"}
        return {"kind": "miter", "with": o["id"]}
    group = ending + [m]
    order = {x["id"]: i for i, x in enumerate(project["members"])}
    longest = max(group, key=lambda x: (round(lines[x["line"]]["length"], 6), -order[x["id"]]))        # the longest; a tie goes to the earlier member
    if longest["id"] == m["id"]:
        return {"kind": "free"}
    return {"kind": "butt", "to": longest["id"], "gap": "0"}


def resolve_end(project, lines, m, end, names=None):
    """What an 'auto' joint means at this end (see _resolve_end); a butt on a round or turned target is a conform, since a flat cut would only touch along a line."""
    r = _resolve_end(project, lines, m, end, names)
    if r["kind"] == "butt":
        o = member(project, r["to"])
        if o is not None and member_curved(o, project):
            r = dict(r, kind="conform")
    return r


# ---------------------------------------------------------------------------------------------------- one member
class Geo:
    """A member's place in the truss plane for one configuration (before any trimming)."""

    def __init__(self, project, m, line, names):
        self.m, self.line, self.names = m, line, dict(names)
        self.prof = m.get("profile") or project["profile"]
        self.hy, self.hz = profile_extent(self.prof, self.names)
        self.roll = float(m.get("roll") or 0.0)
        r = math.radians(self.roll)
        self.w = abs(self.hy * math.cos(r)) + abs(self.hz * math.sin(r))               # width across the truss plane
        p0, p1 = line["p0"], line["p1"]
        self.u = _unit(_sub(p1, p0))
        self.nl = (-self.u[1], self.u[0])                                              # left of the direction of the line
        ref = m.get("ref", "center")
        shift = num(m.get("offset", "0") or "0", self.names)
        if ref == "left":                                                              # the line is the left face: the body lies to its right
            shift -= self.w / 2
        elif ref == "right":
            shift += self.w / 2
        self.c0 = (p0[0] + self.nl[0] * shift, p0[1] + self.nl[1] * shift)
        self.L0 = line["length"]
        self.angle = line["angle"]

    def point(self, t):
        return (self.c0[0] + self.u[0] * t, self.c0[1] + self.u[1] * t)

    def raw(self, t0=0.0, t1=None, filled=False):
        """The untrimmed solid from parameter t0 to t1 along the axis, in the truss plane.  filled: without the hollow of a tube."""
        from build123d import Pos, Rot, extrude
        t1 = self.L0 if t1 is None else t1
        s = extrude(_face(self.prof, self.names, filled), amount=t1 - t0)
        if self.roll:
            s = Rot(X=self.roll) * s
        x, y = self.point(t0)
        return Pos(x, y, 0) * (Rot(Z=self.angle) * s)


def _curved_kind(kind, roll):
    return kind in ("round_tube", "round_bar") or abs(((float(roll or 0.0) + 45.0) % 90.0) - 45.0) > 1e-6


def is_curved(g):
    """True when a flat cut could not sit on the member's long side: a round section, or one turned off square.  (A rounded-square tube has flat sides.)"""
    return _curved_kind(g.prof["kind"], g.roll)


def member_curved(m, project):
    return _curved_kind((m.get("profile") or project["profile"])["kind"], m.get("roll"))


def tc_member(project, mid):
    return next((x for x in project["members"] if x["id"] == mid), None)


def section_key(m, project, names=None):
    """What makes two members the same stock: profile kind, its sizes, and the turn."""
    prof = m.get("profile") or project["profile"]
    pr = {k: round(num(v, names), 3) for k, v in {**PROFILES[prof["kind"]][1], **prof.get("params", {})}.items()}
    return (prof["kind"], tuple(sorted(pr.items())), round(float(m.get("roll") or 0.0), 3))


def section_area(m, project, names=None):
    hy, hz = profile_extent(m.get("profile") or project["profile"], names)
    return hy * hz


def _axis_hit(a, b):
    """Parameter along a's axis where it meets b's axis."""
    d = _cross(a.u, b.u)
    if abs(d) < 1e-9:
        raise TrussError("two members that run parallel cannot meet")
    return _cross(_sub(b.c0, a.c0), b.u) / d


def _foot(point, direction, near):
    """The point of the line through `point` along `direction` that is closest to `near`: where a cutting plane is centred, so a short member far from the other member's start is still reached."""
    d = _dot(_sub(near, point), direction)
    return (point[0] + direction[0] * d, point[1] + direction[1] * d)


def _plane_cutter(point, direction, side, size):
    """A prism that fills the half of the truss plane on `side` (+1 / -1: the left / right of `direction`) of the line through `point`, all through z."""
    from build123d import Face, Vector, Wire, extrude
    nl = (-direction[1], direction[0])
    S = size
    pts = [(point[0] - S * direction[0], point[1] - S * direction[1]), (point[0] + S * direction[0], point[1] + S * direction[1]),
           (point[0] + S * direction[0] + side * S * nl[0], point[1] + S * direction[1] + side * S * nl[1]),
           (point[0] - S * direction[0] + side * S * nl[0], point[1] - S * direction[1] + side * S * nl[1])]
    face = Face(Wire.make_polygon([Vector(x, y, 0) for x, y in pts], close=True))
    return extrude(face, amount=S, both=True)


class Member:
    """A member built for one configuration: the trimmed solid in the truss plane, and what the cut list needs."""

    def __init__(self, project, g, ends, geos):
        self.project, self.g, self.m = project, g, g.m
        self.ends = ends                                   # {"start": joint dict, "end": joint dict} - resolved (no 'auto')
        self.geos = geos
        self.info = {"start": {"kind": "free"}, "end": {"kind": "free"}}

    FACES = ("left", "right", "start", "end")

    def auto_face(self, o, end):
        """The long side of member o nearest this member's body (what a joint with no face chosen uses)."""
        g = self.g
        far = g.point(0.0 if end == "end" else g.L0)
        return "left" if _dot(_sub(far, o.c0), o.nl) > 0 else "right"

    def butt_plan(self, o, j, end):
        """Where this end meets the chosen face of member o: (face, t along this member's axis, a flat plane (point, direction, side to remove, outward normal)
        or None for a saddle on round pipe, angle of the cut)."""
        g = self.g
        far = g.point(0.0 if end == "end" else g.L0)                       # this member's body lies toward its other end
        face = j.get("face")
        if face not in self.FACES:
            face = "left" if _dot(_sub(far, o.c0), o.nl) > 0 else "right"        # the long side nearest this member
        round_o = j.get("kind") == "conform"                                   # Conform Connect wraps the target's curve; Butt Connect is always a flat cut
        gap = num(j.get("gap", "0") or "0", g.names)
        if face in ("left", "right") and round_o:
            t = _axis_hit(g, o)                                            # a saddle: no flat face, the side only says which way the pipe is approached
            side = 1 if face == "left" else -1
            if _dot(_sub(far, o.c0), o.nl) * side < 0:
                raise TrussError(f"this member is not on the {face} side of {o.m['name']}")
            return face, t, None, 90.0 - math.degrees(math.acos(min(1.0, abs(_dot(g.u, o.u))))), side
        if face in ("left", "right"):
            sgn = 1.0 if face == "left" else -1.0
            out_n = (sgn * o.nl[0], sgn * o.nl[1])                         # out of o through this face
            P = (o.c0[0] + out_n[0] * (o.w / 2 + gap), o.c0[1] + out_n[1] * (o.w / 2 + gap))
            D = o.u
        else:
            tt = 0.0 if face == "start" else o.L0
            sgn = -1.0 if face == "start" else 1.0
            out_n = (sgn * o.u[0], sgn * o.u[1])
            Q = o.point(tt)
            P = (Q[0] + out_n[0] * gap, Q[1] + out_n[1] * gap)
            D = o.nl
        if _dot(_sub(far, P), out_n) <= 0:
            raise TrussError(f"this member is not on the outside of the {face} face of {o.m['name']}")
        d = _cross(g.u, D)
        if abs(d) < 1e-9:
            raise TrussError(f"{self.m['name']} runs parallel to the {face} face of {o.m['name']}, so that end can never meet it. Choose another member or face, or Automatic.")
        t = _cross(_sub(P, g.c0), D) / d
        # the half plane to remove lies on the inside of the face: opposite out_n; side +1 of a direction D is its left normal
        left_of_D = (-D[1], D[0])
        side_remove = 1 if _dot(left_of_D, out_n) < 0 else -1
        ang = 90.0 - math.degrees(math.acos(min(1.0, abs(_dot(g.u, D)))))
        return face, t, (P, D, side_remove), ang, None

    def build(self):
        g = self.g
        t0, t1 = 0.0, g.L0
        margin = 2.0 * (g.w + g.hz) + 10.0
        partner = {}
        for end in ("start", "end"):
            j = self.ends[end]
            if j["kind"] in ("butt", "conform", "miter"):
                other = j.get("to") or j.get("with")
                o = self.geos.get(other)
                if o is None:
                    raise TrussError(f"the {end} joint refers to a member that is not in this configuration")
                plan = None
                if j["kind"] in ("butt", "conform"):
                    plan = self.butt_plan(o, j, end)
                    t = plan[1]
                else:
                    t = _axis_hit(g, o)
                partner[end] = (j, o, t, plan)
                if end == "start":
                    t0 = t - margin
                else:
                    t1 = t + margin
        if t1 - t0 < 1e-6:
            raise TrussError("the member has no length")
        solid = g.raw(t0, t1)
        S = max(g.L0, 1.0) * 4 + 1000.0
        for end, (j, o, t, plan) in partner.items():
            out = g.u if end == "start" else (-g.u[0], -g.u[1])                      # the direction of the body, away from the joint
            if j["kind"] in ("butt", "conform"):
                face, tt, flat, ang, side = plan
                if flat is not None:                                                 # a flat face: cut on its plane
                    P, D, side_remove = flat
                    solid = solid - _plane_cutter(_foot(P, D, g.point(t)), D, side_remove, S)       # centred where this member's axis meets the face, not at the other member's start
                    saddle = False
                else:                                                                # round pipe: the curved saddle
                    ext = 4.0 * (g.w + g.hz + o.w) + 100.0              # the target is cut as if it ran on past its ends, like the flat face line does:
                    other = o.raw(-ext, o.L0 + ext, filled=True)         # a member that overhangs the end of the tube is still cut to its face, not left sticking out
                    gap = num(j.get("gap", "0") or "0", g.names)
                    if gap > 0:
                        from build123d import offset
                        try:
                            other = offset(other, amount=gap)
                        except Exception:
                            pass
                    solid = solid - other - _plane_cutter(_foot(o.c0, o.u, g.point(t)), o.u, -side, S)
                    saddle = True
                self.info[end] = {"kind": j["kind"], "to": o.m["id"], "face": face, "angle": round(ang, 3), "saddle": saddle,
                                  "shape": "cope" if saddle else "flat"}
            else:
                so = _axis_hit(o, g)                                                      # where the other member meets this one, along its own axis
                b = o.u if so < o.L0 / 2 else (-o.u[0], -o.u[1])                          # its body, away from the joint
                w = _unit((out[0] + b[0], out[1] + b[1])) if math.hypot(out[0] + b[0], out[1] + b[1]) > 1e-9 else None
                if w is None:
                    raise TrussError("two members in line cannot be mitered")
                c = g.point(t)
                keep = 1 if _cross(w, out) > 0 else -1                                # the side of the bisector where this member is
                solid = solid - _plane_cutter(c, w, -keep, S)
                phi = math.degrees(math.acos(min(1.0, abs(_dot(g.u, w)))))
                self.info[end] = {"kind": "miter", "with": o.m["id"], "angle": round(90.0 - phi, 3)}
        self.solid = solid
        from build123d import Rot
        self.length = float((Rot(Z=-g.angle) * solid).bounding_box().size.X)             # the longest extrusion: the stock length
        return solid

    def placed(self, place=None):
        """The solid in the truss plane plus a manual offset from the Assembly page."""
        return self.xform(self.solid, place)

    @staticmethod
    def xform(s, place=None):
        from build123d import Pos, Rot
        if place and (place.get("dx") or place.get("dy") or place.get("dz") or place.get("rot")):
            if place.get("rot"):
                s = Rot(Z=place["rot"]) * s
            s = Pos(place.get("dx", 0.0), place.get("dy", 0.0), place.get("dz", 0.0)) * s
        return s

    def cut_row(self):
        def end_text(e):
            i = self.info[e]
            return i["kind"] if i["kind"] == "free" else f"{i['kind']} {i['angle']}"
        return {"member": self.m["name"], "profile": self.g.prof["kind"], "params": {k: num(v, self.g.names) for k, v in self.g.prof["params"].items()},
                "length": round(self.length, 3), "start": self.info["start"], "end": self.info["end"],
                "start_angles": [self.info["start"]["angle"]] if "angle" in self.info["start"] else [],
                "end_angles": [self.info["end"]["angle"]] if "angle" in self.info["end"] else [],
                "start_text": end_text("start"), "end_text": end_text("end")}


# ---------------------------------------------------------------------------------------------------- a whole configuration
class Built:
    """Every member of one configuration: solids, placed solids, the joints as they were resolved, the cut list, and the problems met."""

    def __init__(self, project, source, config):
        self.project, self.source, self.config = project, source, config
        self.members, self.errors, self.resolved, self.warnings = {}, {}, {}, {}
        lines = source.lines(config)
        names = source.names(config)
        self.names = set_config_names(project, config)
        geos = {}
        for m in project["members"]:
            ln = lines.get(m["line"])
            if ln is None:
                self.errors[m["id"]] = "its sketch line is not in this configuration"
                continue
            try:
                geos[m["id"]] = Geo(project, m, ln, names)
            except TrussError as ex:
                self.errors[m["id"]] = str(ex)
        for m in project["members"]:
            g = geos.get(m["id"])
            if g is None:
                continue
            ends = {}
            for e in ("start", "end"):
                j = m["ends"].get(e) or {"kind": "auto"}
                ends[e] = resolve_end(project, lines, m, e, names) if j["kind"] == "auto" else dict(j)
            self.resolved[m["id"]] = {e: dict(j, auto=(m["ends"].get(e) or {"kind": "auto"})["kind"] == "auto") for e, j in ends.items()}
            try:
                mb = Member(project, g, ends, geos)
                mb.build()
                self.members[m["id"]] = mb
            except TrussError as ex:
                self.errors[m["id"]] = str(ex)
            except Exception as ex:                          # a boolean that fails on odd geometry
                self.errors[m["id"]] = f"could not build: {ex}"
        self.check_joints()

    def check_joints(self):
        """Things that build but will not fit well: a hand-made miter of two different sections (the pieces do not touch), and a flat Butt Connect
        on a round or turned target (it touches along a line only)."""
        names = self.source.names(self.config)
        for mid, r in self.resolved.items():
            msgs = []
            a = tc_member(self.project, mid)
            for e, j in r.items():
                if j["kind"] == "miter" and not j.get("auto"):
                    o = tc_member(self.project, j.get("with"))
                    try:
                        if a and o and section_key(a, self.project, names) != section_key(o, self.project, names):
                            msgs.append(f"A miter of two different sections leaves them not touching ({a['name']} and {o['name']}). Use a Butt Connect: the larger member runs through.")
                    except TrussError:
                        pass
                elif j["kind"] == "butt" and j.get("face") in (None, "left", "right"):
                    o = tc_member(self.project, j.get("to"))
                    if o is not None and member_curved(o, self.project):
                        msgs.append(f"Butt Connect on {o['name']} touches along a line only, because its side is curved. Use Conform Connect.")
            if msgs:
                self.warnings[mid] = "\n".join(dict.fromkeys(msgs))

    def placed(self, mid):
        return self.members[mid].placed(self.project["place"].get(self.config, {}).get(mid))

    def cut_list(self):
        rows = []
        for m in self.project["members"]:
            mb = self.members.get(m["id"])
            if mb:
                r = mb.cut_row()
                r["part"] = self.names.get(m["id"], m["name"])
                rows.append(r)
        return rows

    def hit(self, point, tol=3.0):
        """The member and face under a point picked in the 3D view: (member id, 'left' | 'right' | 'start' | 'end') or None."""
        r = self.hit_detail(point, tol)
        return None if r is None else (r["mid"], r["face"])

    def hit_detail(self, point, tol=3.0):
        """{"mid", "face", "curved"}: the member and face under a picked point; curved = the click was on a round tube or on a rounded corner (no flat face there).
        A click on the face's side picks by its direction; a click on the top or bottom picks the nearest side of the member."""
        from build123d import Vector, Vertex
        v = Vertex(*point)
        best, bd = None, tol
        for mid in self.members:
            d = self.placed(mid).distance_to(v)
            if d < bd:
                best, bd = mid, d
        if best is None:
            return None
        g = self.members[best].g
        rel = (point[0] - g.c0[0], point[1] - g.c0[1])
        s_, r_ = _dot(rel, g.u), _dot(rel, g.nl)
        round_ = is_curved(g)
        nn, nz = (0.0, 0.0), 0.0
        try:
            sol = self.placed(best)
            f = min(sol.faces(), key=lambda f: f.distance_to(v))
            n = f.normal_at(Vector(*point))
            nn, nz = (n.X, n.Y), abs(n.Z)
        except Exception:
            pass
        m_ = math.hypot(*nn)
        if m_ > 0.5 and not round_:                                            # a face seen from the side: its direction decides
            cand = {"left": g.nl, "right": (-g.nl[0], -g.nl[1]), "start": (-g.u[0], -g.u[1]), "end": g.u}
            face = max(cand, key=lambda k: _dot(nn, cand[k]))
            return {"mid": best, "face": face, "curved": g.prof["kind"] == "rounded_tube" and m_ < 0.95}
        if round_:
            return {"mid": best, "face": "left" if r_ > 0 else "right", "curved": True}
        dist = {"left": abs(r_ - g.w / 2), "right": abs(r_ + g.w / 2), "start": abs(s_), "end": abs(s_ - g.L0)}      # a top / bottom click
        return {"mid": best, "face": min(dist, key=dist.get), "curved": False}

    def face_shape(self, target_mid, face, curved=False):
        """The chosen face of a member as a shape to draw on top of it (placed like the member), or None when it cannot be found."""
        mb = self.members.get(target_mid)
        if mb is None:
            return None
        g = mb.g
        place = self.project["place"].get(self.config, {}).get(target_mid)
        want = {"left": g.nl, "right": (-g.nl[0], -g.nl[1]), "start": (-g.u[0], -g.u[1]), "end": g.u}.get(face)
        if want is None:
            return None
        try:
            from build123d import Compound
            if curved and is_curved(g) and face in ("left", "right"):          # a round tube: the half of its surface that faces the other member
                env = g.raw(0, g.L0, filled=True)
                try:
                    from build123d import offset
                    env = offset(env, amount=0.4)                                        # a hair above the surface, so it is not hidden by it
                except Exception:
                    pass
                half = env & _plane_cutter(g.c0, g.u, 1 if face == "left" else -1, g.L0 * 2 + 1000.0)
                fs = [f for f in half.faces() if not str(f.geom_type).endswith("PLANE")]
            else:
                fs = []
                for f in mb.solid.faces():
                    if not str(f.geom_type).endswith("PLANE"):
                        continue
                    n = f.normal_at()
                    d = n.X * want[0] + n.Y * want[1]
                    if d > (0.3 if face in ("start", "end") else 0.9) and abs(n.Z) < 0.2:
                        fs.append((d, f.area, f))
                if not fs:
                    return None
                from build123d import Pos
                fs = [Pos(want[0] * 0.4, want[1] * 0.4, 0) * max(fs, key=lambda t: (round(t[1]), t[0]))[2]]           # a hair above the surface
            return mb.xform(Compound(fs), place) if fs else None
        except Exception:
            return None

    def joint_highlights(self, mid):
        """[(shape, ok)] the faces the joints of member mid sit on, for drawing: ok=False when the joint could not be built (the face is drawn red)."""
        out = []
        for e in ("start", "end"):
            j = (self.resolved.get(mid) or {}).get(e)
            if not j or j["kind"] not in ("butt", "conform"):
                continue
            mb, o = self.members.get(mid), self.members.get(j["to"])
            if o is None:
                continue
            try:
                g = Geo(self.project, tc_member(self.project, mid), self.source.lines(self.config)[tc_member(self.project, mid)["line"]], self.source.names(self.config))
                face = j.get("face")
                if face not in Member.FACES:
                    face = "left" if _dot(_sub(g.point(0.0 if e == "end" else g.L0), o.g.c0), o.g.nl) > 0 else "right"
            except Exception:
                continue
            sh = self.face_shape(j["to"], face, curved=(j["kind"] == "conform"))
            if sh is not None:
                out.append((sh, mb is not None and mid not in self.errors))
        return out

    def assembly(self):
        from build123d import Compound
        return Compound([self.placed(mid) for mid in self.members])


def cut_list_csv(rows, unit=None):
    """unit: (name, mm per unit) of the length column; None = mm.  Files and projects hold mm; only this text follows File > Units."""
    name, k = unit or ("mm", 1.0)
    out = [f"part,member,profile,length_{name},start,end"]
    for r in rows:
        out.append(",".join([r["part"], r["member"], r["profile"], f"{r['length'] / k:.4f}".rstrip("0").rstrip("."), r["start_text"].replace(" ", "_"),
                             r["end_text"].replace(" ", "_")]))
    return "\n".join(out) + "\n"


def _unique_files(project):
    """One file name per member, the same in every configuration (the per-configuration names live in the cut list)."""
    used, out = set(), {}
    for m in project["members"]:
        base = _clean(m["name"]) or m["id"]
        nm, k = base, 2
        while nm.lower() in used:
            nm, k = f"{base}_{k}", k + 1
        used.add(nm.lower())
        out[m["id"]] = nm
    return out


def export(project, source, folder, configs=None, step=True, stl=True, unit=None, openpara=True):
    """Write the project into folder/exports/: ONE set of OpenPara files (a part per member holding every configuration, and one configurable
    assembly), one cut list with a configuration column, and, per configuration, read-only STEP / STL snapshots in exports/<config>/."""
    import os
    from build123d import export_step, export_stl
    configs = list(configs or source.configs())
    out = os.path.join(folder, "exports")
    os.makedirs(out, exist_ok=True)
    written, errors, builts = [], {}, {}
    for c in configs:
        b = Built(project, source, c)
        builts[c] = b
        for mid, why in b.errors.items():
            errors[f"{c}: {mid}"] = why
    files = _unique_files(project)
    for c, b in builts.items():
        if not b.members or not (step or stl):
            continue
        sub = os.path.join(out, _clean(c))
        os.makedirs(sub, exist_ok=True)
        for mid in b.members:
            nm = files[mid]
            if step:
                export_step(b.placed(mid), os.path.join(sub, nm + ".step")); written.append(f"{_clean(c)}/{nm}.step")
            if stl:
                export_stl(b.placed(mid), os.path.join(sub, nm + ".stl")); written.append(f"{_clean(c)}/{nm}.stl")
        if step:
            export_step(b.assembly(), os.path.join(sub, "assembly.step")); written.append(f"{_clean(c)}/assembly.step")
    if openpara and any(b.members for b in builts.values()):
        written += export_openpara(project, builts, files, out)
    name_, k = unit or ("mm", 1.0)
    lines = [f"config,part,member,profile,length_{name_},start,end"]
    for c, b in builts.items():
        rows = cut_list_csv(b.cut_list(), unit).splitlines()[1:]
        lines += [f"{_clean(c)},{r}" for r in rows]
    with open(os.path.join(out, "cut_list.csv"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    written.append("cut_list.csv")
    return out, written, errors


def export_openpara(project, builts, files, out):
    """One part (.gpd) per member holding one solid per configuration, and one assembly (.gpa) with the same configurations: put it in a bigger
    assembly as a sub-assembly and pick the configuration there.  The parts sit exactly where they are in the truss, so the assembly places them at the origin."""
    import os
    import exchange as ex
    import pm_model as pm
    import asm_model
    configs = list(builts)
    written = []
    a = asm_model.Assembly()
    comps = {}
    for m in project["members"]:
        present = [c for c in configs if m["id"] in builts[c].members]
        if not present:
            continue
        nm = files[m["id"]]
        d = pm.Document()
        fids = {}
        for c in present:
            f = d.add(pm.new_feature("imported", brep=ex.pack(builts[c].placed(m["id"])), source="Truss Generator", name=f"{nm} ({c})"))
            fids[c] = f["id"]
        d.rebuild()
        d.cfg["names"] = [configs[0]]
        d.cfg["active"] = configs[0]
        d.cfg["cells"] = {configs[0]: {}}
        for c in configs[1:]:
            d.cfg_add(c)
        d.cfg["cols"] = [f"s:{fid}" for fid in fids.values()]
        for c in configs:
            d.cfg["cells"][c] = {f"s:{fids[k]}": (k != c) for k in present}      # only this configuration's solid is switched on
        d.cfg["active"] = configs[0]
        for c0, fid in fids.items():                                   # the document starts in the first configuration
            d.feature(fid)["suppressed"] = c0 != configs[0]
        d.rebuild()
        with open(os.path.join(out, nm + ".gpd"), "w", encoding="utf-8") as f:
            f.write(d.to_json())
        written.append(nm + ".gpd")
        comp = a.add_component(nm + ".gpd", name=nm, fixed=True)
        comp["config"] = configs[0]
        comps[m["id"]] = (comp, present)
    a.cfg["names"] = [configs[0]]
    a.cfg["active"] = configs[0]
    a.cfg["cells"] = {configs[0]: {}}
    for c in configs[1:]:
        a.cfg_add(c)
    a.cfg["cols"] = []
    for mid, (comp, present) in comps.items():
        a.cfg["cols"] += [f"c:{comp['id']}", f"x:{comp['id']}"]
    for c in configs:
        a.cfg["cells"][c] = {}
        for mid, (comp, present) in comps.items():
            a.cfg["cells"][c][f"c:{comp['id']}"] = c if c in present else present[0]
            a.cfg["cells"][c][f"x:{comp['id']}"] = c not in present                  # a member that is not in this configuration is suppressed
    for mid, (comp, present) in comps.items():                        # the assembly starts in the first configuration
        comp["config"] = configs[0] if configs[0] in present else present[0]
        comp["suppressed"] = configs[0] not in present
    asm_name = _clean(project["name"]) or "Truss"
    with open(os.path.join(out, asm_name + ".gpa"), "w", encoding="utf-8") as f:
        f.write(a.to_json())
    written.append(asm_name + ".gpa")
    return written


def save(project, folder):
    """The project folder: project.json and sketch.gpd, the sketch part itself with all its configurations (the one copy of the sketch)."""
    import os
    os.makedirs(folder, exist_ok=True)
    sk = project.get("sketch")
    slim = dict(project)
    if sk and sk.get("doc"):
        import fileio
        fileio.write_text(os.path.join(folder, SKETCH_FILE), sk["doc"])
        slim["sketch"] = {"sid": sk["sid"], "name": sk["name"], "file": SKETCH_FILE}
    import fileio
    fileio.write_text(os.path.join(folder, "project.json"), to_json(slim))
    return os.path.join(folder, "project.json")


def load(folder):
    import os
    if not os.path.isdir(folder):
        folder = os.path.dirname(folder)
    with open(os.path.join(folder, "project.json"), encoding="utf-8") as f:
        p = from_json(f.read())
    sk = p.get("sketch")
    if sk and not sk.get("doc"):                          # the sketch lives in the folder as sketch.gpd
        path = os.path.join(folder, sk.get("file") or SKETCH_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                sk["doc"] = f.read()
        except OSError:
            raise TrussError(f"the sketch file {os.path.basename(path)} is missing from the project folder")
    return p


def reload_sketch(project, folder):
    """Read sketch.gpd again (after it was edited and saved): the members, joints and profiles stay.  Returns what changed:
    {"new_configs": [...], "gone_configs": [...], "missing_lines": [member names whose sketch line is no longer there]}."""
    import os
    sk = project.get("sketch")
    path = os.path.join(folder, (sk or {}).get("file") or SKETCH_FILE)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    old = SketchSource(sk["doc"], sk["sid"]) if sk and sk.get("doc") else None
    new = SketchSource(text, sk["sid"])
    before = old.configs() if old else []
    after = new.configs()
    missing = []
    for m in project["members"]:
        if not any(m["line"] in new.lines(c) for c in after):
            missing.append(m["name"])
    sk["doc"] = text
    return {"new_configs": [c for c in after if c not in before], "gone_configs": [c for c in before if c not in after], "missing_lines": missing}
