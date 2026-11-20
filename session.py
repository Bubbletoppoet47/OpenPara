"""
session.py - which documents were open, so that an update (or a restart from the program) puts them back.

The window writes session.json in the user's data folder every time its tabs change:  the program version, the files and project folders that
are open (in tab order), the one in front, and whether the window was closed FOR a restart.  The next start reads it back:

    to_restore(data, version, on)   [{"path", "kind"}, ...], current path     what to reopen ('' / [] when nothing should be)

Tabs come back when the setting "Reopen my tabs after an update" is on AND the program is not the version that wrote the file (it was updated, by
the in-app update, by the installer or by a new Playground build) or it was closed for a restart.  A document that was never saved has no file, so it is
not in the list (the window asks to save it before an update restarts the program).

No Qt here, so it is tested without a window.
"""
import json
import os

import paths

FILE = "session.json"


def _file():
    return os.path.join(paths.user_dir(), FILE)


def read():
    """What the last run left: {"version": str, "restart": bool, "tabs": [{"path", "kind"}], "current": str}.  {} when there is nothing usable."""
    try:
        with open(_file(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    tabs = []
    for t in d.get("tabs") if isinstance(d.get("tabs"), list) else []:
        if isinstance(t, dict) and isinstance(t.get("path"), str) and t["path"]:
            tabs.append({"path": t["path"], "kind": str(t.get("kind") or "")})
    return {"version": str(d.get("version") or ""), "restart": bool(d.get("restart")), "tabs": tabs,
            "current": d["current"] if isinstance(d.get("current"), str) else ""}


def write(tabs, current, version, restart=False):
    """Keeps the list (an atomic write; a failure is not worth an error: the list is a convenience)."""
    d = {"version": str(version), "restart": bool(restart), "current": current or "",
         "tabs": [{"path": str(t["path"]), "kind": str(t.get("kind") or "")} for t in tabs]}
    try:
        tmp = _file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, _file())
    except OSError:
        pass


def to_restore(data, version, on=True):
    """-> (tabs to reopen, the path to bring to the front).  Nothing when the setting is off, when the list is empty, or when this is the same version
    that wrote it and it was not closed for a restart (a normal quit, or a crash, starts empty as it always did)."""
    if not on or not data or not data.get("tabs"):
        return [], ""
    if data.get("version") == str(version) and not data.get("restart"):
        return [], ""
    return list(data["tabs"]), data.get("current") or ""
