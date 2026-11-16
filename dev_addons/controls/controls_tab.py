"""controls_tab.py - the Systems and Controls tab: dropdown sections on the left (one tool each), the worked answer and plots on the right.

Today there is one section, "Transfer function": type G(s) and get the zeros, poles, gain, DC gain, stability and a pole-zero plot.
A section is a small class (title, an inputs widget for the left, a results widget for the right, to_json / from_json); add a class to SECTIONS
to add a tool.  Files: .opctl (JSON).
"""
import json
import math
import os

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
                             QStackedWidget, QToolButton, QVBoxLayout, QWidget)

import ctl_core as core

FILTER = "OpenPara controls (*.opctl);;All files (*)"
FORMAT = "openpara-controls"


# ------------------------------------------------------------------------------------------------------------- pole-zero plot
def nice_step(span, n=6):
    raw = max(span, 1e-12) / n
    mag = 10 ** math.floor(math.log10(raw))
    for s in (1, 2, 2.5, 5, 10):
        if s * mag >= raw:
            return s * mag
    return 10 * mag


class PoleZeroPlot(QWidget):
    """The s-plane: × for poles, ○ for zeros (a number beside it when a root is repeated), the left half-plane lightly tinted."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 260)
        self.poles, self.zeros = [], []

    def set_roots(self, zeros, poles):
        self.zeros, self.poles = list(zeros), list(poles)
        self.update()

    def view_box(self):
        pts = self.zeros + self.poles
        re_lo = min([0.0] + [z.real for z in pts])
        re_hi = max([0.0] + [z.real for z in pts])
        im = max([1.0] + [abs(z.imag) for z in pts])
        wid = max(re_hi - re_lo, 1.0)
        pad_x = 0.2 * wid + 0.3
        re_lo, re_hi = re_lo - pad_x, re_hi + pad_x
        im = im * 1.3
        return re_lo, re_hi, -im, im

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            self.draw(p)
        except Exception:                      # noqa: BLE001 - an error escaping a paint event would close the whole program
            pass
        finally:
            p.end()

    def draw(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        m = 34
        area = QRectF(m + 14, 10, w - m - 24, h - m - 12)
        if area.width() < 40 or area.height() < 40:                      # too small to draw anything useful
            return
        x0, x1, y0, y1 = self.view_box()
        sc = min(area.width() / (x1 - x0), area.height() / (y1 - y0))               # the same scale on both axes
        cx = area.center().x() - sc * (x0 + x1) / 2
        cy = area.center().y() + sc * (y0 + y1) / 2

        def px(z):
            return QPointF(cx + sc * z.real, cy - sc * z.imag)

        # left half-plane tint
        left = QRectF(area.left(), area.top(), max(0.0, min(area.right(), cx) - area.left()), area.height())
        p.fillRect(left, QColor(46, 160, 120, 22))
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        step = nice_step(max(x1 - x0, y1 - y0))
        p.setPen(QPen(QColor("#e1e6ee"), 1))
        v = math.ceil((area.left() - cx) / sc / step) * step
        while cx + sc * v <= area.right():
            x = cx + sc * v
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            p.setPen(QColor("#4a5668"))
            p.drawText(QRectF(x - 28, area.bottom() + 3, 56, 14), Qt.AlignmentFlag.AlignCenter, core.fmt(v, 4))
            p.setPen(QPen(QColor("#e1e6ee"), 1))
            v += step
        v = math.ceil((cy - area.bottom()) / sc / step) * step
        while cy - sc * v >= area.top():
            y = cy - sc * v
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(QColor("#4a5668"))
            p.drawText(QRectF(area.left() - 40, y - 7, 36, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, core.fmt(v, 4))
            p.setPen(QPen(QColor("#e1e6ee"), 1))
            v += step
        p.setPen(QPen(QColor("#6b7a90"), 1.4))                                      # the axes
        if area.left() <= cx <= area.right():
            p.drawLine(QPointF(cx, area.top()), QPointF(cx, area.bottom()))
        if area.top() <= cy <= area.bottom():
            p.drawLine(QPointF(area.left(), cy), QPointF(area.right(), cy))
        p.setPen(QColor("#4a5668"))
        p.drawText(QRectF(area.left(), h - 16, area.width(), 14), Qt.AlignmentFlag.AlignCenter, "real axis (σ)")
        p.save()
        p.translate(11, area.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-60, -8, 120, 14), Qt.AlignmentFlag.AlignCenter, "imaginary axis (jω)")
        p.restore()
        p.setClipRect(area.adjusted(-6, -6, 6, 6))
        for roots, kind in ((self.zeros, "zero"), (self.poles, "pole")):
            for z, mult in core._group(roots):
                q = px(z)
                if kind == "zero":
                    p.setPen(QPen(QColor("#1f77b4"), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(q, 6, 6)
                else:
                    p.setPen(QPen(QColor("#d62828"), 2.4))
                    p.drawLine(QPointF(q.x() - 6, q.y() - 6), QPointF(q.x() + 6, q.y() + 6))
                    p.drawLine(QPointF(q.x() - 6, q.y() + 6), QPointF(q.x() + 6, q.y() - 6))
                if mult > 1:
                    p.setPen(QColor("#222222"))
                    p.drawText(QRectF(q.x() + 6, q.y() - 20, 24, 14), Qt.AlignmentFlag.AlignLeft, f"×{mult}")
        p.setClipping(False)
        p.setPen(QColor("#1f77b4"))
        p.drawText(QRectF(area.right() - 120, area.top() + 2, 118, 14), Qt.AlignmentFlag.AlignRight, "○ zero")
        p.setPen(QColor("#d62828"))
        p.drawText(QRectF(area.right() - 120, area.top() + 16, 118, 14), Qt.AlignmentFlag.AlignRight, "× pole")


# ------------------------------------------------------------------------------------------------------------- sections
class Section:
    """One tool.  `inputs` goes in the left column (shown when the section is open); `results` is its page on the right."""
    key = "section"
    title = "Section"

    def __init__(self, changed):
        self.changed = changed                      # call when an input was edited
        self.inputs = QWidget()
        self.results = QWidget()

    def to_json(self):
        return {}

    def from_json(self, d):
        pass


class TransferFunctionSection(Section):
    key = "transfer_function"
    title = "Transfer function: poles, zeros, gain"
    EXAMPLES = (("Book 1.4.5.1:  (2s+3) / (s²+3s+2)", "2s+3", "s^2+3s+2"),
                ("Integrator:  1 / (s(s+1)²)", "1", "s(s+1)^2"),
                ("Complex poles:  10(s+2) / ((s²+2s+5)(s+3))", "10(s+2)", "(s^2+2s+5)(s+3)"),
                ("Unstable:  1 / (s²-s-2)", "1", "s^2-s-2"))

    def __init__(self, changed):
        super().__init__(changed)
        self.analysis = None
        lay = QVBoxLayout(self.inputs)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.addWidget(QLabel("G(s) = numerator / denominator"))
        self.num = QLineEdit()
        self.num.setPlaceholderText("numerator, e.g. 2s+3")
        self.den = QLineEdit()
        self.den.setPlaceholderText("denominator, e.g. s^2+3s+2")
        tip = ("Write the polynomial in s: 2s+3, s^2+3s+2, 10(s+2), (s+1)(s+2).\nOr list the coefficients, highest power first: [1 3 2].\n"
               "Use ^ for powers (s^2) and brackets for products.")
        self.num.setToolTip(tip)
        self.den.setToolTip(tip)
        lay.addWidget(QLabel("Numerator"))
        lay.addWidget(self.num)
        lay.addWidget(QLabel("Denominator"))
        lay.addWidget(self.den)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color:#b3261e;")
        lay.addWidget(self.msg)
        self.ex = QComboBox()
        self.ex.addItem("Examples…")
        for name, *_ in self.EXAMPLES:
            self.ex.addItem(name)
        self.ex.activated.connect(self.load_example)
        lay.addWidget(self.ex)
        hint = QLabel("Write polynomials like 2s+3 or s^2+3s+2, products like (s+1)(s+2), or coefficient lists like [1 3 2].")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#5b6675;")
        lay.addWidget(hint)
        lay.addStretch(1)

        rl = QVBoxLayout(self.results)
        rl.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Vertical)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(11)
        self.text.setFont(mono)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.plot = PoleZeroPlot()
        split.addWidget(self.text)
        split.addWidget(self.plot)
        split.setSizes([480, 300])
        rl.addWidget(split)
        self.num.textChanged.connect(self.update_result)
        self.den.textChanged.connect(self.update_result)
        self.num.textEdited.connect(lambda _t: self.changed())
        self.den.textEdited.connect(lambda _t: self.changed())
        self.update_result()

    def load_example(self, i):
        if i <= 0:
            return
        _name, n, d = self.EXAMPLES[i - 1]
        self.ex.setCurrentIndex(0)
        self.num.setText(n)
        self.den.setText(d)
        self.changed()

    def update_result(self):
        self.analysis = None
        nt, dt = self.num.text().strip(), self.den.text().strip()
        if not nt and not dt:
            self.msg.setText("")
            self.text.setPlainText("Type the numerator and denominator of G(s) on the left.\n\nExample from the book (1.4.5.1):\n"
                                   "  numerator   2s+3\n  denominator s^2+3s+2\nor pick it from Examples.")
            self.plot.set_roots([], [])
            return
        try:
            num = core.parse_poly(nt)
        except core.TFError as e:
            return self.fail("Numerator: " + str(e))
        try:
            den = core.parse_poly(dt)
        except core.TFError as e:
            return self.fail("Denominator: " + str(e))
        try:
            a = core.analyze(num, den)
        except core.TFError as e:
            return self.fail(str(e))
        self.analysis = a
        self.msg.setText("")
        self.text.setPlainText(core.report(a))
        self.plot.set_roots(a.zeros, a.poles)

    def fail(self, why):
        self.msg.setText(why)
        self.text.setPlainText("")
        self.plot.set_roots([], [])

    def to_json(self):
        return {"num": self.num.text(), "den": self.den.text()}

    def from_json(self, d):
        self.num.setText(d.get("num", ""))
        self.den.setText(d.get("den", ""))


SECTIONS = [TransferFunctionSection]


# ------------------------------------------------------------------------------------------------------------- the dropdown column
class Drop(QWidget):
    """A header button (▸ / ▾ title) that opens and closes its content."""

    def __init__(self, title, content, on_open):
        super().__init__()
        self.content = content
        self.on_open = on_open
        self.btn = QToolButton()
        self.btn.setText(title)
        self.btn.setCheckable(True)
        self.btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn.setArrowType(Qt.ArrowType.RightArrow)
        self.btn.setStyleSheet("QToolButton{border:none;font-weight:bold;text-align:left;padding:6px 4px;}"
                               "QToolButton:checked{background:#e8eef7;}")
        self.btn.toggled.connect(self._toggled)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.btn)
        lay.addWidget(content)
        content.setVisible(False)

    def _toggled(self, on):
        self.btn.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.content.setVisible(on)
        if on:
            self.on_open(self)

    def set_open(self, on):
        self.btn.setChecked(on)

    def is_open(self):
        return self.btn.isChecked()


# ------------------------------------------------------------------------------------------------------------- the tab
class ControlsTab(QWidget):
    def __init__(self, path=None):
        super().__init__()
        self.path = None
        self.host = None
        self.dirty = False
        self.sections = [cls(self.edited) for cls in SECTIONS]
        self.pages = QStackedWidget()
        self.drops = []
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(2)
        for s in self.sections:
            self.pages.addWidget(s.results)
            d = Drop(s.title, s.inputs, self.opened)
            d.section = s
            self.drops.append(d)
            lv.addWidget(d)
        lv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(300)

        top = QHBoxLayout()
        self.status = QLabel("")
        for text, tip, fn in (("New", "Clear all sections", self.new), ("Open", "Open a .opctl file", self.open_dialog),
                              ("Save", "Save (Ctrl+S)", self.save), ("Save as", "", self.save_as)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            top.addWidget(b)
        top.addStretch(1)
        top.addWidget(self.status)
        split = QSplitter()
        split.addWidget(scroll)
        split.addWidget(self.pages)
        split.setSizes([340, 860])
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        self.drops[0].set_open(True)
        if path and os.path.isfile(path):
            self.load(path)
        self.dirty = False

    def opened(self, drop):
        for d in self.drops:                                     # one section open at a time
            if d is not drop and d.is_open():
                d.btn.blockSignals(True)
                d.set_open(False)
                d.btn.setArrowType(Qt.ArrowType.RightArrow)
                d.content.setVisible(False)
                d.btn.blockSignals(False)
        self.pages.setCurrentWidget(drop.section.results)

    def edited(self):
        self.dirty = True

    def section(self, key):
        for s in self.sections:
            if s.key == key:
                return s
        return None

    # ------------------------------------------------------------------ files
    def title(self):
        return os.path.basename(self.path) if self.path else "Controls"

    def to_json(self):
        return {"format": FORMAT, "version": 1, "sections": {s.key: s.to_json() for s in self.sections}}

    def load(self, path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        for s in self.sections:
            s.from_json(d.get("sections", {}).get(s.key, {}))
        self.path = path
        self.dirty = False

    def new(self):
        for s in self.sections:
            s.from_json({})
        self.path = None
        self.dirty = False

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open", "", FILTER)
        if p:
            self.load(p)

    def is_dirty(self):
        return self.dirty

    def save(self):
        if not self.path:
            return self.save_as()
        import fileio
        fileio.write_text(self.path, json.dumps(self.to_json(), indent=1))
        self.dirty = False
        self.status.setText(f"Saved {self.path}")

    def save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save", self.path or "controls.opctl", FILTER)
        if p:
            if not p.lower().endswith(".opctl"):
                p += ".opctl"
            self.path = p
            self.save()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_S and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return self.save()
        super().keyPressEvent(ev)


def make_tab(path=None):
    return ControlsTab(path)
