"""
recent.py - what was opened lately, and where the file windows start.

Kept in the user's data folder (recent.json): the files and project folders of File > Open Recent and of the start page, newest first,
and the folder File > Open last used.  A path that is not there right now (a drive that is unplugged) stays in the list: it is shown as
"not found" and works again when the drive is back.  Nothing here ever touches the files themselves.

    add(path, kind)      put a file / project folder at the top ("Part", "Assembly", "1D FEA project" ...)
    items()              [{"path", "kind", "name", "folder", "missing"}], newest first
    remove(path)  clear()
    last_folder()  set_last_folder(path_of_what_was_opened)
"""
import json
import os

import paths

FILE = "recent.json"
MAX = 15


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def _load():
    try:
        with open(os.path.join(paths.user_dir(), FILE), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("items", []), list):
            d["items"] = [it for it in d.get("items", []) if isinstance(it, dict) and isinstance(it.get("path"), str)]
            return d
    except (OSError, ValueError):
        pass
    return {"items": [], "folder": ""}


def _save(d):
    try:
        tmp = os.path.join(paths.user_dir(), FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, os.path.join(paths.user_dir(), FILE))
    except OSError:
        pass                                              # a list of recent files is never worth an error message


def add(path, kind=""):
    if not path:
        return
    path = os.path.abspath(str(path).rstrip("/\\") or str(path))
    d = _load()
    old = next((it for it in d["items"] if _norm(it["path"]) == _norm(path)), None)
    d["items"] = [it for it in d["items"] if _norm(it["path"]) != _norm(path)]
    d["items"].insert(0, {"path": path, "kind": kind or (old or {}).get("kind", "")})
    del d["items"][MAX:]
    _save(d)


def remove(path):
    d = _load()
    d["items"] = [it for it in d["items"] if _norm(it["path"]) != _norm(path)]
    _save(d)


def clear():
    d = _load()
    d["items"] = []
    _save(d)


def items():
    out = []
    for it in _load()["items"]:
        p = it["path"]
        out.append({"path": p, "kind": it.get("kind", ""), "name": os.path.basename(p.rstrip("/\\")) or p, "folder": os.path.dirname(p.rstrip("/\\")),
                    "missing": not os.path.exists(p)})
    return out


def last_folder():
    """The folder a file window starts in: the one used last, when it is still there."""
    f = _load().get("folder") or ""
    return f if f and os.path.isdir(f) else ""


def set_last_folder(path):
    """`path` is something that was just opened or saved (a file or a project folder): the next file window starts in the folder it is in."""
    if not path:
        return
    f = os.path.dirname(os.path.abspath(str(path).rstrip("/\\") or str(path)))
    if f and os.path.isdir(f):
        d = _load()
        if d.get("folder") != f:
            d["folder"] = f
            _save(d)
