"""
sim_tab.py - the 1D FEA, 2D FEA and 2D CFD containers (a "simulation" document tab, saved as a PROJECT FOLDER: .gpb / .gpf / .gpc).

A simulation is a project folder (sim_project.py).  New project makes the folder; Import copies a part or an assembly INTO it (source/), and
the simulation only ever works on that copy (sim_source.py), so the original can be moved or deleted.  What it solves is a snapshot of
  * a part:      one of its sketches, or a slice - a plane that cuts the part (a base plane, a reference plane, with an offset)
  * an assembly: only a slice (a plane cuts all its parts; touching parts are bonded)
"Update from original" copies the original again into the project and takes the snapshot again; that clears the mesh and result.
The material of the part (Material in its tree) fills the material boxes by itself; in an assembly slice every region uses the material
of the part it was cut from.  The solvers and tabs are the ones of the earlier program (physics_tab, cfd_tab, beam_tab).
"""
import json
import os
import types

import numpy as np

from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout,
                             QWidget)

import beam_tab
import cfd_tab
import ext
import mat_lib
import physics_materials as pmat
import physics_store as pstore
import physics_tab
import sim_project
import sim_slice
import sim_source
import sketcher_core as sc
import ui_kit
import slice3d
import slice_sketch as ss
import unitctl
import units

KINDS = {"beam": ("1D FEA", beam_tab.BeamTab), "fea": ("2D FEA", physics_tab.PhysicsTab), "cfd": ("2D CFD", cfd_tab.CFDTab)}
SLICE_NEW, SLICE_LAST = "__slice_new__", "__slice_last__"


class _HostModel:
    """The solver tabs read `win.m.unit_system`: it is the program's unit system (File > Units)."""

    @property
    def unit_system(self):
        return unitctl.system()


class SimHost:
    """What the solver tabs call their 'window': they ask it for the sketches to import and show its status."""

    def __init__(self, sim):
        self.sim = sim
        self.doc = None
        self.m = _HostModel()
        self._restoring = False

    def status(self, text):
        self.sim.status_lbl.setText(text)

    def sketch_list(self):
        return self.sim.source_items()

    def sketch_json(self, sid):
        return self.sim.source_json(sid)


def fill_material(tab, kind, mat):
    """Puts a part material into the material boxes of a 1D / 2D FEA tab (in the tab's units).  False when it has no elastic values."""
    e = mat_lib.elastic(mat_lib.with_elastic(mat))
    if e is None:
        return False
    E, nu, sy, su = e
    u = tab.cur_unit
    tab.mat_combo.blockSignals(True)
    tab.mat_combo.setCurrentIndex(0)                                  # "(custom values)": the values come from the part
    tab.mat_combo.blockSignals(False)
    tab.e_E.setText(f"{pmat.from_mpa(E, u):.10g}")
    tab.e_sy.setText(f"{pmat.from_mpa(sy, u):.10g}")
    tab.e_su.setText(f"{pmat.from_mpa(su, u):.10g}")
    if kind == "fea":
        tab.e_nu.setText(f"{nu:.6g}")
    return True


class SimWindow(QWidget):
    plotter = None
    nav = None

    def __init__(self, kind, shell=None, src_tab=None, path=None):
        super().__init__()
        self.kind = kind
        self.label, cls = KINDS[kind]
        self.shell = shell
        self.candidate = src_tab                  # an open part / assembly tab that Import offers first (the ribbon button of that tab)
        self.path = path                          # the project folder (None until New project / Open project)
        self.source = None                        # the sim_source.Source loaded from the project's copy
        self.src = {"type": "asm" if (src_tab is not None and hasattr(src_tab, "asm")) else "part", "path": getattr(src_tab, "path", None),
                    "name": src_tab.title() if src_tab is not None else ""}
        self.meta = {"sid": None, "slice": None}
        self.pending = None
        self.units_note = ""
        self.host = SimHost(self)
        self.saved_sig = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(ui_kit.kind_chip(self.label, "#7c4dcc"))      # the same bar as the Truss, Visualize and Study tabs: what it is, then its commands
        self.src_lbl = QLabel()
        self.src_lbl.setWordWrap(True)
        self.src_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        bar.addWidget(self.src_lbl, 1)
        self.b_new = QPushButton("New project...")
        self.b_new.setToolTip(f"Makes the project folder of this simulation ({sim_project.ext_of(kind)}). The source is copied into it, so the "
                              "simulation never depends on the original part.")
        self.b_new.clicked.connect(self.new_project)
        bar.addWidget(self.b_new)
        self.b_import = QPushButton("Import source...")
        self.b_import.setToolTip("Copies a part or an assembly into the project folder (an open tab, or a .gpd / .gpa file). The simulation "
                                 "works on the copy; the original can be moved or deleted.")
        self.b_import.clicked.connect(self.import_source)
        bar.addWidget(self.b_import)
        self.b_refresh = QPushButton("Update from original")
        self.b_refresh.setToolTip("Copies the original part / assembly into the project again (as it is now) and takes the sketch or the slice "
                                  "again. This clears the mesh and result, because the geometry may have changed.")
        self.b_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.b_refresh)
        lay.addLayout(bar)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#707070;")
        self.tab = cls(self.host)
        self.tab.picker.on_import = self.on_imported
        self.empty = ui_kit.EmptyState("", "", [("New project...", self.new_project), ("Import source...", self.import_source)])
        self.stack = QStackedWidget()                        # the guidance while there is nothing to work on; the solver tab once there is
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tab)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.status_lbl)
        self.status_lbl.hide()                               # one status line per tab: the solver tab's own (see say)
        self.b_study = QPushButton("Create parametric study")
        self.b_study.setToolTip("Opens a parametric study tab for this simulation: the inputs to vary, the cases to run and the results. The "
                                "study is saved in the project folder (study/).")
        self.b_study.clicked.connect(self.open_study)
        self.tab.study_box.layout().addWidget(self.b_study)
        self.show_source()
        self.saved_sig = self.signature()

    # ------------------------------------------------------------------ title / dirty / files
    def title(self):
        if self.path:
            return os.path.splitext(os.path.basename(self.path.rstrip("/\\")))[0]
        return f"{self.label} - {os.path.splitext(self.src.get('name') or 'new')[0]}"

    def show_source(self):
        have = self.project_ok()
        self.refresh_study_button()
        self.b_new.setVisible(not have)
        self.b_import.setEnabled(have)
        self.b_refresh.setEnabled(self.source is not None)
        what = "a part" if self.kind == "beam" else "a part or an assembly"
        self.stack.setCurrentWidget(self.tab if have and self.source is not None else self.empty)
        if not have:
            self.src_lbl.setText("No project yet")
            self.empty.set_text(f"Start a {self.label} project",
                                f"A simulation is a project folder with its own copy of {what}, so it never depends on the original. "
                                f"Make the folder, then import {what} into it.")
            self.empty.buttons[0].setVisible(True)
            self.empty.buttons[1].setStyleSheet("")
            return
        if self.source is None:
            self.src_lbl.setText(f"Project <b>{os.path.basename(self.path.rstrip('/' + chr(92)))}</b> - nothing imported yet")
            self.empty.set_text(f"Import {what}",
                                f"The project folder is made. Import {what} - from a tab that is open, or from a file. The simulation works on "
                                "its own copy; you then choose the sketch" + (" of the part." if self.kind == "beam" else " or the slice to analyse."))
            self.empty.buttons[0].setVisible(False)
            ui_kit.primary(self.empty.buttons[1])
            return
        kind = "assembly" if self.src["type"] == "asm" else "part"
        rule = ("slice only (a plane through the parts; touching parts are bonded)" if kind == "assembly" else
                ("sketch of the part" if self.kind == "beam" else "sketch of the part, or a slice"))
        self.src_lbl.setText(f"of the {kind} <b>{self.src.get('name') or '?'}</b> (the copy in the project) - works on: {rule}")
        self.refresh_study_button()

    def refresh_study_button(self):
        """The parametric-study button under Solve: only when the Parametric Studies add-on is installed."""
        on = bool(ext.hooks("sim_study"))
        self.tab.study_box.setVisible(on)
        if not on:
            return
        have = bool(self.path) and os.path.isfile(os.path.join(self.path, sim_project.STUDY_DIR, "study.json"))
        self.b_study.setText("Open parametric study" if have else "Create parametric study")
        self.b_study.setEnabled(True)                  # a click that cannot work says why (open_study), instead of a grey button that says nothing

    def open_study(self):
        """Saves the simulation (the study lives in its project folder) and opens its parametric study tab."""
        fns = ext.hooks("sim_study")
        if not fns:
            QMessageBox.information(self, "Parametric study", "The Parametric Studies add-on is not loaded. Install or enable it, then restart.")
            return None
        if not self.project_ok():
            QMessageBox.information(self, "Parametric study", "This simulation has no project folder yet. Press 'New project...', import a part, "
                                    "choose a sketch or a slice and press Import. The study is saved in that project.")
            return None
        # a study opens as soon as there is a project folder: the study tab itself says what is still missing (a sketch, supports...) and only a
        # run needs it
        if self.is_dirty():
            if not self.save():
                return None
        return fns[0](self)

    def project_ok(self):
        return bool(self.path) and sim_project.kind_of_folder(self.path) == self.kind

    def signature(self):
        t = self.tab
        if getattr(t, "model", None) is None:
            return None
        try:
            ins = pstore.get_inputs(t, t.INPUTS)
        except Exception:
            ins = {}
        return (repr(getattr(t, "supports", None)), repr(getattr(t, "loads", None)), id(getattr(t, "mesh", None)),
                id(getattr(t, "result", None)), repr(sorted(ins.items())), repr(getattr(t, "members", None)),
                repr([bool(f["included"]) for f in t.geom["faces"]]) if getattr(t, "geom", None) else "")

    def is_dirty(self):
        return self.signature() != self.saved_sig

    # ------------------------------------------------------------------ the project folder
    def new_project(self):
        """Asks where to put the project folder, makes it, and offers the import of the source."""
        folder = os.path.dirname(self.src["path"]) if self.src.get("path") else ""
        start = sim_project.default_name(self.kind, self.src.get("name") or self.label, folder or os.getcwd())
        ext = sim_project.ext_of(self.kind)
        path, _ = QFileDialog.getSaveFileName(self, "New simulation project (a folder)", start, f"{self.label} project (*{ext})")
        if not path:
            return False
        return self.create_project(path)

    def create_project(self, path):
        ext = sim_project.ext_of(self.kind)
        if not path.lower().endswith(ext):
            path += ext
        try:
            sim_project.create(path, self.kind)
        except sim_project.ProjectError as ex:
            QMessageBox.warning(self, "New project", str(ex))
            return False
        self.path = os.path.abspath(path)
        self.show_source()
        self.say(f"Project folder {self.path} made.")
        self.retitle()
        if self.candidate is not None and self.candidate_ok():
            return self.import_tab(self.candidate)
        return True

    def retitle(self):
        """The tab strip and the title bar show the new name at once (not at the window's next look)."""
        try:
            if self.shell is not None:
                self.shell.refresh_titles()
        except Exception:
            pass

    def say(self, text):
        """A message of the project (made, saved, imported).  It is shown on the tab's one status line, next to the coordinates; the window's
        own label is kept (hidden) for what reads it."""
        self.status_lbl.setText(text)
        try:
            self.tab.status_lbl.setText(text)
            self.tab.status_lbl.setToolTip(text)
        except (AttributeError, RuntimeError):
            pass

    def candidate_ok(self):
        c = self.candidate
        try:                                             # the part's tab may have been closed since: Qt has deleted it, touching it raises
            c.title()
            if self.shell is not None and self.shell.tabs.indexOf(c) < 0:
                return False
        except RuntimeError:
            return False
        return self.kind != "beam" or not hasattr(c, "asm")

    def open_tabs(self):
        """[(label, tab)] of the open parts and assemblies the source can come from."""
        out = []
        if self.shell is None:
            return out
        for i in range(self.shell.tabs.count()):
            w = self.shell.tabs.widget(i)
            if hasattr(w, "asm") or (getattr(w, "doc", None) is not None and hasattr(w.doc, "features")):
                if self.kind == "beam" and hasattr(w, "asm"):
                    continue
                out.append((("assembly - " if hasattr(w, "asm") else "part - ") + w.title(), w))
        return out

    def import_source(self):
        """Choose what to copy into the project: an open part / assembly tab, or a file."""
        if not self.project_ok():
            if not self.new_project():
                return False
            if self.source is not None:
                return True
        dlg = QDialog(self)
        dlg.setWindowTitle("Import source")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Copy this into the project (the simulation then works on the copy):"))
        lst = QListWidget()
        tabs = self.open_tabs()
        for text, w in tabs:
            lst.addItem(text)
        if self.candidate is not None:
            for i, (_t, w) in enumerate(tabs):
                if w is self.candidate:
                    lst.setCurrentRow(i)
        elif tabs:
            lst.setCurrentRow(0)
        lay.addWidget(lst)
        pick = {"file": None}
        b_file = QPushButton("Browse for a .gpd / .gpa file...")
        lay.addWidget(b_file)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        lay.addWidget(bb)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)

        def browse():
            filt = "Part (*.gpd)" if self.kind == "beam" else "Part or assembly (*.gpd *.gpa)"
            f, _ = QFileDialog.getOpenFileName(dlg, "Part or assembly to copy", os.path.dirname(self.src.get("path") or ""), filt)
            if f:
                pick["file"] = f
                dlg.accept()
        b_file.clicked.connect(browse)
        if not dlg.exec():
            return False
        if pick["file"]:
            return self.import_file(pick["file"])
        row = lst.currentRow()
        if row < 0:
            return False
        return self.import_tab(tabs[row][1])

    def import_tab(self, w):
        """Copies an open part / assembly tab into the project: its live state (unsaved edits included) and, for an assembly, its part files."""
        p = getattr(w, "path", None)
        if hasattr(w, "asm"):
            text = w.asm.to_json()
            if not p:
                QMessageBox.information(self, "Import source", "Save the assembly once first: its parts are found from its file.")
                return False
        else:
            text = w.doc.to_json()
        return self.do_import(p, text, name=(os.path.splitext(os.path.basename(p))[0] if p else w.title()), ext=".gpa" if hasattr(w, "asm") else ".gpd")

    def import_file(self, path):
        return self.do_import(path, None)

    def do_import(self, orig, text, name=None, ext=None):
        """The copy itself: files into source/, the source loaded, the tab told.  The geometry the tab holds is cleared."""
        if not self.project_ok():
            return False
        t = self.tab
        if getattr(t, "model", None) is not None and (t.result is not None or t.mesh is not None or getattr(t, "supports", None) or getattr(t, "loads", None)):
            if QMessageBox.question(self, "Import source", "Importing a source replaces the copy in the project and clears the supports, loads, mesh and "
                                    "result of this simulation. Continue?") != QMessageBox.StandardButton.Yes:
                return False
        try:
            fake = orig if orig else os.path.join(self.path, (name or "source") + (ext or ".gpd"))
            m, missing = sim_project.import_source(self.path, orig_path=fake, text=text, name=name)
            self.source = sim_source.open_source(sim_project.source_file(self.path, m))
        except (sim_project.ProjectError, sim_source.SourceError) as ex:
            QMessageBox.warning(self, "Import source", str(ex))
            return False
        if self.kind == "beam" and self.source.type == "asm":
            QMessageBox.information(self, "Import source", "1D FEA works on a sketch of a part. An assembly can only be used for 2D, through a slice.")
            self.source = None
            return False
        self.src = {"type": self.source.type, "path": orig, "name": m["source"]["name"]}
        self.meta = {"sid": None, "slice": None}
        self.pending = None
        self.tab.picker.refresh()
        self.show_source()
        msg = f"Copied {m['source']['name']} into the project ({m['source']['file']})."
        if missing:
            msg += "  Not found, left out of the copy: " + ", ".join(sorted(set(missing))) + "."
        self.say(msg + "  Choose a sketch or a slice and press Import.")
        self.save()
        return True

    def save(self, as_new=False):
        if as_new or not self.project_ok():
            if not self.new_project():
                return False
        folder = self.path
        m = sim_project.read(folder)
        m["meta"] = self.meta
        try:
            sim_project.write(folder, m)
            pstore.save(sim_project.state_path(folder), {"main": self.tab}, extras={"sim.json": json.dumps({"kind": self.kind, "meta": self.meta}).encode("utf-8")})
        except Exception as ex:
            import traceback
            QMessageBox.warning(self, "Save", f"Could not save: {ex}\n\n{traceback.format_exc()}")
            return False
        self.saved_sig = self.signature()
        self.say(f"Saved {folder}")
        return True

    @classmethod
    def open_project(cls, shell, folder):
        folder = os.path.abspath(folder.rstrip("/\\") or folder)
        kind = sim_project.kind_of_folder(folder)
        if kind is None:
            raise ValueError("not a simulation project folder")
        m = sim_project.read(folder)
        w = cls(kind, shell=shell, src_tab=None, path=folder)
        s = m.get("source") or {}
        w.src = {"type": s.get("type", "part"), "path": s.get("orig"), "name": s.get("name", "")}
        w.meta = m.get("meta") or {"sid": None, "slice": None}
        note = ""
        sf = sim_project.source_file(folder, m)
        if sf:
            try:
                w.source = sim_source.open_source(sf)
            except sim_source.SourceError as ex:
                note = str(ex)
        w.show_source()
        sp = sim_project.state_path(folder)
        if os.path.isfile(sp):
            data = pstore.load(sp) or {}
            st = data.get("main")
            if st is not None:
                try:                                       # a file saved in other units opens converted to the program's units
                    st = pstore.to_current_units(kind, st, unitctl.system(), unitctl.speed())
                except (ValueError, KeyError) as ex:
                    w.units_note = f"kept in its own units ({ex})"
                w.host._restoring = True
                try:
                    w.tab.import_state(st)
                finally:
                    w.host._restoring = False
        if note:
            w.say(note)
        w.tab.picker.refresh()
        w.saved_sig = w.signature()
        return w

    def update_all(self, fit=False):
        pass

    def units_changed(self, old_s, new_s, old_v, new_v):
        """File > Units was changed: the solver tab's sketch copy, numbers, loads and results are converted (a mesh or result that
        cannot be converted is cleared - solve again).  The speed unit is converted separately."""
        t = self.tab
        msgs = []
        if getattr(t, "model", None) is None:
            try:                                           # nothing imported yet: only the boxes hold numbers
                if units.canon(old_s) != units.canon(new_s):
                    if hasattr(t, "convert_input_units"):
                        t.convert_input_units(new_s)
                    elif hasattr(t, "apply_units"):
                        t.apply_units(new_s)
                if old_v != new_v and hasattr(t, "e_speed"):
                    txt = t.e_speed.text().strip()
                    if txt:
                        t.e_speed.setText(f"{float(txt) * units.speed_factor(old_v, new_v):.6g}")
            except Exception:
                pass
            return
        if units.canon(old_s) != units.canon(new_s):
            try:
                m = t.change_units(old_s, new_s, True)
                if m:
                    msgs.append(m)
            except ValueError as ex:
                msgs.append(f"kept in {old_s}: {ex}")
        if old_v != new_v and self.kind in ("cfd", "beam"):
            t.import_state(pstore.speed_state(t.export_state(), old_v, new_v))
        self.status_lbl.setText(f"Units: {new_s}, speed in {new_v}." + ((" " + " ".join(msgs)) if msgs else ""))

    # ------------------------------------------------------------------ the source
    def source_widget(self):
        """What the solver tabs ask for the sketches, the planes and the solids: the Source loaded from the project's copy (None until imported)."""
        return self.source

    def part_doc(self):
        s = self.source
        return s.doc if s is not None and s.type == "part" else None

    def bodies(self):
        """[(name, solid, material)] of the source copy (a part: itself; an assembly: its parts, placed)."""
        s = self.source
        if s is None:
            return []
        if s.type == "part":
            d = s.doc
            return [(self.src.get("name") or "part", d.solid, d.material)] if d is not None and d.solid is not None else []
        import asm_sub
        return asm_sub.bodies_of(s, s.asm)

    def planes(self):
        w = self.source
        if w is None:
            return []
        if w.type == "part":
            return slice3d.part_plane_specs(w.doc) if w.doc is not None else []
        return slice3d.asm_plane_specs(w.asm)

    def visible_planes(self):
        """The planes the source viewport shows (hidden planes are left out of the slice window)."""
        return sim_slice.visible_planes(self.source, self.src["type"])

    def source_items(self):
        items = []
        d = self.part_doc() if self.src["type"] == "part" else None
        if d is not None:
            items += [(f["id"], f["name"]) for f in d.features if f["kind"] == "sketch"]
        if self.kind != "beam":
            items.append((SLICE_NEW, "Slice with a plane..."))
            sl = self.meta.get("slice")
            if sl:
                items.append((SLICE_LAST, "Slice again: " + self.slice_text(sl)))
        return items

    @staticmethod
    def slice_text(sl):
        return f"{sl['plane']} {unitctl.to_disp(sl.get('offset', 0)):+.6g} {unitctl.length_unit()}" + (" (flipped)" if sl.get("flip") else "")

    def source_json(self, sid):
        """(name, sketch JSON text) for an item of the picker, or None."""
        if sid in (SLICE_NEW, SLICE_LAST):
            return self.slice_json(sid == SLICE_LAST)
        d = self.part_doc()
        f = d.feature(sid) if d is not None else None
        if f is None or f["kind"] != "sketch":
            self.status_lbl.setText("That sketch is no longer in the part.")
            return None
        text = f["model"] if isinstance(f["model"], str) else json.dumps(f["model"])
        self.pending = None
        return f["name"], text

    def slice_json(self, again):
        planes = self.planes()
        bodies = self.bodies()
        if not planes or not bodies:
            QMessageBox.information(self, "Slice", "There is no solid to slice yet (is the source open and does it have a solid?).")
            return None
        spec = self.meta.get("slice") if again else None
        if spec is None:
            vis = self.visible_planes()
            dlg = sim_slice.SliceDialog(self, vis, bodies, self.meta.get("slice"), multi=self.src["type"] == "asm")
            if not dlg.exec() or dlg.out is None:
                return None
            spec = dlg.out
        if spec.get("face"):
            pl = {k: np.array(v, float) for k, v in spec["face"].items()}
        else:
            pl = dict(planes).get(spec["plane"])
        if pl is None:
            QMessageBox.information(self, "Slice", f"The plane '{spec['plane']}' no longer exists.")
            return None
        use = [(i, b) for i, b in enumerate(bodies) if b[0] not in spec.get("excluded", [])]
        sp = slice3d.shifted(pl, spec.get("offset", 0.0), spec.get("flip", False))
        loops = slice3d.slice_bodies([(i, b[1]) for i, b in use], sp)
        if not loops:
            QMessageBox.information(self, "Slice", "The plane does not cut any part. Move it (offset) or choose another plane.")
            return None
        m = sc.Model()
        scale = 1.0e-3 / units.get(m.unit_system)["L_m"]
        bld = ss._Builder(m, loops, scale)
        bld.make_geometry()
        self.pending = {"loops": loops, "bodies": [(b[0], b[2]) for i, b in enumerate(bodies)], "scale": scale, "notes": list(bld.notes)}
        self.meta["slice"] = dict(spec)
        return "Slice " + self.slice_text(spec), m.to_json()

    # ------------------------------------------------------------------ after an import
    def on_imported(self, sid, text, name):
        t = self.tab
        t.import_picked(sid, text, name)
        sid = SLICE_LAST if sid == SLICE_NEW else sid           # Refresh repeats the slice without asking again
        self.meta["sid"] = sid
        notes = []
        mats = None
        if sid == SLICE_LAST and self.pending is not None:
            mats = self.apply_regions()
            notes += self.pending.get("notes", [])
        if self.kind in ("fea", "beam"):
            first = None
            if mats:
                first = next((m for m in mats.values() if mat_lib.elastic(m)), None)
            elif self.src["type"] == "part" and self.part_doc() is not None:
                first = self.part_doc().material
            if first is not None:
                if fill_material(t, self.kind, first):
                    notes.append(f"Material from the part: {mat_lib.summary(mat_lib.with_elastic(first))}.")
                else:
                    notes.append("The part's material has no elastic properties: type E and Poisson's ratio (or choose another material in the part).")
        self.tab.picker.refresh()
        self.tab.picker.select(sid)
        self.refresh_study_button()
        if notes:
            self.status_lbl.setText("  ".join(notes))

    def apply_regions(self):
        """Names the regions of a slice by the part they come from, switches off the ones that belong to no part (holes), and (2D FEA) gives each
        its material.  -> {region id: material dict} or None."""
        t, p = self.tab, self.pending
        if getattr(t, "geom", None) is None:
            return None
        rp = slice3d.region_parts(t.geom, p["loops"])
        names = {f: p["bodies"][i][0] for f, i in rp.items() if i is not None}
        mats = {f: mat_lib.with_elastic(p["bodies"][i][1]) for f, i in rp.items() if i is not None}
        if self.kind == "cfd":
            return mats
        if self.kind == "fea":
            for f in t.geom["faces"]:
                if rp.get(f["id"]) is None:
                    f["included"] = False              # inside a hole of a part: no material there
            t.region_names = names
            t.region_mats = {f: {"E_MPa": e[0], "nu": e[1], "Sy_MPa": e[2], "Su_MPa": e[3]} for f, m in mats.items()
                             for e in [mat_lib.elastic(m)] if e is not None}
            missing = [names[f] for f, m in mats.items() if mat_lib.elastic(m) is None]
            t.fill_regions()
            t.refresh_lists()
            t.canvas.invalidate()
            if missing:
                self.status_lbl.setText("No elastic properties for: " + ", ".join(sorted(set(missing))) + ". These regions use the material boxes of the tab.")
        return mats

    def original_text(self):
        """(path, live text or None) of the original the project was imported from: an open tab of it (unsaved edits count), else the file."""
        p = self.src.get("path")
        if not p:
            return None, None
        if self.shell is not None:
            i = self.shell.find_tab(p)
            if i is not None:
                w = self.shell.tabs.widget(i)
                if hasattr(w, "asm"):
                    return p, w.asm.to_json()
                if getattr(w, "doc", None) is not None:
                    return p, w.doc.to_json()
        return p, None

    def refresh(self):
        """Update from original: copy it into the project again, then take the same sketch or slice again."""
        if self.source is None:
            self.say("Nothing imported yet: press Import source...")
            return
        sid = self.meta.get("sid")
        p, text = self.original_text()
        if text is None and (not p or not os.path.isfile(p)):
            ok = QMessageBox.question(self, "Update from original", "The original file cannot be found any more (it was moved or deleted). The copy in the "
                                      "project is kept and still works.\n\nChoose another file to copy instead?") == QMessageBox.StandardButton.Yes
            if ok:
                self.import_source()
            return
        if self.tab.result is not None or self.tab.mesh is not None:
            if QMessageBox.question(self, "Update from original", "Copying the original again clears the supports, loads, mesh and result of this "
                                    "tab. Continue?") != QMessageBox.StandardButton.Yes:
                return
        try:
            m, missing = sim_project.import_source(self.path, orig_path=p, text=text, name=self.src.get("name"))
            self.source = sim_source.open_source(sim_project.source_file(self.path, m))
        except (sim_project.ProjectError, sim_source.SourceError) as ex:
            QMessageBox.warning(self, "Update from original", str(ex))
            return
        self.meta = {"sid": sid, "slice": self.meta.get("slice")}
        self.tab.picker.refresh()
        if sid is None:
            self.say("Copied the original again. Choose a sketch or a slice and press Import.")
            return
        self.tab.picker.select(sid)
        self.tab.picker.go()
        self.save()


# ---------------------------------------------------------------------------------------------------------------- the document tabs of the manifest
def _make(kind, host, path):
    if path:
        return SimWindow.open_project(host, path)
    return SimWindow(kind, shell=host)


def make_beam(host, path=None):
    return _make("beam", host, path)


def make_fea(host, path=None):
    return _make("fea", host, path)


def make_cfd(host, path=None):
    return _make("cfd", host, path)
