"""
sh_edit.py - the text box that formulas are typed into (in a cell and in the formula bar).

    FormulaEdit        a line edit that completes function names as you type (a small list under the box), tells its owner when Enter / Tab / Esc was
                       pressed, and can have a cell reference put in at the cursor (click-to-point, the way Excel does it)
    signature(text, pos)    the help line for the function the cursor is in: ("AISI16.J4_4_1", ["tc", "d", "Fu2"], 1, "Screw diameter [in]") or None
"""
import re

from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem

import sh_engine as E
import sh_std

_WORD = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)$")
_POINT_AFTER = "=(,+-*/^&<>;:%"


def signature(text, pos):
    """(function name, [argument names], index of the argument at the cursor, that argument's hint) for the function being typed, else None."""
    if not text.startswith("="):
        return None
    at = E.function_at(text, pos)
    if at is None:
        return None
    name, idx = at
    f = E.FUNCS.get(name)
    if f is None:
        return None
    names = [a[0] for a in f.args]
    if f.hi is None and names:                                  # SUM(number1, number2, ...)
        while idx >= len(names):
            names.append(names[-1])
        names = names[:max(len(f.args), idx + 1)]
    hint = ""
    if f.args:
        a = f.args[min(idx, len(f.args) - 1)]
        hint = a[1]
    names_shown = [(n + "?") if (i < len(f.args) and len(f.args[i]) > 2 and f.args[i][2]) else n for i, n in enumerate(names)]
    return f.name, names_shown, idx, hint


def matches(prefix, limit=10):
    """Function names that start with `prefix` (upper-cased), the standards' ones included."""
    p = prefix.upper()
    if not p:
        return []
    out = sorted(n for n in E.FUNCS if n.startswith(p))
    return out[:limit]


def _drop(widget):
    try:
        widget.deleteLater()
    except RuntimeError:                                       # already gone (the program is closing)
        pass


class FormulaEdit(QLineEdit):
    done = pyqtSignal(int, int)               # Enter (down) / Tab (right) pressed: the move wanted, (rows, columns)
    cancelled = pyqtSignal()
    typed = pyqtSignal()                      # the person typed (not a change made by the program)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enter_mode = False               # started by typing: the arrow keys finish the entry (as in Excel)
        self.last_point = None                # (start, end, text) of the reference that clicking a cell put in last
        self.pop = QListWidget(None)
        self.pop.setWindowFlags(Qt.WindowType.ToolTip)
        self.pop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pop.setStyleSheet("QListWidget { background:white; border:1px solid #9fb4d4; font-size:12px; } QListWidget::item { padding:2px 8px; }"
                               "QListWidget::item:selected { background:#cfe3fb; color:#1f2a3c; }")
        self.pop.itemClicked.connect(lambda it: self.accept_name(it.text().split("  ")[0]))
        self.textEdited.connect(self._on_typed)
        self.installEventFilter(self)
        self.destroyed.connect(lambda _o=None, p=self.pop: _drop(p))           # the list is a window of its own: it goes when the box goes

    def _hide_pop(self):
        try:
            self.pop.hide()
        except RuntimeError:                                  # the program is closing and the list is already gone
            pass

    # ------------------------------------------------------------------ completing function names
    def _prefix(self):
        t, c = self.text(), self.cursorPosition()
        if not t.startswith("=") or c < 2:
            return None
        m = _WORD.search(t[:c])
        if not m:
            return None
        before = t[:m.start()].rstrip()
        if before and before[-1] not in _POINT_AFTER and before[-1] != " ":
            return None
        if before.endswith("'") or before.endswith("!"):
            return None
        return m.group(1) if not E.parse_addr(m.group(1)) else None

    def _on_typed(self, _text=""):
        self.last_point = None
        self.typed.emit()
        pre = self._prefix()
        names = matches(pre) if pre else []
        if not names or (len(names) == 1 and names[0] == pre.upper()):
            self.pop.hide()
            return
        self.pop.clear()
        for n in names:
            f = E.FUNCS[n]
            QListWidgetItem(f"{n}  {f.summary}"[:80] if f.summary else n, self.pop)
        self.pop.setCurrentRow(0)
        w = max(260, self.width())
        self.pop.setFixedSize(w, min(180, 22 * len(names) + 6))
        self.pop.move(self.mapToGlobal(QPoint(0, self.height() + 2)))
        self.pop.show()

    def accept_name(self, name):
        t, c = self.text(), self.cursorPosition()
        m = _WORD.search(t[:c])
        if not m:
            return
        new = t[:m.start(1)] + name + "(" + t[c:]
        self.setText(new)
        self.setCursorPosition(m.start(1) + len(name) + 1)
        self.pop.hide()
        self._on_typed()

    # ------------------------------------------------------------------ keys
    def eventFilter(self, obj, ev):
        if obj is self and ev.type() == QEvent.Type.FocusOut:
            self._hide_pop()
        return False

    def hideEvent(self, ev):
        self._hide_pop()
        super().hideEvent(ev)

    def keyPressEvent(self, ev):
        k = ev.key()
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self.pop.isVisible():
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.pop.currentRow() + (1 if k == Qt.Key.Key_Down else -1)
                self.pop.setCurrentRow(max(0, min(self.pop.count() - 1, row)))
                return
            if k in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                it = self.pop.currentItem()
                if it is not None:
                    self.accept_name(it.text().split("  ")[0])
                    return
            if k == Qt.Key.Key_Escape:
                self.pop.hide()
                return
        if k == Qt.Key.Key_F4 and not ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            self.cycle_reference()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.done.emit(-1 if shift else 1, 0)
            return
        if k == Qt.Key.Key_Tab:
            self.done.emit(0, 1)
            return
        if k == Qt.Key.Key_Backtab:
            self.done.emit(0, -1)
            return
        if k == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        if self.enter_mode and k in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right) and not self.can_point():
            self.done.emit({Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}.get(k, 0), {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(k, 0))
            return
        super().keyPressEvent(ev)

    def cycle_reference(self):
        """F4: the reference at the cursor (or the ones in the selection) goes on to the next lock: B2, $B$2, B$2, $B2."""
        sel = self.selectionStart()
        if sel >= 0:
            a, b = sel, sel + len(self.selectedText())
        else:
            a = b = self.cursorPosition()
        got = E.cycle_refs(self.text(), a, b)
        if got is None:
            return
        text, start, end = got
        self.setText(text)
        if start != end:
            self.setSelection(start, end - start)
        else:
            self.setCursorPosition(end)
        refs = [sp for sp in E._ref_spans(text) if sp[0] <= end <= sp[1]]
        if refs and start == end:
            self.last_point = (refs[0][0], refs[0][1], text[refs[0][0]:refs[0][1]])            # a click on a cell now replaces this reference, as after pointing
        self.typed.emit()

    # ------------------------------------------------------------------ pointing at cells
    def can_point(self):
        """True when a click on a cell should put its address into the formula here (the cursor follows an operator, a bracket, a comma or an earlier
        reference that clicking put in)."""
        t, c = self.text(), self.cursorPosition()
        if not t.startswith("="):
            return False
        if self.last_point and self.last_point[1] == c and t[self.last_point[0]:c] == self.last_point[2]:
            return True
        before = t[:c].rstrip()
        return bool(before) and before[-1] in _POINT_AFTER

    def put_reference(self, ref, extend=False):
        """Puts `ref` at the cursor (replacing the reference that was put in last, when `extend` or a second click)."""
        t, c = self.text(), self.cursorPosition()
        if self.last_point and self.last_point[1] == c and t[self.last_point[0]:c] == self.last_point[2]:
            start = self.last_point[0]
        else:
            start = c
        new = t[:start] + ref + t[c:]
        self.setText(new)
        end = start + len(ref)
        self.setCursorPosition(end)
        self.last_point = (start, end, ref)
        self.typed.emit()
