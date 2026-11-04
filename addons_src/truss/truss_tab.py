"""truss_tab.py - the Truss Generator window: a Members page (the sketch on one side, the member and its joints on the other) and an Assembly page
(every member of a sketch configuration placed in the truss plane).  The engine is truss_core.py."""
import os

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

import truss_core as tc
import unitctl


def disp(text):
    """A length formula stored in mm -> text in the current unit (File > Units)."""
    return unitctl.expr_to_display(str(text))


def store(text):
    """A length formula typed in the current unit -> mm text for the project."""
    t = str(text).strip()
    try:
        return unitctl.expr_from_display(t) if t else t
    except Exception:
        return t


def udisp(mm):
    """A length in mm as a number for display (current unit)."""
    return unitctl.num(unitctl.to_disp(float(mm)), 6)



def to_poly(shape, tol=0.4):
    import pyvista as pv
    v, t = shape.tessellate(tol, 0.3)
    pts = np.array([(p.X, p.Y, p.Z) for p in v], float)
    if not len(t):
        return pv.PolyData()
    return pv.PolyData(pts, np.hstack([np.full((len(t), 1), 3), np.array(t, np.int64)]).ravel())


class View3D(QWidget):
    """A small 3D view (pyvista); if it cannot start, a label says so and the rest keeps working."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plotter = None
        try:
            from pyvistaqt import QtInteractor
            self.plotter = QtInteractor(self)
            self.plotter.set_background("#f4f5f7")
            lay.addWidget(self.plotter.interactor, 1)
            row = QHBoxLayout()
            for text, fn in (("Iso", lambda: self.set_view("iso")), ("Truss plane", lambda: self.set_view("xy")), ("Side", lambda: self.set_view("xz")), ("Fit", lambda: self.set_view("fit"))):
                b = QPushButton(text)
                b.clicked.connect(fn)
                row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)
        except Exception as ex:
            lay.addWidget(QLabel(f"The 3D view could not start: {ex}"))

    def set_view(self, which):
        if self.plotter is None:
            return
        try:
            {"iso": self.plotter.view_isometric, "xy": self.plotter.view_xy, "xz": self.plotter.view_xz, "fit": self.plotter.reset_camera}[which]()
            self.plotter.render()
        except Exception:
            pass

    @staticmethod
    def edge_mesh(shape):
        """The outline of a solid, drawn the way the part and assembly windows draw it (same curve accuracy)."""
        import pm_app
        import settings
        polys = [np.array(settings.edge_points(e, None)) for e in shape.edges()]
        return pm_app.MainWindow.merged_lines(polys)

    @staticmethod
    def dashed(p0, p1, dash, gap):
        """A dotted line from p0 to p1 as short separate segments (pyvista has no line pattern)."""
        import pyvista as pv
        a, b = np.array(p0, float), np.array(p1, float)
        L = float(np.linalg.norm(b - a))
        if L < 1e-9:
            return None
        u = (b - a) / L
        pts, cells, t = [], [], 0.0
        while t < L:
            e = min(t + dash, L)
            cells += [2, len(pts), len(pts) + 1]
            pts += [a + u * t, a + u * e]
            t = e + gap
        pd = pv.PolyData()
        pd.points = np.array(pts)
        pd.lines = np.array(cells)
        return pd

    def enable_pick(self, callback):
        """The next click on a solid calls callback((x, y, z)) with the point on its surface."""
        if self.plotter is None:
            return False
        try:
            self.plotter.enable_surface_point_picking(callback=lambda *a: callback(tuple(float(v) for v in a[0])), show_message=False, show_point=False,
                                                      left_clicking=True, pickable_window=False)
            return True
        except Exception:
            return False

    def disable_pick(self):
        if self.plotter is not None:
            try:
                self.plotter.disable_picking()
            except Exception:
                pass

    def show_shapes(self, items, fit=True, overlays=None):
        """items: [(build123d shape, (r, g, b), opacity)]"""
        if self.plotter is None:
            return
        try:
            self.plotter.clear()
            for shape, color, op in items:
                m = to_poly(shape)
                if m.n_points:
                    self.plotter.add_mesh(m, color=color, opacity=op, smooth_shading=False, show_edges=False, pickable=True, reset_camera=False)
                    try:
                        import settings
                        ml = self.edge_mesh(shape)
                        if ml is not None:
                            self.plotter.add_mesh(ml, color=(0.13, 0.15, 0.20), line_width=settings.get("line_px"), pickable=False, reset_camera=False)
                    except Exception:
                        pass
            import pyvista as pv
            for ov in overlays or []:
                if ov["kind"] == "dash":
                    ml = self.dashed(ov["p0"], ov["p1"], ov["dash"], ov["gap"])
                    if ml is not None:
                        self.plotter.add_mesh(ml, color=ov["color"], line_width=2.5, pickable=False, reset_camera=False)
                elif ov["kind"] == "face":
                    fm = to_poly(ov["shape"])
                    if fm.n_points:
                        self.plotter.add_mesh(fm, color=ov["color"], opacity=0.92, smooth_shading=False, show_edges=False, pickable=False, reset_camera=False)
                else:
                    self.plotter.add_mesh(pv.Sphere(radius=ov["r"], center=ov["pt"]), color=ov["color"], pickable=False, reset_camera=False)
            if fit:
                self.plotter.view_isometric()
                self.plotter.reset_camera()
            self.plotter.render()
        except Exception:
            pass


class SketchCanvas(QWidget):
    """The lines of the sketch in the active configuration; click a line to select it, double-click to make it a member."""
    picked = pyqtSignal(object)
    toggled = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 260)
        self.lines, self.members, self.selected = {}, {}, None
        self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)            # the view: wheel zooms at the cursor, middle-drag pans; the direction never changes
        self._drag = None
        self.setMouseTracking(True)
        self.btn_fit = QPushButton("Fit", self)
        self.btn_fit.setToolTip("Show the whole sketch (double-clicking empty space does the same)")
        self.btn_fit.clicked.connect(self.fit)

    def resizeEvent(self, ev):
        self.btn_fit.move(self.width() - self.btn_fit.width() - 6, 6)

    def fit(self):
        self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)
        self.update()

    def set_data(self, lines, members, selected):
        if set(lines) != set(self.lines):                       # another sketch: show all of it; the same lines keep the zoom and the pan
            self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)
        self.lines, self.members, self.selected = lines, members, selected
        self.update()

    def wheelEvent(self, ev):
        if not self.lines:
            return
        f = 1.25 ** (ev.angleDelta().y() / 120.0)
        z = min(max(self.zoom * f, 0.2), 200.0)
        f = z / self.zoom
        c = ev.position()
        self.pan = QPointF(f * self.pan.x() + (1 - f) * c.x(), f * self.pan.y() + (1 - f) * c.y())
        self.zoom = z
        self.update()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is not None:
            d = ev.position() - self._drag
            self._drag = ev.position()
            self.pan = self.pan + d
            self.update()

    def _map(self):
        if not self.lines:
            return None
        xs = [v for ln in self.lines.values() for v in (ln["p0"][0], ln["p1"][0])]
        ys = [v for ln in self.lines.values() for v in (ln["p0"][1], ln["p1"][1])]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        pad = 28
        k = min((self.width() - 2 * pad) / w, (self.height() - 2 * pad) / h)
        ox = (self.width() - k * w) / 2 - k * x0
        oy = (self.height() + k * h) / 2 + k * y0
        z, pan = self.zoom, self.pan
        return lambda p: QPointF(z * (ox + k * p[0]) + pan.x(), z * (oy - k * p[1]) + pan.y())

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        f = self._map()
        if f is None:
            p.setPen(QColor("#667085"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Import a sketch to see its lines here")
            return
        p.setFont(QFont("Segoe UI", 8))
        for lid, ln in self.lines.items():
            mem = self.members.get(lid)
            sel = lid == self.selected
            col = QColor("#e8590c") if sel else QColor("#1d4ed8") if mem else QColor("#98a2b3")
            p.setPen(QPen(col, 4 if (sel or mem) else 2))
            a, b = f(ln["p0"]), f(ln["p1"])
            p.drawLine(a, b)
            p.setBrush(col)
            p.drawEllipse(a, 3, 3)
            p.drawEllipse(b, 3, 3)
            u = b - a
            n = (u.x() ** 2 + u.y() ** 2) ** 0.5
            if n > 1e-6:                                              # the direction: a green dot at the start, an arrowhead at the end
                from PyQt6.QtGui import QPolygonF
                ux, uy = u.x() / n, u.y() / n
                tip = b
                base = QPointF(b.x() - ux * 14, b.y() - uy * 14)
                p.setPen(QPen(col, 1))
                p.setBrush(col)
                p.drawPolygon(QPolygonF([tip, QPointF(base.x() - uy * 6, base.y() + ux * 6), QPointF(base.x() + uy * 6, base.y() - ux * 6)]))
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.setBrush(QColor("#2f9e44"))
            p.drawEllipse(a, 5, 5)
            if mem or sel:
                p.setPen(col)
                p.drawText((a + b) / 2 + QPointF(6, -6), mem["name"] if mem else "(double-click to add)")

    def _hit(self, pos):
        f = self._map()
        if f is None:
            return None
        best, bd = None, 10.0
        for lid, ln in self.lines.items():
            a, b = f(ln["p0"]), f(ln["p1"])
            ab = b - a
            L2 = ab.x() ** 2 + ab.y() ** 2
            t = 0 if L2 == 0 else max(0, min(1, ((pos.x() - a.x()) * ab.x() + (pos.y() - a.y()) * ab.y()) / L2))
            q = a + ab * t
            d = ((pos.x() - q.x()) ** 2 + (pos.y() - q.y()) ** 2) ** 0.5
            if d < bd:
                best, bd = lid, d
        return best

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            self._drag = ev.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        lid = self._hit(ev.position())
        if lid is not None:
            self.picked.emit(lid)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            self._drag = None
            self.unsetCursor()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        lid = self._hit(ev.position())
        if lid is not None:
            self.toggled.emit(lid)
        else:
            self.fit()


class ProfileEditor(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, title="Profile"):
        super().__init__(title)
        self.lay = QFormLayout(self)
        self.kind = QComboBox()
        for k, (label, _d, _e) in tc.PROFILES.items():
            self.kind.addItem(label, k)
        self.lay.addRow("Shape", self.kind)
        self.fields = {}
        self.box = QWidget()
        self.form = QFormLayout(self.box)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.lay.addRow(self.box)
        self.busy = False
        self.kind.currentIndexChanged.connect(self._kind)

    def _clear(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}

    def _kind(self):
        if self.busy:
            return
        self.load({"kind": self.kind.currentData(), "params": dict(tc.PROFILES[self.kind.currentData()][1])})
        self.changed.emit()

    def load(self, prof):
        self.busy = True
        try:
            self.kind.setCurrentIndex(self.kind.findData(prof["kind"]))
            self._clear()
            for k, dflt in tc.PROFILES[prof["kind"]][1].items():
                e = QLineEdit(disp(prof["params"].get(k, dflt)))
                e.setToolTip(f"{unitctl.length_unit()}, or a formula of the sketch variables")
                e.editingFinished.connect(self.changed.emit)
                self.form.addRow(k, e)
                self.fields[k] = e
        finally:
            self.busy = False

    def value(self):
        return {"kind": self.kind.currentData(), "params": {k: store(e.text()) for k, e in self.fields.items()}}


FACES = [("auto", "Nearest long side (automatic)"), ("left", "Left face"), ("right", "Right face"), ("start", "Start end face"), ("end", "End end face")]


class EndEditor(QGroupBox):
    """The joint at one end of a member: automatic (from the sketch), a square end, a butt against a face of another member, or a miter with it."""
    changed = pyqtSignal()
    pick_requested = pyqtSignal()

    def __init__(self, title):
        super().__init__(title)
        f = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItem("Automatic", "auto")
        self.kind.addItem("No Cut", "free")
        self.kind.addItem("Butt Connect", "butt")
        self.kind.addItem("Miter Connect", "miter")
        self.kind.addItem("Conform Connect", "conform")
        self.kind.setToolTip("Automatic: worked out from the sketch.   No Cut: a plain square end.   Butt Connect: this member sits on a face of another, with a flat cut.\n"
                             "Miter Connect: both are cut at the bisector.   Conform Connect: this end is shaped to fit the other member's curve.")
        self.other = QComboBox()
        self.face = QComboBox()
        for k, label in FACES:
            self.face.addItem(label, k)
        self.pick = QPushButton("Pick the face in the 3D view")
        self.pick.setToolTip("Press, then click the face of a member in the 3D view that this end sits on; the face is highlighted")
        self.pick.clicked.connect(self.pick_requested.emit)
        self.gap = QLineEdit("0")
        self.gap.setToolTip(f"Root gap left at the joint, {unitctl.length_unit()} (weld clearance)")
        self.result = QLabel("")
        self.result.setWordWrap(True)
        f.addRow("Joint", self.kind)
        f.addRow("  member", self.other)
        f.addRow("  face", self.face)
        f.addRow(self.pick)
        f.addRow("  gap", self.gap)
        f.addRow(self.result)
        self.rows = {w_: f.labelForField(w_) for w_ in (self.other, self.face, self.gap)}
        self.rows[self.pick] = None
        self.busy = False
        self.kind.currentIndexChanged.connect(self._edit)
        self.other.currentIndexChanged.connect(self._edit)
        self.face.currentIndexChanged.connect(self._edit)
        self.gap.editingFinished.connect(self._edit)

    def _show(self):
        k = self.kind.currentData()
        for w_, v in ((self.other, k in ("butt", "miter", "conform")), (self.face, k in ("butt", "conform")), (self.pick, k in ("butt", "conform")), (self.gap, k in ("butt", "conform"))):
            w_.setVisible(v)
            if self.rows[w_] is not None:
                self.rows[w_].setVisible(v)

    def _edit(self, *a):
        self._show()
        if not self.busy:
            self.changed.emit()

    def load(self, joint, others, resolved_text):
        """joint: the stored joint dict; others: [(member id, name)] the other members; resolved_text: what 'automatic' came to, and the cut."""
        self.busy = True
        try:
            j = joint or {"kind": "auto"}
            self.kind.setCurrentIndex(max(0, self.kind.findData(j["kind"])))
            self.other.clear()
            for mid, name in others:
                self.other.addItem(name, mid)
            self.other.setCurrentIndex(max(0, self.other.findData(j.get("to") or j.get("with"))))
            self.gap.setText(disp(j.get("gap", "0")))
            self.face.setCurrentIndex(max(0, self.face.findData(j.get("face") or "auto")))
            self.result.setText(resolved_text)
            self._show()
        finally:
            self.busy = False

    def value(self):
        k = self.kind.currentData()
        o = self.other.currentData()
        if k in ("butt", "miter", "conform") and o is None:
            return {"kind": "auto"}
        if k in ("butt", "conform"):
            f_ = self.face.currentData()
            return {"kind": k, "to": o, "face": None if f_ == "auto" else f_, "gap": store(self.gap.text()) or "0"}
        if k == "miter":
            return {"kind": "miter", "with": o}
        return {"kind": k}


class TrussTab(QWidget):
    KIND = "truss"

    def __init__(self, host=None, path=None):
        super().__init__()
        self.host = host
        self.path = None
        self.p = tc.new_project("Truss")
        self.src = None
        self.config = None
        self.dirty = False
        self.sel_line = None
        self.sel_member = None
        self.built = None
        self.busy = False
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_import = QPushButton("Import sketch…")
        self.btn_import.setToolTip("Take the sketch (and its configurations) from an open Sketch/Part tab or from a part file. A copy is saved in this project's folder as sketch.gpd; that copy is the sketch from then on.")
        self.btn_import.clicked.connect(self.import_menu)
        self.btn_open = QPushButton("Open project…")
        self.btn_open.setToolTip("Open a project folder (File > Open Project Folder)")
        self.btn_open.clicked.connect(lambda: getattr(self.host, "open_project_folder_dialog", lambda: None)())
        self.btn_edit = QPushButton("Open sketch for editing")
        self.btn_edit.setToolTip("Open this project's own sketch.gpd in a Sketch/Part tab: add lines or configurations there, save it, then press Refresh from sketch.")
        self.btn_edit.clicked.connect(self.open_sketch_for_editing)
        self.btn_refresh = QPushButton("Refresh from sketch")
        self.btn_refresh.setToolTip("Read the project's sketch.gpd again after you saved it. Members, joints and profiles stay; new configurations are built.")
        self.btn_refresh.clicked.connect(self.refresh_from_sketch)
        self.lbl_sketch = QLabel("No sketch yet")
        self.cfg = QComboBox()
        self.cfg.setToolTip("The sketch configuration that is built. Members of each configuration have their own names.")
        self.cfg.currentIndexChanged.connect(self.config_changed)
        self.name_edit = QLineEdit(self.p["name"])
        self.name_edit.setMaximumWidth(180)
        self.name_edit.editingFinished.connect(self.rename_project)
        self.btn_export = QPushButton("Export assembly…")
        self.btn_export.setToolTip("Writes ONE configurable assembly file (every sketch configuration in it), the part files, one cut list, and STEP / STL per configuration")
        self.btn_export.clicked.connect(lambda _=False: self.export_dialog())
        for w_ in (QLabel("Project"), self.name_edit, self.btn_open, self.btn_import, self.btn_edit, self.btn_refresh, self.lbl_sketch, QLabel("Configuration"), self.cfg):
            bar.addWidget(w_)
        bar.addStretch(1)
        bar.addWidget(self.btn_export)
        root.addLayout(bar)
        self.pages = QTabWidget()
        root.addWidget(self.pages, 1)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        root.addWidget(self.msg)

        # Members page
        mp = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        self.canvas = SketchCanvas()
        self.canvas.picked.connect(self.line_picked)
        self.canvas.toggled.connect(self.line_toggled)
        ll.addWidget(QLabel("Sketch: click a line, double-click to make it a member.  Green dot = start of the line, arrow = its end."))
        ll.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        b = QPushButton("Add member from line")
        b.clicked.connect(lambda: self.line_toggled(self.sel_line, add_only=True))
        row.addWidget(b)
        b = QPushButton("Remove member")
        b.clicked.connect(self.remove_member)
        row.addWidget(b)
        ll.addLayout(row)
        self.mlist = QListWidget()
        self.mlist.setMaximumHeight(110)
        self.mlist.currentRowChanged.connect(self.member_row)
        ll.addWidget(self.mlist)
        mp.addWidget(left)
        mid = QWidget()
        ml = QVBoxLayout(mid)
        self.mname = QLineEdit()
        self.mname.editingFinished.connect(self.member_edited)
        self.mref = QComboBox()
        self.mref.addItem("the centreline of the member", "center")
        self.mref.addItem("its left face (looking start to end)", "left")
        self.mref.addItem("its right face (looking start to end)", "right")
        self.mref.setToolTip("What the sketch line stands for. The member's body is placed from it.")
        self.mref.currentIndexChanged.connect(self.member_edited)
        self.moff = QLineEdit("0")
        self.moff.setToolTip(f"Move the member across its line, {unitctl.length_unit()} (positive = to the left)")
        self.moff.editingFinished.connect(self.member_edited)
        self.mroll = QLineEdit("0")
        self.mroll.setToolTip("Turn the profile about the member's axis, degrees")
        self.mroll.editingFinished.connect(self.member_edited)
        self.stock = QLabel("")
        self.stock.setWordWrap(True)
        f = QFormLayout()
        f.addRow("Member", self.mname)
        f.addRow("The sketch line is", self.mref)
        f.addRow("  offset", self.moff)
        f.addRow("Turn profile", self.mroll)
        ml.addLayout(f)
        ml.addWidget(self.stock)
        self.own_prof = QCheckBox("This member has its own profile")
        self.own_prof.toggled.connect(self.profile_mode)
        ml.addWidget(self.own_prof)
        self.prof = ProfileEditor("Profile (the project's default unless this member has its own)")
        self.prof.changed.connect(self.profile_edited)
        ml.addWidget(self.prof)
        self.end_ed = {"start": EndEditor("Start end (where the line starts)"), "end": EndEditor("End (where the line ends)")}
        for e_, w_ in self.end_ed.items():
            w_.changed.connect(lambda e_=e_: self.end_edited(e_))
            w_.pick_requested.connect(lambda e_=e_: self.start_pick(e_))
            ml.addWidget(w_)
        ml.addStretch(1)
        mp.addWidget(mid)
        vbox = QWidget()
        vl = QVBoxLayout(vbox)
        vl.setContentsMargins(0, 0, 0, 0)
        self.only_sel = QCheckBox("Show only the selected member")
        self.only_sel.setToolTip("Off: the whole truss is shown, the selected member highlighted")
        self.only_sel.toggled.connect(lambda *_: self.refresh_preview())
        self.show_lines = QCheckBox("Show sketch lines (dotted; green = start, red = end)")
        self.show_lines.setChecked(True)
        self.show_lines.setToolTip("Where each member's sketch line is: its centreline or one of its faces")
        self.show_lines.toggled.connect(lambda *_: self.refresh_preview())
        vl.addWidget(self.only_sel)
        vl.addWidget(self.show_lines)
        self.view_m = View3D()
        vl.addWidget(self.view_m, 1)
        mp.addWidget(vbox)
        mp.setSizes([360, 380, 420])
        self.pages.addTab(mp, "Members")

        # Assembly page
        ap = QSplitter(Qt.Orientation.Horizontal)
        al = QWidget()
        av = QVBoxLayout(al)
        av.addWidget(QLabel("Members of this configuration. The part name is the file name of an export; the offsets move a member off its sketch position."))
        self.table = QTableWidget(0, 7)
        self.set_headers()
        self.table.itemChanged.connect(self.table_edited)
        av.addWidget(self.table, 1)
        self.cutlist = QLabel("")
        self.cutlist.setWordWrap(True)
        av.addWidget(self.cutlist)
        row = QHBoxLayout()
        b = QPushButton("Rebuild")
        b.clicked.connect(self.rebuild)
        row.addWidget(b)
        b = QPushButton("Export assembly…")
        b.setToolTip("Writes ONE configurable assembly file (every sketch configuration in it), the part files, one cut list, and STEP / STL per configuration")
        b.clicked.connect(lambda _=False: self.export_dialog())
        row.addWidget(b)
        av.addLayout(row)
        ap.addWidget(al)
        self.view_a = View3D()
        ap.addWidget(self.view_a)
        ap.setSizes([520, 560])
        self.pages.addTab(ap, "Assembly")
        self.pages.currentChanged.connect(lambda i: self.refresh_assembly() if i == 1 else None)
        unitctl.on_change(self.units_changed)
        self.destroyed.connect(lambda *a: unitctl.off_change(self.units_changed))
        if path:
            self.open_path(path)
        self.refresh_all()

    # ------------------------------------------------------------------ the file
    def is_dirty(self):
        return self.dirty

    def say(self, text):
        self.msg.setText(text)

    def touch(self):
        self.dirty = True

    def rename_project(self):
        t = self.name_edit.text().strip()
        if t and t != self.p["name"]:
            self.p["name"] = t
            self.p["names"] = {}                            # part names follow the project name until they are edited
            self.touch()
            self.refresh_all()

    def save(self, as_new=False):
        path = self.path
        if as_new or not path:
            start = (self.path or self.p["name"] + ".truss")
            path, _ = QFileDialog.getSaveFileName(self, "Save truss project (a folder)", start, "Truss project (*.truss)")
            if not path:
                return False
            if not path.lower().endswith(".truss"):
                path += ".truss"
        tc.save(self.p, path)                                   # project.json and sketch.gpd (the one copy of the sketch)
        self.path = path
        self.dirty = False
        return True

    def open_path(self, path):
        folder = os.path.dirname(path) if path.lower().endswith("project.json") else path
        self.p = tc.load(folder)
        self.path = folder
        self.name_edit.setText(self.p["name"])
        self.src = None
        self.load_source()
        self.dirty = False

    # ------------------------------------------------------------------ the sketch
    def import_menu(self):
        choices = []
        tabs = getattr(getattr(self.host, "tabs", None), "count", lambda: 0)()
        for i in range(tabs):
            w = self.host.tabs.widget(i)
            if getattr(w, "kind", "") == "sketch" and hasattr(w, "doc") and any(f["kind"] == "sketch" for f in w.doc.features):
                choices.append((self.host.tabs.tabText(i), w))
        items = [f"Tab: {t}" for t, _ in choices] + ["A part file (.gpd)…"]
        pick, ok = QInputDialog.getItem(self, "Import sketch", "Take the sketch from", items, 0, False)
        if not ok:
            return
        if pick.startswith("Tab: "):
            w = dict((f"Tab: {t}", w) for t, w in choices)[pick]
            self.import_doc(w.doc.to_json())
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Part with the sketch", "", "Part (*.gpd)")
            if path:
                with open(path, encoding="utf-8") as f:
                    self.import_doc(f.read())

    def import_doc(self, text):
        import pm_model as pm
        d = pm.Document.from_json(text)
        sk = [f for f in d.features if f["kind"] == "sketch"]
        if not sk:
            return QMessageBox.information(self, "Import", "That part has no sketch.")
        old = (self.p.get("sketch") or {}).get("sid")
        if old and any(f["id"] == old for f in sk):
            sid = old
        elif len(sk) == 1:
            sid = sk[0]["id"]
        else:
            names = [f["name"] for f in sk]
            nm, ok = QInputDialog.getItem(self, "Import sketch", "Which sketch?", names, 0, False)
            if not ok:
                return
            sid = sk[names.index(nm)]["id"]
        self.p["sketch"] = {"doc": text, "sid": sid, "name": d.feature(sid)["name"]}
        if self.path:                                           # the copy in the project folder is the sketch from now on
            tc.save(self.p, self.path)
        self.touch()
        self.load_source()
        self.refresh_all()

    def open_sketch_for_editing(self):
        if not self.p.get("sketch"):
            return QMessageBox.information(self, "Sketch", "Import a sketch first.")
        if not self.path and not self.save():
            return
        tc.save(self.p, self.path)
        f = os.path.join(self.path, tc.SKETCH_FILE)
        if hasattr(self.host, "open_path") and self.host.open_path(f) is not None:
            self.say("The project's sketch is open. Edit it, save it (Ctrl+S), then come back and press Refresh from sketch.")
        else:
            self.say(f"Open {f} in OpenPara, edit and save it, then press Refresh from sketch.")

    def refresh_from_sketch(self):
        if not self.path or not self.p.get("sketch"):
            return QMessageBox.information(self, "Sketch", "Save the project first: its sketch lives in the project folder.")
        try:
            i = self.host.find_tab(os.path.join(self.path, tc.SKETCH_FILE)) if hasattr(self.host, "find_tab") else None
            w = self.host.tabs.widget(i) if i is not None else None
            if w is not None and hasattr(w, "doc") and getattr(w, "saved_json", None) not in (None, w.doc.to_json()):
                return self.say("The sketch tab has changes that are not saved. Save it (Ctrl+S) and press Refresh from sketch again.")
        except Exception:
            pass
        try:
            rep = tc.reload_sketch(self.p, self.path)
        except Exception as ex:
            return self.say(f"The sketch could not be read: {ex}")
        self.load_source()
        self.refresh_all()
        bits = []
        if rep["new_configs"]:
            bits.append("new configurations: " + ", ".join(rep["new_configs"]))
        if rep["gone_configs"]:
            bits.append("configurations no longer in the sketch: " + ", ".join(rep["gone_configs"]))
        if rep["missing_lines"]:
            bits.append("members whose sketch line is gone (they stay in the list and show red): " + ", ".join(rep["missing_lines"]))
        self.say("Sketch refreshed" + (" — " + "; ".join(bits) if bits else " — nothing changed in its lines or configurations.") + " Export adds them to the parts and the assembly.")

    def load_source(self):
        s = self.p.get("sketch")
        self.src = None
        if s and s.get("doc"):
            try:
                self.src = tc.SketchSource(s["doc"], s["sid"])
            except Exception as ex:
                self.say(f"The sketch could not be read: {ex}")
        self.busy = True
        self.cfg.clear()
        if self.src:
            for c in self.src.configs():
                self.cfg.addItem(c)
            i = self.cfg.findText(self.config or self.src.active())
            self.cfg.setCurrentIndex(max(0, i))
            self.config = self.cfg.currentText()
        self.busy = False
        self.lbl_sketch.setText(f"Sketch: {s['name']}" if s else "No sketch yet")

    def config_changed(self, *a):
        if self.busy or not self.src:
            return
        self.config = self.cfg.currentText()
        self.refresh_all()

    # ------------------------------------------------------------------ building
    def lines(self):
        try:
            return self.src.lines(self.config) if self.src else {}
        except Exception as ex:
            self.say(f"Sketch: {ex}")
            return {}

    def rebuild(self):
        self.built = tc.Built(self.p, self.src, self.config) if self.src and self.config else None
        if self.built and self.built.errors:
            names = {m["id"]: m["name"] for m in self.p["members"]}
            self.say("; ".join(f"{names.get(k, k)}: {v}" for k, v in self.built.errors.items()))
        else:
            self.say("")
        m = self.current_member()
        if m:
            was, self.busy = self.busy, True
            try:
                self.show_joints(m)
            finally:
                self.busy = was
        self.mark_errors()
        self.refresh_preview()
        if self.pages.currentIndex() == 1:
            self.refresh_assembly()

    def refresh_all(self):
        mem = {m["line"]: m for m in self.p["members"]}
        L = self.lines()
        self.canvas.set_data(L, mem, self.sel_line)
        self.busy = True
        self.mlist.clear()
        for m in self.p["members"]:
            self.mlist.addItem(QListWidgetItem(m["name"]))
            if m["id"] == self.sel_member:
                self.mlist.setCurrentRow(self.mlist.count() - 1)
        self.busy = False
        self.load_member()
        self.rebuild()

    def mark_errors(self):
        """Members that could not be built are red in the list (and left out of the view)."""
        from PyQt6.QtGui import QBrush
        bad = self.built.errors if self.built else {}
        for i, m in enumerate(self.p["members"]):
            it = self.mlist.item(i)
            if it is not None:
                warn = self.built.warnings.get(m["id"], "") if self.built else ""
                it.setForeground(QBrush(QColor("#c92a2a")) if m["id"] in bad else QBrush(QColor("#d9480f")) if warn else QBrush())
                it.setToolTip(bad.get(m["id"], "") or warn)

    def current_member(self):
        return tc.member(self.p, self.sel_member) if self.sel_member else None

    SELECTED, OTHERS = (0.20, 0.45, 0.90), (0.74, 0.78, 0.86)

    def refresh_preview(self):
        """The whole truss of this configuration, each member placed from the sketch; the selected one is highlighted."""
        b = self.built
        if not b or not b.members:
            self.view_m.show_shapes([])
            self._fitkey = None
            return
        sel = self.sel_member
        only = self.only_sel.isChecked() and sel in b.members
        items = []
        for mid in b.members:
            if only and mid != sel:
                continue
            try:
                items.append((b.placed(mid), self.SELECTED if mid == sel or only else self.OTHERS, 1.0))
            except Exception:
                pass
        key = (self.config, tuple(b.members), only, sel if only else None)
        self.view_m.show_shapes(items, fit=key != getattr(self, "_fitkey", None), overlays=self.sketch_overlays(only) + self.joint_overlays(only))          # the camera stays where you put it while you edit
        self._fitkey = key

    def sketch_overlays(self, only=False):
        """Dotted lines on the members where their sketch lines are, with a green dot at each start and a red dot at each end."""
        out = []
        if not self.show_lines.isChecked() or not self.built:
            return out
        for mid, mb in self.built.members.items():
            if only and mid != self.sel_member:
                continue
            g = mb.g
            z = g.hz / 2 + 0.5
            p0, p1 = g.line["p0"], g.line["p1"]
            d = max(g.line["length"] / 70.0, 8.0)
            r = max(g.hy * 0.14, 3.0)
            out.append({"kind": "dash", "p0": (p0[0], p0[1], z), "p1": (p1[0], p1[1], z), "dash": d, "gap": d * 0.7, "color": (0.80, 0.10, 0.10)})
            out.append({"kind": "dot", "pt": (p0[0], p0[1], z), "r": r, "color": (0.18, 0.62, 0.27)})
            out.append({"kind": "dot", "pt": (p1[0], p1[1], z), "r": r, "color": (0.80, 0.10, 0.10)})
        return out

    def joint_overlays(self, only=False):
        """The faces the selected member's Butt / Conform joints sit on, drawn on the members: orange when they work, red when the joint could not be built."""
        out = []
        if only or not self.built or not self.sel_member:
            return out
        try:
            for shape, ok in self.built.joint_highlights(self.sel_member):
                out.append({"kind": "face", "shape": shape, "color": (1.0, 0.55, 0.0) if ok else (0.85, 0.10, 0.10)})
        except Exception:
            pass
        return out

    def start_pick(self, end):
        """The next click on a face in the 3D view sets the butt joint at this end of the selected member."""
        m = self.current_member()
        if not m:
            return
        if self.only_sel.isChecked():
            self.only_sel.setChecked(False)                      # the face to pick may be on another member
        self.pick_end = end
        if self.view_m.enable_pick(self.picked_point):
            self.say(f"Click the face this {end} end sits on, in the 3D view; it will be highlighted.")
        else:
            self.say("The 3D view cannot pick here. Choose the member and the face in the joint box.")

    def picked_point(self, pt):
        self.view_m.disable_pick()
        m, end = self.current_member(), getattr(self, "pick_end", None)
        if not m or end is None or not self.built:
            return
        self.pick_end = None
        hit = self.built.hit_detail(pt)
        if hit is None:
            return self.say("No member under that click. Press Pick the face again and click a member.")
        mid, face = hit["mid"], hit["face"]
        if mid == m["id"]:
            return self.say("That is this member itself. Click a face of another member.")
        target = tc.member(self.p, mid)
        old = m["ends"].get(end) or {}
        kind = old.get("kind") if old.get("kind") in ("butt", "conform") else ("conform" if tc.member_curved(target, self.p) else "butt")
        m["ends"][end] = {"kind": kind, "to": mid, "face": face, "gap": old.get("gap", "0") if old.get("kind") in ("butt", "conform") else "0"}
        self.touch()
        self.refresh_all()
        names = {x["id"]: x["name"] for x in self.p["members"]}
        label = "Butt Connect" if kind == "butt" else "Conform Connect"
        msg = f"The {end} end is a {label} to the {face} face of {names.get(mid, mid)} (highlighted)."
        if hit["curved"] and kind == "butt":
            msg += " You clicked a rounded part, and a Butt Connect is flat: it uses the flat side. Choose Conform Connect to wrap the curve."
        err = self.built.errors.get(m["id"]) if self.built else None
        if err:
            msg = f"That face does not work: {err} (shown in red)"
        self.say(msg)

    def refresh_assembly(self):
        self.busy = True
        self.table.setRowCount(0)
        b = self.built
        place = self.p["place"].get(self.config, {}) if self.config else {}
        for m in self.p["members"]:
            r = self.table.rowCount()
            self.table.insertRow(r)
            mb = b.members.get(m["id"]) if b else None
            name = (b.names.get(m["id"]) if b else "") or m["name"]
            pl = place.get(m["id"], {})
            vals = [m["name"], name, udisp(mb.length) if mb else "—", udisp(pl.get("dx", 0)), udisp(pl.get("dy", 0)), udisp(pl.get("dz", 0)), pl.get("rot", 0)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setData(Qt.ItemDataRole.UserRole, m["id"])
                if c in (0, 2):
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, it)
        self.busy = False
        if b:
            rows = b.cut_list()
            self.cutlist.setText("Cut list: " + "   |   ".join(
                f"{r['member']}: {unitctl.length_text(r['length'], 6)}, start {r['start_text']}, end {r['end_text']}"
                for r in rows))
            items = []
            palette = [(0.45, 0.55, 0.75), (0.8, 0.5, 0.3), (0.45, 0.7, 0.5), (0.7, 0.45, 0.65), (0.6, 0.6, 0.35)]
            for i, mid in enumerate(b.members):
                try:
                    items.append((b.placed(mid), palette[i % len(palette)], 1.0))
                except Exception:
                    pass
            akey = (self.config, tuple(b.members))
            self.view_a.show_shapes(items, fit=akey != getattr(self, "_afitkey", None))      # the camera stays where you put it while you edit
            self._afitkey = akey
        else:
            self.cutlist.setText("")
            self.view_a.show_shapes([])
            self._afitkey = None

    def set_headers(self):
        u = unitctl.length_unit()
        self.table.setHorizontalHeaderLabels(["Member", "Part name", f"Length ({u})", f"dx ({u})", f"dy ({u})", f"dz ({u})", "turn (deg)"])

    def units_changed(self, *a):
        """File > Units was flipped: what is shown is converted, what is stored (mm) is not."""
        try:
            self.set_headers()
            self.load_member()
            self.refresh_assembly()
        except RuntimeError:                                  # the window is already gone
            pass

    def table_edited(self, it):
        if self.busy:
            return
        mid, c = it.data(Qt.ItemDataRole.UserRole), it.column()
        if c == 1:
            self.p["names"].setdefault(self.config, {})[mid] = it.text().strip() or tc._clean(it.text())
        elif c >= 3:
            try:
                v = float(it.text()) if c == 6 else unitctl.read_length(it.text())
            except ValueError:
                v = 0.0
            self.p["place"].setdefault(self.config, {}).setdefault(mid, {})[("dx", "dy", "dz", "rot")[c - 3]] = v
        self.touch()
        if c >= 3:
            self.rebuild()

    # ------------------------------------------------------------------ members
    def line_picked(self, lid):
        self.sel_line = lid
        mem = next((m for m in self.p["members"] if m["line"] == lid), None)
        if mem:
            self.sel_member = mem["id"]
        self.refresh_all()

    def line_toggled(self, lid, add_only=False):
        if lid is None:
            return
        mem = next((m for m in self.p["members"] if m["line"] == lid), None)
        if mem and not add_only:
            self.sel_member = mem["id"]
        elif not mem:
            mem = tc.add_member(self.p, lid)
            self.sel_member = mem["id"]
            self.touch()
        self.sel_line = lid
        self.refresh_all()

    def remove_member(self):
        m = self.current_member()
        if m:
            tc.remove_member(self.p, m["id"])
            self.sel_member = None
            self.touch()
            self.refresh_all()

    def member_row(self, row):
        if self.busy or row < 0 or row >= len(self.p["members"]):
            return
        m = self.p["members"][row]
        self.sel_member, self.sel_line = m["id"], m["line"]
        self.canvas.set_data(self.lines(), {x["line"]: x for x in self.p["members"]}, self.sel_line)
        self.load_member()
        self.refresh_preview()

    def load_member(self):
        m = self.current_member()
        self.busy = True
        try:
            for w_ in (self.mname, self.mref, self.moff, self.mroll, self.own_prof, self.prof, *self.end_ed.values()):
                w_.setEnabled(m is not None)
            if not m:
                self.mname.setText("")
                self.stock.setText("")
                for w_ in self.end_ed.values():
                    w_.load(None, [], "")
                return
            self.mname.setText(m["name"])
            self.mref.setCurrentIndex(max(0, self.mref.findData(m.get("ref", "center"))))
            self.moff.setText(disp(m.get("offset", "0")))
            self.mroll.setText(str(m.get("roll", 0)))
            own = m.get("profile") is not None
            self.own_prof.setChecked(own)
            self.prof.load(m["profile"] if own else self.p["profile"])
            self.show_joints(m)
        finally:
            self.busy = False

    def joint_text(self, mid, end):
        """What this end came to in the current configuration: the joint, the angle of the cut."""
        b = self.built
        r = (b.resolved.get(mid) or {}).get(end) if b else None
        if not r:
            return ""
        names = {x["id"]: x["name"] for x in self.p["members"]}
        mb = b.members.get(mid)
        info = mb.info[end] if mb else {}
        tgt = names.get(r.get("to") or r.get("with"), "?")
        what = {"free": "No Cut (a square end)",
                "butt": f"Butt Connect to the {info.get('face') or 'nearest'} face of {tgt} (flat cut)",
                "conform": f"Conform Connect to the {info.get('face') or 'nearest'} face of {tgt} (shaped to fit)",
                "miter": f"Miter Connect with {tgt}"}[r["kind"]]
        extra = f", cut at {info['angle']}° from the end face" if info.get("angle") and r["kind"] in ("butt", "miter") else ""
        warn = b.warnings.get(mid) if b else None
        return ("Automatic: " if r.get("auto") else "") + what + extra + (f"\nWarning: {warn}" if warn else "")

    def show_joints(self, m):
        others = [(x["id"], x["name"]) for x in self.p["members"] if x["id"] != m["id"]]
        for e_, w_ in self.end_ed.items():
            w_.load(m["ends"].get(e_), others, self.joint_text(m["id"], e_))
        mb = self.built.members.get(m["id"]) if self.built else None
        self.stock.setText(f"Stock length (the longest extrusion): {unitctl.length_text(mb.length, 6)}" if mb else
                           (self.built.errors.get(m["id"], "") if self.built else ""))

    def member_edited(self):
        m = self.current_member()
        if not m or self.busy:
            return
        m["name"] = self.mname.text().strip() or m["name"]
        m["ref"] = self.mref.currentData()
        m["offset"] = store(self.moff.text()) or "0"
        try:
            m["roll"] = float(self.mroll.text() or 0)
        except ValueError:
            m["roll"] = 0.0
        self.touch()
        self.refresh_all()

    def end_edited(self, end):
        m = self.current_member()
        if not m or self.busy:
            return
        j = self.end_ed[end].value()
        m["ends"][end] = j
        other = j.get("with")
        if j["kind"] == "miter" and other:                  # a miter is a pair: the other member's end that meets this one miters back
            om = tc.member(self.p, other)
            if om and self.built:
                for oe in ("start", "end"):
                    r = (self.built.resolved.get(other) or {}).get(oe) or {}
                    if r.get("kind") in ("miter", "butt", "conform", "free") and r.get("auto") and (r.get("with") == m["id"] or r.get("to") == m["id"]):
                        om["ends"][oe] = {"kind": "miter", "with": m["id"]}
        self.touch()
        self.refresh_all()

    def profile_mode(self, on):
        m = self.current_member()
        if not m or self.busy:
            return
        m["profile"] = tc.json.loads(tc.json.dumps(self.prof.value())) if on else None
        self.touch()
        self.load_member()
        self.rebuild()

    def profile_edited(self):
        if self.busy:
            return
        m = self.current_member()
        if not m:
            return
        if m.get("profile") is not None:
            m["profile"] = self.prof.value()
        else:
            self.p["profile"] = self.prof.value()                # editing without "own profile" changes the project's default
        self.touch()
        self.rebuild()

    # ------------------------------------------------------------------ export
    def export_dialog(self):
        if not self.src or not self.p["members"]:
            return QMessageBox.information(self, "Export", "Import a sketch and make at least one member first.")
        if not self.path and not self.save():
            return
        tc.save(self.p, self.path)
        out, written, errs = tc.export(self.p, self.src, self.path, unit=(unitctl.length_unit(), unitctl.mm_per_unit()))
        self.dirty = False
        cfgs = self.src.configs()
        asm = next((w for w in written if w.endswith(".gpa")), None)
        parts = [w for w in written if w.endswith(".gpd")]
        self.say(f"Exported to {out}:  {asm or 'no assembly'} (ONE assembly with the configuration{'s' if len(cfgs) != 1 else ''} {', '.join(cfgs)}; "
                 f"use it as a sub-assembly and choose the configuration in the bigger assembly), {len(parts)} part file{'s' if len(parts) != 1 else ''}, "
                 f"cut_list.csv, and STEP / STL per configuration." + (f"  Problems: {errs}" if errs else ""))
        if asm and hasattr(self.cutlist, "setText"):
            self.last_export = os.path.join(out, asm)


def make_tab(host=None, path=None):
    p = path if path and (path.lower().endswith(".truss") or path.lower().endswith("project.json") or os.path.isfile(os.path.join(path, "project.json"))) else None
    return TrussTab(host, p)
