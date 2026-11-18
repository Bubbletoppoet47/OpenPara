"""
sh_prefs.py - the few settings Sheets keeps for itself (in its own file, <user folder>/sheets/prefs.json): they are the person's, not a workbook's.

    get(key)  /  set_many({...})  /  on_change(fn)        ribbon_icon (pt), ribbon_text (pt), chart_preset (name of the style new charts start from)
    LIMITS                                                 the bounds of every number, so a box can never take a value that breaks the ribbon

The file is read when needed and written at once; a missing or damaged file reads as the defaults.  `use_folder(path)` points it somewhere else (tests).
"""
import json
import os

DEFAULTS = {"ribbon_icon": 20, "ribbon_text": 10, "chart_preset": "Default"}
LIMITS = {"ribbon_icon": (10, 48), "ribbon_text": (8, 20)}

_folder = None
_listeners = []
_cache = None


def use_folder(path):
    """Keeps the settings in `path` (a folder) instead of the user folder; None goes back to the user folder."""
    global _folder, _cache
    _folder = path
    _cache = None


def folder():
    if _folder:
        return _folder
    try:
        import paths
        base = paths.user_dir()
    except ImportError:
        base = os.path.join(os.path.expanduser("~"), ".openpara")
    return os.path.join(base, "sheets")


def _file():
    return os.path.join(folder(), "prefs.json")


def clamp(key, value):
    lo, hi = LIMITS.get(key, (None, None))
    if lo is None:
        return value
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULTS[key]
    return max(lo, min(hi, v))


def _load():
    global _cache
    if _cache is None:
        data = {}
        try:
            with open(_file(), "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                data = d
        except (OSError, ValueError):
            data = {}
        _cache = {k: (clamp(k, data[k]) if k in LIMITS and k in data else (data[k] if k in data and isinstance(data[k], str) else DEFAULTS[k]))
                  for k in DEFAULTS}
    return _cache


def get(key):
    return _load().get(key, DEFAULTS.get(key))


def set_many(values):
    """Changes the settings, saves them and tells the listeners which keys changed.  Returns the keys that changed."""
    cur = _load()
    changed = []
    for k, v in values.items():
        if k not in DEFAULTS:
            continue
        v = clamp(k, v) if k in LIMITS else (v if isinstance(v, str) else DEFAULTS[k])
        if cur.get(k) != v:
            cur[k] = v
            changed.append(k)
    if changed:
        try:
            os.makedirs(folder(), exist_ok=True)
            tmp = _file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f, indent=1)
            os.replace(tmp, _file())
        except OSError:
            pass                                     # the new values still hold for this session
        for fn in list(_listeners):
            try:
                fn(changed)
            except RuntimeError:                     # a window that has gone
                pass
    return changed


def reset():
    return set_many(dict(DEFAULTS))


def on_change(fn):
    _listeners.append(fn)


def off_change(fn):
    try:
        _listeners.remove(fn)
    except ValueError:
        pass
