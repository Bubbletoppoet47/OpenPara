"""File > Settings: typed values (no sliders), in sections, with a small live picture for the drawing settings."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

import settings
import unitctl

INK, SOFT, ACC, BAD, FACE = QColor("#1f2933"), QColor("#b8c2d0"), QColor("#2f6fdd"), QColor("#d03030"), QColor("#e9eef6")


# ------------------------------------------------------------------------------------------------------------ the pictures
class Preview(QWidget):
    """Base of the small pictures: a framed area of fixed size (no text under it)."""
    W, H = 280, 150

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.W, self.H)

    def paint_frame(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#ffffff"))
        p.setPen(QPen(QColor("#c8d0dc"), 1))
        p.drawRect(0, 0, self.W - 1, self.H - 1)


def _chord_dist(a, b, m):
    ab = (b[0] - a[0], b[1] - a[1])
    am = (m[0] - a[0], m[1] - a[1])
    n2 = ab[0] ** 2 + ab[1] ** 2
    t = 0.0 if n2 < 1e-18 else min(1.0, max(0.0, (am[0] * ab[0] + am[1] * ab[1]) / n2))
    return math.hypot(am[0] - ab[0] * t, am[1] - ab[1] * t)


class CurvePreview(Preview):
    """A 90 degree bend (radius 10 mm): the true curve in grey, the straight pieces the program would draw over it."""
    R = 10.0

    def __init__(self):
        super().__init__()
        self.gap = settings.get("edge_gap")

    def pieces(self):
        fn = lambda t: (self.R * math.cos(t * math.pi / 2), self.R * math.sin(t * math.pi / 2), 0.0)
        return settings.subdivide(fn, self.gap)

    def worst_gap(self, pts):
        w = 0.0
        for a, b in zip(pts[:-1], pts[1:]):
            a0, a1 = math.atan2(a[1], a[0]), math.atan2(b[1], b[0])
            for k in range(1, 20):
                t = a0 + (a1 - a0) * k / 20
                w = max(w, _chord_dist(a, b, (self.R * math.cos(t), self.R * math.sin(t))))
        return w

    def paintEvent(self, _e):
        p = QPainter(self)
        self.paint_frame(p)
        pts = self.pieces()
        s = (self.H - 40) / self.R
        ox, oy = 50, self.H - 20
        xy = lambda q: QPointF(ox + q[0] * s, oy - q[1] * s)
        ring = [(self.R * math.cos(i * math.pi / 2 / 60), self.R * math.sin(i * math.pi / 2 / 60)) for i in range(61)]
        p.setPen(QPen(SOFT, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for a, b in zip(ring, ring[1:]):
            p.drawLine(xy(a), xy(b))
        p.setPen(QPen(ACC, 1.8))
        for a, b in zip(pts[:-1], pts[1:]):
            p.drawLine(xy(a), xy(b))
        p.setBrush(QBrush(INK))
        p.setPen(Qt.PenStyle.NoPen)
        for q in pts:
            p.drawEllipse(xy(q), 2.2, 2.2)


class SurfacePreview(Preview):
    """The cross-section of a round surface (radius 10 mm): the flat facets the graphics card shades, against the true circle."""
    R = 10.0

    def __init__(self):
        super().__init__()
        self.gap = settings.get("surf_gap")

    def paintEvent(self, _e):
        p = QPainter(self)
        self.paint_frame(p)
        n = settings.circle_facets(self.R, self.gap)
        r = (self.H - 24) / 2
        c = QPointF(self.W / 2, self.H / 2)
        poly = QPolygonF([QPointF(c.x() + r * math.cos(2 * math.pi * i / n), c.y() - r * math.sin(2 * math.pi * i / n)) for i in range(n)])
        p.setBrush(QBrush(FACE))
        p.setPen(QPen(ACC, 1.4))
        p.drawPolygon(poly)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(SOFT, 1.0, Qt.PenStyle.DashLine))
        p.drawEllipse(c, r, r)


class LinePreview(Preview):
    """Outline lines at the chosen thickness, in real screen pixels."""

    def __init__(self):
        super().__init__()
        self.px = settings.get("line_px")

    def paintEvent(self, _e):
        p = QPainter(self)
        self.paint_frame(p)
        p.setBrush(QBrush(FACE))
        p.setPen(Qt.PenStyle.NoPen)
        box = QRectF(24, 20, self.W - 48, self.H - 40)
        p.drawRect(box)
        w = self.px / max(1.0, self.devicePixelRatioF())
        p.setPen(QPen(QColor("#222a38"), w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        p.drawLine(QPointF(box.left(), box.center().y()), QPointF(box.right(), box.center().y()))
        p.drawEllipse(box.center(), 28, 28)


class PullPreview(Preview):
    """Side view, viewer at the top: the outline lies in a surface and a thin wall is slightly closer to the viewer.  Amber = the line
    sinks into the surface, green = right, red = it shows through the wall."""
    WALL = 3.0

    def __init__(self):
        super().__init__()
        self.pull = settings.get("pull_px")

    def paintEvent(self, _e):
        p = QPainter(self)
        self.paint_frame(p)
        base, k = 100, 7.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#cdd6e4")))
        p.drawRect(QRectF(20, base, self.W - 40, 24))
        wall_top = base - self.WALL * k
        p.setBrush(QBrush(QColor("#8696b0")))
        p.drawRect(QRectF(self.W / 2 + 10, wall_top, 14, base - wall_top))
        y = base - self.pull * k
        col = QColor("#d08a00") if self.pull < 0.5 else BAD if self.pull > self.WALL else QColor("#2e8b57")
        p.setPen(QPen(col, 3))
        p.drawLine(QPointF(40, y), QPointF(self.W / 2 - 4, y))
        p.setPen(QPen(col, 3, Qt.PenStyle.DashLine if self.pull >= 0.5 else Qt.PenStyle.DotLine))
        p.drawLine(QPointF(self.W / 2 + 10, y), QPointF(self.W - 40, y))
        p.setPen(QPen(QColor("#6a7a92"), 1))
        p.drawText(QPointF(24, 18), "viewer ↑")


class DimPreview(Preview):
    """A small drawing with a length, a diameter and an angle dimension, drawn by the same code as the sketch, with the typed values."""
    W, H = 440, 230

    def __init__(self):
        super().__init__()
        self.values = {}
        self._build()

    def _build(self):
        import sk_tools as sk
        import sketch_edit as se
        m = sk.new_model()
        r = sk.add_rect_corner(m, (0, 0), (40, 24))
        lns = r["lns"]
        m.add_con("dim_h", [("ln", lns[0])], value=40.0)
        m.add_con("dim_v", [("ln", lns[1])], value=24.0)
        ci = sk.add_circle(m, (66, 12), (74, 12))
        c = m.add_con("dim_dia", [("ci", ci)], value=16.0)
        c["off"] = [12.0, 12.0]
        pa, pb, pc = m.add_point(-52, 0), m.add_point(-18, 0), m.add_point(-30, 20)
        l1, l2 = m.add_line(pa, pb), m.add_line(pa, pc)
        refs = [("ln", l1), ("ln", l2)]
        s1, s2, eps = m.angle_default(refs, hint=(-40, 4))[:3]
        m.add_con("dim_ang", refs, value=50.0, s1=s1, s2=s2, eps=eps)
        self.m = m

        class Stub:
            pass
        st = Stub()
        st.m = m
        st.tag_base = lambda c: se.SketchEditor.tag_base(st, c)
        self.ed = st
        self.names = {"dim_h": "40", "dim_v": "24", "dim_dia": "Ø16", "dim_ang": "50°"}

    def paintEvent(self, _e):
        import sk_dimlines as dl
        import sk_tools as sk
        p = QPainter(self)
        self.paint_frame(p)
        with settings.overriding(self.values):
            shs = []
            for c in self.m.cons:
                sh = dl.shapes(self.ed, c)
                if sh is not None:
                    shs.append((c, sh))
            ext = dl.extent(self.m)
            prims = [it for _c, sh in shs for it in dl.primitives(sh, ext)]
            pts = []
            for key in sk.all_keys(self.m):
                pts.append(sk.polyline(self.m, key, 48))
            allp = [q for arr in pts for q in arr] + [q for _k, a, _w, _c in prims for q in a] + [sh["label"] for _c, sh in shs]
            xs, ys = [q[0] for q in allp], [q[1] for q in allp]
            x0, x1, y0, y1 = min(xs) - 6, max(xs) + 14, min(ys) - 4, max(ys) + 8
            s = min((self.W - 16) / (x1 - x0), (self.H - 16) / (y1 - y0))
            ox = (self.W - s * (x1 - x0)) / 2 - x0 * s
            oy = (self.H + s * (y1 - y0)) / 2 + y0 * s
            xy = lambda q: QPointF(ox + q[0] * s, oy - q[1] * s)
            ratio = max(1.0, self.devicePixelRatioF())
            p.setPen(QPen(QColor("#2f6fdd"), 2.2))
            for arr in pts:
                for a, b in zip(arr[:-1], arr[1:]):
                    p.drawLine(xy(a), xy(b))
            for kind, arr, wd, rgb in prims:
                col = QColor.fromRgbF(*rgb)
                if kind == "line":
                    p.setPen(QPen(col, wd / ratio, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPolyline(QPolygonF([xy(q) for q in arr]))
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(col))
                    p.drawPolygon(QPolygonF([xy(q) for q in arr]))
            f = QFont()
            f.setPointSizeF(settings.get("text_pt") * 0.75)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QPen(QColor.fromRgbF(*settings.rgb("dim_color"))))
            for c, sh in shs:
                q = xy(sh["label"])
                p.drawText(QPointF(q.x() + 5, q.y() - 5), self.names.get(c["type"], ""))


# ------------------------------------------------------------------------------------------------------------ the inputs
HINTS = {
    "edge_gap": "Largest gap between a drawn line and the true curve.",
    "surf_gap": "Largest gap between shaded facets and the true surface.",
    "line_px": "Thickness of outlines.",
    "pull_px": "How far outlines move toward you. Lower it if thin faces are covered.",
    "pick3d_px": "Distance from an edge or corner at which a click picks it.",
    "snap_px": "Distance at which a new sketch point snaps.",
    "pick_px": "Distance at which a click selects a sketch item.",
    "label_px": "Click area around a dimension label.",
    "dim_line_px": "Thickness of the dimension line and arrowheads.",
    "dim_line_style": "Pattern of the dimension line.",
    "ext_line_px": "Thickness of the extension lines.",
    "ext_line_style": "Pattern of the extension lines.",
    "ext_gap_pct": "Space between the part and the extension line (% of sketch size).",
    "ext_over_pct": "How far the extension line passes the dimension line (% of sketch size).",
    "arrow_pct": "Arrowhead size (% of sketch size).",
    "arrow_style": "Shape at the ends of dimension lines.",
    "text_pt": "Size of the dimension text.",
    "dim_color": "Colour of dimensions.",
    "dim_sel_color": "Colour of a selected dimension.",
}
UNITS = {"line_px": "px", "pull_px": "px", "pick3d_px": "px", "snap_px": "px", "pick_px": "px", "label_px": "px", "dim_line_px": "px",
         "ext_line_px": "px", "ext_gap_pct": "%", "ext_over_pct": "%", "arrow_pct": "%", "text_pt": "pt"}
LENGTHY = ("edge_gap", "surf_gap")


class Field:
    """One setting: its name, the input, a short line under it.  A number is parsed on every keystroke (for the picture) and held between
    its limits when editing ends; a choice is a drop-down; a colour is a swatch button."""

    def __init__(self, key):
        self.key = key
        d, lo, hi, label = settings.SPEC[key]
        self.lo, self.hi = lo, hi
        self.lengthy = key in LENGTHY
        self.kind = "color" if hi == "color" else "choice" if isinstance(d, str) else "number"
        self.on_value = None
        self.value = settings.get(key)
        self.note = QLabel("")
        self.note.setStyleSheet("color:#a05000;")
        self.note.setWordWrap(True)
        self.unit = QLabel(unitctl.length_unit() if self.lengthy else UNITS.get(key, ""))
        box = QHBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        if self.kind == "number":
            self.edit = QLineEdit(self.to_text(self.value))
            self.edit.setMaximumWidth(90)
            self.edit.textEdited.connect(self.typing)
            self.edit.editingFinished.connect(self.finish)
            box.addWidget(self.edit)
            box.addWidget(self.unit)
        elif self.kind == "choice":
            self.combo = QComboBox()
            for k, text in hi.items():
                self.combo.addItem(text, k)
            self.combo.setCurrentIndex(max(0, self.combo.findData(self.value)))
            self.combo.currentIndexChanged.connect(self.picked)
            box.addWidget(self.combo)
        else:
            self.btn = QPushButton()
            self.btn.setFixedWidth(90)
            self.btn.clicked.connect(self.choose_color)
            self.paint_btn()
            box.addWidget(self.btn)
        box.addStretch(1)
        lab = QLabel(label)
        lab.setStyleSheet("font-weight:600;")
        hint = QLabel(HINTS.get(key, ""))
        hint.setStyleSheet("color:#506080;")
        hint.setWordWrap(True)
        lay = QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(2)
        lay.addWidget(lab)
        lay.addLayout(box)
        lay.addWidget(hint)
        lay.addWidget(self.note)
        self.layout = lay

    # numbers
    def to_text(self, v):
        return f"{unitctl.to_disp(v):.5g}" if self.lengthy else f"{v:g}"

    def parse(self, text):
        try:
            x = float(text.strip().replace(",", "."))
        except ValueError:
            return None
        return unitctl.from_disp(x) if self.lengthy else x

    def typing(self, text):
        v = self.parse(text)
        if v is not None:
            self.value = settings.clamp(self.key, v)
            self.note.setText("")
            if self.on_value:
                self.on_value()

    def finish(self):
        v = self.parse(self.edit.text())
        if v is None:
            self.set_value(self.value)
            return
        c = settings.clamp(self.key, v)
        if abs(c - v) > 1e-12:
            self.note.setText(f"Held to the allowed range: {self.to_text(self.lo)} to {self.to_text(self.hi)} {self.unit.text()}")
        self.set_value(c)

    # choices and colours
    def picked(self, _i):
        self.value = self.combo.currentData()
        if self.on_value:
            self.on_value()

    def paint_btn(self):
        c = QColor(self.value)
        self.btn.setStyleSheet(f"background:{self.value}; color:{'#000' if c.lightness() > 128 else '#fff'};")
        self.btn.setText(self.value)

    def choose_color(self):
        c = QColorDialog.getColor(QColor(self.value))
        if c.isValid():
            self.set_value(c.name())

    def set_value(self, v):
        self.value = settings.clamp(self.key, v)
        if self.kind == "number":
            self.edit.setText(self.to_text(self.value))
        elif self.kind == "choice":
            self.combo.setCurrentIndex(max(0, self.combo.findData(self.value)))
        else:
            self.paint_btn()
        if self.on_value:
            self.on_value()

    def refresh_unit(self):
        if self.lengthy:
            self.unit.setText(unitctl.length_unit())
            self.edit.setText(self.to_text(self.value))


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(900, 640)
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        outer.addLayout(row, 1)
        self.sections = QListWidget()
        self.sections.setMaximumWidth(170)
        self.pages = QStackedWidget()
        row.addWidget(self.sections)
        row.addWidget(self.pages, 1)
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.fields = {}
        self.warn = QLabel("")
        self.warn.setStyleSheet("color:#b04000;")
        self.warn.setWordWrap(True)

        self.curve, self.surf, self.line, self.pull = CurvePreview(), SurfacePreview(), LinePreview(), PullPreview()
        self.dimprev = DimPreview()
        self.section("Curves && Surfaces", [("edge_gap", self.curve), ("surf_gap", self.surf)], extra=self.warn)
        self.section("Outlines", [("line_px", self.line), ("pull_px", self.pull)])
        self.section("Dimensions", [("dim_line_px", None), ("dim_line_style", None), ("ext_line_px", None), ("ext_line_style", None),
                                    ("ext_gap_pct", None), ("ext_over_pct", None), ("arrow_pct", None), ("arrow_style", None),
                                    ("text_pt", None), ("dim_color", None), ("dim_sel_color", None)], top=self.dimprev)
        self.hover = QCheckBox("Highlight the face, edge or point under the cursor while picking")
        self.hover.setChecked(bool(settings.get("hover")))
        self.section("Picking && Snapping", [("pick3d_px", None), ("snap_px", None), ("pick_px", None), ("label_px", None)], extra=self.hover)
        self.sections.setCurrentRow(0)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        rb = QPushButton("Reset to defaults")
        bb.addButton(rb, QDialogButtonBox.ButtonRole.ResetRole)
        rb.clicked.connect(self.reset_defaults)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        outer.addWidget(bb)
        self.update_previews()

    def section(self, title, rows, top=None, extra=None):
        self.sections.addItem(title.replace("&&", "&"))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        body = QWidget()
        v = QVBoxLayout(body)
        for key, prev in rows:
            f = Field(key)
            f.on_value = self.update_previews
            self.fields[key] = f
            line = QHBoxLayout()
            line.addLayout(f.layout, 1)
            if prev is not None:
                line.addWidget(prev, alignment=Qt.AlignmentFlag.AlignTop)
            v.addLayout(line)
        if extra is not None:
            v.addWidget(extra)
        v.addStretch(1)
        sc.setWidget(body)
        if top is None:
            self.pages.addWidget(sc)
        else:                                   # the picture stays in view while the values below scroll
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(0, 0, 0, 0)
            pv.addWidget(top, alignment=Qt.AlignmentFlag.AlignHCenter)
            pv.addWidget(sc, 1)
            self.pages.addWidget(page)

    def update_previews(self):
        v = self.values()
        self.curve.gap, self.surf.gap, self.line.px, self.pull.pull = v["edge_gap"], v["surf_gap"], v["line_px"], v["pull_px"]
        self.dimprev.values = {k: x for k, x in v.items() if k not in ("hover",)}
        for w in (self.curve, self.surf, self.line, self.pull, self.dimprev):
            w.update()
        msgs = []
        if v["edge_gap"] < settings.FINE_EDGE:
            msgs.append("Curve accuracy this fine makes big models slow to draw.")
        if v["surf_gap"] < settings.FINE_SURF:
            msgs.append("Surface accuracy this fine makes big assemblies slow to draw and rotate.")
        self.warn.setText("  ".join(msgs))

    def values(self):
        out = {k: f.value for k, f in self.fields.items()}
        out["hover"] = self.hover.isChecked()
        return out

    def reset_defaults(self):
        d = settings.defaults()
        for k, f in self.fields.items():
            f.note.setText("")
            f.set_value(d[k])
        self.hover.setChecked(bool(d["hover"]))

    def apply(self):
        settings.set_many(self.values())

    def ok(self):
        self.apply()
        self.accept()
