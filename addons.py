"""
addons.py - optional parts of OpenPara that can be installed and removed without touching the core (modelling, sketching, assemblies,
STEP / STL exchange, units, settings and the updater are always there).

An add-on is a folder with  addon.json  and its Python modules:
    <program>/addons_src/<id>/        the copy that ships with every release (never imported directly)
    <user folder>/addons/<id>/        the installed copy; this folder is on sys.path while the add-on is installed
    <user folder>/addons.json         {"removed": [ids]}   add-ons the user took out (an update must not bring them back)

Start-up (startup()) puts a shipped add-on in place when it is missing (unless the user removed it) or older than the shipped one, and
adds every installed folder to sys.path.  install() / uninstall() do the same on request.  Your own files (.gps, .gpr, the material
library) are never touched: they live elsewhere and open again as soon as the add-on is installed again.
"""
import importlib
import json
import os
import shutil
import sys

import paths

SRC_DIR = os.path.join(paths.CODE_DIR, "addons_src")
MANIFEST = "addon.json"


def addons_dir():
    d = os.path.join(paths.user_dir(), "addons")
    os.makedirs(d, exist_ok=True)
    return d


def state_file():
    return os.path.join(paths.user_dir(), "addons.json")


def _read_state():
    try:
        with open(state_file(), encoding="utf-8") as f:
            s = json.load(f)
        if isinstance(s.get("removed"), list):
            return s
    except (OSError, ValueError, AttributeError):
        pass
    return {"removed": []}


def _write_state(s):
    tmp = state_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, state_file())


def _vkey(v):
    out = []
    for p in str(v).replace("-", ".").split("."):
        out.append(int(p) if p.isdigit() else 0)
    return tuple(out)


def _manifest(folder):
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            m = json.load(f)
        if m.get("id") and m.get("name"):
            m.setdefault("version", "0")
            m.setdefault("description", "")
            return m
    except (OSError, ValueError, AttributeError):
        pass
    return None


def shipped():
    """{id: manifest} of the add-ons that came with this copy of the program."""
    out = {}
    if os.path.isdir(SRC_DIR):
        for n in sorted(os.listdir(SRC_DIR)):
            m = _manifest(os.path.join(SRC_DIR, n))
            if m and m["id"] == n:
                out[n] = m
    return out


def installed_path(aid):
    return os.path.join(addons_dir(), aid)


def installed_manifest(aid):
    return _manifest(installed_path(aid))


def is_installed(aid):
    return installed_manifest(aid) is not None


def is_active(aid):
    """Installed and its folder is on sys.path (the modules can be imported)."""
    return is_installed(aid) and installed_path(aid) in sys.path


def status(aid):
    """'installed', 'update' (a newer one ships with this program) or 'not installed'."""
    m = installed_manifest(aid)
    if m is None:
        return "not installed"
    s = shipped().get(aid)
    if s and _vkey(s["version"]) > _vkey(m["version"]):
        return "update"
    return "installed"


def module_names(aid):
    d = installed_path(aid) if is_installed(aid) else os.path.join(SRC_DIR, aid)
    names = set()
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith(".py"):
                names.add(f[:-3])
            elif os.path.isdir(os.path.join(d, f)) and os.path.exists(os.path.join(d, f, "__init__.py")):
                names.add(f)
    return names


def owner_of_module(name):
    """The id of the installed add-on that provides module `name` (a module's __module__), or None."""
    top = name.split(".")[0]
    for aid in shipped():
        if top in module_names(aid):
            return aid
    return None


def _clean_trash():
    d = addons_dir()
    for n in os.listdir(d):
        if n.startswith(".trash-"):
            shutil.rmtree(os.path.join(d, n), ignore_errors=True)


def _copy_in(aid):
    """Copy the shipped add-on to the user folder, all or nothing."""
    src = os.path.join(SRC_DIR, aid)
    if not os.path.isdir(src):
        raise FileNotFoundError(f"The add-on '{aid}' is not part of this copy of OpenPara.")
    dest = installed_path(aid)
    tmp = dest + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if os.path.isdir(dest):
        _remove_dir(dest)
    os.replace(tmp, dest)


def _remove_dir(path):
    """Delete a folder; when a file is in use (Windows) move the folder aside and let the next start delete it."""
    shutil.rmtree(path, ignore_errors=True)
    if not os.path.exists(path):
        return True
    n = 0
    while True:
        trash = os.path.join(os.path.dirname(path), f".trash-{os.path.basename(path)}-{n}")
        if not os.path.exists(trash):
            break
        n += 1
    try:
        os.replace(path, trash)
        shutil.rmtree(trash, ignore_errors=True)
        return True
    except OSError:
        return False


def activate():
    for aid in list(shipped()):
        p = installed_path(aid)
        if is_installed(aid) and p not in sys.path:
            sys.path.insert(0, p)
    importlib.invalidate_caches()


def startup():
    """Called once when the program starts: tidy, put shipped add-ons in place or upgrade them, activate."""
    try:
        _clean_trash()
        removed = set(_read_state()["removed"])
        for aid in shipped():
            if aid in removed:
                continue
            if status(aid) in ("not installed", "update"):
                try:
                    _copy_in(aid)
                except Exception as ex:
                    sys.stderr.write(f"add-on {aid}: could not install: {ex}\n")
    finally:
        activate()


def install(aid):
    """Install (or update) a shipped add-on and make it importable at once."""
    if aid not in shipped():
        raise KeyError(f"unknown add-on '{aid}'")
    _copy_in(aid)
    s = _read_state()
    s["removed"] = [r for r in s["removed"] if r != aid]
    _write_state(s)
    for m in module_names(aid):                      # a stale failed import must not stick
        sys.modules.pop(m, None)
    activate()


def uninstall(aid):
    """Remove an installed add-on: its modules are dropped from memory, its folder is deleted. Returns True when the folder is gone."""
    p = installed_path(aid)
    names = module_names(aid)
    while p in sys.path:
        sys.path.remove(p)
    for n in list(sys.modules):
        if n.split(".")[0] in names:
            sys.modules.pop(n, None)
    ok = _remove_dir(p) if os.path.exists(p) else True
    s = _read_state()
    if aid not in s["removed"]:
        s["removed"].append(aid)
    _write_state(s)
    importlib.invalidate_caches()
    return ok
