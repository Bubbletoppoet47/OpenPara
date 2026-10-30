"""
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


class MateError(Exception):
    pass


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
        pts = [_v(v.center()) for v in solid.vertices()]
        if not pts:
            raise MateError("the point it refers to no longer exists")
        q = np.array(r["p"])
        d = [float(np.linalg.norm(p - q)) for p in pts]
        i = int(np.argmin(d))
        if d[i] > 1.0:
            raise MateError("the point it refers to has moved away")
        return {"t": "point", "p": pts[i]}
    if k == "face":
        best, sc = None, 1e18
        c0 = np.array(r["c"])
        for f in solid.faces():
            if f.geom_type.name != r["g"]:
                continue
            if r.get("n") is not None and float(_v(f.normal_at()) @ np.array(r["n"])) < 0.98:
                continue
            s = float(np.linalg.norm(_v(f.center()) - c0))
            if s < sc:
                best, sc = f, s
        if best is None or sc > 2.0:
            raise MateError("the face it refers to no longer exists")
        return face_entity(best)
    if k == "edge":
        best, sc = None, 1e18
        m0 = np.array(r["m"])
        for e in solid.edges():
            if e.geom_type.name != r["g"]:
                continue
            s = float(np.linalg.norm(_v(e.position_at(0.5)) - m0))
            if s < sc:
                best, sc = e, s
        if best is None or sc > 2.0:
            raise MateError("the edge it refers to no longer exists")
        return edge_entity(best)
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
        d = json.loads(text)
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
        """Fill in the options of a new mate from how the two items lie right now (aligned or opposed, which side, value)."""
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

    def solve(self, drag=None, weight=0.02, extra=None, iters=80, limit=None):
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

        def res(x, with_drag=True):
            P = poses_of(x)
            out = []
            for m in mates:
                try:
                    out += self.mate_residual(m, P)
                except MateError:
                    raise
            r = np.array(out, float)
            if with_drag and targets:
                pull = [weight * (x[6 * i:6 * i + 6] - tv) for i, tv in targets.items()]
                r = np.concatenate([r] + pull)
            return r

        if not mates or not fl:
            if drag:
                for cid, (R, t) in drag.items():
                    c = self.comp(cid)
                    if c is not None and not c.get("fixed"):
                        c["pos"], c["rv"] = list(map(float, t)), list(map(float, rotvec(R)))
            self.status = {m["id"]: "ok" for m in self.mates}
            self.dof = {c["id"]: (0 if c.get("fixed") else 6) for c in self.components if not c.get("derived")}
            return True
        lam = 1e-3
        r = res(x)
        for _ in range(iters):
            n = len(x)
            J = np.zeros((len(r), n))
            for j in range(n):
                h = 1e-6 if j % 6 < 3 else 1e-7
                xp = x.copy()
                xp[j] += h
                J[:, j] = (res(xp) - r) / h
            g = J.T @ r
            if np.linalg.norm(g, np.inf) < 1e-10:
                break
            improved = False
            for _k in range(8):
                A = J.T @ J + lam * np.eye(n)
                try:
                    dx = -np.linalg.solve(A, g)
                except np.linalg.LinAlgError:
                    lam *= 10
                    continue
                r2 = res(x + dx)
                if float(r2 @ r2) < float(r @ r):
                    x, r, lam, improved = x + dx, r2, max(lam / 3, 1e-9), True
                    break
                lam *= 4
            if not improved or float(r @ r) < 1e-22:
                break
        for i, c in enumerate(fl):
            c["pos"], c["rv"] = list(map(float, x[6 * i:6 * i + 3])), list(map(float, x[6 * i + 3:6 * i + 6]))
        if targets:                      # the pull left the mates slightly off: snap them exactly (no pull this time)
            return self.solve(extra=extra, iters=40, limit=limit)
        # report
        P = poses_of(x)
        ok = True
        if limit is None:
            self.status = {}
        live = self.active_mates()
        for m in self.mates:
            if limit is not None and m not in mates:
                continue
            if m.get("suppressed") or m not in live:
                self.status[m["id"]] = "suppressed"
                continue
            try:
                rr = np.array(self.mate_residual(m, P), float)
            except MateError as ex:
                self.status[m["id"]] = f"error: {ex}"
                ok = False
                continue
            if rr.size and float(np.max(np.abs(rr))) > 1e-4 * max(1.0, 1.0):
                self.status[m["id"]] = "error: this mate cannot be satisfied together with the others"
                ok = False
            else:
                self.status[m["id"]] = "ok"
        if limit is None:
            self.dof = self.degrees_of_freedom(fl, mates, x, poses_of)
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
