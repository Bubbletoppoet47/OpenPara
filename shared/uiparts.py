"""Small Qt widget helpers used by several add-ons (spin boxes, buttons, rows)."""
from PyQt6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QWidget


def spin(lo, hi, val, dec=2, step=None, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    s.setSingleStep(step if step else 10 ** -dec)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


def button(text, fn):
    b = QPushButton(text)
    b.clicked.connect(lambda _=False: fn())
    return b


def row(*widgets):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        lay.addWidget(QLabel(x) if isinstance(x, str) else x)
    return w
