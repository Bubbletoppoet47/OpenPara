"""motor_ui.py - small widgets of the Motor Control tab (copied in spirit from the other add-ons, which must not import each other)."""
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QFormLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

BIG_CSS = ("QPushButton { background:#0e7f86; color:white; font-size:15px; font-weight:bold; border:none; border-radius:8px; margin:4px 2px; }"
           "QPushButton:hover { background:#13979f; } QPushButton:disabled { background:#b9c4cf; color:#eef2f6; }")
STOP_CSS = ("QPushButton { background:#c62828; color:white; font-size:16px; font-weight:bold; border:none; border-radius:8px; margin:4px 2px; }"
            "QPushButton:hover { background:#e53935; }")
OK, WARN, BAD = "#1b7f3b", "#a86400", "#b3261e"


def big_button(text, checkable=False):
    b = QPushButton(text)
    b.setMinimumHeight(44)
    b.setCheckable(checkable)
    b.setStyleSheet(BIG_CSS)
    return b


def stop_button(text="STOP"):
    b = QPushButton(text)
    b.setMinimumHeight(48)
    b.setStyleSheet(STOP_CSS)
    return b


def note_label(text):
    n = QLabel(text)
    n.setWordWrap(True)
    n.setStyleSheet("color:#53647c; font-size:11px; padding:0 4px;")
    return n


def verdict_html(items):
    """[(level, text)] -> small HTML list with a coloured mark in front."""
    col = {"ok": OK, "warn": WARN, "bad": BAD}
    mark = {"ok": "✔", "warn": "▲", "bad": "✖"}
    return "<br>".join(f"<span style='color:{col.get(l, WARN)}'><b>{mark.get(l, '•')}</b></span> {t}" for l, t in items)


class Section(QWidget):
    """A numbered block that folds away."""

    def __init__(self, title, open_=True, number=None, summary=None):
        super().__init__()
        self.title, self.number, self.summary = title, number, summary
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(2)
        self.head = QPushButton()
        self.head.setCheckable(True)
        self.head.setChecked(open_)
        self.head.setFlat(True)
        self.head.setMinimumHeight(26)
        self.head.setStyleSheet("QPushButton { text-align:left; border:none; border-bottom:1px solid #cfd6e0; padding:3px 2px; font-weight:bold; "
                                "color:#16324f; } QPushButton:hover { background:#eef4f7; }")
        self.head.toggled.connect(self.toggle)
        lay.addWidget(self.head)
        self.sum_lbl = QLabel("")
        self.sum_lbl.setStyleSheet("color:#53647c; font-size:11px; padding-left:18px;")
        self.sum_lbl.setWordWrap(True)
        lay.addWidget(self.sum_lbl)
        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(4, 4, 2, 4)
        lay.addWidget(self.body)
        self.toggle(open_)

    def toggle(self, on):
        self.body.setVisible(on)
        self.head.setText(f"{'▾' if on else '▸'}  {self.number}   {self.title}" if self.number else f"{'▾' if on else '▸'}  {self.title}")
        txt = ""
        if not on and self.summary is not None:
            try:
                txt = self.summary() or ""
            except Exception:  # noqa: BLE001
                txt = ""
        self.sum_lbl.setText(txt)

    def add(self, w):
        self.form.addRow(w)
        return w


class LivePlot(QWidget):
    """A scrolling line plot: set_data(ts, ys); the last `span` seconds are shown, the vertical range follows the data."""
    COLORS = ["#0e7f86", "#c25b00", "#5b3fa0"]

    def __init__(self, title, unit="", span=10.0):
        super().__init__()
        self.title, self.unit, self.span = title, unit, span
        self.ts, self.series = [], []
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, ts, *series):
        self.ts, self.series = list(ts), [list(s) for s in series]
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        L, R, T, B = 52, 8, 18, 14
        p.setPen(QPen(QColor("#cfd6e0")))
        p.drawRect(L, T, w - L - R, h - T - B)
        p.setPen(QColor("#16324f"))
        p.drawText(L, 13, f"{self.title}" + (f" ({self.unit})" if self.unit else ""))
        if len(self.ts) < 2 or not self.series:
            p.end()
            return
        t1 = self.ts[-1]
        t0 = max(self.ts[0], t1 - self.span)
        idx = [i for i, t in enumerate(self.ts) if t >= t0]
        vals = [s[i] for s in self.series for i in idx if i < len(s)]
        if not vals:
            p.end()
            return
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-9:
            lo, hi = lo - 1, hi + 1
        pad = 0.08 * (hi - lo)
        lo, hi = lo - pad, hi + pad
        sx = (w - L - R) / max(t1 - t0, 1e-9)
        sy = (h - T - B) / (hi - lo)
        p.setPen(QColor("#53647c"))
        for v in (lo + pad, (lo + hi) / 2, hi - pad):
            y = h - B - (v - lo) * sy
            p.drawText(2, int(y) + 4, f"{v:.3g}")
            p.setPen(QPen(QColor("#eef2f6")))
            p.drawLine(L, int(y), w - R, int(y))
            p.setPen(QColor("#53647c"))
        for k, s in enumerate(self.series):
            pts = [QPointF(L + (self.ts[i] - t0) * sx, h - B - (s[i] - lo) * sy) for i in idx if i < len(s)]
            p.setPen(QPen(QColor(self.COLORS[k % 3]), 1.6))
            p.drawPolyline(pts)
        p.end()
