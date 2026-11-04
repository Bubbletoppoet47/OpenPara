"""1D FEA tab: beam-theory approximations of trusses and frames (Euler-Bernoulli plane frames).

  Left   : import, material, joints, supports, loads, results
  Right  : the drawing (click a joint or a member; hotkeys work while the drawing has the focus), and the members table below it

Each line of the sketch is a member; points shared by lines are the joints. A member has its own profile (cross-section), made
in the Profile button of its table row, and optionally its own material. Everything is solved at once (it is instant), so the
default is to solve after every change.

Needs numpy only.
"""
import copy
import math
import time
import traceback

import numpy as np
from PyQt6.QtCore import QItemSelectionModel, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                             QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

import beam1d
import beam_canvas
import beam_dialogs as bd
import loads1d
import result_style
import physics_materials as pm
import physics_store as pstore
import profiles1d as pr1
import sketcher_core as sc
from sketch_pick import SketchPicker
import sketcher_script as scr
import units

SUP_NAME = {"fixed": "Fixed", "pinned": "Pinned", "x": "ux = 0", "y": "uy = 0"}
SUP_FLAGS = {"fixed": (True, True, True), "pinned": (True, True, False), "x": (True, False, False), "y": (False, True, False)}
SUP_LONG = {"fixed": "Fixed (ux = uy = rotation = 0)", "pinned": "Pinned (ux = uy = 0)", "x": "Roller, ux = 0 (free in y)",
            "y": "Roller, uy = 0 (free in x)"}
LOAD_NAME = {"force": "Force", "moment": "Moment", "dist": "Line load", "wind": "Wind", "snow": "Snow"}
LINE_KINDS = ("dist", "wind", "snow")      # loads whose targets are members (line ids)
VIEWS = [("(none - geometry only)", None), ("Displacement magnitude", "umag"), ("Displacement X", "ux"), ("Displacement Y", "uy"),
         ("von Mises stress", "vm"), ("Normal stress X", "sx"), ("Normal stress Y", "sy"),
         ("Factor of safety, yield", "fos"), ("Bending moment M (diagram)", "M"), ("Shear force V (diagram)", "V"),
         ("Axial force N (diagram)", "N")]
RESULT_COLS = 7                      # the last columns of the members table that hold results
COL_LEN, COL_DEPTH, COL_RES = 5, 6, 7
HEADERS = ["Member", "Material", "Profile", "End A", "End B", "Length", "Depth", "N (peak)", "V (peak)", "M (peak)", "Max stress",
           "FoS yield", "FoS ult.", "Euler N/Pcr"]


def ask_numbers(parent, title, labels, defaults, note=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(420)
    lay = QVBoxLayout(dlg)
    if note:
        lb = QLabel(note)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#555555; font-size:11px;")
        lay.addWidget(lb)
    form = QFormLayout()
    edits = []
    for lab, d in zip(labels, defaults):
        e = QLineEdit(str(d))
        form.addRow(lab, e)
        edits.append(e)
    lay.addLayout(form)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    try:
        return [float(e.text().strip()) for e in edits]
    except ValueError:
        QMessageBox.warning(parent, title, "Please enter plain numbers (for example 2.5 or 1e6).")
        return None


def fmt(v):
    return "" if v is None else f"{v:.4g}"


class BeamTab(QWidget):
    INPUTS = ("e_E", "e_sy", "e_su", "cb_def", "e_def", "cb_names", "cb_auto", "view_combo")

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.model = None
        self.source = ""
        self.members = []        # {"lid", "name", "a", "b", "mat": None | {"name", "E", "sy", "su"}, "profile": dict | None, "rel_a", "rel_b", "depth": None | float}
        self.supports = []       # {"mode": "fixed"|"pinned"|"x"|"y", "targets": [point id], "name"?}
        self.loads = []          # {"kind": "force", "fx", "fy", "targets": [point id]} | {"kind": "moment", "mz", "targets"} |
        #                          {"kind": "dist", "frame": "global"|"local", "q1", "q2", "targets": [line id]} |
        #                          {"kind": "wind", "V", "angle", "cp", "rho", "targets": [line id]} |
        #                          {"kind": "snow", "h", "rho", "shape", "wet", "targets": [line id]}   (linked to the member depths)
        self.result = None
        self.notes_in = []       # remarks made while collecting the inputs for the solver
        self.problem_members, self.problem_nodes = set(), set()    # what the solver found to be a mechanism (highlighted)
        self.ties = []           # manual ties: {"pt": point id, "lid": line id}  (the point is part of that member)
        self.tie_map = {}        # every tie in force: {(point id, line id): position 0..1 along the member}
        self.import_msg = ""
        self.stale = False
        self.clip_profile = None
        self.building = False
        self.syncing = False
        self.cur_unit = units.DEFAULT
        self.library = []
        self.coords = QLabel("")
        self.canvas = beam_canvas.BeamCanvas(self)

        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(6, 6, 6, 6)
        self.cb_tie = QCheckBox("Connect points that lie on members (auto tie)")
        self.cb_tie.setChecked(True)
        self.cb_tie.setToolTip("A point that lies in the middle of a member (a diagonal meeting a long rail, say) becomes part of that "
                               "member: the member is continuous through the point and whatever else meets there is connected to it. "
                               "Applies at once. Without it such points are NOT connected, unless you tie them by hand (Tie point to member).")
        self.cb_tie.toggled.connect(self.ties_changed)
        lay.addWidget(self.cb_tie)
        self.picker = SketchPicker(self.win, self.import_picked,
                                   "Makes a copy of the chosen sketch as it is now: every line is a member, every shared point a joint "
                                   "(construction lines are ignored). Importing the same sketch again after changing it keeps the profiles, "
                                   "supports and loads of the lines that still exist.")
        lay.addWidget(self.picker)
        b = QPushButton("Clear (start over)")
        b.setToolTip("Removes the imported copy of the sketch and everything set up on this tab (supports, loads, results...) so you can "
                     "import the sketch again from scratch. The sketch itself is not touched.")
        b.clicked.connect(self.clear_tab)
        lay.addWidget(b)
        self.info = QLabel("Nothing imported yet.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        lay.addWidget(QLabel("<b>Material</b> (used by every member that does not choose its own)"))
        form = QFormLayout()
        self.mat_combo = QComboBox()
        self.e_E, self.e_sy, self.e_su = QLineEdit("200000"), QLineEdit("250"), QLineEdit("400")
        self.lbl_E, self.lbl_sy, self.lbl_su = QLabel("E"), QLabel("Yield strength"), QLabel("Ultimate strength")
        self.e_sy.setToolTip("Yield strength. 0 or empty = no yield check (brittle material).")
        form.addRow("Material", self.mat_combo)
        form.addRow(self.lbl_E, self.e_E)
        form.addRow(self.lbl_sy, self.e_sy)
        form.addRow(self.lbl_su, self.e_su)
        lay.addLayout(form)
        self.units_note = self.note("")
        lay.addWidget(self.units_note)
        self.mat_note = self.note("Materials come from the shared library (materials.json); add your own in the 2D FEA tab. A member can "
                                  "pick another material in its table row.")
        lay.addWidget(self.mat_note)
        self.fill_materials(select="Structural steel (A36)")
        self.material_picked()
        self.mat_combo.currentIndexChanged.connect(self.material_picked)
        for e in (self.e_E, self.e_sy, self.e_su):
            e.textEdited.connect(self.set_custom)
            e.editingFinished.connect(self.changed)

        lay.addWidget(QLabel("<b>Joints</b> (select joints or members on the drawing first)"))
        row = QHBoxLayout()
        b = QPushButton("Rigid joint  (R)")
        b.setToolTip("The selected joints carry bending moment between the members that meet there (all members meeting at a selected "
                     "joint, or both ends of a selected member).")
        b.clicked.connect(lambda: self.set_joint(False))
        row.addWidget(b)
        b = QPushButton("Pinned joint  (J)")
        b.setToolTip("The members meeting at the selected joints can rotate freely there (they transmit no bending moment). A frame with "
                     "pinned joints everywhere is a truss.")
        b.clicked.connect(lambda: self.set_joint(True))
        row.addWidget(b)
        lay.addLayout(row)

        lay.addWidget(QLabel("<b>Supports and loads</b> (select joints / members first)"))
        row = QHBoxLayout()
        for text, mode, tip in (("Fixed  (F)", "fixed", "Holds x, y and rotation."), ("Pinned  (P)", "pinned", "Holds x and y; rotation is free."),
                                ("ux = 0  (X)", "x", "Holds x only (a roller that rolls in y)."),
                                ("uy = 0  (Y)", "y", "Holds y only (a roller that rolls in x).")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m_=mode: self.add_support(m_))
            row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        for text, fn, tip in (("Force...  (Shift+F)", self.add_force, "A force on each selected joint."),
                              ("Moment...  (M)", self.add_moment, "A moment on each selected joint (counter-clockwise positive)."),
                              ("Line load...  (D)", self.add_dist, "A uniform load per length on each selected member.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        for text, fn, tip in (("Wind...  (W)", lambda: self.add_pressure("wind"),
                               "Wind speed and direction on the selected members. Needs each member's in-plane depth (Depth column)."),
                              ("Snow...  (N)", lambda: self.add_pressure("snow"),
                               "Snow height and wetness on the selected members. Needs each member's in-plane depth (Depth column).")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("Tie point to member  (T)")
        b.setToolTip("Select one or more joints and the member they lie on (in the middle of it), then press this. The joint becomes part of "
                     "the member (the member is continuous through it), so other members that end there are connected to it.")
        b.clicked.connect(self.add_tie)
        row.addWidget(b)
        b = QPushButton("Remove selected tie")
        b.clicked.connect(self.remove_tie)
        row.addWidget(b)
        lay.addLayout(row)
        self.tie_table = QTableWidget(0, 3)
        self.tie_table.setHorizontalHeaderLabels(["Tied point", "Member", "At"])
        self.tie_table.verticalHeader().hide()
        self.tie_table.setMaximumHeight(90)
        self.tie_table.horizontalHeader().setStretchLastSection(True)
        self.tie_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tie_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.tie_table)
        lay.addWidget(self.note("Ties made by hand are listed above (automatic ones are counted in the line under the import buttons). "
                                "In the results a tied member is still ONE member."))
        lay.addWidget(self.note("Hotkeys work while the drawing has the keyboard focus (click in it first). Esc clears the selection."))
        self.cond_table = QTableWidget(0, 4)
        self.cond_table.setHorizontalHeaderLabels(["Name", "Type", "Applied to", "Value"])
        self.cond_table.verticalHeader().hide()
        self.cond_table.setMinimumHeight(110)
        self.cond_table.setMaximumHeight(200)
        self.cond_table.horizontalHeader().setStretchLastSection(True)
        self.cond_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cond_table.itemChanged.connect(self.cond_item_changed)
        lay.addWidget(self.cond_table)
        lay.addWidget(self.note("Double-click a Name to rename it (the Parameterization tab uses these names). Forces, moments and line loads "
                                "can be edited in the Value column (force: Fx, Fy; moment: Mz; line load: the two values you entered)."))
        row = QHBoxLayout()
        b = QPushButton("Edit selected wind / snow...")
        b.clicked.connect(self.edit_pressure)
        row.addWidget(b)
        b = QPushButton("Remove selected item")
        b.clicked.connect(self.remove_condition)
        row.addWidget(b)
        lay.addLayout(row)

        lay.addWidget(QLabel("<b>Results</b>"))
        self.cb_auto = QCheckBox("Solve automatically after every change")
        self.cb_auto.setChecked(True)
        self.cb_auto.setToolTip("A frame solves in a fraction of a second, so this is on by default.")
        lay.addWidget(self.cb_auto)
        self.b_solve = QPushButton("Solve")
        self.b_solve.clicked.connect(lambda: self.solve(auto=False))
        lay.addWidget(self.b_solve)
        self.view_combo = QComboBox()
        for text, key in VIEWS:
            self.view_combo.addItem(text, key)
        self.view_combo.setCurrentIndex(max(0, self.view_combo.findData("vm")))
        self.view_combo.currentIndexChanged.connect(self.view_changed)
        lay.addWidget(self.view_combo)
        row = QHBoxLayout()
        row.addWidget(QLabel("Colours"))
        self.cmap_combo = result_style.make_combo(self, self.view_changed)
        row.addWidget(self.cmap_combo, 1)
        lay.addLayout(row)
        self.cb_def = QCheckBox("Show deformed shape")
        self.cb_def.setChecked(True)
        self.cb_def.toggled.connect(self.view_changed)
        lay.addWidget(self.cb_def)
        row = QHBoxLayout()
        row.addWidget(QLabel("Deformation scale"))
        self.e_def = QLineEdit("")
        self.e_def.setPlaceholderText("auto")
        self.e_def.editingFinished.connect(self.view_changed)
        row.addWidget(self.e_def)
        lay.addLayout(row)
        self.cb_names = QCheckBox("Show member names")
        self.cb_names.toggled.connect(self.view_changed)
        lay.addWidget(self.cb_names)
        self.res_lbl = QLabel("")
        self.res_lbl.setWordWrap(True)
        self.res_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.res_lbl)
        b = QPushButton("Member report...")
        b.setToolTip("Every member's end forces, peaks and stresses as text you can copy.")
        b.clicked.connect(self.show_report)
        lay.addWidget(b)
        b = QPushButton("Zoom to fit")
        b.clicked.connect(self.canvas.fit)
        lay.addWidget(b)
        lay.addWidget(self.note("Beam theory (Euler-Bernoulli, linear elastic): bending and axial deformation, no shear deformation, no "
                                "buckling or second-order (P-delta) effects, no joint stress concentrations. The Euler column shows how close "
                                "a compressed member is to its pin-ended buckling load (1 or more = it would buckle). Use the 2D FEA tab "
                                "for local effects."))
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(left)
        scroll.setMinimumWidth(340)
        scroll.setMaximumWidth(420)
        scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        left.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        self.mem_table = QTableWidget(0, len(HEADERS))
        self.mem_table.setHorizontalHeaderLabels(HEADERS)
        self.mem_table.verticalHeader().hide()
        self.mem_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mem_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.mem_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mem_table.customContextMenuRequested.connect(self.member_menu)
        self.mem_table.itemChanged.connect(self.member_item_changed)
        self.mem_table.itemSelectionChanged.connect(self.table_selection_changed)
        sh = QShortcut(QKeySequence.StandardKey.Copy, self.mem_table)
        sh.setContext(Qt.ShortcutContext.WidgetShortcut)
        sh.activated.connect(self.copy_profile)
        sh = QShortcut(QKeySequence.StandardKey.Paste, self.mem_table)
        sh.setContext(Qt.ShortcutContext.WidgetShortcut)
        sh.activated.connect(self.paste_profile)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(6, 4, 6, 4)
        bl.addWidget(self.note("<b>Members.</b> Click Profile to make the cross-section of a member (or double-click the member in the "
                               "drawing). Right-click a row, or use Ctrl+C / Ctrl+V on selected rows, to copy a profile to other "
                               "members. Members without a profile are drawn dashed red and are left out of the analysis."))
        bl.addWidget(self.mem_table, 1)
        right = QSplitter(Qt.Orientation.Vertical)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right.addWidget(self.canvas)
        right.addWidget(bottom)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 1)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(scroll)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(split, 1)
        row = QHBoxLayout()
        row.setContentsMargins(6, 2, 6, 2)
        self.status_lbl = QLabel("")
        row.addWidget(self.status_lbl, 1)
        row.addWidget(self.coords)
        outer.addLayout(row)
        self.refresh_unit_labels()

    # ------------------------------------------------------------------------------------------
    # small helpers
    # ------------------------------------------------------------------------------------------
    @staticmethod
    def note(text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#555555; font-size:11px;")
        return lb

    def status(self, text):
        self.status_lbl.setText(text)
        try:
            self.win.status(text)
        except Exception:
            pass

    def unit_name(self):
        return self.model.unit_system if self.model is not None else self.cur_unit

    def U(self):
        return units.get(self.unit_name())

    def node_ids(self):
        out = set()
        for m in self.members:
            out.add(m["a"])
            out.add(m["b"])
        return out

    def node_xy(self):
        pts = self.model.pts if self.model is not None else {}
        ids = self.node_ids() or set(pts)
        return [tuple(pts[i]) for i in ids if i in pts]

    def model_size(self):
        xy = self.node_xy()
        if not xy:
            return 1.0
        xs, ys = [p[0] for p in xy], [p[1] for p in xy]
        return max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)

    def view_mode(self):
        return self.view_combo.currentData()

    def deform_scale(self, res):
        txt = self.e_def.text().strip()
        if txt:
            try:
                return float(txt)
            except ValueError:
                pass
        um = res.get("umax", 0.0) if res else 0.0
        return 0.1 * self.model_size() / um if um > 0 else 1.0

    def member_by_lid(self, lid):
        return next((m for m in self.members if m["lid"] == lid), None)

    def sel_points(self):
        return [i for k, i in self.canvas.sel if k == "pt" and i in self.node_ids()]

    def sel_lines(self):
        return [i for k, i in self.canvas.sel if k == "ln"]

    def selected_rows(self):
        return sorted({i.row() for i in self.mem_table.selectedIndexes()})

    def view_changed(self, *_):
        self.canvas.update()

    def enable_buttons(self):
        pass

    # ------------------------------------------------------------------------------------------
    # units and materials
    # ------------------------------------------------------------------------------------------
    def refresh_unit_labels(self):
        u = units.get(self.cur_unit)
        self.lbl_E.setText(f"E ({u['S']})")
        self.lbl_sy.setText(f"Yield strength ({u['S']})")
        self.lbl_su.setText(f"Ultimate strength ({u['S']})")
        self.units_note.setText(f"Units: {self.cur_unit}  (change in File > Units)")
        L, F, S = u["L"], u["F"], u["S"]
        heads = list(HEADERS)
        heads[5] = f"Length ({L})"
        heads[6] = f"Depth ({L})"
        heads[7], heads[8], heads[9] = f"N peak ({F})", f"V peak ({F})", f"M peak ({F} {L})"
        heads[10] = f"Max stress ({S})"
        self.mem_table.setHorizontalHeaderLabels(heads)

    def convert_input_units(self, new):
        """The boxes hold numbers in `self.cur_unit`; express them in `new` (same physical values)."""
        old = self.cur_unit
        if old == new or not units.valid(old) or not units.valid(new):
            self.cur_unit = new
            return
        self.convert_default_material(old, new)
        self.cur_unit = new

    def convert_default_material(self, old, new):
        name = self.mat_combo.currentData()
        m_ = self.library_entry(name) if name is not None else None
        if m_ is not None and m_.get("Sy_MPa") is not None and m_.get("Su_MPa") is not None:
            self.e_E.setText(f"{pm.from_mpa(m_['E_MPa'], new):.10g}")
            self.e_sy.setText(f"{pm.from_mpa(m_['Sy_MPa'], new):.10g}")
            self.e_su.setText(f"{pm.from_mpa(m_['Su_MPa'], new):.10g}")
            return
        f = units.stress_factor(old, new)
        for w in (self.e_E, self.e_sy, self.e_su):
            try:
                w.setText(f"{float(w.text()) * f:.10g}")
            except ValueError:
                pass

    def apply_units(self, name):
        if self.cur_unit != name:
            self.convert_input_units(name)
        self.cur_unit = name
        self.refresh_unit_labels()

    def fill_materials(self, select=None):
        self.library = pm.load()
        builtin = {n for n, _, _ in pm.DEFAULTS}
        keep = select if select is not None else self.mat_combo.currentData()
        self.mat_combo.blockSignals(True)
        self.mat_combo.clear()
        self.mat_combo.addItem("(custom values)", None)
        for m_ in self.library:
            self.mat_combo.addItem(m_["name"] + ("" if m_["name"] in builtin else "   (mine)"), m_["name"])
        i = self.mat_combo.findData(keep) if keep is not None else -1
        self.mat_combo.setCurrentIndex(max(0, i))
        self.mat_combo.blockSignals(False)

    def library_entry(self, name):
        return next((x for x in self.library if x["name"] == name), None)

    def material_picked(self, *_):
        name = self.mat_combo.currentData()
        m_ = self.library_entry(name) if name is not None else None
        if m_ is not None:
            u = self.cur_unit
            self.e_E.setText(f"{pm.from_mpa(m_['E_MPa'], u):.10g}")
            if m_.get("Sy_MPa") is not None and m_.get("Su_MPa") is not None:
                self.e_sy.setText(f"{pm.from_mpa(m_['Sy_MPa'], u):.10g}")
                self.e_su.setText(f"{pm.from_mpa(m_['Su_MPa'], u):.10g}")
        if self.model is not None:
            self.changed()

    def set_custom(self, *_):
        if self.mat_combo.currentIndex() != 0:
            self.mat_combo.blockSignals(True)
            self.mat_combo.setCurrentIndex(0)
            self.mat_combo.blockSignals(False)

    def showEvent(self, ev):
        super().showEvent(ev)
        try:
            self.fill_materials()                      # materials added in the 2D FEA tab appear here
            if self.members:
                self.fill_members()
        except Exception:
            pass

    @staticmethod
    def _num(edit, what, positive=True):
        try:
            v = float(edit.text())
        except ValueError:
            raise beam1d.BeamError(f"{what} must be a number.")
        if positive and not v > 0:
            raise beam1d.BeamError(f"{what} must be positive.")
        return v

    @staticmethod
    def _opt(edit):
        t = edit.text().strip()
        if not t:
            return None
        try:
            v = float(t)
        except ValueError:
            raise beam1d.BeamError("The yield and ultimate strengths must be numbers (or empty).")
        return v if v > 0 else None

    # ------------------------------------------------------------------------------------------
    # import
    # ------------------------------------------------------------------------------------------
    def import_picked(self, sid, text, name):
        m = sc.Model()
        m.from_json(text)
        self.set_model(m, name, keep=(sid == getattr(self, "sketch_id", None)))
        self.sketch_id = sid

    def import_current(self):
        self.picker.go()

    def clear_tab(self):
        """The Clear button: forget the imported sketch and this tab's setup, so the sketch can be imported again from scratch."""
        if self.model is None:
            self.status("Nothing to clear: no sketch is imported here.") if hasattr(self, "status") else None
            return
        if getattr(self, "worker", None) is not None:
            QMessageBox.information(self, "Clear", "A run is in progress on this tab. Stop it first.")
            return
        if QMessageBox.question(self, "Clear", "Remove the imported sketch and everything set up on this tab (supports, loads, results)? "
                                "The sketch itself is not touched.") != QMessageBox.StandardButton.Yes:
            return
        self.clear_state()
        param = getattr(self.win, "param", None)
        if param is not None:
            try:
                param.refresh_params()
            except Exception:
                pass

    def adopt_units(self, m):
        if getattr(self.win, "_restoring", False):
            return m                                   # a saved tab keeps its own units
        want = getattr(getattr(self.win, "m", None), "unit_system", None)
        if want and units.valid(want) and m.unit_system != want:
            try:
                m.convert_units(want, True)
            except ValueError:
                m.unit_system = want
        return m

    def unique_name(self, base, skip=None):
        taken = {m["name"] for m in self.members if m is not skip}
        if base not in taken:
            return base
        k = 2
        while f"{base} ({k})" in taken:
            k += 1
        return f"{base} ({k})"

    def set_model(self, m, source, keep=True):
        m = self.adopt_units(m)
        old = {mem["lid"]: mem for mem in self.members} if (keep and self.model is not None) else {}
        old_sup = self.supports if (keep and self.model is not None) else []
        old_loads = self.loads if (keep and self.model is not None) else []
        old_ties = self.ties if (keep and self.model is not None) else []
        self.model = m
        self.source = source
        self.apply_units(m.unit_system)
        self.members = []
        n_constr = n_zero = 0
        for lid in sorted(m.lns):
            if ("ln", lid) in m.constr:
                n_constr += 1
                continue
            a, b = m.lns[lid]
            if a == b or math.hypot(m.pts[b][0] - m.pts[a][0], m.pts[b][1] - m.pts[a][1]) <= 0:
                n_zero += 1
                continue
            o = old.get(lid)
            mem = {"lid": lid, "a": a, "b": b, "mat": copy.deepcopy(o["mat"]) if o else None,
                   "profile": copy.deepcopy(o["profile"]) if o else None, "rel_a": bool(o and o["rel_a"]), "rel_b": bool(o and o["rel_b"]),
                   "depth": o.get("depth") if o else None}
            mem["name"] = self.unique_name(o["name"] if o else f"Member {len(self.members) + 1}")
            self.members.append(mem)
        nodes = self.node_ids()
        lids = {mm["lid"] for mm in self.members}
        dropped = 0
        self.supports = []
        for s in old_sup:
            tg = [t for t in s["targets"] if t in nodes]
            dropped += len(s["targets"]) - len(tg)
            if tg:
                self.supports.append(dict(copy.deepcopy(s), targets=tg))
        self.loads = []
        for ld in old_loads:
            pool = lids if ld["kind"] in LINE_KINDS else nodes
            tg = [t for t in ld["targets"] if t in pool]
            dropped += len(ld["targets"]) - len(tg)
            if tg:
                self.loads.append(dict(copy.deepcopy(ld), targets=tg))
        self.ties = [dict(t) for t in old_ties if t["pt"] in nodes and t["lid"] in lids]
        self.result = None
        self.canvas.sel = []
        msg = f"Imported {source}: {len(self.members)} member(s), {len(nodes)} joint(s)."
        extra = []
        if n_constr:
            extra.append(f"{n_constr} construction line(s) ignored")
        if m.cis or m.ars:
            extra.append(f"{len(m.cis) + len(m.ars)} arc(s)/circle(s) ignored (only straight lines are members)")
        if n_zero:
            extra.append(f"{n_zero} zero-length line(s) ignored")
        if dropped:
            extra.append(f"{dropped} support/load target(s) on geometry that no longer exists were dropped")
        if extra:
            msg += " " + "; ".join(extra) + "."
        self.import_msg = msg
        self.stale = False
        self.refresh_ties()
        self.status(msg)
        self.fill_members()
        self.refresh_lists()
        self.notify_param()
        self.canvas.fit()
        self.changed()

    def connectivity_warnings(self):
        out = []
        pts = self.model.pts
        size = self.model_size()
        tol = 1e-4 * size
        for pid in sorted(self.node_ids()):
            x, y = pts[pid]
            for mem in self.members:
                if pid in (mem["a"], mem["b"]):
                    continue
                ax, ay = pts[mem["a"]]
                bx, by = pts[mem["b"]]
                dx, dy = bx - ax, by - ay
                L2 = dx * dx + dy * dy
                t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2)) if L2 > 0 else 0.0
                if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) < tol:
                    if (pid, mem["lid"]) in self.tie_map:
                        continue
                    out.append(f"point {pid} lies on {mem['name']} but is not one of its ends, so they are NOT connected (tick 'Connect "
                               "points that lie on members', or select the point and the member and press T)")
        ms = self.members
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                p1, p2, p3, p4 = pts[ms[i]["a"]], pts[ms[i]["b"]], pts[ms[j]["a"]], pts[ms[j]["b"]]
                if {ms[i]["a"], ms[i]["b"]} & {ms[j]["a"], ms[j]["b"]}:
                    continue

                def side(p, q, r):
                    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
                d1, d2, d3, d4 = side(p3, p4, p1), side(p3, p4, p2), side(p1, p2, p3), side(p1, p2, p4)
                if d1 * d2 < 0 and d3 * d4 < 0:
                    out.append(f"{ms[i]['name']} and {ms[j]['name']} cross without a shared point (they are not connected)")
        if len(out) > 6:
            out = out[:6] + [f"... and {len(out) - 6} more"]
        return out

    # ------------------------------------------------------------------------------------------
    # the members table
    # ------------------------------------------------------------------------------------------
    def fill_members(self):
        t = self.mem_table
        self.building = True
        t.blockSignals(True)
        t.clearSelection()
        t.setRowCount(len(self.members))
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        rw = ro | Qt.ItemFlag.ItemIsEditable
        for r, mem in enumerate(self.members):
            it = QTableWidgetItem(mem["name"])
            it.setFlags(rw)
            t.setItem(r, 0, it)
            cb = QComboBox()
            cb.addItem("(default)", None)
            for x in self.library:
                cb.addItem(x["name"], x["name"])
            want = mem["mat"]["name"] if mem["mat"] else None
            if want is not None and cb.findData(want) < 0:
                cb.addItem(f"{want} (not in the library)", want)
            cb.setCurrentIndex(max(0, cb.findData(want)))
            cb.currentIndexChanged.connect(lambda _i, r=r, cb=cb: self.member_material_changed(r, cb.currentData()))
            t.setCellWidget(r, 1, cb)
            btn = QPushButton(mem["profile"]["label"] if mem["profile"] else "Set profile...")
            if not mem["profile"]:
                btn.setStyleSheet("color:#b00020;")
            btn.clicked.connect(lambda _=False, r=r: self.edit_profile(r))
            t.setCellWidget(r, 2, btn)
            for col, key in ((3, "rel_a"), (4, "rel_b")):
                c2 = QComboBox()
                c2.addItems(["Rigid", "Pinned"])
                c2.setCurrentIndex(1 if mem[key] else 0)
                c2.currentIndexChanged.connect(lambda i, r=r, key=key: self.member_end_changed(r, key, i == 1))
                t.setCellWidget(r, col, c2)
            pa, pb = self.model.pts[mem["a"]], self.model.pts[mem["b"]]
            L = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
            it = QTableWidgetItem(f"{L:.5g}")
            it.setFlags(ro)
            t.setItem(r, 5, it)
            it = QTableWidgetItem("" if mem.get("depth") is None else f"{mem['depth']:.8g}")
            it.setFlags(rw)
            it.setToolTip("In-plane depth of the strip this member carries (its tributary width). Only wind and snow loads use it; "
                          "leave it empty otherwise.")
            t.setItem(r, COL_DEPTH, it)
            for col in range(COL_RES, len(HEADERS)):
                it = QTableWidgetItem("")
                it.setFlags(ro)
                t.setItem(r, col, it)
        t.resizeColumnsToContents()
        t.setColumnWidth(1, max(t.columnWidth(1), 150))
        t.setColumnWidth(2, max(t.columnWidth(2), 170))
        t.blockSignals(False)
        self.building = False
        self.update_member_results()

    def update_member_results(self):
        t = self.mem_table
        t.blockSignals(True)
        rm = {m["id"]: m for m in self.result["members"]} if self.result else {}
        for r, mem in enumerate(self.members):
            x = rm.get(mem["lid"])
            vals = [""] * RESULT_COLS
            bad = warn = False
            if x is not None:
                vals = [fmt(x["N_peak"]), fmt(x["V_peak"]), fmt(x["M_peak"]), fmt(x["sigma_max"]), fmt(x["fos_y"]) if x["fos_y"] else "n/a",
                        fmt(x["fos_u"]) if x["fos_u"] else "n/a", fmt(x["euler_ratio"]) if x["euler_ratio"] > 0 else "-"]
                bad = (x["fos_y"] is not None and x["fos_y"] < 1.0) or (x["fos_y"] is None and x["fos_u"] is not None and x["fos_u"] < 1.0)
                warn = x["euler_ratio"] >= 1.0
            for k, v in enumerate(vals):
                it = t.item(r, COL_RES + k)
                if it is None:
                    continue
                it.setText(v)
                it.setBackground(QBrush(QColor("#fde0e0")) if (bad and k in (3, 4, 5)) else QBrush(QColor("#fff3d6")) if (warn and k == 6) else QBrush())
        t.blockSignals(False)

    def member_item_changed(self, it):
        if self.building or it.column() not in (0, COL_DEPTH) or not (0 <= it.row() < len(self.members)):
            return
        mem = self.members[it.row()]
        if it.column() == COL_DEPTH:
            txt = it.text().strip()
            new = None
            if txt:
                try:
                    new = float(txt)
                    if new <= 0:
                        raise ValueError
                except ValueError:
                    self.status("The depth must be a number greater than zero (or empty).")
                    new = mem.get("depth")
            self.mem_table.blockSignals(True)
            it.setText("" if new is None else f"{new:.8g}")
            self.mem_table.blockSignals(False)
            if new != mem.get("depth"):
                mem["depth"] = new
                self.notify_param()
                self.changed()
            return
        new = it.text().strip() or mem["name"]
        new = self.unique_name(new, skip=mem)
        mem["name"] = new
        self.mem_table.blockSignals(True)
        it.setText(new)
        self.mem_table.blockSignals(False)
        self.refresh_lists()
        self.notify_param()
        self.changed()

    def member_material_changed(self, r, name):
        if self.building or not (0 <= r < len(self.members)):
            return
        mem = self.members[r]
        if name is None:
            mem["mat"] = None
        else:
            m_ = self.library_entry(name)
            if m_ is None:
                return
            u = self.cur_unit
            mem["mat"] = {"name": name, "E": pm.from_mpa(m_["E_MPa"], u),
                          "sy": pm.from_mpa(m_["Sy_MPa"], u) if m_.get("Sy_MPa") is not None else None,
                          "su": pm.from_mpa(m_["Su_MPa"], u) if m_.get("Su_MPa") is not None else None}
        self.changed()

    def member_end_changed(self, r, key, pinned):
        if self.building or not (0 <= r < len(self.members)):
            return
        self.members[r][key] = bool(pinned)
        self.changed()

    def table_selection_changed(self):
        if self.syncing or self.building:
            return
        self.canvas.sel = [("ln", self.members[r]["lid"]) for r in self.selected_rows() if r < len(self.members)]
        self.canvas.update()

    def selection_changed(self):
        """The drawing's selection changed: show the same members as selected rows."""
        if self.building:
            return
        self.syncing = True
        try:
            t = self.mem_table
            t.clearSelection()
            lids = {i for k, i in self.canvas.sel if k == "ln"}
            sm = t.selectionModel()
            for r, mem in enumerate(self.members):
                if mem["lid"] in lids:
                    sm.select(t.model().index(r, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        finally:
            self.syncing = False
        npt, nln = len(self.sel_points()), len(self.sel_lines())
        if npt or nln:
            self.status(f"Selected: {npt} joint(s), {nln} member(s).")

    # --- profiles
    def edit_profile_lid(self, lid):
        for r, m in enumerate(self.members):
            if m["lid"] == lid:
                self.edit_profile(r)
                return

    def edit_profile(self, r):
        if not (0 <= r < len(self.members)):
            return
        dlg = bd.ProfileDialog(self, r)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        prof = None if dlg.cleared else dlg.profile
        self.set_profiles(dlg.rows, prof)

    def set_profiles(self, rows, prof):
        for r in rows:
            if 0 <= r < len(self.members):
                self.members[r]["profile"] = copy.deepcopy(prof)
        self.fill_members()
        self.notify_param()
        self.changed()
        self.status(("Profile removed from " if prof is None else "Profile set on ") + f"{len(rows)} member(s).")

    def copy_profile(self):
        rows = self.selected_rows()
        r = rows[0] if rows else self.mem_table.currentRow()
        if not (0 <= r < len(self.members)) or not self.members[r]["profile"]:
            self.status("That member has no profile to copy.")
            return
        self.clip_profile = copy.deepcopy(self.members[r]["profile"])
        self.status(f"Copied the profile of {self.members[r]['name']}: {self.clip_profile['label']}.")

    def paste_profile(self, all_rows=False):
        if self.clip_profile is None:
            self.status("Nothing copied yet: select a member with a profile and press Ctrl+C (or right-click > Copy profile).")
            return
        rows = list(range(len(self.members))) if all_rows else self.selected_rows()
        if not rows:
            self.status("Select the members to paste onto first.")
            return
        self.set_profiles(rows, self.clip_profile)

    def member_menu(self, pos):
        r = self.mem_table.rowAt(pos.y())
        menu = QMenu(self)
        a = menu.addAction("Copy profile")
        a.triggered.connect(self.copy_profile)
        a = menu.addAction("Paste profile onto the selected members")
        a.triggered.connect(lambda: self.paste_profile(False))
        a.setEnabled(self.clip_profile is not None)
        a = menu.addAction("Paste profile onto all members")
        a.triggered.connect(lambda: self.paste_profile(True))
        a.setEnabled(self.clip_profile is not None)
        menu.addSeparator()
        a = menu.addAction("Edit profile...")
        a.triggered.connect(lambda: self.edit_profile(r))
        a.setEnabled(0 <= r < len(self.members))
        a = menu.addAction("Remove profile from the selected members")
        a.triggered.connect(lambda: self.set_profiles(self.selected_rows(), None))
        menu.exec(self.mem_table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------------------------------
    # joints, supports and loads
    # ------------------------------------------------------------------------------------------
    def handle_key(self, ev):
        """The constraint hotkeys (the drawing has the focus). -> True when the key was used."""
        if self.model is None:
            return False
        if ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        k = ev.key()
        K = Qt.Key
        if k == K.Key_F:
            self.add_force() if shift else self.add_support("fixed")
        elif shift:
            return False
        elif k == K.Key_P:
            self.add_support("pinned")
        elif k == K.Key_X:
            self.add_support("x")
        elif k == K.Key_Y:
            self.add_support("y")
        elif k == K.Key_M:
            self.add_moment()
        elif k == K.Key_D:
            self.add_dist()
        elif k == K.Key_W:
            self.add_pressure("wind")
        elif k == K.Key_N:
            self.add_pressure("snow")
        elif k == K.Key_T:
            self.add_tie()
        elif k == K.Key_R:
            self.set_joint(False)
        elif k == K.Key_J:
            self.set_joint(True)
        else:
            return False
        return True

    def need_points(self, what):
        pts = self.sel_points()
        if not pts:
            QMessageBox.information(self, what, "Select one or more joints on the drawing first (click; Ctrl-click or drag a box to add more).")
        return pts

    def set_joint(self, pinned):
        pts, lns = set(self.sel_points()), set(self.sel_lines())
        if not pts and not lns:
            QMessageBox.information(self, "Joint type", "Select joints (points) or members on the drawing first.")
            return
        n = 0
        for mem in self.members:
            if mem["lid"] in lns:
                mem["rel_a"] = mem["rel_b"] = pinned
                n += 2
                continue
            if mem["a"] in pts:
                mem["rel_a"] = pinned
                n += 1
            if mem["b"] in pts:
                mem["rel_b"] = pinned
                n += 1
        self.fill_members()
        self.changed()
        self.status(f"{n} member end(s) set to {'pinned' if pinned else 'rigid'}.")

    def add_support(self, mode):
        pts = self.need_points("Support")
        if not pts:
            return
        self.supports.append({"mode": mode, "targets": pts})
        self.after_conditions()

    def add_force(self):
        pts = self.need_points("Force")
        if not pts:
            return
        u = self.U()
        v = ask_numbers(self, "Force on each selected joint", [f"Fx ({u['F']})", f"Fy ({u['F']})"], [0, -1000],
                        note="The force is applied to EACH selected joint. Positive Fy pushes up.")
        if v is None:
            return
        if v[0] == 0 and v[1] == 0:
            QMessageBox.information(self, "Force", "Both components are zero.")
            return
        self.loads.append({"kind": "force", "fx": v[0], "fy": v[1], "targets": pts})
        self.after_conditions()

    def add_moment(self):
        pts = self.need_points("Moment")
        if not pts:
            return
        u = self.U()
        v = ask_numbers(self, "Moment on each selected joint", [f"Mz ({u['F']} {u['L']}), counter-clockwise positive"], [1000],
                        note="The moment is applied to EACH selected joint (it has no effect at a joint where every member is pinned).")
        if v is None or v[0] == 0:
            return
        self.loads.append({"kind": "moment", "mz": v[0], "targets": pts})
        self.after_conditions()

    def add_dist(self):
        lns = self.sel_lines()
        if not lns:
            QMessageBox.information(self, "Line load", "Select one or more members (lines) on the drawing first.")
            return
        last = next((ld for ld in reversed(self.loads) if ld["kind"] == "dist"), None)
        dlg = bd.DistDialog(self, last["frame"] if last else "global", last["q1"] if last else 0.0, last["q2"] if last else -1.0)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.loads.append({"kind": "dist", "frame": dlg.frame, "q1": dlg.q1, "q2": dlg.q2, "targets": lns})
        self.after_conditions()

    # --- ties: a point that lies inside a member becomes part of it
    def points_on_members(self):
        """[(point id, line id, position 0..1)] for every joint that lies inside a member (not at its ends)."""
        pts = self.model.pts
        tol = 1e-4 * self.model_size()
        out = []
        for pid in sorted(self.node_ids()):
            x, y = pts[pid]
            for mem in self.members:
                if pid in (mem["a"], mem["b"]):
                    continue
                ax, ay = pts[mem["a"]]
                bx, by = pts[mem["b"]]
                dx, dy = bx - ax, by - ay
                L2 = dx * dx + dy * dy
                if L2 <= 0:
                    continue
                L = math.sqrt(L2)
                t = ((x - ax) * dx + (y - ay) * dy) / L2
                if t * L <= tol or (1 - t) * L <= tol:
                    continue
                if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) < tol:
                    out.append((pid, mem["lid"], t))
        return out

    def refresh_ties(self, solve=False):
        """Works out which ties are in force (automatic ones when the box is ticked, plus the manual ones), then updates the lists."""
        if self.model is None:
            self.tie_map = {}
            return
        on = {(p, l): t for p, l, t in self.points_on_members()}
        tm = dict(on) if self.cb_tie.isChecked() else {}
        for tie in self.ties:
            k = (tie["pt"], tie["lid"])
            if k in on:
                tm[k] = on[k]
        self.tie_map = tm
        self.fill_ties()
        self.update_info()
        self.canvas.update()
        if solve:
            self.changed()

    def tie_pids(self):
        return {p for p, _ in self.tie_map}

    def fill_ties(self):
        t = self.tie_table
        t.setRowCount(len(self.ties))
        for r, tie in enumerate(self.ties):
            mem = self.member_by_lid(tie["lid"])
            pos = self.tie_map.get((tie["pt"], tie["lid"]))
            for c, txt in enumerate((f"Point {tie['pt']}", mem["name"] if mem else "?",
                                     f"{100 * pos:.1f} % along" if pos is not None else "not on the member any more (ignored)")):
                t.setItem(r, c, QTableWidgetItem(txt))

    def update_info(self):
        if self.model is None:
            return
        txt = self.import_msg
        auto = sum(1 for k in self.tie_map if not any(k == (x["pt"], x["lid"]) for x in self.ties))
        if auto:
            txt += f"<br>{auto} point(s) tied to the members they lie on (automatic)."
        warn = self.connectivity_warnings()
        if warn:
            txt += "<br><span style='color:#b36b00'>WARNING: " + "<br>".join(warn) + "</span>"
        if self.stale:
            txt = ("<b style='color:#b36b00'>OUT OF DATE: the sketch has changed since this was saved. This tab still shows the "
                   "older copy. Import the sketch again to update it (profiles, supports and loads of the lines that still exist are "
                   "kept).</b><br>") + txt
        self.info.setText(txt)

    def ties_changed(self, *_):
        if self.model is not None:
            self.refresh_ties(solve=True)

    def add_tie(self):
        if self.model is None:
            return
        pts, lns = self.sel_points(), self.sel_lines()
        if not pts or not lns:
            QMessageBox.information(self, "Tie", "Select one or more joints AND the member they lie on (click; Ctrl-click to add), then press Tie.")
            return
        on = {(p, l) for p, l, _t in self.points_on_members()}
        added, bad = 0, []
        for p in pts:
            hit = False
            for lid in lns:
                if (p, lid) in on:
                    hit = True
                    if not any(t["pt"] == p and t["lid"] == lid for t in self.ties):
                        self.ties.append({"pt": p, "lid": lid})
                        added += 1
            if not hit:
                bad.append(p)
        if bad:
            QMessageBox.information(self, "Tie", "Point " + ", ".join(str(b) for b in bad) + " does not lie on a selected member (it has to lie "
                                    "in the middle of the line, not at an end and not off to the side).")
        if added:
            self.status(f"{added} tie(s) made.")
        self.refresh_ties(solve=True)

    def remove_tie(self):
        r = self.tie_table.currentRow()
        if 0 <= r < len(self.ties):
            del self.ties[r]
            self.refresh_ties(solve=True)

    # --- wind and snow
    def pressure_calc(self, ld, depths=None):
        """-> (pressure in the stress unit, rows).  Each row: lid, name, depth, factor, vec (qx, qy per length, or None without a depth).
        `depths` {lid: depth} overrides the depths stored on the members."""
        p, _pa = loads1d.pressure(ld, self.cur_unit)
        rows = []
        for lid in ld["targets"]:
            mem = self.member_by_lid(lid)
            if mem is None:
                continue
            pa, pb = self.model.pts[mem["a"]], self.model.pts[mem["b"]]
            L = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
            if L <= 0:
                continue
            c, s_ = (pb[0] - pa[0]) / L, (pb[1] - pa[1]) / L
            depth = (depths or {}).get(lid, mem.get("depth"))
            row = {"lid": lid, "name": mem["name"], "depth": depth, "vec": None, "factor": 0.0}
            if ld["kind"] == "wind":
                a = math.radians(ld["angle"])
                d = math.cos(a) * -s_ + math.sin(a) * c
                row["factor"] = d * abs(d)
            else:
                row["factor"] = abs(c)
            if depth is not None:
                row["vec"] = loads1d.member_vec(ld, c, s_, p, depth)
            rows.append(row)
        return p, rows

    def pressure_vectors(self, ld):
        """{lid: (qx, qy)} of a wind / snow load, for the drawing (members without a depth are left out)."""
        return {r["lid"]: r["vec"] for r in self.pressure_calc(ld)[1] if r["vec"] is not None}

    def add_pressure(self, kind):
        lns = self.sel_lines()
        if not lns:
            QMessageBox.information(self, "Wind" if kind == "wind" else "Snow", "Select one or more members (lines) on the drawing first.")
            return
        last = next((ld for ld in reversed(self.loads) if ld["kind"] == kind), None)
        dlg = bd.PressureDialog(self, kind, lns, last)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.apply_depth(dlg.targets, dlg.depth)
        ld = dict(dlg.values)
        ld["targets"] = list(dlg.targets)
        self.loads.append(ld)
        self.fill_members()
        self.after_conditions()

    def edit_pressure(self):
        r = self.cond_table.currentRow() - len(self.supports)
        if not (0 <= r < len(self.loads)) or self.loads[r]["kind"] not in ("wind", "snow"):
            QMessageBox.information(self, "Edit", "Select a wind or snow row in the table first.")
            return
        ld = self.loads[r]
        dlg = bd.PressureDialog(self, ld["kind"], ld["targets"], ld)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.apply_depth(dlg.targets, dlg.depth)
        keep = {k: v for k, v in ld.items() if k == "name"}
        self.loads[r] = dict(dlg.values, targets=list(dlg.targets), **keep)
        self.fill_members()
        self.after_conditions()

    def apply_depth(self, targets, depth):
        if depth is None:
            return
        for lid in targets:
            mem = self.member_by_lid(lid)
            if mem is not None:
                mem["depth"] = depth

    def after_conditions(self):
        self.refresh_lists()
        self.notify_param()
        self.changed()

    def notify_param(self):
        param = getattr(self.win, "param", None)
        if param is not None:
            try:
                param.refresh_params()
            except Exception:
                pass

    # --- the conditions table
    def target_names(self, item, is_sup):
        if not is_sup and item["kind"] in LINE_KINDS:
            return ", ".join((self.member_by_lid(t) or {"name": f"line {t}"})["name"] for t in item["targets"])
        return ", ".join(f"Point {t}" for t in item["targets"])

    def default_name(self, is_sup, idx):
        items = self.supports if is_sup else self.loads
        key = "mode" if is_sup else "kind"
        base = (SUP_NAME if is_sup else LOAD_NAME)[items[idx][key]]
        same = [j for j, x in enumerate(items) if x[key] == items[idx][key]]
        return f"{base} {same.index(idx) + 1}"

    def cond_name(self, is_sup, idx):
        items = self.supports if is_sup else self.loads
        return items[idx].get("name") or self.default_name(is_sup, idx)

    def cond_value_text(self, item, is_sup):
        if is_sup:
            return ""
        k = item["kind"]
        if k == "force":
            return f"{item['fx']:.10g}, {item['fy']:.10g}"
        if k == "moment":
            return f"{item['mz']:.10g}"
        if k == "wind":
            return f"{item['V']:.6g} {self.U()['V']}, {item['angle']:.6g} deg, Cp {item['cp']:.4g}"
        if k == "snow":
            return f"{item['h']:.6g} {self.U()['L']} at {item['rho']:.5g} {self.U()['rho']}"
        return f"{item['q1']:.10g}, {item['q2']:.10g}"

    def refresh_lists(self):
        t = self.cond_table
        t.blockSignals(True)
        t.setRowCount(len(self.supports) + len(self.loads))
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        rw = ro | Qt.ItemFlag.ItemIsEditable
        u = self.U()
        r = 0
        for i, s in enumerate(self.supports):
            self.fill_cond_row(r, True, i, SUP_LONG[s["mode"]], s, ro, rw)
            r += 1
        for k, ld in enumerate(self.loads):
            if ld["kind"] == "force":
                typ = f"Force ({u['F']}) on each"
            elif ld["kind"] == "moment":
                typ = f"Moment ({u['F']} {u['L']}) on each"
            elif ld["kind"] == "wind":
                typ = "Wind (linked to the member depths)"
            elif ld["kind"] == "snow":
                typ = "Snow (linked to the member depths)"
            else:
                typ = f"Line load ({u['F']}/{u['L']}, " + ("x, y)" if ld["frame"] == "global" else "along, across)")
            self.fill_cond_row(r, False, k, typ, ld, ro, rw)
            r += 1
        t.resizeColumnsToContents()
        t.blockSignals(False)

    def fill_cond_row(self, r, is_sup, idx, typ, item, ro, rw):
        t = self.cond_table
        a = QTableWidgetItem(self.cond_name(is_sup, idx))
        a.setFlags(rw)
        b = QTableWidgetItem(typ)
        b.setFlags(ro)
        c = QTableWidgetItem(self.target_names(item, is_sup))
        c.setFlags(ro)
        val = self.cond_value_text(item, is_sup)
        d = QTableWidgetItem(val)
        d.setFlags(rw if (val and item.get("kind") not in ("wind", "snow")) else ro)
        for col, it in enumerate((a, b, c, d)):
            t.setItem(r, col, it)

    def cond_item_changed(self, it):
        r, c = it.row(), it.column()
        if c == 0:
            self.rename_condition(r, it.text())
        elif c == 3:
            self.set_condition_value(r, it.text())

    def _cond_ref(self, r):
        n = len(self.supports)
        return (True, r, self.supports[r]) if r < n else (False, r - n, self.loads[r - n])

    def rename_condition(self, r, text):
        if not (0 <= r < len(self.supports) + len(self.loads)):
            return
        is_sup, idx, item = self._cond_ref(r)
        text = text.strip()
        if text and text != self.default_name(is_sup, idx):
            item["name"] = text
        else:
            item.pop("name", None)
        self.cond_table.blockSignals(True)
        self.cond_table.item(r, 0).setText(self.cond_name(is_sup, idx))
        self.cond_table.blockSignals(False)
        self.notify_param()

    def set_condition_value(self, r, text):
        if not (0 <= r < len(self.supports) + len(self.loads)):
            return False
        is_sup, idx, item = self._cond_ref(r)
        if is_sup:
            return False
        try:
            nums = [float(x) for x in text.replace(";", ",").split(",") if x.strip()]
            if item["kind"] == "force":
                assert len(nums) == 2
                new = {"fx": nums[0], "fy": nums[1]}
            elif item["kind"] == "moment":
                assert len(nums) == 1
                new = {"mz": nums[0]}
            else:
                assert len(nums) == 2
                new = {"q1": nums[0], "q2": nums[1]}
        except (AssertionError, ValueError):
            self.status("That value was not understood: give one number (moment) or two separated by a comma (force, line load).")
            QTimer.singleShot(0, self.refresh_lists)
            return False
        if any(item.get(k) != v for k, v in new.items()):
            item.update(new)
            QTimer.singleShot(0, self.after_conditions)
        return True

    def remove_condition(self):
        r = self.cond_table.currentRow()
        if not (0 <= r < len(self.supports) + len(self.loads)):
            return
        if r < len(self.supports):
            del self.supports[r]
        else:
            del self.loads[r - len(self.supports)]
        self.after_conditions()

    # ------------------------------------------------------------------------------------------
    # solving
    # ------------------------------------------------------------------------------------------
    def member_material(self, mem, ov=None):
        """-> (E, sy, su) of a member; `ov` can override the default material (Parameterization)."""
        if mem["mat"]:
            m = mem["mat"]
            return float(m["E"]), m.get("sy"), m.get("su")
        E = self._num(self.e_E, "E")
        sy, su = self._opt(self.e_sy), self._opt(self.e_su)
        if ov:
            E = ov.get("E", E)
            sy = ov.get("sy", sy)
            su = ov.get("su", su)
        return E, sy, su

    def build_input(self, ov=None):
        """-> (nodes, members, supports, nodal loads, notes, names of the members left out).  `ov` (Parameterization):
        {"loads": {index: {key: value}}, "dims": {line id: {dimension: value}}, "E"/"sy"/"su": default material}."""
        ov = ov or {}
        notes = []
        used = []
        left_out = []
        for mem in self.members:
            prof = mem["profile"]
            dims = ov.get("dims", {}).get(mem["lid"])
            if prof and dims:
                for k, v in dims.items():
                    if k != "depth":
                        prof = pr1.with_dim(prof, k, v)
            if prof is None:
                left_out.append(mem["name"])
                continue
            E, sy, su = self.member_material(mem, ov)
            used.append({"id": mem["lid"], "name": mem["name"], "a": mem["a"], "b": mem["b"], "E": E, "A": prof["A"], "I": prof["I"],
                         "c_top": prof["c_top"], "c_bottom": prof["c_bottom"], "sy": sy, "su": su, "rel_a": mem["rel_a"],
                         "rel_b": mem["rel_b"], "qg": [0.0, 0.0], "ql": [0.0, 0.0]})
        if left_out:
            notes.append("Left out of the analysis because they have no profile: " + ", ".join(left_out) + ".")
        nodes = {}
        for m in used:
            for pid in (m["a"], m["b"]):
                nodes[pid] = tuple(self.model.pts[pid])
        for (pid, lid_) in self.tie_map:                      # tie points are joints too (loads and supports can sit on them)
            if any(m["id"] == lid_ for m in used):
                nodes[pid] = tuple(self.model.pts[pid])
        by_lid = {m["id"]: m for m in used}
        depth_ov = {lid: d_["depth"] for lid, d_ in ov.get("dims", {}).items() if "depth" in d_}
        nodal = {}
        for i, ld in enumerate(self.loads):
            vals = dict(ld)
            vals.update(ov.get("loads", {}).get(i, {}))
            nm = self.cond_name(False, i)
            if ld["kind"] in ("force", "moment"):
                gone = [t for t in ld["targets"] if t not in nodes]
                if gone:
                    notes.append(f"'{nm}': {len(gone)} joint(s) are not part of the analysed members and were ignored.")
                for pid in ld["targets"]:
                    if pid in nodes:
                        f = nodal.get(pid, (0.0, 0.0, 0.0))
                        if ld["kind"] == "force":
                            nodal[pid] = (f[0] + vals["fx"], f[1] + vals["fy"], f[2])
                        else:
                            nodal[pid] = (f[0], f[1], f[2] + vals["mz"])
            elif ld["kind"] in ("wind", "snow"):
                p_, rows_ = self.pressure_calc(vals, depth_ov)
                gone = [t for t in ld["targets"] if t not in by_lid]
                nodepth = []
                for r_ in rows_:
                    m = by_lid.get(r_["lid"])
                    if m is None:
                        continue
                    if r_["vec"] is None:
                        nodepth.append(r_["name"])
                        continue
                    m["qg"] = [m["qg"][0] + r_["vec"][0], m["qg"][1] + r_["vec"][1]]
                if nodepth:
                    notes.append(f"'{nm}': no depth on {', '.join(nodepth)}, so they get no {ld['kind']} load (fill the Depth column).")
                if gone:
                    notes.append(f"'{nm}': {len(gone)} member(s) are not part of the analysis and were ignored.")
            else:
                gone = 0
                for lid in ld["targets"]:
                    m = by_lid.get(lid)
                    if m is None:
                        gone += 1
                        continue
                    key = "qg" if ld["frame"] == "global" else "ql"
                    m[key] = [m[key][0] + vals["q1"], m[key][1] + vals["q2"]]
                if gone:
                    notes.append(f"'{nm}': {gone} member(s) are not part of the analysis and were ignored.")
        sups = {}
        for i, s in enumerate(self.supports):
            flags = SUP_FLAGS[s["mode"]]
            for pid in s["targets"]:
                if pid in nodes:
                    old = sups.get(pid, (False, False, False))
                    sups[pid] = tuple(a or b for a, b in zip(old, flags))
        used = self.split_at_ties(used, nodes, notes)
        return nodes, used, sups, nodal, notes, left_out

    def split_at_ties(self, used, nodes, notes):
        """Members with tie points become pieces (same properties and loads); the solver merges them back in the results."""
        by = {}
        for (pid, lid), t in self.tie_map.items():
            if pid in nodes or any(m["id"] == lid for m in used):
                by.setdefault(lid, []).append((t, pid))
        out = []
        for m in used:
            cuts = sorted(by.get(m["id"], []))
            if not cuts:
                out.append(m)
                continue
            chain = [m["a"]] + [pid for _t, pid in cuts] + [m["b"]]
            for pid in chain:
                if pid not in nodes:
                    nodes[pid] = tuple(self.model.pts[pid])
            for k in range(len(chain) - 1):
                pc = dict(m)
                pc.update({"id": (m["id"], k), "group": m["id"], "a": chain[k], "b": chain[k + 1],
                           "rel_a": m["rel_a"] if k == 0 else False, "rel_b": m["rel_b"] if k == len(chain) - 2 else False,
                           "qg": list(m["qg"]), "ql": list(m["ql"])})
                out.append(pc)
        return out

    def clear_result_text(self, html):
        self.res_lbl.setText(html)

    def changed(self, *_):
        """An input changed: the old result no longer applies."""
        self.result = None
        if self.model is None:
            return
        if self.cb_auto.isChecked():
            self.solve(auto=True)
        else:
            self.res_lbl.setText("<i>Inputs changed. Press Solve.</i>")
            self.update_member_results()
            self.canvas.update()

    def solve(self, auto=False):
        if self.model is None:
            return False
        self.result = None
        self.problem_members, self.problem_nodes = set(), set()
        problem = None
        try:
            nodes, mems, sups, nodal, notes, left_out = self.build_input()
            self.notes_in = notes
            if not self.members:
                problem = "The sketch has no lines to use as members."
            elif not mems:
                problem = "Give the members a profile (the Profile button in the members table) to analyse them."
            elif not sups:
                problem = "Add at least one support (select a joint, then Fixed / Pinned / ux = 0 / uy = 0)."
            if problem is None:
                self.result = beam1d.solve(nodes, mems, sups, nodal)
                self.result["notes"] = list(notes) + list(self.result.get("notes", []))
                self.result["excluded"] = left_out
        except beam1d.BeamError as ex:
            problem = str(ex)
            self.problem_members = set(ex.members)
            self.problem_nodes = set(ex.nodes)
        except Exception:
            problem = "Unexpected error while solving:\n" + traceback.format_exc()
        if problem is not None:
            self.result = None
            self.res_lbl.setText(f"<span style='color:#b36b00'>{problem}</span>")
            if not auto:
                QMessageBox.warning(self, "Solve", problem)
            self.update_member_results()
            self.canvas.update()
            return False
        self.show_summary()
        self.update_member_results()
        self.canvas.update()
        return True

    def show_summary(self):
        r = self.result
        u = self.U()
        L = [f"<b>Solved</b>: {len(r['members'])} member(s), {len(r['nodes'])} joint(s)."]
        L.append(f"Largest displacement: <b>{r['umax']:.5g} {u['L']}</b> ({r['umax_member']}).")
        L.append(f"Largest fibre stress: <b>{r['sigma_max']:.5g} {u['S']}</b> ({r['sigma_member']}).")
        for key, lab in (("fos_y", "yield"), ("fos_u", "ultimate")):
            v = r.get(key)
            if v is None:
                L.append(f"Factor of safety, {lab}: not available (no {lab} strength).")
            else:
                col = "#b00020" if v < 1 else "#1a7f37"
                L.append(f"Lowest factor of safety, {lab}: <b style='color:{col}'>{v:.3g}</b> ({r[key + '_member']}).")
        L.append(f"Peaks: N = {r['N_peak']:.5g} {u['F']} ({r['N_member']}), V = {r['V_peak']:.5g} {u['F']} ({r['V_member']}), "
                 f"M = {r['M_peak']:.5g} {u['F']} {u['L']} ({r['M_member']}).")
        if r["euler_max"] >= 1.0:
            L.append("<b style='color:#b36b00'>A compressed member is at or beyond its Euler buckling load: this analysis does not include "
                     "buckling.</b>")
        elif r["euler_max"] > 0:
            L.append(f"Most compressed member: {100 * r['euler_max']:.1f} % of its Euler (pin-ended) buckling load.")
        if r["reactions"]:
            L.append("<b>Reactions</b> (" + f"{u['F']}, {u['F']} {u['L']}):")
            for pid, (rx, ry, mz) in sorted(r["reactions"].items()):
                L.append(f"Point {pid}: Rx = {rx:.5g}, Ry = {ry:.5g}" + (f", Mz = {mz:.5g}" if mz else ""))
        eq = r["equilibrium"]
        L.append(f"Equilibrium check: residual {eq['relative']:.1e} of the largest load or reaction.")
        for n in r.get("notes", []):
            L.append(f"<span style='color:#b36b00'>{n}</span>")
        self.res_lbl.setText("<br>".join(L))

    def show_report(self):
        if self.result is None:
            QMessageBox.information(self, "Member report", "There is no result yet.")
            return
        r = self.result
        u = self.U()
        out = ["1D FEA - MEMBER REPORT", time.strftime("%Y-%m-%d %H:%M:%S"), f"Units: {self.unit_name()}", ""]
        for m in r["members"]:
            F = m["F"]
            out += [f"{m['name']}   (points {m['a']} -> {m['b']}, length {m['L']:.6g} {u['L']})",
                    f"  E = {m['E']:.6g} {u['S']}   A = {m['A']:.6g}   I = {m['I']:.6g}   c = {m['c_top']:.5g} / {m['c_bottom']:.5g}",
                    f"  ends: {'pinned' if m['rel_a'] else 'rigid'} at A, {'pinned' if m['rel_b'] else 'rigid'} at B",
                    f"  force on the member at A: N {F[0]:.6g}, V {F[1]:.6g}, M {F[2]:.6g}",
                    f"  force on the member at B: N {F[3]:.6g}, V {F[4]:.6g}, M {F[5]:.6g}   (local axes, counter-clockwise moments)",
                    f"  peaks: N {m['N_peak']:.6g}, V {m['V_peak']:.6g}, M {m['M_peak']:.6g}; largest stress {m['sigma_max']:.6g} {u['S']}; "
                    f"displacement {m['umax']:.6g} {u['L']}",
                    f"  FoS yield {fmt(m['fos_y']) or 'n/a'}, ultimate {fmt(m['fos_u']) or 'n/a'}; Euler N/Pcr {m['euler_ratio']:.4g}", ""]
        out.append("Joint displacements (ux, uy, rotation):")
        for pid, (ux, uy, rz) in sorted(r["nodes"].items()):
            out.append(f"  Point {pid}: {ux:.6g}, {uy:.6g}, {rz:.6g}")
        dlg = QDialog(self)
        dlg.setWindowTitle("Member report")
        dlg.resize(760, 600)
        lay = QVBoxLayout(dlg)
        box = QTextEdit()
        box.setReadOnly(True)
        box.setFont(QFont("Consolas", 9))
        box.setPlainText("\n".join(out))
        lay.addWidget(box)
        b = QPushButton("Copy to clipboard")
        b.clicked.connect(lambda: QGuiApplication.clipboard().setText(box.toPlainText()))
        lay.addWidget(b)
        dlg.exec()

    # ------------------------------------------------------------------------------------------
    # Parameterization support (the main thread builds the inputs, a worker thread only runs beam1d.solve on them)
    # ------------------------------------------------------------------------------------------
    def make_spec(self, ov=None):
        nodes, mems, sups, nodal, notes, left_out = self.build_input(ov)
        if not mems:
            raise beam1d.BeamError("No member has a profile.")
        if not sups:
            raise beam1d.BeamError("The 1D FEA tab has no supports.")
        return {"args": (nodes, copy.deepcopy(mems), sups, nodal), "notes": notes, "excluded": left_out}

    def load_case(self, result):
        """Shows a result computed by the Parameterization tab."""
        self.result = result
        self.show_summary()
        self.update_member_results()
        self.canvas.update()
        self.status("Showing a Parameterization case (the inputs on the left may differ). Change anything to solve the current inputs again.")

    # ------------------------------------------------------------------------------------------
    # save / restore with the sketch file, units
    # ------------------------------------------------------------------------------------------
    def export_state(self):
        return {"model_json": self.model.to_json(), "source": self.source, "inputs": pstore.get_inputs(self, self.INPUTS),
                "cur_unit": self.cur_unit, "material": self.mat_combo.currentData(), "members": copy.deepcopy(self.members),
                "supports": copy.deepcopy(self.supports), "loads": copy.deepcopy(self.loads),
                "ties": copy.deepcopy(self.ties), "auto_tie": self.cb_tie.isChecked(), "sketch_id": getattr(self, "sketch_id", None)}

    def import_state(self, st, out_of_date=False):
        m = sc.Model()
        m.from_json(st["model_json"])
        self.cb_tie.blockSignals(True)
        self.cb_tie.setChecked(bool(st.get("auto_tie", True)))
        self.cb_tie.blockSignals(False)
        self.set_model(m, st.get("source") or "the saved sketch", keep=False)
        self.sketch_id = st.get("sketch_id")
        pstore.set_inputs(self, st.get("inputs", {}))
        self.cur_unit = st.get("cur_unit", self.cur_unit)
        self.refresh_unit_labels()
        self.mat_combo.blockSignals(True)
        i = self.mat_combo.findData(st.get("material"))
        self.mat_combo.setCurrentIndex(i if i >= 0 else 0)
        self.mat_combo.blockSignals(False)
        saved = {x["lid"]: x for x in st.get("members", [])}
        for mem in self.members:
            o = saved.get(mem["lid"])
            if o:
                for k in ("name", "mat", "profile", "rel_a", "rel_b", "depth"):
                    mem[k] = copy.deepcopy(o.get(k))
        nodes = self.node_ids()
        lids = {mm["lid"] for mm in self.members}
        self.supports = [dict(copy.deepcopy(s), targets=[t for t in s["targets"] if t in nodes]) for s in st.get("supports", [])]
        self.supports = [s for s in self.supports if s["targets"]]
        self.loads = []
        for ld in st.get("loads", []):
            pool = lids if ld["kind"] in LINE_KINDS else nodes
            tg = [t for t in ld["targets"] if t in pool]
            if tg:
                self.loads.append(dict(copy.deepcopy(ld), targets=tg))
        self.ties = [dict(t) for t in st.get("ties", []) if t["pt"] in nodes and t["lid"] in lids]
        self.refresh_ties()
        self.fill_members()
        self.refresh_lists()
        self.canvas.fit()
        self.changed()
        self.status("Restored the saved 1D FEA setup.")
        if out_of_date:
            self.mark_out_of_date()

    def change_units(self, old, new, convert):
        """The program's unit system changed: this tab's copy of the sketch, its numbers and loads follow. The result is solved again."""
        st = pstore.convert_beam_state(self.export_state(), old, new, convert)
        self.import_state(st)
        return ""

    def mark_out_of_date(self):
        self.stale = True
        self.update_info()

    def clear_state(self):
        self.model = None
        self.sketch_id = None
        self.source = ""
        self.members, self.supports, self.loads = [], [], []
        self.ties, self.tie_map, self.import_msg, self.stale = [], {}, "", False
        self.problem_members, self.problem_nodes = set(), set()
        self.tie_table.setRowCount(0)
        self.result = None
        self.notes_in = []
        self.canvas.sel = []
        self.building = True
        self.mem_table.setRowCount(0)
        self.cond_table.setRowCount(0)
        self.building = False
        self.info.setText("Nothing imported yet.")
        self.res_lbl.setText("")
        self.canvas.update()
