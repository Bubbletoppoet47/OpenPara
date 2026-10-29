"""
part_refgeo.py - reference planes and axes in the part window: the PropertyManager panel, picking of references (view and small tree),
and drawing.  The methods are attached to pm_app.MainWindow by install().
"""
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QFormLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QRadioButton, QWidget)

import pm_model as pm
import refgeo
import viewpick

REF_COL = (0.20, 0.68, 0.74)
AXIS_COL = (0.62, 0.30, 0.80)
PICK_COL = (1.0, 0.45, 0.0)
ORD = ["First", "Second", "Third"]


def is_ref(f):
    return f is not None and f["kind"] in ("refplane", "refaxis")


def spec_kind(spec):
    """plane | line | cyl | point for a stored reference (without resolving it)."""
    k = spec["k"]
    if k == "base":
        return "plane"
    if k in ("origin", "vertex"):
        return "point"
    if k == "edge":
        return "line"
    if k == "face":
        g = spec["r"].get("g", "PLANE")
        return "plane" if g == "PLANE" else "cyl" if g == "CYLINDER" else "point"
    return spec.get("kind", "plane")                       # "ref": the kind is stored with the pick


def fake(kind):
    return {"plane": {"t": "plane"}, "line": {"t": "line"}, "cyl": {"t": "axis", "r": 1.0}, "point": {"t": "point"}}[kind]


def describe(win, spec):
    k = spec["k"]
    if k == "base":
        return f"{spec['n']} Plane"
    if k == "origin":
        return "Origin"
    if k == "vertex":
        return "Point"
    if k == "edge":
        return "Edge"
    if k == "face":
        g = spec["r"].get("g", "PLANE")
        return {"PLANE": "Face", "CYLINDER": "Cylindrical face", "SPHERE": "Spherical face"}.get(g, "Face")
    if k == "ref":
        f = win.doc.feature(spec["id"])
        return f["name"] if f else "(deleted)"
    return k


def retype(f):
    """Auto mode: choose the type from what is picked."""
    if f.get("auto", True):
        ents = [fake(spec_kind(s)) for s in f.get("refs", [])]
        f["ptype"] = refgeo.infer_plane_type(ents) if f["kind"] == "refplane" else refgeo.infer_axis_type(ents)


# ------------------------------------------------------------------------------------------- state
def rg_feature(self):
    """The reference feature whose references are being picked now, or None."""
    f = self.doc.feature(self.rg_edit) if getattr(self, "rg_edit", None) else None
    if f is None or not is_ref(f) or self.sel != f["id"]:
        return None
    return f


def rg_start(self, key):
    d = self.doc
    refs = []
    if self.sel_face is not None and self.sel_face.get("ref") is not None:
        refs.append({"k": "face", "r": dict(self.sel_face["ref"])})
    elif self.sel_plane in pm.BASE_PLANES:
        refs.append({"k": "base", "n": self.sel_plane})
    for e in self.sel_edges[:2]:
        refs.append({"k": "edge", "r": e})
    sel = d.feature(self.sel) if self.sel else None
    if is_ref(sel) and not refs:
        refs.append({"k": "ref", "id": sel["id"], "kind": "plane" if sel["kind"] == "refplane" else "line"})
    self.snapshot()
    f = d.add(pm.new_feature(key, refs=refs[:3], ptype=None, auto=True, d="10", ang="45", flip=False))
    retype(f)
    self.sel, self.sel_face, self.sel_plane, self.sel_edges = f["id"], None, None, []
    self.rg_edit = f["id"]
    self.created_new = f["id"]
    self.update_all()
    self.left.setCurrentIndex(1)
    self.say("Pick the references: click faces, edges, points or planes in the view, or items in the small tree. Click a pick again to remove it.")


def rg_toggle(self, f, spec):
    refs = list(f.get("refs", []))
    if spec in refs:
        refs.remove(spec)
    else:
        refs.append(spec)
        refs = refs[-3:]
    self.snapshot()
    f["refs"] = refs
    retype(f)
    self.update_all()


# ------------------------------------------------------------------------------------------- picking
def pick_vertex(self, x, y):
    solid = self.pick_solid()
    if solid is None or self.ed is None or self.actor_part is None:
        return None
    vs = solid.vertices()
    if not vs:
        return None
    P = np.array([tuple(v.center()) for v in vs])
    S = self.ed.to_screen(P)
    dist = np.hypot(S[:, 0] - x, S[:, 1] - y)
    i = int(np.argmin(dist))
    if dist[i] > 9.0 * self.plotter.devicePixelRatioF():
        return None
    wpp = viewpick.world_per_pixel(self.plotter)
    hit = viewpick.pick_actor(self.plotter, S[i][0], S[i][1], self.actor_part)
    if hit is not None and float(np.linalg.norm(np.array(hit) - P[i])) > max(0.5, 6.0 * wpp):
        return None
    return P[i]


def rg_pick(self, x, y):
    """A click while the references of a plane / axis are being picked."""
    f = self.rg_feature()
    solid = self.shown_solid()
    q = self.pick_vertex(x, y)
    if q is not None:
        return rg_toggle(self, f, {"k": "vertex", "r": {"p": [float(v) for v in q]}})
    ei = self.pick_edge(x, y)
    if ei is not None and self.pick_solid() is not None:
        return rg_toggle(self, f, {"k": "edge", "r": self.doc.edge_ref(self.pick_solid().edges()[ei])})
    r = viewpick.pick_surface(self.plotter, x, y)
    if r is None:
        return
    pos, actor, cid = r
    for nm, a in self.actor_planes.items():
        if viewpick.same_actor(a, actor) and not (self.actor_part is not None and viewpick.same_actor(self.actor_part, actor)):
            return rg_toggle(self, f, {"k": "base", "n": nm})
    for fid, a in getattr(self, "actor_refs", {}).items():
        if viewpick.same_actor(a, actor) and fid != f["id"]:
            g = self.doc.feature(fid)
            return rg_toggle(self, f, {"k": "ref", "id": fid, "kind": "plane" if g["kind"] == "refplane" else "line"})
    if self.actor_part is None or not viewpick.same_actor(self.actor_part, actor) or solid is None:
        return
    idx = int(self.view_cells.cell_data["face"][cid])
    face = solid.faces()[idx]
    g = face.geom_type.name
    if g == "PLANE":
        spec = {"k": "face", "r": self.doc.face_ref(face)}
    else:
        c = face.center()
        spec = {"k": "face", "r": {"c": [c.X, c.Y, c.Z], "g": g}}
    rg_toggle(self, f, spec)


def rg_pick_tree(self, kind, key):
    """A click on a plane / origin / reference feature of the (small) tree while references are picked.  True when it was used."""
    f = self.rg_feature()
    if f is None:
        return False
    if kind == "plane":
        rg_toggle(self, f, {"k": "base", "n": key})
    elif kind == "origin":
        rg_toggle(self, f, {"k": "origin"})
    elif kind == "feature":
        g = self.doc.feature(key)
        if is_ref(g) and g["id"] != f["id"]:
            rg_toggle(self, f, {"k": "ref", "id": key, "kind": "plane" if g["kind"] == "refplane" else "line"})
        else:
            return False
    else:
        return False
    return True


# ------------------------------------------------------------------------------------------- panel
def ref_panel(self, form, f):
    d = self.doc
    plane = f["kind"] == "refplane"
    editing = self.rg_feature() is f
    types = refgeo.PLANE_TYPES if plane else refgeo.AXIS_TYPES
    info = QLabel("Pick the references in the view or in the small tree (top left of the view). Click a pick again to remove it."
                  if editing else "Press  Edit references  to change what this " + ("plane" if plane else "axis") + " is built from.")
    info.setWordWrap(True)
    info.setStyleSheet("color:#1f4fb4; padding:2px 0;")
    form.addRow(info)
    lw = QListWidget()
    lw.setMaximumHeight(92)
    for i, s in enumerate(f.get("refs", [])):
        lw.addItem(f"{ORD[i]}:  {describe(self, s)}")
    if not f.get("refs"):
        lw.addItem("(nothing picked yet)")
    form.addRow(lw)
    row = QHBoxLayout()
    if editing:
        b = QPushButton("Remove last pick")
        b.clicked.connect(lambda: self.rg_remove_last(f))
        row.addWidget(b)
        b = QPushButton("Clear picks")
        b.clicked.connect(lambda: self.rg_clear(f))
        row.addWidget(b)
    else:
        b = QPushButton("Edit references")
        b.clicked.connect(lambda: self.rg_begin(f))
        row.addWidget(b)
    w = QWidget()
    w.setLayout(row)
    form.addRow(w)
    form.addRow(QLabel("<b>Type</b>"))
    grp = QButtonGroup(self.props)
    cur = f.get("ptype")
    for t, name, needs, tip in types:
        rb = QRadioButton(name)
        rb.setToolTip(f"{tip}.  Needs: {needs}")
        rb.setChecked(cur == t)
        rb.toggled.connect(lambda on, t=t: on and self.rg_set_type(f, t))
        grp.addButton(rb)
        form.addRow(rb)
    if f.get("auto", True):
        form.addRow(QLabel("<i>The type follows what you pick - choose one above to fix it.</i>"))
    t = f.get("ptype")
    if plane and t == "offset":
        self.expr_edit(form, "Distance (mm)", f, "d")
    if plane and t == "angle":
        self.expr_edit(form, "Angle (deg)", f, "ang")
    if plane:
        self.check(form, "Flip", f, "flip")
    st = d.status.get(f["id"], "")
    if st == "ok":
        ok = QLabel("Fully defined")
        ok.setStyleSheet("background:#8cf58c; padding:3px; font-weight:bold;")
        form.addRow(ok)
    if plane and t == "angle" and f.get("refs") and st == "ok":
        pass


def rg_set_type(self, f, t):
    if f.get("ptype") == t and not f.get("auto", True):
        return
    self.snapshot()
    f["ptype"], f["auto"] = t, False
    self.update_all()


def rg_remove_last(self, f):
    if f.get("refs"):
        self.snapshot()
        f["refs"] = f["refs"][:-1]
        retype(f)
        self.update_all()


def rg_clear(self, f):
    self.snapshot()
    f["refs"] = []
    retype(f)
    self.update_all()


def rg_begin(self, f):
    self.rg_edit = f["id"]
    self.created_new = None
    self.show_props()
    self.draw()
    self.say("Pick the references in the view or the small tree. Press OK when done.")


# ------------------------------------------------------------------------------------------- drawing
def draw_refgeo(self, pl, pv, solid, size):
    d = self.doc
    self.actor_refs = {}
    f_edit = self.rg_feature()
    if f_edit is not None and solid is not None:               # highlight what is picked
        faces = solid.faces()
        for s in f_edit.get("refs", []):
            try:
                if s["k"] == "face":
                    ent = d.spec_entity(s, solid)
                    c0 = np.array(s["r"]["c"])
                    best = min(range(len(faces)), key=lambda i: float(np.linalg.norm(np.array(tuple(faces[i].center())) - c0))
                               if faces[i].geom_type.name == s["r"].get("g", "PLANE") else 1e18)
                    cs = np.where(np.array(self.view_cells.cell_data["face"]) == best)[0]
                    if len(cs):
                        pl.add_mesh(self.view_cells.extract_cells(cs), color=PICK_COL, lighting=False, pickable=False, reset_camera=False)
                elif s["k"] == "edge":
                    ml = self.merged_lines([self.edge_pts(s["r"], solid)])
                    if ml is not None:
                        pl.add_mesh(ml, color=PICK_COL, line_width=5, pickable=False, reset_camera=False)
                elif s["k"] == "vertex":
                    pl.add_mesh(pv.PolyData(np.array([s["r"]["p"]])), color=PICK_COL, point_size=12, render_points_as_spheres=True,
                                pickable=False, reset_camera=False)
                elif s["k"] == "origin":
                    pl.add_mesh(pv.PolyData(np.zeros((1, 3))), color=PICK_COL, point_size=13, render_points_as_spheres=True,
                                pickable=False, reset_camera=False)
            except Exception:
                pass
    picked = {s["id"] for s in (f_edit.get("refs", []) if f_edit is not None else []) if s["k"] == "ref"}
    picked |= {s["n"] for s in (f_edit.get("refs", []) if f_edit is not None else []) if s["k"] == "base"}
    for f in d.features:
        if not is_ref(f) or f["id"] not in d.refgeo:
            continue
        sel = f["id"] == self.sel
        on = f.get("show", True) if self.vis.get("refgeo", True) else False
        if not (on or sel or f["id"] in picked):
            continue
        e = d.refgeo[f["id"]]
        hot = sel or f["id"] in picked
        if f["kind"] == "refplane":
            x = np.asarray(e["x"], float)
            y = np.cross(e["n"], x)
            h = size / 2
            p = np.asarray(e["p"], float)
            sq = pv.Plane(center=tuple(p), direction=tuple(e["n"]), i_size=size, j_size=size)
            a = pl.add_mesh(sq, color=PICK_COL if f["id"] in picked else REF_COL, opacity=0.5 if hot else 0.16, pickable=True, lighting=False,
                            reset_camera=False)
            self.actor_refs[f["id"]] = a
            cor = np.array([p - x * h - y * h, p + x * h - y * h, p + x * h + y * h, p - x * h + y * h, p - x * h - y * h])
            pl.add_mesh(self.merged_lines([cor]), color=REF_COL, line_width=2.5 if hot else 1.2, pickable=False, reset_camera=False)
        else:
            p, dv = np.asarray(e["p"], float), np.asarray(e["d"], float)
            L = 0.7 * size
            tube = pv.Tube(pointa=tuple(p - dv * L), pointb=tuple(p + dv * L), radius=size * (0.010 if hot else 0.006))
            a = pl.add_mesh(tube, color=PICK_COL if f["id"] in picked else AXIS_COL, pickable=True, lighting=False, reset_camera=False)
            self.actor_refs[f["id"]] = a


def select_ref_from_view(self, actor):
    """A plain click on a reference plane / axis in the view: select its feature (so Sketch can use it)."""
    for fid, a in getattr(self, "actor_refs", {}).items():
        if viewpick.same_actor(a, actor):
            self.sel, self.sel_plane, self.sel_face, self.sel_edges = fid, None, None, []
            self.refresh_tree()
            self.show_props()
            self.draw()
            f = self.doc.feature(fid)
            self.say(f"{f['name']} selected" + (" - press Sketch to draw on it." if f["kind"] == "refplane" else "."))
            return True
    return False


def mini_pick(self, data):
    """A click in the small tree: used as a pick when something is waiting for one."""
    kind, key = data
    if self.ed is not None and self.ed.active:
        return False
    if self.rg_pick_tree(kind, key):
        return True
    f = self.doc.feature(self.sel) if self.sel else None
    if f is not None and f["kind"] == "mirror":
        if kind == "plane":
            newp = {"base": key}
        elif kind == "feature" and (self.doc.feature(key) or {}).get("kind") == "refplane":
            newp = {"ref": key}
        else:
            return False
        self.snapshot()
        f["plane"] = newp
        self.update_all()
        return True
    return False


def install(cls):
    for fn in (mini_pick, rg_feature, rg_start, pick_vertex, rg_pick, rg_pick_tree, ref_panel, rg_set_type, rg_remove_last, rg_clear, rg_begin,
               draw_refgeo, select_ref_from_view):
        setattr(cls, fn.__name__, fn)
