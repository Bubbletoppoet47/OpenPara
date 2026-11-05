"""
solid_tab.py - the 3D FEA window (project folder .gpv): a SINGLE parametric part, linear elastic, quadratic tetrahedra.

Project bar:  New project / Import source / Update from original / Save   (the same project folder machinery as the 1D / 2D simulations:
              the part is COPIED into  source/  and the simulation only uses the copy)
Left panel:   Geometry (part dimensions you can edit), Material, Supports, Loads, Mesh, Solve, [parametric study], Results
Right:        the part in 3D; click a face to pick it (the Faces list does the same without the mouse)

The window is also the 'tab' the parametric studies talk to (study_adapter), so it offers export_state / import_state / unit_name.
"""
import json
import os
import threading
import traceback

import numpy as np
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea, QSplitter,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import ext
import physics_materials as pm
import sim_project
import sim_report as R
import sim_ui
import sim_source
import solid_fem as fem
import solid_geom as sg
import solid_model as sm
import solid_view as sv
import unitctl
import units

FIELDS = ["Von Mises stress", "Displacement", "Safety factor (yield)"]


# --- the program's global units (File > Units).  The solver works in mm / N / MPa / kg per m3; these convert only what is shown or typed.
def UD():
    return units.get(unitctl.system())


def l_out(mm):
    return mm * 1e-3 / UD()["L_m"]


def l_in(x):
    return x * UD()["L_m"] * 1e3


def s_out(mpa):
    return mpa * 1e6 / UD()["S_Pa"]


def s_in(x):
    return x * UD()["S_Pa"] / 1e6


def f_out(n):
    return n / UD()["F_N"]


def f_in(x):
    return x * UD()["F_N"]


def r_out(kgm3):
    return kgm3 / UD()["rho_si"]


def r_in(x):
    return x * UD()["rho_si"]


class Job(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str, bool)
    note = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.stop = False

    def run(self):
        try:
            self.done.emit(self.fn(lambda t: self.note.emit(str(t)), lambda: self.stop))
        except fem.Cancelled:
            self.failed.emit("Cancelled.", True)
        except fem.FemError as ex:
            self.failed.emit(str(ex), False)
        except Exception:
            self.failed.emit(traceback.format_exc(), False)


def num(edit, label):
    try:
        return float(edit.text().replace(",", "."))
    except ValueError:
        raise ValueError(f"{label}: '{edit.text()}' is not a number.")


class SolidWindow(QWidget):
    kind = "solid"
    label = "3D FEA"
    plotter = None
    nav = None
    study_geometry = True                       # a study can change the part's dimensions

    def __init__(self, shell=None, path=None, threaded=True):
        super().__init__()
        self.shell = shell
        self.path = path
        self.threaded = threaded
        self.tab = self                         # what a parametric study calls the simulation tab
        self.host = self
        self._restoring = False
        self.meta = {"sid": "__solid__", "slice": None}
        self.src = {"type": "part", "path": None, "name": ""}
        self.source = None
        self.geom = None
        self.setup = sm.default_setup()
        self.setup["dims"] = {}
        self.mesh_q = None
        self.result = None
        self.cache = {}
        self.sel_faces = []
        self.sel_vertex = None
        self.job = None
        self.saved_sig = None
        self.candidate = None
        self.pending_dims = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.src_lbl = QLabel()
        self.src_lbl.setWordWrap(True)
        bar.addWidget(self.src_lbl, 1)
        self.b_new = QPushButton("New project...")
        self.b_new.clicked.connect(self.new_project)
        self.b_import = QPushButton("Import source...")
        self.b_import.setToolTip("Copies a part into the project folder (an open part tab, or a .gpd file). The simulation works on the copy.")
        self.b_import.clicked.connect(self.import_source)
        self.b_refresh = QPushButton("Update from original")
        self.b_refresh.clicked.connect(self.refresh)
        self.b_save = QPushButton("Save")
        self.b_save.clicked.connect(lambda: self.save())
        for b in (self.b_new, self.b_import, self.b_refresh, self.b_save):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#707070;")
        self.status_lbl.setWordWrap(True)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        col = QWidget()
        self.col = QVBoxLayout(col)
        self.col.setContentsMargins(6, 6, 6, 6)
        self.col.setSpacing(4)
        self.sections = []
        self.last_probe = None
        self.panel = sim_ui.make_panel(col, [])
        split.addWidget(self.panel)
        split.setStretchFactor(0, 0)
        self.view = sv.SolidView(self)
        self.view.on_pick = self.picked
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        if self.view.widget is not None:
            rl.addWidget(self.view.widget, 1)
        else:
            rl.addWidget(QLabel("The 3D view is not available here; use the Faces list."), 1)
        rl.addWidget(self.status_lbl)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        self.build_panel()
        self.show_source()
        unitctl.on_change(self.units_changed)

    # ------------------------------------------------------------------ the panel
    def sec(self, n, title, open_=True, summary=None, help_text=None):
        s_ = sim_ui.Section("solid", n, title, open_, help_text, summary)
        self.sections.append(s_)
        return s_.body

    def build_panel(self):
        # --- 1 geometry
        v = self.sec(1, "Geometry", True, summary=lambda: self.geo_lbl.text().split("\n")[0][:90])
        self.geo_lbl = QLabel("No part yet: press Import source...")
        self.geo_lbl.setWordWrap(True)
        v.addWidget(self.geo_lbl)
        self.dims = QTableWidget(0, 2)
        self.dims.setHorizontalHeaderLabels(["Part dimension", "Value (as stored)"])
        self.dims.horizontalHeader().setStretchLastSection(True)
        self.dims.setMaximumHeight(130)
        self.dims.itemChanged.connect(self.dim_edited)
        v.addWidget(self.dims)
        self.faces_lbl = QLabel("Faces (click one in the view, or select here; Ctrl/Shift for several):")
        self.faces_lbl.setWordWrap(True)
        v.addWidget(self.faces_lbl)
        self.faces = QListWidget()
        self.faces.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.faces.setMaximumHeight(130)
        self.faces.itemSelectionChanged.connect(self.faces_selected)
        v.addWidget(self.faces)
        # --- 2 material and analysis
        v = self.sec(2, "Material and analysis", True, summary=lambda: self.mat_combo.currentText().strip() or "custom material")
        self.mat_combo = QComboBox()
        self.mat_combo.activated.connect(self.material_picked)
        v.addWidget(self.mat_combo)
        self.mat_note = QLabel("")
        self.mat_note.setWordWrap(True)
        self.mat_note.setStyleSheet("color:#707070;")
        v.addWidget(self.mat_note)
        f = QFormLayout()
        self.e_E, self.e_nu, self.e_rho, self.e_sy, self.e_su = (QLineEdit() for _ in range(5))
        self.mat_labels = {}
        for e, key in ((self.e_E, "E"), (self.e_nu, "nu"), (self.e_rho, "rho"), (self.e_sy, "sy"), (self.e_su, "su")):
            lab = QLabel()
            self.mat_labels[key] = lab
            f.addRow(lab, e)
            e.editingFinished.connect(self.inputs_changed)
        v.addLayout(f)
        v.addWidget(QLabel("Analysis: linear elastic, small displacements, quadratic tetrahedra."))
        self.fill_materials()
        self.put_material(self.setup["material"])
        # --- 3 supports
        v = self.sec(3, "Supports", True, summary=lambda: f"{len(self.setup['supports'])} support(s)")
        v.addWidget(QLabel("Select the face(s) first, then add."))
        row = QHBoxLayout()
        self.cb_mode = QComboBox()
        for k, lab in sm.MODES.items():
            self.cb_mode.addItem(lab, k)
        row.addWidget(self.cb_mode, 1)
        b = QPushButton("Add support")
        b.clicked.connect(lambda: self.add_support())
        row.addWidget(b)
        v.addLayout(row)
        self.sup_list = QListWidget()
        self.sup_list.setMaximumHeight(90)
        v.addWidget(self.sup_list)
        b = QPushButton("Remove selected support")
        b.clicked.connect(lambda: self.remove_item("supports", self.sup_list))
        v.addWidget(b)
        # --- 4 loads
        v = self.sec(4, "Loads", True, summary=lambda: f"{len(self.setup['loads'])} load(s)")
        row = QHBoxLayout()
        for text, kind in (("Force on face(s)", "force"), ("Pressure on face(s)", "pressure"), ("Force at vertex", "point"), ("Gravity", "gravity")):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, k=kind: self.add_load(k))
            row.addWidget(b)
        v.addLayout(row)
        self.load_list = QListWidget()
        self.load_list.setMaximumHeight(100)
        self.load_list.itemDoubleClicked.connect(lambda it: self.edit_load(self.load_list.row(it)))
        v.addWidget(self.load_list)
        row = QHBoxLayout()
        b = QPushButton("Edit selected")
        b.clicked.connect(lambda: self.edit_load(self.load_list.currentRow()))
        row.addWidget(b)
        b = QPushButton("Remove selected load")
        b.clicked.connect(lambda: self.remove_item("loads", self.load_list))
        row.addWidget(b)
        v.addLayout(row)
        # --- 5 mesh
        v = self.sec(5, "Mesh", True, summary=lambda: self.mesh_lbl.text() or "not meshed")
        f = QFormLayout()
        self.e_h = QLineEdit()
        self.e_h.setPlaceholderText("auto")
        self.e_h.editingFinished.connect(self.inputs_changed)
        self.h_label = QLabel()
        f.addRow(self.h_label, self.e_h)
        v.addLayout(f)
        self.b_mesh = QPushButton("Mesh")
        self.b_mesh.clicked.connect(self.run_mesh)
        v.addWidget(self.b_mesh)
        self.mesh_lbl = QLabel("")
        self.mesh_lbl.setWordWrap(True)
        v.addWidget(self.mesh_lbl)
        # --- 6 probe
        v = self.sec(6, "Probe", True, summary=lambda: "click a point on the result")
        self.b_probe = QPushButton("Probe by clicking the surface")
        self.b_probe.setCheckable(True)
        self.b_probe.setToolTip("Switch this on, then click the solved part: the values of the node nearest to the click appear below. "
                                "The view still turns with the mouse; only a click without moving is a probe.")
        self.b_probe.toggled.connect(self.set_probe_mode)
        v.addWidget(self.b_probe)
        row = QHBoxLayout()
        self.e_probe = QLineEdit()
        row.addWidget(self.e_probe, 1)
        b = QPushButton("Probe nearest node")
        b.clicked.connect(self.probe_node)
        row.addWidget(b)
        v.addLayout(row)
        self.probe_lbl = QLabel("")
        self.probe_lbl.setWordWrap(True)
        self.probe_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.probe_lbl)
        # --- 7 results
        v = self.sec(7, "Results", True)
        self.res_lbl = QLabel("No result yet.")
        self.res_lbl.setWordWrap(True)
        self.res_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.res_lbl)
        f = QFormLayout()
        self.cb_field = QComboBox()
        self.cb_field.addItems(FIELDS)
        self.cb_field.currentIndexChanged.connect(lambda _i: self.show_field())
        f.addRow("Show", self.cb_field)
        self.e_scale = QLineEdit("0")
        self.e_scale.setToolTip("Displacement magnification; 0 = true shape, 'auto' = about a tenth of the part")
        self.e_scale.editingFinished.connect(self.show_field)
        f.addRow("Deformation scale", self.e_scale)
        v.addLayout(f)
        self.cb_edges = QCheckBox("Show mesh edges")
        self.cb_edges.toggled.connect(lambda _on: self.show_field())
        v.addWidget(self.cb_edges)
        self.b_anim = QPushButton("Export animation...")
        self.b_anim.clicked.connect(lambda: self.export_animation())
        v.addWidget(self.b_anim)
        # --- the Solve button (wide), the study slot, then the Results
        row = QHBoxLayout()
        self.b_solve = sim_ui.solve_button()
        self.b_solve.clicked.connect(self.run_solve)
        row.addWidget(self.b_solve, 1)
        self.b_cancel = QPushButton("Cancel")
        self.b_cancel.setMinimumHeight(44)
        self.b_cancel.setEnabled(False)
        self.b_cancel.clicked.connect(self.cancel)
        row.addWidget(self.b_cancel)
        self.study_box = QWidget()
        sl = QVBoxLayout(self.study_box)
        sl.setContentsMargins(4, 0, 4, 4)
        self.b_study = QPushButton("Create parametric study")
        self.b_study.setMinimumHeight(30)
        self.b_study.clicked.connect(self.open_study)
        sl.addWidget(self.b_study)
        for s_ in sorted(self.sections, key=lambda x: x.number):
            if s_.number == 7:
                self.col.addLayout(row)
                self.col.addWidget(self.study_box)
            self.col.addWidget(s_)
        self.study_box.setVisible(False)
        self.col.addStretch(1)
        self.refresh_labels()
        self.enable_buttons()

    def refresh_labels(self):
        """Every label that carries a unit, in the program's current units."""
        D = UD()
        for key, text in (("E", f"Young's modulus E ({D['S']})"), ("nu", "Poisson's ratio"), ("rho", f"Density ({D['rho']})"),
                          ("sy", f"Yield strength ({D['S']})"), ("su", f"Ultimate strength ({D['S']})")):
            self.mat_labels[key].setText(text)
        self.h_label.setText(f"Element size ({D['L']}, blank = auto)")
        self.e_probe.setPlaceholderText(f"x, y, z  ({D['L']})")
        for i, base in enumerate(("Von Mises stress", "Displacement")):
            self.cb_field.setItemText(i, f"{base} ({D['S'] if i == 0 else D['L']})")
        self.update_mat_note()

    def units_changed(self, *_a):
        try:
            self.refresh_labels()
            self.put_material(self.setup["material"])
            self.e_h.setText(format(l_out(self.setup["h"]), ".8g") if self.setup.get("h") else "")
            if self.geom is not None:
                self.fill_faces()
                self.set_geo_text()
            self.refresh_lists()
            if self.result is not None:
                self.describe()
                self.show_field()
            if self.last_probe is not None:
                self.show_probe(self.last_probe)
            for s_ in self.sections:
                s_.refresh_summary()
        except RuntimeError:
            unitctl.off_change(self.units_changed)               # the window is gone

    def say(self, text):
        self.status_lbl.setText(text)

    def status(self, text):
        self.say(text)

    # ------------------------------------------------------------------ material and inputs
    def fill_materials(self, select=None):
        self.library = pm.load()
        builtin = {n for n, _, _ in pm.DEFAULTS}
        self.mat_combo.blockSignals(True)
        self.mat_combo.clear()
        self.mat_combo.addItem("(custom values)", None)
        for m_ in self.library:
            self.mat_combo.addItem(m_["name"] + ("" if m_["name"] in builtin else "   (mine)"), m_["name"])
        self.mat_combo.setCurrentIndex(0)
        self.mat_combo.blockSignals(False)
        self.select_material_name(select)

    def select_material_name(self, name):
        i = 0
        for k in range(self.mat_combo.count()):
            if name is not None and self.mat_combo.itemData(k) == name:
                i = k
        self.mat_combo.blockSignals(True)
        self.mat_combo.setCurrentIndex(i)
        self.mat_combo.blockSignals(False)
        self.update_mat_note()

    def library_entry(self, name):
        return next((x for x in self.library if x["name"] == name), None)

    def update_mat_note(self):
        name = self.mat_combo.currentData()
        txt = "Custom values." if name is None else "Typical value - check your source."
        m_ = self.library_entry(name) if name is not None else None
        if m_ is not None and (m_.get("Sy_MPa") is None or m_.get("Su_MPa") is None):
            txt += "  No strengths are stored for this material: type the yield and ultimate strength below."
        self.mat_note.setText(txt + "  The unit system is chosen in File > Units.")

    def material_picked(self, *_a):
        name = self.mat_combo.currentData()
        m_ = self.library_entry(name) if name is not None else None
        if m_ is not None:
            cur = self.setup["material"]
            self.put_material({"E": m_["E_MPa"], "nu": m_["nu"], "rho": m_.get("density") or cur.get("rho") or 7850.0,
                               "sy": m_["Sy_MPa"] if m_.get("Sy_MPa") is not None else cur.get("sy", 0.0),
                               "su": m_["Su_MPa"] if m_.get("Su_MPa") is not None else cur.get("su", 0.0)})
            self.setup["mat_name"] = name
        else:
            self.setup.pop("mat_name", None)
        self.update_mat_note()
        self.inputs_changed()

    def put_material(self, m):
        """m in the solver's units (MPa, kg per m3); the fields show the program's units."""
        for e, k, fn in ((self.e_E, "E", s_out), (self.e_nu, "nu", float), (self.e_rho, "rho", r_out), (self.e_sy, "sy", s_out),
                         (self.e_su, "su", s_out)):
            e.setText(format(fn(float(m.get(k) or 0.0)), ".8g"))

    def read_inputs(self):
        m = {"E": s_in(num(self.e_E, "E")), "nu": num(self.e_nu, "Poisson's ratio"), "rho": r_in(num(self.e_rho, "Density")),
             "sy": s_in(num(self.e_sy, "Yield strength")), "su": s_in(num(self.e_su, "Ultimate strength"))}
        h = self.e_h.text().strip()
        self.setup["material"] = m
        self.setup["h"] = l_in(num(self.e_h, "Element size")) if h else 0.0
        return self.setup

    def inputs_changed(self):
        try:
            self.read_inputs()
        except ValueError as ex:
            self.say(str(ex))
            return
        self.invalidate(mesh=True)

    def invalidate(self, mesh=False):
        self.result = None
        if mesh:
            self.mesh_q = None
        self.res_lbl.setText("No result yet.")
        self.view.clear_result()
        self.enable_buttons()

    def enable_buttons(self):
        have = self.geom is not None
        busy = self.job is not None
        self.b_import.setEnabled(self.project_ok() and not busy)
        self.b_refresh.setEnabled(self.source is not None and not busy)
        self.b_save.setEnabled(have)
        self.b_mesh.setEnabled(have and not busy)
        self.b_solve.setEnabled(have and not busy)
        self.b_cancel.setEnabled(busy)
        self.b_anim.setEnabled(self.result is not None)
        self.b_study.setEnabled(have and not busy)

    # ------------------------------------------------------------------ the project
    def title(self):
        return os.path.basename(self.path.rstrip("/\\")) if self.path else "3D FEA"

    def project_ok(self):
        return bool(self.path) and sim_project.kind_of_folder(self.path) == "solid"

    def show_source(self):
        if not self.project_ok():
            self.src_lbl.setText("<b>3D FEA</b> - press <b>New project...</b>: the project is a folder (.gpv) with its own copy of the part.")
            return
        if self.source is None:
            self.src_lbl.setText(f"<b>3D FEA</b> project <b>{self.title()}</b> - press <b>Import source...</b> to copy a part into it.")
            return
        self.src_lbl.setText(f"<b>3D FEA</b> of the part <b>{self.src.get('name') or '?'}</b> (the copy in the project)")

    def new_project(self):
        start = sim_project.default_name("solid", self.src.get("name") or "3D FEA", os.path.dirname(self.src.get("path") or "") or os.getcwd())
        path, _ = QFileDialog.getSaveFileName(self, "New 3D FEA project (a folder)", start, "3D FEA project (*.gpv)")
        return self.create_project(path) if path else False

    def create_project(self, path):
        if not path.lower().endswith(sim_project.ext_of("solid")):
            path += sim_project.ext_of("solid")
        try:
            sim_project.create(path, "solid")
        except sim_project.ProjectError as ex:
            QMessageBox.warning(self, "New project", str(ex))
            return False
        self.path = os.path.abspath(path)
        self.show_source()
        self.say(f"Project folder {self.path} made.")
        c = self.candidate
        if c is not None:
            try:
                c.title()
                return self.import_tab(c)
            except RuntimeError:
                pass
        self.enable_buttons()
        return True

    def open_tabs(self):
        out = []
        if self.shell is None:
            return out
        for i in range(self.shell.tabs.count()):
            w = self.shell.tabs.widget(i)
            if not hasattr(w, "asm") and getattr(w, "doc", None) is not None and hasattr(w.doc, "features"):
                out.append(("part - " + w.title(), w))
        return out

    def import_source(self):
        if not self.project_ok() and not self.new_project():
            return False
        if self.source is not None and self.candidate is not None:
            pass
        from PyQt6.QtWidgets import QDialog as _D
        dlg = QDialog(self)
        dlg.setWindowTitle("Import source")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Copy this part into the project (3D FEA works on a single part, not an assembly):"))
        lst = QListWidget()
        tabs = self.open_tabs()
        for text, _w in tabs:
            lst.addItem(text)
        if tabs:
            lst.setCurrentRow(0)
        lay.addWidget(lst)
        pick = {"file": None}
        b_file = QPushButton("Browse for a .gpd file...")
        lay.addWidget(b_file)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        lay.addWidget(bb)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)

        def browse():
            f, _ = QFileDialog.getOpenFileName(dlg, "Part to copy", os.path.dirname(self.src.get("path") or ""), "Part (*.gpd)")
            if f:
                pick["file"] = f
                dlg.accept()
        b_file.clicked.connect(browse)
        if not dlg.exec():
            return False
        if pick["file"]:
            return self.import_file(pick["file"])
        row = lst.currentRow()
        return self.import_tab(tabs[row][1]) if row >= 0 else False

    def import_tab(self, w):
        p = getattr(w, "path", None)
        return self.do_import(p, w.doc.to_json(), name=(os.path.splitext(os.path.basename(p))[0] if p else w.title()))

    def import_file(self, path):
        return self.do_import(path, None)

    def do_import(self, orig, text, name=None):
        if not self.project_ok():
            return False
        if self.geom is not None and (self.setup["supports"] or self.setup["loads"]):
            if QMessageBox.question(self, "Import source", "Importing a source replaces the copy in the project. Supports and loads are kept when "
                                    "their faces are found in the new part; the mesh and result are cleared. Continue?") != QMessageBox.StandardButton.Yes:
                return False
        if orig and orig.lower().endswith(".gpa"):
            QMessageBox.information(self, "Import source", "3D FEA works on a single part, not on an assembly.")
            return False
        try:
            fake = orig if orig else os.path.join(self.path, (name or "source") + ".gpd")
            m, _missing = sim_project.import_source(self.path, orig_path=fake, text=text, name=name)
            src = sim_source.open_source(sim_project.source_file(self.path, m))
        except (sim_project.ProjectError, sim_source.SourceError) as ex:
            QMessageBox.warning(self, "Import source", str(ex))
            return False
        if src.type != "part":
            QMessageBox.information(self, "Import source", "3D FEA works on a single part, not on an assembly.")
            return False
        self.source = src
        self.src = {"type": "part", "path": orig, "name": m["source"]["name"]}
        self.setup["dims"] = {}
        ok = self.load_geometry(first=True)
        self.show_source()
        if ok:
            self.say(f"Copied {m['source']['name']} into the project ({m['source']['file']}).")
            self.save()
        return ok

    def original_text(self):
        p = self.src.get("path")
        if not p:
            return None, None
        if self.shell is not None:
            i = self.shell.find_tab(p)
            if i is not None:
                w = self.shell.tabs.widget(i)
                if getattr(w, "doc", None) is not None:
                    return p, w.doc.to_json()
        return p, None

    def refresh(self):
        if self.source is None:
            self.say("Nothing imported yet.")
            return False
        p, text = self.original_text()
        if text is None and (not p or not os.path.isfile(p)):
            self.say("The original file cannot be found any more; the copy in the project is kept and still works.")
            return False
        try:
            m, _ = sim_project.import_source(self.path, orig_path=p, text=text, name=self.src.get("name"))
            self.source = sim_source.open_source(sim_project.source_file(self.path, m))
        except (sim_project.ProjectError, sim_source.SourceError) as ex:
            QMessageBox.warning(self, "Update from original", str(ex))
            return False
        ok = self.load_geometry()
        self.say("Copied the original again." + ("" if ok else " (The part has no solid.)"))
        self.save()
        return ok

    # ------------------------------------------------------------------ geometry
    def apply_dims(self):
        if self.source is None:
            return
        fresh = sim_source.open_source(self.source.path)
        if self.setup["dims"]:
            fresh.set_values(self.setup["dims"])
        self.source = fresh

    def load_geometry(self, first=False):
        """(Re)analyses the solid of the source (with the dimension edits) and rematches the faces of the supports and loads."""
        try:
            if not first:
                self.apply_dims()
            elif self.setup["dims"]:
                self.source.set_values(self.setup["dims"])
            g = sg.analyze(self.source.doc.solid)
        except sg.GeomError as ex:
            self.say(str(ex))
            return False
        except Exception as ex:
            self.say(f"The part could not be read: {ex}")
            return False
        self.geom = g
        self.sel_faces, self.sel_vertex = [], None
        self.mesh_q = None
        self.result = None
        mat = self.source.doc.material
        if first and mat:
            e = mat.get("E_MPa")
            if e:
                self.put_material({"E": e, "nu": mat.get("nu") or 0.3, "rho": mat.get("density") or 7850.0, "sy": mat.get("Sy_MPa") or 0.0,
                                   "su": mat.get("Su_MPa") or 0.0})
                nm = mat.get("name")
                self.select_material_name(nm if nm and self.library_entry(nm) else None)
                self.read_inputs()
                if self.mat_combo.currentData() is not None:
                    self.setup["mat_name"] = self.mat_combo.currentData()
        self.fill_faces()
        self.fill_dims()
        P, T, F = sg.display_mesh(g)
        self.view.set_geometry(P, T, F)
        self.set_geo_text()
        self.refresh_lists()
        self.colour()
        self.enable_buttons()
        self.refresh_study_button()
        return True

    def set_geo_text(self):
        g = self.geom
        if g is None:
            return
        bb = g["bbox"]
        L = UD()["L"]
        k = l_out(1.0)
        self.geo_lbl.setText(f"{self.src.get('name') or 'part'}: {len(g['faces'])} faces, volume {g['volume'] * k ** 3:.5g} {L}3, size "
                             f"{(bb[1][0] - bb[0][0]) * k:.4g} x {(bb[1][1] - bb[0][1]) * k:.4g} x {(bb[1][2] - bb[0][2]) * k:.4g} {L}")

    def fill_faces(self):
        self.faces.blockSignals(True)
        self.faces.clear()
        for f in self.geom["faces"]:
            n = f["normal"]
            self.faces.addItem(f"Face {f['id'] + 1}: {f['kind']}, area {f['area'] * l_out(1.0) ** 2:.4g} {UD()['L']}2, "
                               f"normal ({n[0]:.2f}, {n[1]:.2f}, {n[2]:.2f})")
        self.faces.blockSignals(False)

    def fill_dims(self):
        self.dims.blockSignals(True)
        self.dims.setRowCount(0)
        self.dim_keys = []
        for key, label, now in self.source.doc.cfg_candidates():
            if key.startswith("s:"):
                continue
            r = self.dims.rowCount()
            self.dims.insertRow(r)
            it = QTableWidgetItem(label)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.dims.setItem(r, 0, it)
            self.dims.setItem(r, 1, QTableWidgetItem(str(now)))
            self.dim_keys.append(key)
        self.dims.blockSignals(False)

    def dim_edited(self, item):
        if item.column() != 1 or item.row() >= len(self.dim_keys):
            return
        key = self.dim_keys[item.row()]
        self.setup["dims"][key] = item.text().strip()
        self.set_dim(key, item.text().strip())

    def set_dim(self, key, text):
        """Changes one dimension of the part copy (kept in the project's setup), rebuilds, rematches the faces."""
        self.setup["dims"][key] = text
        old = self.setup_json()
        if not self.load_geometry():
            return False
        self.setup = json.loads(old)
        return True

    # ------------------------------------------------------------------ picking and the lists
    def faces_selected(self):
        self.sel_faces = sorted(self.faces.row(i) for i in self.faces.selectedItems())
        self.colour()

    def picked(self, fid, point):
        mods = QApplication_keyboard()
        if mods and fid in self.sel_faces:
            self.sel_faces.remove(fid)
        elif mods:
            self.sel_faces.append(fid)
        else:
            self.sel_faces = [fid]
        if self.geom is not None and self.geom["verts"]:
            d = np.linalg.norm(np.asarray(self.geom["verts"]) - np.asarray(point), axis=1)
            self.sel_vertex = int(np.argmin(d))
        self.faces.blockSignals(True)
        self.faces.clearSelection()
        for f in self.sel_faces:
            self.faces.item(f).setSelected(True)
        self.faces.blockSignals(False)
        self.colour()
        self.say(f"Picked face {fid + 1}" + (f" (nearest vertex {self.sel_vertex + 1})" if self.sel_vertex is not None else ""))

    def select_faces(self, fids):
        """Selects faces without the mouse (also used by the tests)."""
        self.sel_faces = sorted(set(fids))
        self.faces.blockSignals(True)
        self.faces.clearSelection()
        for f in self.sel_faces:
            self.faces.item(f).setSelected(True)
        self.faces.blockSignals(False)
        self.colour()

    def colour(self):
        if self.geom is None:
            return
        cols = {}
        try:
            r = sm.resolve(self.geom, self.setup)
        except fem.FemError:
            r = {"supports": [], "loads": []}
        for s in r["supports"]:
            for f in s["fids"]:
                cols[f] = sv.SUPPORT
        for l in r["loads"]:
            for f in l.get("fids", []):
                cols[f] = sv.LOAD
        for f in self.sel_faces:
            cols[f] = sv.PICK
        self.view.colour_faces(cols)

    def refresh_lists(self):
        self.sup_list.clear()
        for i, s in enumerate(self.setup["supports"]):
            self.sup_list.addItem(f"{sm.name_of('Support', i, s)}: {s['mode']} on {len(s['faces'])} face(s)")
        self.load_list.clear()
        for i, l in enumerate(self.setup["loads"]):
            self.load_list.addItem(f"{sm.name_of('Load', i, l)}: {self.load_text(l)}")

    @staticmethod
    def load_text(l):
        D = UD()
        k = l["kind"]
        if k == "force":
            return f"force ({', '.join(format(f_out(x), '.5g') for x in l['f'])}) {D['F']} on {len(l['faces'])} face(s)"
        if k == "pressure":
            return f"pressure {s_out(l['p']):.5g} {D['S']} on {len(l['faces'])} face(s)"
        if k == "point":
            return (f"point force ({', '.join(format(f_out(x), '.5g') for x in l['f'])}) {D['F']} at "
                    f"({', '.join(format(l_out(x), '.4g') for x in l['vertex']['point'])}) {D['L']}")
        return f"gravity {l['g']:g} m/s2 along {tuple(l['dir'])}"

    def remove_item(self, key, lst):
        r = lst.currentRow()
        if 0 <= r < len(self.setup[key]):
            del self.setup[key][r]
            self.refresh_lists()
            self.invalidate()
            self.colour()

    def add_support(self, mode=None, fids=None):
        fids = self.sel_faces if fids is None else fids
        if self.geom is None or not fids:
            self.say("Select the face(s) of the support first.")
            return False
        mode = mode or self.cb_mode.currentData()
        n = sum(1 for s in self.setup["supports"] if s["mode"] == mode) + 1
        self.setup["supports"].append({"mode": mode, "faces": [sg.face_sig(self.geom, f) for f in fids], "name": f"{mode.capitalize()} support {n}"})
        self.after_edit()
        return True

    def add_load(self, kind, values=None, fids=None, vertex=None):
        """Adds a load.  Without `values` a small dialog asks for them."""
        if self.geom is None:
            return False
        fids = self.sel_faces if fids is None else fids
        if kind in ("force", "pressure") and not fids:
            self.say("Select the face(s) the load acts on first.")
            return False
        item = {"kind": kind}
        if values is None:
            values = self.ask_load(kind, None)
            if values is None:
                return False
        item.update(values)
        n = sum(1 for l in self.setup["loads"] if l["kind"] == kind) + 1
        item["name"] = f"{sm.KINDS[kind]} {n}"
        if kind in ("force", "pressure"):
            item["faces"] = [sg.face_sig(self.geom, f) for f in fids]
        elif kind == "point":
            vid = vertex if vertex is not None else (self.sel_vertex if self.sel_vertex is not None else item.pop("vertex_index", 0))
            item.pop("vertex_index", None)
            item["vertex"] = sg.vert_sig(self.geom, vid)
        self.setup["loads"].append(item)
        self.after_edit()
        return True

    def edit_load(self, r):
        if not (0 <= r < len(self.setup["loads"])):
            return False
        l = self.setup["loads"][r]
        vals = self.ask_load(l["kind"], l)
        if vals is None:
            return False
        vals.pop("vertex_index", None)
        l.update(vals)
        self.after_edit()
        return True

    def after_edit(self):
        self.refresh_lists()
        self.invalidate()
        self.colour()

    def ask_load(self, kind, cur):
        dlg = QDialog(self)
        dlg.setWindowTitle(sm.KINDS[kind])
        f = QFormLayout(dlg)
        ed = {}

        def add(key, lab, val):
            e = QLineEdit(format(float(val), ".10g"))
            f.addRow(lab, e)
            ed[key] = e
        vcombo = None
        if kind == "force" or kind == "point":
            fv = (cur or {}).get("f", [0.0, 0.0, 0.0])
            for i, a in enumerate("xyz"):
                add("f" + a, f"F{a} ({UD()['F']})", f_out(fv[i]))
        if kind == "point":
            vcombo = QComboBox()
            for i, p in enumerate(self.geom["verts"]):
                vcombo.addItem(f"Vertex {i + 1}: ({l_out(p[0]):.4g}, {l_out(p[1]):.4g}, {l_out(p[2]):.4g}) {UD()['L']}")
            vcombo.setCurrentIndex(self.sel_vertex if self.sel_vertex is not None else 0)
            f.addRow("Vertex", vcombo)
        if kind == "pressure":
            add("p", f"Pressure ({UD()['S']}, + pushes into the part)", s_out((cur or {}).get("p", 1.0)))
        if kind == "gravity":
            add("g", "g (m/s2)", (cur or {}).get("g", 9.81))
            d = (cur or {}).get("dir", [0.0, 0.0, -1.0])
            for i, a in enumerate("xyz"):
                add("d" + a, f"Direction {a}", d[i])
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if not dlg.exec():
            return None
        try:
            v = {k: float(e.text().replace(",", ".")) for k, e in ed.items()}
        except ValueError:
            QMessageBox.warning(self, "Load", "Type numbers.")
            return None
        if kind == "pressure":
            return {"p": s_in(v["p"])}
        if kind == "gravity":
            return {"g": v["g"], "dir": [v["dx"], v["dy"], v["dz"]]}
        out = {"f": [f_in(v["fx"]), f_in(v["fy"]), f_in(v["fz"])]}
        if vcombo is not None:
            out["vertex_index"] = vcombo.currentIndex()
            self.sel_vertex = vcombo.currentIndex()
        return out

    # ------------------------------------------------------------------ running
    def ready(self):
        if self.geom is None:
            return "Import a part first."
        try:
            self.read_inputs()
        except ValueError as ex:
            return str(ex)
        return sm.check_ready(self.setup)

    def run_job(self, fn, done, title):
        if self.job is not None:
            return False
        self.say(title + "...")
        if not self.threaded:
            try:
                done(fn(lambda t: None, lambda: False))
            except fem.FemError as ex:
                self.failed(str(ex), False)
            except Exception:
                self.failed(traceback.format_exc(), False)
            return True
        j = Job(fn)
        self.job = j
        j.note.connect(self.say)
        j.done.connect(lambda r: self.finished(j, done, r))
        j.failed.connect(lambda m, c: self.finished(j, None, None, m, c))
        self.enable_buttons()
        j.start()
        return True

    def finished(self, j, done, r, msg=None, cancelled=False):
        j.wait()
        self.job = None
        self.enable_buttons()
        if done is not None:
            done(r)
        else:
            self.failed(msg, cancelled)

    def failed(self, msg, cancelled=False):
        self.say(msg.strip().splitlines()[-1] if msg.strip() else "Failed.")
        self.last_error = msg
        self.enable_buttons()

    def cancel(self):
        if self.job is not None:
            self.job.stop = True
            self.say("Cancelling...")

    def run_mesh(self):
        why = None
        try:
            self.read_inputs()
        except ValueError as ex:
            why = str(ex)
        if self.geom is None or why:
            self.say(why or "Import a part first.")
            return False
        g, h = self.geom, self.setup["h"] or sm.auto_h(self.geom)

        def work(progress, cancel):
            return sm.get_mesh(g, h, self.cache, cancel, progress)

        def done(q):
            self.mesh_q = q
            self.mesh_lbl.setText(f"{len(q['tets']):,} tetrahedra, {len(q['nodes']):,} nodes (quadratic), element size {l_out(h):.4g} {UD()['L']}")
            self.say("Meshed.")
            self.show_field(mesh_only=True)
        return self.run_job(work, done, "Meshing")

    def run_solve(self):
        why = self.ready()
        if why:
            self.say(why)
            return False
        try:
            r = sm.resolve(self.geom, self.setup)
        except fem.FemError as ex:
            self.say(str(ex))
            return False
        g = self.geom

        def work(progress, cancel):
            return sm.run(g, r, self.cache, cancel, progress)

        def done(res):
            self.result = res
            self.mesh_q = self.cache.get(sm.mesh_key(g, res["h"]), self.mesh_q)
            self.mesh_lbl.setText(f"{res['n_tets']:,} tetrahedra, {res['n_nodes']:,} nodes (quadratic), element size {l_out(res['h']):.4g} {UD()['L']}")
            self.describe()
            self.show_field()
            self.enable_buttons()
        return self.run_job(work, done, "Solving")

    def describe(self):
        r = self.result
        if r is None:
            return
        D = UD()
        mu = unitctl.mass_units()
        rows = [("Largest von Mises stress", R.num(s_out(r["vm_max"])), D["S"]), ("Largest displacement", R.num(l_out(r["umax"])), D["L"]),
                ("Largest principal stress", R.num(s_out(r["s1_max"])), D["S"]), ("Smallest principal stress", R.num(s_out(r["s3_min"])), D["S"]),
                ("Mass", R.num(r["mass"] * mu[3]), mu[1])]
        html = R.summary(r.get("fos_y"), r.get("fos_u"), rows)
        if r.get("support_reactions"):
            html += R.heading("Reactions", D["F"])
            html += R.grid(["", "Fx", "Fy", "Fz"], [[n, *(R.num(f_out(x)) for x in v)] for n, v in r["support_reactions"]])
        html += R.heading("Mesh") + R.kv([("Tetrahedra (quadratic)", f"{r['n_tets']:,}", None), ("Nodes", f"{r['n_nodes']:,}", None),
                                           ("Element size", R.num(l_out(r["h"]), 4), D["L"])])
        html += R.note("This window does not refine the mesh by itself: check by meshing finer and comparing, or run a parametric study "
                       "over the element size.")
        info = r.get("info") or {}
        ok = r["equilibrium"] < 1e-6
        sums = "Applied + reactions = (" + ", ".join(R.num(f_out(a + b), 3) for a, b in zip(r["applied"], r["reaction"])) + f") {D['F']}"
        html += R.solver_block(info.get("solver", "?"), info.get("residual"), ok, sums,
                               [f"Relative error of the force balance {r['equilibrium']:.1e}."] if not ok else None)
        self.res_lbl.setText(html)
        self.say("Solved.")

    def scale_value(self):
        t = self.e_scale.text().strip().lower()
        if t == "auto" and self.result is not None:
            return 0.1 * self.geom["diag"] / max(self.result["umax"], 1e-300)
        try:
            return float(t)
        except ValueError:
            return 0.0

    def field_values(self):
        r = self.result
        i = self.cb_field.currentIndex()
        D = UD()
        if i == 0:
            return s_out(r["vm_node"]), f"von Mises ({D['S']})"
        if i == 1:
            return l_out(r["un"]), f"displacement ({D['L']})"
        sy = r["material"].get("sy") or 0.0
        return np.where(r["vm_node"] > 1e-12, sy / np.maximum(r["vm_node"], 1e-12), 100.0).clip(0, 100), "safety factor (yield)"

    def show_field(self, mesh_only=False):
        if self.result is None:
            if self.mesh_q is not None:
                q = self.mesh_q
                self.view.show_mesh(q["nodes"], q["tets"])          # grey surface with the mesh edges: no result colours before Solve
            return
        r = self.result
        vals, title = self.field_values()
        self.view.show_result(r["nodes"], r["conn"], r["u"], vals, title, self.scale_value(), self.cb_edges.isChecked())

    # ------------------------------------------------------------------ probes
    def set_probe_mode(self, on):
        self.view.probe_mode = bool(on)
        self.view.on_probe = self.probe_at if on else None
        self.say("Click the solved part to read the values there." if on else "Probe off: a click picks a face again.")

    def probe_at(self, point):
        """A click on the result surface: the node nearest to the clicked point (of the deformed shape that is on screen)."""
        if self.result is None or point is None:
            self.probe_lbl.setText("Solve first, then click the coloured part.")
            return None
        r = self.result
        pts = r["nodes"] + self.scale_value() * r["u"]
        i = int(np.argmin(np.linalg.norm(pts - np.asarray(point, float), axis=1)))
        return self.probe_index(i, float(np.linalg.norm(pts[i] - np.asarray(point, float))))

    def probe_node(self):
        if self.result is None:
            self.probe_lbl.setText("Solve first.")
            return None
        D = UD()
        try:
            p = [l_in(float(x)) for x in self.e_probe.text().replace(";", ",").split(",")]
            assert len(p) == 3
        except Exception:
            self.probe_lbl.setText(f"Type the point as x, y, z ({D['L']}).")
            return None
        i, d, un, vm = sm.probe(self.result, p)
        self.probe_index(i, d)
        return i, d, un, vm

    def probe_index(self, i, dist):
        r = self.result
        self.last_probe = {"i": int(i), "dist": float(dist)}
        self.show_probe(self.last_probe)
        return int(i), float(dist), float(r["un"][i]), float(r["vm_node"][i])

    def show_probe(self, pr):
        r = self.result
        if r is None:
            return
        i = pr["i"]
        D = UD()
        x = r["nodes"][i]
        u = r["u"][i]
        vm = float(r["vm_node"][i])
        sy = r["material"].get("sy") or 0.0
        fos = (sy / vm) if vm > 1e-12 and sy else None
        d = [("ux", R.num(l_out(u[0])), None), ("uy", R.num(l_out(u[1])), None), ("uz", R.num(l_out(u[2])), None),
             ("Total |u|", R.num(l_out(float(r["un"][i]))), None)]
        st = [("von Mises", R.num(s_out(vm)), None)]
        if fos is not None:
            st.append(("Safety factor, yield", R.num(fos, 4), None))
        where = (f"node {i} at ({R.num(l_out(x[0]))}, {R.num(l_out(x[1]))}, {R.num(l_out(x[2]))}) {D['L']}, "
                 f"{R.num(l_out(pr['dist']), 3)} {D['L']} from the point")
        self.probe_lbl.setText(R.probe_block("Probe", where, d, st, D["L"], D["S"], "Stress: value at the node (average of the elements around it)."))

    def export_animation(self, path=None, frames=16):
        if self.result is None:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export animation", "result.gif", "GIF (*.gif)")
            if not path:
                return None
        from PIL import Image
        r = self.result
        vals, title = self.field_values()
        sc = self.scale_value() or 0.1 * self.geom["diag"] / max(r["umax"], 1e-300)
        try:
            arr = sv.SolidView.render_frames(r["nodes"], r["conn"], r["u"], vals, title, sc, frames, self.cb_edges.isChecked())
        except Exception as ex:
            self.say(f"Could not render the animation: {ex}")
            return None
        imgs = [Image.fromarray(a) for a in arr]
        if not imgs:
            return None
        imgs = imgs + imgs[::-1][1:-1]
        imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=80, loop=0)
        return path

    # ------------------------------------------------------------------ state, save, open
    def setup_json(self):
        return json.dumps(self.setup)

    def export_state(self):
        try:
            self.read_inputs()
        except ValueError:
            pass
        return {"setup": json.loads(self.setup_json()), "result": self.result, "mesh": None}

    def import_state(self, st):
        s = st.get("setup") or sm.default_setup()
        s.setdefault("dims", {})
        dims_changed = s["dims"] != self.setup.get("dims") or getattr(self, "geom_case", False)
        self.geom_case = False
        self.setup = json.loads(json.dumps(s))
        self.put_material(self.setup["material"])
        self.select_material_name(self.setup.get("mat_name"))
        self.e_h.setText(format(l_out(self.setup["h"]), ".8g") if self.setup.get("h") else "")
        if dims_changed and self.source is not None:
            self.load_geometry()
        self.result = st.get("result")
        self.refresh_lists()
        self.colour()
        if self.result is not None:
            self.describe()
            self.show_field()
        else:
            self.invalidate()

    def unit_name(self):
        return "mm"

    def signature(self):
        return self.setup_json() if self.geom is not None else None

    def is_dirty(self):
        try:
            self.read_inputs()
        except ValueError:
            pass
        return self.signature() != self.saved_sig

    def save(self, as_new=False):
        if as_new or not self.project_ok():
            if not self.new_project():
                return False
        try:
            self.read_inputs()
        except ValueError as ex:
            self.say(str(ex))
        m = sim_project.read(self.path)
        m["meta"] = {"dims": self.setup["dims"]}
        try:
            sim_project.write(self.path, m)
            tmp = sim_project.state_path(self.path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"kind": "solid", "setup": self.setup}, f)
            os.replace(tmp, sim_project.state_path(self.path))
        except Exception as ex:
            QMessageBox.warning(self, "Save", f"Could not save: {ex}")
            return False
        self.saved_sig = self.signature()
        self.say(f"Saved {self.path}")
        return True

    @classmethod
    def open_project(cls, shell, folder, threaded=True):
        folder = os.path.abspath(folder.rstrip("/\\") or folder)
        if sim_project.kind_of_folder(folder) != "solid":
            raise ValueError("not a 3D FEA project folder")
        m = sim_project.read(folder)
        w = cls(shell=shell, path=folder, threaded=threaded)
        s = m.get("source") or {}
        w.src = {"type": "part", "path": s.get("orig"), "name": s.get("name", "")}
        sp = sim_project.state_path(folder)
        if os.path.isfile(sp):
            try:
                with open(sp, encoding="utf-8") as f:
                    st = json.load(f).get("setup")
                if st:
                    st.setdefault("dims", {})
                    w.setup = st
            except Exception:
                pass
        w.put_material(w.setup["material"])
        w.select_material_name(w.setup.get("mat_name"))
        w.e_h.setText(format(l_out(w.setup["h"]), ".8g") if w.setup.get("h") else "")
        sf = sim_project.source_file(folder, m)
        if sf:
            try:
                w.source = sim_source.open_source(sf)
                w.load_geometry()
            except sim_source.SourceError as ex:
                w.say(str(ex))
        w.show_source()
        w.refresh_lists()
        w.colour()
        w.saved_sig = w.signature()
        w.enable_buttons()
        return w

    # ------------------------------------------------------------------ the parametric study
    def study_adapter(self):
        import solid_study
        return solid_study.SolidStudy(self)

    def refresh_study_button(self):
        on = bool(ext.hooks("sim_study"))
        self.study_box.setVisible(on)
        if not on:
            return
        have = bool(self.path) and os.path.isfile(os.path.join(self.path, sim_project.STUDY_DIR, "study.json"))
        self.b_study.setText("Open parametric study" if have else "Create parametric study")
        self.b_study.setEnabled(self.job is None)

    def open_study(self):
        fns = ext.hooks("sim_study")
        if not fns:
            QMessageBox.information(self, "Parametric study", "The Parametric Studies add-on is not loaded. Install or enable it, then restart.")
            return None
        if not self.project_ok() or self.geom is None:
            QMessageBox.information(self, "Parametric study", "Press 'New project...' and import a part first: the study is saved in the project.")
            return None
        if self.is_dirty():
            if not self.save():
                return None
        return fns[0](self)

    def closeEvent(self, ev):
        unitctl.off_change(self.units_changed)
        if self.job is not None:
            self.job.stop = True
            self.job.wait(5000)
        self.view.close()
        super().closeEvent(ev)


def QApplication_keyboard():
    from PyQt6.QtWidgets import QApplication
    m = QApplication.keyboardModifiers()
    return bool(m & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))


def make_solid(host, path=None):
    if path:
        return SolidWindow.open_project(host, path)
    return SolidWindow(shell=host)
