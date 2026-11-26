"""wb_testing_compare.py - the "Models side by side" pane of the Model testing window: one row per run made in the window on the open session (the numbers of
wb_testing_boxes.summarise), and a chart of the share of boxes that pass, by distance (the LiDAR's, in the Analyse tab's six bands).

A run keeps its colour and its marker shape for as long as the window is open (the colour follows the run, not its place in the table), up to eight runs on the chart; the table has all of
them.  The shapes make the lines readable without the colours.  A band with fewer than MIN_N boxes judged is drawn hollow: one or two boxes say little.
Nothing here runs a model: the window hands over the numbers, and the two buttons call back into it.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget


PALETTE = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647"]       # the eight categorical hues, in their fixed order
SHAPES = ["circle", "square", "diamond", "up", "down", "pentagon", "hexagon", "plus"]
MIN_N = 5
BAND_NAMES = ["0-2", "2-4", "4-6", "6-8", "8-10", "10+"]
GRID, AXIS, INK = "#e3e6ea", "#6a7790", "#2b3445"
HEADING = "color:#4a5872; font-size:11px; font-weight:600; letter-spacing:1px;"


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
    else:                                                                                   # plus
        t = r * 0.45
        p.addPolygon(QPolygonF([QPointF(cx - t, cy - r), QPointF(cx + t, cy - r), QPointF(cx + t, cy - t), QPointF(cx + r, cy - t), QPointF(cx + r, cy + t), QPointF(cx + t, cy + t),
                                QPointF(cx + t, cy + r), QPointF(cx - t, cy + r), QPointF(cx - t, cy + t), QPointF(cx - r, cy + t), QPointF(cx - r, cy - t), QPointF(cx - t, cy - t)]))
    return p


def swatch(slot, px=16):
    """The small picture of a run's colour and shape (the legend: the table's first column)."""
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    if slot is not None and 0 <= slot < len(PALETTE):
        g = QPainter(pm)
        g.setRenderHint(QPainter.RenderHint.Antialiasing)
        g.setPen(QPen(QColor("#ffffff"), 1.5))
        g.setBrush(QBrush(QColor(PALETTE[slot])))
        g.drawPath(marker_path(SHAPES[slot], px / 2, px / 2, px * 0.33))
        g.end()
    return QIcon(pm)


class BandChart(QWidget):
    """Share that pass (0-100 %) in the six distance bands, one line with markers per run."""
    L, R, T, B = 36, 10, 8, 24

    def __init__(self):
        super().__init__()
        self.series = []                                     # [{"name", "slot", "points": [(band index, pass %, n judged, n passed)]}]
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_series(self, series):
        self.series = series
        self.update()

    def _xy(self, bi, pct):
        w, h = self.width() - self.L - self.R, self.height() - self.T - self.B
        return self.L + w * (bi + 0.5) / len(BAND_NAMES), self.T + h * (1 - pct / 100.0)

    def paintEvent(self, _e):
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing)
        g.fillRect(self.rect(), QColor("#ffffff"))
        w, h = self.width() - self.L - self.R, self.height() - self.T - self.B
        g.setFont(self.font())
        for v in (0, 25, 50, 75, 100):                                                       # recessive grid, the numbers in the axis ink
            y = self.T + h * (1 - v / 100.0)
            g.setPen(QPen(QColor(GRID), 1))
            g.drawLine(self.L, int(y), self.L + int(w), int(y))
            g.setPen(QColor(AXIS))
            g.drawText(QRectF(0, y - 8, self.L - 5, 16), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{v}%")
        for i, name in enumerate(BAND_NAMES):
            x, _y = self._xy(i, 0)
            g.setPen(QColor(AXIS))
            g.drawText(QRectF(x - 24, self.T + h + 4, 48, 16), int(Qt.AlignmentFlag.AlignCenter), name)
        for s in self.series:
            if s["slot"] is None or not s["points"]:
                continue
            col = QColor(PALETTE[s["slot"]])
            pts = [self._xy(bi, pct) for bi, pct, _n, _p in s["points"]]
            g.setPen(QPen(col, 2))
            g.setBrush(Qt.BrushStyle.NoBrush)
            for a, b in zip(pts, pts[1:]):
                g.drawLine(QPointF(*a), QPointF(*b))
        for s in self.series:                                                                # the markers over every line, a 2 px ring of the surface round each
            if s["slot"] is None:
                continue
            col = QColor(PALETTE[s["slot"]])
            for (bi, pct, n, _p), (x, y) in zip(s["points"], [self._xy(bi, pct) for bi, pct, _n, _p in s["points"]]):
                path = marker_path(SHAPES[s["slot"]], x, y, 5.0)
                g.setPen(QPen(QColor("#ffffff"), 2))
                g.setBrush(QBrush(col) if n >= MIN_N else QBrush(QColor("#ffffff")))
                g.drawPath(path)
                if n < MIN_N:
                    g.setPen(QPen(col, 1.5))
                    g.setBrush(Qt.BrushStyle.NoBrush)
                    g.drawPath(path)
        if not any(s["points"] for s in self.series):
            g.setPen(QColor(AXIS))
            g.drawText(QRectF(self.L, self.T, w, h), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), "Nothing to show yet: run a model over the session.")
        g.end()

    def hit(self, pos):
        """The nearest marker within 14 px of `pos`: (series, point) or None."""
        best, bd = None, 14.0 ** 2
        for s in self.series:
            if s["slot"] is None:
                continue
            for pt in s["points"]:
                x, y = self._xy(pt[0], pt[1])
                d = (x - pos.x()) ** 2 + (y - pos.y()) ** 2
                if d <= bd:
                    best, bd = (s, pt), d
        return best

    def text_at(self, pos):
        h = self.hit(pos)
        if h is None:
            return ""
        s, (bi, pct, n, p) = h
        return f"{s['name']}\n{BAND_NAMES[bi]} m: {p} of {n} pass ({pct:.0f} %)" + ("\n(only a few boxes: not much to go on)" if n < MIN_N else "")

    def mouseMoveEvent(self, e):
        t = self.text_at(e.position())
        if t:
            QToolTip.showText(e.globalPosition().toPoint(), t, self)
        else:
            QToolTip.hideText()


class CompareView(QWidget):
    """The pane: the table and the chart.  set_items() is all the window has to call."""
    HEAD = ["Model", "Judged", "Pass", "Off by (median)", "Off by (mean)"]

    def __init__(self, on_run_others, on_export):
        super().__init__()
        self.items = []
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        h = QLabel("MODELS SIDE BY SIDE")
        h.setStyleSheet(HEADING)
        v.addWidget(h)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{AXIS}; font-size:11px;")
        v.addWidget(self.note)
        self.table = QTableWidget(0, len(self.HEAD))
        self.table.setHorizontalHeaderLabels(self.HEAD)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setIconSize(QSize(16, 16))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(self.HEAD)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(110)
        v.addWidget(self.table, 2)
        self.chart_head = QLabel("SHARE THAT PASS, BY DISTANCE")
        self.chart_head.setStyleSheet(HEADING)
        v.addWidget(self.chart_head)
        self.chart = BandChart()
        v.addWidget(self.chart, 3)
        self.foot = QLabel("A hollow marker: fewer than %d boxes in that band." % MIN_N)
        self.foot.setStyleSheet(f"color:{AXIS}; font-size:11px;")
        v.addWidget(self.foot)
        row = QHBoxLayout()
        self.run_btn = QPushButton("Run the other distance models")
        self.run_btn.setToolTip("Runs every distance-only model of the list that has not been run on this session yet, on the same boxes (the detector runs once).")
        self.run_btn.clicked.connect(lambda _c=False: on_run_others())
        self.csv_btn = QPushButton("Export CSV…")
        self.csv_btn.setToolTip("The table and the bands as a CSV file.")
        self.csv_btn.clicked.connect(lambda _c=False: on_export())
        row.addWidget(self.run_btn)
        row.addWidget(self.csv_btn)
        v.addLayout(row)
        self.setMinimumWidth(330)

    def set_items(self, items, tol_pct, method_text, note=""):
        """items: [{"name", "slot", "summary" or None, "note"}] in the order the runs were made."""
        self.items = items
        self.note.setText(note or f"The runs made in this window on the open session, judged as set on the left: within ± {tol_pct:g} % of the model's distance, by {method_text.lower()}.")
        self.table.setHorizontalHeaderItem(2, QTableWidgetItem(f"Pass (±{tol_pct:g} %)"))
        self.table.setRowCount(len(items))
        series = []
        for r, it in enumerate(items):
            s = it["summary"]
            first = QTableWidgetItem(it["name"] + (f"  ({it['note']})" if it.get("note") else ""))
            first.setIcon(swatch(it["slot"]))
            first.setToolTip(it["name"])
            self.table.setItem(r, 0, first)
            cells = ["–"] * 4
            if s is not None and s["frames"]:
                cells = [str(s["judged"]),
                         "–" if s["pass_pct"] is None else f"{s['pass_pct']:.0f} %",
                         "–" if s["median_off_pct"] is None else f"{s['median_off_pct']:.1f} %",
                         "–" if s["mean_abs_m"] is None else f"{s['mean_abs_m']:.2f} m"]
            for c, text in enumerate(cells, 1):
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                self.table.setItem(r, c, cell)
            if s is not None and s["frames"] and it["slot"] is not None:
                pts = [(bi, 100.0 * p / n, n, p) for bi, (_label, n, p) in enumerate(s["bands"]) if n]
                series.append({"name": it["name"], "slot": it["slot"], "points": pts})
        self.chart.set_series(series)
        self.chart_head.setText(f"SHARE THAT PASS, BY DISTANCE (LiDAR, {method_text.lower()})".upper())
        hidden = sum(1 for it in items if it["slot"] is None)
        self.foot.setText(f"A hollow marker: fewer than {MIN_N} boxes in that band." + (f"  {hidden} more run{'s' if hidden != 1 else ''} in the table only (the chart has eight)." if hidden else ""))
