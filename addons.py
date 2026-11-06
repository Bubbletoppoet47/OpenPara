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
Your own files (simulation project folders, .gpr, the material library) are never touched by installing or uninstalling.
"""
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

import channel
import paths

SRC_DIR = os.path.join(paths.CODE_DIR, "addons_src")
MANIFEST = "addon.json"
REPO = "Bubbletoppoet47/OpenPara"

# what the dialog and the "install it?" questions show before anything is downloaded (tests keep it equal to addons_src/*/addon.json)
CATALOG = {
    "partgen": {"name": "Part Generator",
                "description": "Gears (spur, helical, herringbone), gear systems and other parts made from a few parameters. Parts made with it "
                               "need it to be rebuilt."},
    "truss": {"project_marker": {"marker": "project.json", "format": "openpara-truss"},
              "name": "Truss Generator",
              "description": "Builds the members of a truss from the lines of a sketch: each member is a profile extruded to its longest length with "
                             "angled cuts. Exports a cut list. Opens .truss files and truss project folders."},
    "annotator": {"project_marker": {"marker": "manifest.json"},
                  "name": "General Classification Annotator",
                  "description": "Draw boxes on photos and video frames, pick LiDAR distances, pre-label with YOLO models downloaded from GitHub, hand a "
                                 "dataset to someone as a zip (and merge theirs into yours), annotate from a tablet. An annotator project is a folder "
                                 "with its dataset inside."},
    "render": {"project_marker": {"marker": "visualize.json", "format": "openpara-visualize"},
               "name": "Renderer",
               "description": "Visualize: Previs, a live lit Preview and ray-traced Renders (pictures and videos) of a part or assembly, with sun, lights, floor and cameras. A Visualize project is a folder (.gpv) with its own copy of the model."},
    "simulation": {"name": "Simulation (1D FEA, 2D FEA, 2D CFD)",
                   "description": "Frames and trusses (1D FEA), plane stress / strain FEA (2D FEA) and 2D CFD of a sketch or a slice of a part or "
                                  "assembly, with animation export. Each simulation is a project folder (.gpb, .gpf, .gpc) with its own copy of the part. "
                                  "Needs gmsh for meshing.",
                   "project_marker": {"marker": "simulation.json"}},
    "annotator_gimble": {"name": "Gimble sessions for the Annotator",
                         "description": "Adds File > Import Gimble Session... to the Annotator: sessions recorded by the Gimble rig (camera + LiDAR) "
                                        "become sets of photos with their depth. Needs the Annotator add-on."},
    "trainer": {"project_marker": {"marker": "training.json", "format": "openpara-training"},
                "name": "Trainer",
                "description": "Merge annotator datasets (zips) into one training project, choose training and validation sets and distortions, and "
                               "train a YOLO model in the background; the result is saved as a model version the Annotator lists. Needs the Annotator "
                               "add-on, and torch, ultralytics and (to be practical) a GPU in the Python you train with. A training project is a "
                               ".training folder."},
}


# files the program opens through an add-on although the add-on has no document tab of its own: extension -> (add-on id, name in the Open dialog)
OPENABLE = {}


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
        m.setdefault("id", os.path.basename(os.path.normpath(folder)))        # the folder name is the id when the file does not say
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


def dev_dir():
    """A folder of add-ons that are used where they are (never copied, never removed): set OPARA_DEV_ADDONS to it.  Used by the playground to
    run the real program with its own add-ons next to the shipped ones; a normal start does not have it."""
    d = os.environ.get("OPARA_DEV_ADDONS")
    if d and os.path.isdir(d):
        return os.path.abspath(d)
    return channel.dev_addons_dir()                      # a playground build carries its own dev_addons/ folder


def dev_ids():
    d = dev_dir()
    if not d:
        return []
    return [n for n in sorted(os.listdir(d)) if _manifest(os.path.join(d, n)) is not None]


def is_dev(aid):
    return aid in dev_ids()


def known():
    """All add-on ids that can be installed: the catalog plus anything in the program folder (and the development folder, when set)."""
    ids = list(CATALOG)
    for a in list(shipped()) + dev_ids():
        if a not in ids:
            ids.append(a)
    return ids


def project_hint(folder):
    """The id of a catalog add-on that is NOT installed and whose project folder `folder` looks like (by its marker file), else None."""
    for aid, c in CATALOG.items():
        pm = c.get("project_marker")
        if not pm or is_installed(aid):
            continue
        mk = os.path.join(folder, pm["marker"])
        if not os.path.isfile(mk):
            continue
        if pm.get("format"):
            try:
                with open(mk, encoding="utf-8") as f:
                    if json.load(f).get("format") != pm["format"]:
                        continue
            except (OSError, ValueError, AttributeError):
                continue
        return aid
    return None


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
    if is_dev(aid):
        return os.path.join(dev_dir(), aid)
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
    if is_dev(aid):
        return "installed"
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
    sh = channel.shared_dir()                            # code the playground's dev add-ons share
    if sh and sh not in sys.path:
        sys.path.insert(0, sh)
    for aid in known():
        p = installed_path(aid)
        if is_installed(aid):
            for q in (os.path.join(p, "site"), p):
                if os.path.isdir(q) and q not in sys.path:
                    sys.path.insert(0, q)
    importlib.invalidate_caches()


def outdated():
    """Ids of the installed add-ons that are older than this program (they are not updated by themselves)."""
    return [a for a in known() if not is_dev(a) and status(a) == "update"]


def update_prompt_declined():
    """True when the person already said 'not now' to the start-up update question for this version of the program."""
    import version
    return _read_state().get("declined_update") == version.__version__


def set_update_prompt_declined(on=True):
    import version
    s = _read_state()
    if on:
        s["declined_update"] = version.__version__
    else:
        s.pop("declined_update", None)
    _write_state(s)


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


def register_extensions(ext):
    """Tell the core (ext.py) which add-ons are active and let those that extend the Part / Assembly windows register.  Safe to call again
    after an add-on was installed or removed."""
    ext.FEATURES.clear()
    ext.HOOKS.clear()
    for aid in known():
        on = is_active(aid)
        ext.mark_present(aid, on)
        m = installed_manifest(aid) if on else None
        if m and m.get("extension"):
            mod = importlib.import_module(m["extension"])
            mod.register(ext)


def tab_kinds():
    """{kind: spec} of the document tabs the active add-ons offer (their manifest "tabs"); spec has aid, label, short, module, factory, file_types ..."""
    out = {}
    for aid in known():
        m = installed_manifest(aid) if is_active(aid) else None
        for t in (m or {}).get("tabs", []):
            if t.get("in_program") is False:                       # a tab that only the playground's own window needs (the program has Part / Assembly itself)
                continue
            out[t["kind"]] = dict(t, aid=aid)
    return out


# ---------------------------------------------------------------- getting an add-on

def release_base():
    b = os.environ.get("OPARA_ADDON_BASE")
    if b:
        return b if b.endswith("/") else b + "/"
    import version
    return f"https://github.com/{REPO}/releases/download/{channel.tag_for(version.__version__)}/"


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


def _importable_without(mod, aid=None):
    """Whether `mod` can be imported from somewhere other than the installed copy of add-on `aid`.  That copy (and its site/ folder) is about to be
    replaced, so what only it has does not count; modules that are already loaded do not count either (the path is searched, sys.modules is not)."""
    skip = []
    if aid:
        p = installed_path(aid)
        skip = [os.path.normcase(os.path.realpath(q)) for q in (p, os.path.join(p, "site"))]
    path = [q for q in sys.path if os.path.normcase(os.path.realpath(q or ".")) not in skip]
    return importlib.machinery.PathFinder.find_spec(mod.split(".")[0], path) is not None or mod in sys.builtin_module_names


def _missing_packages(manifest, aid=None):
    out = []
    for r in manifest.get("requires", []):
        mod = r.get("import") or r["pip"].split("=")[0].replace("-", "_")
        if os.environ.get("OPARA_ADDON_FORCE_PIP") or not _importable_without(mod, aid):
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
    if is_dev(aid):                                                        # used where it is: nothing to install
        if activate_now:
            activate()
        return
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
        pins = _missing_packages(m, aid)           # an update must bring the packages the OLD copy had too: its folder is removed below
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
    if is_dev(aid):                                                        # a development add-on is the folder you work in: never deleted
        return False
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
