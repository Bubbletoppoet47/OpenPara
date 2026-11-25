"""
cfd3d_tab.py - the 3D Fluid Flow window (project folder .gpw): the steady flow of air or water around a 3D part, with the temperature of the fluid, and the
force, the pressure and the heat that the fluid puts on the part.

It is the 3D Thermal window (solid_base.SolidBase) with a fluid in place of the solid: the same project bar, Geometry (the part, its faces), Mesh (element sizes,
advanced options, quality) and Solve button with its progress bar.  What is particular here:

  Fluid and flow   the fluid (density, viscosity; conductivity and specific heat for the temperature), its speed and the direction it flows in
  Domain           how far the box of fluid reaches upstream, downstream and sideways of the part (the part is cut out of it)
  Conditions       on the faces of the part, picked in the view:  wall temperature  -  wall heat flux (into the fluid)  -  adiabatic wall.  The fluid sticks to
                   every face of the part (no slip); the box faces are: inlet, outlet, and slip planes at the sides
  Mesh             tetrahedra of the air: small at the part, growing to the size far away
  Results          speed, pressure, temperature and velocity components: on the part, on a slice through the fluid and along flow lines; the force and the
                   heat on the part; the mass and energy balances; a probe

The solver is cfd3d_flow.py (laminar, steady, stabilised linear tetrahedra), the mesher cfd3d_mesh.py and the setup layer cfd3d_model.py (no Qt in any); the test
example and the self-check are in cfd3d_example.py.
"""
import json
import os

import numpy as np
from PyQt6.QtCore import QPointF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import cfd3d_ext
import cfd3d_flow as cf
import cfd3d_model as cm
import cfd3d_view as fv
import physics_cfd as pcfd
import result_style
import sim_report as R
import sim_ui
import solid_diag
import solid_fem as fem
import solid_geom as sg
import solid_mesh as smesh
import solid_model as sm
import solid_progress
import solid_view as sv
import thermal_units as tu
import unitctl
import units
from solid_base import SolidBase, UD, l_in, l_out, num

KIND = "fluid3d"
LABEL = "3D Fluid Flow"
CUSTOM = "Custom"

# (key, name, quantity)  quantity: V speed, S pressure, T temperature
FIELDS = [("speed", "Speed", "V"), ("p", "Pressure", "S"), ("T", "Temperature", "T"), ("ux", "Velocity X", "V"), ("uy", "Velocity Y", "V"), ("uz", "Velocity Z", "V")]
PLAIN_PART = ("speed", "ux", "uy", "uz")                   # fields that are zero on a wall: the part is drawn grey
COLOURS = {"temps": sv.SUPPORT, "fluxes": sv.LOAD, "ins": (0.45, 0.62, 0.45)}
SPECS = {"temps": [("T", "T", "Temperature ({u})")], "fluxes": [("q", "q", "Heat flux ({u})")], "ins": []}
TITLES = {"temps": "Wall temperature on the selected faces", "fluxes": "Wall heat flux on the selected faces", "ins": "Adiabatic wall"}
NOTES = {
    "temps": "The selected faces of the part are held at this temperature (a heater, a cooled plate). The fluid takes heat from them or gives heat to them.",
    "fluxes": "Heat pushed from the faces into the fluid, per unit of area. Positive heats the fluid.",
    "ins": "",
}
DEFAULTS = {"T": 323.15, "q": 1000.0}
DIR_ITEMS = [(k, f"{cm.DIR_TEXT[k]}") for k in ("+x", "-x", "+y", "-y", "+z", "-z")]
SCENE_DELAY_MS = 120


def pressure_unit():
    """-> (name, Pa per unit): the pressure unit this window shows.  The pressures of a slow air or water flow are fractions of a pascal to some kilopascals, so
    the stress unit of the unit system (MPa, ksi ...) would show 0.000000002: Pa in the metric systems, psf in the US ones."""
    return ("psf", 47.88025898034) if unitctl.system().startswith("US") else ("Pa", 1.0)


def box_text(v):
    v = float(v)
    short = f"{v:.6g}"
    return short if abs(float(short) - v) <= 1e-9 * abs(v) else f"{v:.10g}"


def insulated_icon():
    """The button picture of 'Adiabatic wall': a wall with the slanted ticks of insulation on one side."""
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    q = QPainter(pm)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    q.setPen(QPen(QColor("#0e7f86"), 4))
    q.drawLine(QPointF(8, 34), QPointF(40, 34))
    q.setPen(QPen(QColor("#5b6770"), 3))
    for x in (10, 18, 26, 34):
        q.drawLine(QPointF(x, 34), QPointF(x + 5, 42))
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
    if key == "temps" and not v["T"] > 0:
        return "That is below absolute zero."
    return None


class FluidWindow(SolidBase):
    kind = KIND
    label = LABEL
    MESH_SEC = 5
    RESULTS_SEC = 6
    CONDITION_KINDS = cm.CONDITION_KINDS
    _box_key = None

    def __init__(self, *a, **k):
        self.last_vals = {}
        self.check_rows = None
        self._nodal_cache = {}
        super().__init__(*a, **k)
        unitctl.on_heat_change(self.heat_changed)
        self.put_physics()                                                   # the boxes show the defaults of the setup (air, 0.05 m/s ...) before any part is imported
        self.refresh_labels()
        self.scene_timer = QTimer(self)
        self.scene_timer.setSingleShot(True)
        self.scene_timer.timeout.connect(self.show_field)
        if self.path is None and self.geom is None:
            self.say("3D Fluid Flow: import a part, or press Load test example (Test and diagnostics, at the bottom of the panel).")

    @property
    def example_info(self):
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
        return tu.family_of(unitctl.system())

    def heat_changed(self, *_a):
        try:
            self.units_changed()
        except RuntimeError:
            unitctl.off_heat_change(self.heat_changed)

    def closeEvent(self, ev):
        unitctl.off_heat_change(self.heat_changed)
        super().closeEvent(ev)

    # ------------------------------------------------------------------ what SolidBase asks of the window (its hooks)
    def new_setup(self):
        return cm.default_setup()

    def make_view(self):
        return fv.FluidView(self)

    def build_geometry_section(self):
        super().build_geometry_section()
        for w in [self.split_lbl, self.sp_cols, self.sp_rows, self.b_split, self.b_unsplit, self.split_hdr, self.split_list, self.sz_table, self.b_setsize,
                  self.b_even] + list(self.split_words):
            w.setVisible(False)                                                   # a face of the part is a wall as a whole: no patches in 3D Fluid Flow yet

    def build_mesh_extras(self, v):
        i = self.type_combo.findData("hexdom")
        if i >= 0:
            self.type_combo.removeItem(i)
        self.order_combo.clear()
        self.order_combo.addItem("Linear (the flow elements)", 1)
        self.order_combo.setEnabled(False)
        form = QFormLayout()
        self.e_hfar = QLineEdit()
        self.e_hfar.setPlaceholderText("automatic")
        self.e_hfar.setToolTip("The element size far from the part, at the faces of the box. The elements grow from the size on the part (the table above) to this "
                               "one by the growth rate of the advanced options. Blank = automatic (about a seventh of the longest side of the box).")
        self.e_hfar.editingFinished.connect(self.inputs_changed)
        self.lbl_hfar = QLabel("Element size far away")
        form.addRow(self.lbl_hfar, self.e_hfar)
        v.addLayout(form)
        v.addWidget(self.hint("The air around the part is meshed with linear tetrahedra: small at the part (the size in the table), growing to the size far away. "
                              "The flow is first-order accurate: check a result by meshing finer and comparing."))

    def put_mesh_extras(self):
        d = float((self.setup.get("domain") or {}).get("h_far") or 0.0)
        self.e_hfar.setText(format(l_out(d), ".8g") if d else "")
        self.lbl_hfar.setText(f"Element size far away ({UD()['L']})")

    def read_mesh_more(self):
        self.setup.setdefault("domain", cm.default_setup()["domain"])
        self.setup["domain"]["h_far"] = self.parse_size(self.e_hfar.text(), "Element size far away")
        self.setup["mesh"]["order"] = 1

    def refresh_study_button(self):
        self.study_box.setVisible(False)                                           # no parametric study for 3D Fluid Flow yet

    def study_adapter(self):
        raise NotImplementedError("3D Fluid Flow has no parametric study yet")

    def refresh_labels(self):
        fam = self.family()
        D = UD()
        for lab, text in ((self.lbl_rho, f"Density ({D['rho']})"), (self.lbl_mu, f"Viscosity ({D['mu']})"), (self.lbl_speed, f"Speed ({D['V']})"),
                          (self.lbl_k, f"Conductivity k ({fam.unit('k')})"), (self.lbl_cp, f"Specific heat ({fam.unit('cp')})"),
                          (self.lbl_Tin, f"Inflow temperature ({fam.temp})")):
            lab.setText(text)
        super().refresh_labels()
        self.h_label.setText(f"Element size on the part ({D['L']}, blank = automatic)")
        self.e_probe.setPlaceholderText(f"x, y, z  ({D['L']})")
        for i, (_key, name, q) in enumerate(FIELDS):
            self.cb_field.setItemText(i, f"{name} ({self.quantity_unit(q)})")
        if hasattr(self, "lbl_hfar"):
            self.lbl_hfar.setText(f"Element size far away ({D['L']})")

    def quantity_unit(self, q):
        D, fam = UD(), self.family()
        return {"V": D["V"], "S": pressure_unit()[0], "T": fam.temp}[q]

    def quantity_from_si(self, q, v):
        D, fam = UD(), self.family()
        if q == "V":
            return np.asarray(v, float) / D["V_ms"]
        if q == "S":
            return np.asarray(v, float) / pressure_unit()[1]
        return fam.from_si("T", np.asarray(v, float))

    def read_physics(self):
        n = unitctl.system()
        fam = self.family()
        f = {"name": self.fluid_combo.currentText(), "rho": units.density_to_si(num(self.e_rho, "Density"), n), "mu": units.viscosity_to_si(num(self.e_mu, "Viscosity"), n),
             "k": fam.to_si("k", num(self.e_k, "Conductivity")), "cp": fam.to_si("cp", num(self.e_cp, "Specific heat"))}
        flow = {"speed": units.speed_to_si(num(self.e_speed, "Speed"), n), "dir": self.dir_combo.currentData(), "heat": self.cb_heat.isChecked(),
                "T_in": fam.to_si("T", num(self.e_Tin, "Inflow temperature"))}
        dom = {"up": num(self.e_up, "Margin upstream"), "down": num(self.e_down, "Margin downstream"), "side": num(self.e_side, "Margin at the sides"),
               "h_far": float((self.setup.get("domain") or {}).get("h_far") or 0.0)}
        return {"fluid": f, "flow": flow, "domain": dom}

    def store_physics(self, p):
        f = dict(p["fluid"])
        lib = pcfd.FLUIDS.get(f["name"])
        if f["name"] != CUSTOM and lib is not None and lib[0] is not None and (abs(f["rho"] - lib[0]) > 1e-6 * lib[0] or abs(f["mu"] - lib[1]) > 1e-6 * lib[1]):
            f["name"] = CUSTOM                                                      # the numbers were typed over: it is not that fluid any more
            self.fluid_combo.blockSignals(True)
            self.fluid_combo.setCurrentText(CUSTOM)
            self.fluid_combo.blockSignals(False)
        self.setup["fluid"] = f
        self.setup["flow"] = p["flow"]
        self.setup["domain"] = dict(self.setup.get("domain") or {}, **{k: p["domain"][k] for k in ("up", "down", "side")})

    def after_inputs(self):
        self.heat_box.setVisible(self.cb_heat.isChecked())
        self.update_info()
        self.update_cond_note()
        self.draw_domain()

    def stop_playback(self):
        pass

    def show_no_result(self, had):
        self.res_lbl.setText("The setup changed since the last solve: press Solve." if had else "No result yet.")
        self._nodal_cache = {}

    def enable_results_buttons(self):
        pass

    def put_physics(self):
        s = self.setup
        fam = self.family()
        n = unitctl.system()
        f, flow, dom = s["fluid"], s["flow"], s["domain"]
        widgets = (self.fluid_combo, self.dir_combo, self.cb_heat)
        for wd in widgets:
            wd.blockSignals(True)
        i = self.fluid_combo.findText(f.get("name") or CUSTOM)
        self.fluid_combo.setCurrentIndex(i if i >= 0 else self.fluid_combo.findText(CUSTOM))
        self.dir_combo.setCurrentIndex(max(0, self.dir_combo.findData(flow.get("dir", "+x"))))
        self.cb_heat.setChecked(bool(flow.get("heat")))
        for wd in widgets:
            wd.blockSignals(False)
        self.e_rho.setText(box_text(units.density_from_si(float(f["rho"]), n)))
        self.e_mu.setText(f"{units.viscosity_from_si(float(f['mu']), n):.6g}")
        self.e_speed.setText(box_text(units.speed_from_si(float(flow["speed"]), n)))
        self.e_k.setText(box_text(fam.from_si("k", float(f.get("k") or 0.0))))
        self.e_cp.setText(box_text(fam.from_si("cp", float(f.get("cp") or 0.0))))
        self.e_Tin.setText(box_text(fam.from_si("T", float(flow.get("T_in") or 293.15))))
        self.e_up.setText(box_text(dom["up"]))
        self.e_down.setText(box_text(dom["down"]))
        self.e_side.setText(box_text(dom["side"]))
        self.heat_box.setVisible(bool(flow.get("heat")))
        self.update_info()

    def units_results(self):
        if self.result is not None:
            self._nodal_cache = {}
            self.describe()
            self.show_field()
        if self.last_probe is not None:
            self.show_probe(self.last_probe)

    def has_conditions(self):
        return any(self.setup.get(k) for k in cm.KEYS)

    def condition_colours(self, cols):
        for key in cm.KEYS:
            for i, c in enumerate(self.setup.get(key) or []):
                if not self.cond_wants("Conditions", c):
                    continue
                try:
                    fids = sm._fids(self.geom, c["faces"], sm.name_of(cm.NAMES[key], i, c))
                except fem.FemError:
                    continue
                for f in fids:
                    cols[f] = COLOURS[key]

    def colour(self):
        super().colour()
        self.draw_domain()

    def reset_source_setup(self):
        keep = {k: self.setup[k] for k in ("mesh",) if k in self.setup}
        fresh = cm.default_setup()
        fresh.update(keep)
        self.setup = fresh
        self.cur_body = None
        self.put_physics()

    def use_source_material(self, mat):
        pass                                                                      # the material of the part does not matter to the fluid

    def migrate_setup(self, st):
        fresh = cm.default_setup()
        for k, v in fresh.items():
            st.setdefault(k, v)
        for k in ("fluid", "flow", "domain"):
            st[k] = dict(fresh[k], **(st.get(k) or {}))
        for k in cm.KEYS:
            st[k] = list(st.get(k) or [])
        return []

    def restore_boxes(self):
        self.put_physics()
        super().restore_boxes()

    # ------------------------------------------------------------------ the panel
    def build_physics_sections(self):
        self.build_fluid_section()
        self.build_domain_section()
        self.build_condition_section()

    def build_fluid_section(self):
        v = self.sec(2, "Fluid and flow", True, summary=lambda: f"{self.fluid_combo.currentText()}, {self.e_speed.text()} {UD()['V']}",
                     help_text="The fluid and how fast it flows past the part. The flow is laminar and steady: it is right for slow flows (a Reynolds number up to about "
                               "100 to 150 for a blunt part, higher for a streamlined one). Faster flows are turbulent or shed vortices in reality, and then this "
                               "result is only a steady approximation. The fluid enters the box on the face opposite to the direction it flows toward, and leaves "
                               "on the face it flows toward. 'Solve the temperature too' adds the heat exchange with the faces that have a temperature or a heat "
                               "flux. Typical fluid values: check your source.")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.fluid_combo = QComboBox()
        for n_ in pcfd.FLUIDS:
            self.fluid_combo.addItem(n_)
        self.fluid_combo.activated.connect(self.fluid_picked)
        form.addRow("Fluid", self.fluid_combo)
        self.e_rho, self.e_mu, self.e_speed = QLineEdit(), QLineEdit(), QLineEdit()
        self.lbl_rho, self.lbl_mu, self.lbl_speed = QLabel(), QLabel(), QLabel()
        for lab, e in ((self.lbl_rho, self.e_rho), (self.lbl_mu, self.e_mu), (self.lbl_speed, self.e_speed)):
            form.addRow(lab, e)
            e.editingFinished.connect(self.inputs_changed)
        self.dir_combo = QComboBox()
        for k, text in DIR_ITEMS:
            self.dir_combo.addItem(text, k)
        self.dir_combo.activated.connect(lambda _i: self.inputs_changed())
        form.addRow("The fluid flows", self.dir_combo)
        v.addLayout(form)
        self.re_lbl = QLabel("")
        self.re_lbl.setWordWrap(True)
        v.addWidget(self.re_lbl)
        self.cb_heat = QCheckBox("Solve the temperature too")
        self.cb_heat.setToolTip("Adds the temperature of the fluid: the fluid enters at the inflow temperature and is warmed or cooled by the faces that have a "
                                "wall temperature or a wall heat flux (Conditions). The flow itself does not depend on the temperature.")
        self.cb_heat.toggled.connect(lambda _on: self.inputs_changed())
        v.addWidget(self.cb_heat)
        self.heat_box = QWidget()
        hl = QFormLayout(self.heat_box)
        hl.setContentsMargins(14, 0, 0, 0)
        self.e_k, self.e_cp, self.e_Tin = QLineEdit(), QLineEdit(), QLineEdit()
        self.lbl_k, self.lbl_cp, self.lbl_Tin = QLabel(), QLabel(), QLabel()
        for lab, e in ((self.lbl_k, self.e_k), (self.lbl_cp, self.e_cp), (self.lbl_Tin, self.e_Tin)):
            hl.addRow(lab, e)
            e.editingFinished.connect(self.inputs_changed)
        self.heat_box.setVisible(False)
        v.addWidget(self.heat_box)
        self.fluid_note = QLabel("")
        self.fluid_note.setWordWrap(True)
        self.fluid_note.setStyleSheet("color:#707070;")
        v.addWidget(self.fluid_note)

    def fluid_picked(self, *_a):
        name = self.fluid_combo.currentText()
        rho, mu = pcfd.FLUIDS.get(name, (None, None))
        if rho is not None:
            n = unitctl.system()
            fam = self.family()
            self.e_rho.setText(box_text(units.density_from_si(rho, n)))
            self.e_mu.setText(f"{units.viscosity_from_si(mu, n):.6g}")
            k, cp = pcfd.FLUID_HEAT.get(name, (None, None))
            if k is not None:
                self.e_k.setText(box_text(fam.from_si("k", k)))
                self.e_cp.setText(box_text(fam.from_si("cp", cp)))
        self.inputs_changed()

    def build_domain_section(self):
        v = self.sec(3, "Domain", True, summary=lambda: self.dom_lbl.text().split("\n")[0][:80],
                     help_text="The fluid is a box around the part; the part is cut out of it. The margins say how far the box reaches beyond the part - upstream "
                               "(where the fluid comes from), downstream (where it leaves) and at the sides - in multiples of the part's largest size. A box that "
                               "is too small squeezes the flow (the walls of the box are slip planes: the fluid slides along them); a long way downstream lets the "
                               "wake settle before the outlet. A bigger box needs more elements. The box is drawn around the part.")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.e_up, self.e_down, self.e_side = QLineEdit(), QLineEdit(), QLineEdit()
        for text, e in (("Margin upstream (x the size of the part)", self.e_up), ("Margin downstream (x the size)", self.e_down),
                        ("Margin at the sides (x the size)", self.e_side)):
            form.addRow(text, e)
            e.editingFinished.connect(self.inputs_changed)
        v.addLayout(form)
        self.dom_lbl = QLabel("")
        self.dom_lbl.setWordWrap(True)
        v.addWidget(self.dom_lbl)

    def update_info(self):
        """The Reynolds number, the size of the box and its share of the cross-section: what to look at before pressing Solve."""
        g = self.geom
        if g is None or g.get("bodies") or not hasattr(self, "re_lbl"):
            if hasattr(self, "re_lbl"):
                self.re_lbl.setText("")
                self.dom_lbl.setText("No part yet.")
            return
        s = self.setup
        D = UD()
        try:
            L = cm.part_size(g) * 1e-3
            re = float(s["fluid"]["rho"]) * float(s["flow"]["speed"]) * L / float(s["fluid"]["mu"])
            lo, hi = cm.domain_box(g, s)
            ext = hi - lo
            _a, block = cm.frontal_area(g, s)
            n = cm.estimate_nodes(g, s)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return
        hot = re > cm.RE_STEADY
        self.re_lbl.setText(f"Reynolds number about {re:,.0f} (size of the part {R.num(l_out(cm.part_size(g)), 4)} {D['L']})"
                            + (": too high for a steady laminar flow, the result is an approximation." if hot else "."))
        self.re_lbl.setStyleSheet("color:#b36b00;" if hot else "color:#555555;")
        self.dom_lbl.setText(f"Box {R.num(l_out(ext[0]), 4)} x {R.num(l_out(ext[1]), 4)} x {R.num(l_out(ext[2]), 4)} {D['L']}; the part covers {block * 100:.0f} % "
                             f"of its cross-section; about {n:,} nodes.")

    def draw_domain(self):
        key = None
        if self.geom is not None and not self.geom.get("bodies"):
            try:
                lo, hi = cm.domain_box(self.geom, self.setup)
                key = tuple(round(float(x), 6) for x in list(lo) + list(hi))
            except (KeyError, TypeError, ValueError):
                key = None
        if key == self._box_key and self.view.line_data.get("domain") is not None:
            return
        self._box_key = key
        self.view.set_lines("domain", fv.box_segments(lo, hi) if key else [], color=(0.35, 0.45, 0.65), width=1.0)

    def build_condition_section(self):
        v = self.sec(4, "Conditions", True, summary=lambda: f"{sum(len(self.setup.get(k) or []) for k in cm.KEYS)} condition(s)",
                     help_text="The fluid sticks to every face of the part (no slip). Here you say what the faces do with HEAT: select the face(s) in the view first "
                               "(click them; Ctrl or Shift for several), then press a button. Wall temperature holds the faces at a temperature; wall heat flux "
                               "pushes heat from the faces into the fluid; a face with no condition is adiabatic (no heat passes). These conditions act only when "
                               "'Solve the temperature too' is ticked under Fluid and flow. Double-click a Name to rename it; double-click a value to change it.")
        v.addWidget(self.hint("Select the face(s) first (click them in the view), then press a button."))
        for text, icn, key, tip in (("Wall temperature...", "fixed", "temps", "Holds the selected faces of the part at a temperature."),
                                    ("Wall heat flux...", "pressure", "fluxes", "Heat per unit of area from the selected faces into the fluid."),
                                    ("Adiabatic wall", None, "ins", "No heat passes through the selected faces. Faces with no condition are adiabatic too: this "
                                                                    "only makes the choice visible.")):
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
        self.cond_table.setMinimumHeight(90)
        self.cond_table.setMaximumHeight(190)
        self.cond_table.horizontalHeader().setStretchLastSection(True)
        self.cond_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cond_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cond_table.itemChanged.connect(self.cond_item_changed)
        self.cond_table.cellDoubleClicked.connect(self.cond_double_clicked)
        v.addWidget(self.cond_table)
        self.cond_note = QLabel("")
        self.cond_note.setWordWrap(True)
        self.cond_note.setStyleSheet("color:#b36b00;")
        v.addWidget(self.cond_note)
        row = QHBoxLayout()
        b = QPushButton("Edit selected...")
        b.clicked.connect(self.edit_condition)
        row.addWidget(b)
        b = QPushButton("Remove selected")
        b.clicked.connect(self.remove_condition)
        row.addWidget(b)
        v.addLayout(row)

    def build_results_section(self):
        v = self.sec(self.RESULTS_SEC, "Results", True, summary=lambda: self.cb_field.currentText(),
                     help_text="Choose a field: speed, pressure, temperature or a velocity component. It is drawn on the surface of the part (speed and velocity are "
                               "zero there: the fluid sticks) and, if you tick them, on a slice through the fluid and along flow lines (the paths of particles "
                               "carried by the fluid). The report under the picture gives the force on the part split into pressure and friction, the drag "
                               "coefficient, the heat of every condition and the checks: the fluid that enters must leave (mass balance), the heat carried away "
                               "must equal the heat from the walls (energy balance). The values are what the equations gave at the nodes, nothing is smoothed.")
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
        self.cb_slice = QCheckBox("Slice through the fluid")
        self.cb_slice.setChecked(True)
        self.cb_slice.toggled.connect(lambda _on: self.scene_changed())
        v.addWidget(self.cb_slice)
        self.slice_box = QWidget()
        sl = QFormLayout(self.slice_box)
        sl.setContentsMargins(14, 0, 0, 0)
        self.slice_axis = QComboBox()
        for k, text in ((0, "across X (a plane of constant X)"), (1, "across Y"), (2, "across Z")):
            self.slice_axis.addItem(text, k)
        self.slice_axis.setCurrentIndex(2)
        self.slice_axis.activated.connect(lambda _i: self.scene_changed())
        self.slice_pos = QSlider(Qt.Orientation.Horizontal)
        self.slice_pos.setRange(0, 100)
        self.slice_pos.setValue(50)
        self.slice_pos.valueChanged.connect(lambda _v: self.scene_changed())
        sl.addRow("Plane", self.slice_axis)
        sl.addRow("Position", self.slice_pos)
        v.addWidget(self.slice_box)
        self.cb_lines = QCheckBox("Flow lines")
        self.cb_lines.setChecked(True)
        self.cb_lines.toggled.connect(lambda _on: self.scene_changed())
        v.addWidget(self.cb_lines)
        self.lines_box = QWidget()
        ll = QFormLayout(self.lines_box)
        ll.setContentsMargins(14, 0, 0, 0)
        self.sp_lines = QSpinBox()
        self.sp_lines.setRange(4, 900)
        self.sp_lines.setValue(49)
        self.sp_lines.setToolTip("About this many flow lines, started on a grid across the flow just inside the inlet and following the fluid downstream.")
        self.sp_lines.valueChanged.connect(lambda _v: self.scene_changed())
        ll.addRow("Number of lines", self.sp_lines)
        v.addWidget(self.lines_box)
        self.res_lbl = QLabel("No result yet.")
        self.res_lbl.setWordWrap(True)
        self.res_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.res_lbl)
        v.addWidget(QLabel("<b>Probe</b>"))
        self.b_probe = QPushButton("Probe by clicking the surface of the part")
        self.b_probe.setCheckable(True)
        self.b_probe.setToolTip("Switch this on, then click the solved part: the values of the node nearest to the click appear below.")
        self.b_probe.toggled.connect(self.set_probe_mode)
        v.addWidget(self.b_probe)
        row = QHBoxLayout()
        self.e_probe = QLineEdit()
        row.addWidget(self.e_probe, 1)
        b = QPushButton("Probe nearest node")
        b.setToolTip("The values at the node of the fluid mesh nearest to the point typed in the box (x, y, z): anywhere in the fluid, not only on the part.")
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
        self.slice_box.setVisible(True)

    def build_test_section(self):
        v = self.sec(self.RESULTS_SEC + 1, "Test and diagnostics", True,
                     help_text="Load test example makes a ready project (an air flow past a part, with a hot face) in a folder you choose; press Solve to run it. "
                               "Run self-check solves small problems whose answer is known and prints the numbers beside PASS or FAIL. Diagnostics report... "
                               "gathers the computer, the program, the geometry, the mesh, the setup, the time of every stage, the solver and every message "
                               "in one text: copy it or find it in the project folder as diagnostics.txt.")
        v.addWidget(self.hint("For testing the add-on: the report is what to send back when something is wrong."))
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

    # ------------------------------------------------------------------ the conditions
    def cond_rows(self):
        return [(key, i) for key in cm.KEYS for i in range(len(self.setup.get(key) or []))]

    def cond_ref(self, r):
        rows = self.cond_rows()
        return rows[r] if 0 <= r < len(rows) else (None, -1)

    def value_text(self, key, c):
        fam = self.family()
        if key == "temps":
            return f"{box_text(fam.from_si('T', c['T']))} {fam.temp}"
        if key == "fluxes":
            return f"{box_text(fam.from_si('q', c['q']))} {fam.unit('q')}"
        return ""

    def applied_text(self, key, i, c):
        try:
            fids = sm._fids(self.geom, c["faces"], sm.name_of(cm.NAMES[key], i, c)) if self.geom is not None else []
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
            for col, text in enumerate((sm.name_of(cm.NAMES[key], i, c), cm.NAMES[key], self.applied_text(key, i, c), self.value_text(key, c))):
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
                why = cm.check_ready(self.setup, self.geom)
            except Exception:                                                      # noqa: BLE001 - a note, never an error
                why = None
        if why is None and self.has_conditions() and not self.setup["flow"].get("heat"):
            why = "These conditions act only when 'Solve the temperature too' is ticked (Fluid and flow)."
        if why is None and self.setup["flow"].get("heat") and not (self.setup.get("temps") or self.setup.get("fluxes")):
            why = "No face has a temperature or a heat flux: the fluid stays at the inflow temperature."
        self.cond_note.setText(why or "")

    def cond_item_changed(self, it):
        if it.column() != 0:
            return
        key, i = self.cond_ref(it.row())
        if key is None:
            return
        item = self.setup[key][i]
        text = it.text().strip()
        if text and text != sm.name_of(cm.NAMES[key], i):
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
        fam = self.family()
        labels, defaults = [], []
        for k, q, lab in SPECS[key]:
            v = float((cur or {}).get(k, self.last_vals.get(k, DEFAULTS[k])))
            labels.append(lab.format(u=fam.temp if q == "T" else fam.unit(q)))
            defaults.append(box_text(fam.from_si(q, v)))
        got = ask_values(self, TITLES[key], NOTES[key], labels, defaults)
        if got is None:
            return None
        vals = {k: fam.to_si(q, x) for (k, q, _l), x in zip(SPECS[key], got)}
        why = value_problem(key, vals)
        if why:
            QMessageBox.warning(self, TITLES[key], why)
            return None
        self.last_vals.update(vals)
        return vals

    def add_cond(self, key):
        return self.add_condition(key)

    def add_condition(self, key, values=None, fids=None, name=None):
        """Adds a condition of kind `key` (one of cm.KEYS) on faces (the selected ones by default).  Without `values` a small box asks for them."""
        if self.geom is None:
            self.say("Import a part first.")
            return False
        fids = self.sel_faces if fids is None else fids
        if not fids:
            self.say("Select the face(s) first.")
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
        item = {"name": name or f"{cm.NAMES[key]} {n}", "faces": [sg.face_sig(self.geom, f) for f in fids]}
        item.update(values)
        self.setup[key].append(item)
        self.after_edit()
        return True

    # ------------------------------------------------------------------ the mesh and the solve
    def ready(self):
        if self.geom is None:
            return "Import a part first."
        try:
            self.read_inputs()
        except ValueError as ex:
            return str(ex)
        return cm.check_ready(self.setup, self.geom)

    def job_plan(self, g, r, solving=True):
        try:
            cached = self.cache.get(cm.mesh_key(g, r)) if self.cache is not None else None
            n = float(len(cached["nodes"])) if cached else float(cm.estimate_nodes(g, self.setup))
            el = float(len(cached["tets"])) if cached else n * 5.2
            plan = [] if cached else [("mesh", el)]
            if solving:
                plan += [("assemble", el), ("factor", solid_progress.factor_cost(4.0 * n))]
            return plan
        except Exception:                                                          # noqa: BLE001 - only the estimate of a time
            return None

    def mesh_summary(self, q, r):
        ql = q.get("quality") or {}
        return (f"{ql.get('elements', len(q['tets'])):,} tetrahedra, {len(q['nodes']):,} nodes (linear), element size {l_out(r['h_near']):.4g} on the part, "
                f"{l_out(r['h_far']):.4g} {UD()['L']} far away")

    def run_mesh(self):
        why = self.ready()
        if why:
            self.say(why)
            return False
        try:
            r = cm.resolve(self.geom, self.setup)
        except fem.FemError as ex:
            self.say(str(ex))
            return False
        g = self.geom

        def work(progress, cancel):
            return cm.get_mesh(g, r, self.cache, cancel, progress)
        plan = self.job_plan(g, r, solving=False)

        def done(q):
            self.mesh_q = q
            self.mesh_lbl.setText(self.mesh_summary(q, r))
            self.show_counts(q)
            self.show_quality(q.get("quality"))
            self.say("Meshed.")
            self.show_field(mesh_only=True)
        return self.run_job(work, done, "Meshing", plan)

    def run_solve(self):
        why = self.ready()
        if why:
            self.say(why)
            return False
        try:
            r = cm.resolve(self.geom, self.setup)
        except fem.FemError as ex:
            self.say(str(ex))
            return False
        g = self.geom

        def work(progress, cancel):
            return cm.run(g, r, self.cache, cancel, progress)
        plan = self.job_plan(g, r)

        def done(res):
            self.result = res
            self._nodal_cache = {}
            self.mesh_q = res["mesh"]
            self.mesh_lbl.setText(self.mesh_summary(res["mesh"], r))
            self.show_counts(self.mesh_q)
            self.show_quality(res["mesh"].get("quality"))
            self.describe()
            self.show_field()
            self.colour()
            self.enable_buttons()
        return self.run_job(work, done, "Solving", plan)

    # ------------------------------------------------------------------ the report of a result
    def describe(self):
        r = self.result
        if r is None:
            return
        s = r["summary"]
        run = r["run"]
        D = UD()
        fam = self.family()
        force = lambda v: R.num(float(v) / D["F_N"], 4)
        sound = r["status"] == "converged"
        rows = [("Reynolds number (size of the part)", f"{s['Re']:,.1f}", None), ("Speed of the inflow", R.num(run["speed"] / D["V_ms"], 4), D["V"]),
                ("Drag: force on the part along the flow", force(s["drag"]), D["F"]), ("   of which pressure", force(s["drag_pressure"]), D["F"]),
                ("   of which friction", force(s["drag_viscous"]), D["F"]),
                ("Side force (across the flow)", force(np.linalg.norm(s["side"])), D["F"]), ("Drag coefficient (the part seen from the flow: " + R.num(s["area_front_m2"] / D["L_m"] ** 2, 3) +
                                                                                         f" {D['L']}2)", f"{s['Cd']:.3f}", None),
                ("Pressure on the part, highest", R.num(s["p_max"] / pressure_unit()[1], 4), pressure_unit()[0]), ("Pressure, lowest", R.num(s["p_min"] / pressure_unit()[1], 4), pressure_unit()[0]),
                ("Highest speed", R.num(s["speed_max"] / D["V_ms"], 4), D["V"])]
        html = R.heading("Summary") + R.kv(rows)
        html += R.note("Pressure is relative to the outlet. The force is the one the fluid puts on the part (the consistent reaction of the equations at its nodes); the friction is what is left of it after the pressure is taken off, the least certain number here on a coarse mesh.")
        if "T" in r:
            T = lambda v: R.num(fam.from_si("T", v), 5)
            html += R.heading("Temperature") + R.kv([("Highest", T(s["T_max"]), fam.temp), ("Lowest", T(s["T_min"]), fam.temp)])
            if s["flows"]:
                html += R.heading("Heat of each condition", f"({fam.unit('P')}; positive = into the fluid)")
                html += R.grid(["", "Heat", "Area (" + D["L"] + "2)"], [[f["name"], R.num(fam.from_si("P", f["Q"]), 5), R.num(f["area_m2"] / D["L_m"] ** 2, 4)] for f in s["flows"]])
            en = s["energy"]
            kind, word = cm.energy_verdict(en["mismatch"])
            html += R.heading("Heat balance") + R.kv([("Heat carried away by the fluid", R.num(fam.from_si("P", en["gain"]), 5), fam.unit("P")),
                                                      ("Heat from the walls", R.num(fam.from_si("P", en["walls"]), 5), fam.unit("P")),
                                                      ("Difference", R.chip(word, kind) + f" {en['mismatch'] * 100:.1f} % of the larger", None)])
            lo_ref = min([run["T_in"]] + [float(c["T"]) for c in run["temps"]])
            hi_ref = max([run["T_in"]] + [float(c["T"]) for c in run["temps"]])
            span = max(hi_ref - lo_ref, 1e-9)
            over = max(lo_ref - s["T_min"], s["T_max"] - hi_ref)
            if run["temps"] and over > 0.05 * span:
                html += R.note(f"The temperature goes beyond the inflow and wall temperatures by {R.num(over, 3)} K ({over / span * 100:.0f} % of their difference): the mesh "
                               "is too coarse for this flow near the part. Use smaller elements on the part.", R.AMBER)
        mb = s["mass"]
        okm = mb["mismatch"] < 0.02
        html += R.heading("Checks") + R.kv([("Flow in", R.num(mb["in"], 5), "m3/s"), ("Flow out", R.num(mb["out"], 5), "m3/s"),
                                            ("Mass balance", (R.chip("OK", "ok") if okm else R.chip("CHECK", "bad")) + f" {mb['mismatch'] * 100:.3f} %", None),
                                            ("The flow settled", (R.chip("OK", "ok") if sound else R.chip("NO", "bad")) + f" {r['status']} after {r['steps']} steps "
                                                                                                                        f"(last change {r['history'][-1]:.1e})", None)])
        q = r["mesh"]
        ql = q.get("quality") or {}
        html += R.heading("Mesh") + R.kv([("Tetrahedra (linear)", f"{len(q['tets']):,}", None), ("Nodes", f"{len(q['nodes']):,}", None),
                                          ("Element size on the part", R.num(l_out(run["h_near"]), 4), D["L"]), ("Element size far away", R.num(l_out(run["h_far"]), 4), D["L"]),
                                          ("Worst element (radius ratio)", f"{ql.get('ratio_min', 0.0):.3f}", None)])
        html += R.note("The method is first-order: the mesh is not refined by itself. Check a result by meshing finer and comparing (the drag of a blunt body still changes "
                       "by about ten per cent when the elements on it are made half as long).")
        if q.get("unmatched"):
            html += R.note(f"{len(q['unmatched'])} surface(s) of the part could not be matched to a face; they are walls but cannot carry a condition.", R.AMBER)
        sec = r.get("seconds")
        html += R.heading("Solver check") + R.kv([("Solver", r["solver"], None), ("Unknowns", f"{r['unknowns']:,}", None), ("Time", f"{sec:.2f} s" if sec else "?", None)])
        for n_ in cm.result_notes(r):
            html += R.note(n_, R.RED if not sound and n_.startswith("The flow did not settle") else R.AMBER)
        for n_ in cm.notes(self.setup, self.geom):
            html += R.note(n_, R.AMBER)
        self.res_lbl.setText(html)
        self.say("Solved." if sound else "Solved, but the flow did not settle: see the report.")

    # ------------------------------------------------------------------ the pictures
    def field_key(self):
        return self.cb_field.currentData() or "speed"

    def nodal(self, key):
        """The field at every node, SI: speed, p, T, ux, uy, uz."""
        c = self._nodal_cache
        if key not in c:
            r = self.result
            c[key] = {"speed": lambda: cm.speed_of(r), "p": lambda: r["p"], "T": lambda: r["T"], "ux": lambda: r["u"][:, 0], "uy": lambda: r["u"][:, 1],
                      "uz": lambda: r["u"][:, 2]}[key]()
        return c[key]

    def field_values(self, key=None):
        """-> (values at every node in the program's units, lo, hi, the legend dict)."""
        key = key or self.field_key()
        name, q = next((n, q) for kk, n, q in FIELDS if kk == key)
        vals = self.quantity_from_si(q, self.nodal(key))
        lo, hi = float(vals.min()), float(vals.max())
        if not hi > lo:
            hi = lo + 1.0
        leg = {"title": f"{name}  [{self.quantity_unit(q)}]", "labels": [(0.0, f"{hi:.5g}"), (0.5, f"{(hi + lo) / 2:.5g}"), (1.0, f"{lo:.5g}")],
               "subtitle": "at the nodes of the mesh, nothing smoothed"}
        return vals, lo, hi, leg

    def scene_changed(self):
        self.slice_box.setVisible(self.cb_slice.isChecked())
        self.lines_box.setVisible(self.cb_lines.isChecked())
        if self.result is not None:
            self.scene_timer.start(SCENE_DELAY_MS)

    def slice_spec(self):
        r = self.result
        ax = int(self.slice_axis.currentData())
        lo, hi = np.asarray(r["run"]["lo"], float), np.asarray(r["run"]["hi"], float)
        return ax, float(lo[ax] + (hi[ax] - lo[ax]) * self.slice_pos.value() / 100.0)

    def lines_spec(self):
        r = self.result
        run = r["run"]
        lo, hi = np.asarray(run["lo"], float), np.asarray(run["hi"], float)
        bb = np.asarray(self.geom["bbox"], float)
        ax = "xyz".index(run["dir"][1])
        sign = 1 if run["dir"][0] == "+" else -1
        return {"seeds": fv.seed_grid(lo, hi, ax, sign, self.sp_lines.value(), cross_lo=bb[0], cross_hi=bb[1]), "max_length": 4.0 * float(np.linalg.norm(hi - lo))}

    def show_field(self, mesh_only=False):
        if self.result is None:
            if self.mesh_q is not None:
                q = self.mesh_q
                self.view.show_mesh(q["nodes"], q.get("viewcells") or q["tets"])
            return
        r = self.result
        key = self.field_key()
        if key == "T" and "T" not in r:
            self.say("No temperature was solved: tick 'Solve the temperature too' under Fluid and flow, then Solve again.")
            key = "speed"
        vals, lo, hi, leg = self.field_values(key)
        tris, _ids = cm.part_surface(r)
        self.slice_box.setVisible(self.cb_slice.isChecked())
        self.lines_box.setVisible(self.cb_lines.isChecked())
        self.view.show_fluid(r["mesh"]["nodes"], r["mesh"]["tets"], r["u"], vals, lo, hi, tris, key not in PLAIN_PART,
                             self.slice_spec() if self.cb_slice.isChecked() else None, self.lines_spec() if self.cb_lines.isChecked() else None,
                             {"title": leg["title"], "labels": leg["labels"], "subtitle": leg["subtitle"]})

    def colours_changed(self, *_a):
        try:
            if self.result is not None:
                self.show_field()
        except RuntimeError:
            result_style.unsubscribe(self.cmap_combo._external)

    # ------------------------------------------------------------------ probes
    def set_probe_mode(self, on):
        self.view.probe_mode = bool(on)
        self.view.on_probe = self.probe_at if on else None
        self.say("Click the solved part to read the values there." if on else "Probe off: a click picks a face again.")

    def probe_at(self, point):
        if self.result is None or point is None:
            self.probe_lbl.setText("Solve first, then click the part.")
            return None
        return self.probe_point(np.asarray(point, float))

    def probe_node(self):
        if self.result is None:
            self.probe_lbl.setText("Solve first.")
            return None
        try:
            p = [l_in(float(x)) for x in self.e_probe.text().replace(";", ",").split(",")]
            assert len(p) == 3
        except Exception:                                                          # noqa: BLE001
            self.probe_lbl.setText(f"Type the point as x, y, z ({UD()['L']}).")
            return None
        return self.probe_point(np.asarray(p, float))

    def probe_point(self, p):
        nodes = self.result["mesh"]["nodes"]
        i = int(np.argmin(np.linalg.norm(nodes - p, axis=1)))
        self.last_probe = {"i": i, "dist": float(np.linalg.norm(nodes[i] - p))}
        self.show_probe(self.last_probe)
        return i, self.last_probe["dist"], float(self.nodal("speed")[i]), float(self.nodal("p")[i])

    def show_probe(self, pr):
        r = self.result
        if r is None:
            return
        i = pr["i"]
        D = UD()
        fam = self.family()
        x = r["mesh"]["nodes"][i]
        v = lambda a: R.num(float(a) / D["V_ms"], 4)
        rows = [("Speed", v(self.nodal("speed")[i]), D["V"]), ("Velocity X", v(r["u"][i, 0]), D["V"]), ("Velocity Y", v(r["u"][i, 1]), D["V"]),
                ("Velocity Z", v(r["u"][i, 2]), D["V"]), ("Pressure", R.num(float(r["p"][i]) / pressure_unit()[1], 4), pressure_unit()[0])]
        if "T" in r:
            rows.append(("Temperature", R.num(fam.from_si("T", float(r["T"][i])), 5), fam.temp))
        where = f"node {i} at ({R.num(l_out(x[0]))}, {R.num(l_out(x[1]))}, {R.num(l_out(x[2]))}) {D['L']}, {R.num(l_out(pr['dist']), 3)} {D['L']} from the point"
        self.probe_lbl.setText(R.heading("Probe") + R.note(where) + R.kv(rows))

    # ------------------------------------------------------------------ a state (a test) in and out
    def import_state(self, st):
        s = st.get("setup") or cm.default_setup()
        s.setdefault("dims", {})
        s.setdefault("splits", [])
        s.setdefault("bond_tol", 0.0)
        s.setdefault("body_mats", {})
        s.setdefault("body_h", {})
        self.migrate_setup(s)
        s["mesh"] = smesh.complete(s.get("mesh"))
        dims_changed = s["dims"] != self.setup.get("dims")
        self.setup = json.loads(json.dumps(s))
        self.put_physics()
        self.put_mesh_options()
        if dims_changed and self.source is not None:
            self.load_geometry()
        self.fill_part_sizes()
        self.result = st.get("result")
        self._nodal_cache = {}
        self.refresh_lists()
        self.colour()
        if self.result is not None:
            self.describe()
            self.show_field()
        else:
            self.invalidate()

    # ------------------------------------------------------------------ the test example, the self-check, the diagnostics report
    def load_example(self, folder=None):
        import cfd3d_example as ex
        return ex.load_example(self, folder)

    def run_self_check(self):
        import cfd3d_example as ex
        return ex.run_self_check(self)

    def diagnostics_text(self):
        import cfd3d_example as ex
        return ex.diagnostics_text(self)

    def show_diagnostics(self):
        solid_diag.show_report(self, self.diagnostics_text(), self.path if self.project_ok() else None, "3D Fluid Flow diagnostics report")


def make_fluid3d(host, path=None):
    cfd3d_ext.ensure_registered()
    if path:
        return FluidWindow.open_project(host, path)
    return FluidWindow(shell=host)


cfd3d_ext.ensure_registered()
