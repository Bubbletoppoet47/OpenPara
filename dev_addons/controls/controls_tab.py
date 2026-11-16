"""controls_tab.py - the Systems and Controls tab: dropdown sections on the left (one tool each), the worked answer and plots on the right.

Today there is one section, "Transfer function": type G(s) and get the zeros, poles, gain, DC gain, stability and a pole-zero plot.
A section is a small class (title, an inputs widget for the left, a results widget for the right, to_json / from_json); add a class to SECTIONS
to add a tool.  Files: .opctl (JSON).
"""
import json
import math
import os

import numpy as np

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
                             QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

import ctl_canvas as cv
import ctl_circuit as ckt
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


# ------------------------------------------------------------------------------------------------------------- time response plot
def ticks(lo, hi):
    step = nice_step(hi - lo)
    v = math.ceil(lo / step - 1e-9) * step
    out = []
    while v <= hi + step * 1e-9:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


class TimePlot(QWidget):
    """y(t) of the step or impulse response, drawn from the analytical expression, with the final value as a dashed line."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 200)
        self.resp = None
        self.kind = "step"

    def set_response(self, resp, kind):
        self.resp, self.kind = resp, kind
        self.update()

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
        r = QRectF(58, 12, w - 74, h - 46)
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        if r.width() < 40 or r.height() < 40:
            return
        rs = self.resp
        if rs is None:
            p.setPen(QColor("#7a8696"))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "Type G(s) to see its step and impulse response.")
            return
        if not rs.terms:
            p.setPen(QColor("#7a8696"))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                       "The response is only a δ(t) spike (nothing to draw)." if rs.deltas else "The response is zero.")
            return
        T = rs.horizon
        t = np.unique(np.concatenate([np.linspace(0, T, 600), T * np.linspace(0, 1, 500) ** 3]))
        y = rs.eval(t)
        y = np.nan_to_num(y, nan=0.0, posinf=1e300, neginf=-1e300)
        lo, hi = float(np.min(y)), float(np.max(y))
        if rs.final is not None:
            lo, hi = min(lo, rs.final), max(hi, rs.final)
        lo, hi = min(lo, 0.0), max(hi, 0.0)
        if hi - lo < 1e-12:
            lo, hi = lo - 1.0, hi + 1.0
        pad = 0.06 * (hi - lo)
        lo, hi = lo - pad, hi + pad

        def X(v):
            return r.left() + v / T * r.width()

        def Y(v):
            return r.bottom() - (v - lo) / (hi - lo) * r.height()

        for v in ticks(lo, hi):
            p.setPen(QPen(QColor("#e1e6ee"), 1))
            p.drawLine(QPointF(r.left(), Y(v)), QPointF(r.right(), Y(v)))
            p.setPen(QColor("#4a5668"))
            p.drawText(QRectF(0, Y(v) - 7, r.left() - 5, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, core.fmt(v, 4))
        for v in ticks(0, T):
            p.setPen(QPen(QColor("#e1e6ee"), 1))
            p.drawLine(QPointF(X(v), r.top()), QPointF(X(v), r.bottom()))
            p.setPen(QColor("#4a5668"))
            p.drawText(QRectF(X(v) - 30, r.bottom() + 3, 60, 14), Qt.AlignmentFlag.AlignCenter, core.fmt(v, 4))
        p.setPen(QPen(QColor("#9aa6b8"), 1))
        p.drawRect(r)
        p.setPen(QPen(QColor("#6b7a90"), 1.2))
        p.drawLine(QPointF(r.left(), Y(0)), QPointF(r.right(), Y(0)))
        p.setPen(QColor("#4a5668"))
        p.drawText(QRectF(r.left(), h - 17, r.width(), 14), Qt.AlignmentFlag.AlignCenter, "time t (s)")
        p.setClipRect(r)
        if rs.final is not None:
            p.setPen(QPen(QColor("#e76f51"), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(r.left(), Y(rs.final)), QPointF(r.right(), Y(rs.final)))
        p.setPen(QPen(QColor("#1f77b4"), 2))
        pts = [QPointF(X(a), Y(b)) for a, b in zip(t, y)]
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)
        p.setClipping(False)
        p.setPen(QColor("#4a5668"))
        note = ("final value " + core.fmt(rs.final)) if rs.final is not None else rs.final_note
        p.drawText(QRectF(r.left() + 6, r.top() + 2, r.width() - 12, 14), Qt.AlignmentFlag.AlignRight, note)


# ------------------------------------------------------------------------------------------------------------- block diagram
class BlockDiagram(QWidget):
    """R(s) -> [ G(s) ] -> Y(s): one box, or a row of boxes in series.  A block is (top, bottom); bottom None means a lone expression, otherwise a
    fraction with a real bar.  Too wide for the window: the whole drawing shrinks."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(140)
        self.blocks = []

    def set_blocks(self, blocks):
        self.blocks = list(blocks)
        self.update()

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
        if not self.blocks or w < 80 or h < 60:
            return
        f = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
        f.setPixelSize(17)
        p.setFont(f)
        fm = QFontMetricsF(f)
        pad, gap = 14.0, 40.0
        widths = []
        for top, bot in self.blocks:
            tw = fm.horizontalAdvance(top)
            bw = fm.horizontalAdvance(bot) if bot else 0.0
            widths.append(max(tw, bw) + 2 * pad)
        lab_in, lab_out = fm.horizontalAdvance("R(s)"), fm.horizontalAdvance("Y(s)")
        bh = 2 * fm.height() + 22 if any(b for _t, b in self.blocks) else fm.height() + 26
        total = lab_in + gap + sum(widths) + gap * (len(widths) - 1) + gap + lab_out
        sc = min(1.0, (w - 24) / total)
        if sc < 0.3:
            return
        p.translate(w / 2, h / 2 + 8)
        p.scale(sc, sc)
        x = -total / 2
        ink = QColor("#1d3557")

        def arrow(x0, x1):
            p.setPen(QPen(ink, 2))
            p.drawLine(QPointF(x0, 0), QPointF(x1, 0))
            p.drawLine(QPointF(x1, 0), QPointF(x1 - 8, -5))
            p.drawLine(QPointF(x1, 0), QPointF(x1 - 8, 5))

        p.setPen(ink)
        p.drawText(QRectF(x, -fm.height() / 2, lab_in, fm.height()), Qt.AlignmentFlag.AlignCenter, "R(s)")
        x += lab_in
        for i, ((top, bot), bw) in enumerate(zip(self.blocks, widths)):
            arrow(x, x + gap)
            x += gap
            p.setPen(QPen(ink, 2))
            p.setBrush(QColor("#eef3fb"))
            p.drawRoundedRect(QRectF(x, -bh / 2, bw, bh), 6, 6)
            p.setPen(QColor("#111111"))
            if bot:
                p.drawText(QRectF(x, -bh / 2 + 4, bw, fm.height()), Qt.AlignmentFlag.AlignCenter, top)
                p.setPen(QPen(QColor("#111111"), 1.6))
                p.drawLine(QPointF(x + pad * 0.6, 0), QPointF(x + bw - pad * 0.6, 0))
                p.setPen(QColor("#111111"))
                p.drawText(QRectF(x, bh / 2 - fm.height() - 4, bw, fm.height()), Qt.AlignmentFlag.AlignCenter, bot)
            else:
                p.drawText(QRectF(x, -bh / 2, bw, bh), Qt.AlignmentFlag.AlignCenter, top)
            x += bw
        arrow(x, x + gap)
        x += gap
        p.setPen(ink)
        p.drawText(QRectF(x, -fm.height() / 2, lab_out, fm.height()), Qt.AlignmentFlag.AlignCenter, "Y(s)")


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
    VIEWS = ["Pole-zero plot", "Block diagram", "Step response", "Impulse response"]
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
        lay.addWidget(QLabel("Block diagram"))
        self.diag_mode = QComboBox()
        self.diag_mode.addItems(["Single block", "Blocks in series"])
        self.diag_mode.setToolTip("Single block: G(s) in one box.  Blocks in series: the gain, then one block for each zero and pole.")
        lay.addWidget(self.diag_mode)
        self.working = QCheckBox("Show the full working")
        self.working.setToolTip("Adds the polynomial form, how K and G(0) are found, the order and type, and the time constants.")
        lay.addWidget(self.working)
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
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.diagram = BlockDiagram()
        self.plot = PoleZeroPlot()
        self.time_plot = TimePlot()
        # the bottom half: one view at a time, picked from a dropdown (a new tool later = one more view and one more entry here)
        self.view = QComboBox()
        self.view.addItems(self.VIEWS)
        self.view.setToolTip("What to show in the lower half.")
        self.stack = QStackedWidget()
        for w in (self.plot, self.diagram, self.time_plot):            # order matches VIEWS (the two responses share the time plot)
            self.stack.addWidget(w)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 2, 0, 0)
        bl.addWidget(self.view)
        bl.addWidget(self.stack, 1)
        split.addWidget(self.text)
        split.addWidget(bottom)
        split.setSizes([230, 520])
        rl.addWidget(split)
        self.num.textChanged.connect(self.update_result)
        self.den.textChanged.connect(self.update_result)
        self.diag_mode.activated.connect(lambda _i: (self.update_result(), self.changed()))
        self.working.toggled.connect(lambda _on: self.update_result())
        self.view.activated.connect(lambda _i: (self.show_view(), self.changed()))
        self.working.clicked.connect(lambda _c: self.changed())
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
            self.diagram.set_blocks([])
            self.time_plot.set_response(None, "step")
            self.show_view()
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
        self.text.setPlainText(core.report(a) if self.working.isChecked() else core.simple_report(a))
        self.diagram.set_blocks(core.blocks_series(a) if self.diag_mode.currentIndex() == 1 else core.blocks_single(a))
        self.plot.set_roots(a.zeros, a.poles)
        self.show_view()

    def show_view(self):
        """Show the picked view in the lower half (and feed the time plot when a response is picked)."""
        i = max(0, self.view.currentIndex())
        if i >= 2:
            kind = "impulse" if i == 3 else "step"
            self.time_plot.set_response(core.response_of(self.analysis, kind) if self.analysis else None, kind)
        self.stack.setCurrentIndex(min(i, 2))

    def fail(self, why):
        self.msg.setText(why)
        self.text.setPlainText("")
        self.plot.set_roots([], [])
        self.diagram.set_blocks([])
        self.time_plot.set_response(None, "step")

    def to_json(self):
        return {"num": self.num.text(), "den": self.den.text(), "diagram": self.diag_mode.currentText(), "working": self.working.isChecked(),
                "view": self.view.currentText()}

    def from_json(self, d):
        self.diag_mode.setCurrentIndex(max(0, self.diag_mode.findText(d.get("diagram", "Single block"))))
        self.working.setChecked(bool(d.get("working", False)))
        self.view.setCurrentIndex(max(0, self.view.findText(d.get("view", self.VIEWS[0]))))
        self.num.setText(d.get("num", ""))
        self.den.setText(d.get("den", ""))


class NetworkSection(Section):
    """Draw an electrical circuit or a mechanical system; get G(s) (with your names, and with numbers), its analog, and the usual plots."""
    key = "network"
    title = "Mechanical / Electrical systems"
    VIEWS = ("Analog system", "Pole-zero plot", "Block diagram", "Step response", "Impulse response")
    TOOLS = {"electrical": ("V", "R", "L", "C", "GND", "VO"), "mechanical": ("M", "K", "B", "WALL", "F", "X")}
    HINT = ("Pick a part, then click on the grid: two clicks for a part with two ends, one click for ground, wall, force and the output.\n"
            "Wire joins parts. R rotates, Delete removes the selected part, right click goes back to Select.")

    def __init__(self, changed):
        super().__init__(changed)
        self.domain = "electrical"
        self.data = {"electrical": [], "mechanical": []}
        self.sol = None
        self.analysis = None
        self.numbers = None
        self.tab = None
        self._building = False
        lay = QVBoxLayout(self.inputs)
        lay.setContentsMargins(8, 4, 8, 8)
        self.dom = QComboBox()
        self.dom.addItems(["Electrical circuit", "Mechanical system"])
        lay.addWidget(self.dom)
        grid = QGridLayout()
        self.group = QButtonGroup(self.inputs)
        self.group.setExclusive(True)
        self.btns = {}
        order = [("select", "Select"), ("wire", "Wire")] + [(k, cv.LABELS[k]) for k in ckt.ELECTRICAL if k in self.TOOLS["electrical"]] + \
                [(k, cv.LABELS[k]) for k in ckt.MECHANICAL]
        for tool, text in order:
            b = QPushButton(text)
            b.setCheckable(True)
            self.group.addButton(b)
            self.btns[tool] = b
            b.clicked.connect(lambda _c=False, t=tool: self.canvas.set_tool(t))
        self.btns["select"].setChecked(True)
        self.tool_grid = grid
        lay.addLayout(grid)
        row = QHBoxLayout()
        self.rot_btn = QPushButton("Rotate (R)")
        self.del_btn = QPushButton("Delete")
        row.addWidget(self.rot_btn)
        row.addWidget(self.del_btn)
        lay.addLayout(row)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(130)
        self.table.setToolTip("Leave Value empty to keep the part as a symbol (R, L, C ...); type a number to use it.")
        lay.addWidget(QLabel("Parts (leave Value empty to keep the name as a symbol)"))
        lay.addWidget(self.table)
        self.ex = QComboBox()
        self.ex.addItem("Examples…")
        for name, _d in ckt.EXAMPLES:
            self.ex.addItem(name)
        lay.addWidget(self.ex)
        self.send = QPushButton("Open G(s) in Transfer function")
        self.send.setToolTip("Needs numbers for every part.")
        lay.addWidget(self.send)
        hint = QLabel(self.HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#5b6675;")
        lay.addWidget(hint)
        lay.addStretch(1)

        rl = QVBoxLayout(self.results)
        rl.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Vertical)
        self.canvas = cv.Canvas()
        self.canvas.empty_text = "Pick a part on the left and click here to draw, or choose an example."
        self.canvas.set_parts(self.data["electrical"])
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.analog = cv.Canvas(readonly=True)
        self.plot = PoleZeroPlot()
        self.diagram = BlockDiagram()
        self.time_plot = TimePlot()
        self.view = QComboBox()
        self.view.addItems(self.VIEWS)
        self.stack = QStackedWidget()
        for w in (self.analog, self.plot, self.diagram, self.time_plot):
            self.stack.addWidget(w)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 2, 0, 0)
        rv.addWidget(self.view)
        rv.addWidget(self.stack, 1)
        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.addWidget(self.text)
        bottom.addWidget(right)
        bottom.setSizes([380, 520])
        split.addWidget(self.canvas)
        split.addWidget(bottom)
        split.setSizes([420, 330])
        rl.addWidget(split)

        self.dom.activated.connect(lambda i: self.set_domain("electrical" if i == 0 else "mechanical", user=True))
        self.canvas.edited.connect(self.parts_changed)
        self.canvas.tool_reset.connect(lambda: (self.btns["select"].setChecked(True), self.canvas.set_tool("select")))
        self.rot_btn.clicked.connect(self.canvas.rotate_selected)
        self.del_btn.clicked.connect(self.canvas.delete_selected)
        self.table.itemChanged.connect(self.cell_edited)
        self.ex.activated.connect(self.load_example)
        self.send.clicked.connect(self.open_in_tf)
        self.view.activated.connect(lambda _i: (self.show_view(), self.changed()))
        self.layout_tools()
        self.set_domain("electrical")

    # ------------------------------------------------------------------ the left column
    def layout_tools(self):
        for i in reversed(range(self.tool_grid.count())):
            self.tool_grid.takeAt(i)
        tools = ["select", "wire"] + list(self.TOOLS[self.domain])
        for b in self.btns.values():
            b.setVisible(False)
        for i, t in enumerate(tools):
            self.tool_grid.addWidget(self.btns[t], i // 2, i % 2)
            self.btns[t].setVisible(True)

    def set_domain(self, domain, user=False):
        self.domain = domain
        self.dom.setCurrentIndex(0 if domain == "electrical" else 1)
        self.view.setItemText(0, "Mechanical analog" if domain == "electrical" else "Electrical analog")
        self.canvas.set_parts(self.data[domain])
        self.btns["select"].setChecked(True)
        self.canvas.set_tool("select")
        self.layout_tools()
        self.rebuild_table()
        self.update_result()
        if user:
            self.changed()

    def rebuild_table(self):
        self._building = True
        self.table.setRowCount(0)
        self.rows = [i for i, p in enumerate(self.canvas.parts) if p["kind"] in ckt.VALUED]
        self.table.setRowCount(len(self.rows))
        for r, i in enumerate(self.rows):
            p = self.canvas.parts[i]
            kind = QTableWidgetItem("%s  " % p["kind"])
            self.table.setItem(r, 0, QTableWidgetItem(p.get("name", "")))
            self.table.setItem(r, 1, QTableWidgetItem(p.get("value", "")))
        self._building = False

    def cell_edited(self, item):
        if self._building:
            return
        r, c = item.row(), item.column()
        if r >= len(self.rows):
            return
        part = self.canvas.parts[self.rows[r]]
        part["name" if c == 0 else "value"] = item.text().strip()
        self.canvas.update()
        self.update_result()
        self.changed()

    def parts_changed(self):
        self.rebuild_table()
        self.update_result()
        self.changed()

    def load_example(self, i):
        if i <= 0:
            return
        self.ex.setCurrentIndex(0)
        domain, parts = ckt.example(i - 1)
        self.data[domain] = [dict(p) for p in parts]
        self.set_domain(domain)
        self.changed()

    def open_in_tf(self):
        if not self.numbers or self.tab is None:
            return
        tf = self.tab.section("transfer_function")
        n, d = self.numbers
        tf.num.setText("[" + " ".join(core.fmt(x, 12) for x in n) + "]")
        tf.den.setText("[" + " ".join(core.fmt(x, 12) for x in d) + "]")
        self.tab.show_section("transfer_function")

    # ------------------------------------------------------------------ the answer
    def update_result(self):
        parts = self.canvas.parts
        self.sol = self.analysis = self.numbers = None
        analog_parts, analog_lines = [], []
        if not any(p["kind"] != "W" for p in parts):
            self.text.setPlainText(self.HINT)
            self.finish([], "")
            return
        try:
            sol = ckt.solve(parts, self.domain)
        except ckt.CircuitError as e:
            self.text.setPlainText(str(e))
            self.finish([], "")
            return
        self.sol = sol
        lines = ["G(s) = %s/%s = %s" % (sol.out_name, sol.in_name, ckt.tf_text(sol)), "Equation: " + ckt.equation_text(sol)]
        nums = ckt.numeric(sol, {})
        if nums is None:
            left = sorted(sol.num.names() | sol.den.names())
            lines.append("")
            lines.append("Give a number to %s to get the poles and the step response." % ", ".join(left))
        else:
            try:
                self.analysis = core.analyze(nums[0], nums[1])
                self.numbers = nums
                lines.append("")
                lines.append(core.simple_report(self.analysis))
            except core.TFError as e:
                lines.append("")
                lines.append(str(e))
        try:
            if self.domain == "electrical":
                if ckt.is_series_loop(parts):
                    analog_parts, analog_lines = ckt.analog_of_loop(parts)
                else:
                    analog_lines = ckt.analog_lines_general(parts, "electrical")
            else:
                if ckt.is_single_body(parts):
                    analog_parts, analog_lines = ckt.analog_of_body(parts)
                else:
                    analog_lines = ckt.analog_lines_general(parts, "mechanical")
        except ckt.CircuitError:
            pass
        lines += [""] + analog_lines
        self.text.setPlainText("\n".join(lines))
        self.finish(analog_parts, "A drawn analog is made for a single series loop (electrical) or one rigid body (mechanical).")

    def finish(self, analog_parts, empty):
        self.analog.empty_text = empty
        self.analog.set_parts(analog_parts)
        a = self.analysis
        self.send.setEnabled(self.numbers is not None)
        self.plot.set_roots(a.zeros if a else [], a.poles if a else [])
        self.diagram.set_blocks(core.blocks_single(a) if a else [])
        self.show_view()

    def show_view(self):
        i = max(0, self.view.currentIndex())
        if i >= 3:
            kind = "impulse" if i == 4 else "step"
            self.time_plot.set_response(core.response_of(self.analysis, kind) if self.analysis else None, kind)
        self.stack.setCurrentIndex(min(i, 3))

    # ------------------------------------------------------------------ files
    def to_json(self):
        return {"domain": self.domain, "electrical": cv.parts_to_json(self.data["electrical"]), "mechanical": cv.parts_to_json(self.data["mechanical"]),
                "view": self.view.currentIndex()}

    def from_json(self, d):
        self.data = {"electrical": cv.parts_from_json(d.get("electrical")), "mechanical": cv.parts_from_json(d.get("mechanical"))}
        self.view.setCurrentIndex(min(max(int(d.get("view", 0)), 0), len(self.VIEWS) - 1) if isinstance(d.get("view", 0), int) else 0)
        self.set_domain("mechanical" if d.get("domain") == "mechanical" else "electrical")


SECTIONS = [TransferFunctionSection, NetworkSection]


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
        for s in self.sections:
            s.tab = self
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

    def show_section(self, key):
        for d in self.drops:
            if d.section.key == key:
                d.set_open(True)

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
