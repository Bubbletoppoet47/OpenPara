"""
unitctl.py - the program-wide unit setting (File > Units) and the conversions at the edge of the user interface.

What is stored never changes: part and assembly files keep their geometry in millimetres, whatever units are shown.  So switching
the units never alters a model - it only changes what is shown and how typed numbers are read.  Everywhere the interface shows or
asks for a length it goes through this module:

    to_disp(mm) / from_disp(x)              a length in millimetres <-> in the current length unit
    expr_to_display(text) / expr_from_display(text)
                                             a formula such as "W/2 + 3" stored in mm <-> as the user sees / types it
    length_text(mm)                          "25.4 mm"-style text, e.g. "1 in"

The simulation tabs (1D FEA, 2D FEA, 2D CFD) work in the full unit system (length, force, stress, density) and are converted
by their own change_units() when the system changes (see physics_store.py); the speed unit is a separate setting
(units.set_speed) so that a wind / flow speed can be in mph with metric lengths, and so on.

Formulas.  A number typed in a formula is a length when it is added to / subtracted from something (W/2 + 3), alone (40), or an
argument of min / max / abs / round.  A number that multiplies or divides (2*W, W/3) is a plain factor and is never converted.
A number can carry its own unit: "3 in", "25.4mm", "2 ft + 10 cm" - it is then exact whatever the current unit.  A Global can be
marked 'number' or 'angle' in the Globals table so that it is never converted.
"""
import ast
import json
import os
import re

import paths
import units

SETTINGS_FILE = "units.json"
_state = {"system": units.DEFAULT, "speed": units.DEFAULT_SPEED}
_listeners = []

# the unit written after a number typed in a formula -> millimetres in one of it
SUFFIX_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}
_SUFFIX_RE = re.compile(r"(?<![\w.])(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)\s*(mm|cm|m|in|ft)\b(?!\s*[\w(])", re.I)


# ----------------------------------------------------------------------------------------------------- the setting
def settings_path():
    return os.path.join(paths.user_dir(), SETTINGS_FILE)


def load():
    """Read the saved choice (the system and the speed unit) - the first start uses the defaults."""
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    s = d.get("system")
    sp = d.get("speed")
    _state["system"] = units.canon(s) if isinstance(s, str) and units.valid(s) else units.DEFAULT
    _state["speed"] = sp if sp in units.SPEEDS else units.DEFAULT_SPEED
    units.set_speed(_state["speed"])
    return dict(_state)


def save():
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(_state, f)
    except OSError:
        pass


def system():
    return _state["system"]


def speed():
    return _state["speed"]


def on_change(fn):
    """fn(old_system, new_system, old_speed, new_speed) is called after the units were changed."""
    if fn not in _listeners:
        _listeners.append(fn)


def off_change(fn):
    if fn in _listeners:
        _listeners.remove(fn)


def set_units(new_system=None, new_speed=None, notify=True, persist=True):
    """Change the program's units.  Returns True when something changed."""
    old_s, old_v = _state["system"], _state["speed"]
    ns = units.canon(new_system) if new_system else old_s
    nv = new_speed or old_v
    if not units.valid(ns):
        raise ValueError(f"unknown unit system '{new_system}'")
    if nv not in units.SPEEDS:
        raise ValueError(f"unknown speed unit '{new_speed}'")
    if ns == old_s and nv == old_v:
        return False
    _state["system"], _state["speed"] = ns, nv
    units.set_speed(nv)
    if persist:
        save()
    if notify:
        for fn in list(_listeners):
            try:
                fn(old_s, ns, old_v, nv)
            except Exception:
                import traceback
                traceback.print_exc()
    return True


# ----------------------------------------------------------------------------------------------------- lengths
def length_unit():
    return units.get(_state["system"])["L"]


def mm_per_unit():
    """Millimetres in one length unit of the current system."""
    return units.get(_state["system"])["L_m"] * 1000.0


def to_disp(mm):
    return mm / mm_per_unit()


def from_disp(x):
    return x * mm_per_unit()


def is_mm():
    return abs(mm_per_unit() - 1.0) < 1e-12


def num(x, digits=6):
    """A number as short text: no trailing zeros, no exponent for ordinary sizes."""
    x = float(x)
    if x == 0:
        return "0"
    t = f"{x:.{digits}g}"
    if "e" in t:
        t = f"{x:.{digits}f}".rstrip("0").rstrip(".") if abs(x) >= 1e-5 else t
    return t


def length_text(mm, digits=6):
    """'25.4 mm'-style text for a length held in mm, in the current unit:  1 in"""
    return f"{num(to_disp(mm), digits)} {length_unit()}"


def area_unit():
    return length_unit() + "2"


def volume_unit():
    return length_unit() + "3"


def area_text(mm2, digits=6):
    f = mm_per_unit()
    return f"{num(mm2 / f ** 2, digits)} {area_unit()}"


def volume_text(mm3, digits=6):
    f = mm_per_unit()
    return f"{num(mm3 / f ** 3, digits)} {volume_unit()}"


def label(text):
    """'Width (mm)' -> 'Width (in)': the length unit in a label follows the setting.  A label without 'mm' in brackets is unchanged."""
    L = length_unit()
    t = re.sub(r"\(mm(?=[\s;)])", "(" + L, text)
    return t.replace("mm²", L + "²").replace("mm2", L + "2").replace("mm³", L + "³")


# ----------------------------------------------------------------------------------------------------- mass
def mass_units():
    """(length unit, mass unit, density unit, mass per kg, density per kg/m3) for displaying mass properties in the current system."""
    L = length_unit()
    if L in ("in", "ft"):
        lb = 2.2046226218
        if L == "in":
            return L, "lb", "lb/in3", lb, lb * 0.0254 ** 3
        return L, "lb", "lb/ft3", lb, lb * 0.3048 ** 3
    if L == "m":
        return L, "kg", "kg/m3", 1.0, 1.0
    return L, "g", "g/cm3", 1000.0, 1e-3                    # mm and cm: small parts read best in grams


# ----------------------------------------------------------------------------------------------------- formulas
_LEN_FUNCS = {"min", "max", "abs", "round", "floor", "ceil"}


def _has_name(node):
    return any(isinstance(n, ast.Name) for n in ast.walk(node))


def _length_constants(node, ctx, out):
    """Collects the numeric literal nodes of an expression that are lengths (see the module text)."""
    if isinstance(node, ast.Constant):
        if ctx and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            out.append(node)
    elif isinstance(node, ast.UnaryOp):
        _length_constants(node.operand, ctx, out)
    elif isinstance(node, ast.BinOp):
        if isinstance(node.op, (ast.Add, ast.Sub)):
            _length_constants(node.left, ctx, out)
            _length_constants(node.right, ctx, out)
        elif isinstance(node.op, ast.Mult):
            lc, rc = not _has_name(node.left), not _has_name(node.right)
            if lc and not rc:
                _length_constants(node.right, ctx, out)
            else:                                           # name * const, or const * const: the first factor carries the unit
                _length_constants(node.left, ctx, out)
        elif isinstance(node.op, ast.Div):
            if not _has_name(node.right) or _has_name(node.left):
                _length_constants(node.left, ctx, out)
        # a power, modulo ... : not a length
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _LEN_FUNCS:
        for a in node.args:
            _length_constants(a, ctx, out)
    elif isinstance(node, ast.IfExp):
        _length_constants(node.body, ctx, out)
        _length_constants(node.orelse, ctx, out)


def _fmt(v, to_mm=False):
    """Number text.  Shown values keep 8 digits; values going back to mm snap to a tidy number when they are within the rounding
    of what was shown (1.5748031 in -> 40 mm, not 39.9999987)."""
    if to_mm:
        r = round(v, 5)
        if abs(v - r) < 2e-6 * max(1.0, abs(v) / 100.0):
            v = r
        return f"{v:.12g}"
    return f"{v:.8g}"


def _scale_expr(text, k, to_mm=False):
    """Multiplies the length constants of the formula by k; text keeps its layout otherwise."""
    t = text.strip()
    if not t or k == 1.0:
        return text
    try:
        v = float(t)
        return _fmt(v * k, to_mm)
    except ValueError:
        pass
    if "\n" in t:
        return text
    try:
        tree = ast.parse(t, mode="eval")
    except SyntaxError:
        return text
    nodes = []
    _length_constants(tree.body, True, nodes)
    spans = sorted(((n.col_offset, n.end_col_offset, n.value) for n in nodes), reverse=True)
    for a, b, val in spans:
        t = t[:a] + _fmt(val * k, to_mm) + t[b:]
    return t


def _suffixes_to_mm(text, k):
    """'3 in + W' -> placeholders; returns (text with placeholders, {placeholder: mm}) and k is not applied to them."""
    found = {}

    def rep(m):
        name = f"_u{len(found)}_"
        found[name] = float(m.group(1)) * SUFFIX_MM[m.group(2).lower()]
        return name
    return _SUFFIX_RE.sub(rep, text), found


def expr_to_display(text, kind="length"):
    """A formula stored in mm -> the formula in the current unit.  Names are untouched; only length constants change."""
    text = str(text)
    if kind != "length" or is_mm():
        return text
    return _scale_expr(text, 1.0 / mm_per_unit())


def expr_from_display(text, kind="length"):
    """A formula typed in the current unit (it may have '3 in' style numbers) -> the formula in mm for storage."""
    text = str(text)
    if kind != "length":
        return text
    t, found = _suffixes_to_mm(text, 1.0)
    if not is_mm():
        t = _scale_expr(t, mm_per_unit(), True)
    for name, mm in found.items():
        t = re.sub(r"\b" + name + r"\b", _fmt(mm, True), t)
    return t


def convert_expr(text, old_system, new_system, kind="length"):
    """A formula written in one unit system -> in another (used when a file in other units is opened)."""
    if kind != "length":
        return str(text)
    k = units.length_factor(old_system, new_system)
    return _scale_expr(str(text), k, abs(k) > 1)


def read_length(text):
    """Text typed in a length box -> millimetres.  A plain number is in the current unit; a number with a unit ('3 in') or a
    formula of such numbers is evaluated.  Raises ValueError."""
    t = str(text).strip()
    if not t:
        raise ValueError("empty")
    try:
        return from_disp(float(t))
    except ValueError:
        pass
    mm_text = expr_from_display(t)
    try:
        return float(eval(mm_text, {"__builtins__": {}}, {}))
    except Exception as ex:
        raise ValueError(f"'{text}' is not a number ({ex})")


# load the saved choice when the module is first used by the program (tests set OPARA_USER_DIR before importing)
def _boot():
    try:
        load()
    except Exception:
        pass


_boot()
