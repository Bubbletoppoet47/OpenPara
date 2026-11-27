"""dr_panels.py - the panels of the Drawings window.

    NewDrawingDialog(sheet)       the first thing a new drawing asks: the sheet (standard sizes only, landscape or portrait, a preview) and the kind of projection
    ModelViewPanel(tab)           Model View: the models, the nine orientations, the display style, the scale; picking an orientation lets the view follow the pointer to the sheet.
                                  The style buttons and the scale field work on ONE view: the one that follows the pointer or is selected (undo takes it back); with none, they set
                                  what the next view starts with
    ProjectedPanel(tab)           Projected View: the view to project from, the display style and the scale (the parent's unless set); the pointer picks the side.  The same: the view
                                  just put down is the one they change
    ToolPanel(tab)                Dimension (the person picks the type: Horizontal, Vertical, Aligned, Diameter, Radius, Angle) / Center Mark / Centerline / Note / Balloon / Linear Note Pattern / Line / Rectangle / Circle / Arc: what to click, the options of the tool
                                  (a note's text, size and leader; the number of the next balloon; the direction, spacing and number of a note pattern), and ✔ OK to leave the tool
    OutlinePanel(tab)             the tree of the drawing (sheet, models, views and what is drawn on each, the notes, what is drawn on the sheet) with the Details of the selected item below it

A panel never changes the document itself: it asks the tab (dr_tab.DrawingTab), which keeps the undo and the dirty mark.
"""
from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QStackedWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import dr_annot as A
import dr_icons as I
import dr_items as IT
import dr_model as M
import dr_proj as P
import dr_sheet as S
import ui_kit

STYLE_BUTTONS = [("wireframe", "Wireframe"), ("hlv", "Hidden Lines\nVisible"), ("hlr", "Hidden Lines\nRemoved"), ("shaded_edges", "Shaded With\nEdges"), ("shaded", "Shaded")]
DIM_ICON = {"h": "dr_dim_h", "v": "dr_dim_v", "a": "dr_dim_len", "dia": "dr_dim_dia", "rad": "dr_dim_rad", "ang": "dr_dim_ang"}
BIG_QSS = "QToolButton{font-size:11px; padding:2px;} QToolButton:checked{background:#cfe3fb; border:1px solid #6aa0e0;} QToolButton:disabled{color:#a0a0a0;}"


def section(text):
    lb = QLabel(text)
    lb.setStyleSheet("font-weight:600; color:#4a5872; padding:8px 0 2px 0;")
    return lb


def icon_button(icon_key, text, tip, px=32, checkable=True):
    b = QToolButton()
    b.setIcon(I.icon(icon_key, px))
    b.setIconSize(QSize(px, px))
    b.setText(text)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    b.setToolTip(tip or text.replace("\n", " "))
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setStyleSheet(BIG_QSS)
    b.setMinimumWidth(64)
    return b


def ok_cancel(on_ok, on_cancel):
    row = QHBoxLayout()
    ok = QPushButton("✔ OK")
    ok.setToolTip("Finish")
    ok.clicked.connect(lambda _c=False: on_ok())
    cancel = QPushButton("✖ Cancel")
    cancel.clicked.connect(lambda _c=False: on_cancel())
    row.addWidget(ok)
    row.addWidget(cancel)
    row.addStretch(1)
    return row


def scale_combo(current=None):
    cb = QComboBox()
    cb.setEditable(True)
    for t, _v in M.SCALES:
        cb.addItem(t)
    cb.lineEdit().setPlaceholderText("1:2, 2:1, 0.5 ...")
    ui_kit.tame_combo(cb, 8)
    cb.setCurrentIndex(-1)                                   # nothing picked: a new view takes the scale the drawing starts its views at
    if current:
        cb.setCurrentText(current)
    return cb


# ---------------------------------------------------------------------------------------------------------------------------- the sheet dialog
class PaperPreview(QWidget):
    """The sheet as it lies on the table, to scale, on a grey ground, with its size written under it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.size_key, self.landscape = S.DEFAULT, True
        self.setMinimumSize(260, 220)

    def set_sheet(self, size_key, landscape):
        self.size_key, self.landscape = size_key, landscape
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#a9b1bf"))
        w, h = S.dims(self.size_key, self.landscape)
        room = QRectF(self.rect()).adjusted(24, 20, -24, -44)
        k = min(room.width() / w, room.height() / h)
        r = QRectF(room.center().x() - w * k / 2, room.center().y() - h * k / 2, w * k, h * k)
        p.fillRect(r.translated(3, 4), QColor(0, 0, 0, 55))
        p.fillRect(r, QColor("#ffffff"))
        p.setPen(QPen(QColor("#7d8799"), 1))
        p.drawRect(r)
        f = QFont(self.font())
        f.setPointSizeF(10)
        p.setFont(f)
        p.setPen(QColor("#10204d"))
        label = S.size(self.size_key)[1]
        inch = self.size_key.startswith("ansi")
        text = (f"{S.inch_text(w, h)}   ({w:.1f} x {h:.1f} mm)" if inch else f"{w:g} x {h:g} mm   ({S.inch_text(w, h)})")
        p.drawText(QRectF(0, self.height() - 40, self.width(), 18), Qt.AlignmentFlag.AlignCenter, text)
        p.setPen(QColor("#33415c"))
        p.drawText(QRectF(0, self.height() - 22, self.width(), 18), Qt.AlignmentFlag.AlignCenter, label.split("  ")[0] + (", landscape" if self.landscape else ", portrait"))
        p.end()


class NewDrawingDialog(QDialog):
    """Sheet setup: standard sizes only (ANSI A to E, ISO A4 to A0), landscape or portrait, and the projection (third angle by default)."""

    def __init__(self, sheet=None, parent=None, title="New drawing", ok_text="Create"):
        super().__init__(parent)
        self.setWindowTitle(title)
        sheet = sheet or {"size": S.DEFAULT, "landscape": True, "first_angle": False}
        lay = QVBoxLayout(self)
        lay.addWidget(ui_kit.note("Pick the sheet.  Only the standard sizes are offered."))
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.sizes = QListWidget()
        self.sizes.setIconSize(QSize(20, 20))
        for key, label, _w, _h in S.SIZES:
            it = QListWidgetItem(I.icon("dr_sheet", 20), label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.sizes.addItem(it)
        self.sizes.setMinimumWidth(230)
        left.addWidget(self.sizes, 1)
        row = QHBoxLayout()
        self.land = icon_button("dr_landscape", "Landscape", "The long side runs left to right", 24)
        self.port = icon_button("dr_portrait", "Portrait", "The long side runs up and down", 24)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(self.land)
        grp.addButton(self.port)
        row.addWidget(self.land)
        row.addWidget(self.port)
        row.addStretch(1)
        left.addLayout(row)
        form = QFormLayout()
        self.proj = QComboBox()
        self.proj.addItem("Third angle (US: ANSI)", False)
        self.proj.addItem("First angle (ISO)", True)
        form.addRow("Projection", self.proj)
        left.addLayout(form)
        body.addLayout(left, 0)
        self.preview = PaperPreview()
        body.addWidget(self.preview, 1)
        lay.addLayout(body, 1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok = ui_kit.primary(QPushButton(ok_text))
        self.ok.clicked.connect(self.accept)
        self.ok.setDefault(True)
        btns.addWidget(cancel)
        btns.addWidget(self.ok)
        lay.addLayout(btns)
        keys = [s[0] for s in S.SIZES]
        self.sizes.setCurrentRow(keys.index(sheet["size"]) if sheet["size"] in keys else 0)
        (self.land if sheet.get("landscape", True) else self.port).setChecked(True)
        self.proj.setCurrentIndex(1 if sheet.get("first_angle") else 0)
        self.sizes.currentRowChanged.connect(lambda _r: self.sync())
        self.land.toggled.connect(lambda _c: self.sync())
        self.sizes.itemDoubleClicked.connect(lambda _i: self.accept())
        self.resize(640, 420)
        self.sync()

    def sync(self):
        self.preview.set_sheet(self.size_key(), self.land.isChecked())

    def size_key(self):
        it = self.sizes.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else S.DEFAULT

    def result_sheet(self):
        return {"size": self.size_key(), "landscape": self.land.isChecked(), "first_angle": bool(self.proj.currentData())}


# ---------------------------------------------------------------------------------------------------------------------------- Model View
class ModelViewPanel(QWidget):
    """The Model View PropertyManager: pick a model, an orientation, a style and a scale; the view then follows the pointer until it is clicked onto the sheet."""
    TITLE = "Model View"

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.busy = False
        self.start_style, self.start_scale = "hlv", ""            # what the next view starts with while no view is the one these controls work on
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(ok_cancel(lambda: tab.finish_command(True), lambda: tab.finish_command(False)))
        t = QLabel(self.TITLE)
        t.setStyleSheet("font-weight:bold; font-size:13px; padding:4px 0;")
        lay.addWidget(t)
        lay.addWidget(section("Part / Assembly to Insert"))
        self.models = QListWidget()
        self.models.setMaximumHeight(96)
        self.models.setIconSize(QSize(18, 18))
        self.models.currentRowChanged.connect(lambda _r: self.sync_hint())
        lay.addWidget(self.models)
        self.add_btn = QPushButton("Add from file…")
        self.add_btn.setToolTip("Bring a part (.gpd) or an assembly (.gpa) into the drawing")
        self.add_btn.clicked.connect(lambda _c=False: tab.add_model_file())
        lay.addWidget(self.add_btn)
        lay.addWidget(section("Orientation"))
        grid = QGridLayout()
        grid.setSpacing(2)
        self.orient = QButtonGroup(self)
        self.orient.setExclusive(False)
        self.obtn = {}
        for i, name in enumerate(P.ORIENTATIONS):
            b = icon_button(I.ORIENT_ICON[name], name, f"{name} view: click here, then click on the sheet to put it down")
            b.clicked.connect(lambda _c=False, n=name: self.pick_orientation(n))
            grid.addWidget(b, i // 3, i % 3)
            self.obtn[name] = b
        lay.addLayout(grid)
        lay.addWidget(section("Display Style"))
        row = QHBoxLayout()
        row.setSpacing(2)
        self.style = QButtonGroup(self)
        self.sbtn = {}
        for key, label in STYLE_BUTTONS:
            b = icon_button(I.STYLE_ICON[key], label, label.replace("\n", " "), 28)
            b.setMinimumWidth(58)
            on = key in M.STYLE_KEYS
            b.setEnabled(on)
            if not on:
                b.setToolTip(label.replace("\n", " ") + " is not built yet")
            else:
                b.clicked.connect(lambda _c=False, k=key: self.style_clicked(k))
            self.style.addButton(b)
            self.sbtn[key] = b
            row.addWidget(b)
        self.style.setExclusive(True)
        self.sbtn["hlv"].setChecked(True)
        lay.addLayout(row)
        lay.addWidget(section("Scale"))
        self.scale = scale_combo()
        self.scale.setToolTip("The scale of this view: type it (1:2, 2:1, 0.5) or pick one.  Every view has a scale of its own.")
        self.scale.activated.connect(lambda _i: self.scale_edited())
        self.scale.lineEdit().editingFinished.connect(self.scale_edited)
        lay.addWidget(self.scale)
        self.target = ui_kit.note("")
        lay.addWidget(self.target)
        self.hint = ui_kit.note("")
        lay.addWidget(self.hint)
        lay.addStretch(1)
        self.refresh()

    def refresh(self):
        """The drawing changed: the list of models follows, and the style and the scale show the view they work on."""
        d = self.tab.d
        cur = self.current_model()
        self.models.blockSignals(True)
        self.models.clear()
        for m in d.models:
            it = QListWidgetItem(I.icon("dr_assembly" if m["kind"] == "assembly" else "dr_part", 18), m["name"])
            it.setData(Qt.ItemDataRole.UserRole, m["id"])
            self.models.addItem(it)
            if m["id"] == cur:
                self.models.setCurrentItem(it)
        if self.models.currentRow() < 0 and self.models.count():
            self.models.setCurrentRow(0)
        self.models.blockSignals(False)
        self.add_btn.setVisible(not self.tab.models_from_wires)
        self.sync_hint()
        self.show_view()

    def target_view(self):
        """The view that the style buttons and the scale field change now (None: the next view)."""
        return self.tab.panel_view("model")

    def show_view(self):
        """The style buttons and the scale field show the view they work on; with none, what the next view starts with."""
        v = self.target_view()
        self.busy = True
        try:
            style = v["style"] if v is not None else self.start_style
            for k, b in self.sbtn.items():
                b.setChecked(k == style)
            self.scale.lineEdit().setPlaceholderText(f"new views: {M.scale_text(self.tab.d.scale)}" if self.tab.d.views else "set by the first view")
            self.scale.setCurrentText(M.scale_text(v["scale"]) if v is not None else self.start_scale)
            self.target.setText(f"These change {v['name']}." if v is not None else "These set the style and the scale of the next view you put down.")
        finally:
            self.busy = False

    def current_model(self):
        it = self.models.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def current_style(self):
        for k, b in self.sbtn.items():
            if b.isChecked():
                return k
        return "hlv"

    def style_clicked(self, key):
        if self.busy:
            return
        self.start_style = key
        self.tab.panel_style("model", key)

    def scale_edited(self):
        if self.busy:
            return
        text = self.scale.currentText().strip()
        if self.target_view() is None:
            self.start_scale = text                                  # nothing to change: the next view starts at it (checked when the view is made)
            return
        if not text:
            self.show_view()
            return
        self.tab.panel_scale("model", text)
        self.show_view()                                             # a scale that is not a scale goes back to the view's own

    def sync_hint(self):
        if not self.tab.d.models:
            self.hint.setText("There is no part or assembly in the drawing yet. " + ("Wire one into this block in the Workbench." if self.tab.models_from_wires else "Add one from a file."))
        else:
            self.hint.setText("Pick an orientation, then click on the sheet to put the view down.  Click a view on the sheet to change its style or its scale here.")

    def pick_orientation(self, name):
        for n, b in self.obtn.items():
            b.setChecked(n == name)
        mid = self.current_model()
        if mid is None:
            self.obtn[name].setChecked(False)
            self.tab.status.say("Pick the part or assembly to show first.", "warn")
            return
        text = self.scale.currentText().strip()
        self.tab.start_model_view(mid, name, self.current_style(), text or None)

    def clear_pick(self):
        for b in self.obtn.values():
            b.setChecked(False)


# ---------------------------------------------------------------------------------------------------------------------------- Projected View
class ProjectedPanel(QWidget):
    """The Projected View PropertyManager: the style and the scale of the views put down by it.  They start as the parent's; the buttons and the scale field change the view just put
    down (or the one that is selected), and what is set here is what the next views start with."""
    TITLE = "Projected View"

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.busy = False
        self.start_style, self.start_scale = None, ""               # None: the parent's
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(ok_cancel(lambda: tab.finish_command(True), lambda: tab.finish_command(False)))
        t = QLabel(self.TITLE)
        t.setStyleSheet("font-weight:bold; font-size:13px; padding:4px 0;")
        lay.addWidget(t)
        lay.addWidget(section("Parent view"))
        self.parent_lbl = QLabel("")
        self.parent_lbl.setWordWrap(True)
        lay.addWidget(self.parent_lbl)
        lay.addWidget(section("Display Style"))
        row = QHBoxLayout()
        row.setSpacing(2)
        self.style = QButtonGroup(self)
        self.sbtn = {}
        for key, label in STYLE_BUTTONS:
            b = icon_button(I.STYLE_ICON[key], label, label.replace("\n", " "), 28)
            b.setMinimumWidth(58)
            b.setEnabled(key in M.STYLE_KEYS)
            if key in M.STYLE_KEYS:
                b.clicked.connect(lambda _c=False, k=key: self.style_clicked(k))
            self.style.addButton(b)
            self.sbtn[key] = b
            row.addWidget(b)
        self.style.setExclusive(True)
        lay.addLayout(row)
        self.same = QPushButton("Same as parent")
        self.same.setCheckable(True)
        self.same.setChecked(True)
        self.same.setToolTip("The style of the parent view (also for the views put down next)")
        self.same.clicked.connect(lambda _c=False: self.same_clicked())
        lay.addWidget(self.same)
        lay.addWidget(section("Scale"))
        self.scale = scale_combo()
        self.scale.setToolTip("The scale of this view: type it (1:2, 2:1, 0.5) or pick one.  Left empty, a new view takes the scale of its parent.")
        self.scale.activated.connect(lambda _i: self.scale_edited())
        self.scale.lineEdit().editingFinished.connect(self.scale_edited)
        lay.addWidget(self.scale)
        self.target = ui_kit.note("")
        lay.addWidget(self.target)
        self.hint = ui_kit.note("")
        lay.addWidget(self.hint)
        lay.addStretch(1)

    def style_choice(self):
        """The style of the next projected view (None: its parent's)."""
        return None if self.same.isChecked() else self.start_style

    def scale_choice(self):
        """The scale of the next projected view as a number (None: its parent's; a text that is not a scale counts as none)."""
        text = self.start_scale.strip()
        if not text:
            return None
        try:
            return M.parse_scale(text)
        except M.DrawingError:
            return None

    def target_view(self):
        return self.tab.panel_view("projected")

    def parent_view(self):
        return next((v for v in self.tab.d.views if v["id"] == self.tab.canvas.proj_parent), None)

    def set_parent(self, view):
        if view is None:
            self.parent_lbl.setText("Click the view on the sheet to project from.")
            self.hint.setText("")
            self.show_view()
            return
        self.parent_lbl.setText(f"{view['name']}  ({view['orient']}, {M.scale_text(view['scale'])})")
        self.hint.setText("Move the pointer to the side of the parent where the new view should go, then click.  Where you click it is put in line with the parent, and from then on it is a view of its own: move, scale, turn or change it as you like.")
        self.show_view(view)

    def show_view(self, parent=None):
        """The buttons and the scale field show the view they change; with none, what the next projected view starts with (its parent's unless set here)."""
        v = self.target_view()
        parent = parent or self.parent_view() or (next((x for x in self.tab.d.views if x["id"] == self.tab.canvas.sel), None) if v is None else None)
        self.busy = True
        try:
            if v is not None:
                style, scale = v["style"], M.scale_text(v["scale"])
            else:
                style = self.start_style if not self.same.isChecked() else (parent["style"] if parent is not None else None)
                scale = self.start_scale
            for k, b in self.sbtn.items():
                b.setChecked(k == style)
            self.scale.lineEdit().setPlaceholderText(f"like the parent: {M.scale_text(parent['scale'])}" if parent is not None else "like the parent")
            self.scale.setCurrentText(scale)
            self.target.setText(f"These change {v['name']}." if v is not None else "These set the style and the scale of the next view you put down.")
        finally:
            self.busy = False

    def style_clicked(self, key):
        if self.busy:
            return
        self.start_style = key
        self.busy = True
        self.same.setChecked(False)
        self.busy = False
        self.tab.panel_style("projected", key)

    def same_clicked(self):
        if self.busy:
            return
        if self.same.isChecked():
            self.tab.panel_style("projected", None)                   # the parent's style
        self.show_view()

    def scale_edited(self):
        if self.busy:
            return
        text = self.scale.currentText().strip()
        v = self.target_view()
        self.start_scale = text
        if v is not None and not text:
            self.show_view()
            return
        self.tab.panel_scale("projected", text)
        if v is not None:
            self.show_view()


# ---------------------------------------------------------------------------------------------------------------------------- the tools of the Annotation and Sketch pages

class FocusTextEdit(QPlainTextEdit):
    """A multi-line text box that says when the person has finished with it (it lost the focus): the text is then applied."""
    finished = pyqtSignal()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.finished.emit()


class PatternDirection(QWidget):
    """One direction of a note pattern: its angle (with Horizontal, Vertical and Pick line), the spacing between the notes and how many notes."""

    def __init__(self, panel, which):
        super().__init__()
        self.panel, self.which = panel, which
        f = QFormLayout(self)
        f.setContentsMargins(0, 0, 0, 0)
        self.angle = QDoubleSpinBox()
        self.angle.setRange(0.0, 359.99)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" °")
        self.angle.setWrapping(True)
        self.angle.setToolTip("The direction, counter-clockwise from the right-hand side of the sheet.")
        self.space = QDoubleSpinBox()
        self.space.setRange(-2000.0, 2000.0)
        self.space.setDecimals(2)
        self.space.setSuffix(" mm")
        self.space.setToolTip("From a note to the next one (corner to corner).  A negative spacing goes the other way.")
        self.count = QSpinBox()
        self.count.setRange(1, IT.MAX_COPIES)
        self.count.setToolTip("The notes in this direction, the first one included.")
        row = QHBoxLayout()
        self.horiz = QPushButton("Horizontal")
        self.vert = QPushButton("Vertical")
        self.pick = QPushButton("Pick line")
        self.pick.setCheckable(True)
        self.pick.setToolTip("Then click a line of a view: the notes follow its direction.")
        for b in (self.horiz, self.vert, self.pick):
            b.setAutoDefault(False)
            row.addWidget(b)
        f.addRow(row)
        f.addRow("Angle", self.angle)
        f.addRow("Spacing", self.space)
        f.addRow("Notes", self.count)
        self.horiz.clicked.connect(lambda _c=False: self.set_angle(0.0))
        self.vert.clicked.connect(lambda _c=False: self.set_angle(90.0))
        self.pick.toggled.connect(lambda on: panel.pattern_pick_line(which, on))
        for w in (self.angle, self.space, self.count):
            w.editingFinished.connect(lambda: panel.pattern_edited(which))
        self.count.valueChanged.connect(lambda _v: panel.pattern_edited(which))

    def set_angle(self, a):
        self.angle.setValue(a)
        self.panel.pattern_edited(self.which)

    def show_values(self, a, s, c):
        for w, v in ((self.angle, a), (self.space, s), (self.count, c)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)

    def values(self):
        return self.angle.value(), self.space.value(), self.count.value()


class ToolPanel(QWidget):
    """The PropertyManager of a tool: a title, what to click, the options of the tool, and OK (leave the tool)."""
    TITLES = {"dim": "Dimension", "center_mark": "Center Mark", "centerline": "Centerline", "note": "Note", "balloon": "Balloon", "note_pattern": "Linear Note Pattern",
              "line": "Line", "rect": "Rectangle", "circle": "Circle", "arc": "Arc"}
    HELP = {"dim": ["Pick the type first.", "Horizontal, Vertical, Length: a line or two points.", "Diameter, Radius: a circle or an arc.", "Angle: two lines that meet."],
            "center_mark": ["Click a circle or an arc (or its centre point): a cross is put on it."],
            "centerline": ["Click two parallel lines: a dash-dot line is put midway between them."],
            "note": ["Type the text, choose its size and a leader.", "Without a leader: click where the text goes.", "With a leader: click what it points at, then where the text goes."],
            "balloon": ["Click the edge or the face of a view that the balloon points at, then where the circle goes.", "The number counts on by itself."],
            "note_pattern": ["Click the note to repeat.", "Set the direction, the spacing and how many notes in each direction.", "Direction 2 is a second row: leave it at 1 note for a single row."],
            "line": ["Click the start, then the end.  The next click carries on from the end."], "rect": ["Click one corner, then the opposite corner."],
            "circle": ["Click the centre, then a point on the circle."], "arc": ["Click the centre, the start, then the end.  The arc runs counter-clockwise from the start."]}
    AFTER = {"dim": "After the picks, move the pointer to where the dimension should go and click.  What it measures is the type you picked, wherever you put it.  Drag a dimension later to move it; the number is always the model's, whatever the scale.",
             "center_mark": "Pick as many as you like, then OK.", "centerline": "Pick pairs of lines, one pair after another, then OK.",
             "note": "Double-click a note later to change its text.  Drag the square at the end of its leader to point it somewhere else.",
             "balloon": "Drag the square at the end of the leader to point it at something else.  Double-click a balloon to change its number.",
             "note_pattern": "The first note is the one you clicked; the others are copies of it, so changing its text changes them all.  A negative spacing goes the other way.",
             "line": "Points snap to the corners of the views and to the ends of what is drawn.  Drag the squares on a selected line to change it.",
             "rect": "Points snap to the corners of the views and to the ends of what is drawn.  Drag the squares on a selected rectangle to change it.",
             "circle": "Points snap to the corners of the views and to the ends of what is drawn.  Drag the squares on a selected circle to change it.",
             "arc": "Points snap to the corners of the views and to the ends of what is drawn.  Drag the squares on a selected arc to change it."}

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.name = "dim"
        self.busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(ok_cancel(lambda: tab.finish_tool(), lambda: tab.finish_tool()))
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight:bold; font-size:13px; padding:4px 0;")
        lay.addWidget(self.title)
        # ---- the type of a dimension (the ones of the Part sketcher's Dimension menu)
        self.opt_dim = QWidget()
        dl = QVBoxLayout(self.opt_dim)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(section("Type"))
        dgrid = QGridLayout()
        dgrid.setSpacing(2)
        self.dim_btn = {}
        for i, (key, label) in enumerate(A.DIM_TYPES):
            b = icon_button(DIM_ICON[key], label.replace(" / ", "\n"), label, 26)
            b.clicked.connect(lambda _c=False, k=key: self.dim_type_clicked(k))
            dgrid.addWidget(b, i // 3, i % 3)
            b.setMinimumWidth(60)
            self.dim_btn[key] = b
        dl.addLayout(dgrid)
        lay.addWidget(self.opt_dim)
        # ---- the options of a note
        self.opt_note = QWidget()
        nl = QVBoxLayout(self.opt_note)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.addWidget(section("Text"))
        self.n_text = QPlainTextEdit()
        self.n_text.setFixedHeight(76)
        self.n_text.setPlaceholderText("Type the note here")
        self.n_text.textChanged.connect(self.options_edited)
        nl.addWidget(self.n_text)
        nf = QFormLayout()
        self.n_size = QComboBox()
        self.n_size.setEditable(True)
        for pt in IT.NOTE_SIZES:
            self.n_size.addItem(str(pt), float(pt))
        self.n_size.activated.connect(lambda _i: self.options_edited())
        self.n_size.lineEdit().editingFinished.connect(self.options_edited)
        self.n_size.setToolTip("Font size in points.  14 is the height of the numbers of a dimension.")
        self.n_leader = QComboBox()
        self.n_leader.addItem("No leader", None)
        self.n_leader.addItem("Straight leader", "straight")
        self.n_leader.addItem("Bent leader", "bent")
        self.n_leader.activated.connect(lambda _i: self.options_edited())
        nf.addRow("Size (pt)", self.n_size)
        nf.addRow("Leader", self.n_leader)
        nl.addLayout(nf)
        lay.addWidget(self.opt_note)
        # ---- the options of a balloon
        self.opt_balloon = QWidget()
        bf = QFormLayout(self.opt_balloon)
        bf.setContentsMargins(0, 0, 0, 0)
        self.b_text = QLineEdit()
        self.b_text.setToolTip("The number in the next balloon.  It counts on after each one.")
        self.b_text.textChanged.connect(self.options_edited)
        bf.addRow("Next number", self.b_text)
        lay.addWidget(self.opt_balloon)
        # ---- the options of a note pattern
        self.opt_pattern = QWidget()
        pl = QVBoxLayout(self.opt_pattern)
        pl.setContentsMargins(0, 0, 0, 0)
        self.p_note = QLabel("")
        self.p_note.setWordWrap(True)
        pl.addWidget(self.p_note)
        self.p_dir = {}
        for which, title in ((1, "Direction 1"), (2, "Direction 2")):
            pl.addWidget(section(title))
            self.p_dir[which] = box = PatternDirection(self, which)
            pl.addWidget(box)
        self.p_remove = QPushButton("Remove the pattern")
        self.p_remove.setToolTip("The note stays; its copies go away.")
        self.p_remove.clicked.connect(lambda _c=False: self.pattern_removed())
        pl.addWidget(self.p_remove)
        lay.addWidget(self.opt_pattern)
        for w in (self.opt_dim, self.opt_note, self.opt_balloon, self.opt_pattern):
            w.setVisible(False)                                   # set_tool shows the options of the tool that opens; the panel is not as tall as all of them together before that
        lay.addWidget(section("What to click"))
        self.what = QLabel("")
        self.what.setWordWrap(True)
        lay.addWidget(self.what)
        self.after = ui_kit.note("")
        lay.addWidget(self.after)
        lay.addStretch(1)
        tab.canvas.options_changed.connect(self.sync)

    def set_tool(self, name):
        self.name = name
        self.title.setText(self.TITLES.get(name, name))
        self.what.setText("\n".join("•  " + t for t in self.HELP.get(name, [])))
        self.after.setText(self.AFTER.get(name, ""))
        self.opt_dim.setVisible(name == "dim")
        self.opt_note.setVisible(name == "note")
        self.opt_balloon.setVisible(name == "balloon")
        self.opt_pattern.setVisible(name == "note_pattern")
        self.sync()

    def sync(self):
        """The canvas's options into the boxes (the next balloon number moves on by itself)."""
        o = self.tab.canvas.opts
        self.busy = True
        try:
            if self.n_text.toPlainText() != o.get("text", ""):
                self.n_text.setPlainText(o.get("text", ""))
            self.n_size.setEditText(A.number_text(o.get("size", IT.NOTE_SIZE), 2))
            self.n_leader.setCurrentIndex(max(0, self.n_leader.findData(o.get("leader"))))
            if self.b_text.text() != o.get("balloon", ""):
                self.b_text.setText(o.get("balloon", ""))
            self.sync_pattern()
            for k, b in self.dim_btn.items():
                b.setChecked(self.tab.canvas.dim_type == k)
        finally:
            self.busy = False

    def dim_type_clicked(self, key):
        if self.busy:
            return
        self.tab.canvas.set_dim_type(key)
        self.tab.canvas.setFocus()
        self.sync()

    def pattern_note(self):
        """The note the pattern tool is working on, or None."""
        aid = self.tab.canvas.pattern_note
        if aid is None:
            return None
        try:
            n = self.tab.d.annot(aid)
        except M.DrawingError:
            return None
        return n if n.get("type") == "note" else None

    def sync_pattern(self):
        n = self.pattern_note()
        pat = (n or {}).get("pattern")
        self.p_note.setText("Click the note to repeat." if n is None else "Note:  " + IT.label(n))
        for which, box in self.p_dir.items():
            box.setEnabled(bool(pat))
            if pat:
                box.show_values(pat["a%d" % which], pat["s%d" % which], pat["c%d" % which])
        self.p_remove.setEnabled(bool(pat))
        for which, box in self.p_dir.items():
            box.pick.setChecked(self.tab.canvas.pattern_pick == which)

    def pattern_edited(self, which):
        """A box of direction `which` was changed: the whole pattern is set from the boxes of that direction."""
        if self.busy:
            return
        n = self.pattern_note()
        if n is None:
            return
        a, s, c = self.p_dir[which].values()
        self.tab.set_note_pattern(n["id"], **{"a%d" % which: a, "s%d" % which: s, "c%d" % which: c})

    def pattern_pick_line(self, which, on):
        """Pick line: the next click on a line of a view gives the direction."""
        cv = self.tab.canvas
        if self.busy or self.pattern_note() is None:
            return
        cv.pattern_pick = which if on else 0
        cv.options_changed.emit()
        cv.hint.emit(cv._tool_hint("note_pattern"))
        cv.setFocus()
        cv.update()

    def pattern_removed(self):
        n = self.pattern_note()
        if n is not None:
            self.tab.set_note_pattern(n["id"], remove=True)

    def options_edited(self):
        if self.busy:
            return
        o = self.tab.canvas.opts
        o["text"] = self.n_text.toPlainText()
        try:
            o["size"] = IT.clean_size(float(self.n_size.currentText().replace(",", ".")))
        except ValueError:
            pass
        o["leader"] = self.n_leader.currentData()
        o["balloon"] = self.b_text.text()
        if self.name == "note":
            self.tab.canvas.hint.emit(self.tab.canvas._tool_hint("note"))


ANNOT_LABEL = {"linear": "Dimension", "diameter": "Diameter", "radius": "Radius", "angle": "Angle", "center_mark": "Center Mark", "centerline": "Centerline", "note": "Note", "balloon": "Balloon",
               "line": "Line", "rect": "Rectangle", "circle": "Circle", "arc": "Arc"}
ANNOT_ICON = {"linear": "dr_dim", "diameter": "dr_dim_dia", "radius": "dr_dim_rad", "angle": "dr_dim_ang", "center_mark": "dr_center_mark", "centerline": "dr_centerline", "note": "dr_note",
              "balloon": "dr_balloon", "line": "dr_draw_line", "rect": "dr_draw_rect", "circle": "dr_draw_circle", "arc": "dr_draw_arc"}


def annot_label(a):
    """What an item is called: a linear dimension by what the person chose to measure (Horizontal, Vertical, Length / distance), the rest by its type."""
    if a.get("type") == "linear":
        return {"h": "Horizontal", "v": "Vertical"}.get(a.get("mode"), "Length / distance")
    return ANNOT_LABEL.get(a.get("type"), "Dimension")


def annot_icon(a):
    if a.get("type") == "linear":
        return DIM_ICON.get(a.get("mode") or "a", "dr_dim")
    return ANNOT_ICON.get(a.get("type"), "dr_dim")


def annot_text(a, fmt=None):
    """How an item reads in the Outline: 'Diameter  ⌀6', 'Center Mark', 'Balloon  3', the first line of a note, 'Line', '... (lost)'."""
    if a.get("type") in ("note", "balloon") + IT.DRAW_TYPES:
        return IT.label(a)
    t = annot_label(a)
    if a.get("type") in ("linear", "diameter", "radius", "angle"):
        try:
            t += "   " + A.text(a, fmt)
        except (KeyError, ValueError, IndexError, ZeroDivisionError):
            pass
    return t + ("   (lost)" if a.get("lost") else "")


# ---------------------------------------------------------------------------------------------------------------------------- Outline and Details
class OutlinePanel(QWidget):
    """The tree of the drawing and the Details of the selected item (sheet, model, view)."""

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.currentItemChanged.connect(self.tree_selected)
        split.addWidget(self.tree)
        self.details = QStackedWidget()
        self.details.addWidget(self._page_none())
        self.details.addWidget(self._page_sheet())
        self.details.addWidget(self._page_model())
        self.details.addWidget(self._page_view())
        self.details.addWidget(self._page_annot())
        self.details.addWidget(self._page_note())
        self.details.addWidget(self._page_balloon())
        self.details.addWidget(self._page_item())
        split.addWidget(self.details)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split)
        self.rebuild()

    # ---- the Details pages
    def _wrap(self, title):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 6, 8, 6)
        t = QLabel(title)
        t.setStyleSheet("font-weight:600; color:#1a56c4; padding-bottom:4px;")
        lay.addWidget(t)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(form)
        lay.addStretch(1)
        return w, form, lay

    def _page_none(self):
        w, _f, lay = self._wrap("Details")
        lay.insertWidget(1, ui_kit.note("Pick the sheet, a model or a view in the tree (or click a view on the sheet) to see and change its details."))
        return w

    def _page_sheet(self):
        w, f, _lay = self._wrap("Sheet")
        self.sh_size = QComboBox()
        for key, label, _w, _h in S.SIZES:
            self.sh_size.addItem(label, key)
        ui_kit.tame_combo(self.sh_size, 18)
        self.sh_land = QComboBox()
        self.sh_land.addItem("Landscape", True)
        self.sh_land.addItem("Portrait", False)
        self.sh_proj = QComboBox()
        self.sh_proj.addItem("Third angle", False)
        self.sh_proj.addItem("First angle", True)
        for c in (self.sh_size, self.sh_land, self.sh_proj):
            c.activated.connect(lambda _i: self.sheet_edited())
        f.addRow("Size", self.sh_size)
        f.addRow("Direction", self.sh_land)
        f.addRow("Projection", self.sh_proj)
        return w

    def _page_model(self):
        w, f, lay = self._wrap("Model")
        self.m_name = QLabel("")
        self.m_kind = QLabel("")
        self.m_src = QLabel("")
        self.m_src.setWordWrap(True)
        self.m_views = QLabel("")
        f.addRow("Name", self.m_name)
        f.addRow("Kind", self.m_kind)
        f.addRow("Comes from", self.m_src)
        f.addRow("Views", self.m_views)
        self.m_remove = QPushButton("Remove model and its views")
        self.m_remove.clicked.connect(lambda _c=False: self.tab.remove_model(self.cur_id))
        lay.insertWidget(2, self.m_remove)
        return w

    def _page_view(self):
        w, f, lay = self._wrap("View")
        self.v_name = QLineEdit()
        self.v_name.editingFinished.connect(self.view_renamed)
        self.v_model = QLabel("")
        self.v_orient = QComboBox()
        for n in P.ORIENTATIONS:
            self.v_orient.addItem(I.icon(I.ORIENT_ICON[n], 18), n, n)
        self.v_orient.activated.connect(lambda _i: self.tab.set_view_orient(self.cur_id, self.v_orient.currentData()))
        self.v_turn = QLabel("")                                  # how the view is turned on the sheet (DRW-1)
        self.v_turn.setWordWrap(True)
        self.v_turn_l = QPushButton("Turn left 90\u00b0")
        self.v_turn_l.setToolTip("Turn the picture of this view 90 degrees to the left on the sheet, like a sheet of paper.  The dimensions and notes of the view turn with it.")
        self.v_turn_l.clicked.connect(lambda _c=False: self.tab.turn_view(self.cur_id, 1))
        self.v_turn_r = QPushButton("Turn right 90\u00b0")
        self.v_turn_r.setToolTip("Turn the picture of this view 90 degrees to the right on the sheet, like a sheet of paper.  The dimensions and notes of the view turn with it.")
        self.v_turn_r.clicked.connect(lambda _c=False: self.tab.turn_view(self.cur_id, -1))
        self.v_style = QComboBox()
        for k, label in M.STYLES:
            self.v_style.addItem(I.icon(I.STYLE_ICON[k], 18), label, k)
        ui_kit.tame_combo(self.v_style, 18)
        self.v_style.activated.connect(lambda _i: self.tab.set_view_style(self.cur_id, self.v_style.currentData()))
        self.v_scale = scale_combo()
        self.v_scale.activated.connect(lambda _i: self.scale_edited())
        self.v_scale.lineEdit().editingFinished.connect(self.scale_edited)
        f.addRow("Name", self.v_name)
        f.addRow("Model", self.v_model)
        f.addRow("Orientation", self.v_orient)
        trow = QWidget()
        tl = QHBoxLayout(trow)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.v_turn_l)
        tl.addWidget(self.v_turn_r)
        f.addRow("Turn", trow)
        f.addRow("", self.v_turn)
        f.addRow("Style", self.v_style)
        f.addRow("Scale", self.v_scale)
        self.v_del = QPushButton("Delete view")
        self.v_del.clicked.connect(lambda _c=False: self.tab.delete_view(self.cur_id))
        lay.insertWidget(2, self.v_del)
        self.v_form = f
        return w

    def _page_annot(self):
        w, f, lay = self._wrap("Dimension")
        self.a_type = QLabel("")
        self.a_value = QLabel("")
        self.a_view = QLabel("")
        self.a_state = QLabel("")
        self.a_state.setWordWrap(True)
        f.addRow("Kind", self.a_type)
        f.addRow("Says", self.a_value)
        f.addRow("On", self.a_view)
        f.addRow("", self.a_state)
        self.a_del = QPushButton("Delete")
        self.a_del.clicked.connect(lambda _c=False: self.tab.delete_annot(self.cur_id))
        lay.insertWidget(2, self.a_del)
        return w

    def _page_note(self):
        w, f, lay = self._wrap("Note")
        self.n_text = FocusTextEdit()
        self.n_text.setFixedHeight(90)
        self.n_text.finished.connect(self.note_edited)
        self.n_size = QComboBox()
        self.n_size.setEditable(True)
        for pt in IT.NOTE_SIZES:
            self.n_size.addItem(str(pt), float(pt))
        self.n_size.activated.connect(lambda _i: self.note_edited())
        self.n_size.lineEdit().editingFinished.connect(self.note_edited)
        self.n_leader = QComboBox()
        self.n_leader.addItem("No leader", None)
        self.n_leader.addItem("Straight leader", "straight")
        self.n_leader.addItem("Bent leader", "bent")
        self.n_leader.activated.connect(lambda _i: self.note_edited())
        f.addRow("Text", self.n_text)
        f.addRow("Size (pt)", self.n_size)
        f.addRow("Leader", self.n_leader)
        self.n_pat = QLabel("")
        self.n_pat.setWordWrap(True)
        f.addRow("Pattern", self.n_pat)
        prow = QHBoxLayout()
        self.n_pat_edit = QPushButton("Repeat...")
        self.n_pat_edit.clicked.connect(lambda _c=False: self.tab.start_tool("note_pattern"))
        self.n_pat_off = QPushButton("Remove pattern")
        self.n_pat_off.clicked.connect(lambda _c=False: self.tab.set_note_pattern(self.cur_id, remove=True))
        prow.addWidget(self.n_pat_edit)
        prow.addWidget(self.n_pat_off)
        f.addRow(prow)
        self.n_del = QPushButton("Delete")
        self.n_del.clicked.connect(lambda _c=False: self.tab.delete_annot(self.cur_id))
        lay.insertWidget(2, self.n_del)
        return w

    def _page_balloon(self):
        w, f, lay = self._wrap("Balloon")
        self.bl_text = QLineEdit()
        self.bl_text.editingFinished.connect(self.balloon_edited)
        self.bl_view = QLabel("")
        f.addRow("Number", self.bl_text)
        f.addRow("On", self.bl_view)
        self.bl_del = QPushButton("Delete")
        self.bl_del.clicked.connect(lambda _c=False: self.tab.delete_annot(self.cur_id))
        lay.insertWidget(2, self.bl_del)
        return w

    def _page_item(self):
        w, f, lay = self._wrap("Drawn on the sheet")
        self.i_type = QLabel("")
        self.i_size = QLabel("")
        f.addRow("Kind", self.i_type)
        f.addRow("Size (mm)", self.i_size)
        lay.insertWidget(1, ui_kit.note("Drag the squares on it to change it; drag the line itself to move it."))
        self.i_del = QPushButton("Delete")
        self.i_del.clicked.connect(lambda _c=False: self.tab.delete_annot(self.cur_id))
        lay.insertWidget(3, self.i_del)
        return w

    # ---- the tree
    cur_kind, cur_id = "none", None

    def rebuild(self):
        d = self.tab.d
        self.busy = True
        keep = ("view", self.tab.canvas.sel) if self.tab.canvas.sel else ("annot", self.tab.canvas.sel_annot) if self.tab.canvas.sel_annot else (self.cur_kind, self.cur_id)
        self.tree.clear()
        w, h = d.sheet_dims()
        root = QTreeWidgetItem([f"Sheet1   {S.size(d.sheet['size'])[1].split('  ')[0]}, {'landscape' if d.sheet['landscape'] else 'portrait'}"])
        root.setIcon(0, I.icon("dr_sheet", 18))
        root.setData(0, Qt.ItemDataRole.UserRole, ("sheet", None))
        self.tree.addTopLevelItem(root)
        mroot = QTreeWidgetItem(root, ["Models"])
        mroot.setIcon(0, I.icon("dr_part", 18))
        mroot.setData(0, Qt.ItemDataRole.UserRole, ("folder", None))
        for m in d.models:
            it = QTreeWidgetItem(mroot, [m["name"]])
            it.setIcon(0, I.icon("dr_assembly" if m["kind"] == "assembly" else "dr_part", 18))
            it.setData(0, Qt.ItemDataRole.UserRole, ("model", m["id"]))
        vroot = QTreeWidgetItem(root, ["Views"])
        vroot.setIcon(0, I.icon("dr_view", 18))
        vroot.setData(0, Qt.ItemDataRole.UserRole, ("folder", None))
        items, aitems = {}, {}

        def add(v, parent):
            turned = M.TURN_TEXT[int(v.get("turn", 0)) % 4]
            it = QTreeWidgetItem(parent, [f"{v['name']}   {v['orient']}, {M.scale_text(v['scale'])}" + (f", {turned}" if turned else "")])
            it.setIcon(0, I.icon(I.ORIENT_ICON.get(v["orient"], "dr_view"), 18))
            it.setData(0, Qt.ItemDataRole.UserRole, ("view", v["id"]))
            items[v["id"]] = it
            for a in d.view_items(v["id"]):
                at = QTreeWidgetItem(it, [annot_text(a, self.tab.canvas.r.fmt)])
                at.setIcon(0, I.icon(annot_icon(a), 18))
                at.setData(0, Qt.ItemDataRole.UserRole, ("annot", a["id"]))
                aitems[a["id"]] = at
        for v in d.views:
            add(v, vroot)                                          # (a view projected from another is a view of its own: no nesting)
        for title, icon, recs in (("Notes", "dr_note", d.notes), ("Drawn on the sheet", "dr_draw_line", d.lines)):
            if not recs:
                continue
            folder = QTreeWidgetItem(root, [title])
            folder.setIcon(0, I.icon(icon, 18))
            folder.setData(0, Qt.ItemDataRole.UserRole, ("folder", None))
            for a in recs:
                at = QTreeWidgetItem(folder, [annot_text(a, self.tab.canvas.r.fmt)])
                at.setIcon(0, I.icon(annot_icon(a), 18))
                at.setData(0, Qt.ItemDataRole.UserRole, ("annot", a["id"]))
                aitems[a["id"]] = at
        self.tree.expandAll()
        target = None
        if keep[0] == "view" and keep[1] in items:
            target = items[keep[1]]
        elif keep[0] == "annot" and keep[1] in aitems:
            target = aitems[keep[1]]
        elif keep[0] == "model":
            target = next((mroot.child(i) for i in range(mroot.childCount()) if mroot.child(i).data(0, Qt.ItemDataRole.UserRole)[1] == keep[1]), None)
        elif keep[0] == "sheet":
            target = root
        self.items, self.aitems = items, aitems
        if target is not None:
            self.tree.setCurrentItem(target)
            self.cur_kind, self.cur_id = keep
        else:
            self.tree.setCurrentItem(None)
            self.cur_kind, self.cur_id = "none", None
        self.busy = False
        self.show_details()

    def tree_selected(self, cur, _prev):
        if self.busy:
            return
        kind, ident = cur.data(0, Qt.ItemDataRole.UserRole) if cur is not None else ("none", None)
        self.cur_kind, self.cur_id = kind, ident
        if kind == "view":
            self.tab.canvas.set_selected(ident, emit=False)
        elif kind == "annot":
            self.tab.canvas.set_selected_annot(ident, emit=False)
        else:
            self.tab.canvas.set_selected(None, emit=False)
            self.tab.canvas.set_selected_annot(None, emit=False)
        self.show_details()

    def select_view(self, vid):
        """The sheet selected a view (or none): the tree follows."""
        if self.busy:
            return
        it = getattr(self, "items", {}).get(vid) if vid else None
        self.busy = True
        if it is not None:
            self.tree.setCurrentItem(it)
            self.cur_kind, self.cur_id = "view", vid
        else:
            if self.cur_kind == "view":
                self.tree.setCurrentItem(None)
                self.cur_kind, self.cur_id = "none", None
        self.busy = False
        self.show_details()

    def select_annot(self, aid):
        """The sheet selected a dimension / mark (or none): the tree follows."""
        if self.busy:
            return
        it = getattr(self, "aitems", {}).get(aid) if aid else None
        self.busy = True
        if it is not None:
            self.tree.setCurrentItem(it)
            self.cur_kind, self.cur_id = "annot", aid
        elif self.cur_kind == "annot":
            self.tree.setCurrentItem(None)
            self.cur_kind, self.cur_id = "none", None
        self.busy = False
        self.show_details()

    def set_orient_item(self, orient):
        """The orientation box shows the standard orientation of the view; a view that looks along none of them (one projected from an Isometric view) shows "Custom" as a last item
        that is there only while it is selected."""
        n = len(P.ORIENTATIONS)
        while self.v_orient.count() > n:
            self.v_orient.removeItem(self.v_orient.count() - 1)
        if orient not in P.ORIENTATIONS:
            self.v_orient.addItem(I.icon("dr_view", 18), M.CUSTOM, M.CUSTOM)
        self.v_orient.setCurrentIndex(max(0, self.v_orient.findData(orient)))

    def show_details(self):
        d = self.tab.d
        k = self.cur_kind
        self.busy = True
        try:
            if k == "sheet":
                self.sh_size.setCurrentIndex(max(0, self.sh_size.findData(d.sheet["size"])))
                self.sh_land.setCurrentIndex(0 if d.sheet["landscape"] else 1)
                self.sh_proj.setCurrentIndex(1 if d.sheet["first_angle"] else 0)
                self.details.setCurrentIndex(1)
            elif k == "model":
                m = d.model(self.cur_id)
                self.m_name.setText(m["name"])
                self.m_kind.setText("Assembly" if m["kind"] == "assembly" else "Part")
                self.m_src.setText(self.tab.source_text(m))
                n = len([v for v in d.views if v["model"] == m["id"]])
                self.m_views.setText(f"{n} view{'s' if n != 1 else ''}")
                self.m_remove.setVisible(not self.tab.models_from_wires)
                self.details.setCurrentIndex(2)
            elif k == "view":
                v = d.view(self.cur_id)
                self.v_name.setText(v["name"])
                self.v_model.setText(d.model(v["model"])["name"])
                self.set_orient_item(v["orient"])
                tt = M.TURN_TEXT[int(v.get("turn", 0)) % 4]
                self.v_turn.setText(f"This view is {tt}." if tt else "")
                self.v_turn.setVisible(bool(tt))
                self.v_turn_l.setEnabled(v["kind"] == "model")
                self.v_turn_r.setEnabled(v["kind"] == "model")
                self.v_style.setCurrentIndex(max(0, self.v_style.findData(v["style"])))
                self.v_scale.setCurrentText(M.scale_text(v["scale"]))
                self.details.setCurrentIndex(3)
            elif k == "annot" and d.annot(self.cur_id).get("type") == "note":
                a = d.annot(self.cur_id)
                if self.n_text.toPlainText() != a["text"]:
                    self.n_text.setPlainText(a["text"])
                self.n_size.setEditText(A.number_text(a.get("size", IT.NOTE_SIZE), 2))
                self.n_leader.setCurrentIndex(max(0, self.n_leader.findData((a.get("leader") or {}).get("kind"))))
                pat = a.get("pattern")
                self.n_pat.setText("none" if not pat else IT.pattern_text(pat))
                self.n_pat_edit.setText("Edit pattern..." if pat else "Repeat...")
                self.n_pat_off.setVisible(bool(pat))
                self.details.setCurrentIndex(5)
            elif k == "annot" and d.annot(self.cur_id).get("type") == "balloon":
                a = d.annot(self.cur_id)
                self.bl_text.setText(a["text"])
                try:
                    self.bl_view.setText(d.view(a["view"])["name"])
                except M.DrawingError:
                    self.bl_view.setText("-")
                self.details.setCurrentIndex(6)
            elif k == "annot" and d.annot(self.cur_id).get("type") in IT.DRAW_TYPES:
                a = d.annot(self.cur_id)
                self.i_type.setText(ANNOT_LABEL[a["type"]])
                self.i_size.setText(IT.describe(a))
                self.details.setCurrentIndex(7)
            elif k == "annot":
                a = d.annot(self.cur_id)
                self.a_type.setText(annot_label(a))
                self.a_value.setText(A.text(a, self.tab.canvas.r.fmt) if a["type"] in ("linear", "diameter", "radius", "angle") else "-")
                self.a_view.setText(d.view(a["view"])["name"])
                self.a_state.setText("Its geometry is not in the model any more.  Delete it, or change the model back." if a.get("lost") else "")
                self.a_state.setStyleSheet("color:#c0392b;")
                self.details.setCurrentIndex(4)
            else:
                self.details.setCurrentIndex(0)
        except M.DrawingError:
            self.details.setCurrentIndex(0)
        self.busy = False

    # ---- edits
    def sheet_edited(self):
        if self.busy:
            return
        self.tab.set_sheet(self.sh_size.currentData(), self.sh_land.currentData(), self.sh_proj.currentData())

    def note_edited(self):
        if self.busy or self.cur_kind != "annot":
            return
        try:
            size = float(self.n_size.currentText().replace(",", "."))
        except ValueError:
            size = None
        self.tab.set_note(self.cur_id, self.n_text.toPlainText(), size, self.n_leader.currentData())

    def balloon_edited(self):
        if self.busy or self.cur_kind != "annot":
            return
        self.tab.set_balloon_text(self.cur_id, self.bl_text.text())

    def view_renamed(self):
        if self.busy or self.cur_kind != "view":
            return
        self.tab.rename_view(self.cur_id, self.v_name.text())

    def scale_edited(self):
        if self.busy or self.cur_kind != "view":
            return
        self.tab.set_view_scale(self.cur_id, self.v_scale.currentText())
