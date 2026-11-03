"""
suggest.py - Excel-style suggestion lists under the boxes where a number or a formula is typed.

    attach(edit, names_fn)       a QLineEdit gets a drop-down of the names that match the word being typed
    SuggestDelegate(names_fn)    the same for the cells of a QTableWidget column

names_fn() -> [(name, shown value text, group)]; build it with names_of(doc) / names_of(doc, sketch_model).  The list opens while typing,
when the box is empty and gets the focus, and with the Down key.  Enter / Tab / a click puts the name in place of the word typed.
"""
import re

from PyQt6.QtCore import QEvent, QModelIndex, QObject, Qt
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QCompleter, QLineEdit, QStyledItemDelegate

import unitctl

FUNCS = [("min", "min(a, b)"), ("max", "max(a, b)"), ("abs", "abs(x)"), ("sqrt", "sqrt(x)"), ("sin", "sin(x)  x in radians"),
         ("cos", "cos(x)"), ("tan", "tan(x)"), ("atan", "atan(x)"), ("radians", "radians(deg)"), ("degrees", "degrees(rad)"),
         ("round", "round(x)"), ("floor", "floor(x)"), ("ceil", "ceil(x)"), ("pi", "3.14159...")]
_WORD = re.compile(r"[A-Za-z_]\w*$")
NAME_ROLE = Qt.ItemDataRole.UserRole


def value_text(v, kind="length"):
    """A global's value as shown next to its name, in the current unit."""
    if v is None:
        return "?"
    if kind == "length":
        return f"{unitctl.num(unitctl.to_disp(v), 6)} {unitctl.length_unit()}"
    if kind == "angle":
        return f"{unitctl.num(v, 6)} deg"
    return unitctl.num(v, 6)


def names_of(doc, sketch_model=None):
    """Globals, named dimensions, the open sketch's own symbols and the functions, each with its current value."""
    out = []
    seen = set()
    try:
        for k in doc.params:
            kind = getattr(doc, "param_kinds", {}).get(k, "length")
            out.append((k, value_text(doc.values.get(k), kind), "global"))
            seen.add(k)
        for k, v in getattr(doc, "dimvals", {}).items():
            if k not in seen:
                out.append((k, value_text(v), "dimension"))
                seen.add(k)
    except Exception:
        pass
    if sketch_model is not None:
        try:
            vals = sketch_model.param_values()
            for k in sketch_model.params:
                if k not in seen:
                    v = vals.get(k)
                    out.append((k, unitctl.num(v, 6) if isinstance(v, (int, float)) and v == v else "?", "sketch"))
                    seen.add(k)
        except Exception:
            pass
    out += [(n, tip, "function") for n, tip in FUNCS if n not in seen]
    return out


class Suggest(QObject):
    def __init__(self, edit, names_fn):
        super().__init__(edit)
        self.edit, self.names_fn = edit, names_fn
        self.model = QStandardItemModel(self)
        self.comp = QCompleter(self.model, edit)
        self.comp.setWidget(edit)
        self.comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.comp.setCompletionRole(NAME_ROLE)
        self.comp.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self.comp.activated[QModelIndex].connect(self.chosen)
        edit.textEdited.connect(lambda _t: self.update(False))
        edit.installEventFilter(self)

    # the word at the cursor
    def word(self):
        t = self.edit.text()[:self.edit.cursorPosition()]
        m = _WORD.search(t)
        return (m.group(0), m.start()) if m else ("", len(t))

    def fill(self):
        self.model.clear()
        order = {"global": 0, "dimension": 1, "sketch": 2, "function": 3}
        for name, val, grp in sorted(self.names_fn() or [], key=lambda x: (order.get(x[2], 9), x[0].lower())):
            it = QStandardItem(f"{name}   =   {val}" if grp != "function" else f"{name}     {val}")
            it.setData(name, NAME_ROLE)
            it.setToolTip(grp)
            self.model.appendRow(it)

    def update(self, force):
        w, _ = self.word()
        if not w and not force and self.edit.text():
            self.comp.popup().hide()            # after an operator or a digit: nothing to complete yet
            return
        self.fill()
        self.comp.setCompletionPrefix(w)
        if self.comp.completionCount() == 0 or (w and any(self.model.item(i).data(NAME_ROLE) == w for i in range(self.model.rowCount()))
                                                 and self.comp.completionCount() == 1):
            self.comp.popup().hide()
            return
        pop = self.comp.popup()
        pop.setCurrentIndex(self.comp.completionModel().index(-1, 0))
        self.comp.complete()

    def chosen(self, idx):
        name = idx.data(NAME_ROLE) if hasattr(idx, "data") else str(idx)
        if isinstance(name, str) and " " in name:
            name = name.split()[0]
        _, start = self.word()
        t = self.edit.text()
        cur = self.edit.cursorPosition()
        self.edit.setText(t[:start] + name + t[cur:])
        self.edit.setCursorPosition(start + len(name))

    def eventFilter(self, obj, ev):
        if obj is self.edit:
            t = ev.type()
            if t == QEvent.Type.FocusIn and not self.edit.text():
                self.update(True)
            elif t == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Down and not self.comp.popup().isVisible():
                self.update(True)
                return True
        return False


def attach(edit, names_fn):
    """Give a QLineEdit the suggestion list.  Returns the Suggest object (kept alive by the edit)."""
    return Suggest(edit, names_fn)


class SuggestDelegate(QStyledItemDelegate):
    """A table column whose cells are edited with the suggestion list."""

    def __init__(self, names_fn, parent=None, exclude=()):
        super().__init__(parent)
        self.names_fn, self.exclude = names_fn, tuple(exclude)

    def createEditor(self, parent, option, index):
        if index.column() in self.exclude:
            return super().createEditor(parent, option, index)
        e = QLineEdit(parent)
        attach(e, self.names_fn)
        return e
