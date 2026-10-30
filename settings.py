"""
settings.py - File > Settings: how the 3D views are drawn and how close a click must be to pick something.

These choices belong to the program, not to a model: they are kept in the user's data folder (settings.json, next to units.json) and
apply to every part and assembly.  Lengths are kept in millimetres whatever the unit shown; pixel values are screen pixels.

    get(key)            the current value             set_many({...})   change several, save, tell the listeners
    reset()             back to the defaults          on_change(fn)     fn(changed_keys) is called after a change
    edge_points(edge)   points along a curved edge, so that no point of the true curve is further than edge_gap from the line drawn
"""
import json
import math
import os
import re

import paths

SETTINGS_FILE = "settings.json"

ARROW_STYLES = {"open": "Open arrow", "filled": "Filled arrow", "closed": "Closed arrow", "dot": "Solid dot", "hollow_dot": "Empty dot",
                "tick": "Tick (slash)", "none": "None"}
LINE_STYLES = {"solid": "Solid", "dashed": "Dashed", "dotted": "Dotted", "dashdot": "Dash-dot"}

# key: (default, minimum, maximum, label).  A text default is a choice (the maximum is then the dict of choices) or a colour (maximum "color").
SPEC = {
    "edge_gap": (0.02, 0.001, 1.0, "Curve accuracy (edges)"),
    "surf_gap": (0.05, 0.005, 1.0, "Surface accuracy (shading)"),
    "line_px": (1.2, 0.5, 4.0, "Outline thickness"),
    "pull_px": (2.0, 0.0, 8.0, "Outline pull toward viewer"),
    "pick3d_px": (4.0, 1.0, 20.0, "3D pick distance"),
    "snap_px": (12.0, 4.0, 40.0, "Sketch snap distance"),
    "pick_px": (9.0, 3.0, 30.0, "Sketch pick distance"),
    "label_px": (16.0, 6.0, 40.0, "Dimension label click area"),
    "hover": (True, False, True, "Highlight what is under the cursor"),
    "dim_line_px": (1.1, 0.5, 4.0, "Dimension line thickness"),
    "dim_line_style": ("solid", None, LINE_STYLES, "Dimension line style"),
    "ext_line_px": (1.0, 0.5, 4.0, "Extension line thickness"),
    "ext_line_style": ("solid", None, LINE_STYLES, "Extension line style"),
    "ext_gap_pct": (0.9, 0.0, 5.0, "Gap between part and extension line"),
    "ext_over_pct": (2.0, 0.0, 8.0, "Extension past the dimension line"),
    "arrow_pct": (2.2, 0.5, 8.0, "Arrowhead size"),
    "arrow_style": ("open", None, ARROW_STYLES, "Arrowhead style"),
    "text_pt": (14.0, 8.0, 30.0, "Label text size"),
    "dim_color": ("#1a1a1a", None, "color", "Dimension colour"),
    "dim_sel_color": ("#ff7300", None, "color", "Selected dimension colour"),
}
FINE_EDGE, FINE_SURF = 0.004, 0.02          # below these a big model gets slow: the dialog warns
_state = {}
_listeners = []


def defaults():
    return {k: v[0] for k, v in SPEC.items()}


def clamp(key, val):
    d, lo, hi, _ = SPEC[key]
    if isinstance(d, bool):
        return bool(val)
    if isinstance(d, str):
        if hi == "color":
            return val.lower() if isinstance(val, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", val) else d
        return val if val in hi else d
    try:
        v = float(val)
    except (TypeError, ValueError):
        return d
    if v != v:
        return d
    return min(hi, max(lo, v))


def path():
    return os.path.join(paths.user_dir(), SETTINGS_FILE)


def load():
    try:
        with open(path(), "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    _state.clear()
    for k in SPEC:
        _state[k] = clamp(k, d[k]) if k in d else SPEC[k][0]
    return dict(_state)


def save():
    try:
        with open(path(), "w", encoding="utf-8") as f:
            json.dump(_state, f)
    except OSError:
        pass


_override = {}


def get(key):
    if key in _override:
        return _override[key]
    if not _state:
        load()
    return _state[key]


class overriding:
    """with settings.overriding({...}): the values are used by get() meanwhile (the live pictures of the settings window)."""

    def __init__(self, values):
        self.values = {k: clamp(k, v) for k, v in values.items() if k in SPEC}

    def __enter__(self):
        self.old = dict(_override)
        _override.update(self.values)

    def __exit__(self, *a):
        _override.clear()
        _override.update(self.old)


def all_values():
    if not _state:
        load()
    return dict(_state)


def on_change(fn):
    if fn not in _listeners:
        _listeners.append(fn)


def set_many(values, persist=True):
    """Change several settings at once (each is held between its limits); returns the keys that really changed."""
    if not _state:
        load()
    changed = []
    for k, v in values.items():
        if k in SPEC:
            nv = clamp(k, v)
            if nv != _state[k]:
                _state[k] = nv
                changed.append(k)
    if changed:
        if persist:
            save()
        for fn in list(_listeners):
            try:
                fn(changed)
            except Exception:
                import traceback
                traceback.print_exc()
    return changed


def reset():
    return set_many(defaults())


# ------------------------------------------------------------------------------------------------------ the sampling of curves
def _pt(e, t):
    p = e.position_at(t)
    return (p.X, p.Y, p.Z)


def _dev(a, b, m):
    """Distance of m from the chord a-b."""
    ab = [b[i] - a[i] for i in range(3)]
    am = [m[i] - a[i] for i in range(3)]
    n2 = sum(x * x for x in ab)
    if n2 < 1e-18:
        return math.sqrt(sum(x * x for x in am))
    t = min(1.0, max(0.0, sum(am[i] * ab[i] for i in range(3)) / n2))
    return math.sqrt(sum((am[i] - ab[i] * t) ** 2 for i in range(3)))


def subdivide(fn, gap, max_depth=9):
    """Points (from fn(t), t = 0..1) of a curve cut into straight pieces: a piece is split until the middle of the curve lies within
    `gap` of it.  Used for the real edges and for the curve preview of the settings window, so both show the same thing."""
    p0, p1 = fn(0.0), fn(1.0)
    out = [p0]

    def rec(t0, t1, a, b, depth):
        tm = (t0 + t1) / 2
        m = fn(tm)
        split = depth < max_depth and _dev(a, b, m) > gap
        if not split and depth < max_depth:        # also probe the quarter points, so an S-shaped piece is not mistaken for a straight one
            split = any(_dev(a, b, fn(t0 + (t1 - t0) * q)) > gap for q in (0.25, 0.75))
        if split:
            rec(t0, tm, a, m, depth + 1)
            rec(tm, t1, m, b, depth + 1)
        else:
            out.append(b)

    rec(0.0, 1.0, p0, p1, 0)
    return out


def edge_points(e, gap=None):
    """Points along an edge (a build123d Edge) so that no point of the true curve is further than `gap` mm (default: File > Settings
    > Curve accuracy) from the line drawn.  A straight edge gives its two ends."""
    gap = get("edge_gap") if gap is None else gap
    if e.geom_type.name == "LINE":
        return [_pt(e, 0.0), _pt(e, 1.0)]
    return subdivide(lambda t: _pt(e, t), gap)


def surface_angle(gap=None):
    """The largest turn (radians) between neighbouring facets of a curved surface: it follows the surface accuracy, so that a small
    round surface is also drawn finer when the accuracy is raised."""
    gap = get("surf_gap") if gap is None else gap
    return min(0.8, 0.9 * math.sqrt(max(gap, 1e-6)))


def circle_facets(radius, gap):
    """How many flat facets a circle of this radius gets at this surface accuracy (the same rule as the real surfaces)."""
    ang = surface_angle(gap)
    n_ang = math.ceil(2 * math.pi / ang)
    n_gap = 3 if gap >= radius else math.ceil(math.pi / math.acos(1.0 - gap / radius))
    return max(6, n_ang, n_gap)


def rgb(key):
    """A colour setting as (r, g, b) floats."""
    c = get(key).lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
