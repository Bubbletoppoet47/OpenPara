"""
vis_project.py - a Visualize project is a FOLDER (.gpv) with its own copy of the part / assembly, so it does not depend on the original:

    <name>.gpv/visualize.json     the looks, lights, floor, cameras, video path and output settings (format "openpara-visualize")
    <name>.gpv/source/            the copy of the part (.gpd) or assembly (.gpa, with every part it uses, paths rewritten to the copies)
    <name>.gpv/output/            where pictures and videos go unless another folder is chosen in Render > Folder
"""
import json
import os
import shutil

FORMAT = "openpara-visualize"
MARKER = "visualize.json"
SOURCE_DIR = "source"
OUTPUT_DIR = "output"
EXT = ".gpv"


def _unique(dirpath, name):
    base, ext = os.path.splitext(name)
    out, i = name, 1
    while os.path.exists(os.path.join(dirpath, out)):
        i += 1
        out = f"{base}_{i}{ext}"
    return out


def _pack_assembly(text, orig_dir, dest, done, missing, stack=()):
    """JSON text of an assembly (living in orig_dir) -> JSON text whose component paths point at flat copies made in `dest`."""
    d = json.loads(text)
    for c in d.get("components") or []:
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
            if key in stack:
                missing.append(p + " (loop)")
                continue
            with open(ap, encoding="utf-8") as f:
                sub = _pack_assembly(f.read(), os.path.dirname(ap), dest, done, missing, stack + (key,))
            name = _unique(dest, os.path.basename(ap))
            with open(os.path.join(dest, name), "w", encoding="utf-8") as f:
                f.write(sub)
        else:
            name = _unique(dest, os.path.basename(ap))
            shutil.copyfile(ap, os.path.join(dest, name))
        done[key] = name
        c["path"] = name
    d["sims"], d["renders"] = [], []
    return json.dumps(d, indent=1)


def pack_source(folder, text, orig_path, name=None):
    """Replaces <folder>/source with a copy of the model whose JSON is `text` (the live state of the open file, or the file read from disk).
    -> (path of the main file relative to the folder, [files that could not be found])."""
    ext = os.path.splitext(orig_path or "")[1].lower() or (".gpa" if '"components"' in text[:400] else ".gpd")
    name = name or (os.path.splitext(os.path.basename(orig_path))[0] if orig_path else "model")
    dest = os.path.join(folder, SOURCE_DIR)
    tmp = dest + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    missing = []
    try:
        if ext == ".gpa":
            body = _pack_assembly(text, os.path.dirname(os.path.abspath(orig_path)) if orig_path else os.getcwd(), tmp, {}, missing)
        else:
            d = json.loads(text)
            d["sims"], d["renders"] = [], []
            body = json.dumps(d, indent=1)
        main = _unique(tmp, name + ext)
        with open(os.path.join(tmp, main), "w", encoding="utf-8") as f:
            f.write(body)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)
    return f"{SOURCE_DIR}/{main}", missing


def write(folder, proj, main_rel):
    """Writes visualize.json; the model is stored relative to the folder, and the default output folder as blank (so the project can be moved)."""
    out = json.loads(json.dumps(proj))
    out["format"] = FORMAT
    out["source"] = main_rel
    if os.path.normcase(os.path.abspath(out["output"].get("folder") or "")) == os.path.normcase(os.path.abspath(os.path.join(folder, OUTPUT_DIR))):
        out["output"]["folder"] = ""
    os.makedirs(os.path.join(folder, OUTPUT_DIR), exist_ok=True)
    with open(os.path.join(folder, MARKER), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)


def read(folder):
    with open(os.path.join(folder, MARKER), encoding="utf-8") as f:
        proj = json.load(f)
    if proj.get("format") != FORMAT:
        raise ValueError("this folder is not a Visualize project")
    return proj


def source_file(folder, proj):
    return os.path.normpath(os.path.join(folder, proj["source"]))


def new_folder_name(model_path):
    base = os.path.splitext(model_path)[0] + "_visual"
    p, k = base + EXT, 2
    while os.path.exists(p):
        p = f"{base}_{k}{EXT}"
        k += 1
    return p
