"""Makes the playground look and behave like OpenPara: its theme, its 3D background, its result colours, its unit setting (File > Units),
its material library.  Everything is read from the playground's copy of OpenPara (core/, or OPENPARA_DIR when set); if that is missing the playground falls back to plain
defaults.  Nothing in the OpenPara folder is changed."""
import ast
import os
import sys

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QWidget

import boot

APP = boot.CORE if os.path.isfile(os.path.join(boot.CORE, "pm_app.py")) else os.environ.get("OPENPARA_DIR", "")
if APP and APP not in sys.path:
    sys.path.insert(0, APP)

BG_BOTTOM, BG_TOP = "#f7f9fc", "#cfd9ea"          # the 3D views of OpenPara


def _try(name):
    try:
        return __import__(name)
    except Exception:
        return None


units = _try("units")
unitctl = _try("unitctl")
result_style = _try("result_style")
mat_lib = _try("mat_lib")


# ---------------------------------------------------------------------------------------------------------------- theme
def theme_text():
    """OpenPara's THEME stylesheet, read from pm_app.py without importing the whole modeller."""
    if not APP:
        return ""
    try:
        with open(os.path.join(APP, "pm_app.py"), "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "THEME" for t in node.targets):
                return ast.literal_eval(node.value)
    except Exception:
        pass
    return ""


def apply(app):
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    css = theme_text()
    if css:
        app.setStyleSheet(css)


def set_bg(plotter):
    plotter.set_background(BG_BOTTOM, top=BG_TOP)


# ---------------------------------------------------------------------------------------------------------------- result colours
def cmap():
    try:
        return result_style.current()
    except Exception:
        return "jet"


def cmap_combo(on_change=None):
    if result_style is not None:
        try:
            return result_style.make_combo(None, on_change)
        except Exception:
            pass
    cb = QComboBox()
    cb.addItems(["jet", "turbo", "viridis"])
    return cb


# ---------------------------------------------------------------------------------------------------------------- units
FALLBACK = {"L": "mm", "L_m": 1e-3, "F": "N", "F_N": 1.0, "S": "MPa", "S_Pa": 1e6}


def system():
    try:
        return units.get(unitctl.system())
    except Exception:
        return FALLBACK


def factor(kind):
    """Internal units (mm, N, MPa) in one displayed unit."""
    s = system()
    return {"L": s["L_m"] * 1e3, "F": s["F_N"], "S": s["S_Pa"] / 1e6, "A": (s["L_m"] * 1e3) ** 2}.get(kind, 1.0)


def name(kind):
    s = system()
    return {"L": s["L"], "F": s["F"], "S": s["S"], "A": s["L"] + "²"}.get(kind, "")


def fmt(kind, value, digits=5):
    """'12.3 MPa' from a value in mm / N / MPa, in the unit system chosen under File > Units."""
    return f"{value / factor(kind):.{digits}g} {name(kind)}"


def on_units_changed(fn):
    try:
        unitctl.on_change(fn)
    except Exception:
        pass


class UnitSpin(QDoubleSpinBox):
    """A number box in the displayed unit (File > Units) that always hands out mm / N / MPa through .internal().
    kind: 'L' length, 'F' force, 'S' stress."""

    def __init__(self, kind, lo, hi, value, decimals=4, step=None):
        super().__init__()
        self.kind = kind
        self.lo, self.hi = lo, hi
        self._f = factor(kind)
        self.setDecimals(decimals)
        self.setKeyboardTracking(False)
        self.setRange(lo / self._f, hi / self._f)
        self.setSingleStep((step if step else 10 ** -decimals * 10) / self._f)
        self.setValue(value / self._f)
        self.setSuffix(" " + name(kind))
        on_units_changed(self.units_changed)

    def internal(self):
        return float(self.value()) * self._f

    def set_internal(self, v):
        self.setValue(v / self._f)

    def units_changed(self, *_a):
        try:
            v = self.internal()
            self._f = factor(self.kind)
            self.blockSignals(True)
            self.setRange(self.lo / self._f, self.hi / self._f)
            self.setValue(v / self._f)
            self.setSuffix(" " + name(self.kind))
            self.blockSignals(False)
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------------------------------------------- material
def library():
    """[(name, E in MPa, nu)] from OpenPara's material library (only materials that have elastic values)."""
    out = []
    try:
        for m in mat_lib.library():
            if m.get("E_MPa") and m.get("nu") is not None:
                out.append((m["name"], float(m["E_MPa"]), float(m["nu"])))
    except Exception:
        pass
    return out


class MaterialBox(QWidget):
    """Material pick (OpenPara's library, or Custom) with the modulus and Poisson's ratio boxes."""
    changed = pyqtSignal()

    def __init__(self, E=10000.0, nu=0.3):
        super().__init__()
        self.items = library()
        self.combo = QComboBox()
        self.combo.addItem("Custom")
        self.combo.addItems([n for n, _e, _v in self.items])
        self.E = UnitSpin("S", 1.0, 1e8, E, 1, 100)
        self.nu = QDoubleSpinBox()
        self.nu.setRange(0.0, 0.49)
        self.nu.setDecimals(3)
        self.nu.setSingleStep(0.01)
        self.nu.setValue(nu)
        self.nu.setKeyboardTracking(False)
        lay = __import__("PyQt6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        for lab, w in (("Material", self.combo), ("Young's modulus E", self.E), ("Poisson's ratio", self.nu)):
            r = QWidget()
            h = QHBoxLayout(r)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(QLabel(lab))
            h.addWidget(w, 1)
            lay.addWidget(r)
        self.combo.currentIndexChanged.connect(self.pick)
        self.E.valueChanged.connect(self.edited)
        self.nu.valueChanged.connect(self.edited)

    def pick(self, i):
        if i <= 0:
            return
        _n, E, nu = self.items[i - 1]
        self.E.blockSignals(True)
        self.nu.blockSignals(True)
        self.E.set_internal(E)
        self.nu.setValue(nu)
        self.E.blockSignals(False)
        self.nu.blockSignals(False)
        self.changed.emit()

    def edited(self, *_a):
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)
        self.changed.emit()

    def values(self):
        return self.E.internal(), float(self.nu.value())
