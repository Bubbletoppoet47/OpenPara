"""ctl_dyn_widgets.py - small widgets shared by the Dynamic simulation section and its Learn panel."""
import math

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLabel, QLineEdit


class NumEdit(QLineEdit):
    """A number field: commits on Enter or when it loses focus, and puts the old value back (tinted) if the text is not a number."""
    committed = pyqtSignal(float)

    def __init__(self, value=0.0, tip=""):
        super().__init__()
        self.value = float(value)
        self.setText(self._text(self.value))
        if tip:
            self.setToolTip(tip)
        self.setMinimumWidth(70)
        self.setMinimumHeight(24)
        self.editingFinished.connect(self._done)

    @staticmethod
    def _text(v):
        return f"{v:.6g}"

    def _base_style(self):
        return "background:#f1f3f7;color:#4a5668;" if self.isReadOnly() else ""

    def set_value(self, v):
        self.value = float(v)
        self.setText(self._text(self.value))
        self.setStyleSheet(self._base_style())

    def _done(self):
        if self.isReadOnly():
            return
        try:
            v = float(self.text().strip().replace(",", "."))
            if not math.isfinite(v):
                raise ValueError
        except ValueError:
            self.setText(self._text(self.value))
            self.setStyleSheet("background:#fbe3e0;")
            return
        self.setStyleSheet(self._base_style())
        if v != self.value:
            self.value = v
            self.setText(self._text(v))
            self.committed.emit(v)

    def setReadOnly(self, on):
        super().setReadOnly(on)
        self.setStyleSheet(self._base_style())


def head(text):
    lb = QLabel(text)
    lb.setStyleSheet("font-weight:bold;margin-top:8px;")
    return lb


def small(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet("color:#5b6675;")
    return lb
