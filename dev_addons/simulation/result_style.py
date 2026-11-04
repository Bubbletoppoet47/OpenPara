"""
result_style.py - one colour scheme for every result picture (1D FEA, 2D FEA, 2D CFD), chosen once and shared.

CMAPS are the same names the earlier 3D FEA offered.  ramp(t) maps 0..1 to RGB (0..255, float); colours(t) the same as ints.
The choice is remembered in gpd_settings.json next to the program.  Tabs call subscribe(fn) to be told when it changes.
matplotlib's maps are used when it is installed; otherwise approximations from a few anchor colours (same look).
"""
import json
import os

import numpy as np

CMAPS = ["turbo", "jet", "viridis", "plasma", "coolwarm", "rainbow", "gray"]
DEFAULT = "jet"            # what the earlier 2D tabs looked like (blue -> red)

# anchor colours (0..255) for the fallback, evenly spaced from 0 to 1
_ANCH = {
    "jet": [(0, 0, 128), (0, 0, 255), (0, 255, 255), (255, 255, 0), (255, 0, 0), (128, 0, 0)],
    "turbo": [(48, 18, 59), (70, 107, 227), (40, 187, 236), (50, 241, 138), (164, 252, 60), (250, 186, 57), (228, 82, 15), (122, 4, 3)],
    "viridis": [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)],
    "plasma": [(13, 8, 135), (126, 3, 168), (204, 71, 120), (248, 149, 64), (240, 249, 33)],
    "coolwarm": [(59, 76, 192), (141, 176, 254), (221, 221, 221), (245, 156, 125), (180, 4, 38)],
    "rainbow": [(128, 0, 255), (43, 126, 246), (128, 254, 179), (213, 126, 179), (255, 0, 0)],
    "gray": [(0, 0, 0), (255, 255, 255)],
}


def _settings_path():
    import paths
    return paths.user_file("gpd_settings.json")


def _load():
    try:
        with open(_settings_path(), "r", encoding="utf-8") as fh:
            n = json.load(fh).get("result_cmap")
            return n if n in CMAPS else DEFAULT
    except Exception:
        return DEFAULT


_state = {"name": _load(), "lut": None, "subs": []}


def lut_of(name):
    """256 x 3 uint8 table of a colour map."""
    try:
        import matplotlib
        cm = matplotlib.colormaps[name]
        return (np.asarray(cm(np.linspace(0, 1, 256)))[:, :3] * 255 + 0.5).astype(np.uint8)
    except Exception:
        a = np.array(_ANCH[name], float)
        x = np.linspace(0, 1, len(a))
        t = np.linspace(0, 1, 256)
        return (np.stack([np.interp(t, x, a[:, k]) for k in range(3)], axis=-1) + 0.5).astype(np.uint8)


def current():
    return _state["name"]


def lut():
    if _state["lut"] is None:
        _state["lut"] = lut_of(_state["name"]).astype(float)
    return _state["lut"]


def ramp(t):
    """0..1 -> RGB floats 0..255, shape (..., 3)."""
    t = np.clip(np.nan_to_num(np.asarray(t, dtype=float), nan=0.0), 0.0, 1.0) * 255.0
    L = lut()
    i0 = np.minimum(t.astype(int), 254)
    f = (t - i0)[..., None]
    return L[i0] * (1 - f) + L[i0 + 1] * f


def colours(t):
    return ramp(t).astype(int)


def subscribe(fn):
    _state["subs"].append(fn)


def unsubscribe(fn):
    if fn in _state["subs"]:
        _state["subs"].remove(fn)


def set_current(name):
    if name not in CMAPS or name == _state["name"]:
        return
    _state["name"], _state["lut"] = name, None
    try:
        with open(_settings_path(), "w", encoding="utf-8") as fh:
            json.dump({"result_cmap": name}, fh)
    except OSError:
        pass
    try:
        import meshdraw
        meshdraw.reload_lut()
    except Exception:
        pass
    for fn in list(_state["subs"]):
        try:
            fn(name)
        except RuntimeError:                      # a tab that is already gone
            unsubscribe(fn)
        except Exception:
            pass


def make_combo(parent_tab, on_change=None):
    """A 'Colours' combo box tied to the shared choice: choosing here changes every tab.  Returns the QComboBox."""
    from PyQt6.QtWidgets import QComboBox
    cb = QComboBox()
    cb.addItems(CMAPS)
    cb.setCurrentText(current())
    cb.setToolTip("The colour scheme of all result pictures (1D FEA, 2D FEA, 2D CFD): the same everywhere, so results compare easily.")

    def user(_i):
        set_current(cb.currentText())

    def external(name):
        cb.blockSignals(True)
        cb.setCurrentText(name)
        cb.blockSignals(False)
        if on_change:
            on_change()
    cb.currentIndexChanged.connect(user)
    subscribe(external)
    cb._external = external                      # keep a reference
    return cb
