"""
thermal3d_tab.py - the 3D Thermal window (project folder .gpt): steady and transient heat conduction in a parametric part or an ASSEMBLY of parts, with
convection and radiation to the surroundings.

It is the 3D FEA window (solid_base.SolidBase) with heat in place of stress: the same project bar, Geometry (the part, its faces, splitting a flat face into
patches, the bodies of an assembly), Mesh (element sizes, advanced options, quality) and Solve button with its progress bar.  What is particular here:

  Material      conductivity, density, specific heat and heat generation (per volume) of every body, from the library 2D Thermal uses
  Conditions    on faces, picked in the view:  fixed temperature  -  heat flux (into the body)  -  heat flow (watts, spread over the faces)  -  convection to a
                fluid  -  radiation to surroundings  -  insulated.  A face with no condition is insulated.
  Analysis      steady state, or transient (backward Euler or Crank-Nicolson) from a start temperature
  Results       temperature and heat flux on the surface, a transient run with a picture slider and an animation, the heat through every condition, a heat
                balance that must close, a probe
  Units         temperatures, heat flows ... follow File > Units > Heat transfer (shown and typed in them); what is kept and solved is SI and kelvin

The solver is thermal3d_fem.py and the setup layer thermal3d_model.py (no Qt in either); the test example and the self-check are in thermal3d_example.py.
"""
import json
import os
import time

import numpy as np
from PyQt6.QtCore import QPointF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import anim_export
import result_style
import sim_report as R
import sim_ui
import solid_diag
import solid_fem as fem
import solid_geom as sg
import solid_mesh as smesh
import solid_model as sm
import solid_view as sv
import thermal3d_ext
import thermal3d_fem as tf
import thermal3d_model as tm
import thermal_mat as tmat
import thermal_units as tu
import unitctl
from solid_base import SolidBase, UD, l_in, l_out, num

KIND = "thermal3d"
LABEL = "3D Thermal"
CUSTOM = "(custom values)"

# (key, name, quantity of thermal_units for its unit)
FIELDS = [("T", "Temperature", "T"), ("qmag", "Heat flux magnitude", "q"), ("qx", "Heat flux X", "q"), ("qy", "Heat flux Y", "q"), ("qz", "Heat flux Z", "q")]
METHODS = [("Backward Euler (very stable)", 1.0), ("Crank-Nicolson (more accurate)", 0.5)]
COLOURS = {"temps": sv.SUPPORT, "fluxes": sv.LOAD, "powers": sv.LOAD, "convs": (0.1, 0.65, 0.65), "rads": (0.72, 0.3, 0.72), "ins": (0.45, 0.62, 0.45)}

# what every kind of condition asks for: (key in the item, quantity of thermal_units or None, label with {unit} for the unit)
SPECS = {
    "temps": [("T", "T", "Temperature ({u})")],
    "fluxes": [("q", "q", "Heat flux ({u})")],
    "powers": [("P", "P", "Heat flow ({u})")],
    "convs": [("h", "h", "Convection coefficient h ({u})"), ("Tinf", "T", "Fluid temperature ({u})")],
    "rads": [("eps", None, "Emissivity (0 to 1)"), ("Ts", "T", "Surroundings temperature ({u})")],
    "ins": [],
}
TITLES = {"temps": "Fixed temperature on the selected faces", "fluxes": "Heat flux on the selected faces", "powers": "Heat flow on the selected faces",
          "convs": "Convection on the selected faces", "rads": "Radiation on the selected faces", "ins": "Insulated"}
NOTES = {
    "temps": "The selected faces are held at this temperature, whatever heat it takes (a heat sink, a bath, a cooled plate).",
    "fluxes": "Heat pushed through the faces, per unit of area. Positive heats the body; negative takes heat out of it.",
    "powers": "Heat put into the body through the faces, in watts in total (it is spread over their area). Positive heats the body. For a heater, a chip, "
              "a motor winding.",
    "convs": "The faces lose heat to a fluid (air, water): the coefficient times the difference between the face's temperature and the fluid's. Still air "
             "is about 5 to 25 W/(m2 K); moving air 10 to 100; water 100 to 10000.",
    "rads": "The faces radiate to surroundings that are much larger than the model: emissivity times the Stefan-Boltzmann constant times (T^4 - surroundings^4). "
            "Radiation between the faces of the model is not included.",
    "ins": "",
}
DEFAULTS = {"T": 373.15, "q": 1000.0, "P": 10.0, "h": 10.0, "Tinf": 293.15, "eps": 0.8, "Ts": 293.15}
MAX_PICTURES = 400


def box_text(v):
    """A number for a box: short when six digits say it exactly (401, 0.026), otherwise ten digits (a value converted from another unit)."""
    v = float(v)
    short = f"{v:.6g}"
    return short if abs(float(short) - v) <= 1e-9 * abs(v) else f"{v:.10g}"


def insulated_icon():
    """The button picture of 'Insulated': a wall with the slanted ticks of insulation on one side."""
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    q = QPainter(pm)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    q.setPen(QPen(QColor("#0e7f86"), 4))
    q.drawLine(QPointF(8, 34), QPointF(40, 34))
    q.setPen(QPen(QColor("#5b6770"), 3))
    for x in (10, 18, 26, 34):
        q.drawLine(QPointF(x, 34), QPointF(x + 5, 42))
    q.setPen(QPen(QColor("#0e7f86"), 3))
    q.drawLine(QPointF(14, 22), QPointF(34, 22))
    q.drawLine(QPointF(14, 14), QPointF(34, 14))
    q.end()
    return QIcon(pm)


def ask_values(parent, title, note, labels, defaults):
    """A small box with one number per label (and a note above them).  -> [float] or None."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    form = QFormLayout(dlg)
    if note:
        lb = QLabel(note)
        lb.setWordWrap(True)
        lb.setMinimumWidth(380)
        form.addRow(lb)
    edits = []
    for lab, d in zip(labels, defaults):
        e = QLineEdit(str(d))
        form.addRow(lab, e)
        edits.append(e)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    form.addRow(bb)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    try:
        return [float(e.text().strip().replace(",", ".")) for e in edits]
    except ValueError:
        QMessageBox.warning(parent, title, "Please enter plain numbers (for example 2.5 or 1e6).")
        return None


def value_problem(key, v):
    """The reason why the numbers of a condition (SI) cannot be used, or None."""
    if key == "temps" and not v["T"] > 0:
        return "That is below absolute zero."
    if key == "convs" and (v["h"] < 0 or not v["Tinf"] > 0):
        return "The coefficient cannot be negative and the fluid cannot be below absolute zero."
    if key == "rads" and (not 0 <= v["eps"] <= 1 or not v["Ts"] > 0):
        return "The emissivity must be between 0 and 1 and the surroundings cannot be below absolute zero."
    return None


class ThermalWindow(SolidBase):
    kind = KIND
    label = LABEL
    MESH_SEC = 4
    RESULTS_SEC = 5
    CONDITION_KINDS = tm.CONDITION_KINDS
    frame = None                                   # the picture of a transient result on show (None = the last)
    _nodal_cache = None
    _ranges = None

    def __init__(self, *a, **k):
        self.last_vals = {}
        self.check_rows = None                     # the rows of the last self-check
        super().__init__(*a, **k)
        unitctl.on_heat_change(self.heat_changed)
        if self.path is None and self.geom is None:
            self.say("3D Thermal: import a part or an assembly, or press Load test example (Test and diagnostics, at the bottom of the panel).")

    @property
    def example_info(self):
        """What the test example loaded (names of its bodies, the heater and the heat generation), kept in the setup so a reopened project can still be checked."""
        st = getattr(self, "setup", None)
        return st.get("example") if isinstance(st, dict) else None

    @example_info.setter
    def example_info(self, info):
        if info is None:
            self.setup.pop("example", None)
        else:
            self.setup["example"] = dict(info)

    # ------------------------------------------------------------------ units
    def family(self):
        """The heat-transfer units now chosen in File > Units (temperature, heat flow, conductivity ...)."""
        return tu.family_of(unitctl.system())

    def heat_changed(self, *_a):
        try:
            self.units_changed()
        except RuntimeError:
            unitctl.off_heat_change(self.heat_changed)

    def closeEvent(self, ev):
        unitctl.off_heat_change(self.heat_changed)
        super().closeEvent(ev)

    # ------------------------------------------------------------------ what SolidBase asks the thermal window for (its hooks)
    def new_setup(self):
        return tm.default_setup()

    def build_mesh_extras(self, v):
        i = self.type_combo.findData("hexdom")
        if i >= 0:
            self.type_combo.removeItem(i)                                       # the thermal solver works on tetrahedra
        v.addWidget(self.hint("3D Thermal works on tetrahedra. Quadratic elements (the default) follow a curved surface and a temperature gradient much better "
                              "than linear ones."))

    def refresh_study_button(self):
        self.study_box.setVisible(False)                                       # no parametric study for 3D Thermal yet

    def study_adapter(self):
        raise NotImplementedError("3D Thermal has no parametric study yet")

    def read_physics(self):
        fam = self.family()
        m = {"name": self.mat_combo.currentData() or "", "k": fam.to_si("k", num(self.e_k, "Conductivity")), "rho": fam.to_si("rho", num(self.e_rho, "Density")),
             "cp": fam.to_si("cp", num(self.e_cp, "Specific heat")), "gen": fam.to_si("qv", num(self.e_gen, "Heat generation"))}
        out = {"material": m, "analysis": "transient" if self.analysis_combo.currentIndex() == 1 else "steady",
               "T0": fam.to_si("T", num(self.e_T0, "Start temperature")), "time_unit": self.time_combo.currentText()}
        out["t_end"] = num(self.e_tend, "End time") * tu.TIME[out["time_unit"]]
        out["steps"] = self.whole(self.e_steps, "Time steps")
        out["frames"] = self.whole(self.e_nframes, "Pictures kept")
        out["theta"] = METHODS[max(0, self.method_combo.currentIndex())][1]
        return out

    @staticmethod
    def whole(edit, label):
        try:
            v = float(edit.text().replace(",", "."))
        except ValueError:
            raise ValueError(f"{label}: '{edit.text()}' is not a number.")
        if v != int(v) or v < 1:
            raise ValueError(f"{label}: type a whole number, 1 or more.")
        return int(v)

    def store_physics(self, p):
        m = dict(p["material"])
        lib = tmat.find(m["name"]) if m["name"] else None
        if lib is not None and any(abs(float(m[k]) - float(lib[k])) > 1e-9 * max(1.0, abs(float(lib[k]))) for k in ("k", "rho", "cp")):
            m["name"] = ""                                                    # the numbers were typed over: it is not that material any more
            self.select_material_name(None)
        if self.is_asm() and self.cur_body is not None:
            self.store_body_material(m)
        else:
            self.setup["material"] = m
        for k in ("analysis", "T0", "t_end", "steps", "frames", "theta", "time_unit"):
            self.setup[k] = p[k]

    def after_inputs(self):
        self.tr_box.setVisible(self.setup.get("analysis") == "transient")

    def stop_playback(self):
        self.anim_timer.stop()

    def show_no_result(self, had):
        self.res_lbl.setText("The setup changed since the last solve: press Solve." if had else "No result yet.")
        self.frame = None
        self._nodal_cache, self._ranges = None, None
        self.sync_time_controls()

    def enable_results_buttons(self):
        have = self.result is not None
        moving = have and tm.frame_count(self.result) > 1
        for b in (self.b_anim, self.b_play, self.b_stop):
            b.setEnabled(moving)
        self.slider.setEnabled(moving)

    def refresh_labels(self):
        """Every label that carries a unit, in the program's current units."""
        fam = self.family()
        D = UD()
        for lab, text in ((self.lbl_k, f"Conductivity k ({fam.unit('k')})"), (self.lbl_rho, f"Density ({fam.unit('rho')})"),
                          (self.lbl_cp, f"Specific heat ({fam.unit('cp')})"), (self.lbl_gen, f"Heat generation inside ({fam.unit('qv')})"),
                          (self.lbl_T0, f"Start temperature ({fam.temp})")):
            lab.setText(text)
        super().refresh_labels()
        self.e_probe.setPlaceholderText(f"x, y, z  ({D['L']})")
        for i, (_key, name, q) in enumerate(FIELDS):
            self.cb_field.setItemText(i, f"{name} ({fam.unit(q)})")
        self.update_mat_note()

    def put_physics(self):
        self.put_material(self.material_shown())
        s = self.setup
        fam = self.family()
        widgets = (self.analysis_combo, self.time_combo, self.method_combo)
        for wd in widgets:
            wd.blockSignals(True)
        self.analysis_combo.setCurrentIndex(1 if s.get("analysis") == "transient" else 0)
        unit = s.get("time_unit") if s.get("time_unit") in tu.TIME else "s"
        self.time_combo.setCurrentText(unit)
        self.method_combo.setCurrentIndex(0 if float(s.get("theta", 1.0)) >= 1.0 else 1)
        for wd in widgets:
            wd.blockSignals(False)
        self.e_T0.setText(box_text(fam.from_si("T", s["T0"])))
        self.e_tend.setText(box_text(s["t_end"] / tu.TIME[unit]))
        self.e_steps.setText(str(int(s["steps"])))
        self.e_nframes.setText(str(int(s["frames"])))
        self.tr_box.setVisible(s.get("analysis") == "transient")

    def units_results(self):
        if self.result is not None:
            self._nodal_cache, self._ranges = None, None
            self.describe()
            self.show_field()
        if self.last_probe is not None:
            self.show_probe(self.last_probe)

    def has_conditions(self):
        return any(self.setup.get(k) for k in tm.KEYS)

    def condition_colours(self, cols):
        for key in tm.KEYS:
            for i, c in enumerate(self.setup.get(key) or []):
                try:
                    fids = sm._fids(self.geom, c["faces"], sm.name_of(tm.NAMES[key], i, c))
                except fem.FemError:
                    continue
                for f in fids:
                    cols[f] = COLOURS[key]

    def reset_source_setup(self):
        keep = {k: self.setup[k] for k in ("mesh",) if k in self.setup}
        fresh = tm.default_setup()
        fresh.update(keep)
        self.setup = fresh
        self.cur_body = None
        self.put_physics()

    def use_source_material(self, mat):
        found = tmat.for_part_material({"name": mat.get("name"), "density": mat.get("density")})
        if found is not None:
            self.setup["material"] = {"name": found["name"] if tmat.find(found["name"]) else "", "k": found["k"], "rho": found["rho"], "cp": found["cp"],
                                      "gen": 0.0}
            if not tmat.find(found["name"]):
                self.setup["material"]["name"] = ""
        else:
            m = dict(self.setup["material"])
            if mat.get("density"):
                m["rho"] = float(mat["density"])
            m["name"] = ""
            self.setup["material"] = m
            self.say(f"No thermal numbers are stored for '{mat.get('name') or 'the material of the part'}': choose a material below or type its conductivity "
                     "and specific heat.")
        self.put_physics()
        self.select_material_name(self.setup["material"].get("name") or None)

    def asm_only(self):
        return super().asm_only() + [self.body_lbl, self.body_table]

    def migrate_setup(self, st):
        fresh = tm.default_setup()
        for k, v in fresh.items():
            st.setdefault(k, v)
        for k in tm.KEYS:
            st[k] = list(st.get(k) or [])
        st["material"] = dict(fresh["material"], **(st.get("material") or {}))
        return []

    def restore_boxes(self):
        self.put_physics()
        super().restore_boxes()

    # ------------------------------------------------------------------ the panel
    def build_physics_sections(self):
        self.build_material_section()
        self.build_condition_section()

    def build_material_section(self):
        v = self.sec(2, "Material and analysis", True, summary=self.material_summary,
                     help_text="The conductivity k says how easily heat flows through the material; the density and the specific heat say how much heat it "
                               "stores (only a transient run needs them). 'Heat generation inside' is heat made in the body itself, per unit of volume "
                               "(an electrical resistance, a reaction); leave it 0 otherwise. The numbers are typical room-temperature values, taken as "
                               "constant. An assembly gives every body its own material: select the body in the list. The units are chosen in File > Units "
                               "> Heat transfer.")
        self.mat_combo = QComboBox()
        self.mat_combo.activated.connect(self.material_picked)
        row = QHBoxLayout()
        row.addWidget(self.mat_combo, 1)
        b = QPushButton("Add material...")
        b.setToolTip("Adds the numbers now in the boxes below to your thermal material library (the one 2D Thermal uses).")
        b.clicked.connect(self.add_material)
        row.addWidget(b)
        self.b_del_mat = QPushButton("Delete")
        self.b_del_mat.setToolTip("Deletes a material you added. The built-in ones stay.")
        self.b_del_mat.clicked.connect(self.delete_material)
        row.addWidget(self.b_del_mat)
        v.addLayout(row)
        self.body_lbl = QLabel("Bodies of the assembly: select one, and the material above and the numbers below are its own (a body starts with the "
                               "material of its part).")
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
        f = QFormLayout()
        self.e_k, self.e_rho, self.e_cp, self.e_gen = (QLineEdit() for _ in range(4))
        self.lbl_k, self.lbl_rho, self.lbl_cp, self.lbl_gen = QLabel(), QLabel(), QLabel(), QLabel()
        self.e_rho.setToolTip("Only a transient run needs the density and the specific heat (how much heat the material stores).")
        self.e_cp.setToolTip(self.e_rho.toolTip())
        self.e_gen.setToolTip("Heat generated inside the body per unit of volume (positive heats it). Added to the whole body: for a heater or a chip, give the "
                              "watts on a face as a Heat flow instead.")
        for lab, e in ((self.lbl_k, self.e_k), (self.lbl_rho, self.e_rho), (self.lbl_cp, self.e_cp), (self.lbl_gen, self.e_gen)):
            f.addRow(lab, e)
            e.editingFinished.connect(self.inputs_changed)
        self.analysis_combo = QComboBox()
        self.analysis_combo.addItems(list(tm.ANALYSES.values()))
        self.analysis_combo.activated.connect(lambda _i: self.inputs_changed())
        f.addRow("Analysis", self.analysis_combo)
        v.addLayout(f)
        self.tr_box = QWidget()
        tf_ = QFormLayout(self.tr_box)
        tf_.setContentsMargins(14, 0, 0, 0)
        self.e_T0, self.e_tend, self.e_steps, self.e_nframes = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.lbl_T0 = QLabel()
        self.time_combo = QComboBox()
        self.time_combo.addItems(list(tu.TIME))
        trow = QHBoxLayout()
        trow.setContentsMargins(0, 0, 0, 0)
        trow.addWidget(self.e_tend, 1)
        trow.addWidget(self.time_combo)
        self.method_combo = QComboBox()
        self.method_combo.addItems([m for m, _t in METHODS])
        self.method_combo.setToolTip("Backward Euler is stable for any time step and smooths a sudden start. Crank-Nicolson is more accurate for smooth changes "
                                     "but can swing up and down after a sudden change when the steps are long.")
        self.e_nframes.setToolTip(f"How many temperature pictures are kept to look at and to animate (at most {MAX_PICTURES}; the first and the last are always kept).")
        tf_.addRow(self.lbl_T0, self.e_T0)
        tf_.addRow("End time", trow)
        tf_.addRow("Time steps", self.e_steps)
        tf_.addRow("Method", self.method_combo)
        tf_.addRow("Pictures kept", self.e_nframes)
        for e in (self.e_T0, self.e_tend, self.e_steps, self.e_nframes):
            e.editingFinished.connect(self.inputs_changed)
        self.time_combo.activated.connect(lambda _i: self.time_unit_changed())
        self.method_combo.activated.connect(lambda _i: self.inputs_changed())
        self.tr_box.setVisible(False)
        v.addWidget(self.tr_box)
        self.mat_note = QLabel("")
        self.mat_note.setWordWrap(True)
        self.mat_note.setStyleSheet("color:#707070;")
        v.addWidget(self.mat_note)
        self.fill_materials()
        self.put_physics()

    def time_unit_changed(self):
        """The time unit box was changed: the end time stays the same time, shown in the new unit."""
        try:
            t_end = float(self.setup["t_end"])
        except (KeyError, ValueError, TypeError):
            t_end = 600.0
        self.setup["time_unit"] = self.time_combo.currentText()
        self.e_tend.setText(box_text(t_end / tu.TIME[self.setup["time_unit"]]))
        self.inputs_changed()

    def material_summary(self):
        m = self.material_shown()
        return m.get("name") or "custom material"

    def build_condition_section(self):
        v = self.sec(3, "Conditions", True, summary=lambda: f"{sum(len(self.setup.get(k) or []) for k in tm.KEYS)} condition(s)",
                     help_text="Select the face(s) in the view first (click them; Ctrl or Shift for several), then press a button. Fixed temperature holds the "
                               "faces at a temperature. Heat flux and Heat flow push heat into the body (positive heats it). Convection: the faces lose "
                               "heat to a fluid at the temperature you give. Radiation: they radiate to surroundings at the temperature you give (not to "
                               "other faces of the model). A face with no condition is insulated. A steady problem needs at least one fixed temperature, "
                               "convection or radiation to settle on. Double-click a Name to rename it; double-click a value to change it.")
        v.addWidget(self.hint("Select the face(s) first (click them in the view), then press a button."))
        for text, icn, key, tip in (("Fixed temperature...", "fixed", "temps", "Holds the selected faces at a temperature."),
                                    ("Heat flux...", "pressure", "fluxes", "Heat per unit of area through the selected faces (positive = into the body)."),
                                    ("Heat flow (watts)...", "force", "powers", "Watts put into the body through the selected faces, spread over their area."),
                                    ("Convection...", "wind", "convs", "The selected faces lose heat to a fluid: coefficient and fluid temperature."),
                                    ("Radiation...", "snow", "rads", "The selected faces radiate to surroundings: emissivity and temperature."),
                                    ("Insulated", None, "ins", "No heat goes through the selected faces (an adiabatic face or a plane of symmetry). Faces with no "
                                                                "condition are insulated too: this only makes the choice visible.")):
            b = sim_ui.icon_button(text, icn, tip)
            if icn is None:
                b.setIcon(insulated_icon())
                b.setIconSize(QSize(22, 22))
            b.clicked.connect(lambda _c=False, k=key: self.add_cond(k))
            v.addWidget(b)
        v.addWidget(QLabel("Conditions on this model"))
        self.cond_table = QTableWidget(0, 4)
        self.cond_table.setHorizontalHeaderLabels(["Name", "Type", "Applied to", "Value"])
        self.cond_table.verticalHeader().hide()
        self.cond_table.setMinimumHeight(110)
        self.cond_table.setMaximumHeight(210)
        self.cond_table.horizontalHeader().setStretchLastSection(True)
        self.cond_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cond_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cond_table.setToolTip("Double-click a Name to rename it; double-click a Type, Applied to or Value cell to change the numbers.")
        self.cond_table.itemChanged.connect(self.cond_item_changed)
        self.cond_table.cellDoubleClicked.connect(self.cond_double_clicked)
        v.addWidget(self.cond_table)
        self.cond_note = QLabel("")
        self.cond_note.setWordWrap(True)
        self.cond_note.setStyleSheet("color:#707070;")
        v.addWidget(self.cond_note)
        row = QHBoxLayout()
        b = QPushButton("Edit selected...")
        b.setToolTip("Changes the numbers of the selected row (or renames an Insulated one).")
        b.clicked.connect(self.edit_condition)
        row.addWidget(b)
        b = QPushButton("Remove selected")
        b.clicked.connect(self.remove_condition)
        row.addWidget(b)
        v.addLayout(row)

    def build_results_section(self):
        v = self.sec(self.RESULTS_SEC, "Results", True, summary=lambda: self.cb_field.currentText(),
                     help_text="Temperature and heat flux on the surface of the part. The heat flux is the heat flowing per unit of area (k times the "
                               "temperature gradient, in the direction the heat moves, X Y Z being the axes of the part - the triad in the corner of the view "
                               "shows them); the picture shows its value at the nodes (the average of the elements around each one). The report under the "
                               "picture lists the heat through every condition and the heat balance (heat in = heat out + heat stored), which must close. "
                               "A transient run keeps pictures: move the slider, or press Animate.")
        self.cb_field = QComboBox()
        for key, name, _q in FIELDS:
            self.cb_field.addItem(name, key)
        self.cb_field.currentIndexChanged.connect(lambda _i: self.show_field())
        v.addWidget(self.cb_field)
        row = QHBoxLayout()
        row.addWidget(QLabel("Colours"))
        self.cmap_combo = result_style.make_combo(self, self.colours_changed)
        row.addWidget(self.cmap_combo, 1)
        v.addLayout(row)
        self.cb_edges = QCheckBox("Show mesh edges")
        self.cb_edges.toggled.connect(lambda _on: self.show_field())
        v.addWidget(self.cb_edges)
        self.time_box = QWidget()                                         # a transient result: the picture slider and the animation
        tl = QVBoxLayout(self.time_box)
        tl.setContentsMargins(0, 0, 0, 0)
        self.time_lbl = QLabel("")
        tl.addWidget(self.time_lbl)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.slider_moved)
        tl.addWidget(self.slider)
        self.cb_anim = QCheckBox("Animate")
        self.cb_anim.setToolTip("Plays the pictures of the transient run one after the other.")
        self.cb_anim.toggled.connect(self.anim_toggled)
        tl.addWidget(self.cb_anim)
        self.anim_box = QWidget()
        al = QFormLayout(self.anim_box)
        al.setContentsMargins(14, 0, 0, 0)
        self.e_dur = QLineEdit("6")
        self.loop_combo = QComboBox()
        self.loop_combo.addItems(["Once", "Loop", "Back and forth"])
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
        self.b_anim.setToolTip("Saves the animation as a transparent animated WebP or PNG, an animated GIF"
                               + (", an MP4 video" if anim_export.mp4_available() else " (an MP4 video too when OpenCV or imageio-ffmpeg is installed)")
                               + " or a folder of PNG pictures, seen from where the part is on screen now. It uses the pictures of the run, the Duration and the "
                                 "Playback above.")
        self.b_anim.clicked.connect(lambda: self.export_animation())
        al.addRow(self.b_anim)
        self.anim_box.setVisible(False)
        tl.addWidget(self.anim_box)
        self.time_box.setVisible(False)
        v.addWidget(self.time_box)
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.anim_step)
        self.anim_dir, self.anim_k = 1, 0
        self.res_lbl = QLabel("No result yet.")
        self.res_lbl.setWordWrap(True)
        self.res_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.res_lbl)
        v.addWidget(QLabel("<b>Probe</b>"))
        self.b_probe = QPushButton("Probe by clicking the surface")
        self.b_probe.setCheckable(True)
        self.b_probe.setToolTip("Switch this on, then click the solved part: the values of the node nearest to the click appear below. The view still turns "
                                "with the mouse; only a click without moving is a probe.")
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
        self.build_test_section()

    def build_test_section(self):
        """Section 6: the test example, the self-check and the diagnostics report."""
        v = self.sec(self.RESULTS_SEC + 1, "Test and diagnostics", True,
                     help_text="Load test example makes a ready, deliberately demanding project (an assembly of four bodies with holes, a thin fin, curved "
                               "faces, every kind of condition, radiation and a transient run) in a folder you choose; press Solve to run it. Run self-check "
                               "solves small problems whose answer is known (a wall, a pipe, a cooling block ...) and prints the numbers side by side with PASS "
                               "or FAIL. Diagnostics report... gathers the computer, the program, the geometry, the mesh, the setup, the time of every stage, "
                               "the solver and every message in one text: copy it or find it in the project folder as diagnostics.txt.")
        v.addWidget(self.hint("For testing the add-on: the example is a stress test, and the report is what to send back when something is wrong."))
        for text, tip, fn in (("Load test example...", "Makes the test project in a new folder and opens it here; then press Solve.", self.load_example),
                              ("Run self-check", "Solves a series of problems with known answers and shows how close the program comes.", self.run_self_check),
                              ("Diagnostics report...", "The whole state of this window as plain text (also saved as diagnostics.txt in the project folder).",
                               self.show_diagnostics)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setMinimumHeight(28)
            b.clicked.connect(lambda _c=False, f=fn: f())
            v.addWidget(b)
        self.check_lbl = QLabel("")
        self.check_lbl.setWordWrap(True)
        self.check_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.check_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.check_lbl)

    # ------------------------------------------------------------------ material and inputs
    def fill_materials(self, select=None):
        self.library = tmat.library()
        builtin = tmat.builtin_names()
        self.mat_combo.blockSignals(True)
        self.mat_combo.clear()
        self.mat_combo.addItem(CUSTOM, None)
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
        self.b_del_mat.setEnabled(self.mat_combo.currentData() is not None and self.mat_combo.currentData() not in tmat.builtin_names())
        self.update_mat_note()

    def library_entry(self, name):
        return next((x for x in self.library if x["name"] == name), None)

    def update_mat_note(self):
        name = self.mat_combo.currentData()
        fam = self.family()
        self.mat_note.setText(("Custom values." if name is None else "Typical room-temperature values - check your source.")
                              + f"  Heat transfer units: {fam.name} (File > Units).")

    def material_shown(self):
        """The material the boxes show: the selected body's in an assembly, else the part's."""
        if self.is_asm() and self.cur_body is not None and self.cur_body < len(self.geom["bodies"]):
            return tm.body_materials(self.geom, self.setup)[self.cur_body]
        return self.setup["material"]

    def put_material(self, m):
        """The material (SI) in the boxes, in the heat units now chosen, and its name in the combo."""
        fam = self.family()
        for e, q, k in ((self.e_k, "k", "k"), (self.e_rho, "rho", "rho"), (self.e_cp, "cp", "cp"), (self.e_gen, "qv", "gen")):
            e.setText(box_text(fam.from_si(q, float(m.get(k) or 0.0))))
        if hasattr(self, "mat_combo"):
            nm = m.get("name")
            self.select_material_name(nm if nm and self.library_entry(nm) else None)

    def material_picked(self, *_a):
        name = self.mat_combo.currentData()
        m_ = self.library_entry(name) if name is not None else None
        if m_ is not None:
            cur = self.material_shown()
            self.put_material({"name": name, "k": m_["k"], "rho": m_["rho"], "cp": m_["cp"], "gen": cur.get("gen") or 0.0})
        self.b_del_mat.setEnabled(name is not None and name not in tmat.builtin_names())
        self.update_mat_note()
        self.inputs_changed()

    def add_material(self):
        try:
            p = self.read_physics()
        except ValueError as ex:
            QMessageBox.warning(self, "Add material", str(ex))
            return None
        m = p["material"]
        why = tm.material_problem(m)
        if why:
            QMessageBox.warning(self, "Add material", why)
            return None
        name, ok = QInputDialog.getText(self, "Add material", "Name of the new material (the conductivity, density and specific heat now in the boxes):")
        name = (name or "").strip()
        if not ok or not name:
            return None
        if name in tmat.builtin_names() or any(x["name"] == name for x in tmat.user_materials()):
            QMessageBox.information(self, "Add material", "A material with that name exists already. Choose another name.")
            return None
        try:
            tmat.save_user(tmat.user_materials() + [{"name": name, "k": m["k"], "rho": m["rho"], "cp": m["cp"]}])
        except OSError as ex:
            QMessageBox.warning(self, "Add material", f"Could not save the library: {ex}")
            return None
        self.fill_materials(select=name)
        self.material_picked()
        return name

    def delete_material(self):
        name = self.mat_combo.currentData()
        if name is None or name in tmat.builtin_names():
            QMessageBox.information(self, "Delete material", "Choose a material you added first. The built-in ones cannot be deleted.")
            return False
        if QMessageBox.question(self, "Delete material", f"Delete '{name}' from your library?") != QMessageBox.StandardButton.Yes:
            return False
        tmat.save_user([m for m in tmat.user_materials() if m["name"] != name])
        self.fill_materials()
        self.inputs_changed()
        return True

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
        fam = self.family()
        for i, m in enumerate(tm.body_materials(self.geom, self.setup)):
            it = self.body_table.item(i, 1)
            if it is not None:
                it.setText(m.get("name") or f"k = {box_text(fam.from_si('k', m['k']))} {fam.unit('k')}")

    def body_selected(self):
        if not self.is_asm():
            return
        rows = self.body_table.selectionModel().selectedRows() if self.body_table.selectionModel() is not None else []
        if not rows:
            return
        i = rows[0].row()
        self.cur_body = i
        self.put_material(tm.body_materials(self.geom, self.setup)[i])
        self.update_mat_note()
        self.mat_note.setText(f"Material of {self.geom['bodies'][i]['name']}. " + self.mat_note.text())

    def store_body_material(self, m):
        """The numbers on the screen belong to the selected body of an assembly: keep them for it when they differ from what the library gives its part."""
        if not self.is_asm() or self.cur_body is None or self.cur_body >= len(self.geom["bodies"]):
            return
        b = self.geom["bodies"][self.cur_body]
        own = tm.body_materials(self.geom, dict(self.setup, body_mats={}))[self.cur_body]
        mine = self.setup.setdefault("body_mats", {})
        if all(abs(float(m.get(k) or 0.0) - float(own.get(k) or 0.0)) <= 1e-9 * max(1.0, abs(float(own.get(k) or 0.0))) for k in ("k", "rho", "cp", "gen")):
            mine.pop(b["name"], None)
        else:
            mine[b["name"]] = {k: m[k] for k in ("name", "k", "rho", "cp", "gen")}
        self.fill_body_materials()

    # ------------------------------------------------------------------ the conditions
    def cond_rows(self):
        """[(key, index)] of every condition, in the order of the table: fixed temperatures first, then fluxes, heat flows, convection, radiation, insulated."""
        return [(key, i) for key in tm.KEYS for i in range(len(self.setup.get(key) or []))]

    def cond_ref(self, r):
        rows = self.cond_rows()
        return rows[r] if 0 <= r < len(rows) else (None, -1)

    def value_text(self, key, c):
        fam = self.family()
        T = lambda k: f"{box_text(fam.from_si('T', k))} {fam.temp}"
        if key == "temps":
            return T(c["T"])
        if key == "fluxes":
            return f"{box_text(fam.from_si('q', c['q']))} {fam.unit('q')}"
        if key == "powers":
            return f"{box_text(fam.from_si('P', c['P']))} {fam.unit('P')}"
        if key == "convs":
            return f"h {box_text(fam.from_si('h', c['h']))} {fam.unit('h')}, fluid {T(c['Tinf'])}"
        if key == "rads":
            return f"emissivity {c['eps']:g}, surroundings {T(c['Ts'])}"
        return ""

    def applied_text(self, key, i, c):
        try:
            fids = sm._fids(self.geom, c["faces"], sm.name_of(tm.NAMES[key], i, c)) if self.geom is not None else []
        except fem.FemError:
            return "face lost: select it again"
        k = l_out(1.0)
        area = sum(self.geom["faces"][f]["area"] for f in fids) * k * k
        return f"{len(fids)} face(s), {R.num(area, 4)} {UD()['L']}2"

    def refresh_lists(self):
        t = self.cond_table
        t.blockSignals(True)
        t.setRowCount(0)
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        for r, (key, i) in enumerate(self.cond_rows()):
            c = self.setup[key][i]
            t.insertRow(r)
            for col, text in enumerate((sm.name_of(tm.NAMES[key], i, c), tm.NAMES[key], self.applied_text(key, i, c), self.value_text(key, c))):
                it = QTableWidgetItem(text)
                it.setFlags(ro | Qt.ItemFlag.ItemIsEditable if col == 0 else ro)
                t.setItem(r, col, it)
        t.blockSignals(False)
        self.update_cond_note()
        self.fill_face_table()

    def update_cond_note(self):
        why = None
        if self.geom is not None:
            try:
                why = tm.check_ready(self.setup, self.geom)
            except Exception:                                                    # noqa: BLE001 - a note, never an error
                why = None
        self.cond_note.setText(why or "")
        self.cond_note.setStyleSheet("color:#b36b00;")

    def cond_item_changed(self, it):
        if it.column() != 0:
            return
        key, i = self.cond_ref(it.row())
        if key is None:
            return
        item = self.setup[key][i]
        text = it.text().strip()
        if text and text != sm.name_of(tm.NAMES[key], i):
            item["name"] = text
        else:
            item.pop("name", None)
        self.refresh_lists()

    def cond_double_clicked(self, r, c):
        if c != 0:
            QTimer.singleShot(0, lambda: self.edit_cond_row(r))

    def edit_condition(self):
        r = self.cond_table.currentRow()
        key, _i = self.cond_ref(r)
        if key is None:
            self.say("Select a row of the list first.")
            return False
        if not SPECS[key]:
            it = self.cond_table.item(r, 0)
            self.cond_table.setCurrentItem(it)
            self.cond_table.editItem(it)
            return True
        return self.edit_cond_row(r)

    def edit_cond_row(self, r):
        key, i = self.cond_ref(r)
        if key is None or not SPECS[key]:
            return False
        vals = self.ask_condition(key, self.setup[key][i])
        if vals is None:
            return False
        self.setup[key][i].update(vals)
        self.after_edit()
        return True

    def remove_condition(self):
        key, i = self.cond_ref(self.cond_table.currentRow())
        if key is None:
            self.say("Select a row of the list first.")
            return False
        del self.setup[key][i]
        self.after_edit()
        return True

    def ask_condition(self, key, cur=None):
        """The small box for the numbers of a condition (in the heat units now chosen).  -> {key in the item: SI value} or None."""
        fam = self.family()
        labels, defaults = [], []
        for k, q, lab in SPECS[key]:
            v = float((cur or {}).get(k, self.last_vals.get(k, DEFAULTS[k])))
            labels.append(lab.format(u=fam.temp if q == "T" else (fam.unit(q) if q else "")))
            defaults.append(box_text(fam.from_si(q, v) if q else v))
        got = ask_values(self, TITLES[key], NOTES[key], labels, defaults)
        if got is None:
            return None
        vals = {k: (fam.to_si(q, x) if q else x) for (k, q, _l), x in zip(SPECS[key], got)}
        why = value_problem(key, vals)
        if why:
            QMessageBox.warning(self, TITLES[key], why)
            return None
        self.last_vals.update(vals)
        return vals

    def add_cond(self, key):
        """A condition button: asks for the numbers, then puts the condition on the selected faces."""
        return self.add_condition(key)

    def add_condition(self, key, values=None, fids=None, name=None):
        """Adds a condition of kind `key` (one of tm.KEYS) on faces (the selected ones by default).  Without `values` a small box asks for them."""
        if self.geom is None:
            self.say("Import a part first.")
            return False
        fids = self.sel_faces if fids is None else fids
        if not fids:
            self.say("Select the face(s) first.")
            return False
        if any(self.geom["faces"][f].get("interface") for f in fids):
            self.say("A face between two bodies is inside the assembly: put the condition on an outside face.")
            return False
        if values is None:
            values = self.ask_condition(key) if SPECS[key] else {}
            if values is None:
                return False
        else:
            why = value_problem(key, values)
            if why:
                self.say(why)
                return False
        n = len(self.setup[key]) + 1
        item = {"name": name or f"{tm.NAMES[key]} {n}", "faces": [sg.face_sig(self.geom, f) for f in fids]}
        item.update(values)
        self.setup[key].append(item)
        self.after_edit()
        return True

    # ------------------------------------------------------------------ running
    def ready(self):
        if self.geom is None:
            return "Import a part first."
        try:
            self.read_inputs()
        except ValueError as ex:
            return str(ex)
        return tm.check_ready(self.setup, self.geom)

    def run_solve(self):
        why = self.ready()
        if why:
            self.say(why)
            return False
        try:
            r = tm.resolve(self.geom, self.setup)
        except fem.FemError as ex:
            self.say(str(ex))
            return False
        g = self.geom

        def work(progress, cancel):
            return tm.run(g, r, self.cache, cancel, progress)
        plan = self.job_plan(g, r)

        def done(res):
            self.result = res
            self.frame = None
            self._nodal_cache, self._ranges = {}, {}
            self.mesh_q = res["mesh"]
            ql = res["mesh"].get("quality")
            self.mesh_lbl.setText(self.mesh_text(res["elements"], len(res["nodes"]), res["order"], fem.element_sizes(g, res["h_used"], r.get("mesh")), None))
            self.show_counts(self.mesh_q)
            self.show_quality(ql)
            self.sync_time_controls()
            self.describe()
            self.show_field()
            self.colour()
            self.enable_buttons()
        return self.run_job(work, done, "Solving", plan)

    def sync_time_controls(self):
        """The picture slider of a transient result (hidden for a steady one)."""
        res = self.result
        n = tm.frame_count(res) if res is not None else 1
        self.time_box.setVisible(res is not None and n > 1)
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, n - 1))
        self.slider.setValue(self.cur_frame())
        self.slider.blockSignals(False)
        self.time_lbl.setText(self.time_text(self.cur_frame()) if res is not None and n > 1 else "")

    def cur_frame(self):
        if self.result is None:
            return 0
        n = tm.frame_count(self.result)
        return n - 1 if self.frame is None else max(0, min(int(self.frame), n - 1))

    def time_text(self, k):
        r = self.result
        u = self.setup.get("time_unit") if self.setup.get("time_unit") in tu.TIME else "s"
        return f"t = {tm.time_of(r, k) / tu.TIME[u]:.5g} {u}   (picture {k + 1} of {tm.frame_count(r)})"

    # ------------------------------------------------------------------ the report of a result
    def describe(self):
        r = self.result
        if r is None:
            return
        fam = self.family()
        D = UD()
        k_len = l_out(1.0)
        trans = r["analysis"] == "transient"
        end = " (at the end)" if trans else ""
        T = lambda v: R.num(fam.from_si("T", v), 5)
        P = lambda v: R.num(fam.from_si("P", v), 5)
        rows = [("Highest temperature" + end, T(r["Tmax"]), fam.temp), ("Lowest temperature" + end, T(r["Tmin"]), fam.temp),
                ("Average temperature (by volume)" + end, T(r["Tmean"]), fam.temp),
                ("Largest heat flux" + end, R.num(fam.from_si("q", float(np.max(r["qmag"])))), fam.unit("q"))]
        if trans:
            fr = r["frames"]
            used = np.unique(r["conn"])
            rows += [("Highest temperature during the run", T(float(fr[:, used].max())), fam.temp), ("Lowest temperature during the run", T(float(fr[:, used].min())), fam.temp)]
        html = R.heading("Summary") + R.kv(rows)
        if trans:
            run, st = r.get("run") or {}, r.get("setup") or {}
            html += R.note(f"Transient: {st.get('steps', '?')} steps of {R.num(run.get('dt'), 3)} s to {R.num(st.get('t_end'), 4)} s, "
                           f"{'Crank-Nicolson' if st.get('theta', 1.0) < 1.0 else 'backward Euler'}; {tm.frame_count(r)} pictures kept (use the slider).")
        flows = r.get("flows") or []
        if flows:
            html += R.heading("Heat through each condition", f"({fam.unit('P')}; positive = into the body)")

            def flux_text(f):
                a = f.get("area")
                if not a or f.get("kind") not in ("flux", "conv", "rad"):
                    return ""
                qq = "qr" if f["kind"] == "rad" else "q"
                return f"{R.num(fam.from_si(qq, f['Q'] / a), 4)} {fam.unit(qq)}"
            html += R.grid(["", "Heat", "Average heat flux"], [[f["name"], P(f["Q"]), flux_text(f)] for f in flows])
        b = r["balance"]
        brow = [("Heat in (conditions and generation)", P(b["in"]), fam.unit("P")), ("Heat out", P(b["out"]), fam.unit("P"))]
        if abs(b["generation"]) > 0:
            brow.insert(1, ("   of which generated inside", P(b["generation"]), fam.unit("P")))
        if abs(b["stored"]) > 0 or trans:
            brow.append(("Stored (heating up)", P(b["stored"]), fam.unit("P")))
        html += R.heading("Heat balance") + R.kv(brow)
        cn = trans and (r.get("setup") or {}).get("theta", 1.0) < 1.0
        ok = b["relative_error"] <= (5e-2 if cn else 1e-6)
        html += R.kv([("Heat in - out - stored", (R.chip("OK", "ok") if ok else R.chip("CHECK", "bad")) + f" {b['relative_error']:.1e} of the flow", None)])
        bodies = r.get("bodies") or []
        if len(bodies) > 1:
            html += R.heading("Bodies")
            html += R.grid(["Body", f"Volume ({D['L']}3)", f"Mean ({fam.temp})", "Lowest", "Highest", f"Largest flux ({fam.unit('q')})", f"Generates ({fam.unit('P')})"],
                           [[x["name"], R.num(x["volume_m3"] * 1e9 * k_len ** 3, 4), T(x["Tmean"]), T(x["Tmin"]), T(x["Tmax"]),
                             R.num(fam.from_si("q", x["q_max"]), 4), P(x["generation"])] for x in bodies])
        kind = "quadratic" if r.get("order", 2) == 2 else "linear"
        sizes = r.get("sizes") or ([r["h_used"]] if r.get("h_used") else [])
        szs = sorted({round(float(x), 9) for x in (sizes if isinstance(sizes, (list, tuple, np.ndarray)) else [sizes])})
        size_rows = [("Element size", R.num(l_out(szs[0]), 4), D["L"])] if len(szs) == 1 else \
            [("Element sizes", f"{R.num(l_out(szs[0]), 4)} to {R.num(l_out(szs[-1]), 4)}", D["L"])] if szs else []
        html += R.heading("Mesh") + R.kv([(f"Tetrahedra ({kind})", f"{r['elements']:,}", None), ("Nodes", f"{len(r['nodes']):,}", None)] + size_rows)
        html += R.note("The mesh is not refined by itself: check a result by meshing finer and comparing.")
        run = r.get("run") or {}
        nw = r.get("newton")
        srows = [("Solver", run.get("solver", "?"), None), ("Unknowns", f"{r['unknowns']:,}", None)]
        if run.get("linear_iterations"):
            srows.append(("Linear iterations", f"{run['linear_iterations']:,}", None))
        if run.get("residual_rel") is not None:
            srows.append(("Relative residual", R.num(run["residual_rel"], 3), None))
        sec = r.get("seconds") or {}
        srows.append(("Time", f"{sec.get('total', 0.0):.2f} s (assembling {sec.get('assemble', 0.0):.2f}, solving {sec.get('solve', 0.0):.2f})", None))
        html += R.heading("Solver check") + R.kv(srows)
        if nw is not None:
            html += R.note(f"Radiation makes the problem nonlinear: Newton's method needed {nw.get('iterations', '?')} iteration(s) "
                           f"({'converged' if nw.get('converged') else 'NOT converged'}).", R.GREY if nw.get("converged") else R.RED)
        for n in sorted(set(r.get("notes") or [])):
            html += R.note(n, R.AMBER)
        self.res_lbl.setText(html)
        self.say("Solved.")

    # ------------------------------------------------------------------ the pictures
    def nodal(self, k):
        """The values the pictures and the probe show at picture k, one per node (SI): T, qx, qy, qz, qmag (the heat flux averaged over the elements round a node)."""
        if self._nodal_cache is None:
            self._nodal_cache = {}
        cache = self._nodal_cache
        if k not in cache:
            r = self.result
            q, qm = tm.flux_of(r, k)
            cache[k] = {"T": tm.temperature_of(r, k), "qx": tm.node_average(r, q[:, 0]), "qy": tm.node_average(r, q[:, 1]), "qz": tm.node_average(r, q[:, 2]),
                        "qmag": tm.node_average(r, qm)}
            while len(cache) > 6:
                cache.pop(next(iter(cache)))
        return cache[k]

    def field_range(self, key):
        """(lowest, highest) SI value of a field over all the pictures of the result: the colours of an animation keep one scale."""
        if self._ranges is None:
            self._ranges = {}
        if key not in self._ranges:
            r = self.result
            if key == "T":
                arr = r["frames"] if r.get("frames") is not None else r["T"]
                used = np.unique(r["conn"])
                self._ranges[key] = (float(np.min(arr[..., used])), float(np.max(arr[..., used])))
            else:
                lo, hi = np.inf, -np.inf
                for k in range(tm.frame_count(r)):
                    v = self.nodal(k)[key]
                    lo, hi = min(lo, float(v.min())), max(hi, float(v.max()))
                self._ranges[key] = (lo, hi)
        return self._ranges[key]

    def field_key(self):
        return self.cb_field.currentData() or "T"

    def field_values(self, k=None):
        """-> (value per node in the program's heat units at picture k, the legend {"title", "labels", "lo", "hi", "flip", "subtitle"}).  The range of colours is that of
        the whole run."""
        r = self.result
        key = self.field_key()
        fam = self.family()
        name, q = next((n, q) for kk, n, q in FIELDS if kk == key)
        k = self.cur_frame() if k is None else k
        lo_si, hi_si = self.field_range(key)
        lo, hi = fam.from_si(q, lo_si), fam.from_si(q, hi_si)
        if not hi > lo:
            hi = lo + 1.0
        vals = fam.from_si(q, self.nodal(k)[key])
        unit = fam.unit(q)
        leg = {"title": f"{name}  [{unit}]", "lo": lo, "hi": hi, "flip": False, "labels": [(0.0, f"{hi:.5g}"), (0.5, f"{(hi + lo) / 2:.5g}"), (1.0, f"{lo:.5g}")],
               "subtitle": ("range of the whole run" if tm.frame_count(r) > 1 else ("average of the elements round each node" if key != "T" else None))}
        return vals, leg

    def show_field(self, mesh_only=False):
        if self.result is None:
            if self.mesh_q is not None:
                q = self.mesh_q
                self.view.show_mesh(q["nodes"], q.get("viewcells") or q["tets"])        # grey surface with the mesh edges: no result colours before Solve
            return
        r = self.result
        vals, leg = self.field_values()
        self.view.show_result(r["nodes"], r["conn"], np.zeros_like(r["nodes"]), vals, 0.0, self.cb_edges.isChecked(), leg["lo"], leg["hi"], False,
                              legend={"title": leg["title"], "labels": leg["labels"], "subtitle": leg["subtitle"]})

    def colours_changed(self, *_a):
        try:
            if self.result is not None:
                self.show_field()
        except RuntimeError:
            result_style.unsubscribe(self.cmap_combo._external)        # the window is gone

    # ------------------------------------------------------------------ the pictures of a transient run
    def apply_frame(self, k):
        """Shows picture k of a transient result (the colours only change: the part does not move)."""
        if self.result is None:
            return
        n = tm.frame_count(self.result)
        k = max(0, min(int(k), n - 1))
        self.frame = k
        self.slider.blockSignals(True)
        self.slider.setValue(k)
        self.slider.blockSignals(False)
        self.time_lbl.setText(self.time_text(k))
        vals, _leg = self.field_values(k)
        self.view.set_ramp(k / (n - 1) if n > 1 else 1.0, vals)
        if self.last_probe is not None:
            self.show_probe(self.last_probe)

    def slider_moved(self, v):
        self.apply_frame(v)

    def anim_toggled(self, on):
        self.anim_box.setVisible(on)
        if not on:
            self.anim_stop()

    def anim_inputs(self, what):
        try:
            dur = float(self.e_dur.text().replace(",", "."))
        except ValueError:
            QMessageBox.warning(self, what, "The duration must be a number.")
            return None
        if dur <= 0:
            QMessageBox.warning(self, what, "The duration must be greater than zero.")
            return None
        return dur

    def anim_play(self):
        if self.result is None or tm.frame_count(self.result) < 2:
            QMessageBox.information(self, "Animate", "Solve a transient analysis first: a steady result has one picture.")
            return
        dur = self.anim_inputs("Animate")
        if dur is None:
            return
        n = tm.frame_count(self.result)
        self.anim_timer.stop()
        self.anim_dir, self.anim_k = 1, 0
        self.apply_frame(0)
        self.anim_timer.start(max(10, int(dur * 1000 / n)))

    def anim_step(self):
        n = tm.frame_count(self.result) if self.result is not None else 0
        if n < 2:
            self.anim_timer.stop()
            return
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
        self.apply_frame(k)

    def anim_stop(self):
        self.anim_timer.stop()

    def export_animation(self, path_fmt=None, dur=None):
        """Saves the pictures of a transient run as WebP / PNG / GIF / MP4 / PNG pictures.  `path_fmt` = (path, format), or a plain path read by its extension,
        skips the Save box.  -> the path written or None."""
        r = self.result
        if r is None or tm.frame_count(r) < 2:
            QMessageBox.information(self, "Export animation", "Solve a transient analysis first: a steady result has one picture.")
            return None
        if isinstance(path_fmt, str):
            fmt = {".webp": "webp", ".mp4": "mp4", ".png": "png"}.get(os.path.splitext(path_fmt)[1].lower(), "gif")
            path_fmt = (path_fmt, fmt)
        d = float(dur) if dur else self.anim_inputs("Export animation")
        if d is None:
            return None
        n = tm.frame_count(r)
        self.anim_timer.stop()
        keep = self.cur_frame()
        self.apply_frame(n - 1)
        self.show_field()
        sess = self.view.export_session()
        if sess is None:
            QMessageBox.information(self, "Export animation", "The 3D view is not available here, so there is nothing to draw the pictures with.")
            return None
        state = {"bg": None}

        def grab(k):
            vals, _leg = self.field_values(k)
            return sess.frame(k / (n - 1), vals, state["bg"])

        def set_bg(level):
            state["bg"] = level
        try:
            return anim_export.export(self, LABEL, n, grab, n / d, self.loop_combo.currentIndex(), say=self.say, path_fmt=path_fmt, set_bg=set_bg)
        except Exception as ex:                                  # noqa: BLE001 - a drawing failure is shown, not raised into the event loop
            self.say(f"Could not render the animation: {ex}")
            return None
        finally:
            sess.close()
            self.apply_frame(keep)

    # ------------------------------------------------------------------ probes
    def set_probe_mode(self, on):
        self.view.probe_mode = bool(on)
        self.view.on_probe = self.probe_at if on else None
        self.say("Click the solved part to read the values there." if on else "Probe off: a click picks a face again.")

    def probe_at(self, point):
        if self.result is None or point is None:
            self.probe_lbl.setText("Solve first, then click the coloured part.")
            return None
        nodes = self.result["nodes"]
        i = int(np.argmin(np.linalg.norm(nodes - np.asarray(point, float), axis=1)))
        return self.probe_index(i, float(np.linalg.norm(nodes[i] - np.asarray(point, float))))

    def probe_node(self):
        if self.result is None:
            self.probe_lbl.setText("Solve first.")
            return None
        try:
            p = [l_in(float(x)) for x in self.e_probe.text().replace(";", ",").split(",")]
            assert len(p) == 3
        except Exception:                                      # noqa: BLE001
            self.probe_lbl.setText(f"Type the point as x, y, z ({UD()['L']}).")
            return None
        nodes = self.result["nodes"]
        i = int(np.argmin(np.linalg.norm(nodes - np.asarray(p, float), axis=1)))
        return self.probe_index(i, float(np.linalg.norm(nodes[i] - np.asarray(p, float))))

    def probe_index(self, i, dist):
        """-> (node, distance mm, temperature K, heat flux magnitude W/m2) at the picture on show."""
        self.last_probe = {"i": int(i), "dist": float(dist)}
        self.show_probe(self.last_probe)
        d = self.nodal(self.cur_frame())
        return int(i), float(dist), float(d["T"][i]), float(d["qmag"][i])

    def show_probe(self, pr):
        r = self.result
        if r is None:
            return
        i = pr["i"]
        fam = self.family()
        D = UD()
        d = self.nodal(self.cur_frame())
        x = r["nodes"][i]
        e = int(np.argmax((np.asarray(r["conn"]) == i).any(axis=1)))
        bods = r.get("bodies") or []
        bi = int(r["body"][e]) if r.get("body") is not None else 0
        who = bods[bi]["name"] if 0 <= bi < len(bods) and len(bods) > 1 else None
        q = lambda a: R.num(fam.from_si("q", float(a)), 4)
        rows = [("Temperature", R.num(fam.from_si("T", float(d["T"][i])), 5), fam.temp), ("Heat flux magnitude", q(d["qmag"][i]), fam.unit("q")),
                ("Heat flux X", q(d["qx"][i]), fam.unit("q")), ("Heat flux Y", q(d["qy"][i]), fam.unit("q")), ("Heat flux Z", q(d["qz"][i]), fam.unit("q"))]
        where = (f"node {i} at ({R.num(l_out(x[0]))}, {R.num(l_out(x[1]))}, {R.num(l_out(x[2]))}) {D['L']}, {R.num(l_out(pr['dist']), 3)} {D['L']} from the point"
                 + (f", in {who}" if who else "") + (f", {self.time_text(self.cur_frame())}" if tm.frame_count(r) > 1 else ""))
        self.probe_lbl.setText(R.heading("Probe") + R.note(where) + R.kv(rows) + R.note("Heat flux: the average of the elements around the node."))

    # ------------------------------------------------------------------ a state (a parametric study, a test) in and out
    def import_state(self, st):
        s = st.get("setup") or tm.default_setup()
        s.setdefault("dims", {})
        s.setdefault("splits", [])
        s.setdefault("bond_tol", 0.0)
        s.setdefault("body_mats", {})
        s.setdefault("body_h", {})
        self.migrate_setup(s)
        s["mesh"] = smesh.complete(s.get("mesh"))
        dims_changed = (s["dims"] != self.setup.get("dims") or s["splits"] != (self.setup.get("splits") or []) or s["bond_tol"] != self.setup.get("bond_tol")
                        or s["body_mats"] != self.setup.get("body_mats"))
        self.setup = json.loads(json.dumps(s))
        self.put_physics()
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
            self.sync_time_controls()
            self.describe()
            self.show_field()
        else:
            self.invalidate()

    # ------------------------------------------------------------------ the test example, the self-check, the diagnostics report
    def load_example(self, folder=None):
        """Makes the test project (parts, assembly, conditions) in a new folder and opens it in this window.  -> True when it is loaded."""
        import thermal3d_example as ex
        return ex.load_example(self, folder)

    def run_self_check(self):
        """Solves the problems with known answers and shows the numbers side by side.  -> the rows (see thermal3d_example.self_check)."""
        import thermal3d_example as ex
        return ex.run_self_check(self)

    def diagnostics_text(self):
        import thermal3d_example as ex
        return ex.diagnostics_text(self)

    def show_diagnostics(self):
        solid_diag.show_report(self, self.diagnostics_text(), self.path if self.project_ok() else None, "3D Thermal diagnostics report")


def make_thermal3d(host, path=None):
    thermal3d_ext.ensure_registered()
    if path:
        return ThermalWindow.open_project(host, path)
    return ThermalWindow(shell=host)


thermal3d_ext.ensure_registered()
