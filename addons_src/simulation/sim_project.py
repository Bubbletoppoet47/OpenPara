"""
sim_project.py - the project folder of a simulation (no Qt).

A simulation is a PROJECT FOLDER named with the type of the simulation:
    bracket.gpb/   1D FEA          bracket.gpf/   2D FEA          bracket.gpc/   2D CFD          bracket.gpv/   3D FEA (the 3D add-on)
        simulation.json   the marker: {"format": "openpara-sim-<kind>", "kind", "source": {...}, "meta": {...}}
        state.sim         the setup, mesh and result (written by physics_store)
        source/           THE LOCAL COPY of what the simulation works on: a part (<name>.gpd), or an assembly (<name>.gpa) with the part files it
                          uses.  The simulation only ever reads this copy, never the original, which can be moved, renamed or deleted.
        profiles/         1D FEA: the local copies of OTHER parts whose sketches are member profiles (cross-sections).  One .gpd per part,
                          listed in the marker as "profiles": [{"key": file name, "name", "file", "orig", "imported"}].  Importing another
                          source does not touch them.
        study/            parametric studies (the Parametric Studies add-on)

Importing a source copies it into source/ (replacing the earlier copy).  Everything here is plain files and JSON, so it is easy to test.
"""
import json
import os
import shutil
import time

MARKER = "simulation.json"
STATE = "state.sim"
SOURCE_DIR = "source"
STUDY_DIR = "study"
PROFILE_DIR = "profiles"
EXT = {"beam": ".gpb", "fea": ".gpf", "cfd": ".gpc", "solid": ".gpv"}
LABEL = {"beam": "1D FEA", "fea": "2D FEA", "cfd": "2D CFD", "solid": "3D FEA"}
VERSION = 1


class ProjectError(Exception):
    pass


def fmt(kind):
    return f"openpara-sim-{kind}"


def ext_of(kind):
    return EXT[kind]


def kind_of_folder(folder):
    """The kind of the simulation project in `folder` ('beam', 'fea', ...), or None when it is not one."""
    try:
        with open(os.path.join(folder, MARKER), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    f_ = m.get("format", "") if isinstance(m, dict) else ""
    return f_[len("openpara-sim-"):] if f_.startswith("openpara-sim-") and f_[len("openpara-sim-"):] in EXT else None


def default_name(kind, source_name, folder=None):
    """A folder name for a new project: '<source name><ext>' (next to `folder` when given), numbered when it already exists."""
    base = "".join(c if c not in '<>:"/\\|?*' else "_" for c in (source_name or "simulation")).strip() or "simulation"
    name = base + EXT[kind]
    if folder is None:
        return name
    i = 1
    while os.path.exists(os.path.join(folder, name)):
        i += 1
        name = f"{base} {i}{EXT[kind]}"
    return os.path.join(folder, name)


def create(folder, kind):
    """Makes the project folder (it may exist but must be empty or already a project of this kind) and returns its manifest."""
    if kind not in EXT:
        raise ProjectError(f"unknown simulation kind '{kind}'")
    if os.path.exists(folder):
        have = kind_of_folder(folder)
        if have is None and (not os.path.isdir(folder) or os.listdir(folder)):
            raise ProjectError(f"'{os.path.basename(folder)}' already exists and is not a simulation project.")
        if have not in (None, kind):
            raise ProjectError(f"'{os.path.basename(folder)}' is a {LABEL[have]} project.")
        if have == kind:
            return read(folder)
    os.makedirs(folder, exist_ok=True)
    m = {"format": fmt(kind), "version": VERSION, "kind": kind, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "source": None,
         "meta": {"sid": None, "slice": None}}
    write(folder, m)
    return m


def read(folder):
    try:
        with open(os.path.join(folder, MARKER), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as ex:
        raise ProjectError(f"'{os.path.basename(folder)}' is not a simulation project ({ex}).")


def write(folder, m):
    tmp = os.path.join(folder, MARKER + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)
    os.replace(tmp, os.path.join(folder, MARKER))


def state_path(folder):
    return os.path.join(folder, STATE)


def study_dir(folder):
    d = os.path.join(folder, STUDY_DIR)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------------------------------------------- the local copy
def source_file(folder, m=None):
    """Absolute path of the project's copy of the source (a .gpd or .gpa), or None when nothing was imported yet."""
    m = m or read(folder)
    s = m.get("source")
    if not s or not s.get("file"):
        return None
    return os.path.normpath(os.path.join(folder, s["file"]))


def _unique(dirpath, name):
    base, ext = os.path.splitext(name)
    out, i = name, 1
    while os.path.exists(os.path.join(dirpath, out)):
        i += 1
        out = f"{base}_{i}{ext}"
    return out


def _pack_assembly(text, orig_dir, dest, done, missing, seen_stack=()):
    """Copies the files an assembly (given as JSON text, living in orig_dir) uses into `dest` and returns the JSON with its paths rewritten
    to the copies (relative, flat).  Sub-assemblies are packed the same way.  `done` maps original abs path -> copied file name."""
    d = json.loads(text)
    comps = d.get("components") or []
    for c in comps:
        p = c.get("path")
        if not p:
            continue
        ap = os.path.normpath(p if os.path.isabs(p) else os.path.join(orig_dir, p))
        key = os.path.normcase(ap)
        if key in done:
            c["path"] = done[key]
            continue
        if not os.path.isfile(ap):
            missing.append(p)
            continue
        if ap.lower().endswith(".gpa"):
            if key in seen_stack:
                missing.append(p + " (loop)")
                continue
            with open(ap, encoding="utf-8") as f:
                sub = _pack_assembly(f.read(), os.path.dirname(ap), dest, done, missing, seen_stack + (key,))
            name = _unique(dest, os.path.basename(ap))
            with open(os.path.join(dest, name), "w", encoding="utf-8") as f:
                f.write(sub)
        else:
            name = _unique(dest, os.path.basename(ap))
            shutil.copyfile(ap, os.path.join(dest, name))
        done[key] = name
        c["path"] = name
    d["sims"] = []                                  # the copy carries no links of its own
    d["renders"] = []
    return json.dumps(d, indent=1)


def import_source(folder, orig_path=None, text=None, name=None):
    """Copies a part (.gpd) or assembly (.gpa) into the project, replacing the earlier copy.  `text` = the live state of the file when it is
    open with unsaved edits (else the file on disk is read).  -> (manifest, [files that could not be found]).  The state of the simulation
    (state.sim) is NOT touched here: the caller decides what to keep."""
    m = read(folder)
    if text is None:
        if not orig_path or not os.path.isfile(orig_path):
            raise ProjectError("The file to import was not found.")
        with open(orig_path, encoding="utf-8") as f:
            text = f.read()
    ext = os.path.splitext(orig_path or "")[1].lower() or (".gpa" if '"components"' in text[:400] else ".gpd")
    if ext not in (".gpd", ".gpa"):
        raise ProjectError("Only a part (.gpd) or an assembly (.gpa) can be imported.")
    kind = "asm" if ext == ".gpa" else "part"
    name = name or (os.path.splitext(os.path.basename(orig_path))[0] if orig_path else "source")
    dest = os.path.join(folder, SOURCE_DIR)
    tmp = dest + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    missing = []
    main = name + ext
    try:
        if kind == "asm":
            body = _pack_assembly(text, os.path.dirname(os.path.abspath(orig_path)) if orig_path else os.getcwd(), tmp, {}, missing)
            main = _unique(tmp, main)
        else:
            d = json.loads(text)
            d["sims"], d["renders"] = [], []
            body = json.dumps(d, indent=1)
        with open(os.path.join(tmp, main), "w", encoding="utf-8") as f:
            f.write(body)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)
    m["source"] = {"type": kind, "name": name, "file": f"{SOURCE_DIR}/{main}", "orig": os.path.abspath(orig_path) if orig_path else None,
                   "imported": time.strftime("%Y-%m-%d %H:%M:%S")}
    m["meta"] = {"sid": None, "slice": None}
    write(folder, m)
    return m, missing


# ---------------------------------------------------------------------------------------------------------------- profile parts (1D FEA)
def profile_parts(folder, m=None):
    """[{"key", "name", "file", "orig", "imported"}]: the parts copied into the project for their profile sketches."""
    m = m or read(folder)
    return [dict(e) for e in (m.get("profiles") or []) if isinstance(e, dict) and e.get("key") and e.get("file")]


def profile_file(folder, key, m=None):
    """Absolute path of the copy of a profile part, or None when the project has no such part."""
    for e in profile_parts(folder, m):
        if e["key"] == key:
            return os.path.normpath(os.path.join(folder, e["file"]))
    return None


def _same_file(a, b):
    return bool(a) and bool(b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def import_profile_part(folder, orig_path=None, text=None, name=None, key=None):
    """Copies a part (.gpd) into profiles/ for its profile sketches.  A part that is already there (the same original file, or `key`) is
    replaced by the new copy and keeps its key, so the profile sketches taken from it stay linked.  `text` = the live state of the part when
    it is open with unsaved edits.  -> (manifest, the entry of the part)."""
    m = read(folder)
    if text is None:
        if not orig_path or not os.path.isfile(orig_path):
            raise ProjectError("The part to import was not found.")
        with open(orig_path, encoding="utf-8") as f:
            text = f.read()
    if orig_path and os.path.splitext(orig_path)[1].lower() not in ("", ".gpd"):
        raise ProjectError("Only a part (.gpd) can hold profile sketches.")
    try:
        d = json.loads(text)
    except ValueError as ex:
        raise ProjectError(f"The part could not be read ({ex}).")
    if not isinstance(d, dict) or "components" in d or "features" not in d:
        raise ProjectError("Only a part (.gpd) can hold profile sketches.")
    d["sims"], d["renders"] = [], []
    name = name or (os.path.splitext(os.path.basename(orig_path))[0] if orig_path else "profile")
    parts = [e for e in (m.get("profiles") or []) if isinstance(e, dict) and e.get("key")]
    old = next((e for e in parts if e["key"] == key), None) if key else None
    if old is None and orig_path:
        old = next((e for e in parts if _same_file(e.get("orig"), orig_path)), None)
    dest = os.path.join(folder, PROFILE_DIR)
    os.makedirs(dest, exist_ok=True)
    safe = "".join(c if c not in '<>:"/\\|?*' else "_" for c in name).strip() or "profile"
    fname = old["key"] if old else _unique(dest, safe + ".gpd")
    tmp = os.path.join(dest, fname + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, indent=1))
    os.replace(tmp, os.path.join(dest, fname))
    entry = {"key": fname, "name": name, "file": f"{PROFILE_DIR}/{fname}",
             "orig": os.path.abspath(orig_path) if orig_path else (old or {}).get("orig"), "imported": time.strftime("%Y-%m-%d %H:%M:%S")}
    m["profiles"] = [e for e in parts if e["key"] != fname] + [entry]
    write(folder, m)
    return m, entry


def remove_profile_part(folder, key):
    """Takes a profile part out of the project: its entry in the marker and its copy in profiles/."""
    m = read(folder)
    parts = [e for e in (m.get("profiles") or []) if isinstance(e, dict) and e.get("key")]
    gone = [e for e in parts if e["key"] == key]
    if not gone:
        return m
    m["profiles"] = [e for e in parts if e["key"] != key]
    write(folder, m)
    try:
        os.remove(os.path.join(folder, gone[0]["file"]))
    except OSError:
        pass
    return m
