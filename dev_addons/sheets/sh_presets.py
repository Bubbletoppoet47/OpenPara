"""
sh_presets.py - saved chart looks.

A preset is the look of a chart and nothing of its data: the basic options (`style`: fonts, line widths, grid, frame, legend ...) and the advanced ones (`adv`), without the
words in the chart (titles, labels, legend title, series names), the data, the guides or the settings of one single series.

    names()  /  get(name)  /  save(name, style, adv)  /  delete(name)  /  is_builtin(name)
    parts(chart)                 (style, adv) of a chart without what is the chart's own   (what Save as preset keeps)
    apply(chart, name)           puts the preset's look on a chart (its own words, data and per-series settings stay); the palette recolours the series
    export_file(path, names) / import_file(path)       presets as a file, to share them
    default_name() / set_default(name)                 the preset new charts start from (kept in sh_prefs)

The built-in ones cannot be changed or deleted.  Saved ones are in <Sheets folder>/chart_presets.json.
"""
import copy
import json
import os

import sh_adv
import sh_prefs

BUILTIN = {
    "Default": {"style": {}, "adv": {}},
    "Report": {"style": {"font": "serif", "title_size": 12, "label_size": 10, "tick_size": 9, "legend_size": 9, "line_width": 1.2, "marker_size": 3.5, "grid": "horizontal",
                         "grid_style": ":", "grid_color": "#b8bfcc", "frame": "open", "frame_color": "#333333", "tick_dir": "in", "text_color": "#111111",
                         "tick_color": "#333333", "palette": "Engineering"}, "adv": {}},
    "Presentation": {"style": {"title_size": 22, "label_size": 17, "tick_size": 15, "legend_size": 15, "line_width": 3.5, "marker_size": 9, "grid_width": 1.2,
                               "frame_width": 1.6, "tick_len": 6, "label_bold": True, "palette": "Bold", "legend_pos": "best"}, "adv": {}},
    "Print (black and white)": {"style": {"font": "serif", "palette": "Greys", "auto_dash": True, "grid": "horizontal", "grid_style": ":", "grid_color": "#999999",
                                          "frame": "box", "frame_color": "#000000", "frame_width": 0.9, "text_color": "#000000", "tick_color": "#000000", "tick_dir": "in",
                                          "line_width": 1.3, "legend_frame": True}, "adv": {}},
    "Dark": {"style": {"bg": "#1b2230", "plot_bg": "#1b2230", "text_color": "#e6ebf5", "tick_color": "#b8c2d6", "frame_color": "#4a566e", "grid_color": "#323d54",
                       "palette": "Bold"}, "adv": {}},
}

_STYLE_ALWAYS_OWN = ()                                    # (style keys that belong to the chart itself would be listed here; none do)


def _file():
    return os.path.join(sh_prefs.folder(), "chart_presets.json")


def _user():
    try:
        with open(_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, dict)} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d):
    try:
        os.makedirs(sh_prefs.folder(), exist_ok=True)
        tmp = _file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, _file())
        return True
    except OSError:
        return False


def is_builtin(name):
    return name in BUILTIN


def names():
    """The built-in presets, then the saved ones by name."""
    return list(BUILTIN) + sorted(n for n in _user() if n not in BUILTIN)


def get(name):
    """A copy of {"style": {...}, "adv": {...}} or None."""
    d = BUILTIN.get(name) or _user().get(name)
    if d is None:
        return None
    return {"style": copy.deepcopy(d.get("style") or {}), "adv": copy.deepcopy(d.get("adv") or {})}


def clean_adv(adv):
    """The advanced entries a preset may hold: no words, no setting of one single series, nothing that is not a known property."""
    out = {}
    for key, v in (adv or {}).items():
        t, index, _n = sh_adv.split_key(key)
        p = sh_adv.get(key)
        if p is None or not p.preset or index is not None:
            continue
        out[key] = v
    return out


def parts(chart):
    """(style, adv) of `chart` as a preset keeps them."""
    return copy.deepcopy(chart.get("style") or {}), clean_adv(chart.get("adv"))


def save(name, style, adv):
    """Saves (or replaces) a preset.  Returns None, or a plain message when it could not be saved."""
    name = (name or "").strip()
    if not name:
        return "Give the preset a name."
    if name in BUILTIN:
        return f"'{name}' is one of the built-in presets: choose another name."
    if len(name) > 60:
        return "Use a shorter name."
    d = _user()
    d[name] = {"style": copy.deepcopy(style or {}), "adv": clean_adv(adv)}
    return None if _write(d) else "The preset could not be written to the settings folder."


def delete(name):
    if name in BUILTIN:
        return "A built-in preset cannot be deleted."
    d = _user()
    if name in d:
        del d[name]
        _write(d)
    return None


def apply(chart, name):
    """Puts the look `name` on the chart.  Returns False when there is no such preset."""
    pr = get(name)
    if pr is None:
        return False
    chart["style"] = pr["style"]
    keep = {k: v for k, v in (chart.get("adv") or {}).items() if (sh_adv.get(k) is None) or (not sh_adv.get(k).preset) or sh_adv.split_key(k)[1] is not None}
    keep.update(pr["adv"])
    chart["adv"] = keep
    import sh_chart
    sh_chart.recolor(chart, pr["style"].get("palette"))
    return True


def export_file(path, which=None):
    """Writes presets (all saved ones, or the names given) to `path`.  Returns None or a message."""
    d = _user()
    pick = {n: d[n] for n in (which or d) if n in d}
    if not pick:
        return "There is no saved preset to write."
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"openpara-sheets-presets": 1, "presets": pick}, f, indent=1)
    except OSError as ex:
        return f"The file could not be written: {ex}"
    return None


def import_file(path):
    """Adds the presets of a file; returns (how many, message or None).  A name that is built in gets ' (imported)'."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return 0, "That file is not a presets file."
    src = d.get("presets") if isinstance(d, dict) else None
    if not isinstance(src, dict):
        return 0, "That file is not a presets file."
    mine = _user()
    n = 0
    for name, v in src.items():
        if not isinstance(name, str) or not isinstance(v, dict):
            continue
        style = v.get("style") if isinstance(v.get("style"), dict) else {}
        adv = v.get("adv") if isinstance(v.get("adv"), dict) else {}
        nm = name if name not in BUILTIN else name + " (imported)"
        mine[nm[:60]] = {"style": style, "adv": clean_adv(adv)}
        n += 1
    if n and not _write(mine):
        return 0, "The presets could not be saved."
    return n, None


def default_name():
    n = sh_prefs.get("chart_preset")
    return n if n in names() else "Default"


def set_default(name):
    if name in names():
        sh_prefs.set_many({"chart_preset": name})
