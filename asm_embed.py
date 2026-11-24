"""asm_embed.py - components that live INSIDE the assembly file.  No Qt.

Normally a component of an assembly is a reference: the path of a part file (.gpd) or of another assembly (.gpa).  An assembly can instead keep its own copy of every
part it uses: the copy is stored in the assembly file ("parts": {key: {"kind", "name", "doc"}}) and the component's path is "embedded:<key>/<name>.gpd".  The assembly is
then ONE self-contained file; changing a component changes only this assembly's copy, and the original part file is not touched (and does not change the assembly).

  embed_file(asm, path)        a part / assembly file -> its copy in asm.parts; -> (component path, [warning])
  embed_references(asm, base)  every component that still refers to a file (an old .gpa) becomes embedded; -> [warning] (a file that is not there stays a reference)
  self_contained_text(path)    the JSON text of an assembly file with every component embedded (an assembly file inserted into another is inserted like this)
  flatten_to_files(asm, dir, name)  the other way round: an assembly that keeps its parts inside it written as ordinary files (what a simulation project folder wants)
"""
import json
import os

import asm_model as am


class EmbedError(Exception):
    pass


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as ex:
        raise EmbedError(f"{os.path.basename(path)} could not be read: {ex}")


def embed_file(asm, path, _seen=()):
    """-> (the path a component uses for the copy, [warnings])."""
    ap = os.path.normcase(os.path.abspath(path))
    if ap in _seen:
        raise EmbedError(f"{os.path.basename(path)} contains itself (through other assemblies).")
    name = os.path.splitext(os.path.basename(path))[0]
    if path.lower().endswith(".gpa"):
        text, warns = self_contained_text(path, _seen + (ap,))
        return asm.embed_part(name, "assembly", json.loads(text)), warns
    try:
        obj = json.loads(_read(path))
    except ValueError as ex:
        raise EmbedError(f"{os.path.basename(path)} is not a part file: {ex}")
    return asm.embed_part(name, "part", obj), []


def embed_references(asm, base_dir, _seen=()):
    """Turns the components that refer to files into embedded copies (the files are found relative to base_dir).  A file that is not there stays a reference
    and is named in the warnings.  -> [warning]."""
    warns = []
    for c in asm.components:
        if am.is_embedded(c["path"]):
            continue
        p = c["path"] if os.path.isabs(c["path"]) else os.path.normpath(os.path.join(base_dir, c["path"]))
        if not os.path.isfile(p):
            warns.append(f"{c['path']} was not found: '{c['name']}' stays a reference to it.")
            continue
        try:
            vpath, w = embed_file(asm, p, _seen)
        except EmbedError as ex:
            warns.append(f"'{c['name']}': {ex}")
            continue
        warns += w
        c["path"] = vpath
    return warns


def self_contained_text(path, _seen=()):
    """-> (the JSON text of the assembly file `path` with every component embedded, [warning])."""
    a = am.Assembly.from_json(_read(path))
    warns = embed_references(a, os.path.dirname(os.path.abspath(path)), _seen + (os.path.normcase(os.path.abspath(path)),))
    return a.to_json(), warns


def _unique(folder, name):
    base, ext = os.path.splitext(name)
    out, i = name, 1
    while os.path.exists(os.path.join(folder, out)):
        i += 1
        out = f"{base}_{i}{ext}"
    return out


def _file_name(name, default):
    n = "".join(ch if ch.isalnum() or ch in " -_()." else "_" for ch in str(name or "")).strip(" .")
    return n or default


def flatten_to_files(asm_obj, dest_dir, name):
    """An assembly that keeps its parts inside it (asm_obj = its JSON as an object) is written to dest_dir as ordinary files: every embedded part becomes <name>.gpd, every
    embedded assembly <name>.gpa (with its own parts the same way), and the assembly itself <name>.gpa with its components pointing at those files (plain relative names).
    A component that refers to a file stays as it is.  -> the path of the assembly file.  (A simulation project copies an assembly by reading such a file.)"""
    os.makedirs(dest_dir, exist_ok=True)
    a = am.Assembly.from_json(json.dumps(asm_obj))
    done = {}
    for c in a.components:
        if not am.is_embedded(c["path"]):
            continue
        key = am.embed_key(c["path"])
        if key not in done:
            ent = a.parts.get(key)
            if ent is None:
                raise EmbedError(f"'{c.get('name', '?')}': its copy ({key}) is missing from the assembly.")
            base = _file_name(ent.get("name"), "part")
            if ent.get("kind") == "assembly":
                sub = flatten_to_files(ent["asm"], dest_dir, base)
                done[key] = os.path.basename(sub)
            else:
                fn = _unique(dest_dir, base + ".gpd")
                with open(os.path.join(dest_dir, fn), "w", encoding="utf-8") as f:
                    json.dump(ent["doc"], f, indent=1)
                done[key] = fn
        c["path"] = done[key]
    a.parts = {}
    fn = _unique(dest_dir, _file_name(name, "assembly") + ".gpa")
    with open(os.path.join(dest_dir, fn), "w", encoding="utf-8") as f:
        f.write(a.to_json())
    return os.path.join(dest_dir, fn)
