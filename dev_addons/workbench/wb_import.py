"""wb_import.py - the files the program already had become blocks of the project.

    .gpd                  a Part block (a copy of the part inside the project; the file is not touched)
    .gpa                  an Assembly block; the parts it refers to by file name are read and kept INSIDE the assembly as copies (a part that cannot be found stays a reference, and is said)
    .gpv .gpt .gpf ...    an analysis project FOLDER (3D / 2D / 1D): the block keeps its files without meshes and results (Update works them out again);
                          the path of the original part on this computer is not kept
    .opsheet .opctl .opcirc, a .truss folder     the tool block of that kind
    .opara                another project: its blocks and wires are added next to the ones that are here (new letters, the wires between them kept)

Nothing is computed and nothing is opened: the blocks say what they are ready for (a part without a solid is 'incomplete', an analysis with supports and loads is 'update').
import_path(tab, path) -> the node (the first one, for a project) or None; what happened, or why not, is said in the workbench's status line.
import_item(tab, path) -> (nodes, [notes]); raises ImportProblem.
"""
import copy
import json
import os

import wb_nodes as nodes
import wb_project as wp


class ImportProblem(Exception):
    pass


def stem(path):
    return os.path.splitext(os.path.basename(str(path).rstrip("/\\")))[0] or "Imported"


def read_text(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as ex:
        raise ImportProblem(f"'{os.path.basename(path)}' could not be read: {ex}")


def what_is(path):
    """-> ("part" | "assembly" | "project" | "analysis" | "tool", the block kind or "")."""
    if not os.path.exists(path):
        raise ImportProblem(f"'{path}' was not found.")
    p = str(path).rstrip("/\\")
    ext = os.path.splitext(p)[1].lower()
    if os.path.isdir(p):
        if os.path.isfile(os.path.join(p, "simulation.json")):
            return "analysis", ""
        if ext == ".truss" and os.path.isfile(os.path.join(p, "project.json")):
            return "tool", "truss"
        raise ImportProblem(f"'{os.path.basename(p)}' is a folder, but not an analysis project (simulation.json) or a Truss Generator project (project.json).")
    if ext == ".gpd":
        return "part", "part"
    if ext == ".gpa":
        return "assembly", "assembly"
    if ext == ".opara":
        return "project", ""
    import wb_tools
    for kind, _tab, e, _addon, folder in wb_tools.TOOLS:
        if ext == e and not folder:
            return "tool", kind
    raise ImportProblem(f"'{os.path.basename(p)}' is not a kind of file the workbench can import (a part .gpd, an assembly .gpa, an analysis project folder, "
                        "a Sheets, Controls or Circuits file, a Truss Generator folder or a project .opara).")


# ---------------------------------------------------------------------------------------------------------------------------- one file, one block
def import_part(tab, path, x=None, y=None):
    text = read_text(path)
    try:
        obj = json.loads(text)
        if not isinstance(obj, dict) or "features" not in obj:
            raise ValueError("it has no features list")
        import pm_model as pm
        pm.Document.from_json(text)                          # it must be readable as a part
    except Exception as ex:                                  # noqa: BLE001
        raise ImportProblem(f"'{os.path.basename(path)}' is not a part file: {ex}")
    n = tab.add_block("part", x, y, title=stem(path), data={"doc": obj})
    return [n], []


def import_assembly(tab, path, x=None, y=None):
    import asm_embed
    try:
        text, warns = asm_embed.self_contained_text(path)
        obj = json.loads(text)
    except Exception as ex:                                  # noqa: BLE001
        raise ImportProblem(f"'{os.path.basename(path)}' is not an assembly file: {ex}")
    if not isinstance(obj, dict) or "components" not in obj:
        raise ImportProblem(f"'{os.path.basename(path)}' is not an assembly file: it has no components list.")
    n = tab.add_block("assembly", x, y, title=stem(path), data={"asm": obj})
    notes = [f"{len(obj.get('parts') or {})} part(s) are inside it now."] + list(warns)
    return [n], notes


def adapter_for_sim(sim_kind):
    for a in nodes.ADAPTERS.values():
        if getattr(a, "sim_kind", None) == sim_kind:
            return a
    return None


def import_analysis(tab, folder, x=None, y=None):
    import wb_analysis
    try:
        sp = wb_analysis.sim_project()
    except ImportError:
        raise ImportProblem("Analysis projects need the add-on 'Simulation (1D FEA, 2D FEA, 2D CFD)', which is not installed or is switched off (Add-ons).")
    folder = str(folder).rstrip("/\\")
    sk = sp.kind_of_folder(folder)
    if sk is None:
        raise ImportProblem(f"'{os.path.basename(folder)}' is not a simulation project this program knows (its kind may need an add-on that is switched off).")
    a = adapter_for_sim(sk)
    if a is None:
        raise ImportProblem(f"The workbench has no block for {sp.LABEL.get(sk, sk)} projects.")
    files = wb_analysis.pack(folder)
    try:                                                     # a path on this computer does not belong in the project file
        m = json.loads(wp.unpack_bytes(files["simulation.json"]).decode("utf-8"))
        if isinstance(m.get("source"), dict) and m["source"].get("orig"):
            m["source"]["orig"] = None
            files["simulation.json"] = wp.pack_bytes(json.dumps(m, indent=1).encode("utf-8"))
    except (KeyError, ValueError, UnicodeDecodeError) as ex:
        raise ImportProblem(f"'{os.path.basename(folder)}' has no readable simulation.json: {ex}")
    n = tab.add_block(a.kind, x, y, title=stem(folder), data={"files": files})
    tab.project.set_ready(n.id, "geometry", wb_analysis.has_source(folder))
    tab.project.set_ready(n.id, "setup", a.setup_is_ready(None, folder))
    notes = []
    if not wb_analysis.has_source(folder):
        notes.append("It has no geometry yet: wire a Part or an Assembly into its Geometry cell.")
    return [n], notes


def import_tool(tab, path, kind, x=None, y=None):
    a = nodes.adapter_for(kind)
    if a is None or not hasattr(a, "slot"):
        raise ImportProblem(f"The workbench has no block for '{kind}'.")
    path = str(path).rstrip("/\\")
    try:
        if a.folder:
            data = {a.slot: wp.pack_folder(path)}
            doc = json.loads(read_text(os.path.join(path, "project.json")))
        else:
            data = {a.slot: wp.pack_file(path)}
            doc = json.loads(read_text(path))
        if not isinstance(doc, dict):
            raise ValueError("it is not a document")
        if not a.folder and not str(doc.get("format", "")).startswith("openpara-"):
            raise ValueError("it is not an OpenPara document")
    except ImportProblem:
        raise
    except Exception as ex:                                  # noqa: BLE001
        raise ImportProblem(f"'{os.path.basename(path)}' is not a {a.kind} document: {ex}")
    n = tab.add_block(kind, x, y, title=stem(path), data=data)
    tab.project.set_ready(n.id, a.first_cell, True)
    return [n], []


def import_project(tab, path, x=None, y=None):
    """The blocks and wires of another project file are added to this one (new ids and letters; the cells keep their state)."""
    try:
        other = wp.Project.read(path)
    except wp.ProjectError as ex:
        raise ImportProblem(str(ex))
    mine = tab.project
    known = [n for n in other.nodes.values() if n.spec is not None]
    skipped = [n.title for n in other.nodes.values() if n.spec is None]
    if not known:
        raise ImportProblem(f"'{os.path.basename(path)}' has no blocks this program knows.")
    dx = dy = 0.0
    if mine.nodes:                                           # put them right of what is here, top lines up
        left = min(n.pos[0] for n in known)
        top = min(n.pos[1] for n in known)
        right = max(n.pos[0] for n in mine.nodes.values())
        dx = round((right + 260.0 - left) / 20.0) * 20.0
        dy = round((min(n.pos[1] for n in mine.nodes.values()) - top) / 20.0) * 20.0
    new = {}
    out = []
    for n in known:
        n2 = tab.scene.add_node(n.kind, n.pos[0] + dx, n.pos[1] + dy, n.title, copy.deepcopy(n.data), select=False)
        n2.cells = copy.deepcopy(n.cells)
        n2.notes = n.notes
        new[n.id] = n2.id
        out.append(n2)
    for k in other.links:
        if k.a in new and k.b in new:
            tab.scene.make_link(new[k.a], k.a_cell, new[k.b], k.b_cell)
    tab.scene.refresh()
    notes = [f"{len(out)} block(s) were added with their wires."]
    if skipped:
        notes.append("Left out (kinds this program does not know): " + ", ".join(skipped) + ".")
    return out, notes


# ---------------------------------------------------------------------------------------------------------------------------- the entry points
def import_item(tab, path, x=None, y=None):
    what, kind = what_is(path)
    if what == "part":
        return import_part(tab, path, x, y)
    if what == "assembly":
        return import_assembly(tab, path, x, y)
    if what == "analysis":
        return import_analysis(tab, path, x, y)
    if what == "tool":
        return import_tool(tab, path, kind, x, y)
    return import_project(tab, path, x, y)


def import_path(tab, path, x=None, y=None):
    """-> the first node made, or None (the reason is said)."""
    try:
        made, notes = import_item(tab, path, x, y)
    except ImportProblem as ex:
        tab.say(str(ex))
        return None
    except Exception as ex:                                  # noqa: BLE001
        tab.say(f"'{os.path.basename(str(path))}' could not be imported: {ex}")
        return None
    tab.say(f"Imported {os.path.basename(str(path).rstrip('/' + chr(92)))} as {made[0].label} {made[0].title}" + (f" (and {len(made) - 1} more)" if len(made) > 1 else "") + ". "
            + " ".join(notes))
    return made[0]
