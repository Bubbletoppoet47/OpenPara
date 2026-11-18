"""
sh_panel.py - the chart panel that sits to the right of the grid (the way Google Sheets does it).

    ChartPanel          Setup (type, data range, X, the series), Customize (the basic look in sections), Advanced (everything matplotlib can change), and a bar of presets.
                        It edits the chart's dictionary in place, so the chart on the grid follows every change as it is made.

Cells are picked on the sheet itself: the little button next to a range box makes the next selections on the grid fill that box (the button again stops it).  Nothing here asks for code: every input is a number inside bounds, a choice from a list, a colour, a switch or a short text.
"""
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                             QPushButton, QScrollArea, QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget)

import sh_adv
import sh_chart
import sh_dialogs as D
import sh_presets
import ui_kit

WARN_QSS = "QLineEdit { border:1px solid #c04040; }"
SET_INK = "#1a56c4"
LINE_TYPES = ("line", "step")


def _spin(lo, hi, value, step=1.0, decimals=1, auto=False, suffix=""):
    """A number box inside its bounds.  `auto`: the lowest step reads "Auto" and stands for no value (None)."""
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setKeyboardTracking(False)
    if suffix:
        box.setSuffix(suffix)
    if auto:
        box.setRange(lo - step, hi)
        box.setSpecialValueText("Auto")
        box.setValue(lo - step if value is None else value)
    else:
        box.setRange(lo, hi)
        box.setValue(lo if value is None else value)
    return box


def _spin_value(box, auto):
    if auto and box.value() <= box.minimum() + 1e-9:
        return None
    return float(box.value())


def _combo(options, current):
    cb = QComboBox()
    for key, text in options:
        cb.addItem(text, key)
    k = cb.findData(current)
    cb.setCurrentIndex(max(0, k))
    return cb


def _hint(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color:{ui_kit.MUTED}; font-size:11px;")
    return lb


def _fonts():
    out = [("", "Default"), ("sans-serif", "Sans-serif"), ("serif", "Serif"), ("monospace", "Monospace")]
    try:
        from matplotlib import font_manager
        names = sorted({f.name for f in font_manager.fontManager.ttflist})
        out += [(n, n) for n in names[:400]]
    except Exception:                                    # noqa: BLE001
        pass
    return out


class PickEdit(QWidget):
    """A range box with a button that makes the next selections on the sheet fill it."""
    committed = pyqtSignal(str)
    pick_toggled = pyqtSignal(object, bool)

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.btn = QToolButton()
        self.btn.setText("▦")
        self.btn.setCheckable(True)
        self.btn.setToolTip("Select the cells on the sheet")
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn)
        self.edit.editingFinished.connect(lambda: self.committed.emit(self.edit.text()))
        self.btn.toggled.connect(lambda on: self.pick_toggled.emit(self, on))

    def text(self):
        return self.edit.text()

    def set_text(self, t):
        self.edit.blockSignals(True)
        self.edit.setText(t)
        self.edit.blockSignals(False)

    def set_state(self, ok, tip=""):
        self.edit.setStyleSheet("" if ok else WARN_QSS)
        self.edit.setToolTip(tip)

    def set_picking(self, on):
        self.btn.blockSignals(True)
        self.btn.setChecked(on)
        self.btn.blockSignals(False)
        self.edit.setStyleSheet("QLineEdit { border:1px solid #2b7de9; }" if on else "")


class SeriesRow(QFrame):
    """One series: colour, name, left / right axis, how it is drawn, and the cells it reads."""
    edited = pyqtSignal(int, str, object)
    removed = pyqtSignal(int)
    pick_toggled = pyqtSignal(object, bool)

    def __init__(self, index, series, ctype):
        super().__init__()
        self.index = index
        self.setFrameShape(QFrame.Shape.StyledPanel)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.color = D.ColorButton(series.get("color") or "#2b7de9")
        self.color.setFixedWidth(26)
        self.color.picked.connect(lambda c: self.edited.emit(self.index, "color", c))
        self.name = QLineEdit(series.get("label", ""))
        self.name.setPlaceholderText(f"Series {index + 1}")
        self.name.editingFinished.connect(lambda: self.edited.emit(self.index, "label", self.name.text().strip()))
        self.axis = _combo([("L", "Left"), ("R", "Right")], series.get("axis", "L"))
        self.axis.setToolTip("Which Y axis the series uses")
        self.axis.currentIndexChanged.connect(lambda _i: self.edited.emit(self.index, "axis", self.axis.currentData()))
        self.style = _combo([("line", "Line"), ("markers", "Markers"), ("both", "Both")], series.get("style", "line"))
        self.style.setVisible(ctype in LINE_TYPES)
        self.style.currentIndexChanged.connect(lambda _i: self.edited.emit(self.index, "style", self.style.currentData()))
        b_del = QToolButton()
        b_del.setText("✕")
        b_del.setToolTip("Remove the series")
        b_del.clicked.connect(lambda _c=False: self.removed.emit(self.index))
        for w in (self.color, self.name, self.axis, self.style, b_del):
            top.addWidget(w, 1 if w is self.name else 0)
        v.addLayout(top)
        self.range = PickEdit("Y values: the cells of the series")
        self.range.set_text(series.get("y", ""))
        self.range.committed.connect(lambda t: self.edited.emit(self.index, "y", t))
        self.range.pick_toggled.connect(lambda w, on: self.pick_toggled.emit(w, on))
        v.addWidget(self.range)


class ChartPanel(QWidget):
    changed = pyqtSignal(str)                  # chart id: something about the chart was changed
    closed = pyqtSignal()
    export_asked = pyqtSignal(str)
    message = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.wb = None
        self.grid = None
        self.chart = None
        self.sheet = ""
        self._loading = False
        self._pick = None                       # the PickEdit that is taking the selections of the sheet
        self._pick_set = None                   # what to do with the text the selection gives
        self.setMinimumWidth(360)
        self.setObjectName("chartpanel")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._emit_now)
        self.note_timer = QTimer(self)
        self.note_timer.setSingleShot(True)
        self.note_timer.setInterval(500)
        self.note_timer.timeout.connect(self.update_notes)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        head = QHBoxLayout()
        self.heading = QLabel("Chart")
        self.heading.setStyleSheet(f"font-weight:600; color:{ui_kit.INK};")
        head.addWidget(self.heading, 1)
        b_exp = QToolButton()
        b_exp.setText("Export…")
        b_exp.setToolTip("Save the chart as PNG, SVG or PDF")
        b_exp.clicked.connect(lambda _c=False: self.chart and self.export_asked.emit(self.chart["id"]))
        b_x = QToolButton()
        b_x.setText("✕")
        b_x.setToolTip("Close the panel")
        b_x.clicked.connect(lambda _c=False: self.close_panel())
        head.addWidget(b_exp)
        head.addWidget(b_x)
        lay.addLayout(head)
        # ---- presets
        pr = QHBoxLayout()
        pr.setSpacing(3)
        pr.addWidget(QLabel("Look"))
        self.preset = QComboBox()
        self.preset.setToolTip("A saved look: fonts, line widths, grid, frame, legend and the advanced options (never data or words)")
        pr.addWidget(self.preset, 1)
        b_apply = QPushButton("Apply")
        b_apply.clicked.connect(lambda _c=False: self.apply_preset())
        b_save = QPushButton("Save as…")
        b_save.clicked.connect(lambda _c=False: self.save_preset())
        self.b_more = QToolButton()
        self.b_more.setText("⋯")
        self.b_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.b_more)
        menu.addAction("Use for new charts", self.preset_default)
        menu.addAction("Delete this look", self.preset_delete)
        menu.addSeparator()
        menu.addAction("Export saved looks…", self.preset_export)
        menu.addAction("Import looks…", self.preset_import)
        self.b_more.setMenu(menu)
        for w in (b_apply, b_save, self.b_more):
            pr.addWidget(w)
        lay.addLayout(pr)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        lay.addWidget(self.tabs, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{ui_kit.WARN}; font-size:11px;")
        lay.addWidget(self.note)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet(f"color:{ui_kit.BAD}; font-size:11px;")
        lay.addWidget(self.msg)
        self.build_setup()
        self.build_customize()
        self.build_advanced()
        self.tabs.currentChanged.connect(lambda _i: self.stop_pick())
        self.reload_presets()

    # ------------------------------------------------------------------ the chart being edited
    def set_context(self, wb, grid):
        self.wb, self.grid = wb, grid

    def open_chart(self, chart, sheet, start_pick=False):
        """Shows `chart` (a dictionary of the sheet) for editing."""
        self.stop_pick()
        self.chart, self.sheet = chart, sheet
        self.heading.setText(f"Chart: {chart.get('title') or chart.get('id')}")
        self.load_all()
        if start_pick and not chart.get("series"):
            self.tabs.setCurrentIndex(0)
            self.data_range.btn.setChecked(True)
        self.update_notes()

    def close_panel(self):
        self.stop_pick()
        self.chart = None
        self.hide()
        self.closed.emit()

    def is_open_for(self, cid):
        return self.chart is not None and self.chart.get("id") == cid and not self.isHidden()

    def picking(self):
        return self._pick is not None

    def load_all(self):
        self._loading = True
        try:
            self.load_setup()
            self.load_customize()
            self.load_advanced()
        finally:
            self._loading = False

    # ------------------------------------------------------------------ telling the sheet
    def touch(self):
        """The chart changed: the sheet redraws it soon (typing does not redraw at every key)."""
        if self._loading or self.chart is None:
            return
        self.timer.start()
        self.note_timer.start()

    def _emit_now(self):
        if self.chart is not None:
            self.changed.emit(self.chart["id"])

    def say(self, text, level="bad"):
        self.msg.setText(text if level == "bad" else "")
        if level != "bad" and text:
            self.message.emit(text, level)

    def sync_size(self):
        """The chart was moved or resized on the sheet: the size boxes follow."""
        if self.chart is None:
            return
        was, self._loading = self._loading, True
        try:
            w, h = self.chart.get("size", sh_chart.DEFAULT_SIZE)
            self.cw["w"].setValue(int(w))
            self.cw["h"].setValue(int(h))
        finally:
            self._loading = was

    def update_notes(self):
        if self.chart is None or self.wb is None:
            self.note.setText("")
            return
        notes = sh_chart.notes(self.wb, self.chart)
        self.note.setText("⚠ " + "\n⚠ ".join(notes[:4]) + (f"\n… and {len(notes) - 4} more" if len(notes) > 4 else "") if notes else "")

    # ------------------------------------------------------------------ picking cells on the sheet
    def start_pick(self, widget, on):
        """The range box `widget` takes the selections of the sheet while `on`."""
        if on:
            if self._pick is not None and self._pick is not widget:
                self._pick.set_picking(False)
            self._pick = widget
            widget.set_picking(True)
            self.say("Select the cells on the sheet.", "good")
            if self.grid is not None:
                self.grid.setFocus()
        elif self._pick is widget:
            widget.set_picking(False)
            self._pick = None

    def stop_pick(self):
        if self._pick is not None:
            try:
                self._pick.set_picking(False)
            except RuntimeError:
                pass
            self._pick = None

    def grid_selection(self):
        """The tab tells the panel that the selection of the grid changed: a range box that is picking takes it."""
        if self._pick is None or self.grid is None or self.chart is None:
            return
        g = self.grid
        rects = g.used_rects()                                # (a whole column or row stops where the data stops)
        use = rects if self._pick is self.data_range else rects[-1:]
        text = ", ".join(D.rect_text(g.sheet, a) for a in use)
        self._pick.set_text(text)
        self._pick.committed.emit(text)

    # ------------------------------------------------------------------ Setup
    def build_setup(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(6)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.type = _combo(sh_chart.TYPES, "line")
        self.type.currentIndexChanged.connect(lambda _i: self.on_type())
        form.addRow("Chart type", self.type)
        v.addLayout(form)
        row = QHBoxLayout()
        self.swap = QCheckBox("Swap X and Y")
        self.swap.setToolTip("Put the X values on the vertical axis")
        self.swap.toggled.connect(lambda on: self.set_chart("swap", on))
        self.stacked = QCheckBox("Stack")
        self.stacked.toggled.connect(lambda on: self.set_chart("stacked", on))
        row.addWidget(self.swap)
        row.addWidget(self.stacked)
        row.addStretch(1)
        v.addLayout(row)
        sec = ui_kit.Section("sheets-chart", None, "Data range", True)
        self.data_range = PickEdit("The cells to plot, e.g. A1:C20")
        self.data_range.committed.connect(lambda t: self.on_data_range(t))
        self.data_range.pick_toggled.connect(self.start_pick)
        sec.body.addWidget(self.data_range)
        self.switch = QCheckBox("Switch rows / columns")
        self.headers = QCheckBox("First row is the header")
        self.xcol = QCheckBox("First column is X")
        for cb in (self.switch, self.headers, self.xcol):
            cb.toggled.connect(lambda _on: self.on_data_options())
            sec.body.addWidget(cb)
        sec.body.addWidget(_hint("Changing the range or these boxes reads the series again; their colours and styles stay."))
        v.addWidget(sec)
        sec = ui_kit.Section("sheets-chart", None, "X axis", True)
        self.xrange = PickEdit("Cells for X (empty: 1, 2, 3 …)")
        self.xrange.committed.connect(lambda t: self.on_x_range(t))
        self.xrange.pick_toggled.connect(self.start_pick)
        sec.body.addWidget(self.xrange)
        v.addWidget(sec)
        sec = ui_kit.Section("sheets-chart", None, "Series", True)
        self.series_box = QVBoxLayout()
        self.series_box.setSpacing(4)
        sec.body.addLayout(self.series_box)
        b_add = QPushButton("Add series")
        b_add.clicked.connect(lambda _c=False: self.add_series())
        sec.body.addWidget(b_add)
        v.addWidget(sec)
        v.addStretch(1)
        self.rows = []
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tabs.addTab(scroll, "Setup")

    def load_setup(self):
        ch = self.chart
        self.type.setCurrentIndex(max(0, self.type.findData(ch.get("type", "line"))))
        self.swap.setChecked(bool(ch.get("swap")))
        self.stacked.setChecked(bool(ch.get("stacked")))
        self.stacked.setVisible(ch.get("type") in ("column", "bar", "area"))
        d = ch.get("data") or {}
        self.data_range.set_text(d.get("range", ""))
        for cb, key, default in ((self.switch, "switch", False), (self.headers, "headers", False), (self.xcol, "x_col", False)):
            cb.blockSignals(True)
            cb.setChecked(bool(d.get(key)) if d.get(key) is not None else default)
            cb.blockSignals(False)
        self.relabel_options()
        self.xrange.set_text(ch.get("x", ""))
        self.rebuild_series_rows()

    def relabel_options(self):
        sw = self.switch.isChecked()
        self.headers.setText("First column is the header" if sw else "First row is the header")
        self.xcol.setText("First row is X" if sw else "First column is X")

    def rebuild_series_rows(self):
        if self._pick is not None and self._pick not in (self.data_range, self.xrange):
            self.stop_pick()                                 # (the box of a series that is going away)
        for r in self.rows:
            r.hide()
            r.deleteLater()
        self.rows = []
        ctype = self.chart.get("type", "line")
        for i, s in enumerate(self.chart.get("series", [])):
            row = SeriesRow(i, s, ctype)
            row.edited.connect(self.on_series_edit)
            row.removed.connect(self.remove_series)
            row.pick_toggled.connect(self.start_pick)
            self.series_box.addWidget(row)
            self.rows.append(row)
        self.reload_series_choice()

    def on_type(self):
        if self._loading or self.chart is None:
            return
        self.chart["type"] = self.type.currentData()
        self.stacked.setVisible(self.chart["type"] in ("column", "bar", "area"))
        for r in self.rows:
            r.style.setVisible(self.chart["type"] in LINE_TYPES)
        self.touch()

    def set_chart(self, key, value):
        if self._loading or self.chart is None:
            return
        self.chart[key] = value
        self.touch()

    def on_data_range(self, text):
        if self._loading or self.chart is None:
            return
        text = text.strip()
        if not text:
            self.chart["data"] = {"range": "", "headers": None, "x_col": None, "switch": False}
            self.touch()
            return
        parts = sh_chart.split_ranges(text)
        norm = [D.norm_range(self.wb, t, self.sheet) for t in parts]
        if any(n is None for n in norm):
            self.data_range.set_state(False, "Not a range of cells.")
            self.say(f"'{text}' is not a range of cells.")
            return
        self.data_range.set_state(True)
        self.say("", "good")
        d = self.chart.setdefault("data", {})
        d["range"] = ", ".join(norm)
        d["headers"], d["x_col"] = None, None                    # a new range: decided from the cells again
        self.reread()

    def on_data_options(self):
        self.relabel_options()
        if self._loading or self.chart is None:
            return
        d = self.chart.setdefault("data", {})
        d["switch"], d["headers"], d["x_col"] = self.switch.isChecked(), self.headers.isChecked(), self.xcol.isChecked()
        self.reread()

    def reread(self):
        msg = sh_chart.rebuild(self.wb, self.chart, self.sheet)
        if msg:
            self.say(msg)
            return
        d = self.chart["data"]
        self._loading = True
        try:
            self.data_range.set_text(d["range"])
            for cb, key in ((self.headers, "headers"), (self.xcol, "x_col")):
                cb.setChecked(bool(d.get(key)))
            self.xrange.set_text(self.chart.get("x", ""))
            self.rebuild_series_rows()
            self.load_customize_axes()
        finally:
            self._loading = False
        self.touch()

    def on_x_range(self, text):
        if self._loading or self.chart is None:
            return
        text = text.strip()
        if text:
            n = D.norm_range(self.wb, text, self.sheet)
            if n is None:
                self.xrange.set_state(False, "Not a range of cells.")
                self.say(f"'{text}' is not a range of cells.")
                return
            text = n
        self.xrange.set_state(True)
        self.say("", "good")
        self.chart["x"] = text
        self.xrange.set_text(text)
        self.touch()

    def add_series(self):
        if self.chart is None:
            return
        ch = self.chart
        ch.setdefault("series", []).append({"y": "", "label": "", "axis": "L", "style": "both" if ch.get("type") == "scatter" else "line", "color": sh_chart.next_color(ch)})
        self.rebuild_series_rows()
        self.rows[-1].range.btn.setChecked(True)
        self.touch()

    def remove_series(self, i):
        sers = self.chart.get("series", [])
        if 0 <= i < len(sers):
            del sers[i]
            self.shift_series_keys(i)
            self.rebuild_series_rows()
            self.touch()

    def shift_series_keys(self, removed):
        """The advanced settings of one series (series[3]:...) follow the series that move up when one is removed."""
        adv = self.chart.get("adv") or {}
        out = {}
        for key, v in adv.items():
            t, idx, name = sh_adv.split_key(key)
            if idx is None or t not in sh_adv.INDEXED:
                out[key] = v
            elif idx < removed:
                out[key] = v
            elif idx > removed:
                out[sh_adv.make_key(t, name, idx - 1)] = v
        self.chart["adv"] = out

    def on_series_edit(self, i, key, value):
        if self._loading or self.chart is None:
            return
        sers = self.chart.get("series", [])
        if not 0 <= i < len(sers):
            return
        if key == "y":
            t = (value or "").strip()
            n = D.norm_range(self.wb, t, self.sheet) if t else None
            row = self.rows[i]
            if t and n is None:
                row.range.set_state(False, "Not a range of cells.")
                self.say(f"'{t}' is not a range of cells.")
                return
            row.range.set_state(True)
            self.say("", "good")
            row.range.set_text(n or "")
            value = n or ""
        sers[i][key] = value
        if key == "label":
            self.reload_series_choice()
        self.touch()

    # ------------------------------------------------------------------ Customize
    def build_customize(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(4)
        self.cw = {}                                           # the widgets of this tab by name

        def section(title, open_=False):
            s = ui_kit.Section("sheets-chart", None, title, open_)
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            s.body.addLayout(form)
            v.addWidget(s)
            return form

        # --- the chart
        f = section("Chart", True)
        self.cw["title"] = QLineEdit()
        self.cw["title"].textEdited.connect(lambda t: self.set_chart("title", t.strip()))
        f.addRow("Title", self.cw["title"])
        self.cw["palette"] = _combo([("", "Keep colours")] + [(k, k) for k in sh_chart.PALETTES], "")
        self.cw["palette"].setToolTip("Gives the series the colours of this palette")
        self.cw["palette"].activated.connect(lambda _i: self.on_palette())
        f.addRow("Palette", self.cw["palette"])
        row = QHBoxLayout()
        self.cw["w"] = QSpinBox()
        self.cw["h"] = QSpinBox()
        for k, box in (("w", self.cw["w"]), ("h", self.cw["h"])):
            box.setRange(200, 3000)
            box.setSuffix(" px")
            box.setKeyboardTracking(False)
            box.valueChanged.connect(lambda _v: self.on_size())
        row.addWidget(self.cw["w"])
        row.addWidget(QLabel("×"))
        row.addWidget(self.cw["h"])
        f.addRow("Size", row)
        self.cw["bg"] = self.color_row(f, "Background", "bg")
        self.cw["plot_bg"] = self.color_row(f, "Plot area", "plot_bg")
        self.cw["dpi"] = self.num_row(f, "Saved picture", "dpi", 50, 1200, 25, 0, suffix=" dpi")
        # --- text
        f = section("Text")
        self.cw["font"] = QComboBox()
        self.cw["font"].setEditable(True)
        self.cw["font"].setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for key, text in _fonts():
            self.cw["font"].addItem(text, key)
        self.cw["font"].activated.connect(lambda _i: self.on_font())
        self.cw["font"].lineEdit().editingFinished.connect(lambda: self.on_font())
        f.addRow("Font", self.cw["font"])
        for key, label in (("title_size", "Title size"), ("label_size", "Axis label size"), ("tick_size", "Number size"), ("legend_size", "Legend size")):
            self.cw[key] = self.num_row(f, label, key, 5, 60, 0.5, 1, auto=True, suffix=" pt")
        self.cw["title_bold"] = self.check_row(f, "Title bold", "title_bold")
        self.cw["label_bold"] = self.check_row(f, "Axis labels bold", "label_bold")
        self.cw["text_color"] = self.color_row(f, "Text colour", "text_color")
        self.cw["tick_color"] = self.color_row(f, "Number colour", "tick_color")
        # --- lines
        f = section("Lines and markers")
        self.cw["line_width"] = self.num_row(f, "Line width", "line_width", 0.25, 12, 0.25, 2, suffix=" pt")
        self.cw["line_style"] = self.choice_row(f, "Line style", "line_style", sh_adv.LINESTYLES)
        self.cw["marker"] = self.choice_row(f, "Marker", "marker", sh_adv.MARKERS)
        self.cw["marker_size"] = self.num_row(f, "Marker size", "marker_size", 1, 24, 0.5, 1, suffix=" pt")
        self.cw["auto_dash"] = self.check_row(f, "A different dash and marker for each series", "auto_dash")
        self.cw["bar_width"] = self.num_row(f, "Bar width", "bar_width", 0.1, 1.0, 0.05, 2)
        self.cw["area_alpha"] = self.num_row(f, "Area opacity", "area_alpha", 0.05, 1.0, 0.05, 2)
        # --- one series
        f = section("One series")
        self.cw["series_pick"] = QComboBox()
        self.cw["series_pick"].currentIndexChanged.connect(lambda _i: self.load_series_look())
        f.addRow("Series", self.cw["series_pick"])
        self.sw = {}
        self.sw["color"] = D.ColorButton("#2b7de9")
        self.sw["color"].picked.connect(lambda c: self.set_series_look("color", c))
        f.addRow("Colour", self.sw["color"])
        self.sw["width"] = _spin(0.25, 12, None, 0.25, 2, auto=True, suffix=" pt")
        self.sw["width"].valueChanged.connect(lambda _v: self.set_series_look("width", _spin_value(self.sw["width"], True)))
        f.addRow("Line width", self.sw["width"])
        self.sw["linestyle"] = _combo([("", "Same as the chart")] + sh_adv.LINESTYLES, "")
        self.sw["linestyle"].activated.connect(lambda _i: self.set_series_look("linestyle", self.sw["linestyle"].currentData() or None))
        f.addRow("Line style", self.sw["linestyle"])
        self.sw["marker"] = _combo([("", "Same as the chart")] + sh_adv.MARKERS, "")
        self.sw["marker"].activated.connect(lambda _i: self.set_series_look("marker", self.sw["marker"].currentData() or None))
        f.addRow("Marker", self.sw["marker"])
        self.sw["marker_size"] = _spin(1, 24, None, 0.5, 1, auto=True, suffix=" pt")
        self.sw["marker_size"].valueChanged.connect(lambda _v: self.set_series_look("marker_size", _spin_value(self.sw["marker_size"], True)))
        f.addRow("Marker size", self.sw["marker_size"])
        # --- axes
        f = section("Axes")
        self.ax = {}
        for key, title in (("x", "X axis"), ("left", "Left Y axis"), ("right", "Right Y axis")):
            lab = QLabel(title)
            lab.setStyleSheet("font-weight:600;")
            f.addRow(lab)
            ed = {"label": QLineEdit(), "units": QLineEdit(), "log": QCheckBox("Log scale"), "min": QLineEdit(), "max": QLineEdit()}
            ed["units"].setPlaceholderText("units, e.g. in")
            for k in ("min", "max"):
                ed[k].setPlaceholderText("auto (a number or a cell)")
            ed["label"].textEdited.connect(lambda _t, k=key: self.on_axis(k))
            ed["units"].textEdited.connect(lambda _t, k=key: self.on_axis(k))
            ed["log"].toggled.connect(lambda _on, k=key: self.on_axis(k))
            ed["min"].editingFinished.connect(lambda k=key: self.on_axis(k))
            ed["max"].editingFinished.connect(lambda k=key: self.on_axis(k))
            f.addRow("Label", ed["label"])
            f.addRow("Units", ed["units"])
            f.addRow("", ed["log"])
            f.addRow("Minimum", ed["min"])
            f.addRow("Maximum", ed["max"])
            self.ax[key] = ed
        # --- grid and frame
        f = section("Grid, frame and ticks")
        self.cw["grid"] = self.choice_row(f, "Grid lines", "grid", [("both", "Both"), ("horizontal", "Horizontal"), ("vertical", "Vertical"), ("none", "None")])
        self.cw["grid_style"] = self.choice_row(f, "Grid style", "grid_style", sh_adv.LINESTYLES)
        self.cw["grid_width"] = self.num_row(f, "Grid width", "grid_width", 0.1, 4, 0.1, 1, suffix=" pt")
        self.cw["grid_color"] = self.color_row(f, "Grid colour", "grid_color")
        self.cw["minor_grid"] = self.check_row(f, "Minor grid lines", "minor_grid")
        self.cw["frame"] = self.choice_row(f, "Frame", "frame", [("box", "Box"), ("open", "Left and bottom only"), ("none", "None")])
        self.cw["frame_width"] = self.num_row(f, "Frame width", "frame_width", 0.25, 6, 0.25, 2, suffix=" pt")
        self.cw["frame_color"] = self.color_row(f, "Frame colour", "frame_color")
        self.cw["tick_dir"] = self.choice_row(f, "Ticks point", "tick_dir", [("out", "Out"), ("in", "In"), ("inout", "Both")])
        self.cw["tick_len"] = self.num_row(f, "Tick length", "tick_len", 0, 16, 0.5, 1, suffix=" pt")
        self.cw["minor_ticks"] = self.check_row(f, "Minor ticks", "minor_ticks")
        # --- legend
        f = section("Legend")
        self.cw["legend"] = QCheckBox("Show the legend")
        self.cw["legend"].toggled.connect(lambda on: self.set_chart("legend", on))
        f.addRow(self.cw["legend"])
        self.cw["legend_pos"] = self.choice_row(f, "Place", "legend_pos", sh_adv.LEGEND_LOCS)
        self.cw["legend_cols"] = self.num_row(f, "Columns", "legend_cols", 1, 8, 1, 0)
        self.cw["legend_frame"] = self.check_row(f, "Frame", "legend_frame")
        # --- guides
        s = ui_kit.Section("sheets-chart", None, "Limit lines, zones and notes", False)
        s.body.addWidget(_hint("A value is a number or a cell, so a limit follows the sheet."))
        self.limits = D.RowTable([("Axis", "combo", D.AXES_X), ("Value", "text", ""), ("Label", "text", "wide"), ("Colour", "color", None)],
                                 lambda: ["L", "", "", "#c0392b"], "Add limit line")
        self.zones = D.RowTable([("Axis", "combo", D.AXES_X), ("From", "text", ""), ("To", "text", ""), ("Label", "text", "wide"), ("Colour", "color", None)],
                                lambda: ["L", "", "", "", "#e8590c"], "Add shaded zone")
        self.notes = D.RowTable([("X", "text", ""), ("Y", "text", ""), ("Axis", "combo", D.AXES), ("Text", "text", "wide")], lambda: ["", "", "L", ""], "Add note")
        for title, w in (("Limit lines", self.limits), ("Shaded zones", self.zones), ("Notes (text with an arrow)", self.notes)):
            lab = QLabel(title)
            lab.setStyleSheet("font-weight:600;")
            s.body.addWidget(lab)
            s.body.addWidget(w)
            w.changed.connect(self.on_guides)
        v.addWidget(s)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tabs.addTab(scroll, "Customize")

    # small row builders: each keeps its widget in self.cw[key] and stores into chart["style"][key]
    def num_row(self, form, label, key, lo, hi, step, decimals, auto=False, suffix=""):
        box = _spin(lo, hi, None if auto else lo, step, decimals, auto=auto, suffix=suffix)
        box.valueChanged.connect(lambda _v, k=key, b=box, a=auto: self.set_style(k, _spin_value(b, a)))
        form.addRow(label, box)
        return box

    def check_row(self, form, label, key):
        cb = QCheckBox(label)
        cb.toggled.connect(lambda on, k=key: self.set_style(k, on))
        form.addRow(cb)
        return cb

    def choice_row(self, form, label, key, options):
        cb = _combo(options, None)
        cb.activated.connect(lambda _i, k=key, c=cb: self.set_style(k, c.currentData()))
        form.addRow(label, cb)
        return cb

    def color_row(self, form, label, key):
        b = D.ColorButton("#ffffff")
        b.picked.connect(lambda c, k=key: self.set_style(k, c))
        form.addRow(label, b)
        return b

    def set_style(self, key, value):
        if self._loading or self.chart is None:
            return
        spec = sh_chart.STYLE_SPEC.get(key)
        st = self.chart.setdefault("style", {})
        if spec is not None and value == spec[1]:
            st.pop(key, None)                                    # (the default is not kept in the file)
        else:
            st[key] = value
        if key == "grid":
            self.chart["grid"] = value != "none"
        self.touch()

    def on_font(self):
        if self._loading or self.chart is None:
            return
        cb = self.cw["font"]
        i = cb.findText(cb.currentText(), Qt.MatchFlag.MatchFixedString)
        name = (cb.itemData(i) if i >= 0 else cb.currentText().strip()) or ""
        if name != (self.chart.get("style") or {}).get("font", ""):
            self.set_style("font", name)

    def on_palette(self):
        if self.chart is None:
            return
        name = self.cw["palette"].currentData()
        if not name:
            return
        self.chart.setdefault("style", {})["palette"] = name
        sh_chart.recolor(self.chart, name)
        self._loading = True
        try:
            self.rebuild_series_rows()
            self.load_series_look()
        finally:
            self._loading = False
        self.touch()

    def on_size(self):
        if self._loading or self.chart is None:
            return
        self.chart["size"] = [self.cw["w"].value(), self.cw["h"].value()]
        self.touch()

    def reload_series_choice(self):
        pick = self.cw.get("series_pick") if hasattr(self, "cw") else None
        if pick is None or self.chart is None:
            return
        pick.blockSignals(True)
        cur = pick.currentIndex()
        pick.clear()
        for i, s in enumerate(self.chart.get("series", [])):
            pick.addItem(f"{i + 1}: {s.get('label') or 'Series ' + str(i + 1)}", i)
        pick.setCurrentIndex(max(0, min(cur, pick.count() - 1)) if pick.count() else -1)
        pick.blockSignals(False)
        self.reload_adv_scope()

    def series_look_index(self):
        i = self.cw["series_pick"].currentData()
        return i if isinstance(i, int) and 0 <= i < len(self.chart.get("series", [])) else None

    def load_series_look(self):
        if self.chart is None:
            return
        i = self.series_look_index()
        was, self._loading = self._loading, True
        try:
            on = i is not None
            for w in self.sw.values():
                w.setEnabled(on)
            if not on:
                return
            s = self.chart["series"][i]
            self.sw["color"].color = s.get("color") or "#2b7de9"
            self.sw["color"].paint()
            w = s.get("width")
            self.sw["width"].setValue(self.sw["width"].minimum() if w is None else float(w))
            for key in ("linestyle", "marker"):
                self.sw[key].setCurrentIndex(max(0, self.sw[key].findData(s.get(key) or "")))
            ms = s.get("marker_size")
            self.sw["marker_size"].setValue(self.sw["marker_size"].minimum() if ms is None else float(ms))
        finally:
            self._loading = was

    def set_series_look(self, key, value):
        if self._loading or self.chart is None:
            return
        i = self.series_look_index()
        if i is None:
            return
        s = self.chart["series"][i]
        if value is None:
            s.pop(key, None)
        else:
            s[key] = value
        if key == "color":
            self.rows[i].color.color = value
            self.rows[i].color.paint()
        self.touch()

    def on_axis(self, key):
        if self._loading or self.chart is None:
            return
        ed = self.ax[key]
        vals = {}
        ok = True
        for k in ("min", "max"):
            t = ed[k].text().strip()
            v = D.norm_value(self.wb, t, self.sheet) if t else ""
            if v is None:
                ed[k].setStyleSheet(WARN_QSS)
                self.say(f"'{t}' is not a number or a cell.")
                ok = False
            else:
                ed[k].setStyleSheet("")
                vals[k] = None if v == "" else v
        if not ok:
            return
        self.say("", "good")
        label, units, log = ed["label"].text().strip(), ed["units"].text().strip(), ed["log"].isChecked()
        if key == "x":
            self.chart.update({"x_label": label, "x_units": units, "x_log": log, "x_min": vals["min"], "x_max": vals["max"]})
        else:
            self.chart[key] = sh_chart.axis_def(label=label, units=units, log=log, min=vals["min"], max=vals["max"])
        self.touch()

    def on_guides(self):
        if self._loading or self.chart is None:
            return
        wb, sh = self.wb, self.sheet
        problems = []
        lim = []
        for axis, val, label, color in self.limits.rows():
            v = D.norm_value(wb, val, sh)
            if v == "":
                continue                                          # (a line that is still being typed)
            if v is None:
                problems.append(f"Limit line '{val}' is not a number or a cell.")
                continue
            lim.append({"axis": axis, "value": v, "label": label.strip(), "color": color})
        zs = []
        for axis, lo, hi, label, color in self.zones.rows():
            a, b = D.norm_value(wb, lo, sh), D.norm_value(wb, hi, sh)
            if a == "" and b == "":
                continue
            if a in (None, "") or b in (None, ""):
                problems.append(f"Zone '{lo}' to '{hi}': both ends must be a number or a cell.")
                continue
            zs.append({"axis": axis, "lo": a, "hi": b, "label": label.strip(), "color": color})
        ns = []
        for x, y, axis, text in self.notes.rows():
            a, b = D.norm_value(wb, x, sh), D.norm_value(wb, y, sh)
            if a == "" and b == "" and not text.strip():
                continue
            if a in (None, "") or b in (None, ""):
                problems.append(f"Note '{text}': X and Y must be a number or a cell.")
                continue
            ns.append({"x": a, "y": b, "axis": axis, "text": text.strip()})
        self.chart["limits"], self.chart["zones"], self.chart["notes"] = lim, zs, ns
        self.say(problems[0] if problems else "", "bad" if problems else "good")
        self.touch()

    def load_customize_axes(self):
        ch = self.chart
        for key in ("x", "left", "right"):
            ed = self.ax[key]
            if key == "x":
                d = {"label": ch.get("x_label", ""), "units": ch.get("x_units", ""), "log": ch.get("x_log", False), "min": ch.get("x_min"), "max": ch.get("x_max")}
            else:
                d = ch.get(key, {})
            ed["label"].setText(d.get("label", ""))
            ed["units"].setText(d.get("units", ""))
            ed["log"].setChecked(bool(d.get("log")))
            ed["min"].setText(D._t(d.get("min")))
            ed["max"].setText(D._t(d.get("max")))
            ed["min"].setStyleSheet("")
            ed["max"].setStyleSheet("")

    def load_customize(self):
        ch = self.chart
        st, _n = sh_chart.style_of(ch)
        self.cw["title"].setText(ch.get("title", ""))
        self.cw["palette"].setCurrentIndex(max(0, self.cw["palette"].findData(st["palette"])))
        w, h = ch.get("size", sh_chart.DEFAULT_SIZE)
        self.cw["w"].setValue(int(w))
        self.cw["h"].setValue(int(h))
        for key, widget in self.cw.items():
            spec = sh_chart.STYLE_SPEC.get(key)
            if spec is None:
                continue
            kind = spec[0]
            if isinstance(widget, QDoubleSpinBox):
                v = st[key]
                widget.setValue(widget.minimum() if v is None else float(v))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(st[key]))
            elif isinstance(widget, QComboBox) and kind == "choice":
                widget.setCurrentIndex(max(0, widget.findData(st[key])))
            elif isinstance(widget, D.ColorButton):
                widget.color = st[key]
                widget.paint()
        k = self.cw["font"].findData(st["font"])
        if k >= 0:
            self.cw["font"].setCurrentIndex(k)
        else:
            self.cw["font"].setCurrentText(st["font"])
        if not ch.get("grid", True):
            self.cw["grid"].setCurrentIndex(max(0, self.cw["grid"].findData("none")))
        self.cw["legend"].setChecked(bool(ch.get("legend", True)))
        self.cw["legend_cols"].setValue(float(st["legend_cols"]))
        self.load_customize_axes()
        for table, rows in ((self.limits, [[x.get("axis", "L"), D._t(x.get("value")), x.get("label", ""), x.get("color")] for x in ch.get("limits", [])]),
                            (self.zones, [[x.get("axis", "L"), D._t(x.get("lo")), D._t(x.get("hi")), x.get("label", ""), x.get("color")] for x in ch.get("zones", [])]),
                            (self.notes, [[D._t(x.get("x")), D._t(x.get("y")), x.get("axis", "L"), x.get("text", "")] for x in ch.get("notes", [])])):
            table.t.setRowCount(0)
            for r in rows:
                table.add(r)
        self.load_series_look()

    # ------------------------------------------------------------------ Advanced
    def build_advanced(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(4)
        v.addWidget(_hint("Everything matplotlib can change. A setting you change here wins over the basic look; ✕ puts it back."))
        top = QHBoxLayout()
        self.adv_search = QLineEdit()
        self.adv_search.setPlaceholderText("Search the settings")
        self.adv_search.setClearButtonEnabled(True)
        self.adv_search.textChanged.connect(lambda _t: self.adv_filter())
        self.adv_changed = QCheckBox("Changed only")
        self.adv_changed.toggled.connect(lambda _on: self.adv_filter())
        b_reset = QPushButton("Reset all")
        b_reset.clicked.connect(lambda _c=False: self.adv_reset_all())
        top.addWidget(self.adv_search, 1)
        top.addWidget(self.adv_changed)
        top.addWidget(b_reset)
        v.addLayout(top)
        sc = QHBoxLayout()
        sc.addWidget(QLabel("Series settings apply to"))
        self.adv_scope = QComboBox()
        self.adv_scope.addItem("All series", None)
        self.adv_scope.currentIndexChanged.connect(lambda _i: self.adv_rescope())
        sc.addWidget(self.adv_scope, 1)
        v.addLayout(sc)
        self.adv_secs = []                                       # (Section, group title, [AdvRow]) in display order
        for gtitle, plist in sh_adv.groups():
            sec = ui_kit.Section("sheets-adv", None, gtitle, False)
            entry = {"sec": sec, "group": gtitle, "props": plist, "rows": None, "forced": False}
            sec.toggle.toggled.connect(lambda _on, e=entry: self.adv_build(e) if _on else None)
            v.addWidget(sec)
            self.adv_secs.append(entry)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tabs.addTab(scroll, "Advanced")

    def load_advanced(self):
        for e in self.adv_secs:
            if e["rows"] is not None:
                self.adv_refresh_rows(e)
            elif e["sec"].is_open():
                self.adv_build(e)
        self.adv_filter()

    def reload_adv_scope(self):
        if not hasattr(self, "adv_scope") or self.chart is None:
            return
        self.adv_scope.blockSignals(True)
        cur = self.adv_scope.currentData()
        self.adv_scope.clear()
        self.adv_scope.addItem("All series", None)
        for i, s in enumerate(self.chart.get("series", [])):
            self.adv_scope.addItem(f"Series {i + 1}: {s.get('label') or 'no name'}", i)
        k = self.adv_scope.findData(cur)
        self.adv_scope.setCurrentIndex(max(0, k))
        self.adv_scope.blockSignals(False)

    def adv_scope_index(self):
        return self.adv_scope.currentData()

    def adv_rescope(self):
        for e in self.adv_secs:
            if e["rows"] is not None and any(p.target in sh_adv.INDEXED for p in e["props"]):
                self.adv_refresh_rows(e)
        self.adv_filter()

    def adv_build(self, e):
        if e["rows"] is not None:
            return
        grid = QGridLayout()
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setVerticalSpacing(2)
        e["sec"].body.addLayout(grid)
        e["rows"] = []
        for n, p in enumerate(e["props"]):
            row = AdvRow(p, self)
            grid.addWidget(row.label, n, 0)
            grid.addWidget(row.editor, n, 1)
            grid.addWidget(row.reset, n, 2)
            e["rows"].append(row)
        self.adv_refresh_rows(e)
        self.adv_filter()

    def adv_key(self, p):
        idx = self.adv_scope_index() if p.target in sh_adv.INDEXED else None
        return sh_adv.make_key(p.target, p.name, idx)

    def adv_refresh_rows(self, e):
        adv = (self.chart or {}).get("adv") or {}
        for row in e["rows"] or []:
            row.load(adv.get(self.adv_key(row.p)))

    def adv_set(self, p, raw):
        """A value for property `p` was typed or picked (raw None: put it back)."""
        if self._loading or self.chart is None:
            return
        adv = self.chart.setdefault("adv", {})
        key = self.adv_key(p)
        if raw is None:
            adv.pop(key, None)
            return self.touch()
        ok, val, msg = sh_adv.coerce(p, raw)
        if not ok:
            self.say(msg)
            return
        self.say("", "good")
        if val is None:
            adv.pop(key, None)
        else:
            adv[key] = val
        self.touch()

    def adv_reset_all(self):
        if self.chart is None:
            return
        if self.chart.get("adv") and QMessageBox.question(self, "Reset all", "Put every advanced setting of this chart back?") != QMessageBox.StandardButton.Yes:
            return
        self.chart["adv"] = {}
        self.load_advanced()
        self.touch()

    def adv_filter(self):
        q = self.adv_search.text().strip().lower()
        only = self.adv_changed.isChecked()
        adv = (self.chart or {}).get("adv") or {}
        for e in self.adv_secs:
            if (q or only) and e["rows"] is None:
                self.adv_build_quiet(e)
            rows = e["rows"] or []
            shown = 0
            for row in rows:
                hit = (not q or q in row.p.label.lower() or q in row.p.name.lower() or q in e["group"].lower()) and (not only or self.adv_key(row.p) in adv)
                row.set_visible(hit)
                shown += 1 if hit else 0
            if q or only:
                e["sec"].setVisible(shown > 0)
                if shown > 0 and not e["sec"].is_open():
                    self.fold(e["sec"], True)
                    e["forced"] = True
            else:
                e["sec"].setVisible(True)
                if e["forced"]:
                    self.fold(e["sec"], False)
                    e["forced"] = False

    @staticmethod
    def fold(sec, on):
        """Opens or closes a section without it being remembered as the person's choice."""
        sec.toggle.blockSignals(True)
        sec.toggle.setChecked(on)
        sec.toggle.blockSignals(False)
        sec.set_open(on, save=False)

    def adv_build_quiet(self, e):
        was = self._loading
        self.adv_build(e)
        self._loading = was

    # ------------------------------------------------------------------ presets
    def reload_presets(self, select=None):
        cur = select or (self.preset.currentData() if self.preset.count() else None) or sh_presets.default_name()
        self.preset.blockSignals(True)
        self.preset.clear()
        dflt = sh_presets.default_name()
        for n in sh_presets.names():
            self.preset.addItem(n + ("  (new charts)" if n == dflt else ""), n)
        self.preset.setCurrentIndex(max(0, self.preset.findData(cur)))
        self.preset.blockSignals(False)

    def apply_preset(self):
        if self.chart is None:
            return
        name = self.preset.currentData()
        if not name or not sh_presets.apply(self.chart, name):
            self.say("That look is not there any more.")
            return
        self.say("", "good")
        self.load_all()
        self.touch()

    def save_preset(self):
        if self.chart is None:
            return
        name, ok = QInputDialog.getText(self, "Save the look", "Name of the look:")
        if not ok or not name.strip():
            return
        style, adv = sh_presets.parts(self.chart)
        msg = sh_presets.save(name.strip(), style, adv)
        if msg:
            self.say(msg)
            return
        self.say("", "good")
        self.reload_presets(select=name.strip())
        self.message.emit(f"Saved the look '{name.strip()}'. Words, data and the settings of single series are not part of it.", "good")

    def preset_default(self):
        name = self.preset.currentData()
        if name:
            sh_presets.set_default(name)
            self.reload_presets(select=name)
            self.message.emit(f"New charts start with '{name}'.", "good")

    def preset_delete(self):
        name = self.preset.currentData()
        if not name:
            return
        msg = sh_presets.delete(name)
        if msg:
            self.say(msg)
            return
        self.reload_presets(select="Default")

    def preset_export(self):
        from PyQt6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getSaveFileName(self, "Export saved looks", "chart_looks.json", "Looks (*.json)")
        if p:
            msg = sh_presets.export_file(p)
            self.say(msg) if msg else self.message.emit(f"Saved {p}", "good")

    def preset_import(self):
        from PyQt6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getOpenFileName(self, "Import looks", "", "Looks (*.json)")
        if p:
            n, msg = sh_presets.import_file(p)
            if msg:
                self.say(msg)
            else:
                self.reload_presets()
                self.message.emit(f"Added {n} look(s).", "good")


class AdvRow:
    """One advanced property: its name, an input of the right kind, and a ✕ that puts it back."""

    def __init__(self, p, panel):
        self.p, self.panel = p, panel
        self.label = QLabel(p.label)
        self.label.setToolTip(p.key)
        self.label.setWordWrap(True)
        self.reset = QToolButton()
        self.reset.setText("✕")
        self.reset.setToolTip("Put it back")
        self.reset.clicked.connect(lambda _c=False: self.on_reset())
        self.shown = None                                  # the text last shown or sent (a box that was only passed through changes nothing)
        self.editor = self.make_editor()
        self.is_set = False
        self.paint_state()

    def make_editor(self):
        p = self.p
        k = p.kind
        if k == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda on: self.send(bool(on)))
        elif k in ("int", "optint"):
            lo, hi = int(p.lo if p.lo is not None else -1000), int(p.hi if p.hi is not None else 1000)
            w = QSpinBox()
            w.setKeyboardTracking(False)
            if k == "optint":
                w.setRange(lo - 1, hi)
                w.setSpecialValueText("Default")
            else:
                w.setRange(lo, hi)
            w.valueChanged.connect(lambda v, o=(k == "optint"), mn=lo - 1: self.send(None if o and v <= mn else v))
        elif k in ("float", "optfloat"):
            lo = float(p.lo if p.lo is not None else -1000.0)
            hi = float(p.hi if p.hi is not None else 1000.0)
            step = float(p.step or 0.1)
            w = _spin(lo, hi, None, step, 3 if step < 0.1 else 2, auto=(k == "optfloat"))
            if k == "optfloat":
                w.setSpecialValueText("Default")
            w.valueChanged.connect(lambda v, o=(k == "optfloat"), b=w: self.send(_spin_value(b, o)))
        elif k == "fontsize":
            w = QComboBox()
            w.setEditable(True)
            for n in sh_adv.NAMED_SIZES + ("6", "8", "9", "10", "12", "14", "16", "18", "24", "36"):
                w.addItem(n)
            w.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            w.activated.connect(lambda _i, b=w: self.send_size(b.currentText()))
            w.lineEdit().editingFinished.connect(lambda b=w: self.send_size(b.currentText()))
        elif k == "color":
            w = D.ColorButton("#000000")
            w.picked.connect(lambda c: self.send(c))
        elif k == "choice":
            w = QComboBox()
            for key, text in p.choices or []:
                w.addItem(text, key)
            w.activated.connect(lambda _i, b=w: self.send(b.currentData()))
        else:
            w = QLineEdit()
            w.editingFinished.connect(lambda b=w: self.send_text(b.text()))
        return w

    def send_text(self, text):
        if text != self.shown:
            self.shown = text
            self.send(text)

    def send_size(self, text):
        t = text.strip()
        if t == (self.shown or ""):
            return
        self.shown = t
        self.send(t if t else None)

    def send(self, raw):
        if self.panel._loading:
            return
        self.panel.adv_set(self.p, raw)
        self.is_set = raw is not None and self.panel.adv_key(self.p) in (self.panel.chart.get("adv") or {})
        self.paint_state()

    def on_reset(self):
        self.panel.adv_set(self.p, None)
        self.load(None)

    def load(self, raw):
        """Shows the stored value (raw) or the default; no change is made to the chart."""
        p, w = self.p, self.editor
        self.is_set = raw is not None
        val = raw if raw is not None else p.default
        was, self.panel._loading = self.panel._loading, True
        try:
            k = p.kind
            if k == "bool":
                w.setChecked(bool(val))
            elif k in ("int", "optint"):
                w.setValue(w.minimum() if val is None else int(val))
            elif k in ("float", "optfloat"):
                w.setValue(w.minimum() if val is None else float(val))
            elif k == "fontsize":
                self.shown = "" if val is None else (str(val) if isinstance(val, str) else f"{val:g}")
                w.setCurrentText(self.shown)
            elif k == "color":
                w.color = sh_adv.to_hex(val) if val is not None else "#000000"
                w.paint()
            elif k == "choice":
                i = w.findData(val)
                w.setCurrentIndex(i if i >= 0 else 0)
            else:
                text = ", ".join(str(x) for x in val) if isinstance(val, (list, tuple)) else ("" if val is None else str(val))
                self.shown = text
                w.setText(text)
        except (TypeError, ValueError):
            pass
        finally:
            self.panel._loading = was
        self.paint_state()

    def paint_state(self):
        on = self.is_set
        self.label.setStyleSheet(f"color:{SET_INK}; font-weight:600;" if on else "")
        self.reset.setEnabled(on)

    def set_visible(self, on):
        for w in (self.label, self.editor, self.reset):
            w.setVisible(on)
