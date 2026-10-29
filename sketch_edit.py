"""
sketch_edit.py - sketching directly in the 3D view (SolidWorks style), on top of the constraint solver (sketcher_core.Model).

The sketch lives on a plane (origin o, axes x, y, normal z) and is drawn as real 3D lines on a second VTK layer on top of the part, so it
follows the camera by itself: orbit, pan and zoom while sketching and it stays on its plane.  A mouse click is turned into plane
coordinates by shooting a ray through the pixel and cutting it with the plane.

The sketch itself is a sketcher_core.Model (points, lines, circles, arcs, constraints, dimensions); the geometry of every tool is in
sk_tools.py.  Drawing snaps to existing points (re-using them, so shapes are joined) and to lines / circles (a coincident relation is
added), and lines that are almost horizontal or vertical get that relation.  Colours: blue = still has freedom, green = fully defined,
red = conflicting relations, orange = selected, grey = construction.
"""
import copy
import math

import numpy as np
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QInputDialog, QLineEdit,
                             QMessageBox, QVBoxLayout)

import sk_tools as sk
import sketcher_core as sc
import sketcher_offset as skoff

try:
    import pyvista as pv
    from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkRenderer
except Exception:                                           # the editor then stays inactive (the window says why)
    pv = None
try:
    from vtkmodules.vtkRenderingCore import vtkBillboardTextActor3D
except Exception:
    vtkBillboardTextActor3D = None

COL_FREE, COL_FIXED, COL_BAD = (0.05, 0.30, 0.85), (0.10, 0.60, 0.20), (0.85, 0.10, 0.10)
COL_SEL, COL_CONSTR, COL_PREVIEW, COL_TAG = (1.0, 0.45, 0.0), (0.50, 0.55, 0.70), (0.45, 0.55, 0.75), (0.10, 0.10, 0.10)
COL_ORIGIN = (0.80, 0.15, 0.55)
AX_U, AX_V = (0.85, 0.15, 0.15), (0.15, 0.65, 0.15)
SNAP_PX, PICK_PX, TAG_PX, EDGE_ON_COS = 12.0, 9.0, 16.0, 0.12

CONSTRAINTS = ("horizontal", "vertical", "parallel", "perpendicular", "collinear", "coincident", "concentric", "tangent", "equal", "fixed",
               "midpoint")
DIMS = tuple(sc.DIMENSIONS)


def fmt(v):
    v = round(float(v), 4)
    return str(int(v)) if v == int(v) else str(v)


# ---------------------------------------------------------------------------------------------------- dialogs (module functions: tests replace them)
def ask_form(parent, title, fields, checks=()):
    """fields [(label, default)], checks [(label, default)] -> ([floats], [bools]) or None."""
    d = QDialog(parent)
    d.setWindowTitle(title)
    lay = QVBoxLayout(d)
    form = QFormLayout()
    lay.addLayout(form)
    spins = []
    for label, val in fields:
        s = QDoubleSpinBox()
        s.setRange(-1e9, 1e9)
        s.setDecimals(6)
        s.setValue(val)
        form.addRow(label, s)
        spins.append(s)
    boxes = []
    for label, val in checks:
        c = QCheckBox(label)
        c.setChecked(val)
        lay.addWidget(c)
        boxes.append(c)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    lay.addWidget(bb)
    if d.exec() != QDialog.DialogCode.Accepted:
        return None
    return [s.value() for s in spins], [c.isChecked() for c in boxes]


def ask_dim(parent, title, text, symbols):
    """A number, a symbol name or an expression (e.g. Width/2) -> text or None."""
    t, ok = QInputDialog.getText(parent, title, "Value, symbol or equation  (a new name makes a symbol; globals such as Width can be used):\n"
                                 + ("Existing: " + ", ".join(symbols) if symbols else ""), QLineEdit.EchoMode.Normal, text)
    return t.strip() if ok else None


def ask_yes(parent, title, text):
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


# ---------------------------------------------------------------------------------------------------- which picks complete a relation (as in the old sketcher)
def make_constraint(tool, picks):
    """Do the picked entities complete the tool?  -> refs, 'more' or None (invalid)."""
    k = [p[0] for p in picks]
    if tool in ("horizontal", "vertical", "dim_h", "dim_v", "dim_len"):
        if k == ["ln"]:
            return picks
        if k == ["pt"]:
            return "more"
        if k == ["pt", "pt"] and picks[0] != picks[1]:
            return picks
        return None
    if tool in ("parallel", "perpendicular", "collinear"):
        if k == ["ln"]:
            return "more"
        return picks if k == ["ln", "ln"] and picks[0] != picks[1] else None
    if tool == "equal":
        if len(k) == 1:
            return "more" if k[0] in ("ln", "ci", "ar") else None
        lines = all(x == "ln" for x in k)
        rounds = all(x in ("ci", "ar") for x in k)
        return picks if (lines or rounds) and len(set(picks)) == len(picks) else None
    if tool == "concentric":
        if len(k) == 1:
            return "more" if k[0] in ("ci", "ar") else None
        return picks if k[1] in ("ci", "ar") and picks[0] != picks[1] else None
    if tool == "tangent":
        if len(k) == 1:
            return "more" if k[0] in ("ln", "ci", "ar") else None
        return picks if sorted(["ln" if x == "ln" else "c" for x in k]) == ["c", "ln"] else None
    if tool == "coincident":
        if len(k) == 1:
            return "more" if k[0] in ("pt", "ln", "ci", "ar") else None
        if "pt" not in k or picks[0] == picks[1]:
            return None
        return picks
    if tool == "fixed":
        return picks if k == ["pt"] else None
    if tool == "midpoint":
        if len(k) == 1:
            return "more" if k[0] in ("pt", "ln") else None
        return picks if sorted(k) == ["ln", "pt"] else None
    if tool in ("dim_rad", "dim_dia"):
        return picks if k in (["ci"], ["ar"]) else None
    if tool == "dim_ang":
        if k == ["ln"]:
            return "more"
        return picks if k == ["ln", "ln"] and picks[0] != picks[1] else None
    return None


# ---------------------------------------------------------------------------------------------------- the drawing tools: clicks needed and the geometry builder
DRAW = {                                   # name: (clicks, builder(model, specs, editor), prompts)
    "midline": (2, lambda m, p, e: sk.add_midpoint_line(m, p[0], p[1]), ["Click the middle", "Click an end"]),
    "rect_corner": (2, lambda m, p, e: sk.add_rect_corner(m, p[0], p[1]), ["First corner", "Opposite corner"]),
    "rect_center": (2, lambda m, p, e: sk.add_rect_center(m, p[0], p[1]), ["Centre", "A corner"]),
    "rect_3pt": (3, lambda m, p, e: sk.add_rect_3pt(m, p[0], p[1], p[2]), ["Corner", "Next corner (sets the angle)", "A point that sets the width"]),
    "rect_3pt_center": (3, lambda m, p, e: sk.add_rect_3pt_center(m, p[0], p[1], p[2]),
                        ["Centre", "Middle of one side (sets the angle)", "A point that sets the half width"]),
    "parallelogram": (3, lambda m, p, e: sk.add_parallelogram(m, p[0], p[1], p[2]), ["First corner", "Second corner", "Third corner"]),
    "circle": (2, lambda m, p, e: sk.add_circle(m, p[0], p[1]), ["Centre", "A point on the circle"]),
    "circle_3pt": (3, lambda m, p, e: sk.add_circle_3pt(m, p[0], p[1], p[2]), ["First point on the circle", "Second point", "Third point"]),
    "arc_center": (3, lambda m, p, e: sk.add_arc_center(m, p[0], p[1], p[2], e.arc_cw()), ["Centre", "Start point",
                                                                                      "End point (move round the centre to pick the direction)"]),
    "arc_3pt": (3, lambda m, p, e: sk.add_arc_3pt(m, p[0], p[1], p[2]), ["Start point", "End point", "A point on the arc"]),
    "arc_tangent": (2, None, ["Click the end of a line or arc to continue from", "End point of the arc"]),
    "slot_straight": (3, lambda m, p, e: sk.add_slot_straight(m, p[0], p[1], p[2]), ["First end centre", "Second end centre", "A point that sets the width"]),
    "slot_center": (3, lambda m, p, e: sk.add_slot_center(m, p[0], p[1], p[2]), ["Centre", "An end centre", "A point that sets the width"]),
    "slot_arc_center": (4, lambda m, p, e: sk.add_slot_arc_center(m, p[0], p[1], p[2], p[3]),
                        ["Arc centre", "Start (centre of the slot end)", "End (centre of the slot end)", "A point that sets the width"]),
    "slot_arc_3pt": (4, lambda m, p, e: sk.add_slot_arc_3pt(m, p[0], p[1], p[2], p[3]),
                     ["Start (slot end centre)", "End (slot end centre)", "A point on the centre arc", "A point that sets the width"]),
    "polygon": (2, lambda m, p, e: sk.add_polygon(m, p[0], p[1], e.poly_n), ["Centre", "A corner (sets size and rotation)"]),
    "point": (1, lambda m, p, e: sk.pid(m, p[0]), ["Click where the point goes"]),
}
CHAIN = {"line": False, "centerline": True}
EDIT = ("trim", "fillet", "mirror", "convert")
ALL_TOOLS = ("select",) + tuple(CHAIN) + tuple(DRAW) + EDIT + CONSTRAINTS + DIMS


def wrap_pi(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class SketchEditor:
    def __init__(self, app):
        self.app = app
        self.pl = app.plotter
        self.sk_id = None
        self.tool = "select"
        self.pending = []                 # point specs already clicked for the shape being drawn
        self.cursor = None                # (u, v) under the mouse (snapped), or None
        self.snapped = None               # "pt" / "on" / None
        self.sel = []                     # selected keys: ("pt", id) ("ln", id) ("ci", id) ("ar", id) ("con", id)
        self.picks = []                   # picks of the relation / dimension tool in progress
        self.press_px = None
        self.press_first = False
        self.drag = None                  # [point id, moved?]
        self.host = None                  # tangent arc: the line / arc it continues
        self.poly_n = 6
        self.fillet_r = 5.0
        self.axis_wait = False
        self.arc_acc, self.arc_last = 0.0, None
        self.tags = []                    # (u, v, con id) positions of the dimension labels
        self.ren = None
        self.actors = []
        self.size_fn = self.default_size  # (W, H) of the view in device pixels (tests replace it)

    @property
    def active(self):
        return self.sk_id is not None

    @property
    def m(self):
        return self.app.doc.models.get(self.sk_id) if self.sk_id else None

    @property
    def rep(self):
        return self.app.doc.reports.get(self.sk_id)

    # ------------------------------------------------------------------ the sketch and its plane
    def sketch(self):
        return self.app.doc.feature(self.sk_id) if self.sk_id else None

    def plane(self):
        p = self.app.doc.planes.get(self.sk_id)
        if p is None:
            return None
        return (np.array(tuple(p.origin)), np.array(tuple(p.x_dir)), np.array(tuple(p.y_dir)), np.array(tuple(p.z_dir)))

    def default_size(self):
        r = self.pl.devicePixelRatioF()
        return max(1.0, self.pl.width() * r), max(1.0, self.pl.height() * r)

    def begin(self, sk_id):
        self.sk_id = sk_id
        self.reset_tool("select")
        self.sel = []
        self.normal_to()

    def end(self):
        self.sk_id, self.pending, self.cursor, self.sel, self.picks = None, [], None, [], []
        self.clear_actors()
        try:
            self.pl.camera.ParallelProjectionOff()
        except Exception:
            pass
        self.pl.render()

    def reset_tool(self, name):
        self.tool, self.pending, self.picks, self.host, self.axis_wait = name, [], [], None, False
        self.arc_acc, self.arc_last = 0.0, None

    # ------------------------------------------------------------------ camera maths
    def matrix(self):
        W, H = self.size_fn()
        m = self.pl.camera.GetCompositeProjectionTransformMatrix(W / H, -1, 1)
        return np.array([[m.GetElement(i, j) for j in range(4)] for i in range(4)]), W, H

    def to_screen(self, P):
        """World points (N, 3) -> device pixels (N, 2), origin at the bottom left."""
        M, W, H = self.matrix()
        P = np.atleast_2d(np.asarray(P, float))
        h = np.hstack([P, np.ones((len(P), 1))]) @ M.T
        return np.column_stack([(h[:, 0] / h[:, 3] + 1) / 2 * W, (h[:, 1] / h[:, 3] + 1) / 2 * H])

    def ray(self, px, py):
        M, W, H = self.matrix()
        inv = np.linalg.inv(M)
        pts = []
        for z in (-1.0, 1.0):
            v = inv @ np.array([2 * px / W - 1, 2 * py / H - 1, z, 1.0])
            pts.append(v[:3] / v[3])
        return pts[0], pts[1] - pts[0]

    def to_plane(self, px, py):
        """Plane coordinates (u, v) under a pixel, or None when the plane is seen edge-on."""
        pl = self.plane()
        if pl is None:
            return None
        o, xd, yd, zd = pl
        p0, d = self.ray(px, py)
        den = float(zd @ d)
        if abs(den) < 1e-12 * max(1.0, float(np.linalg.norm(d))):
            return None
        P = p0 + d * (float((o - p0) @ zd) / den)
        return float((P - o) @ xd), float((P - o) @ yd)

    def to_world(self, uv):
        o, xd, yd, _ = self.plane()
        uv = np.atleast_2d(np.asarray(uv, float))
        return o + uv[:, :1] * xd + uv[:, 1:2] * yd

    def screen_of(self, uv):
        return self.to_screen(self.to_world(uv))

    def edge_on(self):
        pl = self.plane()
        if pl is None:
            return True
        cam = self.pl.camera
        d = np.array(cam.GetFocalPoint()) - np.array(cam.GetPosition())
        return abs(float(pl[3] @ d)) / max(float(np.linalg.norm(d)), 1e-12) < EDGE_ON_COS

    def normal_to(self):
        """Turn the view to look straight at the sketch plane (from the side the normal points to), orthographic, centred on the part."""
        pl = self.plane()
        if pl is None:
            return
        o, xd, yd, zd = pl
        c, size = o.copy(), 60.0
        solid = self.app.doc.solid
        if solid is not None:
            b = solid.bounding_box()
            ctr = np.array([(b.min.X + b.max.X) / 2, (b.min.Y + b.max.Y) / 2, (b.min.Z + b.max.Z) / 2])
            c = o + float((ctr - o) @ xd) * xd + float((ctr - o) @ yd) * yd
            size = max(b.size.X, b.size.Y, b.size.Z, 20.0)
        cam = self.pl.camera
        cam.ParallelProjectionOn()
        cam.SetFocalPoint(*c)
        cam.SetPosition(*(c + zd * size * 4))
        cam.SetViewUp(*yd)
        cam.SetParallelScale(0.75 * size)
        self.pl.renderer.reset_camera_clipping_range()
        self.redraw()

    # ------------------------------------------------------------------ picking and snapping
    def keys(self, m=None):
        m = m or self.m
        return sk.all_keys(m) if m is not None else []

    def poly_screen(self, key):
        return self.screen_of(sk.polyline(self.m, key, 48))

    @staticmethod
    def seg_dist(s, px, py):
        """Smallest distance from the pixel to the polyline s, and the point on it (pixel)."""
        a, b = s[:-1], s[1:]
        ab = b - a
        P = np.array([px, py])
        t = np.clip(np.einsum("ij,ij->i", P - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
        q = a + ab * t[:, None]
        d = np.linalg.norm(q - P, axis=1)
        i = int(np.argmin(d))
        return float(d[i]), i, float(t[i])

    def pick_point(self, px, py, px_tol):
        m = self.m
        ids = [i for i in m.pts]
        if not ids:
            return None
        scr = self.screen_of(np.array([m.pts[i] for i in ids]))
        d = np.linalg.norm(scr - np.array([px, py]), axis=1)
        j = int(np.argmin(d))
        return ids[j] if d[j] <= px_tol else None

    def pick_tag(self, px, py):
        if not self.tags:
            return None
        scr = self.screen_of(np.array([(u, v) for u, v, _ in self.tags]))
        d = np.linalg.norm(scr - np.array([px, py]), axis=1)
        j = int(np.argmin(d))
        return self.tags[j][2] if d[j] <= TAG_PX * self.pl.devicePixelRatioF() else None

    def pick(self, px, py, kinds=None):
        """The entity under the pixel: points first, then the closest line / arc / circle.  -> ("pt", id) ... or None."""
        m = self.m
        if m is None:
            return None
        r = self.pl.devicePixelRatioF()
        if kinds is None or "pt" in kinds:
            p = self.pick_point(px, py, PICK_PX * r)
            if p is not None:
                return ("pt", p)
        best, bd = None, PICK_PX * r
        for key in self.keys():
            if kinds is not None and key[0] not in kinds:
                continue
            try:
                d = self.seg_dist(self.poly_screen(key), px, py)[0]
            except Exception:
                continue
            if d < bd:
                best, bd = key, d
        return best

    def snap(self, uv, px, py):
        """-> (spec, (u, v), kind).  spec: ("pt", id) an existing point, ("on", key, u, v) a spot on an entity, or (u, v) a free spot."""
        r = self.pl.devicePixelRatioF()
        p = self.pick_point(px, py, SNAP_PX * r)
        if p is not None:
            return ("pt", p), tuple(self.m.pts[p]), "pt"
        mv = self.model_vertex(px, py, SNAP_PX * r)
        if mv is not None:
            return mv, mv, "pt"
        key = self.pick(px, py, kinds=("ln", "ci", "ar"))
        if key is not None:
            s = self.poly_screen(key)
            _d, i, t = self.seg_dist(s, px, py)
            pl = sk.polyline(self.m, key, 48)
            q = pl[i] + (pl[i + 1] - pl[i]) * t
            return ("on", key, float(q[0]), float(q[1])), (float(q[0]), float(q[1])), "on"
        u, v = round(uv[0], 2), round(uv[1], 2)
        return (u, v), (u, v), None

    def model_vertex(self, px, py, tol):
        """Corner of the part near the pixel -> its (u, v) in the sketch plane (a position only, no link to the part)."""
        solid = self.app.shown_solid()
        if solid is None:
            return None
        if self._mv_key is not solid:
            self._mv_key = solid
            try:
                self._mv = np.array([[v.X, v.Y, v.Z] for v in solid.vertices()])
            except Exception:
                self._mv = np.zeros((0, 3))
        if not len(self._mv):
            return None
        d = np.linalg.norm(self.to_screen(self._mv) - np.array([px, py]), axis=1)
        j = int(np.argmin(d))
        if d[j] > tol:
            return None
        o, xd, yd, _ = self.plane()
        p = self._mv[j] - o
        return (round(float(p @ xd), 6), round(float(p @ yd), 6))

    _mv_key, _mv = None, None

    def coords(self, spec, m=None):
        m = m or self.m
        if sk.is_ref(spec):
            return tuple(m.pts[spec[1]])
        if spec[0] == "on":
            return (spec[2], spec[3])
        return (float(spec[0]), float(spec[1]))

    def resolve(self, m, spec):
        """A spec -> a point reference or coordinates for the builders; a spot on an entity becomes a new point tied to it."""
        if not sk.is_ref(spec) and spec[0] == "on":
            p = m.add_point(spec[2], spec[3])
            sk.con(m, "coincident", [("pt", p), spec[1]], auto=True)
            return ("pt", p)
        return spec

    # ------------------------------------------------------------------ the mouse
    def point_at(self, px, py):
        uv = self.to_plane(px, py)
        if uv is None:
            return None
        spec, xy, kind = self.snap(uv, px, py)
        self.snapped = kind
        return spec, xy

    def press(self, px, py):
        """A left click.  Returns True when the editor used it."""
        if not self.active or self.m is None:
            return False
        if self.edge_on():
            self.app.say("The sketch plane is seen edge-on - press Normal To.")
            return True
        self.press_px = (px, py)
        shift = bool(getattr(self.app, "shift", False))
        t = self.tool
        if t == "select":
            tag = self.pick_tag(px, py)
            key = ("con", tag) if tag is not None else self.pick(px, py)
            if key is None:
                if not shift:
                    self.sel = []
                self.after_select()
                self.redraw()
                self.app.pick_model(px, py, shift)             # nothing of the sketch here: pick an edge / face of the part
                return True
            elif shift:
                self.sel = [k for k in self.sel if k != key] if key in self.sel else self.sel + [key]
            else:
                self.sel = [key]
                if key[0] == "pt" and key[1] != 0:
                    self.drag = [key[1], False]
            self.after_select()
            self.redraw()
            return True
        if t in DRAW or t in CHAIN:
            hit = self.point_at(px, py)
            if hit is None:
                return True
            self.cursor = hit[1]
            self.press_first = not self.pending
            self.click(hit[0], hit[1])
            return True
        if t == "trim":
            key = self.pick(px, py, kinds=("ln", "ar", "ci"))
            uv = self.to_plane(px, py)
            if key is None or uv is None:
                self.app.say("Click the piece of a line, arc or circle to trim away.")
                return True
            self.commit(lambda m: sk.trim(m, key, uv))
            return True
        if t == "fillet":
            p = self.pick_point(px, py, SNAP_PX * self.pl.devicePixelRatioF())
            if p is None:
                self.app.say("Click the corner (the point where two lines meet).")
                return True
            self.commit(lambda m: sk.fillet_corner(m, p, self.fillet_r))
            return True
        if t == "mirror" and self.axis_wait:
            key = self.pick(px, py, kinds=("ln",))
            if key is None:
                self.app.say("Click the line to mirror about (a centerline is usual).")
                return True
            ents = [k for k in self.sel if k[0] in ("ln", "ci", "ar") and k != key]
            self.commit(lambda m: sk.mirror(m, ents, key[1]))
            self.reset_tool("select")
            self.app.sync_tool()
            return True
        if t in CONSTRAINTS or t in DIMS:
            key = self.pick(px, py, kinds=("pt", "ln", "ci", "ar"))
            if key is None:
                return True
            self.picks.append(key)
            self.try_apply()
            self.redraw()
            return True
        return True

    def after_select(self):
        self.app.say(self.describe_selection())

    def describe_selection(self):
        if not self.sel:
            return "Nothing selected."
        m = self.m
        bits = []
        for k, i in self.sel[:4]:
            try:
                if k == "pt":
                    bits.append(f"point ({m.pts[i][0]:.3f}, {m.pts[i][1]:.3f})")
                elif k == "ln":
                    a, b = m.line_pts(i)
                    bits.append(f"line, length {math.hypot(b[0] - a[0], b[1] - a[1]):.3f}")
                elif k == "ci":
                    bits.append(f"circle, diameter {2 * m.cis[i]['r']:.3f}")
                elif k == "ar":
                    bits.append(f"arc, radius {sk.arc_span(m, i)[1]:.3f}")
                elif k == "con":
                    c = m.con_by_id(i)
                    bits.append(f"{c['type']} {c.get('name', '')}")
            except Exception:
                pass
        return "Selected: " + "; ".join(bits) + (f" (+{len(self.sel) - 4} more)" if len(self.sel) > 4 else "")

    def release(self, px, py):
        """Press-drag-release: the release point is the second point of the shape (for the first click only)."""
        if not self.active:
            return False
        if self.drag is not None:
            moved = self.drag[1]
            self.drag = None
            if moved:
                self.finish_drag()
            return True
        if self.press_px is None:
            return False
        moved = math.hypot(px - self.press_px[0], py - self.press_px[1]) > 6 * self.pl.devicePixelRatioF()
        self.press_px = None
        if moved and self.press_first and self.pending and (self.tool in DRAW or self.tool in CHAIN):
            hit = self.point_at(px, py)
            if hit is not None:
                self.click(hit[0], hit[1])
        self.press_first = False
        return True

    def move(self, px, py):
        if not self.active or self.m is None or self.edge_on():
            return
        if self.drag is not None:
            uv = self.to_plane(px, py)
            if uv is None:
                return
            if not self.drag[1]:
                self.app.snapshot()
                self.drag[1] = True
            self.m.solve(pin=(self.drag[0], round(uv[0], 3), round(uv[1], 3)))
            self.redraw()
            return
        if self.tool == "select":
            return
        hit = self.point_at(px, py)
        self.cursor = hit[1] if hit else None
        if self.tool == "arc_center" and len(self.pending) == 2 and self.cursor is not None:
            c = self.coords(self.pending[0])
            a = math.atan2(self.cursor[1] - c[1], self.cursor[0] - c[0])
            if self.arc_last is not None:
                self.arc_acc += wrap_pi(a - self.arc_last)
            self.arc_last = a
        self.redraw()

    def double_click(self, px=None, py=None):
        if self.tool in CHAIN:
            self.pending = []
            self.redraw()
        elif self.tool == "select":
            for k in self.sel:
                if k[0] == "con":
                    self.edit_dimension(k[1])
                    return

    def arc_cw(self):
        return self.arc_acc < 0

    # ------------------------------------------------------------------ drawing with the tools
    def click(self, spec, xy):
        t, p = self.tool, self.pending
        if t in CHAIN:
            if not p:
                self.pending, self.chain_start = [spec], None
            elif self.coords(p[-1]) != xy:
                last, h = p[-1], {}

                def build(m):
                    lid = sk.add_line(m, self.resolve(m, last), self.resolve(m, spec), construction=CHAIN[t])
                    h["s"], h["e"] = m.lns[lid]

                if self.commit(build, refresh=False) is None and "e" in h:
                    if self.chain_start is None:
                        self.chain_start = h["s"]
                    closed = h["e"] == self.chain_start
                    self.pending = [] if closed else [("pt", h["e"])]
                    if closed:
                        self.chain_start = None
                    self.app.update_all(keep_props=False)
        elif t == "arc_tangent":
            if not p:
                if not sk.is_ref(spec):
                    self.app.say("Click the end point of an existing line or arc.")
                    return
                host = self.host_of(spec[1])
                if host is None:
                    self.app.say("That point is not the end of a line or arc.")
                    return
                self.pending, self.host = [spec], host
            else:
                s, host = p[0], self.host
                self.commit(lambda m: sk.add_arc_tangent(m, s[1], host, self.resolve(m, spec)))
                self.pending, self.host = [], None
        elif t in DRAW:
            n, fn, _ = DRAW[t]
            self.pending = p + [spec]
            if len(self.pending) == 2 and t == "arc_center":
                self.arc_acc, self.arc_last = 0.0, None
            if len(self.pending) >= n:
                specs = self.pending
                self.commit(lambda m: fn(m, [self.resolve(m, s) for s in specs], self))
                self.pending = []
                self.arc_acc, self.arc_last = 0.0, None
        self.redraw()
        self.say_prompt()

    chain_start = None

    def host_of(self, pid):
        m = self.m
        for i, (a, b) in m.lns.items():
            if pid in (a, b) and ("ln", i) not in m.constr:
                return ("ln", i)
        for i, ar in m.ars.items():
            if pid in (ar["s"], ar["e"]):
                return ("ar", i)
        return None

    def say_prompt(self):
        t = self.tool
        if t in DRAW:
            pr = DRAW[t][2]
            self.app.say(pr[min(len(self.pending), len(pr) - 1)])
        elif t in CHAIN:
            self.app.say("Click the next point (double-click or Esc ends the chain)." if self.pending else "Click the start point.")
        elif t == "arc_tangent":
            self.app.say(DRAW[t][2][min(len(self.pending), 1)])

    def commit(self, fn, refresh=True):
        """Run `fn(model)` as one undoable edit, re-solve, store the sketch and rebuild."""
        m = self.m
        self.app.snapshot()
        try:
            res = fn(m)
        except Exception as ex:
            self.app.say("That failed: " + str(ex))
            self.app.undo_pop()
            return None
        if isinstance(res, str):
            self.app.say(res)
            self.app.undo_pop()
            return res
        self.app.doc.reports[self.sk_id] = sk.solve_model(m)
        self.app.doc.store_sketch(self.sk_id)
        if refresh:
            self.app.update_all(keep_props=False)
        return res

    def finish_drag(self):
        m = self.m
        self.app.doc.reports[self.sk_id] = sk.solve_model(m)
        self.app.doc.store_sketch(self.sk_id)
        self.app.update_all(keep_props=False)

    # ------------------------------------------------------------------ relations and dimensions
    def try_apply(self):
        res = make_constraint(self.tool, self.picks)
        if res == "more":
            self.app.say("Pick the next entity.")
            return
        if res is None:
            self.app.say("That does not fit this tool - pick again.")
            self.picks = []
            return
        self.apply(self.tool, res)
        self.picks = []

    def apply(self, tool, refs):
        m = self.m
        kw = {}
        if tool == "fixed":
            kw["xy"] = tuple(m.pts[refs[0][1]])
        if tool in DIMS:
            if tool == "dim_ang":
                s1, s2, eps, cur = m.angle_default(refs, hint=self.cursor)
                kw.update(s1=s1, s2=s2, eps=eps)
            else:
                cur = m.measure(tool, refs)
            nxt = m.next_dim_name(tool, list(self.app.doc.params))
            txt = ask_dim(self.app, "Dimension " + nxt, f"{cur:g}", list(m.params))
            if txt is None:
                return
            try:
                expr, val = self.dim_from_text(m, txt, cur)
            except ValueError as ex:
                self.app.say(str(ex))
                return
            kw["value"] = val
            kw["name"] = expr if expr and expr.isidentifier() else nxt
            if expr:
                kw["expr"] = expr
            if tool in ("dim_h", "dim_v"):
                pa, pb = m._two_points(refs)
                k = 0 if tool == "dim_h" else 1
                kw["sign"] = 1 if pb[k] - pa[k] >= 0 else -1

        def build(mm):
            c = mm.add_con(tool, refs, **kw)
            self.last_con = c["id"]

        self.commit(build, refresh=False)
        rep = self.rep
        if rep is not None and self.last_con in rep.conflicts:
            self.app.say("Warning: that conflicts with the existing relations (shown red).")
        elif rep is not None and self.last_con in rep.redundant:
            self.app.say("Note: that is redundant (already implied by other relations).")
        self.app.doc.store_sketch(self.sk_id)
        self.app.update_all(keep_props=False)

    last_con = None

    @staticmethod
    def dim_from_text(m, text, value):
        """What was typed -> (expression or None, number).  A new name makes a symbol.  Raises ValueError."""
        t = text.strip().lstrip("=").strip()
        if not t:
            return None, value
        try:
            return None, float(t)
        except ValueError:
            pass
        try:
            syms = sc.expr_symbols(t)
        except SyntaxError:
            raise ValueError(f"'{t}' is not a valid expression")
        missing = [s for s in syms if s not in m.params]
        if t.isidentifier() and t in missing:
            m.add_param(t, value)
        elif missing:
            raise ValueError("Unknown symbol(s): " + ", ".join(missing))
        try:
            val = sc.safe_eval(t, m.param_values())
        except Exception:
            raise ValueError(f"Cannot evaluate '{t}'")
        return t, float(val) if isinstance(val, (int, float)) else value

    def edit_dimension(self, cid):
        m = self.m
        c = m.con_by_id(cid)
        if not c or c["type"] not in DIMS:
            return
        txt = ask_dim(self.app, "Dimension " + c.get("name", ""), c.get("expr") or f"{c['value']:g}", list(m.params))
        if txt is None:
            return
        self.set_dimension(cid, txt)

    def set_dimension(self, cid, txt):
        def build(m):
            c = m.con_by_id(cid)
            expr, val = self.dim_from_text(m, txt, c["value"])
            c["value"] = val
            if expr:
                c["expr"] = expr
                if expr.isidentifier():
                    c["name"] = expr
            else:
                c.pop("expr", None)
        r = self.commit(build, refresh=False)
        self.app.update_all(keep_props=True)
        return r

    def cancel(self):
        """Esc: drop the shape / relation being made; else go back to the select tool; else leave the sketch."""
        if self.pending or self.picks or self.axis_wait:
            self.pending, self.picks, self.host, self.axis_wait = [], [], None, False
            self.redraw()
        elif self.tool != "select":
            self.app.set_tool("select")
        else:
            self.app.leave_sketch()

    def start_relation(self, name):
        """Add Relation / Dimension from the ribbon: entities that are already selected are used at once."""
        self.reset_tool(name)
        self.picks = [k for k in self.sel if k[0] in ("pt", "ln", "ci", "ar")]
        if self.picks:
            res = make_constraint(name, self.picks)
            if res is None:
                self.picks = []
                self.app.say("The selection does not fit; click the entities one at a time.")
            elif res != "more":
                self.try_apply()
                return
        self.app.say({"fixed": "Click a point to fix.", "midpoint": "Click a point, then a line."}.get(name, "Click the entities."))

    def command_construction(self):
        """Turn the selected lines / arcs / circles into construction geometry (or back, when they all are)."""
        ents = self.entities_selected()
        if not ents:
            self.app.say("Select lines, arcs or circles first.")
            return

        def build(m):
            on = all(k in m.constr for k in ents)
            for k in ents:
                if on:
                    m.constr.discard(k)
                else:
                    m.constr.add(k)
        self.commit(build)

    def context_actions(self, px, py):
        """[(label, function)] for a right click: acts on the selection (the entity under the cursor is selected first)."""
        key = None
        tag = self.pick_tag(px, py)
        key = ("con", tag) if tag is not None else self.pick(px, py)
        if key is not None and key not in self.sel:
            self.sel = [key]
            self.redraw()
        out = []
        ents = self.entities_selected()
        if ents:
            on = all(k in self.m.constr for k in ents)
            out.append(("Normal geometry" if on else "Make construction", self.command_construction))
        if any(k[0] in ("ln", "ci", "ar", "pt", "con") for k in self.sel):
            out.append(("Delete", self.delete_selected))
        if any(k[0] == "con" for k in self.sel):
            out.append(("Edit dimension...", lambda: [self.edit_dimension(k[1]) for k in self.sel[:1] if k[0] == "con"]))
        if not out:
            out = [("Select", lambda: self.app.set_tool("select"))]
        out += [("Normal To", self.normal_to), ("Exit Sketch", self.app.leave_sketch)]
        return out

    def delete_selected(self):
        if not self.active or not self.sel or self.m is None:
            return
        items = list(self.sel)
        self.commit(lambda m: m.delete(items))
        self.sel = []

    # ------------------------------------------------------------------ edit commands that act on the selection
    def entities_selected(self):
        return [k for k in self.sel if k[0] in ("ln", "ci", "ar")]

    def command_mirror(self):
        if not self.entities_selected():
            self.app.say("Select the lines, arcs or circles to mirror first, then press Mirror.")
            return False
        self.reset_tool("mirror")
        self.axis_wait = True
        self.app.say("Now click the line to mirror about.")
        return True

    def command_linear(self):
        ents = self.entities_selected()
        if not ents:
            self.app.say("Select what to copy first.")
            return
        r = ask_form(self.app, "Linear sketch pattern", [("Number of extra copies", 2), ("Step X (mm)", 10.0), ("Step Y (mm)", 0.0)])
        if r:
            n, dx, dy = r[0]
            self.commit(lambda m: sk.linear_pattern(m, ents, int(n), dx, dy))

    def command_circular(self):
        ents = self.entities_selected()
        if not ents:
            self.app.say("Select what to copy first.")
            return
        r = ask_form(self.app, "Circular sketch pattern", [("Number of extra copies", 3), ("Angle between copies (deg)", 90.0),
                                                            ("Centre X (mm)", 0.0), ("Centre Y (mm)", 0.0)])
        if r:
            n, a, cx, cy = r[0]
            self.commit(lambda m: sk.circular_pattern(m, ents, int(n), a, cx, cy))

    def command_move(self):
        ents = self.sel
        if not ents:
            self.app.say("Select what to move first.")
            return
        r = ask_form(self.app, "Move entities", [("Move X (mm)", 0.0), ("Move Y (mm)", 0.0)])
        if r:
            dx, dy = r[0]
            self.commit(lambda m: sk.move(m, [k for k in ents if k[0] != "con"], dx, dy))

    def command_offset(self):
        m = self.m
        sel = self.entities_selected()
        if not sel:
            self.app.say("Select the lines, arcs and circles to offset first, then press Offset.")
            return
        r = ask_form(self.app, "Offset entities", [("Distance (mm; + = outward / left)", round(0.05 * max(m.extent(), 1.0), 3) or 1.0)],
                     [("Both sides", False), ("Keep linked to the originals (an offset dimension)", True), ("Select the whole closed loop", True)])
        if not r:
            return
        dist = r[0][0]
        both, link, chain = r[1]
        if abs(dist) < 1e-12:
            return

        def build(mm):
            edges = [k for k in sel if k[0] in ("ln", "ar")]
            circles = [i for k, i in sel if k == "ci"]
            if chain and edges:
                edges = edges + skoff.loop_rest(mm, edges)
            chains = skoff.find_chains(mm, edges)
            tol = 1e-7 * max(1.0, mm.extent())
            plans = [skoff.plan_offset(mm, chains, circles, dist, tol)]
            if both:
                plans.append(skoff.plan_offset(mm, chains, circles, -dist, tol))
            if not any(pl["edges"] or pl["circles"] for pl in plans):
                return "Nothing was added: every piece collapses at that distance."
            used = set(self.app.doc.params) | set(mm.params)
            name = mm.next_dim_name("dim_off", used)
            skoff.apply_plan(mm, plans, link, name if link else None)
        self.commit(build)

    def command_convert(self):
        """Convert Entities: copy picked edges (or the outline of a picked face) of the part into the sketch, projected onto its plane.
        With nothing picked: every edge of the part that lies in the sketch plane.  The copies are fixed where they are."""
        solid = self.app.shown_solid()
        pl = self.plane()
        if solid is None or pl is None:
            self.app.say("There is no part to convert edges from.")
            return
        o, xd, yd, zd = pl
        edges = []
        for ref in self.app.sel_edges:
            try:
                edges.append(self.app.doc.resolve_edge(ref, solid))
            except Exception:
                pass
        if not edges and self.app.sel_face is not None:
            try:
                edges = list(solid.faces()[self.app.sel_face["index"]].edges())
            except Exception:
                edges = []
        if not edges:
            for e in solid.edges():
                pts = np.array([tuple(e.position_at(t)) for t in np.linspace(0, 1, 9)])
                if np.max(np.abs((pts - o) @ zd)) <= 1e-6:
                    edges.append(e)
        if not edges:
            self.app.say("Pick edges or a face of the part first (click them in the view), then press Convert Entities.")
            return
        items = []
        for e in edges:
            pts = np.array([tuple(e.position_at(t)) for t in np.linspace(0, 1, 25)])
            uv = np.column_stack([(pts - o) @ xd, (pts - o) @ yd])
            items.append((str(e.geom_type).split(".")[-1].upper(), uv))
        approx = []

        def build(m):
            made = 0

            def spec(p):
                for i, q in m.pts.items():
                    if abs(q[0] - p[0]) < 1e-6 and abs(q[1] - p[1]) < 1e-6:
                        return ("pt", i)
                return (float(p[0]), float(p[1]))

            def have_line(a, b):
                if not (sk.is_ref(a) and sk.is_ref(b)):
                    return False
                return any({x, y} == {a[1], b[1]} for x, y in m.lns.values())

            def fix(ref):
                if ref[1] != 0 and not any(c["type"] == "fixed" and c["refs"] == [("pt", ref[1])] for c in m.cons):
                    sk.con(m, "fixed", [("pt", ref[1])], xy=tuple(m.pts[ref[1]]))
            for gt, uv in items:
                if np.linalg.norm(uv[0] - uv[-1]) < 1e-9 and gt != "CIRCLE" and np.ptp(uv, axis=0).max() < 1e-9:
                    continue                                         # an edge seen end-on
                if gt == "LINE":
                    if np.linalg.norm(uv[0] - uv[-1]) < 1e-9:
                        continue
                    if not have_line(spec(uv[0]), spec(uv[-1])):
                        lid = sk.add_line(m, spec(uv[0]), spec(uv[-1]), auto=False)
                        for p in m.lns[lid]:
                            fix(("pt", p))
                    made += 1
                    continue
                cc = sk.circumcircle(tuple(uv[3]), tuple(uv[10]), tuple(uv[19])) if gt == "CIRCLE" else None
                if cc is not None and np.max(np.abs(np.hypot(uv[:, 0] - cc[0][0], uv[:, 1] - cc[0][1]) - cc[1])) < 1e-5 * max(1.0, cc[1]):
                    if np.linalg.norm(uv[0] - uv[-1]) < 1e-6:
                        cid = sk.add_circle(m, spec(cc[0]), (cc[0][0] + cc[1], cc[0][1]))
                        fix(("pt", m.cis[cid]["c"]))
                    else:
                        aid = sk.add_arc_3pt(m, spec(uv[0]), spec(uv[-1]), tuple(uv[12]))
                        if aid is not None:
                            ar = m.ars[aid]
                            for p in (ar["c"], ar["s"], ar["e"]):
                                fix(("pt", p))
                    made += 1
                    continue
                approx.append(gt)                                    # a curve that does not stay a circle / line in this plane
                for a_, b_ in zip(uv[:-1], uv[1:]):
                    if np.linalg.norm(a_ - b_) > 1e-9 and not have_line(spec(a_), spec(b_)):
                        lid = sk.add_line(m, spec(a_), spec(b_), auto=False)
                        for p in m.lns[lid]:
                            fix(("pt", p))
                made += 1
            if not made:
                return "Nothing could be converted."
            self.app.say(f"Converted {made} edge(s)." + (" (A curved edge seen at an angle became short line segments.)" if approx else ""))
        r = self.commit(build)
        if r is None:
            self.app.sel_edges, self.app.sel_face = [], None
            self.app.draw()

    # ------------------------------------------------------------------ drawing (a second VTK layer on top of the part)
    def layer(self):
        if self.ren is None:
            self.ren = vtkRenderer()
            self.ren.SetLayer(1)
            self.ren.InteractiveOff()
            rw = self.pl.render_window
            rw.SetNumberOfLayers(3)
            rw.AddRenderer(self.ren)
        self.ren.SetActiveCamera(self.pl.camera)
        return self.ren

    def clear_actors(self):
        if self.ren is not None:
            for a in self.actors:
                self.ren.RemoveActor(a)
        self.actors = []

    def actor(self, mesh, color, width=2.0, points=False):
        m = vtkPolyDataMapper()
        m.SetInputData(mesh)
        a = vtkActor()
        a.SetMapper(m)
        pr = a.GetProperty()
        pr.SetColor(*color)
        pr.SetLighting(False)
        if points:
            pr.SetPointSize(width)
            pr.SetRenderPointsAsSpheres(True)
        else:
            pr.SetLineWidth(width)
        self.layer().AddActor(a)
        self.actors.append(a)

    def polyline(self, uv, color, width=2.0):
        if len(uv) >= 2:
            self.actor(pv.lines_from_points(self.to_world(uv)), color, width)

    def text(self, uv, s, color=COL_TAG, size=14):
        if vtkBillboardTextActor3D is None:
            return
        a = vtkBillboardTextActor3D()
        a.SetInput(s)
        a.SetPosition(*self.to_world(np.array([uv]))[0])
        tp = a.GetTextProperty()
        tp.SetFontSize(size)
        tp.SetColor(*color)
        tp.SetBold(True)
        a.SetDisplayOffset(6, 6)
        self.layer().AddActor(a)
        self.actors.append(a)

    def entity_color(self, key):
        m, rep = self.m, self.rep
        if key in self.sel:
            return COL_SEL, 4.0
        if key in m.constr:
            return COL_CONSTR, 1.5
        if rep is None:
            return COL_FREE, 3.0
        if rep.conflicts:
            return COL_BAD, 3.0
        k, i = key
        if k == "ci":
            free = i in rep.free_circles or m.cis[i]["c"] in rep.free_pts
        elif k == "ln":
            free = any(p in rep.free_pts for p in m.lns[i])
        else:
            a = m.ars[i]
            free = any(p in rep.free_pts for p in (a["c"], a["s"], a["e"]))
        return (COL_FREE if free else COL_FIXED), 3.0

    def tag_anchor(self, c):
        """Where the label of a dimension is drawn (plane coordinates), or None."""
        m, t, refs = self.m, c["type"], c["refs"]
        try:
            if t in ("dim_h", "dim_v", "dim_len"):
                a, b = m._two_points(refs)
                return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if t in ("dim_rad", "dim_dia"):
                k, i = refs[0]
                if k == "ci":
                    cc, r = m.pts[m.cis[i]["c"]], m.cis[i]["r"]
                else:
                    cc, r = m.pts[m.ars[i]["c"]], sk.arc_span(m, i)[1]
                return (cc[0] + 0.7 * r, cc[1] + 0.7 * r)
            if t == "dim_ang":
                pts = [p for k, i in refs for p in m.line_pts(i)]
                return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        except Exception:
            return None
        return None

    def redraw(self):
        if not self.active or pv is None:
            return
        self.clear_actors()
        m = self.m
        if m is None or self.plane() is None:
            return
        L = 0.04 * self.view_height()
        self.polyline(np.array([(0, 0), (L, 0)]), AX_U, 2.5)
        self.polyline(np.array([(0, 0), (0, L)]), AX_V, 2.5)
        for key in self.keys():
            try:
                col, w = self.entity_color(key)
                self.polyline(sk.polyline(m, key, 48), col, w)
            except Exception:
                continue
        free, fixed, sel = [], [], []
        rep = self.rep
        for i, p in m.pts.items():
            if i == 0:
                self.actor(pv.PolyData(self.to_world(np.array([p]))), COL_SEL if ("pt", 0) in self.sel else COL_ORIGIN, 11.0, points=True)
                continue
            if ("pt", i) in self.sel:
                sel.append(p)
            elif rep is not None and not rep.conflicts and i not in rep.free_pts:
                fixed.append(p)
            else:
                free.append(p)
        for pts, col, size in ((free, COL_FREE, 7.0), (fixed, COL_FIXED, 7.0), (sel, COL_SEL, 10.0)):
            if pts:
                self.actor(pv.PolyData(self.to_world(np.array(pts))), col, size, points=True)
        self.tags = []
        for c in m.cons:
            if c["type"] in DIMS and c.get("grp") is None and self.app.vis["dims"]:
                a = self.tag_anchor(c)
                if a is not None:
                    self.tags.append((a[0], a[1], c["id"]))
                    sel_c = ("con", c["id"]) in self.sel
                    self.text(a, f"{c.get('name', '')} = {c['value']:.4g}", COL_SEL if sel_c else COL_TAG)
        self.draw_preview()
        self.pl.render()

    def draw_preview(self):
        c, t = self.cursor, self.tool
        if c is not None and t != "select":
            self.actor(pv.PolyData(self.to_world(np.array([c]))), (1.0, 0.55, 0.0) if self.snapped else (0.4, 0.4, 0.4),
                       11.0 if self.snapped else 7.0, points=True)
        if not self.pending or c is None:
            return
        m = self.m
        try:
            if t in CHAIN:
                self.polyline(np.array([self.coords(self.pending[-1]), c]), COL_PREVIEW, 2.0)
                return
            if t == "arc_tangent":
                sm = copy.deepcopy(m)
                sk.add_arc_tangent(sm, self.pending[0][1], self.host, c)
                base = len(m.pts)
            elif t in DRAW and len(self.pending) < DRAW[t][0]:
                sm = sk.new_model()
                specs = [self.coords(s) for s in self.pending]
                n, fn, _ = DRAW[t]
                specs += [c] * (n - len(specs))
                fn(sm, specs, self)
                base = 0
            else:
                return
            for key in sk.all_keys(sm):
                if t == "arc_tangent" and (key in sk.all_keys(m)):
                    continue
                self.polyline(sk.polyline(sm, key, 48), COL_PREVIEW, 2.0)
            del base
        except Exception:
            pass

    def view_height(self):
        """Height of the view in mm (orthographic) - to size the little axes."""
        try:
            return 2.0 * self.pl.camera.GetParallelScale()
        except Exception:
            return 100.0


class SketchHook(QObject):
    """Qt mouse events on the 3D view while a sketch is open: a plain left click / drag belongs to the sketch tools; Alt+left (orbit),
    middle (pan), right (zoom) and the wheel go on to the 3D view as usual."""

    def __init__(self, plotter, ed):
        super().__init__(plotter)
        self.plotter, self.ed = plotter, ed
        self.down = False
        try:
            from PyQt6.QtWidgets import QWidget as _W
            for w in [plotter] + list(plotter.findChildren(_W)):
                w.installEventFilter(self)
        except Exception:
            pass

    def xy(self, obj, ev):
        r = obj.devicePixelRatioF()
        p = ev.position()
        return p.x() * r, (obj.height() - p.y() - 1) * r

    def eventFilter(self, obj, ev):
        ed = self.ed
        if not ed.active:
            return False
        try:
            t = ev.type()
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                self.ed.app.shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self.down = ed.press(*self.xy(obj, ev))
                return self.down
            if t == QEvent.Type.MouseButtonDblClick and ev.button() == Qt.MouseButton.LeftButton:
                ed.double_click(*self.xy(obj, ev))
                return True
            if t == QEvent.Type.MouseMove:
                ed.move(*self.xy(obj, ev))
                return False
            if t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton and self.down:
                self.down = False
                ed.release(*self.xy(obj, ev))
                return True
        except Exception:
            import traceback
            self.down = False
            ed.app.say("Sketch tool failed: " + traceback.format_exc(limit=3))
        return False
