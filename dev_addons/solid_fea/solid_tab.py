"""
solid_tab.py - the 3D FEA window (project folder .gpv): a parametric part, or an ASSEMBLY - fully bonded (faces within the bond distance are joined) or
joined by SCREWS and BOLTS (frictionless contact between the parts, the patches with a screw bonded, the force through each patch checked with AISI S100-16);
every body keeps its own material.  Linear elastic, quadratic tetrahedra (or a hex-dominant mesh for a single part).

Project bar:  New project / Import source / Update from original / Save   (the same project folder machinery as the 1D / 2D simulations:
              the part is COPIED into  source/  and the simulation only uses the copy)
Left panel:   the sections of 1D FEA: Geometry (part dimensions you can edit), Material, Supports, Loads, Mesh, then Solve, [parametric study] and
              Results (result, Colours, deformed shape, scale, Animate with Play / Export, the Probe)
Right:        the part in 3D with the X / Y / Z triad bottom-left and the colour legend top-right; click a face to pick it (the Faces list
              does the same without the mouse)

The window is also the 'tab' the parametric studies talk to (study_adapter), so it offers export_state / import_state / unit_name.
"""
import json
import os
import threading
import traceback

import numpy as np
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import anim_export
import ext
import physics_materials as pm
import result_style
import sim_matdlg
import sim_project
import sim_report as R
import sim_ui
import sim_source
import solid_asm as sasm
import solid_fem as fem
import solid_geom as sg
import solid_mesh as smesh
import solid_model as sm
import solid_screw as screw
import solid_view as sv
import unitctl
import units

# the results the "Result" box offers (key, name); displacement magnitude first, as in 1D FEA.  Units are added to the names by refresh_labels().
FIELDS = [("umag", "Displacement magnitude"), ("ux", "Displacement X"), ("uy", "Displacement Y"), ("uz", "Displacement Z"),
          ("vm", "Von Mises stress"), ("fos", "Safety factor (yield)")]
FOS_LOW, FOS_HIGH = 0.5, 3.0                 # the safety-factor colours, as in 1D FEA: red at or below FOS_LOW, blue at or above FOS_HIGH


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
        self.cur_body = None
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
        self.hidden_bodies = set()              # the parts of an assembly that are not drawn (to see and pick the faces between parts); not saved

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
        split.setSizes([400, 1000])                  # the panel starts about 400 wide; drag the divider for more (not remembered)
        lay.addWidget(split, 1)
        self.build_panel()
        self.show_source()
        unitctl.on_change(self.units_changed)

    # ------------------------------------------------------------------ the panel
    def sec(self, n, title, open_=True, summary=None, help_text=None):
        s_ = sim_ui.Section("solid", n, title, open_, help_text, summary)
        self.sections.append(s_)
        return s_.body

    @staticmethod
    def hint(text):
        """The one-line hint over the support / load buttons: small grey text, like the other simulation panels."""
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#555555; font-size:11px;")
        return lb

    def build_panel(self):
        # --- 1 geometry
        v = self.sec(1, "Geometry", True, summary=lambda: self.geo_lbl.text().split("\n")[0][:90])
        self.geo_lbl = QLabel("No part yet: press Import source...")
        self.geo_lbl.setWordWrap(True)
        v.addWidget(self.geo_lbl)
        self.asm_box = QWidget()                                     # an assembly: what is bonded to what, what is wrong, the bond distance
        al = QVBoxLayout(self.asm_box)
        al.setContentsMargins(0, 0, 0, 0)
        self.asm_lbl = QLabel("")
        self.asm_lbl.setWordWrap(True)
        self.asm_lbl.setTextFormat(Qt.TextFormat.RichText)
        al.addWidget(self.asm_lbl)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("Bond distance"))
        self.e_bond = QLineEdit()
        self.e_bond.setPlaceholderText("automatic")
        self.e_bond.setToolTip("Faces of different parts that are closer than this are treated as one face: the parts are fully bonded there (no slip, no gap, "
                               "no separation). Empty = automatic (about a ten-thousandth of the size of the assembly). Raise it to bond parts that sit a little apart.")
        self.e_bond.editingFinished.connect(self.bond_changed)
        brow.addWidget(self.e_bond, 1)
        self.bond_unit = QLabel("mm")
        brow.addWidget(self.bond_unit)
        al.addLayout(brow)
        jrow = QHBoxLayout()
        jrow.addWidget(QLabel("Joint"))
        self.joint_combo = QComboBox()
        self.joint_combo.addItem("Fully bonded: touching faces are one", "bonded")
        self.joint_combo.addItem("Screws and bolts: parts touch freely", "contact")
        self.joint_combo.setToolTip("Fully bonded: the parts are one body wherever their faces touch (no slip, no gap, no separation).\n"
                                    "Screws and bolts: the faces between two parts are frictionless contact (the parts press on each other but slide and may "
                                    "open), and only the patches that carry a screw or bolt are bonded. The force through each of those patches is what the "
                                    "screw or bolt has to carry.")
        sim_ui.tame(self.joint_combo, 24)
        self.joint_combo.activated.connect(lambda _i: self.joint_picked())
        jrow.addWidget(self.joint_combo, 1)
        al.addLayout(jrow)
        self.screw_box = QWidget()                                   # only with the joint 'screws and bolts'
        sl = QVBoxLayout(self.screw_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(3)
        sl.addWidget(self.hint("Cut the face between two parts into patches with Split (below), the size of a screw head or so, and select the patches "
                               "that carry a screw: click them in the view (untick a part under Show parts to see the faces between the parts) or in the "
                               "Faces list; Ctrl/Shift for several. Then press Add screw."))
        sl.addWidget(QLabel("Show parts"))
        self.show_list = QListWidget()
        self.show_list.setMaximumHeight(80)
        self.show_list.setToolTip("Untick a part to hide it: the faces between it and the parts that stay shown then appear and can be clicked.")
        self.show_list.itemChanged.connect(self.show_changed)
        sl.addWidget(self.show_list)
        row = QHBoxLayout()
        self.b_add_screw = QPushButton("Add screw...")
        self.b_add_screw.setToolTip("Puts the same screw or bolt on every selected patch (a patch is a face between two parts). The screw sits at the centre of "
                                    "the patch; no hole is modelled, the patch is bonded and the force through it is read.")
        self.b_add_screw.clicked.connect(lambda: self.add_screws())
        self.b_edit_screw = QPushButton("Edit...")
        self.b_edit_screw.clicked.connect(lambda: self.edit_screw())
        self.b_del_screw = QPushButton("Remove")
        self.b_del_screw.clicked.connect(lambda: self.remove_screw())
        for b in (self.b_add_screw, self.b_edit_screw, self.b_del_screw):
            row.addWidget(b)
        sl.addLayout(row)
        self.screw_table = QTableWidget(0, 5)
        self.screw_table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Patches", "Result"])
        self.screw_table.verticalHeader().hide()
        self.screw_table.setMinimumHeight(90)
        self.screw_table.setMaximumHeight(170)
        self.screw_table.horizontalHeader().setStretchLastSection(True)
        self.screw_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.screw_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.screw_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.screw_table.setToolTip("Click a row to select its patches in the view. Double-click to change the screw.")
        self.screw_table.itemSelectionChanged.connect(self.screw_row_selected)
        self.screw_table.cellDoubleClicked.connect(lambda _r, _c: self.edit_screw())
        sl.addWidget(self.screw_table)
        drow = QHBoxLayout()
        drow.addWidget(QLabel("Design method"))
        self.design_combo = QComboBox()
        for k, text in screw.METHODS.items():
            self.design_combo.addItem(text, k)
        self.design_combo.setToolTip("How the strengths of AISI S100-16 are taken: ASD divides the nominal strength by the safety factor, LRFD multiplies it by "
                                     "phi, LSD by the Canadian phi, nominal uses it as it is. Loads are the ones you typed (no load factors are applied).")
        sim_ui.tame(self.design_combo, 24)
        self.design_combo.activated.connect(lambda _i: self.design_picked())
        drow.addWidget(self.design_combo, 1)
        sl.addLayout(drow)
        al.addWidget(self.screw_box)
        self.screw_box.hide()
        v.addWidget(self.asm_box)
        self.asm_box.hide()
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
        self.split_lbl = QLabel("Split a flat face into patches (to load or support only a part of it): select the face, then choose how many columns "
                                "(along its longer side) and rows (across it).")
        self.split_lbl.setWordWrap(True)
        self.split_lbl.setStyleSheet("color:#707070;")
        v.addWidget(self.split_lbl)
        self.split_words = []
        row = QHBoxLayout()
        self.sp_cols = QSpinBox()
        self.sp_rows = QSpinBox()
        for sbx, word in ((self.sp_cols, "columns"), (self.sp_rows, "rows")):
            sbx.setRange(1, 9999)
            sbx.setValue(1)
            sbx.setToolTip(f"How many equal strips. The grid is shown on the selected face before you press Split; there is no limit, but above {sg.WARN_PATCHES} patches it asks first.")
            sbx.valueChanged.connect(self.preview_grid)
            row.addWidget(sbx)
            wl = QLabel(word + ("  x" if word == "columns" else ""))
            self.split_words.append(wl)
            row.addWidget(wl)
        row.addStretch(1)
        self.b_split = QPushButton("Split")
        self.b_split.setToolTip("Cuts the selected flat face into equal columns x rows patches. Supports and loads on the whole face stay and apply to every patch.")
        self.b_split.clicked.connect(lambda: self.split_selected())
        self.b_unsplit = QPushButton("Unsplit")
        self.b_unsplit.setToolTip("Puts the patches of the selected face back together into one face.")
        self.b_unsplit.clicked.connect(lambda: self.unsplit_selected())
        row.addWidget(self.b_split)
        row.addWidget(self.b_unsplit)
        v.addLayout(row)
        self.split_hdr = QLabel("Split faces (click one to see and change the sizes of its columns and rows):")
        self.split_hdr.setWordWrap(True)
        v.addWidget(self.split_hdr)
        self.split_list = QListWidget()
        self.split_list.setMaximumHeight(70)
        self.split_list.itemSelectionChanged.connect(self.split_list_changed)
        v.addWidget(self.split_list)
        self.sz_table = QTableWidget(0, 3)
        self.sz_table.setHorizontalHeaderLabels(["Strip", "Size", "Fixed"])
        self.sz_table.horizontalHeader().setStretchLastSection(True)
        self.sz_table.verticalHeader().setVisible(False)
        self.sz_table.setMaximumHeight(190)
        self.sz_table.setToolTip("Type a size to fix it (decimals are fine, in the program's length unit). Strips that are not fixed share what is left "
                                 "equally. Clear the box, or untick Fixed, to make a strip free again.")
        self.sz_table.itemChanged.connect(self.size_item_changed)
        v.addWidget(self.sz_table)
        row = QHBoxLayout()
        self.b_setsize = QPushButton("Set size...")
        self.b_setsize.setToolTip("Sets the width of the column and the height of the row of the selected patch.")
        self.b_setsize.clicked.connect(lambda: self.set_size_dialog())
        self.b_even = QPushButton("Even sizes")
        self.b_even.setToolTip("Makes every column and row of the selected split face equal again.")
        self.b_even.clicked.connect(lambda: self.even_sizes())
        row.addWidget(self.b_setsize)
        row.addWidget(self.b_even)
        row.addStretch(1)
        v.addLayout(row)
        self.cur_split = None
        self.part_only = [self.dims]                                       # what only a single part has: the dimensions (the face splits work on an assembly too)
        # --- 2 material and analysis
        v = self.sec(2, "Material and analysis", True, summary=lambda: self.mat_combo.currentText().strip() or "custom material")
        self.mat_combo = QComboBox()
        self.mat_combo.activated.connect(self.material_picked)
        row = QHBoxLayout()
        row.addWidget(self.mat_combo, 1)
        b = QPushButton("Add material...")
        b.setToolTip("Adds the numbers now in the boxes below (or others you type in the box that opens) to your material library "
                     "(the same one 1D and 2D FEA use).")
        b.clicked.connect(self.add_material)
        row.addWidget(b)
        self.b_del_mat = QPushButton("Delete")
        self.b_del_mat.setToolTip("Deletes a material you added. The built-in ones stay.")
        self.b_del_mat.clicked.connect(self.delete_material)
        row.addWidget(self.b_del_mat)
        v.addLayout(row)
        self.body_lbl = QLabel("Bodies of the assembly: select one, and the material above and the numbers below are its own (a body starts with the material of its part).")
        self.body_lbl.setWordWrap(True)
        v.addWidget(self.body_lbl)
        self.body_table = QTableWidget(0, 2)
        self.body_table.setHorizontalHeaderLabels(["Body", "Material"])
        self.body_table.verticalHeader().setVisible(False)
        self.body_table.horizontalHeader().setStretchLastSection(True)
        self.body_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.body_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.body_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.body_table.setMaximumHeight(160)
        self.body_table.itemSelectionChanged.connect(self.body_selected)
        v.addWidget(self.body_table)
        self.body_lbl.hide()
        self.body_table.hide()
        self.mat_note = QLabel("")
        self.mat_note.setWordWrap(True)
        self.mat_note.setStyleSheet("color:#707070;")
        f = QFormLayout()
        self.e_E, self.e_nu, self.e_rho, self.e_sy, self.e_su = (QLineEdit() for _ in range(5))
        self.mat_labels = {}
        for e, key in ((self.e_E, "E"), (self.e_nu, "nu"), (self.e_rho, "rho"), (self.e_sy, "sy"), (self.e_su, "su")):
            lab = QLabel()
            self.mat_labels[key] = lab
            f.addRow(lab, e)
            e.editingFinished.connect(self.inputs_changed)
        v.addLayout(f)
        v.addWidget(sim_ui.wrapped("Analysis: linear elastic, small displacements, tetrahedra (quadratic unless you choose linear in the advanced mesh options; hex-dominant is there too)."))
        v.addWidget(self.mat_note)
        self.fill_materials()
        self.put_material(self.setup["material"])
        # --- 3 supports
        v = self.sec(3, "Supports", True, summary=lambda: f"{len(self.setup['supports'])} support(s)")
        v.addWidget(self.hint("Select the face(s) first (click them in the view), then press a button."))
        for mode, icn, tip in (("fixed", "fixed", "Holds the selected faces in every direction."),
                               ("slide", "ux", "Holds the selected faces only in the direction normal to them; they slide freely along it."),
                               ("bolt", "bolt", "A bolt or pin hole: the selected hole surface is held fixed.")):
            b = sim_ui.icon_button({"fixed": "Fixed", "slide": "One direction (normal)", "bolt": "Bolt / pin hole"}[mode], icn, tip)
            b.clicked.connect(lambda _c=False, m_=mode: self.add_support(m_))
            v.addWidget(b)
        self.sup_list = QListWidget()                 # the plain-text copy of the supports (kept for scripts); the table under Loads shows them
        self.sup_list.hide()
        v.addWidget(self.sup_list)
        # --- 4 loads
        v = self.sec(4, "Loads", True, summary=lambda: f"{len(self.setup['loads'])} load(s)")
        v.addWidget(self.hint("Select the face(s) first (click them in the view), then press a button."))
        for text, icn, kind, tip in (("Force on face(s)...", "force", "force", "A total force spread over the selected faces."),
                                     ("Pressure on face(s)...", "pressure", "pressure", "Pressure on the selected faces; positive pushes into the part."),
                                     ("Force at vertex...", "force", "point", "A force at the selected vertex (a click on a face picks its nearest vertex)."),
                                     ("Gravity...", "line_load", "gravity", "The weight of the part (body load).")):
            b = sim_ui.icon_button(text, icn, tip)
            b.clicked.connect(lambda _c=False, k=kind: self.add_load(k))
            v.addWidget(b)
        self.load_list = QListWidget()                # the plain-text copy of the loads (kept for scripts)
        self.load_list.hide()
        v.addWidget(self.load_list)
        v.addWidget(QLabel("Conditions on this model"))
        self.cond_table = QTableWidget(0, 4)
        self.cond_table.setHorizontalHeaderLabels(["Name", "Type", "Applied to", "Value"])
        self.cond_table.verticalHeader().hide()
        self.cond_table.setMinimumHeight(110)
        self.cond_table.setMaximumHeight(200)
        self.cond_table.horizontalHeader().setStretchLastSection(True)
        self.cond_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cond_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cond_table.setToolTip("Supports first, then loads. Double-click a Name to rename it; double-click a load to change its numbers.")
        self.cond_table.itemChanged.connect(self.cond_item_changed)
        self.cond_table.cellDoubleClicked.connect(self.cond_double_clicked)
        v.addWidget(self.cond_table)
        row = QHBoxLayout()
        b = QPushButton("Edit selected...")
        b.setToolTip("Edits the selected row: a load opens its numbers again; a support lets you rename it.")
        b.clicked.connect(self.edit_condition)
        row.addWidget(b)
        b = QPushButton("Remove selected")
        b.clicked.connect(self.remove_condition)
        row.addWidget(b)
        v.addLayout(row)
        # --- 5 mesh
        v = self.sec(5, "Mesh", True, summary=lambda: self.mesh_lbl.text() or "not meshed",
                     help_text="The part is filled with tetrahedra. Element size: the length of an element edge (blank = automatic, a fourteenth of "
                               "the part's size). Smaller elements are more accurate and slower. Advanced mesh options: choose linear or quadratic "
                               "elements, make the mesh finer at curved surfaces or on single faces, and read how good the elements are.")
        f = QFormLayout()
        self.e_h = QLineEdit()
        self.e_h.setPlaceholderText("auto")
        self.e_h.editingFinished.connect(self.inputs_changed)
        self.h_label = QLabel()
        f.addRow(self.h_label, self.e_h)
        v.addLayout(f)
        self.build_advanced_mesh(v)
        self.b_mesh = QPushButton("Mesh")
        self.b_mesh.clicked.connect(self.run_mesh)
        v.addWidget(self.b_mesh)
        self.mesh_lbl = QLabel("")
        self.mesh_lbl.setWordWrap(True)
        v.addWidget(self.mesh_lbl)
        self.quality_box = QWidget()                                    # the quality of the mesh just made (only with the advanced options)
        ql = QVBoxLayout(self.quality_box)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(QLabel("<b>Mesh quality</b>"))
        self.quality_lbl = QLabel("")
        self.quality_lbl.setWordWrap(True)
        self.quality_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.quality_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ql.addWidget(self.quality_lbl)
        self.quality_box.setVisible(False)
        v.addWidget(self.quality_box)
        # --- 6 results (laid out like the Results of 1D FEA: result, colours, deformed shape, scale, animation; the probe is part of it)
        v = self.sec(6, "Results", True, summary=lambda: self.cb_field.currentText(),
                     help_text="Linear elastic, small displacements, tetrahedra (quadratic by default). Stresses are values at the nodes (the average of the elements "
                               "around each node). The safety factor is the yield strength divided by the von Mises stress (red at 0.5 or less, "
                               "blue at 3 or more; grey = no yield strength typed). The X, Y and Z of the results and loads are the axes of the part "
                               "- the triad in the bottom-left corner of the view shows them.")
        self.cb_field = QComboBox()
        for key, name in FIELDS:
            self.cb_field.addItem(name, key)
        self.cb_field.currentIndexChanged.connect(lambda _i: self.show_field())
        v.addWidget(self.cb_field)
        row = QHBoxLayout()
        row.addWidget(QLabel("Colours"))
        self.cmap_combo = result_style.make_combo(self, self.colours_changed)
        row.addWidget(self.cmap_combo, 1)
        v.addLayout(row)
        self.cb_def = QCheckBox("Show deformed shape")
        self.cb_def.setChecked(True)
        self.cb_def.toggled.connect(lambda _on: self.show_field())
        v.addWidget(self.cb_def)
        row = QHBoxLayout()
        row.addWidget(QLabel("Deformation scale"))
        self.e_scale = QLineEdit("")
        self.e_scale.setPlaceholderText("auto")
        self.e_scale.setToolTip("Displacement magnification. Blank (auto) = the largest displacement is about a tenth of the part; 1 = the true "
                                "shape (you will hardly see it); any number you type is used as it is.")
        self.e_scale.editingFinished.connect(self.show_field)
        row.addWidget(self.e_scale)
        v.addLayout(row)
        self.cb_edges = QCheckBox("Show mesh edges")
        self.cb_edges.toggled.connect(lambda _on: self.show_field())
        v.addWidget(self.cb_edges)
        self.cb_anim = QCheckBox("Animate")
        self.cb_anim.setToolTip("Ramps the load from 0 to its full value. The analysis is linear and static, so this is a ramp, not a time simulation.")
        self.cb_anim.toggled.connect(self.anim_toggled)
        v.addWidget(self.cb_anim)
        self.anim_box = QWidget()
        al = QFormLayout(self.anim_box)
        al.setContentsMargins(14, 0, 0, 0)
        self.e_frames = QLineEdit("30")
        self.e_dur = QLineEdit("3")
        self.loop_combo = QComboBox()
        self.loop_combo.addItems(["Once", "Loop", "Back and forth"])
        al.addRow("Frames", self.e_frames)
        al.addRow("Duration (s)", self.e_dur)
        al.addRow("Playback", self.loop_combo)
        arow = QHBoxLayout()
        self.b_play = QPushButton("Play")
        self.b_play.clicked.connect(self.anim_play)
        self.b_stop = QPushButton("Stop")
        self.b_stop.clicked.connect(self.anim_stop)
        arow.addWidget(self.b_play)
        arow.addWidget(self.b_stop)
        al.addRow(arow)
        self.b_anim = QPushButton("Export animation...")
        self.b_anim.setToolTip("Saves the animation as a transparent animated WebP or PNG (only what is drawn is kept), an animated GIF"
                               + (", an MP4 video" if anim_export.mp4_available() else " (an MP4 video too when OpenCV or imageio-ffmpeg is installed)")
                               + " or a folder of PNG pictures, seen from where the part is on screen now. It uses the Frames, Duration and Playback above.")
        self.b_anim.clicked.connect(lambda: self.export_animation())
        al.addRow(self.b_anim)
        note = QLabel("Ramp of the load from 0 to full (linear static analysis, not a time simulation). The colour scale stays that of the "
                      "final result.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#707070;")
        al.addRow(note)
        self.anim_box.setVisible(False)
        v.addWidget(self.anim_box)
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.anim_step)
        self.anim_dir, self.anim_k, self.anim_n = 1, 0, 0
        self.res_lbl = QLabel("No result yet.")
        self.res_lbl.setWordWrap(True)
        self.res_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.res_lbl)
        pl = QLabel("<b>Probe</b>")
        v.addWidget(pl)
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
        b = QPushButton("Zoom to fit")
        b.clicked.connect(self.view.fit)
        v.addWidget(b)
        # --- the Solve button (wide), the study slot, then the Results
        row = QHBoxLayout()
        self.b_solve = sim_ui.solve_button()
        self.b_solve.clicked.connect(self.run_solve)
        row.addWidget(self.b_solve, 1)
        self.b_cancel = sim_ui.solve_side_button("Cancel")
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
            if s_.number == 6:
                self.col.addLayout(row)
                self.col.addWidget(self.study_box)
            self.col.addWidget(s_)
        self.study_box.setVisible(False)
        self.col.addStretch(1)
        sim_ui.soften(self.panel)                    # the sections were added after make_panel: give them the soft bevel look too
        self.refresh_labels()
        self.enable_buttons()

    # ------------------------------------------------------------------ advanced mesh options
    def build_advanced_mesh(self, v):
        """The 'Advanced mesh options' tick box and what it reveals (see solid_mesh for what each option does)."""
        self.cb_adv = QCheckBox("Advanced mesh options")
        self.cb_adv.setToolTip("Mesh type (tetrahedra or hex-dominant), element order, a minimum size and a growth rate, refinement at curved surfaces and on "
                               "single faces, and a quality report. Off = the plain automatic mesh (quadratic tetrahedra).")
        v.addWidget(self.cb_adv)
        self.adv_box = QWidget()
        al = QVBoxLayout(self.adv_box)
        al.setContentsMargins(14, 0, 0, 0)
        al.setSpacing(3)
        f = QFormLayout()
        self.type_combo = QComboBox()
        for k, text in smesh.TYPES.items():
            self.type_combo.addItem(text, k)
        self.type_combo.setToolTip("Tetrahedra: the whole part is filled with them. Hex-dominant: a block of brick elements (hexahedra) inside the part, and "
                                   "tetrahedra, joined to the bricks by pyramids, between it and the surface. The surface mesh is the same either way, so the "
                                   "borders of split patches stay mesh edges. A part with no room for bricks (thin, small, or a fine element size) gets "
                                   "tetrahedra, and the mesh quality box says so. The share of bricks grows as the elements get small compared to the part.")
        sim_ui.tame(self.type_combo, 24)
        f.addRow("Mesh type", self.type_combo)
        self.order_combo = QComboBox()
        for k, text in smesh.ORDERS.items():
            self.order_combo.addItem(text, k)
        self.order_combo.setToolTip("Quadratic elements (mid-edge nodes: 10-node tetrahedra, 20-node bricks) bend and carry stress gradients much better, so they "
                                    "are the right choice almost always. Linear elements (corner nodes only) are quicker but stiffer in bending: they need a "
                                    "much finer mesh for the same accuracy.")
        sim_ui.tame(self.order_combo, 24)
        f.addRow("Element order", self.order_combo)
        self.e_hmin = QLineEdit()
        self.e_hmin.setPlaceholderText("auto")
        self.e_hmin.setToolTip("The smallest element edge the mesher may make (blank = a sixth of the element size).")
        self.hmin_label = QLabel("Minimum size")
        f.addRow(self.hmin_label, self.e_hmin)
        self.e_growth = QLineEdit("1.3")
        self.e_growth.setToolTip(f"How fast elements grow away from a refined face: 1.3 = every layer of elements is 30 % longer than the one before. "
                                 f"{smesh.GROWTH_RANGE[0]:g} to {smesh.GROWTH_RANGE[1]:g}. Smaller = a smoother mesh with more elements.")
        f.addRow("Growth rate", self.e_growth)
        al.addLayout(f)
        row = QHBoxLayout()
        self.cb_curv = QCheckBox("Refine at curved surfaces")
        self.cb_curv.setChecked(True)
        self.cb_curv.setToolTip("Makes the elements smaller where a surface is curved (holes, fillets), so the curve is followed.")
        row.addWidget(self.cb_curv)
        self.sp_curv = QSpinBox()
        self.sp_curv.setRange(*smesh.CURV_RANGE)
        self.sp_curv.setValue(10)
        self.sp_curv.setToolTip("Elements around a full circle (a hole, a round edge). 10 is the automatic choice; more gives a rounder, finer mesh.")
        self.sp_curv.setSuffix(" per circle")
        row.addWidget(self.sp_curv)
        al.addLayout(row)
        self.local_hdr = QLabel("Smaller elements on single faces: select the face(s) in the view (or the Faces list), type a size, press the button.")
        self.local_hdr.setWordWrap(True)
        self.local_hdr.setStyleSheet("color:#555555; font-size:11px;")
        al.addWidget(self.local_hdr)
        row = QHBoxLayout()
        self.e_face_h = QLineEdit()
        self.e_face_h.setPlaceholderText("size")
        row.addWidget(self.e_face_h, 1)
        self.b_face_size = QPushButton("Set on selected faces")
        self.b_face_size.setToolTip("Gives the selected faces (or patches of a split face) a smaller element size than the global one. The elements grow "
                                    "back to the global size away from them, at the growth rate above.")
        self.b_face_size.clicked.connect(self.set_face_size)
        row.addWidget(self.b_face_size)
        al.addLayout(row)
        self.face_table = QTableWidget(0, 2)
        self.face_table.setHorizontalHeaderLabels(["Face", "Size"])
        self.face_table.verticalHeader().hide()
        self.face_table.setMinimumHeight(70)
        self.face_table.setMaximumHeight(130)
        self.face_table.horizontalHeader().setStretchLastSection(True)
        self.face_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.face_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.face_table.setToolTip("Double-click a size to change it.")
        self.face_table.itemChanged.connect(self.face_item_changed)
        al.addWidget(self.face_table)
        self.b_face_size_del = QPushButton("Remove selected size")
        self.b_face_size_del.clicked.connect(self.remove_face_size)
        al.addWidget(self.b_face_size_del)
        f = QFormLayout()
        self.follows_combo = QComboBox()
        for k, text in smesh.FOLLOWS.items():
            self.follows_combo.addItem(text, k)
        self.follows_combo.setToolTip("What the mesh follows: the borders of the patches of a split face lie on mesh edges, so a load or support on a patch "
                                      "covers exactly the patch.")
        f.addRow("Mesh follows", self.follows_combo)
        al.addLayout(f)
        self.adv_box.setVisible(False)
        v.addWidget(self.adv_box)
        self.cb_adv.toggled.connect(self.adv_toggled)
        self.order_combo.activated.connect(lambda _i: self.inputs_changed())
        self.type_combo.activated.connect(lambda _i: self.inputs_changed())
        self.follows_combo.activated.connect(lambda _i: self.inputs_changed())
        self.e_hmin.editingFinished.connect(self.inputs_changed)
        self.e_growth.editingFinished.connect(self.inputs_changed)
        self.cb_curv.toggled.connect(self.curv_toggled)
        self.sp_curv.valueChanged.connect(lambda _v: self.inputs_changed())

    def adv_toggled(self, on):
        self.adv_box.setVisible(bool(on))
        self.show_quality(self.mesh_q["quality"] if self.mesh_q is not None else None)
        self.inputs_changed()
        for s_ in self.sections:
            s_.refresh_summary()

    def curv_toggled(self, on):
        self.sp_curv.setEnabled(bool(on))
        self.inputs_changed()

    def read_mesh_options(self, h):
        """The mesh options from the boxes into the setup.  `h` = the element size typed (mm, 0 = automatic).  Raises ValueError for a bad number."""
        mo = smesh.complete(self.setup.get("mesh"))                      # the local sizes stay as they are
        mo["advanced"] = self.cb_adv.isChecked()
        mo["order"] = self.order_combo.currentData()
        mo["type"] = self.type_combo.currentData() or "tets"
        mo["follows"] = self.follows_combo.currentData() or "patches"
        mo["curv"] = self.sp_curv.value() if self.cb_curv.isChecked() else 0
        self.setup["mesh"] = mo
        if not mo["advanced"]:
            return
        t = self.e_hmin.text().strip()
        mo["hmin"] = l_in(num(self.e_hmin, "Minimum size")) if t else 0.0
        mo["growth"] = num(self.e_growth, "Growth rate")
        why = smesh.validate(mo, h or (sm.auto_h(self.geom) if self.geom is not None else 0.0))
        if why:
            raise ValueError(why)

    def put_mesh_options(self):
        """The boxes from the setup's mesh options (after opening a project, importing a state ...)."""
        mo = smesh.complete(self.setup.get("mesh"))
        self.setup["mesh"] = mo
        for wd in (self.cb_adv, self.cb_curv, self.sp_curv, self.order_combo, self.type_combo, self.follows_combo):
            wd.blockSignals(True)
        self.cb_adv.setChecked(bool(mo["advanced"]))
        self.order_combo.setCurrentIndex(max(0, self.order_combo.findData(mo["order"])))
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(mo["type"])))
        self.follows_combo.setCurrentIndex(max(0, self.follows_combo.findData(mo["follows"])))
        self.cb_curv.setChecked(mo["curv"] > 0)
        self.sp_curv.setValue(mo["curv"] or 10)
        self.sp_curv.setEnabled(mo["curv"] > 0)
        for wd in (self.cb_adv, self.cb_curv, self.sp_curv, self.order_combo, self.type_combo, self.follows_combo):
            wd.blockSignals(False)
        self.e_hmin.setText(format(l_out(mo["hmin"]), ".8g") if mo["hmin"] else "")
        self.e_growth.setText(format(mo["growth"], ".8g"))
        self.adv_box.setVisible(bool(mo["advanced"]))
        self.fill_face_table()

    def face_group_label(self, sig):
        ids = sg.match_faces(self.geom, sig) if self.geom is not None else None
        if not ids:
            return "(face not found)"
        if len(ids) == 1:
            return self.face_label(ids[0])
        p = self.geom["faces"][ids[0]].get("parent")
        return f"Face {(p if p is not None else ids[0]) + 1}, all {len(ids)} patches"

    def fill_face_table(self):
        t = self.face_table
        t.blockSignals(True)
        t.setRowCount(0)
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        for r, x in enumerate(smesh.complete(self.setup.get("mesh"))["face_sizes"]):
            t.insertRow(r)
            a = QTableWidgetItem(self.face_group_label(x["face"]))
            a.setFlags(ro)
            b = QTableWidgetItem(format(l_out(x["h"]), ".8g"))
            b.setFlags(ro | Qt.ItemFlag.ItemIsEditable)
            t.setItem(r, 0, a)
            t.setItem(r, 1, b)
        t.blockSignals(False)
        self.hmin_label.setText(f"Minimum size ({UD()['L']})")

    def face_sizes_changed(self):
        self.fill_face_table()
        self.invalidate(mesh=True)

    def effective_h(self):
        """The element size (mm) the next mesh gets: the typed one, or the automatic one."""
        try:
            t = self.e_h.text().strip()
            h = l_in(float(t.replace(",", "."))) if t else 0.0
        except ValueError:
            h = 0.0
        return h or (sm.auto_h(self.geom) if self.geom is not None else 0.0)

    def try_face_sizes(self, sizes):
        """Takes a new list of local sizes when the options stay valid with it; else says why not."""
        mo = smesh.complete(self.setup.get("mesh"))
        mo["face_sizes"] = sizes
        why = smesh.validate(dict(mo, advanced=True), self.effective_h())
        if why:
            self.say(why)
            return False
        self.setup["mesh"] = mo
        self.face_sizes_changed()
        return True

    def set_face_size(self):
        if self.geom is None:
            self.say("Import a part first.")
            return False
        if not self.sel_faces:
            self.say("Select the face(s) first (click them in the view, or in the Faces list), then set the size.")
            return False
        try:
            hf = l_in(float(self.e_face_h.text().strip().replace(",", ".")))
        except ValueError:
            self.say("Type the element size for the selected faces (a number).")
            return False
        sizes = [dict(x) for x in smesh.complete(self.setup.get("mesh"))["face_sizes"]]
        for fid in self.sel_faces:
            sig = sg.face_sig(self.geom, fid)
            old = next((x for x in sizes if x["face"] == sig), None)
            if old is not None:
                old["h"] = hf
            else:
                sizes.append({"face": sig, "h": hf})
        if self.try_face_sizes(sizes):
            self.say(f"Element size {format(l_out(hf), '.4g')} {UD()['L']} on {len(self.sel_faces)} face(s).")
            return True
        return False

    def remove_face_size(self):
        r = self.face_table.currentRow()
        sizes = [dict(x) for x in smesh.complete(self.setup.get("mesh"))["face_sizes"]]
        if not 0 <= r < len(sizes):
            self.say("Select a row of the list first.")
            return False
        del sizes[r]
        return self.try_face_sizes(sizes)

    def face_item_changed(self, it):
        if it.column() != 1:
            return
        sizes = [dict(x) for x in smesh.complete(self.setup.get("mesh"))["face_sizes"]]
        r = it.row()
        try:
            hf = l_in(float(it.text().strip().replace(",", ".")))
        except ValueError:
            self.say("The size must be a number.")
            QTimer.singleShot(0, self.fill_face_table)
            return
        if 0 <= r < len(sizes):
            sizes[r]["h"] = hf
            if not self.try_face_sizes(sizes):
                QTimer.singleShot(0, self.fill_face_table)

    def show_quality(self, qr, note=None):
        """The quality report of a mesh (solid_mesh.quality) under the Mesh button - only with the advanced options on.  `note`: why a hex-dominant mesh
        is tetrahedra only (or None)."""
        if qr is None or not self.cb_adv.isChecked():
            self.quality_lbl.setText("")
            self.quality_box.setVisible(False)
            return
        L = UD()["L"]
        n = qr["elements"]
        verdict = smesh.verdict(qr)
        colour = {"good": "#1b7f3b", "acceptable": "#a86a00", "poor": "#b3261e"}[verdict]
        mixed = qr.get("hexes", 0) > 0 or qr.get("pyramids", 0) > 0
        head = f"{n:,} elements, {qr['nodes']:,} nodes ({'quadratic' if qr['order'] == 2 else 'linear'})<br>"
        if mixed:
            head += (f"Hexahedra {qr['hexes']:,} ({100.0 * qr['hex_share']:.0f} % of the elements, {100.0 * qr['hex_volume_share']:.0f} % of the volume), "
                     f"tetrahedra {qr['tets']:,}, pyramids {qr['pyramids']:,}<br>")
        elif note:
            head += "Tetrahedra only: " + note + "<br>"
        tail = "Worst tetrahedron or pyramid" if mixed else "Worst element"
        self.quality_lbl.setText(
            head +
            f"Edge length: smallest {l_out(qr['edge_min']):.4g}, average {l_out(qr['edge_mean']):.4g}, largest {l_out(qr['edge_max']):.4g} {L}<br>"
            f"{tail}, radius ratio: {qr['ratio_min']:.3f} (1 = perfect; below 0.1 is poor)<br>"
            f"Angles between faces: smallest {qr['dihedral_min']:.0f}&deg;, largest {qr['dihedral_max']:.0f}&deg;<br>"
            f"Elements below 0.2: {qr['below_02']:,} ({100.0 * qr['below_02'] / max(n, 1):.1f} %)<br>"
            f"Overall: <b style='color:{colour}'>{verdict}</b>")
        self.quality_box.setVisible(True)

    @staticmethod
    def mesh_text(n_elements, n_nodes, order, h, counts=None):
        """One line about the mesh; `counts` = {"tets", "hexes", "pyramids"} when it has bricks."""
        kind = "quadratic" if order == 2 else "linear"
        if counts and (counts.get("hexes") or counts.get("pyramids")):
            what = (f"{n_elements:,} elements ({counts['hexes']:,} hexahedra, {counts['tets']:,} tetrahedra, {counts['pyramids']:,} pyramids)")
        else:
            what = f"{n_elements:,} tetrahedra"
        return f"{what}, {n_nodes:,} nodes ({kind}), element size {l_out(h):.4g} {UD()['L']}"

    def refresh_labels(self):
        """Every label that carries a unit, in the program's current units."""
        D = UD()
        for key, text in (("E", f"Young's modulus E ({D['S']})"), ("nu", "Poisson's ratio"), ("rho", f"Density ({D['rho']})"),
                          ("sy", f"Yield strength ({D['S']})"), ("su", f"Ultimate strength ({D['S']})")):
            self.mat_labels[key].setText(text)
        self.h_label.setText(f"Element size ({D['L']}, blank = auto)")
        self.hmin_label.setText(f"Minimum size ({D['L']})")
        self.e_probe.setPlaceholderText(f"x, y, z  ({D['L']})")
        for i, (key, name) in enumerate(FIELDS):
            unit = D["S"] if key == "vm" else (D["L"] if key.startswith("u") else None)
            self.cb_field.setItemText(i, name + (f" ({unit})" if unit else ""))
        self.update_mat_note()

    def units_changed(self, *_a):
        try:
            self.refresh_labels()
            self.put_material(self.setup["material"])
            self.e_h.setText(format(l_out(self.setup["h"]), ".8g") if self.setup.get("h") else "")
            self.put_mesh_options()
            if self.geom is not None:
                self.fill_faces()
                self.fill_splits()
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
        self.b_del_mat.setEnabled(sim_matdlg.can_delete(self.mat_combo.currentData()))
        self.update_mat_note()

    def library_entry(self, name):
        return next((x for x in self.library if x["name"] == name), None)

    def add_material(self):
        nm = sim_matdlg.add_material(self, self.library, unitctl.system(),
                                     {"E": self.e_E.text(), "nu": self.e_nu.text(), "sy": self.e_sy.text(), "su": self.e_su.text(), "eu": ""})
        if nm is not None:
            self.fill_materials(select=nm)
            self.material_picked()

    def delete_material(self):
        if sim_matdlg.delete_material(self, self.mat_combo.currentData(), self.library):
            self.fill_materials()
            self.material_picked()

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
        self.b_del_mat.setEnabled(sim_matdlg.can_delete(name))
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
        self.store_body_material(m)
        self.setup["h"] = l_in(num(self.e_h, "Element size")) if h else 0.0
        self.read_mesh_options(self.setup["h"])
        return self.setup

    def inputs_changed(self):
        try:
            self.read_inputs()
        except ValueError as ex:
            self.say(str(ex))
            return
        self.invalidate(mesh=True)

    def invalidate(self, mesh=False):
        had = self.result is not None
        self.anim_timer.stop()
        self.result = None
        if mesh:
            self.mesh_q = None
            self.show_quality(None)
        self.res_lbl.setText("The setup changed since the last solve: press Solve." if had else "No result yet.")
        self.view.clear_result()
        self.enable_buttons()
        if had and self.geom is not None and self.is_asm():                      # the screws' results and colours go with the result
            self.fill_screws()
            self.colour()

    def enable_buttons(self):
        have = self.geom is not None
        busy = self.job is not None
        self.b_import.setEnabled(self.project_ok() and not busy)
        self.b_refresh.setEnabled(self.source is not None and not busy)
        self.b_save.setEnabled(have)
        self.b_mesh.setEnabled(have and not busy)
        self.b_solve.setEnabled(have and not busy)
        self.b_cancel.setEnabled(busy)
        for b in (self.b_anim, self.b_play, self.b_stop):
            b.setEnabled(self.result is not None)
        self.b_study.setEnabled(have and not busy)
        if hasattr(self, "b_split"):
            self.preview_grid()

    # ------------------------------------------------------------------ the project
    def title(self):
        return os.path.basename(self.path.rstrip("/\\")) if self.path else "3D FEA"

    def project_ok(self):
        return bool(self.path) and sim_project.kind_of_folder(self.path) == "solid"

    def show_source(self):
        if not self.project_ok():
            self.src_lbl.setText("<b>3D FEA</b> - press <b>New project...</b>: the project is a folder (.gpv) with its own copy of the part or assembly.")
            return
        if self.source is None:
            self.src_lbl.setText(f"<b>3D FEA</b> project <b>{self.title()}</b> - press <b>Import source...</b> to copy a part or an assembly into it.")
            return
        what = "assembly" if self.src.get("type") == "asm" else "part"
        self.src_lbl.setText(f"<b>3D FEA</b> of the {what} <b>{self.src.get('name') or '?'}</b> (the copy in the project)")

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
            if hasattr(w, "asm"):
                out.append(("assembly - " + w.title(), w))
            elif getattr(w, "doc", None) is not None and hasattr(w.doc, "features"):
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
        lay.addWidget(QLabel("Copy this part or assembly into the project (an assembly is solved as fully bonded parts, or joined by screws):"))
        lst = QListWidget()
        tabs = self.open_tabs()
        for text, _w in tabs:
            lst.addItem(text)
        if tabs:
            lst.setCurrentRow(0)
        lay.addWidget(lst)
        pick = {"file": None}
        b_file = QPushButton("Browse for a .gpd or .gpa file...")
        lay.addWidget(b_file)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        lay.addWidget(bb)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)

        def browse():
            f, _ = QFileDialog.getOpenFileName(dlg, "Part or assembly to copy", os.path.dirname(self.src.get("path") or ""), "Part or assembly (*.gpd *.gpa)")
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
        if hasattr(w, "asm"):
            if not p:
                QMessageBox.information(self, "Import source", "Save the assembly once first: its parts are found from its file.")
                return False
            return self.do_import(p, w.asm.to_json(), name=os.path.splitext(os.path.basename(p))[0])
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
        try:
            fake = orig if orig else os.path.join(self.path, (name or "source") + ".gpd")
            m, missing_parts = sim_project.import_source(self.path, orig_path=fake, text=text, name=name)
            src = sim_source.open_source(sim_project.source_file(self.path, m))
        except (sim_project.ProjectError, sim_source.SourceError) as ex:
            QMessageBox.warning(self, "Import source", str(ex))
            return False
        self.source = src
        self.src = {"type": src.type, "path": orig, "name": m["source"]["name"]}
        self.setup["dims"] = {}
        self.setup["body_mats"] = {}
        self.cur_body = None
        self.hidden_bodies = set()
        ok = self.load_geometry(first=True)
        self.show_source()
        miss = ("  Not found, so left out: " + ", ".join(os.path.basename(x.replace("\\", "/")) for x in missing_parts) + ".") if missing_parts else ""
        if ok:
            self.say(f"Copied {m['source']['name']} into the project ({m['source']['file']})." + miss)
            self.save()
        elif miss:
            self.say("The assembly has no part with a solid." + miss)
        return ok

    def original_text(self):
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
        self.say("Copied the original again." + ("" if ok else " (There is no solid.)"))
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

    def load_geometry(self, first=False, keep_view=False):
        """(Re)analyses the solid of the source (with the dimension edits) and rematches the faces of the supports and loads."""
        asm = self.source.type == "asm"
        try:
            if asm:
                g = sasm.analyze_assembly(sasm.bodies_of_source(self.source), self.setup.get("bond_tol") or 0.0, self.setup.get("splits"))
            else:
                if not first:
                    self.apply_dims()
                elif self.setup["dims"]:
                    self.source.set_values(self.setup["dims"])
                g = sg.analyze(self.source.doc.solid, self.setup.get("splits"))
        except (sg.GeomError, sasm.AsmError) as ex:
            self.say(str(ex))
            return False
        except Exception as ex:
            self.say(f"The {'assembly' if asm else 'part'} could not be read: {ex}")
            return False
        self.geom = g
        self.sel_faces, self.sel_vertex = [], None
        self.mesh_q = None
        self.result = None
        mat = None if asm else self.source.doc.material
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
        for sp in self.setup.get("splits") or []:                       # remember the column direction that was used, so a rebuild keeps it
            pid = sg.match_face(g.get("orig") or g, sp["face"])
            if pid in g["split_of"] and not sp.get("u"):
                sp["u"] = list(g["split_of"][pid]["u"])
        self.fill_faces()
        self.fill_dims()
        self.fill_splits()
        self.show_asm()
        P, T, F = sg.display_mesh(g, self.hidden_bodies if asm else ())
        self.view.set_geometry(P, T, F, keep_camera=keep_view)
        self.view.set_lines("grid", sg.patch_outlines(g))
        self.view.set_lines("preview", [])
        self.set_geo_text()
        if g["notes"]:
            self.say(" ".join(g["notes"]))
        if asm and g["hints"]:
            self.say(g["hints"][0])
        self.refresh_lists()
        self.colour()
        self.enable_buttons()
        self.refresh_study_button()
        return True

    # ------------------------------------------------------------------ an assembly
    def is_asm(self):
        return self.geom is not None and bool(self.geom.get("bodies"))

    def show_asm(self):
        """Shows what only an assembly has (the bodies, the bond distance, what is bonded) and hides what only a part has (dimensions, face splits)."""
        on = self.is_asm()
        for w in self.part_only:
            w.setVisible(not on)
        for w in (self.asm_box, self.body_lbl, self.body_table):
            w.setVisible(on)
        if not on:
            self.cur_body = None
            self.hidden_bodies = set()
            return
        import html
        g = self.geom
        names = [b["name"] for b in g["bodies"]]
        k = l_out(1.0)
        contact = self.setup.get("joint") == "contact"
        if contact:
            lines = [f"Parts that touch within {l_out(g['tol']):.4g} {UD()['L']} of each other share a face (a joint). The joint is frictionless contact; "
                     "only the patches with a screw or bolt are bonded."]
            lines += [f"{html.escape(names[r['a']])} - {html.escape(names[r['b']])}: joint, area {r['area'] * k ** 2:.4g} {UD()['L']}2" for r in g["bonds"]]
        else:
            lines = [f"Fully bonded where faces are within {l_out(g['tol']):.4g} {UD()['L']} of each other."]
            lines += [f"{html.escape(names[r['a']])} - {html.escape(names[r['b']])}: bonded, area {r['area'] * k ** 2:.4g} {UD()['L']}2" for r in g["bonds"]]
        txt = "<br>".join(lines)
        bad = [html.escape(x) for x in g["hints"] + g["notes"]]
        if bad:
            txt += "<br>" + "<br>".join(f"<span style='color:#b05a00'>{x}</span>" for x in bad)
        self.asm_lbl.setText(txt)
        self.bond_unit.setText(UD()["L"])
        self.e_bond.setPlaceholderText(f"automatic ({l_out(g['tol']):.3g})")
        bt = self.setup.get("bond_tol") or 0.0
        self.e_bond.setText(format(l_out(bt), ".8g") if bt else "")
        self.fill_bodies()
        self.sync_joint()

    def bond_changed(self):
        t = self.e_bond.text().strip()
        try:
            v = l_in(float(t.replace(",", "."))) if t else 0.0
        except ValueError:
            self.say(f"Bond distance: '{t}' is not a number.")
            return
        if v < 0:
            self.say("The bond distance cannot be negative.")
            return
        if abs(v - float(self.setup.get("bond_tol") or 0.0)) < 1e-12 or not self.is_asm():
            return
        self.setup["bond_tol"] = v
        self.load_geometry(keep_view=True)

    def body_colour(self, i):
        return sv.BODY_COLOURS[i % len(sv.BODY_COLOURS)]

    def fill_bodies(self):
        t = self.body_table
        t.blockSignals(True)
        t.setRowCount(0)
        for i, b in enumerate(self.geom["bodies"]):
            t.insertRow(i)
            it = QTableWidgetItem(b["name"])
            c = self.body_colour(i)
            it.setBackground(QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255)))
            it.setForeground(QColor(20, 20, 20))
            t.setItem(i, 0, it)
            t.setItem(i, 1, QTableWidgetItem(""))
        self.fill_body_materials()
        t.blockSignals(False)
        keep = self.cur_body if self.cur_body is not None and self.cur_body < t.rowCount() else 0
        self.cur_body = None
        t.selectRow(keep)
        self.body_selected()

    def fill_body_materials(self):
        D = UD()
        for i, m in enumerate(sm.body_materials(self.geom, self.setup)):
            it = self.body_table.item(i, 1)
            if it is not None:
                it.setText(m.get("name") or f"E = {s_out(m['E']):.5g} {D['S']}, density {r_out(m['rho']):.5g}")

    def body_selected(self):
        if not self.is_asm():
            return
        rows = self.body_table.selectionModel().selectedRows() if self.body_table.selectionModel() is not None else []
        if not rows:
            return
        i = rows[0].row()
        self.cur_body = i
        m = sm.body_materials(self.geom, self.setup)[i]
        self.put_material(m)
        nm = m.get("name")
        self.select_material_name(nm if nm and self.library_entry(nm) else None)
        self.mat_note.setText(f"Material of {self.geom['bodies'][i]['name']}. " + self.mat_note.text())

    def store_body_material(self, m):
        """The numbers on the screen belong to the selected body of an assembly: keep them for it when they differ from the part's own."""
        if not self.is_asm() or self.cur_body is None or self.cur_body >= len(self.geom["bodies"]):
            return
        b = self.geom["bodies"][self.cur_body]
        base = b["material"]
        own = {k: float(m[k]) for k in ("E", "nu", "rho", "sy", "su")}
        mine = self.setup.setdefault("body_mats", {})
        if all(abs(own[k] - float(base[k])) <= 1e-9 * max(1.0, abs(float(base[k]))) for k in own):
            mine.pop(b["name"], None)
        else:
            own["name"] = self.mat_combo.currentData() or ""
            mine[b["name"]] = own
        self.fill_body_materials()

    # ------------------------------------------------------------------ the joint of an assembly: bonded, or screws and bolts with contact
    def joint_mode(self):
        return "contact" if self.is_asm() and self.setup.get("joint") == "contact" else "bonded"

    def sync_joint(self):
        """The joint box, the screw box and the lists show the joint of the setup."""
        for combo, key, default in ((self.joint_combo, "joint", "bonded"), (self.design_combo, "design", "ASD")):
            i = combo.findData(self.setup.get(key) or default)
            combo.blockSignals(True)
            combo.setCurrentIndex(max(i, 0))
            combo.blockSignals(False)
        self.screw_box.setVisible(self.joint_mode() == "contact")
        self.fill_show_list()
        self.fill_screws()

    def joint_picked(self):
        self.set_joint(self.joint_combo.currentData())

    def set_joint(self, mode):
        """'bonded' or 'contact' (screws and bolts).  The screws stay in the setup when it goes back to bonded; they are not used then."""
        mode = "contact" if mode == "contact" else "bonded"
        if not self.is_asm():
            return False
        if mode == (self.setup.get("joint") or "bonded"):
            return True
        self.setup["joint"] = mode
        if mode != "contact":
            self.hidden_bodies = set()                                      # fully bonded: there is nothing to see between the parts
        keep = [f for f in self.sel_faces if mode == "contact" or not self.geom["faces"][f].get("interface")]
        self.fill_faces()
        self.show_asm()
        self.redraw()
        self.select_faces(keep)
        self.after_edit()
        self.say("The parts touch freely now; only the screws and bolts join them. Cut the face between two parts into patches, select them and press Add screw."
                 if mode == "contact" else "The parts are fully bonded where their faces touch.")
        return True

    def design_picked(self):
        self.set_design(self.design_combo.currentData())

    def set_design(self, method):
        if method not in screw.METHODS:
            return False
        self.setup["design"] = method
        self.design_combo.blockSignals(True)
        self.design_combo.setCurrentIndex(max(self.design_combo.findData(method), 0))
        self.design_combo.blockSignals(False)
        self.screws_edited(True)
        return True

    def fill_show_list(self):
        t = self.show_list
        t.blockSignals(True)
        t.clear()
        if self.is_asm():
            for i, b in enumerate(self.geom["bodies"]):
                it = QListWidgetItem(b["name"])
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked if i in self.hidden_bodies else Qt.CheckState.Checked)
                c = self.body_colour(i)
                it.setBackground(QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255)))
                it.setForeground(QColor(20, 20, 20))
                t.addItem(it)
        t.blockSignals(False)

    def show_changed(self, _item=None):
        hid = {i for i in range(self.show_list.count()) if self.show_list.item(i).checkState() != Qt.CheckState.Checked}
        self.set_hidden_bodies(hid)

    def set_hidden_bodies(self, hid):
        """The parts that are not drawn (body numbers).  At least one part stays."""
        n = len(self.geom["bodies"]) if self.is_asm() else 0
        hid = {int(b) for b in hid if 0 <= int(b) < n}
        if n and len(hid) >= n:
            hid = set(range(1, n))
            self.say("At least one part stays on screen.")
        self.hidden_bodies = hid
        self.fill_show_list()
        self.redraw()

    def redraw(self):
        """Draws the geometry again (a part shown or hidden, the joint changed) from the same point of view."""
        if self.geom is None:
            return
        self.hidden_bodies = {b for b in self.hidden_bodies if b < len(self.geom.get("bodies") or [])}
        P, T, F = sg.display_mesh(self.geom, self.hidden_bodies if self.is_asm() else ())
        self.view.set_geometry(P, T, F, keep_camera=True)
        self.view.set_lines("grid", sg.patch_outlines(self.geom))
        self._prev_key = None
        self.view.set_lines("preview", [])
        self.colour()
        self.preview_grid()
        if self.result is not None:
            self.show_field()

    # ------------------------------------------------------------------ screws and bolts
    def screw_fids(self, sc):
        """The patch ids of a stored screw in the geometry now (a patch that is not found any more is left out).  Remembered for the geometry on show: a
        screw can have hundreds of patches and the colours ask again after every click."""
        cache = getattr(self, "_fid_cache", None)
        if cache is None or cache[0] is not self.geom:
            cache = self._fid_cache = (self.geom, {})
        key = json.dumps(sc.get("faces", []), sort_keys=True)
        out = cache[1].get(key)
        if out is None:
            out = []
            for sig in sc.get("faces", []):
                for i in sg.match_faces(self.geom, sig) or []:
                    if i not in out:
                        out.append(i)
            if len(cache[1]) > 200:
                cache[1].clear()
            cache[1][key] = out
        return list(out)

    def screw_of_patch(self):
        """{patch id: index of the screw on it}."""
        m = {}
        for i, sc in enumerate(self.setup.get("screws") or []):
            for f in self.screw_fids(sc):
                m[f] = i
        return m

    def screw_results(self):
        """{screw name: [the records of its patches]} of the result on screen."""
        out = {}
        for rec in (self.result or {}).get("screws") or []:
            out.setdefault(rec["screw"], []).append(rec)
        return out

    @staticmethod
    def screw_size_text(sc):
        c = screw.complete(sc)
        if c["kind"] == "bolt":
            return f"d {l_out(c['d']):.3g} {UD()['L']}"
        return f"d {l_out(c['d']):.3g} x {l_out(c['length']):.3g} {UD()['L']}"

    @staticmethod
    def screw_result_text(recs):
        if not recs:
            return ""
        bad = [r_ for r_ in recs if r_["status"] == "fails"]
        live = [r_ for r_ in recs if r_["worst"] is not None]
        worst = max(live, key=lambda r_: r_["worst"]) if live else None
        if bad:
            w = max(bad, key=lambda r_: r_["worst"])
            return f"{len(bad)} of {len(recs)} fail: {w['worst_name']} {w['worst']:.2f}"
        if any(r_["status"] == "incomplete" for r_ in recs):
            return (f"{worst['worst']:.2f} so far, " if worst else "") + "some checks need numbers"
        return f"all ok, worst {worst['worst']:.2f}" if worst else "ok"

    def fill_screws(self):
        t = self.screw_table
        t.blockSignals(True)
        keep = t.currentRow()
        t.setRowCount(0)
        if self.geom is not None and self.is_asm():
            res = self.screw_results()
            for i, sc in enumerate(self.setup.get("screws") or []):
                nm = sm.name_of("Screw", i, sc)
                cells = [nm, screw.KINDS.get(sc.get("kind", "screw"), "Screw").split(" (")[0], self.screw_size_text(sc), str(len(self.screw_fids(sc))),
                         self.screw_result_text(res.get(nm))]
                t.insertRow(i)
                for c, text in enumerate(cells):
                    it = QTableWidgetItem(text)
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    t.setItem(i, c, it)
            if 0 <= keep < t.rowCount():
                t.selectRow(keep)
        t.blockSignals(False)
        for b in (self.b_edit_screw, self.b_del_screw):
            b.setEnabled(t.rowCount() > 0)

    def screw_row_selected(self):
        r = self.screw_table.currentRow()
        scs = self.setup.get("screws") or []
        if self.geom is not None and 0 <= r < len(scs):
            self.select_faces(self.screw_fids(scs[r]))

    def add_screws(self, values=None, fids=None):
        """Puts the same screw or bolt on every selected patch.  `values` (the numbers of solid_screw.default_screw in mm / N / MPa, with "name" and "kind")
        skips the window that asks for them."""
        if not self.is_asm():
            self.say("Screws and bolts join the parts of an assembly: import an assembly first.")
            return False
        if self.joint_mode() != "contact":
            self.say("Choose the joint 'Screws and bolts' first: with the parts fully bonded there is nothing for a screw to join.")
            return False
        fids = sorted(set(self.sel_faces if fids is None else fids))
        if not fids:
            self.say("Select the patch(es) first: faces between two parts (untick a part under Show parts to see them, or use the Faces list).")
            return False
        faces = self.geom["faces"]
        bad = [f for f in fids if not faces[f].get("interface") or len(faces[f].get("bodies", ())) < 2]
        if bad:
            self.say(f"A screw goes on a face between two parts. {self.face_label(bad[0])} is not one: select joint faces only.")
            return False
        taken = self.screw_of_patch()
        clash = [f for f in fids if f in taken]
        if clash:
            self.say(f"{self.face_label(clash[0])} already has a screw ({sm.name_of('Screw', taken[clash[0]], self.setup['screws'][taken[clash[0]]])}): "
                     "remove it first, or select other patches.")
            return False
        if values is None:
            values = self.ask_screw(None, len(fids))
            if values is None:
                return False
        item = screw.complete(values)
        scs = self.setup.setdefault("screws", [])
        base = "Bolt" if item["kind"] == "bolt" else "Screw"
        n = 1
        names = {sm.name_of("Screw", i, x) for i, x in enumerate(scs)}
        nm = (values.get("name") or "").strip()
        while not nm or nm in names:
            nm = f"{base} {n}" if not (values.get("name") or "").strip() else f"{values['name'].strip()} ({n})"
            n += 1
        item["name"] = nm
        item["faces"] = [sg.face_sig(self.geom, f) for f in fids]
        scs.append(item)
        self.after_edit()
        self.say(f"{nm}: {len(fids)} patch{'es' if len(fids) != 1 else ''}. Solve to read the force through each and see what fails. "
                 "(Untick a part under Show parts to see the screws inside the joint.)")
        return True

    def edit_screw(self, row=None, values=None):
        """Changes the numbers of the selected screw (all its patches).  `values` skips the window."""
        r = self.screw_table.currentRow() if row is None else row
        scs = self.setup.get("screws") or []
        if not (0 <= r < len(scs)):
            self.say("Select a screw in the list first.")
            return False
        cur = scs[r]
        if values is None:
            values = self.ask_screw(cur, len(self.screw_fids(cur)))
            if values is None:
                return False
        new = screw.complete(dict(values, faces=cur["faces"]))
        new["name"] = (values.get("name") or "").strip() or sm.name_of("Screw", r, cur)
        scs[r] = new
        self.screws_edited(True)
        return True

    def remove_screw(self, row=None):
        r = self.screw_table.currentRow() if row is None else row
        scs = self.setup.get("screws") or []
        if not (0 <= r < len(scs)):
            self.say("Select a screw in the list first.")
            return False
        del scs[r]
        self.screws_edited(False)
        return True

    def screws_edited(self, same_patches):
        """The screws of the setup changed.  When only their numbers (or the design method) changed, a result on screen is checked again from the forces it
        has; a change of the patches asks for a new solution."""
        if same_patches and self.result is not None and self.result.get("patch_forces") and self.geom is not None:
            try:
                r = sm.resolve(self.geom, self.setup)
            except fem.FemError:
                r = None
            if r is not None and sm.recheck(self.geom, r, self.result):
                self.fill_screws()
                self.describe()
                self.colour()
                self.say("The checks are made again with the new numbers (the forces are those of the last solution).")
                return
        self.after_edit()

    def ask_screw(self, cur=None, n_patches=1):
        """The window for a screw or bolt: -> its numbers (mm, N, MPa) with "kind", "name" and "head", or None."""
        c = screw.complete(cur) if cur else screw.default_screw("screw")
        D = UD()
        dlg = QDialog(self)
        dlg.setWindowTitle("Screw or bolt" + (f" on {n_patches} patches" if n_patches != 1 else ""))
        form = QFormLayout(dlg)
        kind = QComboBox()
        for k, text in screw.KINDS.items():
            kind.addItem(text, k)
        kind.setCurrentIndex(max(kind.findData(c["kind"]), 0))
        form.addRow("Type", kind)
        name = QLineEdit((cur or {}).get("name", ""))
        name.setPlaceholderText("automatic")
        form.addRow("Name", name)
        units = {"L": (D["L"], l_out, l_in), "F": (D["F"], f_out, f_in), "S": (D["S"], s_out, s_in), "N": ("", float, float)}
        specs = [("d", "Diameter", "L", ("screw", "bolt")), ("length", "Length of the screw", "L", ("screw",)),
                 ("thread", "Threaded length (0 = all of it)", "L", ("screw",)), ("dh", "Head diameter", "L", ("screw",)),
                 ("dw", "Washer diameter (0 = no washer)", "L", ("screw",)), ("tw", "Washer thickness", "L", ("screw",)),
                 ("Pnvs", "Shear strength of the screw, from its maker (0 = not given)", "F", ("screw",)),
                 ("Pnts", "Tension strength of the screw, from its maker (0 = not given)", "F", ("screw",)),
                 ("Fnv", "Nominal shear stress of the bolt (Table J3.4-1; 0 = not given)", "S", ("bolt",)),
                 ("Fnt", "Nominal tension stress of the bolt (Table J3.4-1; 0 = not given)", "S", ("bolt",)),
                 ("planes", "Shear planes through the bolt", "N", ("bolt",))]
        edits = {}
        for key, label, q, kinds in specs:
            u = units[q][0]
            e = QLineEdit()
            edits[key] = (e, q, kinds)
            form.addRow(f"{label}" + (f" ({u})" if u else ""), e)
        head = QComboBox()
        for k, text in screw.HEADS.items():
            head.addItem(text, k)
        head.setToolTip("Which part has the head (and the washer): the thinner one by default. The other part holds the threads.")
        form.addRow("Head and washer", head)

        def fill(vals):
            for key, (e, q, _k) in edits.items():
                v = float(vals.get(key) or 0.0)
                e.setText(format(int(v) if q == "N" else units[q][1](v), ".8g"))
            head.setCurrentIndex(max(head.findData(vals.get("head", "thin")), 0))

        def show():
            k = kind.currentData()
            for key, (e, _q, kinds) in edits.items():
                e.setVisible(k in kinds)
                form.labelForField(e).setVisible(k in kinds)
            head.setVisible(k == "screw")
            form.labelForField(head).setVisible(k == "screw")
        state = {"kind": c["kind"]}

        def kind_changed(_i=None):
            if kind.currentData() != state["kind"]:
                state["kind"] = kind.currentData()
                fill(screw.default_screw(state["kind"]))                     # another type: the usual numbers of that type
            show()
        fill(c)
        show()
        kind.currentIndexChanged.connect(kind_changed)
        form.addRow(QLabel("The same screw goes on every selected patch, at its centre. No hole is modelled: the patch is bonded and the force through it is read.\n"
                           "The strengths of the screw itself come from its maker; leave them 0 to check the sheets only."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return None
        k = kind.currentData()
        out = {"kind": k, "name": name.text().strip(), "head": head.currentData()}
        try:
            for key, (e, q, kinds) in edits.items():
                if k in kinds:
                    v = float(e.text().replace(",", ".")) if e.text().strip() else 0.0
                    out[key] = int(v) if q == "N" else units[q][2](v)
        except ValueError:
            QMessageBox.warning(self, "Screw or bolt", "Type numbers.")
            return None
        if out["d"] <= 0 or (k == "screw" and out["length"] <= 0) or (k == "bolt" and out.get("planes", 1) < 1) or any(v < 0 for key, v in out.items() if isinstance(v, (int, float))):
            QMessageBox.warning(self, "Screw or bolt", "The diameter and the length must be positive, the other numbers zero or more, and a bolt has at least one shear plane.")
            return None
        return out

    def update_markers(self):
        """A round marker at the centre of every screw patch, teal; after a solution green (ok), orange (needs numbers) or red (fails), carried along with the
        deformed shape."""
        pts, cols = [], []
        if self.geom is not None and self.joint_mode() == "contact" and (self.setup.get("screws") or []):
            status = {rec["fid"]: rec["status"] for rec in (self.result or {}).get("screws") or []}
            r = self.result
            sc_ = self.scale_value() if r is not None else 0.0
            for sc in self.setup["screws"]:
                for f in self.screw_fids(sc):
                    p = np.asarray(self.geom["faces"][f]["center"], float)
                    if r is not None and sc_:
                        i = int(np.argmin(np.linalg.norm(r["nodes"] - p, axis=1)))
                        p = p + sc_ * r["u"][i]
                    pts.append(p)
                    cols.append(tuple(0.55 * x for x in sv.STATUS_RGB.get(status.get(f), sv.STATUS_RGB[None])))      # darker than the patch under it
        self.view.set_markers(pts, cols, size=22)

    def set_geo_text(self):
        g = self.geom
        if g is None:
            return
        bb = g["bbox"]
        L = UD()["L"]
        k = l_out(1.0)
        nf = len((g.get("orig") or g)["faces"])
        extra = f" ({len(g['faces'])} with the patches)" if g.get("orig") else ""
        if g.get("bodies"):
            nf = sum(1 for f in g["faces"] if not f["interface"])
            extra = f", {len(g['bodies'])} bodies"
        self.geo_lbl.setText(f"{self.src.get('name') or 'part'}: {nf} faces{extra}, volume {g['volume'] * k ** 3:.5g} {L}3, size "
                             f"{(bb[1][0] - bb[0][0]) * k:.4g} x {(bb[1][1] - bb[0][1]) * k:.4g} x {(bb[1][2] - bb[0][2]) * k:.4g} {L}")

    def fill_faces(self):
        self.faces.blockSignals(True)
        self.faces.clear()
        for f in self.geom["faces"]:
            n = f["normal"]
            self.faces.addItem(f"{self.face_label(f['id'])}: {f['kind']}, area {f['area'] * l_out(1.0) ** 2:.4g} {UD()['L']}2, "
                               f"normal ({n[0]:.2f}, {n[1]:.2f}, {n[2]:.2f})")
            if f.get("interface") and self.setup.get("joint") != "contact":       # fully bonded: a face between two bodies is inside, nothing to pick there
                self.faces.item(f["id"]).setHidden(True)
        self.faces.blockSignals(False)

    def face_label(self, fid):
        """'Face 3' - or, for a patch of a split face, 'Face 3, column 2 row 1' (the number of the face in the unsplit part)."""
        f = self.geom["faces"][fid]
        p = f.get("parent")
        n = (p if p is not None else fid) + 1
        if self.geom.get("bodies"):
            nm = self.geom["bodies"]
            cell = f", column {f['cell'][0] + 1} row {f['cell'][1] + 1}" if f.get("cell") is not None else ""
            if f.get("interface"):
                return f"{' - '.join(nm[b]['name'] for b in f['bodies'][:2])}, joint face {n}{cell}"
            return f"{nm[f['body']]['name']}, face {n}{cell}"
        if f.get("cell") is not None:
            return f"Face {n}, column {f['cell'][0] + 1} row {f['cell'][1] + 1}"
        return f"Face {n}"

    def fill_dims(self):
        self.dims.blockSignals(True)
        self.dims.setRowCount(0)
        self.dim_keys = []
        for key, label, now in ([] if self.source.type == "asm" else self.source.doc.cfg_candidates()):
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
        self.preview_grid()

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
        self.preview_grid()
        self.say(f"Picked {self.face_label(fid).lower()}" + (f" (nearest vertex {self.sel_vertex + 1})" if self.sel_vertex is not None else ""))

    def select_faces(self, fids):
        """Selects faces without the mouse (also used by the tests)."""
        self.sel_faces = sorted(set(fids))
        self.faces.blockSignals(True)
        self.faces.clearSelection()
        for f in self.sel_faces:
            self.faces.item(f).setSelected(True)
        self.faces.blockSignals(False)
        self.colour()
        self.preview_grid()

    # ------------------------------------------------------------------ splitting a flat face into patches
    def split_target(self):
        """(face id, why not) of the one face the Split / Unsplit buttons work on: the selected face (or a patch of it)."""
        if self.geom is None:
            return None, "Import a part first."
        parents = {self.geom["faces"][f].get("parent") for f in self.sel_faces}
        if len(self.sel_faces) == 0:
            return None, "Select the flat face to split first."
        if len(parents) != 1:
            return None, "Select one face (or the patches of one face) to split."
        return self.sel_faces[0], None

    def preview_grid(self, *_a):
        """Shows the grid the Split button would cut on the selected face, and enables / disables the buttons."""
        segs = []
        fid, _why = self.split_target() if self.geom is not None else (None, None)
        split_now = False
        key = None
        if fid is not None:
            f = self.geom["faces"][fid]
            split_now = f.get("cell") is not None
            if f["kind"] == "plane" and not split_now:
                key = (id(self.geom), fid, self.sp_cols.value(), self.sp_rows.value())
        if key != getattr(self, "_prev_key", None):
            self._prev_key = key
            if key is not None:
                try:
                    segs = sg.grid_lines(self.geom, fid, key[2], key[3])
                except Exception:                                        # noqa: BLE001 - a preview never stops the program
                    segs = []
            self.view.set_lines("preview", segs, color=(0.95, 0.5, 0.05), width=3.0)
        have = fid is not None and self.job is None
        self.b_split.setEnabled(have)
        self.b_unsplit.setEnabled(have and split_now)
        self.b_setsize.setEnabled(have and split_now)
        self.b_even.setEnabled(self.cur_split is not None and self.job is None)
        self.sync_splits()

    def split_selected(self, cols=None, rows=None, confirm=True):
        """Cuts the selected flat face into cols x rows patches (the numbers in the boxes by default).  Conditions on the whole face stay (they now
        apply to all its patches); conditions on patches of the face's earlier split are removed, after asking."""
        cols = self.sp_cols.value() if cols is None else int(cols)
        rows = self.sp_rows.value() if rows is None else int(rows)
        fid, why = self.split_target()
        if fid is None:
            self.say(why)
            return False
        f = self.geom["faces"][fid]
        if f["kind"] != "plane":
            self.say("Only flat faces can be split for now.")
            return False
        if cols * rows < 2:
            self.say("Choose 2 or more columns or rows (or press Unsplit to put a split face back together).")
            return False
        return self.apply_split(fid, cols, rows, confirm)

    def unsplit_selected(self, confirm=True):
        fid, why = self.split_target()
        if fid is None:
            self.say(why)
            return False
        if sm.split_of_face(self.setup, self.geom, fid)[1] is None:
            self.say("That face is not split.")
            return False
        return self.apply_split(fid, 1, 1, confirm)

    def apply_split(self, fid, cols, rows, confirm=True):
        o = self.geom.get("orig") or self.geom
        pid = self.geom["faces"][fid]["parent"]
        i, rec = sm.split_of_face(self.setup, self.geom, fid)
        if rec is not None and rec["cols"] == cols and rec["rows"] == rows:
            self.say(f"That face is already split into {cols} x {rows}.")
            return False
        if confirm and cols * rows > sg.WARN_PATCHES:
            r = QMessageBox.question(self, "Split face", f"{cols} x {rows} makes {cols * rows:,} patches. That can take a long time to cut and to mesh. Continue?")
            if r != QMessageBox.StandardButton.Yes:
                return False
        lost = sm.patch_conditions(self.setup, self.geom, fid)
        if lost and confirm:
            r = QMessageBox.question(self, "Split face", ("Changing the split removes the supports and loads that are on single patches of this face:\n\n  "
                                     + "\n  ".join(lost) + "\n\nSupports and loads on the whole face stay. Continue?"))
            if r != QMessageBox.StandardButton.Yes:
                return False
        before = json.loads(json.dumps(self.setup))
        sm.set_split(self.setup, self.geom, fid, cols, rows)
        keep_sel = self.sp_cols.value(), self.sp_rows.value()
        if not self.load_geometry(keep_view=True):
            self.setup = before
            return False
        if cols * rows > 1 and pid not in self.geom["split_of"]:                 # the cut did not work: back to what it was
            why = " ".join(self.geom["notes"]) or "The face could not be split here."
            self.setup = before
            self.load_geometry(keep_view=True)
            self.say(why)
            return False
        self.cur_split = pid if cols * rows > 1 else None
        self.fill_splits()
        self.sp_cols.blockSignals(True)
        self.sp_rows.blockSignals(True)
        self.sp_cols.setValue(keep_sel[0])
        self.sp_rows.setValue(keep_sel[1])
        self.sp_cols.blockSignals(False)
        self.sp_rows.blockSignals(False)
        self.after_edit()
        n = pid + 1
        if cols * rows > 1:
            self.say(f"Face {n} is split into {cols} x {rows} patches. Click a patch to select it (Ctrl/Shift for several), then add a support or a load.")
        else:
            self.say(f"Face {n} is one face again.")
        self.preview_grid()
        return True

    # ------------------------------------------------------------------ the sizes of the columns and rows of a split face
    def fill_splits(self):
        """The list of the split faces and the table of the sizes of the one on show (the program's current length unit)."""
        if not hasattr(self, "split_list"):
            return
        so = (self.geom or {}).get("split_of") or {}
        self.split_list.blockSignals(True)
        self.split_list.clear()
        for pid in sorted(so):
            sp = so[pid]
            it = QListWidgetItem(f"Face {pid + 1}: {sp['cols']} column{'s' if sp['cols'] != 1 else ''} x {sp['rows']} row{'s' if sp['rows'] != 1 else ''}")
            it.setData(Qt.ItemDataRole.UserRole, pid)
            self.split_list.addItem(it)
        if self.cur_split not in so:
            self.cur_split = None
        for i in range(self.split_list.count()):
            if self.split_list.item(i).data(Qt.ItemDataRole.UserRole) == self.cur_split:
                self.split_list.item(i).setSelected(True)
        self.split_list.blockSignals(False)
        self.fill_sizes()

    def split_record(self, pid):
        o = (self.geom.get("orig") or self.geom)
        for s in self.setup.get("splits") or []:
            if sg.match_face(o, s["face"]) == pid:
                return s
        return None

    def fill_sizes(self):
        """The table: one line per column and per row with its size (solved for the free ones) and whether it is fixed."""
        tb = self.sz_table
        tb.blockSignals(True)
        tb.setRowCount(0)
        pid = self.cur_split
        so = (self.geom or {}).get("split_of") or {}
        rec = self.split_record(pid) if pid in so else None
        tb.setHorizontalHeaderLabels(["Strip", f"Size ({UD()['L']})", "Fixed"])
        if rec is not None:
            info = so[pid]
            for kind, word, sizes, fixed in (("c", "Column", info["col_sizes"], rec.get("col_sizes") or []), ("r", "Row", info["row_sizes"], rec.get("row_sizes") or [])):
                for i, sz in enumerate(sizes):
                    fx = fixed[i] if i < len(fixed) else None
                    r = tb.rowCount()
                    tb.insertRow(r)
                    a = QTableWidgetItem(f"{word} {i + 1}")
                    a.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    b_ = QTableWidgetItem(format(l_out(sz), ".6g"))
                    c = QTableWidgetItem()
                    only = len(sizes) == 1                                   # one column (row) is the whole face: nothing to set
                    b_.setFlags((Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable) if not only else Qt.ItemFlag.ItemIsEnabled)
                    c.setFlags((Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable) if not only else Qt.ItemFlag.ItemIsEnabled)
                    c.setCheckState(Qt.CheckState.Checked if fx is not None else Qt.CheckState.Unchecked)
                    if fx is not None:
                        f = b_.font()
                        f.setBold(True)
                        b_.setFont(f)
                    for it in (a, b_, c):
                        it.setData(Qt.ItemDataRole.UserRole, (kind, i))
                    tb.setItem(r, 0, a)
                    tb.setItem(r, 1, b_)
                    tb.setItem(r, 2, c)
        tb.blockSignals(False)
        self.b_even.setEnabled(rec is not None and self.job is None)

    def split_list_changed(self):
        it = self.split_list.selectedItems()
        self.cur_split = it[0].data(Qt.ItemDataRole.UserRole) if it else None
        self.fill_sizes()
        if self.cur_split is not None and self.geom is not None:           # its patches are selected in the view
            ids = [f["id"] for f in self.geom["faces"] if f.get("parent") == self.cur_split and f.get("cell") is not None]
            self._syncing = True
            try:
                self.select_faces(ids)
            finally:
                self._syncing = False

    def sync_splits(self):
        """The face selection points at a split face: that one is shown in the list and the table."""
        if getattr(self, "_syncing", False) or self.geom is None or not hasattr(self, "split_list"):
            return
        ps = {self.geom["faces"][f].get("parent") for f in self.sel_faces if self.geom["faces"][f].get("cell") is not None}
        if len(ps) == 1:
            pid = next(iter(ps))
            if pid != self.cur_split:
                self.cur_split = pid
                self.split_list.blockSignals(True)
                self.split_list.clearSelection()
                for i in range(self.split_list.count()):
                    if self.split_list.item(i).data(Qt.ItemDataRole.UserRole) == pid:
                        self.split_list.item(i).setSelected(True)
                self.split_list.blockSignals(False)
                self.fill_sizes()

    def size_item_changed(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        pid = self.cur_split
        rec = self.split_record(pid) if pid is not None else None
        if data is None or rec is None:
            return
        kind, i = data
        key = "col_sizes" if kind == "c" else "row_sizes"
        sizes = list(rec.get(key) or [None] * (rec["cols"] if kind == "c" else rec["rows"]))
        now = self.geom["split_of"][pid]["col_sizes" if kind == "c" else "row_sizes"][i]
        if item.column() == 1:
            text = item.text().strip().replace(",", ".")
            if text == "" or text.lower() in ("even", "free", "-"):
                sizes[i] = None
            else:
                try:
                    x = float(format(l_in(float(text)), ".12g"))                  # no unit-conversion noise (2.25 stays 2.25)
                except ValueError:
                    self.say(f"'{item.text()}' is not a number.")
                    self.fill_sizes()
                    return
                sizes[i] = x
        elif item.column() == 2:
            sizes[i] = now if item.checkState() == Qt.CheckState.Checked else None
        else:
            return
        cs = list(rec.get("col_sizes") or [None] * rec["cols"])
        rs = list(rec.get("row_sizes") or [None] * rec["rows"])
        if kind == "c":
            cs = sizes
        else:
            rs = sizes
        self.apply_sizes(pid, cs, rs)

    def apply_sizes(self, pid, cs, rs):
        """Sets the fixed sizes of the split of face `pid` (the others are free), cuts again and shows the solved sizes.  The patches keep their numbers, so
        the supports and loads on them stay."""
        fid = next((f["id"] for f in self.geom["faces"] if f.get("parent") == pid and f.get("cell") is not None), None)
        if fid is None:
            return False
        before = json.loads(json.dumps(self.setup))
        keep = {(self.geom["faces"][f].get("parent"), self.geom["faces"][f].get("cell")) for f in self.sel_faces}
        try:
            sm.set_sizes(self.setup, self.geom, fid, cs, rs)
        except sg.GeomError as ex:
            self.setup = before
            self.say(str(ex))
            self.fill_sizes()
            return False
        if not self.load_geometry(keep_view=True) or pid not in self.geom["split_of"]:
            why = " ".join(self.geom["notes"]) if self.geom is not None and self.geom.get("notes") else "The sizes could not be applied."
            self.setup = before
            self.load_geometry(keep_view=True)
            self.say(why)
            return False
        self.cur_split = pid
        self.fill_splits()
        ids = [f["id"] for f in self.geom["faces"] if (f.get("parent"), f.get("cell")) in keep]
        self._syncing = True
        try:
            self.select_faces(ids)
        finally:
            self._syncing = False
        self.after_edit()
        info = self.geom["split_of"][pid]
        self.say(f"Face {pid + 1}: columns " + ", ".join(format(l_out(x), ".5g") for x in info["col_sizes"][:6]) + (" ..." if info["cols"] > 6 else "")
                 + f"; rows " + ", ".join(format(l_out(x), ".5g") for x in info["row_sizes"][:6]) + (" ..." if info["rows"] > 6 else "") + f" ({UD()['L']}).")
        return True

    def even_sizes(self):
        if self.cur_split is None or self.geom is None:
            self.say("Click a split face in the list first.")
            return False
        rec = self.split_record(self.cur_split)
        if rec is None:
            return False
        return self.apply_sizes(self.cur_split, [None] * rec["cols"], [None] * rec["rows"])

    def set_size_dialog(self, width=None, height=None, ask=True):
        """Sets the width of the column and the height of the row of the selected patch (a blank box = free).  width / height (in the program's unit,
        None = leave) skip the window (used by the tests)."""
        fid, why = self.split_target()
        if fid is None or self.geom["faces"][fid].get("cell") is None:
            self.say("Select a patch of a split face first.")
            return False
        f = self.geom["faces"][fid]
        pid, (ci, ri) = f["parent"], f["cell"]
        rec = self.split_record(pid)
        info = self.geom["split_of"][pid]
        cs = list(rec.get("col_sizes") or [None] * rec["cols"])
        rs = list(rec.get("row_sizes") or [None] * rec["rows"])
        if ask:
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Size of {self.face_label(fid)}")
            form = QFormLayout(dlg)
            edits = {}
            for key, label, arr, idx, n, solved in (("w", f"Width of column {ci + 1} ({UD()['L']})", cs, ci, rec["cols"], info["col_sizes"]),
                                                    ("h", f"Height of row {ri + 1} ({UD()['L']})", rs, ri, rec["rows"], info["row_sizes"])):
                e = QLineEdit(format(l_out(arr[idx]), ".8g") if arr[idx] is not None else "")
                e.setPlaceholderText(f"free ({l_out(solved[idx]):.6g})")
                if n == 1:
                    e.setEnabled(False)
                    e.setPlaceholderText("the whole face")
                form.addRow(label, e)
                edits[key] = e
            form.addRow(QLabel("Leave a box blank to let that strip take its share of what is left."))
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            form.addRow(bb)
            if not dlg.exec():
                return False
            try:
                vals = {k: (None if e.text().strip() == "" else float(e.text().replace(",", "."))) for k, e in edits.items() if e.isEnabled()}
            except ValueError:
                QMessageBox.warning(self, "Size", "Type numbers.")
                return False
            width, height = vals.get("w", "keep"), vals.get("h", "keep")
        if width != "keep" and rec["cols"] > 1 and (ask or width is not None):
            cs[ci] = None if width is None else float(format(l_in(width), ".12g"))
        if height != "keep" and rec["rows"] > 1 and (ask or height is not None):
            rs[ri] = None if height is None else float(format(l_in(height), ".12g"))
        return self.apply_sizes(pid, cs, rs)

    def colour(self):
        if self.geom is None:
            return
        cols = {}
        if self.is_asm():
            cols = {f["id"]: self.body_colour(f["body"]) for f in self.geom["faces"] if not f["interface"]}
            if self.joint_mode() == "contact":
                cols.update({f["id"]: sv.JOINT for f in self.geom["faces"] if f["interface"]})
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
        if self.joint_mode() == "contact":
            status = {rec["fid"]: rec["status"] for rec in (self.result or {}).get("screws") or []}
            for sc in self.setup.get("screws") or []:
                for f in self.screw_fids(sc):
                    cols[f] = sv.STATUS_RGB.get(status.get(f), sv.SCREW) if status.get(f) else sv.SCREW
        for f in self.sel_faces:
            cols[f] = sv.PICK
        self.view.colour_faces(cols)
        self.update_markers()

    SUPPORT_TYPES = {"fixed": "Fixed", "slide": "One direction (normal)", "bolt": "Bolt / pin hole"}

    def refresh_lists(self):
        self.sup_list.clear()
        for i, s in enumerate(self.setup["supports"]):
            self.sup_list.addItem(f"{sm.name_of('Support', i, s)}: {s['mode']} on {len(s['faces'])} face(s)")
        self.load_list.clear()
        for i, l in enumerate(self.setup["loads"]):
            self.load_list.addItem(f"{sm.name_of('Load', i, l)}: {self.load_text(l)}")
        t = self.cond_table
        t.blockSignals(True)
        t.setRowCount(0)
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        rows = [(sm.name_of("Support", i, s), self.SUPPORT_TYPES.get(s["mode"], s["mode"]), f"{len(s['faces'])} face(s)", "") for i, s in enumerate(self.setup["supports"])]
        rows += [(sm.name_of("Load", i, l),) + self.load_cells(l) for i, l in enumerate(self.setup["loads"])]
        for r, cells in enumerate(rows):
            t.insertRow(r)
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setFlags(ro | Qt.ItemFlag.ItemIsEditable if c == 0 else ro)
                t.setItem(r, c, it)
        t.blockSignals(False)
        self.fill_face_table()
        self.fill_screws()

    @staticmethod
    def load_cells(l):
        """(type, applied to, value) of a load for the conditions table."""
        D = UD()
        k = l["kind"]
        if k == "force":
            return "Force", f"{len(l['faces'])} face(s)", f"({', '.join(format(f_out(x), '.5g') for x in l['f'])}) {D['F']}"
        if k == "pressure":
            return "Pressure", f"{len(l['faces'])} face(s)", f"{s_out(l['p']):.5g} {D['S']}"
        if k == "point":
            return ("Force at vertex", "1 vertex", f"({', '.join(format(f_out(x), '.5g') for x in l['f'])}) {D['F']}")
        return "Gravity", "whole part", f"{l['g']:g} m/s2 along {tuple(l['dir'])}"

    def cond_ref(self, r):
        """Table row -> (key in the setup, index): the supports come first, then the loads."""
        n = len(self.setup["supports"])
        if 0 <= r < n:
            return "supports", r
        if n <= r < n + len(self.setup["loads"]):
            return "loads", r - n
        return None, -1

    def cond_item_changed(self, it):
        if it.column() != 0:
            return
        key, i = self.cond_ref(it.row())
        if key is None:
            return
        item = self.setup[key][i]
        default = sm.name_of("Support" if key == "supports" else "Load", i)
        text = it.text().strip()
        if text and text != default:
            item["name"] = text
        else:
            item.pop("name", None)
        self.refresh_lists()

    def cond_double_clicked(self, r, c):
        key, i = self.cond_ref(r)
        if key == "loads" and c != 0:
            QTimer.singleShot(0, lambda: self.edit_load(i))

    def edit_condition(self):
        """Edit selected: a load opens its numbers again; a support lets you rename it."""
        r = self.cond_table.currentRow()
        key, i = self.cond_ref(r)
        if key is None:
            self.say("Select a row of the list first.")
            return False
        if key == "loads":
            return self.edit_load(i)
        it = self.cond_table.item(r, 0)
        self.cond_table.setCurrentItem(it)
        self.cond_table.editItem(it)
        return True

    def remove_condition(self):
        key, i = self.cond_ref(self.cond_table.currentRow())
        if key is None:
            self.say("Select a row of the list first.")
            return False
        del self.setup[key][i]
        self.after_edit()
        return True

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
        if any(self.geom["faces"][f].get("interface") for f in fids):
            self.say("A face between two parts is inside the assembly: put the support on an outside face. (Screws go on those faces: Add screw.)")
            return False
        mode = mode or "fixed"
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
        if kind in ("force", "pressure") and any(self.geom["faces"][f].get("interface") for f in fids):
            self.say("A face between two parts is inside the assembly: put the load on an outside face.")
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
        return sm.check_ready(self.setup, self.geom)

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
        try:
            opts = sm.resolve(g, self.setup)["mesh"] if self.joint_mode() == "contact" else smesh.resolve(g, self.setup, h)     # screws: finer on the patches
        except fem.FemError as ex:
            self.say(str(ex))
            return False

        def work(progress, cancel):
            return sm.get_mesh(g, h, self.cache, cancel, progress, opts)

        def done(q):
            self.mesh_q = q
            ql = q.get("quality") or {}
            self.mesh_lbl.setText(self.mesh_text(ql.get("elements", len(q["tets"])), len(q["nodes"]), q["order"], h, ql))
            self.show_quality(q.get("quality"), q.get("hexdom_note"))
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
            self.mesh_q = self.cache.get(sm.mesh_key(g, res["h"], res.get("mesh_opts")), self.mesh_q)
            self.mesh_lbl.setText(self.mesh_text(res.get("n_elements", res["n_tets"]), res["n_nodes"], res["order"], res["h"], res.get("counts")))
            self.show_quality(res.get("quality"), res.get("hexdom_note"))
            self.describe()
            self.show_field()
            self.fill_screws()
            self.colour()
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
        if r.get("bodies"):
            contact = r.get("joint") == "contact"
            html += R.heading("Bodies (joined by screws and bolts)" if contact else "Bodies (fully bonded)")
            html += R.grid(["Body", "Material", f"von Mises max ({D['S']})", "Safety factor", f"Mass ({mu[1]})"],
                           [[b["name"], b["material"].get("name") or "custom", R.num(s_out(b["vm_max"])), R.num(b["fos_y"], 3) if b.get("fos_y") else "-",
                             R.num(b["mass"] * mu[3])] for b in r["bodies"]])
            if contact:
                html += R.note("Between the parts there is frictionless contact: they press on each other, slide and may open. Only the screw patches are bonded, "
                               "and the stress right at a patch is not reliable (there is no hole and no screw stiffness): the force through the patch is what counts.")
            else:
                html += R.note("The parts are bonded where their faces touch: no slip, no gap, no separation. A bolted or sliding joint is stiffer here than in "
                               "reality, and the stress right at the edge of a bonded face is not reliable. The coloured stress is averaged at the nodes of a shared "
                               "face, so it blends the two bodies there; the table above is per body.")
            for t_ in r.get("notes") or []:
                html += R.note(t_, "#b05a00")
        if r.get("contact"):
            html += self.joint_report(r)
        kind = 'quadratic' if r.get('order', 2) == 2 else 'linear'
        cn = r.get("counts") or {}
        if cn.get("hexes") or cn.get("pyramids"):
            mesh_rows = [(f"Elements ({kind})", f"{r['n_elements']:,}", None), ("Hexahedra", f"{cn['hexes']:,} ({100.0 * cn['hexes'] / max(r['n_elements'], 1):.0f} %)", None),
                         ("Tetrahedra", f"{cn['tets']:,}", None), ("Pyramids", f"{cn['pyramids']:,}", None)]
        else:
            mesh_rows = [(f"Tetrahedra ({kind})", f"{r['n_tets']:,}", None)]
        html += R.heading("Mesh") + R.kv(mesh_rows + [("Nodes", f"{r['n_nodes']:,}", None), ("Element size", R.num(l_out(r["h"]), 4), D["L"])])
        if r.get("hexdom_note"):
            html += R.note("Hex-dominant was asked for, but this mesh is tetrahedra only: " + r["hexdom_note"])
        html += R.note("This window does not refine the mesh by itself: check by meshing finer and comparing, or run a parametric study "
                       "over the element size.")
        info = r.get("info") or {}
        ok = r["equilibrium"] < 1e-6
        sums = "Applied + reactions = (" + ", ".join(R.num(f_out(a + b), 3) for a, b in zip(r["applied"], r["reaction"])) + f") {D['F']}"
        html += R.solver_block(info.get("solver", "?"), info.get("residual"), ok, sums,
                               [f"Relative error of the force balance {r['equilibrium']:.1e}."] if not ok else None)
        self.res_lbl.setText(html)
        self.say("Solved.")

    def joint_report(self, r):
        """The HTML of the contact between the parts and of the screws and bolts (see solid_model._contact_results)."""
        D = UD()
        k2 = l_out(1.0) ** 2
        c = r["contact"]
        out = R.heading("Contact between the parts")
        rows = [[f"{j['a']} - {j['b']}", R.num(j["area"] * k2), f"{100.0 * j['closed_area'] / max(j['area'], 1e-12):.0f} %", R.num(f_out(j["force"])),
                 R.num(l_out(j["gap_max"]))] for j in c["joints"]]
        if rows:
            out += R.grid(["Joint", f"Area ({D['L']}2)", "Pressing", f"Contact force ({D['F']})", f"Largest gap ({D['L']})"], rows)
        if c["pairs"]:
            out += R.note(f"{c['closed']:,} of {c['pairs']:,} node pairs press, found in {c['iterations']} round{'s' if c['iterations'] != 1 else ''}. "
                          "The contact force is what the parts press on each other with, besides the screws.")
        else:
            out += R.note("Every face between the parts is a screw patch, so it is all bonded and there is no free contact.")
        if not c["converged"]:
            out += R.note("The set of pairs that press kept changing and was cut off: the contact is not settled. Try a smaller element size.", "#b00020")
        recs = r.get("screws") or []
        if not recs:
            return out + R.note("No screw or bolt: nothing is bonded between the parts, so every part must be held by the supports.")
        method = screw.METHODS.get(r.get("design") or "ASD", "ASD")
        out += R.heading("Screws and bolts", f"AISI S100-16, {method}")
        loc = lambda p: "(" + ", ".join(format(l_out(x), ".4g") for x in p) + ")"
        rows = []
        for rec in recs:
            kind = {"ok": "ok", "fails": "bad", "incomplete": "warn"}.get(rec["status"], "warn")
            word = {"ok": "ok", "fails": "FAILS", "incomplete": "needs numbers"}.get(rec["status"], "?")
            rows.append([f"{rec['screw']} at {loc(rec['centre'])}", " - ".join(rec["bodies"]), R.num(f_out(rec["V"])), R.num(f_out(rec["T"])),
                         rec["worst_name"].rpartition("(")[2].rstrip(")") if rec["worst_name"] else "-",
                         R.num(rec["worst"], 3) if rec["worst"] is not None else "-", R.chip(word, kind)])
        out += R.grid(["Screw (position)", "Joins", f"Shear V ({D['F']})", f"Tension T ({D['F']})", "Governs", "Ratio", ""], rows)
        out += R.note("Ratio = demand over available strength, 1 or less passes; Governs is the clause of the check with the largest ratio (listed below for the "
                      "failing screws). Shear is the force in the plane of the joint through the patch; tension is the force along its normal and includes "
                      "prying (a negative value is compression, which a screw does not feel). Both come from the solution.")
        show = [rec for rec in recs if rec["status"] == "fails"] or []
        live = [rec for rec in recs if rec["worst"] is not None]
        if live:
            top = max(live, key=lambda rec: rec["worst"])
            if top not in show:
                show.append(top)
        for rec in show[:4]:
            out += R.subhead(f"{rec['screw']} at {loc(rec['centre'])}: the checks", f"{' - '.join(rec['bodies'])}")
            rows = []
            for ck in rec["checks"]:
                if not ck["applies"]:
                    rows.append([f"{ck['name']} ({ck['clause']})", "-", "-", "-", ck["note"]])
                    continue
                unit = ck.get("unit")
                fmt = (lambda x: R.num(f_out(x))) if unit == "N" else ((lambda x: R.num(l_out(x))) if unit == "mm" else (lambda x: R.num(x, 3)))
                rows.append([f"{ck['name']} ({ck['clause']})", fmt(ck["demand"]) if ck["demand"] is not None else "-",
                             fmt(ck["capacity"]) if ck["capacity"] is not None else "-", R.num(ck["ratio"], 3), ck["note"] or ""])
            out += R.grid(["Check", "Demand", "Available", "Ratio", "Note"], rows)
            t1, t2 = l_out(rec["t1"]), l_out(rec["t2"])
            if rec["kind"] == "bolt":
                out += R.note(f"Thickness of the parts: {rec['bodies'][0 if rec['head_body'] == rec['a'] else 1]} {t1:.4g} {D['L']}, "
                              f"{rec['bodies'][1 if rec['head_body'] == rec['a'] else 0]} {t2:.4g} {D['L']}.")
            else:
                out += R.note(f"Under the head: {rec['bodies'][0 if rec['head_body'] == rec['a'] else 1]}, t1 = {t1:.4g} {D['L']}; the part with the threads, "
                              f"{rec['bodies'][1 if rec['head_body'] == rec['a'] else 0]}, t2 = {t2:.4g} {D['L']}.")
            for t_ in rec["notes"]:
                out += R.note(t_, "#b05a00")
        if len(show) < len(recs):
            out += R.note(f"The checks of the failing screws and of the one with the largest ratio are shown; there are {len(recs)} patches in all.")
        return out

    def scale_value(self):
        """The displacement magnification on screen: 0 when the deformed shape is off, a tenth of the part when blank / auto."""
        if self.result is None or not self.cb_def.isChecked():
            return 0.0
        t = self.e_scale.text().strip().lower()
        if t in ("", "auto"):
            umax = float(self.result["umax"])
            return 0.1 * self.geom["diag"] / umax if umax > 0 else 0.0
        try:
            return float(t.replace(",", "."))
        except ValueError:
            return 0.0

    def field_key(self):
        return self.cb_field.currentData() or "umag"

    def field_values(self, ramp=1.0):
        """-> (value per node with the load at `ramp` of its full value, the legend: {"title", "labels", "lo", "hi", "flip", "subtitle"}).
        The colour range (lo, hi) and the legend are always those of the full result, so an animation keeps one scale."""
        r = self.result
        key = self.field_key()
        D = UD()
        if key == "fos":
            syn = r.get("sy_node")                                  # an assembly: the yield strength of the body at every node
            sy = float(r["material"].get("sy") or 0.0) if syn is None else float(np.max(syn))
            if syn is not None and sy > 0:
                syn = np.asarray(syn, float)
                vals = np.where(syn > 0, syn / np.maximum(np.asarray(r["vm_node"], float) * ramp, 1e-12), np.nan).clip(0, 100)
            elif sy > 0:
                vals = (sy / np.maximum(np.asarray(r["vm_node"], float) * ramp, 1e-12)).clip(0, 100)
            else:
                vals = np.full(len(r["vm_node"]), np.nan)
            leg = {"title": "Factor of safety, yield", "lo": FOS_LOW, "hi": FOS_HIGH, "flip": True,
                   "labels": [(0.0, f"{FOS_LOW:g} or less"), (1.0, f"{FOS_HIGH:g} or more")],
                   "subtitle": "grey = no yield strength" if sy <= 0 else None}
            return vals, leg
        full, name, unit = {"umag": (lambda: l_out(r["un"]), "Displacement magnitude", D["L"]),
                            "ux": (lambda: l_out(r["u"][:, 0]), "Displacement X", D["L"]),
                            "uy": (lambda: l_out(r["u"][:, 1]), "Displacement Y", D["L"]),
                            "uz": (lambda: l_out(r["u"][:, 2]), "Displacement Z", D["L"]),
                            "vm": (lambda: s_out(r["vm_node"]), "von Mises stress", D["S"])}[key]
        full = np.asarray(full(), float)
        lo, hi = float(np.nanmin(full)), float(np.nanmax(full))
        if not hi > lo:
            hi = lo + 1.0
        leg = {"title": f"{name}  [{unit}]", "lo": lo, "hi": hi, "flip": False,
               "labels": [(0.0, f"{hi:.4g}"), (0.5, f"{(hi + lo) / 2:.4g}"), (1.0, f"{lo:.4g}")], "subtitle": None}
        return full * ramp, leg

    def shown_cells(self):
        """The elements of the result that are drawn: all of them, but without the parts of an assembly that are hidden (so the joint faces and the screws show)."""
        r = self.result
        if self.hidden_bodies and self.is_asm() and r.get("tet_body") is not None and len(r["tet_body"]) == len(r["conn"]) and not r.get("viewcells"):
            return r["conn"][~np.isin(r["tet_body"], sorted(self.hidden_bodies))]
        return r.get("viewcells") or r["conn"]

    def show_field(self, mesh_only=False):
        if self.result is None:
            if self.mesh_q is not None:
                q = self.mesh_q
                self.view.show_mesh(q["nodes"], q.get("viewcells") or q["tets"])          # grey surface with the mesh edges: no result colours before Solve
            return
        r = self.result
        vals, leg = self.field_values()
        self.view.show_result(r["nodes"], self.shown_cells(), r["u"], vals, self.scale_value(), self.cb_edges.isChecked(), leg["lo"], leg["hi"], leg["flip"],
                              legend={"title": leg["title"], "labels": leg["labels"], "subtitle": leg["subtitle"]})
        self.update_markers()

    def colours_changed(self, *_a):
        """The shared colour scheme was changed (here or in another tab)."""
        try:
            if self.result is not None:
                self.show_field()
        except RuntimeError:
            result_style.unsubscribe(self.cmap_combo._external)        # the window is gone

    # ------------------------------------------------------------------ animation: the load ramps from 0 to full (deformation and colours scale with it)
    def anim_toggled(self, on):
        self.anim_box.setVisible(on)
        if not on:
            self.anim_stop()

    def anim_inputs(self, what):
        try:
            n = int(float(self.e_frames.text()))
            dur = float(self.e_dur.text())
        except ValueError:
            QMessageBox.warning(self, what, "Frames and duration must be numbers.")
            return None
        if not (2 <= n <= 300) or dur <= 0:
            QMessageBox.warning(self, what, "Use 2 to 300 frames and a positive duration.")
            return None
        return n, dur

    def apply_ramp(self, ramp):
        if self.result is None:
            return
        vals, _leg = self.field_values(ramp)
        self.view.set_ramp(ramp, vals)

    def anim_play(self):
        if self.result is None:
            QMessageBox.information(self, "Animate", "Solve first.")
            return
        got = self.anim_inputs("Animate")
        if got is None:
            return
        n, dur = got
        self.anim_timer.stop()
        self.anim_n, self.anim_k, self.anim_dir = n, 0, 1
        self.apply_ramp(0.0)
        self.anim_timer.start(max(10, int(dur * 1000 / n)))

    def anim_step(self):
        n = self.anim_n
        k = self.anim_k + self.anim_dir
        mode = self.loop_combo.currentIndex()
        if k >= n:
            if mode == 0:
                self.anim_timer.stop()
                k = n - 1
            elif mode == 1:
                k = 0
            else:
                self.anim_dir = -1
                k = max(0, n - 2)
        elif k < 0:
            self.anim_dir = 1
            k = min(1, n - 1)
        self.anim_k = k
        self.apply_ramp(k / (n - 1) if n > 1 else 1.0)

    def anim_stop(self):
        self.anim_timer.stop()
        self.apply_ramp(1.0)

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
        sy = (float(r["sy_node"][i]) if r.get("sy_node") is not None else r["material"].get("sy")) or 0.0
        fos = (sy / vm) if vm > 1e-12 and sy else None
        d = [("ux", R.num(l_out(u[0])), None), ("uy", R.num(l_out(u[1])), None), ("uz", R.num(l_out(u[2])), None),
             ("Total |u|", R.num(l_out(float(r["un"][i]))), None)]
        st = [("von Mises", R.num(s_out(vm)), None)]
        if fos is not None:
            st.append(("Safety factor, yield", R.num(fos, 4), None))
        where = (f"node {i} at ({R.num(l_out(x[0]))}, {R.num(l_out(x[1]))}, {R.num(l_out(x[2]))}) {D['L']}, "
                 f"{R.num(l_out(pr['dist']), 3)} {D['L']} from the point")
        self.probe_lbl.setText(R.probe_block("Probe", where, d, st, D["L"], D["S"], "Stress: value at the node (average of the elements around it)."))

    def export_animation(self, path_fmt=None, frames=None, dur=None):
        """Saves the load ramp as WebP / PNG / GIF / MP4 / PNG pictures (Frames, Duration and Playback of the Animate box).  `path_fmt` =
        (path, format) skips the Save box; a plain path is read as GIF / by its extension.  -> the path written or None."""
        if self.result is None:
            QMessageBox.information(self, "Export animation", "Solve first.")
            return None
        if isinstance(path_fmt, str):
            fmt = {".webp": "webp", ".mp4": "mp4", ".png": "png"}.get(os.path.splitext(path_fmt)[1].lower(), "gif")
            path_fmt = (path_fmt, fmt)
        got = self.anim_inputs("Export animation")
        if got is None:
            return None
        n, d = got
        n = int(frames) if frames else n
        d = float(dur) if dur else d
        self.anim_timer.stop()
        self.show_field()                                      # the full result on screen: the pictures are made from this view
        sess = self.view.export_session()
        if sess is None:
            QMessageBox.information(self, "Export animation", "The 3D view is not available here, so there is nothing to draw the pictures with.")
            return None
        state = {"bg": None}

        def grab(k):
            ramp = k / (n - 1)
            vals, _leg = self.field_values(ramp)
            return sess.frame(ramp, vals, state["bg"])

        def set_bg(level):
            state["bg"] = level
        try:
            return anim_export.export(self, "3D FEA", n, grab, n / d, self.loop_combo.currentIndex(), say=self.say, path_fmt=path_fmt, set_bg=set_bg)
        except Exception as ex:                                  # noqa: BLE001 - a drawing failure is shown, not raised into the event loop
            self.say(f"Could not render the animation: {ex}")
            return None
        finally:
            sess.close()

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
        s.setdefault("splits", [])
        s.setdefault("bond_tol", 0.0)
        s.setdefault("body_mats", {})
        s.setdefault("joint", "bonded")
        s.setdefault("screws", [])
        s.setdefault("design", "ASD")
        s["mesh"] = smesh.complete(s.get("mesh"))
        dims_changed = (s["dims"] != self.setup.get("dims") or s["splits"] != (self.setup.get("splits") or []) or getattr(self, "geom_case", False)
                        or s["bond_tol"] != self.setup.get("bond_tol") or s["body_mats"] != self.setup.get("body_mats"))
        self.geom_case = False
        self.setup = json.loads(json.dumps(s))
        self.put_material(self.setup["material"])
        self.select_material_name(self.setup.get("mat_name"))
        self.e_h.setText(format(l_out(self.setup["h"]), ".8g") if self.setup.get("h") else "")
        self.put_mesh_options()
        if dims_changed and self.source is not None:
            self.load_geometry()
        elif self.geom is not None and self.is_asm():
            self.fill_faces()
            self.show_asm()
            self.redraw()
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
        w.src = {"type": s.get("type") or "part", "path": s.get("orig"), "name": s.get("name", "")}
        sp = sim_project.state_path(folder)
        if os.path.isfile(sp):
            try:
                with open(sp, encoding="utf-8") as f:
                    st = json.load(f).get("setup")
                if st:
                    st.setdefault("dims", {})
                    st.setdefault("splits", [])
                    st.setdefault("bond_tol", 0.0)
                    st.setdefault("body_mats", {})
                    st.setdefault("joint", "bonded")
                    st.setdefault("screws", [])
                    st.setdefault("design", "ASD")
                    st["mesh"] = smesh.complete(st.get("mesh"))
                    w.setup = st
            except Exception:
                pass
        w.put_material(w.setup["material"])
        w.select_material_name(w.setup.get("mat_name"))
        w.e_h.setText(format(l_out(w.setup["h"]), ".8g") if w.setup.get("h") else "")
        w.put_mesh_options()
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
        self.b_study.setEnabled(self.job is None and not self.is_asm())
        self.b_study.setToolTip("Parametric studies work on a single part for now, not on an assembly." if self.is_asm() else "")

    def open_study(self):
        if self.is_asm():
            QMessageBox.information(self, "Parametric study", "Parametric studies work on a single part for now, not on an assembly.")
            return None
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
