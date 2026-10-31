"""
pm_model.py - the document of the parametric modeller: an ordered FEATURE TREE per part, rebuilt from the top (SolidWorks style).

    Document
      params   {name: expression}          global equations ("Globals"), e.g. {"W": "40", "H": "W/2"}
      features [Feature, ...]              sketch / extrude / fillet / chamfer, in order
      rollback index of the last feature that is built (None = all)

Every number in a feature is an EXPRESSION (a string such as "H*2+1") that may use the globals.  rebuild() runs the features in order on the
OpenCascade kernel (build123d); a feature that fails is marked with its error and the ones after it are not built (as in SolidWorks).

References to faces and edges are not numbers ("Face7" breaks when the model changes): a face is stored as the point + normal where you
clicked it, an edge as its midpoint + direction; on every rebuild they are matched to the closest face / edge of the new solid.
"""
import copy
import json
import math

import numpy as np
from build123d import Align, Axis, Box, Compound, Edge, Face, Location, Matrix, Plane, PositionMode, Transition, Vector, Wire, extrude, loft, revolve, sweep
from OCP.gp import gp_Trsf

import refgeo
import settings
import sk_tools as sk
import sketcher_core as sc

BASE_PLANES = {"Front": Plane.XZ, "Top": Plane.XY, "Right": Plane.YZ}     # normals: -Y (to the viewer in front), +Z, +X
FUNCS = {k: getattr(math, k) for k in ("sin", "cos", "tan", "atan", "sqrt", "pi", "radians", "degrees", "floor", "ceil")}
FUNCS.update({"abs": abs, "min": min, "max": max, "round": round})


# features that add or remove a shape and so can be repeated by a pattern / mirror
SOLID_FEATURES = ("extrude", "cut", "revolve", "revolve_cut", "sweep", "sweep_cut", "loft", "loft_cut")

class ModelError(Exception):
    pass


def new_feature(kind, **kw):
    return {"id": None, "name": None, "kind": kind, "suppressed": False, **kw}


class Document:
    def __init__(self):
        self.dimvals = {}                    # values of the dimensions the user gave a name, for formulas (filled by rebuild)
        self.params = {}
        self.param_kinds = {}                # {global name: 'number' | 'angle'}; anything else is a length (units follow File > Units)
        self.sims = []                       # linked simulation files (sim_links.py)
        self.renders = []                    # linked render projects (.gpr)
        self.material = {"name": "Steel (generic)", "density": 7850.0, "E_MPa": 200000.0, "nu": 0.30, "Sy_MPa": 250.0, "Su_MPa": 400.0}   # density kg/m3, see mat_lib.py
        self.display = {"color": None, "opacity": 1.0}                      # how the part is drawn (Display tab)
        self.cfg = {"active": "Default", "names": ["Default"], "cols": [], "cells": {"Default": {}}}
        self.features = []
        self.rollback = None            # index of the last built feature (None = the end)
        self.counter = {}
        self.values = {}                # evaluated globals
        self.solid = None               # the part after the last built feature
        self.status = {}                # feature id -> "ok" | "error: ..." | "not built" | "suppressed"
        self.planes = {}                # sketch id -> build123d Plane (where it ended up)
        self.refgeo = {}                # reference plane / axis feature id -> entity (see refgeo.py)
        self.after = {}                 # feature id -> the solid after that feature (for rollback and picking)
        self.models = {}                # sketch id -> its solved sketcher_core.Model (live: the sketch editor works on it)
        self.reports = {}               # sketch id -> the solver report (degrees of freedom, conflicts)

    # ------------------------------------------------------------------ editing
    def add(self, feat):
        k = feat["kind"]
        self.counter[k] = self.counter.get(k, 0) + 1
        title = {"sketch": "Sketch", "extrude": "Boss-Extrude", "cut": "Cut-Extrude", "fillet": "Fillet", "chamfer": "Chamfer",
                 "revolve": "Boss-Revolve", "revolve_cut": "Cut-Revolve", "sweep": "Boss-Sweep", "sweep_cut": "Cut-Sweep",
                 "loft": "Boss-Loft", "loft_cut": "Cut-Loft", "pattern": "Pattern", "mirror": "Mirror",
                 "refplane": "Plane", "refaxis": "Axis", "partgen": "Part"}[k]
        if k == "partgen":
            title = (feat.get("gen") or "Part").replace(" ", "-")
        if k == "pattern":
            title = "LPattern" if feat.get("ptype") == "linear" else "CirPattern"
        feat["name"] = feat["name"] or f"{title}{self.counter[k]}"
        feat["id"] = f"F{sum(self.counter.values())}"
        i = len(self.features) if self.rollback is None else self.rollback + 1     # a new feature goes after the rollback bar
        self.features.insert(i, feat)
        if self.rollback is not None:
            self.rollback = i
        return feat

    def feature(self, fid):
        return next((f for f in self.features if f["id"] == fid), None)

    def remove(self, fid):
        self.features = [f for f in self.features if f["id"] != fid]
        if self.rollback is not None:
            self.rollback = min(self.rollback, len(self.features) - 1)

    # ------------------------------------------------------------------ expressions
    def evaluate_params(self):
        """Resolve the globals (they may use each other, in any order)."""
        vals, pending = {}, dict(self.params)
        for _ in range(len(pending) + 1):
            for k, e in list(pending.items()):
                try:
                    vals[k] = float(eval(str(e), {"__builtins__": {}}, {**FUNCS, **vals}))
                    del pending[k]
                except NameError:
                    pass
                except Exception as ex:
                    raise ModelError(f"global '{k}' = {e}: {ex}")
        if pending:
            raise ModelError("globals cannot be resolved (a loop or an unknown name): " + ", ".join(pending))
        self.values = vals

    def num(self, expr):
        try:
            return float(eval(str(expr), {"__builtins__": {}}, {**FUNCS, **self.dimvals, **self.values}))
        except Exception as ex:
            raise ModelError(f"'{expr}': {ex}")

    # ------------------------------------------------------------------ rebuild
    def rebuild(self):
        """Run the features in order.  Fills self.solid, self.status, self.planes."""
        self.status, self.planes, self.after, self.models, self.reports = {}, {}, {}, {}, {}
        self.refgeo = {}
        try:
            self.prune_cfg()
        except Exception:
            pass
        self.dimvals = {}
        solid = None
        try:
            self.evaluate_params()
        except ModelError as ex:
            self.solid = None
            for f in self.features:
                self.status[f["id"]] = "error: " + str(ex) if f is self.features[0] else "not built"
            return
        last = len(self.features) - 1 if self.rollback is None else self.rollback
        failed = False
        for i, f in enumerate(self.features):
            if i > last:
                self.status[f["id"]] = "rolled back"
                continue
            if failed:
                self.status[f["id"]] = "not built"
                continue
            if f["suppressed"]:
                self.status[f["id"]] = "suppressed"
                self.after[f["id"]] = solid
                continue
            try:
                solid = self.run(f, solid)
                self.status[f["id"]] = "ok"
            except Exception as ex:
                self.status[f["id"]] = "error: " + (str(ex) or type(ex).__name__)
                failed = True
            self.after[f["id"]] = solid
        self.solid = solid

    def run(self, f, solid):
        k = f["kind"]
        if k == "sketch":
            self.planes[f["id"]] = self.resolve_plane(f["plane"], solid)
            self.load_sketch(f)
            return solid
        if k in ("refplane", "refaxis"):
            return self.run_refgeo(f, solid)
        if k in ("extrude", "cut"):
            return self.run_extrude(f, solid)
        if k in ("revolve", "revolve_cut"):
            return self.run_revolve(f, solid)
        if k == "partgen":
            return self.run_partgen(f, solid)
        if k in ("sweep", "sweep_cut"):
            return self.run_sweep(f, solid)
        if k in ("loft", "loft_cut"):
            return self.run_loft(f, solid)
        if k == "pattern":
            return self.run_pattern(f, solid)
        if k == "mirror":
            return self.run_mirror(f, solid)
        if k in ("fillet", "chamfer"):
            if solid is None:
                raise ModelError("nothing to round yet")
            if not f["edges"]:
                raise ModelError("no edges selected")
            r = self.num(f["size"])
            if r <= 0:
                raise ModelError("the size must be positive")
            bodies = solid.solids()
            if not bodies:
                raise ModelError("nothing to round yet")
            done, used = [], 0
            for b in bodies:                                   # each body gets the edges that belong to it
                es = []
                for ref in f["edges"]:
                    try:
                        es.append(self.resolve_edge(ref, b))
                    except ModelError:
                        pass
                if es:
                    used += len(es)
                    done.append(b.fillet(r, es) if k == "fillet" else b.chamfer(r, None, es))
                else:
                    done.append(b)
            if not used:
                raise ModelError("an edge it refers to no longer exists")
            out = done[0] if len(done) == 1 else Compound(done)
            return self.clean(out)
        raise ModelError(f"unknown feature kind {k}")

    @staticmethod
    def clean(shape):
        solids = shape.solids() if hasattr(shape, "solids") else []
        if not solids:
            raise ModelError("the result has no volume")
        return solids[0] if len(solids) == 1 else shape

    # ------------------------------------------------------------------ sketches
    # ------------------------------------------------------------------ the sketch model
    def load_sketch(self, f):
        """Make the live Model of a sketch feature: from its saved text (or from the old entity list), with the globals added as symbols,
        solved.  Dimensions that use a global (e.g. 'Width/2') follow it."""
        if not f.get("model"):
            f["model"] = self.legacy_model(f)
            f.pop("entities", None)
        m = sc.Model()
        m.from_json(f["model"])
        for k, e in self.params.items():
            m.params[k] = {"vals": [0.0] * len(m.configs), "input": False, "expr": str(e), "doc": True}
        for k, v in self.dimvals.items():                      # named dimensions of the sketches before this one
            if k not in m.params:
                m.params[k] = {"vals": [float(v)] * len(m.configs), "input": False, "expr": repr(float(v)), "doc": True}
        self.reports[f["id"]] = sk.solve_model(m)
        self.models[f["id"]] = m
        for c in m.cons:                                      # and this one's, for the features and sketches after it
            if c["type"] in sc.DIMENSIONS and c.get("user_name") and c.get("name"):
                self.dimvals[c["name"]] = float(c["value"])
        return m

    # ------------------------------------------------------------------ named dimensions
    def dim_name_taken(self, name, ignore=None):
        """Why `name` cannot be a dimension name (a text), or None.  Names are unique over the globals and the named dimensions."""
        if not name.isidentifier() or name.startswith("__"):
            return "a name uses letters, digits and _ and does not start with a digit"
        if name in FUNCS or name in ("e", "pi", "True", "False", "None"):
            return f"'{name}' is a function / constant name"
        if name in self.params:
            return f"'{name}' is already a global"
        for f in self.features:
            if f["kind"] != "sketch":
                continue
            m = self.sketch_model_raw(f)
            for c in m.cons:
                if c["type"] in sc.DIMENSIONS and c.get("name") == name and (f["id"], c["id"]) != ignore:
                    if c.get("user_name") or f["id"] == (ignore or (None,))[0]:
                        return f"'{name}' is already used by a dimension of {f['name']}"
            if f["id"] == (ignore or (None,))[0] and name in m.params:
                return f"'{name}' is already a symbol of this sketch"
        return None

    def rename_dimension(self, fid, cid, new):
        """Give a sketch dimension a name of your choice (unique in the part, usable in formulas).  Raises ModelError."""
        import re
        new = new.strip()
        f = self.feature(fid)
        if f is None or f["kind"] != "sketch":
            raise ModelError("no such sketch")
        m = self.sketch_model_raw(f)
        c = m.con_by_id(int(cid) if str(cid).isdigit() else cid)
        if not c or c["type"] not in sc.DIMENSIONS:
            raise ModelError("no such dimension")
        old = c.get("name")
        if new == old:
            return
        why = self.dim_name_taken(new, ignore=(fid, c["id"]))
        if why:
            raise ModelError(why)
        sym = c.get("expr") == old and old in m.params and not m.params[old].get("doc")
        if sym:                                               # the dimension is a named symbol: the symbol is renamed everywhere
            pat = re.compile(r"\b" + re.escape(old) + r"\b")
            m.params[new] = m.params.pop(old)
            for k in m.cons:
                if k.get("expr"):
                    k["expr"] = pat.sub(new, str(k["expr"]))
                if k.get("name") == old:
                    k["name"] = new
            for p in m.params.values():
                if p.get("expr"):
                    p["expr"] = pat.sub(new, str(p["expr"]))
        else:
            c["name"] = new
        c["user_name"] = True
        f["model"] = m.to_json()
        self.rename_refs(old, new, skip=fid)                  # later features / sketches / globals that used the name follow

    # ------------------------------------------------------------------ renames that follow everywhere
    FORMULA_KEYS = ("depth", "depth2", "draft", "thickness", "angle", "size", "count", "spacing", "count2", "spacing2", "d", "ang", "offset", "twist")

    def rename_refs(self, old, new, skip=None):
        """Every formula that uses the name `old` (whole word) now uses `new`: globals, feature values, sketch dimensions / symbols, and the
        cells of the Configurations table.  `skip` = a sketch id that was already rewritten."""
        import re
        if not old or old == new:
            return
        pat = re.compile(r"(?<![\w.])" + re.escape(old) + r"\b")

        def sub(t):
            return pat.sub(new, t) if isinstance(t, str) else t
        self.params = {k: sub(v) for k, v in self.params.items()}
        for f in self.features:
            for key in self.FORMULA_KEYS:
                if key in f and isinstance(f[key], str):
                    f[key] = sub(f[key])
            pl = f.get("plane")
            if isinstance(pl, dict) and isinstance(pl.get("offset"), str):
                pl["offset"] = sub(pl["offset"])
            if f["kind"] == "sketch" and f["id"] != skip:
                try:
                    m = self.sketch_model_raw(f)
                except Exception:
                    continue
                changed = False
                for c in m.cons:
                    if isinstance(c.get("expr"), str) and sub(c["expr"]) != c["expr"]:
                        c["expr"] = sub(c["expr"])
                        changed = True
                for p_ in m.params.values():
                    if isinstance(p_.get("expr"), str) and sub(p_["expr"]) != p_["expr"]:
                        p_["expr"] = sub(p_["expr"])
                        changed = True
                if changed:
                    f["model"] = m.to_json()
        for row in self.cfg.get("cells", {}).values():
            for k, v in list(row.items()):
                if isinstance(v, str):
                    row[k] = sub(v)
        self.models = {}

    def uses_name(self, name, skip_sketch=None):
        """Where else a name (a global or a named dimension) is used in a formula: a list of short descriptions, empty when nowhere."""
        import re
        pat = re.compile(r"(?<![\w.])" + re.escape(name) + r"\b")
        out = []
        for k, v in self.params.items():
            if k != name and pat.search(str(v)):
                out.append(f"global {k}")
        for f in self.features:
            for key in self.FORMULA_KEYS:
                if isinstance(f.get(key), str) and pat.search(f[key]):
                    out.append(f"{key} of {f['name']}")
            if f["kind"] == "sketch" and f["id"] != skip_sketch:
                try:
                    m = self.sketch_model_raw(f)
                except Exception:
                    continue
                if any(isinstance(c.get("expr"), str) and pat.search(c["expr"]) for c in m.cons):
                    out.append(f"a dimension of {f['name']}")
        for cn, row in self.cfg.get("cells", {}).items():
            if any(isinstance(v, str) and pat.search(v) for v in row.values()):
                out.append(f"configuration {cn}")
        return out

    def prune_cfg(self):
        """Drop Configurations columns of sketch dimensions that no longer exist."""
        cols = self.cfg.get("cols", [])
        keep = []
        for k in cols:
            if k.startswith("d:"):
                _, fid, cid = k.split(":", 2)
                f = self.feature(fid)
                try:
                    m = self.sketch_model_raw(f) if f is not None and f["kind"] == "sketch" else None
                except Exception:
                    m = None
                if m is None or m.con_by_id(int(cid) if cid.isdigit() else cid) is None:
                    for row in self.cfg.get("cells", {}).values():
                        row.pop(k, None)
                    continue
            keep.append(k)
        if len(keep) != len(cols):
            self.cfg["cols"] = keep

    def rename_global(self, old, new):
        """Rename a global.  Every formula that used it, and its column in the Configurations table, follow.  Raises ModelError."""
        new = new.strip()
        if old not in self.params:
            raise ModelError(f"no global called {old}")
        if new == old:
            return
        why = self.dim_name_taken(new)
        if why:
            raise ModelError(why)
        self.params = {(new if k == old else k): v for k, v in self.params.items()}
        if old in self.param_kinds:
            self.param_kinds[new] = self.param_kinds.pop(old)
        cfg = self.cfg
        cfg["cols"] = [f"g:{new}" if k == f"g:{old}" else k for k in cfg.get("cols", [])]
        for row in cfg.get("cells", {}).values():
            if f"g:{old}" in row:
                row[f"g:{new}"] = row.pop(f"g:{old}")
        self.rename_refs(old, new)

    def rename_feature(self, fid, new):
        """Give a feature (sketch, extrude, plane ...) a new name, unique among the features.  Raises ModelError."""
        new = new.strip()
        f = self.feature(fid)
        if f is None:
            raise ModelError("no such feature")
        if not new:
            raise ModelError("the name is empty")
        if new in ("Front", "Top", "Right") or any(g["name"].lower() == new.lower() for g in self.features if g["id"] != fid):
            raise ModelError(f"'{new}' is already used")
        f["name"] = new

    def store_sketch(self, fid):
        """Write the live Model of sketch `fid` back into its feature (without the globals)."""
        f, m = self.feature(fid), self.models[fid]
        keep = m.params
        m.params = {k: v for k, v in keep.items() if not v.get("doc")}
        try:
            f["model"] = m.to_json()
        finally:
            m.params = keep

    def legacy_model(self, f):
        """Sketch given as a list of rectangles / circles / lines (older files, tests) -> Model text."""
        m = sk.new_model()
        for e in f.get("entities", []):
            try:
                if e["kind"] == "rect":
                    cx, cy, w, h = (self.num(e.get(x, 0)) for x in ("cx", "cy", "w", "h"))
                    r = sk.add_rect_corner(m, (cx - w / 2, cy - h / 2), (cx + w / 2, cy + h / 2))
                    for t, ln, ex in (("dim_h", r["lns"][0], e["w"]), ("dim_v", r["lns"][1], e["h"])):
                        m.add_con(t, [("ln", ln)], value=self.num(ex), sign=1, **({"expr": str(ex)} if not _is_number(ex) else {}))
                elif e["kind"] == "circle":
                    cx, cy, d = (self.num(e.get(x, 0)) for x in ("cx", "cy", "d"))
                    cid = sk.add_circle(m, (cx, cy), (cx + d / 2, cy))
                    m.add_con("dim_dia", [("ci", cid)], value=d, **({"expr": str(e["d"])} if not _is_number(e["d"]) else {}))
                elif e["kind"] == "line":
                    ends = []
                    for q in ((self.num(e["x1"]), self.num(e["y1"])), (self.num(e["x2"]), self.num(e["y2"]))):
                        hit = next((i for i, p in m.pts.items() if abs(p[0] - q[0]) < 1e-9 and abs(p[1] - q[1]) < 1e-9), None)
                        ends.append(("pt", hit) if hit is not None else q)
                    sk.add_line(m, ends[0], ends[1], auto=False)
            except Exception:
                pass
        return m.to_json()

    # ------------------------------------------------------------------ extrude / cut
    @staticmethod
    def end_condition(f, which=1):
        """('blind' | 'mid' | 'through' | 'face', ...) of end 1 (older files kept 'through' / 'midplane' flags)."""
        if which == 1:
            return f.get("end1") or ("through" if f.get("through") else "mid" if f.get("midplane") else "blind")
        return f.get("end2") or "blind"

    def run_extrude(self, f, solid, tool_only=False):
        k = f["kind"]
        sk_ = self.feature(f["sketch"])
        if sk_ is None or sk_["id"] not in self.planes:
            raise ModelError("its sketch is missing or suppressed")
        if k == "cut" and solid is None:
            raise ModelError("nothing to cut yet")
        faces = self.profile(sk_, f.get("pts") or None)
        plane = self.planes[sk_["id"]]
        zdir = np.array(tuple(plane.z_dir))
        diag = 200.0
        if solid is not None:
            b = solid.bounding_box()
            diag = 2.0 * float(np.linalg.norm([b.size.X, b.size.Y, b.size.Z])) + 10.0
        e1, e2 = self.end_condition(f, 1), self.end_condition(f, 2)
        d1 = self.num(f.get("depth", "10")) if e1 in ("blind", "mid") else diag
        if e1 in ("blind", "mid") and d1 <= 0:
            raise ModelError("the depth must be positive")
        two = bool(f.get("dir2"))
        d2 = (self.num(f.get("depth2", "10")) if e2 == "blind" else diag) if two else 0.0
        if two and e2 == "blind" and d2 <= 0:
            raise ModelError("the depth of direction 2 must be positive")
        taper = self.num(f.get("draft", "0")) if f.get("draft_on") else 0.0
        if taper and f.get("draft_out"):
            taper = -taper
        if f.get("thin"):
            t = self.num(f.get("thickness", "1"))
            if t <= 0:
                raise ModelError("the wall thickness must be positive")
            faces = [self.thin_face(p, t, f.get("thin_side", "inside")) for p in faces]

        def prism(direction, amount, tp, only_to=None):
            tool = None
            for prof in faces:
                try:
                    t_ = extrude(prof, amount=amount, dir=Vector(*direction), taper=tp)
                except Exception as ex:
                    raise ModelError("the draft angle is too large for this depth" if tp else f"cannot extrude this profile ({ex})")
                tool = t_ if tool is None else tool + t_
            if only_to is not None:
                tool = self.stop_at_face(tool, only_to, direction)
            return tool

        face_ref = None
        if e1 == "face" or (two and e2 == "face"):
            if solid is None or not f.get("to_face"):
                raise ModelError("pick the face to extrude up to")
            face_ref = self.resolve_face(f["to_face"], solid)

        def build(sign):
            direction = zdir * sign
            if e1 == "mid":
                tool = prism(direction, d1 / 2.0, taper) + prism(-direction, d1 / 2.0, taper)
            else:
                tool = prism(direction, d1, taper, face_ref if e1 == "face" else None)
            if two:
                tool = tool + prism(-direction, d2, taper, face_ref if e2 == "face" else None)
            return tool

        rev = -1.0 if f.get("reverse") else 1.0
        if k == "extrude":
            tool = build(rev)
            if tool_only:
                return tool
            return self.clean(tool if solid is None else (solid + tool if f.get("merge", True)
                                                          else Compound(solid.solids() + tool.solids())))
        # cut: the first time, go the way that removes material; the choice is kept so that the cut does not jump around later
        if f.get("dir") not in (1, -1):
            best, bv = 1, -1.0
            for sg in (1, -1):
                try:
                    v = (solid & build(float(sg))).volume
                except Exception:
                    v = 0.0
                if v > bv + 1e-9:
                    best, bv = sg, v
            f["dir"] = best
        tool = build(float(f["dir"]) * rev)
        if tool_only:
            return tool
        out = solid & tool if f.get("flip_side") else solid - tool
        before = sum(x.volume for x in solid.solids())
        after = sum(x.volume for x in out.solids()) if out.solids() else 0.0
        if abs(before - after) < 1e-9 * max(1.0, before) and not f.get("flip_side"):
            raise ModelError("the cut does not touch the part (try Reverse direction, or check the sketch position)")
        return self.clean(out)

    @staticmethod
    def stop_at_face(tool, face, direction):
        """Keep the part of `tool` that lies on the near side of the plane of `face` (seen from the sketch)."""
        n = face.normal_at()
        n = np.array([n.X, n.Y, n.Z])
        c = face.center()
        big = 1.0e5
        side = Plane(origin=c, z_dir=Vector(*(n if float(n @ np.array(direction)) > 0 else -n)))
        box = side.location * Box(big, big, big, align=(Align.CENTER, Align.CENTER, Align.MAX))
        out = tool & box
        if not out.solids():
            raise ModelError("the face it extrudes up to is behind the sketch")
        return out

    @staticmethod
    def thin_face(face, t, side):
        """A closed profile -> the ring of wall thickness t inside / outside / half each side of its outline."""
        w = face.outer_wire()
        def off(dist):
            r = w.offset_2d(dist)
            return r if isinstance(r, Wire) else Wire(r)
        a1, a2 = Face(off(t)).area, Face(off(-t)).area
        out_d = t if a1 > a2 else -t                    # the sign that makes the outline bigger
        if side == "outside":
            outer, inner = off(out_d), w
        elif side == "mid":
            outer, inner = off(out_d / 2.0), off(-out_d / 2.0)
        else:
            outer, inner = w, off(-out_d)
        return Face(outer, [inner])

    def region_info(self, sketch):
        """[(area, interior point (u, v))] of the closed regions of a sketch (for the contour list of an extrude)."""
        m = self.models.get(sketch["id"])
        out = []
        if m is None:
            return out
        for outer, holes in self.region_polys(sketch):
            area = abs(_area(outer)) - sum(abs(_area(h)) for h in holes)
            out.append((area, _interior(outer, holes)))
        return out

    def region_polys(self, sketch):
        m = self.models[sketch["id"]]
        return [(self.loop_poly(m, r["outer"]), [self.loop_poly(m, h) for h in r["holes"]]) for r in sk.regions(m)]

    @staticmethod
    def loop_poly(m, loop):
        pts = []
        for item in loop:
            kind, i = item[0], item[1]
            fwd = item[2] if len(item) > 2 else True
            p = sk.polyline(m, (kind, i), 48)
            pts.extend(p if fwd else p[::-1])
        return np.array(pts)

    # ------------------------------------------------------------------ revolve
    def sketch_axis(self, sketch, spec):
        """Axis (3D) from a sketch axis spec: "sx" / "sy" (the sketch axes), ("ln", id) / {"ln": id} (a line of the sketch) or "auto"."""
        plane = self.planes[sketch["id"]]
        o = np.array(tuple(plane.origin))
        xd, yd = np.array(tuple(plane.x_dir)), np.array(tuple(plane.y_dir))
        m = self.models[sketch["id"]]
        if spec in (None, "auto"):
            cl = [i for i in m.lns if ("ln", i) in m.constr]
            spec = {"ln": cl[0]} if cl else "sy"
        if spec == "sx":
            return Axis(Vector(*o), Vector(*xd))
        if spec == "sy":
            return Axis(Vector(*o), Vector(*yd))
        lid = spec["ln"] if isinstance(spec, dict) else spec[1]
        if lid not in m.lns:
            raise ModelError("the axis line it revolves about no longer exists")
        a, b = m.line_pts(lid)
        d = (b[0] - a[0], b[1] - a[1])
        if math.hypot(*d) < 1e-9:
            raise ModelError("the axis line has no length")
        return Axis(Vector(*(o + a[0] * xd + a[1] * yd)), Vector(*(d[0] * xd + d[1] * yd)))

    def run_revolve(self, f, solid, tool_only=False):
        k = f["kind"]
        sk_ = self.feature(f["sketch"])
        if sk_ is None or sk_["id"] not in self.planes:
            raise ModelError("its sketch is missing or suppressed")
        if k == "revolve_cut" and solid is None:
            raise ModelError("nothing to cut yet")
        faces = self.profile(sk_, f.get("pts") or None)
        axis = self.sketch_axis(sk_, f.get("axis"))
        if f.get("reverse"):
            axis = Axis(axis.position, -axis.direction)
        ang = self.num(f.get("angle", "360"))
        if not 0 < ang <= 360:
            raise ModelError("the angle must be between 0 and 360 degrees")
        tool = None
        for prof in faces:
            try:
                t_ = revolve(prof, axis=axis, revolution_arc=ang)
            except Exception as ex:
                raise ModelError(f"cannot revolve this profile ({ex}); it must not cross the axis")
            tool = t_ if tool is None else tool + t_
        if tool_only:
            return tool
        if k == "revolve":
            return self.clean(tool if solid is None else (solid + tool if f.get("merge", True)
                                                          else Compound(solid.solids() + tool.solids())))
        out = solid - tool
        before = sum(x.volume for x in solid.solids())
        after = sum(x.volume for x in out.solids()) if out.solids() else 0.0
        if abs(before - after) < 1e-9 * max(1.0, before):
            raise ModelError("the cut does not touch the part")
        return self.clean(out)

    # ------------------------------------------------------------------ sweep and loft
    def add_or_cut(self, f, solid, tool, cut):
        """Join `tool` to the part (boss) or remove it from the part (cut); the same rules as extrudes and revolves."""
        if not cut:
            return self.clean(tool if solid is None else (solid + tool if f.get("merge", True)
                                                          else Compound(solid.solids() + tool.solids())))
        out = solid & tool if f.get("flip_side") else solid - tool
        before = sum(x.volume for x in solid.solids())
        after = sum(x.volume for x in out.solids()) if out.solids() else 0.0
        if abs(before - after) < 1e-9 * max(1.0, before) and not f.get("flip_side"):
            raise ModelError("the cut does not touch the part")
        return self.clean(out)

    @staticmethod
    def path_smooth(path, tol_deg=1.0):
        """True when the tangent of the path is continuous (no sharp corner)."""
        edges = path.edges()
        for a, b in zip(edges, edges[1:]):
            ta, tb = a.tangent_at(1.0), b.tangent_at(0.0)
            va, vb = np.array([ta.X, ta.Y, ta.Z]), np.array([tb.X, tb.Y, tb.Z])
            if float(va @ vb) / (np.linalg.norm(va) * np.linalg.norm(vb)) < math.cos(math.radians(tol_deg)):
                return False
        return True

    @staticmethod
    def twisted_sections(prof, path, twist_deg, n):
        """Copies of the profile along the path, each turned a little more about the path (right-handed about the direction of travel).
        The profile keeps its place relative to the path start; between the sections it is carried along with a rotation-minimising frame."""
        L = path.length
        pts, tans = [], []
        for i in range(n + 1):
            s = L * i / n
            p, t_ = path.position_at(s, position_mode=PositionMode.LENGTH), path.tangent_at(s, position_mode=PositionMode.LENGTH)
            pts.append(np.array([p.X, p.Y, p.Z]))
            v = np.array([t_.X, t_.Y, t_.Z])
            tans.append(v / np.linalg.norm(v))

        def rot(axis, ang):
            a = axis / max(np.linalg.norm(axis), 1e-30)
            K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
            return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)

        def between(u, v):
            c = np.cross(u, v)
            s = np.linalg.norm(c)
            d = float(u @ v)
            if s < 1e-12:
                return np.eye(3) if d > 0 else rot(np.cross(u, [1, 0, 0]) if abs(u[0]) < 0.9 else np.cross(u, [0, 1, 0]), math.pi)
            return rot(c, math.atan2(s, d))
        out, R = [], np.eye(3)
        for i in range(n + 1):
            if i:
                R = between(tans[i - 1], tans[i]) @ R
            Rt = rot(tans[i], math.radians(twist_deg) * i / n) @ R
            M = np.eye(4)
            M[:3, :3] = Rt
            M[:3, 3] = pts[i] - Rt @ pts[0]
            t_ = gp_Trsf()
            t_.SetValues(*M[:3].flatten().tolist())
            out.append(prof.moved(Location(t_)))
        return out

    def run_partgen(self, f, solid):
        """A part made by the Part Generator (a gear, ...): ONE feature whose parameters are kept in the feature, so the
        generator window can be reopened to change them.  The new solid is added to the part."""
        import partgen
        kind = f.get("gen")
        if kind not in partgen.PART_TYPES:
            raise ModelError(f"unknown generated part type {kind!r}")
        try:
            v = partgen.numbers(kind, f.get("params") or {}, self.num)
            tool = partgen.build(kind, v)
            pl = f.get("place") or {}
            tool = partgen.placed(tool, pl.get("plane", "Top"), self.num(pl.get("ox", "0")), self.num(pl.get("oy", "0")), self.num(pl.get("oz", "0")))
        except ModelError:
            raise
        except (ValueError, ZeroDivisionError) as ex:
            raise ModelError(str(ex))
        if not tool.is_valid:
            raise ModelError("the generated part is not a valid solid for these inputs")
        return self.clean(tool if solid is None else solid + tool)

    def run_sweep(self, f, solid, tool_only=False):
        cut = f["kind"] == "sweep_cut"
        sk_, ps = self.feature(f.get("sketch")), self.feature(f.get("path"))
        if sk_ is None or sk_["id"] not in self.planes:
            raise ModelError("its profile sketch is missing or suppressed")
        if ps is None or ps["id"] not in self.planes:
            raise ModelError("pick the sketch that holds the path")
        if ps["id"] == sk_["id"]:
            raise ModelError("the profile and the path must be in two different sketches")
        if cut and solid is None:
            raise ModelError("nothing to cut yet")
        faces = self.profile(sk_, f.get("pts") or None)
        path = self.path_wire(ps, bool(f.get("reverse")))
        twist = self.num(f.get("twist", "0")) if f.get("twist_on") else 0.0
        trans = Transition.ROUND if f.get("corners") == "round" else Transition.RIGHT
        if twist and not self.path_smooth(path):
            raise ModelError("a twisted sweep needs a smooth path (no sharp corners); round the corners of the path sketch")
        tool = None
        for prof in faces:
            try:
                if twist:
                    n = int(min(60, max(8, math.ceil(abs(twist) / 10.0), math.ceil(path.length / max(prof.bounding_box().diagonal, 1e-6) * 2))))
                    t_ = sweep(self.twisted_sections(prof, path, twist, n), path, multisection=True, transition=trans)
                else:
                    t_ = sweep(prof, path, transition=trans, is_frenet=f.get("orient") == "frenet")
            except ModelError:
                raise
            except Exception as ex:
                raise ModelError(f"cannot sweep this profile along this path ({ex or type(ex).__name__})")
            if not t_.solids() or t_.volume < 1e-9:
                raise ModelError("the sweep has no volume - check that the profile is not flat against the path direction")
            tool = t_ if tool is None else tool + t_
        if tool_only:
            return tool
        return self.add_or_cut(f, solid, tool, cut)

    def loft_loops(self, f):
        """[(sketch, loop, polygon)] of the sections of a loft: each sketch must hold exactly one closed region without holes."""
        ids = f.get("sections") or []
        if len(ids) < 2:
            raise ModelError("pick at least two section sketches")
        out = []
        for sid in ids:
            s_ = self.feature(sid)
            if s_ is None or s_["id"] not in self.planes or s_["id"] not in self.models:
                raise ModelError("a section sketch is missing or suppressed")
            regs = sk.regions(self.models[sid])
            if not regs:
                raise ModelError(f"{s_['name']} has no closed profile")
            if len(regs) > 1:
                raise ModelError(f"{s_['name']} has {len(regs)} closed regions - a loft section is one closed profile (make the other lines construction geometry)")
            if regs[0]["holes"]:
                raise ModelError(f"{s_['name']} has a hole inside the profile - a loft section is one closed outline")
            out.append((s_, regs[0]["outer"], self.loop_poly(self.models[sid], regs[0]["outer"])))
        return out

    def run_loft(self, f, solid, tool_only=False):
        cut = f["kind"] == "loft_cut"
        if cut and solid is None:
            raise ModelError("nothing to cut yet")
        secs = self.loft_loops(f)
        cents, normals, areas = [], [], []
        for s_, loop, poly in secs:
            plane = self.planes[s_["id"]]
            o, xd, yd = self.sketch_frame(plane)
            c = poly.mean(axis=0)
            cents.append(o + c[0] * xd + c[1] * yd)
            normals.append(np.array(tuple(plane.z_dir)))
            areas.append(_area(poly))
        n = len(secs)
        for i in range(n):
            if np.linalg.norm(cents[min(i + 1, n - 1)] - cents[max(i - 1, 0)]) < 1e-9 and n == 2:
                raise ModelError("the section sketches are at the same place")
        # every outline must turn the same way as seen along the loft: reverse the ones that do not
        hand = []
        for i, (s_, loop, poly) in enumerate(secs):
            d = cents[min(i + 1, n - 1)] - cents[max(i - 1, 0)]
            q = float(np.sign(np.dot(normals[i], d) * np.sign(areas[i] if areas[i] else 1.0)))
            if q == 0:
                raise ModelError(f"{s_['name']} lies along the direction of the loft - its sketch plane must cross the loft, not contain it")
            hand.append(q)
        loops = []
        for (s_, loop, poly), q in zip(secs, hand):
            rev = q != hand[0]
            loops.append((s_, loop, rev))
        # start each outline at the corner nearest to the start of the one before it, so the loft does not twist
        wires, start = [], None
        for s_, loop, rev in loops:
            m, plane = self.models[s_["id"]], self.planes[s_["id"]]
            o, xd, yd = self.sketch_frame(plane)
            if len(loop) > 1:
                pieces = [(k_, i_, not fw) for k_, i_, fw in reversed(loop)] if rev else list(loop)
                pts3 = []
                for kind, i, fwd in pieces:
                    e = self.piece_edge(m, plane, kind, i, fwd)
                    p = e.start_point()
                    pts3.append(np.array([p.X, p.Y, p.Z]))
                if start is not None:
                    k0 = int(np.argmin([np.linalg.norm(p - start) for p in pts3]))
                    pieces = pieces[k0:] + pieces[:k0]
                    pts3 = pts3[k0:] + pts3[:k0]
                wire = Wire([self.piece_edge(m, plane, kind, i, fwd) for kind, i, fwd in pieces])
                start = pts3[0]
            else:
                wire = self.loop_wire(m, plane, loop, rev)
                p = wire.start_point()
                start = np.array([p.X, p.Y, p.Z]) if start is None else start
            wires.append(wire)
        try:
            tool = loft([Face(w) for w in wires], ruled=bool(f.get("ruled")))
        except Exception as ex:
            raise ModelError(f"cannot loft these sections ({ex or type(ex).__name__})")
        if not tool.solids() or tool.volume < 1e-9:
            raise ModelError("the loft has no volume")
        if tool_only:
            return tool
        return self.add_or_cut(f, solid, tool, cut)

    def feature_sketches(self, f):
        """The ids of every sketch a feature uses (profile, path, loft sections)."""
        ids = [f["sketch"]] if f.get("sketch") else []
        if f.get("path"):
            ids.append(f["path"])
        ids += list(f.get("sections") or [])
        return ids

    # ------------------------------------------------------------------ patterns and mirror of features
    def feature_tool(self, g, solid_before):
        """(tool shape, 'add' | 'cut') of an extrude / cut / revolve feature, for patterning it."""
        k = g["kind"]
        if k == "extrude":
            return self.run_extrude(g, solid_before, tool_only=True), "add"
        if k == "cut":
            return self.run_extrude(g, solid_before, tool_only=True), "cut"
        if k == "revolve":
            return self.run_revolve(g, solid_before, tool_only=True), "add"
        if k == "revolve_cut":
            return self.run_revolve(g, solid_before, tool_only=True), "cut"
        if k == "sweep":
            return self.run_sweep(g, solid_before, tool_only=True), "add"
        if k == "sweep_cut":
            return self.run_sweep(g, solid_before, tool_only=True), "cut"
        if k == "loft":
            return self.run_loft(g, solid_before, tool_only=True), "add"
        if k == "loft_cut":
            return self.run_loft(g, solid_before, tool_only=True), "cut"
        raise ModelError(f"{g['name']} cannot be patterned (only extrudes, cuts, revolves, sweeps and lofts)")

    def source_tools(self, f, solid):
        """[(tool, mode)] of the features listed in f['features'] (each rebuilt from the part before it)."""
        out = []
        for gid in f.get("features", []):
            g = self.feature(gid)
            if g is None:
                raise ModelError("a feature it repeats no longer exists")
            i = self.features.index(g)
            if self.features.index(f) <= i:
                raise ModelError("it can only repeat features that come before it")
            before = self.after.get(self.features[i - 1]["id"]) if i > 0 else None
            if self.status.get(g["id"]) != "ok":
                raise ModelError(f"{g['name']} is not built")
            out.append(self.feature_tool(g, before))
        if not out:
            raise ModelError("pick the features to repeat (or the whole body)")
        return out

    @staticmethod
    def global_dir(spec):
        return {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[spec]

    def edge_vec(self, ref, solid):
        e = self.resolve_edge(ref, solid)
        t = e.tangent_at(0.5)
        return np.array([t.X, t.Y, t.Z])

    def pattern_moves(self, f, solid):
        """[function(shape) -> moved copy] for every copy of a pattern (not the original)."""
        moves = []
        if f.get("ptype") == "linear":
            n1 = int(round(self.num(f.get("count", "3"))))
            s1 = self.num(f.get("spacing", "10"))
            if n1 < 1:
                raise ModelError("the number of copies must be at least 1")
            if f.get("dir1") == "edge":
                if not f.get("edge1"):
                    raise ModelError("pick the edge that gives the direction")
                d1 = self.edge_vec(f["edge1"], solid)
            else:
                d1 = np.array(self.global_dir(f.get("dir1", "X")), float)
            d1 = d1 / np.linalg.norm(d1) * (-1.0 if f.get("reverse") else 1.0)
            two = bool(f.get("dir2_on"))
            n2 = int(round(self.num(f.get("count2", "2")))) if two else 1
            s2 = self.num(f.get("spacing2", "10")) if two else 0.0
            d2 = np.array(self.global_dir(f.get("dir2", "Y")), float)
            for i in range(n1):
                for j in range(n2):
                    if i == 0 and j == 0:
                        continue
                    v = d1 * s1 * i + d2 * s2 * j
                    moves.append(lambda sh, v=v: sh.moved(Location(tuple(v))))
            return moves
        n = int(round(self.num(f.get("count", "4"))))
        total = self.num(f.get("angle", "360"))
        if n < 2:
            raise ModelError("the number of copies must be at least 2")
        if f.get("axis") == "edge":
            if not f.get("edge1"):
                raise ModelError("pick the edge that gives the axis")
            e = self.resolve_edge(f["edge1"], solid)
            if e.geom_type.name == "CIRCLE":
                c = e.arc_center
                nrm = e.normal()
                axis = Axis(Vector(c.X, c.Y, c.Z), Vector(nrm.X, nrm.Y, nrm.Z))
            else:
                p, t = e.position_at(0.5), e.tangent_at(0.5)
                axis = Axis(Vector(p.X, p.Y, p.Z), Vector(t.X, t.Y, t.Z))
        else:
            axis = Axis(Vector(0, 0, 0), Vector(*self.global_dir(f.get("axis", "Z"))))
        step = total / n if abs(total - 360.0) < 1e-9 else total / (n - 1)
        if f.get("reverse"):
            step = -step
        for i in range(1, n):
            moves.append(lambda sh, a=step * i: sh.rotate(axis, a))
        return moves

    def apply_copies(self, f, solid, moves):
        """Add / cut the moved copies of the chosen features (or of the whole body)."""
        if solid is None:
            raise ModelError("nothing to repeat yet")
        if f.get("source") == "body":
            out = solid
            for mv in moves:
                out = out + mv(solid)
            return self.clean(out)
        out = solid
        for tool, mode in self.source_tools(f, solid):
            for mv in moves:
                t = mv(tool)
                out = out + t if mode == "add" else out - t
        return self.clean(out)

    def run_pattern(self, f, solid):
        return self.apply_copies(f, solid, self.pattern_moves(f, solid))

    def mirror_plane(self, f, solid):
        spec = f.get("plane") or {"base": "Front"}
        if "ref" in spec:
            return self.ref_plane(spec["ref"])
        if "base" in spec:
            return BASE_PLANES[spec["base"]]
        if solid is None:
            raise ModelError("the face it mirrors about does not exist yet")
        return Plane(self.resolve_face(spec["face"], solid))

    def run_mirror(self, f, solid):
        pl = self.mirror_plane(f, solid)
        return self.apply_copies(f, solid, [lambda sh: sh.mirror(pl)])

    # ------------------------------------------------------------------ sketches -> faces
    def profile(self, sketch, pts=None):
        """The closed regions of a sketch as faces in 3D (a list); regions inside regions become holes.  `pts` [(u, v)]: only the regions
        that contain one of these points."""
        m = self.models.get(sketch["id"])
        if m is None:
            raise ModelError("the sketch is not built")
        plane = self.planes[sketch["id"]]
        o = np.array(tuple(plane.origin))
        xd, yd = np.array(tuple(plane.x_dir)), np.array(tuple(plane.y_dir))
        wire = lambda loop: self.loop_wire(m, plane, loop)
        faces = []
        polys = self.region_polys(sketch) if pts else None
        for n, reg in enumerate(sk.regions(m)):
            if pts and not any(_inside(p, polys[n][0], polys[n][1]) for p in pts):
                continue
            try:
                outer = wire(reg["outer"])
                inner = [wire(h) for h in reg["holes"]]
                faces.append(Face(outer, inner) if inner else Face(outer))
            except Exception as ex:
                raise ModelError(f"{sketch['name']}: cannot make a face ({ex})")
        if not faces:
            raise ModelError(f"{sketch['name']} has no closed profile")
        return faces

    # ------------------------------------------------------------------ wires of sketch loops and chains (profiles, sweep paths, loft sections)
    @staticmethod
    def sketch_frame(plane):
        o = np.array(tuple(plane.origin))
        return o, np.array(tuple(plane.x_dir)), np.array(tuple(plane.y_dir))

    @staticmethod
    def piece_edge(m, plane, kind, i, fwd=True):
        """One line or arc of a sketch as a 3D edge (reversed when fwd is False)."""
        o, xd, yd = Document.sketch_frame(plane)
        w3 = lambda p: Vector(*(o + p[0] * xd + p[1] * yd))
        P = m.pts
        if kind == "ln":
            a, b = m.lns[i]
            a, b = (a, b) if fwd else (b, a)
            return Edge.make_line(w3(P[a]), w3(P[b]))
        c, r, t0, sw = sk.arc_span(m, i)
        ar = m.ars[i]
        mid = (c[0] + r * math.cos(t0 + sw / 2), c[1] + r * math.sin(t0 + sw / 2))
        s, e = P[ar["s"]], P[ar["e"]]
        s, e = (s, e) if fwd else (e, s)
        return Edge.make_three_point_arc(w3(s), w3(mid), w3(e))

    @staticmethod
    def loop_wire(m, plane, loop, reverse=False):
        """The wire of a closed loop of a sketch (a list of pieces, or one circle); reverse = the other way round."""
        o, xd, yd = Document.sketch_frame(plane)
        if len(loop) == 1 and loop[0][0] == "ci":
            c = m.pts[m.cis[loop[0][1]]["c"]]
            r = m.cis[loop[0][1]]["r"]
            pl = Plane(origin=Vector(*(o + c[0] * xd + c[1] * yd)), x_dir=plane.x_dir, z_dir=(-plane.z_dir if reverse else plane.z_dir))
            return Wire([Edge.make_circle(r, plane=pl)])
        pieces = [(k_, i_, not fw) for k_, i_, fw in reversed(loop)] if reverse else loop
        return Wire([Document.piece_edge(m, plane, kind, i, fwd) for kind, i, fwd in pieces])

    @staticmethod
    def sketch_unions(m):
        """Union-find over the points of a sketch, joining points that a 'coincident' relation ties together."""
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
        return find

    def path_wire(self, sketch, reverse=False):
        """The sweep path of a sketch: its lines and arcs (construction geometry left out) as ONE connected chain, open or closed;
        or a single circle.  reverse = start at the other end."""
        m = self.models.get(sketch["id"])
        if m is None or sketch["id"] not in self.planes:
            raise ModelError("the path sketch is not built")
        plane = self.planes[sketch["id"]]
        find = self.sketch_unions(m)
        segs = [(("ln", i), find(a), find(b)) for i, (a, b) in m.lns.items() if ("ln", i) not in m.constr]
        segs += [(("ar", i), find(a["s"]), find(a["e"])) for i, a in m.ars.items() if ("ar", i) not in m.constr]
        circles = [i for i in m.cis if ("ci", i) not in m.constr]
        if not segs and len(circles) == 1:
            return self.loop_wire(m, plane, [("ci", circles[0])], reverse)
        if circles:
            raise ModelError(f"{sketch['name']}: a path is one chain of lines and arcs, or a single circle (make the others construction geometry)")
        if not segs:
            raise ModelError(f"{sketch['name']} has no path (draw lines or arcs)")
        adj = {}
        for s in segs:
            adj.setdefault(s[1], []).append(s)
            adj.setdefault(s[2], []).append(s)
        if any(len(v) > 2 for v in adj.values()):
            raise ModelError(f"{sketch['name']}: the path branches - a sweep path is one chain with no forks")
        ends = [n for n, v in adj.items() if len(v) == 1]
        if len(ends) not in (0, 2):
            raise ModelError(f"{sketch['name']}: the path is not one connected chain")
        node = ends[0] if ends else segs[0][1]
        chain, cur, used = [], None, set()
        while True:
            nxt = [s for s in adj.get(node, []) if s[0] not in used]
            if not nxt:
                break
            cur = nxt[0]
            fwd = cur[1] == node
            chain.append((cur[0][0], cur[0][1], fwd))
            used.add(cur[0])
            node = cur[2] if fwd else cur[1]
        if len(chain) != len(segs):
            raise ModelError(f"{sketch['name']}: the path is not one connected chain")
        if reverse:
            chain = [(k_, i_, not fw) for k_, i_, fw in reversed(chain)]
        return Wire([self.piece_edge(m, plane, k_, i_, fw) for k_, i_, fw in chain])

    # ------------------------------------------------------------------ reference planes and axes
    def spec_entity(self, spec, solid):
        """The geometry (refgeo entity) that a reference of a plane / axis feature points at."""
        import asm_model as am
        k = spec["k"]
        if k == "base":
            pl = BASE_PLANES[spec["n"]]
            return {"t": "plane", "p": np.zeros(3), "n": np.array(tuple(pl.z_dir)), "x": np.array(tuple(pl.x_dir))}
        if k == "origin":
            return {"t": "point", "p": np.zeros(3)}
        if k == "ref":
            e = self.refgeo.get(spec["id"])
            if e is None:
                raise ModelError("it refers to a plane / axis that is not built (yet)")
            return e
        if solid is None:
            raise ModelError("the geometry it refers to does not exist yet")
        r = spec["r"]
        try:
            if k == "face":
                if r.get("g", "PLANE") == "PLANE":
                    f = self.resolve_face(r, solid)
                    pl = Plane(f)
                    return {"t": "plane", "p": np.array(tuple(pl.origin)), "n": np.array(tuple(pl.z_dir)), "x": np.array(tuple(pl.x_dir))}
                best, sc = None, 1e18
                c0 = np.array(r["c"])
                for f in solid.faces():
                    if f.geom_type.name != r["g"]:
                        continue
                    c = f.center()
                    s_ = float(np.linalg.norm(np.array([c.X, c.Y, c.Z]) - c0))
                    if s_ < sc:
                        best, sc = f, s_
                if best is None:
                    raise ModelError("the face it refers to no longer exists")
                return am.face_entity(best)
            if k == "edge":
                return am.edge_entity(self.resolve_edge(r, solid))
            if k == "vertex":
                q = np.array(r["p"])
                best, sc = None, 1e18
                for v in solid.vertices():
                    c = v.center()
                    s_ = float(np.linalg.norm(np.array([c.X, c.Y, c.Z]) - q))
                    if s_ < sc:
                        best, sc = np.array([c.X, c.Y, c.Z]), s_
                if best is None or sc > 1.0:
                    raise ModelError("the point it refers to no longer exists")
                return {"t": "point", "p": best}
        except am.MateError as ex:
            raise ModelError(str(ex))
        raise ModelError(f"unknown reference {k}")

    def run_refgeo(self, f, solid):
        ents = [self.spec_entity(s, solid) for s in f.get("refs", [])]
        try:
            if f["kind"] == "refplane":
                e = refgeo.compute_plane(f.get("ptype"), ents, self.num(f.get("d", "10")), self.num(f.get("ang", "45")), bool(f.get("flip")))
            else:
                e = refgeo.compute_axis(f.get("ptype"), ents)
        except refgeo.RefError as ex:
            raise ModelError(str(ex))
        self.refgeo[f["id"]] = e
        return solid

    def ref_plane(self, fid):
        e = self.refgeo.get(fid)
        if e is None:
            raise ModelError("the plane it refers to is not built")
        return Plane(origin=Vector(*e["p"]), x_dir=Vector(*e["x"]), z_dir=Vector(*e["n"]))

    def resolve_plane(self, spec, solid):
        if "ref" in spec:
            return self.ref_plane(spec["ref"])
        if "base" in spec:
            p = BASE_PLANES[spec["base"]]
            off = self.num(spec.get("offset", 0))
            return p.offset(off) if off else p
        if solid is None:
            raise ModelError("the face it was drawn on does not exist yet")
        face = self.resolve_face(spec["face"], solid)
        return Plane(face)

    # ------------------------------------------------------------------ references that survive a rebuild
    @staticmethod
    def face_ref(face):
        c, n = face.center(), face.normal_at()
        return {"c": [c.X, c.Y, c.Z], "n": [n.X, n.Y, n.Z]}

    @staticmethod
    def resolve_face(ref, solid):
        c0, n0 = np.array(ref["c"]), np.array(ref["n"])
        best, score = None, 1e18
        for f in solid.faces():
            if f.geom_type.name != "PLANE":
                continue
            n = f.normal_at()
            n = np.array([n.X, n.Y, n.Z])
            if float(n @ n0) < 0.98:
                continue
            c = f.center()
            d = np.array([c.X, c.Y, c.Z]) - c0
            s = 3.0 * abs(float(d @ n0)) + float(np.linalg.norm(d))      # the plane position counts most, then where on it
            if s < score:
                best, score = f, s
        if best is None:
            raise ModelError("the face it refers to no longer exists")
        return best

    @staticmethod
    def edge_ref(edge):
        m, t = edge.position_at(0.5), edge.tangent_at(0.5)
        return {"m": [m.X, m.Y, m.Z], "d": [t.X, t.Y, t.Z]}

    @staticmethod
    def resolve_edge(ref, solid):
        m0, d0 = np.array(ref["m"]), np.array(ref["d"])
        best, score = None, 1e18
        for e in solid.edges():
            t = e.tangent_at(0.5)
            if abs(float(np.array([t.X, t.Y, t.Z]) @ d0)) < 0.9:
                continue
            m = e.position_at(0.5)
            s = float(np.linalg.norm(np.array([m.X, m.Y, m.Z]) - m0))
            if s < score:
                best, score = e, s
        if best is None or score > 0.5 * max(1.0, float(np.linalg.norm(m0)) + 50.0):
            raise ModelError("an edge it refers to no longer exists")
        return best

    # ------------------------------------------------------------------ geometry for the viewer
    def mesh(self, solid=None, tol=None):
        """[(face index, vertices Nx3, triangles Mx3)] of a solid; tol (mm) defaults to File > Settings > Surface accuracy."""
        tol = settings.get("surf_gap") if tol is None else tol
        out = []
        solid = solid or self.solid
        if solid is None:
            return out
        for i, f in enumerate(solid.faces()):
            v, t = f.tessellate(tol, settings.surface_angle(tol))
            if v and t:
                out.append((i, np.array([[p.X, p.Y, p.Z] for p in v]), np.array(t, dtype=np.int64)))
        return out

    def edge_lines(self, solid=None, gap=None):
        """One polyline per edge; a curve is cut into straight pieces so that none lies further than `gap` mm (File > Settings >
        Curve accuracy) from the true curve."""
        solid = solid or self.solid
        out = []
        if solid is None:
            return out
        for e in solid.edges():
            out.append(np.array(settings.edge_points(e, gap)))
        return out

    def sketch_lines(self, sketch, n=48):
        """Outline of a sketch in 3D (for drawing it in the view): a list of (N, 3) arrays."""
        m = self.models.get(sketch["id"])
        if m is None or sketch["id"] not in self.planes:
            return []
        plane = self.planes[sketch["id"]]
        o = np.array(tuple(plane.origin))
        xd, yd = np.array(tuple(plane.x_dir)), np.array(tuple(plane.y_dir))
        out = []
        for key in sk.all_keys(m):
            if key in m.constr:
                continue
            p = sk.polyline(m, key, n)
            out.append(o + p[:, :1] * xd + p[:, 1:2] * yd)
        return out

    # ------------------------------------------------------------------ files
    def to_json(self):
        return json.dumps({"version": 1, "params": self.params, "kinds": self.param_kinds, "features": self.features, "rollback": self.rollback,
                           "counter": self.counter, "material": self.material, "sims": self.sims, "renders": self.renders,
                           "display": self.display, "cfg": self.cfg_snapshot()}, indent=1)

    @classmethod
    def from_json(cls, text):
        d = json.loads(text)
        doc = cls()
        doc.params, doc.features, doc.rollback, doc.counter = d["params"], d["features"], d.get("rollback"), d.get("counter", {})
        doc.param_kinds = d.get("kinds") or {}
        doc.material = d.get("material") or doc.material
        doc.sims = d.get("sims") or []
        doc.renders = d.get("renders") or []
        doc.display = d.get("display") or doc.display
        doc.cfg = d.get("cfg") or doc.cfg
        return doc

    def copy(self):
        return Document.from_json(self.to_json())

    # ------------------------------------------------------------------ configurations
    # A configuration is a named set of values for the columns of the configuration table:
    #   "g:<global>"            the equation of a global variable
    #   "d:<sketch id>:<con>"   one sketch dimension (a number or an equation)
    #   "s:<feature id>"        True = that feature is suppressed
    # The document always holds the values of the ACTIVE configuration; the table keeps one row of values per configuration.
    def cfg_read(self, key):
        kind, _, rest = key.partition(":")
        if kind == "g":
            return self.params.get(rest)
        if kind == "s":
            f = self.feature(rest)
            return None if f is None else bool(f.get("suppressed"))
        if kind == "d":
            fid, _, cid = rest.partition(":")
            f = self.feature(fid)
            if f is None or f["kind"] != "sketch":
                return None
            m = self.sketch_model_raw(f)
            c = m.con_by_id(int(cid)) if cid.isdigit() else m.con_by_id(cid)
            if not c:
                return None
            sym = self.dim_symbol(m, c)
            if sym:                                            # a dimension driven by a named symbol: the column holds the symbol's number
                return float(m.params[sym]["vals"][m.active if 0 <= m.active < len(m.params[sym]["vals"]) else 0])
            return str(c["expr"]) if c.get("expr") else float(c["value"])
        if kind == "f":
            fid, _, field = rest.partition(":")
            f = self.feature(fid)
            if f is None:
                return None
            if field == "offset":
                v = (f.get("plane") or {}).get("offset")
            else:
                v = f.get(field)
            return None if v is None else str(v)
        return None

    @staticmethod
    def dim_symbol(m, c):
        """The name of the plain symbol (a number you can change) that drives dimension c, or None."""
        e = c.get("expr")
        if e and str(e).isidentifier() and e in m.params:
            p = m.params[e]
            if not p.get("expr") and not p.get("doc"):
                return e
        return None

    def cfg_write(self, key, val):
        kind, _, rest = key.partition(":")
        if val is None:
            return
        if kind == "g":
            if rest in self.params:
                self.params[rest] = str(val)
        elif kind == "s":
            f = self.feature(rest)
            if f is not None:
                f["suppressed"] = bool(val)
        elif kind == "d":
            fid, _, cid = rest.partition(":")
            f = self.feature(fid)
            if f is None or f["kind"] != "sketch":
                return
            m = self.sketch_model_raw(f)
            c = m.con_by_id(int(cid)) if cid.isdigit() else m.con_by_id(cid)
            if not c:
                return
            sym = self.dim_symbol(m, c)
            if sym and val == sym:
                return                                          # an older file stored the symbol's name here: keep the symbol's number
            if sym and (isinstance(val, (int, float)) or _is_number(val)):
                p = m.params[sym]
                p["vals"] = [float(val)] * len(p["vals"]) if len(p["vals"]) < 2 else [float(val) if i == m.active else v for i, v in enumerate(p["vals"])]
                c["value"] = float(val)
            elif isinstance(val, (int, float)) or _is_number(val):
                c["value"] = float(val)
                c.pop("expr", None)
            else:
                c["expr"] = str(val)
                try:
                    c["value"] = float(self.num(str(val)))
                except Exception:
                    pass
            f["model"] = m.to_json()
        elif kind == "f":
            fid, _, field = rest.partition(":")
            f = self.feature(fid)
            if f is None:
                return
            if field == "offset":
                if "plane" in f:
                    f["plane"]["offset"] = str(val)
            else:
                f[field] = str(val)

    # the numbers of a feature that a configuration can change:  (field, label, kind)  kind = length | number | angle
    def feature_fields(self, f):
        k = f["kind"]
        out = []
        if k in ("extrude", "cut"):
            if self.end_condition(f, 1) in ("blind", "mid") and "depth" in f:
                out.append(("depth", "Depth", "length"))
            if f.get("dir2") and self.end_condition(f, 1) != "mid" and self.end_condition(f, 2) == "blind" and "depth2" in f:
                out.append(("depth2", "Depth2", "length"))
            if f.get("draft_on") and "draft" in f:
                out.append(("draft", "Draft", "angle"))
            if f.get("thin") and "thickness" in f:
                out.append(("thickness", "Wall", "length"))
        elif k in ("revolve", "revolve_cut"):
            out.append(("angle", "Angle", "angle"))
        elif k in ("sweep", "sweep_cut"):
            if "twist" in f:
                out.append(("twist", "Twist", "angle"))
        elif k in ("fillet", "chamfer"):
            out.append(("size", "Radius" if k == "fillet" else "Distance", "length"))
        elif k == "pattern":
            if f.get("ptype") == "linear":
                out += [("count", "Copies", "number"), ("spacing", "Spacing", "length")]
                if f.get("dir2_on"):
                    out += [("count2", "Copies2", "number"), ("spacing2", "Spacing2", "length")]
            else:
                out += [("count", "Copies", "number"), ("angle", "Angle", "angle")]
        elif k == "refplane":
            if f.get("ptype") == "offset" and "d" in f:
                out.append(("d", "Distance", "length"))
            if f.get("ptype") == "angle" and "ang" in f:
                out.append(("ang", "Angle", "angle"))
        elif k == "sketch":
            if "base" in (f.get("plane") or {}) and "offset" in f["plane"]:
                out.append(("offset", "Offset", "length"))
        return out

    def cfg_kind(self, key):
        """'length' | 'number' | 'angle' for a feature-value column, else None."""
        kind, _, rest = key.partition(":")
        if kind != "f":
            return None
        fid, _, field = rest.partition(":")
        f = self.feature(fid)
        if f is None:
            return None
        return next((kd for fl, _l, kd in self.feature_fields(f) if fl == field), "length" if field in ("depth", "depth2", "thickness", "size", "spacing", "spacing2", "d", "offset") else "number")

    def sketch_model_raw(self, f):
        """The Model of a sketch straight from its saved text (no globals added)."""
        if not f.get("model"):
            f["model"] = self.legacy_model(f)
            f.pop("entities", None)
        m = sc.Model()
        m.from_json(f["model"])
        return m

    # Where the labels of the sketch dimensions were put is kept per configuration as well: cfg["offs"][configuration]["<sketch id>:<con id>"]
    # = {"off": ..., "aoff": ...}.  A new configuration starts as a copy of the one it was made from.
    LABEL_KEYS = ("off", "aoff")

    def label_offsets(self):
        """{"<sketch id>:<con id>": {"off": .., "aoff": ..}} of the labels moved in the document right now."""
        out = {}
        for f in self.features:
            if f["kind"] != "sketch" or not f.get("model"):
                continue
            try:
                m = self.sketch_model_raw(f)
            except Exception:
                continue
            for c in m.cons:
                if c["type"] in sc.DIMENSIONS:
                    e = {k: c[k] for k in self.LABEL_KEYS if c.get(k)}
                    if e:
                        out[f"{f['id']}:{c['id']}"] = e
        return out

    def apply_label_offsets(self, row):
        """Put the saved label positions of a configuration into the sketches (a label not in `row` goes back to its automatic place)."""
        for f in self.features:
            if f["kind"] != "sketch" or not f.get("model"):
                continue
            try:
                m = self.sketch_model_raw(f)
            except Exception:
                continue
            changed = False
            for c in m.cons:
                if c["type"] not in sc.DIMENSIONS:
                    continue
                want = row.get(f"{f['id']}:{c['id']}", {})
                for k in self.LABEL_KEYS:
                    if want.get(k):
                        if c.get(k) != want[k]:
                            c[k] = want[k]
                            changed = True
                    elif k in c:
                        c.pop(k)
                        changed = True
            if changed:
                f["model"] = m.to_json()

    def cfg_capture(self):
        """Copy the document's current values into the row of the active configuration."""
        c = self.cfg
        row = c["cells"].setdefault(c["active"], {})
        for key in c["cols"]:
            v = self.cfg_read(key)
            if v is not None:
                row[key] = v
        c.setdefault("offs", {})[c["active"]] = self.label_offsets()

    def cfg_snapshot(self):
        self.cfg_capture()
        return self.cfg

    def cfg_apply(self, name):
        """Make `name` the active configuration: write its values into the document."""
        if name not in self.cfg["names"]:
            raise ModelError(f"no configuration called {name}")
        self.cfg_capture()
        self.cfg["active"] = name
        row = self.cfg["cells"].get(name, {})
        for key in self.cfg["cols"]:
            if key in row:
                self.cfg_write(key, row[key])
        offs = self.cfg.get("offs", {})
        if name in offs:                                     # (a file from before this was kept leaves the labels where they are)
            self.apply_label_offsets(offs[name])

    def cfg_add(self, name, copy_of=None):
        name = name.strip()
        if not name or name in self.cfg["names"]:
            raise ModelError("that configuration name is empty or already used")
        self.cfg_capture()
        src = copy_of or self.cfg["active"]
        self.cfg["names"].append(name)
        self.cfg["cells"][name] = dict(self.cfg["cells"].get(src, {}))
        offs = self.cfg.setdefault("offs", {})
        offs[name] = copy.deepcopy(offs.get(src, {}))

    def cfg_delete(self, name):
        if len(self.cfg["names"]) < 2:
            raise ModelError("a part needs at least one configuration")
        if name == self.cfg["active"]:
            self.cfg_apply(next(n for n in self.cfg["names"] if n != name))
        self.cfg["names"].remove(name)
        self.cfg["cells"].pop(name, None)
        self.cfg.get("offs", {}).pop(name, None)

    def cfg_rename(self, name, new):
        new = new.strip()
        if not new or (new in self.cfg["names"] and new != name):
            raise ModelError("that configuration name is empty or already used")
        i = self.cfg["names"].index(name)
        self.cfg["names"][i] = new
        self.cfg["cells"][new] = self.cfg["cells"].pop(name, {})
        if "offs" in self.cfg:
            self.cfg["offs"][new] = self.cfg["offs"].pop(name, {})
        if self.cfg["active"] == name:
            self.cfg["active"] = new

    def cfg_add_col(self, key):
        if key in self.cfg["cols"]:
            return
        self.cfg_capture()
        v = self.cfg_read(key)
        if v is None:
            raise ModelError("that item cannot be put in the table")
        self.cfg["cols"].append(key)
        for n in self.cfg["names"]:
            self.cfg["cells"].setdefault(n, {})[key] = v

    def cfg_del_col(self, key):
        if key in self.cfg["cols"]:
            self.cfg["cols"].remove(key)
            for row in self.cfg["cells"].values():
                row.pop(key, None)

    def cfg_set_cell(self, name, key, val):
        self.cfg["cells"].setdefault(name, {})[key] = val
        if name == self.cfg["active"]:
            self.cfg_write(key, val)

    def cfg_label(self, key):
        kind, _, rest = key.partition(":")
        if kind == "g":
            return rest
        if kind == "s":
            f = self.feature(rest)
            return f"$SUPPRESS@{f['name']}" if f else key
        if kind == "f":
            fid, _, field = rest.partition(":")
            f = self.feature(fid)
            if f is None:
                return key
            lab = next((l for fl, l, _k in self.feature_fields(f) if fl == field), field.capitalize())
            return f"{lab}@{f['name']}"
        fid, _, cid = rest.partition(":")
        f = self.feature(fid)
        if f is None:
            return key
        m = self.sketch_model_raw(f)
        dims = [c for c in m.cons if c["type"] in sc.DIMENSIONS]
        for i, c in enumerate(dims):
            if str(c["id"]) == cid:
                return f"{self.dim_label(m, c, i)}@{f['name']}"
        return key

    def dim_label(self, m, c, i):
        """What a dimension is called: the name you gave it, the symbol that drives it, else D<number>."""
        sym = self.dim_symbol(m, c)
        if c.get("user_name") or sym:
            return sym or c["name"]
        return f"D{i + 1}"

    def cfg_candidates(self):
        """[(key, label, current value)] of everything that can be a column."""
        out = [(f"g:{k}", k, e) for k, e in self.params.items()]
        for f in self.features:
            if f["kind"] == "sketch":
                try:
                    m = self.sketch_model_raw(f)
                except Exception:
                    continue
                dims = [c for c in m.cons if c["type"] in sc.DIMENSIONS]
                for i, c in enumerate(dims):
                    out.append((f"d:{f['id']}:{c['id']}", f"{self.dim_label(m, c, i)}@{f['name']}", self.cfg_read(f"d:{f['id']}:{c['id']}")))
            else:
                out.append((f"s:{f['id']}", f"$SUPPRESS@{f['name']}", bool(f.get("suppressed"))))
            for fl, lab, _kd in self.feature_fields(f):
                key = f"f:{f['id']}:{fl}"
                out.append((key, f"{lab}@{f['name']}", self.cfg_read(key)))
        return out


def _is_number(x):
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def _area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _in_poly(pt, poly):
    x, y = pt
    px, py = poly[:, 0], poly[:, 1]
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    cond = (py > y) != (qy > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = (qx - px) * (y - py) / (qy - py) + px
    return bool(np.sum(cond & (x < xi)) % 2)


def _inside(pt, outer, holes):
    return _in_poly(pt, outer) and not any(_in_poly(pt, h) for h in holes)


def _interior(outer, holes):
    """A point well inside a region (grid search for the one farthest from the outline)."""
    lo, hi = outer.min(axis=0), outer.max(axis=0)
    allp = np.vstack([outer] + list(holes))
    best, bs = (float(outer[:, 0].mean()), float(outer[:, 1].mean())), -1.0
    for u in np.linspace(lo[0], hi[0], 27)[1:-1]:
        for v in np.linspace(lo[1], hi[1], 27)[1:-1]:
            if _inside((u, v), outer, holes):
                sc_ = float(np.min(np.hypot(allp[:, 0] - u, allp[:, 1] - v)))
                if sc_ > bs:
                    best, bs = (float(u), float(v)), sc_
    return best
