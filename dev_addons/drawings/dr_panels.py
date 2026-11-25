"""dr_panels.py - the panels of the Drawings window.

    NewDrawingDialog(sheet)       the first thing a new drawing asks: the sheet (standard sizes only, landscape or portrait, a preview) and the kind of projection
    ModelViewPanel(tab)           Model View: the models, the nine orientations, the display style, the scale; picking an orientation lets the view follow the pointer to the sheet
    ProjectedPanel(tab)           Projected View: the view to project from, the display style; the pointer picks the side
    ToolPanel(tab)                Smart Dimension / Center Mark / Centerline / Note / Balloon / Line / Rectangle / Circle / Arc: what to click, the options of the tool (a note's text, size
                                  and leader; the number of the next balloon), and ✔ OK to leave the tool
    OutlinePanel(tab)             the tree of the drawing (sheet, models, views and what is drawn on each, the notes, what is drawn on the sheet) with the Details of the selected item below it

A panel never changes the document itself: it asks the tab (dr_tab.DrawingTab), which keeps the undo and the dirty mark.
"""
from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import dr_annot as A
import dr_icons as I
import dr_items as IT
import dr_model as M
import dr_proj as P
import dr_sheet as S
import ui_kit

STYLE_BUTTONS = [("wireframe", "Wireframe"), ("hlv", "Hidden Lines\nVisible"), ("hlr", "Hidden Lines\nRemoved"), ("shaded_edges", "Shaded With\nEdges"), ("shaded", "Shaded")]
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
    cb.setCurrentIndex(-1)                                   # nothing picked: a new view takes the sheet scale
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
            self.style.addButton(b)
            self.sbtn[key] = b
            row.addWidget(b)
        self.style.setExclusive(True)
        self.sbtn["hlv"].setChecked(True)
        lay.addLayout(row)
        lay.addWidget(section("Scale"))
        self.scale = scale_combo()
        self.scale.setToolTip("Leave on the sheet scale, or type / pick a scale for this view")
        lay.addWidget(self.scale)
        self.hint = ui_kit.note("")
        lay.addWidget(self.hint)
        lay.addStretch(1)
        self.refresh()

    def refresh(self):
        """The drawing changed: the list of models and the sheet scale follow."""
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
        self.scale.setPlaceholderText("")
        if d.views:
            self.scale.lineEdit().setPlaceholderText(f"sheet scale {M.scale_text(d.scale)}")
        self.sync_hint()

    def current_model(self):
        it = self.models.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def current_style(self):
        for k, b in self.sbtn.items():
            if b.isChecked():
                return k
        return "hlv"

    def sync_hint(self):
        if not self.tab.d.models:
            self.hint.setText("There is no part or assembly in the drawing yet. " + ("Wire one into this block in the Workbench." if self.tab.models_from_wires else "Add one from a file."))
        else:
            self.hint.setText("Pick an orientation, then click on the sheet to put the view down.")

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
    TITLE = "Projected View"

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
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
            self.style.addButton(b)
            self.sbtn[key] = b
            row.addWidget(b)
        self.style.setExclusive(True)
        lay.addLayout(row)
        self.same = QPushButton("Same as parent")
        self.same.setCheckable(True)
        self.same.setChecked(True)
        self.same.toggled.connect(lambda on: [b.setEnabled(not on and k in M.STYLE_KEYS) for k, b in self.sbtn.items()])
        lay.addWidget(self.same)
        for b in self.sbtn.values():
            b.setEnabled(False)
        lay.addWidget(section("Scale"))
        lay.addWidget(QLabel("The scale of the parent view."))
        self.hint = ui_kit.note("")
        lay.addWidget(self.hint)
        lay.addStretch(1)

    def style_choice(self):
        if self.same.isChecked():
            return None
        for k, b in self.sbtn.items():
            if b.isChecked():
                return k
        return None

    def set_parent(self, view):
        if view is None:
            self.parent_lbl.setText("Click the view on the sheet to project from.")
            self.hint.setText("")
            return
        self.parent_lbl.setText(f"{view['name']}  ({view['orient']}, {M.scale_text(view['scale'])})")
        self.hint.setText("Move the pointer to the side of the parent where the new view should go, then click.  The view stays aligned with its parent: it only slides along its axis.")
        if self.same.isChecked():
            k = view["style"]
            if k in self.sbtn:
                self.sbtn[k].setChecked(True)


# ---------------------------------------------------------------------------------------------------------------------------- the tools of the Annotation and Sketch pages
class FocusTextEdit(QPlainTextEdit):
    """A multi-line text box that says when the person has finished with it (it lost the focus): the text is then applied."""
    finished = pyqtSignal()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.finished.emit()


class ToolPanel(QWidget):
    """The PropertyManager of a tool: a title, what to click, the options of the tool, and OK (leave the tool)."""
    TITLES = {"dim": "Smart Dimension", "center_mark": "Center Mark", "centerline": "Centerline", "note": "Note", "balloon": "Balloon", "line": "Line", "rect": "Rectangle",
              "circle": "Circle", "arc": "Arc"}
    HELP = {"dim": ["Click a line: its length.", "Click a circle: its diameter.  An arc: its radius.",
                    "Click two points, a point and a line, or two circles: the distance.", "Click two parallel lines: the distance between them.",
                    "Click two lines that meet: the angle between them."],
            "center_mark": ["Click a circle or an arc (or its centre point): a cross is put on it."],
            "centerline": ["Click two parallel lines: a dash-dot line is put midway between them."],
            "note": ["Type the text, choose its size and a leader.", "Without a leader: click where the text goes.", "With a leader: click what it points at, then where the text goes."],
            "balloon": ["Click the edge or the face of a view that the balloon points at, then where the circle goes.", "The number counts on by itself."],
            "line": ["Click the start, then the end.  The next click carries on from the end."], "rect": ["Click one corner, then the opposite corner."],
            "circle": ["Click the centre, then a point on the circle."], "arc": ["Click the centre, the start, then the end.  The arc runs counter-clockwise from the start."]}
    AFTER = {"dim": "After the picks, move the pointer to where the dimension should go and click.  Drag a dimension later to move it; the number is always the model's, whatever the scale.",
             "center_mark": "Pick as many as you like, then OK.", "centerline": "Pick pairs of lines, one pair after another, then OK.",
             "note": "Double-click a note later to change its text.  Drag the square at the end of its leader to point it somewhere else.",
             "balloon": "Drag the square at the end of the leader to point it at something else.  Double-click a balloon to change its number.",
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
        self.opt_note.setVisible(name == "note")
        self.opt_balloon.setVisible(name == "balloon")
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
        finally:
            self.busy = False

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


def annot_text(a, fmt=None):
    """How an item reads in the Outline: 'Diameter  ⌀6', 'Center Mark', 'Balloon  3', the first line of a note, 'Line', '... (lost)'."""
    if a.get("type") in ("note", "balloon") + IT.DRAW_TYPES:
        return IT.label(a)
    t = ANNOT_LABEL.get(a.get("type"), "Dimension")
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
        self.sh_scale = QLabel("")
        for c in (self.sh_size, self.sh_land, self.sh_proj):
            c.activated.connect(lambda _i: self.sheet_edited())
        f.addRow("Size", self.sh_size)
        f.addRow("Direction", self.sh_land)
        f.addRow("Projection", self.sh_proj)
        f.addRow("Sheet scale", self.sh_scale)
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
        self.v_proj = QLabel("")
        self.v_proj.setWordWrap(True)
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
        f.addRow("", self.v_proj)
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
            it = QTreeWidgetItem(parent, [f"{v['name']}   {v['orient']}, {M.scale_text(v['scale'])}"])
            it.setIcon(0, I.icon(I.ORIENT_ICON.get(v["orient"], "dr_view"), 18))
            it.setData(0, Qt.ItemDataRole.UserRole, ("view", v["id"]))
            items[v["id"]] = it
            for a in d.view_items(v["id"]):
                at = QTreeWidgetItem(it, [annot_text(a, self.tab.canvas.r.fmt)])
                at.setIcon(0, I.icon(ANNOT_ICON.get(a.get("type"), "dr_dim"), 18))
                at.setData(0, Qt.ItemDataRole.UserRole, ("annot", a["id"]))
                aitems[a["id"]] = at
            for c in d.children(v["id"]):
                add(c, it)
        for v in d.views:
            if v.get("parent") is None:
                add(v, vroot)
        for title, icon, recs in (("Notes", "dr_note", d.notes), ("Drawn on the sheet", "dr_draw_line", d.lines)):
            if not recs:
                continue
            folder = QTreeWidgetItem(root, [title])
            folder.setIcon(0, I.icon(icon, 18))
            folder.setData(0, Qt.ItemDataRole.UserRole, ("folder", None))
            for a in recs:
                at = QTreeWidgetItem(folder, [annot_text(a, self.tab.canvas.r.fmt)])
                at.setIcon(0, I.icon(ANNOT_ICON.get(a.get("type"), "dr_dim"), 18))
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

    def show_details(self):
        d = self.tab.d
        k = self.cur_kind
        self.busy = True
        try:
            if k == "sheet":
                self.sh_size.setCurrentIndex(max(0, self.sh_size.findData(d.sheet["size"])))
                self.sh_land.setCurrentIndex(0 if d.sheet["landscape"] else 1)
                self.sh_proj.setCurrentIndex(1 if d.sheet["first_angle"] else 0)
                self.sh_scale.setText(M.scale_text(d.scale) if d.views else "not set yet (the first view sets it)")
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
                proj = v["kind"] == "projected"
                self.v_orient.setVisible(not proj)
                self.v_form.labelForField(self.v_orient).setVisible(not proj)
                self.v_proj.setVisible(proj)
                if proj:
                    par = d.view(v["parent"])
                    self.v_proj.setText(f"Projected from {par['name']}, to its {v['side']}.  It slides along its axis only.")
                else:
                    self.v_orient.setCurrentIndex(max(0, self.v_orient.findData(v["orient"])))
                self.v_style.setCurrentIndex(max(0, self.v_style.findData(v["style"])))
                self.v_scale.setCurrentText(M.scale_text(v["scale"]))
                self.details.setCurrentIndex(3)
            elif k == "annot" and d.annot(self.cur_id).get("type") == "note":
                a = d.annot(self.cur_id)
                if self.n_text.toPlainText() != a["text"]:
                    self.n_text.setPlainText(a["text"])
                self.n_size.setEditText(A.number_text(a.get("size", IT.NOTE_SIZE), 2))
                self.n_leader.setCurrentIndex(max(0, self.n_leader.findData((a.get("leader") or {}).get("kind"))))
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
                self.a_type.setText(ANNOT_LABEL.get(a["type"], "Dimension"))
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
