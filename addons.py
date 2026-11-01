"""
addons.py - optional parts of OpenPara that are installed (downloaded) and removed on request; the core (modelling, sketching, assemblies,
STEP / STL exchange, units, settings, the updater) is always there.

An add-on is a folder with  addon.json  and its Python modules, and may list pip packages that only it needs ("requires").
    <user folder>/addons/<id>/          the installed add-on; this folder and its  site/  sub-folder are on sys.path while it is installed
    <user folder>/addons/<id>/site/     the packages it needs that the base does not have (pip --target, so uninstalling removes them too)
    <user folder>/addons.json           {"removed": [ids]}   (only used for add-ons that ship inside the program, see below)

Where an add-on comes from:
  * download: the GitHub release of this version has  addons-index.json  and one  addon-<id>.zip  per add-on (built by tools/build_addons.py).
    OPARA_ADDON_BASE overrides the release address (tests, mirrors; a file:// address works).
  * the program folder: a  addons_src/<id>/  folder next to this file (a source checkout) is used first and, at start, installed or upgraded
    by startup(), so a developer's copy keeps working without a network.
Your own files (.gps, .gpr, the material library) are never touched by installing or uninstalling.
"""
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

import paths

SRC_DIR = os.path.join(paths.CODE_DIR, "addons_src")
MANIFEST = "addon.json"
REPO = "Bubbletoppoet47/OpenPara"

# what the dialog and the "install it?" questions show before anything is downloaded (tests keep it equal to addons_src/*/addon.json)
CATALOG = {
    "simulation": {"name": "Simulation",
                   "description": "1D FEA (frames and trusses), 2D FEA (plane stress / strain) and 2D CFD of a sketch or a slice of a part or "
                                  "assembly, with the material library and the result viewer. Saved simulations (.gps) need it."},
    "render": {"name": "Renderer",
               "description": "Render Studio: photorealistic pictures and videos of a part or assembly with sun, lights, floor and cameras. "
                              "Saved renders (.gpr) need it."},
}


class AddonError(Exception):
    pass


class Cancelled(AddonError):
    pass


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
            m.setdefault("requires", [])
            return m
    except (OSError, ValueError, AttributeError):
        pass
    return None


def shipped():
    """{id: manifest} of the add-ons that sit in the program folder (a source checkout); empty for the installed program."""
    out = {}
    if os.path.isdir(SRC_DIR):
        for n in sorted(os.listdir(SRC_DIR)):
            m = _manifest(os.path.join(SRC_DIR, n))
            if m and m["id"] == n:
                out[n] = m
    return out


def known():
    """All add-on ids that can be installed: the catalog plus anything in the program folder."""
    ids = list(CATALOG)
    for a in shipped():
        if a not in ids:
            ids.append(a)
    return ids


def info(aid):
    """{'name','description'} for the dialogs."""
    m = shipped().get(aid) or CATALOG.get(aid) or {"name": aid, "description": ""}
    return {"name": m["name"], "description": m["description"]}


def target_version():
    """The add-on version that fits this copy of the program."""
    s = shipped()
    if s:
        return max((m["version"] for m in s.values()), key=_vkey)
    import version
    return version.__version__


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
    """'installed', 'update' (the add-on is older than this program) or 'not installed'."""
    m = installed_manifest(aid)
    if m is None:
        return "not installed"
    if _vkey(target_version()) > _vkey(m["version"]):
        return "update"
    return "installed"


def module_names(aid):
    """Top-level module names of the add-on's own code (not its packages)."""
    names = set()
    for d in (installed_path(aid), os.path.join(SRC_DIR, aid)):
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".py"):
                    names.add(f[:-3])
    return names


def owner_of_module(name):
    """The id of the add-on that provides module `name` (a class's __module__), or None."""
    top = name.split(".")[0]
    for aid in known():
        if top in module_names(aid):
            return aid
    return None


def _remove_dir(path):
    """Delete a folder; when a file is in use (Windows) move the folder aside, or at least leave it without a manifest: start-up finishes."""
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
        return not os.path.exists(path)
    except OSError:
        return False


def _clean_leftovers():
    """Folders of removed add-ons that could not be deleted while the program ran, and unfinished installs."""
    d = addons_dir()
    for n in os.listdir(d):
        p = os.path.join(d, n)
        if not os.path.isdir(p):
            continue
        if n.startswith(".trash-") or n.endswith(".new") or n.startswith(".dl-") or _manifest(p) is None:
            shutil.rmtree(p, ignore_errors=True)
    for n in os.listdir(d):
        if n.startswith(".dl-") and os.path.isfile(os.path.join(d, n)):
            try:
                os.remove(os.path.join(d, n))
            except OSError:
                pass


def activate():
    for aid in known():
        p = installed_path(aid)
        if is_installed(aid):
            for q in (os.path.join(p, "site"), p):
                if os.path.isdir(q) and q not in sys.path:
                    sys.path.insert(0, q)
    importlib.invalidate_caches()


def startup():
    """Called once when the program starts: tidy, put add-ons that ship in the program folder in place (or upgrade them), activate."""
    try:
        _clean_leftovers()
        removed = set(_read_state()["removed"])
        for aid in shipped():
            if aid in removed:
                continue
            if status(aid) in ("not installed", "update"):
                try:
                    install(aid, activate_now=False)
                except Exception as ex:
                    sys.stderr.write(f"add-on {aid}: could not install: {ex}\n")
    finally:
        activate()


# ---------------------------------------------------------------- getting an add-on

def release_base():
    b = os.environ.get("OPARA_ADDON_BASE")
    if b:
        return b if b.endswith("/") else b + "/"
    import version
    return f"https://github.com/{REPO}/releases/download/v{version.__version__}/"


def _open(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "OpenPara"})
    return urllib.request.urlopen(req, timeout=timeout)


def _say(progress, text, frac=None):
    if progress is not None and progress(text, frac) is False:
        raise Cancelled("cancelled")


def _download(url, dest, progress, label):
    try:
        with _open(url) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                _say(progress, f"{label} {got / 1e6:.1f} MB" + (f" of {total / 1e6:.1f} MB" if total else ""), (got / total) if total else None)
    except Cancelled:
        raise
    except Exception as ex:
        raise AddonError(f"Could not download {label.lower()} ({url}): {ex}. Add-ons are downloaded from GitHub, so this needs an internet connection.")


def _safe_extract(zpath, dest):
    root = os.path.realpath(dest)
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            t = os.path.realpath(os.path.join(dest, n))
            if t != root and not t.startswith(root + os.sep):
                raise AddonError("The add-on file contains an unsafe path.")
        z.extractall(dest)


def _missing_packages(manifest):
    out = []
    for r in manifest.get("requires", []):
        mod = r.get("import") or r["pip"].split("=")[0].replace("-", "_")
        if os.environ.get("OPARA_ADDON_FORCE_PIP") or importlib.util.find_spec(mod) is None:
            out.append(r["pip"])
    return out


def _unpack_wheel(wheel, site):
    """Unpack a wheel into `site` the way an install would, without pip's --target (which loses a wheel's data/lib files on Windows, e.g.
    gmsh's DLL). purelib / platlib and data files all go below `site`; scripts, headers and docs are left out."""
    root = os.path.realpath(site)
    with zipfile.ZipFile(wheel) as z:
        for info_ in z.infolist():
            n = info_.filename
            if n.endswith("/"):
                continue
            parts = n.split("/")
            if parts[0].endswith(".data"):
                if len(parts) < 3 or parts[1] not in ("purelib", "platlib", "data"):
                    continue
                if parts[1] == "data" and parts[2] in ("include", "share"):
                    continue
                parts = parts[2:]
            if n.endswith(".dll.lib"):                                      # Windows import library: only needed to link against it
                continue
            dest = os.path.realpath(os.path.join(site, *parts))
            if not dest.startswith(root + os.sep):
                raise AddonError("A package file contains an unsafe path.")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info_) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def _pip_install(pins, target, progress):
    """Download the wheels of `pins` (pip download, no dependencies - the add-on lists all it needs) and unpack them into `target`.
    The program's own python runs pip; it is polled so the window stays alive and can cancel."""
    os.makedirs(target, exist_ok=True)
    wheels = tempfile.mkdtemp(prefix="opara_whl_")
    try:
        cmd = [paths.python_exe(), "-m", "pip", "download", "--dest", wheels, "--no-deps", "--only-binary=:all:",
               "--disable-pip-version-check", "--no-input"] + list(pins)
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000                              # CREATE_NO_WINDOW
        log = tempfile.TemporaryFile()
        p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, **kw)
        try:
            while p.poll() is None:
                _say(progress, "Downloading " + ", ".join(x.split("==")[0] for x in pins) + " ...")
                try:
                    p.wait(0.3)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            p.kill()
            raise
        if p.returncode != 0:
            log.seek(0)
            tail = log.read().decode("utf-8", "replace")[-1500:]
            raise AddonError("Downloading the packages failed (needs an internet connection):\n" + tail)
        for w in sorted(os.listdir(wheels)):
            if w.endswith(".whl"):
                _say(progress, f"Unpacking {w.split('-')[0]} ...")
                _unpack_wheel(os.path.join(wheels, w), target)
    finally:
        shutil.rmtree(wheels, ignore_errors=True)


def _fetch_folder(aid, work, progress):
    """Put the add-on's files (addon.json + modules) into `work`; from the program folder when it has them, else from the release."""
    src = os.path.join(SRC_DIR, aid)
    if os.path.isdir(src) and _manifest(src):
        shutil.copytree(src, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return
    base = release_base()
    _say(progress, "Looking for the add-on ...")
    idx_path = work + ".index.json"
    _download(base + "addons-index.json", idx_path, progress, "The add-on list")
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)
    os.remove(idx_path)
    ent = (idx.get("addons") or {}).get(aid)
    if not ent:
        raise AddonError(f"The add-on '{aid}' is not part of this release.")
    zpath = work + ".zip"
    _download(base + ent["file"], zpath, progress, f"{info(aid)['name']} add-on")
    h = hashlib.sha256()
    with open(zpath, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if ent.get("sha256") and h.hexdigest() != ent["sha256"]:
        os.remove(zpath)
        raise AddonError("The downloaded add-on is damaged (checksum differs). Try again.")
    os.makedirs(work)
    _safe_extract(zpath, work)
    os.remove(zpath)


def install(aid, progress=None, activate_now=True):
    """Install or update an add-on. progress(text, fraction_or_None) may return False to cancel (Cancelled is raised, nothing is changed)."""
    if aid not in known():
        raise KeyError(f"unknown add-on '{aid}'")
    ad = addons_dir()
    work = os.path.join(ad, f".dl-{aid}")
    shutil.rmtree(work, ignore_errors=True)
    for extra in (work + ".index.json", work + ".zip"):
        try:
            os.remove(extra)
        except OSError:
            pass
    try:
        _fetch_folder(aid, work, progress)
        m = _manifest(work)
        if not m or m["id"] != aid:
            raise AddonError(f"The downloaded file is not the add-on '{aid}'.")
        pins = _missing_packages(m)
        if pins:
            _pip_install(pins, os.path.join(work, "site"), progress)
        dest = installed_path(aid)
        new = dest + ".new"
        shutil.rmtree(new, ignore_errors=True)
        os.replace(work, new)
        if os.path.isdir(dest):
            _unload(aid)
            if not _remove_dir(dest):
                raise AddonError("The old copy of the add-on is in use. Restart OpenPara and try again.")
        os.replace(new, dest)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(installed_path(aid) + ".new", ignore_errors=True)
        for extra in (work + ".index.json", work + ".zip"):
            try:
                os.remove(extra)
            except OSError:
                pass
        raise
    s = _read_state()
    s["removed"] = [r for r in s["removed"] if r != aid]
    _write_state(s)
    for n in module_names(aid):                      # a stale failed import must not stick
        sys.modules.pop(n, None)
    if activate_now:
        activate()


def _unload(aid):
    p = os.path.realpath(installed_path(aid))
    for q in (os.path.join(installed_path(aid), "site"), installed_path(aid)):
        while q in sys.path:
            sys.path.remove(q)
    for n, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and os.path.realpath(f).startswith(p + os.sep):
            sys.modules.pop(n, None)
    importlib.invalidate_caches()


def uninstall(aid):
    """Remove an installed add-on with its packages: modules dropped from memory, folder deleted. True when the folder is gone; otherwise the
    add-on is already marked as removed and the rest is deleted at the next start."""
    p = installed_path(aid)
    _unload(aid)
    mf = os.path.join(p, MANIFEST)
    if os.path.exists(mf):
        try:
            os.remove(mf)                                                  # from now on it counts as not installed, whatever else happens
        except OSError:
            pass
    ok = _remove_dir(p) if os.path.exists(p) else True
    s = _read_state()
    if aid not in s["removed"]:
        s["removed"].append(aid)
    _write_state(s)
    return ok
