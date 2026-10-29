"""
sim_slice.py - the "Slice with a plane" window of a simulation.

A small 3D view of the source part / assembly (only the planes that are switched on in the source viewport are drawn).  Click a plane or a
flat face of the model to choose the cutting plane, set the offset (signed; - / + buttons, Reverse), and see the cut before importing it.

  visible_planes(widget, kind)  [(name, spec)] the planes the source viewport shows (hidden ones are left out)
  ScenePicker                   the geometry of the small view + ray picking (no widgets: testable without a screen)
  SliceDialog(parent, planes, bodies, last)   .out = {"plane", "offset", "flip", "excluded"[, "face": plane spec as lists]} after exec()
"""
import numpy as np
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter,
                             QVBoxLayout, QWidget)

import refgeo
import unitctl
import slice3d

try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
except Exception:                                    # no 3D: the window still works with the plane list
    pv, QtInteractor = None, None

FACE = "Face (clicked)"
PLANE_COL = {"Front": (0.2, 0.45, 0.9), "Top": (0.2, 0.75, 0.3), "Right": (0.9, 0.35, 0.3)}
REF_COL = (0.75, 0.55, 0.15)


# ---------------------------------------------------------------------------------------------- which planes the viewport shows
def visible_planes(widget, kind):
    """[(name, spec)] of the planes that are on in the source viewport: the base planes (when 'planes' is on and the plane is ticked)
    and the reference planes that are shown (when 'reference geometry' is on).  Mirrors what the part / assembly window draws."""
    out = []
    if widget is None:
        return out
    vis = getattr(widget, "vis", {}) or {}
    if kind == "part":
        doc = getattr(widget, "doc", None)
        if doc is None:
            return out
        if vis.get("planes", True):
            show = getattr(widget, "plane_show", {})
            out += [(nm, slice3d.base_spec(nm)) for nm in ("Front", "Top", "Right") if show.get(nm, True)]
        if vis.get("refgeo", True):
            for nm, sp in slice3d.part_plane_specs(doc):
                if nm in ("Front", "Top", "Right"):
                    continue
                f = next((x for x in doc.features if x["name"] == nm), None)
                if f is not None and f.get("show", True):
                    out.append((nm, sp))
        return out
    a = getattr(widget, "asm", None)
    if a is None:
        return out
    if vis.get("planes", True):
        out += [(nm, slice3d.base_spec(nm)) for nm in ("Front", "Top", "Right") if a.world_show.get(nm, True)]
    if vis.get("refgeo", True):
        shown = {r["name"] for r in a.refs if r.get("kind") == "refplane" and r.get("show", True)}
        out += [(nm, sp) for nm, sp in slice3d.asm_plane_specs(a) if nm not in ("Front", "Top", "Right") and nm in shown]
    return out


# ---------------------------------------------------------------------------------------------- scene geometry and picking
def _tess(shape, tol=0.4):
    v, t = shape.tessellate(tol, 0.3)
    if not len(t):
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    return np.array([[p.X, p.Y, p.Z] for p in v], float), np.array(t, int)


def face_spec(origin, normal):
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    x = np.array(refgeo.frame_x(n), float)
    x = x - np.dot(x, n) * n
    x /= np.linalg.norm(x)
    v = np.cross(n, x)
    o = np.asarray(origin, float)
    return {"o": o, "n": n, "u": x, "v": v / np.linalg.norm(v)}


class ScenePicker:
    """bodies = [(name, solid, ...)] (placed); planes = [(name, spec)].  Holds the body meshes, the flat faces (for picking) and the plane squares."""

    def __init__(self, bodies, planes):
        self.bodies = bodies
        self.planes = planes
        self.meshes = []                  # per body (vertices, triangles)
        tri_p, tri_f = [], []             # all flat-face triangles (3,3) and the face id of each
        self.faces = []                   # per flat face: spec of its plane
        lo, hi = np.full(3, 1e30), np.full(3, -1e30)
        for b in bodies:
            solid = b[1]
            try:
                self.meshes.append(_tess(solid))
            except Exception:
                self.meshes.append((np.zeros((0, 3)), np.zeros((0, 3), int)))
            try:
                bb = solid.bounding_box()
                lo = np.minimum(lo, [bb.min.X, bb.min.Y, bb.min.Z])
                hi = np.maximum(hi, [bb.max.X, bb.max.Y, bb.max.Z])
            except Exception:
                pass
            try:
                faces = list(solid.faces())
            except Exception:
                faces = []
            for f in faces:
                if f.geom_type.name != "PLANE":
                    continue
                try:
                    v, t = _tess(f)
                    c = f.center()
                    nrm = f.normal_at(c)
                    spec = face_spec([c.X, c.Y, c.Z], [nrm.X, nrm.Y, nrm.Z])
                except Exception:
                    continue
                if not len(t):
                    continue
                self.faces.append(spec)
                tri_p.append(v[t])
                tri_f.append(np.full(len(t), len(self.faces) - 1))
        self.tri = np.concatenate(tri_p) if tri_p else np.zeros((0, 3, 3))
        self.tri_face = np.concatenate(tri_f) if tri_f else np.zeros(0, int)
        if not np.all(np.isfinite(lo)):
            lo, hi = np.full(3, -50.0), np.full(3, 50.0)
        self.centre = 0.5 * (lo + hi)
        self.size = max(float(np.linalg.norm(hi - lo)), 10.0)
        self.plane_half = 0.4 * self.size

    def plane_quad(self, spec):
        """The 4 corners of the square drawn for a plane (centred on the model's projection onto it)."""
        c = spec["o"] + spec["n"] * 0.0
        c = self.centre - spec["n"] * float(np.dot(self.centre - spec["o"], spec["n"]))
        h = self.plane_half
        return np.array([c - spec["u"] * h - spec["v"] * h, c + spec["u"] * h - spec["v"] * h,
                         c + spec["u"] * h + spec["v"] * h, c - spec["u"] * h + spec["v"] * h])

    def pick(self, o, d):
        """Nearest thing under a ray: ("face", spec) / ("plane", name) / None."""
        o, d = np.asarray(o, float), np.asarray(d, float)
        d = d / np.linalg.norm(d)
        best = None
        if len(self.tri):
            a, b, c = self.tri[:, 0], self.tri[:, 1], self.tri[:, 2]
            e1, e2 = b - a, c - a
            p = np.cross(d, e2)
            det = np.einsum("ij,ij->i", e1, p)
            ok = np.abs(det) > 1e-12
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            tv = o - a
            u = np.einsum("ij,ij->i", tv, p) * inv
            q = np.cross(tv, e1)
            v = (q @ d) * inv
            t = np.einsum("ij,ij->i", e2, q) * inv
            hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-9)
            if hit.any():
                i = int(np.argmin(np.where(hit, t, np.inf)))
                best = (float(t[i]), "face", self.faces[int(self.tri_face[i])])
        for nm, sp in self.planes:
            den = float(np.dot(sp["n"], d))
            if abs(den) < 1e-12:
                continue
            t = float(np.dot(sp["o"] - o, sp["n"])) / den
            if t <= 1e-9 or (best is not None and t >= best[0]):
                continue
            x = o + d * t - (self.centre - sp["n"] * float(np.dot(self.centre - sp["o"], sp["n"])))
            if abs(float(x @ sp["u"])) <= self.plane_half and abs(float(x @ sp["v"])) <= self.plane_half:
                best = (t, "plane", nm)
        return None if best is None else (best[1], best[2])


# ---------------------------------------------------------------------------------------------- the window
class SliceDialog(QDialog):
    def __init__(self, parent, planes, bodies, last=None, multi=False):
        """planes = [(name, spec)] visible ones; bodies = [(name, solid, material)]; last = the previous choice."""
        super().__init__(parent)
        self.setWindowTitle("Slice with a plane")
        self.resize(980, 620)
        self.planes = list(planes)
        self.bodies = bodies
        self.multi = multi
        self.face = None                         # plane spec of a clicked face
        self.out = None
        self.pick = ScenePicker(bodies, self.planes)
        self.pl = None
        self.hook = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.update_preview)

        outer = QHBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split)
        self.view_holder = QWidget()
        vl = QVBoxLayout(self.view_holder)
        vl.setContentsMargins(0, 0, 0, 0)
        self.view_hint = QLabel("Click a plane or a flat face of the model to choose it.  Drag to rotate, wheel to zoom.")
        self.view_hint.setWordWrap(True)
        vl.addWidget(self.view_hint)
        self.make_view(vl)
        split.addWidget(self.view_holder)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.addWidget(QLabel("The plane cuts the model; the cut outlines become the 2D sketch of this simulation.\n"
                            "Only the planes that are shown in the model window are listed."))
        sl.addWidget(QLabel("Plane"))
        self.lst = QListWidget()
        self.lst.setMaximumHeight(150)
        for nm, _ in self.planes:
            self.lst.addItem(nm)
        self.lst.currentRowChanged.connect(self.plane_row)
        sl.addWidget(self.lst)

        row = QHBoxLayout()
        row.addWidget(QLabel(unitctl.label("Offset (mm)")))
        self.b_minus = QPushButton("-")
        self.b_plus = QPushButton("+")
        for b in (self.b_minus, self.b_plus):
            b.setFixedWidth(30)
        self.offset = QLineEdit("0")
        self.offset.setToolTip(f"Moves the plane along its arrow (its normal), in {unitctl.length_unit()}.  Negative values move it the other way.")
        self.step = QLineEdit(f"{unitctl.to_disp(self.default_step()):.2g}")
        self.step.setFixedWidth(50)
        self.step.setToolTip(f"How far - / + move the plane ({unitctl.length_unit()}).")
        self.b_rev = QPushButton("Reverse")
        self.b_rev.setToolTip("Swaps the sign of the offset (moves the plane to the other side of the starting plane).")
        row.addWidget(self.b_minus)
        row.addWidget(self.offset)
        row.addWidget(self.b_plus)
        row.addWidget(QLabel("step"))
        row.addWidget(self.step)
        row.addWidget(self.b_rev)
        sl.addLayout(row)
        self.b_minus.clicked.connect(lambda: self.nudge(-1))
        self.b_plus.clicked.connect(lambda: self.nudge(+1))
        self.b_rev.clicked.connect(self.reverse)
        self.offset.textChanged.connect(self.changed)

        self.flip = QCheckBox("Look at the cut from the other side")
        self.flip.setToolTip("Turns the 2D sketch over (the cut itself does not move).")
        self.flip.toggled.connect(self.changed)
        sl.addWidget(self.flip)

        self.parts = None
        if multi and len(bodies) > 1:
            sl.addWidget(QLabel("Parts to cut (untick the ones to leave out, e.g. bolts):"))
            self.parts = QListWidget()
            self.parts.setMaximumHeight(150)
            for b in bodies:
                it = QListWidgetItem(b[0])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked if last and b[0] in last.get("excluded", []) else Qt.CheckState.Checked)
                self.parts.addItem(it)
            self.parts.itemChanged.connect(self.changed)
            sl.addWidget(self.parts)

        self.info = QLabel()
        self.info.setWordWrap(True)
        sl.addWidget(self.info)
        self.err = QLabel()
        self.err.setStyleSheet("color:#b00020;")
        sl.addWidget(self.err)
        sl.addStretch(1)
        brow = QHBoxLayout()
        brow.addStretch(1)
        ok = QPushButton("Slice")
        ok.setDefault(True)
        ok.clicked.connect(self.go)
        no = QPushButton("Cancel")
        no.clicked.connect(self.reject)
        brow.addWidget(ok)
        brow.addWidget(no)
        sl.addLayout(brow)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.cur_name = None
        if last:
            if last.get("face"):
                self.set_face(self.spec_from_lists(last["face"]))
            else:
                i = next((k for k, (nm, _) in enumerate(self.planes) if nm == last.get("plane")), -1)
                if i >= 0:
                    self.lst.setCurrentRow(i)
            self.offset.setText(f"{unitctl.to_disp(last.get('offset', 0)):.8g}")
            self.flip.setChecked(bool(last.get("flip")))
        elif self.planes:
            self.lst.setCurrentRow(0)
        self.redraw_scene()
        self.update_preview()

    # ------------------------------------------------------------------ the small view
    def make_view(self, layout):
        if QtInteractor is None:
            layout.addWidget(QLabel("(3D view not available - choose the plane from the list)"))
            return
        try:
            self.pl = QtInteractor(self.view_holder)
            layout.addWidget(self.pl.interactor if hasattr(self.pl, "interactor") else self.pl, 1)
            import viewpick
            self.hook = viewpick.ClickHook(self.pl, self.on_click)
        except Exception:
            self.pl = None
            layout.addWidget(QLabel("(3D view could not start - choose the plane from the list)"))

    def default_step(self):
        s = self.pick.size / 40.0
        return float(f"{max(s, 0.1):.1g}")

    def ray(self, x, y):
        pl = self.pl
        ren = pl.renderer
        ren.SetDisplayPoint(x, y, 0.0)
        ren.DisplayToWorld()
        p0 = np.array(ren.GetWorldPoint()[:3]) / ren.GetWorldPoint()[3]
        ren.SetDisplayPoint(x, y, 1.0)
        ren.DisplayToWorld()
        p1 = np.array(ren.GetWorldPoint()[:3]) / ren.GetWorldPoint()[3]
        return p0, p1 - p0

    def on_click(self, x, y):
        if self.pl is None:
            return
        try:
            o, d = self.ray(x, y)
        except Exception:
            return
        self.choose(self.pick.pick(o, d))

    def choose(self, hit):
        if hit is None:
            return
        kind, what = hit
        if kind == "plane":
            for i, (nm, _) in enumerate(self.planes):
                if nm == what:
                    self.lst.setCurrentRow(i)
                    return
        else:
            self.set_face(what)

    def set_face(self, spec):
        self.face = spec
        if self.lst.count() and self.lst.item(self.lst.count() - 1).text() == FACE:
            self.lst.takeItem(self.lst.count() - 1)
        self.lst.addItem(FACE)
        self.lst.setCurrentRow(self.lst.count() - 1)

    @staticmethod
    def spec_from_lists(d):
        return {k: np.array(v, float) for k, v in d.items()}

    def redraw_scene(self):
        """The model (grey) and the visible planes (translucent squares).  The cutting plane and the cut are redrawn by update_preview()."""
        pl = self.pl
        if pl is None:
            return
        try:
            pl.clear()
            for v, t in self.pick.meshes:
                if len(t):
                    faces = np.hstack([np.full((len(t), 1), 3), t]).ravel()
                    pl.add_mesh(pv.PolyData(v, faces), color=(0.72, 0.74, 0.78), smooth_shading=False, pickable=False, reset_camera=False)
            for nm, sp in self.planes:
                q = self.pick.plane_quad(sp)
                col = PLANE_COL.get(nm, REF_COL)
                pl.add_mesh(pv.PolyData(q, np.array([4, 0, 1, 2, 3])), color=col, opacity=0.14, pickable=False, lighting=False, reset_camera=False)
            pl.reset_camera()
            pl.render()
        except Exception:
            pass

    # ------------------------------------------------------------------ the choice
    def plane_row(self, row):
        if row < 0 or row >= self.lst.count():
            return
        nm = self.lst.item(row).text()
        self.cur_name = nm
        self.changed()

    def base(self):
        if self.cur_name == FACE:
            return self.face
        return dict(self.planes).get(self.cur_name)

    def value(self):
        try:
            return unitctl.read_length(self.offset.text())          # millimetres
        except ValueError:
            return None

    def nudge(self, sign):
        try:
            st = abs(unitctl.read_length(self.step.text()))
        except ValueError:
            st = unitctl.from_disp(1.0)
        v = self.value() or 0.0
        self.offset.setText(f"{unitctl.to_disp(v + sign * st):.8g}")

    def reverse(self):
        v = self.value()
        if v:
            self.offset.setText(f"{unitctl.to_disp(-v):.8g}")
        else:
            self.flip.setChecked(not self.flip.isChecked())

    def changed(self, *_):
        self.err.setText("")
        self.timer.start()

    def excluded(self):
        if self.parts is None:
            return []
        return [self.parts.item(i).text() for i in range(self.parts.count()) if self.parts.item(i).checkState() != Qt.CheckState.Checked]

    def cut_loops(self):
        base, off = self.base(), self.value()
        if base is None or off is None:
            return None, None
        sp = slice3d.shifted(base, off, self.flip.isChecked())
        ex = set(self.excluded())
        use = [(i, b[1]) for i, b in enumerate(self.bodies) if b[0] not in ex]
        try:
            return sp, slice3d.slice_bodies(use, sp)
        except Exception:
            return sp, []

    def update_preview(self):
        """The cutting plane (strong square with its normal arrow) and the cut outlines (thick lines) in the small view."""
        sp, loops = self.cut_loops()
        if sp is None:
            self.info.setText("Choose a plane and give the offset as a number.")
            return
        self.info.setText(("The plane cuts the model: %d outline(s)." % len(loops)) if loops else "The plane does not cut any part - move it.")
        self.preview_loops = loops
        pl = self.pl
        if pl is None:
            return
        try:
            for nm in ("_cutplane", "_cutarrow", "_cutlines"):
                pl.remove_actor(nm, render=False)
            q = self.pick.plane_quad(sp)
            pl.add_mesh(pv.PolyData(q, np.array([4, 0, 1, 2, 3])), color=(1.0, 0.55, 0.0), opacity=0.35, pickable=False, lighting=False,
                        name="_cutplane", reset_camera=False)
            c = q.mean(axis=0)
            L = 0.12 * self.pick.size
            pl.add_mesh(pv.Arrow(start=c, direction=sp["n"], scale=L), color=(1.0, 0.35, 0.0), pickable=False, name="_cutarrow", reset_camera=False)
            pts = []
            for lp in loops or []:
                for poly in self.loop_points(lp):
                    P = np.array([sp["o"] + sp["u"] * x + sp["v"] * y for x, y in poly])
                    for a, b in zip(P[:-1], P[1:]):
                        pts += [a, b]
            if pts:
                P = np.array(pts)
                cells = np.column_stack([np.full(len(P) // 2, 2), np.arange(0, len(P), 2), np.arange(1, len(P), 2)]).ravel()
                pd = pv.PolyData(P)
                pd.lines = cells
                pl.add_mesh(pd, color=(0.85, 0.1, 0.1), line_width=3, pickable=False, lighting=False, name="_cutlines", reset_camera=False)
            pl.render()
        except Exception:
            pass

    @staticmethod
    def loop_points(lp):
        """The loop as one or more polylines of (x, y) points (arcs and circles sampled)."""
        import math
        pts = []
        for e in lp["edges"]:
            t = e["t"]
            if t == "line":
                pts.append([tuple(e["a"]), tuple(e["b"])])
            elif t == "poly":
                pts.append([tuple(p) for p in e["pts"]])
            elif t == "circle":
                cx, cy = e["c"]
                r = e["r"]
                pts.append([(cx + r * math.cos(a), cy + r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 49)])
            elif t == "arc":
                cx, cy = e["c"]
                r = e["r"]
                a0 = math.atan2(e["s"][1] - cy, e["s"][0] - cx)
                am = math.atan2(e["m"][1] - cy, e["m"][0] - cx)
                a1 = math.atan2(e["e"][1] - cy, e["e"][0] - cx)
                two = 2 * math.pi
                dm, d1 = (am - a0) % two, (a1 - a0) % two
                if dm > d1:                      # the middle point lies on the clockwise way round
                    d1 -= two
                pts.append([(cx + r * math.cos(a0 + d1 * k / 24), cy + r * math.sin(a0 + d1 * k / 24)) for k in range(25)])
        return pts

    def go(self):
        v = self.value()
        if v is None:
            self.err.setText("The offset must be a number.")
            return
        if self.base() is None:
            self.err.setText("Choose a plane (click it in the view or pick it from the list).")
            return
        ex = self.excluded()
        if self.parts is not None and len(ex) == self.parts.count():
            self.err.setText("Leave at least one part in.")
            return
        out = {"plane": self.cur_name, "offset": v, "flip": self.flip.isChecked(), "excluded": ex}
        if self.cur_name == FACE:
            out["face"] = {k: [float(x) for x in a] for k, a in self.face.items()}
        self.out = out
        self.cleanup()
        self.accept()

    def cleanup(self):
        if self.pl is not None:
            try:
                self.pl.close()
            except Exception:
                pass
            self.pl = None

    def reject(self):
        self.cleanup()
        super().reject()

    def closeEvent(self, ev):
        self.cleanup()
        super().closeEvent(ev)
