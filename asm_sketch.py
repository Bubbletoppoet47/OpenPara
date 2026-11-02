"""Assembly sketch: a sketch of its own file (.gpk) whose symbols and named dimensions are VARIABLES that drive the parts and the assembly linked to it, one way.

The sketch is an ordinary sketch of a Document (so every sketch tool, relation, dimension, symbol and configuration works), kept in a file of its own.
Each variable has one number per configuration of the sketch.  A variable is DRIVING (a dimension / symbol you set) or DRIVEN (measured from the geometry or
computed from other variables) and has a kind (length, angle or number); the ones with the Export box ticked (Document.export) are handed over.

The sketch file lists the one assembly it belongs to and the parts it drives (paths relative to the sketch).  Each linked file keeps the link itself (Document.gsv /
Assembly.gsv: the sketch's path, relative to that file, and the numbers it last received) and shows the numbers as its read-only table "Global Sketch Variables" (gsv.py);
for every sketch configuration the file has a configuration of the same name.  Linked files are updated live when open, written on request, and pull the
numbers themselves when they are opened.  Nothing ever flows from a part back into the sketch.  No Qt in here.
"""
import json
import os

import gsv
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


def dumps(doc, assembly=None, parts=()):
    return json.dumps({"format": FORMAT, "version": 2, "doc": json.loads(doc.to_json()), "assembly": assembly, "parts": list(parts)}, indent=1)


def loads(text):
    """-> (Document, assembly path as saved or None, [part paths as saved])"""
    d = json.loads(text)
    if d.get("format") != FORMAT:
        raise AsmSketchError("this is not an assembly sketch file")
    doc = pm.Document.from_json(json.dumps(d["doc"]))
    return doc, d.get("assembly"), list(d.get("parts") or [])


def load(path):
    with open(path, encoding="utf-8") as f:
        return loads(f.read())


def save(path, doc, assembly=None, parts=()):
    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(doc, assembly, parts))


def rel(path, base):
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


def absolute(path, base):
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))


# ------------------------------------------------------------------------------------------------------------- the variables
def _kind_of(m, name, sc):
    """length / angle / number: what the dimensions that use the symbol measure (a symbol no dimension uses is a plain number)."""
    kinds = set()
    for c in m.cons:
        if c["type"] in sc.DIMENSIONS and c.get("expr"):
            try:
                if name in sc.expr_symbols(str(c["expr"])):
                    kinds.add("angle" if c["type"] == "dim_ang" else "length")
            except Exception:                                       # noqa: BLE001
                pass
    return "angle" if "angle" in kinds and "length" not in kinds else ("length" if kinds else "number")


def variables(doc):
    """-> (configs, vars, values): configuration names, [{"name", "kind", "role", "export"}], {configuration: {variable: number}}.
    kind: length (mm) | angle (degrees) | number.  role: driving (a symbol you set, or a named dimension) | driven (measured from the geometry or computed)."""
    f = sketch_feature(doc)
    if f is None:
        return [], [], {}
    doc.rebuild()
    m = doc.models.get(f["id"])
    if m is None:
        return [], [], {}
    sc = pm.sc
    keep = m.active
    try:
        try:
            m.solve_all_configs()                                   # driven symbols get their number in every configuration
        except Exception:                                           # noqa: BLE001
            pass
        configs = list(m.configs)
        out, values = [], {c: {} for c in configs}
        for name, p in m.params.items():
            if p.get("doc"):
                continue
            driven = m.is_output(name) or bool(p.get("expr"))
            if driven and any(c.get("coupled") and c.get("expr") == name for c in m.cons):
                driven = False                                      # a dimension that follows measured values still constrains the sketch
            out.append({"name": name, "kind": _kind_of(m, name, sc), "role": "driven" if driven else "driving"})
        for j, c in enumerate(configs):
            m.active = j
            for k, v in m.param_values().items():
                if any(o["name"] == k for o in out):
                    values[c][k] = float(v)
        m.active = keep
        for c in m.cons:                                            # named dimensions that are not driven by a symbol
            if c["type"] in sc.DIMENSIONS and c.get("user_name") and c.get("name") and not doc.dim_symbol(m, c):
                out.append({"name": c["name"], "kind": "angle" if c["type"] == "dim_ang" else "length", "role": "driven" if (c.get("expr") and not c.get("coupled")) else "driving"})
                for cn in configs:
                    values[cn][c["name"]] = float(c["value"])
        for o in out:
            o["export"] = o["name"] in doc.export
        return configs, out, values
    finally:
        m.active = keep


def payload(doc):
    """What the sketch hands over: (configs, [{"name","kind","role"}] of the exported variables, {configuration: {variable: number}})."""
    configs, vars_, values = variables(doc)
    ex = [{k: v[k] for k in ("name", "kind", "role")} for v in vars_ if v["export"]]
    names = {v["name"] for v in ex}
    return configs, ex, {c: {k: x for k, x in row.items() if k in names} for c, row in values.items()}


def set_export(doc, name, on):
    if on and name not in doc.export:
        doc.export.append(name)
    elif not on and name in doc.export:
        doc.export.remove(name)


# ------------------------------------------------------------------------------------------------------------- the linked files
def is_assembly(path):
    return str(path).lower().endswith(".gpa")


def load_target(path):
    """The Document (.gpd) or Assembly (.gpa) in a file, with base_dir set."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if is_assembly(path):
        import asm_model
        obj = asm_model.Assembly.from_json(text)
    else:
        obj = pm.Document.from_json(text)
    obj.base_dir = os.path.dirname(os.path.abspath(path))
    return obj


def save_target(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj.to_json())


def apply(obj, sketch_path, pl):
    """Give a part / assembly object (base_dir set) the sketch's payload `pl` = payload(doc), written as a path relative to the object's file.  -> messages."""
    src = rel(os.path.normpath(os.path.abspath(sketch_path)), obj.base_dir) if obj.base_dir else os.path.abspath(sketch_path)
    return obj.gsv_set(src, *pl)


def link(path, sketch_path, sketch_doc, open_obj=None):
    """Write the link into the file `path` (the live object `open_obj` when it is open, else the file) and give it the numbers.
    -> (state "open" | "written" | "missing" | "error: ...", messages)"""
    pl = payload(sketch_doc)
    try:
        if open_obj is not None:
            msgs = apply(open_obj, sketch_path, pl)
            open_obj.gsv_refresh()
            return "open", msgs
        if not os.path.isfile(path):
            return "missing", []
        obj = load_target(path)
        msgs = apply(obj, sketch_path, pl)
        obj.gsv_refresh()
        save_target(path, obj)
        return "written", msgs
    except Exception as ex:                                          # noqa: BLE001
        return f"error: {ex}", []


def unlink(path, open_obj=None):
    """Remove the link from a file (its configurations and cells stay; the numbers go)."""
    try:
        if open_obj is not None:
            open_obj.gsv_clear()
            return "open"
        if not os.path.isfile(path):
            return "missing"
        obj = load_target(path)
        obj.gsv_clear()
        save_target(path, obj)
        return "written"
    except Exception as ex:                                          # noqa: BLE001
        return f"error: {ex}"


def push(sketch_path, sketch_doc, files, open_obj=None, write_closed=False):
    """Push the sketch's numbers to its linked files (`files` = absolute paths: the assembly and the parts).  `open_obj(path)` returns the live Document /
    Assembly of a file that is open.  A file that is not open is only changed on disk when write_closed (it pulls the numbers itself when opened).
    -> [(path, "open" | "written" | "skipped" | "missing" | "error: ...", messages)]"""
    out = []
    for p in files:
        o = open_obj(p) if open_obj else None
        if o is None and not write_closed:
            out.append((p, "skipped", []))
            continue
        st, msgs = link(p, sketch_path, sketch_doc, o)
        out.append((p, st, msgs))
    return out


def pull(obj, live=None):
    """After a part / assembly was opened (base_dir set): bring its Global Sketch Variables up to date from its sketch file (or from the open sketch tab
    `live(path)` -> Document).  -> (changed, messages)"""
    if not getattr(obj, "gsv", None):
        return False, []
    src = obj.gsv_src_path()
    doc = live(src) if live else None
    if doc is None:
        if not src or not os.path.isfile(src):
            return False, [f"assembly sketch not found: {src}"]
        try:
            doc = load(src)[0]
        except Exception as ex:                                      # noqa: BLE001
            return False, [f"{os.path.basename(src)}: {ex}"]
    before = json.dumps([obj.gsv, obj.cfg["names"]], sort_keys=True)
    msgs = obj.gsv_set(obj.gsv["src"], *payload(doc))
    return before != json.dumps([obj.gsv, obj.cfg["names"]], sort_keys=True), msgs
