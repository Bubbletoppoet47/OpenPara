"""wb_project.py - the OpenPara WORKBENCH project: what a .opara file holds and when its cells are up to date.  No window in it (no Qt).

A project is a set of NODES (the blocks of the Project Schematic: a part, an assembly, a 3D analysis, a sheet, ...) and the LINKS between their cells
(a Geometry cell feeding the Geometry cell of an analysis).  Each node is made of ordered CELLS, like the systems of ANSYS Workbench (A1 is the name of the
system, A2, A3 ... its cells).  A cell has a ROLE:

    data      what the user makes in the node's editor (a part, the setup of an analysis).  Ready or not.
    import    takes its content from a node upstream (the geometry an analysis uses), through a link; it must be REFRESHED when the source changed.
    compute   a result that is computed from the cells before it (the solution of an analysis); it must be UPDATED when something before it changed.
    view      shows the cell before it (the results of an analysis); it has nothing to compute.

STATUS of a cell (what the little icon of the cell says):

    ok          up to date
    incomplete  something it needs is not there yet (no geometry, no setup, a source that is not ready)
    refresh     the node upstream changed: the cell must take the new data
    update      the cell, or a cell before it, changed since the last solve (or it was never solved)
    failed      the last update of the cell stopped with an error (the text is kept until something changes)

The status is not stored: it follows from COUNTERS.  Every cell has a stamp that grows each time its content changes; an import cell remembers the stamp of the
source it last took, a compute cell remembers the stamps of the cells before it when it was last updated.  Results, meshes and parametric outputs are NOT
saved in the file: after the file is opened every compute cell says "update" until the user presses Update (opening a project never starts a computation).

The file (.opara) is ONE JSON document you can read in any editor (or the same text in a zip, written only when asked):
    {"format": "openpara-project", "version": 1, "name", "saved_with", "saved": "2026-11-24T10:00:00", "view": {...},
     "nodes": [{"id", "kind", "title", "label", "pos": [x, y], "cells": {key: {"stamp", "seen", "ready", "failed"}}, "data": {...}, "notes"}],
     "links": [{"from": id, "from_cell": key, "to": id, "to_cell": key}]}
"data" is what the node needs to be opened again: a part's JSON, an assembly with its own embedded copies of its components, a project folder as {relative
path: {"text": ...} or {"b64": ...}}, a link to a big file (a relative path next to the .opara file).  A node of a kind this program does not know is kept
exactly as it was read and written back unchanged.
"""
import base64
import copy
import json
import os
import tempfile
import time
import zipfile

FORMAT = "openpara-project"
VERSION = 1
EXT = ".opara"
INNER = "project.json"                                     # the name of the document inside a zipped project

OK, INCOMPLETE, REFRESH, UPDATE, FAILED = "ok", "incomplete", "refresh", "update", "failed"
STATUSES = (OK, INCOMPLETE, REFRESH, UPDATE, FAILED)
STATUS_TEXT = {OK: "Up to date", INCOMPLETE: "Incomplete: something it needs is missing", REFRESH: "Refresh required: the data it uses changed upstream",
               UPDATE: "Update required: the cell or a cell before it changed", FAILED: "The last update failed"}
ROLES = ("data", "import", "compute", "view")
GROUPS = ("Analysis Systems", "Geometry", "Component Tools", "Design Exploration")


class ProjectError(Exception):
    """A project that cannot be used (not a project file, made by a newer program, broken) or a change that is not allowed (a link that cannot be made)."""


# ---------------------------------------------------------------------------------------------------------------------------- the kinds of node
class CellSpec:
    def __init__(self, key, label, role, provides=(), accepts=(), needs_link=False, many=False, needs_any=(), optional=False):
        if role not in ROLES:
            raise ValueError(f"cell role '{role}' is not one of {ROLES}")
        self.key, self.label, self.role = key, label, role
        self.needs_link = bool(needs_link)                                   # an import cell that has nothing of its own: without a wire it is incomplete
        self.many = bool(many)                                               # an import cell that takes any number of wires (the profiles of a beam, the inputs of a study)
        self.needs_any = tuple(needs_any)                                    # an import cell that is incomplete unless at least one of its wires comes from a cell that gives one of these kinds
        self.optional = bool(optional)                                       # an import cell that is fine with no wire at all (the block works without it): Sheets takes studies, but needs none
        self.provides, self.accepts = tuple(provides), tuple(accepts)       # kinds of data a link from / to this cell carries ("geometry", "sketch")


class KindSpec:
    def __init__(self, kind, label, group, cells, tip="", standalone=""):
        if group not in GROUPS:
            raise ValueError(f"group '{group}' is not one of {GROUPS}")
        self.kind, self.label, self.group, self.tip = kind, label, group, tip
        self.cells = tuple(cells)
        self.standalone = standalone                        # how the node is saved on its own: a file extension (".gpd"), "folder" or ""

    def cell(self, key):
        return next((c for c in self.cells if c.key == key), None)

    def index(self, key):
        return next((i for i, c in enumerate(self.cells) if c.key == key), -1)


KINDS = {}


def register(kind, label, group, cells, tip="", standalone=""):
    """Teaches the workbench a kind of node.  cells: [CellSpec or (key, label, role[, provides[, accepts]])] in the order they are shown."""
    cs = [c if isinstance(c, CellSpec) else CellSpec(*c) for c in cells]
    KINDS[kind] = KindSpec(kind, label, group, cs, tip, standalone)
    return KINDS[kind]


def spec_of(kind):
    return KINDS.get(kind)


# Geometry: a part gives its solid (to 3D analyses) and its sketches (to 2D / 1D analyses); an assembly gives its solid.
register("part", "Part", "Geometry", [("geometry", "Part", "data", ("geometry", "sketch", "profile", "dimensions"))],
         "One parametric part: sketches, features and profile sketches; its dimensions can be varied by a Parametric Study", ".gpd")
register("assembly", "Assembly", "Geometry", [("geometry", "Assembly", "data", ("geometry",))],
         "Parts put together with mates; its components are its own copies", ".gpa")
# Analysis systems: the first cell takes the geometry (a link, or imported inside the analysis), then the setup, the solution and the results.
# The geometry of an analysis comes ONLY from a wire (needs_link): without one the cell says incomplete and the window is empty.  A 1D Beam / Truss also takes any number of Parts
# as the source of its profile sketches (cross-sections).
_SOLID = ("geometry", "Geometry", "import", (), ("geometry",), True)
_SKETCH = ("geometry", "Sketch", "import", (), ("sketch",), True)
_PROFILE = ("profile", "Profile", "import", (), ("profile",), False, True)
for _k, _l, _tip, _cells in (
        ("solid", "3D Static Structural", "3D FEA: stress and displacement of a part or an assembly", [_SOLID]),
        ("thermal3d", "3D Thermal", "Heat conduction in a part or an assembly", [_SOLID]),
        ("fluid3d", "3D Fluid Flow", "Steady laminar flow of air or water around a part, with the temperature of the fluid", [_SOLID]),
        ("fea", "2D Static Structural", "2D FEA of a sketch", [_SKETCH]),
        ("thermal", "2D Thermal", "Heat conduction in a sketch", [_SKETCH]),
        ("cfd", "2D Fluid Flow", "2D CFD of a sketch", [_SKETCH]),
        ("beam", "1D Beam / Truss", "Beams and trusses from the lines of a sketch, with the profiles of their cross-sections", [_SKETCH, _PROFILE])):
    # the Setup of an analysis that a parametric study can run gives "analysis" (to the Parameters cell of a Parametric Study block); 3D Thermal has no study yet.  The Setup of a
    # heat, stress or fluid flow analysis (2D or 3D) also gives "coupling" (to the Physics cell of a Coupled Physics block)
    _prov = tuple(x for x in (("analysis",) if _k in ("solid", "fea", "thermal", "cfd", "beam") else ()) + (("coupling",) if _k in ("solid", "fea", "thermal", "thermal3d", "cfd", "fluid3d") else ()))
    _setup = ("setup", "Setup", "data", _prov) if _prov else ("setup", "Setup", "data")
    register(_k, _l, "Analysis Systems", _cells + [_setup, ("solution", "Solution", "compute"), ("results", "Results", "view")], _tip, "folder")
# Coupled Physics: one heat analysis and one stress analysis of the same geometry (both 2D or both 3D) solved together.  The Physics cell takes their Setups (a wire from each);
# the Setup cell holds the coupling options; Solution solves both in order and hands the temperature over; the Results page shows the combined result.
register("coupled", "Coupled Physics", "Analysis Systems",
         [CellSpec("physics", "Physics", "import", (), ("coupling",), True, True, ("coupling",)), ("setup", "Setup", "data"), ("solution", "Solution", "compute"), ("results", "Results", "view")],
         "A heat analysis and a stress analysis of the same geometry solved together: the temperature of the first is the load of the second", "folder")
# Other tools: one document each.
for _k, _l, _tip, _st in (
        ("sheets", "Sheets", "A spreadsheet", ".opsheet"), ("pdf", "PDF Editor", "Read, mark up and arrange PDF files; the PDFs opened in it are kept in the project", "folder"),
        ("controls", "Controls", "Control systems: blocks, step responses", ".opctl"), ("circuits", "Circuits", "Circuit diagrams with a simulator", ".opcirc"),
        ("visualize", "Visualize", "Pictures and videos of a part or assembly", "folder"), ("motor", "Motor Control", "A motor drive", "folder"),
        ("truss", "Truss Generator", "The members of a truss from a sketch", ".truss")):
    register(_k, _l, "Component Tools", [("document", _l, "data")], _tip, _st)
# Annotator and Trainer.  The Annotator's project folder is kept as a link (a dataset is far too big for a project file); its Dataset cell (the annotated pictures with their boxes) and
# its Distances cell (the LiDAR distance picked for each box) can be wired into a Trainer, ONE Annotator for each Trainer.  The Trainer's two import cells take them (Refresh copies the
# dataset into the Trainer's own training project; pictures are never stored in the project file).  Its Training cell is "data", not "compute": Update Project never starts a training,
# the person presses Start training in the Trainer window.  The Models cell shows the models trained (kept inside the project file up to 500 MB each, a longer one is linked).
register("annotator", "Annotator", "Component Tools",
         [("document", "Annotator", "data"), ("dataset", "Dataset", "data", ("dataset",)), ("distances", "Distances", "data", ("distances",))],
         "Pictures with labels, for training; the project folder is kept as a link.  Its Dataset and Distances can be wired into a Trainer", "folder")
register("trainer", "Trainer", "Component Tools",
         [CellSpec("dataset", "Dataset", "import", (), ("dataset",)), CellSpec("distances", "Distances", "import", (), ("distances",), optional=True),
          ("setup", "Setup", "data"), ("training", "Training", "data"), ("models", "Models", "view", ("models",))],
         "Trains models on the Dataset (and Distances) of the Annotator wired into it; the models are kept in the project", "folder")
# Trained models: ONE list of every model there is - the ones trained in the Trainers wired into its From trainers cell, the ones imported into it (kept inside the project file up to
# 500 MB each, a bigger one is linked) and the ones in the shared Models folder (the ones downloaded from GitHub).  Nothing is copied from a Trainer: the list follows the wires.
# From trainers takes any number of Trainers (none is fine), Library is the list (ready when there is a model in it; its stamp grows when the list changes, a model of a wired Trainer
# too), Models gives the list to a Model testing block.
register("trained_models", "Trained models", "Component Tools",
         [CellSpec("trainers", "From trainers", "import", (), ("models",), many=True, optional=True), ("library", "Library", "data"), ("models", "Models", "view", ("models",))],
         "One list of every model: the ones trained in the Trainers wired into it, the ones imported into it and the ones downloaded from GitHub; import, export, rename, remove", "folder")
# Model testing: runs the models over a recorded session of the Gimble rig and compares the distance each gives with the LiDAR (the Annotator's Analyse tab, in a block of its own).  Models:
# the ones of the Trainers / Trained models blocks wired into its Models cell (any number; none is fine) and the ones dropped on it.  Test data is a link to a recorded session folder
# (never a copy: a session is frames and depth).  Setup holds the confidence, the tolerance and the way the LiDAR is read.  Analysis is a "data" cell, not "compute": it is ready while an
# analysis has been run in the window, and Update Project never runs a model (the person presses Run analysis).  Results are not saved in the project (CSV and report are exported).
register("model_test", "Model testing", "Component Tools",
         [CellSpec("models", "Models", "import", (), ("models",), many=True, optional=True), ("data", "Test data", "data"), ("setup", "Setup", "data"), ("analysis", "Analysis", "data"),
          ("results", "Results", "view")],
         "Runs trained models over a recorded session of the Gimble rig and compares the distance they give with the LiDAR, frame by frame", "")
# A study takes any number of wires into its Parameters cell: the dimensions of Parts (they change the geometry of every analysis that works on that Part) and the Setup of analyses
# (their own inputs; the outputs recorded come from every analysis wired).  It needs at least one analysis.  The study itself is kept in the study block.
register("study", "Parametric Study", "Design Exploration",
         [CellSpec("setup", "Parameters", "import", (), ("analysis", "dimensions"), True, True, ("analysis",)), ("solution", "Study", "compute"), ("results", "Results", "view", ("study",))],
         "Runs the analyses wired into it again and again with other values of their inputs and of the dimensions of the parts they use", "")
# Sheets takes the results of any number of Parametric Studies into its Study Results cell: in the Sheets window only THESE studies can be imported (a study is never imported from
# anywhere else in a workbench block); the cell is optional, a spreadsheet needs no study.
register("sheets", "Sheets", "Component Tools",
         [CellSpec("studies", "Study Results", "import", (), ("study",), False, True, (), optional=True), ("document", "Sheets", "data")],
         "A spreadsheet; the results of the Parametric Studies wired into it can be imported onto its sheets", ".opsheet")
# A drawing takes the Parts and Assemblies wired into its Models cell as the things it shows (any number): they are the "Part / Assembly to Insert" of its Model View, and a change in
# one of them is a refresh of the cell (the views are drawn again).  Without a wire there is nothing to draw: the cell says incomplete.
register("drawing", "Drawing", "Component Tools",
         [CellSpec("models", "Models", "import", (), ("geometry",), True, True), ("document", "Drawing", "data")],
         "A drawing of the parts and assemblies wired into it: views on a standard sheet, exported as a PDF", ".opdraw")


# ---------------------------------------------------------------------------------------------------------------------------- the project
def new_cell():
    return {"stamp": 0, "seen": {}, "ready": False, "failed": "", "failed_deps": {}}


def letter_of(n):
    """0 -> A ... 25 -> Z, 26 -> AA ..."""
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class Node:
    def __init__(self, nid, kind, title, label, pos=(0.0, 0.0)):
        self.id, self.kind, self.title, self.label = nid, kind, title, label
        self.pos = [float(pos[0]), float(pos[1])]
        self.cells = {}
        self.data = {}                                      # what the node needs to be opened again (see the module text)
        self.notes = ""
        self.raw = None                                     # a node of an unknown kind: the dict as it was read

    @property
    def spec(self):
        return KINDS.get(self.kind)

    def cell_name(self, key):
        """The name of a cell in the schematic: the letter of the system and the row (A1 is the name of the system, A2 the first cell)."""
        sp = self.spec
        i = sp.index(key) if sp else -1
        return f"{self.label}{i + 2}" if i >= 0 else f"{self.label}?"


class Link:
    def __init__(self, a, a_cell, b, b_cell):
        self.a, self.a_cell, self.b, self.b_cell = a, a_cell, b, b_cell

    def key(self):
        return (self.a, self.a_cell, self.b, self.b_cell)

    def to_dict(self):
        return {"from": self.a, "from_cell": self.a_cell, "to": self.b, "to_cell": self.b_cell}


class Project:
    def __init__(self, name="Project"):
        self.name = name
        self.nodes = {}                                     # id -> Node, in the order they were added
        self.links = []
        self.counter = 0
        self.view = {"x": 0.0, "y": 0.0, "zoom": 1.0}       # where the schematic was looking
        self.extra = {}                                     # keys of the file this program does not know, kept for writing back
        self.path = None                                    # where the file is (None: never saved)
        self.rev = 0                                        # counts the changes; the saved one is `saved_rev`
        self.saved_rev = 0

    # ------------------------------------------------------------------ changes
    def changed(self):
        self.rev += 1

    def is_dirty(self):
        return self.rev != self.saved_rev

    def node(self, nid):
        n = self.nodes.get(nid)
        if n is None:
            raise ProjectError(f"There is no node '{nid}' in the project.")
        return n

    def next_label(self):
        used = {n.label for n in self.nodes.values()}
        i = 0
        while letter_of(i) in used:
            i += 1
        return letter_of(i)

    def add_node(self, kind, title=None, pos=None, data=None):
        sp = KINDS.get(kind)
        if sp is None:
            raise ProjectError(f"The workbench does not know the kind '{kind}'.")
        self.counter += 1
        nid = f"n{self.counter}"
        while nid in self.nodes:
            self.counter += 1
            nid = f"n{self.counter}"
        n = Node(nid, kind, title or sp.label, self.next_label(), pos or self.free_spot())
        for c in sp.cells:
            n.cells[c.key] = new_cell()
        if data is not None:
            n.data = data
        self.nodes[nid] = n
        self.changed()
        return n

    def free_spot(self, grid=20.0, step_x=260.0):
        """A place for a new block: right of the right-most one, in the top row."""
        if not self.nodes:
            return (grid * 3, grid * 3)
        x = max(n.pos[0] for n in self.nodes.values()) + step_x
        return (round(x / grid) * grid, grid * 3)

    def remove_node(self, nid):
        self.node(nid)
        self.links = [k for k in self.links if nid not in (k.a, k.b)]
        del self.nodes[nid]
        self.changed()

    def move_node(self, nid, x, y):
        n = self.node(nid)
        if [float(x), float(y)] != n.pos:
            n.pos = [float(x), float(y)]
            self.changed()

    def rename_node(self, nid, title):
        n = self.node(nid)
        title = (title or "").strip() or (n.spec.label if n.spec else n.kind)
        if title != n.title:
            n.title = title
            self.changed()

    # ------------------------------------------------------------------ links
    def incoming(self, nid, key):
        return next((k for k in self.links if k.b == nid and k.b_cell == key), None)

    def incoming_all(self, nid, key):
        """Every wire into a cell, in the order they were made (a cell that takes one wire has at most one)."""
        return [k for k in self.links if k.b == nid and k.b_cell == key]

    def link_stamps(self, nid, key):
        """What an import cell depends on right now: the stamp of the cell its wire comes from ({"link": stamp}), or of every one of its wires ({"links": {"A:cell": stamp}})."""
        ks = self.incoming_all(nid, key)
        if self.node(nid).spec.cell(key).many:
            return {"links": {f"{k.a}:{k.a_cell}": self.cell(*self.source_cell(k.a, k.a_cell))["stamp"] for k in ks}} if ks else {}
        return {"link": self.cell(*self.source_cell(ks[0].a, ks[0].a_cell))["stamp"]} if ks else {}

    def source_cell(self, nid, key):
        """(node, cell key) of the cell whose state a wire that leaves (nid, key) carries: a result cell only SHOWS what the compute cell before it made (it has no stamp of its own
        that changes with a run), so a wire from it follows that cell."""
        sp = self.node(nid).spec
        cs = sp.cell(key)
        i = sp.index(key)
        if cs.role == "view" and i > 0:
            return nid, sp.cells[i - 1].key
        return nid, key

    def outgoing(self, nid, key=None):
        return [k for k in self.links if k.a == nid and (key is None or k.a_cell == key)]

    def why_not_link(self, a, a_cell, b, b_cell):
        """The reason why the link cannot be made, or None when it can."""
        na, nb = self.nodes.get(a), self.nodes.get(b)
        if na is None or nb is None:
            return "One end of the link is not in the project."
        if a == b:
            return "A node cannot be linked to itself."
        sa, sb = na.spec, nb.spec
        if sa is None or sb is None:
            return "A node of a kind this program does not know cannot be linked."
        ca, cb = sa.cell(a_cell), sb.cell(b_cell)
        if ca is None or cb is None:
            return "The link needs a cell at both ends."
        if not ca.provides:
            return f"{na.cell_name(a_cell)} ({ca.label}) does not give anything to another node."
        if not cb.accepts:
            return f"{nb.cell_name(b_cell)} ({cb.label}) does not take anything from another node."
        if not set(ca.provides) & set(cb.accepts):
            return (f"{na.cell_name(a_cell)} gives {' / '.join(ca.provides)}, but {nb.cell_name(b_cell)} takes {' / '.join(cb.accepts)}.")
        if cb.many:
            if any(k.a == a and k.a_cell == a_cell for k in self.incoming_all(b, b_cell)):
                return f"{na.cell_name(a_cell)} is wired into {nb.cell_name(b_cell)} already."
        elif self.incoming(b, b_cell) is not None:
            return f"{nb.cell_name(b_cell)} already has a source: remove that link first."
        if self.reaches(b, a):
            return "That link would make a loop: the first node already depends on the second."
        return None

    def reaches(self, a, b):
        """True when node b is downstream of node a (a link path a -> ... -> b)."""
        seen, todo = set(), [a]
        while todo:
            x = todo.pop()
            if x == b:
                return True
            if x in seen:
                continue
            seen.add(x)
            todo += [k.b for k in self.links if k.a == x]
        return False

    def link(self, a, a_cell, b, b_cell):
        why = self.why_not_link(a, a_cell, b, b_cell)
        if why:
            raise ProjectError(why)
        k = Link(a, a_cell, b, b_cell)
        self.links.append(k)
        self.changed()
        return k

    def unlink(self, k):
        if k in self.links:
            self.links.remove(k)
            self.changed()

    def link_type(self, k):
        """What a link carries: the first data kind both ends know."""
        na, nb = self.nodes[k.a], self.nodes[k.b]
        both = [t for t in na.spec.cell(k.a_cell).provides if t in nb.spec.cell(k.b_cell).accepts]
        return both[0] if both else ""

    # ------------------------------------------------------------------ counters and status
    def cell(self, nid, key):
        n = self.node(nid)
        c = n.cells.get(key)
        if c is None:
            raise ProjectError(f"{n.title} has no cell '{key}'.")
        return c

    def touch(self, nid, key):
        """The content of a cell changed: its stamp grows (the cells that use it become 'refresh' / 'update'); a failure it had is forgotten."""
        c = self.cell(nid, key)
        c["stamp"] += 1
        c["failed"], c["failed_deps"] = "", {}
        self.changed()

    def set_ready(self, nid, key, ready=True):
        c = self.cell(nid, key)
        if bool(ready) != c["ready"]:
            c["ready"] = bool(ready)
            self.changed()

    def mark_refreshed(self, nid, key):
        """An import cell has taken the data of its source (or of its own, when it has no link)."""
        n, c = self.node(nid), self.cell(nid, key)
        c["seen"] = self.link_stamps(nid, key)
        c["stamp"] += 1
        c["ready"] = True
        c["failed"], c["failed_deps"] = "", {}
        self.changed()
        return n

    def mark_updated(self, nid, key):
        """A compute cell was computed from the cells as they are now."""
        c = self.cell(nid, key)
        c["seen"] = self.dep_stamps(nid, key)
        c["stamp"] += 1
        c["ready"] = True
        c["failed"], c["failed_deps"] = "", {}
        self.changed()

    def mark_failed(self, nid, key, text):
        """The update of a cell stopped with an error.  The failure is shown until something the cell uses changes (then it is simply 'update' again)."""
        c = self.cell(nid, key)
        c["failed"] = str(text or "The update failed.")
        c["failed_deps"] = self.now_deps(nid, key)
        self.changed()

    def now_deps(self, nid, key):
        """What the cell depends on right now: the source stamp of an import cell, the stamps of the cells before a compute cell."""
        n = self.node(nid)
        if n.spec.cell(key).role == "import":
            return self.link_stamps(nid, key)
        return self.dep_stamps(nid, key)

    def dep_stamps(self, nid, key):
        """{key of an earlier cell of the node: its stamp}: what a compute cell computed from."""
        n = self.node(nid)
        i = n.spec.index(key)
        return {c.key: n.cells[c.key]["stamp"] for c in n.spec.cells[:i]}

    def status(self, nid, key):
        n = self.node(nid)
        sp = n.spec
        if sp is None:
            return INCOMPLETE
        cs = sp.cell(key)
        c = n.cells.get(key)
        if cs is None or c is None:
            return INCOMPLETE
        if c["failed"] and cs.role in ("compute", "import") and c.get("failed_deps") == self.now_deps(nid, key):
            return FAILED
        if cs.role == "data":
            return OK if c["ready"] else INCOMPLETE
        if cs.role == "import":
            ks = self.incoming_all(nid, key)
            if not ks:
                return OK if (c["ready"] or cs.optional) and not cs.needs_link else INCOMPLETE
            if cs.needs_any and not self.has_wire_of(ks, cs.needs_any):
                return INCOMPLETE
            for k in ks:
                if self.status(k.a, k.a_cell) in (INCOMPLETE, FAILED) or not self.cell(*self.source_cell(k.a, k.a_cell))["ready"]:
                    return INCOMPLETE
            if not c["ready"] or c["seen"] != self.link_stamps(nid, key):
                return REFRESH
            return OK
        i = sp.index(key)
        before = [self.status(nid, p.key) for p in sp.cells[:i]]
        if cs.role == "view":
            if before and before[-1] == OK:
                return OK
            return FAILED if before and before[-1] == FAILED else INCOMPLETE
        # compute: needs everything before it in order, then compares the stamps
        if any(s == INCOMPLETE for s in before):
            return INCOMPLETE
        if any(s == FAILED for s in before):
            return INCOMPLETE
        if not c["ready"] or c["seen"] != self.dep_stamps(nid, key):
            return UPDATE
        if any(s in (REFRESH, UPDATE) for s in before):
            return UPDATE
        return OK

    def has_wire_of(self, links, kinds):
        """True when one of the wires comes from a cell that gives one of `kinds`."""
        for k in links:
            n = self.nodes.get(k.a)
            c = n.spec.cell(k.a_cell) if n is not None and n.spec is not None else None
            if c is not None and set(c.provides) & set(kinds):
                return True
        return False

    def statuses(self, nid):
        n = self.node(nid)
        return {c.key: self.status(nid, c.key) for c in n.spec.cells} if n.spec else {}

    def node_status(self, nid):
        """The worst status of the node's cells (what the node needs next), for a one-word summary."""
        order = (FAILED, REFRESH, UPDATE, INCOMPLETE, OK)
        sts = list(self.statuses(nid).values())
        for s in order:
            if s in sts:
                return s
        return INCOMPLETE

    # ------------------------------------------------------------------ order and the plan of "Update Project"
    def order(self):
        """The node ids with every source before the nodes that take from it (ties: the order they were added)."""
        ids = list(self.nodes)
        out, done = [], set()
        while len(out) < len(ids):
            moved = False
            for i in ids:
                if i in done:
                    continue
                if all(k.a in done for k in self.links if k.b == i):
                    out.append(i)
                    done.add(i)
                    moved = True
            if not moved:                                   # a loop in a damaged file: the rest in the order they were added
                out += [i for i in ids if i not in done]
                break
        return out

    def light_copy(self):
        """The project with copies of the counters and the links but the same payloads (for working out a plan without changing anything)."""
        p = Project(self.name)
        p.counter = self.counter
        for nid, n in self.nodes.items():
            m = Node(n.id, n.kind, n.title, n.label, n.pos)
            m.cells = copy.deepcopy(n.cells)
            m.data = n.data
            p.nodes[nid] = m
        p.links = [Link(k.a, k.a_cell, k.b, k.b_cell) for k in self.links]
        return p

    def plan_update(self, only=None):
        """The steps that bring the project (or the nodes `only`) up to date, in the order they must run: [{"node", "cell", "action": "refresh" | "update",
        "name": "B3"}].  A cell that cannot be done (something it needs is missing) is left out; `blocked()` says why."""
        sim = self.light_copy()
        steps = []
        for nid in sim.order():
            if only is not None and nid not in only:
                continue
            n = sim.nodes[nid]
            if n.spec is None:
                continue
            for cs in n.spec.cells:
                st = sim.status(nid, cs.key)
                if st == REFRESH:
                    steps.append({"node": nid, "cell": cs.key, "action": "refresh", "name": n.cell_name(cs.key)})
                    sim.mark_refreshed(nid, cs.key)
                elif st == UPDATE and cs.role == "compute":
                    steps.append({"node": nid, "cell": cs.key, "action": "update", "name": n.cell_name(cs.key)})
                    sim.mark_updated(nid, cs.key)
        return steps

    def blocked(self):
        """[(cell name, why)] of the cells that cannot be brought up to date because something they need is missing."""
        out = []
        for nid in self.order():
            n = self.nodes[nid]
            if n.spec is None:
                out.append((n.label, f"'{n.title}' is of a kind this program does not know ({n.kind})."))
                continue
            for cs in n.spec.cells:
                if cs.role in ("data", "import", "compute") and self.status(nid, cs.key) == INCOMPLETE:
                    out.append((n.cell_name(cs.key), self.why_incomplete(nid, cs.key)))
        return out

    def why_incomplete(self, nid, key):
        n = self.node(nid)
        cs = n.spec.cell(key)
        if cs.role == "data":
            return f"{cs.label} of '{n.title}' is not set up yet."
        if cs.role == "import":
            ks = self.incoming_all(nid, key)
            if not ks:
                if cs.needs_link:
                    return f"{cs.label} of '{n.title}' needs a wire from the {'/'.join(cs.accepts)} it takes."
                return f"{cs.label} of '{n.title}' has no source: link it to a node, or import one in its editor."
            if cs.needs_any and not self.has_wire_of(ks, cs.needs_any):
                return f"{cs.label} of '{n.title}' needs a wire from the Setup cell of an analysis: a study records the outputs of the analyses it runs."
            k = next((x for x in ks if self.status(x.a, x.a_cell) in (INCOMPLETE, FAILED) or not self.cell(x.a, x.a_cell)["ready"]), ks[0])
            return f"The source {self.nodes[k.a].cell_name(k.a_cell)} ('{self.nodes[k.a].title}') is not ready."
        i = n.spec.index(key)
        for p in n.spec.cells[:i]:
            if self.status(nid, p.key) in (INCOMPLETE, FAILED):
                return f"{p.label} of '{n.title}' comes first and is not complete."
        return f"{cs.label} of '{n.title}' cannot be computed yet."

    # ------------------------------------------------------------------ checks and a report
    def check(self):
        """[text] of everything that is wrong in the project (a link to a node that is gone, a loop, two sources for a cell, a duplicate letter)."""
        out = []
        labels = {}
        for n in self.nodes.values():
            labels.setdefault(n.label, []).append(n.title)
            if n.spec is None:
                out.append(f"'{n.title}' ({n.label}) is of the kind '{n.kind}', which this program does not know; it is kept as it is.")
            else:
                for c in n.spec.cells:
                    if c.key not in n.cells:
                        out.append(f"'{n.title}' has no state for its cell '{c.key}'.")
        for lab, names in labels.items():
            if len(names) > 1:
                out.append(f"The letter {lab} is used by {len(names)} nodes ({', '.join(names)}).")
        seen = set()
        for k in self.links:
            why = None
            na, nb = self.nodes.get(k.a), self.nodes.get(k.b)
            if na is None or nb is None:
                why = "an end of a link is not in the project"
            elif na.spec is not None and nb.spec is not None:
                ca, cb = na.spec.cell(k.a_cell), nb.spec.cell(k.b_cell)
                if ca is None or cb is None:
                    why = f"{k.a}.{k.a_cell} -> {k.b}.{k.b_cell} names a cell that does not exist"
                elif not set(ca.provides) & set(cb.accepts):
                    why = f"{na.cell_name(k.a_cell)} -> {nb.cell_name(k.b_cell)} carries nothing both ends know"
            if why:
                out.append(why[0].upper() + why[1:] + ".")
            many = na is not None and nb is not None and nb.spec is not None and nb.spec.cell(k.b_cell) is not None and nb.spec.cell(k.b_cell).many
            if (k.b, k.b_cell, k.a, k.a_cell) in seen if many else (k.b, k.b_cell) in seen:
                out.append(f"{k.b}.{k.b_cell} has more than one source." if not many else f"{k.a}.{k.a_cell} is wired into {k.b}.{k.b_cell} twice.")
            seen.add((k.b, k.b_cell, k.a, k.a_cell) if many else (k.b, k.b_cell))
        if any(k.a in self.nodes and k.b in self.nodes and self.reaches(k.b, k.a) for k in self.links):
            out.append("The links make a loop.")
        return out

    def report_lines(self):
        """Plain lines for the project report: what is in it, every cell with its status, the links, what is not saved, what is wrong."""
        out = [f"Project '{self.name}'" + (f" ({self.path})" if self.path else " (not saved yet)"),
               f"{len(self.nodes)} nodes, {len(self.links)} links; format {FORMAT} {VERSION}" + ("; unsaved changes" if self.is_dirty() else "")]
        for nid in self.order():
            n = self.nodes[nid]
            if n.spec is None:
                out.append(f"  {n.label}  {n.title}: unknown kind '{n.kind}' (kept as it is)")
                continue
            sts = self.statuses(nid)
            cells = ", ".join(f"{n.cell_name(c.key)} {c.label}: {sts[c.key]}" for c in n.spec.cells)
            out.append(f"  {n.label}  {n.title} [{n.spec.label}] at ({n.pos[0]:g}, {n.pos[1]:g}): {cells}")
            size = payload_bytes(n.data)
            out.append(f"       holds {size_text(size)}" + (f" ({', '.join(sorted(n.data))})" if n.data else " (nothing yet)"))
            for key, c in n.cells.items():
                if c["failed"]:
                    out.append(f"       {n.cell_name(key)} failed: {c['failed']}")
        for k in self.links:
            na, nb = self.nodes.get(k.a), self.nodes.get(k.b)
            if na is not None and nb is not None and na.spec is not None and nb.spec is not None:
                out.append(f"  link {na.cell_name(k.a_cell)} ({na.title}) -> {nb.cell_name(k.b_cell)} ({nb.title}): {self.link_type(k)}, "
                           f"{self.status(k.b, k.b_cell)}")
        steps = self.plan_update()
        out.append(f"Update Project would do {len(steps)} step{'s' if len(steps) != 1 else ''}" + (": " + ", ".join(f"{s['action']} {s['name']}" for s in steps) if steps else "."))
        for name, why in self.blocked():
            out.append(f"  cannot yet: {name}: {why}")
        out.append("Not stored in the file: results, meshes and the outputs of a parametric study (they are computed again by Update).")
        for p in self.check():
            out.append("PROBLEM: " + p)
        return out

    # ------------------------------------------------------------------ the file
    def to_dict(self):
        nodes = []
        for n in self.nodes.values():
            if n.raw is not None and n.spec is None:
                nodes.append(n.raw)                         # an unknown kind goes back as it came
                continue
            nodes.append({"id": n.id, "kind": n.kind, "title": n.title, "label": n.label, "pos": [n.pos[0], n.pos[1]], "cells": n.cells, "data": n.data,
                          "notes": n.notes})
        d = dict(self.extra)
        d.update({"format": FORMAT, "version": VERSION, "name": self.name, "saved_with": program_version(), "saved": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "counter": self.counter, "view": self.view, "nodes": nodes, "links": [k.to_dict() for k in self.links]})
        return d

    def dumps(self):
        return json.dumps(self.to_dict(), indent=1, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            raise ProjectError("This is not an OpenPara project file.")
        v = d.get("version")
        if not isinstance(v, int) or v < 1:
            raise ProjectError("The project file has no usable version number.")
        if v > VERSION:
            raise ProjectError(f"This project was saved by a newer OpenPara (file version {v}; this program reads up to {VERSION}). Update OpenPara to open it.")
        p = cls(str(d.get("name") or "Project"))
        p.counter = int(d.get("counter") or 0)
        if isinstance(d.get("view"), dict):
            p.view.update({k: d["view"][k] for k in ("x", "y", "zoom") if isinstance(d["view"].get(k), (int, float))})
        known = {"format", "version", "name", "saved_with", "saved", "counter", "view", "nodes", "links"}
        p.extra = {k: v2 for k, v2 in d.items() if k not in known}
        for nd in d.get("nodes") or []:
            if not isinstance(nd, dict) or "id" not in nd or "kind" not in nd:
                raise ProjectError("The project file has a node without an id or a kind.")
            pos = nd.get("pos") if isinstance(nd.get("pos"), list) and len(nd["pos"]) == 2 else (0.0, 0.0)
            n = Node(str(nd["id"]), str(nd["kind"]), str(nd.get("title") or nd["kind"]), str(nd.get("label") or p.next_label()), pos)
            n.data = nd.get("data") if isinstance(nd.get("data"), dict) else {}
            n.notes = str(nd.get("notes") or "")
            sp = n.spec
            if sp is None:
                n.raw = nd
            else:
                for c in sp.cells:
                    cs = new_cell()
                    got = (nd.get("cells") or {}).get(c.key)
                    if isinstance(got, dict):
                        cs.update({k: got[k] for k in ("stamp", "seen", "ready", "failed", "failed_deps") if k in got})
                    if c.role in ("compute", "view"):       # results are not in the file: nothing computed yet
                        cs["ready"], cs["seen"] = False, {}
                        cs["failed"], cs["failed_deps"] = "", {}
                    n.cells[c.key] = cs
            if n.id in p.nodes:
                raise ProjectError(f"The project file has the node id {n.id} twice.")
            p.nodes[n.id] = n
        for ld in d.get("links") or []:
            try:
                p.links.append(Link(ld["from"], ld["from_cell"], ld["to"], ld["to_cell"]))
            except (KeyError, TypeError):
                raise ProjectError("The project file has a link that is not complete.")
        p.counter = max(p.counter, len(p.nodes))
        return p

    @classmethod
    def loads(cls, text):
        try:
            d = json.loads(text)
        except ValueError as ex:
            raise ProjectError(f"The project file is not readable: {ex}")
        return cls.from_dict(d)

    def write(self, path=None, zipped=False):
        """Saves the project: the text goes to a temporary file next to the real one, then replaces it, so a failure on the way (full disk, power) leaves
        the old file whole.  zipped=True writes the same document in a zip (optional; the plain file is the normal form)."""
        path = path or self.path
        if not path:
            raise ProjectError("The project has no file name yet.")
        if not path.lower().endswith(EXT):
            path += EXT
        text = self.dumps()
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".opara-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as f:
                if zipped:
                    with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
                        z.writestr(INNER, text)
                else:
                    f.write(text.encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        self.path = os.path.abspath(path)
        self.saved_rev = self.rev
        return self.path

    @classmethod
    def read(cls, path):
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as ex:
            raise ProjectError(f"The project file cannot be read: {ex}")
        if raw[:2] == b"PK":                                # a zipped project
            import io
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    raw = z.read(INNER)
            except (zipfile.BadZipFile, KeyError) as ex:
                raise ProjectError(f"The zipped project cannot be read: {ex}")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ProjectError("The project file is not text (UTF-8).")
        p = cls.loads(text)
        p.path = os.path.abspath(path)
        p.saved_rev = p.rev
        return p


def program_version():
    try:
        import version
        return str(version.__version__)
    except Exception:                                       # noqa: BLE001
        return "unknown"


# ---------------------------------------------------------------------------------------------------------------------------- payloads: files and folders in a node
def _is_text(b):
    if b"\0" in b:
        return False
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def pack_bytes(b):
    """One file as it goes into the project: {"text": ...} when it is UTF-8 text (you can read it in the .opara file), else {"b64": ...}.  Exact: unpack_bytes gives
    the same bytes back."""
    if _is_text(b):
        return {"text": b.decode("utf-8")}
    return {"b64": base64.b64encode(b).decode("ascii")}


def unpack_bytes(blob):
    if "text" in blob:
        return blob["text"].encode("utf-8")
    if "b64" in blob:
        return base64.b64decode(blob["b64"])
    raise ProjectError("A stored file has neither text nor binary content.")


def pack_file(path):
    with open(path, "rb") as f:
        b = f.read()
    d = pack_bytes(b)
    d["name"] = os.path.basename(path)
    return d


def unpack_file(blob, folder, name=None):
    """Writes a stored file into `folder`; -> its path."""
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, safe_name(name or blob.get("name") or "file"))
    with open(p, "wb") as f:
        f.write(unpack_bytes(blob))
    return p


def safe_name(name):
    n = os.path.basename(str(name).replace("\\", "/"))
    if n in ("", ".", ".."):
        raise ProjectError(f"'{name}' is not a usable file name.")
    return n


def safe_rel(rel):
    """A relative path from a project file, checked: no drive, no leading slash, no '..' (a project must not write outside the folder it is unpacked in)."""
    r = str(rel).replace("\\", "/")
    parts = r.split("/")
    if r.startswith("/") or (len(r) > 1 and r[1] == ":") or any(p in ("", ".", "..") for p in parts):
        raise ProjectError(f"The stored path '{rel}' is not allowed.")
    return "/".join(parts)


def pack_folder(folder, skip=None):
    """{relative path: {"text"|"b64"}} of every file under `folder` (skip(rel) -> True leaves a file out: results, caches)."""
    out = {}
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            if skip is not None and skip(rel):
                continue
            with open(full, "rb") as f:
                out[rel] = pack_bytes(f.read())
    return out


def unpack_folder(files, dest):
    """Writes what pack_folder made into `dest` (created); -> dest."""
    os.makedirs(dest, exist_ok=True)
    for rel, blob in files.items():
        p = os.path.join(dest, *safe_rel(rel).split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(unpack_bytes(blob))
    return dest


def rel_link(target, project_path):
    """A link to a big file: {"rel": path relative to the folder of the project file (when it can be), "abs": the full path as a hint}."""
    t = os.path.abspath(target)
    d = {"abs": t}
    if project_path:
        try:
            d["rel"] = os.path.relpath(t, os.path.dirname(os.path.abspath(project_path))).replace(os.sep, "/")
        except ValueError:                                  # another drive on Windows
            pass
    return d


def resolve_link(link, project_path):
    """The path a link points to now: relative to the project file first (the folder may have been moved or copied), then the full path; None when neither exists."""
    if project_path and link.get("rel"):
        p = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(project_path)), *str(link["rel"]).split("/")))
        if os.path.exists(p):
            return p
    p = link.get("abs")
    return p if p and os.path.exists(p) else None


def payload_bytes(data):
    """About how many bytes a payload takes in the file."""
    try:
        return len(json.dumps(data))
    except (TypeError, ValueError):
        return 0


def size_text(n):
    for unit, k in (("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= k:
            return f"{n / k:.1f} {unit}"
    return f"{n} bytes"
