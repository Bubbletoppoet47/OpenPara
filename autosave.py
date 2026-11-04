"""
autosave.py - the AutoSave switch at the top of the window, like Word's.

One switch for the tab on screen (every tab that has a file of its own: Sketch/Part, Assembly, Assembly Sketch, Simulation, Truss, Circuits ...).
While it is On, the tab's file is written whenever the tab has unsaved changes and they have settled: the check runs twice a second, a change is
saved on the second look that still finds it unsaved, so a burst of edits or a rebuild after every keystroke writes once, and nothing is written
while a mouse button is held (a drag) or a dialog is open.  The file is replaced in one step (see fileio.py) and no backup is made; Undo / Redo are
not touched (saving never changes the history).  The switch is remembered per file in userdata/autosave.json.  Off by default; a file with no name
asks for one when the switch is turned on.
"""
import json
import os
import time

from PyQt6.QtCore import QObject, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QAbstractButton, QApplication, QHBoxLayout, QLabel, QToolBar, QWidget

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(HERE, "userdata", "autosave.json")
TICK_MS = 500
RETRY_TICKS = 10


class Switch(QAbstractButton):
    """A small on / off switch (a pill with a knob)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(QSize(38, 20))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on, ok = self.isChecked(), self.isEnabled()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2b7de9" if on and ok else "#2b7de966" if on else "#b8c1d1" if ok else "#d9dee8"))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), self.height() / 2, self.height() / 2)
        r = self.height() - 6
        x = self.width() - r - 3 if on else 3
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, 3, r, r))


def _key(path):
    return os.path.normcase(os.path.abspath(path)) if path else None


class AutoSave(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.remembered = self.load_store()
        self.bar = QToolBar("AutoSave", host)
        self.bar.setMovable(False)
        self.bar.setFloatable(False)
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(8)
        self.switch = Switch()
        self.label = QLabel("AutoSave")
        self.status = QLabel("")
        self.status.setStyleSheet("color:#4a5872;")
        for w in (self.label, self.switch, self.status):
            lay.addWidget(w)
        self.bar.addWidget(box)
        host.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.bar)
        self.switch.clicked.connect(self.clicked)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)
        host.tabs.currentChanged.connect(lambda _i: self.sync())
        self.sync()

    # ------------------------------------------------------------------ the remembered files
    @staticmethod
    def load_store():
        try:
            with open(STORE, encoding="utf-8") as fh:
                return set(json.load(fh))
        except Exception:
            return set()

    def save_store(self):
        try:
            os.makedirs(os.path.dirname(STORE), exist_ok=True)
            from fileio import write_text
            write_text(STORE, json.dumps(sorted(self.remembered)))
        except Exception:
            pass

    # ------------------------------------------------------------------ one tab
    def state(self, w):
        return w.__dict__.setdefault("_autosave", {"on": False, "dirty_ticks": 0, "fail": 0, "msg": "", "bad": False})

    def available(self, w):
        return self.host.saveable(w)

    def is_on(self, w):
        return bool(w is not None and self.available(w) and self.state(w)["on"])

    def set_on(self, w, on):
        """Turn AutoSave on / off for tab w.  Turning it on for a file with no name asks for one first (False when that was cancelled)."""
        if not self.available(w):
            return False
        st = self.state(w)
        if on and not getattr(w, "path", None):
            if not self.host.save_widget(w, as_new=True) or not getattr(w, "path", None):
                st["on"] = False
                self.sync()
                return False
        st["on"], st["dirty_ticks"], st["fail"], st["bad"] = bool(on), 0, 0, False
        k = _key(getattr(w, "path", None))
        if k:
            (self.remembered.add if on else self.remembered.discard)(k)
            self.save_store()
        st["msg"] = "AutoSave is on" if on else ""
        if on and self.host.tab_dirty(w):
            self.write(w)                                  # unsaved changes are saved at once
        self.sync()
        return True

    def clicked(self):
        w = self.host.cur()
        self.set_on(w, self.switch.isChecked())

    def write(self, w):
        """Save tab w now (its own save routine; no dialogs).  True when written."""
        st = self.state(w)
        self.status.setText("Saving…")
        self.status.repaint()
        try:
            ok = w.save()
        except TypeError:
            ok = w.save(as_new=False)
        except Exception as ex:
            ok, err = False, str(ex) or type(ex).__name__
            st["bad"], st["msg"] = True, f"AutoSave failed: {err}"
            return False
        if ok is False:
            st["bad"], st["msg"] = True, "AutoSave could not save"
            return False
        st["bad"], st["fail"], st["dirty_ticks"] = False, 0, 0
        st["msg"] = "Saved " + time.strftime("%I:%M:%S %p").lstrip("0")
        try:
            self.host.refresh_titles()
        except Exception:
            pass
        return True

    def tick(self):
        if getattr(self, "_in_tick", False):
            return
        self._in_tick = True
        try:
            self._tick()
        finally:
            self._in_tick = False

    def _tick(self):
        busy = QApplication.mouseButtons() != Qt.MouseButton.NoButton or QApplication.activeModalWidget() is not None
        for i in range(self.host.tabs.count()):
            w = self.host.tabs.widget(i)
            if not self.available(w):
                continue
            st = self.state(w)
            if not st["on"]:
                k = _key(getattr(w, "path", None))
                if k and k in self.remembered:             # a file opened that was left with AutoSave on
                    st["on"] = True
                    st["msg"] = "AutoSave is on"
                continue
            if busy or not self.host.tab_dirty(w):
                st["dirty_ticks"] = 0 if not busy else st["dirty_ticks"]
                continue
            st["dirty_ticks"] += 1
            if st["fail"] > 0:                              # a failed save is retried every few looks
                st["fail"] += 1
                if st["fail"] < RETRY_TICKS:
                    continue
            if st["dirty_ticks"] >= 2:                      # the change has settled
                if not self.write(w):
                    st["fail"] = 1
        self.sync()

    def sync(self):
        """The switch and the status show the tab on screen."""
        w = self.host.cur()
        ok = self.available(w)
        self.switch.setEnabled(ok)
        self.switch.blockSignals(True)
        self.switch.setChecked(ok and self.state(w)["on"])
        self.switch.blockSignals(False)
        self.switch.update()
        if not ok:
            self.status.setText("")
            self.switch.setToolTip("This tab has no file of its own to save.")
            self.label.setToolTip(self.switch.toolTip())
            return
        st = self.state(w)
        self.switch.setToolTip("AutoSave: write this file after every change (no backup is kept; Undo / Redo still work)." if not st["on"]
                               else "AutoSave is on: the file is written a moment after each change.")
        self.status.setText(st["msg"] if st["on"] or st["bad"] else "")
        self.status.setStyleSheet("color:#c00000;" if st["bad"] else "color:#4a5872;")
