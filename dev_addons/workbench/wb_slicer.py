"""wb_slicer.py - the Slicer block of the workbench (SLC-5; planning/design/slicer/PLAN.md, chapter 7).

The Parts and Assemblies wired into the block's Geometry cell are put on the plate of a printer and sliced with Orca Slicer's slicing engine (the module orca_core, built into the
Slicer add-on).  What comes out is the G-code and the toolpaths: where every road of plastic is, with its width, height and role.  The toolpaths can feed a printed-part analysis.

The cells:   Geometry (import)   the Parts and Assemblies to print (any number of wires).  Refresh checks that every wire brings something to print.
             Setup (data)        the printer, the print profile and the filament (Orca's own presets), the settings the person changed, and for each part which side is up, its turn
                                 about the vertical and where it sits on the plate (by default the parts are arranged on the bed).  Opened by double-click.
             Slicing (compute)   Update meshes the parts at print grade, arranges them, runs the engine in a worker process and keeps the result in memory.
             Preview (view)      the layers of the result, a summary and Export G-code.
Nothing of the result is saved in the project (the G-code is tens of MB); after the project is opened Slicing says "update".  What is saved is the Setup: the names of the presets, the
resolved settings they gave (so the project slices the same way after a profile update) and the changes.

Everything but the three windows is plain Python (no Qt): the functions below are what the tests call.  The windows are made when asked for.
"""
import json
import os
import threading
import time

import numpy as np

import wb_nodes as nodes
import wb_project as wp

SETUP_VERSION = 1
DEFAULT_MACHINE = "Elegoo Centauri Carbon 0.4 nozzle"
DEFAULT_PROCESS = "0.20mm Standard @Elegoo CC 0.4 nozzle"
DEFAULT_FILAMENT = "Elegoo PLA @ECC"
MESH_TOLERANCE = 0.02                       # mm: how far a facet of a curved wall may be from the true surface (a coarse picture mesh would be printed as facets)
ANGULAR_TOLERANCE = 0.2                     # radians
GAP = 6.0                                   # mm between parts that are arranged on the bed
# the side of a part that is printed face up: the matrix that turns that side to +Z (a part is printed in the pose it was modelled in: +Z)
UP = {"+Z": np.eye(3),
      "-Z": np.array([[1.0, 0, 0], [0, -1, 0], [0, 0, -1]]),
      "+X": np.array([[0.0, 0, -1], [0, 1, 0], [1, 0, 0]]),
      "-X": np.array([[0.0, 0, 1], [0, 1, 0], [-1, 0, 0]]),
      "+Y": np.array([[1.0, 0, 0], [0, 0, -1], [0, 1, 0]]),
      "-Y": np.array([[1.0, 0, 0], [0, 0, 1], [0, -1, 0]])}


class SlicerError(Exception):
    """Something the person can fix or has to know, in words."""


# ---------------------------------------------------------------------------------------------------------------------------- the engine and the profiles
def _engine_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    out = [os.environ.get("OPARA_ORCA_CORE_PYTHON", "")]
    for up in (os.path.join("..", ".."), os.path.join("..", "..", ".."), ".."):
        out.append(os.path.normpath(os.path.join(here, up, "engines", "orca_core", "python")))
    try:
        import addons
        out.append(os.path.join(addons.installed_path("slicer"), "engine", "orca_core"))
    except Exception:                                        # noqa: BLE001
        pass
    return [p for p in out if p and os.path.isdir(os.path.join(p, "orca_core"))]


def engine():
    """-> (the orca_core package, "") or (None, why not, in words).  The compiled part must be there too."""
    import sys
    try:
        import orca_core
    except ImportError:
        orca_core = None
        for p in _engine_paths():
            if p not in sys.path:
                sys.path.insert(0, p)
            try:
                import orca_core
                break
            except ImportError:
                continue
    if orca_core is None:
        return None, "The slicing engine is not part of this copy of OpenPara (the Slicer add-on's download)."
    try:
        from orca_core import _engine
        _engine._core()
    except Exception as ex:                                  # noqa: BLE001
        return None, str(ex) or "The slicing engine cannot be loaded."
    return orca_core, ""


def profiles():
    """-> (Profiles, "") or (None, why not)."""
    oc, why = engine_package()
    if oc is None:
        return None, why
    try:
        return oc.Profiles.open(), ""
    except oc.ProfileError as ex:
        return None, str(ex)


def engine_package():
    """The orca_core package without the compiled part (the profiles do not need it)."""
    import sys
    try:
        import orca_core
        return orca_core, ""
    except ImportError:
        for p in _engine_paths():
            if p not in sys.path:
                sys.path.insert(0, p)
            try:
                import orca_core
                return orca_core, ""
            except ImportError:
                continue
    return None, "The slicing engine is not part of this copy of OpenPara (the Slicer add-on's download)."


# ---------------------------------------------------------------------------------------------------------------------------- the Setup
def default_setup():
    return {"version": SETUP_VERSION, "machine": DEFAULT_MACHINE, "process": DEFAULT_PROCESS, "filament": DEFAULT_FILAMENT, "overrides": {}, "resolved": None,
            "mesh_tolerance": MESH_TOLERANCE, "parts": {}}


def part_setup(setup, key):
    """The Setup of one part (key = the id of its block, plus the component name for the parts of an assembly)."""
    return setup.setdefault("parts", {}).setdefault(key, {"up": "+Z", "turn": 0.0, "x": None, "y": None, "settings": {}})


def resolved_settings(setup, prof=None):
    """The settings of the print: the three presets resolved and the person's changes on top.  The resolved presets are kept in the Setup (`resolved`, with the names they were
    made for) so that the project slices the same way when Orca's profiles change; they are made again when a name changed or there are none yet (that needs the profiles)."""
    names = [setup["machine"], setup["process"], setup["filament"]]
    res = setup.get("resolved")
    if not res or res.get("names") != names:
        if prof is None:
            prof, why = profiles()
            if prof is None:
                raise SlicerError(why)
        try:
            base = prof.settings(*names)
        except Exception as ex:                              # noqa: BLE001  (ProfileError)
            raise SlicerError(str(ex)) from None
        res = setup["resolved"] = {"names": names, "settings": base}
    out = dict(res["settings"])
    out.update(setup.get("overrides") or {})
    return out


def bed_of(settings):
    """(x0, y0, x1, y1) of the printable area, from Orca's printable_area ("0x0", "256x0", ...)."""
    pts = []
    for s in settings.get("printable_area") or []:
        try:
            x, y = str(s).lower().split("x")
            pts.append((float(x), float(y)))
        except ValueError:
            continue
    if not pts:
        return (0.0, 0.0, 200.0, 200.0)
    a = np.array(pts)
    return (float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max()))


# ---------------------------------------------------------------------------------------------------------------------------- the geometry
def weld(vertices, faces, tol=1e-6):
    """Merges vertices that are the same point (a solid is meshed face by face, so its faces do not share vertices) and drops triangles that have collapsed."""
    v = np.asarray(vertices, float)
    f = np.asarray(faces, np.int64)
    key = np.round(v / tol).astype(np.int64)
    _u, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    f = inv.reshape(-1)[f]
    keep = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    used = np.unique(f[keep])
    remap = -np.ones(len(first), np.int64)
    remap[used] = np.arange(len(used))
    return v[first[used]], remap[f[keep]].astype(np.int32)


def mesh_of_shape(shape, tol=MESH_TOLERANCE, ang=ANGULAR_TOLERANCE):
    """The triangles of a solid at print grade: (vertices (N, 3) in mm, faces (M, 3)).  Raises SlicerError for a shape with nothing in it."""
    if shape is None:
        raise SlicerError("there is no solid to print")
    pts, tris = shape.tessellate(float(tol), float(ang))
    if not len(tris):
        raise SlicerError("the solid has no surface to print")
    return weld(np.array([[p.X, p.Y, p.Z] for p in pts], float), np.array(tris, np.int64))


def _doc_shape(doc):
    import pm_model as pm
    d = pm.Document.from_json(json.dumps(doc))
    d.rebuild()
    return d.solid


def objects_of_source(src, tol=MESH_TOLERANCE, memo=None):
    """[(key, name, vertices, faces)] of what a Part or Assembly block gives to print.  A part is one object; an assembly gives one object for every component that has a solid, in the
    place the assembly puts it.  Raises SlicerError (in words) when there is nothing to print."""
    stem = nodes.safe_stem(src.title)
    memo = memo if memo is not None else {}
    if src.kind == "part":
        doc = src.data.get("doc")
        if doc is None:
            raise SlicerError(f"'{src.title}' is empty: there is no part to print.")
        try:
            v, f = _cached(memo, ("part", src.id, json.dumps(doc, sort_keys=True), tol), lambda: mesh_of_shape(_doc_shape(doc), tol))
        except SlicerError as ex:
            raise SlicerError(f"'{src.title}' is empty: {ex}.") from None
        return [(src.id, stem, v, f)]
    if src.kind == "assembly":
        asm = src.data.get("asm")
        if asm is None:
            raise SlicerError(f"'{src.title}' is empty: there is nothing in the assembly.")
        out = []
        _assembly_objects(asm, np.eye(4), stem, src.id, tol, memo, out, 0)
        if not out:
            raise SlicerError(f"'{src.title}' has no component with a solid to print.")
        return out
    raise SlicerError(f"'{src.title}' ({src.kind}) cannot be printed: only Parts and Assemblies can.")


def _cached(memo, key, make):
    got = memo.get(key)
    if got is None:
        got = memo[key] = make()
    return got


def _assembly_objects(asm, M0, stem, nid, tol, memo, out, depth):
    import asm_model as am
    if depth > 6:
        raise SlicerError("the assembly holds assemblies inside assemblies too deep to follow")
    a = am.Assembly.from_json(json.dumps(asm))
    by_id = {c.get("id"): c for c in a.components}
    for c in a.components:
        src_c = by_id.get(c["derived"]["src"], c) if c.get("derived") else c
        M = M0 @ (np.array(c["M"], float) if c.get("derived") else a.T4(c))
        path = src_c.get("path", "")
        if not am.is_embedded(path):
            continue                                         # a component that is a file somewhere else is not kept inside the block: it cannot be printed from here
        ent = a.parts.get(am.embed_key(path))
        if ent is None:
            continue
        name = f"{stem}/{c.get('name') or c.get('id')}"
        if ent.get("kind") == "assembly":
            _assembly_objects(ent["asm"], M, name, nid, tol, memo, out, depth + 1)
            continue
        doc = ent.get("doc")
        if doc is None:
            continue
        try:
            v, f = _cached(memo, ("doc", json.dumps(doc, sort_keys=True), tol), lambda d=doc: mesh_of_shape(_doc_shape(d), tol))
        except SlicerError:
            continue                                         # a component with no solid (sketches only) is not printed
        out.append((f"{nid}/{c.get('id')}", name, v @ M[:3, :3].T + M[:3, 3], f))


def arrange(extents, bed, gap=GAP):
    """Where to put parts on the bed: [(x, y)] for the middle of each part's footprint, from [(width, depth)].  Rows from the left, then the group is centred on the bed.  A single
    part goes to the middle.  The second value is True when everything fits on the bed."""
    x0, y0, x1, y1 = bed
    if not extents:
        return [], True
    rows, row, w, h = [], [], 0.0, 0.0
    limit = (x1 - x0)
    cur_y = 0.0
    pos = []
    for i, (ew, ed) in enumerate(extents):
        if row and w + gap + ew > limit:
            cur_y += h + gap
            row, w, h = [], 0.0, 0.0
        x = w + (gap if row else 0.0)
        pos.append((x, cur_y, ew, ed))
        row.append(i)
        w = x + ew
        h = max(h, ed)
    total_w = max(p[0] + p[2] for p in pos)
    total_d = max(p[1] + p[3] for p in pos)
    ox = (x0 + x1) / 2 - total_w / 2
    oy = (y0 + y1) / 2 - total_d / 2
    centres = [(ox + p[0] + p[2] / 2, oy + p[1] + p[3] / 2) for p in pos]
    fits = total_w <= (x1 - x0) + 1e-9 and total_d <= (y1 - y0) + 1e-9
    return centres, fits


def place(objects, setup, bed):
    """[(key, name, vertices, faces, transform)] with the part turned as the Setup says and put on the plate.  Parts with a place of their own (x, y in the Setup) go there; the rest are
    arranged on the bed.  Returns (placed, notes)."""
    turned = []
    for key, name, v, f in objects:
        ps = part_setup(setup, key)
        R = UP.get(ps.get("up", "+Z"), UP["+Z"])
        a = np.radians(float(ps.get("turn") or 0.0))
        Rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1.0]])
        R = Rz @ R
        w = v @ R.T
        lo, hi = w.min(0), w.max(0)
        turned.append((key, name, v, f, R, lo, hi, ps))
    auto = [t for t in turned if t[7].get("x") is None or t[7].get("y") is None]
    centres, fits = arrange([(t[6][0] - t[5][0], t[6][1] - t[5][1]) for t in auto], bed)
    where = {t[0]: c for t, c in zip(auto, centres)}
    notes = []
    if not fits:
        notes.append("The parts do not all fit on the bed; they are arranged anyway (some are over the edge).")
    placed = []
    for key, name, v, f, R, lo, hi, ps in turned:
        cx, cy = (float(ps["x"]), float(ps["y"])) if key not in where else where[key]
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = (cx - (lo[0] + hi[0]) / 2, cy - (lo[1] + hi[1]) / 2, -lo[2])
        placed.append((key, name, v, f, T))
    return placed, notes


def build_job(oc, setup, sources, prof=None, memo=None, threads=None):
    """The Job for a Setup and the Parts / Assemblies that are wired in.  -> (job, notes).  Raises SlicerError."""
    settings = resolved_settings(setup, prof)
    tol = float(setup.get("mesh_tolerance") or MESH_TOLERANCE)
    objects = []
    for src in sources:
        objects += objects_of_source(src, tol, memo)
    if not objects:
        raise SlicerError("There is nothing to print: wire a Part or an Assembly into the Geometry cell.")
    placed, notes = place(objects, setup, bed_of(settings))
    job = oc.Job(settings, threads=threads)
    for key, name, v, f, T in placed:
        job.add_object(v, f, name=name, transform=T, settings=part_setup(setup, key).get("settings") or None)
    return job, notes


def summary(res):
    """The numbers of a Result for the Preview and the project report, as {text}."""
    est = res.estimate
    secs = float(est.time_normal_s)
    h, m = int(secs // 3600), int(round(secs % 3600 / 60.0))
    g = float(est.filament_g[0]) if len(est.filament_g) else 0.0
    mm = float(est.filament_mm[0]) if len(est.filament_mm) else 0.0
    roles = {}
    from orca_core import roles as _roles
    for rid, mm3 in zip(res.paths.role, res.paths.volumes()):
        roles[_roles.role_name(rid)] = roles.get(_roles.role_name(rid), 0.0) + float(mm3)
    return {"layers": res.paths.n_layers, "paths": len(res.paths), "time_s": secs, "time_text": (f"{h} h {m:02d} min" if h else f"{m} min"), "filament_g": g, "filament_m": mm / 1000.0,
            "volume_mm3": float(sum(roles.values())), "by_role": roles, "warnings": [str(w) for w in res.warnings],
            "gcode_mb": (os.path.getsize(res.gcode_path) / 1e6) if res.gcode_path and os.path.isfile(res.gcode_path) else 0.0}


# ---------------------------------------------------------------------------------------------------------------------------- the adapter
class SlicerAdapter(nodes.Adapter):
    kind = "slicer"
    first_cell = "setup"

    def available(self, tab):
        oc, why = engine()
        if oc is None:
            return False, why
        prof, why = profiles()
        if prof is None:
            return False, why
        return True, ""

    # ---- state
    def state(self, tab, node):
        return tab.node_state.setdefault(node.id, {})

    def setup_of(self, node):
        s = node.data.get("setup")
        if not isinstance(s, dict) or s.get("version") != SETUP_VERSION:
            s = node.data["setup"] = default_setup() if not isinstance(s, dict) else {**default_setup(), **s, "version": SETUP_VERSION}
        return s

    def created(self, tab, node):
        self.setup_of(node)
        tab.project.set_ready(node.id, "setup", True)

    def sources(self, tab, node):
        prj = tab.project
        out = []
        for k in prj.incoming_all(node.id, "geometry"):
            n = prj.nodes.get(k.a)
            if n is not None:
                out.append(n)
        return out

    def result_of(self, tab, node):
        """The Result of the last Update in this session, or None (it is not saved in the project)."""
        return self.state(tab, node).get("result")

    # ---- cells
    def refresh(self, tab, node, key):
        if key != "geometry":
            return None
        src = self.sources(tab, node)
        if not src:
            return "There is no wire into this cell: nothing to print."
        for n in src:
            if n.kind not in ("part", "assembly"):
                return f"'{n.title}' is a {n.kind}: only Parts and Assemblies can be printed."
            if n.data.get("doc" if n.kind == "part" else "asm") is None:
                return f"'{n.title}' is empty: there is nothing to print."
        return None

    def update(self, tab, node, key):
        if key != "slicing":
            return None
        st = self.state(tab, node)
        oc, why = engine()
        if oc is None:
            return why
        prof, why = profiles()
        if prof is None:
            return why
        setup = self.setup_of(node)
        memo = st.setdefault("meshes", {})
        try:
            job, notes = build_job(oc, setup, self.sources(tab, node), prof, memo, threads=st.get("threads"))
        except SlicerError as ex:
            return str(ex)
        except ValueError as ex:
            return str(ex)
        for n in notes:
            tab.note(f"{node.label} {node.title}: {n}")
        out = os.path.join(nodes.workspace_of(tab, node), "gcode")
        os.makedirs(out, exist_ok=True)
        cancel = st["cancel"] = threading.Event()
        last = [0.0]

        def progress(pct, msg):
            now = time.monotonic()
            if now - last[0] < 0.2 and pct < 100:
                return
            last[0] = now
            try:
                tab.say(f"{node.title}: slicing {pct:.0f}%  {msg}")
                from PyQt6.QtWidgets import QApplication
                if QApplication.instance() is not None:
                    QApplication.processEvents()
            except Exception:                                # noqa: BLE001
                pass

        st.pop("result", None)
        try:
            res = job.slice(progress=progress, cancel=cancel, output_dir=out)
        except oc.ConfigError as ex:
            where = f" (part '{ex.object}')" if getattr(ex, "object", None) else ""
            st["error_key"] = ex.key
            return f"Setting {ex.key}{where}: {ex.message}" if ex.key else str(ex)
        except oc.Cancelled:
            return "Slicing was cancelled."
        except oc.OrcaCoreError as ex:
            return str(ex)
        finally:
            st.pop("cancel", None)
        st["result"] = res
        st["summary"] = summary(res)
        # the project changed in what it can say: the setup was resolved (and kept) while slicing
        for w in res.warnings:
            tab.note(f"{node.label} {node.title}: {w}")
        tab.say(f"{node.title}: {st['summary']['layers']} layers, {st['summary']['time_text']}, {st['summary']['filament_g']:.1f} g")
        return None

    def cancel(self, tab, node):
        ev = self.state(tab, node).get("cancel")
        if ev is not None:
            ev.set()
            return True
        return False

    def open_cell(self, tab, node, key):
        if key == "geometry":
            src = self.sources(tab, node)
            tab.say(f"'{node.title}': {len(src)} part(s) wired in: " + (", ".join(n.title for n in src) if src else "none yet; wire a Part or an Assembly into this cell."))
            return None
        if key == "setup":
            return open_setup(tab, node, self)
        if key in ("slicing", "preview"):
            res = self.result_of(tab, node)
            if res is None:
                tab.say(f"'{node.title}' has not been sliced in this session: press Update (Update Project) first.")
                return None
            return open_preview(tab, node, self, res)
        return None

    def closed(self, tab, node):
        ev = self.state(tab, node).get("cancel")
        if ev is not None:
            ev.set()
        tab.node_state.pop(node.id, None)

    def export(self, tab, node, folder):
        d = os.path.join(folder, nodes.safe_stem(node.title) + ".slicer")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "slicer.json"), "w", encoding="utf-8") as f:
            json.dump({"format": "openpara-slicer", "version": 1, "setup": self.setup_of(node)}, f, indent=1)
        return d

    # ---- what the person does in the windows, kept apart from the windows so the tests can do it
    def apply_setup(self, tab, node, setup):
        """A Setup edited in the window: kept, and the cells after it say so."""
        old = json.dumps(self.setup_of(node), sort_keys=True)
        node.data["setup"] = setup
        if json.dumps(setup, sort_keys=True) != old:
            tab.project.touch(node.id, "setup")
            tab.project.set_ready(node.id, "setup", True)
            if hasattr(tab, "scene"):
                tab.scene.refresh()
            return True
        return False

    def export_gcode(self, tab, node, path):
        res = self.result_of(tab, node)
        if res is None or not res.gcode_path or not os.path.isfile(res.gcode_path):
            raise SlicerError("There is no G-code yet: update the Slicing cell first.")
        import shutil
        shutil.copyfile(res.gcode_path, path)
        return path


nodes.register(SlicerAdapter())


# ---------------------------------------------------------------------------------------------------------------------------- the windows
def open_setup(tab, node, adapter):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                                 QVBoxLayout)
    setup = json.loads(json.dumps(adapter.setup_of(node)))
    prof, why = profiles()
    d = QDialog(tab)
    d.setWindowTitle(f"Slicer setup: {node.title}")
    v = QVBoxLayout(d)
    if prof is None:
        v.addWidget(QLabel(why))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        d.exec()
        return None
    form = QFormLayout()
    vendor_box, machine_box, process_box, filament_box = QComboBox(), QComboBox(), QComboBox(), QComboBox()
    for w in (vendor_box, machine_box, process_box, filament_box):
        w.setMinimumWidth(320)
    form.addRow("Vendor", vendor_box)
    form.addRow("Printer", machine_box)
    form.addRow("Print profile", process_box)
    form.addRow("Filament", filament_box)
    vendors = [x for x in prof.vendors() if x not in ("OrcaFilamentLibrary", "Custom") or x == "Custom"]
    vendor_box.addItems(vendors)

    def vendor_of(machine):
        for x in prof.vendors():
            for m in prof.machines(x):
                if m.name == machine:
                    return x
        return None

    def fill_machines():
        machine_box.blockSignals(True)
        machine_box.clear()
        machine_box.addItems([m.name for m in prof.machines(vendor_box.currentText())])
        machine_box.blockSignals(False)

    def fill_rest(keep=True):
        m = machine_box.currentText()
        if not m:
            return
        pr = [p.name for p in prof.processes(m)]
        fl = sorted(p.name for p in prof.filaments(m))
        r = prof.resolve("machine", m, vendor_of(m))
        want_p = setup["process"] if keep and setup["process"] in pr else r.get("default_print_profile") or (pr[0] if pr else "")
        want_f = setup["filament"] if keep and setup["filament"] in fl else (r.get("default_filament_profile") or [""])[0] or (fl[0] if fl else "")
        for box, items, want in ((process_box, pr, want_p), (filament_box, fl, want_f)):
            box.blockSignals(True)
            box.clear()
            box.addItems(items)
            if want in items:
                box.setCurrentText(want)
            box.blockSignals(False)

    cur = vendor_of(setup["machine"]) or (vendors[0] if vendors else "")
    vendor_box.setCurrentText(cur)
    fill_machines()
    machine_box.setCurrentText(setup["machine"])
    fill_rest(True)
    vendor_box.currentTextChanged.connect(lambda _t: (fill_machines(), fill_rest(False)))
    machine_box.currentTextChanged.connect(lambda _t: fill_rest(False))
    tol = QDoubleSpinBox()
    tol.setDecimals(3)
    tol.setRange(0.001, 0.5)
    tol.setSingleStep(0.005)
    tol.setSuffix(" mm")
    tol.setValue(float(setup.get("mesh_tolerance") or MESH_TOLERANCE))
    form.addRow("Surface accuracy", tol)
    v.addLayout(form)
    v.addWidget(QLabel("Settings changed from the profile (Orca's setting names, for example sparse_infill_density = 30%):"))
    table = QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(["Setting", "Value"])
    table.horizontalHeader().setStretchLastSection(True)
    for k, val in sorted((setup.get("overrides") or {}).items()):
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r, 0, QTableWidgetItem(k))
        table.setItem(r, 1, QTableWidgetItem(", ".join(val) if isinstance(val, list) else str(val)))
    v.addWidget(table)
    row = QHBoxLayout()
    b_add, b_del = QPushButton("Add a setting"), QPushButton("Remove the selected")
    b_add.clicked.connect(lambda: table.insertRow(table.rowCount()))
    b_del.clicked.connect(lambda: [table.removeRow(i.row()) for i in sorted(table.selectionModel().selectedRows(), key=lambda i: -i.row())])
    row.addWidget(b_add)
    row.addWidget(b_del)
    row.addStretch(1)
    v.addLayout(row)
    # the parts: which side is up, the turn, where
    srcs = adapter.sources(tab, node)
    parts_tab = QTableWidget(0, 5)
    parts_tab.setHorizontalHeaderLabels(["Part", "Side up", "Turn (deg)", "X (mm, blank: arrange)", "Y (mm)"])
    keys = []
    try:
        memo = adapter.state(tab, node).setdefault("meshes", {})
        for s in srcs:
            for key, name, _v, _f in objects_of_source(s, float(tol.value()), memo):
                keys.append((key, name))
    except SlicerError as ex:
        v.addWidget(QLabel(str(ex)))
    for key, name in keys:
        ps = part_setup(setup, key)
        r = parts_tab.rowCount()
        parts_tab.insertRow(r)
        parts_tab.setItem(r, 0, QTableWidgetItem(name))
        parts_tab.item(r, 0).setFlags(parts_tab.item(r, 0).flags() & ~Qt.ItemFlag.ItemIsEditable)
        cb = QComboBox()
        cb.addItems(list(UP))
        cb.setCurrentText(ps.get("up", "+Z"))
        parts_tab.setCellWidget(r, 1, cb)
        parts_tab.setItem(r, 2, QTableWidgetItem(f"{float(ps.get('turn') or 0):g}"))
        parts_tab.setItem(r, 3, QTableWidgetItem("" if ps.get("x") is None else f"{float(ps['x']):g}"))
        parts_tab.setItem(r, 4, QTableWidgetItem("" if ps.get("y") is None else f"{float(ps['y']):g}"))
    if keys:
        v.addWidget(QLabel("Parts on the plate (the side that is up is printed upwards: it decides how the layers lie in the part):"))
        v.addWidget(parts_tab)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    d.resize(640, 700)
    if d.exec() != QDialog.DialogCode.Accepted:
        return None
    new = json.loads(json.dumps(setup))
    new["machine"], new["process"], new["filament"] = machine_box.currentText(), process_box.currentText(), filament_box.currentText()
    new["mesh_tolerance"] = float(tol.value())
    new["overrides"] = {}
    for r in range(table.rowCount()):
        k = (table.item(r, 0).text() if table.item(r, 0) else "").strip()
        val = (table.item(r, 1).text() if table.item(r, 1) else "").strip()
        if k:
            new["overrides"][k] = val
    for r, (key, _name) in enumerate(keys):
        ps = part_setup(new, key)
        ps["up"] = parts_tab.cellWidget(r, 1).currentText()
        for col, field in ((2, "turn"), (3, "x"), (4, "y")):
            txt = (parts_tab.item(r, col).text() if parts_tab.item(r, col) else "").strip()
            try:
                ps[field] = float(txt) if txt else (0.0 if field == "turn" else None)
            except ValueError:
                ps[field] = 0.0 if field == "turn" else None
    new["resolved"] = None                                   # made again from the names, with the profiles of this computer
    try:
        resolved_settings(new, prof)
    except SlicerError as ex:
        tab.say(f"The setup was not changed: {ex}")
        return None
    adapter.apply_setup(tab, node, new)
    return d


def open_preview(tab, node, adapter, res):
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QColor, QPainter, QPen
    from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget
    from orca_core import roles as R
    info = summary(res)
    colours = {"Outer wall": "#2e5aa8", "Inner wall": "#7aa3d9", "Overhang wall": "#c44", "Sparse infill": "#d6892b", "Internal solid infill": "#b5651d", "Top surface": "#c22",
               "Bottom surface": "#7a3", "Bridge": "#a0a", "Internal Bridge": "#a5a", "Gap infill": "#fa0", "Skirt": "#888", "Brim": "#999", "Support": "#2aa",
               "Support interface": "#2cc", "Ironing": "#e88", "Custom": "#aaa"}

    class LayerView(QWidget):
        def __init__(self):
            super().__init__()
            self.layer = res.paths.n_layers - 1
            self.setMinimumSize(520, 420)

        def paintEvent(self, _e):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.fillRect(self.rect(), QColor("#1b1d21"))
            lay = res.paths.layer_slice(self.layer)
            if not len(lay):
                return
            allp = res.paths.points[:, :2]
            lo, hi = allp.min(0), allp.max(0)
            s = 0.92 * min(self.width() / max(hi[0] - lo[0], 1e-6), self.height() / max(hi[1] - lo[1], 1e-6))
            ox = (self.width() - s * (hi[0] - lo[0])) / 2
            oy = (self.height() - s * (hi[1] - lo[1])) / 2

            def xy(pt):
                return QPointF(ox + (pt[0] - lo[0]) * s, self.height() - oy - (pt[1] - lo[1]) * s)

            for i in range(len(lay)):
                pts = lay.path(i)[:, :2] if hasattr(lay, "path") else np.zeros((0, 2))
                if len(pts) < 2:
                    continue
                name = R.role_name(lay.role[i])
                pen = QPen(QColor(colours.get(name, "#ccc")), max(1.0, float(lay.width[i]) * s))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                for a, b in zip(pts[:-1], pts[1:]):
                    p.drawLine(xy(a), xy(b))

    d = QDialog(tab)
    d.setWindowTitle(f"Slicer preview: {node.title}")
    v = QVBoxLayout(d)
    head = QLabel(f"{info['layers']} layers  |  {info['time_text']}  |  {info['filament_g']:.1f} g ({info['filament_m']:.2f} m) of filament  |  G-code {info['gcode_mb']:.1f} MB")
    v.addWidget(head)
    view = LayerView()
    v.addWidget(view, 1)
    row = QHBoxLayout()
    sl = QSlider(Qt.Orientation.Horizontal)
    sl.setRange(1, max(1, res.paths.n_layers))
    sl.setValue(res.paths.n_layers)
    lab = QLabel()

    def moved(n):
        view.layer = n - 1
        lab.setText(f"Layer {n} of {res.paths.n_layers}   z = {res.paths.layer_z[n - 1]:.2f} mm")
        view.update()

    sl.valueChanged.connect(moved)
    moved(res.paths.n_layers)
    row.addWidget(sl, 1)
    row.addWidget(lab)
    v.addLayout(row)
    if info["warnings"]:
        v.addWidget(QLabel("Warnings: " + "; ".join(info["warnings"][:5])))
    b = QHBoxLayout()
    bx = QPushButton("Export G-code...")

    def export():
        f, _ = QFileDialog.getSaveFileName(d, "Export G-code", nodes.safe_stem(node.title) + ".gcode", "G-code (*.gcode);;All files (*)")
        if f:
            try:
                adapter.export_gcode(tab, node, f)
                tab.say(f"G-code saved to {f}")
            except (SlicerError, OSError) as ex:
                tab.say(str(ex))

    bx.clicked.connect(export)
    bc = QPushButton("Close")
    bc.clicked.connect(d.accept)
    b.addWidget(bx)
    b.addStretch(1)
    b.addWidget(bc)
    v.addLayout(b)
    d.resize(760, 640)
    d.exec()
    return d
