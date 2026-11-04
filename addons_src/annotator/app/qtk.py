"""qtk.py - the small Qt helpers the annotator window uses (message boxes, simple input dialogs, thread hand-over, key names).

Everything the old Tk version did with messagebox / simpledialog / filedialog / root.after / key events is here in one place.
"""
import os

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

import hotkeys as hk


# ------------------------------------------------------------------ message boxes (parent = a widget or None)
def info(parent, title, text):
    QMessageBox.information(parent, title, text)


def warn(parent, title, text):
    QMessageBox.warning(parent, title, text)


def error(parent, title, text):
    QMessageBox.critical(parent, title, text)


def yesno(parent, title, text, default_no=False):
    B = QMessageBox.StandardButton
    r = QMessageBox.question(parent, title, text, B.Yes | B.No, B.No if default_no else B.Yes)
    return r == B.Yes


# ------------------------------------------------------------------ input dialogs; None = cancelled
def ask_string(parent, title, label, initial=""):
    s, ok = QInputDialog.getText(parent, title, label, text=initial)
    return s if ok else None


def ask_int(parent, title, label, initial=1, minimum=1, maximum=1_000_000):
    v, ok = QInputDialog.getInt(parent, title, label, initial, minimum, maximum)
    return v if ok else None


def ask_float(parent, title, label, initial=0.0, minimum=0.0, maximum=1.0, decimals=3):
    v, ok = QInputDialog.getDouble(parent, title, label, initial, minimum, maximum, decimals)
    return v if ok else None


def ask_dir(parent, title, initial=None):
    d = QFileDialog.getExistingDirectory(parent, title, initial or "")
    return os.path.normpath(d) if d else None


def ask_files(parent, title, pattern):
    files, _ = QFileDialog.getOpenFileNames(parent, title, "", pattern)
    return [os.path.normpath(f) for f in files]


# ------------------------------------------------------------------ work from other threads: post(fn) runs fn in the GUI thread
class Poster(QObject):
    call = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda fn: fn())

    def __call__(self, fn):
        self.call.emit(fn)


def later(ms, fn):
    QTimer.singleShot(ms, fn)


# ------------------------------------------------------------------ keys: stored text ("d", "Delete", "Ctrl+z", "Left" ...) <-> Qt
_TO_QT = {"Delete": "Del", "BackSpace": "Backspace", "Return": "Return", "Prior": "PgUp", "Next": "PgDown", "space": "Space",
          "plus": "+", "Escape": "Esc"}
_FROM_QT = {"Del": "Delete", "Backspace": "BackSpace", "Return": "Return", "Enter": "Return", "PgUp": "Prior", "PgDown": "Next",
            "Space": "space", "Esc": "Escape"}
_MODIFIER_KEYS = {Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock,
                  Qt.Key.Key_NumLock, Qt.Key.Key_ScrollLock, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R}


def to_qt_sequence(binding):
    """QKeySequence for a stored shortcut."""
    mods, key = hk.split(binding)
    k = _TO_QT.get(key, key.upper() if len(key) == 1 and key.isalpha() else key)
    parts = [{"Ctrl": "Ctrl", "Shift": "Shift", "Alt": "Alt"}.get(m, m) for m in mods]
    return QKeySequence("+".join(parts + [k]))


def from_qt_event(ev):
    """The stored text for a QKeyEvent, or None for a bare modifier key (wait for the real key)."""
    if ev.key() in _MODIFIER_KEYS or ev.key() == 0:
        return None
    name = QKeySequence(ev.key()).toString()
    if not name:
        return None
    key = _FROM_QT.get(name, name)
    if len(key) == 1 and key.isalpha():
        key = key.lower()
    M = Qt.KeyboardModifier
    mods = []
    if ev.modifiers() & M.ControlModifier:
        mods.append("Ctrl")
    if (ev.modifiers() & M.ShiftModifier) and (len(key) > 1 or key.isalpha()):
        mods.append("Shift")
    return "+".join(mods + [key])
