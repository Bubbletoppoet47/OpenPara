"""dr_model.py - the document of a drawing (no Qt here): the sheet, the models it shows (a copy of every part / assembly, so the file is self-contained), the views, and the
annotations.  Saved as an .opdraw file (JSON).

    Drawing()                                   a new drawing: Letter landscape, third-angle projection, no model, no view
    d.set_sheet(size, landscape, first_angle)   the standard sheet sizes only (dr_sheet.py)
    d.add_model(name, kind, data, src=None)     a copy of a part ("part": the JSON of a .gpd) or an assembly ("assembly": the JSON of a .gpa); -> its id.  src = the Workbench block it
                                                came from (a Drawing block takes its models from its wires)
    d.refresh_model(mid, data)                  the model changed: every view of it is projected again; -> the ids of the views
    d.add_view(mid, orient, center, scale=None, style="hlv")      a model view: Front, Back, Left, Right, Top, Bottom, Isometric, Trimetric, Dimetric, placed with the middle of its
                                                lines at `center` (mm on the sheet); the scale defaults to the sheet scale
    d.add_projected(parent, side, pos)          a view projected from `parent` to the "right" / "left" / "up" / "down" of it (third-angle: it shows the side you moved to; first-angle:
                                                the opposite side).  It keeps the scale of its parent and stays ALIGNED: it can only slide along its axis
    d.move_view(vid, x, y)                      moves a view (a projected one only along its axis; its own projected views move with it)
    d.set_scale(vid, s), d.set_style(vid, style), d.set_orient(vid, name)
    d.to_json() / Drawing.from_json(text)       the file; the lines of every view are in it (a drawing opens at once and shows without its models)

A view has: id, name ("Drawing View1"), kind ("model" | "projected"), model, orient, eye / up (the direction it looks from, in the model's frame), parent, side, origin (where the model's
origin is on the sheet, mm: the lines are drawn at origin + scale * point), scale (a number: 2 means 2:1, 0.5 means 1:2), style, geom (the projection).
"""
import copy
import hashlib
import json
import math
import re

import dr_annot as A
import dr_geom as G
import dr_items as IT
import dr_proj as P
import dr_sheet as S

FORMAT = "openpara-drawing"
VERSION = 1
EXT = ".opdraw"

STYLES = [("wireframe", "Wireframe"), ("hlv", "Hidden Lines Visible"), ("hlr", "Hidden Lines Removed")]      # the shaded styles come last (not built yet)
STYLE_KEYS = [k for k, _l in STYLES]
SCALES = [("1:1", 1.0), ("1:2", 0.5), ("1:4", 0.25), ("1:5", 0.2), ("1:10", 0.1), ("1:20", 0.05), ("1:50", 0.02), ("1:100", 0.01), ("2:1", 2.0), ("4:1", 4.0),
          ("5:1", 5.0), ("10:1", 10.0), ("20:1", 20.0), ("50:1", 50.0)]
FIT_FRACTION = 0.5                                                # the first view fills at most this much of the sheet's width and height
ANNOT = ("notes", "dims", "balloons", "marks", "lines")          # what is drawn on top of the views
SIDES = ("right", "left", "up", "down")
OPPOSITE = {"right": "left", "left": "right", "up": "down", "down": "up"}


class DrawingError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------------------- scales
def parse_scale(text):
    """'1:2' -> 0.5, '2:1' -> 2.0, '1' / '0.5' -> that number, '1/4' -> 0.25.  A scale must be over zero (DrawingError otherwise)."""
    t = str(text).strip().replace(" ", "")
    try:
        if ":" in t:
            a, b = t.split(":", 1)
            v = float(a) / float(b)
        elif "/" in t:
            a, b = t.split("/", 1)
            v = float(a) / float(b)
        else:
            v = float(t)
    except (ValueError, ZeroDivisionError):
        raise DrawingError(f"'{text}' is not a scale: type it like 1:2, 2:1 or 0.5.")
    if not (v > 0) or math.isinf(v):
        raise DrawingError(f"'{text}' is not a scale: it must be over zero.")
    return v


def scale_text(s):
    """0.5 -> '1:2', 2 -> '2:1', 1 -> '1:1', 0.4 -> '1:2.5'."""
    for t, v in SCALES:
        if abs(v - s) < 1e-9 * max(1.0, s):
            return t
    if s >= 1:
        return f"{s:.6g}:1"
    return f"1:{1.0 / s:.6g}"


def fit_scale(w, h, sheet_w, sheet_h):
    """The largest standard scale at which something w x h (mm, at 1:1) takes at most FIT_FRACTION of the sheet's width and height."""
    if w <= 0 or h <= 0:
        return 1.0
    want = min(FIT_FRACTION * sheet_w / w, FIT_FRACTION * sheet_h / h)
    best = min(v for _t, v in SCALES)
    for _t, v in SCALES:
        if v <= want + 1e-12 and v > best:
            best = v
    return best


def model_hash(data):
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------------- the document
class Drawing:
    def __init__(self):
        self.sheet = {"size": S.DEFAULT, "landscape": True, "first_angle": False}
        self.models = []
        self.views = []
        self.notes, self.dims, self.balloons, self.marks, self.lines = [], [], [], [], []
        self.counter = {"view": 0, "model": 0, "dim": 0, "mark": 0, "note": 0, "balloon": 0, "draw": 0}
        self.scale = 1.0                                          # the sheet scale: what a new model view starts at
        self.cache = {}                                           # model id -> its build123d shape (not saved)
        self._pcache = {}                                         # view id -> (its geom, the Projection made of it) (not saved)

    # ---- the sheet
    def sheet_dims(self):
        return S.dims(self.sheet["size"], self.sheet["landscape"])

    def set_sheet(self, size=None, landscape=None, first_angle=None):
        if size is not None:
            if size not in [s[0] for s in S.SIZES]:
                raise DrawingError(f"'{size}' is not a standard sheet size.")
            self.sheet["size"] = size
        if landscape is not None:
            self.sheet["landscape"] = bool(landscape)
        if first_angle is not None and bool(first_angle) != self.sheet["first_angle"]:
            self.sheet["first_angle"] = bool(first_angle)
            for v in self.views:                                  # a projected view shows the side it is on: the other projection shows the other side
                if v["kind"] == "projected":
                    self.reproject(v)

    # ---- the models
    def model(self, mid):
        for m in self.models:
            if m["id"] == mid:
                return m
        raise DrawingError("That model is not in the drawing.")

    def model_of_src(self, src):
        return next((m for m in self.models if m.get("src") == src), None)

    def add_model(self, name, kind, data, src=None):
        if kind not in ("part", "assembly"):
            raise DrawingError("A drawing shows a part or an assembly.")
        self.counter["model"] += 1
        m = {"id": f"m{self.counter['model']}", "name": str(name), "kind": kind, "src": src, "data": data, "hash": model_hash(data)}
        self.models.append(m)
        return m["id"]

    def remove_model(self, mid):
        """The model and every view of it (and of those: the projected views)."""
        self.model(mid)
        for v in [v for v in self.views if v["model"] == mid]:
            if any(x["id"] == v["id"] for x in self.views):               # (it may have gone with its parent)
                self.remove_view(v["id"])
        self.models = [m for m in self.models if m["id"] != mid]
        self.cache.pop(mid, None)

    def shape(self, mid):
        """The build123d shape of a model (made once)."""
        if mid not in self.cache:
            import dr_geom
            m = self.model(mid)
            self.cache[mid] = dr_geom.shape_of(m["kind"], m["data"])
        return self.cache[mid]

    def refresh_model(self, mid, data, name=None):
        """The model changed (a wired block changed): the views of it are projected again.  -> the ids of the views."""
        m = self.model(mid)
        old = (m["data"], m["hash"], m["name"], self.cache.get(mid), [(v, v["geom"], v["eye"], v["up"]) for v in self.views if v["model"] == mid],
               copy.deepcopy((self.dims, self.marks)))
        m["data"], m["hash"] = data, model_hash(data)
        if name:
            m["name"] = str(name)
        self.cache.pop(mid, None)
        out = []
        try:
            for v in self.views:
                if v["model"] == mid:
                    self.reproject(v)
                    out.append(v["id"])
        except Exception:                                          # the new model cannot be built: the drawing keeps the model and the views it had
            m["data"], m["hash"], m["name"] = old[0], old[1], old[2]
            if old[3] is not None:
                self.cache[mid] = old[3]
            else:
                self.cache.pop(mid, None)
            for v, geom, eye, up in old[4]:
                v["geom"], v["eye"], v["up"] = geom, eye, up
            self.dims, self.marks = old[5]
            raise
        return out

    def sync_models(self, items):
        """A Drawing block of the Workbench: `items` = [{"src", "name", "kind", "data"}] is what is wired into the block now.  A model that is new is added, one whose data (or name)
        changed is refreshed (its views are drawn again; one that cannot be built is reported and left as it was), one that is no longer wired goes with its views.  A model that
        was not wired in (it came from a file) is left alone.  -> {"added", "refreshed", "removed": [names], "failed": [(name, message)], "lost": the number of dimensions and marks
        whose geometry is not in their view any more}."""
        out = {"added": [], "refreshed": [], "removed": [], "failed": [], "lost": 0}
        want = {it["src"] for it in items}
        for m in [m for m in self.models if m.get("src") and m["src"] not in want]:
            self.remove_model(m["id"])
            out["removed"].append(m["name"])
        for it in items:
            m = self.model_of_src(it["src"])
            if m is None:
                self.add_model(it["name"], it["kind"], it["data"], src=it["src"])
                out["added"].append(it["name"])
            elif model_hash(it["data"]) != m["hash"] or m["name"] != it["name"]:
                try:
                    self.refresh_model(m["id"], it["data"], name=it["name"])
                    out["refreshed"].append(it["name"])
                except (DrawingError, G.GeometryError) as ex:
                    out["failed"].append((it["name"], str(ex)))
        out["lost"] = len(self.lost_annots())
        return out

    # ---- the views
    def view(self, vid):
        for v in self.views:
            if v["id"] == vid:
                return v
        raise DrawingError("That view is not in the drawing.")

    def children(self, vid):
        return [v for v in self.views if v.get("parent") == vid]

    def descendants(self, vid):
        out, todo = [], [vid]
        while todo:
            for c in self.children(todo.pop()):
                out.append(c)
                todo.append(c["id"])
        return out

    def _new_view(self, kind, mid, orient, eye, up, scale, style):
        if style not in STYLE_KEYS:
            raise DrawingError(f"'{style}' is not a display style.")
        self.counter["view"] += 1
        n = self.counter["view"]
        return {"id": f"v{n}", "name": f"Drawing View{n}", "kind": kind, "model": mid, "orient": orient, "eye": [float(x) for x in eye], "up": [float(x) for x in up],
                "parent": None, "side": None, "origin": [0.0, 0.0], "scale": float(scale), "style": style, "geom": None}

    def project(self, v):
        """The lines of the view (from its model, direction and style)."""
        pr = P.project_axes(self.shape(v["model"]), v["eye"], v["up"], v["orient"], hidden=v["style"] != "hlr")
        v["geom"] = pr.to_json()
        return pr

    def projection(self, v):
        """The lines of a view as a Projection (kept until the view is projected again)."""
        if v["geom"] is None:
            return self.project(v)
        hit = self._pcache.get(v["id"])
        if hit is not None and hit[0] is v["geom"]:
            return hit[1]
        pr = P.Projection.from_json(v["geom"])
        self._pcache[v["id"]] = (v["geom"], pr)
        return pr

    def bbox(self, v):
        """(xmin, ymin, xmax, ymax) of the view's visible lines on the SHEET (mm)."""
        x0, y0, x1, y1 = self.projection(v).bbox()
        s, (ox, oy) = v["scale"], v["origin"]
        return (ox + s * x0, oy + s * y0, ox + s * x1, oy + s * y1)

    def add_view(self, mid, orient, center, scale=None, style="hlv"):
        """A model view with the middle of its lines at `center` = (x, y) mm on the sheet."""
        eye, up, _r = P.view_axes(orient)
        if scale is None:
            first = not self.views
            scale = self.scale
            if first:                                             # the first view sets the sheet scale: the whole model fits (and room for the projected views)
                pr = P.project_axes(self.shape(mid), eye, up, orient, hidden=False)
                x0, y0, x1, y1 = pr.bbox()
                w, h = self.sheet_dims()
                self.scale = scale = fit_scale(x1 - x0, y1 - y0, w, h)
        v = self._new_view("model", mid, orient, eye, up, scale, style)
        pr = self.project(v)
        x0, y0, x1, y1 = pr.bbox()
        v["origin"] = [float(center[0]) - v["scale"] * (x0 + x1) / 2.0, float(center[1]) - v["scale"] * (y0 + y1) / 2.0]
        self.views.append(v)
        return v

    def projected_axes(self, parent, side):
        """(eye, up) of the view projected from `parent` to its `side`."""
        eye, up, right = P.frame_of(parent["eye"], parent["up"])
        s = OPPOSITE[side] if self.sheet["first_angle"] else side
        if s == "right":
            return right, up
        if s == "left":
            return -right, up
        if s == "up":
            return up, -eye
        return -up, eye

    def add_projected(self, parent_id, side, pos, style=None):
        """A view projected from `parent_id` to its `side` ("right", "left", "up", "down"); `pos` = (x, y) where the person clicked: only the coordinate along the axis counts (the
        other is the parent's: the views are aligned), and the lines are put there by the middle."""
        if side not in SIDES:
            raise DrawingError(f"'{side}' is not a side: right, left, up or down.")
        par = self.view(parent_id)
        eye, up = self.projected_axes(par, side)
        v = self._new_view("projected", par["model"], "Projected", eye, up, par["scale"], style or par["style"])
        v["parent"], v["side"] = par["id"], side
        pr = self.project(v)
        x0, y0, x1, y1 = pr.bbox()
        s = v["scale"]
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if side in ("right", "left"):
            v["origin"] = [float(pos[0]) - s * cx, par["origin"][1]]
        else:
            v["origin"] = [par["origin"][0], float(pos[1]) - s * cy]
        self.views.append(v)
        return v

    def side_of(self, parent_id, pos):
        """Which side of the parent a click at `pos` is on: the larger of the horizontal and the vertical distance from the middle of its lines decides."""
        x0, y0, x1, y1 = self.bbox(self.view(parent_id))
        dx, dy = pos[0] - (x0 + x1) / 2.0, pos[1] - (y0 + y1) / 2.0
        if abs(dx) >= abs(dy):
            return "right" if dx >= 0 else "left"
        return "up" if dy >= 0 else "down"

    def reproject(self, v):
        """The lines of a view again (the model, the style, the sheet's projection changed); a projected view takes the direction its side now means."""
        before = (v["eye"], v["up"])
        if v["kind"] == "projected":
            par = self.view(v["parent"])
            eye, up = self.projected_axes(par, v["side"])
            v["eye"], v["up"] = [float(x) for x in eye], [float(x) for x in up]
        self.project(v)
        self._annots_follow(v, _same_dir(before, (v["eye"], v["up"])))
        for c in self.children(v["id"]):
            self.reproject(c)

    def move_view(self, vid, x, y):
        """Puts the ORIGIN of a view's lines at (x, y)... as a move: a model view goes where it is put; a projected view only along its axis (the other coordinate stays the
        parent's).  The views projected from it move with it."""
        v = self.view(vid)
        ox, oy = v["origin"]
        nx, ny = float(x), float(y)
        if v["kind"] == "projected":
            par = self.view(v["parent"])
            if v["side"] in ("right", "left"):
                ny = par["origin"][1]
            else:
                nx = par["origin"][0]
        dx, dy = nx - ox, ny - oy
        v["origin"] = [nx, ny]
        for c in self.descendants(vid):
            c["origin"] = [c["origin"][0] + dx, c["origin"][1] + dy]
        return dx, dy

    def center_view(self, vid, x, y):
        """Moves a view so that the middle of its lines is at (x, y) (a projected view only along its axis); -> the step it made."""
        x0, y0, x1, y1 = self.bbox(self.view(vid))
        return self.shift_view(vid, x - (x0 + x1) / 2.0, y - (y0 + y1) / 2.0)

    def shift_view(self, vid, dx, dy):
        """Moves a view by (dx, dy) as the mouse does (a projected view only along its axis); -> the step it made."""
        v = self.view(vid)
        return self.move_view(vid, v["origin"][0] + dx, v["origin"][1] + dy)

    def set_scale(self, vid, scale):
        """A new scale for a view: the middle of its lines stays; a projected view stays in line with its parent, and the views projected from it stay in line with it."""
        v = self.view(vid)
        s = parse_scale(scale) if isinstance(scale, str) else float(scale)
        if not (s > 0):
            raise DrawingError("A scale must be over zero.")
        c0 = self.bbox(v)
        mid = ((c0[0] + c0[2]) / 2.0, (c0[1] + c0[3]) / 2.0)
        v["scale"] = s
        pr = self.projection(v)
        x0, y0, x1, y1 = pr.bbox()
        v["origin"] = [mid[0] - s * (x0 + x1) / 2.0, mid[1] - s * (y0 + y1) / 2.0]           # the middle of the lines stays where it was
        self._align(v)
        return s

    def _align(self, v):
        """A projected view has the origin of its model in line with its parent's (the cross coordinate); the views projected from it follow in turn."""
        if v["kind"] == "projected":
            par = self.view(v["parent"])
            if v["side"] in ("right", "left"):
                v["origin"][1] = par["origin"][1]
            else:
                v["origin"][0] = par["origin"][0]
        for c in self.children(v["id"]):
            self._align(c)

    def set_style(self, vid, style):
        if style not in STYLE_KEYS:
            raise DrawingError(f"'{style}' is not a display style.")
        v = self.view(vid)
        old = v["style"]
        v["style"] = style
        if (old == "hlr") != (style == "hlr"):                     # the hidden lines are needed (or not) by this style
            self.project(v)

    def set_orient(self, vid, name):
        v = self.view(vid)
        if v["kind"] != "model":
            raise DrawingError("A projected view looks along its parent: change the orientation of the parent.")
        eye, up, _r = P.view_axes(name)
        before = (v["eye"], v["up"])
        v["orient"], v["eye"], v["up"] = name, [float(x) for x in eye], [float(x) for x in up]
        self.project(v)
        self._annots_follow(v, _same_dir(before, (v["eye"], v["up"])))
        for c in self.children(vid):
            self.reproject(c)

    def remove_view(self, vid):
        """The view and the views projected from it."""
        self.view(vid)
        gone = {vid} | {c["id"] for c in self.descendants(vid)}
        for n in self.notes:                                       # a leader that pointed into a view that goes keeps pointing at the same place on the sheet
            if n.get("leader") and n["leader"].get("view") in gone:
                self._leader_to_sheet(n)
        self.views = [v for v in self.views if v["id"] not in gone]
        for k in ("notes", "dims", "balloons", "marks"):
            setattr(self, k, [a for a in getattr(self, k) if a.get("view") not in gone])

    # ---- dimensions and marks (what is drawn on a view; dr_annot.py)
    def annots(self, vid=None):
        """The dimensions and marks (of one view)."""
        return [a for a in self.dims + self.marks if vid is None or a.get("view") == vid]

    def sheet_items(self):
        """Everything that is drawn over the views, in the order it is painted: dimensions, marks, balloons, notes, drawing items."""
        return self.dims + self.marks + self.balloons + self.notes + self.lines

    def annot(self, aid):
        for a in self.sheet_items():
            if a.get("id") == aid:
                return a
        raise DrawingError("That item is not on the drawing.")

    def add_dim(self, vid, refs, kind=None):
        """A dimension on a view from what was picked on it (A.pick: points, lines, circles, arcs in the view's frame); -> the dimension.  Where it is drawn comes from place_annot."""
        v = self.view(vid)
        d = A.new_dim(refs, self.projection(v).bbox(), kind)
        if d is None:
            raise DrawingError("That does not make a dimension: pick a line, a circle, two points, a point and a line, or two lines.")
        self.counter["dim"] += 1
        d["id"], d["view"] = f"d{self.counter['dim']}", vid
        self.dims.append(d)
        return d

    def add_mark(self, vid, refs):
        """A center mark (one circle or arc) or a centerline (two parallel lines) on a view; -> the mark."""
        v = self.view(vid)
        kind = A.mark_kind_for(refs)
        if kind is None:
            raise DrawingError("A center mark goes on a circle or an arc, a centerline between two parallel lines.")
        m = A.new_mark(kind, refs, self.projection(v).bbox())
        self.counter["mark"] += 1
        m["id"], m["view"] = f"k{self.counter['mark']}", vid
        self.marks.append(m)
        return m

    def place_annot(self, aid, pointer):
        """Draws a dimension where the pointer is (sheet mm)."""
        a = self.annot(aid)
        if "refs" in a and a.get("type") in ("linear", "diameter", "radius", "angle"):
            v = self.view(a["view"])
            A.place(a, v["scale"], v["origin"], pointer)
        return a

    def remove_annot(self, aid):
        self.annot(aid)
        for k in ("dims", "marks", "balloons", "notes", "lines"):
            setattr(self, k, [a for a in getattr(self, k) if a.get("id") != aid])

    def lost_annots(self):
        """The dimensions and marks whose geometry is not in the model any more."""
        return [a for a in self.dims + self.marks if a.get("lost")]

    def dim_shape(self, a):
        v = self.view(a["view"])
        return A.mark_shape(a, v["scale"], v["origin"]) if a["type"] in ("center_mark", "centerline") else A.shape(a, v["scale"], v["origin"])

    def item_shape(self, a, mt=None):
        """The shape of any item drawn over the views (what is painted, picked): a dimension, a mark, a note, a balloon, a drawing item.  `mt` measures text (the renderer's font)."""
        t = a.get("type")
        mt = mt or IT.default_metrics
        if t == "note":
            return IT.note_shape(a, self.leader_tip(a), mt)
        if t == "balloon":
            return IT.balloon_shape(a, self.balloon_tip(a), mt)
        if t in IT.DRAW_TYPES:
            return IT.item_shape(a)
        return self.dim_shape(a)

    # ---- notes, balloons and drawing items (what is drawn on the sheet; dr_items.py)
    def _tip(self, vid, p):
        if vid is None:
            return (float(p[0]), float(p[1]))
        try:
            v = self.view(vid)
        except DrawingError:
            return None
        return (v["origin"][0] + v["scale"] * p[0], v["origin"][1] + v["scale"] * p[1])

    def leader_tip(self, n):
        """Where the leader of a note ends on the sheet (mm), None without a leader."""
        ld = n.get("leader")
        return self._tip(ld.get("view"), ld["p"]) if ld else None

    def balloon_tip(self, b):
        return self._tip(b.get("view"), b["tip"])

    def _leader_to_sheet(self, n):
        tip = self.leader_tip(n)
        if tip is None:
            n["leader"] = None
        else:
            n["leader"]["view"], n["leader"]["p"] = None, [tip[0], tip[1]]

    def add_note(self, text, pos, size=IT.NOTE_SIZE, leader=None):
        """A note with its top-left corner at pos (sheet mm); leader = {"kind": "straight" | "bent", "view": a view id or None, "p": the tip in the view's frame (or on the sheet)}."""
        if not str(text).strip():
            raise DrawingError("A note needs some text: type it in the panel first.")
        if leader and leader.get("view") is not None:
            self.view(leader["view"])
        n = IT.new_note(text, pos, size, leader)
        self.counter["note"] += 1
        n["id"] = f"n{self.counter['note']}"
        self.notes.append(n)
        return n

    def add_balloon(self, vid, text, tip, pos, snap=True):
        """A balloon on a view: its circle at pos (sheet mm), its leader to `tip` (the view's frame)."""
        self.view(vid)
        if not str(text).strip():
            raise DrawingError("A balloon needs a number: type it in the panel first.")
        b = IT.new_balloon(text, vid, tip, pos, snap)
        self.counter["balloon"] += 1
        b["id"] = f"b{self.counter['balloon']}"
        self.balloons.append(b)
        return b

    def add_item(self, kind, **geo):
        """A line, a rectangle, a circle or an arc on the sheet (dr_items.new_item)."""
        it = IT.new_item(kind, **geo)
        if it is None:
            raise DrawingError("That draws nothing: the points are on top of each other.")
        self.counter["draw"] += 1
        it["id"] = f"l{self.counter['draw']}"
        self.lines.append(it)
        return it

    def set_note(self, aid, text=None, size=None, leader=False):
        """Changes a note: its text, its size (points), its leader (None: no leader, "straight" or "bent"; a leader that is not there yet starts to the lower left of the text)."""
        n = self.annot(aid)
        if n.get("type") != "note":
            raise DrawingError("That is not a note.")
        if text is not None:
            if not str(text).strip():
                raise DrawingError("A note needs some text.")
            n["text"] = str(text)
        if size is not None:
            n["size"] = IT.clean_size(size)
        if leader is not False:
            if leader is None:
                n["leader"] = None
            elif n.get("leader"):
                n["leader"]["kind"] = "bent" if leader == "bent" else "straight"
            else:
                n["leader"] = {"kind": "bent" if leader == "bent" else "straight", "view": None, "p": [n["pos"][0] - 20.0, n["pos"][1] - 14.0]}
        return n

    def set_balloon_text(self, aid, text):
        b = self.annot(aid)
        if b.get("type") != "balloon":
            raise DrawingError("That is not a balloon.")
        if not str(text).strip():
            raise DrawingError("A balloon needs a number.")
        b["text"] = str(text).strip()
        return b

    def set_tip(self, aid, x, y, hit=None):
        """Drags the tip of a note's leader or of a balloon's leader to the sheet point (x, y).  hit = (view id, the point in that view's frame, snapped) when the pointer is on a view's lines
        (the tip then follows the view); without it a note's tip is a point of the sheet, and a balloon's stays in its own view."""
        a = self.annot(aid)
        if a.get("type") == "note":
            if not a.get("leader"):
                raise DrawingError("That note has no leader.")
            if hit is not None:
                a["leader"]["view"], a["leader"]["p"] = hit[0], [float(hit[1][0]), float(hit[1][1])]
            else:
                a["leader"]["view"], a["leader"]["p"] = None, [float(x), float(y)]
        elif a.get("type") == "balloon":
            if hit is not None:
                a["view"], a["tip"], a["snap"] = hit[0], [float(hit[1][0]), float(hit[1][1])], bool(hit[2])
            else:
                v = self.view(a["view"])
                a["tip"], a["snap"] = [(x - v["origin"][0]) / v["scale"], (y - v["origin"][1]) / v["scale"]], False
        else:
            raise DrawingError("That has no leader.")
        return a

    def move_item(self, aid, dx, dy):
        """Moves a note, a balloon (its circle) or a drawing item by (dx, dy) sheet mm."""
        a = self.annot(aid)
        if a.get("type") not in ("note", "balloon") + IT.DRAW_TYPES:
            raise DrawingError("A dimension moves by its own handles.")
        IT.translate(a, dx, dy)
        return a

    def place_item(self, aid, x, y):
        """Puts a note (its top-left corner) or a balloon (its circle) at the sheet point (x, y); -> the item."""
        a = self.annot(aid)
        if a.get("type") not in ("note", "balloon"):
            raise DrawingError("Only a note or a balloon is put down by its position.")
        a["pos"] = [float(x), float(y)]
        return a

    def drag_handle(self, aid, name, p):
        a = self.annot(aid)
        if a.get("type") not in IT.DRAW_TYPES:
            raise DrawingError("That has no handles.")
        return IT.drag_handle(a, name, p)

    def view_items(self, vid):
        """What is drawn on a view and goes with it: its dimensions, marks and balloons."""
        return [a for a in self.dims + self.marks + self.balloons if a.get("view") == vid]

    def _annots_follow(self, v, same_dir):
        """The lines of a view were drawn again: the dimensions and marks of it find their geometry again in them; when the view looks another way now they have nothing to hold on to
        and go, and so do the balloons of it; a note's leader that pointed into it stays where it points on the sheet."""
        if not same_dir:
            for n in self.notes:
                if n.get("leader") and n["leader"].get("view") == v["id"]:
                    self._leader_to_sheet(n)
            self.balloons = [b for b in self.balloons if b.get("view") != v["id"]]
        mine = [a for a in self.dims + self.marks if a.get("view") == v["id"]]
        if not mine:
            return
        if not same_dir:
            self.dims = [a for a in self.dims if a.get("view") != v["id"]]
            self.marks = [a for a in self.marks if a.get("view") != v["id"]]
            return
        pr = self.projection(v)
        A.rematch(mine, pr, pr.bbox())

    # ---- the file
    def to_json(self):
        d = {"format": FORMAT, "version": VERSION, "sheet": dict(self.sheet), "scale": self.scale, "counter": dict(self.counter), "models": self.models, "views": self.views,
             "notes": self.notes, "dims": self.dims, "balloons": self.balloons, "marks": self.marks, "lines": self.lines}
        return json.dumps(d, separators=(",", ":"), default=_plain)

    @classmethod
    def from_json(cls, text):
        try:
            d = json.loads(text)
        except ValueError as ex:
            raise DrawingError(f"This is not a drawing file: {ex}")
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            raise DrawingError("This is not an OpenPara drawing.")
        if int(d.get("version", 1)) > VERSION:
            raise DrawingError("This drawing was made by a newer version of the program.")
        o = cls()
        sh = d.get("sheet") or {}
        o.set_sheet(sh.get("size", S.DEFAULT) if sh.get("size") in [s[0] for s in S.SIZES] else S.DEFAULT, sh.get("landscape", True), False)
        o.sheet["first_angle"] = bool(sh.get("first_angle", False))
        o.scale = float(d.get("scale") or 1.0)
        o.counter.update({k: int(v) for k, v in (d.get("counter") or {}).items() if k in o.counter})
        o.models = [dict(m) for m in d.get("models", []) if isinstance(m, dict) and "id" in m]
        ids = {m["id"] for m in o.models}
        for v in d.get("views", []):
            if isinstance(v, dict) and v.get("model") in ids and v.get("style") in STYLE_KEYS:
                o.views.append(v)
        for k in ("dims", "marks"):
            setattr(o, k, [dict(x) for x in d.get(k, []) if isinstance(x, dict)])
        for k in ("notes", "balloons", "lines"):                  # what is not a whole record is left out: the rest of the drawing opens
            setattr(o, k, [dict(x) for x in d.get(k, []) if isinstance(x, dict) and IT.valid(x)])
        view_ids = {v["id"] for v in o.views}
        o.balloons = [b for b in o.balloons if b["view"] in view_ids]
        return o

    def snapshot(self):
        """Everything that can change, as a value to come back to (undo): the models are shared, not copied (their data never changes in place)."""
        return {"sheet": dict(self.sheet), "scale": self.scale, "counter": dict(self.counter), "models": [dict(m) for m in self.models], "views": copy.deepcopy(self.views),
                "annot": {k: copy.deepcopy(getattr(self, k)) for k in ANNOT}}

    def restore(self, snap):
        self.sheet, self.scale, self.counter = dict(snap["sheet"]), snap["scale"], dict(snap["counter"])
        self.models = [dict(m) for m in snap["models"]]
        self.views = copy.deepcopy(snap["views"])
        for k in ANNOT:
            setattr(self, k, copy.deepcopy(snap["annot"][k]))
        self.cache = {}
        self._pcache = {}

    def used_counters(self):
        return self.counter


def _same_dir(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for u, w in zip(a, b) for x, y in zip(u, w))


def _plain(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(f"{type(o).__name__} is not JSON")
