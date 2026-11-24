"""
solid_base.py - what the 3D windows of a part or an ASSEMBLY have in common (3D FEA, 3D Thermal, 3D CFD): the project bar and the project folder, the part
or assembly copy, its dimensions, the faces list and picking in the 3D view, splitting a flat face into patches, the bodies of an assembly and the bond
distance, the element sizes (of every part, of single faces, of the curved surfaces), the mesh and its quality, the jobs that run on a worker thread with
their progress bar, save / open and the parametric-study button.

A window for one kind of physics derives from SolidBase and gives the parts that differ, through these hooks (every one has a plain default here):
    kind, label                      the project kind ('solid') and the name on the tab / buttons ('3D FEA'); MESH_SEC, RESULTS_SEC: the numbers of those sections
    new_setup()                      the setup dict of a new project (the keys of the geometry and the mesh, and the physics')
    make_view()                      the 3D view (a solid_view.SolidView or one derived from it)
    build_physics_sections()         the panel sections between Geometry and Mesh (material, conditions ...)
    build_mesh_extras(v)             anything more under the Mesh section (the adaptive mesh)       put_mesh_extras()  its boxes from the setup
    build_results_section()          the Results section; the window must offer  show_field(mesh_only=False)  (the meshing and a change of the view call it)
    stop_playback() / show_no_result(had)   what a changed setup does to a running animation / to the text of the results
    read_physics() / store_physics   parse the physics boxes (ValueError for a bad number) / put what was parsed into the setup
    after_inputs()                   what to do after the boxes were read          clear_results_ui(had)  the Results section when the setup changed
    refresh_labels()                 labels with units (call super() first)         put_physics() / units_results()  the boxes / the results after a change of units
    enable_results_buttons()         the buttons that need a result                 refresh_lists()  the table of conditions
    CONDITION_KINDS                  the lists of conditions of the setup that act on faces ((name, key) ...: splitting a face looks in them)
    has_conditions() / condition_colours(cols)
    reset_source_setup()             what a new source clears                       use_source_material(mat)  the material of a freshly imported part
    asm_only()                       the widgets only an assembly has               fill_bodies()  the table of the bodies
    migrate_setup(st) / restore_boxes()   opening an older project / filling the boxes from the setup of a project just opened
    job_plan(g, r, solving)          the stages a mesh or a solve goes through      study_adapter()
    run_solve()                      the Solve button (a job through run_job)       read_mesh_more()  more of the setup read after the mesh options
"""
import json
import os
import traceback

import numpy as np
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

import ext
import sim_project
import sim_ui
import sim_source
import solid_asm as sasm
import solid_fem as fem
import solid_geom as sg
import solid_mesh as smesh
import solid_model as sm
import solid_progress
import solid_view as sv
import unitctl
import units


# --- the program's global units (File > Units).  The solvers work in mm; these convert only what is shown or typed.
def UD():
    return units.get(unitctl.system())


def l_out(mm):
    return mm * 1e-3 / UD()["L_m"]


def l_in(x):
    return x * UD()["L_m"] * 1e3


class Job(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str, bool)
    note = pyqtSignal(str)

    def __init__(self, fn, tracker=None):
        super().__init__()
        self.fn = fn
        self.stop = False
        self.tracker = tracker                        # solid_progress.Tracker: what the solver is given as `progress` (a function of one text that also knows the stages)

    def run(self):
        try:
            if self.tracker is not None:
                self.tracker.attach(self.note.emit)
            self.done.emit(self.fn(self.tracker if self.tracker is not None else (lambda t: self.note.emit(str(t))), lambda: self.stop))
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


def QApplication_keyboard():
    from PyQt6.QtWidgets import QApplication
    m = QApplication.keyboardModifiers()
    return bool(m & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))


class SolidBase(QWidget):
    kind = "solid"
    label = "3D FEA"
    plotter = None
    nav = None
    study_geometry = True                       # a study can change the part's dimensions
    MESH_SEC = 5                                # the numbers of the Mesh and the Results sections
    RESULTS_SEC = 6
    CONDITION_KINDS = ()                        # (name, key in the setup) of the lists of conditions that act on faces: splitting a face has to look in them
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
        self.setup = self.new_setup()
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
        self.view = self.make_view()
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

    def build_panel(self):
        self.build_geometry_section()
        self.build_physics_sections()
        self.build_mesh_section()
        self.build_results_section()
        self.finish_panel()

    def build_geometry_section(self):
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

    def build_mesh_section(self):
        # --- 5 mesh
        v = self.sec(self.MESH_SEC, "Mesh", True, summary=lambda: self.mesh_lbl.text() or "not meshed",
                     help_text="The part is filled with tetrahedra. Element size: the length of an element edge, typed for every part in the table (blank = "
                               "automatic, a fourteenth of the size of the whole model). Smaller elements are more accurate and slower. The parts of an "
                               "assembly can have different sizes: they are still meshed as one, so the faces they share keep matching nodes. "
                               "Advanced mesh options: choose linear or quadratic "
                               "elements, make the mesh finer at curved surfaces or on single faces, and read how good the elements are.")
        self.h_label = QLabel()
        v.addWidget(self.h_label)
        self.size_table = QTableWidget(0, 3)
        self.size_table.setHorizontalHeaderLabels(["Part", "Size", "Elements"])
        self.size_table.verticalHeader().hide()
        self.size_table.setMinimumHeight(60)
        self.size_table.setMaximumHeight(190)
        hd_ = self.size_table.horizontalHeader()
        hd_.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hd_.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hd_.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.size_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.size_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.size_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.size_table.setToolTip("Double-click the size of a part and type its element size (blank = automatic). Every part can have its own size, "
                                   "for example a fine mesh on a small part and a coarse one on a big part next to it. The parts are meshed as one mesh, "
                                   "so the nodes of the faces they share match: that face gets the finer of the two sizes, and the coarser part grows "
                                   "away from it. The last column shows how many elements each part got.")
        self.size_table.itemChanged.connect(self.part_size_changed)
        v.addWidget(self.size_table)
        self.build_advanced_mesh(v)
        self.build_mesh_extras(v)
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

    def finish_panel(self):
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
            if s_.number == self.RESULTS_SEC:
                self.col.addLayout(row)
                self.prog = solid_progress.make_row()                # the progress bar: under the Solve button, shown while a mesh or a solve runs
                self.col.addWidget(self.prog)
                self.col.addWidget(self.study_box)
            self.col.addWidget(s_)
        self.study_box.setVisible(False)
        self.col.addStretch(1)
        sim_ui.soften(self.panel)                    # the sections were added after make_panel: give them the soft bevel look too
        self.refresh_labels()
        self.enable_buttons()

    # ------------------------------------------------------------------ the panel
    def sec(self, n, title, open_=True, summary=None, help_text=None):
        s_ = sim_ui.Section(self.kind, n, title, open_, help_text, summary)
        self.sections.append(s_)
        return s_.body

    @staticmethod
    def hint(text):
        """The one-line hint over the support / load buttons: small grey text, like the other simulation panels."""
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#555555; font-size:11px;")
        return lb

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
        self.e_hmin.setToolTip("The smallest element edge the mesher may make (blank = a sixth of the smallest element size).")
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

    def read_mesh_options(self, h, bs=None, hd=None):
        """The mesh options from the boxes into the setup.  `h` = the smallest element size (mm, 0 = automatic); `bs` = {body index: mm} of the parts of an
        assembly that have a size of their own and `hd` = the size of the others.  Raises ValueError for a bad number."""
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
        why = smesh.validate(mo, h or (sm.auto_h(self.geom) if self.geom is not None else 0.0), self.local_refs(mo["face_sizes"], bs, hd))
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
        self.put_mesh_extras()

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
        """The (smallest) element size (mm) the next mesh gets: the typed one, or the automatic one."""
        return self.size_state()[2]

    def local_refs(self, face_sizes, bs, hd):
        """The element size of the part under each local size, for smesh.validate (None: they are all compared with the one size)."""
        if not bs or self.geom is None:
            return None
        return smesh.face_refs(self.geom, [sg.match_faces(self.geom, x["face"]) for x in face_sizes], bs, hd)

    def try_face_sizes(self, sizes):
        """Takes a new list of local sizes when the options stay valid with it; else says why not."""
        mo = smesh.complete(self.setup.get("mesh"))
        mo["face_sizes"] = sizes
        hd, bs, hlow = self.size_state()
        why = smesh.validate(dict(mo, advanced=True), hlow, self.local_refs(sizes, bs, hd))
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

    # ------------------------------------------------------------------ the element size of every part
    def part_names(self):
        """The rows of the size table: the bodies of an assembly, or the one part."""
        if self.geom is None:
            return []
        if self.is_asm():
            return [b["name"] for b in self.geom["bodies"]]
        return [self.src.get("name") or "Part"]

    @staticmethod
    def parse_size(text, label):
        """mm from the text typed in the program's length unit; 0.0 (automatic) for a blank one or one that starts with 'auto'.  ValueError otherwise."""
        t = (text or "").strip()
        if not t or t.lower().startswith("auto"):
            return 0.0
        try:
            v = float(t.replace(",", "."))
        except ValueError:
            raise ValueError(f"{label}: '{t}' is not a number.")
        if v < 0:
            raise ValueError(f"{label}: the element size cannot be negative.")
        return l_in(v)

    def read_sizes(self):
        """(h, body_h) from the table: h = the size of a single part (mm, 0 = automatic) and body_h = {part name: mm} of an assembly (only the parts that
        have one).  The setup's own numbers when the table has no rows yet.  ValueError for a bad number."""
        t = self.size_table
        if self.geom is None or t.rowCount() == 0:
            return float(self.setup.get("h") or 0.0), dict(self.setup.get("body_h") or {})
        names = self.part_names()
        asm = self.is_asm()
        vals = []
        for r in range(min(t.rowCount(), len(names))):
            it = t.item(r, 1)
            vals.append(self.parse_size(it.text() if it is not None else "", f"Element size of {names[r]}" if asm else "Element size"))
        if asm:
            return float(self.setup.get("h") or 0.0), {n: v for n, v in zip(names, vals) if v > 0}
        return (vals[0] if vals else 0.0), dict(self.setup.get("body_h") or {})

    def size_state(self):
        """(the size of the parts without one of their own, {body index: mm} of those that have one, the smallest size) - what the next mesh gets."""
        try:
            h, bh = self.read_sizes()
        except ValueError:
            h, bh = float(self.setup.get("h") or 0.0), dict(self.setup.get("body_h") or {})
        if self.geom is None:
            return h, {}, h
        hd = h or sm.auto_h(self.geom)
        try:
            bs = smesh.body_sizes(self.geom, {"body_h": bh}, hd)
        except fem.FemError:
            bs = {}
        return hd, bs, min(fem.element_sizes(self.geom, hd, {"body_h": bs}))

    def set_size(self, text, part=None):
        """Types `text` (the program's length unit; blank = automatic) into the size of the part named `part`, or of every part.  inputs_changed() then
        reads it into the setup - what the old Element size box did, for scripts and the parametric studies."""
        t = self.size_table
        names = self.part_names()
        if not names or t.rowCount() == 0:
            self.setup["h"] = self.parse_size(str(text), "Element size")
            return
        t.blockSignals(True)
        for r in range(min(t.rowCount(), len(names))):
            if part is None or names[r] == part:
                t.item(r, 1).setText(str(text))
        t.blockSignals(False)

    def adopt_default_size(self):
        """An assembly saved with one element size for all its parts (setup["h"]): every part gets it as its own, so the table shows it."""
        if not self.is_asm() or not self.setup.get("h"):
            return
        mine = self.setup.setdefault("body_h", {})
        for n in self.part_names():
            mine.setdefault(n, float(self.setup["h"]))
        self.setup["h"] = 0.0

    def fill_part_sizes(self):
        """The size table from the setup: the parts, their sizes ('auto (size)' where there is none), the elements of the last mesh."""
        t = self.size_table
        t.blockSignals(True)
        t.setRowCount(0)
        D = UD()
        t.setHorizontalHeaderLabels(["Part", f"Size ({D['L']})", "Elements"])
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.geom is not None:
            self.adopt_default_size()
            auto = sm.auto_h(self.geom)
            asm = self.is_asm()
            for i, n in enumerate(self.part_names()):
                v = float((self.setup.get("body_h") or {}).get(n) or 0.0) if asm else float(self.setup.get("h") or 0.0)
                t.insertRow(i)
                a = QTableWidgetItem(n)
                a.setFlags(ro)
                if asm:
                    c = self.body_colour(i)
                    a.setBackground(QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255)))
                    a.setForeground(QColor(20, 20, 20))
                b = QTableWidgetItem(format(l_out(v), ".8g") if v else f"auto ({l_out(auto):.4g})")
                b.setFlags(ro | Qt.ItemFlag.ItemIsEditable)
                if not v:
                    b.setForeground(QColor(110, 110, 110))
                t.setItem(i, 0, a)
                t.setItem(i, 1, b)
                t.setItem(i, 2, QTableWidgetItem(""))
                t.item(i, 2).setFlags(ro)
        t.blockSignals(False)
        rows = max(t.rowCount(), 1)
        t.setFixedHeight(min(190, t.horizontalHeader().height() + 2 * t.frameWidth() + 4 + sum(t.rowHeight(i) for i in range(t.rowCount())) + (0 if t.rowCount() else 26 * rows)))
        self.mark_thin()
        self.show_counts(self.mesh_q)

    def mark_thin(self):
        """Colours the size of a part that is thin for it (a coarse mesh through a thin sheet is poor) and says why in its tooltip."""
        t = self.size_table
        t.blockSignals(True)
        notes = {}
        if self.geom is not None and self.is_asm():
            hd, bs, _lo = self.size_state()
            notes = sm.thin_parts(self.geom, hd, fem.element_sizes(self.geom, hd, {"body_h": bs}))
        for r in range(t.rowCount()):
            it = t.item(r, 1)
            if it is None:
                continue
            if r in notes:
                it.setForeground(QColor(176, 90, 0))
                it.setToolTip(notes[r])
            else:
                it.setToolTip("")
                if it.text().startswith("auto"):
                    it.setForeground(QColor(110, 110, 110))
                else:
                    it.setData(Qt.ItemDataRole.ForegroundRole, None)
        t.blockSignals(False)

    def show_counts(self, q):
        """The number of elements of every part in the mesh `q` (blank when there is no mesh)."""
        t = self.size_table
        t.blockSignals(True)
        counts = {}
        if q is not None and t.rowCount():
            groups = q.get("groups") or []
            if self.is_asm() and groups and all("body" in g for g in groups):
                for g in groups:
                    counts[g["body"]] = counts.get(g["body"], 0) + len(g["conn"])
            else:
                counts[0] = sum(len(g["conn"]) for g in groups) if groups else len(q.get("conn", q.get("tets", ())))
        for r in range(t.rowCount()):
            it = t.item(r, 2)
            if it is not None:
                it.setText(f"{counts[r]:,}" if r in counts else "")
        t.blockSignals(False)

    def part_size_changed(self, it):
        if it.column() != 1:
            return
        self.inputs_changed()                                  # reads the table into the setup; a bad number is said in the status line
        self.fill_part_sizes()                                      # and the table shows what the setup holds (blank as 'auto (size)', a bad number undone)

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
        """One line about the mesh; `h` = the element size (mm), or the list of the sizes of the parts of an assembly (a range is shown when they
        differ); `counts` = {"tets", "hexes", "pyramids"} when it has bricks."""
        kind = "quadratic" if order == 2 else "linear"
        if counts and (counts.get("hexes") or counts.get("pyramids")):
            what = (f"{n_elements:,} elements ({counts['hexes']:,} hexahedra, {counts['tets']:,} tetrahedra, {counts['pyramids']:,} pyramids)")
        else:
            what = f"{n_elements:,} tetrahedra"
        hs = sorted({round(float(x), 9) for x in (h if isinstance(h, (list, tuple)) else [h])})
        size = f"element size {l_out(hs[0]):.4g} {UD()['L']}" if len(hs) == 1 else f"element sizes {l_out(hs[0]):.4g} to {l_out(hs[-1]):.4g} {UD()['L']}"
        return f"{what}, {n_nodes:,} nodes ({kind}), {size}"

    def refresh_labels(self):
        """Every label that carries a unit, in the program's current units."""
        D = UD()
        self.h_label.setText(f"Element size of every part ({D['L']}, blank = auto)")
        self.size_table.setHorizontalHeaderLabels(["Part", f"Size ({D['L']})", "Elements"])
        self.hmin_label.setText(f"Minimum size ({D['L']})")

    def units_changed(self, *_a):
        try:
            self.refresh_labels()
            self.put_physics()
            self.put_mesh_options()
            self.fill_part_sizes()
            if self.geom is not None:
                self.fill_faces()
                self.fill_splits()
                self.set_geo_text()
            self.refresh_lists()
            self.units_results()
            for s_ in self.sections:
                s_.refresh_summary()
        except RuntimeError:
            unitctl.off_change(self.units_changed)               # the window is gone

    # ------------------------------------------------------------------ the hooks (see the top of the file); the defaults do nothing, or what is common
    def new_setup(self):
        """The setup of a new project: the geometry and the mesh keys (a window adds its physics)."""
        return {"dims": {}, "splits": [], "bond_tol": 0.0, "body_mats": {}, "body_h": {}, "h": 0.0, "mesh": smesh.default_mesh()}

    def make_view(self):
        return sv.SolidView(self)

    def build_physics_sections(self):
        pass

    def build_results_section(self):
        pass

    def build_mesh_extras(self, v):
        pass

    def put_mesh_extras(self):
        pass

    def read_mesh_more(self):
        """More of the setup read after the mesh options (the adaptive mesh).  ValueError for a bad number."""

    def read_physics(self):
        """Parses the physics boxes (ValueError for a bad number) and returns what store_physics() puts into the setup."""
        return None

    def store_physics(self, phys):
        pass

    def after_inputs(self):
        pass

    def stop_playback(self):
        pass

    def show_no_result(self, had):
        pass

    def enable_results_buttons(self):
        pass

    def put_physics(self):
        """The physics boxes from the setup (a change of units, ...)."""

    def units_results(self):
        """The results on screen again, after a change of units."""

    def refresh_lists(self):
        self.fill_face_table()

    def has_conditions(self):
        return False

    def patch_conditions(self, fid):
        """The names of the conditions that are on single patches of the face `fid` (changing its split would remove them)."""
        return sm.patch_conditions(self.setup, self.geom, fid, self.CONDITION_KINDS)

    def condition_colours(self, cols):
        """Adds {face id: colour} for the faces the conditions act on (the picked faces are coloured after this)."""

    def reset_source_setup(self):
        pass

    def use_source_material(self, mat):
        pass

    def asm_only(self):
        return [self.asm_box]

    def fill_bodies(self):
        pass

    def migrate_setup(self, st):
        """An older project's setup brought up to date in place -> the sentences that say what was changed."""
        return []

    def restore_boxes(self):
        self.put_mesh_options()

    def run_solve(self):
        """The Solve button: a window's physics solves here (as a job, through run_job)."""
        self.say("This window has no solver.")
        return False

    def study_adapter(self):
        raise NotImplementedError("this window has no parametric study")


    def say(self, text):
        self.status_lbl.setText(text)

    def status(self, text):
        self.say(text)

    def read_inputs(self):
        phys = self.read_physics()                                      # a bad number in the physics boxes stops here, before anything is stored
        h, bh = self.read_sizes()
        self.store_physics(phys)
        self.setup["h"] = h
        if self.is_asm():
            self.setup["body_h"] = bh
        hd, bs, hlow = self.size_state()
        self.read_mesh_options(hlow, bs, hd)
        self.read_mesh_more()
        return self.setup

    def inputs_changed(self):
        try:
            self.read_inputs()
        except ValueError as ex:
            self.say(str(ex))
            return
        self.after_inputs()
        self.invalidate(mesh=True)

    def invalidate(self, mesh=False):
        had = self.result is not None
        self.stop_playback()
        self.result = None
        if mesh:
            self.mesh_q = None
            self.show_quality(None)
            self.show_counts(None)
            self.mark_thin()
        self.show_no_result(had)
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
        self.enable_results_buttons()
        self.b_study.setEnabled(have and not busy)
        if hasattr(self, "b_split"):
            self.preview_grid()

    # ------------------------------------------------------------------ the project
    def title(self):
        return os.path.basename(self.path.rstrip("/\\")) if self.path else self.label

    def project_ok(self):
        return bool(self.path) and sim_project.kind_of_folder(self.path) == self.kind

    def show_source(self):
        if not self.project_ok():
            self.src_lbl.setText(f"<b>{self.label}</b> - press <b>New project...</b>: the project is a folder ({sim_project.ext_of(self.kind)}) with its own copy of the "
                                 "part or assembly.")
            return
        if self.source is None:
            self.src_lbl.setText(f"<b>{self.label}</b> project <b>{self.title()}</b> - press <b>Import source...</b> to copy a part or an assembly into it.")
            return
        what = "assembly" if self.src.get("type") == "asm" else "part"
        self.src_lbl.setText(f"<b>{self.label}</b> of the {what} <b>{self.src.get('name') or '?'}</b> (the copy in the project)")

    def new_project(self):
        start = sim_project.default_name(self.kind, self.src.get("name") or self.label, os.path.dirname(self.src.get("path") or "") or os.getcwd())
        path, _ = QFileDialog.getSaveFileName(self, f"New {self.label} project (a folder)", start, f"{self.label} project (*{sim_project.ext_of(self.kind)})")
        return self.create_project(path) if path else False

    def create_project(self, path):
        if not path.lower().endswith(sim_project.ext_of(self.kind)):
            path += sim_project.ext_of(self.kind)
        try:
            sim_project.create(path, self.kind)
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
        lay.addWidget(QLabel("Copy this part or assembly into the project (an assembly is solved as fully bonded parts):"))
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
        if self.geom is not None and self.has_conditions():
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
        self.setup["body_h"] = {}
        self.reset_source_setup()
        self.cur_body = None
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
            self.use_source_material(mat)
        for sp in self.setup.get("splits") or []:                       # remember the column direction that was used, so a rebuild keeps it
            pid = sg.match_face(g.get("orig") or g, sp["face"])
            if pid in g["split_of"] and not sp.get("u"):
                sp["u"] = list(g["split_of"][pid]["u"])
        self.fill_faces()
        self.fill_dims()
        self.fill_splits()
        self.show_asm()
        self.fill_part_sizes()
        P, T, F = sg.display_mesh(g)
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
        for w in self.asm_only():
            w.setVisible(on)
        if not on:
            self.cur_body = None
            return
        import html
        g = self.geom
        names = [b["name"] for b in g["bodies"]]
        k = l_out(1.0)
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

    def redraw(self):
        """Draws the geometry again from the same point of view."""
        if self.geom is None:
            return
        P, T, F = sg.display_mesh(self.geom)
        self.view.set_geometry(P, T, F, keep_camera=True)
        self.view.set_lines("grid", sg.patch_outlines(self.geom))
        self._prev_key = None
        self.view.set_lines("preview", [])
        self.colour()
        self.preview_grid()
        if self.result is not None:
            self.show_field()

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
            if f.get("interface"):                                                # a face between two bodies is inside: nothing to pick there
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
        lost = self.patch_conditions(fid)
        if lost and confirm:
            r = QMessageBox.question(self, "Split face", ("Changing the split removes the supports and loads that are on single patches of this face:\n\n  "
                                     + "\n  ".join(lost) + "\n\nSupports and loads on the whole face stay. Continue?"))
            if r != QMessageBox.StandardButton.Yes:
                return False
        before = json.loads(json.dumps(self.setup))
        sm.set_split(self.setup, self.geom, fid, cols, rows, self.CONDITION_KINDS)
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
        self.condition_colours(cols)
        for f in self.sel_faces:
            cols[f] = sv.PICK
        self.view.colour_faces(cols)

    def after_edit(self):
        self.refresh_lists()
        self.invalidate()
        self.colour()

    def run_job(self, fn, done, title, plan=None):
        """Runs fn(progress, cancel) on a worker thread, then done(result) here.  `plan`: [(stage, size)] the stages it is expected to go through (for the
        progress bar's time estimate; see solid_progress.plan_for)."""
        if self.job is not None:
            return False
        self.say(title + "...")
        trk = solid_progress.Tracker()
        if plan:
            trk.expect(plan)
        if not self.threaded:
            try:
                res = fn(trk, lambda: False)
                trk.finish(True)
                done(res)
            except fem.FemError as ex:
                trk.finish(False)
                self.failed(str(ex), False)
            except Exception:
                trk.finish(False)
                self.failed(traceback.format_exc(), False)
            return True
        j = Job(fn, trk)
        self.job = j
        j.note.connect(self.say)
        j.done.connect(lambda r: self.finished(j, done, r))
        j.failed.connect(lambda m, c: self.finished(j, None, None, m, c))
        self.enable_buttons()
        self.prog.begin(trk)
        j.start()
        return True

    def finished(self, j, done, r, msg=None, cancelled=False):
        j.wait()
        self.job = None
        ok = done is not None
        if j.tracker is not None:
            j.tracker.finish(ok)
        self.prog.end(ok)
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
            self.prog.cancelling()

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
            opts = smesh.resolve(g, self.setup, h)
        except fem.FemError as ex:
            self.say(str(ex))
            return False

        def work(progress, cancel):
            return sm.get_mesh(g, h, self.cache, cancel, progress, opts)
        plan = self.job_plan(g, {"h": h, "mesh": opts}, solving=False)

        def done(q):
            self.mesh_q = q
            ql = q.get("quality") or {}
            self.mesh_lbl.setText(self.mesh_text(ql.get("elements", len(q["tets"])), len(q["nodes"]), q["order"], fem.element_sizes(g, h, opts), ql))
            self.show_counts(q)
            self.show_quality(q.get("quality"), q.get("hexdom_note"))
            self.say("Meshed.")
            self.show_field(mesh_only=True)
        return self.run_job(work, done, "Meshing", plan)

    def job_plan(self, g, r, solving=True):
        """The stages that a mesh or a solve of this setup is expected to go through (the progress bar's estimate); None when that cannot be told."""
        try:
            h, cached = self.plan_mesh(g, r)
            return solid_progress.plan_for(g, dict(r, h=h), mesh=cached, solving=solving)
        except Exception:
            return None

    def plan_mesh(self, g, r):
        """-> (the element size, the mesh of that size already made or None) of a setup: what a job plan starts from."""
        h = r.get("h") or sm.auto_h(g)
        return h, (self.cache.get(sm.mesh_key(g, h, r.get("mesh"))) if self.cache is not None else None)

    # ------------------------------------------------------------------ state, save, open
    def setup_json(self):
        return json.dumps(self.setup)

    def export_state(self):
        try:
            self.read_inputs()
        except ValueError:
            pass
        return {"setup": json.loads(self.setup_json()), "result": self.result, "mesh": None}

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
                json.dump({"kind": self.kind, "setup": self.setup}, f)
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
        if sim_project.kind_of_folder(folder) != cls.kind:
            raise ValueError(f"not a {cls.label} project folder")
        m = sim_project.read(folder)
        w = cls(shell=shell, path=folder, threaded=threaded)
        notes = []
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
                    st.setdefault("body_h", {})
                    notes = w.migrate_setup(st)
                    st["mesh"] = smesh.complete(st.get("mesh"))
                    w.setup = st
            except Exception:
                pass
        w.restore_boxes()
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
        if notes:
            w.say(" ".join(notes))
        return w

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
