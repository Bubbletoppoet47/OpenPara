"""annotator_analyse.py - the Analyse tab of the annotator window: open a recorded Gimble session, run a model over it, and see how the model's
distance holds up against the LiDAR, frame by frame.

The numbers come from annotator_analysis.py (no toolkit there).  This file is what is on screen:
    AnalysePanel   the side panel: the setup card (session, model, confidence, tolerance) over Results / Boxes / Frames tabs
    AnalyseView    the picture with the model's boxes coloured by what the LiDAR says, a card for the selected box, and the scrubber under it
    AnalyseTab     the state and the commands (open, run, stop, save a frame, CSV, report); the window gives each ribbon button one of its methods

The model is run once (down to a low confidence) and the confidence and tolerance only filter that run, so moving them redraws at once.
"""
import os
import shutil
import tempfile
import threading
import time

import numpy as np
from PIL import Image
from PyQt6.QtCore import QBuffer, QIODevice, QObject, QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPolygonF, QShortcut
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QListWidget, QListWidgetItem,
                             QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

import annotator_analysis as aa
import annotator_canvas as cv
import annotator_core as ac
import annotator_icons as icons
import annotator_ribbon as rib
import qtk

PASS, FAIL, NONE, RING = "#2aa3ab", "#e0702f", "#9aa3b2", "#ffd23f"
STATE_COLOUR = {"pass": PASS, "fail": FAIL, "none": "#6b7380", "empty": "#2c313a", None: "#1f232a"}
MARK = {"pass": "✓", "fail": "✕", "none": "–"}
DEMO_LABEL = "Made-up model (example)"
INK, MUTED = "#1f2a3c", "#5a6577"
HEADING = "color:#4a5872; font-size:11px; font-weight:600; letter-spacing:1px;"


def box_state(det, st, settings):
    """"pass" / "fail" / "none" of one box by the method that judges the boxes."""
    v = aa.judge(det.pred, st.value(settings.method), settings.tol)
    return "none" if v is None else "pass" if v else "fail"


def kept_boxes(an, idx, settings):
    """[(box number, detection, LiDAR numbers)] of frame idx at or above the confidence."""
    res = an.frames[idx] if an is not None else None
    if res is None:
        return []
    return [(i, d, s) for i, (d, s) in enumerate(zip(res.dets, res.stats)) if d.conf >= settings.conf]


def result_text(det, st, settings):
    """What the Boxes list says of a box: a verdict, or why there is none."""
    if det.pred is None:
        return "no distance"
    if st.n < aa.MIN_POINTS:
        return "no LiDAR"
    state = box_state(det, st, settings)
    return f"{MARK[state]} {state}"


METHOD_SHORT = {"closest": "Closest", "median": "Median", "average": "Average"}
METHOD_TIP = {"closest": "The LiDAR return inside the box that is nearest the predicted distance. It forgives LiDAR that lags the picture and what is behind the object.\nClick to make it the one that colours the boxes.",
              "median": "The middle LiDAR return inside the box (the Pi's own number is a median of the middle of the box).\nClick to make it the one that colours the boxes.",
              "average": "The average of the LiDAR returns inside the box: every return counts, so what is behind the object pulls it away.\nClick to make it the one that colours the boxes."}


def boxes_word(n):
    return f"{n} box" + ("" if n == 1 else "es")


def fmt_m(v):
    return "-" if v is None else f"{v:.2f} m"


def off_text(pred, v):
    e = aa.error_fraction(pred, v)
    return "" if e is None else f"off by {100 * e:.0f}%"


def pil_to_qimage(im):
    return cv.pil_to_qimage(im)


# ---------------------------------------------------------------------------------------------- painting one frame (screen, saved picture, report)
def draw_chip(p, x, y, text, bg, fg="#ffffff"):
    m = p.fontMetrics()
    w, h = m.horizontalAdvance(text) + 10, m.height() + 4
    p.fillRect(QRectF(x, y - h, w, h), QColor(bg))
    p.setPen(QColor(fg))
    p.drawText(QRectF(x, y - h, w, h), Qt.AlignmentFlag.AlignCenter, text)


def paint_frame(p, rect, qimg, points, kept, settings, region, dots, selected, k=1.0):
    """The photo in `rect`, the LiDAR dots, and each kept box in the colour of its verdict with a label; the closest return of the selected
    box ringed.  `k` scales line widths and text (1 on screen, more for a saved picture)."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.drawImage(rect, qimg)
    sx, sy = rect.width() / qimg.width(), rect.height() / qimg.height()
    to = lambda x, y: QPointF(rect.left() + x * sx, rect.top() + y * sy)
    u, v, z = points
    f = QFont(p.font())
    f.setPixelSize(max(9, int(12 * k)))
    f.setBold(True)
    p.setFont(f)
    if dots == "all" and len(u):
        cols = ac.depth_colors(z)
        for i in np.argsort(-z):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(int(cols[i][0]), int(cols[i][1]), int(cols[i][2])))
            p.drawEllipse(to(u[i], v[i]), 1.8 * k, 1.8 * k)
    elif dots == "box" and len(u):
        inside = np.zeros(len(u), bool)
        for _i, d, _s in kept:
            inside |= aa.points_in_box((u, v, z), d.box, region)
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor("#10204d"), 0.8 * k))
        for i in np.nonzero(inside)[0]:
            p.drawEllipse(to(u[i], v[i]), 2.4 * k, 2.4 * k)
    for bi, d, s in kept:
        state = box_state(d, s, settings)
        colour = QColor(STATE_COLOUR[state] if state != "none" else NONE)
        pen = QPen(colour, (4.5 if bi == selected else 2.4) * k)
        p.setBrush(Qt.BrushStyle.NoBrush)
        a, b = to(d.box[0], d.box[1]), to(d.box[2], d.box[3])
        if state == "none":                       # dashed, over a pale line so that it shows on any photo
            p.setPen(QPen(QColor(255, 255, 255, 170), pen.widthF() + 2 * k))
            p.drawRect(QRectF(a, b))
            colour = QColor("#5b6472")
            pen = QPen(colour, pen.widthF())
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(QRectF(a, b))
        label = f"{d.cls} {d.conf:.2f}" + (f" · {d.pred:.1f} m" if d.pred is not None else "") + f"  {MARK[state]}"
        draw_chip(p, a.x() - 1, a.y(), label, STATE_COLOUR[state] if state != "none" else "#6b7380")
    for bi, d, s in kept:
        if bi == selected and s.closest_uv is not None:
            c = to(*s.closest_uv)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(RING), 3.2 * k))
            p.drawEllipse(c, 9 * k, 9 * k)
            draw_chip(p, c.x() + 12 * k, c.y() - 4 * k, f"{s.closest:.2f} m", "#10204d")


# ---------------------------------------------------------------------------------------------- small widgets
class Bar(QWidget):
    """A thin bar filled to a fraction (0-1)."""

    def __init__(self, colour="#0e7f86"):
        super().__init__()
        self.fraction, self.colour = 0.0, colour
        self.setFixedHeight(8)

    def set_fraction(self, f):
        self.fraction = 0.0 if f is None else max(0.0, min(1.0, f))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e3e6ec"))
        p.drawRoundedRect(self.rect(), 2, 2)
        if self.fraction > 0:
            p.setBrush(QColor(self.colour))
            p.drawRoundedRect(QRectF(0, 0, self.width() * self.fraction, self.height()), 2, 2)
        p.end()


class MethodRow(QFrame):
    """One of the three ways of reading the LiDAR: its name, the share passing, a bar; a click makes it the one that colours the boxes."""

    def __init__(self, tab, method):
        super().__init__()
        self.tab, self.method = tab, method
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(4)
        top = QHBoxLayout()
        self.title = QLabel(aa.METHOD_NAMES[method])
        self.title.setStyleSheet(f"font-weight:600; color:{INK};")
        self.value = QLabel("-")
        self.value.setStyleSheet("font-size:20px; font-weight:600; color:#0e7f86;")
        top.addWidget(self.title, 1)
        top.addWidget(self.value)
        v.addLayout(top)
        self.bar = Bar()
        v.addWidget(self.bar)
        self.sub = QLabel("")
        self.sub.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        v.addWidget(self.sub)
        self.setToolTip(METHOD_TIP[method])
        self.set_selected(False)

    def set_selected(self, on):
        self.setStyleSheet("MethodRow{background:#eef6f7; border-left:3px solid #0e7f86; border-bottom:1px solid #e6e6e6;}" if on
                           else "MethodRow{background:#ffffff; border-left:3px solid transparent; border-bottom:1px solid #e6e6e6;}")

    def mousePressEvent(self, e):
        self.tab.set_method(self.method)


# ---------------------------------------------------------------------------------------------- the side panel
class AnalysePanel(QWidget):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self._dirty = {"boxes", "frames"}               # the lists are filled when their tab is on show (a long session has thousands of rows)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self._setup_card())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setIconSize(QSize(26, 26))
        for page, key, name in ((self._results_page(), "ann_tab_results", "Results"), (self._boxes_page(), "ann_tab_boxes", "Boxes"),
                                (self._frames_page(), "ann_tab_scrub", "Frames")):
            ic = icons.icon(key, 26)
            i = self.tabs.addTab(page, ic if ic is not None else QIcon(), "" if ic is not None else name)
            self.tabs.setTabToolTip(i, name)
        lay.addWidget(self.tabs, 1)
        self.setMinimumWidth(270)
        self.tabs.currentChanged.connect(lambda _i: self.fill_visible())

    # ---- setup card
    def _setup_card(self):
        box = QFrame()
        box.setObjectName("setup")
        box.setStyleSheet("QFrame#setup{background:#ffffff; border:1px solid #ababab;}")
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(5)
        h = QLabel("ANALYSIS SETUP")
        h.setStyleSheet(HEADING)
        v.addWidget(h)
        v.addWidget(self._muted("Session folder"))
        row = QHBoxLayout()
        self.folder_label = QLabel("None open")
        self.folder_label.setStyleSheet("border:1px solid #bdbdbd; border-radius:3px; padding:4px 8px; background:#ffffff;")
        self.folder_label.setMinimumWidth(10)
        row.addWidget(self.folder_label, 1)
        b = QPushButton("Open…")
        b.clicked.connect(lambda _c=False: self.tab.open_session())
        row.addWidget(b)
        v.addLayout(row)
        v.addWidget(self._muted("Model"))
        self.model_combo = QComboBox()
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setMinimumContentsLength(14)
        self.model_combo.setToolTip("The Annotator's models. It runs here on the PC; the Gimble runs the converted copy, so the two can differ a little.")
        self.model_combo.activated.connect(lambda _i: self.tab.set_model(self.model_combo.currentText()))
        v.addWidget(self.model_combo)
        self.model_note = self._muted("")
        v.addWidget(self.model_note)
        r = QHBoxLayout()
        r.addWidget(QLabel("Confidence at least"))
        self.conf_label = QLabel("85%")
        self.conf_label.setStyleSheet("font-weight:600;")
        r.addStretch(1)
        r.addWidget(self.conf_label)
        v.addLayout(r)
        self.conf_slider = QSlider(Qt.Orientation.Horizontal)
        self.conf_slider.setRange(10, 99)
        self.conf_slider.setValue(85)
        self.conf_slider.setToolTip("Boxes below this confidence are left out. The model ran once (down to 10 %), so moving this judges again at once.")
        self.conf_slider.valueChanged.connect(self.tab.set_confidence_percent)
        v.addWidget(self.conf_slider)
        r = QHBoxLayout()
        r.addWidget(QLabel("Pass when within"))
        r.addStretch(1)
        self.tol_spin = QSpinBox()
        self.tol_spin.setRange(1, 100)
        self.tol_spin.setValue(10)
        self.tol_spin.setPrefix("± ")
        self.tol_spin.setSuffix(" %")
        self.tol_spin.setToolTip("A box passes when the LiDAR number is within this share of the predicted distance.")
        self.tol_spin.valueChanged.connect(self.tab.set_tolerance_percent)
        r.addWidget(self.tol_spin)
        v.addLayout(r)
        self.core_check = QCheckBox("Middle 60 % of each box only")
        self.core_check.setToolTip("Take the LiDAR returns from the middle of each box, as the Pi does (less of the wall behind the object).")
        self.core_check.toggled.connect(lambda on: self.tab.set_region("core" if on else "box"))
        v.addWidget(self.core_check)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(16)
        self.progress.hide()
        v.addWidget(self.progress)
        return box

    @staticmethod
    def _muted(text):
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet("color:#6a7790; font-size:11px;")
        return lab

    def set_models(self, labels, current=None):
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(labels)
        if current in labels:
            self.model_combo.setCurrentText(current)
        self.model_combo.blockSignals(False)

    # ---- Results tab
    def _results_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.results_head = QLabel("RESULTS")
        self.results_head.setStyleSheet(HEADING + " padding:9px 12px; border-bottom:1px solid #e6e6e6;")
        v.addWidget(self.results_head)
        self.empty_note = QLabel("Open a session and press Run analysis.")
        self.empty_note.setWordWrap(True)
        self.empty_note.setStyleSheet(f"color:{MUTED}; padding:12px;")
        v.addWidget(self.empty_note)
        self.rows = {m: MethodRow(self.tab, m) for m in aa.METHODS}
        for m in aa.METHODS:
            v.addWidget(self.rows[m])
        self.nolidar = QLabel("")
        self.nolidar.setWordWrap(True)
        self.nolidar.setStyleSheet(f"color:{MUTED}; padding:8px 12px; border-bottom:1px solid #e6e6e6;")
        v.addWidget(self.nolidar)
        self.bands_head = QLabel("")
        self.bands_head.setStyleSheet(HEADING + " padding:8px 12px 2px 12px;")
        v.addWidget(self.bands_head)
        self.band_rows = []
        for _ in aa.BANDS:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(12, 2, 12, 2)
            lab, bar, val = QLabel(""), Bar(), QLabel("")
            lab.setFixedWidth(88)
            val.setFixedWidth(64)
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            h.addWidget(lab)
            h.addWidget(bar, 1)
            h.addWidget(val)
            v.addWidget(w)
            self.band_rows.append((w, lab, bar, val))
            w.hide()
        v.addStretch(1)
        sc = QScrollArea()
        sc.setWidget(page)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return sc

    def show_results(self, ev, settings, an):
        have = ev is not None and an is not None and an.analysed > 0
        self.empty_note.setVisible(not have)
        for m in aa.METHODS:
            self.rows[m].setVisible(have)
        self.nolidar.setVisible(have)
        self.bands_head.setVisible(have)
        for w, *_ in self.band_rows:
            w.setVisible(False)
        if not have:
            self.results_head.setText("RESULTS")
            return
        part = "" if an.finished else f" · {an.analysed} of {len(an.session)} frames so far"
        self.results_head.setText(f"RESULTS · {boxes_word(ev.boxes)} AT {settings.conf * 100:.0f}% OR MORE{part}".upper())
        for m in aa.METHODS:
            row, pc = self.rows[m], ev.percent(m)
            row.value.setText("-" if pc is None else f"{pc:.0f}%")
            row.bar.set_fraction(None if pc is None else pc / 100)
            p, f = ev.counts[m]
            row.sub.setText(f"{p} pass · {f} fail" + ("   (colours the boxes)" if m == settings.method else ""))
            row.set_selected(m == settings.method)
        txt = f"No LiDAR in the box: {boxes_word(ev.no_lidar)} (fewer than {aa.MIN_POINTS} returns; neither pass nor fail)."
        if ev.no_distance:
            txt += f"\nNo predicted distance: {boxes_word(ev.no_distance)} (this model gives none)."
        self.nolidar.setText(txt)
        self.bands_head.setText(f"{aa.METHOD_NAMES[settings.method]}, by distance".upper())
        bi = 0
        for lbl, n, p in ev.bands:
            if n:
                w, lab, bar, val = self.band_rows[bi]
                lab.setText(lbl)
                bar.set_fraction(p / n)
                val.setText(f"{100 * p / n:.0f}% ({n})")
                w.show()
                bi += 1

    def lists_changed(self):
        self._dirty.update(("boxes", "frames"))
        self.fill_visible()

    def fill_visible(self):
        i = self.tabs.currentIndex()
        if i == 1 and "boxes" in self._dirty:
            self.fill_boxes()
        elif i == 2 and "frames" in self._dirty:
            self.fill_frames()

    # ---- Boxes tab
    def _boxes_page(self):
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Frame", "Class", "Conf.", "Predicted", "Closest", "Result"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        for c in range(6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c in (1, 5) else QHeaderView.ResizeMode.ResizeToContents)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.cellClicked.connect(self._box_clicked)
        self._table_keys = []
        self._row_of = {}
        return self.table

    def fill_boxes(self):
        tab, an, settings = self.tab, self.tab.analysis, self.tab.settings
        self._dirty.discard("boxes")
        self.table.setRowCount(0)
        self._table_keys, self._row_of = [], {}
        self.table.setHorizontalHeaderItem(4, QTableWidgetItem(METHOD_SHORT[settings.method]))
        if an is None:
            return
        out = [(fi, bi, d, s) for fi in range(len(an.frames)) for bi, d, s in kept_boxes(an, fi, settings)]
        self.table.setRowCount(len(out))
        for r, (fi, bi, d, s) in enumerate(out):
            state = box_state(d, s, settings)
            cells = [str(fi + 1), d.cls, f"{d.conf:.2f}", fmt_m(d.pred), fmt_m(s.value(settings.method)), result_text(d, s, settings)]
            for c, t in enumerate(cells):
                it = QTableWidgetItem(t)
                if c == 5 and state != "none":
                    it.setForeground(QColor(STATE_COLOUR[state]))
                self.table.setItem(r, c, it)
            self._table_keys.append((fi, bi))
            self._row_of[(fi, bi)] = r
        self.mark_row(tab.cur, tab.sel)

    def mark_row(self, frame, box):
        """The row of the box on show is the selected one."""
        r = self._row_of.get((frame, box))
        if r is None:
            self.table.clearSelection()
        elif self.table.currentRow() != r:
            self.table.selectRow(r)
            self.table.scrollToItem(self.table.item(r, 0))

    def _box_clicked(self, row, _col):
        if 0 <= row < len(self._table_keys):
            self.tab.goto(self._table_keys[row][0], self._table_keys[row][1])

    # ---- Frames tab
    def _frames_page(self):
        self.frame_list = QListWidget()
        self.frame_list.setFrameShape(QFrame.Shape.NoFrame)
        self.frame_list.currentRowChanged.connect(self._frame_clicked)
        self._frame_keys = []
        return self.frame_list

    def fill_frames(self):
        tab = self.tab
        session, an, ev, settings, flt = tab.session, tab.analysis, tab.ev, tab.settings, tab.filter
        self._dirty.discard("frames")
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        self._frame_keys = []
        if session is not None:
            for fi, fr in enumerate(session.frames):
                if not self.tab.matches(fi, flt):
                    continue
                n = len(kept_boxes(an, fi, settings))
                st = ev.state[fi] if ev is not None and fi < len(ev.state) else None
                it = QListWidgetItem(f"{MARK.get(st, '·')}  Frame {fi + 1}  ·  {fr.key}" + (f"  ·  {boxes_word(n)}" if st is not None else ""))
                if st in ("pass", "fail"):
                    it.setForeground(QColor(STATE_COLOUR[st]))
                self.frame_list.addItem(it)
                self._frame_keys.append(fi)
            if self.tab.cur in self._frame_keys:
                self.frame_list.setCurrentRow(self._frame_keys.index(self.tab.cur))
        self.frame_list.blockSignals(False)

    def _frame_clicked(self, row):
        if 0 <= row < len(self._frame_keys) and self._frame_keys[row] != self.tab.cur:
            self.tab.goto(self._frame_keys[row])


# ---------------------------------------------------------------------------------------------- the picture, the card, the scrubber
class Strip(QWidget):
    """One thin cell per frame, in the colour of its verdict; click or drag to go there; frames the filter leaves out are dimmed."""

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("One cell per frame: teal all judged boxes pass, orange a box fails, grey no LiDAR or no distance, dark no box.\nClick or drag to go to a frame. Home / End, Left / Right (frames) and Up / Down (boxes) work too.")

    def _index_at(self, x):
        n = len(self.tab.session) if self.tab.session else 0
        return None if n == 0 else max(0, min(n - 1, int(x / max(self.width(), 1) * n)))

    def mousePressEvent(self, e):
        i = self._index_at(e.position().x())
        if i is not None:
            self.tab.goto(i)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.mousePressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1b1f25"))
        t = self.tab
        n = len(t.session) if t.session else 0
        if n:
            W, H = self.width(), self.height()
            ev = t.ev
            states = ev.state if ev is not None else [None] * n
            cols = max(1, min(n, W))
            rank = {"fail": 4, "pass": 3, "none": 2, "empty": 1, None: 0}
            for c in range(cols):
                lo, hi = c * n // cols, max(c * n // cols + 1, (c + 1) * n // cols)
                grp = range(lo, min(hi, n))
                st = max((states[i] for i in grp), key=lambda s: rank[s])
                on = any(t.matches(i, t.filter) for i in grp)
                colour = QColor(STATE_COLOUR[st])
                if not on:
                    colour.setAlpha(60)
                x0, x1 = c * W / cols, (c + 1) * W / cols
                p.fillRect(QRectF(x0, 3, max(1.0, x1 - x0 - (1 if x1 - x0 > 3 else 0)), H - 6), colour)
            x = (t.cur + 0.5) / n * W
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(QPointF(x, 0), QPointF(x, H))
            p.setBrush(QColor("#ffffff"))
            p.drawPolygon(QPolygonF([QPointF(x - 4, 0), QPointF(x + 4, 0), QPointF(x, 5)]))
        p.end()


class AnalysisCanvas(QWidget):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setMinimumSize(300, 200)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._rect = QRectF()
        self.card = DetailCard(tab, self)

    def fit_rect(self, qimg):
        cw, ch = max(self.width(), 1), max(self.height(), 1)
        s = min(cw / qimg.width(), ch / qimg.height())
        w, h = qimg.width() * s, qimg.height() * s
        return QRectF((cw - w) / 2, (ch - h) / 2, w, h)

    def resizeEvent(self, e):
        self.card.move(max(0, self.width() - self.card.width() - 10), 10)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#23272e"))
        t = self.tab
        qimg = t.frame_image(t.cur)
        if qimg is None:
            p.setPen(QColor("#aeb6c4"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open a session folder (Open session…) to see its photos here.\nOr try the example.")
            p.end()
            return
        self._rect = self.fit_rect(qimg)
        paint_frame(p, self._rect, qimg, t.frame_points(t.cur), kept_boxes(t.analysis, t.cur, t.settings), t.settings, t.region, t.dots, t.sel)
        p.end()

    def mousePressEvent(self, e):
        t = self.tab
        qimg = t.frame_image(t.cur)
        if qimg is None or not self._rect.contains(e.position()):
            return
        x = (e.position().x() - self._rect.left()) / self._rect.width() * qimg.width()
        y = (e.position().y() - self._rect.top()) / self._rect.height() * qimg.height()
        best, area = None, None
        for bi, d, _s in kept_boxes(t.analysis, t.cur, t.settings):
            if d.box[0] <= x <= d.box[2] and d.box[1] <= y <= d.box[3]:
                a = (d.box[2] - d.box[0]) * (d.box[3] - d.box[1])
                if area is None or a < area:
                    best, area = bi, a
        if best is not None:
            t.select_box(best)


class DetailCard(QFrame):
    """The numbers of the selected box, over the picture's top right corner."""

    def __init__(self, tab, parent):
        super().__init__(parent)
        self.tab = tab
        self.setFixedWidth(292)
        self.setStyleSheet("DetailCard{background:#ffffff; border:1px solid #ababab; border-radius:3px;} QLabel{color:#1f2a3c;}")
        g = QGridLayout(self)
        g.setContentsMargins(12, 10, 12, 10)
        g.setVerticalSpacing(3)
        self.head = QLabel("")
        self.head.setStyleSheet("font-weight:600; font-size:13px;")
        self.points = QLabel("")
        self.points.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        g.addWidget(self.head, 0, 0, 1, 2)
        g.addWidget(self.points, 1, 0, 1, 2)
        self.value_labels = {}
        for r, key in enumerate(("pred",) + aa.METHODS, start=2):
            name = QLabel("Predicted" if key == "pred" else aa.METHOD_NAMES[key].replace(" of points", ""))
            val = QLabel("")
            val.setTextFormat(Qt.TextFormat.RichText)
            g.addWidget(name, r, 0)
            g.addWidget(val, r, 1, Qt.AlignmentFlag.AlignRight)
            self.value_labels[key] = val
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        g.addWidget(self.note, 6, 0, 1, 2)
        self.hide()

    def show_box(self, n, total, det, st, settings):
        if det is None:
            self.hide()
            return
        self.head.setText(f"Box {n} of {total} · {det.cls} {det.conf:.2f}")
        self.points.setText(f"{st.n} LiDAR points in the box")
        self.value_labels["pred"].setText(f"<b>{fmt_m(det.pred)}</b>" if det.pred is not None else "<b>none (this model gives no distance)</b>")
        for m in aa.METHODS:
            v = st.value(m)
            ok = aa.judge(det.pred, v, settings.tol)
            mark = "" if ok is None else (f" <b style='color:{PASS}'>✓</b>" if ok else f" <b style='color:{FAIL}'>✕</b>")
            self.value_labels[m].setText("no LiDAR" if st.n < aa.MIN_POINTS else f"{fmt_m(v)} · {off_text(det.pred, v)}{mark}" if v is not None else "-")
        self.note.setText(f"Pass means within ±{settings.tol * 100:.0f}%." + (" Points in the box include what is behind the object." if self.tab.region == "box" else ""))
        self.adjustSize()
        self.show()
        self.raise_()


class AnalyseView(QWidget):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.canvas = AnalysisCanvas(tab)
        v.addWidget(self.canvas, 1)
        bar = QWidget()
        bar.setStyleSheet("background:#1b1f25; color:#e6e9ee;")
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.prev_btn, self.next_btn = QPushButton("‹"), QPushButton("›")
        for b, d in ((self.prev_btn, -1), (self.next_btn, 1)):
            b.setFixedSize(28, 26)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("QPushButton{border:1px solid #4a5160; background:transparent; color:#e6e9ee; border-radius:3px; font-size:14px;} QPushButton:disabled{color:#5b6372;}")
            b.setToolTip("Previous frame (Left arrow)" if d < 0 else "Next frame (Right arrow)")
            b.clicked.connect(lambda _c=False, d=d: tab.step(d))
            row.addWidget(b)
        self.where = QLabel("")
        self.where.setStyleSheet("font-weight:600;")
        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#aeb6c4;")
        row.addWidget(self.where)
        row.addWidget(self.summary)
        row.addStretch(1)
        self.chips = {}
        for key, text in (("all", "All frames"), ("fail", "With a fail"), ("nolidar", "No LiDAR")):
            c = QPushButton(text)
            c.setCheckable(True)
            c.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            c.setStyleSheet("QPushButton{padding:3px 11px; border:1px solid #4a5160; border-radius:11px; color:#e6e9ee; background:transparent;}"
                            "QPushButton:checked{background:#e6e9ee; color:#1b1f25; font-weight:600;}")
            c.setToolTip({"all": "Every frame.", "fail": "Only the frames where a box fails (by the method that judges the boxes).",
                          "nolidar": "Only the frames with a box that has too few LiDAR returns."}[key])
            c.clicked.connect(lambda _c=False, k=key: tab.set_filter(k))
            row.addWidget(c)
            self.chips[key] = c
        bl.addLayout(row)
        self.strip = Strip(tab)
        bl.addWidget(self.strip)
        v.addWidget(bar)

    def refresh(self):
        t = self.tab
        n = len(t.session) if t.session else 0
        self.where.setText(f"Frame {t.cur + 1} of {n}" if n else "No session open")
        ev, an = t.ev, t.analysis
        if n and an is not None and an.frames[t.cur] is not None and ev is not None:
            kept = kept_boxes(an, t.cur, t.settings)
            c = {"pass": 0, "fail": 0, "none": 0}
            for _i, d, s in kept:
                c[box_state(d, s, t.settings)] += 1
            self.summary.setText(f"· {boxes_word(len(kept))}" + (f": {c['pass']} pass, {c['fail']} fail, {c['none']} no result" if kept else ""))
        else:
            self.summary.setText("" if n == 0 else "· not analysed yet")
        for k, b in self.chips.items():
            b.setChecked(k == t.filter)
        self.prev_btn.setEnabled(t.neighbour(-1) is not None)
        self.next_btn.setEnabled(t.neighbour(1) is not None)
        kept = kept_boxes(an, t.cur, t.settings)
        sel = next(((i, d, s) for i, d, s in kept if i == t.sel), None)
        self.canvas.card.show_box(kept.index(sel) + 1 if sel else 0, len(kept), sel[1] if sel else None, sel[2] if sel else None, t.settings)
        self.canvas.update()
        self.strip.update()
        t.panel.mark_row(t.cur, t.sel)


# ---------------------------------------------------------------------------------------------- the tab itself
class AnalyseTab(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.settings = aa.Settings()
        self.region = "box"
        self.dots = "box"                       # "box": the LiDAR returns inside the boxes; "all": every return, coloured by distance
        self.session = None
        self.analysis = None
        self.ev = None
        self.cur, self.sel = 0, 0
        self.filter = "all"
        self.running = False
        self._fail_set = self._nolidar_set = set()
        self._stop = threading.Event()
        self.demo_dir = None
        self._img = (None, None)                # (frame, QImage)
        self._pts = (None, None)
        self._assists = {}                      # model label -> predictor (a model is loaded once)
        self.predictor_for = self._default_predictor     # tests (and the example) put their own here
        self.panel = AnalysePanel(self)
        self.view = AnalyseView(self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(lambda: self.refresh(True))
        self.refresh_models()
        self.refresh(True)
        for key, fn in (("Left", lambda: self.step(-1)), ("Right", lambda: self.step(1)), ("Up", lambda: self.step_box(-1)), ("Down", lambda: self.step_box(1)),
                        ("Home", lambda: self.jump(False)), ("End", lambda: self.jump(True))):
            sc = QShortcut(QKeySequence(key), self.view)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ---- the ribbon page
    def ribbon_items(self):
        B = rib.button
        self.dots_box = B("dots_box", "ann_an_dots_box", "Dots in\nboxes", "Show only the LiDAR returns that fall inside the model's boxes.", checkable=True)
        self.dots_all = B("dots_all", "ann_an_dots_all", "All\ndots", "Show every LiDAR return of the frame, coloured by distance.", checkable=True)
        return [B("open", "ann_an_open", "Open\nsession…", "Open a recorded Gimble session folder (images, depth, index.csv).", self.open_session),
                B("run", "ann_an_run", "Run\nanalysis", "Run the model over every frame and compare its distance with the LiDAR.", self.run, bold=True),
                B("stop", "ann_an_stop", "Stop", "Stop the run; what is done so far is kept.", self.stop),
                "|", self.dots_box, self.dots_all, "|",
                B("save_img", "ann_an_save_img", "Save frame\nimage", "Save this frame as a picture, with its boxes, dots and numbers.", self.save_frame_image),
                B("csv", "ann_an_csv", "Export\nCSV", "One row per box: the model's class and distance, the LiDAR numbers and the verdicts.", self.export_csv),
                B("report", "ann_an_report", "Export\nreport", "A single page with the settings, the results and a selection of frames, to put in a report.", self.export_report),
                "|",
                B("example", "ann_an_example", "Try the\nexample", "Open a made-up session with a made-up model, to see how this works without any recording.", self.example),
                B("selfcheck", "ann_an_check", "Self-check", "Run the analysis on the made-up session and check the answers worked out by hand.", self.selfcheck)]

    def bind_ribbon(self, buttons):
        """The window made the buttons; the two dot buttons are one choice, and Run / Stop / the exports follow what is possible."""
        self.rb = buttons
        self.rb["dots_box"].setChecked(True)
        self.rb["dots_box"].toggled.connect(lambda on: self._dots_pick("box", on))
        self.rb["dots_all"].toggled.connect(lambda on: self._dots_pick("all", on))
        self.update_buttons()

    def _dots_pick(self, which, on):
        other = self.rb["dots_all" if which == "box" else "dots_box"]
        if on:
            self.dots = which
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
        elif not other.isChecked():          # a choice cannot be switched off: one of the two is always on
            self.rb[f"dots_{which}"].blockSignals(True)
            self.rb[f"dots_{which}"].setChecked(True)
            self.rb[f"dots_{which}"].blockSignals(False)
        self.view.refresh()

    def update_buttons(self):
        rb = getattr(self, "rb", None)
        if not rb:
            return
        has = self.session is not None
        done = self.analysis is not None and self.analysis.analysed > 0
        rb["run"].setEnabled(not self.running)
        rb["open"].setEnabled(not self.running)
        rb["stop"].setEnabled(self.running)
        rb["save_img"].setEnabled(has)
        rb["csv"].setEnabled(done and not self.running)
        rb["report"].setEnabled(done and not self.running)
        rb["example"].setEnabled(not self.running)
        rb["selfcheck"].setEnabled(not self.running)
        self.panel.core_check.setEnabled(not self.running)
        self.panel.model_combo.setEnabled(not self.running)
        for k in ("dots_box", "dots_all"):
            rb[k].setEnabled(has)

    # ---- models
    def refresh_models(self):
        w = self.win
        labels = [w.ai_choice.itemText(i) for i in range(w.ai_choice.count()) if w.ai_choice.itemText(i) != "No AI model"]
        if self.demo_dir is not None:
            labels.append(DEMO_LABEL)
        cur = self.panel.model_combo.currentText()
        self.panel.set_models(labels, cur if cur in labels else (labels[0] if labels else None))

    def set_model(self, label):
        self.analysis = None
        self.refresh(True)

    def _default_predictor(self, label):
        """(predict, has_distance) for a model of the annotator's list.  Loaded here, once per model, apart from the annotator's own (which may be
        busy predicting on another thread).  Runs on the worker thread."""
        if label == DEMO_LABEL:
            return aa.demo_predictor, True
        if label in self._assists:
            return self._assists[label]
        entry = self.win._ai_entries.get(label)
        if entry is None or not os.path.exists(entry["path"]):
            raise RuntimeError(f"'{label}' is not there (any more). Pick another model, or download models on the Models tab.")
        try:
            import gimble_assist
        except ImportError as e:
            raise RuntimeError(f"{e}\n\nRunning a model needs ultralytics and torch:\n\n    pip install ultralytics") from e
        assist = gimble_assist.GimbleAssist(entry["path"]) if entry["kind"] == "scratch" else gimble_assist.HelperAssist(entry["path"])
        pred = aa.AssistPredictor(assist)
        self._assists[label] = (pred, pred.has_distance)
        return self._assists[label]

    # ---- opening a session
    def open_session(self, path=None):
        if self.running:
            return False
        asked = not path
        path = path or qtk.ask_dir(self.win, "Select a recorded Gimble session folder (or the dataset folder that holds sessions)", self.win.cfg.get("analyse_dir"))
        if not path:
            return False
        found = aa.find_sessions(path)
        if not found:
            qtk.error(self.win, "Not a recorded session", "No session in that folder. A session has an images folder and index.csv (and a depth folder), like 20261125_184611.")
            return False
        if len(found) > 1:
            names = [os.path.basename(f) for f in found]
            name, ok = QInputDialog.getItem(self.win, "Which session?", f"{len(found)} sessions in this folder:", names, len(names) - 1, False)
            if not ok:
                return False
            found = [found[names.index(name)]]
        try:
            sess = aa.open_session(found[0])
        except ValueError as e:
            qtk.error(self.win, "Can't open the session", str(e))
            return False
        if asked:
            self.win.cfg["analyse_dir"] = path if aa.find_sessions(path) != [path] else os.path.dirname(path)    # next time the dialog starts there
            self.win._save_cfg()
        self.session, self.analysis, self.ev = sess, None, None
        self.cur = self.sel = 0
        self._img = self._pts = (None, None)
        self.filter = "all"
        self.panel.folder_label.setText(sess.name)
        self.panel.folder_label.setToolTip(sess.folder)
        self.refresh(True)
        return True

    def example(self):
        """A made-up session with a made-up model: nothing to record or load, so the whole tab can be tried (and tested)."""
        if self.running:
            return
        if self.demo_dir is None:
            self.demo_dir = tempfile.mkdtemp(prefix="analysis_example_")
            aa.make_demo_session(os.path.join(self.demo_dir, "example_session"))
        self.refresh_models()
        self.panel.model_combo.setCurrentText(DEMO_LABEL)
        if self.open_session(os.path.join(self.demo_dir, "example_session")):
            self.run()

    def selfcheck(self):
        """Builds the made-up session, runs the analysis on it and shows how many of the answers worked out by hand come out."""
        d = tempfile.mkdtemp(prefix="analysis_check_")
        try:
            results = aa.selfcheck(d)
        except Exception as e:  # noqa: BLE001
            qtk.error(self.win, "Self-check", f"The self-check could not run: {e}")
            return None
        finally:
            shutil.rmtree(d, ignore_errors=True)
        bad = [r for r in results if not r[1]]
        lines = [("PASS  " if ok else "FAIL  ") + what + (f"  ({detail})" if detail else "") for what, ok, detail in results]
        (qtk.info if not bad else qtk.warn)(self.win, "Self-check", f"{len(results) - len(bad)} of {len(results)} checks passed.\n\n" + "\n".join(lines))
        return results

    # ---- running
    def run(self):
        if self.running:
            return
        if self.session is None and not self.open_session():
            return
        label = self.panel.model_combo.currentText()
        if not label:
            qtk.info(self.win, "Pick a model", "There is no AI model to run yet. Download models (Models tab) or train one, then try again.")
            return
        self.running = True
        self._stop.clear()
        self.analysis = aa.Analysis(self.session, label, self.region)
        an, sess = self.analysis, self.session
        self.panel.progress.setRange(0, len(sess))
        self.panel.progress.setValue(0)
        self.panel.progress.setFormat("Loading the model…")
        self.panel.progress.show()
        self.update_buttons()
        last = [0.0]

        def worker():
            try:
                predict, has_distance = self.predictor_for(label)
                self._post(lambda: self._note_model(has_distance))
                aa.run_into(an, predict, progress=lambda d, t: self._progress(d, t, last), stop=self._stop.is_set, region=self.region)
                err = None
            except Exception as e:  # noqa: BLE001
                err = str(e)
            self._post(lambda: self._run_done(err))
        threading.Thread(target=worker, daemon=True).start()

    def _post(self, fn):
        """Hand fn to the window's thread (from the worker); a window closed meanwhile is no error."""
        try:
            self.win.post(fn)
        except RuntimeError:
            pass

    def _note_model(self, has_distance):
        self.panel.model_note.setText("This model gives a distance." if has_distance else "This model gives no distance: boxes can be seen, but not judged.")

    def _progress(self, done, total, last):
        now = time.time()
        if now - last[0] < 0.4 and done < total:
            return
        last[0] = now
        self._post(lambda: self._progress_gui(done, total))

    def _progress_gui(self, done, total):
        if not self.running:
            return
        self.panel.progress.setValue(done)
        self.panel.progress.setFormat(f"Analysing {done} / {total}")
        self.refresh(False)

    def _run_done(self, err):
        self.running = False
        self.panel.progress.hide()
        if err:
            qtk.error(self.win, "Analysis failed", err)
        self.refresh(True)
        self.update_buttons()
        self.win._update_status()

    def stop(self):
        self._stop.set()

    def set_region(self, region):
        """Another part of each box for the LiDAR numbers: the model is not run again, only the returns are read again."""
        if region == self.region:
            return
        self.region = region
        an = self.analysis
        if an is None or an.analysed == 0 or self.running:
            return
        self.running = True
        self.panel.progress.setRange(0, len(an.session))
        self.panel.progress.setFormat("Reading the LiDAR again…")
        self.panel.progress.show()
        self.update_buttons()

        def worker():
            aa.restat(an, region, progress=None, stop=None)
            self._post(lambda: self._run_done(None))
        threading.Thread(target=worker, daemon=True).start()

    # ---- settings
    def set_confidence_percent(self, pct):
        self.settings.conf = pct / 100
        self.panel.conf_label.setText(f"{pct}%")
        self._debounce.start(120)
        self.view.refresh()

    def set_tolerance_percent(self, pct):
        self.settings.tol = pct / 100
        self._debounce.start(120)
        self.view.refresh()

    def set_method(self, method):
        if method != self.settings.method:
            self.settings.method = method
            self.refresh(True)

    def set_filter(self, flt):
        self.filter = flt
        if not self.matches(self.cur, flt):
            n = self.neighbour(1) if self.neighbour(1) is not None else self.neighbour(-1)
            if n is not None:
                self.cur = n
        self.refresh(True)

    # ---- moving about
    def matches(self, idx, flt):
        if flt == "all" or self.ev is None:
            return True
        return idx in (self._fail_set if flt == "fail" else self._nolidar_set)

    def neighbour(self, delta):
        if self.session is None:
            return None
        i = self.cur + delta
        while 0 <= i < len(self.session):
            if self.matches(i, self.filter):
                return i
            i += delta
        return None

    def step(self, delta):
        n = self.neighbour(delta)
        if n is not None:
            self.goto(n)

    def goto(self, idx, box=None):
        if self.session is None or not (0 <= idx < len(self.session)):
            return
        self.cur = idx
        kept = kept_boxes(self.analysis, idx, self.settings)
        self.sel = box if box is not None else (kept[0][0] if kept else 0)
        self.refresh(False)
        lst = self.panel.frame_list
        keys = self.panel._frame_keys
        if idx in keys:
            lst.blockSignals(True)
            lst.setCurrentRow(keys.index(idx))
            lst.blockSignals(False)

    def jump(self, last):
        """The first / last frame the filter lets through."""
        if self.session is None:
            return
        idxs = [i for i in range(len(self.session)) if self.matches(i, self.filter)]
        if idxs:
            self.goto(idxs[-1] if last else idxs[0])

    def step_box(self, delta):
        """The next / previous box of the open frame."""
        kept = [i for i, _d, _s in kept_boxes(self.analysis, self.cur, self.settings)]
        if kept:
            now = kept.index(self.sel) if self.sel in kept else -1
            self.select_box(kept[(now + delta) % len(kept)])

    def select_box(self, bi):
        self.sel = bi
        self.view.refresh()

    # ---- drawing support
    def frame_image(self, idx):
        if self.session is None:
            return None
        if self._img[0] != idx:
            try:
                with Image.open(self.session.frames[idx].image) as im:
                    self._img = (idx, pil_to_qimage(im.convert("RGB")))
            except (OSError, ValueError):
                self._img = (idx, None)
        return self._img[1]

    def frame_points(self, idx):
        if self._pts[0] != idx:
            self._pts = (idx, aa.depth_points(self.session.frames[idx].depth))
        return self._pts[1]

    def refresh(self, lists=True):
        self.ev = aa.evaluate(self.analysis, self.settings) if self.analysis is not None else None
        self.panel.show_results(self.ev, self.settings, self.analysis)
        self._fail_set, self._nolidar_set = (set(self.ev.with_fail), set(self.ev.with_no_lidar)) if self.ev is not None else (set(), set())
        if lists and not self.running:
            self.panel.lists_changed()
        self.view.refresh()
        self.update_buttons()
        self.win.show_analyse_status(self.status_text())

    def status_text(self):
        s = self.session
        if s is None:
            return "Analyse: no session open"
        an = self.analysis
        return (f"Session {s.name}  |  {len(s)} frames" + (f"  |  {an.analysed} analysed" if an is not None else "  |  not run yet")
                + (f"  |  model: {an.model}" if an is not None and an.model else ""))

    # ---- pictures, CSV, report
    def render_frame(self, idx, width=1280, dots=None):
        """The frame as a picture for a report: the photo with its boxes, dots and closest point, and under it a line per box with the numbers."""
        qimg = self.frame_image(idx) if idx == self.cur else None
        if qimg is None:
            with Image.open(self.session.frames[idx].image) as im:
                qimg = pil_to_qimage(im.convert("RGB"))
        k = width / 960.0
        H = int(width * qimg.height() / qimg.width())
        kept = kept_boxes(self.analysis, idx, self.settings)
        foot_line = int(20 * k)
        foot = foot_line * (len(kept) + 2)
        out = QImage(width, H + foot, QImage.Format.Format_RGB32)
        out.fill(QColor("#ffffff"))
        p = QPainter(out)
        paint_frame(p, QRectF(0, 0, width, H), qimg, self.frame_points(idx) if idx == self.cur else aa.depth_points(self.session.frames[idx].depth),
                    kept, self.settings, self.region, dots or self.dots, None, k)
        f = QFont(p.font())
        f.setPixelSize(int(13 * k))
        p.setFont(f)
        p.setPen(QColor(INK))
        y = H + foot_line
        p.drawText(QPointF(10 * k, y - 5 * k), f"Frame {idx + 1} of {len(self.session)} · {self.session.frames[idx].key} · confidence ≥ {self.settings.conf * 100:.0f}% · pass within ±{self.settings.tol * 100:.0f}%")
        for _bi, d, s in kept:
            y += foot_line
            st = box_state(d, s, self.settings)
            p.setPen(QColor(STATE_COLOUR[st] if st != "none" else "#6b7380"))
            p.drawText(QPointF(10 * k, y - 5 * k), f"{MARK[st]}  {d.cls} {d.conf:.2f}   predicted {fmt_m(d.pred)}   closest {fmt_m(s.closest)}   median {fmt_m(s.med)}   average {fmt_m(s.avg)}   ({s.n} points)")
        p.end()
        return out

    def _png_bytes(self, image):
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buf, "PNG")
        return bytes(buf.data())

    def save_frame_image(self, path=None):
        if self.session is None:
            return None
        if not path:
            path, _ = QFileDialog.getSaveFileName(self.win, "Save this frame as a picture", f"{self.session.name}_frame_{self.cur + 1}.png", "Picture (*.png)")
        if not path:
            return None
        if not path.lower().endswith(".png"):
            path += ".png"
        if not self.render_frame(self.cur).save(path, "PNG"):
            qtk.error(self.win, "Save frame image", f"Could not write {path}")
            return None
        self.win._announce("Frame image saved")
        return path

    def export_csv(self, path=None):
        if self.analysis is None or self.analysis.analysed == 0:
            return None
        if not path:
            path, _ = QFileDialog.getSaveFileName(self.win, "Export the analysis as CSV", f"{self.session.name}_analysis.csv", "CSV (*.csv)")
        if not path:
            return None
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            aa.write_csv(path, self.analysis, self.settings)
        except OSError as e:
            qtk.error(self.win, "Export CSV", str(e))
            return None
        self.win._announce("CSV saved")
        return path

    def report_frames(self, limit=6):
        """Which frames go in the report: the worst failures first, then passing frames spread over the session."""
        ev, an = self.ev, self.analysis
        worst = []
        for fi in ev.with_fail:
            errs = [aa.error_fraction(d.pred, s.value(self.settings.method)) for _i, d, s in kept_boxes(an, fi, self.settings)]
            worst.append((max([e for e in errs if e is not None] or [0]), fi))
        fails = [fi for _e, fi in sorted(worst, reverse=True)[:limit]]
        passes = [fi for fi, st in enumerate(ev.state) if st == "pass"]
        n = min(limit, len(passes))
        pick = [passes[int(i * len(passes) / n)] for i in range(n)]            # spread over the passing frames, none twice
        return fails, pick

    def export_report(self, path=None):
        if self.analysis is None or self.analysis.analysed == 0:
            return None
        if not path:
            path, _ = QFileDialog.getSaveFileName(self.win, "Export the report", f"{self.session.name}_model_check.html", "Report page (*.html)")
        if not path:
            return None
        if not path.lower().endswith((".html", ".htm")):
            path += ".html"
        fails, passes = self.report_frames()
        examples = [(f"Frame {fi + 1}: a miss" if fi in fails else f"Frame {fi + 1}: passes", self._png_bytes(self.render_frame(fi, 960, "box"))) for fi in fails + passes]
        page = aa.report_html(self.analysis, self.settings, self.ev, examples, made=time.strftime("%Y-%m-%d %H:%M"))
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(page)
        except OSError as e:
            qtk.error(self.win, "Export report", str(e))
            return None
        self.win._announce("Report saved")
        return path

    def shutdown(self):
        """The window is closing: the run stops after its frame, the made-up example session goes."""
        self._stop.set()
        if self.demo_dir is not None:
            shutil.rmtree(self.demo_dir, ignore_errors=True)
