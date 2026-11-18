"""
sh_dialogs.py - the windows of Sheets:

    FunctionArgsDialog   Excel's "Function Arguments": one box per argument (name, units, a short hint), the value of each box and the result at the bottom
    StandardsBrowser     the standards as a tree (standard > connections > screws / bolts / welds > equation) with a search box and a detail pane
    ColorButton, RowTable    small parts the chart panel (sh_panel.py) uses: a colour button, an editable table with Add / Remove
    StudyImportDialog    pick a finished parametric study to bring in as a block of cells
    FormatDialog, PasteSpecialDialog, NamesDialog

The windows that need to read cells (the arguments and chart windows) stay open next to the grid, so a range can be picked by selecting it there.
"""
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
                             QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import sh_book as B
import sh_engine as E
import sh_fmt
import sh_prefs
import sh_std
import sh_study
import ui_kit

MONO = QFont("Consolas")
MONO.setStyleHint(QFont.StyleHint.Monospace)


def num_text(x):
    return f"{x:.6g}" if isinstance(x, float) else str(x)


def show_value(v):
    if isinstance(v, E.Err):
        return v.code
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return num_text(v)
    return str(v)


def muted(text, size=11):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color:{ui_kit.MUTED}; font-size:{size}px;")
    return lb


def norm_range(wb, text, sheet):
    """'B2:B9' or 'Sheet2!B2:B9' -> 'Sheet2!B2:B9' (the sheet named), None when it is not a range."""
    p = wb.parse_range((text or "").strip(), sheet)
    if p is None:
        return None
    sh, r1, c1, r2, c2 = p
    return f"{E.quote_sheet(sh)}!{E.addr(r1, c1)}:{E.addr(r2, c2)}" if (r1, c1) != (r2, c2) else f"{E.quote_sheet(sh)}!{E.addr(r1, c1)}"


def norm_value(wb, text, sheet):
    """A guide value typed in a table: a number, or a cell reference (kept as 'Sheet!$B$2'); '' for nothing; None when it makes no sense."""
    t = (text or "").strip()
    if t == "":
        return ""
    try:
        return float(t)
    except ValueError:
        pass
    p = wb.parse_range(t, sheet)
    if p is not None and (p[1], p[2]) == (p[3], p[4]):
        return f"{E.quote_sheet(p[0])}!${E.col_letter(p[2])}${p[1]}"
    r = wb.evaluate(t if t.startswith("=") else "=" + t, sheet)
    return t if isinstance(r, float) and r == r else None                                   # (a formula that gives a number)


def rect_text(sheet, rect):
    """A block of cells as text with its sheet: 'Sheet1'!B2:C9 (one cell: 'Sheet1'!B2)."""
    r1, c1, r2, c2 = rect
    return f"{E.quote_sheet(sheet)}!{E.addr(r1, c1)}" + (f":{E.addr(r2, c2)}" if (r1, c1) != (r2, c2) else "")


def selection_range(grid):
    return rect_text(grid.sheet, grid.sel())


def split_call(text):
    """'=NAME(a, b, c)' -> ('NAME', ['a', 'b', 'c']) when the formula is one function call and nothing else, else None."""
    if not text.startswith("="):
        return None
    body = text[1:]
    try:
        toks = E.tokenize(body)
    except E.FormulaError:
        return None
    if len(toks) < 3 or toks[0][0] != "func" or toks[1][0] != "lp" or toks[-1][0] != "rp":
        return None
    depth, parts, start = 0, [], toks[1][3]
    for i, (kind, tx, s, e, val) in enumerate(toks[1:], 1):
        if kind == "lp":
            depth += 1
        elif kind == "rp":
            depth -= 1
            if depth == 0 and i != len(toks) - 1:
                return None
            if depth == 0:
                parts.append(body[start:s].strip())
        elif kind == "comma" and depth == 1:
            parts.append(body[start:s].strip())
            start = e
    if depth != 0:
        return None
    if parts == [""]:
        parts = []
    return toks[0][4], parts


# ------------------------------------------------------------------------------------------------------------------ Function Arguments
class FunctionArgsDialog(QDialog):
    """The Excel-style window for the arguments of one function.  OK sends the formula through `accepted_formula`."""
    accepted_formula = pyqtSignal(str)

    def __init__(self, wb, sheet, r, c, name, values=None, grid=None, parent=None):
        super().__init__(parent)
        self.wb, self.sheet, self.r, self.c, self.grid = wb, sheet, r, c, grid
        self.func = E.FUNCS[name.upper()]
        self.std = sh_std.func(self.func.name)
        self.args = list(self.std.all_args) if self.std else None
        self.hints = [(a.name, a.meaning + (f" [{a.units}]" if a.units else ""), "opt" if a.optional else "") for a in self.args] if self.std else list(self.func.args)
        self.variadic = self.func.hi is None
        self.rows = []
        self.pick = None
        self.setWindowTitle("Function Arguments")
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        lay = QVBoxLayout(self)
        head = QLabel(self.func.name)
        head.setStyleSheet(f"font-size:15px; font-weight:600; color:{ui_kit.INK};")
        lay.addWidget(head)
        if self.std:
            lay.addWidget(muted(f"{self.std.pack.short} · {self.std.section} · {self.std.title}"))
        if self.func.summary:
            lay.addWidget(muted(self.func.summary))
        lay.addWidget(ui_kit.hline())
        self.form_host = QWidget()
        self.form = QVBoxLayout(self.form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(6)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setWidget(self.form_host)
        sc.setMinimumHeight(220)
        lay.addWidget(sc, 1)
        self.hint = muted("")
        self.hint.setMinimumHeight(34)
        lay.addWidget(self.hint)
        lay.addWidget(ui_kit.hline())
        self.result = QLabel("")
        self.result.setStyleSheet(f"font-size:14px; font-weight:600; color:{ui_kit.INK};")
        lay.addWidget(self.result)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color:{ui_kit.WARN}; font-size:11px;")
        lay.addWidget(self.warn)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ui_kit.primary(bb.button(QDialogButtonBox.StandardButton.Ok))
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        n = max(len(self.hints), len(values or []))
        if self.variadic:
            n = max(len(self.hints), len(values or []) + 1)
        for i in range(n):
            self.add_row(i, (values[i] if values and i < len(values) else ""))
        if grid is not None:
            grid.selection_changed.connect(self.grid_picked)
        self.rows[0][1].setFocus() if self.rows else None
        self.update_result()

    def add_row(self, i, text):
        name, hint, opt = (self.hints[i] + ("",))[:3] if i < len(self.hints) else (self.hints[-1][0] if self.hints else "value", "", "opt")
        a = self.args[i] if self.args and i < len(self.args) else None
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lb = QLabel(name)
        lb.setMinimumWidth(92)
        lb.setStyleSheet("font-weight:600;" if not opt else "")
        h.addWidget(lb)
        if a is not None and a.kind == "text" and a.choices:
            ed = QComboBox()
            ed.setEditable(True)
            ed.addItems([""] + [f'"{x}"' for x in a.choices])
            ed.setEditText(text)
            field = ed.lineEdit()
            ed.currentTextChanged.connect(lambda _t, k=i: self.changed(k))
        else:
            ed = QLineEdit(text)
            field = ed
            ed.textChanged.connect(lambda _t, k=i: self.changed(k))
        if a is not None and a.example is not None and not text:
            field.setPlaceholderText(f'e.g. {a.example!r}'.replace("'", '"') if isinstance(a.example, str) else f"e.g. {a.example:g}")
        field.installEventFilter(self)
        field._row = i
        h.addWidget(ed, 1)
        pk = QPushButton("⊞")
        pk.setFixedWidth(28)
        pk.setToolTip("Pick cells: select them in the grid")
        pk.setCheckable(True)
        pk.clicked.connect(lambda _c=False, k=i: self.toggle_pick(k))
        h.addWidget(pk)
        pv = QLabel("")
        pv.setMinimumWidth(110)
        pv.setStyleSheet(f"color:{ui_kit.MUTED};")
        h.addWidget(pv)
        self.form.addWidget(w)
        self.rows.append((lb, ed, pk, pv, hint, opt, field))

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if ev.type() == QEvent.Type.FocusIn and hasattr(obj, "_row"):
            self.hint.setText(self.rows[obj._row][4])
        return super().eventFilter(obj, ev)

    def toggle_pick(self, i):
        on = self.rows[i][2].isChecked()
        for k, row in enumerate(self.rows):
            if k != i:
                row[2].setChecked(False)
        self.pick = i if on else None
        if on and self.grid is not None:
            self.grid.setFocus()

    def grid_picked(self):
        if self.pick is None or self.grid is None or not self.isVisible():
            return
        ref = selection_range(self.grid)
        row = self.rows[self.pick]
        if ref.startswith(E.quote_sheet(self.sheet) + "!"):
            ref = ref.split("!", 1)[1]
        row[1].setEditText(ref) if isinstance(row[1], QComboBox) else row[1].setText(ref)

    def all_texts(self):
        """The text of every box, with a word that matches a choice of a text argument put in quotes."""
        out = []
        for i, row in enumerate(self.rows):
            t = (row[1].currentText() if isinstance(row[1], QComboBox) else row[1].text()).strip()
            a = self.args[i] if self.args and i < len(self.args) else None
            if a is not None and a.kind == "text" and t and not t.startswith('"') and not t.startswith("=") and a.choices and t.casefold() in [x.casefold() for x in a.choices]:
                t = f'"{t}"'
            out.append(t)
        return out

    def texts(self):
        out = self.all_texts()
        while out and out[-1] == "":
            out.pop()
        return out

    def formula(self):
        return f"={self.func.name}({', '.join(self.texts())})"

    def changed(self, i):
        if self.variadic and i == len(self.rows) - 1 and self.texts() and self.rows[i][1].text().strip() if isinstance(self.rows[i][1], QLineEdit) else False:
            self.add_row(len(self.rows), "")
        self.update_result()

    def update_result(self):
        texts = self.texts()
        for i, (row, t) in enumerate(zip(self.rows, self.all_texts())):
            if not t:
                row[3].setText("")
                continue
            v = self.wb.evaluate("=" + t, self.sheet, self.r, self.c)
            row[3].setText("= " + (show_value(v) if v is not None else "?"))
        missing = [self.hints[i][0] for i in range(len(self.hints)) if i >= len(texts) and not (self.hints[i] + ("",))[2:3][0] == "opt"] if not self.variadic else []
        w = []
        f = self.formula()
        msg = E.check(f)
        if msg:
            self.result.setText("Formula result = ")
            self.warn.setText(msg)
            return
        v = self.wb.evaluate(f, self.sheet, self.r, self.c, warnings=w)
        txt = show_value(v)
        self.result.setText("Formula result = " + txt)
        self.result.setStyleSheet(f"font-size:14px; font-weight:600; color:{ui_kit.BAD if isinstance(v, E.Err) else ui_kit.INK};")
        lines = list(w)
        if missing and isinstance(v, E.Err):
            lines.insert(0, "Still needed: " + ", ".join(missing))
        self.warn.setText("\n".join(lines))

    def ok(self):
        f = self.formula()
        msg = E.check(f)
        if msg:
            QMessageBox.warning(self, "Function Arguments", f"That formula cannot be read: {msg}")
            return
        self.accepted_formula.emit(f)
        self.accept()

    def done(self, code):
        if self.grid is not None:
            try:
                self.grid.selection_changed.disconnect(self.grid_picked)
            except (TypeError, RuntimeError):
                pass
        super().done(code)


# ------------------------------------------------------------------------------------------------------------------ the standards browser
class StandardsBrowser(QDialog):
    """Standards as a tree with a search box; the detail pane shows the equation, its variables and a worked example.  `chosen` is the StdFunc to insert."""

    def __init__(self, pack_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Engineering standards")
        self.resize(940, 600)
        self.chosen = None
        self.pack_id = pack_id
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search: screw pull-out, J4.4, weld ...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        top.addWidget(self.search, 1)
        lay.addLayout(top)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(300)
        self.tree.currentItemChanged.connect(self.show_item)
        self.tree.itemDoubleClicked.connect(lambda *_: self.insert())
        split.addWidget(self.tree)
        self.detail = QScrollArea()
        self.detail.setWidgetResizable(True)
        self.detail.setFrameShape(QFrame.Shape.NoFrame)
        split.addWidget(self.detail)
        split.setStretchFactor(1, 1)
        split.setSizes([320, 620])
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        self.status = muted("")
        row.addWidget(self.status, 1)
        self.b_copy = QPushButton("Copy example")
        self.b_copy.clicked.connect(lambda _c=False: self.copy_example())
        self.b_insert = ui_kit.primary(QPushButton("Insert into cell"))
        self.b_insert.clicked.connect(lambda _c=False: self.insert())
        close = QPushButton("Close")
        close.clicked.connect(lambda _c=False: self.reject())
        for b in (self.b_copy, self.b_insert, close):
            row.addWidget(b)
        lay.addLayout(row)
        self.fill()
        self.show_item(None, None)

    def fill(self):
        self.tree.clear()
        packs = [p for p in sh_std.packs() if not self.pack_id or p.id == self.pack_id]
        for p in packs:
            top = QTreeWidgetItem([f"{p.short}  -  {p.edition}"])
            top.setToolTip(0, p.title)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            self._add_level(top, p.tree())
            top.setExpanded(True)
        if self.tree.topLevelItemCount() == 1:
            self._expand_first(self.tree.topLevelItem(0), 1)

    def _expand_first(self, item, depth):
        item.setExpanded(True)
        for i in range(item.childCount()):
            if depth > 0:
                self._expand_first(item.child(i), depth - 1)

    def _add_level(self, parent, node):
        if isinstance(node, dict):
            for label, sub in node.items():
                it = QTreeWidgetItem([label])
                parent.addChild(it)
                self._add_level(it, sub)
        else:
            for f in node:
                it = QTreeWidgetItem([f"{f.section}  {f.title}"])
                it.setData(0, Qt.ItemDataRole.UserRole, f)
                it.setToolTip(0, f.brief)
                parent.addChild(it)

    def filter(self, text):
        hits = {f.full_name for f in sh_std.search(text, self.pack_id)} if text.strip() else None

        def walk(item):
            f = item.data(0, Qt.ItemDataRole.UserRole)
            if f is not None:
                show = hits is None or f.full_name in hits
                item.setHidden(not show)
                return show
            any_ = False
            for i in range(item.childCount()):
                any_ |= walk(item.child(i))
            item.setHidden(not any_)
            if hits is not None and any_:
                item.setExpanded(True)
            return any_
        n = 0
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        if hits is not None:
            n = len(hits)
            self.status.setText(f"{n} match(es)" if n else "No equation matches.")
            first = self._first_visible(self.tree.invisibleRootItem())
            if first is not None:
                self.tree.setCurrentItem(first)
        else:
            self.status.setText("")

    def _first_visible(self, item):
        for i in range(item.childCount()):
            ch = item.child(i)
            if ch.isHidden():
                continue
            if ch.data(0, Qt.ItemDataRole.UserRole) is not None:
                return ch
            r = self._first_visible(ch)
            if r is not None:
                return r
        return None

    def current_func(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None

    def show_item(self, cur, _prev):
        f = cur.data(0, Qt.ItemDataRole.UserRole) if cur is not None else None
        self.b_insert.setEnabled(f is not None)
        self.b_copy.setEnabled(f is not None)
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(14, 8, 14, 12)
        v.setSpacing(8)
        if f is None:
            if cur is not None:
                v.addWidget(self._title(cur.text(0)))
                if cur.parent() is None:
                    p = next((p for p in sh_std.packs() if cur.text(0).startswith(p.short)), None)
                    if p:
                        v.addWidget(muted(p.title))
                        v.addWidget(muted(f"{p.publisher} · {p.edition}. {p.about}"))
            else:
                v.addWidget(muted("Pick an equation on the left." if sh_std.packs() else "No engineering standards are installed."))
            v.addStretch(1)
            self.detail.setWidget(host)
            return
        v.addWidget(self._title(f.title))
        v.addWidget(muted(" · ".join(x for x in (f.pack.short, f.section, ("Eq. " + f.eq) if f.eq else "", f.units) if x)))
        v.addWidget(QLabel(f.brief))
        box = QLabel(f.formula)
        box.setFont(MONO)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.setStyleSheet("background:#f3f5f9; border:1px solid #d5dbe6; border-radius:6px; padding:8px;")
        v.addWidget(box)
        if f.factors:
            v.addWidget(muted(f.factors_text() + ".  Last argument: nominal, ASD, LRFD or LSD."))
        elif f.check:
            v.addWidget(muted("Last argument: ASD (default), LRFD or LSD.  1.00 or less passes."))
        tbl = QTableWidget(len(f.all_args), 4)
        tbl.setHorizontalHeaderLabels(["Symbol", "Meaning", "Units", "Limits"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, a in enumerate(f.all_args):
            lim = a.limits_text()
            if a.limit_ref and (a.min is not None or a.max is not None):
                lim += f" ({a.limit_ref})"
            for j, t in enumerate((a.symbol + (" (optional)" if a.optional else ""), a.meaning, a.units, lim)):
                tbl.setItem(i, j, QTableWidgetItem(t))
        tbl.resizeColumnsToContents()
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tbl.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tbl.setFixedHeight(tbl.horizontalHeader().height() + sum(tbl.rowHeight(i) for i in range(tbl.rowCount())) + 4)
        v.addWidget(tbl)
        for n in f.notes:
            v.addWidget(muted("• " + n, 12))
        ex = f.example
        if ex:
            vals = [x for x in ex["values"]]
            while vals and vals[-1] is None:
                vals.pop()
            txt = f.formula_text([("" if x is None else (f'"{x}"' if isinstance(x, str) else num_text(float(x)))) for x in vals])
            res = ex["result"]
            lab = QLabel(f"Example  {txt}  =  {show_value(res)} {f.units if not f.check else ''}".rstrip())
            lab.setFont(MONO)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setStyleSheet("background:#eef7f7; border:1px solid #bfe0e2; border-radius:6px; padding:8px;")
            v.addWidget(lab)
            self._example = txt
        else:
            self._example = f.formula_text()
        v.addStretch(1)
        self.detail.setWidget(host)

    @staticmethod
    def _title(text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet(f"font-size:16px; font-weight:600; color:{ui_kit.INK};")
        return lb

    def copy_example(self):
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(getattr(self, "_example", ""))
        self.status.setText("Example copied.")

    def insert(self):
        f = self.current_func()
        if f is None:
            return
        self.chosen = f
        self.accept()


# ------------------------------------------------------------------------------------------------------------------ charts
def load_custom_colors():
    """Puts the person's saved "Custom colors" into the colour picker (Qt keeps them for the running program only)."""
    for i, t in enumerate((sh_prefs.get("custom_colors") or "").split(",")[:QColorDialog.customCount()]):
        c = QColor(t.strip())
        if c.isValid():
            QColorDialog.setCustomColor(i, c)


def save_custom_colors():
    sh_prefs.set_many({"custom_colors": ",".join(QColorDialog.customColor(i).name() for i in range(QColorDialog.customCount()))})


def pick_color(parent, initial, title="Colour"):
    """The colour picker, opened on the window of `parent` (so it keeps the program's look) with the person's custom colours.  Returns the colour, or None."""
    load_custom_colors()
    dlg = QColorDialog(QColor(initial or "#ffffff"), parent.window() if parent is not None else None)
    dlg.setWindowTitle(title)
    ok = dlg.exec()
    save_custom_colors()
    c = dlg.currentColor()
    dlg.deleteLater()
    return c if ok and c.isValid() else None


class ColorButton(QPushButton):
    """A colour swatch.  Its colour is painted by a rule for this button only: a rule without a target would reach everything opened from the button,
    and the colour picker took the colour of the swatch."""
    picked = pyqtSignal(str)

    def __init__(self, color):
        super().__init__()
        self.color = color
        self.setObjectName("colorswatch")
        self.setFixedWidth(46)
        self.clicked.connect(lambda _c=False: self.pick())
        self.paint()

    def paint(self):
        self.setStyleSheet(f"QPushButton#colorswatch {{ background:{self.color}; border:1px solid #8a93a3; border-radius:4px; }}")

    def pick(self):
        c = pick_color(self, self.color)                               # (on the window, not on the swatch)
        if c is not None:
            self.color = c.name()
            self.paint()
            self.picked.emit(self.color)


class RowTable(QWidget):
    """A small editable table with Add / Remove buttons.  columns: [(title, kind, options)] with kind text | combo | color."""

    changed = pyqtSignal()                       # a cell, a choice or a colour was changed, or a row added or removed

    def __init__(self, columns, new_row, add_text="Add", parent=None):
        super().__init__(parent)
        self.columns, self.new_row = columns, new_row
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.t = QTableWidget(0, len(columns))
        self.t.setHorizontalHeaderLabels([c[0] for c in columns])
        self.t.verticalHeader().setVisible(False)
        self.t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t.horizontalHeader().setStretchLastSection(False)
        for i, c in enumerate(columns):
            if c[1] == "text" and c[2] == "wide":
                self.t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.t.itemChanged.connect(lambda _it: self.changed.emit())
        lay.addWidget(self.t)
        row = QHBoxLayout()
        b_add = QPushButton(add_text)
        b_add.clicked.connect(lambda _c=False: (self.add(self.new_row()), self.changed.emit()))
        b_del = QPushButton("Remove")
        b_del.clicked.connect(lambda _c=False: self.remove())
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch(1)
        lay.addLayout(row)

    def add(self, values):
        r = self.t.rowCount()
        self.t.insertRow(r)
        for i, (title, kind, opts) in enumerate(self.columns):
            v = values[i] if i < len(values) else ""
            if kind == "combo":
                cb = QComboBox()
                for key, text in opts:
                    cb.addItem(text, key)
                k = cb.findData(v)
                cb.setCurrentIndex(max(0, k))
                cb.currentIndexChanged.connect(lambda _i=0: self.changed.emit())
                self.t.setCellWidget(r, i, cb)
            elif kind == "color":
                cbtn = ColorButton(v or "#2b7de9")
                cbtn.picked.connect(lambda _c="": self.changed.emit())
                self.t.setCellWidget(r, i, cbtn)
            else:
                self.t.setItem(r, i, QTableWidgetItem("" if v is None else str(v)))

    def remove(self):
        rows = sorted({i.row() for i in self.t.selectedIndexes()}, reverse=True)
        for r in rows or ([self.t.rowCount() - 1] if self.t.rowCount() else []):
            self.t.removeRow(r)
        self.changed.emit()

    def value(self, r, c):
        w = self.t.cellWidget(r, c)
        if isinstance(w, QComboBox):
            return w.currentData()
        if isinstance(w, ColorButton):
            return w.color
        it = self.t.item(r, c)
        return it.text() if it is not None else ""

    def set_text(self, r, c, text):
        it = self.t.item(r, c)
        if it is not None:
            it.setText(text)

    def rows(self):
        return [[self.value(r, c) for c in range(len(self.columns))] for r in range(self.t.rowCount())]


AXES = [("L", "Left"), ("R", "Right")]
AXES_X = [("L", "Left Y"), ("R", "Right Y"), ("X", "X")]


def _t(v):
    return "" if v is None else (num_text(v) if isinstance(v, float) else str(v))


def _num(text):
    t = (text or "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------------------------ study import
class StudyImportDialog(QDialog):
    """Pick a parametric study: from the project folders of the studies that are open, or any project folder.  `result()` = (project, sub, new_sheet)."""

    def __init__(self, open_projects=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import a study")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.addWidget(muted("Brings the table of a finished parametric study (1D, 2D, 3D FEA or CFD) onto a sheet. Refresh from study reads it again."))
        form = QFormLayout()
        self.project = QComboBox()
        self.project.setEditable(False)
        for name, path in open_projects:
            self.project.addItem(name, path)
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda _c=False: self.browse())
        row = QHBoxLayout()
        row.addWidget(self.project, 1)
        row.addWidget(browse)
        form.addRow("Project", row)
        self.study = QComboBox()
        form.addRow("Study", self.study)
        lay.addLayout(form)
        self.new_sheet = QRadioButton("On a new sheet")
        self.here = QRadioButton("On this sheet, under what is there")
        self.new_sheet.setChecked(True)
        lay.addWidget(self.new_sheet)
        lay.addWidget(self.here)
        self.msg = muted("")
        lay.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ui_kit.primary(bb.button(QDialogButtonBox.StandardButton.Ok))
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.project.currentIndexChanged.connect(self.load_studies)
        self.load_studies()

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Project folder of a study")
        if d:
            name = os.path.basename(d.rstrip("/\\")) or d
            i = self.project.findData(d)
            if i < 0:
                self.project.addItem(name, d)
                i = self.project.count() - 1
            self.project.setCurrentIndex(i)

    def load_studies(self):
        self.study.clear()
        p = self.project.currentData()
        found = sh_study.studies(p) if p else []
        for x in found:
            self.study.addItem(x["name"], x["sub"])
        self.msg.setText("" if found or not p else "No study with results in this folder.")

    def ok(self):
        if not self.project.currentData() or self.study.count() == 0:
            self.msg.setText("Pick a project folder that holds a study.")
            return
        self.accept()

    def result_choice(self):
        return self.project.currentData(), self.study.currentData() or "", self.new_sheet.isChecked()


# ------------------------------------------------------------------------------------------------------------------ small ones
class FormatDialog(QDialog):
    """Number format, font and colours of the selected cells.  `values()` -> dict of Style fields to set."""

    def __init__(self, style, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Format cells")
        st = style or B.DEFAULT_STYLE
        self.fg, self.bg = st.fg, st.bg
        lay = QFormLayout(self)
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        for label, f in sh_fmt.FORMATS:
            self.fmt.addItem(label, f)
        i = self.fmt.findData(st.fmt)
        if i >= 0:
            self.fmt.setCurrentIndex(i)
        else:
            self.fmt.setEditText(st.fmt)
        lay.addRow("Number", self.fmt)
        self.bold, self.italic = QCheckBox("Bold"), QCheckBox("Italic")
        self.bold.setChecked(st.bold)
        self.italic.setChecked(st.italic)
        r = QHBoxLayout()
        r.addWidget(self.bold)
        r.addWidget(self.italic)
        lay.addRow("Font", r)
        self.align = QComboBox()
        for k, t in ((None, "Automatic"), ("left", "Left"), ("center", "Centre"), ("right", "Right")):
            self.align.addItem(t, k)
        self.align.setCurrentIndex(max(0, self.align.findData(st.align)))
        lay.addRow("Align", self.align)
        self.b_fg, self.b_bg = QPushButton(), QPushButton()
        for b, which in ((self.b_fg, "fg"), (self.b_bg, "bg")):
            b.clicked.connect(lambda _c=False, w=which: self.pick(w))
        self.paint()
        lay.addRow("Text colour", self.b_fg)
        lay.addRow("Fill", self.b_bg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ui_kit.primary(bb.button(QDialogButtonBox.StandardButton.Ok))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def pick(self, which):
        cur = self.fg if which == "fg" else self.bg
        c = pick_color(self, cur)
        if c is not None:
            setattr(self, which, c.name())
        else:
            setattr(self, which, None)
        self.paint()

    def paint(self):
        self.b_fg.setText(self.fg or "automatic")
        self.b_bg.setText(self.bg or "none")
        self.b_fg.setStyleSheet(f"color:{self.fg or '#1f2a3c'};")
        self.b_bg.setStyleSheet(f"background:{self.bg};" if self.bg else "")

    def values(self):
        txt = self.fmt.currentText()
        i = self.fmt.currentIndex()
        fmt = self.fmt.itemData(i) if i >= 0 and self.fmt.itemText(i) == txt else txt
        return {"fmt": fmt or "General", "bold": self.bold.isChecked(), "italic": self.italic.isChecked(), "align": self.align.currentData(), "fg": self.fg, "bg": self.bg}


class PasteSpecialDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paste special")
        lay = QVBoxLayout(self)
        self.opts = []
        for key, text in (("all", "All"), ("values", "Values only"), ("formulas", "Formulas (no formats)"), ("formats", "Formats only")):
            rb = QRadioButton(text)
            rb.key = key
            self.opts.append(rb)
            lay.addWidget(rb)
        self.opts[0].setChecked(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ui_kit.primary(bb.button(QDialogButtonBox.StandardButton.Ok))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def what(self):
        return next(rb.key for rb in self.opts if rb.isChecked())


class NamesDialog(QDialog):
    """Names: a word for a cell or a range (NumScrews).  A name of a sheet is read by that sheet's formulas only, so a sheet can be copied with its own
    values under the same names."""

    def __init__(self, wb, sheet, selection_ref="", parent=None):
        super().__init__(parent)
        self.wb, self.sheet = wb, sheet
        self.setWindowTitle("Names")
        self.resize(520, 380)
        lay = QVBoxLayout(self)
        self.list = QTableWidget(0, 3)
        self.list.setHorizontalHeaderLabels(["Name", "Refers to", "Scope"])
        self.list.verticalHeader().setVisible(False)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.list, 1)
        form = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name")
        self.refers = QLineEdit(selection_ref)
        self.refers.setPlaceholderText("=Sheet1!$B$2")
        self.scope = QComboBox()
        self.scope.addItem("This sheet", sheet)
        self.scope.addItem("Whole workbook", "")
        form.addWidget(self.name)
        form.addWidget(self.refers, 1)
        form.addWidget(self.scope)
        lay.addLayout(form)
        row = QHBoxLayout()
        b_add = ui_kit.primary(QPushButton("Add / change"))
        b_add.clicked.connect(lambda _c=False: self.add())
        b_del = QPushButton("Delete")
        b_del.clicked.connect(lambda _c=False: self.delete())
        close = QPushButton("Close")
        close.clicked.connect(lambda _c=False: self.accept())
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.msg = muted("")
        lay.addWidget(self.msg)
        self.list.itemSelectionChanged.connect(self.pick)
        self.fill()

    def entries(self):
        out = [(k, v, "") for k, v in self.wb.names.items()]
        for s in self.wb.sheets:
            out += [(k, v, s.name) for k, v in s.names.items()]
        return sorted(out, key=lambda e: (e[2] != "", e[2], e[0].casefold()))

    def fill(self):
        ent = self.entries()
        self.list.setRowCount(len(ent))
        for i, (k, v, sc) in enumerate(ent):
            for j, t in enumerate((k, v, sc or "Workbook")):
                self.list.setItem(i, j, QTableWidgetItem(t))

    def pick(self):
        rows = {i.row() for i in self.list.selectedIndexes()}
        if not rows:
            return
        r = rows.pop()
        self.name.setText(self.list.item(r, 0).text())
        self.refers.setText(self.list.item(r, 1).text())
        sc = self.list.item(r, 2).text()
        self.scope.setCurrentIndex(1 if sc == "Workbook" else max(0, self.scope.findData(sc)))

    def add(self):
        n, ref = self.name.text().strip(), self.refers.text().strip()
        if not n or not ref:
            self.msg.setText("Give a name and what it refers to.")
            return
        if not self.wb.set_name(n, ref, sheet=self.scope.currentData() or None):
            self.msg.setText("That is not a valid name (letters, digits, _ and . only; it may not look like a cell such as A1).")
            return
        self.msg.setText(f"{n} saved.")
        self.fill()

    def delete(self):
        rows = {i.row() for i in self.list.selectedIndexes()}
        for r in rows:
            sc = self.list.item(r, 2).text()
            self.wb.delete_name(self.list.item(r, 0).text(), None if sc == "Workbook" else sc)
        self.fill()


class FunctionPicker(QDialog):
    """Insert function: every function of Sheets with a search box.  `chosen` = the function's name."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert function")
        self.resize(520, 420)
        self.chosen = None
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search functions: sum, lookup, screw ...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.fill)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.ok())
        lay.addWidget(self.list, 1)
        self.info = muted("")
        lay.addWidget(self.info)
        self.list.currentItemChanged.connect(self.show_info)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ui_kit.primary(bb.button(QDialogButtonBox.StandardButton.Ok))
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill("")

    def fill(self, text):
        words = text.casefold().split()
        self.list.clear()
        for n in sorted(E.FUNCS):
            f = E.FUNCS[n]
            hay = (n + " " + f.summary).casefold()
            if f.pack:
                s = sh_std.func(n)
                hay += " " + (s.title + " " + s.keywords + " " + s.section + " " + s.pack.short).casefold() if s else ""
            if all(w in hay for w in words):
                it = QListWidgetItem(n)
                it.setData(Qt.ItemDataRole.UserRole, n)
                self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def show_info(self, cur, _prev):
        if cur is None:
            self.info.setText("")
            return
        f = E.FUNCS[cur.data(Qt.ItemDataRole.UserRole)]
        sig = f"{f.name}({', '.join(a[0] for a in f.args)})" if f.args else f.name
        self.info.setText(f"{sig}\n{f.summary}")

    def ok(self):
        it = self.list.currentItem()
        if it is not None:
            self.chosen = it.data(Qt.ItemDataRole.UserRole)
            self.accept()


class SheetPickDialog(QDialog):
    """Tick sheets: Paste to sheets copies the selected block to the same cells of each ticked sheet."""

    def __init__(self, names, title="Sheets", text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        if text:
            lay.addWidget(muted(text))
        self.list = QListWidget()
        for n in names:
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ui_kit.primary(bb.button(QDialogButtonBox.StandardButton.Ok))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def ticked(self):
        return [self.list.item(i).text() for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.CheckState.Checked]
