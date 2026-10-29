"""
Physics Calc tab for the sketcher:  import a copy of a sketch, mesh it, apply supports and loads, solve (2D linear FEA).

  Left   : import, material, mesh, supports / loads, results, diagnostics
  Right  : the drawing - click to select (Ctrl-click adds), wheel = zoom, middle-drag = pan

Needs numpy, scipy and gmsh:   pip install numpy scipy gmsh
"""
import math
import platform
import sys
import time
import traceback

import numpy as np
from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
                             QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QAbstractItemView,
                             QTextEdit, QVBoxLayout, QWidget)

import physics_cfd as pcfd
import physics_fea as pf
import physics_geom as pg
import physics_materials as pm
import physics_refine as prefine
import units
import physics_solve as psolve
import physics_store as pstore
import section_props as secp
import sketcher_core as sc
from sketch_pick import SketchPicker
import sketcher_script as scr

KIND_NAME = {"pt": "Point", "ln": "Line", "ar": "Arc", "ci": "Circle"}


def dependency_status():
    """{package: (version or None, problem text)}"""
    out = {}
    for name in ("numpy", "scipy", "gmsh"):
        try:
            mod = __import__(name)
            out[name] = (getattr(mod, "__version__", "?"), "")
        except Exception as ex:                                  # ImportError, or a missing system library
            out[name] = (None, f"{type(ex).__name__}: {ex}")
    return out


# ----------------------------------------------------------------------------------------------
# background tasks with a progress bar
# ----------------------------------------------------------------------------------------------
class TaskWorker(QThread):
    progress = pyqtSignal(str, int)
    finished_ok = pyqtSignal(object)
    cancelled = pyqtSignal()
    failed = pyqtSignal(str, bool)          # text, True when it is a message for the user (not a program error)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.stop = False

    def run(self):
        try:
            res = self.fn(lambda text, f: self.progress.emit(text, int(max(0.0, min(1.0, f)) * 1000)), lambda: self.stop)
            self.finished_ok.emit(res)
        except (pg.Cancelled, pf.Cancelled):
            self.cancelled.emit()
        except (pg.GeometryError, pf.ModelError) as ex:
            self.failed.emit(str(ex), True)
        except Exception:
            self.failed.emit(traceback.format_exc(), False)


class TaskDialog(QDialog):
    def __init__(self, parent, title, fn):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        self.lbl = QLabel("Starting...")
        lay.addWidget(self.lbl)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        lay.addWidget(self.bar)
        self.btn = QPushButton("Cancel")
        self.btn.clicked.connect(self.cancel)
        lay.addWidget(self.btn)
        self.outcome = None
        self.worker = TaskWorker(fn)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(lambda r: self.end(("ok", r)))
        self.worker.cancelled.connect(lambda: self.end(("cancelled", None)))
        self.worker.failed.connect(lambda t, user: self.end(("user" if user else "bug", t)))

    def on_progress(self, text, v):
        self.lbl.setText(text)
        self.bar.setValue(v)

    def cancel(self):
        self.worker.stop = True
        self.btn.setEnabled(False)
        self.lbl.setText("Cancelling (a running solve step finishes first)...")

    def reject(self):
        self.cancel()

    def end(self, outcome):
        self.outcome = outcome
        self.worker.wait()
        self.accept()

    def run(self):
        self.worker.start()
        self.exec()
        return self.outcome


def _flat(g):
    """All the numbers of an edge description (for a size estimate)."""
    out = []
    for v in g.values():
        if isinstance(v, (tuple, list)):
            out += [float(x) for x in v]
        elif isinstance(v, (int, float)):
            out.append(float(v))
    return out


def polyline_length(pts, closed):
    P = list(pts) + ([pts[0]] if closed else [])
    return sum(math.hypot(P[i + 1][0] - P[i][0], P[i + 1][1] - P[i][1]) for i in range(len(P) - 1))


def points_along(pts, closed, count):
    """`count` points evenly spaced by arc length along a polyline -> [(x, y, tx, ty)] with (tx, ty) the unit tangent."""
    P = list(pts) + ([pts[0]] if closed else [])
    seg = [math.hypot(P[i + 1][0] - P[i][0], P[i + 1][1] - P[i][1]) for i in range(len(P) - 1)]
    total = sum(seg)
    if total <= 0 or count < 1:
        return []
    out = []
    cum, i = 0.0, 0
    for k in range(count):
        target = (k + 0.5) / count * total
        while i < len(seg) - 1 and cum + seg[i] < target:
            cum += seg[i]
            i += 1
        if seg[i] <= 0:
            continue
        f = (target - cum) / seg[i]
        out.append((P[i][0] + f * (P[i + 1][0] - P[i][0]), P[i][1] + f * (P[i + 1][1] - P[i][1]),
                    (P[i + 1][0] - P[i][0]) / seg[i], (P[i + 1][1] - P[i][1]) / seg[i]))
    return out


def ask_numbers(parent, title, labels, defaults):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    form = QFormLayout(dlg)
    edits = []
    for lab, d in zip(labels, defaults):
        e = QLineEdit(str(d))
        form.addRow(lab, e)
        edits.append(e)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    form.addRow(bb)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    try:
        return [float(e.text().strip()) for e in edits]
    except ValueError:
        QMessageBox.warning(parent, title, "Please enter plain numbers (for example 2.5 or 1e6).")
        return None


# ----------------------------------------------------------------------------------------------
# colours
# ----------------------------------------------------------------------------------------------
import result_style


def colours(t):
    """0..1 -> RGB ints: the colour scheme shared by all result pictures (result_style.py)."""
    return result_style.colours(t)


# the first six are the standard results, named and ordered the same in the 1D FEA tab
FIELDS = [("Displacement magnitude", "umag", "nodal"), ("Displacement X", "ux", "nodal"), ("Displacement Y", "uy", "nodal"),
          ("von Mises stress", "vm", "elem"), ("Normal stress X", "sx", "elem"), ("Normal stress Y", "sy", "elem"),
          ("Shear stress XY", "txy", "elem"), ("Principal stress 1", "s1", "elem"), ("Principal stress 2", "s2", "elem"),
          ("Maximum shear", "tmax", "elem"), ("Equivalent plastic strain", "peeq", "elem")]


def field_values(result, key):
    if key == "umag":
        return np.hypot(result["u"][:, 0], result["u"][:, 1])
    if key == "ux":
        return result["u"][:, 0]
    if key == "uy":
        return result["u"][:, 1]
    if key == "peeq" and key not in result:
        return np.zeros_like(result["vm"])
    return result[key]


# ----------------------------------------------------------------------------------------------
# the drawing
# ----------------------------------------------------------------------------------------------
class PhysCanvas(QWidget):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(420, 320)
        self.scale = 8.0
        self.org = QPointF(60, 400)
        self.sel = []
        self.pan_from = None
        self.pan_off = QPointF(0, 0)
        self.hl_face = None
        self.field = None                 # key of the field shown, or None
        self.show_mesh = True
        self.show_deformed = True
        self.def_scale = 1.0
        self._cache = None
        self._cache_key = None
        self.anim_frames = None           # list of pre-rendered pictures (ramp 0 -> full), or None
        self.anim_idx = 0
        self.box = None                   # rubber-band selection: [start QPointF, current QPointF, additive]
        self.mode = "select"              # "select", "rect" / "circle" (drawing a probe region) or "node" (node probe)
        self.drag = None                  # probe region being drawn: [start (x, y), current (x, y)] in sketch units
        self.node_sel = None              # the node picked with the node probe

    # --- transforms
    def w2s(self, x, y):
        return QPointF(self.org.x() + x * self.scale, self.org.y() - y * self.scale)

    def s2w(self, sp):
        return (sp.x() - self.org.x()) / self.scale, (self.org.y() - sp.y()) / self.scale

    def fit(self):
        tab = self.tab
        if tab.geom is None:
            return
        xs, ys = [], []
        for pts in tab.geom["polys"]:
            xs += [p[0] for p in pts]
            ys += [p[1] for p in pts]
        if not xs:
            return
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        W, H = max(self.width(), 200), max(self.height(), 200)
        self.scale = 0.8 * min(W / max(w, 1e-9), H / max(h, 1e-9))
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        self.org = QPointF(W / 2 - cx * self.scale, H / 2 + cy * self.scale)
        self.invalidate()

    def invalidate(self):
        self._cache_key = None
        if self.anim_frames is not None:                  # the pictures no longer match the view
            self.anim_frames = None
            self.tab.anim_dropped()
        self.update()

    # --- interaction
    def hit(self, sp):
        tab = self.tab
        if tab.geom is None:
            return None
        m = tab.model
        best = None
        pids = set()
        for e in tab.geom["edges"]:
            if e["kind"] == "ci":
                pids.add(e["c"])
            else:
                pids |= {e["a"], e["b"]}
                if e["kind"] == "ar":
                    pids.add(e["c"])
        for pid in pids:
            s = self.w2s(*m.pts[pid])
            d = math.hypot(s.x() - sp.x(), s.y() - sp.y())
            if d < 9 and (best is None or d < best[0]):
                best = (d, ("pt", pid))
        if best:
            return best[1]
        for e, pts in zip(tab.geom["edges"], tab.geom["polys"]):
            sp_pts = [self.w2s(*p) for p in pts]
            if e["kind"] == "ci":
                sp_pts.append(sp_pts[0])
            for a, b in zip(sp_pts[:-1], sp_pts[1:]):
                d = self.seg_dist(sp, a, b)
                if d < 7 and (best is None or d < best[0]):
                    best = (d, e["src"])
        return best[1] if best else None

    @staticmethod
    def seg_dist(p, a, b):
        dx, dy = b.x() - a.x(), b.y() - a.y()
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / L2))
        return math.hypot(p.x() - (a.x() + t * dx), p.y() - (a.y() + t * dy))

    def mousePressEvent(self, ev):
        self.setFocus()
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.pan_from = ev.position()
            return
        if ev.button() == Qt.MouseButton.LeftButton and self.mode in ("rect", "circle"):
            w = self.s2w(ev.position())
            self.drag = [w, w]
            return
        if ev.button() == Qt.MouseButton.LeftButton and self.mode == "node":
            self.tab.pick_node(ev.position())
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            h = self.hit(ev.position())
            add = bool(ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
            if h is None:
                if not add:
                    self.sel = []
                self.box = [ev.position(), ev.position(), add]      # drag on empty space: select everything inside the box
            elif add:
                self.sel = [s for s in self.sel if s != h] if h in self.sel else self.sel + [h]
            else:
                self.sel = [h]
            self.tab.selection_changed()
            self.update()

    def mouseMoveEvent(self, ev):
        sp = ev.position()
        x, y = self.s2w(sp)
        self.tab.coords.setText(f"x = {x:.5g}   y = {y:.5g}")
        if self.drag is not None:
            self.drag[1] = (x, y)
            self.update()
        elif self.pan_from is not None:
            self.pan_off = QPointF(sp.x() - self.pan_from.x(), sp.y() - self.pan_from.y())
            self.update()
        elif self.box is not None:
            self.box[1] = sp
            self.update()

    def box_select(self, a, b, add):
        """Points inside the rectangle (screen coordinates a-b), and edges whose every point is inside it."""
        tab = self.tab
        r = QRectF(a, b).normalized()
        inside = lambda xy: r.contains(self.w2s(*xy))
        m = tab.model
        got = []
        pids = set()
        for e, pts in zip(tab.geom["edges"], tab.geom["polys"]):
            if e["kind"] == "ci":
                pids.add(e["c"])
            else:
                pids |= {e["a"], e["b"]}
                if e["kind"] == "ar":
                    pids.add(e["c"])
            if pts and all(inside(q) for q in pts):
                got.append(e["src"])
        got = [("pt", i) for i in sorted(pids) if inside(m.pts[i])] + got
        self.sel = self.sel + [g for g in got if g not in self.sel] if add else got
        return len(got)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.drag is not None:
            (x0, y0), (x1, y1) = self.drag
            self.drag = None
            self.tab.finish_probe_drag(self.mode, x0, y0, x1, y1)
            self.update()
            return
        if ev.button() == Qt.MouseButton.LeftButton and self.box is not None:
            a, b, add = self.box
            self.box = None
            if abs(a.x() - b.x()) > 4 or abs(a.y() - b.y()) > 4:
                n = self.box_select(a, b, add)
                self.tab.status(f"Box selected {len(self.sel)} object(s)." if n else "Nothing inside the box.")
            self.tab.selection_changed()
            self.update()
        if ev.button() == Qt.MouseButton.MiddleButton and self.pan_from is not None:
            self.org = QPointF(self.org.x() + self.pan_off.x(), self.org.y() + self.pan_off.y())
            self.pan_from = None
            self.pan_off = QPointF(0, 0)
            self.invalidate()

    def wheelEvent(self, ev):
        f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        pos = ev.position()
        wx, wy = self.s2w(pos)
        self.scale *= f
        self.org = QPointF(pos.x() - wx * self.scale, pos.y() + wy * self.scale)
        self.invalidate()

    def resizeEvent(self, ev):
        self._cache_key = None
        super().resizeEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            if self.mode != "select":
                self.drag = None
                self.tab.set_tool("select")
            self.sel = []
            self.tab.selection_changed()
            self.update()
        elif not self.tab.handle_key(ev):
            super().keyPressEvent(ev)

    # --- drawing
    def face_path(self, f):
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        for poly in [f["poly"]] + [h["poly"] for h in f["holes"]]:
            path.addPolygon(QPolygonF([self.w2s(*p) for p in poly]))
            path.closeSubpath()
        return path

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        tab = self.tab
        if tab.geom is None:
            p.setPen(QColor("#666666"))
            p.setFont(QFont("Arial", 11))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Choose a sketch and press Import (left) to begin.")
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 1. regions, or the field / mesh picture
        want_field = self.field is not None and tab.result is not None and tab.mesh is not None
        mesh_only = tab.mesh is not None and not want_field and self.show_mesh
        if want_field or mesh_only:
            key = (self.field if want_field else "mesh", self.show_mesh, self.show_deformed, round(self.def_scale, 9),
                   round(self.scale, 6), round(self.org.x(), 3), round(self.org.y(), 3), self.width(), self.height(),
                   id(tab.result), id(tab.mesh))
            if self.anim_frames is not None and want_field:
                p.drawPixmap(0, 0, self.anim_frames[min(self.anim_idx, len(self.anim_frames) - 1)])
            else:
                if key != self._cache_key:
                    self._cache = self.render_picture(want_field)
                    self._cache_key = key
                p.drawPixmap(int(self.pan_off.x()), int(self.pan_off.y()), self._cache)
            if self.pan_from is not None:
                p.translate(self.pan_off)
        else:
            if self.pan_from is not None:
                p.translate(self.pan_off)
            for f in tab.geom["faces"]:
                path = self.face_path(f)
                if f["included"]:
                    p.fillPath(path, QColor(190, 215, 245, 140 if f["id"] != self.hl_face else 230))
                else:
                    p.fillPath(path, QBrush(QColor(110, 110, 110, 160), Qt.BrushStyle.BDiagPattern))
        # 2. geometry
        self.paint_geometry(p)
        self.paint_conditions(p)
        self.paint_fasteners(p)
        self.paint_probes(p)
        p.resetTransform()
        if self.box is not None:
            p.setPen(QPen(QColor("#3a7bd5"), 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor(58, 123, 213, 30))
            p.drawRect(QRectF(self.box[0], self.box[1]).normalized())
            p.setBrush(Qt.BrushStyle.NoBrush)
        if want_field:
            self.paint_legend(p)

    def paint_geometry(self, p):
        tab = self.tab
        sel = set(self.sel)
        supp = {t for s in tab.supports for t in s["targets"]}
        for e, pts in zip(tab.geom["edges"], tab.geom["polys"]):
            pen_col = QColor("#1f3d7a")
            width = 1.8
            if e["src"] in supp:
                pen_col, width = QColor("#1a9641"), 3.2
            if e["src"] in sel:
                pen_col, width = QColor("#ff8800"), 3.4
            if e["src"] not in tab.geom_used():
                pen_col = QColor("#b0b0b0")                       # not part of any closed region
            p.setPen(QPen(pen_col, width))
            poly = QPolygonF([self.w2s(*q) for q in pts] + ([self.w2s(*pts[0])] if e["kind"] == "ci" else []))
            p.drawPolyline(poly)
        m = tab.model
        pids = set()
        for e in tab.geom["edges"]:
            if e["kind"] == "ci":
                pids.add(e["c"])
            else:
                pids |= {e["a"], e["b"]}
        supp_pts = {t[1] for t in supp if t[0] == "pt"}
        for pid in pids:
            s = self.w2s(*m.pts[pid])
            if ("pt", pid) in sel:
                p.setPen(QPen(QColor("#ff8800"), 1))
                p.setBrush(QColor("#ff8800"))
                p.drawEllipse(s, 5, 5)
            elif pid in supp_pts:
                p.setPen(QPen(QColor("#1a9641"), 1))
                p.setBrush(QColor("#1a9641"))
                p.drawEllipse(s, 4.5, 4.5)
            else:
                p.setPen(QPen(QColor("#1f3d7a"), 1))
                p.setBrush(QColor("#1f3d7a"))
                p.drawEllipse(s, 2.5, 2.5)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def inward_normal(self, x, y, nx, ny):
        """Unit normal (nx, ny) flipped, if needed, to point into the material."""
        eps = 6.0 / max(self.scale, 1e-9)                          # six pixels, in sketch units
        def inside(px, py):
            cnt = 0
            for f in self.tab.geom["faces"]:
                if not f["included"]:
                    continue
                if pg.point_in_poly((px, py), f["poly"]) and not any(pg.point_in_poly((px, py), h["poly"]) for h in f["holes"]):
                    cnt += 1
            return cnt > 0
        # six pixels can be more than the whole thickness of a thin sheet when zoomed out (both probes then miss the material,
        # or land in the far side), so halve the probe distance until exactly one side is inside
        for k in range(30):
            e = eps * 0.5 ** k
            a, b = inside(x + nx * e, y + ny * e), inside(x - nx * e, y - ny * e)
            if a != b:
                return (nx, ny) if a else (-nx, -ny)
        return nx, ny

    def arrow(self, p, a, b):
        dx, dy = b.x() - a.x(), b.y() - a.y()
        L = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L
        p.drawLine(a, b)
        p.drawPolyline(QPolygonF([QPointF(b.x() - 8 * ux + 4 * uy, b.y() - 8 * uy - 4 * ux), b,
                                  QPointF(b.x() - 8 * ux - 4 * uy, b.y() - 8 * uy + 4 * ux)]))

    def paint_probes(self, p):
        """The probe regions (original geometry) and the picked node."""
        tab = self.tab
        for pr in tab.probes:
            mark = pr["name"] in (tab.probe_fos, tab.probe_trig)
            p.setPen(QPen(QColor("#7b2cbf"), 2.4 if mark else 1.6, Qt.PenStyle.DashLine))
            p.setBrush(QColor(123, 44, 191, 28))
            if pr["shape"] == "circle":
                c = self.w2s(pr["cx"], pr["cy"])
                p.drawEllipse(c, pr["r"] * self.scale, pr["r"] * self.scale)
                lab = c + QPointF(4, -4)
            else:
                a, b = self.w2s(pr["x0"], pr["y0"]), self.w2s(pr["x1"], pr["y1"])
                p.drawRect(QRectF(a, b).normalized())
                lab = QRectF(a, b).normalized().topLeft() + QPointF(4, 12)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setFont(QFont("Arial", 9))
            p.drawText(lab, pr["name"])
        if self.drag is not None:
            (x0, y0), (x1, y1) = self.drag
            p.setPen(QPen(QColor("#7b2cbf"), 1.4, Qt.PenStyle.DotLine))
            p.setBrush(QColor(123, 44, 191, 20))
            if self.mode == "circle":
                r = float(np.hypot(x1 - x0, y1 - y0))
                p.drawEllipse(self.w2s(x0, y0), r * self.scale, r * self.scale)
            else:
                p.drawRect(QRectF(self.w2s(x0, y0), self.w2s(x1, y1)).normalized())
            p.setBrush(Qt.BrushStyle.NoBrush)
        if self.node_sel is not None and tab.result is not None:
            q = tab.node_screen(self.node_sel)
            if q is not None:
                p.setPen(QPen(QColor("#000000"), 2))
                p.setBrush(QColor(255, 220, 0))
                p.drawEllipse(q, 6, 6)
                p.setBrush(Qt.BrushStyle.NoBrush)

    def paint_conditions(self, p):
        tab = self.tab
        m = tab.model
        # forces / pressures / tractions
        p.setPen(QPen(QColor("#c0182b"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        edge_of = {e["src"]: (e, pts) for e, pts in zip(tab.geom["edges"], tab.geom["polys"])}
        for ld in tab.loads:
            for kind, i in ld["targets"]:
                if ld["kind"] == "force" and kind == "pt":
                    s = self.w2s(*m.pts[i])
                    fx, fy = ld["fx"], ld["fy"]
                    L = math.hypot(fx, fy)
                    if L > 0:
                        u = QPointF(fx / L, -fy / L)
                        self.arrow(p, QPointF(s.x() - 46 * u.x(), s.y() - 46 * u.y()), s)
                elif ld["kind"] == "cfd" and (kind, i) in edge_of:
                    pair = next((pr for pr in ld["pairs"] if pr["target"] == (kind, i)), None)
                    if pair is None or "table" not in pair:
                        continue
                    e, pts = edge_of[(kind, i)]
                    closed = e["kind"] == "ci"
                    count = max(3, min(120, int(round(polyline_length(pts, closed) * self.scale / 30.0))))
                    pmax = pair["pmax"] or 1.0
                    for x0, y0, tx, ty in points_along(pts, closed, count):
                        pr, _, _ = pcfd.sample_wall(pair["table"], pcfd.edge_param(pair["fea_geom"], x0, y0), pair["closed"])
                        ix, iy = self.inward_normal(x0, y0, -ty, tx)
                        sgn = 1.0 if pr >= 0 else -1.0
                        length = 8.0 + 36.0 * abs(pr) / pmax
                        s0 = self.w2s(x0, y0)
                        self.arrow(p, QPointF(s0.x() - length * ix * sgn, s0.y() + length * iy * sgn), s0)
                elif ld["kind"] in ("pressure", "traction") and (kind, i) in edge_of:
                    e, pts = edge_of[(kind, i)]
                    closed = e["kind"] == "ci"
                    total = polyline_length(pts, closed)
                    count = max(2, min(80, int(round(total * self.scale / 40.0))))      # about one arrow per 40 pixels
                    for x0, y0, tx, ty in points_along(pts, closed, count):
                        nx, ny = -ty, tx
                        if ld["kind"] == "pressure":
                            ix, iy = self.inward_normal(x0, y0, nx, ny)
                            sgn = 1.0 if ld["p"] >= 0 else -1.0
                            d = (ix * sgn, iy * sgn)
                        else:
                            L = math.hypot(ld["tx"], ld["ty"]) or 1.0
                            d = (ld["tx"] / L, ld["ty"] / L)
                        s0 = self.w2s(x0, y0)
                        self.arrow(p, QPointF(s0.x() - 36 * d[0], s0.y() + 36 * d[1]), s0)

    def paint_fasteners(self, p):
        """Bolt / screw heads (a bar of the head width on the edge, an arrow toward the head side) and contact arrows."""
        tab = self.tab
        m = tab.model
        for sup in tab.supports:
            if sup["mode"] not in ("bolt", "screw", "contact"):
                continue
            if sup["mode"] == "contact":
                p.setPen(QPen(QColor("#6a3d9a"), 2))
                for kind, i in sup["targets"]:
                    for e, pts in zip(tab.geom["edges"], tab.geom["polys"]):
                        if e["src"] != (kind, i):
                            continue
                        closed = e["kind"] == "ci"
                        count = max(2, min(60, int(round(polyline_length(pts, closed) * self.scale / 30.0))))
                        for x0, y0, tx, ty in points_along(pts, closed, count):
                            ix, iy = self.inward_normal(x0, y0, -ty, tx)
                            s0 = self.w2s(x0, y0)
                            o = -1.0 if sup.get("flip") else 1.0
                            p.drawLine(QPointF(s0.x() - o * 7 * ix, s0.y() + o * 7 * iy), QPointF(s0.x() - o * 15 * ix, s0.y() + o * 15 * iy))
                            bx, by = s0.x() - o * 16 * ix, s0.y() + o * 16 * iy
                            p.drawLine(QPointF(bx + 5 * tx, by - 5 * ty), QPointF(bx - 5 * tx, by + 5 * ty))
                continue
            for kind, pid in sup["targets"]:
                if pid not in m.pts:
                    continue
                x, y = m.pts[pid]
                tx, ty = 1.0, 0.0
                for e in tab.geom["edges"]:
                    if e["kind"] == "ln" and pid in (e["a"], e["b"]):
                        a, b = m.pts[e["a"]], m.pts[e["b"]]
                        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
                        tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
                        break
                ix, iy = self.inward_normal(x, y, -ty, tx)
                o = -1.0 if sup.get("flip") else 1.0
                s0 = self.w2s(x, y)
                half = 0.5 * sup["d"] * self.scale
                col = QColor("#a31515") if sup["mode"] == "bolt" else QColor("#6a3d9a")
                p.setPen(QPen(col, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                hx, hy = -o * ix, o * iy                     # toward the head side, in screen coordinates (y down)
                p.drawLine(QPointF(s0.x() - tx * half + hx * 4, s0.y() + ty * half + hy * 4),
                           QPointF(s0.x() + tx * half + hx * 4, s0.y() - ty * half + hy * 4))
                if sup["mode"] == "bolt":
                    p.drawLine(QPointF(s0.x() - tx * half - hx * 4, s0.y() + ty * half - hy * 4),
                               QPointF(s0.x() + tx * half - hx * 4, s0.y() - ty * half - hy * 4))
                p.setPen(QPen(col, 2))
                # the arrow is the holding force on the sheet: from the head toward the sheet (head on top -> arrow points down)
                self.arrow(p, QPointF(s0.x() + hx * 30, s0.y() + hy * 30), QPointF(s0.x() + hx * 9, s0.y() + hy * 9))

    def paint_legend(self, p):
        r = self.tab.result
        key = self.field
        vals = field_values(r, key)
        lo, hi = float(np.min(vals)), float(np.max(vals))
        x0, y0, w, h = self.width() - 90, 40, 16, 180
        for k in range(h):
            c = colours(1 - k / (h - 1))
            p.fillRect(int(x0), int(y0 + k), w, 2, QColor(int(c[0]), int(c[1]), int(c[2])))
        p.setPen(QColor("black"))
        p.setFont(QFont("Arial", 8))
        p.drawRect(int(x0), int(y0), w, h)
        for k in range(6):
            t = k / 5
            p.drawText(int(x0 + w + 4), int(y0 + t * h + 4), f"{hi - t * (hi - lo):.4g}")
        name = next(n for n, k, _ in FIELDS if k == key)
        u = units.get(self.tab.unit_name())
        p.drawText(int(x0 - 40), int(y0 - 12), f"{name}  [{u['L'] if key in ('umag', 'ux', 'uy') else u['S']}]")

    def render_picture(self, want_field, ramp=1.0):
        tab = self.tab
        mesh, r = tab.mesh, tab.result
        if want_field and r is not None and r.get("mesh") is not None:
            mesh = r["mesh"]                                   # quadratic result: nodes include the mid-edge nodes, 4 small triangles each
        import meshdraw as md
        W, H = max(self.width(), 10), max(self.height(), 10)
        nodes = mesh["nodes"]
        tris = mesh["tris"]
        pos = nodes
        if want_field and self.show_deformed:
            pos = nodes + self.def_scale * ramp * r["u"]
        scr_x = self.org.x() + pos[:, 0] * self.scale
        scr_y = self.org.y() - pos[:, 1] * self.scale
        edges = md.unique_edges(tab.mesh["tris"]) if self.show_mesh else None      # the element edges, not the small drawing triangles
        if want_field:
            key = self.field
            kind = next(k for _, kk, k in FIELDS if kk == key)
            full = field_values(r, key)
            lo, hi = float(np.min(full)), float(np.max(full))          # the colour scale is always that of the final result
            vals = full * ramp
            if kind == "elem":
                img = md.render(W, H, scr_x, scr_y, tris, tri_vals=vals, lo=lo, hi=hi, edges=edges, edge_alpha=0.35)
            else:
                img = md.render(W, H, scr_x, scr_y, tris, nodal=vals, lo=lo, hi=hi, edges=edges, edge_alpha=0.35)
        else:
            img = md.render(W, H, scr_x, scr_y, np.zeros((0, 3), dtype=int), tri_vals=np.zeros(0), edges=edges, edge_alpha=0.35)
        return QPixmap.fromImage(img)


# ----------------------------------------------------------------------------------------------
# the tab
# ----------------------------------------------------------------------------------------------
class PhysicsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.model = None
        self.geom = None
        self.mesh = None
        self.result = None
        self.supports = []       # {"mode": "fixed"|"x"|"y", "targets": [(kind, id)]}
        self.loads = []          # {"kind": "force"|"pressure"|"traction", ..., "targets": [...]}
        self.profile = None      # imported profile properties: {"name", "A_w", "I_w", "c_top", "c_bottom"} in the sketch's units
        self.probes = []         # {"name", "shape": "rect"|"circle", x0 y0 x1 y1 | cx cy r}  (original geometry, sketch units)
        self.probe_fos = None    # name of the probe whose average von Mises stress feeds the factors of safety
        self.probe_trig = None   # name of the probe whose average von Mises stress is tested against the nonlinear trigger
        self.deps = dependency_status()
        self.coords = QLabel("")
        self.canvas = PhysCanvas(self)

        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(6, 6, 6, 6)

        missing = [n for n, (v, _) in self.deps.items() if v is None]
        if missing:
            warn = QLabel("<b>Missing:</b> " + ", ".join(missing) + "<br>Install with:<br><code>pip install " +
                          " ".join(missing) + "</code><br>then restart the program.<br><small>" +
                          "<br>".join(f"{n}: {t}" for n, (v, t) in self.deps.items() if v is None) + "</small>")
            warn.setWordWrap(True)
            warn.setStyleSheet("background:#fff3cd; padding:6px; border:1px solid #e0c36a;")
            warn.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(warn)

        self.picker = SketchPicker(self.win, self.import_picked)
        lay.addWidget(self.picker)
        b = QPushButton("Clear (start over)")
        b.setToolTip("Removes the imported copy of the sketch and everything set up on this tab (supports, loads, results...) so you can "
                     "import the sketch again from scratch. The sketch itself is not touched.")
        b.clicked.connect(self.clear_tab)
        lay.addWidget(b)
        self.info = QLabel("Nothing imported yet.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        lay.addWidget(QLabel("<b>Regions</b> (tick = material)"))
        self.regions = QListWidget()
        self.regions.setMaximumHeight(110)
        self.regions.itemChanged.connect(self.region_toggled)
        self.regions.currentRowChanged.connect(self.region_picked)
        lay.addWidget(self.regions)

        lay.addWidget(QLabel("<b>Material and analysis</b>"))
        row = QHBoxLayout()
        self.rb_stress = QRadioButton("Plane stress")
        self.rb_strain = QRadioButton("Plane strain")
        self.rb_stress.setChecked(True)
        row.addWidget(self.rb_stress)
        row.addWidget(self.rb_strain)
        lay.addLayout(row)
        form = QFormLayout()
        self.mat_combo = QComboBox()
        self.unit_combo = QComboBox()
        for u in pm.UNITS:
            self.unit_combo.addItem(u)
        self.unit_combo.setCurrentText(pm.DEFAULT_UNIT)
        self.cur_unit = pm.DEFAULT_UNIT
        self.e_E = QLineEdit("200000")
        self.e_nu = QLineEdit("0.3")
        self.e_t = QLineEdit("1")
        self.e_h = QLineEdit("")
        self.e_sy, self.e_su, self.e_eu = QLineEdit("250"), QLineEdit("400"), QLineEdit("10")
        self.cb_lin = QCheckBox("Linear solver")
        self.cb_nl = QCheckBox("Nonlinear solver")
        self.cb_lin.setChecked(True)
        self.cb_nl.setChecked(True)
        self.cb_lin.setToolTip("Both ticked: solve linear first, and switch to the nonlinear solver if a trigger below is passed.\n"
                               "Linear only: never switch.  Nonlinear only: always solve nonlinearly (the triggers are ignored).")
        self.cb_nl.setToolTip(self.cb_lin.toolTip() + "\nThe nonlinear solver uses large displacements AND yielding, and needs quadratic elements.")
        self.e_nld, self.e_nly = QLineEdit(""), QLineEdit("90")
        self.e_sy.setToolTip("Yield strength. 0 = brittle material (no yielding).")
        self.e_eu.setToolTip("Plastic strain (in %) at the ultimate strength. The stress rises in a straight line from the yield to the ultimate "
                             "strength over this strain, then stays flat.")
        self.e_nld.setToolTip("Largest displacement (a length) that triggers the nonlinear solver. Empty = no displacement trigger.")
        self.e_nly.setToolTip("Largest von Mises stress, in % of the yield strength, that triggers the nonlinear solver. Empty = no stress trigger.")
        self.unit_combo.hide()                       # holds the program-wide unit system (File > Units); never shown
        self.lbl_E, self.lbl_t, self.lbl_h = QLabel("E"), QLabel("Thickness (depth)"), QLabel("Element size")
        self.lbl_sy, self.lbl_su, self.lbl_nld = QLabel("Yield strength"), QLabel("Ultimate strength"), QLabel("Displacement trigger")
        form.addRow("Material", self.mat_combo)
        form.addRow(self.lbl_E, self.e_E)
        form.addRow("Poisson's ratio", self.e_nu)
        form.addRow(self.lbl_t, self.e_t)
        form.addRow(self.lbl_h, self.e_h)
        form.addRow(self.lbl_sy, self.e_sy)
        form.addRow(self.lbl_su, self.e_su)
        form.addRow("Plastic strain at ultimate (%)", self.e_eu)
        rowc = QHBoxLayout()
        rowc.addWidget(self.cb_lin)
        rowc.addWidget(self.cb_nl)
        form.addRow(rowc)
        form.addRow(self.lbl_nld, self.e_nld)
        form.addRow("Stress trigger (% of yield)", self.e_nly)
        lay.addLayout(form)
        rowp = QHBoxLayout()
        b_pi = QPushButton("Import profile properties...")
        b_pi.setToolTip("Idealise a ribbed panel as a thin strip: reads a .profprops file written by Edit > Section properties in the "
                        "sketcher. The strip is given the stiffness (EA and EI) of the real panel and the strengths are scaled.")
        b_pi.clicked.connect(self.import_profile)
        b_pc = QPushButton("Clear")
        b_pc.clicked.connect(self.clear_profile)
        rowp.addWidget(b_pi)
        rowp.addWidget(b_pc)
        lay.addLayout(rowp)
        self.profile_lbl = self.note("No profile: the sheet is a plain solid strip.")
        lay.addWidget(self.profile_lbl)
        self.units_note = self.note("")
        lay.addWidget(self.units_note)
        row = QHBoxLayout()
        b = QPushButton("Add material...")
        b.clicked.connect(self.add_material)
        row.addWidget(b)
        self.b_del_mat = QPushButton("Delete")
        self.b_del_mat.setToolTip("Deletes a material you added. The built-in ones stay.")
        self.b_del_mat.clicked.connect(self.delete_material)
        row.addWidget(self.b_del_mat)
        lay.addLayout(row)
        self.mat_note = self.note("")
        lay.addWidget(self.mat_note)
        self.order_combo = QComboBox()
        self.order_combo.addItems(["Quadratic (6-node triangles)", "Linear (3-node triangles)"])
        self.order_combo.setToolTip("Quadratic elements have a node in the middle of every edge. They bend far more accurately than linear "
                                    "ones for the same mesh (linear triangles are far too stiff in bending). The mesh and its size do not change.")
        form.addRow("Elements", self.order_combo)
        lay.addWidget(self.note("One material for everything. Quadratic elements need only a coarse mesh to capture bending (at least 2 "
                                "elements through a thin sheet); linear ones are much too stiff in bending."))
        self.library = []
        self.fill_materials(select="Structural steel (A36)")
        self.material_picked()
        self.mat_combo.currentIndexChanged.connect(self.material_picked)
        self.unit_combo.currentIndexChanged.connect(self.unit_changed)
        self.e_E.textEdited.connect(self.set_custom)
        self.e_nu.textEdited.connect(self.set_custom)
        self.cb_lin.toggled.connect(self.solver_boxes)
        self.cb_nl.toggled.connect(self.solver_boxes)
        self.e_sy.textEdited.connect(self.set_custom)
        self.e_su.textEdited.connect(self.set_custom)

        row = QHBoxLayout()
        self.b_mesh = QPushButton("Mesh")
        self.b_mesh.clicked.connect(self.run_mesh)
        self.b_solve = QPushButton("Solve")
        self.b_solve.clicked.connect(self.run_solve)
        row.addWidget(self.b_mesh)
        row.addWidget(self.b_solve)
        lay.addLayout(row)
        self.cb_auto = QCheckBox("Auto-refine the mesh until the result converges")
        self.cb_auto.setToolTip("Solve, then refine the mesh where the stress changes fastest and solve again, until the strain energy "
                                "and the largest displacement change by less than 1 % between two meshes, or a limit below is reached. "
                                "Starts from the mesh you made with Mesh.")
        lay.addWidget(self.cb_auto)
        self.auto_box = QWidget()
        af = QFormLayout(self.auto_box)
        af.setContentsMargins(14, 0, 0, 0)
        self.e_passes = QLineEdit("4")
        self.e_maxtris = QLineEdit("100000")
        af.addRow("Maximum refinement passes", self.e_passes)
        af.addRow("Maximum triangles", self.e_maxtris)
        af.addRow(self.note("Press Solve. Convergence is judged on the strain energy and the largest displacement. The largest stress is "
                            "listed for each pass but not used: at a sharp corner or a point load it never converges."))
        self.auto_box.setVisible(False)
        self.cb_auto.toggled.connect(self.auto_box.setVisible)
        lay.addWidget(self.auto_box)

        lay.addWidget(QLabel("<b>Supports and loads</b> (select on the drawing first)"))
        row = QHBoxLayout()
        for text, mode in (("Fixed  (F)", "fixed"), ("ux = 0  (X)", "x"), ("uy = 0  (Y)", "y")):
            b = QPushButton(text)
            b.clicked.connect(lambda _, m_=mode: self.add_support(m_))
            row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        for text, fn, tip in (("Bolt...  (B)", lambda: self.add_fastener("bolt"),
                               "A bolt through the sheet at the selected points: a fixed patch of the width you give, held in every direction."),
                              ("Screw...  (S)", lambda: self.add_fastener("screw"),
                               "A screw head at the selected points: a patch of the width you give that is held sideways and "
                               "cannot move toward the head side, but is free to move away from it."),
                              ("Contact  (C)", self.add_contact,
                               "The selected edges rest against a frictionless surface: they cannot move into it but are free to lift off.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        for text, fn in (("Force...  (Shift+F)", self.add_force), ("Pressure...  (P)", self.add_pressure),
                         ("Traction...  (T)", self.add_traction)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(self.note("Hotkeys work while the drawing has the keyboard focus (click in it first): F, X, Y, B, S, C, Shift+F, P, T."))
        b = QPushButton("Pressure from CFD...")
        b.setToolTip("Loads the selected edges with the pressure (and optionally wall shear) of a solved CFD result, "
                     "interpolated along the whole length of each edge.")
        b.clicked.connect(self.add_cfd_load)
        lay.addWidget(b)
        lay.addWidget(self.note("Force: on points, total force. Pressure: on edges, positive pushes into the material. "
                                "Traction: on edges, force per area in a fixed direction."))
        self.cond_list = QListWidget()                       # plain-text copy of the table (kept for scripts and tests)
        self.cond_list.hide()
        self.cond_table = QTableWidget(0, 4)
        self.cond_table.setHorizontalHeaderLabels(["Name", "Type", "Applied to", "Value"])
        self.cond_table.verticalHeader().hide()
        self.cond_table.setMinimumHeight(110)
        self.cond_table.setMaximumHeight(190)
        self.cond_table.horizontalHeader().setStretchLastSection(True)
        self.cond_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cond_table.itemChanged.connect(self.cond_item_changed)
        lay.addWidget(self.cond_table)
        lay.addWidget(self.note("Double-click a Name to rename it (the Parameterization tab uses these names). Force, pressure, "
                                "traction and screw / bolt head widths can be edited in the Value column."))
        b = QPushButton("Remove selected item")
        b.clicked.connect(self.remove_condition)
        lay.addWidget(b)

        lay.addWidget(QLabel("<b>Probe regions</b> (average stress over an area of the original geometry)"))
        row = QHBoxLayout()
        self.b_prect = QPushButton("Rectangle (drag)")
        self.b_pcirc = QPushButton("Circle (drag)")
        for b_, mode in ((self.b_prect, "rect"), (self.b_pcirc, "circle")):
            b_.setCheckable(True)
            b_.clicked.connect(lambda on, m=mode: self.set_tool(m if on else "select"))
            row.addWidget(b_)
        lay.addLayout(row)
        self.probe_table = QTableWidget(0, 5)
        self.probe_table.setHorizontalHeaderLabels(["Name", "Shape", "Geometry", "FoS", "Trigger"])
        self.probe_table.verticalHeader().hide()
        self.probe_table.setMinimumHeight(90)
        self.probe_table.setMaximumHeight(160)
        self.probe_table.horizontalHeader().setStretchLastSection(True)
        self.probe_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.probe_table.itemChanged.connect(self.probe_item_changed)
        lay.addWidget(self.probe_table)
        lay.addWidget(self.note("FoS: the marked probe's average von Mises stress is used for the factors of safety (none marked = the "
                                "largest stress). Trigger: the marked probe's average is tested against the nonlinear stress trigger "
                                "(none marked = the largest stress). Rectangle: x0, y0, x1, y1. Circle: centre x, y, radius."))
        b = QPushButton("Remove selected probe")
        b.clicked.connect(self.remove_probe)
        lay.addWidget(b)

        lay.addWidget(QLabel("<b>Results</b>"))
        self.field = QComboBox()
        self.field.addItem("(none - show the mesh)", None)
        for name, key, _ in FIELDS:
            self.field.addItem(name, key)
        self.field.currentIndexChanged.connect(self.view_changed)
        lay.addWidget(self.field)
        row = QHBoxLayout()
        row.addWidget(QLabel("Colours"))
        self.cmap_combo = result_style.make_combo(self, self.restyle)
        row.addWidget(self.cmap_combo, 1)
        lay.addLayout(row)
        self.cb_def = QCheckBox("Show deformed shape")
        self.cb_def.setChecked(True)
        self.cb_def.toggled.connect(self.view_changed)
        lay.addWidget(self.cb_def)
        row = QHBoxLayout()
        row.addWidget(QLabel("Deformation scale"))
        self.e_def = QLineEdit("")
        self.e_def.setPlaceholderText("auto")
        self.e_def.editingFinished.connect(self.view_changed)
        row.addWidget(self.e_def)
        lay.addLayout(row)
        self.cb_mesh = QCheckBox("Show mesh lines")
        self.cb_mesh.setChecked(True)
        self.cb_mesh.toggled.connect(self.view_changed)
        lay.addWidget(self.cb_mesh)
        self.cb_anim = QCheckBox("Animate")
        self.cb_anim.setToolTip("Ramps the load from 0 to its full value. The analysis is linear and static, so this is a ramp, not a time simulation.")
        self.cb_anim.toggled.connect(self.anim_toggled)
        lay.addWidget(self.cb_anim)
        self.anim_box = QWidget()
        al = QFormLayout(self.anim_box)
        al.setContentsMargins(14, 0, 0, 0)
        self.e_frames = QLineEdit("30")
        self.e_dur = QLineEdit("3")
        self.loop_combo = QComboBox()
        self.loop_combo.addItems(["Once", "Loop", "Back and forth"])
        al.addRow("Frames", self.e_frames)
        al.addRow("Duration (s)", self.e_dur)
        al.addRow("Playback", self.loop_combo)
        arow = QHBoxLayout()
        self.b_play = QPushButton("Play")
        self.b_play.clicked.connect(self.anim_play)
        self.b_stop = QPushButton("Stop")
        self.b_stop.clicked.connect(self.anim_stop)
        arow.addWidget(self.b_play)
        arow.addWidget(self.b_stop)
        al.addRow(arow)
        al.addRow(self.note("Ramp of the load from 0 to full (linear static analysis, not a time simulation). "
                            "The colour scale is fixed to the final result. All frames are drawn first."))
        self.anim_box.setVisible(False)
        lay.addWidget(self.anim_box)
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.anim_step)
        self.anim_dir = 1
        self.b_node = QPushButton("Node probe (click a node)")
        self.b_node.setCheckable(True)
        self.b_node.setToolTip("Click near a node on the result to read every result at that node, whichever field is coloured.")
        self.b_node.clicked.connect(lambda on: self.set_tool("node" if on else "select"))
        lay.addWidget(self.b_node)
        self.node_lbl = QLabel("")
        self.node_lbl.setWordWrap(True)
        self.node_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.node_lbl)
        self.res_lbl = QLabel("")
        self.res_lbl.setWordWrap(True)
        lay.addWidget(self.res_lbl)
        b = QPushButton("Diagnostics report...")
        b.setToolTip("A text report of the geometry, mesh, setup and solution that you can copy and paste to me.")
        b.clicked.connect(self.show_diag)
        lay.addWidget(b)
        b = QPushButton("Zoom to fit")
        b.clicked.connect(self.canvas.fit)
        lay.addWidget(b)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(left)
        scroll.setMinimumWidth(340)
        scroll.setMaximumWidth(400)
        scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        left.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(scroll)
        split.addWidget(self.canvas)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(split, 1)
        row = QHBoxLayout()
        row.setContentsMargins(6, 2, 6, 2)
        self.status_lbl = QLabel("")
        row.addWidget(self.status_lbl, 1)
        row.addWidget(self.coords)
        outer.addLayout(row)
        self.enable_buttons()

    @staticmethod
    def note(text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#555555; font-size:11px;")
        return lb

    def status(self, text):
        self.status_lbl.setText(text)
        try:
            self.win.status(text)
        except Exception:
            pass

    def enable_buttons(self):
        have = {n for n, (v, _) in self.deps.items() if v is not None}
        self.b_mesh.setEnabled(self.geom is not None and "gmsh" in have and "numpy" in have)
        self.b_solve.setEnabled(self.mesh is not None and "scipy" in have)

    def geom_used(self):
        return self.geom["used_edges_src"] if self.geom is not None else set()

    # --- import
    def import_picked(self, sid, text, name):
        m = sc.Model()
        m.from_json(text)
        self.set_model(m, name)
        self.sketch_id = sid

    def import_current(self):
        self.picker.go()

    def clear_tab(self):
        """The Clear button: forget the imported sketch and this tab's setup, so the sketch can be imported again from scratch."""
        if self.model is None:
            self.status("Nothing to clear: no sketch is imported here.") if hasattr(self, "status") else None
            return
        if getattr(self, "worker", None) is not None:
            QMessageBox.information(self, "Clear", "A run is in progress on this tab. Stop it first.")
            return
        if QMessageBox.question(self, "Clear", "Remove the imported sketch and everything set up on this tab (supports, loads, results)? "
                                "The sketch itself is not touched.") != QMessageBox.StandardButton.Yes:
            return
        self.clear_state()
        param = getattr(self.win, "param", None)
        if param is not None:
            try:
                param.refresh_params()
            except Exception:
                pass

    def unit_name(self):
        if self.model is not None:
            return self.model.unit_system
        return getattr(getattr(self.win, "m", None), "unit_system", units.DEFAULT)

    def adopt_units(self, m):
        """A sketch copy in another unit system than the program's is converted to it."""
        if getattr(self.win, "_restoring", False):
            return m                                   # a saved tab keeps its own units
        want = getattr(getattr(self.win, "m", None), "unit_system", None)
        if want and units.valid(want) and m.unit_system != want:
            try:
                m.convert_units(want, True)
            except ValueError:
                m.unit_system = want
        return m

    def apply_units(self, name):
        """Makes `name` the unit system of this tab: the (hidden) combo converts the E in the box, labels are refreshed."""
        if self.unit_combo.currentText() != name:
            self.unit_combo.setCurrentText(name)               # unit_changed() converts E
        self.cur_unit = name
        u = units.get(name)
        self.lbl_E.setText(f"E ({u['S']})")
        self.lbl_t.setText(f"Thickness ({u['L']})")
        self.lbl_h.setText(f"Element size ({u['L']})")
        self.lbl_sy.setText(f"Yield strength ({u['S']})")
        self.lbl_su.setText(f"Ultimate strength ({u['S']})")
        self.lbl_nld.setText(f"Displacement trigger ({u['L']})")
        self.units_note.setText(f"Units: {name}  (change in File > Units)")

    def set_model(self, m, source):
        m = self.adopt_units(m)
        self.model = m
        self.source = source
        self.apply_units(m.unit_system)
        self.geom = pg.analyze(m)
        self.geom["used_edges_src"] = {self.geom["edges"][k]["src"] for k in self.geom["used_edges"]}
        self.mesh = None
        self.result = None
        self.supports, self.loads = [], []
        self.region_mats, self.region_names = {}, {}          # per-region materials (an assembly slice), see sim_tab.py
        self.probes, self.probe_fos, self.probe_trig = [], None, None
        self.profile = None
        self.update_profile_label()
        self.canvas.node_sel = None
        self.canvas.sel = []
        self.canvas.field = None
        self.field.setCurrentIndex(0)
        self.fill_regions()
        xs = [p[0] for pts in self.geom["polys"] for p in pts]
        ys = [p[1] for pts in self.geom["polys"] for p in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) if xs else 1.0
        self.e_h.setText(f"{span / 30:.4g}")
        self.e_nld.setText(f"{span / 50:.4g}")             # 2 % of the model size: a sensible start, change it freely
        g = self.geom
        msg = f"Imported {source}: {len(g['edges'])} edges, {len(g['faces'])} closed region(s)."
        if g["pruned"]:
            msg += f" {len(g['pruned'])} edge(s) not part of a closed loop were ignored."
            msg += pg.gap_note(g.get("gaps"))
        if g["crossings"]:
            msg += f" WARNING: {len(g['crossings'])} pair(s) of edges cross without a shared point."
        self.info.setText(msg)
        self.status(msg)
        self.refresh_lists()
        self.canvas.fit()
        self.enable_buttons()

    def fill_regions(self):
        self.regions.blockSignals(True)
        self.regions.clear()
        for f in self.geom["faces"]:
            nm = (getattr(self, "region_names", None) or {}).get(f["id"])
            it = QListWidgetItem(f"Region {f['id'] + 1}" + (f"  [{nm}]" if nm else "") + f"   area {f['net_area']:.5g}   nesting {f['depth']}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if f["included"] else Qt.CheckState.Unchecked)
            self.regions.addItem(it)
        self.regions.blockSignals(False)

    def region_toggled(self, item):
        r = self.regions.row(item)
        self.geom["faces"][r]["included"] = item.checkState() == Qt.CheckState.Checked
        self.mesh = None
        self.result = None
        self.canvas.field = None
        self.field.setCurrentIndex(0)
        self.canvas.invalidate()
        self.enable_buttons()
        self.status("Region changed: mesh again.")

    def region_picked(self, row):
        self.canvas.hl_face = row if row >= 0 else None
        self.canvas.update()

    # --- supports and loads
    def selection_changed(self):
        pass

    def targets(self, kinds, what):
        t = [s for s in self.canvas.sel if s[0] in kinds]
        if not t:
            QMessageBox.information(self, what, "Select " + " / ".join(KIND_NAME[k].lower() + "s" for k in kinds) +
                                    " on the drawing first (click; Ctrl-click to add more).")
        return t

    def handle_key(self, ev):
        """The constraint hotkeys (the drawing has the focus).  -> True when the key was used."""
        if self.model is None or self.geom is None:
            return False
        if ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        k, K = ev.key(), Qt.Key
        if k == K.Key_F:
            self.add_force() if shift else self.add_support("fixed")
        elif shift:
            return False
        elif k == K.Key_X:
            self.add_support("x")
        elif k == K.Key_Y:
            self.add_support("y")
        elif k == K.Key_B:
            self.add_fastener("bolt")
        elif k == K.Key_S:
            self.add_fastener("screw")
        elif k == K.Key_C:
            self.add_contact()
        elif k == K.Key_P:
            self.add_pressure()
        elif k == K.Key_T:
            self.add_traction()
        else:
            return False
        return True

    def add_support(self, mode):
        t = self.targets(("pt", "ln", "ar", "ci"), "Support")
        if not t:
            return
        self.supports.append({"mode": mode, "targets": t})
        self.after_conditions()

    def add_fastener(self, mode):
        t = self.targets(("pt",), "Bolt" if mode == "bolt" else "Screw")
        if not t:
            return
        lu = units.get(self.unit_name())["L"]
        dlg = QDialog(self)
        dlg.setWindowTitle("Bolt" if mode == "bolt" else "Screw")
        form = QFormLayout(dlg)
        form.addRow(QLabel(("The sheet is held over a patch of this width, centred on the point, along its edge. For a bolt that is the "
                            "washer / head width; it is fixed in every direction.") if mode == "bolt" else
                           ("The sheet is held over a patch of this width (the head or washer), centred on the point. It cannot slide "
                            "and cannot move toward the head side; it is free to move away.")))
        e = QLineEdit(f"{getattr(self, 'last_fastener_d', 1.0):g}")
        form.addRow(f"Head width ({lu})", e)
        flip = QCheckBox("Head on the inside (flip the head side)")
        if mode == "screw":
            flip.setToolTip("By default the head is on the outside of the profile. Tick to put it on the other side.")
            form.addRow(flip)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            d = float(e.text().strip())
            if not d > 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Head width", "The head width must be a number greater than zero.")
            return
        self.last_fastener_d = d
        for tg in t:
            self.supports.append({"mode": mode, "targets": [tg], "d": d, "flip": bool(flip.isChecked()) if mode == "screw" else False})
        self.after_conditions()

    def add_contact(self):
        t = self.targets(("ln", "ar", "ci"), "Contact")
        if not t:
            return
        self.supports.append({"mode": "contact", "targets": t, "flip": False})
        self.after_conditions()

    def add_force(self):
        t = self.targets(("pt",), "Force")
        if not t:
            return
        fu = units.get(self.unit_name())["F"]
        v = ask_numbers(self, "Force on the selected points", [f"Fx ({fu})", f"Fy ({fu})"], [0, -1000])
        if v is None:
            return
        self.loads.append({"kind": "force", "fx": v[0], "fy": v[1], "targets": t})
        self.after_conditions()

    def add_pressure(self):
        t = self.targets(("ln", "ar", "ci"), "Pressure")
        if not t:
            return
        v = ask_numbers(self, "Pressure on the selected edges (positive pushes into the material)",
                        [f"Pressure ({units.get(self.unit_name())['S']})"], [1])
        if v is None:
            return
        self.loads.append({"kind": "pressure", "p": v[0], "targets": t})
        self.after_conditions()

    def add_traction(self):
        t = self.targets(("ln", "ar", "ci"), "Traction")
        if not t:
            return
        su = units.get(self.unit_name())["S"]
        v = ask_numbers(self, "Traction on the selected edges (force per area)", [f"Tx ({su})", f"Ty ({su})"], [0, -1])
        if v is None:
            return
        self.loads.append({"kind": "traction", "tx": v[0], "ty": v[1], "targets": t})
        self.after_conditions()

    def add_cfd_load(self):
        """Sets up a LINK: which FEA edge takes the pressure of which CFD edge.  The pressure itself is read from the CFD result
        at the moment the FEA solves, so this works before any CFD result exists (see resolved_loads)."""
        cfd = getattr(self.win, "cfd", None)
        if cfd is None or getattr(cfd, "model", None) is None:
            QMessageBox.information(self, "Pressure from CFD", "Import the sketch in the CFD tab first (choose a sketch and press Import).")
            return
        info = cfd.transfer_info()
        t = self.targets(("ln", "ar", "ci"), "Pressure from CFD")
        if not t:
            return
        fea_geoms = {e["src"]: pcfd.edge_geometry(self.model, e) for e in self.geom["edges"]}
        if info is not None:
            cfd_geoms, walls, stat = info["edge_geoms"], info["walls"], info["status"]
        else:
            cfd_geoms = {e["src"]: pcfd.edge_geometry(cfd.model, e) for e in cfd.geom["edges"]}
            sel_ok = cfd.selectable()
            walls = {k: None for k in (sorted(sel_ok) if sel_ok else sorted(cfd_geoms.keys()))}
            stat = None
        span = max([abs(v) for g in fea_geoms.values() for v in _flat(g)] + [1.0])
        tol = 1e-6 * span
        pref = [tuple(k) for k in cfd.canvas.sel if tuple(k) in walls]          # edges picked in the CFD tab
        sources = pref + [k for k in sorted(walls.keys()) if k not in pref]
        by_order = {}
        if pref and len(pref) == len(t) and not any(tg in walls for tg in t):
            by_order = dict(zip(sorted(t), sorted(pref)))
        dlg = QDialog(self)
        dlg.setWindowTitle("Pressure from CFD")
        dlg.setMinimumWidth(560)
        dlg.resize(620, min(720, max(360, 320 + 62 * len(t))))
        lay = QVBoxLayout(dlg)
        if stat is None:
            lay.addWidget(self.note("There is no CFD result yet. This sets up a LINK: when the FEA solves (or when the Parameterization "
                                    "tab runs a case: CFD first, then FEA), the pressure is read from the CFD result at that moment. "
                                    "Pressure is gauge, relative to the outlet, converted to this tab's unit system."))
        else:
            lay.addWidget(self.note("This is a LINK: the pressure is read from the CFD result at the moment the FEA solves, so solving "
                                    "the CFD again changes this load. Pressure is gauge, relative to the outlet, converted to this "
                                    "tab's unit system."))
            if stat != "converged":
                warn = QLabel(f"WARNING: the CFD result now in the CFD tab is NOT converged (status: {stat}). It is the last time "
                              "step, not a steady state. The FEA will still use it and its result will say so.")
                warn.setWordWrap(True)
                warn.setStyleSheet("background:#fde0e0; padding:6px; border:1px solid #d08080;")
                lay.addWidget(warn)
        grid = QFormLayout()
        combos = []
        for tgt in t:
            cb = QComboBox()
            cb.addItem("(do not load this edge)", None)
            for src in sources:
                cb.addItem(f"CFD {KIND_NAME[src[0]]} {src[1]}" + ("   (selected in CFD)" if src in pref else ""), src)
            want = tgt if tgt in walls else by_order.get(tgt)
            idx = next((k for k in range(cb.count()) if cb.itemData(k) == want), 0)
            cb.setCurrentIndex(idx)
            note = QLabel("")
            note.setWordWrap(True)

            def update(_=0, cb=cb, tgt=tgt, note=note):
                src = cb.currentData()
                if src is None:
                    note.setText("")
                elif src not in cfd_geoms or not pcfd.same_edge(fea_geoms[tgt], cfd_geoms[src], tol):
                    note.setText("<span style='color:#b00020'>The geometry of this edge differs from that CFD edge "
                                 "(or the ids do not match). The load is still placed by position along the edge.</span>")
                else:
                    note.setText("<span style='color:#1a7a1a'>Same geometry in both sketches.</span>")
            cb.currentIndexChanged.connect(update)
            update()
            box = QVBoxLayout()
            box.addWidget(cb)
            box.addWidget(note)
            grid.addRow(f"FEA {KIND_NAME[tgt[0]]} {tgt[1]}  gets the pressure of", box)
            combos.append((tgt, cb))
        holder = QWidget()
        holder.setLayout(grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)                      # long edge lists scroll; the buttons below stay on screen
        cb_shear = QCheckBox("Include wall shear")
        cb_shear.setChecked(False)
        lay.addWidget(cb_shear)
        lay.addWidget(self.note("The load is the CFD value at each position along the edge, so different edges can take different "
                                "CFD edges. Nothing is averaged."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pairs = [{"target": tgt, "source": cb.currentData()} for tgt, cb in combos if cb.currentData() is not None]
        if not pairs:
            return
        self.loads.append({"kind": "cfd", "include_shear": cb_shear.isChecked(), "pairs": pairs, "live": True,
                           "targets": [pr["target"] for pr in pairs], "converged": True})
        self.after_conditions()

    def resolved_loads(self, lds):
        """The loads with every CFD link replaced by the pressure of the CFD result that exists now (ModelError if there is none)."""
        cfd = getattr(self.win, "cfd", None)
        info = cfd.transfer_info() if cfd is not None else None
        fea_geoms = {e["src"]: pcfd.edge_geometry(self.model, e) for e in self.geom["edges"]}
        return prefine.resolve_cfd_links(lds, info, fea_geoms, pm.from_mpa(1e-6, self.stress_unit()))

    def after_conditions(self):
        self.result = None
        self.canvas.field = None
        self.field.setCurrentIndex(0)
        self.refresh_lists()
        self.canvas.invalidate()

    @staticmethod
    def names(targets):
        return ", ".join(f"{KIND_NAME[k]} {i}" for k, i in targets)

    SUP_NAME = {"fixed": "Fixed", "x": "Slide x", "y": "Slide y", "bolt": "Bolt", "screw": "Screw", "contact": "Contact"}
    LOAD_NAME = {"force": "Force", "pressure": "Pressure", "traction": "Traction", "cfd": "CFD pressure"}

    def default_name(self, is_sup, idx):
        items = self.supports if is_sup else self.loads
        key = "mode" if is_sup else "kind"
        base = (self.SUP_NAME if is_sup else self.LOAD_NAME)[items[idx][key]]
        same = [j for j, x in enumerate(items) if x[key] == items[idx][key]]
        return f"{base} {same.index(idx) + 1}"

    def cond_name(self, is_sup, idx):
        items = self.supports if is_sup else self.loads
        return items[idx].get("name") or self.default_name(is_sup, idx)

    def cond_value_text(self, item, is_sup):
        if is_sup:
            return f"{item['d']:.10g}" if item["mode"] in ("bolt", "screw") else ""
        k = item["kind"]
        return {"force": lambda: f"{item['fx']:.10g}, {item['fy']:.10g}", "pressure": lambda: f"{item['p']:.10g}",
                "traction": lambda: f"{item['tx']:.10g}, {item['ty']:.10g}"}.get(k, lambda: "")()

    def refresh_lists(self):
        self.cond_list.clear()
        t = self.cond_table
        t.blockSignals(True)
        t.setRowCount(len(self.supports) + len(self.loads))
        r = 0
        for s in self.supports:
            lab = {"fixed": "Fixed (ux = uy = 0)", "x": "ux = 0", "y": "uy = 0", "bolt": "Bolt", "screw": "Screw",
                   "contact": "Contact (one-way, frictionless)"}[s["mode"]]
            if s["mode"] in ("bolt", "screw"):
                lab += f", head width {s['d']:g}" + (", head inside" if s.get("flip") else "")
            self.cond_list.addItem(f"Support {lab}: {self.names(s['targets'])}")
            self.fill_cond_row(r, True, r, lab, s)
            r += 1
        for k, ld in enumerate(self.loads):
            uu = units.get(self.unit_name())
            if ld["kind"] == "force":
                txt, typ = f"Force ({ld['fx']:g}, {ld['fy']:g}) {uu['F']}", f"Force ({uu['F']})"
            elif ld["kind"] == "cfd":
                txt = ("Pressure from CFD" + (" (link)" if ld.get("live") else "") + (" + wall shear" if ld["include_shear"] else "") +
                       ("" if ld.get("converged", True) else " (NOT converged)"))
                typ = txt
            elif ld["kind"] == "pressure":
                txt, typ = f"Pressure {ld['p']:g} {uu['S']}", f"Pressure ({uu['S']})"
            else:
                txt, typ = f"Traction ({ld['tx']:g}, {ld['ty']:g}) {uu['S']}", f"Traction ({uu['S']})"
            self.cond_list.addItem(f"{txt}: {self.names(ld['targets'])}")
            self.fill_cond_row(r, False, k, typ, ld)
            r += 1
        t.resizeColumnsToContents()
        t.blockSignals(False)
        self.fill_probe_table()

    def fill_cond_row(self, r, is_sup, idx, typ, item):
        t = self.cond_table
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        rw = ro | Qt.ItemFlag.ItemIsEditable
        a = QTableWidgetItem(self.cond_name(is_sup, idx))
        a.setFlags(rw)
        b = QTableWidgetItem(typ)
        b.setFlags(ro)
        c = QTableWidgetItem(self.names(item["targets"]))
        c.setFlags(ro)
        val = self.cond_value_text(item, is_sup)
        d = QTableWidgetItem(val)
        d.setFlags(rw if val else ro)
        for col, it in enumerate((a, b, c, d)):
            t.setItem(r, col, it)

    def cond_item_changed(self, it):
        r, c = it.row(), it.column()
        if c == 0:
            self.rename_condition(r, it.text())
        elif c == 3:
            self.set_condition_value(r, it.text())

    def _cond_ref(self, r):
        n = len(self.supports)
        return (True, r, self.supports[r]) if r < n else (False, r - n, self.loads[r - n])

    def rename_condition(self, r, text):
        if not (0 <= r < len(self.supports) + len(self.loads)):
            return
        is_sup, idx, item = self._cond_ref(r)
        text = text.strip()
        if text and text != self.default_name(is_sup, idx):
            item["name"] = text
        else:
            item.pop("name", None)
        self.cond_table.blockSignals(True)
        self.cond_table.item(r, 0).setText(self.cond_name(is_sup, idx))
        self.cond_table.blockSignals(False)
        param = getattr(self.win, "param", None)
        if param is not None:
            try:
                param.refresh_params()
            except Exception:
                pass

    def set_condition_value(self, r, text):
        """Edits a force / pressure / traction / head width from the table.  Returns True when the value was taken."""
        if not (0 <= r < len(self.supports) + len(self.loads)):
            return False
        is_sup, idx, item = self._cond_ref(r)
        try:
            nums = [float(x) for x in text.replace(";", ",").split(",") if x.strip()]
            if is_sup and item["mode"] in ("bolt", "screw"):
                assert len(nums) == 1 and nums[0] > 0
                new = {"d": nums[0]}
            elif not is_sup and item["kind"] in ("force", "traction"):
                assert len(nums) == 2
                new = dict(zip(("fx", "fy") if item["kind"] == "force" else ("tx", "ty"), nums))
            elif not is_sup and item["kind"] == "pressure":
                assert len(nums) == 1
                new = {"p": nums[0]}
            else:
                return False
        except (AssertionError, ValueError):
            self.status("That value was not understood: give one number (or two separated by a comma) and a positive head width.")
            QTimer.singleShot(0, self.refresh_lists)
            return False
        if any(item.get(k) != v for k, v in new.items()):
            item.update(new)
            QTimer.singleShot(0, self.after_conditions)         # a different load / head width: the old result no longer applies
        return True

    def remove_condition(self):
        r = self.cond_table.currentRow()
        if r < 0:
            r = self.cond_list.currentRow()
        if r < 0:
            return
        if r < len(self.supports):
            del self.supports[r]
        else:
            del self.loads[r - len(self.supports)]
        self.after_conditions()

    # --- profile properties (ribbed panel idealised as a thin strip)
    def profile_for_solver(self):
        if not self.profile:
            return None
        st = self.profile_strip()
        return {"name": self.profile["name"], "h": st["h"], "rho": st["rho"], "c": st["c"]}

    def profile_strip(self):
        pr = self.profile
        return secp.strip(pr["A_w"], pr["I_w"], pr["c_top"], pr["c_bottom"]) if pr else None

    def update_profile_label(self):
        if not self.profile:
            self.profile_lbl.setText("No profile: the sheet is a plain solid strip.")
            return
        st = self.profile_strip()
        L = units.get(self.unit_name())["L"]
        self.profile_lbl.setText(
            f"<b>Profile '{self.profile['name']}'</b>: draw the strip in the side-view sketch with thickness <b>h = {st['h']:.5g} {L}</b>. "
            f"E is multiplied by {st['rho']:.4g} (same EA and EI as the real panel); the strengths are divided by {st['k']:.4g}. "
            "Thickness (depth) above = the panel width this model represents.")

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import profile properties", "", "Profile properties (*.profprops);;All files (*)")
        if not path:
            return
        try:
            d = secp.read(path)
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "Import profile", str(ex))
            return
        self.set_profile(d)

    def set_profile(self, d):
        """d from section_props.read (lengths in the file's unit system); converts to this tab's units."""
        try:
            lf = units.length_factor(d["units"], self.unit_name())
        except Exception:
            QMessageBox.warning(self, "Import profile", f"The unit system '{d['units']}' of the file is not known here.")
            return False
        self.profile = {"name": d.get("name", ""), "A_w": d["A_w"] * lf, "I_w": d["I_w"] * lf ** 3,
                        "c_top": d["c_top"] * lf, "c_bottom": d["c_bottom"] * lf}
        self.update_profile_label()
        self.after_conditions()                     # an old result no longer matches
        st = self.profile_strip()
        self.status(f"Profile imported: strip thickness h = {st['h']:.5g}, E x {st['rho']:.4g}, stress factor {st['k']:.4g}.")
        return True

    def clear_profile(self):
        if self.profile is not None:
            self.profile = None
            self.update_profile_label()
            self.after_conditions()

    # --- probe regions and the node probe
    def set_tool(self, mode):
        self.canvas.mode = mode
        self.canvas.drag = None
        for b_, m in ((self.b_prect, "rect"), (self.b_pcirc, "circle"), (self.b_node, "node")):
            b_.blockSignals(True)
            b_.setChecked(mode == m)
            b_.blockSignals(False)
        self.canvas.setCursor(Qt.CursorShape.CrossCursor if mode != "select" else Qt.CursorShape.ArrowCursor)
        if mode in ("rect", "circle"):
            self.status("Drag on the drawing to place the probe region (original geometry).  Esc cancels." if mode == "rect" else
                        "Drag from the centre outward to set the circle's radius.  Esc cancels.")
        elif mode == "node":
            self.status("Click near a node of the result.  Esc leaves the node probe.")
        self.canvas.update()

    def unique_probe_name(self, base, skip=None):
        names = {q["name"] for q in self.probes if q is not skip}
        if base not in names:
            return base
        k = 2
        while f"{base} {k}" in names:
            k += 1
        return f"{base} {k}"

    def add_probe(self, shape, **geo):
        q = {"name": self.unique_probe_name(f"Probe {len(self.probes) + 1}"), "shape": shape}
        q.update(geo)
        self.probes.append(q)
        self.fill_probe_table()
        self.probes_changed()
        return q

    def finish_probe_drag(self, mode, x0, y0, x1, y1):
        self.set_tool("select")
        if mode == "circle":
            r = float(np.hypot(x1 - x0, y1 - y0))
            if r * self.canvas.scale < 4:
                return
            self.add_probe("circle", cx=x0, cy=y0, r=r)
        else:
            if abs(x1 - x0) * self.canvas.scale < 4 or abs(y1 - y0) * self.canvas.scale < 4:
                return
            self.add_probe("rect", x0=min(x0, x1), y0=min(y0, y1), x1=max(x0, x1), y1=max(y0, y1))

    def probe_geo_text(self, q):
        keys = ("cx", "cy", "r") if q["shape"] == "circle" else ("x0", "y0", "x1", "y1")
        return ", ".join(f"{q[k]:.6g}" for k in keys)

    def fill_probe_table(self):
        t = self.probe_table
        t.blockSignals(True)
        t.setRowCount(len(self.probes))
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        for r, q in enumerate(self.probes):
            a = QTableWidgetItem(q["name"])
            a.setFlags(ro | Qt.ItemFlag.ItemIsEditable)
            b = QTableWidgetItem("Circle" if q["shape"] == "circle" else "Rectangle")
            b.setFlags(ro)
            c = QTableWidgetItem(self.probe_geo_text(q))
            c.setFlags(ro | Qt.ItemFlag.ItemIsEditable)
            for col, key in ((3, self.probe_fos), (4, self.probe_trig)):
                x = QTableWidgetItem("")
                x.setFlags(ro | Qt.ItemFlag.ItemIsUserCheckable)
                x.setCheckState(Qt.CheckState.Checked if key == q["name"] else Qt.CheckState.Unchecked)
                t.setItem(r, col, x)
            t.setItem(r, 0, a)
            t.setItem(r, 1, b)
            t.setItem(r, 2, c)
        t.resizeColumnsToContents()
        t.blockSignals(False)

    def probe_item_changed(self, it):
        r, c = it.row(), it.column()
        if not (0 <= r < len(self.probes)):
            return
        q = self.probes[r]
        if c == 0:
            self.rename_probe(r, it.text())
        elif c == 2:
            self.set_probe_geometry(r, it.text())
        elif c in (3, 4):
            self.mark_probe(r, "fos" if c == 3 else "trig", it.checkState() == Qt.CheckState.Checked)

    def rename_probe(self, r, text):
        q = self.probes[r]
        new = self.unique_probe_name(text.strip() or q["name"], skip=q)
        old = q["name"]
        q["name"] = new
        if self.probe_fos == old:
            self.probe_fos = new
        if self.probe_trig == old:
            self.probe_trig = new
        QTimer.singleShot(0, self.fill_probe_table)
        self.probes_changed(resolve=False)

    def set_probe_geometry(self, r, text):
        q = self.probes[r]
        keys = ("cx", "cy", "r") if q["shape"] == "circle" else ("x0", "y0", "x1", "y1")
        try:
            nums = [float(x) for x in text.replace(";", ",").split(",") if x.strip()]
            assert len(nums) == len(keys)
            if q["shape"] == "circle":
                assert nums[2] > 0
        except (AssertionError, ValueError):
            self.status("The geometry was not understood: " + ("centre x, centre y, radius (positive)" if q["shape"] == "circle"
                                                                else "x0, y0, x1, y1"))
            QTimer.singleShot(0, self.fill_probe_table)
            return False
        q.update(dict(zip(keys, nums)))
        QTimer.singleShot(0, self.fill_probe_table)
        self.probes_changed()
        return True

    def mark_probe(self, r, what, on):
        name = self.probes[r]["name"]
        if what == "fos":
            self.probe_fos = name if on else (None if self.probe_fos == name else self.probe_fos)
        else:
            self.probe_trig = name if on else (None if self.probe_trig == name else self.probe_trig)
        QTimer.singleShot(0, self.fill_probe_table)
        self.probes_changed(resolve=(what == "trig"))

    def remove_probe(self):
        r = self.probe_table.currentRow()
        if not (0 <= r < len(self.probes)):
            return
        name = self.probes[r]["name"]
        del self.probes[r]
        if self.probe_fos == name:
            self.probe_fos = None
        if self.probe_trig == name:
            self.probe_trig = None
        self.fill_probe_table()
        self.probes_changed()

    def probes_changed(self, resolve=True):
        """The factors of safety and the probe averages follow the probes at once (no new solve).  The trigger probe only matters at
        the next solve."""
        self.canvas.update()
        res = self.result
        if res is not None and self.mesh is not None:
            pf.apply_probes(res, self.mesh, self.probes, self.probe_fos, self.probe_trig)
            keep = self.field.currentIndex()
            self.show_solution(res, restored=True)
            self.field.blockSignals(True)
            self.field.setCurrentIndex(keep)
            self.field.blockSignals(False)
            self.view_changed()
            if self.canvas.node_sel is not None:
                self.show_node(self.canvas.node_sel)
        param = getattr(self.win, "param", None)
        if param is not None:
            try:
                param.refresh_params()
                param.fill_outputs()
            except Exception:
                pass

    # node probe
    def _result_nodes(self):
        r = self.result
        vm = (r.get("mesh") if r else None) or self.mesh
        pos = np.asarray(vm["nodes"])[:, :2]
        if r is not None and self.canvas.show_deformed and self.canvas.field is not None:
            pos = pos + self.canvas.def_scale * r["u"]
        return vm, pos

    def node_screen(self, idx):
        try:
            vm, pos = self._result_nodes()
            return QPointF(self.canvas.org.x() + pos[idx, 0] * self.canvas.scale, self.canvas.org.y() - pos[idx, 1] * self.canvas.scale)
        except Exception:
            return None

    def pick_node(self, sp):
        if self.result is None or self.mesh is None:
            self.status("Solve first: the node probe reads the result.")
            return
        vm, pos = self._result_nodes()
        sx = self.canvas.org.x() + pos[:, 0] * self.canvas.scale
        sy = self.canvas.org.y() - pos[:, 1] * self.canvas.scale
        d = np.hypot(sx - sp.x(), sy - sp.y())
        k = int(np.argmin(d))
        if d[k] > 40:
            self.canvas.node_sel = None
            self.node_lbl.setText("")
            self.canvas.update()
            return
        self.canvas.node_sel = k
        self.show_node(k)
        self.canvas.update()

    def node_results(self, idx):
        """-> dict of every result at node `idx` of the result mesh (element fields averaged over the elements around the node)."""
        r = self.result
        vm = r.get("mesh") or self.mesh
        tris = np.asarray(vm["tris"])
        n = len(vm["nodes"])
        cnt = np.zeros(n)
        for k in range(3):
            cnt += np.bincount(tris[:, k], minlength=n)
        out = {"index": idx, "x": float(vm["nodes"][idx][0]), "y": float(vm["nodes"][idx][1]),
               "ux": float(r["u"][idx][0]), "uy": float(r["u"][idx][1])}
        out["umag"] = float(np.hypot(out["ux"], out["uy"]))
        out["n_elems"] = int(cnt[idx])
        for key in ("sx", "sy", "txy", "vm", "s1", "s2", "tmax", "peeq"):
            arr = field_values(r, key) if key != "peeq" or "peeq" in r else None
            if arr is None or len(arr) != len(tris):
                continue
            acc = np.zeros(n)
            for k in range(3):
                acc += np.bincount(tris[:, k], weights=arr, minlength=n)
            out[key] = float(acc[idx] / cnt[idx]) if cnt[idx] > 0 else float("nan")
        return out

    def show_node(self, idx):
        try:
            nr = self.node_results(idx)
        except Exception as ex:
            self.node_lbl.setText(f"Could not read that node: {ex}")
            return
        uu = units.get(self.unit_name())
        L, S = uu["L"], uu["S"]
        lines = [f"<b>Node {nr['index']}</b> at ({nr['x']:.5g}, {nr['y']:.5g}) {L}  (original geometry)",
                 f"displacement: ux = {nr['ux']:.5g}, uy = {nr['uy']:.5g}, |u| = {nr['umag']:.5g} {L}"]
        if "sx" in nr:
            lines.append(f"stress: sx = {nr['sx']:.5g}, sy = {nr['sy']:.5g}, txy = {nr['txy']:.5g} {S}")
            lines.append(f"von Mises = {nr['vm']:.5g}, principal = {nr['s1']:.5g} / {nr['s2']:.5g}, max shear = {nr['tmax']:.5g} {S}")
        if "peeq" in nr:
            lines.append(f"plastic strain = {nr['peeq'] * 100:.4g} %")
        lines.append(f"<span style='color:#666666'>stresses: average of the {nr['n_elems']} element(s) around the node</span>")
        self.node_lbl.setText("<br>".join(lines))
        self.last_node = nr

    # --- material library and units
    def fill_materials(self, select=None):
        self.library = pm.load()
        builtin = {n for n, _, _ in pm.DEFAULTS}
        self.mat_combo.blockSignals(True)
        self.mat_combo.clear()
        self.mat_combo.addItem("(custom values)", None)
        for m_ in self.library:
            self.mat_combo.addItem(m_["name"] + ("" if m_["name"] in builtin else "   (mine)"), m_["name"])
        idx = 0
        if select is not None:
            for i in range(self.mat_combo.count()):
                if self.mat_combo.itemData(i) == select:
                    idx = i
        self.mat_combo.setCurrentIndex(idx)
        self.mat_combo.blockSignals(False)
        self.update_mat_note()

    def library_entry(self, name):
        return next((x for x in self.library if x["name"] == name), None)

    def update_mat_note(self):
        name = self.mat_combo.currentData()
        if name is None:
            txt = "Custom values."
        elif name in {n for n, _, _ in pm.DEFAULTS}:
            txt = "Typical value - check your source."
        else:
            txt = "Your own material (stored in materials.json, in MPa)."
        m_ = self.library_entry(name) if name is not None else None
        if m_ is not None and (m_.get("Sy_MPa") is None or m_.get("Su_MPa") is None):
            txt += "  No strengths are stored for this material: type the yield and ultimate strength below."
        self.mat_note.setText(txt + "  The unit system is chosen in File > Units (shared with the sketch and the CFD tab).")
        self.b_del_mat.setEnabled(name is not None and name not in {n for n, _, _ in pm.DEFAULTS})

    def material_picked(self, *_):
        name = self.mat_combo.currentData()
        m_ = self.library_entry(name) if name is not None else None
        if m_ is not None:
            self.e_E.setText(f"{pm.from_mpa(m_['E_MPa'], self.unit_combo.currentText()):.10g}")
            self.e_nu.setText(f"{m_['nu']:.6g}")
            if m_.get("Sy_MPa") is not None and m_.get("Su_MPa") is not None:
                self.e_sy.setText(f"{pm.from_mpa(m_['Sy_MPa'], self.unit_combo.currentText()):.10g}")
                self.e_su.setText(f"{pm.from_mpa(m_['Su_MPa'], self.unit_combo.currentText()):.10g}")
            if m_.get("eps_u") is not None:
                self.e_eu.setText(f"{100 * m_['eps_u']:.6g}")
        self.update_mat_note()

    def unit_changed(self, *_):
        new, old = self.unit_combo.currentText(), self.cur_unit
        name = self.mat_combo.currentData()
        m_ = self.library_entry(name) if name is not None else None
        if m_ is not None:
            self.e_E.setText(f"{pm.from_mpa(m_['E_MPa'], new):.10g}")
            if m_.get("Sy_MPa") is not None and m_.get("Su_MPa") is not None:
                self.e_sy.setText(f"{pm.from_mpa(m_['Sy_MPa'], new):.10g}")
                self.e_su.setText(f"{pm.from_mpa(m_['Su_MPa'], new):.10g}")
            else:
                for w in (self.e_sy, self.e_su):
                    try:
                        w.setText(f"{pm.from_mpa(pm.to_mpa(float(w.text()), old), new):.10g}")
                    except ValueError:
                        pass
        else:
            for w in (self.e_E, self.e_sy, self.e_su):
                try:
                    v = float(w.text())
                    w.setText(f"{pm.from_mpa(pm.to_mpa(v, old), new):.10g}")
                except ValueError:
                    pass
        self.cur_unit = new

    def solver_boxes(self, *_):
        """The triggers only matter when both solvers are ticked (automatic switch)."""
        both = self.cb_lin.isChecked() and self.cb_nl.isChecked()
        for w in (self.e_nld, self.e_nly):
            w.setEnabled(both)
        self.lbl_nld.setEnabled(both)

    def set_custom(self, *_):
        if self.mat_combo.currentIndex() != 0:
            self.mat_combo.blockSignals(True)
            self.mat_combo.setCurrentIndex(0)
            self.mat_combo.blockSignals(False)
            self.update_mat_note()

    def stress_unit(self):
        return self.unit_combo.currentText()

    def add_material(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add a material")
        form = QFormLayout(dlg)
        name = QLineEdit()
        E = QLineEdit(self.e_E.text())
        unit = QComboBox()
        for u in pm.UNITS:
            unit.addItem(u)
        unit.setCurrentText(self.unit_combo.currentText())
        nu = QLineEdit(self.e_nu.text())
        SY, SU, EU = QLineEdit(self.e_sy.text()), QLineEdit(self.e_su.text()), QLineEdit(self.e_eu.text())
        form.addRow("Name", name)
        form.addRow("E", E)
        form.addRow("E is in", unit)
        form.addRow("Poisson's ratio", nu)
        form.addRow("Yield strength (same unit, 0 = brittle)", SY)
        form.addRow("Ultimate strength (same unit)", SU)
        form.addRow("Plastic strain at ultimate (%)", EU)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        nm = name.text().strip()
        try:
            e_val, nu_val = float(E.text()), float(nu.text())
            sy_val, su_val = float(SY.text() or 0), float(SU.text() or 0)
            eu_val = float(EU.text()) / 100.0 if EU.text().strip() else None
        except ValueError:
            QMessageBox.warning(self, "Add a material", "E, Poisson's ratio and the strengths must be numbers.")
            return
        if not nm or e_val <= 0 or not (-1 < nu_val < 0.5 + 1e-12):
            QMessageBox.warning(self, "Add a material", "Give a name, a positive E and -1 < nu < 0.5.")
            return
        if any(x["name"].lower() == nm.lower() for x in self.library):
            QMessageBox.warning(self, "Add a material", "A material with that name already exists.")
            return
        lib = list(self.library) + [{"name": nm, "E_MPa": pm.to_mpa(e_val, unit.currentText()), "nu": nu_val,
                                          "Sy_MPa": pm.to_mpa(max(sy_val, 0.0), unit.currentText()),
                                          "Su_MPa": pm.to_mpa(max(su_val, 0.0), unit.currentText()),
                                          **({"eps_u": eu_val} if eu_val is not None else {})}]
        try:
            pm.save(lib)
        except OSError as ex:
            QMessageBox.warning(self, "Add a material", f"Could not write {pm.library_path()}:\n{ex}")
            return
        self.fill_materials(select=nm)
        self.material_picked()

    def delete_material(self):
        name = self.mat_combo.currentData()
        if name is None or name in {n for n, _, _ in pm.DEFAULTS}:
            return
        if QMessageBox.question(self, "Delete material", f"Delete '{name}' from materials.json?") != QMessageBox.StandardButton.Yes:
            return
        try:
            pm.save([x for x in self.library if x["name"] != name])
        except OSError as ex:
            QMessageBox.warning(self, "Delete material", f"Could not write {pm.library_path()}:\n{ex}")
            return
        self.fill_materials()

    # --- animation (a ramp of the finished linear result)
    def anim_toggled(self, on):
        self.anim_box.setVisible(on)
        if not on:
            self.anim_stop()
            self.canvas.invalidate()

    def anim_dropped(self):
        self.anim_timer.stop()

    def anim_play(self):
        cv = self.canvas
        if self.result is None or cv.field is None:
            QMessageBox.information(self, "Animate", "Solve first and choose a result field to colour by.")
            return
        try:
            n = int(float(self.e_frames.text()))
            dur = float(self.e_dur.text())
        except ValueError:
            QMessageBox.warning(self, "Animate", "Frames and duration must be numbers.")
            return
        if not (2 <= n <= 300) or dur <= 0:
            QMessageBox.warning(self, "Animate", "Use 2 to 300 frames and a positive duration.")
            return
        if cv.anim_frames is None or len(cv.anim_frames) != n:
            if not self.render_frames(n):
                return
        self.anim_timer.stop()
        cv.anim_idx = 0
        self.anim_dir = 1
        cv.update()
        self.anim_timer.start(max(10, int(dur * 1000 / n)))

    def render_frames(self, n):
        cv = self.canvas
        dlg = QDialog(self)
        dlg.setWindowTitle("Drawing the animation frames")
        dlg.setModal(True)
        dlg.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        dlg.setMinimumWidth(380)
        lay = QVBoxLayout(dlg)
        lbl = QLabel("Starting...")
        bar = QProgressBar()
        bar.setRange(0, n)
        btn = QPushButton("Cancel")
        for w in (lbl, bar, btn):
            lay.addWidget(w)
        state = {"stop": False}
        btn.clicked.connect(lambda: state.update(stop=True))
        dlg.show()
        frames = []
        for k in range(n):
            if state["stop"]:
                dlg.close()
                self.status("Animation cancelled.")
                return False
            lbl.setText(f"Frame {k + 1} of {n}")
            frames.append(cv.render_picture(True, k / (n - 1)))
            bar.setValue(k + 1)
            QApplication.processEvents()
        dlg.close()
        cv.anim_frames = frames
        return True

    def anim_step(self):
        cv = self.canvas
        if cv.anim_frames is None:
            self.anim_timer.stop()
            return
        n = len(cv.anim_frames)
        i = cv.anim_idx + self.anim_dir
        mode = self.loop_combo.currentIndex()
        if i >= n:
            if mode == 0:
                self.anim_timer.stop()
                i = n - 1
            elif mode == 1:
                i = 0
            else:
                self.anim_dir = -1
                i = max(0, n - 2)
        elif i < 0:
            self.anim_dir = 1
            i = min(1, n - 1)
        cv.anim_idx = i
        cv.update()

    def anim_stop(self):
        self.anim_timer.stop()

    # --- reading the inputs
    def read_material(self):
        try:
            E, nu, t = float(self.e_E.text()), float(self.e_nu.text()), float(self.e_t.text())
        except ValueError:
            raise pf.ModelError("E, Poisson's ratio and thickness must be numbers.")
        def opt(w, name):
            tx = w.text().strip()
            if not tx:
                return None
            try:
                return float(tx)
            except ValueError:
                raise pf.ModelError(f"{name} must be a number (or empty).")
        sy, su = opt(self.e_sy, "Yield strength") or 0.0, opt(self.e_su, "Ultimate strength") or 0.0
        eu = opt(self.e_eu, "Plastic strain at ultimate")
        eu = 0.10 if eu is None else eu / 100.0
        if sy < 0 or su < 0 or eu < 0:
            raise pf.ModelError("Yield strength, ultimate strength and plastic strain at ultimate cannot be negative.")
        if sy > 0 and su > 0 and su < sy:
            raise pf.ModelError("The ultimate strength cannot be smaller than the yield strength.")
        if not self.cb_lin.isChecked() and not self.cb_nl.isChecked():
            raise pf.ModelError("Tick the linear solver, the nonlinear solver, or both.")
        ny = opt(self.e_nly, "Stress trigger")
        return {"E": E, "nu": nu, "t": t, "mode": "strain" if self.rb_strain.isChecked() else "stress",
                "order": 1 if self.order_combo.currentIndex() == 1 else 2,
                "sy": sy, "su": su, "eps_u": eu, "nl_on": self.cb_nl.isChecked(), "lin_on": self.cb_lin.isChecked(),
                "nl_disp": opt(self.e_nld, "Displacement trigger"), "nl_yield": None if ny is None else ny / 100.0,
                "probes": [dict(q) for q in self.probes], "probe_fos": self.probe_fos, "probe_trig": self.probe_trig,
                "profile": self.profile_for_solver(), "region_mats": self.region_mats_in_units()}

    def restyle(self):
        """The shared colour scheme changed: draw again."""
        try:
            self.canvas.invalidate()
            self.canvas.update()
        except Exception:
            pass

    def region_mats_in_units(self):
        """The materials of the regions (stored in MPa) in the tab's unit system, for the solver (None when there are none)."""
        rm = getattr(self, "region_mats", None)
        if not rm:
            return None
        u = self.unit_combo.currentText()
        return {fid: {"E": pm.from_mpa(m_["E_MPa"], u), "nu": m_["nu"], "sy": pm.from_mpa(m_.get("Sy_MPa") or 0.0, u),
                      "su": pm.from_mpa(m_.get("Su_MPa") or 0.0, u)} for fid, m_ in rm.items()}

    # --- mesh and solve
    def run_task(self, title, fn):
        dlg = TaskDialog(self, title, fn)
        kind, data = dlg.run() or ("cancelled", None)
        if kind == "user":
            QMessageBox.warning(self, title, data)
        elif kind == "bug":
            QMessageBox.warning(self, title, "The program hit an error. Please copy this and send it to me:\n\n" + data)
        return kind, data

    def run_mesh(self):
        try:
            h = float(self.e_h.text())
        except ValueError:
            QMessageBox.warning(self, "Mesh", "The element size must be a number.")
            return
        included = {f["id"] for f in self.geom["faces"] if f["included"]}
        m, g = self.model, self.geom
        kind, data = self.run_task("Meshing", lambda progress, cancel: pg.mesh_faces(m, g, included, h, progress, cancel))
        if kind != "ok":
            self.status("Meshing cancelled." if kind == "cancelled" else "Meshing failed.")
            return
        self.mesh = data
        self.result = None
        self.canvas.field = None
        self.field.setCurrentIndex(0)
        s = data["stats"]
        self.status(f"Mesh: {s['n_nodes']} nodes, {s['n_tris']} triangles (element size {h:g}); "
                    f"smallest angle {s['angle_min']:.1f} deg, worst aspect ratio {s['aspect_max']:.2f}.")
        self.canvas.invalidate()
        self.enable_buttons()

    def run_solve(self):
        try:
            mat = self.read_material()
        except pf.ModelError as ex:
            QMessageBox.warning(self, "Solve", str(ex))
            return
        mesh, sup, lds = self.mesh, [dict(s) for s in self.supports], [dict(l) for l in self.loads]
        try:
            lds = self.resolved_loads(lds)
        except pf.ModelError as ex:
            QMessageBox.warning(self, "Solve", str(ex))
            return
        unconv = any(l["kind"] == "cfd" and not l.get("converged", True) for l in lds)
        if self.cb_auto.isChecked():
            self.run_solve_auto(mat, mesh, sup, lds, unconv)
            return
        kind, data = self.run_task("Solving", lambda progress, cancel: pf.solve(mesh, mat, sup, lds, progress, cancel))
        if kind != "ok":
            self.status("Solve cancelled." if kind == "cancelled" else "Solve failed.")
            return
        self.last_mat = mat
        data["cfd_unconverged"] = unconv
        self.show_solution(data)

    def run_solve_auto(self, mat, mesh, sup, lds, unconv=False):
        """Solve, refine where the stress changes fastest, solve again - until the result stops changing or a limit is reached."""
        try:
            passes, max_tris, h = int(float(self.e_passes.text())), int(float(self.e_maxtris.text())), float(self.e_h.text())
            if passes < 1 or max_tris < 100:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Solve", "Maximum refinement passes must be a whole number of at least 1, and the maximum "
                                "number of triangles a number of at least 100.")
            return
        included = {f["id"] for f in self.geom["faces"] if f["included"]}
        m, g = self.model, self.geom
        kind, data = self.run_task("Solving with auto-refinement", lambda progress, cancel: prefine.fea_auto(
            m, g, included, h, mesh, mat, sup, lds, passes, max_tris, progress, cancel))
        if kind != "ok":
            self.status("Solve cancelled." if kind == "cancelled" else "Solve failed.")
            return
        self.last_mat = mat
        self.mesh = data["mesh"]
        self.canvas.field = None
        self.field.setCurrentIndex(0)
        self.canvas.invalidate()
        data["result"]["refine"] = {"log": data["log"], "reason": data["reason"]}
        data["result"]["cfd_unconverged"] = unconv
        self.show_solution(data["result"])
        s = self.mesh["stats"]
        self.status(f"Auto-refined to {s['n_tris']:,} triangles in {len(data['log'])} pass(es): "
                    f"{prefine.summary_lines(data['log'], data['reason'], 'fea')[1]}")
        self.enable_buttons()

    def load_case(self, mesh, result):
        """Shows a stored result (from the Parameterization tab) on the canvas."""
        self.mesh = mesh
        self.last_mat = result.get("mat", getattr(self, "last_mat", None))
        self.canvas.field = None
        self.field.blockSignals(True)
        self.field.setCurrentIndex(0)
        self.field.blockSignals(False)
        self.canvas.invalidate()
        self.show_solution(result, restored=True)
        self.enable_buttons()

    def show_solution(self, data, restored=False):
        """Makes a (new or restored) result the one on screen."""
        self.result = data
        umax = float(np.max(np.hypot(data["u"][:, 0], data["u"][:, 1])))
        xs, ys = self.mesh["nodes"][:, 0], self.mesh["nodes"][:, 1]
        size = max(xs.max() - xs.min(), ys.max() - ys.min())
        self.auto_def = 0.05 * size / umax if umax > 0 else 1.0
        self.field.blockSignals(True)
        idx = next(i for i in range(self.field.count()) if self.field.itemData(i) == "vm")
        self.field.setCurrentIndex(idx)
        self.field.blockSignals(False)
        self.view_changed()
        eq = data["equilibrium"]
        uu = units.get(self.unit_name())
        self.res_lbl.setText(f"max |u| = {umax:.5g} {uu['L']}<br>max von Mises = {float(np.max(data['vm'])):.5g} {uu['S']}<br>"
                             f"solve residual = {data['residual']:.2e}<br>"
                             f"equilibrium: sum Fx = {eq['sum_fx']:.3e}, sum Fy = {eq['sum_fy']:.3e}, sum Mz = {eq['sum_mz']:.3e}")
        if data.get("solver") == "nonlinear":
            nl = data.get("nl") or {}
            ok = nl.get("converged", True)
            col = "#1a7a1a" if ok else "#b00020"
            self.res_lbl.setText(self.res_lbl.text() + "<br>(large displacements: the force balance above is taken on the undeformed "
                                 "shape, so sum Mz need not be zero)")
            self.res_lbl.setText(self.res_lbl.text() + f"<br><b style='color:{col}'>Solver: NONLINEAR</b> ({data.get('trigger', '')})<br>"
                                 f"max plastic strain = {float(np.max(data['peeq'])) * 100:.4g} %"
                                 + ("" if ok else f"<br><b style='color:#b00020'>Did not fully converge: only {100 * nl.get('load_fraction', 0):.1f} % "
                                    "of the load was reached. Treat this result with care.</b>"))
        elif data.get("solver"):
            self.res_lbl.setText(self.res_lbl.text() + "<br>Solver: linear")
        fy_, fu_ = data.get("fos_yield"), data.get("fos_ult")
        if fy_ is not None or fu_ is not None:
            self.res_lbl.setText(self.res_lbl.text() + "<br><b>Factor of safety</b>: yield = " +
                                 (f"{fy_:.4g}" if fy_ is not None else "n/a") + ", ultimate = " + (f"{fu_:.4g}" if fu_ is not None else "n/a"))
        pr_ = data.get("probes") or []
        if pr_:
            rows = []
            for q in pr_:
                mark = " (feeds the factors of safety)" if q["name"] == data.get("fos_probe") else ""
                rows.append(f"{q['name']}: " + ("no element inside" if q["avg_vm"] is None else
                                                 f"average von Mises {q['avg_vm']:.5g}, peak {q['max_vm']:.5g} {uu['S']}") + mark)
            self.res_lbl.setText(self.res_lbl.text() + "<br><b>Probes</b><br>" + "<br>".join(rows))
        if data.get("fos_probe") and data.get("fos_yield_peak") is not None:
            self.res_lbl.setText(self.res_lbl.text() + f"<br>(peak-based factor of safety, yield = {data['fos_yield_peak']:.4g})")
        fz = data.get("fasteners") or []
        if fz:
            fu = uu["F"]
            rows = []
            for x in fz:
                nm = {"bolt": "Bolt", "screw": "Screw", "contact": "Contact"}[x["mode"]]
                rows.append(f"{nm} {x['label']}: " + ("contact force" if x["mode"] == "contact" else "pull-off") +
                            f" {x['axial']:.5g} {fu}, shear {x['shear']:.5g} {fu}")
            self.res_lbl.setText(self.res_lbl.text() + "<br><br><b>Fasteners / contact</b> (force per slice of depth "
                                 f"{data['mat']['t']:g})<br>" + "<br>".join(rows))
        scale = max(abs(eq.get("applied", {}).get("fx", 0.0)), abs(eq.get("applied", {}).get("fy", 0.0)), 1e-300)
        if data["residual"] > 1e-6 or max(abs(eq["sum_fx"]), abs(eq["sum_fy"])) > 1e-6 * scale:
            self.res_lbl.setText(self.res_lbl.text() + "<br><b style='color:#b00020'>WARNING: the residual or the force balance is "
                                 "too large, so this result cannot be trusted. Check that the supports stop all rigid-body "
                                 "motion.</b>")
        if data.get("cfd_unconverged"):
            self.res_lbl.setText(self.res_lbl.text() + "<br><b style='color:#b00020'>The CFD pressure used for this solution came from a CFD "
                                 "run that was NOT converged (its last time step). Treat the result accordingly.</b>")
        rf = data.get("refine")
        if rf:
            lines, why = prefine.summary_lines(rf["log"], rf["reason"], "fea")
            col = "#1a7a1a" if rf["reason"] == "converged" else "#b36b00"
            self.res_lbl.setText(self.res_lbl.text() + "<br><br><b>Auto-refinement</b><br>" + "<br>".join(lines) +
                                 f"<br><b style='color:{col}'>{why}</b>")
        if not restored:
            self.status(f"Solved in {data['total_time']:.2f} s.  Deformation scale (auto) = {self.auto_def:.4g}.")

    # --- save / restore with the sketch file
    INPUTS = ("e_E", "e_nu", "e_t", "e_h", "order_combo", "rb_strain", "rb_stress", "unit_combo", "cb_def", "cb_mesh", "e_def", "cb_anim",
              "e_frames", "e_dur", "loop_combo", "cb_auto", "e_passes", "e_maxtris",
              "e_sy", "e_su", "e_eu", "cb_lin", "cb_nl", "e_nld", "e_nly")

    def export_state(self):
        return {"model_json": self.model.to_json(), "source": getattr(self, "source", ""),
                "inputs": pstore.get_inputs(self, self.INPUTS), "cur_unit": self.cur_unit, "material": self.mat_combo.currentData(),
                "faces_included": [bool(f["included"]) for f in self.geom["faces"]],
                "supports": self.supports, "loads": self.loads, "mesh": self.mesh, "result": self.result,
                "probes": [dict(q) for q in self.probes], "probe_fos": self.probe_fos, "probe_trig": self.probe_trig,
                "profile": dict(self.profile) if self.profile else None,
                "last_mat": getattr(self, "last_mat", None), "auto_def": getattr(self, "auto_def", None),
                "field": self.field.currentData(), "sketch_id": getattr(self, "sketch_id", None),
                "region_mats": getattr(self, "region_mats", {}), "region_names": getattr(self, "region_names", {})}

    def import_state(self, st, out_of_date=False):
        m = sc.Model()
        m.from_json(st["model_json"])
        self.set_model(m, st.get("source") or "the saved sketch")
        self.sketch_id = st.get("sketch_id")
        for f, inc in zip(self.geom["faces"], st.get("faces_included", [])):
            f["included"] = bool(inc)
        self.region_mats, self.region_names = dict(st.get("region_mats") or {}), dict(st.get("region_names") or {})
        self.fill_regions()
        pstore.set_inputs(self, st.get("inputs", {}))
        self.solver_boxes()
        self.auto_box.setVisible(self.cb_auto.isChecked())
        self.cur_unit = st.get("cur_unit", self.unit_combo.currentText())
        self.mat_combo.blockSignals(True)
        i = self.mat_combo.findData(st.get("material"))
        self.mat_combo.setCurrentIndex(i if i >= 0 else max(0, self.mat_combo.findData(None)))
        self.mat_combo.blockSignals(False)
        self.update_mat_note()
        self.supports, self.loads = st.get("supports", []), st.get("loads", [])
        self.probes, self.probe_fos, self.probe_trig = [dict(q) for q in st.get("probes", [])], st.get("probe_fos"), st.get("probe_trig")
        self.profile = dict(st["profile"]) if st.get("profile") else None
        self.update_profile_label()
        self.canvas.node_sel = None
        self.node_lbl.setText("")
        self.refresh_lists()
        self.mesh = st.get("mesh")
        if self.mesh is not None:
            s_ = self.mesh["stats"]
            self.status(f"Restored the saved mesh ({s_['n_nodes']} nodes, {s_['n_tris']} triangles).")
        self.result = None
        self.canvas.field = None
        if st.get("last_mat") is not None:
            self.last_mat = st["last_mat"]
        if st.get("result") is not None and self.mesh is not None:
            if st.get("auto_def") is not None:
                self.auto_def = st["auto_def"]
            self.show_solution(st["result"], restored=True)
            i = self.field.findData(st.get("field"))
            if i >= 0:
                self.field.blockSignals(True)
                self.field.setCurrentIndex(i)
                self.field.blockSignals(False)
            self.status("Restored the saved FEA setup and result.")
        elif self.mesh is not None:
            self.status("Restored the saved FEA setup and mesh (not solved).")
        else:
            self.status("Restored the saved FEA setup (not meshed).")
        self.anim_box.setVisible(self.cb_anim.isChecked())
        self.view_changed()
        self.canvas.fit()
        self.enable_buttons()
        if out_of_date:
            self.mark_out_of_date()

    def change_units(self, old, new, convert):
        """The program's unit system changed: convert this tab's copy of the sketch, its numbers and its loads.
        With a conversion the mesh and result are cleared (they are in the old numbers); a relabel keeps them."""
        st = self.export_state()
        dropped = sum(1 for ld in st.get("loads", []) if ld["kind"] == "cfd" and not ld.get("live"))
        st = pstore.convert_fea_state(st, old, new, convert)
        self.import_state(st)
        if convert and getattr(self, "last_fastener_d", None):
            self.last_fastener_d *= units.length_factor(old, new)
        msg = []
        if convert and dropped:
            msg.append(f"{dropped} pressure-from-CFD load(s) were removed; add them again after the CFD is solved in the new units.")
        return " ".join(msg)

    def mark_out_of_date(self):
        txt = ("<b style='color:#b36b00'>OUT OF DATE: the sketch has changed since this was saved. This tab still shows the "
               "older copy. Import the sketch again to update it (that clears the mesh and result).</b>")
        self.info.setText(txt + "<br>" + self.info.text())

    def clear_state(self):
        """Back to the freshly started tab (used when another project is opened)."""
        self.sketch_id = None
        self.model = self.geom = self.mesh = self.result = None
        self.supports, self.loads = [], []
        self.probes, self.probe_fos, self.probe_trig = [], None, None
        self.profile = None
        self.update_profile_label()
        self.canvas.node_sel = None
        self.canvas.sel = []
        self.canvas.field = None
        self.field.blockSignals(True)
        self.field.setCurrentIndex(0)
        self.field.blockSignals(False)
        self.regions.clear()
        self.refresh_lists()
        self.info.setText("Nothing imported yet.")
        self.res_lbl.setText("")
        self.canvas.invalidate()
        self.enable_buttons()

    def view_changed(self, *_):
        cv = self.canvas
        cv.field = self.field.currentData()
        cv.show_deformed = self.cb_def.isChecked()
        cv.show_mesh = self.cb_mesh.isChecked()
        txt = self.e_def.text().strip()
        try:
            cv.def_scale = float(txt) if txt else getattr(self, "auto_def", 1.0)
        except ValueError:
            cv.def_scale = getattr(self, "auto_def", 1.0)
        cv.invalidate()

    # --- diagnostics
    def show_diag(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Diagnostics report")
        dlg.resize(780, 620)
        lay = QVBoxLayout(dlg)
        box = QTextEdit()
        box.setReadOnly(True)
        box.setFont(QFont("Consolas", 9))
        box.setPlainText(self.diagnostics_text())
        lay.addWidget(box)
        row = QHBoxLayout()
        b = QPushButton("Copy to clipboard")
        b.clicked.connect(lambda: QGuiApplication.clipboard().setText(box.toPlainText()))
        row.addWidget(b)
        b = QPushButton("Save as text file...")

        def save():
            path, _ = QFileDialog.getSaveFileName(dlg, "Save report", "physics_report.txt", "Text (*.txt)")
            if path:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(box.toPlainText())
        b.clicked.connect(save)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        dlg.exec()

    def diagnostics_text(self):
        L = []
        add = L.append
        add("PHYSICS CALC - DIAGNOSTICS")
        add(time.strftime("%Y-%m-%d %H:%M:%S"))
        add(f"python {sys.version.split()[0]} on {platform.platform()}")
        for n, (v, t) in self.deps.items():
            add(f"  {n}: {v if v else 'NOT AVAILABLE  ' + t}")
        if self.geom is None:
            add("\nNothing imported.")
            return "\n".join(L)
        g, m = self.geom, self.model
        add("\n== Imported sketch ==")
        add(f"source: {getattr(self, 'source', '?')}")
        add(f"points {len(m.pts)}, lines {len(m.lns)}, arcs {len(m.ars)}, circles {len(m.cis)}, "
            f"construction items {len(m.constr)} (ignored)")
        kinds = {}
        for e in g["edges"]:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        add(f"edges used for regions: {kinds}")
        add(f"edges not in a closed loop (ignored): {[f'{KIND_NAME[k]} {i}' for k, i in g['pruned']] or 'none'}")
        add("possible gaps (ends that almost touch): " + ("none" if not g.get("gaps") else "; ".join(pg.gap_text(x) for x in g["gaps"][:10])))
        add("edge crossings: " + ("none" if not g["crossings"] else "; ".join(
            f"{KIND_NAME[a[0]]} {a[1]} x {KIND_NAME[b[0]]} {b[1]} at ({p[0]:.5g}, {p[1]:.5g})" for a, b, p in g["crossings"])))
        add(f"connected outlines: {g['n_components']}")
        add("regions:")
        for f in g["faces"]:
            add(f"  Region {f['id'] + 1}: gross area {f['area']:.8g}, net area {f['net_area']:.8g}, nesting {f['depth']}, "
                f"holes {len(f['holes'])}, {'MATERIAL' if f['included'] else 'off'}")
        add("\n== Setup ==")
        try:
            mat = self.read_material()
            add(f"analysis: plane {mat['mode']}, E = {mat['E']:g} ({self.unit_combo.currentText()}), nu = {mat['nu']:g}, "
                f"thickness = {mat['t']:g}, material: {self.mat_combo.currentData() or 'custom values'}")
        except pf.ModelError as ex:
            add(f"material: {ex}")
        add(f"element size: {self.e_h.text()}")
        add("supports:")
        for s in self.supports:
            add(f"  {s['mode']}: {self.names(s['targets'])}")
        add("loads:")
        for ld in self.loads:
            if ld["kind"] == "cfd":
                add(f"  CFD pressure (wall shear {'included' if ld['include_shear'] else 'not included'}, "
                    + ("link to the CFD result at solve time" if ld.get("live") else
                       f"CFD result {'converged' if ld.get('converged', True) else 'NOT converged'}") + "):")
                for pr in ld["pairs"]:
                    if "table" not in pr:
                        add(f"    FEA {KIND_NAME[pr['target'][0]]} {pr['target'][1]} <- CFD {KIND_NAME[pr['source'][0]]} {pr['source'][1]}")
                        continue
                    tb = pr["table"]
                    add(f"    FEA {KIND_NAME[pr['target'][0]]} {pr['target'][1]} <- CFD {KIND_NAME[pr['source'][0]]} {pr['source'][1]}: "
                        f"{len(tb['L'])} CFD segments, pressure {float(min(tb['p_a'].min(), tb['p_b'].min())):.6g} .. "
                        f"{float(max(tb['p_a'].max(), tb['p_b'].max())):.6g} Pa, factor to this tab's units {pr['factor']:.6g}")
                continue
            vals = {k: v for k, v in ld.items() if k not in ("targets", "kind")}
            add(f"  {ld['kind']} {vals}: {self.names(ld['targets'])}")
        if self.mesh is None:
            add("\nNo mesh yet.")
            return "\n".join(L)
        s = self.mesh["stats"]
        add("\n== Mesh ==")
        add(f"gmsh {s.get('gmsh', '?')}, algorithm {s['algorithm']}, requested element size {s['h']:g}")
        add(f"nodes {s['n_nodes']}, triangles {s['n_tris']}, regions meshed {[i + 1 for i in self.mesh['faces']]}")
        add(f"edge length min/max: {s['edge_min']:.6g} / {s['edge_max']:.6g}")
        add(f"triangle area min/mean/max: {s['area_min']:.6g} / {s['area_mean']:.6g} / {s['area_max']:.6g}")
        add(f"angle min/max: {s['angle_min']:.2f} / {s['angle_max']:.2f} deg")
        add(f"aspect ratio mean/max: {s['aspect_mean']:.3f} / {s['aspect_max']:.3f}   (1 = equilateral)")
        add(f"degenerate triangles: {s['n_degenerate']}   triangles re-oriented: {s['n_flipped']}")
        add("mesh edges / nodes on each sketch object used by supports and loads:")
        used = {t for s_ in self.supports for t in s_["targets"]} | {t for l in self.loads for t in l["targets"]}
        for k, i in sorted(used):
            segs = self.mesh["curve_segs"].get((k, i))
            if k == "pt":
                add(f"  {KIND_NAME[k]} {i}: node {self.mesh['point_node'].get(i, 'NONE')}")
            else:
                add(f"  {KIND_NAME[k]} {i}: {0 if segs is None else len(segs)} edges")
        if self.result is None:
            add("\nNot solved yet.")
            return "\n".join(L)
        r = self.result
        eq = r["equilibrium"]
        add("\n== Solution ==")
        add(f"degrees of freedom {r['n_dof']} (fixed {r['n_fixed']}), stiffness nonzeros {r['nnz']}")
        add(f"point forces applied at {r['n_point_forces']} node(s), edge loads on {r['n_edge_loads']} element edge(s)")
        add(f"solve residual |K u - f| / (|K| |u| + |f|) (free dofs, backward error) = {r['residual']:.3e}")
        add("equilibrium (applied + support reactions should be 0):")
        add(f"  applied   Fx {eq['applied']['fx']:.8g}  Fy {eq['applied']['fy']:.8g}  Mz(origin) {eq['applied']['mz']:.8g}")
        add(f"  reactions Fx {eq['reactions']['fx']:.8g}  Fy {eq['reactions']['fy']:.8g}  Mz(origin) {eq['reactions']['mz']:.8g}")
        add(f"  sum       Fx {eq['sum_fx']:.3e}  Fy {eq['sum_fy']:.3e}  Mz {eq['sum_mz']:.3e}")
        add(f"strain energy 1/2 u.f = {r['energy']:.8g}")
        add("reactions per support object (force exerted by the support on the body):")
        R = r["reaction_on_body"]
        vmesh = r.get("mesh") or self.mesh
        for sup in self.supports:
            if sup["mode"] in ("bolt", "screw", "contact"):
                continue
            for k, i in sup["targets"]:
                ns = pf.entity_nodes(vmesh, k, i)
                rx = float(sum(R[2 * n] for n in ns))
                ry = float(sum(R[2 * n + 1] for n in ns))
                add(f"  {KIND_NAME[k]} {i} ({sup['mode']}): Rx {rx:.8g}  Ry {ry:.8g}")
        u = r["u"]
        add(f"displacement: max |u| {float(np.max(np.hypot(u[:, 0], u[:, 1]))):.8g}, "
            f"ux [{float(u[:, 0].min()):.6g}, {float(u[:, 0].max()):.6g}], uy [{float(u[:, 1].min()):.6g}, {float(u[:, 1].max()):.6g}]")
        if r.get("fasteners"):
            add("bolts, screws and contact supports (force the fastener exerts on the sheet; pull-off = along the head direction, "
                "per slice of depth t = %g, and per unit depth):" % r["mat"]["t"])
            for fz in r["fasteners"]:
                nm = {"bolt": "bolt", "screw": "screw", "contact": "contact"}[fz["mode"]]
                what = "contact force" if fz["mode"] == "contact" else "pull-off"
                add(f"  {nm} {fz['label']}" + (f" (head width {fz['d']:g})" if fz["d"] else "") +
                    f": {what} {fz['axial']:.8g}, shear {fz['shear']:.8g}, Rx {fz['Rx']:.8g}, Ry {fz['Ry']:.8g}; "
                    f"{fz['n_holding']} of {fz['n_nodes']} nodes carrying load; per unit depth: {what} {fz['per_depth']['axial']:.6g}, "
                    f"shear {fz['per_depth']['shear']:.6g}")
            ow = r.get("oneway") or {}
            if ow.get("oneway"):
                add(f"  one-way supports: {ow['oneway']} node(s), {ow['released']} released, {ow['iterations']} iteration(s)")
        add(f"elements: {'quadratic 6-node (stress shown on four small triangles per element)' if r.get('order') == 2 else 'linear 3-node'}")
        tris, nodes = vmesh["tris"], vmesh["nodes"]
        add("element stresses (raw, not averaged):  min / max   [location of max: element centroid]")
        for name, key, kind in FIELDS:
            if kind != "elem":
                continue
            v = r[key]
            imax = int(np.argmax(v))
            c = nodes[tris[imax]].mean(axis=0)
            add(f"  {name}: {float(v.min()):.6g} / {float(v.max()):.6g}   at ({c[0]:.5g}, {c[1]:.5g})")
        if r["notes"]:
            add("notes from the setup:")
            for n in sorted(set(r["notes"])):
                add("  " + n)
        add("linear solver: " + psolve.status()[1] + ("   (last solve used " + psolve.last_used() + ")" if psolve.last_used() else ""))
        add(f"timing: assemble {r['times'].get('assemble', 0):.3f} s, solve {r['times'].get('solve', 0):.3f} s, total {r['total_time']:.3f} s")
        return "\n".join(L)
