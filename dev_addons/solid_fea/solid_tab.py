"""
solid_tab.py - the 3D FEA window (project folder .gpv): a parametric part, or an ASSEMBLY - fully bonded (faces within the bond distance are joined);
every body keeps its own material.  Linear elastic, quadratic tetrahedra (or a hex-dominant mesh for a single part).

Project bar:  the name of what it works on, and Save   (the same project folder machinery as the 1D / 2D simulations: the Workbench copies the wired block in;
              the part is COPIED into  source/  and the simulation only uses the copy)
Left panel:   the sections of 1D FEA: Geometry (part dimensions you can edit), Material, Supports, Loads, Mesh, then Solve, [parametric study] and
              Results (result, Colours, deformed shape, scale, Animate with Play / Export, the Probe)
Right:        the part in 3D with the X / Y / Z triad bottom-left and the colour legend top-right; click a face to pick it (the Faces list
              does the same without the mouse)

The window is also the 'tab' the parametric studies talk to (study_adapter), so it offers export_state / import_state / unit_name.

What it has in common with the other 3D windows (project, geometry, faces, splits, assemblies, mesh, jobs, save / open) is in solid_base.SolidBase;
this file is what is particular to elasticity: the material, the supports and loads, the adaptive mesh, the results.
"""
import json
import os

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import anim_export
import physics_materials as pm
import result_style
import sim_disp
import sim_matdlg
import sim_report as R
import sim_ui
import solid_adapt as sad
import solid_fem as fem
import solid_geom as sg
import solid_mesh as smesh
import solid_model as sm
import solid_view as sv
import unitctl
from solid_base import SolidBase, UD, l_in, l_out, num                  # UD and l_out are also what the tests import from here

# the results the "Result" box offers (key, name); displacement magnitude first, as in 1D FEA.  Units are added to the names by refresh_labels().
FIELDS = [("umag", "Displacement magnitude"), ("ux", "Displacement X"), ("uy", "Displacement Y"), ("uz", "Displacement Z"),
          ("vm", "Von Mises stress"), ("fos", "Safety factor (yield)")]
ADAPT_TIP = ("Solve, find where the mesh is too coarse (from the solution itself), mesh again with smaller elements only there, and solve again - until the "
             "number you choose to watch changes by less than the tolerance between two loops. Your element size is the first mesh (loop 0). For a single "
             "part or bonded parts, with tetrahedra.")
FOS_LOW, FOS_HIGH = 0.5, 3.0                 # the safety-factor colours, as in 1D FEA: red at or below FOS_LOW, blue at or above FOS_HIGH


# --- the stress / force / density converters (the length ones, UD, l_out and l_in, are in solid_base).  The solver works in mm / N / MPa / kg per m3.
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



class SolidWindow(SolidBase):
    kind = "solid"
    label = "3D FEA"
    SUPPORT_TYPES = {"fixed": "Fixed", "disp": "Displacement", "slide": "One direction (normal)", "bearing": "Bearing"}
    CONDITION_KINDS = sm.CONDITION_KINDS

    # ------------------------------------------------------------------ what SolidBase asks the elasticity window for (its hooks)
    def new_setup(self):
        s = sm.default_setup()
        s["dims"] = {}
        return s

    def build_mesh_extras(self, v):
        self.build_adaptive(v)

    def put_mesh_extras(self):
        self.put_adapt()

    def read_mesh_more(self):
        self.read_adapt()

    def read_physics(self):
        out = {"E": s_in(num(self.e_E, "E")), "nu": num(self.e_nu, "Poisson's ratio"), "rho": r_in(num(self.e_rho, "Density")),
               "sy": s_in(num(self.e_sy, "Yield strength")), "su": s_in(num(self.e_su, "Ultimate strength"))}
        if self.e_alpha.text().strip():                                   # thermal expansion (only used when a temperature is given: Coupled Physics)
            a = num(self.e_alpha, "The thermal expansion coefficient")
            if not (0 < abs(a) < 1e-2):
                raise ValueError("The thermal expansion coefficient is per kelvin: steel is about 12e-6.")
            out["alpha"] = a
            out["Tref"] = (num(self.e_tref, "The reference temperature") if self.e_tref.text().strip() else 20.0) + 273.15
        return out

    def store_physics(self, m):
        self.setup["material"] = m
        self.store_body_material(m)

    def after_inputs(self):
        self.update_adapt_state()

    def stop_playback(self):
        self.anim_timer.stop()

    def show_no_result(self, had):
        self.res_lbl.setText("The setup changed since the last solve: press Solve." if had else "No result yet.")

    def enable_results_buttons(self):
        for b in (self.b_anim, self.b_play, self.b_stop):
            b.setEnabled(self.result is not None)

    def refresh_labels(self):
        """Every label that carries a unit, in the program's current units."""
        D = UD()
        for key, text in (("E", f"Young's modulus E ({D['S']})"), ("nu", "Poisson's ratio"), ("rho", f"Density ({D['rho']})"),
                          ("sy", f"Yield strength ({D['S']})"), ("su", f"Ultimate strength ({D['S']})"),
                          ("alpha", "Thermal expansion α (1/K)"), ("tref", "Reference temperature (°C)")):
            self.mat_labels[key].setText(text)
        super().refresh_labels()
        self.e_probe.setPlaceholderText(f"x, y, z  ({D['L']})")
        for i, (key, name) in enumerate(FIELDS):
            unit = D["S"] if key == "vm" else (D["L"] if key.startswith("u") else None)
            self.cb_field.setItemText(i, name + (f" ({unit})" if unit else ""))
        self.update_mat_note()

    def put_physics(self):
        self.put_material(self.setup["material"])

    def units_results(self):
        if self.result is not None:
            self.describe()
            self.show_field()
        if self.last_probe is not None:
            self.show_probe(self.last_probe)

    def has_conditions(self):
        return bool(self.setup["supports"] or self.setup["loads"])

    def condition_colours(self, cols):
        try:
            r = sm.resolve(self.geom, self.setup)
        except fem.FemError:
            r = {"supports": [], "loads": []}
        for item, s in zip(self.setup["supports"], r["supports"]):
            if self.cond_wants("Supports", item):
                for f in s["fids"]:
                    cols[f] = sv.SUPPORT
        for item, l in zip(self.setup["loads"], r["loads"]):
            if self.cond_wants("Loads", item):
                for f in l.get("fids", []):
                    cols[f] = sv.LOAD

    def use_source_material(self, mat):
        e = mat.get("E_MPa")
        if e:
            import mat_lib
            x = mat_lib.expansion(mat)
            self.put_material({"E": e, "nu": mat.get("nu") or 0.3, "rho": mat.get("density") or 7850.0, "sy": mat.get("Sy_MPa") or 0.0,
                               "su": mat.get("Su_MPa") or 0.0, **({"alpha": x[0], "Tref": x[1]} if x is not None else {})})
            nm = mat.get("name")
            self.select_material_name(nm if nm and self.library_entry(nm) else None)
            self.read_inputs()
            if self.mat_combo.currentData() is not None:
                self.setup["mat_name"] = self.mat_combo.currentData()

    def asm_only(self):
        return super().asm_only() + [self.body_lbl, self.body_table]

    def migrate_setup(self, st):
        return sm.migrate(st)

    def restore_boxes(self):
        self.put_material(self.setup["material"])
        self.select_material_name(self.setup.get("mat_name"))
        super().restore_boxes()

    def job_plan(self, g, r, solving=True):
        """The stages that a mesh or a solve of this setup is expected to go through (the progress bar's estimate); None when that cannot be told."""
        if solving and r.get("adapt"):
            try:
                h, cached = self.plan_mesh(g, r)
                return sad.plan(g, dict(r, h=h), h, cached)
            except Exception:
                return None
        return super().job_plan(g, r, solving)

    def build_physics_sections(self):
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
        self.e_E, self.e_nu, self.e_rho, self.e_sy, self.e_su, self.e_alpha, self.e_tref = (QLineEdit() for _ in range(7))
        self.e_alpha.setToolTip("Linear thermal expansion coefficient, per kelvin (about 12e-6 for steel, 23e-6 for aluminium). It is used only when a temperature is "
                                "given to this analysis (a Coupled Physics block). Empty = none: a thermal-stress solve will say so.")
        self.e_tref.setToolTip("The temperature, in degC, at which the material is free of thermal stress.")
        self.mat_labels = {}
        for e, key in ((self.e_E, "E"), (self.e_nu, "nu"), (self.e_rho, "rho"), (self.e_sy, "sy"), (self.e_su, "su"), (self.e_alpha, "alpha"), (self.e_tref, "tref")):
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
                               ("disp", "disp", "Says for x, y and z what the selected faces do: blank = free, 0 = held, a number = moved by exactly that much."),
                               ("slide", "ux", "Holds the selected faces only in the direction normal to them; they slide freely along it."),
                               ("bearing", "bolt", "For the round (cylindrical) face of a hole: select that face itself, not its edge.  It holds the face against moving "
                                                   "sideways (in or out along the radius) and along the axis of the hole; the face can still turn about the axis.  "
                                                   "One bearing alone leaves the part free to turn about its hole: add a second one on another hole, or another support.")):
            b = sim_ui.icon_button({"bearing": "Bearing (hole face)", "disp": "Displacement..."}.get(mode, self.SUPPORT_TYPES[mode]), icn, tip)
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

    def build_results_section(self):
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

    # ------------------------------------------------------------------ adaptive mesh (solid_adapt)
    def build_adaptive(self, v):
        """The 'Adaptive mesh (h)' tick box and the small menu it reveals (see solid_adapt for what the loops do)."""
        self.cb_adapt = QCheckBox("Adaptive mesh (h)")
        self.cb_adapt.setToolTip(ADAPT_TIP)
        v.addWidget(self.cb_adapt)
        self.adapt_box = QWidget()
        al = QVBoxLayout(self.adapt_box)
        al.setContentsMargins(14, 0, 0, 0)
        al.setSpacing(3)
        f = QFormLayout()
        self.ad_crit = QComboBox()
        for k, (name, _u) in sad.CRITERIA.items():
            self.ad_crit.addItem(name, k)
        self.ad_crit.setToolTip("The number that has to settle. Displacement and strain energy settle on any mesh. A PEAK stress at a point load, a sharp inside "
                                "corner or a fixed edge has no finite value and keeps growing as the elements get smaller: the loops then run to the end (the most "
                                "loops or the largest mesh) and say so.")
        sim_ui.tame(self.ad_crit, 24)
        f.addRow("Criterion", self.ad_crit)
        self.ad_tol = QLineEdit("1")
        self.ad_tol.setToolTip("Converged when the criterion changed by less than this many percent between two loops.")
        f.addRow("Tolerance (%)", self.ad_tol)
        self.ad_loops = QSpinBox()
        self.ad_loops.setRange(*sad.LOOPS_RANGE)
        self.ad_loops.setValue(5)
        self.ad_loops.setToolTip("The most refinements. Loop 0 is your own mesh; every loop after it refines and solves again, so 5 loops is up to 6 solves.")
        f.addRow("Maximum loops", self.ad_loops)
        self.ad_strength = QComboBox()
        for k, (name, _f) in sad.STRENGTHS.items():
            self.ad_strength.addItem(name, k)
        self.ad_strength.setCurrentIndex(self.ad_strength.findData("normal"))
        self.ad_strength.setToolTip("How much of the estimated error one loop tries to remove: aggressive makes more and smaller elements per loop (fewer loops, "
                                    "larger meshes), gentle the opposite.")
        sim_ui.tame(self.ad_strength, 24)
        f.addRow("Refinement", self.ad_strength)
        self.ad_cap = QLineEdit()
        self.ad_cap.setPlaceholderText("auto")
        self.ad_cap.setToolTip("The largest mesh you allow, in elements. The loops never go above it: when the next mesh would, it is refined less so that the last mesh "
                               "lands just under it. Blank = automatic: the loops stop when the result settles, at about "
                               f"{sad.AUTO_UNKNOWNS:,} unknowns, or when this computer's free memory is used up.")
        f.addRow("Largest mesh (elements)", self.ad_cap)
        self.ad_hmin = QLineEdit()
        self.ad_hmin.setPlaceholderText("auto")
        self.ad_hmin.setToolTip("The smallest element the loops may make (blank = a tenth of the element size, or the minimum size of the advanced mesh "
                                "options when that is set).")
        self.ad_hmin_label = QLabel("Smallest element")
        f.addRow(self.ad_hmin_label, self.ad_hmin)
        al.addLayout(f)
        self.ad_note = QLabel("")
        self.ad_note.setWordWrap(True)
        self.ad_note.setStyleSheet("color:#555555; font-size:11px;")
        al.addWidget(self.ad_note)
        self.adapt_box.setVisible(False)
        v.addWidget(self.adapt_box)
        self.cb_adapt.toggled.connect(self.adapt_toggled)
        for wd in (self.ad_crit, self.ad_strength):
            wd.activated.connect(lambda _i: self.inputs_changed())
        for wd in (self.ad_tol, self.ad_cap, self.ad_hmin):
            wd.editingFinished.connect(self.inputs_changed)
        self.ad_loops.valueChanged.connect(lambda _v: self.inputs_changed())

    def adapt_toggled(self, on):
        self.adapt_box.setVisible(bool(on))
        self.inputs_changed()
        for s_ in self.sections:
            s_.refresh_summary()

    def read_adapt(self):
        """The adaptive mesh boxes into the setup.  Raises ValueError for a bad number."""
        a = sad.complete(self.setup.get("adapt"))
        a["on"] = self.cb_adapt.isChecked()
        a["crit"] = self.ad_crit.currentData() or "vm"
        a["strength"] = self.ad_strength.currentData() or "normal"
        a["loops"] = self.ad_loops.value()
        self.setup["adapt"] = a
        if not a["on"]:
            return
        a["tol"] = num(self.ad_tol, "Tolerance")
        t = self.ad_cap.text().strip().replace(",", "")
        try:
            a["cap"] = int(float(t)) if t else 0
        except ValueError:
            raise ValueError(f"Largest mesh: '{t}' is not a number.")
        t = self.ad_hmin.text().strip()
        a["hmin"] = l_in(num(self.ad_hmin, "Smallest element")) if t else 0.0
        why = sad.validate(a)
        if why:
            raise ValueError(why)

    def put_adapt(self):
        """The adaptive mesh boxes from the setup (after opening a project, importing a state, a change of units ...)."""
        a = sad.complete(self.setup.get("adapt"))
        self.setup["adapt"] = a
        wds = (self.cb_adapt, self.ad_crit, self.ad_strength, self.ad_loops)
        for wd in wds:
            wd.blockSignals(True)
        self.cb_adapt.setChecked(bool(a["on"]))
        self.ad_crit.setCurrentIndex(max(0, self.ad_crit.findData(a["crit"])))
        self.ad_strength.setCurrentIndex(max(0, self.ad_strength.findData(a["strength"])))
        self.ad_loops.setValue(int(a["loops"]))
        for wd in wds:
            wd.blockSignals(False)
        self.ad_tol.setText(format(float(a["tol"]), ".8g"))
        self.ad_cap.setText(f"{int(a['cap'])}" if a["cap"] else "")
        self.ad_hmin.setText(format(l_out(a["hmin"]), ".8g") if a["hmin"] else "")
        self.adapt_box.setVisible(bool(a["on"]))
        self.update_adapt_state(auto_off=False)

    def update_adapt_state(self, auto_off=True, say_it=True):
        """The tick box is for tetrahedra and for a single part or bonded parts: when it is not available it is greyed out and its tip says why; (auto_off) it
        switches itself off when a change of the mesh type made it unavailable.  -> the text that says so ('' when it did not), which is
        also said in the status line unless say_it is False."""
        why = sad.unsupported(self.geom, self.setup)
        checked = self.cb_adapt.isChecked()
        said = ""
        if why and checked and auto_off:
            self.cb_adapt.blockSignals(True)
            self.cb_adapt.setChecked(False)
            self.cb_adapt.blockSignals(False)
            self.adapt_box.setVisible(False)
            self.setup["adapt"] = dict(sad.complete(self.setup.get("adapt")), on=False)
            said = why + " The adaptive mesh was switched off."
            if say_it:
                self.say(said)
            checked = False
        self.ad_hmin_label.setText(f"Smallest element ({UD()['L']})")
        self.cb_adapt.setEnabled(why is None or checked)
        self.cb_adapt.setToolTip(ADAPT_TIP if why is None else f"Not available: {why}")
        self.ad_note.setText(why if (why and checked) else "The Mesh button makes your own (first) mesh; the loops run when you press Solve.")
        self.ad_note.setStyleSheet("color:#b3261e; font-size:11px;" if (why and checked) else "color:#555555; font-size:11px;")
        return said

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
                                     {"E": self.e_E.text(), "nu": self.e_nu.text(), "sy": self.e_sy.text(), "su": self.e_su.text(), "eu": "",
                                      "alpha": self.e_alpha.text(), "tref": self.e_tref.text()})
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
                               "su": m_["Su_MPa"] if m_.get("Su_MPa") is not None else cur.get("su", 0.0),
                               **({"alpha": m_["alpha"], "Tref": m_.get("Tref_K", pm.TREF_K)} if m_.get("alpha") is not None else {})})
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
        a = m.get("alpha")                                                # thermal expansion: blank = the material has none
        self.e_alpha.setText("" if a is None else format(float(a), ".6g"))
        self.e_tref.setText(format(float(m.get("Tref") if m.get("Tref") is not None else 293.15) - 273.15, ".6g"))

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
        for k in ("alpha", "Tref"):                                       # (only when the box has one; a body whose material has none keeps none)
            if m.get(k) is not None:
                own[k] = float(m[k])
        mine = self.setup.setdefault("body_mats", {})
        if all(abs(own[k] - float(base[k] if base.get(k) is not None else (0.0 if k == "alpha" else 293.15))) <= 1e-9 * max(1.0, abs(float(base.get(k) or 1.0))) for k in own):
            mine.pop(b["name"], None)
        else:
            own["name"] = self.mat_combo.currentData() or ""
            mine[b["name"]] = own
        self.fill_body_materials()

    def refresh_lists(self):
        self.sup_list.clear()
        for i, s in enumerate(self.setup["supports"]):
            self.sup_list.addItem(f"{sm.name_of('Support', i, s)}: {self.support_text(s)} on {len(s['faces'])} face(s)")
        self.load_list.clear()
        for i, l in enumerate(self.setup["loads"]):
            self.load_list.addItem(f"{sm.name_of('Load', i, l)}: {self.load_text(l)}")
        t = self.cond_table
        t.blockSignals(True)
        t.setRowCount(0)
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        rows = [(sm.name_of("Support", i, s),) + self.support_cells(s) for i, s in enumerate(self.setup["supports"])]
        rows += [(sm.name_of("Load", i, l),) + self.load_cells(l) for i, l in enumerate(self.setup["loads"])]
        for r, cells in enumerate(rows):
            t.insertRow(r)
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setFlags(ro | Qt.ItemFlag.ItemIsEditable if c == 0 else ro)
                t.setItem(r, c, it)
        t.blockSignals(False)
        self.fill_face_table()

    @staticmethod
    def support_text(s):
        """The plain words of a support for the list: 'fixed', 'displacement (ux free, uy held, uz 2 mm)' ..."""
        if s["mode"] != "disp":
            return s["mode"]
        return "displacement (" + sim_disp.describe({k: (None if s.get(k) is None else l_out(s[k])) for k in sim_disp.KEYS[3]}, sim_disp.KEYS[3], lambda k: UD()["L"]) + ")"

    @classmethod
    def support_cells(cls, s):
        """(type, applied to, value) of a support for the conditions table."""
        n = f"{len(s['faces'])} face(s)"
        if s["mode"] == "disp":
            vals = ", ".join(sim_disp.fmt(None if s.get(k) is None else l_out(s[k])) or "free" for k in sim_disp.KEYS[3])
            return f"Displacement (ux, uy, uz) ({UD()['L']})", n, vals
        return cls.SUPPORT_TYPES.get(s["mode"], s["mode"]), n, ""

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
        elif key == "supports" and c != 0 and self.setup["supports"][i]["mode"] == "disp":
            QTimer.singleShot(0, lambda: self.edit_displacement(i))

    def edit_condition(self):
        """Edit selected: a load opens its numbers again; a support lets you rename it."""
        r = self.cond_table.currentRow()
        key, i = self.cond_ref(r)
        if key is None:
            self.say("Select a row of the list first.")
            return False
        if key == "loads":
            return self.edit_load(i)
        if self.setup["supports"][i]["mode"] == "disp":
            return self.edit_displacement(i)
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

    def displacement_values(self, cur=None):
        """The Displacement dialog (in the units of the program); -> {"ux", "uy", "uz"} in mm (None = free), or None when cancelled or when every direction is blank."""
        shown = {k: (None if (cur or {}).get(k) is None else l_out(cur[k])) for k in sim_disp.KEYS[3]}
        vals = sim_disp.ask(self, "Displacement", sim_disp.KEYS[3], {k: UD()["L"] for k in sim_disp.KEYS[3]}, shown)
        if vals is None:
            return None
        why = sim_disp.check(vals, sim_disp.KEYS[3])
        if why:
            self.say(why)
            return None
        return {k: (None if v is None else l_in(v)) for k, v in vals.items()}

    def edit_displacement(self, i):
        s = self.setup["supports"][i]
        vals = self.displacement_values(s)
        if vals is None:
            return False
        s.update(vals)
        self.after_edit()
        return True

    def add_support(self, mode=None, fids=None, values=None):
        """Adds a support on the selected faces.  A Displacement takes `values` ({"ux", "uy", "uz"} in mm, None = free, 0 = held) or asks for them."""
        fids = self.sel_faces if fids is None else fids
        if self.geom is None or not fids:
            self.say("Select the face(s) of the support first.")
            return False
        if any(self.geom["faces"][f].get("interface") for f in fids):
            self.say("A face between two parts is inside the assembly: put the support on an outside face.")
            return False
        mode = mode or "fixed"
        if mode == "bearing":
            bad = [f for f in fids if not self.geom["faces"][f].get("cyl")]
            if bad:
                self.say(f"A bearing needs the round (cylindrical) face of a hole: select that face, not an edge. {self.face_label(bad[0])} is a "
                         f"{self.geom['faces'][bad[0]]['kind']}.")
                return False
        extra = {}
        if mode == "disp":
            if values is None:
                values = self.displacement_values()
                if values is None:
                    return False
            elif all(values.get(k) is None for k in sim_disp.KEYS[3]):
                self.say(sim_disp.check({}, sim_disp.KEYS[3]))
                return False
            extra = {k: (None if values.get(k) is None else float(values[k])) for k in sim_disp.KEYS[3]}
        n = sum(1 for s in self.setup["supports"] if s["mode"] == mode) + 1
        self.setup["supports"].append({"mode": mode, "faces": [sg.face_sig(self.geom, f) for f in fids], "name": f"{'Displacement' if mode == 'disp' else mode.capitalize()} support {n}", **extra})
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
        return sm.check_ready(self.setup, self.geom, thermal=self.coupled_in is not None)

    coupled_in = None        # a Coupled Physics block sets this to a function: (the nodes of the mesh (n, 3), the mesh) -> the temperature there (kelvin)

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

        ci = self.coupled_in
        thermal = None if ci is None else (lambda q: {"T": ci(np.asarray(q["nodes"], float), q)})

        def work(progress, cancel):
            return sm.run(g, r, self.cache, cancel, progress, thermal=thermal)
        plan = self.job_plan(g, r)

        def done(res):
            self.result = res
            self.mesh_q = (self.mesh_view(res) if res.get("adapt") else self.cache.get(sm.mesh_key(g, res["h"], res.get("mesh_opts")), self.mesh_q))
            self.mesh_lbl.setText(self.mesh_text(res.get("n_elements", res["n_tets"]), res["n_nodes"], res["order"],
                                                 [p["h"] for p in res["part_sizes"]] if res.get("part_sizes") else res["h"], res.get("counts")))
            self.show_counts(self.mesh_q)
            self.show_quality(res.get("quality"), res.get("hexdom_note"))
            self.describe()
            self.show_field()
            self.colour()
            self.enable_buttons()
        return self.run_job(work, done, "Solving", plan)

    def mesh_view(self, res):
        """The mesh the last loop of an adaptive solve was solved on, as much of it as the window needs (the picture and the element counts)."""
        tb = res.get("tet_body")
        groups = ([{"kind": "tet", "body": int(b), "conn": res["conn"][tb == b]} for b in np.unique(tb)] if tb is not None and len(tb) == len(res["conn"])
                  else [{"kind": "tet", "conn": res["conn"]}])
        return {"nodes": res["nodes"], "tets": np.asarray(res["conn"])[:, :4], "conn": res["conn"], "groups": groups, "order": res["order"], "quality": res.get("quality"),
                "viewcells": res.get("viewcells")}

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
        if r.get("thermal"):
            html += R.thermal_block(r["thermal"])
        if r.get("support_reactions"):
            html += R.heading("Reactions", D["F"])
            html += R.grid(["", "Fx", "Fy", "Fz"], [[n, *(R.num(f_out(x)) for x in v)] for n, v in r["support_reactions"]])
        if r.get("bodies"):
            html += R.heading("Bodies (fully bonded)")
            html += R.grid(["Body", "Material", f"von Mises max ({D['S']})", "Safety factor", f"Mass ({mu[1]})"],
                           [[b["name"], b["material"].get("name") or "custom", R.num(s_out(b["vm_max"])), R.num(b["fos_y"], 3) if b.get("fos_y") else "-",
                             R.num(b["mass"] * mu[3])] for b in r["bodies"]])
            html += R.note("The parts are bonded where their faces touch: no slip, no gap, no separation. A bolted or sliding joint is stiffer here than in "
                           "reality, and the stress right at the edge of a bonded face is not reliable. The coloured stress is averaged at the nodes of a shared "
                           "face, so it blends the two bodies there; the table above is per body.")
            for t_ in r.get("notes") or []:
                html += R.note(t_, "#b05a00")
        kind = 'quadratic' if r.get('order', 2) == 2 else 'linear'
        cn = r.get("counts") or {}
        if cn.get("hexes") or cn.get("pyramids"):
            mesh_rows = [(f"Elements ({kind})", f"{r['n_elements']:,}", None), ("Hexahedra", f"{cn['hexes']:,} ({100.0 * cn['hexes'] / max(r['n_elements'], 1):.0f} %)", None),
                         ("Tetrahedra", f"{cn['tets']:,}", None), ("Pyramids", f"{cn['pyramids']:,}", None)]
        else:
            mesh_rows = [(f"Tetrahedra ({kind})", f"{r['n_tets']:,}", None)]
        ps = r.get("part_sizes") or []
        if len({round(p_["h"], 9) for p_ in ps}) > 1:                                       # the parts of an assembly have different sizes
            size_rows = [(f"Element size, {p_['name']}", R.num(l_out(p_["h"]), 4), D["L"]) for p_ in ps]
        else:
            size_rows = [("Element size", R.num(l_out(ps[0]["h"] if ps else r["h"]), 4), D["L"])]
        html += R.heading("Mesh") + R.kv(mesh_rows + [("Nodes", f"{r['n_nodes']:,}", None)] + size_rows)
        if r.get("hexdom_note"):
            html += R.note("Hex-dominant was asked for, but this mesh is tetrahedra only: " + r["hexdom_note"])
        if r.get("adapt"):
            html += self.adapt_report(r["adapt"])
        else:
            html += R.note("The mesh is not refined by itself: tick 'Adaptive mesh (h)' to let the loops refine it where the error is large, or check by meshing "
                           "finer and comparing, or run a parametric study over the element size.")
        info = r.get("info") or {}
        ok = r["equilibrium"] < 1e-6
        sums = "Applied + reactions = (" + ", ".join(R.num(f_out(a + b), 3) for a, b in zip(r["applied"], r["reaction"])) + f") {D['F']}"
        html += R.solver_block(info.get("solver", "?"), info.get("residual"), ok, sums,
                               [f"Relative error of the force balance {r['equilibrium']:.1e}."] if not ok else None)
        self.res_lbl.setText(html)
        self.say("Solved.")

    def adapt_report(self, ad):
        """The HTML of what the adaptive mesh did: the outcome and one row per loop."""
        D = UD()
        name, _u = sad.CRITERIA[ad["crit"]]
        conv = {"vm": (lambda v: s_out(v), D["S"]), "umax": (lambda v: l_out(v), D["L"]),
                "energy": (lambda v: f_out(1.0) * l_out(1.0) * v, f"{D['F']} {D['L']}")}[ad["crit"]]
        out = R.heading("Adaptive mesh", f"h-adaptive, {name.lower()} to {ad['tol']:g} %")
        chip = {"converged": "Converged", "max": "Reached your maximum", "auto": "Reached the size limit", "memory": "Stopped by memory"}.get(sad.outcome(ad), "Not converged")
        out += R.chip(chip, "ok" if ad["converged"] else "warn") + " " + (ad.get("reason") or "")
        if ad.get("warning"):
            out += R.note(ad["warning"], R.AMBER)
        rows = [[f"{h_['loop']}" + (" (your mesh)" if h_["loop"] == 0 else ""), f"{h_['elements']:,}", R.num(conv[0](h_["value"])),
                 "-" if h_["change"] is None else f"{h_['change']:.3g} %", f"{h_['err']:.2f} %", f"{h_['seconds']:.1f} s"] for h_ in ad["history"]]
        out += R.grid(["Loop", "Elements", f"{name} ({conv[1]})", "Change", "Estimated error", "Time"], rows)
        out += R.note("The estimated error is the energy of the difference between the stress the elements compute and the stress smoothed over their neighbours, "
                      "against the energy of the solution: a guide to where the mesh is too coarse (the 'Estimated mesh error' result shows where), not a bound. "
                      "A criterion that changed by less than the tolerance is a good sign, not a proof.")
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
        if key == "err":
            vals = np.asarray(r["node_err"], float)
            hi = max(float(np.nanmax(vals)), 1e-9)
            return vals, {"title": "Estimated mesh error  [%]", "lo": 0.0, "hi": hi, "flip": False,
                          "labels": [(0.0, f"{hi:.3g}"), (0.5, f"{hi / 2:.3g}"), (1.0, "0")], "subtitle": "of the energy of the solution, per element"}
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
        """The elements of the result that are drawn."""
        r = self.result
        return r.get("viewcells") or r["conn"]

    def sync_err_field(self):
        """The 'Estimated mesh error' result is offered only for a result that has it (a solve with the adaptive mesh)."""
        have = self.result is not None and self.result.get("node_err") is not None
        i = self.cb_field.findData("err")
        if have == (i >= 0):
            return
        self.cb_field.blockSignals(True)
        if have:
            self.cb_field.addItem("Estimated mesh error (%)", "err")
        else:
            if self.cb_field.currentIndex() == i:
                self.cb_field.setCurrentIndex(0)
            self.cb_field.removeItem(i)
        self.cb_field.blockSignals(False)

    def show_field(self, mesh_only=False):
        self.sync_err_field()
        if self.result is None:
            if self.mesh_q is not None:
                q = self.mesh_q
                self.view.show_mesh(q["nodes"], q.get("viewcells") or q["tets"])          # grey surface with the mesh edges: no result colours before Solve
            return
        r = self.result
        vals, leg = self.field_values()
        self.view.show_result(r["nodes"], self.shown_cells(), r["u"], vals, self.scale_value(), self.cb_edges.isChecked(), leg["lo"], leg["hi"], leg["flip"],
                              legend={"title": leg["title"], "labels": leg["labels"], "subtitle": leg["subtitle"]})

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

    def import_state(self, st):
        s = st.get("setup") or sm.default_setup()
        s.setdefault("dims", {})
        s.setdefault("splits", [])
        s.setdefault("bond_tol", 0.0)
        s.setdefault("body_mats", {})
        s.setdefault("body_h", {})
        self.migrated = sm.migrate(s)                                            # screws, bolts and contact were taken out: old setups open as bonded
        old_res = st.get("result")
        if self.migrated and isinstance(old_res, dict) and (old_res.get("joint") == "contact" or old_res.get("screws")):
            st = dict(st, result=None)                                           # that result was solved with the joint that is gone: it would not match the setup
            self.migrated.append("The old result was solved with that joint, so it was cleared: solve again.")
        s["mesh"] = smesh.complete(s.get("mesh"))
        dims_changed = (s["dims"] != self.setup.get("dims") or s["splits"] != (self.setup.get("splits") or []) or getattr(self, "geom_case", False)
                        or s["bond_tol"] != self.setup.get("bond_tol") or s["body_mats"] != self.setup.get("body_mats"))
        self.geom_case = False
        self.setup = json.loads(json.dumps(s))
        self.put_material(self.setup["material"])
        self.select_material_name(self.setup.get("mat_name"))
        self.put_mesh_options()
        if dims_changed and self.source is not None:
            self.load_geometry()
        elif self.geom is not None and self.is_asm():
            self.fill_faces()
            self.show_asm()
            self.redraw()
        self.fill_part_sizes()
        self.result = st.get("result")
        self.refresh_lists()
        self.colour()
        if self.result is not None:
            self.describe()
            self.show_field()
        else:
            self.invalidate()
        if self.migrated:
            self.say(" ".join(self.migrated))

    # ------------------------------------------------------------------ the parametric study
    def study_adapter(self):
        import solid_study
        return solid_study.SolidStudy(self)


def make_solid(host, path=None):
    if path:
        return SolidWindow.open_project(host, path)
    return SolidWindow(shell=host)
