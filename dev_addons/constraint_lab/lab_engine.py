"""lab_engine.py - the EXPERIMENTAL mate engine of the Constraint Lab (dev_addons/constraint_lab).

It started as an exact copy of core/asm_model.py (the engine the real assembly uses) and is where mate robustness is worked out: nothing outside this
add-on imports it, and the real assembly keeps using asm_model.  The lab swaps a window's assembly onto this class with
a.__class__ = lab_engine.Assembly  (see lab_tab.py); if a version needs extra attributes, give the class a lab_adopt(self) method and the lab calls it right
after the swap.  MateError is the real one, so the window's  except am.MateError  still catches it.

What differs from asm_model.py (each one measured with the Mate Matrix; test_lab_engine.py keeps them true):
  _lm        the fit works on small moves ON TOP of the pose (a shift in mm, a turn about the world axes counted as arm-length mm) instead of on the raw
             position and rotation vector, with damping relative to the size of the Jacobian: the smallest MOVE is taken, not the smallest number, so a point
             on a face slides instead of spinning the part, and no angle wraps near half a turn.
  _run       turn first, then slide: the residual rows that do not change when parts are moved apart (parallel, perpendicular, angle, 'normals agree') are
             fitted alone, then everything with the turns held, then everything together.  Two edges 1.5 m away no longer end up crossing at 68 degrees.
  _restarts  when the fit still ends off the mates, other starting poses for the parts of the unmet mates (small nudges, half turns, larger random ones; the
             same sequence every time).  Not while dragging.
  solve      puts every pose back if anything goes wrong inside (a Python error becomes a MateError), and refuses a pose that is not a number.
  prepare    an angle on a point or sphere is a MateError, not a crash.
  local_entity / _nearest   a part edited after the mate was made is still found when the face / edge / point it meant is clearly the only candidate
             (within a quarter of the part, the next one at least twice as far); two equally likely ones are refused, saying so.
  _snap      never applies a move that is not finite.
The original header of asm_model.py follows.

asm_model.py - the assembly document (.gpa) and its mate solver.  No GUI in here.

An assembly is a list of components (each one a .gpd part file with a position and a rotation) plus mates.
  component  {"id", "name", "path", "pos": [x, y, z] (mm), "rv": [rx, ry, rz] (rotation vector, radians), "fixed", "hidden"}
  mate       {"id", "type", "refs": [ref, ref(, ref)], "suppressed", plus the options of the type}
  ref        {"c": component id, "k": "face" | "edge" | "vertex" | "plane" | "origin", "r": data that finds it again in the part}

Mates are solved with a damped least squares (Levenberg-Marquardt) over the position + rotation of every component that is not fixed.
Dragging a component adds a weak pull towards where the mouse is, so it slides along what its mates still allow.
"""
import json
import math
import os

import numpy as np

import refgeo

FUNCS = {k: getattr(math, k) for k in ("sin", "cos", "tan", "atan", "sqrt", "pi", "radians", "degrees", "floor", "ceil")}
FUNCS.update({"abs": abs, "min": min, "max": max, "round": round})

TYPES = ["coincident", "parallel", "perpendicular", "tangent", "concentric", "lock", "distance", "angle", "symmetric"]
LINELIKE = ("axis", "circle", "line")
BASE_N = {"Front": (0.0, -1.0, 0.0), "Top": (0.0, 0.0, 1.0), "Right": (1.0, 0.0, 0.0)}


from asm_model import MateError             # the real class: the window catches this one (the lab copy must not define its own)


# ---------------------------------------------------------------------------------------------- small math
def rodrigues(rv):
    rv = np.asarray(rv, float)
    th = float(np.linalg.norm(rv))
    if th < 1e-12:
        return np.eye(3)
    k = rv / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * (K @ K)


def rotvec(R):
    c = (np.trace(R) - 1) / 2
    th = math.acos(max(-1.0, min(1.0, c)))
    if th < 1e-9:
        return np.zeros(3)
    if abs(th - math.pi) < 1e-6:
        w, v = np.linalg.eigh((R + R.T) / 2)
        k = v[:, -1]
        return k * th
    k = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * math.sin(th))
    return k * th


def unit(v):
    n = float(np.linalg.norm(v))
    return np.asarray(v, float) / n if n > 1e-12 else np.asarray(v, float)


def axis_rotation(axis, ang):
    return rodrigues(unit(axis) * ang)


# ---------------------------------------------------------------------------------------------- entities of a part
def _v(p):
    return np.array([p.X, p.Y, p.Z], float)


def face_entity(face):
    g = face.geom_type.name
    if g == "PLANE":
        return {"t": "plane", "p": _v(face.center()), "n": unit(_v(face.normal_at()))}
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    s = BRepAdaptor_Surface(face.wrapped)
    if g == "CYLINDER":
        cyl = s.Cylinder()
        a = cyl.Axis()
        return {"t": "axis", "p": np.array([a.Location().X(), a.Location().Y(), a.Location().Z()]),
                "d": unit(np.array([a.Direction().X(), a.Direction().Y(), a.Direction().Z()])), "r": cyl.Radius()}
    if g == "SPHERE":
        sp = s.Sphere()
        c = sp.Location()
        return {"t": "sphere", "p": np.array([c.X(), c.Y(), c.Z()]), "r": sp.Radius()}
    raise MateError(f"a {g.lower()} face cannot be mated yet (flat, cylindrical and spherical faces can)")


def edge_entity(edge):
    g = edge.geom_type.name
    if g == "LINE":
        return {"t": "line", "p": _v(edge.position_at(0.5)), "d": unit(_v(edge.tangent_at(0.5)))}
    if g == "CIRCLE":
        return {"t": "circle", "p": _v(edge.arc_center), "d": unit(_v(edge.normal())), "r": edge.radius}
    raise MateError(f"a {g.lower()} edge cannot be mated yet (straight edges and circles can)")


def face_ref(face):
    c = face.center()
    return {"c": [c.X, c.Y, c.Z], "g": face.geom_type.name, "n": list(_v(face.normal_at(c))) if face.geom_type.name == "PLANE" else None}


def edge_ref(edge):
    m = edge.position_at(0.5)
    return {"m": [m.X, m.Y, m.Z], "g": edge.geom_type.name, "d": list(_v(edge.tangent_at(0.5)))}


def vertex_ref(vertex):
    return {"p": list(_v(vertex.center()))}


def _diag(solid):
    try:
        bb = solid.bounding_box()
        return max(1.0, float(np.linalg.norm([bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z])))
    except Exception:
        return 100.0


def _nearest(cands, tol, solid, noun):
    """The thing a mate reference points at.  cands = [(distance from where the reference remembers it, thing)] of the right kind.  Within `tol` mm the
    nearest wins, as always.  Beyond that the part has been edited since the mate was made: the nearest is still taken when it is within a quarter of
    the part and clearly the only candidate (the next one is at least twice as far), so a changed dimension does not break the mate; with two equally
    likely candidates it refuses, saying so, instead of picking one at random."""
    if not cands:
        raise MateError(f"the {noun} it refers to no longer exists")
    cands = sorted(cands, key=lambda c: c[0])
    d0, best = cands[0]
    if d0 <= tol:
        return best
    if d0 > 0.25 * _diag(solid):
        raise MateError(f"the {noun} it refers to no longer exists")
    if len(cands) > 1 and cands[1][0] < 2 * d0:
        raise MateError(f"the {noun} it refers to has moved and more than one {noun} could be it - pick it again")
    return best


def local_entity(ref, solid):
    """The geometry (in the part's own coordinates) that a mate reference points at."""
    k, r = ref["k"], ref.get("r")
    if k == "origin":
        return {"t": "point", "p": np.zeros(3)}
    if k == "plane":
        return {"t": "plane", "p": np.zeros(3), "n": np.array(BASE_N[r["n"]])}
    if solid is None:
        raise MateError("its part has no solid")
    if k == "vertex":
        q = np.array(r["p"])
        return {"t": "point", "p": _nearest([(float(np.linalg.norm(_v(v.center()) - q)), _v(v.center())) for v in solid.vertices()], 1.0, solid, "point")}
    if k == "face":
        c0 = np.array(r["c"])
        cands = []
        for f in solid.faces():
            if f.geom_type.name != r["g"]:
                continue
            if r.get("n") is not None and float(_v(f.normal_at()) @ np.array(r["n"])) < 0.98:
                continue
            cands.append((float(np.linalg.norm(_v(f.center()) - c0)), f))
        return face_entity(_nearest(cands, 2.0, solid, "face"))
    if k == "edge":
        m0 = np.array(r["m"])
        cands = [(float(np.linalg.norm(_v(e.position_at(0.5)) - m0)), e) for e in solid.edges() if e.geom_type.name == r["g"]]
        return edge_entity(_nearest(cands, 2.0, solid, "edge"))
    raise MateError("unknown reference")


def to_world(ent, T):
    R, t = T
    out = dict(ent)
    out["p"] = R @ ent["p"] + t
    if "n" in ent:
        out["n"] = R @ ent["n"]
    if "d" in ent:
        out["d"] = R @ ent["d"]
    if "x" in ent:
        out["x"] = R @ ent["x"]
    return out


# ---------------------------------------------------------------------------------------------- residuals of the mates
def _is_line(e):
    return e["t"] in LINELIKE


def _cross(a, b):
    return list(np.cross(a, b))


def _line_dist(e, p):
    return float(np.linalg.norm(np.cross(p - e["p"], e["d"])))


def residual(mate, E, T=None):
    """The numbers that are zero when the mate is satisfied.  E = the world entities of its refs; T = the world poses of its components."""
    ty = mate["type"]
    a, b = E[0], E[1]
    ta, tb = a["t"], b["t"]
    bad = MateError(f"{ty} cannot mate a {ta} with a {tb}")
    if ty in ("coincident", "concentric"):
        if ty == "concentric" and not (_is_line(a) or ta == "sphere" or ta == "point") :
            raise bad
        if ta == "plane" and tb == "plane" and ty == "coincident":
            sg = 1.0 if mate.get("al", "opposed") == "opposed" else -1.0
            return list(a["n"] + sg * b["n"]) + [float((b["p"] - a["p"]) @ a["n"])]
        if ta in ("point", "sphere") and tb in ("point", "sphere"):
            return list(a["p"] - b["p"])
        if ta == "plane" and tb in ("point", "sphere"):
            return [float((b["p"] - a["p"]) @ a["n"])]
        if tb == "plane" and ta in ("point", "sphere"):
            return [float((a["p"] - b["p"]) @ b["n"])]
        if _is_line(a) and _is_line(b):
            return _cross(a["d"], b["d"]) + _cross(b["p"] - a["p"], a["d"])
        if _is_line(a) and tb in ("point", "sphere"):
            return _cross(b["p"] - a["p"], a["d"])
        if _is_line(b) and ta in ("point", "sphere"):
            return _cross(a["p"] - b["p"], b["d"])
        if ta == "plane" and _is_line(b):
            return [float(b["d"] @ a["n"]), float((b["p"] - a["p"]) @ a["n"])]
        if tb == "plane" and _is_line(a):
            return [float(a["d"] @ b["n"]), float((a["p"] - b["p"]) @ b["n"])]
        raise bad
    if ty == "parallel":
        if ta == "plane" and tb == "plane":
            return _cross(a["n"], b["n"])
        if _is_line(a) and _is_line(b):
            return _cross(a["d"], b["d"])
        if ta == "plane" and _is_line(b):
            return [float(b["d"] @ a["n"])]
        if tb == "plane" and _is_line(a):
            return [float(a["d"] @ b["n"])]
        raise bad
    if ty == "perpendicular":
        if ta == "plane" and tb == "plane":
            return [float(a["n"] @ b["n"])]
        if _is_line(a) and _is_line(b):
            return [float(a["d"] @ b["d"])]
        if ta == "plane" and _is_line(b):
            return _cross(a["n"], b["d"])
        if tb == "plane" and _is_line(a):
            return _cross(b["n"], a["d"])
        raise bad
    if ty == "distance":
        D, s = float(mate["value"]), float(mate.get("sgn", 1.0))
        if ta == "plane" and tb == "plane":
            sg = 1.0 if mate.get("al", "opposed") == "opposed" else -1.0
            return list(a["n"] + sg * b["n"]) + [float((b["p"] - a["p"]) @ a["n"]) - s * D]
        if ta in ("point", "sphere") and tb in ("point", "sphere"):
            return [float(np.linalg.norm(b["p"] - a["p"])) - D]
        if ta == "plane" and tb in ("point", "sphere"):
            return [float((b["p"] - a["p"]) @ a["n"]) - s * D]
        if tb == "plane" and ta in ("point", "sphere"):
            return [float((a["p"] - b["p"]) @ b["n"]) - s * D]
        if _is_line(a) and _is_line(b):
            return _cross(a["d"], b["d"]) + [_line_dist(a, b["p"]) - D]
        if _is_line(a) and tb in ("point", "sphere"):
            return [_line_dist(a, b["p"]) - D]
        if _is_line(b) and ta in ("point", "sphere"):
            return [_line_dist(b, a["p"]) - D]
        for pl, ln in ((a, b), (b, a)):                                # a flat face and a pipe / hole / straight edge: the axis keeps its distance
            if pl["t"] == "plane" and _is_line(ln):                    # to the face, and stays parallel to it (a circle edge: its centre only)
                off = float((ln["p"] - pl["p"]) @ pl["n"]) - s * D
                return [off] if ln["t"] == "circle" else [float(ln["d"] @ pl["n"]), off]
        raise bad
    if ty == "angle":
        A = math.radians(float(mate["value"]))
        ua = a["n"] if ta == "plane" else a.get("d")
        ub = b["n"] if tb == "plane" else b.get("d")
        if ua is None or ub is None:
            raise bad
        return [float(ua @ ub) - math.cos(A)]
    if ty == "tangent":
        ext = mate.get("tk", "ext") == "ext"
        s = float(mate.get("sgn", 1.0))
        for x, y, swap in ((a, b, False), (b, a, True)):
            if x["t"] == "plane" and y["t"] == "axis":
                return [float(y["d"] @ x["n"]), float((y["p"] - x["p"]) @ x["n"]) - s * y["r"]]
            if x["t"] == "plane" and y["t"] == "sphere":
                return [float((y["p"] - x["p"]) @ x["n"]) - s * y["r"]]
        rr = lambda p, q: (p["r"] + q["r"]) if ext else abs(p["r"] - q["r"])
        if ta == "axis" and tb == "axis":
            return _cross(a["d"], b["d"]) + [_line_dist(a, b["p"]) - rr(a, b)]
        if ta == "sphere" and tb == "sphere":
            return [float(np.linalg.norm(b["p"] - a["p"])) - rr(a, b)]
        for x, y in ((a, b), (b, a)):
            if x["t"] == "axis" and y["t"] == "line":
                return _cross(x["d"], y["d"]) + [_line_dist(x, y["p"]) - x["r"]]
            if x["t"] == "axis" and y["t"] == "sphere":
                return [_line_dist(x, y["p"]) - rr(x, y)]
            if x["t"] == "sphere" and y["t"] == "line":
                return [_line_dist(y, x["p"]) - x["r"]]
        raise bad
    if ty == "symmetric":
        c = E[2]
        if c["t"] != "plane":
            raise MateError("symmetric needs a plane (or flat face) as the third item")
        n, p0 = c["n"], c["p"]
        mir = lambda v: v - 2 * float(v @ n) * n
        mirp = lambda p: p - 2 * float((p - p0) @ n) * n
        if ta in ("point", "sphere") and tb in ("point", "sphere"):
            return [float(((a["p"] + b["p"]) / 2 - p0) @ n)] + _cross(b["p"] - a["p"], n)
        if ta == "plane" and tb == "plane":
            return list(b["n"] - mir(a["n"])) + [float((mirp(a["p"]) - b["p"]) @ b["n"])]
        if _is_line(a) and _is_line(b):
            return _cross(b["d"], mir(a["d"])) + _cross(b["p"] - mirp(a["p"]), b["d"])
        raise bad
    raise MateError(f"unknown mate type {ty}")


# ---------------------------------------------------------------------------------------------- exact first moves ("snaps")
# A snap puts the moving component straight onto the answer of ONE mate (where that mate has a closed-form one), so the numeric fit that follows
# starts on top of the solution instead of searching for it from far away.  It is only a starting guess: the fit still checks the result.
# To add one for another mate type: write  fn(mate, E, mover) -> (Rd, pivot, shift) | None  and register it with @snap("type").
# E = world entities of the mate's refs, mover = index (0 / 1) of the ref whose component moves.  The move is  x -> Rd (x - pivot) + pivot + shift.
SNAPS = {}


def snap(*types):
    def reg(fn):
        for t in types:
            SNAPS[t] = fn
        return fn
    return reg


def _turn(a, b):
    """The smallest rotation that turns direction a onto direction b."""
    a, b = unit(a), unit(b)
    ax = np.cross(a, b)
    s = float(np.linalg.norm(ax))
    if s < 1e-12:
        return np.eye(3)
    return rodrigues(ax / s * math.atan2(s, float(a @ b)))


@snap("concentric")
def snap_concentric(mate, E, mover):
    mv, fx = E[mover], E[1 - mover]
    if _is_line(mv) and _is_line(fx):
        d = fx["d"] if float(mv["d"] @ fx["d"]) >= 0 else -fx["d"]          # the nearer way round: never a half turn
        Rd = _turn(mv["d"], d)
        off = fx["p"] - mv["p"]
        return Rd, mv["p"], off - float(off @ fx["d"]) * fx["d"]            # slide across onto the axis, not along it
    if _is_line(mv) and fx["t"] in ("point", "sphere"):
        off = fx["p"] - mv["p"]
        return np.eye(3), mv["p"], off - float(off @ mv["d"]) * mv["d"]
    if _is_line(fx) and mv["t"] in ("point", "sphere"):
        off = fx["p"] - mv["p"]
        return np.eye(3), mv["p"], off - float(off @ fx["d"]) * fx["d"]
    return None


@snap("distance")
def snap_distance(mate, E, mover):
    """A flat face and a pipe / hole / edge / point: turn the axis parallel to the face (smallest turn), then slide along the face's normal."""
    D, s = float(mate["value"]), float(mate.get("sgn", 1.0))
    mv, fx = E[mover], E[1 - mover]
    pl, ot = (mv, fx) if mv["t"] == "plane" else (fx, mv)
    if pl["t"] != "plane" or ot["t"] == "plane":
        return None
    n, p_pl = pl["n"], pl["p"]
    Rd = np.eye(3)
    if ot["t"] in ("axis", "line"):
        if mv is ot:                                # the pipe moves: tip its axis into the face's plane
            d2 = ot["d"] - float(ot["d"] @ n) * n
            if np.linalg.norm(d2) > 1e-9:
                Rd = _turn(ot["d"], d2)
        else:                                                                   # the face moves: tip its normal square to the axis
            n2 = n - float(n @ ot["d"]) * ot["d"]
            if np.linalg.norm(n2) > 1e-9:
                Rd = _turn(n, n2)
                n = unit(n2)
    elif ot["t"] not in ("circle", "point", "sphere"):
        return None
    cur = float((ot["p"] - p_pl) @ n)
    gap = cur - s * D
    if mv is ot:
        return Rd, mv["p"], -gap * n                                            # the pipe / point moves along the normal
    return Rd, mv["p"], gap * n                                                 # the face moves the other way


# ---------------------------------------------------------------------------------------------- the assembly
class Assembly:
    def __init__(self):
        self.components = []
        self.mates = []
        self.counter = {}
        self.patterns = []                 # step 3: component patterns / mirrors (derived instances)
        self.status = {}                   # mate id -> "ok" | "error: ..."
        self.dof = {}                      # component id -> degrees of freedom left
        self.solid_fn = None               # function(component) -> (build123d solid or None) in the part's own coordinates
        self.sims = []                     # linked simulation files (sim_links.py)
        self.renders = []                  # linked render projects (.gpr)
        self.refs = []                     # reference planes / axes of the assembly (see ref_entity)
        self.world_show = {"Front": True, "Top": True, "Right": True, "origin": True}
        self.refgeo_fn = None              # function(component) -> {feature id: entity} reference planes / axes of its part
        self.part_cfg_fn = None            # function(component) -> name of the configuration its part is in now
        self.part_cfgs_fn = None           # function(component) -> [configuration names of its part]
        self.params = {}                   # the assembly's own globals: name -> formula (lengths held in mm)
        self.param_kinds = {}              # name -> "number" / "angle" (a length when absent)
        self.values = {}                   # evaluated globals
        self.exprs = {}                    # formulas that drive a number: "pos:C1:0" "rv:C1:2" "val:M1" "pat:P1:s1" -> text (mm / deg)
        self.cfg = {"active": "Default", "names": ["Default"], "cols": [], "cells": {"Default": {}}}
        self._cache = {}
        self._scales = {}

    # ------------------------------------------------------------------ globals and formulas
    def evaluate_params(self):
        """Resolve the globals (they may use each other, in any order).  Raises MateError."""
        vals, pending = {}, dict(self.params)
        for _ in range(len(pending) + 1):
            for k, e in list(pending.items()):
                try:
                    vals[k] = float(eval(str(e), {"__builtins__": {}}, {**FUNCS, **vals}))
                    del pending[k]
                except NameError:
                    pass
                except Exception as ex:
                    raise MateError(f"global '{k}' = {e}: {ex}")
        if pending:
            raise MateError("globals cannot be resolved (a loop or an unknown name): " + ", ".join(pending))
        self.values = vals

    def eval_expr(self, text):
        try:
            return float(eval(str(text), {"__builtins__": {}}, {**FUNCS, **self.values}))
        except Exception as ex:
            raise MateError(f"'{text}': {ex}")

    def set_target(self, key, v):
        kind, _, rest = key.partition(":")
        if kind in ("pos", "rv"):
            cid, _, i = rest.partition(":")
            c = self.comp(cid)
            if c is not None:
                c[kind][int(i)] = math.radians(v) if kind == "rv" else v
        elif kind == "val":
            m = self.mate(rest)
            if m is not None:
                m["value"] = v
        elif kind == "pat":
            pid, _, field = rest.partition(":")
            p = next((x for x in self.patterns if x["id"] == pid), None)
            if p is not None:
                p[field] = int(round(v)) if field in ("n", "n1", "n2") else v

    def apply_exprs(self):
        """Evaluate the globals and write every formula's number into the component / mate / pattern it drives.  Raises MateError."""
        self.evaluate_params()
        for key, text in list(self.exprs.items()):
            self.set_target(key, self.eval_expr(text))

    def set_expr(self, key, text):
        """text None / '' removes the formula (the number stays as it is)."""
        if text:
            self.exprs[key] = text
        else:
            self.exprs.pop(key, None)

    # ------------------------------------------------------------------ names
    def mate_label(self, m):
        return m.get("name") or f"{m['type'].capitalize()}{m['id'][1:]}"

    def rename(self, kind, iid, new):
        """Give a component, mate, pattern or reference item of the assembly a new name, unique in its group.  Raises MateError.
        Everything else refers to them by id, so the Configurations headers and mates simply show the new name."""
        new = new.strip()
        group = {"comp": self.components, "mate": self.mates, "pattern": self.patterns, "aref": self.refs}.get(kind)
        if group is None:
            raise MateError("this item cannot be renamed")
        item = next((x for x in group if x["id"] == iid), None)
        if item is None:
            raise MateError("no such item")
        if not new:
            raise MateError("the name is empty")
        label = lambda x: (self.mate_label(x) if kind == "mate" else x["name"]).lower()
        if any(label(x) == new.lower() for x in group if x["id"] != iid):
            raise MateError(f"'{new}' is already used")
        item["name"] = new

    # ------------------------------------------------------------------ bookkeeping
    def next_id(self, kind):
        self.counter[kind] = self.counter.get(kind, 0) + 1
        return f"{kind}{self.counter[kind]}"

    def comp(self, cid):
        return next((c for c in self.components if c["id"] == cid), None)

    def mate(self, mid):
        return next((m for m in self.mates if m["id"] == mid), None)

    # ------------------------------------------------------------------ suppressing (an item and what is built on it)
    @staticmethod
    def _spec_refs(spec):
        """The reference dicts inside a pattern's plane / direction / axis choice (a plain "X" / "Front" has none)."""
        out = []
        if isinstance(spec, dict):
            r = spec.get("ref")
            if isinstance(r, dict):
                out.append(r)
        return out

    def _uses(self, ref, cids, rids):
        return ref.get("c") in cids or (ref.get("c") == "@" and (ref.get("r") or {}).get("id") in rids)

    def suppress_closure(self, kind, iid):
        """[(kind, id)] of the items that cannot work once component / reference item / mate / pattern `iid` is suppressed: reference planes and
        axes built on a component, mates that use the component or such a plane, patterns that repeat the component or are placed by it."""
        cids, rids = set(), set()
        if kind == "comp":
            cids.add(iid)
        elif kind == "aref":
            rids.add(iid)
        else:
            return []
        out = []
        grew = True
        while grew:
            grew = False
            for r in self.refs:
                if r["id"] in rids or r.get("suppressed"):
                    continue
                if any(self._uses(x, cids, rids) for x in r["refs"]):
                    rids.add(r["id"])
                    out.append(("aref", r["id"]))
                    grew = True
        for m in self.mates:
            if not m.get("suppressed") and any(self._uses(r, cids, rids) for r in m["refs"]):
                out.append(("mate", m["id"]))
        for p in self.patterns:
            if p.get("suppressed"):
                continue
            seeds = [x for x in p.get("seeds", [])]
            specs = [r for k in ("plane", "dir1", "dir2", "axis") for r in self._spec_refs(p.get(k))]
            if (seeds and all(x in cids for x in seeds)) or any(self._uses(r, cids, rids) for r in specs):
                out.append(("pattern", p["id"]))
        return out

    def _item(self, kind, iid):
        return {"comp": self.comp, "mate": self.mate, "aref": lambda i: next((r for r in self.refs if r["id"] == i), None),
                "pattern": lambda i: next((p for p in self.patterns if p["id"] == i), None)}[kind](iid)

    def set_suppressed(self, kind, iid, flag):
        """Suppress / unsuppress a component, mate, pattern or reference item.  Suppressing also suppresses what depends on it (marked "sup_by", so
        unsuppressing brings back exactly those).  Returns [(kind, id)] of the dependents that changed."""
        it = self._item(kind, iid)
        if it is None:
            return []
        key = f"{kind}:{iid}"
        if flag:
            deps = self.suppress_closure(kind, iid)
            it["suppressed"] = True
            it.pop("sup_by", None)
            for k2, i2 in deps:
                o = self._item(k2, i2)
                o["suppressed"], o["sup_by"] = True, key
            return deps
        it["suppressed"] = False
        it.pop("sup_by", None)
        back = []
        for k2, group in (("comp", self.components), ("mate", self.mates), ("aref", self.refs), ("pattern", self.patterns)):
            for o in group:
                if o.get("sup_by") == key:
                    o["suppressed"] = False
                    o.pop("sup_by", None)
                    back.append((k2, o["id"]))
        return back

    def add_component(self, path, name=None, pos=(0.0, 0.0, 0.0), fixed=False):
        base = os.path.splitext(os.path.basename(path))[0]
        n = 1 + sum(1 for c in self.components if c.get("base") == base)
        c = {"id": self.next_id("C"), "name": name or f"{base}<{n}>", "base": base, "path": path, "pos": list(map(float, pos)),
             "rv": [0.0, 0.0, 0.0], "fixed": bool(fixed), "hidden": False}
        self.components.append(c)
        return c

    def add_mate(self, ty, refs, **kw):
        m = {"id": self.next_id("M"), "type": ty, "refs": refs, "suppressed": False, **kw}
        self.mates.append(m)
        return m

    def remove_component(self, cid):
        self.components = [c for c in self.components if c["id"] != cid and (c.get("derived") or {}).get("src") != cid]
        gone = {r["id"] for r in self.refs if any(x["c"] == cid for x in r["refs"])}
        grew = True
        while grew:                                           # a plane built on a deleted component goes too, and what is built on it
            grew = False
            for r in self.refs:
                if r["id"] not in gone and any(x["c"] == "@" and (x.get("r") or {}).get("id") in gone for x in r["refs"]):
                    gone.add(r["id"])
                    grew = True
        self.refs = [r for r in self.refs if r["id"] not in gone]
        self.mates = [m for m in self.mates if all(r["c"] != cid and not (r["c"] == "@" and (r.get("r") or {}).get("id") in gone) for r in m["refs"])]
        for p in self.patterns:
            p["seeds"] = [x for x in p.get("seeds", []) if x != cid]
        self.patterns = [p for p in self.patterns if p.get("seeds")]

    @staticmethod
    def pose(c):
        return rodrigues(c["rv"]), np.array(c["pos"], float)

    def T4(self, c):
        if c.get("derived"):
            return np.array(c["M"], float)
        R, t = self.pose(c)
        M = np.eye(4)
        M[:3, :3], M[:3, 3] = R, t
        return M

    # ------------------------------------------------------------------ files
    def to_json(self):
        return json.dumps({"version": 1, "components": [c for c in self.components if not c.get("derived")], "mates": self.mates,
                           "counter": self.counter,
                           "patterns": self.patterns, "params": self.params, "kinds": self.param_kinds, "exprs": self.exprs, "cfg": self.cfg_snapshot(), "refs": self.refs, "world_show": self.world_show, "sims": self.sims, "renders": self.renders}, indent=1)

    @classmethod
    def from_json(cls, text):
        import legacy
        d = legacy.flatten(json.loads(text))
        a = cls()
        a.components, a.mates, a.counter, a.patterns = d["components"], d.get("mates", []), d.get("counter", {}), d.get("patterns", [])
        a.cfg = d.get("cfg") or a.cfg
        a.params, a.param_kinds, a.exprs = d.get("params") or {}, d.get("kinds") or {}, d.get("exprs") or {}
        a.refs = d.get("refs", [])
        a.sims = d.get("sims") or []
        a.renders = d.get("renders") or []
        a.world_show = {**a.world_show, **d.get("world_show", {})}
        return a

    # ------------------------------------------------------------------ geometry of the references
    def ref_entity(self, rid, poses=None, depth=0):
        """World geometry of an assembly reference plane / axis (it follows the components it is built on)."""
        f = next((r for r in self.refs if r["id"] == rid), None)
        if f is None:
            raise MateError("the reference plane / axis it uses was deleted")
        if f.get("suppressed"):
            raise MateError(f"{f['name']} is suppressed")
        if depth > 8:
            raise MateError("reference planes / axes refer to each other in a loop")
        ents = [self.entity(r, poses, depth + 1) for r in f["refs"]]
        try:
            num = lambda x: float(eval(str(x), {"__builtins__": {}}, {}))
            if f["kind"] == "refplane":
                return refgeo.compute_plane(f.get("ptype"), ents, num(f.get("d", 10)), num(f.get("ang", 45)), bool(f.get("flip")))
            return refgeo.compute_axis(f.get("ptype"), ents)
        except refgeo.RefError as ex:
            raise MateError(f"{f['name']}: {ex}")
        except Exception as ex:
            raise MateError(f"{f['name']}: {ex}")

    def entity(self, ref, poses=None, depth=0):
        if ref["c"] == "@":                                   # the assembly itself: its planes, origin, reference planes / axes
            k, r = ref["k"], ref.get("r") or {}
            if k == "origin":
                return {"t": "point", "p": np.zeros(3)}
            if k == "plane" and "n" in r:
                return {"t": "plane", "p": np.zeros(3), "n": np.array(BASE_N[r["n"]]), "x": np.array([1.0, 0, 0])}
            if k in ("plane", "axis") and "id" in r:
                return self.ref_entity(r["id"], poses, depth)
            raise MateError("unknown assembly reference")
        c = self.comp(ref["c"])
        if c is None:
            raise MateError("a component it refers to was deleted")
        if ref["k"] in ("plane", "axis") and "id" in (ref.get("r") or {}):      # a reference plane / axis of the part
            loc = (self.refgeo_fn(c) if self.refgeo_fn else {}).get(ref["r"]["id"])
            if loc is None:
                raise MateError("the plane / axis it refers to no longer exists in the part")
            T = (poses or {}).get(c["id"]) or self.pose(c)
            return to_world(loc if loc["t"] != "plane" else loc, T)
        key = (c["id"], json.dumps(ref, sort_keys=True, default=float))
        solid = self.solid_fn(c) if self.solid_fn else None
        hit = self._cache.get(key)
        if hit is None or hit[0] is not solid:
            hit = (solid, local_entity(ref, solid))
            self._cache[key] = hit
        T = (poses or {}).get(c["id"]) or self.pose(c)
        return to_world(hit[1], T)

    def world_entities(self, mate, poses=None):
        return [self.entity(r, poses) for r in mate["refs"]]

    def mate_residual(self, mate, poses=None):
        if mate["type"] == "lock":
            if any(r["c"] == "@" for r in mate["refs"]):
                raise MateError("Lock needs two components (not the assembly planes)")
            ca, cb = self.comp(mate["refs"][0]["c"]), self.comp(mate["refs"][1]["c"])
            if ca is None or cb is None:
                raise MateError("a component it refers to was deleted")
            Ra, ta = (poses or {}).get(ca["id"]) or self.pose(ca)
            Rb, tb = (poses or {}).get(cb["id"]) or self.pose(cb)
            rel = mate["rel"]
            Rr = Ra.T @ Rb
            return list(Ra.T @ (tb - ta) - np.array(rel["t"])) + list(rotvec(np.array(rel["R"]).T @ Rr))
        return residual(mate, self.world_entities(mate, poses))

    # ------------------------------------------------------------------ creating a mate with sensible defaults
    def prepare(self, mate):
        """Fill in the options of a new mate from how the two items lie right now (aligned or opposed, which side, value).  Anything that goes wrong on
        the way is a MateError with a plain message (the window shows those), never a Python error."""
        try:
            return self._prepare_core(mate)
        except MateError:
            raise
        except Exception as ex:
            raise MateError(f"{mate.get('type')} cannot be set up for these items ({type(ex).__name__}: {str(ex)[:80]})")

    def _prepare_core(self, mate):
        ty = mate["type"]
        if ty == "lock":
            if any(r["c"] == "@" for r in mate["refs"]):
                raise MateError("Lock needs two components (not the assembly planes)")
            ca, cb = self.comp(mate["refs"][0]["c"]), self.comp(mate["refs"][1]["c"])
            Ra, ta = self.pose(ca)
            Rb, tb = self.pose(cb)
            mate["rel"] = {"R": (Ra.T @ Rb).tolist(), "t": list(Ra.T @ (tb - ta))}
            return mate
        E = self.world_entities(mate)
        a, b = E[0], E[1]
        if a["t"] == "plane" and b["t"] == "plane":
            mate["al"] = "opposed" if float(a["n"] @ b["n"]) <= 0 else "aligned"
        if ty == "distance":
            if a["t"] == "plane" and b["t"] == "plane":
                d = float((b["p"] - a["p"]) @ a["n"])
            elif a["t"] == "plane":
                d = float((b["p"] - a["p"]) @ a["n"])
            elif b["t"] == "plane":
                d = float((a["p"] - b["p"]) @ b["n"])
            elif a["t"] in LINELIKE and b["t"] in LINELIKE:
                d = _line_dist(a, b["p"])
            elif a["t"] in LINELIKE:
                d = _line_dist(a, b["p"])
            elif b["t"] in LINELIKE:
                d = _line_dist(b, a["p"])
            else:
                d = float(np.linalg.norm(b["p"] - a["p"]))
            mate["sgn"] = -1.0 if d < 0 else 1.0
            mate.setdefault("value", round(abs(d), 4))
        if ty == "angle":
            ua = a["n"] if a["t"] == "plane" else a.get("d")
            ub = b["n"] if b["t"] == "plane" else b.get("d")
            if ua is None or ub is None:
                raise MateError(f"angle cannot mate a {a['t']} with a {b['t']}: it needs flat faces, straight edges, circles or cylinders")
            mate.setdefault("value", round(math.degrees(math.acos(max(-1, min(1, float(ua @ ub))))), 3))
        if ty == "tangent":
            for x, y in ((a, b), (b, a)):
                if x["t"] == "plane" and y["t"] in ("axis", "sphere"):
                    mate["sgn"] = -1.0 if float((y["p"] - x["p"]) @ x["n"]) < 0 else 1.0
            if a["t"] in ("axis", "sphere") and b["t"] in ("axis", "sphere"):
                d = _line_dist(a, b["p"]) if a["t"] == "axis" else float(np.linalg.norm(b["p"] - a["p"]))
                mate["tk"] = "ext" if abs(d - (a["r"] + b["r"])) <= abs(d - abs(a["r"] - b["r"])) else "int"
        return mate

    # ------------------------------------------------------------------ the solver
    def active_mates(self):
        sup = {c["id"] for c in self.components if c.get("suppressed")}
        return [m for m in self.mates if not m.get("suppressed") and not any(r["c"] in sup for r in m["refs"])]

    def floating(self):
        return [c for c in self.components if not c.get("fixed") and not c.get("derived") and not c.get("suppressed")]

    def cluster(self, cid):
        """Ids of the floating components that are tied to component cid through mates (cid included)."""
        fl = {c["id"] for c in self.floating()}
        seen, todo = {cid}, [cid]
        while todo:
            cur = todo.pop()
            for m in self.active_mates():
                ids = {r["c"] for r in m["refs"]}
                if cur in ids:
                    for o in ids & fl:
                        if o not in seen:
                            seen.add(o)
                            todo.append(o)
        return seen & (fl | {cid})

    def solve(self, drag=None, weight=0.02, extra=None, iters=80, limit=None, grab=None):
        """Move the floating components so that all mates hold (see _solve_core).  Either it returns, or it raises a MateError - and in that case no
        component has been left half way: every pose is put back as it was, whatever went wrong inside (a Python error becomes a MateError too)."""
        before = {c["id"]: (list(c["pos"]), list(c["rv"])) for c in self.components if "pos" in c and "rv" in c}
        for cid, (pos, rv) in before.items():
            if not (np.all(np.isfinite(pos)) and np.all(np.isfinite(rv))):
                raise MateError(f"{(self.comp(cid) or {}).get('name', cid)} has a position or rotation that is not a number")
        try:
            return self._solve_core(drag, weight, extra, iters, limit, grab)
        except Exception as ex:
            for c in self.components:
                if c["id"] in before:
                    c["pos"], c["rv"] = list(before[c["id"]][0]), list(before[c["id"]][1])
            if isinstance(ex, MateError):
                raise
            raise MateError(f"the solver stopped on an unexpected problem ({type(ex).__name__}: {str(ex)[:80]}); the parts were put back where they were")

    def _solve_core(self, drag=None, weight=0.02, extra=None, iters=80, limit=None, grab=None):
        """Move the floating components so that all mates hold.  drag = {component id: (R, t)} pulls those gently to a target pose.
        Returns True when every mate is satisfied.  Fills self.status and self.dof."""
        if drag is None and (self.params or self.exprs):
            self.apply_exprs()
        fl = [c for c in self.floating() if limit is None or c["id"] in limit]
        idx = {c["id"]: i for i, c in enumerate(fl)}
        mates = self.active_mates() + list(extra or [])
        if limit is not None:
            mates = [m for m in mates if any(r["c"] in limit for r in m["refs"])]
        x = np.concatenate([np.concatenate([c["pos"], c["rv"]]) for c in fl]) if fl else np.zeros(0)
        targets = {}
        for cid, (R, t) in (drag or {}).items():
            if cid in idx:
                targets[idx[cid]] = np.concatenate([t, rotvec(R)])

        def poses_of(x):
            return {c["id"]: (rodrigues(x[6 * i + 3:6 * i + 6]), x[6 * i:6 * i + 3]) for i, c in enumerate(fl)}

        if targets and mates and fl:           # a drag: glide along what the mates leave free, never pull against them
            return self._drag_step(fl, mates, {cid: v for cid, v in (drag or {}).items() if cid in idx}, extra, limit, grab or {})

        if not mates or not fl:
            if drag:
                for cid, (R, t) in drag.items():
                    c = self.comp(cid)
                    if c is not None and not c.get("fixed"):
                        c["pos"], c["rv"] = list(map(float, t)), list(map(float, rotvec(R)))
            self.status = {m["id"]: "ok" for m in self.mates}
            self.dof = {c["id"]: (0 if c.get("fixed") else 6) for c in self.components if not c.get("derived")}
            return True

        start = {c["id"]: (list(c["pos"]), list(c["rv"])) for c in fl}
        failed = {}
        try:
            together = self._fit(fl, mates, iters)
        except MateError:
            together = False
        keep = mates
        if not together:
            # Something disagrees.  Solve ONE MATE AT A TIME in the order they were made (a mate that is being added or edited counts as the newest):
            # every earlier mate is trusted and stays exact, the next one is solved with them as hard constraints, and one that cannot be met is
            # left out and reported - it never drags the others out of place.
            for c in fl:
                c["pos"], c["rv"] = list(start[c["id"]][0]), list(start[c["id"]][1])
            keep, failed = self._solve_in_order(fl, mates, iters, limit)
        x = np.concatenate([np.concatenate([c["pos"], c["rv"]]) for c in fl])

        def poses_of(x):
            return {c["id"]: (rodrigues(x[6 * i + 3:6 * i + 6]), x[6 * i:6 * i + 3]) for i, c in enumerate(fl)}

        # report
        P = poses_of(x)
        ok = not failed
        if limit is None:
            self.status = {}
        live = self.active_mates()
        for m in list(self.mates) + [e for e in (extra or []) if e not in self.mates]:
            if limit is not None and m not in mates:
                continue
            if m.get("suppressed") or (m not in live and m not in (extra or [])):
                self.status[m["id"]] = "suppressed"
                continue
            if m["id"] in failed:
                self.status[m["id"]] = failed[m["id"]]
                continue
            try:
                rr = np.array(self.mate_residual(m, P), float)
            except MateError as ex:
                self.status[m["id"]] = f"error: {ex}"
                ok = False
                continue
            if rr.size and float(np.max(np.abs(rr))) > 1e-4:
                self.status[m["id"]] = "error: this mate cannot be satisfied together with the others"
                ok = False
            else:
                self.status[m["id"]] = "ok"
        if limit is None:
            self.dof = self.degrees_of_freedom(fl, keep, x, poses_of)
        return ok

    CONFLICT = "error: conflicts with the mates before it (they were kept exact, this one was left out)"
    NO_FIT = "error: could not be solved (no position was found where it holds)"

    def _snap(self, fl, mates):
        """Give each mate that has an exact first move (SNAPS) that move, on a component no other mate of this set touches (so it cannot undo them)."""
        ids = {c["id"] for c in fl}
        uses = {}
        for m in mates:
            for cid in {r["c"] for r in m["refs"]}:
                uses[cid] = uses.get(cid, 0) + 1
        for m in mates:
            fn = SNAPS.get(m["type"])
            if fn is None or len(m["refs"]) < 2 or m["refs"][0]["c"] == m["refs"][1]["c"]:
                continue
            mover = next((i for i in (0, 1) if m["refs"][i]["c"] in ids and uses.get(m["refs"][i]["c"]) == 1), None)
            if mover is None:
                continue
            try:
                E = self.world_entities(m)
                if all(abs(v) <= 1e-4 for v in residual(m, E)):
                    continue
                out = fn(m, E, mover)
            except MateError:
                continue
            if out is None:
                continue
            Rd, pivot, shift = out
            if not (np.all(np.isfinite(Rd)) and np.all(np.isfinite(pivot)) and np.all(np.isfinite(shift))):
                continue
            c = self.comp(m["refs"][mover]["c"])
            R, t = self.pose(c)
            c["pos"] = list(map(float, Rd @ (t - pivot) + pivot + shift))
            c["rv"] = list(map(float, rotvec(Rd @ R)))

    RESTARTS = 8                    # how many other starting poses _fit may try when the first one does not end on the mates (not while dragging)
    _in_drag = False

    def _fit(self, fl, mates, iters=80, restarts=None):
        """Least squares on the poses of the components fl so that all the mates hold; writes the poses back.  True when every mate is met.
        Local search first (_lm); when that stalls off the mates, other starting poses (_restarts) - never while dragging, which must stay quick."""
        self._snap(fl, mates)
        L = np.array([self._comp_scale(c) for c in fl], float)
        R0 = [rodrigues(c["rv"]) for c in fl]
        t0 = [np.array(c["pos"], float) for c in fl]
        R, t, r = self._run(fl, mates, iters, L, R0, t0)
        ok = bool(r.size == 0 or float(np.max(np.abs(r))) <= 1e-4)
        if not ok:
            n = self.RESTARTS if (restarts is None and not self._in_drag) else (restarts or 0)
            if n:
                got = self._restarts(fl, mates, iters, L, R0, t0, R, t, r, n)
                if got is not None:
                    R, t, r, ok = got
        for i, c in enumerate(fl):
            c["pos"], c["rv"] = list(map(float, t[i])), list(map(float, rotvec(R[i])))
        return ok

    def _run(self, fl, mates, iters, L, R, t):
        """Turn first, then slide.  The rows of the residual that do not change when the components are moved far apart (parallel, perpendicular, angle,
        the 'normals agree' part of a face on a face ...) depend on the turns alone; those are solved first, on their own, so the part is facing the right
        way before the distances are asked for.  Fitting everything at once can stall where a distance is met by a wrong tilt (two edges ended up
        crossing at 68 degrees exactly 7 mm apart, with the part 1.5 m away).  Then the whole fit runs from there.  -> (R, t, residual)."""
        ids = [c["id"] for c in fl]

        def res(R_, t_):
            P = {ids[i]: (R_[i], t_[i]) for i in range(len(fl))}
            out = []
            for m in mates:
                out += self.mate_residual(m, P)
            return np.array(out, float)

        r0 = res(R, t)
        if r0.size and float(np.max(np.abs(r0))) > 1e-4:
            far = [np.array([371.0, -253.0, 417.0]) * (1 + 0.7 * i) * L[i] * 0.01 + 100 * L[i] * np.array([1.0, 0.6, -0.8]) * (i + 1) for i in range(len(fl))]
            r1 = res(R, [t[i] + far[i] for i in range(len(fl))])
            rows = np.abs(r1 - r0) < 1e-9 * (1 + np.abs(r0))
            if rows.any() and not rows.all() and float(np.max(np.abs(r0[rows]))) > 1e-4:
                R, t, _ = self._lm(fl, mates, iters, L, R, t, rows)                                   # 1. turn
                slide = np.tile([True, True, True, False, False, False], len(fl))
                R, t, r2 = self._lm(fl, mates, iters, L, R, t, None, slide)                            # 2. slide, keeping that facing
                if r2.size == 0 or float(np.max(np.abs(r2))) <= 1e-4:
                    return R, t, r2
        return self._lm(fl, mates, iters, L, R, t)                                                    # 3. everything together, from where that left it

    def _lm(self, fl, mates, iters, L, R, t, rows=None, free=None):
        """Levenberg-Marquardt from the poses (R, t).  The unknowns are small moves made ON TOP of the current pose - a shift in mm and a turn about the
        world axes - with the turn counted as arm-length mm (radians x the part's size L), so a step of one unit is the same distance whether it slides
        or turns and the damped step is the smallest MOVE, not the smallest number (before, 1 rad cost as much as 1 mm, so a one-number mate such as a
        point on a face was met by spinning the part).  Updating by composition means no angle ever wraps or flips near half a turn.
        rows = which rows of the residual to fit (None: all of them), free = which of the 6n unknowns may move (None: all of them), so a stage can fit
        only the facing, or only the sliding.  Returns (R, t, residual)."""
        n = len(fl)
        ids = [c["id"] for c in fl]
        R, t = [np.array(x, float) for x in R], [np.array(x, float) for x in t]

        def res(R_, t_):
            P = {ids[i]: (R_[i], t_[i]) for i in range(n)}
            out = []
            for m in mates:
                out += self.mate_residual(m, P)
            out = np.array(out, float)
            return out if rows is None else out[rows]

        def moved(y):
            return ([rodrigues(y[6 * i + 3:6 * i + 6] / L[i]) @ R[i] for i in range(n)], [t[i] + y[6 * i:6 * i + 3] for i in range(n)])

        r = res(R, t)
        lam, h = 1e-3, 1e-6
        for _ in range(iters):
            if r.size == 0 or float(np.max(np.abs(r))) < 1e-10 or not np.all(np.isfinite(r)):
                break
            J = np.zeros((len(r), 6 * n))
            for j in range(6 * n):
                if free is not None and not free[j]:                    # a stage that only slides: the turns stay as they are
                    continue
                y = np.zeros(6 * n)
                y[j] = h
                Rp, tp = moved(y)
                J[:, j] = (res(Rp, tp) - r) / h
            g = J.T @ r
            if np.linalg.norm(g, np.inf) < 1e-12:
                break
            JTJ = J.T @ J
            sc = max(float(np.max(np.diag(JTJ))), 1e-12)               # damping relative to the size of the Jacobian, so it means the same on every problem
            improved = False
            for _k in range(14):
                try:
                    dy = -np.linalg.solve(JTJ + lam * sc * np.eye(6 * n), g)
                except np.linalg.LinAlgError:
                    lam *= 10
                    continue
                if not np.all(np.isfinite(dy)):
                    lam *= 10
                    continue
                Rn, tn = moved(dy)
                r2 = res(Rn, tn)
                if np.all(np.isfinite(r2)) and float(r2 @ r2) < float(r @ r):
                    R, t, r, improved = Rn, tn, r2, True
                    lam = max(lam / 3, 1e-12)
                    break
                lam *= 4
            if not improved:
                break
        return R, t, r

    def _restarts(self, fl, mates, iters, L, R0, t0, R, t, r, count):
        """The first fit ended off the mates (a local minimum, or a start the local search cannot leave).  Try other starting poses for the components
        of the mates that are still unmet: small nudges first, then half turns about each axis (the other side of an opposed / aligned choice), then
        large random ones.  Always the same sequence, so a solve is repeatable.  -> (R, t, residual, True) of the first that ends on every mate, else None."""
        ids = [c["id"] for c in fl]
        bad = set()
        P = {ids[i]: (R[i], t[i]) for i in range(len(fl))}
        for m in mates:
            try:
                rr = np.array(self.mate_residual(m, P), float)
            except MateError:
                return None
            if rr.size and float(np.max(np.abs(rr))) > 1e-4:
                bad |= {x["c"] for x in m["refs"]} & set(ids)
        if not bad:
            bad = set(ids)
        pick = [i for i in range(len(fl)) if ids[i] in bad]
        rng = np.random.default_rng(20240607)
        for k in range(count):
            Rs, ts = [x.copy() for x in R0], [x.copy() for x in t0]
            for i in pick:
                if k % 8 in (3, 4, 5) and len(pick) == 1:                      # a half turn about the part's own x, y or z
                    Rs[i] = Rs[i] @ rodrigues(np.eye(3)[k % 8 - 3] * math.pi)
                else:
                    big = 1.0 if k % 8 < 3 else 2.0
                    ax = rng.normal(size=3)
                    ax /= max(float(np.linalg.norm(ax)), 1e-12)
                    Rs[i] = rodrigues(ax * rng.uniform(0.15, 0.5) * big * (1 + k // 8)) @ Rs[i]
                    d = rng.normal(size=3)
                    ts[i] = ts[i] + d / max(float(np.linalg.norm(d)), 1e-12) * rng.uniform(0.05, 0.3) * big * L[i]
            Rk, tk, rk = self._run(fl, mates, iters, L, Rs, ts)
            if rk.size == 0 or float(np.max(np.abs(rk))) <= 1e-4:
                return Rk, tk, rk, True
        return None

    def _solve_in_order(self, fl, mates, iters, limit):
        """The mates in order, each added to the ones already holding: only the components the new mate can move (those tied to it through the
        earlier mates) are solved, and a mate that cannot be met is rolled back and reported.  -> (the mates that hold, {mate id: message})."""
        floating = {c["id"]: c for c in fl}
        held, failed = [], {}
        for m in mates:
            ids = {r["c"] for r in m["refs"]} & set(floating)
            grew = True
            while grew:                                        # everything tied to those components through the mates that already hold
                grew = False
                for h in held:
                    hid = {r["c"] for r in h["refs"]} & set(floating)
                    if hid & ids and not hid <= ids:
                        ids |= hid
                        grew = True
            trial = held + [m]
            sub = [floating[i] for i in floating if i in ids]
            before = {c["id"]: (list(c["pos"]), list(c["rv"])) for c in sub}
            try:
                met = self._fit(sub, [t for t in trial if {r["c"] for r in t["refs"]} & ids], iters) if sub else self._met(trial)
            except MateError as ex:
                met = False
                failed[m["id"]] = f"error: {ex}"
            if met:
                held.append(m)
                continue
            for c in sub:                                      # roll back: this mate does not fit with the earlier ones
                c["pos"], c["rv"] = before[c["id"]]
            tied = any({r["c"] for r in h["refs"]} & ids for h in held)         # earlier mates act on these components: a real conflict
            failed.setdefault(m["id"], self.CONFLICT if tied else self.NO_FIT)
        return held, failed

    def _met(self, mates):
        try:
            return all(not len(r) or float(np.max(np.abs(r))) <= 1e-4 for r in (np.array(self.mate_residual(m), float) for m in mates))
        except MateError:
            return False

    def drag_reset(self):
        """A new drag starts: forget where the mouse target was."""
        self._drag_last = {}

    def _comp_scale(self, c):
        """A typical size of a component (half its bounding diagonal): turns radians into the same units as millimetres when steps are measured."""
        try:
            solid = self.solid_fn(c)
        except Exception:
            return 100.0
        hit = self._scales.get(c["id"])
        if hit is not None and hit[0] is solid:                  # the bounding box is slow (0.1 s on a big part): once per solid, not once per drag step
            return hit[1]
        try:
            bb = solid.bounding_box()
            v = max(1.0, 0.5 * float(np.linalg.norm([bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z])))
        except Exception:
            return 100.0
        self._scales[c["id"]] = (solid, v)
        return v

    def _drag_step(self, fl, mates, drag, extra, limit, grab, rounds=8):
        """Follow the mouse (see _drag_step_core); while it runs, _fit does not try other starting poses (a drag must stay quick)."""
        was, self._in_drag = self._in_drag, True
        try:
            return self._drag_step_core(fl, mates, drag, extra, limit, grab, rounds)
        finally:
            self._in_drag = was

    def _drag_step_core(self, fl, mates, drag, extra, limit, grab, rounds=8):
        """Follow the mouse while the mates hold.  The old way pulled the component towards the mouse with a soft spring and then snapped the mates
        back: pull a tube against the face it butts on and the spring won out over a tilt of the face, the snap got stuck in the tilted pose and
        the part sat half through the other.  Now only the part of the wanted move that the mates leave FREE is taken (their null space, from the
        Jacobian), one small step at a time, and each step is snapped back onto the mates exactly - so a push into a face does nothing, a push along
        it slides, and where the part can only roll or swing it follows that motion smoothly."""
        n = 6 * len(fl)
        L = np.array([self._comp_scale(c) for c in fl])
        W = np.concatenate([[1, 1, 1, L[i], L[i], L[i]] for i in range(len(fl))])          # radians count as arm-length millimetres
        mates_all = list(mates)

        def getx():
            return np.concatenate([np.concatenate([c["pos"], c["rv"]]) for c in fl])

        def put(x):
            for i, c in enumerate(fl):
                c["pos"], c["rv"] = list(map(float, x[6 * i:6 * i + 3])), list(map(float, x[6 * i + 3:6 * i + 6]))

        def poses_of(x):
            return {c["id"]: (rodrigues(x[6 * i + 3:6 * i + 6]), x[6 * i:6 * i + 3]) for i, c in enumerate(fl)}

        def res(x):
            P = poses_of(x)
            out = []
            for m in mates_all:
                out += self.mate_residual(m, P)
            return np.array(out, float)

        def want(x):
            """The step the mouse asks for, in the weighted coordinates (translation difference, world-frame turn difference)."""
            d = np.zeros(n)
            for i, c in enumerate(fl):
                if c["id"] in drag:
                    Rt, tt = drag[c["id"]]
                    Rc = rodrigues(x[6 * i + 3:6 * i + 6])
                    d[6 * i:6 * i + 3] = tt - x[6 * i:6 * i + 3]
                    d[6 * i + 3:6 * i + 6] = L[i] * rotvec(Rt @ Rc.T)
            return d

        def to_x(dw, x):
            """Weighted step -> new x (turn applied as a rotation on top of the current one, so nothing wraps)."""
            xn = x.copy()
            for i in range(len(fl)):
                xn[6 * i:6 * i + 3] += dw[6 * i:6 * i + 3]
                th = dw[6 * i + 3:6 * i + 6] / L[i]
                xn[6 * i + 3:6 * i + 6] = rotvec(rodrigues(th) @ rodrigues(x[6 * i + 3:6 * i + 6]))
            return xn

        # how far the mouse itself travelled since the last call: the part never moves much faster than that, so a target that cannot be reached
        # (pushed into a face, past the end of a roll) makes it hold still or creep instead of jumping to whichever pose happens to be nearest
        last = getattr(self, "_drag_last", None)
        if last is None:
            last = self._drag_last = {}
        allow = 0.5
        for i, c in enumerate(fl):
            if c["id"] not in drag:
                continue
            Rt, tt = drag[c["id"]]
            Rl, tl = last.get(c["id"]) or (rodrigues(c["rv"]), np.array(c["pos"], float))
            if c["id"] in grab:
                lh = np.asarray(grab[c["id"]], float)
                trav = float(np.linalg.norm((Rt @ lh + tt) - (Rl @ lh + tl)))
            else:
                trav = float(np.linalg.norm(tt - tl)) + L[i] * float(np.linalg.norm(rotvec(Rt @ Rl.T)))
            allow += 1.5 * trav
            last[c["id"]] = (Rt, np.array(tt, float))
        ok = True
        x = getx()
        try:
            r0 = res(x)
        except MateError:
            raise
        if len(r0) and float(np.max(np.abs(r0))) > 1e-4:           # not on the mates yet (a mate was just added / edited): settle first
            self.solve(extra=extra, iters=60, limit=limit)
            x = getx()
        for _ in range(rounds):
            r = res(x)
            J = np.zeros((len(r), n))
            for j in range(n):
                h = (1e-6 if j % 6 < 3 else 1e-7)
                xp = x.copy()
                xp[j] += h
                J[:, j] = (res(xp) - r) / h
            Jw = J / W                                                  # columns in weighted units
            if len(r):
                u, sv, vt = np.linalg.svd(Jw, full_matrices=True)
                tol = 1e-6 * max(1.0, sv.max() if len(sv) else 1.0)
                rank = int(np.sum(sv > tol))
                N = vt[rank:].T
            else:
                N = np.eye(n)
            d = want(x)
            step = np.zeros(n)
            if N.size:
                # best follow of the mouse inside the free motions: the grabbed point counts most (so a part that can only roll or swing still
                # follows the point you hold), the pose as a whole a little (so the free directions that do not move that point settle at the target)
                rows, rhs = [], []
                for i, c in enumerate(fl):
                    if c["id"] not in drag:
                        continue
                    sl = slice(6 * i, 6 * i + 6)
                    eps = 0.15 if c["id"] in grab else 1.0
                    rows.append(eps * np.eye(n)[sl]); rhs.append(eps * d[sl])
                    if c["id"] in grab:
                        Rt, tt = drag[c["id"]]
                        Rc, tc = rodrigues(x[6 * i + 3:6 * i + 6]), x[6 * i:6 * i + 3]
                        lh = np.asarray(grab[c["id"]], float)
                        rr = Rc @ lh
                        A = np.zeros((3, n))
                        A[:, 6 * i:6 * i + 3] = np.eye(3)
                        A[:, 6 * i + 3:6 * i + 6] = -np.array([[0, -rr[2], rr[1]], [rr[2], 0, -rr[0]], [-rr[1], rr[0], 0]]) / L[i]
                        rows.append(A); rhs.append((Rt @ lh + tt) - (rr + tc))
                if rows:
                    M = np.vstack(rows) @ N
                    z = np.linalg.lstsq(M, np.concatenate(rhs), rcond=1e-8)[0]
                    step = N @ z
            size = float(np.linalg.norm(step))
            if size < 1e-6:
                break
            cap = min(0.25 * max(L), allow)                             # one step is never more than about a quarter of the part, nor more than the mouse moved
            if cap < 1e-9:
                break
            if size > cap:
                step *= cap / size
            xn = to_x(step, x)
            put(xn)
            ok = self.solve(extra=extra, iters=40, limit=limit)         # snap exactly onto the mates (no pull)
            if not ok:                                                  # could not follow: stay where we were
                put(x)
                self.solve(extra=extra, iters=40, limit=limit)
                return False
            xs = getx()
            moved = float(np.linalg.norm((xs - x) * W))
            allow -= max(moved, min(size, cap) * 0.0)
            x = xs
            if moved < 1e-4:
                break
        return ok

    def degrees_of_freedom(self, fl, mates, x, poses_of):
        out = {c["id"]: (0 if c.get("fixed") else 6) for c in self.components if not c.get("derived")}
        if not fl or not mates:
            return out
        try:
            def f(x_):
                P = poses_of(x_)
                r = []
                for m in mates:
                    r += self.mate_residual(m, P)
                return np.array(r, float)
            r0 = f(x)
            J = np.zeros((len(r0), len(x)))
            for j in range(len(x)):
                h = 1e-6 if j % 6 < 3 else 1e-7
                xp = x.copy()
                xp[j] += h
                J[:, j] = (f(xp) - r0) / h
            if len(r0) == 0:
                return out
            u, s, vt = np.linalg.svd(J, full_matrices=True)
            tol = 1e-6 * max(1.0, s.max() if len(s) else 1.0)
            rank = int(np.sum(s > tol))
            N = vt[rank:].T                                   # directions the components may still move in
            for i, c in enumerate(fl):
                blk = N[6 * i:6 * i + 6, :]
                out[c["id"]] = int(np.linalg.matrix_rank(blk, tol=1e-6)) if blk.size else 0
        except Exception:
            pass
        return out



# ---------------------------------------------------------------------------------------------- configurations of an assembly
# columns of the table:   "c:<component>"  which configuration of the part it uses     "x:<component>"  component suppressed
#                         "m:<mate>"       mate suppressed                              "v:<mate>"       distance / angle value
#                         "n:<pattern>:<field>"  a number of a pattern (copies, spacing, angle)
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cfg_read(self, key):
    kind, _, rest = key.partition(":")
    if kind in ("c", "x"):
        c = self.comp(rest)
        if c is None or c.get("derived"):
            return None
        if kind == "x":
            return bool(c.get("suppressed"))
        return c.get("config") or (self.part_cfg_fn(c) if self.part_cfg_fn else None)
    if kind in ("m", "v"):
        m = self.mate(rest)
        if m is None:
            return None
        if kind == "m":
            return bool(m.get("suppressed"))
        return m.get("value")
    if kind == "n":
        pid, _, field = rest.partition(":")
        p = next((x for x in self.patterns if x["id"] == pid), None)
        return None if p is None else p.get(field)
    return None


def _cfg_write(self, key, val):
    kind, _, rest = key.partition(":")
    if val is None:
        return
    if kind in ("c", "x"):
        c = self.comp(rest)
        if c is None:
            return
        if kind == "x":
            c["suppressed"] = bool(val)
        else:
            c["config"] = str(val)
    elif kind in ("m", "v"):
        m = self.mate(rest)
        if m is None:
            return
        if kind == "m":
            m["suppressed"] = bool(val)
        elif _num(val) is not None:
            m["value"] = float(val)
            self.exprs.pop(f"val:{rest}", None)
    elif kind == "n":
        pid, _, field = rest.partition(":")
        p = next((x for x in self.patterns if x["id"] == pid), None)
        if p is not None and _num(val) is not None:
            p[field] = int(round(float(val))) if field in ("n", "n1", "n2") else float(val)
            self.exprs.pop(f"pat:{pid}:{field}", None)


def _cfg_label(self, key):
    kind, _, rest = key.partition(":")
    if kind in ("c", "x"):
        c = self.comp(rest)
        nm = c["name"] if c else rest
        return f"Configuration@{nm}" if kind == "c" else f"$SUPPRESS@{nm}"
    if kind in ("m", "v"):
        m = self.mate(rest)
        nm = self.mate_label(m) if m else rest
        return f"$SUPPRESS@{nm}" if kind == "m" else f"Value@{nm}"
    if kind == "n":
        pid, _, field = rest.partition(":")
        p = next((x for x in self.patterns if x["id"] == pid), None)
        return f"{ {'n': 'Copies', 'n1': 'Copies', 's1': 'Spacing', 'angle': 'Angle', 'n2': 'Copies 2', 's2': 'Spacing 2'}.get(field, field) }@{p['name'] if p else pid}"
    return key


def _cfg_candidates(self):
    out = []
    for c in self.components:
        if c.get("derived"):
            continue
        out.append((f"c:{c['id']}", f"Configuration@{c['name']}", self.cfg_read(f"c:{c['id']}")))
        out.append((f"x:{c['id']}", f"$SUPPRESS@{c['name']}", bool(c.get("suppressed"))))
    for m in self.mates:
        out.append((f"m:{m['id']}", self.cfg_label(f"m:{m['id']}"), bool(m.get("suppressed"))))
        if m["type"] in ("distance", "angle"):
            out.append((f"v:{m['id']}", self.cfg_label(f"v:{m['id']}"), m.get("value")))
    for p in self.patterns:
        fields = {"linear": ("n1", "s1", "n2", "s2"), "circular": ("n", "angle"), "mirror": ()}[p["type"]]
        for f in fields:
            if f in p:
                out.append((f"n:{p['id']}:{f}", self.cfg_label(f"n:{p['id']}:{f}"), p[f]))
    return out


def _cfg_capture(self):
    c = self.cfg
    row = c["cells"].setdefault(c["active"], {})
    for key in c["cols"]:
        v = self.cfg_read(key)
        if v is not None:
            row[key] = v


def _cfg_snapshot(self):
    self.cfg_capture()
    return self.cfg


def _cfg_apply(self, name):
    if name not in self.cfg["names"]:
        raise MateError(f"no configuration called {name}")
    self.cfg_capture()
    self.cfg["active"] = name
    row = self.cfg["cells"].get(name, {})
    for key in self.cfg["cols"]:
        if key in row:
            self.cfg_write(key, row[key])


def _cfg_add(self, name, copy_of=None):
    name = name.strip()
    if not name or name in self.cfg["names"]:
        raise MateError("that configuration name is empty or already used")
    self.cfg_capture()
    self.cfg["names"].append(name)
    self.cfg["cells"][name] = dict(self.cfg["cells"].get(copy_of or self.cfg["active"], {}))


def _cfg_delete(self, name):
    if len(self.cfg["names"]) < 2:
        raise MateError("an assembly needs at least one configuration")
    if name == self.cfg["active"]:
        self.cfg_apply(next(n for n in self.cfg["names"] if n != name))
    self.cfg["names"].remove(name)
    self.cfg["cells"].pop(name, None)


def _cfg_rename(self, name, new):
    new = new.strip()
    if not new or (new in self.cfg["names"] and new != name):
        raise MateError("that configuration name is empty or already used")
    self.cfg["names"][self.cfg["names"].index(name)] = new
    self.cfg["cells"][new] = self.cfg["cells"].pop(name, {})
    if self.cfg["active"] == name:
        self.cfg["active"] = new


def _cfg_add_col(self, key):
    if key in self.cfg["cols"]:
        return
    self.cfg_capture()
    v = self.cfg_read(key)
    if v is None:
        raise MateError("that item cannot be put in the table")
    self.cfg["cols"].append(key)
    for n in self.cfg["names"]:
        self.cfg["cells"].setdefault(n, {})[key] = v


def _cfg_del_col(self, key):
    if key in self.cfg["cols"]:
        self.cfg["cols"].remove(key)
        for row in self.cfg["cells"].values():
            row.pop(key, None)


def _cfg_set_cell(self, name, key, val):
    self.cfg["cells"].setdefault(name, {})[key] = val
    if name == self.cfg["active"]:
        self.cfg_write(key, val)


for _f in (_cfg_read, _cfg_write, _cfg_label, _cfg_candidates, _cfg_capture, _cfg_snapshot, _cfg_apply, _cfg_add, _cfg_delete,
           _cfg_rename, _cfg_add_col, _cfg_del_col, _cfg_set_cell):
    setattr(Assembly, _f.__name__[1:], _f)
