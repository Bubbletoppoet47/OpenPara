"""trainer_charts.py - the Charts pane of the Trainer window: PlotWidget (a small chart painter) and ChartsPane (which run, which figure, which rungs).

What is drawn is described by chart_data.py (no Qt); this file only paints it.  One colour and one marker shape for each series (a rung keeps its colour in every figure of a run, so the
colour follows the rung, not its place in the list); lines 2 px, other seeds 1 px; markers with a 2 px ring of the surface round them; a legend above the plot whenever there are two or more
series; the grid and the axes recede; hovering a point says what is behind it; and a Table button shows the numbers that are drawn.  The eight hues are the categorical palette checked for
colour-vision differences (adjacent pairs); the shapes carry the series where the colours cannot.
"""
import math
import os

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout,
                             QWidget)

import chart_data as cd

PALETTE = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647"]
SHAPES = ["circle", "square", "diamond", "up", "down", "pentagon", "hexagon", "plus"]
SURFACE, GRID, AXIS, INK, SPAN = "#ffffff", "#e3e6ea", "#6a7790", "#2b3445", "#eef3fa"
MUTED = "#6a7790"


def marker_path(shape, cx, cy, r):
    p = QPainterPath()
    if shape == "circle":
        p.addEllipse(QPointF(cx, cy), r, r)
    elif shape == "square":
        p.addRect(QRectF(cx - r * 0.85, cy - r * 0.85, r * 1.7, r * 1.7))
    elif shape == "diamond":
        p.addPolygon(QPolygonF([QPointF(cx, cy - r * 1.2), QPointF(cx + r * 1.2, cy), QPointF(cx, cy + r * 1.2), QPointF(cx - r * 1.2, cy)]))
    elif shape == "up":
        p.addPolygon(QPolygonF([QPointF(cx, cy - r * 1.15), QPointF(cx + r * 1.1, cy + r * 0.85), QPointF(cx - r * 1.1, cy + r * 0.85)]))
    elif shape == "down":
        p.addPolygon(QPolygonF([QPointF(cx, cy + r * 1.15), QPointF(cx + r * 1.1, cy - r * 0.85), QPointF(cx - r * 1.1, cy - r * 0.85)]))
    elif shape in ("pentagon", "hexagon"):
        n = 5 if shape == "pentagon" else 6
        p.addPolygon(QPolygonF([QPointF(cx + r * 1.1 * math.sin(2 * math.pi * k / n), cy - r * 1.1 * math.cos(2 * math.pi * k / n)) for k in range(n)]))
    else:
        t = r * 0.45
        p.addPolygon(QPolygonF([QPointF(cx - t, cy - r), QPointF(cx + t, cy - r), QPointF(cx + t, cy - t), QPointF(cx + r, cy - t), QPointF(cx + r, cy + t), QPointF(cx + t, cy + t),
                                QPointF(cx + t, cy + r), QPointF(cx - t, cy + r), QPointF(cx - t, cy + t), QPointF(cx - r, cy + t), QPointF(cx - r, cy - t), QPointF(cx - t, cy - t)]))
    return p


def nice_ticks(lo, hi, n=5, integer=False):
    """About n round values from lo to hi (inclusive of the round numbers inside the range); whole numbers only with `integer`."""
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    if integer:
        step = max(1.0, float(math.ceil(step)))
    first = math.ceil(lo / step - 1e-9) * step
    out, v = [], first
    while v <= hi + step * 1e-9:
        out.append(round(v, 12))
        v += step
    return out


def log_ticks(lo, hi):
    a, b = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    out = [10.0 ** k for k in range(a, b + 1)]
    if b - a <= 3:
        out = sorted({m * 10.0 ** k for k in range(a, b + 1) for m in (1, 2, 5)})
    return [v for v in out if lo * 0.999 <= v <= hi * 1.001] or [lo, hi]


def fmt_tick(v):
    if v == 0:
        return "0"
    if abs(v) >= 1e5 or abs(v) < 1e-3:
        return f"{v:.0e}".replace("e-0", "e-").replace("e+0", "e").replace("e+", "e")
    return f"{v:g}"


class PlotWidget(QWidget):
    L, R, B = 62, 14, 40

    def __init__(self):
        super().__init__()
        self.spec = None
        self._pts = []                                       # [(x px, y px, tip)] of the last paint
        self.setMinimumSize(360, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_spec(self, spec):
        self.spec = spec
        self.update()

    # ------------------------------------------------------------------ the legend and the ranges
    def _legend(self, width):
        """[(series, x, y, label width)] and the height it takes: the series with a legend entry (one entry per name), wrapped."""
        fm = QFontMetrics(self.font())
        seen, items = set(), []
        for s in self.spec["series"]:
            if s["legend"] and s["slot"] is not None and s["name"] not in seen and s["points"]:
                seen.add(s["name"])
                items.append(s)
        if len(items) < 2:                                                               # (one series needs no legend: the title names it)
            items = []
        items += [{"hline": True, "name": label, "slot": None} for _y, label in self.spec["hlines"]]
        out, x, y, lh = [], 0, 0, fm.height() + 6
        for s in items:
            w = 26 + fm.horizontalAdvance(s["name"]) + 16
            if x and x + w > width:
                x, y = 0, y + lh
            out.append((s, x, y, w))
            x += w
        return out, (y + lh if out else 0)

    def _ranges(self):
        sp = self.spec
        xs, ys = [], []
        for s in sp["series"]:
            for x, y, _t in s["points"]:
                xs.append(x)
                ys.append(y)
            for x, lo, hi in s["whisk"] + s["band"]:
                xs.append(x)
                ys += [lo, hi]
        ys += [y for y, _l in sp["hlines"]]
        xs += [x for x, _l in sp["vlines"]] + [v for a, b, _l in sp["spans"] for v in (a, b)]
        if sp["xcat"]:
            x0, x1 = -0.5, len(sp["xcat"]) - 0.5
        else:
            xs = [x for x in xs if x > 0] if sp["xlog"] else xs
            x0, x1 = (min(xs), max(xs)) if xs else (0.0, 1.0)
            if sp["xlog"]:
                x0, x1 = x0 / 1.6, x1 * 1.6
            else:
                pad = (x1 - x0) * 0.04 or 1.0
                x0, x1 = x0 - pad, x1 + pad
        ys = [y for y in ys if y > 0] if sp["ylog"] else ys
        y0, y1 = (min(ys), max(ys)) if ys else (0.0, 1.0)
        if sp["ylog"]:
            y0, y1 = 10 ** math.floor(math.log10(y0)), 10 ** math.ceil(math.log10(y1 * 1.0001))
            if y0 == y1:
                y1 = y0 * 10
        else:
            if sp["y0"]:
                y0 = min(0.0, y0)
            y1 = y1 + (y1 - y0) * 0.08 if y1 > y0 else y1 + 1.0
        return x0, x1, y0, y1

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _e):
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing)
        g.fillRect(self.rect(), QColor(SURFACE))
        sp = self.spec
        self._pts = []
        if sp is None:
            g.end()
            return
        fm = QFontMetrics(self.font())
        g.setPen(QColor(INK))
        g.drawText(QRectF(self.L, 4, self.width() - self.L - self.R, fm.height() + 2), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), sp["title"])
        legend, lh = self._legend(self.width() - self.L - self.R)
        top = 8 + fm.height() + 6 + lh
        plot = QRectF(self.L, top, self.width() - self.L - self.R, max(40, self.height() - top - self.B))
        if sp.get("empty"):
            g.setPen(QColor(AXIS))
            g.drawText(plot.adjusted(10, 10, -10, -10), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), sp["empty"])
            g.end()
            return
        x0, x1, y0, y1 = self._ranges()

        def fx(v):
            return (math.log10(v) - math.log10(x0)) / (math.log10(x1) - math.log10(x0)) if sp["xlog"] else (v - x0) / ((x1 - x0) or 1.0)

        def fy(v):
            return (math.log10(v) - math.log10(y0)) / (math.log10(y1) - math.log10(y0)) if sp["ylog"] else (v - y0) / ((y1 - y0) or 1.0)

        def tx(v):
            return plot.left() + plot.width() * fx(v)

        def ty(v):
            return plot.bottom() - plot.height() * fy(v)

        # legend
        for s, lx, ly, _w in legend:
            cx, cy = self.L + lx + 10, 8 + fm.height() + 6 + ly + (fm.height() + 6) / 2
            if s.get("hline"):                                                           # a reference line: a dash in the ink
                g.setPen(QPen(QColor(INK), 1.2, Qt.PenStyle.DashLine))
                g.drawLine(QPointF(cx - 10, cy), QPointF(cx + 10, cy))
                g.setPen(QColor(INK))
                g.drawText(QRectF(self.L + lx + 26, cy - fm.height() / 2, fm.horizontalAdvance(s["name"]) + 4, fm.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), s["name"])
                continue
            col = QColor(PALETTE[s["slot"]])
            if s["line"]:
                g.setPen(QPen(col, 2, Qt.PenStyle.DashLine if s["dash"] else Qt.PenStyle.SolidLine))
                g.drawLine(QPointF(cx - 10, cy), QPointF(cx + 10, cy))
            if s["markers"]:
                g.setPen(QPen(QColor(SURFACE), 2))
                g.setBrush(QBrush(col))
                g.drawPath(marker_path(SHAPES[s["slot"]], cx, cy, 4.5))
            g.setPen(QColor(INK))
            g.drawText(QRectF(self.L + lx + 26, cy - fm.height() / 2, fm.horizontalAdvance(s["name"]) + 4, fm.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), s["name"])
        # spans and the grid
        for a, b, label in sp["spans"]:
            r = QRectF(tx(a) - 4, plot.top(), max(8.0, tx(b) - tx(a) + 8), plot.height())
            g.fillRect(r, QColor(SPAN))
            g.setPen(QColor(AXIS))
            g.drawText(QRectF(r.left(), plot.bottom() - fm.height() - 2, max(r.width(), 110), fm.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
        yt = log_ticks(y0, y1) if sp["ylog"] else nice_ticks(y0, y1)
        for v in yt:
            y = ty(v)
            g.setPen(QPen(QColor(GRID), 1))
            g.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            g.setPen(QColor(AXIS))
            g.drawText(QRectF(0, y - 8, self.L - 6, 16), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), fmt_tick(v))
        if sp["xcat"]:
            xt = [(float(i), name) for i, name in enumerate(sp["xcat"])]
        else:
            xt = [(v, fmt_tick(v)) for v in (log_ticks(x0, x1) if sp["xlog"] else nice_ticks(x0, x1, integer=sp.get("xint", False)))]
        step = max(1, int(math.ceil(len(xt) * 46.0 / max(plot.width(), 1))))
        for i, (v, label) in enumerate(xt):
            if i % step:
                continue
            x = tx(v)
            g.setPen(QPen(QColor(GRID), 1))
            g.drawLine(QPointF(x, plot.bottom()), QPointF(x, plot.bottom() + 4))
            g.setPen(QColor(AXIS))
            g.drawText(QRectF(x - 34, plot.bottom() + 5, 68, fm.height()), int(Qt.AlignmentFlag.AlignCenter), label)
        g.setPen(QColor(AXIS))
        g.drawText(QRectF(plot.left(), self.height() - fm.height() - 3, plot.width(), fm.height()), int(Qt.AlignmentFlag.AlignCenter), sp["xlabel"])
        g.save()
        g.translate(12, plot.top() + plot.height() / 2)
        g.rotate(-90)
        g.drawText(QRectF(-plot.height() / 2, -8, plot.height(), 16), int(Qt.AlignmentFlag.AlignCenter), sp["ylabel"])
        g.restore()
        g.setPen(QPen(QColor(GRID), 1))
        g.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))
        # reference lines
        g.setClipRect(plot.adjusted(-8, -10, 8, 2))
        for y, label in sp["hlines"]:
            if (not sp["ylog"] or y > 0) and y0 <= y <= y1:
                g.setPen(QPen(QColor(INK), 1.2, Qt.PenStyle.DashLine))
                g.drawLine(QPointF(plot.left(), ty(y)), QPointF(plot.right(), ty(y)))
        for x, label in sp["vlines"]:
            if (not sp["xlog"] or x > 0) and x0 <= x <= x1:
                g.setPen(QPen(QColor(INK), 1.2, Qt.PenStyle.DashLine))
                g.drawLine(QPointF(tx(x), plot.top()), QPointF(tx(x), plot.bottom()))
                g.setPen(QColor(INK))
                g.drawText(QRectF(tx(x) + 3, plot.top() + 1, 120, fm.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
        # bands, whiskers, lines, markers
        series = [s for s in sp["series"] if s["slot"] is not None]
        for s in series:
            col = QColor(PALETTE[s["slot"]])
            if s["band"]:
                fill = QColor(col)
                fill.setAlphaF(0.18)
                top_edge = [QPointF(tx(x), ty(hi)) for x, lo, hi in s["band"]]
                low_edge = [QPointF(tx(x), ty(lo)) for x, lo, hi in reversed(s["band"])]
                if len(s["band"]) == 1:
                    x = s["band"][0][0]
                    g.setPen(QPen(fill, 8))
                    g.drawLine(QPointF(tx(x), ty(s["band"][0][2])), QPointF(tx(x), ty(s["band"][0][1])))
                else:
                    g.setPen(Qt.PenStyle.NoPen)
                    g.setBrush(QBrush(fill))
                    g.drawPolygon(QPolygonF(top_edge + low_edge))
        for s in series:
            col = QColor(PALETTE[s["slot"]])
            for x, lo, hi in s["whisk"]:
                g.setPen(QPen(col, 1.6))
                g.drawLine(QPointF(tx(x), ty(lo)), QPointF(tx(x), ty(hi)))
                for yy in (lo, hi):
                    g.drawLine(QPointF(tx(x) - 4, ty(yy)), QPointF(tx(x) + 4, ty(yy)))
            if s["line"] and len(s["points"]) > 1:
                c = QColor(col)
                if s["thin"]:
                    c.setAlphaF(0.45)
                g.setPen(QPen(c, 1.0 if s["thin"] else s["width"], Qt.PenStyle.DashLine if s["dash"] else Qt.PenStyle.SolidLine))
                g.setBrush(Qt.BrushStyle.NoBrush)
                path = QPainterPath()
                for i, (x, y, _t) in enumerate(s["points"]):
                    (path.moveTo if i == 0 else path.lineTo)(tx(x), ty(y))
                g.drawPath(path)
        for s in series:
            col = QColor(PALETTE[s["slot"]])
            for x, y, tip in s["points"]:
                px, py = tx(x), ty(y)
                if s["markers"]:
                    g.setPen(QPen(QColor(SURFACE), 2))
                    g.setBrush(QBrush(col))
                    g.drawPath(marker_path(SHAPES[s["slot"]], px, py, 5.0))
                if tip:
                    self._pts.append((px, py, tip))
        g.end()

    # ------------------------------------------------------------------ hover
    def tip_at(self, pos):
        best, bd = "", 15.0 ** 2
        for x, y, tip in self._pts:
            d = (x - pos.x()) ** 2 + (y - pos.y()) ** 2
            if d <= bd:
                best, bd = tip, d
        return best

    def mouseMoveEvent(self, e):
        t = self.tip_at(e.position())
        if t:
            QToolTip.showText(e.globalPosition().toPoint(), t, self)
        else:
            QToolTip.hideText()


class ChartsPane(QWidget):
    """Which run, which figure, which rungs; the chart or the table of its numbers; a sentence under it."""
    shown = pyqtSignal(str)                                  # the id of the figure that is drawn (for the window's status line)

    def __init__(self):
        super().__init__()
        self.data = None
        self._runs = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(QLabel("Run"))
        self.run_box = QComboBox()
        self.run_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.run_box.setMinimumContentsLength(18)
        self.run_box.setToolTip("A training run of a distance network in this project (the newest first), or a run folder opened from disk.")
        self.run_box.activated.connect(lambda _i: self._pick_run())
        row.addWidget(self.run_box, 1)
        self.open_btn = QPushButton("Open run folder…")
        self.open_btn.clicked.connect(lambda _c=False: self.open_folder())
        row.addWidget(self.open_btn)
        v.addLayout(row)
        row = QHBoxLayout()
        self.fig_box = QComboBox()
        for fid, label in cd.FIGURES:
            self.fig_box.addItem(label, fid)
        self.group_box, self.key_box, self.metric_box, self.when_box = QComboBox(), QComboBox(), QComboBox(), QComboBox()
        self.group_label, self.key_label, self.metric_label, self.when_label = QLabel("Rungs"), QLabel("Rung"), QLabel("Show"), QLabel("At")
        self.when_box.addItem("start of training", "start")
        self.when_box.addItem("end of training", "end")
        for lab, box in ((QLabel("Figure"), self.fig_box), (self.group_label, self.group_box), (self.key_label, self.key_box), (self.metric_label, self.metric_box), (self.when_label, self.when_box)):
            row.addWidget(lab)
            row.addWidget(box)
        row.addStretch(1)
        self.table_btn = QPushButton("Table")
        self.table_btn.setCheckable(True)
        self.table_btn.setToolTip("The numbers that are drawn, as a table.")
        row.addWidget(self.table_btn)
        v.addLayout(row)
        self.stack = QStackedWidget()
        self.plot = PlotWidget()
        self.table = QTableWidget(0, 3)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stack.addWidget(self.plot)
        self.stack.addWidget(self.table)
        v.addWidget(self.stack, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        v.addWidget(self.note)
        for box in (self.fig_box, self.group_box, self.key_box, self.metric_box, self.when_box):
            box.currentIndexChanged.connect(lambda _i: self._changed())
        self.table_btn.toggled.connect(lambda on: (self.stack.setCurrentIndex(1 if on else 0), self.refresh()))
        self._fill_options()
        self.refresh()

    # ------------------------------------------------------------------ the runs
    def set_runs_dir(self, folder):
        """The runs of a project: every folder of `folder` that holds a distance-network run, newest first.  The one shown stays when it is still there."""
        runs = []
        if folder and os.path.isdir(folder):
            for name in sorted(os.listdir(folder), reverse=True):
                p = os.path.join(folder, name)
                if os.path.isdir(p) and cd.is_run(p):
                    runs.append((name, p))
        self._runs = runs
        cur = self.data.dir if self.data is not None else None
        self.run_box.blockSignals(True)
        self.run_box.clear()
        for name, p in runs:
            self.run_box.addItem(name, p)
        if cur and all(p != cur for _n, p in runs):
            self.run_box.insertItem(0, os.path.basename(cur) + "  (opened)", cur)
        i = self.run_box.findData(cur) if cur else -1
        self.run_box.setCurrentIndex(i if i >= 0 else (0 if self.run_box.count() and self.data is None else -1))
        self.run_box.blockSignals(False)
        if self.data is None and runs:
            self.load(runs[0][1])

    def _pick_run(self):
        p = self.run_box.currentData()
        if p:
            self.load(p)

    def open_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Open the folder of a distance-network run (it has results.csv)")
        if p:
            if not cd.is_run(p):
                self.note.setText("That folder is not a distance-network run: it has no results.csv, lr_sweep.csv and rungs.csv.")
                return
            self.load(p)
            self.set_runs_dir(os.path.dirname(p))

    def load(self, run_dir):
        """Show the run in `run_dir` (a folder with results.csv).  -> True when there is something to draw."""
        self.data = cd.RunData(run_dir) if cd.is_run(run_dir) else None
        i = self.run_box.findData(run_dir)
        if i >= 0:
            self.run_box.blockSignals(True)
            self.run_box.setCurrentIndex(i)
            self.run_box.blockSignals(False)
        self._fill_options()
        self.refresh()
        return self.data is not None and self.data.ok

    # ------------------------------------------------------------------ the choices
    def _fill_options(self):
        """The boxes follow the figure (which of them it uses) and the run (its rungs)."""
        fid = self.fig_box.currentData()
        for box in (self.group_box, self.key_box, self.metric_box, self.when_box):
            box.blockSignals(True)
        keep = (self.group_box.currentIndex(), self.key_box.currentIndex(), self.metric_box.currentIndex())
        self.group_box.clear()
        self.key_box.clear()
        if self.data is not None:
            for label, keys in self.data.groups():
                self.group_box.addItem(label, keys)
            for k in self.data.keys:
                self.key_box.addItem(self.data.label(k), k)
        self.metric_box.clear()
        if fid == "learning":
            for k, (label, *_r) in cd.CURVE_METRICS.items():
                self.metric_box.addItem(label, k)
        elif fid == "layers":
            for k, (label, *_r) in cd.LAYER_METRICS.items():
                self.metric_box.addItem(label, k)
        for box, i in zip((self.group_box, self.key_box, self.metric_box), keep):
            if 0 <= i < box.count():
                box.setCurrentIndex(i)
        for box in (self.group_box, self.key_box, self.metric_box, self.when_box):
            box.blockSignals(False)
        use = {"learning": ("group", "metric"), "sweep": ("key",), "layers": ("group", "metric", "when"), "final": ("group",), "epochs": ("group",), "momentum": ()}[fid]
        for name, (lab, box) in {"group": (self.group_label, self.group_box), "key": (self.key_label, self.key_box), "metric": (self.metric_label, self.metric_box),
                                 "when": (self.when_label, self.when_box)}.items():
            lab.setVisible(name in use)
            box.setVisible(name in use)

    def _changed(self):
        self._fill_options()
        self.refresh()

    def options(self):
        return {"keys": self.group_box.currentData(), "key": self.key_box.currentData(),
                "metric": self.metric_box.currentData(), "when": self.when_box.currentData()}

    def spec(self):
        fid = self.fig_box.currentData()
        o = self.options()
        return cd.figure(fid, self.data, keys=o["keys"], key=o["key"], metric=o["metric"], when=o["when"])

    def refresh(self):
        spec = self.spec()
        self.plot.set_spec(spec)
        head, rows = cd.table_rows(spec)
        self.table.setColumnCount(len(head))
        self.table.setHorizontalHeaderLabels(head)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(f"{v:.5g}" if isinstance(v, float) else str(v)))
        self.note.setText(spec["note"] or (spec["empty"] or ""))
        self.shown.emit(self.fig_box.currentData())
