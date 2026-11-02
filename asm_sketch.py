"""Assembly sketch: a sketch of its own file (.gpk) whose symbols and named dimensions are VARIABLES that drive parts, one way.

The sketch is an ordinary sketch of a Document (so every sketch tool, relation, dimension, symbol and configuration works), kept in a file of its own
next to - or far from - the parts.  Each variable has one number per configuration of the sketch (inputs you set, outputs the geometry measures).
A part links columns of its configuration table to variables (pm_model.Document.link_*); this module computes the variables' numbers and writes
them into the linked parts: live into a part that is open, or into the part file when you ask, and a part pulls them itself when it is opened.
Nothing ever flows from a part back into the sketch.  No Qt in here.
"""
import json
import os

import pm_model as pm

EXT = ".gpk"
FORMAT = "openpara-asm-sketch"


class AsmSketchError(Exception):
    pass


# ------------------------------------------------------------------------------------------------------------- the document
def new_document():
    """A Document holding one sketch (on the Top plane) and nothing else."""
    doc = pm.Document()
    doc.add(pm.new_feature("sketch", plane={"base": "Top"}))
    doc.rebuild()
    return doc


def sketch_feature(doc):
    return next((f for f in doc.features if f["kind"] == "sketch"), None)


def dumps(doc, parts=()):
    return json.dumps({"format": FORMAT, "version": 1, "doc": json.loads(doc.to_json()), "parts": list(parts)}, indent=1)


def loads(text):
    """-> (Document, [part paths as saved])"""
    d = json.loads(text)
    if d.get("format") != FORMAT:
        raise AsmSketchError("this is not an assembly sketch file")
    doc = pm.Document.from_json(json.dumps(d["doc"]))
    return doc, list(d.get("parts") or [])


def load(path):
    with open(path, encoding="utf-8") as f:
        doc, parts = loads(f.read())
    return doc, parts


def save(path, doc, parts=()):
    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(doc, parts))


def rel(path, base):
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


def absolute(path, base):
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))


# ------------------------------------------------------------------------------------------------------------- the variables
def variables(doc):
    """-> (configs, vars, values): configuration names, [{"name", "kind"}], {configuration: {variable: number}}.
    kind: input (a symbol you set, one number per configuration), output (measured from the geometry), formula, dimension (a named dimension)."""
    f = sketch_feature(doc)
    if f is None:
        return [], [], {}
    doc.rebuild()
    m = doc.models.get(f["id"])
    if m is None:
        return [], [], {}
    keep = m.active
    try:
        try:
            m.solve_all_configs()                                   # outputs get their number in every configuration
        except Exception:
            pass
        configs = list(m.configs)
        out, values = [], {c: {} for c in configs}
        for name, p in m.params.items():
            if p.get("doc"):
                continue
            kind = "formula" if p.get("expr") and not m.is_output(name) else ("output" if m.is_output(name) else "input")
            out.append({"name": name, "kind": kind})
        for j, c in enumerate(configs):
            m.active = j
            for k, v in m.param_values().items():
                if any(o["name"] == k for o in out):
                    values[c][k] = float(v)
        m.active = keep
        for c in m.cons:                                            # named dimensions that are not driven by a symbol
            if c["type"] in pm.sc.DIMENSIONS and c.get("user_name") and c.get("name") and not doc.dim_symbol(m, c) and not c.get("expr"):
                out.append({"name": c["name"], "kind": "dimension"})
                for cn in configs:
                    values[cn][c["name"]] = float(c["value"])
        return configs, out, values
    finally:
        m.active = keep


def read_values(path, live=None):
    """The numbers of the sketch file `path` -> {configuration: {variable: number}}.  `live(path)` may return the Document of a sketch that is open
    (with edits that are not saved yet)."""
    doc = live(path) if live else None
    if doc is None:
        doc, _parts = load(path)
    return variables(doc)[2]


# ------------------------------------------------------------------------------------------------------------- driving the parts
def refresh_part(doc, live=None):
    """Pull: bring every link of the part Document `doc` up to date from its sketch files (call after opening a part; `doc.base_dir` is the part's folder).
    -> (changed, messages)"""
    msgs, changed = [], False
    for src in sorted({doc.link_src_path(ln) for ln in doc.links}):
        if not os.path.isfile(src) and not (live and live(src) is not None):
            msgs.append(f"assembly sketch not found: {src}")
            continue
        try:
            vals = read_values(src, live)
        except Exception as ex:                                      # noqa: BLE001
            msgs.append(f"{os.path.basename(src)}: {ex}")
            continue
        before = json.dumps([doc.cfg["names"], doc.cfg["cols"], doc.cfg["cells"]], sort_keys=True)
        msgs += doc.link_apply(src, vals)
        changed = changed or before != json.dumps([doc.cfg["names"], doc.cfg["cols"], doc.cfg["cells"]], sort_keys=True)
    return changed, msgs


def push(sketch_path, sketch_doc, parts, part_doc=None, write_closed=False):
    """Push: write the sketch's numbers into its linked parts.  `parts` are absolute part paths; `part_doc(path)` returns the Document of a part that
    is open (or None).  A part that is not open is only changed on disk when write_closed (it pulls the numbers itself when it is opened anyway).
    -> [(path, "open" | "written" | "skipped" | "missing" | "error: ...")]"""
    vals = variables(sketch_doc)[2]
    out = []
    for p in parts:
        d = part_doc(p) if part_doc else None
        try:
            if d is not None:
                d.link_apply(os.path.normpath(sketch_path), vals)
                d.cfg_apply(d.cfg["active"])
                out.append((p, "open"))
            elif not write_closed:
                out.append((p, "skipped"))
            elif not os.path.isfile(p):
                out.append((p, "missing"))
            else:
                with open(p, encoding="utf-8") as f:
                    d = pm.Document.from_json(f.read())
                d.base_dir = os.path.dirname(p)
                d.link_apply(os.path.normpath(sketch_path), vals)
                d.cfg_apply(d.cfg["active"])
                with open(p, "w", encoding="utf-8") as f:
                    f.write(d.to_json())
                out.append((p, "written"))
        except Exception as ex:                                      # noqa: BLE001
            out.append((p, f"error: {ex}"))
    return out
