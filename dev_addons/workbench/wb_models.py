"""wb_models.py - the models of a workbench project: where they are kept, and how the blocks that use them find them.  No Qt here.

A model is a .pt file with its information (a .json: kind, size, created, trainer, classes, scores, based_on; the annotator's model_library format).  In a project file a model is an
ENTRY of node.data["models"] of the block that holds it:

    {"file": "Medium_2026-10-08_1530_Ian.pt", "key": "assist" | "scratch", "bytes": n, "info": {...},
     "stored": "inside", "blob": {"b64": ...}}        the file is INSIDE the project file (up to MODEL_LIMIT)
     "stored": "linked", "link": {"abs", "rel"}        the file is kept next to the project (bigger than MODEL_LIMIT), and the person was told

Three kinds of block hold models: a Trainer (the models it trained or was given), Trained models (the ones imported into it) and Model testing (the ones dropped on it).  A block that
takes models from other blocks does not copy them (a model would be in the file twice): models_of() follows the wires.  The models in the shared Models folder of the Annotator
(the ones downloaded from GitHub, and any a Trainer saved there before) are listed by Trained models as "shared" entries and are never copied into a project.
"""
import hashlib
import json
import os
import shutil
import time

import wb_project as wp

MODEL_LIMIT = 500 * 1024 * 1024                 # a model up to this many bytes is kept inside the project file, a bigger one is linked
KEYS = ("assist", "scratch")
FOLDERS = {"assist": "Assist", "scratch": "Scratch"}
KIND_TEXT = {"assist": "Classes + boxes", "scratch": "Classes + boxes + distance"}
STORED_TEXT = {"inside": "Inside the project", "linked": "Linked", "shared": "GitHub / shared folder"}
HOLDERS = ("trainer", "trained_models", "model_test")      # the kinds of block that hold models of their own


def mb(n):
    return f"{n / (1 << 20):.0f} MB" if n >= (1 << 20) else f"{n / 1024:.0f} KB"


def libs():
    """(model_library, trainer_core) or (None, None) when the Annotator / Trainer add-ons are not there."""
    try:
        import trainer_core as tc
        return tc.libs()[3], tc
    except Exception:                                        # noqa: BLE001
        return None, None


def linked_folder(tab):
    """Where a model that is too big for the project file is written: next to the project file when it has one, else in the user's Trainer folder."""
    if tab.path:
        stem = os.path.splitext(os.path.basename(tab.path))[0]
        return os.path.join(os.path.dirname(os.path.abspath(tab.path)), f"{stem} models")
    _ml, tc = libs()
    base = tc.user_dir() if tc is not None else os.path.join(os.path.expanduser("~"), ".openpara")
    return os.path.join(base, "Trainer", "Linked models")


def key_of(path):
    """'scratch' for a model with a distance model (a detector with one added, or the earlier kind), else 'assist'.  Read without torch."""
    _ml, tc = libs()
    return "scratch" if tc is not None and tc.checkpoint_kind(path) in ("two", "old") else "assist"


def info_of(path, key):
    """The information of a model file: the .json next to it when it has one, else what can be said without loading it (a model file can run code when it is loaded)."""
    ml, _tc = libs()
    info = ml.read_info(path) if ml is not None else None
    if info:
        return dict(info)
    return {"format": getattr(ml, "FORMAT", "gimble-model-v1"), "kind": key, "size": None, "created": os.path.getmtime(path), "trainer": None, "classes": None,
            "scores": None, "based_on": None, "pasted": True}


# ---------------------------------------------------------------------------------------------------------------------------- keeping a model
def store_file(tab, node, pt, key=None, info=None):
    """Takes the model file `pt` into the block `node`: INSIDE the project up to MODEL_LIMIT, else LINKED (copied to linked_folder, and the person is told).
    -> the entry, or None when the block has this model already (same file name and size)."""
    key = key or key_of(pt)
    fn = os.path.basename(pt)
    lst = node.data.setdefault("models", [])
    size = os.path.getsize(pt)
    info = dict(info) if info else info_of(pt, key)
    old = next((m for m in lst if m["file"] == fn and m.get("key") == key), None)
    if old is not None and old.get("bytes") == size:
        return None
    entry = {"file": fn, "key": key, "bytes": size, "info": info}
    if size <= MODEL_LIMIT:
        entry["stored"], entry["blob"] = "inside", wp.pack_file(pt)
    else:
        dest = linked_folder(tab)
        os.makedirs(dest, exist_ok=True)
        target = os.path.join(dest, fn)
        if os.path.abspath(target) != os.path.abspath(pt):
            shutil.copyfile(pt, target)
        entry["stored"], entry["link"] = "linked", wp.rel_link(target, tab.path)
        tab.note(f"{node.label} {node.title}: the model {fn} is {mb(size)}, over the {mb(MODEL_LIMIT)} limit for a model kept inside the project, so it is linked: it is in "
                 f"{dest}. Keep that folder with the project.")
    if old is not None:
        lst[lst.index(old)] = entry
    else:
        lst.append(entry)
    return entry


def entry_path(tab, node_id, entry):
    """The model file of an entry as a path on disk: a linked or shared model is where it is (None when that file is gone), one inside the project is written once into the
    workspace (and not again while the same)."""
    if entry.get("stored") in ("linked", "shared"):
        p = entry.get("path") or wp.resolve_link(entry.get("link") or {}, tab.path)
        return p if p and os.path.isfile(p) else None
    blob = entry.get("blob")
    if not isinstance(blob, dict):
        return None
    d = os.path.join(tab.workspace, "model_files", hashlib.sha1(f"{node_id}/{entry['file']}".encode()).hexdigest()[:12])
    p = os.path.join(d, wp.safe_name(entry["file"]))
    if not (os.path.isfile(p) and os.path.getsize(p) == entry.get("bytes")):
        shutil.rmtree(d, ignore_errors=True)
        wp.unpack_file(blob, d, os.path.basename(p))
    return p


def write_info(ml, pt, info):
    """The .json beside a model file."""
    if isinstance(info, dict) and info:
        with open(ml.info_path(pt), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)


def export_entry(tab, node_id, entry, dest):
    """Writes a model out as a file: the .pt as `dest` and its information beside it.  -> the .pt written."""
    ml, _tc = libs()
    src = entry_path(tab, node_id, entry)
    if src is None:
        raise ValueError(f"The file of {entry['file']} is not there ({(entry.get('link') or {}).get('abs', 'it is linked')}).")
    if not dest.lower().endswith(".pt"):
        dest += ".pt"
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".part"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)
    if ml is not None:
        write_info(ml, dest, entry.get("info"))
    return dest


# ---------------------------------------------------------------------------------------------------------------------------- finding models
SIZE_NAMES = {"n": "Nano", "s": "Small", "m": "Medium", "l": "Large", "x": "Extra large"}


def size_text(size):
    """'Small' for 's' (what the Annotator's model list says); a size that is not a letter (a network's own description) is shown as it is."""
    return SIZE_NAMES.get(size, str(size)) if size else ""


def describe(entry, node=None, source="", origin="own"):
    """The entry as one row of a list: the fields the windows show (the entry itself stays what the project file holds).
    origin: "own" (kept in the block that lists it), "wired" (in a block wired into it), "shared" (the shared Models folder)."""
    info = entry.get("info") or {}
    sc = info.get("scores") or {}
    key = entry.get("key") or info.get("kind") or "assist"
    return {"id": f"{node.id if node is not None else 'shared'}:{key}:{entry['file']}", "node": node.id if node is not None else "", "file": entry["file"],
            "name": entry.get("name") or os.path.splitext(entry["file"])[0], "key": key, "kind": KIND_TEXT.get(key, key), "size": info.get("size") or "",
            "size_text": size_text(info.get("size")), "created": info.get("created") or 0, "classes": info.get("classes") or [], "scores": sc, "trainer": info.get("trainer") or "",
            "based_on": info.get("based_on") or "", "stored": entry.get("stored", "inside"), "bytes": entry.get("bytes") or 0, "from": source, "origin": origin, "entry": entry}


_SHARED = {"sig": None, "rows": []}


def shared_signature():
    """What shows that the shared Models folder changed (the names, sizes and times of its model files): reading the list again is cheap, listing it for every look is not."""
    ml, tc = libs()
    if ml is None:
        return ()
    sig = []
    d = tc.annotator_models_dir()
    for key in KEYS:
        sub = ml.folder_path(d, key)
        if os.path.isdir(sub):
            for f in sorted(os.listdir(sub)):
                if f.lower().endswith((".pt", ".json")):
                    try:
                        s = os.stat(os.path.join(sub, f))
                        sig.append((key, f, s.st_size, int(s.st_mtime)))
                    except OSError:
                        pass
    return tuple(sig)


def shared_entries():
    """The models in the shared Models folder of the Annotator (GitHub downloads, and what a Trainer saved there on its own): read-only 'shared' entries."""
    ml, tc = libs()
    if ml is None:
        return []
    sig = shared_signature()
    if _SHARED["sig"] == sig:
        return _SHARED["rows"]
    out = []
    d = tc.annotator_models_dir()
    for key in KEYS:
        for v in ml.list_versions(d, key):
            info = ml.read_info(v["path"]) or {"size": v["size"], "created": v["ts"], "trainer": v["trainer"], "classes": v["classes"], "scores": v["scores"], "based_on": v["based_on"]}
            try:
                nbytes = os.path.getsize(v["path"])
            except OSError:
                continue
            out.append({"file": v["file"], "key": key, "bytes": nbytes, "info": info, "stored": "shared", "path": v["path"]})
    _SHARED["sig"], _SHARED["rows"] = sig, out
    return out


def label_of(n):
    return f"{n.label} {n.title}"


def models_of(tab, nid, shared=True, _seen=None):
    """Every model that the block `nid` has: [row of describe()].  A Trainer: its own.  Trained models: its own, those of the blocks wired into its From trainers cell, and (when
    `shared`) the shared Models folder.  Model testing: its own and those of the blocks wired into its Models cell.  A model that is wired in is not copied: its row says which
    block it is in.  A Trained models block that is wired into another passes on what it lists, the shared models too."""
    prj = tab.project
    n = prj.nodes.get(nid)
    _seen = set() if _seen is None else _seen
    if n is None or nid in _seen:
        return []
    _seen.add(nid)
    rows = [describe(m, n, "Imported" if n.kind != "trainer" else label_of(n), "own") for m in n.data.get("models", [])]
    cell = {"trained_models": "trainers", "model_test": "models"}.get(n.kind)
    if cell:
        for k in prj.incoming_all(nid, cell):
            src = prj.nodes.get(k.a)
            if src is not None and src.kind in HOLDERS:
                for r in models_of(tab, src.id, shared=(src.kind == "trained_models"), _seen=_seen):
                    if r["origin"] == "shared":
                        rows.append(r)
                    else:                                    # (what a wired block holds of its own is wired in here; a Trained models block says its models were imported into it)
                        frm = f"{label_of(src)} (imported)" if src.kind == "trained_models" and r["origin"] == "own" else r["from"]
                        rows.append(dict(r, origin="wired", **{"from": frm}))
    if shared and n.kind == "trained_models":
        rows += [describe(m, None, "GitHub / shared folder", "shared") for m in shared_entries()]
    seen_ids, out = set(), []
    for r in rows:                                           # (a model that two wired blocks both pass on is listed once)
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            out.append(r)
    return out


def fingerprint(rows, origins=None):
    """What shows that the list of models changed (`origins`: only the rows of these origins count)."""
    return "|".join(sorted(f"{r['id']}/{r['bytes']}/{r['stored']}/{r['name']}" for r in rows if origins is None or r["origin"] in origins))


def row_path(tab, row):
    return entry_path(tab, row["node"], row["entry"])


def when(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else ""
