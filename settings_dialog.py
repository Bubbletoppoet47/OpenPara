"""File > Settings: typed values (no sliders) for how the views are drawn and how close a click must be - with a small live picture
beside each drawing setting, so what a number does can be seen before it is applied."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

import settings
import unitctl

INK, SOFT, ACC, BAD, FACE = QColor("#1f2933"), QColor("#b8c2d0"), QColor("#2f6fdd"), QColor("#d03030"), QColor("#e9eef6")


class Preview(QWidget):
    """Base of the small pictures: a framed area of fixed size."""
    W, H = 280, 150

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.W, self.H)
        self.caption = ""

    def paint_frame(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#ffffff"))
        p.setPen(QPen(QColor("#c8d0dc"), 1))
        p.drawRect(0, 0, self.W - 1, self.H - 1)

    def text(self, p, txt, y=None):
        p.setPen(QPen(QColor("#40506a")))
        f = p.font()
        f.setPointSizeF(8.0)
        p.setFont(f)
        p.drawText(QRectF(4, (self.H - 30) if y is None else y, self.W - 8, 28), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, txt)


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
        s = (self.H - 56) / self.R
        ox, oy = 40, self.H - 36
        xy = lambda q: QPointF(ox + q[0] * s, oy - q[1] * s)
        p.setPen(QPen(SOFT, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for a, b in zip(self._ring(), self._ring()[1:]):
            p.drawLine(xy(a), xy(b))
        p.setPen(QPen(ACC, 1.8))
        for a, b in zip(pts[:-1], pts[1:]):
            p.drawLine(xy(a), xy(b))
        p.setBrush(QBrush(INK))
        p.setPen(Qt.PenStyle.NoPen)
        for q in pts:
            p.drawEllipse(xy(q), 2.2, 2.2)
        n = len(pts) - 1
        self.text(p, f"{n} straight piece{'s' if n != 1 else ''}; the line is never more than {unitctl.length_text(self.worst_gap(pts))} from the true curve\n(a 90° bend of radius {unitctl.length_text(self.R)})")

    def _ring(self):
        return [(self.R * math.cos(i * math.pi / 2 / 60), self.R * math.sin(i * math.pi / 2 / 60), 0.0) for i in range(61)]


def _chord_dist(a, b, m):
    ab = (b[0] - a[0], b[1] - a[1])
    am = (m[0] - a[0], m[1] - a[1])
    n2 = ab[0] ** 2 + ab[1] ** 2
    t = 0.0 if n2 < 1e-18 else min(1.0, max(0.0, (am[0] * ab[0] + am[1] * ab[1]) / n2))
    return math.hypot(am[0] - ab[0] * t, am[1] - ab[1] * t)


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
        r = (self.H - 48) / 2
        c = QPointF(self.W / 2, 8 + r)
        poly = QPolygonF([QPointF(c.x() + r * math.cos(2 * math.pi * i / n), c.y() - r * math.sin(2 * math.pi * i / n)) for i in range(n)])
        p.setBrush(QBrush(FACE))
        p.setPen(QPen(ACC, 1.4))
        p.drawPolygon(poly)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(SOFT, 1.0, Qt.PenStyle.DashLine))
        p.drawEllipse(c, r, r)
        worst = self.R * (1 - math.cos(math.pi / n))
        self.text(p, f"{n} flat facets around the circle; a facet's middle sits up to {unitctl.length_text(worst)} inside the true surface\n(a round surface of radius {unitctl.length_text(self.R)}, cut across)")


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
        p.drawRect(QRectF(20, 14, self.W - 40, 74))
        w = self.px / max(1.0, self.devicePixelRatioF())
        p.setPen(QPen(QColor("#222a38"), w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(20, 14, self.W - 40, 74))
        p.drawLine(QPointF(20, 51), QPointF(self.W - 20, 51))
        p.drawEllipse(QPointF(self.W / 2, 51), 22, 22)
        self.text(p, f"outline lines {settings.clamp('line_px', self.px):g} screen pixels thick (shown at true size on this screen)", y=92)


class PullPreview(Preview):
    """Side view: why outlines are brought towards the viewer.  Viewer at the top.  The line lies in a surface; a nearby thin wall
    is slightly closer to the viewer.  Too little pull: the line flickers into the surface.  Too much: it shows through the wall."""
    WALL = 3.0              # how far in front of the line the wall is, in the same (pixel-like) units, for the picture

    def __init__(self):
        super().__init__()
        self.pull = settings.get("pull_px")

    def paintEvent(self, _e):
        p = QPainter(self)
        self.paint_frame(p)
        base = 74
        k = 7.0                                            # picture scale for the depth
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#cdd6e4")))
        p.drawRect(QRectF(20, base, self.W - 40, 20))     # the surface (seen edge-on)
        wall_top = base - self.WALL * k
        p.setBrush(QBrush(QColor("#8696b0")))
        p.drawRect(QRectF(self.W / 2 + 10, wall_top, 14, base - wall_top))   # a thin wall just in front of the line
        y = base - self.pull * k
        if self.pull < 0.5:
            col, state = QColor("#d08a00"), "too little: the line sinks into the surface and breaks up"
        elif self.pull > self.WALL:
            col, state = BAD, "too much: the line shows through the wall in front of it"
        else:
            col, state = QColor("#2e8b57"), "good: clear of the surface, still hidden by the wall"
        p.setPen(QPen(col, 3))
        p.drawLine(QPointF(40, y), QPointF(self.W / 2 - 4, y))
        p.setPen(QPen(col, 3, Qt.PenStyle.DashLine if self.pull >= 0.5 else Qt.PenStyle.DotLine))
        p.drawLine(QPointF(self.W / 2 + 10, y), QPointF(self.W - 40, y))
        p.setPen(QPen(QColor("#6a7a92"), 1))
        p.drawText(QPointF(24, 16), "viewer ↑")
        self.text(p, f"{state}\n(a sketch of the idea: the line is {self.pull:g} px closer to you)", y=102)


class Field:
    """A typed number: parsed on every keystroke for the picture, held between its limits when editing ends."""

    def __init__(self, key, grid, row, unit=None, lengthy=False, hint=""):
        self.key, self.lengthy = key, lengthy
        d, lo, hi, label = settings.SPEC[key]
        self.lo, self.hi = lo, hi
        self.edit = QLineEdit()
        self.edit.setMaximumWidth(90)
        self.unit = QLabel(unitctl.length_unit() if lengthy else (unit or ""))
        self.note = QLabel("")
        self.note.setStyleSheet("color:#a05000;")
        self.note.setWordWrap(True)
        self.on_value = None
        self.value = settings.get(key)
        self.edit.setText(self.to_text(self.value))
        box = QHBoxLayout()
        box.addWidget(self.edit)
        box.addWidget(self.unit)
        box.addStretch(1)
        lab = QLabel(label)
        lab.setStyleSheet("font-weight:600;")
        lay = QVBoxLayout()
        lay.addWidget(lab)
        lay.addLayout(box)
        if hint:
            h = QLabel(hint)
            h.setWordWrap(True)
            h.setStyleSheet("color:#506080;")
            lay.addWidget(h)
        lay.addWidget(self.note)
        self.layout = lay
        self.edit.textEdited.connect(self.typing)
        self.edit.editingFinished.connect(self.finish)

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
            lo, hi = self.to_text(self.lo), self.to_text(self.hi)
            self.note.setText(f"Held to the allowed range: {lo} to {hi} {self.unit.text()}")
        self.set_value(c)

    def set_value(self, v):
        self.value = settings.clamp(self.key, v)
        self.edit.setText(self.to_text(self.value))
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
        self.resize(760, 720)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("These apply to every part and assembly (they are not saved inside your files).  Type a value; the picture beside "
                               "a drawing setting shows what it does."))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        body = QWidget()
        self.vbox = QVBoxLayout(body)
        sc.setWidget(body)
        outer.addWidget(sc, 1)
        self.fields = {}
        self.warn = QLabel("")
        self.warn.setStyleSheet("color:#b04000;")
        self.warn.setWordWrap(True)

        self.curve = CurvePreview()
        self.surf = SurfacePreview()
        self.line = LinePreview()
        self.pull = PullPreview()
        self.group("Drawing", [
            ("edge_gap", True, None, "How closely a drawn line follows a round edge: the most the line may stray from the true curve.  Smaller = smoother, more points to draw.", self.curve),
            ("surf_gap", True, None, "How finely round surfaces are shaded.  Smaller = smoother shading, but this is the main load on the graphics card for big assemblies.", self.surf),
            ("line_px", False, "px", "How thick the outlines are drawn.", self.line),
            ("pull_px", False, "px", "How far outlines are brought towards you so they are not buried in the surface they lie on.  "
                                     "If a thin face (such as a cut end) is covered by its outline, lower this.", self.pull),
        ])
        self.vbox.addWidget(self.warn)
        self.group("Picking in 3D (assemblies)", [
            ("pick3d_px", False, "px", "How close to an edge or a corner a click must be to pick it instead of the face.  Smaller makes thin faces easier to pick.", None)])
        self.group("Sketches", [
            ("snap_px", False, "px", "How close the cursor must be to a point or line for a new sketch point to snap to it.", None),
            ("pick_px", False, "px", "How close a click must be to select a sketch line, circle or point.", None),
            ("label_px", False, "px", "Size of the click area around a dimension label.", None)])
        self.hover = QCheckBox("Highlight the face, edge or point under the cursor while picking in an assembly")
        self.hover.setChecked(bool(settings.get("hover")))
        self.vbox.addWidget(self.hover)
        self.vbox.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        rb = QPushButton("Reset to defaults")
        bb.addButton(rb, QDialogButtonBox.ButtonRole.ResetRole)
        rb.clicked.connect(self.reset_defaults)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        outer.addWidget(bb)
        self.update_previews()

    def group(self, title, rows):
        g = QGroupBox(title)
        grid = QGridLayout(g)
        for i, (key, lengthy, unit, hint, prev) in enumerate(rows):
            f = Field(key, grid, i, unit=unit, lengthy=lengthy, hint=hint)
            f.on_value = self.update_previews
            self.fields[key] = f
            grid.addLayout(f.layout, i, 0)
            if prev is not None:
                grid.addWidget(prev, i, 1, alignment=Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(0, 1)
        self.vbox.addWidget(g)

    def update_previews(self):
        v = self.values()
        self.curve.gap, self.surf.gap, self.line.px, self.pull.pull = v["edge_gap"], v["surf_gap"], v["line_px"], v["pull_px"]
        for w in (self.curve, self.surf, self.line, self.pull):
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
