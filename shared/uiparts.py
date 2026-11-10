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


def stack(label, *widgets):
    """A label on its own line with the widgets in a row under it - for three axis boxes that would make one line too wide."""
    from PyQt6.QtWidgets import QVBoxLayout
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lay.addWidget(QLabel(label))
    lay.addWidget(row(*widgets))
    return w


def narrow(*spins, width=92):
    """Number boxes that ask for less room than their range would (three of them fit side by side in a panel)."""
    for sp in spins:
        sp.setMinimumWidth(width)
    return spins
