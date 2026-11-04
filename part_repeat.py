"""
part_repeat.py - Mirror and Pattern (linear / circular) in the part window: the same working style as Fillet / Chamfer and Up-To-Face.

* A "Selections" box in the panel lists what the feature needs - the features to repeat, the mirror plane (a flat face or a plane), the direction
  or axis (a straight edge) - with what each is set to and which one the next click in the view fills.  Opening the tool arms the pick that is
  still missing, so nothing has to be selected beforehand; "Stop picking" / "Pick again" / "Clear" are there on every row.
* What is picked is drawn on the part (the face / the edge), and the result shows as a faded blue (added) or red (removed) body while the panel
  is open - the shared preview of part_preview.py (pattern and mirror are in its KINDS).
The methods are attached to pm_app.MainWindow by install().
"""
import numpy as np
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QWidget
from PyQt6.QtCore import Qt

import pm_model as pm
import viewpick

PICK_COL = (1.0, 0.45, 0.0)


# ------------------------------------------------------------------------------------------------ state
def rp_pick_active(self):
    """True while a click in the view should go to the Mirror / Pattern selection row that is armed."""
    f = self.doc.feature(self.sel) if self.sel else None
    st = getattr(self, "rp_pick", None)
    return bool(f is not None and st is not None and st[0] == f["id"] and f["kind"] in ("pattern", "mirror") and self.left.currentIndex() == 1)


def _arm(self, f, what, on=True):
    off = self.__dict__.setdefault("rp_off", set())
    if on:
        self.rp_pick = (f["id"], what)
        off.discard((f["id"], what))
    else:
        if getattr(self, "rp_pick", None) == (f["id"], what):
            self.rp_pick = None
        off.add((f["id"], what))


def _auto_arm(self, f):
    """Choosing 'a flat face' / 'a selected edge' waits for the click at once (once: Stop picking switches it off)."""
    off = self.__dict__.setdefault("rp_off", set())
    st = getattr(self, "rp_pick", None)
    if st is not None and st[0] != f["id"]:
        self.rp_pick = st = None
    if f["kind"] == "pattern" and "edge" in (f.get("dir1"), f.get("axis")) and not f.get("edge1") and (f["id"], "edge1") not in off and st is None:
        self.rp_pick = (f["id"], "edge1")


# ------------------------------------------------------------------------------------------------ the panel
def _row(self, form, title, status, ok, armed, what, f, clear=None, pick_text="Pick"):
    """One row of the selections box: its name and state in a line, then its buttons."""
    lab = QLabel(f"<b>{title}</b>: {status}")
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setStyleSheet("color:#b4561f;" if armed else "color:#14602a;" if ok else "color:#8a1f1f;")
    lab.setWordWrap(True)
    form.addRow(lab)
    if what is None:
        return
    row = QHBoxLayout()
    b = QPushButton("Stop picking" if armed else (f"{pick_text} again" if ok else pick_text))

    def tog():
        _arm(self, f, what, not armed)
        self.say(("Click the " + ("flat face to mirror about." if what == "plane" else "straight edge for the direction / axis.")) if not armed else "")
        self.show_props()
        self.draw()
    b.clicked.connect(tog)
    row.addWidget(b)
    if clear is not None and ok:
        c = QPushButton("Clear")

        def clr():
            self.snapshot()
            clear()
            _arm(self, f, what, True)
            self.update_all()
        c.clicked.connect(clr)
        row.addWidget(c)
    w = QWidget()
    w.setLayout(row)
    form.addRow(w)


def repeat_panel(self, form, f):
    """Properties of Linear / Circular Pattern and Mirror, with the selections list."""
    d = self.doc
    k = f["kind"]
    _auto_arm(self, f)
    st = getattr(self, "rp_pick", None)
    hint = QLabel(("Mirror" if k == "mirror" else "Pattern") + " - pick what is needed below (any order). The faded body in the view shows the "
                  "result; press OK to keep it.")
    hint.setWordWrap(True)
    hint.setStyleSheet("color:#1f4fb4; padding:2px 0;")
    form.addRow(hint)
    self.combo(form, "Repeat", f, "source", [("features", "Chosen features"), ("body", "The whole body")], "features")
    # ---- selections: what to repeat
    if f.get("source", "features") == "features":
        chosen = [g for g in d.features if g["id"] in f.get("features", [])]
        form.addRow(QLabel(f"<b>Features to repeat</b>: " + (", ".join(g["name"] for g in chosen) if chosen else "none yet - tick them below")))
        lw = QListWidget()
        lw.setMaximumHeight(120)
        for g in d.features:
            if g["kind"] not in pm.SOLID_FEATURES:
                continue
            if d.features.index(g) >= d.features.index(f):
                break
            it = QListWidgetItem(g["name"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if g["id"] in f.get("features", []) else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, g["id"])
            lw.addItem(it)

        def changed(it):
            gid = it.data(Qt.ItemDataRole.UserRole)
            self.snapshot()
            cur = [x for x in f.get("features", []) if x != gid]
            f["features"] = cur + [gid] if it.checkState() == Qt.CheckState.Checked else cur
            self.update_all()
        lw.itemChanged.connect(changed)
        form.addRow(lw)
    else:
        form.addRow(QLabel("<b>Repeats</b>: the whole body"))
    # ---- selections: mirror plane / direction / axis
    if k == "mirror":
        pl = f.get("plane") or {"base": "Right"}
        opts = [("Front", "Front plane"), ("Top", "Top plane"), ("Right", "Right plane"), ("face", "A flat face (click it in the view)")]
        opts += [("ref:" + g["id"], g["name"]) for g in d.features if g["kind"] == "refplane" and d.features.index(g) < d.features.index(f)]
        cb = QComboBox()
        for v, t in opts:
            cb.addItem(t, v)
        cur = pl["base"] if "base" in pl else ("ref:" + pl["ref"] if "ref" in pl else "face")
        cb.setCurrentIndex(max(0, [o[0] for o in opts].index(cur) if cur in [o[0] for o in opts] else 0))

        def chp(_i):
            v = cb.currentData()
            self.snapshot()
            if v == "face":
                _arm(self, f, "plane", True)
                self.say("Click the flat face to mirror about.")
                self.show_props()
                self.draw()
                return
            self.rp_pick = None if getattr(self, "rp_pick", None) == (f["id"], "plane") else getattr(self, "rp_pick", None)
            f["plane"] = {"ref": v[4:]} if v.startswith("ref:") else {"base": v}
            self.update_all()
        cb.currentIndexChanged.connect(chp)
        armed = st == (f["id"], "plane")
        if "face" in pl:
            _row(self, form, "Mirror plane", "a flat face of the part", True, armed, "plane", f, clear=lambda: f.update(plane={"base": "Right"}), pick_text="Pick face")
        else:
            nm = {"base": lambda: pl["base"] + " plane", "ref": lambda: next((g["name"] for g in d.features if g["id"] == pl.get("ref")), "a plane")}
            what = nm["base" if "base" in pl else "ref"]()
            _row(self, form, "Mirror plane", (what if not armed else f"{what} for now - click a flat face of the part to use it instead"),
                 True, armed, "plane", f, pick_text="Pick a face")
        form.addRow("Mirror about", cb)
        return
    axes = [("X", "X"), ("Y", "Y"), ("Z", "Z"), ("edge", "A straight edge (click it in the view)")]
    for kk, vv in (("count2", "2"), ("spacing2", "10"), ("dir2", "Y"), ("angle", "360")):
        f.setdefault(kk, vv)
    key = "dir1" if f.get("ptype") == "linear" else "axis"
    box = self.combo(form, "Direction" if f.get("ptype") == "linear" else "Axis", f, key, axes, "X" if f.get("ptype") == "linear" else "Z")
    if f.get(key) == "edge":
        armed = st == (f["id"], "edge1")
        have = bool(f.get("edge1"))
        _row(self, form, "Direction" if f.get("ptype") == "linear" else "Axis", "a straight edge of the part" if have else
             "none yet - click an edge in the view" if armed else "none yet", have, armed, "edge1", f,
             clear=lambda: f.update(edge1=None), pick_text="Pick edge")
    if f.get("ptype") == "linear":
        self.expr_edit(form, "Copies", f, "count")
        self.expr_edit(form, "Spacing (mm)", f, "spacing")
        self.check(form, "Reverse direction", f, "reverse")
        self.check(form, "Second direction", f, "dir2_on")
        if f.get("dir2_on"):
            self.combo(form, "  Direction 2", f, "dir2", axes[:3], "Y")
            self.expr_edit(form, "  Copies 2", f, "count2")
            self.expr_edit(form, "  Spacing 2 (mm)", f, "spacing2")
    else:
        self.expr_edit(form, "Copies", f, "count")
        self.expr_edit(form, "Angle (deg)", f, "angle")
        self.check(form, "Reverse direction", f, "reverse")
    msg = self.doc.status.get(f["id"], "")
    if str(msg).startswith("error"):
        err = QLabel(str(msg)[7:] if str(msg).startswith("error: ") else str(msg))
        err.setWordWrap(True)
        err.setStyleSheet("color:#b4561f;" if getattr(self, "rp_pick", None) else "color:#c00000;")
        form.addRow(err)


# ------------------------------------------------------------------------------------------------ picking in the view
def rp_pick_click(self, x, y):
    """A click while a Mirror / Pattern selection row is armed."""
    f = self.doc.feature(self.sel) if self.sel else None
    st = getattr(self, "rp_pick", None)
    if f is None or st is None:
        return
    what = st[1]
    solid = self.shown_solid()
    if what == "plane":
        r = viewpick.pick_surface(self.plotter, x, y)
        if r is None or solid is None or self.actor_part is None or not viewpick.same_actor(self.actor_part, r[1]):
            self.say("Click a flat face of the part.")
            return
        face = solid.faces()[int(self.view_cells.cell_data["face"][r[2]])]
        if face.geom_type.name != "PLANE":
            self.say("That face is curved - pick a flat face.")
            return
        self.snapshot()
        f["plane"] = {"face": self.doc.face_ref(face)}
        self.say("Face picked - the faded body shows the mirrored result.")
    else:
        ei = self.pick_edge(x, y)
        s2 = self.pick_solid()
        if ei is None or s2 is None:
            self.say("Click a straight edge of the part.")
            return
        e = s2.edges()[ei]
        okk = ("LINE",) if f.get("ptype") == "linear" else ("LINE", "CIRCLE")
        if e.geom_type.name not in okk:
            self.say("Pick a straight edge." if f.get("ptype") == "linear" else "Pick a straight edge or a circle.")
            return
        self.snapshot()
        f["edge1"] = self.doc.edge_ref(e)
        self.say("Edge picked - the faded body shows the pattern.")
    self.rp_pick = None
    self.__dict__.setdefault("rp_off", set()).add((f["id"], what))
    self.update_all()


def draw_repeat_selection(self, pl):
    """What the Mirror / Pattern has picked, drawn on the part while its panel is open: the mirror face and the direction / axis edge."""
    f = self.doc.feature(self.sel) if self.sel else None
    if f is None or f["kind"] not in ("mirror", "pattern") or self.left.currentIndex() != 1:
        return
    solid = self.shown_solid()
    if solid is None:
        return
    import pyvista as pv
    from part_refgeo import add_face_highlight
    try:
        if f["kind"] == "mirror" and "face" in (f.get("plane") or {}) and self.view_cells is not None:
            face = self.doc.resolve_face(f["plane"]["face"], solid)
            c0 = face.center()
            c0 = np.array([c0.X, c0.Y, c0.Z])
            faces = solid.faces()
            best = min(range(len(faces)), key=lambda i: float(np.linalg.norm(np.array(tuple(faces[i].center())) - c0)) if faces[i].geom_type.name == "PLANE" else 1e18)
            cs = np.where(np.array(self.view_cells.cell_data["face"]) == best)[0]
            if len(cs):
                add_face_highlight(pl, self.view_cells.extract_cells(cs), PICK_COL)
    except Exception:
        pass
    try:
        if f["kind"] == "pattern" and f.get("edge1") and "edge" in (f.get("dir1"), f.get("axis")):
            e = self.doc.resolve_edge(f["edge1"], solid)
            pts = np.array([tuple(e.position_at(t)) for t in np.linspace(0.0, 1.0, 40)])
            pd = pv.PolyData()
            pd.points = pts
            pd.lines = np.hstack([[len(pts)], np.arange(len(pts))]).astype(np.int64)
            a = pl.add_mesh(pd, color=PICK_COL, line_width=4, pickable=False, reset_camera=False)
            try:
                a.GetMapper().SetResolveCoincidentTopologyToPolygonOffset()
                a.GetMapper().SetRelativeCoincidentTopologyLineOffsetParameters(-3.0, -3.0)
            except Exception:
                pass
    except Exception:
        pass


def install(cls):
    for fn in (rp_pick_active, rp_pick_click, draw_repeat_selection, repeat_panel):
        setattr(cls, fn.__name__, fn)
