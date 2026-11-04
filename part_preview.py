"""
part_preview.py - what a feature is about to do, shown on the part itself before it is committed.

While the panel of the LAST feature is open (Boss / Cut / Revolve / Sweep / Loft / Fillet / Chamfer) the view shows the part as it was before that
feature, with the change drawn over it faded: material that will be removed in red, material that will be added in blue.  OK commits (the part
becomes solid); Cancel throws the preview away.  Also here: picking the axis of a revolve in the view and the edge list of a fillet / chamfer.
The methods are attached to pm_app.MainWindow by install().
"""
import json

import numpy as np
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QWidget

import viewpick

CUT_COL = (0.90, 0.20, 0.20)
ADD_COL = (0.20, 0.45, 0.95)
FADE = 0.42
KINDS = ("extrude", "cut", "revolve", "revolve_cut", "sweep", "sweep_cut", "loft", "loft_cut", "fillet", "chamfer", "pattern", "mirror")
DIFF_KINDS = ("fillet", "chamfer", "pattern", "mirror")        # shown as (before - after) in red and (after - before) in blue
# Features that change no shape, or whose own dialog is the preview, and so draw nothing over the part.  EVERY feature kind is in KINDS or here
# (tests/test_preview.py checks it): a new kind must get a preview or be listed here with the reason.
NO_PREVIEW = {"sketch": "a sketch is drawn in its own editor", "refplane": "reference geometry is drawn in the view", "refaxis": "reference geometry is drawn in the view",
              "refpoint": "reference geometry is drawn in the view", "partgen": "the Part Generator window previews the part", "imported": "the whole imported body is the result"}
REVOLVES = ("revolve", "revolve_cut")
AXIS_COL = (0.85, 0.10, 0.55)


# ------------------------------------------------------------------------------------------- what is previewed
def preview_feature(self):
    """The feature whose change is being previewed, or None: the last feature of the part, with its panel open, outside the sketch editor."""
    d = self.doc
    if not d.features or d.rollback is not None:
        return None
    if self.ed is not None and self.ed.active:
        return None
    if self.left.currentIndex() != 1 or not self.sel:
        return None
    f = d.feature(self.sel)
    if f is None or f["kind"] not in KINDS or f is not d.features[-1] or f.get("suppressed"):
        return None
    return f


def before_solid(self, f):
    d = self.doc
    i = d.features.index(f)
    return d.after.get(d.features[i - 1]["id"]) if i > 0 else None


def _diff(a, b, op):
    try:
        r = (a - b) if op == "-" else (a & b)
        return r if r is not None and r.solids() and r.volume > 1e-9 else None
    except Exception:
        return None


def preview_info(self):
    """{"f": feature, "before": solid, "parts": [(shape, colour)], "cut": bool} - cached until the feature or the rebuilt part changes."""
    f = self.preview_feature()
    if f is None:
        return None
    d = self.doc
    after = d.after.get(f["id"])
    key = (f["id"], json.dumps(f, sort_keys=True, default=str), id(after), id(d.solid))
    c = getattr(self, "_pv_cache", None)
    if c is not None and c[0] == key:
        return c[1]
    before = self.before_solid(f)
    parts = []
    try:
        if f["kind"] in DIFF_KINDS:
            if before is not None and d.status.get(f["id"]) == "ok" and after is not None:
                red, blue = _diff(before, after, "-"), _diff(after, before, "-")
                parts = [(s, c_) for s, c_ in ((red, CUT_COL), (blue, ADD_COL)) if s is not None]
        else:
            tool, mode = d.feature_tool(f, before)
            if mode == "cut":
                red = _diff(tool, before, "&") if before is not None else tool
                parts = [(red if red is not None else tool, CUT_COL)]
            else:
                blue = _diff(tool, before, "-") if before is not None else tool
                parts = [(blue if blue is not None else tool, ADD_COL)]
    except Exception:
        parts = []
    info = {"f": f, "before": before, "parts": parts, "cut": any(c_ == CUT_COL for _s, c_ in parts)}
    self._pv_cache = (key, info, after)
    return info


def part_opacity(self):
    """Opacity of the part while a removal is previewed: lowered so that the red body inside it can be seen."""
    op = float(self.doc.display.get("opacity", 1.0))
    info = self.preview_info()
    return min(op, 0.62) if info is not None and info["cut"] else op


def draw_preview(self, pl, pv):
    """Add the faded bodies (and, for a revolve, its axis) to the view."""
    info = self.preview_info()
    f = self.doc.feature(self.sel) if self.sel else None
    if info is not None:
        for shape, col in info["parts"]:
            try:
                verts, cells, off = [], [], 0
                for _i, v, t in self.doc.mesh(shape):
                    verts.append(v)
                    cells.append(np.hstack([np.full((len(t), 1), 3), t + off]).ravel())
                    off += len(v)
                if not verts:
                    continue
                m = pv.PolyData(np.vstack(verts), np.concatenate(cells))
                a = pl.add_mesh(m, color=col, opacity=FADE, smooth_shading=False, pickable=False, reset_camera=False,
                                ambient=0.35, diffuse=0.7, specular=0.1)
                try:
                    mp = a.GetMapper()
                    mp.SetResolveCoincidentTopologyToPolygonOffset()
                    mp.SetRelativeCoincidentTopologyPolygonOffsetParameters(-2.0, -2.0)
                except Exception:
                    pass
                ml = self.merged_lines(self.doc.edge_lines(shape))
                if ml is not None:
                    pl.add_mesh(ml, color=tuple(0.6 * c for c in col), line_width=1.5, opacity=0.8, pickable=False, reset_camera=False)
            except Exception:
                pass
    self.highlight_to_face(pl)
    self.draw_repeat_selection(pl)
    if f is not None and f["kind"] in REVOLVES and self.left.currentIndex() == 1:
        try:
            seg = self.revolve_axis_segment(f)
            if seg is not None:
                pl.add_mesh(self.merged_lines([np.array(seg)]), color=AXIS_COL, line_width=4, pickable=False, reset_camera=False)
        except Exception:
            pass


# ------------------------------------------------------------------------------------------- revolve axis
def revolve_axis_segment(self, f, ext=None):
    """The axis of a revolve as two 3D points (long enough to see), or None."""
    d = self.doc
    sk_ = d.feature(f.get("sketch"))
    if sk_ is None or sk_["id"] not in d.planes:
        return None
    ax = d.revolve_axis(f, self.before_solid(f), sk_)
    p, v = np.array(tuple(ax.position)), np.array(tuple(ax.direction))
    sol = self.doc.solid or self.before_solid(f)
    if ext:
        L = ext
    elif sol is not None:
        bb = sol.bounding_box()
        L = 0.9 * float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z])) + 10.0
    else:
        L = 60.0
    return [p - v * L, p + v * L]


def sketch_line_label(self, sk_, lid):
    m = self.doc.models.get(sk_["id"])
    a, b = m.line_pts(lid)
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) < 1e-6:
        kind = f"vertical, x = {a[0]:.4g}"
    elif abs(dy) < 1e-6:
        kind = f"horizontal, y = {a[1]:.4g}"
    else:
        kind = "sloped"
    return f"Line {lid}  ({kind})" + ("  [centerline]" if ("ln", lid) in m.constr else "")


def rv_axis_pick(self, x, y):
    """A click while 'pick axis' is on: the nearest sketch line, reference axis or straight edge becomes the axis of the revolve."""
    f = self.doc.feature(self.sel) if self.sel else None
    if f is None or f["kind"] not in REVOLVES:
        self.axis_pick = False
        return False
    d, ed = self.doc, self.ed
    sk_ = d.feature(f["sketch"])
    tol = 10.0 * self.plotter.devicePixelRatioF()
    best = None                                              # (screen distance, axis spec, text)
    m = d.models.get(sk_["id"]) if sk_ is not None else None
    plane = d.planes.get(sk_["id"]) if sk_ is not None else None
    if m is not None and plane is not None:
        o = np.array(tuple(plane.origin)); xd, yd = np.array(tuple(plane.x_dir)), np.array(tuple(plane.y_dir))
        for lid in m.lns:
            a, b = m.line_pts(lid)
            P = np.array([o + a[0] * xd + a[1] * yd, o + b[0] * xd + b[1] * yd])
            try:
                dist, _j, _t = ed.seg_dist(ed.to_screen(P), x, y)
            except Exception:
                continue
            if dist <= tol and (best is None or dist < best[0]):
                best = (dist, {"ln": lid}, f"sketch line {lid}")
    for rid, act in getattr(self, "actor_refs", {}).items():
        g = d.feature(rid)
        if g is None or g["kind"] != "refaxis" or rid not in d.refgeo:
            continue
        e = d.refgeo[rid]
        P = np.array([np.array(e["p"]) - np.array(e["d"]) * 50.0, np.array(e["p"]) + np.array(e["d"]) * 50.0])
        try:
            dist, _j, _t = ed.seg_dist(ed.to_screen(P), x, y)
        except Exception:
            continue
        if dist <= tol and (best is None or dist < best[0]):
            best = (dist, {"ref": rid}, g["name"])
    if best is None:
        ei = self.pick_edge(x, y)
        ps = self.pick_solid()
        if ei is not None and ps is not None:
            e = ps.edges()[ei]
            if e.geom_type.name == "LINE":
                best = (0.0, {"edge": d.edge_ref(e)}, "a straight edge of the part")
    if best is None:
        self.say("No line there: click a line of the sketch, a reference axis or a straight edge of the part.")
        return True
    self.snapshot()
    f["axis"] = best[1]
    self.axis_pick = False
    self.update_all()
    self.say(f"Axis set to {best[2]}.")
    return True


def axis_panel_rows(self, form, f):
    """The Axis row of the revolve panel: a list of choices (with plain names) and a button to pick the axis in the view."""
    from PyQt6.QtWidgets import QComboBox
    d = self.doc
    sk_ = d.feature(f["sketch"])
    m = d.models.get(sk_["id"]) if sk_ is not None else None
    opts = [("auto", "Centerline (or vertical axis)"), ("sy", "Sketch vertical axis (through the origin)"),
            ("sx", "Sketch horizontal axis (through the origin)")]
    if m is not None:
        for lid in m.lns:
            opts.append((f"ln{lid}", sketch_line_label(self, sk_, lid)))
    cur = f.get("axis", "auto")
    if isinstance(cur, dict):
        if "ln" in cur:
            cur = f"ln{cur['ln']}"
        else:
            nm = (d.feature(cur["ref"]) or {"name": "(deleted axis)"})["name"] if "ref" in cur else "a straight edge of the part"
            opts.append(("ext", nm))
            cur = "ext"
    cb = QComboBox()
    for v, t in opts:
        cb.addItem(t, v)
    vals = [v for v, _ in opts]
    cb.setCurrentIndex(vals.index(cur) if cur in vals else 0)

    def ch(_i):
        v = cb.currentData()
        if v == "ext":
            return
        self.snapshot()
        f["axis"] = {"ln": int(v[2:])} if v.startswith("ln") else v
        self.update_all()
    cb.currentIndexChanged.connect(ch)
    form.addRow("Axis", cb)
    b = QPushButton("Pick axis in the view" if not getattr(self, "axis_pick", False) else "Click a line in the view...  (click here to stop)")
    b.setToolTip("Click a line of the sketch, a reference axis or a straight edge of the part. The axis is drawn in pink.")

    def tog():
        self.axis_pick = not getattr(self, "axis_pick", False)
        self.show_props()
        self.say("Click the line to revolve about (a sketch line, a reference axis or a straight edge)." if self.axis_pick else "")
    b.clicked.connect(tog)
    form.addRow(b)


# ------------------------------------------------------------------------------------------- fillet / chamfer edges
def edge_list_panel(self, form, f):
    """Fillet / chamfer: the edges taken so far (click edges or a face in the view to add / remove), before or after pressing the tool."""
    d = self.doc
    hint = QLabel("Click edges in the view to add or remove them. Click a face to take all of its edges. You can also select edges first, then press "
                  "the tool.")
    hint.setWordWrap(True)
    hint.setStyleSheet("color:#1f4fb4; padding:2px 0;")
    form.addRow(hint)
    lw = QListWidget()
    lw.setMaximumHeight(110)
    for i, ref in enumerate(f["edges"]):
        lw.addItem(f"Edge {i + 1}")
    if not f["edges"]:
        lw.addItem("(no edges yet)")
    form.addRow(lw)
    row = QHBoxLayout()
    b = QPushButton("Remove selected")

    def rm():
        i = lw.currentRow()
        if 0 <= i < len(f["edges"]):
            self.snapshot()
            f["edges"] = f["edges"][:i] + f["edges"][i + 1:]
            self.update_all(keep_props=False)
    b.clicked.connect(rm)
    row.addWidget(b)
    b2 = QPushButton("Clear edges")

    def clr():
        self.snapshot()
        f["edges"] = []
        self.update_all()
    b2.clicked.connect(clr)
    row.addWidget(b2)
    w = QWidget()
    w.setLayout(row)
    form.addRow(w)


def fc_toggle_face(self, f, face):
    """Fillet / chamfer: a click on a face adds all of its edges (or removes them when they are all in already)."""
    refs = [self.doc.edge_ref(e) for e in face.edges() if e.geom_type.name in ("LINE", "CIRCLE", "ELLIPSE", "BSPLINE", "BEZIER")]
    have = [r for r in refs if any(self.same_edge(q, r) for q in f["edges"])]
    self.snapshot()
    if len(have) == len(refs):
        f["edges"] = [q for q in f["edges"] if not any(self.same_edge(q, r) for r in refs)]
    else:
        f["edges"] = f["edges"] + [r for r in refs if r not in have]
    self.update_all(keep_props=False)


# ------------------------------------------------------------------------------------------- extrude: up to face
def face_needed(self, f):
    d = self.doc
    return f["kind"] in ("extrude", "cut") and (d.end_condition(f, 1) == "face" or (f.get("dir2") and d.end_condition(f, 2) == "face"))


def face_pick_active(self):
    f = self.doc.feature(self.sel) if self.sel else None
    return bool(f is not None and self.face_pick == f["id"] and self.face_needed(f) and self.left.currentIndex() == 1)


def face_row(self, form, f):
    """Under 'Up To Face': the face row.  Choosing the end condition arms the picking (once); the next click on a flat face of the part is the face."""
    if not f.get("to_face") and f["id"] not in self.face_pick_off and self.face_pick != f["id"]:
        self.face_pick = f["id"]                                   # waiting for the click as soon as Up To Face is chosen
    on = self.face_pick == f["id"]
    text = ("Face: picked" if f.get("to_face") else "Face: none yet") + ("   -   click a flat face of the part in the view" if on else "")
    lab = QLabel(text)
    lab.setStyleSheet("color:#14602a;" if f.get("to_face") and not on else "color:#b4561f;" if on else "")
    lab.setWordWrap(True)
    form.addRow(lab)
    row = QHBoxLayout()
    b = QPushButton("Stop picking" if on else ("Pick another face" if f.get("to_face") else "Pick face"))

    def tog():
        if on:
            self.face_pick = None
            self.face_pick_off.add(f["id"])
        else:
            self.face_pick = f["id"]
            self.face_pick_off.discard(f["id"])
            self.say("Click the flat face to extrude up to.")
        self.show_props()
    b.clicked.connect(tog)
    row.addWidget(b)
    if f.get("to_face"):
        b2 = QPushButton("Clear")

        def clr():
            self.snapshot()
            f["to_face"] = None
            self.face_pick = f["id"]
            self.face_pick_off.discard(f["id"])
            self.update_all()
        b2.clicked.connect(clr)
        row.addWidget(b2)
    w = QWidget()
    w.setLayout(row)
    form.addRow(w)


def pick_to_face(self, x, y):
    """A click while the face row is armed: a flat face of the part (before the feature) becomes the 'up to' face."""
    f = self.doc.feature(self.sel) if self.sel else None
    r = viewpick.pick_surface(self.plotter, x, y)
    solid = self.shown_solid()
    if f is None or r is None or solid is None or self.actor_part is None or not viewpick.same_actor(self.actor_part, r[1]):
        self.say("Click a flat face of the part.")
        return
    face = solid.faces()[int(self.view_cells.cell_data["face"][r[2]])]
    if face.geom_type.name != "PLANE":
        self.say("That face is curved - pick a flat face.")
        return
    self.snapshot()
    f["to_face"] = self.doc.face_ref(face)
    self.face_pick = None
    self.face_pick_off.add(f["id"])
    self.update_all()
    self.say("Face picked. The faded body shows the result; press OK.")


def highlight_to_face(self, pl):
    """The chosen 'up to' face, drawn on the part while the panel is open."""
    f = self.doc.feature(self.sel) if self.sel else None
    if f is None or f["kind"] not in ("extrude", "cut") or not f.get("to_face") or self.left.currentIndex() != 1 or self.view_cells is None:
        return
    solid = self.shown_solid()
    if solid is None:
        return
    try:
        face = self.doc.resolve_face(f["to_face"], solid)
        c0 = face.center()
        c0 = np.array([c0.X, c0.Y, c0.Z])
        faces = solid.faces()
        best = min(range(len(faces)), key=lambda i: float(np.linalg.norm(np.array(tuple(faces[i].center())) - c0)) if faces[i].geom_type.name == "PLANE" else 1e18)
        cs = np.where(np.array(self.view_cells.cell_data["face"]) == best)[0]
        if len(cs):
            from part_refgeo import add_face_highlight, PICK_COL
            add_face_highlight(pl, self.view_cells.extract_cells(cs), PICK_COL)
    except Exception:
        pass


def install(cls):
    for fn in (face_needed, face_pick_active, face_row, pick_to_face, highlight_to_face, preview_feature, before_solid, preview_info, part_opacity, draw_preview, revolve_axis_segment, rv_axis_pick, axis_panel_rows,
               edge_list_panel, fc_toggle_face):
        setattr(cls, fn.__name__, fn)
