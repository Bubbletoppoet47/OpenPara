"""
thermal_tab.py - the 2D Thermal tab: steady and transient heat conduction with convection and radiation in a sketch or a slice of a part.

It is the 2D FEA tab with heat in place of stress: the same Geometry (import, regions, split / merge edges), Mesh, conditions on edges and points,
Solve, Results (fields, probes, node probe, animation), diagnostics and project file.  The window around it (project folder, source, slices) is the
Simulation add-on's (sim_tab.SimWindow); this module registers itself there as the kind "thermal" (see make_thermal).

  Conditions   Temperature (fixed)  -  Heat flux (into the body)  -  Heat flow at a point  -  Convection (to a fluid)  -  Radiation (to surroundings)
               an edge with none of them is insulated.  Every region can generate heat and has its own material.
  Plate faces  optional: the two flat faces of the plate lose heat by convection and / or radiation over the whole area.
  Units        the temperature, conductivity ... follow File > Units (metric: degC, W, m; US: degF, Btu, hr, ft).  What is stored and solved is SI.

The solver is thermal_fem.py (no Qt).  Everything the tab keeps is SI and absolute temperature; only the sketch lengths are in the sketch's own unit.
"""
import math
import platform
import re
import sys
import time

import numpy as np
from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QSlider, QSplitter, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget, QListWidget)

import legend_draw
import physics_fea as pf
import physics_geom as pg
import physics_store as pstore
import physics_tab as pt
import result_style
import sim_report as R
import sim_ui
import sketcher_core as sc
import thermal_fem as tfem
import thermal_mat as tmat
import thermal_store as tstore
import thermal_units as tu
import units
from sketch_pick import SketchPicker

KIND = "thermal"
LABEL = "2D Thermal"
EXT = ".gph"
KIND_NAME = pt.KIND_NAME

# name, key, "nodal" (smooth, one value per node) or "elem" (flat, one per drawing triangle), quantity of thermal_units
FIELDS = [("Temperature", "T", "nodal", "T"), ("Heat flux magnitude", "q", "elem", "q"), ("Heat flux X", "qx", "elem", "q"),
          ("Heat flux Y", "qy", "elem", "q")]
CUSTOM = "(custom values)"
SAME = "(the material of the tab)"
COND_TYPES = {"temp": "Temperature", "flux": "Heat flux", "power": "Heat flow", "conv": "Convection", "rad": "Radiation"}
NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def ensure_registered():
    """Makes the Simulation add-on know the kind 'thermal' (project folder .gph, the window, how a saved state changes units).  Safe to call again."""
    import sim_project
    import sim_tab
    if KIND not in sim_project.EXT:
        sim_project.register_kind(KIND, EXT, LABEL)
    if KIND not in sim_tab.KINDS:
        sim_tab.register_kind(KIND, LABEL, ThermalTab)
    if KIND not in pstore.STATE_CONVERTERS:
        tstore.register()


def make_thermal(host, path=None):
    """The factory of the document tab (File > New 2D Thermal, Open Project Folder)."""
    ensure_registered()
    import sim_tab
    return sim_tab._make(KIND, host, path)


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
        return [float(e.text().strip()) for e in edits]
    except ValueError:
        QMessageBox.warning(parent, title, "Please enter plain numbers (for example 2.5 or 1e6).")
        return None


# ----------------------------------------------------------------------------------------------------------------------------------------------
# the drawing
# ----------------------------------------------------------------------------------------------------------------------------------------------
class ThermalCanvas(pt.PhysCanvas):
    """The 2D FEA drawing with the thermal conditions, the temperature / flux pictures and no deformation."""

    def paint_conditions(self, p):
        tab = self.tab
        m = tab.model
        edge_of = {e["src"]: (e, pts) for e, pts in zip(tab.geom["edges"], tab.geom["polys"])}
        if self.field is None:                               # a region that generates heat is hatched (not over a result picture)
            for f in tab.geom["faces"]:
                if f["included"] and abs((tab.region_q or {}).get(f["id"], 0.0)) > 0:
                    p.fillPath(self.face_path(f), QBrush(QColor(224, 70, 40, 90), Qt.BrushStyle.Dense5Pattern))
        for ld in tab.loads:
            kind = ld["kind"]
            if kind == "power":
                p.setPen(QPen(QColor("#c0182b"), 2))
                for tk, i in ld["targets"]:
                    if tk == "pt" and i in m.pts:
                        s = self.w2s(*m.pts[i])
                        p.setBrush(QColor(192, 24, 43, 70))
                        p.drawEllipse(s, 9, 9)
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        p.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                        p.drawText(QPointF(s.x() + 11, s.y() - 8), "Q")
                continue
            col = {"flux": "#c0182b", "conv": "#1d6fb8", "rad": "#d9561f"}.get(kind)
            if col is None:
                continue
            pen = QPen(QColor(col), 2)
            if kind == "rad":
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for tk, i in ld["targets"]:
                if (tk, i) not in edge_of:
                    continue
                e, pts = edge_of[(tk, i)]
                closed = e["kind"] == "ci"
                count = max(2, min(80, int(round(pt.polyline_length(pts, closed) * self.scale / 40.0))))
                for x0, y0, tx, ty in pt.points_along(pts, closed, count):
                    ix, iy = self.inward_normal(x0, y0, -ty, tx)
                    s0 = self.w2s(x0, y0)
                    if kind == "flux":
                        sgn = 1.0 if ld["q"] >= 0 else -1.0                        # a positive flux heats the body: the arrow points into it
                        d = (ix * sgn, iy * sgn)
                        self.arrow(p, QPointF(s0.x() - 34 * d[0], s0.y() + 34 * d[1]), s0)
                    else:                                                          # heat leaves: the arrow points away from the body
                        self.arrow(p, s0, QPointF(s0.x() - 30 * ix, s0.y() + 30 * iy))

    def paint_fasteners(self, p):
        pass

    def paint_legend(self, p):
        tab = self.tab
        name, key, kind, q = next(f for f in FIELDS if f[1] == self.field)
        vals, _kind, lo, hi, _k = tab.field_arrays(self.field, None)
        unit = tab.family().unit(q)
        labels = [(k / 5, f"{hi - (k / 5) * (hi - lo):.4g}") for k in range(6)]
        sub = tab.time_text(tab.frame_of(None)) if tab.frame_count() else None
        legend_draw.draw_legend(p, self.width(), self.height(), f"{name}  [{unit}]", labels, pt.colours, subtitle=sub)

    def render_picture(self, want_field, ramp=None):
        """The picture of the result (the frame shown, or, for an animation frame, the one at `ramp` 0..1 of the run) or of the mesh alone."""
        import meshdraw as md
        tab = self.tab
        mesh, r = tab.mesh, tab.result
        if want_field and r is not None and r.get("mesh") is not None:
            mesh = r["mesh"]
        W, H = max(self.width(), 10), max(self.height(), 10)
        nodes, tris = mesh["nodes"], mesh["tris"]
        scr_x = self.org.x() + nodes[:, 0] * self.scale
        scr_y = self.org.y() - nodes[:, 1] * self.scale
        edges = md.unique_edges(tab.mesh["tris"]) if self.show_mesh else None
        if want_field:
            vals, kind, lo, hi, _k = tab.field_arrays(self.field, ramp)
            if kind == "elem":
                img = md.render(W, H, scr_x, scr_y, tris, tri_vals=vals, lo=lo, hi=hi, edges=edges, edge_alpha=0.35)
            else:
                img = md.render(W, H, scr_x, scr_y, tris, nodal=vals, lo=lo, hi=hi, edges=edges, edge_alpha=0.35)
        else:
            img = md.render(W, H, scr_x, scr_y, np.zeros((0, 3), dtype=int), tri_vals=np.zeros(0), edges=edges, edge_alpha=0.35)
        return QPixmap.fromImage(img)


# ----------------------------------------------------------------------------------------------------------------------------------------------
# the tab
# ----------------------------------------------------------------------------------------------------------------------------------------------
class ThermalTab(pt.PhysicsTab):
    """Built on PhysicsTab for what is the same (import, regions, splitting and merging edges, probes, the node probe, the animation player); its own
    __init__ builds the thermal panel, and the methods below replace what is about stress."""
    ANIM_LABEL = LABEL
    ANIM_FILE = "Thermal_animation"
    kind = KIND

    INPUTS = ("e_k", "e_rho", "e_cp", "e_t", "e_h", "order_combo", "analysis_combo", "e_T0", "e_tend", "time_combo", "e_steps", "method_combo", "e_nframes",
              "cb_plate", "e_hplate", "e_Tamb", "e_eps_plate", "e_Tsur", "cb_mesh", "cb_anim", "e_frames", "e_dur", "loop_combo")

    def __init__(self, win):
        pt.QWidget.__init__(self)                            # not PhysicsTab.__init__: the panel is built here
        self.win = win
        self.model = None
        self.geom = None
        self.mesh = None
        self.result = None
        self.supports = []        # temperature conditions {"kind": "temp", "T" (K), "targets", "name"?}
        self.loads = []           # the others: flux {"q" W/m2}, power {"P" W}, conv {"h", "Tinf" K}, rad {"eps", "Ts" K}
        self.region_mats, self.region_names, self.region_q = {}, {}, {}
        self.profile = None
        self.probes = []
        self.probe_fos = self.probe_trig = None
        self.deps = pt.dependency_status()
        self.cur_unit = None
        self.frame_idx = 0
        self.view_token = 0
        self._flux_cache = {}
        self.reg_sel = None
        self.missing_mats = []
        self.last_vals = {}
        self.coords = QLabel("")
        self.canvas = ThermalCanvas(self)

        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        lay0 = lay
        self.sections = []

        def sec(n, title, open_=True, help_text=None, summary=None):
            s_ = sim_ui.Section("thermal2d", n, title, open_, help_text, summary)
            self.sections.append(s_)
            return s_.body

        missing = [n for n, (v, _) in self.deps.items() if v is None]
        if missing:
            warn = QLabel("<b>Missing:</b> " + ", ".join(missing) + "<br>Install with:<br><code>pip install " + " ".join(missing) +
                          "</code><br>then restart the program.")
            warn.setWordWrap(True)
            warn.setStyleSheet("background:#fff3cd; padding:6px; border:1px solid #e0c36a;")
            lay.addWidget(warn)

        # ---- 1 Geometry
        lay = sec(1, "Geometry", True, summary=lambda: self.info.text().split("\n")[0][:90],
                  help_text="Import a sketch or a slice of a part. Every closed outline is a region; tick the regions that are material. Select a region to "
                            "give it its own material and a heat generation. Split edge cuts an edge in two (so a condition can cover only part of it); "
                            "Merge edges joins two such edges again. The cut is made on this tab's copy of the sketch only.")
        self.picker = SketchPicker(self.win, self.import_picked)
        lay.addWidget(self.picker)
        b = QPushButton("Clear (start over)")
        b.setToolTip("Removes the imported copy of the sketch and everything set up on this tab so you can import the sketch again from scratch.")
        b.clicked.connect(self.clear_tab)
        lay.addWidget(b)
        self.info = QLabel("Nothing imported yet.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addWidget(QLabel("<b>Regions</b> (tick = material)"))
        self.regions = QListWidget()
        self.regions.setMaximumHeight(110)
        self.regions.itemChanged.connect(self.region_toggled)
        self.regions.currentRowChanged.connect(self.region_picked)
        lay.addWidget(self.regions)
        self.reg_box = QWidget()
        rf = QFormLayout(self.reg_box)
        rf.setContentsMargins(0, 0, 0, 0)
        self.reg_lbl = QLabel("Selected region: none")
        rf.addRow(self.reg_lbl)
        self.reg_mat_combo = QComboBox()
        self.reg_mat_combo.setToolTip("The material of this region. 'The material of the tab' uses the one chosen in Material and analysis.")
        self.reg_mat_combo.activated.connect(self.region_material_picked)
        rf.addRow("Material", self.reg_mat_combo)
        self.lbl_qv = QLabel("Heat generation")
        self.e_qv = QLineEdit("0")
        self.e_qv.setToolTip("Heat generated inside the region per unit of volume (an electric heater, a chip, a reaction). 0 = none; negative = a heat sink.")
        self.e_qv.editingFinished.connect(self.region_q_edited)
        rf.addRow(self.lbl_qv, self.e_qv)
        self.reg_box.setEnabled(False)
        lay.addWidget(self.reg_box)
        lay.addWidget(QLabel("<b>Edges</b>"))
        row = QHBoxLayout()
        self.b_split = QPushButton("Split edge")
        self.b_split.setCheckable(True)
        self.b_split.setToolTip("Cuts an edge in two at a point you click, so a condition can cover only part of the edge. A circle is cut at two points.")
        self.b_split.clicked.connect(lambda on: self.set_tool("split" if on else "select"))
        self.b_merge = QPushButton("Merge edges")
        self.b_merge.setToolTip("Select the point where two split edges meet and press this to join them again.")
        self.b_merge.clicked.connect(self.merge_selected)
        row.addWidget(self.b_split)
        row.addWidget(self.b_merge)
        lay.addLayout(row)

        # ---- 2 Material and analysis
        lay = sec(2, "Material and analysis", False,
                  summary=lambda: f"{self.mat_combo.currentText()}, {'steady' if self.analysis_combo.currentIndex() == 0 else 'transient'}",
                  help_text="One material for the whole plate (a region can have its own, above). The values are typical room-temperature numbers and are the "
                            "same at every temperature: check them against your own source. The thickness is the depth of the plate: heat flows in the "
                            "results are in watts through that depth. Steady: the temperatures after everything has settled. Transient: the temperatures "
                            "as time passes, from one uniform start temperature. Crank-Nicolson is the more accurate method; backward Euler is the more "
                            "forgiving one (it never oscillates).")
        self.mat_combo = QComboBox()
        row = QHBoxLayout()
        row.addWidget(self.mat_combo, 1)
        b = QPushButton("Add material...")
        b.setToolTip("Adds the numbers now in the boxes below to your thermal material library (a file in your user folder).")
        b.clicked.connect(self.add_material)
        row.addWidget(b)
        self.b_del_mat = QPushButton("Delete")
        self.b_del_mat.setToolTip("Deletes a material you added. The built-in ones stay.")
        self.b_del_mat.clicked.connect(self.delete_material)
        row.addWidget(self.b_del_mat)
        lay.addLayout(row)
        form = QFormLayout()
        self.e_k, self.e_rho, self.e_cp, self.e_t = QLineEdit("167"), QLineEdit("2700"), QLineEdit("896"), QLineEdit("1")
        self.lbl_k, self.lbl_rho, self.lbl_cp, self.lbl_t = QLabel("Conductivity k"), QLabel("Density"), QLabel("Specific heat"), QLabel("Thickness (depth)")
        self.e_rho.setToolTip("Only a transient run needs the density and the specific heat (how much heat the material stores).")
        self.e_cp.setToolTip(self.e_rho.toolTip())
        form.addRow(self.lbl_k, self.e_k)
        form.addRow(self.lbl_rho, self.e_rho)
        form.addRow(self.lbl_cp, self.e_cp)
        form.addRow(self.lbl_t, self.e_t)
        self.analysis_combo = QComboBox()
        self.analysis_combo.addItems(["Steady state", "Transient (changes with time)"])
        form.addRow("Analysis", self.analysis_combo)
        lay.addLayout(form)
        self.tr_box = QWidget()
        tf = QFormLayout(self.tr_box)
        tf.setContentsMargins(14, 0, 0, 0)
        self.e_T0, self.e_tend, self.e_steps, self.e_nframes = QLineEdit("20"), QLineEdit("60"), QLineEdit("120"), QLineEdit("40")
        self.lbl_T0 = QLabel("Start temperature")
        self.time_combo = QComboBox()
        self.time_combo.addItems(list(tu.TIME))
        self.time_combo.setCurrentText("s")
        trow = QHBoxLayout()
        trow.setContentsMargins(0, 0, 0, 0)
        trow.addWidget(self.e_tend, 1)
        trow.addWidget(self.time_combo)
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Crank-Nicolson (more accurate)", "Backward Euler (very stable)"])
        tf.addRow(self.lbl_T0, self.e_T0)
        tf.addRow("End time", trow)
        tf.addRow("Time steps", self.e_steps)
        tf.addRow("Method", self.method_combo)
        tf.addRow("Pictures kept", self.e_nframes)
        self.tr_box.setVisible(False)
        lay.addWidget(self.tr_box)
        self.cb_plate = QCheckBox("Heat loss from the two flat faces")
        self.cb_plate.setToolTip("For a thin plate in air: both flat faces lose heat over their whole area by convection and / or radiation. Without it the "
                                 "faces are insulated (a long, thick body, or heat that stays in the plane).")
        lay.addWidget(self.cb_plate)
        self.plate_box = QWidget()
        pf_ = QFormLayout(self.plate_box)
        pf_.setContentsMargins(14, 0, 0, 0)
        self.e_hplate, self.e_Tamb, self.e_eps_plate, self.e_Tsur = QLineEdit("10"), QLineEdit("20"), QLineEdit("0"), QLineEdit("20")
        self.lbl_hplate, self.lbl_Tamb, self.lbl_Tsur = QLabel("Convection coefficient"), QLabel("Fluid temperature"), QLabel("Surroundings temperature")
        self.e_eps_plate.setToolTip("Emissivity of the faces, 0 to 1 (0 = no radiation).")
        pf_.addRow(self.lbl_hplate, self.e_hplate)
        pf_.addRow(self.lbl_Tamb, self.e_Tamb)
        pf_.addRow("Emissivity", self.e_eps_plate)
        pf_.addRow(self.lbl_Tsur, self.e_Tsur)
        self.plate_box.setVisible(False)
        lay.addWidget(self.plate_box)
        self.units_note = self.note("")
        lay.addWidget(self.units_note)
        self.mat_note = self.note("")
        lay.addWidget(self.mat_note)
        self.library = []
        self.order_combo = QComboBox()
        self.order_combo.addItems(["Quadratic (6-node triangles)", "Linear (3-node triangles)"])
        self.order_combo.setToolTip("Quadratic elements have a node in the middle of every edge and follow a curved temperature far better than linear ones.")
        self.fill_materials(select=tmat.DEFAULT)
        self.mat_combo.currentIndexChanged.connect(self.material_picked)
        for e in (self.e_k, self.e_rho, self.e_cp):
            e.textEdited.connect(self.set_custom)
        self.analysis_combo.currentIndexChanged.connect(self.analysis_changed)
        self.cb_plate.toggled.connect(self.plate_box.setVisible)

        # ---- 5 Mesh
        self.b_mesh = QPushButton("Mesh")
        self.b_mesh.setMinimumHeight(30)
        self.b_mesh.clicked.connect(self.run_mesh)
        self.b_solve = sim_ui.solve_button()
        self.study_box = sim_ui.study_slot()
        self.b_solve.clicked.connect(self.run_solve)
        lay = sec(5, "Mesh", True, summary=lambda: f"size {self.e_h.text()}, {'quadratic' if self.order_combo.currentIndex() == 0 else 'linear'}",
                  help_text="Choose the element size and the element type, then press Mesh. Make the mesh finer where the temperature changes quickly "
                            "(near a heat source, a sharp corner, a thin wall) and solve again: when the result stops changing, the mesh is fine enough.")
        mf = QFormLayout()
        self.e_h = QLineEdit("")
        self.lbl_h = QLabel("Element size")
        mf.addRow(self.lbl_h, self.e_h)
        mf.addRow("Elements", self.order_combo)
        lay.addLayout(mf)
        lay.addWidget(self.b_mesh)

        # ---- 3 Temperatures, 4 Heat conditions
        lay = sec(3, "Conditions", True, summary=lambda: self.count_text(self.supports + self.loads, "condition"),
                  help_text="Select edges or points on the drawing first, then press a button. Temperature holds the selected edges or points at a fixed "
                            "temperature. Heat flux pushes heat in through an edge (positive heats the body). Heat flow puts a number of watts into a "
                            "point. Convection: the edge loses heat to a fluid at its temperature with the coefficient you give. Radiation: the edge "
                            "radiates to surroundings at the temperature you give (not to other parts of the model). An edge with no condition is "
                            "insulated. A steady problem needs at least one temperature, convection or radiation to settle on. Double-click a Name "
                            "to rename it; the Value column can be edited.")
        lay.addWidget(self.note("Select the edge(s) or point(s) first (click them in the view), then press a button."))
        for text, icn, fn, tip in (("Temperature...", "fixed", self.add_temperature, "Holds the selected edges or points at a fixed temperature."),
                                   ("Heat flux...", "pressure", self.add_flux, "Heat pushed through the selected edges, per unit area (positive = into the body)."),
                                   ("Heat flow at a point...", "force", self.add_power, "Watts put into the selected points (through the whole depth)."),
                                   ("Convection...", "wind", self.add_conv, "The selected edges lose heat to a fluid: coefficient and fluid temperature."),
                                   ("Radiation...", "snow", self.add_rad, "The selected edges radiate to surroundings: emissivity and temperature.")):
            b = sim_ui.icon_button(text, icn, tip)
            b.clicked.connect(fn)
            lay.addWidget(b)
        self.cond_list = QListWidget()
        self.cond_list.hide()
        lay.addWidget(QLabel("Conditions on this model"))
        self.cond_table = QTableWidget(0, 4)
        self.cond_table.setHorizontalHeaderLabels(["Name", "Type", "Applied to", "Value"])
        self.cond_table.verticalHeader().hide()
        self.cond_table.setMinimumHeight(110)
        self.cond_table.setMaximumHeight(190)
        self.cond_table.horizontalHeader().setStretchLastSection(True)
        self.cond_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cond_table.itemChanged.connect(self.cond_item_changed)
        lay.addWidget(self.cond_table)
        row = QHBoxLayout()
        b = QPushButton("Edit selected...")
        b.setToolTip("Edit the Value of the selected row; a row without a value lets you rename it.")
        b.clicked.connect(self.edit_condition)
        row.addWidget(b)
        b = QPushButton("Remove selected")
        b.clicked.connect(self.remove_condition)
        row.addWidget(b)
        lay.addLayout(row)

        # ---- 6 Results
        lay = sec(6, "Results", True, summary=lambda: self.field.currentText(),
                  help_text="Pick what to colour by. A transient run keeps pictures at equal times: move the slider, or Animate. Probe: an area of the original "
                            "geometry whose average temperature and heat flux are reported. Node probe: click near a node to read every result there. "
                            "Heat flows are in watts through the depth; a positive flow through a temperature condition means that edge feeds heat into the body.")
        self.field = QComboBox()
        self.field.addItem("(none - show the mesh)", None)
        for name, key, _k, _q in FIELDS:
            self.field.addItem(name, key)
        self.field.currentIndexChanged.connect(self.view_changed)
        lay.addWidget(self.field)
        row = QHBoxLayout()
        row.addWidget(QLabel("Colours"))
        self.cmap_combo = result_style.make_combo(self, self.restyle)
        row.addWidget(self.cmap_combo, 1)
        lay.addLayout(row)
        self.cb_mesh = QCheckBox("Show mesh lines")
        self.cb_mesh.setChecked(True)
        self.cb_mesh.toggled.connect(self.view_changed)
        lay.addWidget(self.cb_mesh)
        self.time_box = QWidget()
        tl = QVBoxLayout(self.time_box)
        tl.setContentsMargins(0, 0, 0, 0)
        self.time_lbl = QLabel("")
        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.valueChanged.connect(self.frame_moved)
        tl.addWidget(self.time_lbl)
        tl.addWidget(self.time_slider)
        self.time_box.setVisible(False)
        lay.addWidget(self.time_box)
        self.cb_anim = QCheckBox("Animate")
        self.cb_anim.setToolTip("Plays the pictures of the transient run in order. (A steady result has nothing that changes.)")
        self.cb_anim.toggled.connect(self.anim_toggled)
        lay.addWidget(self.cb_anim)
        self.anim_box = QWidget()
        al = QFormLayout(self.anim_box)
        al.setContentsMargins(14, 0, 0, 0)
        self.e_frames, self.e_dur = QLineEdit("30"), QLineEdit("3")
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
        self.b_export = QPushButton("Export animation...")
        self.b_export.clicked.connect(lambda: self.export_animation())
        al.addRow(self.b_export)
        al.addRow(self.note("The colour scale is fixed to the whole run. All frames are drawn first."))
        self.anim_box.setVisible(False)
        lay.addWidget(self.anim_box)
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.anim_step)
        self.anim_dir = 1
        pl = QLabel("<b>Probe</b>")
        pl.setToolTip("A probe is an area of the original geometry whose average temperature and heat flux are reported.")
        lay.addWidget(pl)
        self.b_node = QPushButton("Node probe (click a node)")
        self.b_node.setCheckable(True)
        self.b_node.setToolTip("Click near a node on the result to read every result at that node.")
        self.b_node.clicked.connect(lambda on: self.set_tool("node" if on else "select"))
        lay.addWidget(self.b_node)
        self.node_lbl = QLabel("")
        self.node_lbl.setWordWrap(True)
        self.node_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.node_lbl)
        row = QHBoxLayout()
        self.b_prect = QPushButton("Rectangle (drag)")
        self.b_pcirc = QPushButton("Circle (drag)")
        for b_, mode in ((self.b_prect, "rect"), (self.b_pcirc, "circle")):
            b_.setCheckable(True)
            b_.clicked.connect(lambda on, m=mode: self.set_tool(m if on else "select"))
            row.addWidget(b_)
        lay.addLayout(row)
        self.probe_table = QTableWidget(0, 3)
        self.probe_table.setHorizontalHeaderLabels(["Name", "Shape", "Geometry"])
        self.probe_table.verticalHeader().hide()
        self.probe_table.setMinimumHeight(90)
        self.probe_table.setMaximumHeight(160)
        self.probe_table.horizontalHeader().setStretchLastSection(True)
        self.probe_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.probe_table.itemChanged.connect(self.probe_item_changed)
        lay.addWidget(self.probe_table)
        b = QPushButton("Remove selected probe")
        b.clicked.connect(self.remove_probe)
        lay.addWidget(b)
        self.res_lbl = QLabel("")
        self.res_lbl.setWordWrap(True)
        lay.addWidget(self.res_lbl)
        row = QHBoxLayout()
        b = QPushButton("Diagnostics report...")
        b.setToolTip("A text report of the geometry, mesh, setup and solution that you can copy and paste to me.")
        b.clicked.connect(self.show_diag)
        row.addWidget(b)
        b = QPushButton("Zoom to fit")
        b.clicked.connect(self.canvas.fit)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addStretch(1)

        for s_ in sorted(self.sections, key=lambda x: x.number):
            if s_.number == 6:
                lay0.addWidget(self.b_solve)
                lay0.addWidget(self.study_box)
            lay0.addWidget(s_)
        lay0.addStretch(1)
        panel = sim_ui.make_panel(left, [])
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(panel)
        split.addWidget(self.canvas)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        sim_ui.fit_side_panel(split, panel, left)
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
        self.apply_units(self.unit_name())
        self.material_picked()
        self.enable_buttons()

    # ------------------------------------------------------------------------------------------------------------------------------ units
    def family(self):
        return tu.family_of(self.unit_name())

    def lscale(self):
        """Metres per sketch unit."""
        return float(units.get(self.unit_name())["L_m"])

    def apply_units(self, name):
        """Makes `name` the unit system of this tab: the labels and the material boxes follow it."""
        old_fam = tu.family_of(self.cur_unit) if self.cur_unit else None
        self.cur_unit = name
        fam = tu.family_of(name)
        u = units.get(name)
        if old_fam is not None and old_fam.us != fam.us:     # the numbers typed in the boxes are kept physically
            self.convert_family_boxes(old_fam, fam)
        self.lbl_k.setText(f"Conductivity k ({fam.unit('k')})")
        self.lbl_rho.setText(f"Density ({fam.unit('rho')})")
        self.lbl_cp.setText(f"Specific heat ({fam.unit('cp')})")
        self.lbl_t.setText(f"Thickness (depth) ({u['L']})")
        self.lbl_h.setText(f"Element size ({u['L']})")
        self.lbl_T0.setText(f"Start temperature ({fam.temp})")
        self.lbl_hplate.setText(f"Convection coefficient ({fam.unit('h')})")
        self.lbl_Tamb.setText(f"Fluid temperature ({fam.temp})")
        self.lbl_Tsur.setText(f"Surroundings temperature ({fam.temp})")
        self.lbl_qv.setText(f"Heat generation ({fam.unit('qv')})")
        self.units_note.setText(f"Units: {name}  (change in File > Units); temperatures in {fam.temp}")
        if hasattr(self, "mat_combo"):
            self.update_mat_note()

    def convert_family_boxes(self, fo, fn):
        for n, q in tstore.FAMILY_BOXES.items():
            w = getattr(self, n, None)
            if w is not None and w.text().strip():
                try:
                    w.setText(f"{fn.from_si(q, fo.to_si(q, float(w.text()))):.10g}")
                except ValueError:
                    pass

    def convert_input_units(self, new):
        """File > Units changed while nothing is imported: only the boxes hold numbers."""
        old = self.cur_unit or self.unit_name()
        lf = units.length_factor(old, new)
        for n in tstore.LENGTH_BOXES:
            w = getattr(self, n)
            if w.text().strip():
                try:
                    w.setText(f"{float(w.text()) * lf:.10g}")
                except ValueError:
                    pass
        self.apply_units(new)

    def unit_name(self):
        if self.model is not None:
            return self.model.unit_system
        return getattr(getattr(self.win, "m", None), "unit_system", units.DEFAULT)

    # ------------------------------------------------------------------------------------------------------------------------------ small helpers
    def enable_buttons(self):
        have = {n for n, (v, _) in self.deps.items() if v is not None}
        self.b_mesh.setEnabled(self.geom is not None and "gmsh" in have and "numpy" in have)
        self.b_solve.setEnabled(self.mesh is not None and "scipy" in have)

    def signature_extra(self):
        return (sorted((self.region_q or {}).items()), sorted((f, m.get("name")) for f, m in (self.region_mats or {}).items()))

    def num(self, edit, name, positive=False, nonneg=False):
        try:
            v = float(edit.text().strip())
        except ValueError:
            raise pf.ModelError(f"{name} must be a number.")
        if positive and not v > 0:
            raise pf.ModelError(f"{name} must be greater than zero.")
        if nonneg and v < 0:
            raise pf.ModelError(f"{name} cannot be negative.")
        return v

    # ------------------------------------------------------------------------------------------------------------------------------ import
    def set_model(self, m, source):
        m = self.adopt_units(m)
        self.model = m
        self.source = source
        self.apply_units(m.unit_system)
        self.geom = pg.analyze(m)
        self.geom["used_edges_src"] = {self.geom["edges"][k]["src"] for k in self.geom["used_edges"]}
        self.mesh = None
        self.result = None
        self.supports, self.loads = [], []
        self.region_mats, self.region_names, self.region_q = {}, {}, {}
        self.missing_mats = []
        self.probes, self.probe_fos, self.probe_trig = [], None, None
        self.canvas.node_sel = None
        self.canvas.sel = []
        self.canvas.field = None
        self.field.setCurrentIndex(0)
        self.fill_regions()
        xs = [p[0] for pts in self.geom["polys"] for p in pts]
        ys = [p[1] for pts in self.geom["polys"] for p in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) if xs else 1.0
        self.e_h.setText(f"{span / 30:.4g}")
        g = self.geom
        msg = f"Imported {source}: {len(g['edges'])} edges, {len(g['faces'])} closed region(s)."
        if g["pruned"]:
            msg += f" {len(g['pruned'])} edge(s) not part of a closed loop were ignored."
            msg += pg.gap_note(g.get("gaps"))
        if g["crossings"]:
            msg += f" WARNING: {len(g['crossings'])} pair(s) of edges cross without a shared point."
        self.info.setText(msg)
        self.status(msg)
        self.refresh_lists()
        self.update_time_controls()
        self.canvas.fit()
        self.enable_buttons()

    def clear_state(self):
        """Back to the freshly started tab (used when another project is opened)."""
        self.sketch_id = None
        self.model = self.geom = self.mesh = self.result = None
        self.supports, self.loads = [], []
        self.region_mats, self.region_names, self.region_q = {}, {}, {}
        self.missing_mats = []
        self.probes, self.probe_fos, self.probe_trig = [], None, None
        self.canvas.node_sel = None
        self.canvas.sel = []
        self.canvas.field = None
        self.field.blockSignals(True)
        self.field.setCurrentIndex(0)
        self.field.blockSignals(False)
        self.regions.clear()
        self.reg_sel = None
        self.update_region_box()
        self.refresh_lists()
        self.info.setText("Nothing imported yet.")
        self.res_lbl.setText("")
        self.node_lbl.setText("")
        self.update_time_controls()
        self.canvas.invalidate()
        self.enable_buttons()

    # --- what the Simulation window tells a thermal tab about a slice of a part / assembly
    def sim_apply_regions(self, rp, names, mats):
        """Regions of a slice: named by their part, each with the thermal material of that part's material (looked up by its name)."""
        self.region_names = dict(names)
        self.region_mats, missing = {}, []
        lib = tmat.library()
        for fid, m in mats.items():
            tm = tmat.for_part_material(m, lib)
            if tm is None:
                missing.append(f"{names.get(fid, 'a part')} ({(m or {}).get('name') or 'no material'})")
            else:
                self.region_mats[fid] = {"name": tm["name"], "k": tm["k"], "rho": tm["rho"], "cp": tm["cp"]}
        self.missing_mats = sorted(set(missing))

    def sim_part_materials(self, mats, part_mat):
        notes = []
        if mats:
            if self.region_mats:
                notes.append("Thermal materials from the parts: " + ", ".join(sorted({m["name"] for m in self.region_mats.values()})) + ".")
            if self.missing_mats:
                notes.append("No thermal values for " + ", ".join(self.missing_mats) + ": those regions use the material of the tab (Material and "
                             "analysis); give them one of their own in Geometry > Regions.")
            return notes
        if part_mat:
            tm = tmat.for_part_material(part_mat)
            if tm is None:
                notes.append(f"The part's material ({part_mat.get('name') or 'none'}) has no thermal values here: choose a material in Material and analysis.")
            else:
                self.set_default_material(tm)
                notes.append(f"Thermal material from the part: {tm['name']}.")
        return notes

    def set_default_material(self, tm):
        """Puts a thermal material (SI) into the boxes of the tab as custom values (its name is kept in the note)."""
        fam = self.family()
        self.mat_combo.blockSignals(True)
        i = self.mat_combo.findData(tm["name"])
        self.mat_combo.setCurrentIndex(i if i >= 0 else 0)
        self.mat_combo.blockSignals(False)
        for w, q in ((self.e_k, "k"), (self.e_rho, "rho"), (self.e_cp, "cp")):
            w.setText(f"{fam.from_si(q, tm[q]):.6g}")
        self.update_mat_note()

    # ------------------------------------------------------------------------------------------------------------------------------ regions
    def fill_regions(self):
        self.regions.blockSignals(True)
        self.regions.clear()
        for f in self.geom["faces"]:
            self.regions.addItem(self.region_item(f))
        self.regions.blockSignals(False)
        self.update_region_box()

    def region_item(self, f):
        nm = (self.region_names or {}).get(f["id"])
        extra = ""
        m = (self.region_mats or {}).get(f["id"])
        if m:
            extra += f"  {m['name']}"
        if abs((self.region_q or {}).get(f["id"], 0.0)) > 0:
            extra += "  [heat generation]"
        it = QListWidgetItem(f"Region {f['id'] + 1}" + (f"  [{nm}]" if nm else "") + f"   area {f['net_area']:.5g}{extra}")
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if f["included"] else Qt.CheckState.Unchecked)
        return it

    def region_picked(self, row):
        super().region_picked(row)
        self.update_region_box()

    def selected_face(self):
        r = self.regions.currentRow()
        if self.geom is None or not (0 <= r < len(self.geom["faces"])):
            return None
        return self.geom["faces"][r]

    def update_region_box(self):
        f = self.selected_face() if hasattr(self, "regions") and self.geom is not None else None
        self.reg_box.setEnabled(f is not None)
        self.reg_sel = f["id"] if f is not None else None
        if f is None:
            self.reg_lbl.setText("Select a region to give it a material and a heat generation.")
            return
        nm = (self.region_names or {}).get(f["id"])
        self.reg_lbl.setText(f"Selected: Region {f['id'] + 1}" + (f" [{nm}]" if nm else ""))
        self.reg_mat_combo.blockSignals(True)
        self.reg_mat_combo.clear()
        self.reg_mat_combo.addItem(SAME, None)
        names = [m["name"] for m in tmat.library()]
        have = (self.region_mats or {}).get(f["id"])
        for n in names:
            self.reg_mat_combo.addItem(n, n)
        if have and have["name"] not in names:                # a part's own name (a slice): shown as it is
            self.reg_mat_combo.addItem(have["name"], have["name"])
        i = self.reg_mat_combo.findData(have["name"]) if have else 0
        self.reg_mat_combo.setCurrentIndex(max(i, 0))
        self.reg_mat_combo.blockSignals(False)
        self.e_qv.setText(f"{self.family().from_si('qv', (self.region_q or {}).get(f['id'], 0.0)):.8g}")

    def refresh_region_row(self):
        r = self.regions.currentRow()
        if self.geom is not None and 0 <= r < len(self.geom["faces"]):
            it = self.region_item(self.geom["faces"][r])
            old = self.regions.item(r)
            self.regions.blockSignals(True)
            old.setText(it.text())
            self.regions.blockSignals(False)

    def region_material_picked(self, index):
        f = self.selected_face()
        if f is None:
            return
        name = self.reg_mat_combo.itemData(index)
        if name is None:
            self.region_mats.pop(f["id"], None)
        else:
            cur = (self.region_mats or {}).get(f["id"])
            tm = tmat.find(name) or tmat.for_part_material({"name": name})
            if tm is None and cur is not None and cur["name"] == name:
                tm = cur
            if tm is None:
                return
            self.region_mats[f["id"]] = {"name": name, "k": tm["k"], "rho": tm["rho"], "cp": tm["cp"]}
        self.refresh_region_row()
        self.after_conditions()

    def region_q_edited(self):
        f = self.selected_face()
        if f is None:
            return
        try:
            v = self.family().to_si("qv", float(self.e_qv.text().strip() or "0"))
        except ValueError:
            self.status("The heat generation must be a number (0 = none).")
            self.update_region_box()
            return
        if abs(v - (self.region_q or {}).get(f["id"], 0.0)) <= 1e-12 * max(1.0, abs(v)):
            return
        if v == 0.0:
            self.region_q.pop(f["id"], None)
        else:
            self.region_q[f["id"]] = v
        self.refresh_region_row()
        self.after_conditions()

    def snapshot_faces(self):
        out = super().snapshot_faces()
        for o in out:
            o["q"] = (self.region_q or {}).get(o["id"])
        return out

    def geometry_changed(self, old_faces, msg):
        """After a split or a merge the regions are found again by their area and centre: the heat generation goes with them (the base class
        carries the on / off state, the names and the materials)."""
        super().geometry_changed(old_faces, msg)
        q = {}
        for f in self.geom["faces"]:
            best = None
            for o in old_faces:
                d = math.hypot(o["c"][0] - f["centroid"][0], o["c"][1] - f["centroid"][1])
                if abs(o["a"] - f["net_area"]) <= 1e-6 * max(abs(o["a"]), 1e-300) and (best is None or d < best[0]):
                    best = (d, o)
            if best is not None and best[1].get("q"):
                q[f["id"]] = best[1]["q"]
        self.region_q = q
        self._flux_cache = {}
        self.res_lbl.setText("")
        self.update_time_controls()
        self.fill_regions()
        self.refresh_region_row()

    def region_toggled(self, item):
        super().region_toggled(item)
        self._flux_cache = {}
        self.res_lbl.setText("")
        self.update_time_controls()
        self.update_region_box()

    # ------------------------------------------------------------------------------------------------------------------------------ materials
    def fill_materials(self, select=None):
        self.library = tmat.library()
        builtin = tmat.builtin_names()
        self.mat_combo.blockSignals(True)
        self.mat_combo.clear()
        self.mat_combo.addItem(CUSTOM, None)
        for m in self.library:
            self.mat_combo.addItem(m["name"] + ("" if m["name"] in builtin else "  (yours)"), m["name"])
        i = self.mat_combo.findData(select) if select else 0
        self.mat_combo.setCurrentIndex(max(i, 0))
        self.mat_combo.blockSignals(False)
        if hasattr(self, "b_del_mat"):
            self.b_del_mat.setEnabled(any(m["name"] not in builtin for m in self.library))

    def material_picked(self, *_):
        name = self.mat_combo.currentData()
        tm = tmat.find(name, self.library) if name else None
        if tm is not None:
            fam = self.family()
            for w, q in ((self.e_k, "k"), (self.e_rho, "rho"), (self.e_cp, "cp")):
                w.setText(f"{fam.from_si(q, tm[q]):.6g}")
        self.update_mat_note()
        self.after_inputs()

    def set_custom(self, *_):
        if self.mat_combo.currentData() is not None:
            self.mat_combo.blockSignals(True)
            self.mat_combo.setCurrentIndex(0)
            self.mat_combo.blockSignals(False)
        self.update_mat_note()

    def update_mat_note(self):
        name = self.mat_combo.currentData()
        self.mat_note.setText("" if name is None else "Typical room-temperature values, taken as constant. Check them against your own source.")
        self.refresh_sections()

    def default_material(self):
        fam = self.family()
        k = fam.to_si("k", self.num(self.e_k, "The conductivity", positive=True))
        rho = fam.to_si("rho", self.num(self.e_rho, "The density", positive=True))
        cp = fam.to_si("cp", self.num(self.e_cp, "The specific heat", positive=True))
        return {"name": self.mat_combo.currentData() or CUSTOM, "k": k, "rho": rho, "cp": cp}

    def add_material(self):
        try:
            m = self.default_material()
        except pf.ModelError as ex:
            QMessageBox.warning(self, "Add material", str(ex))
            return
        name, ok = QInputDialog.getText(self, "Add material", "Name of the new material (its values are the ones now in the boxes, SI is stored):")
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in tmat.builtin_names() or any(x["name"] == name for x in tmat.user_materials()):
            QMessageBox.information(self, "Add material", "A material with that name exists already. Choose another name.")
            return
        mats = tmat.user_materials() + [{"name": name, "k": m["k"], "rho": m["rho"], "cp": m["cp"]}]
        try:
            tmat.save_user(mats)
        except OSError as ex:
            QMessageBox.warning(self, "Add material", f"Could not save the library: {ex}")
            return
        self.fill_materials(select=name)
        self.material_picked()

    def delete_material(self):
        name = self.mat_combo.currentData()
        if name is None or name in tmat.builtin_names():
            QMessageBox.information(self, "Delete material", "Choose a material you added first. The built-in ones cannot be deleted.")
            return
        if QMessageBox.question(self, "Delete material", f"Delete '{name}' from your library?") != QMessageBox.StandardButton.Yes:
            return
        tmat.save_user([m for m in tmat.user_materials() if m["name"] != name])
        self.fill_materials()
        self.update_mat_note()

    def analysis_changed(self, *_):
        self.tr_box.setVisible(self.analysis_combo.currentIndex() == 1)
        self.after_inputs()

    def after_inputs(self):
        """An input of the setup changed: the result no longer matches it."""
        self.refresh_sections()

    # ------------------------------------------------------------------------------------------------------------------------------ conditions
    NAMES = {"temp": "Temperature", "flux": "Heat flux", "power": "Heat flow", "conv": "Convection", "rad": "Radiation"}

    def default_name(self, is_sup, idx):
        items = self.supports if is_sup else self.loads
        kind = items[idx]["kind"]
        same = [j for j, x in enumerate(items) if x["kind"] == kind]
        return f"{self.NAMES[kind]} {same.index(idx) + 1}"

    def type_text(self, item):
        fam = self.family()
        k = item["kind"]
        return {"temp": f"Temperature ({fam.temp})", "flux": f"Heat flux ({fam.unit('q')}, into the body)", "power": f"Heat flow ({fam.unit('P')})",
                "conv": f"Convection (h in {fam.unit('h')}, fluid in {fam.temp})", "rad": f"Radiation (emissivity, surroundings in {fam.temp})"}[k]

    def cond_value_text(self, item, is_sup=None):
        fam = self.family()
        k = item["kind"]
        if k == "temp":
            return f"{fam.from_si('T', item['T']):.10g}"
        if k == "flux":
            return f"{fam.from_si('q', item['q']):.10g}"
        if k == "power":
            return f"{fam.from_si('P', item['P']):.10g}"
        if k == "conv":
            return f"{fam.from_si('h', item['h']):.10g}, {fam.from_si('T', item['Tinf']):.10g}"
        return f"{item['eps']:.10g}, {fam.from_si('T', item['Ts']):.10g}"

    def refresh_lists(self):
        self.refresh_sections()
        self.cond_list.clear()
        t = self.cond_table
        t.blockSignals(True)
        t.setRowCount(len(self.supports) + len(self.loads))
        r = 0
        for is_sup, items in ((True, self.supports), (False, self.loads)):
            for idx, it in enumerate(items):
                typ = self.type_text(it)
                self.cond_list.addItem(f"{self.cond_name(is_sup, idx)}: {typ}  {self.cond_value_text(it)}  on {self.names(it['targets'])}")
                self.fill_cond_row(r, is_sup, idx, typ, it)
                r += 1
        t.resizeColumnsToContents()
        t.blockSignals(False)
        self.fill_probe_table()

    def after_conditions(self):
        self.result = None
        self._flux_cache = {}
        self.canvas.field = None
        self.field.blockSignals(True)
        self.field.setCurrentIndex(0)
        self.field.blockSignals(False)
        self.res_lbl.setText("")
        self.node_lbl.setText("")
        self.canvas.node_sel = None
        self.update_time_controls()
        self.refresh_lists()
        self.canvas.invalidate()

    def set_condition_value(self, r, text):
        """Edits a value from the table (in the family's units).  Returns True when it was taken."""
        if not (0 <= r < len(self.supports) + len(self.loads)):
            return False
        is_sup, idx, item = self._cond_ref(r)
        fam = self.family()
        k = item["kind"]
        hints = {"temp": "one temperature above absolute zero", "flux": "one number", "power": "one number",
                 "conv": "the coefficient (0 or more), then the fluid temperature", "rad": "the emissivity (0 to 1), then the surroundings temperature"}
        new = None
        nums = [float(x) for x in NUM.findall(text.replace(";", ","))]
        if k in ("temp", "flux", "power") and len(nums) == 1:
            key = {"temp": "T", "flux": "q", "power": "P"}[k]
            v = fam.to_si("T" if k == "temp" else key, nums[0])
            if k != "temp" or v > 0:
                new = {key: v}
        elif k == "conv" and len(nums) == 2:
            h, Ti = fam.to_si("h", nums[0]), fam.to_si("T", nums[1])
            if h >= 0 and Ti > 0:
                new = {"h": h, "Tinf": Ti}
        elif k == "rad" and len(nums) == 2:
            Ts = fam.to_si("T", nums[1])
            if 0 <= nums[0] <= 1 and Ts > 0:
                new = {"eps": nums[0], "Ts": Ts}
        if new is None:
            self.status("That value was not understood: " + hints[k] + ".")
            QTimer.singleShot(0, self.refresh_lists)
            return False
        if any(abs(item.get(a, 0.0) - v) > 1e-12 * max(1.0, abs(v)) for a, v in new.items()):
            item.update(new)
            QTimer.singleShot(0, self.after_conditions)
        return True

    def add_temperature(self):
        t = self.targets(("pt", "ln", "ar", "ci"), "Temperature")
        if not t:
            return
        fam = self.family()
        v = ask_values(self, "Temperature on the selected edges / points", "The selected edges or points are held at this temperature, whatever heat it takes.",
                       [f"Temperature ({fam.temp})"], [f"{fam.from_si('T', self.last_vals.get('T', 373.15)):.6g}"])
        if v is None:
            return
        K = fam.to_si("T", v[0])
        if not K > 0:
            QMessageBox.warning(self, "Temperature", "That is below absolute zero.")
            return
        self.last_vals["T"] = K
        self.supports.append({"kind": "temp", "T": K, "targets": t})
        self.after_conditions()

    def add_flux(self):
        t = self.targets(("ln", "ar", "ci"), "Heat flux")
        if not t:
            return
        fam = self.family()
        v = ask_values(self, "Heat flux on the selected edges", "Heat pushed through the edge per unit of its area (per unit of length times the depth). "
                       "Positive heats the body; negative takes heat out of it.", [f"Heat flux ({fam.unit('q')})"],
                       [f"{fam.from_si('q', self.last_vals.get('q', 1000.0)):.6g}"])
        if v is None:
            return
        self.last_vals["q"] = fam.to_si("q", v[0])
        self.loads.append({"kind": "flux", "q": fam.to_si("q", v[0]), "targets": t})
        self.after_conditions()

    def add_power(self):
        t = self.targets(("pt",), "Heat flow")
        if not t:
            return
        fam = self.family()
        v = ask_values(self, "Heat flow at the selected points", "Heat put into each selected point, in total through the depth of the plate (a wire, a "
                       "chip, a cartridge heater seen end-on). Positive heats the body.", [f"Heat flow ({fam.unit('P')})"],
                       [f"{fam.from_si('P', self.last_vals.get('P', 10.0)):.6g}"])
        if v is None:
            return
        self.last_vals["P"] = fam.to_si("P", v[0])
        self.loads.append({"kind": "power", "P": fam.to_si("P", v[0]), "targets": t})
        self.after_conditions()

    def add_conv(self):
        t = self.targets(("ln", "ar", "ci"), "Convection")
        if not t:
            return
        fam = self.family()
        v = ask_values(self, "Convection on the selected edges", "The edge loses heat to a fluid (air, water) by h times the difference between its "
                       "temperature and the fluid's. Still air is about 5 to 25 W/(m2 K); moving air 10 to 100; water 100 to 10000.",
                       [f"Convection coefficient h ({fam.unit('h')})", f"Fluid temperature ({fam.temp})"],
                       [f"{fam.from_si('h', self.last_vals.get('h', 10.0)):.6g}", f"{fam.from_si('T', self.last_vals.get('Tinf', 293.15)):.6g}"])
        if v is None:
            return
        h, Ti = fam.to_si("h", v[0]), fam.to_si("T", v[1])
        if h < 0 or not Ti > 0:
            QMessageBox.warning(self, "Convection", "The coefficient cannot be negative and the fluid cannot be below absolute zero.")
            return
        self.last_vals.update(h=h, Tinf=Ti)
        self.loads.append({"kind": "conv", "h": h, "Tinf": Ti, "targets": t})
        self.after_conditions()

    def add_rad(self):
        t = self.targets(("ln", "ar", "ci"), "Radiation")
        if not t:
            return
        fam = self.family()
        v = ask_values(self, "Radiation on the selected edges", "The edge radiates to surroundings that are much larger than the model: emissivity times the "
                       "Stefan-Boltzmann constant times (T^4 - surroundings^4). Radiation between the parts of the model is not included.",
                       ["Emissivity (0 to 1)", f"Surroundings temperature ({fam.temp})"],
                       [f"{self.last_vals.get('eps', 0.8):.6g}", f"{fam.from_si('T', self.last_vals.get('Ts', 293.15)):.6g}"])
        if v is None:
            return
        eps, Ts = v[0], fam.to_si("T", v[1])
        if not (0 <= eps <= 1) or not Ts > 0:
            QMessageBox.warning(self, "Radiation", "The emissivity must be between 0 and 1 and the surroundings cannot be below absolute zero.")
            return
        self.last_vals.update(eps=eps, Ts=Ts)
        self.loads.append({"kind": "rad", "eps": eps, "Ts": Ts, "targets": t})
        self.after_conditions()

    # ------------------------------------------------------------------------------------------------------------------------------ mesh and solve
    def read_setup(self, need_mesh=True):
        """The whole problem in SI for thermal_fem.solve.  Raises pf.ModelError (a message for the user)."""
        if need_mesh and self.mesh is None:
            raise pf.ModelError("Mesh first.")
        fam = self.family()
        mat = self.default_material()
        t = self.num(self.e_t, "The thickness", positive=True) * self.lscale()
        included = {f["id"] for f in self.geom["faces"] if f["included"]}
        setup = {"lscale": self.lscale(), "t": t, "order": 1 if self.order_combo.currentIndex() == 1 else 2,
                 "mat": {"k": mat["k"], "rho": mat["rho"], "cp": mat["cp"]},
                 "region_mats": {f: {"k": m["k"], "rho": m["rho"], "cp": m["cp"]} for f, m in (self.region_mats or {}).items() if f in included},
                 "region_q": {f: v for f, v in (self.region_q or {}).items() if f in included and v != 0.0}, "conds": []}
        for is_sup, items in ((True, self.supports), (False, self.loads)):
            for idx, it in enumerate(items):
                c = {k: v for k, v in it.items() if k in ("kind", "T", "q", "P", "h", "Tinf", "eps", "Ts")}
                c["targets"] = [tuple(x) for x in it["targets"]]
                c["name"] = self.cond_name(is_sup, idx)
                setup["conds"].append(c)
        if self.cb_plate.isChecked():
            h = fam.to_si("h", self.num(self.e_hplate, "The convection coefficient of the faces", nonneg=True))
            eps = self.num(self.e_eps_plate, "The emissivity of the faces", nonneg=True)
            if eps > 1:
                raise pf.ModelError("The emissivity of the faces must be between 0 and 1.")
            Ti = fam.to_si("T", self.num(self.e_Tamb, "The fluid temperature of the faces"))
            Ts = fam.to_si("T", self.num(self.e_Tsur, "The surroundings temperature of the faces"))
            if not (Ti > 0 and Ts > 0):
                raise pf.ModelError("The temperatures of the faces must be above absolute zero.")
            setup["plate"] = {"h": h, "eps": eps, "Tinf": Ti, "Ts": Ts}
        if self.analysis_combo.currentIndex() == 1:
            T0 = fam.to_si("T", self.num(self.e_T0, "The start temperature"))
            if not T0 > 0:
                raise pf.ModelError("The start temperature must be above absolute zero.")
            t_end = self.num(self.e_tend, "The end time", positive=True) * tu.TIME[self.time_combo.currentText()]
            try:
                steps, nfr = int(float(self.e_steps.text())), int(float(self.e_nframes.text()))
            except ValueError:
                raise pf.ModelError("The number of time steps and of pictures must be whole numbers.")
            if not (1 <= steps <= 50000):
                raise pf.ModelError("Use 1 to 50000 time steps.")
            if not (2 <= nfr <= 400):
                raise pf.ModelError("Keep 2 to 400 pictures.")
            setup.update(analysis="transient", T0=T0, t_end=t_end, steps=steps, frames=min(nfr, steps + 1),
                         theta=0.5 if self.method_combo.currentIndex() == 0 else 1.0)
        else:
            setup["analysis"] = "steady"
        return setup

    def run_solve(self):
        try:
            setup = self.read_setup()
        except pf.ModelError as ex:
            QMessageBox.warning(self, "Solve", str(ex))
            return
        mesh = self.mesh
        t0 = time.monotonic()
        kind, data = self.run_task("Solving", lambda progress, cancel: tfem.solve(mesh, setup, progress, cancel))
        if kind != "ok":
            self.status("Solve cancelled." if kind == "cancelled" else "Solve failed.")
            return
        self.last_setup = setup
        data["total_time"] = time.monotonic() - t0
        self.show_solution(data)

    def study_adapter(self):
        """What the Parametric Studies add-on talks to (study_iface.py)."""
        import thermal_study
        return thermal_study.ThermalStudy(self)

    def load_case(self, mesh, result):
        """Shows a stored result (from a parametric study) on the canvas."""
        self.mesh = mesh
        self.canvas.field = None
        self.field.blockSignals(True)
        self.field.setCurrentIndex(0)
        self.field.blockSignals(False)
        self.canvas.invalidate()
        self.frame_idx = max(0, len(result["frames"]) - 1) if result.get("frames") is not None else 0
        self.show_solution(result, restored=True)
        self.enable_buttons()

    # ------------------------------------------------------------------------------------------------------------------------------ what is on screen
    def frame_count(self):
        r = self.result
        return 0 if r is None or r.get("frames") is None else len(r["frames"])

    def frame_of(self, ramp=None):
        """Index of the transient picture shown (`ramp` None) or at `ramp` 0..1 of the run; None for a steady result."""
        n = self.frame_count()
        if n == 0:
            return None
        if ramp is None:
            return max(0, min(n - 1, self.frame_idx))
        return int(round(max(0.0, min(1.0, float(ramp))) * (n - 1)))

    def temperature_of(self, k):
        return self.result["T"] if k is None else self.result["frames"][k]

    def flux_for(self, k):
        r = self.result
        if k is None:
            return r["qx"], r["qy"], r["qmag"]
        key = (id(r), k)
        if key not in self._flux_cache:
            self._flux_cache[key] = tfem.flux_of(r, r["frames"][k])
        return self._flux_cache[key]

    def field_range(self, key):
        """Smallest and largest value of a field over the whole run (SI), so that the colours mean the same in every picture."""
        r = self.result
        if key == "T":
            a = r["frames"] if r.get("frames") is not None else r["T"]
            return float(np.min(a)), float(np.max(a))
        i = {"qx": 0, "qy": 1, "q": 2}[key]
        ks = range(self.frame_count()) if self.frame_count() else [None]
        lo, hi = np.inf, -np.inf
        for k in ks:
            v = self.flux_for(k)[i]
            lo, hi = min(lo, float(v.min())), max(hi, float(v.max()))
        return lo, hi

    def field_arrays(self, key, ramp=None):
        """(values for the drawing triangles / nodes in the family's units, "nodal" | "elem", lo, hi, frame index) of a field."""
        fam = self.family()
        k = self.frame_of(ramp)
        name, _key, kind, q = next(f for f in FIELDS if f[1] == key)
        lo, hi = self.field_range(key)
        if key == "T":
            vals = self.temperature_of(k)
        else:
            vals = self.flux_for(k)[{"qx": 0, "qy": 1, "q": 2}[key]]
        return fam.from_si(q, vals), kind, fam.from_si(q, lo), fam.from_si(q, hi), k

    def time_text(self, k):
        r = self.result
        if k is None or r is None or r.get("times") is None:
            return None
        u = self.time_combo.currentText()
        return f"t = {r['times'][k] / tu.TIME[u]:.4g} {u}"

    def update_time_controls(self):
        n = self.frame_count()
        self.time_box.setVisible(n > 1)
        self.cb_anim.setEnabled(n > 1)
        if n <= 1:
            if self.cb_anim.isChecked():
                self.cb_anim.setChecked(False)
            return
        self.time_slider.blockSignals(True)
        self.time_slider.setRange(0, n - 1)
        self.time_slider.setValue(max(0, min(n - 1, self.frame_idx)))
        self.time_slider.blockSignals(False)
        self.time_lbl.setText(self.time_text(self.frame_of(None)) or "")

    def frame_moved(self, v):
        self.frame_idx = int(v)
        self.view_token += 1
        self.time_lbl.setText(self.time_text(self.frame_of(None)) or "")
        self.canvas.update()
        if self.probes and self.result is not None:            # the probe averages are those of the picture shown
            self.res_lbl.setText(self.report_html(self.result))
        if self.canvas.node_sel is not None:
            self.show_node(self.canvas.node_sel)

    def view_changed(self, *_):
        cv = self.canvas
        cv.field = self.field.currentData()
        cv.show_mesh = self.cb_mesh.isChecked()
        cv.show_deformed = False
        self.view_token += 1
        cv.invalidate()
        if cv.node_sel is not None and self.result is not None:
            self.show_node(cv.node_sel)

    def show_solution(self, data, restored=False):
        """Makes a (new or restored) result the one on screen."""
        self.result = data
        self._flux_cache = {}
        if not restored:
            self.frame_idx = max(0, self.frame_count() - 1)
        self.field.blockSignals(True)
        self.field.setCurrentIndex(max(0, self.field.findData("T")))
        self.field.blockSignals(False)
        self.update_time_controls()
        self.view_changed()
        self.res_lbl.setText(self.report_html(data))
        if not restored:
            tt = data.get("total_time")
            self.status("Solved" + (f" in {tt:.2f} s." if tt else "."))

    def report_html(self, data):
        fam = self.family()
        T = lambda v: R.num(fam.from_si("T", v), 5)
        trans = data.get("analysis") == "transient"
        rows = [("Highest temperature" + (" (at the end)" if trans else ""), T(data["Tmax"]), fam.temp),
                ("Lowest temperature" + (" (at the end)" if trans else ""), T(data["Tmin"]), fam.temp),
                ("Average temperature (by area)" + (" (at the end)" if trans else ""), T(data["Tmean"]), fam.temp),
                ("Largest heat flux" + (" (at the end)" if trans else ""), R.num(fam.from_si("q", float(np.max(data["qmag"])))), fam.unit("q"))]
        html = R.heading("Summary") + R.kv(rows)
        if data.get("analysis") == "transient":
            run = data.get("run") or {}
            st = data.get("setup") or {}
            html += R.note(f"Transient: {st.get('steps', '?')} steps of {R.num(run.get('dt'), 3)} s to {R.num(st.get('t_end'), 4)} s, "
                           f"{'Crank-Nicolson' if st.get('theta', 1.0) < 1.0 else 'backward Euler'}. The picture shown can be chosen with the slider.")
        P = lambda v: R.num(fam.from_si("P", v), 5)
        flows = data.get("flows") or []
        if flows:
            html += R.heading("Heat through each condition", f"({fam.unit('P')}, through the depth; positive = into the body)")
            html += R.grid(["", "Heat"], [[f["name"], P(f["Q"])] for f in flows])
        b = data["balance"]
        brow = [("Heat in (conditions and generation)", P(b["in"]), fam.unit("P")), ("Heat out", P(b["out"]), fam.unit("P"))]
        if abs(b["generation"]) > 0:
            brow.insert(1, ("   of which generated inside", P(b["generation"]), fam.unit("P")))
        if abs(b["stored"]) > 0 or data.get("analysis") == "transient":
            brow.append(("Stored (heating up)", P(b["stored"]), fam.unit("P")))
        if abs(b["face_conv"]) > 0 or abs(b["face_rad"]) > 0:
            brow.append(("   lost from the flat faces: convection", P(b["face_conv"]), fam.unit("P")))
            brow.append(("   lost from the flat faces: radiation", P(b["face_rad"]), fam.unit("P")))
        html += R.heading("Heat balance") + R.kv(brow)
        cn = data.get("analysis") == "transient" and (data.get("setup") or {}).get("theta", 1.0) < 1.0
        ok = b["relative_error"] <= (5e-2 if cn else 1e-6)
        html += R.kv([("Heat in - out - stored", chip_or(ok, f"{b['relative_error']:.1e} of the flow"), None)])
        nw = data.get("newton")
        if nw is not None:
            html += R.note(f"Radiation makes the problem nonlinear: Newton's method needed {nw.get('iterations', '?')} iteration(s) "
                           f"({'converged' if nw.get('converged') else 'NOT converged'}).", R.GREY if nw.get("converged") else R.RED)
        kf = self.frame_of(None)
        pr = tfem.probe_stats(data, self.probes, None if kf is None else self.temperature_of(kf)) if self.probes else []
        if pr:
            html += R.heading("Probe regions", self.time_text(kf) if kf is not None else None)
            for q in pr:
                if q["avg"] is None:
                    html += R.subhead(q["name"]) + R.note("no element inside")
                else:
                    html += R.subhead(q["name"], fam.temp) + R.kv([("Average temperature", T(q["avg"]), None), ("Lowest", T(q["min"]), None),
                                                                  ("Highest", T(q["max"]), None),
                                                                  (f"Average heat flux ({fam.unit('q')})", R.num(fam.from_si('q', q['q_avg'])), None)])
        for n in sorted(set(data.get("notes") or [])):
            html += R.note(n, R.AMBER)
        return html

    # ------------------------------------------------------------------------------------------------------------------------------ probes
    def fill_probe_table(self):
        t = self.probe_table
        t.blockSignals(True)
        t.setRowCount(len(self.probes))
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        for r, q in enumerate(self.probes):
            a = QTableWidgetItem(q["name"])
            a.setFlags(ro | Qt.ItemFlag.ItemIsEditable)
            b = QTableWidgetItem("Circle" if q["shape"] == "circle" else "Rectangle")
            b.setFlags(ro)
            c = QTableWidgetItem(self.probe_geo_text(q))
            c.setFlags(ro | Qt.ItemFlag.ItemIsEditable)
            t.setItem(r, 0, a)
            t.setItem(r, 1, b)
            t.setItem(r, 2, c)
        t.resizeColumnsToContents()
        t.blockSignals(False)

    def probe_item_changed(self, it):
        r, c = it.row(), it.column()
        if not (0 <= r < len(self.probes)):
            return
        if c == 0:
            self.rename_probe(r, it.text())
        elif c == 2:
            self.set_probe_geometry(r, it.text())

    def probes_changed(self, resolve=True):
        self.canvas.update()
        if self.result is not None:
            self.res_lbl.setText(self.report_html(self.result))
            if self.canvas.node_sel is not None:
                self.show_node(self.canvas.node_sel)

    def _result_nodes(self):
        r = self.result
        vm = (r.get("mesh") if r else None) or self.mesh
        return vm, np.asarray(vm["nodes"])[:, :2]

    def node_results(self, idx):
        """Every result at node `idx` of the result mesh: the temperature, and the heat flux averaged over the drawing triangles around the node."""
        r = self.result
        vm = r["mesh"]
        tris = np.asarray(vm["tris"])
        n = len(vm["nodes"])
        k = self.frame_of(None)
        cnt = np.zeros(n)
        for j in range(3):
            cnt += np.bincount(tris[:, j], minlength=n)
        out = {"index": idx, "x": float(vm["nodes"][idx][0]), "y": float(vm["nodes"][idx][1]), "n_elems": int(cnt[idx]),
               "T": float(self.temperature_of(k)[idx]), "t": None if k is None else float(r["times"][k])}
        for key, arr in zip(("qx", "qy", "q"), self.flux_for(k)):
            acc = np.zeros(n)
            for j in range(3):
                acc += np.bincount(tris[:, j], weights=arr, minlength=n)
            out[key] = float(acc[idx] / cnt[idx]) if cnt[idx] > 0 else float("nan")
        return out

    def show_node(self, idx):
        try:
            nr = self.node_results(idx)
        except Exception as ex:                                  # noqa: BLE001
            self.node_lbl.setText(f"Could not read that node: {ex}")
            return
        fam, L = self.family(), units.get(self.unit_name())["L"]
        rows = [("Temperature", R.num(fam.from_si("T", nr["T"])), fam.temp), ("Heat flux x", R.num(fam.from_si("q", nr["qx"])), fam.unit("q")),
                ("Heat flux y", R.num(fam.from_si("q", nr["qy"])), fam.unit("q")), ("Heat flux magnitude", R.num(fam.from_si("q", nr["q"])), fam.unit("q"))]
        where = f"at ({R.num(nr['x'])}, {R.num(nr['y'])}) {L}"
        if nr["t"] is not None:
            where += f", {self.time_text(self.frame_of(None))}"
        self.node_lbl.setText(R.heading(f"Node {nr['index']}") + R.note(where) + R.kv(rows) +
                              R.note(f"Heat flux: average of the {nr['n_elems']} element(s) around the node."))
        self.last_node = nr

    # ------------------------------------------------------------------------------------------------------------------------------ save / restore
    def export_state(self):
        return {"model_json": self.model.to_json(), "source": getattr(self, "source", ""), "inputs": pstore.get_inputs(self, self.INPUTS),
                "cur_unit": self.cur_unit, "material": self.mat_combo.currentData(), "faces_included": [bool(f["included"]) for f in self.geom["faces"]],
                "supports": self.supports, "loads": self.loads, "mesh": self.mesh, "result": self.result, "probes": [dict(q) for q in self.probes],
                "probe_fos": None, "probe_trig": None, "profile": None, "field": self.field.currentData(), "sketch_id": getattr(self, "sketch_id", None),
                "region_mats": getattr(self, "region_mats", {}), "region_names": getattr(self, "region_names", {}),
                "region_q": getattr(self, "region_q", {}), "frame": self.frame_idx, "last_vals": dict(self.last_vals)}

    def import_state(self, st, out_of_date=False):
        m = sc.Model()
        m.from_json(st["model_json"])
        self.set_model(m, st.get("source") or "the saved sketch")
        self.sketch_id = st.get("sketch_id")
        for f, inc in zip(self.geom["faces"], st.get("faces_included", [])):
            f["included"] = bool(inc)
        self.region_mats, self.region_names = dict(st.get("region_mats") or {}), dict(st.get("region_names") or {})
        self.region_q = dict(st.get("region_q") or {})
        self.last_vals = dict(st.get("last_vals") or {})
        self.fill_regions()
        pstore.set_inputs(self, st.get("inputs", {}))
        self.tr_box.setVisible(self.analysis_combo.currentIndex() == 1)
        self.plate_box.setVisible(self.cb_plate.isChecked())
        self.cur_unit = st.get("cur_unit", self.cur_unit)
        self.mat_combo.blockSignals(True)
        i = self.mat_combo.findData(st.get("material"))
        self.mat_combo.setCurrentIndex(i if i >= 0 else 0)
        self.mat_combo.blockSignals(False)
        self.update_mat_note()
        self.supports, self.loads = [dict(s) for s in st.get("supports", [])], [dict(s) for s in st.get("loads", [])]
        self.probes = [dict(q) for q in st.get("probes", [])]
        self.probe_fos = self.probe_trig = None
        self.canvas.node_sel = None
        self.node_lbl.setText("")
        self.refresh_lists()
        self.mesh = st.get("mesh")
        if self.mesh is not None:
            s_ = self.mesh["stats"]
            self.status(f"Restored the saved mesh ({s_['n_nodes']} nodes, {s_['n_tris']} triangles).")
        self.result = None
        self.canvas.field = None
        self.frame_idx = int(st.get("frame") or 0)
        if st.get("result") is not None and self.mesh is not None:
            self.show_solution(st["result"], restored=True)
            j = self.field.findData(st.get("field"))
            if j >= 0:
                self.field.blockSignals(True)
                self.field.setCurrentIndex(j)
                self.field.blockSignals(False)
            self.status("Restored the saved thermal setup and result.")
        elif self.mesh is not None:
            self.status("Restored the saved thermal setup and mesh (not solved).")
        else:
            self.status("Restored the saved thermal setup (not meshed).")
        self.anim_box.setVisible(self.cb_anim.isChecked() and self.cb_anim.isEnabled())
        self.update_time_controls()
        self.view_changed()
        self.canvas.fit()
        self.refresh_region_row()
        self.enable_buttons()
        if out_of_date:
            self.mark_out_of_date()

    def change_units(self, old, new, convert):
        """The program's unit system changed: the sketch copy, the mesh, the result, the probes and the numbers in the boxes follow it."""
        st = tstore.convert_state(self.export_state(), old, new, convert)
        self.import_state(st)
        return "" if convert else "The mesh and the result were cleared (the numbers stayed, their unit changed): mesh and solve again."

    # ------------------------------------------------------------------------------------------------------------------------------ diagnostics
    def diagnostics_text(self):
        L = []
        add = L.append
        add("2D THERMAL - DIAGNOSTICS")
        add(time.strftime("%Y-%m-%d %H:%M:%S"))
        add(f"python {sys.version.split()[0]} on {platform.platform()}")
        for n, (v, t) in self.deps.items():
            add(f"  {n}: {v if v else 'NOT AVAILABLE  ' + t}")
        if self.geom is None:
            add("\nNothing imported.")
            return "\n".join(L)
        g, m = self.geom, self.model
        fam = self.family()
        add("\n== Imported sketch ==")
        add(f"source: {getattr(self, 'source', '?')}")
        add(f"points {len(m.pts)}, lines {len(m.lns)}, arcs {len(m.ars)}, circles {len(m.cis)}, unit system {m.unit_system}")
        add(f"edges not in a closed loop (ignored): {[f'{KIND_NAME[k]} {i}' for k, i in g['pruned']] or 'none'}")
        add("edge crossings: " + ("none" if not g["crossings"] else "; ".join(
            f"{KIND_NAME[a[0]]} {a[1]} x {KIND_NAME[b[0]]} {b[1]} at ({p[0]:.5g}, {p[1]:.5g})" for a, b, p in g["crossings"])))
        add("regions:")
        for f in g["faces"]:
            mm = (self.region_mats or {}).get(f["id"])
            q = (self.region_q or {}).get(f["id"], 0.0)
            add(f"  Region {f['id'] + 1}: net area {f['net_area']:.8g}, {'MATERIAL' if f['included'] else 'off'}"
                + (f", material {mm['name']} (k {mm['k']:g}, rho {mm['rho']:g}, cp {mm['cp']:g})" if mm else "") + (f", generates {q:g} W/m3" if q else ""))
        add("\n== Setup (SI) ==")
        try:
            s = self.read_setup() if self.mesh is not None else None
        except pf.ModelError as ex:
            s = None
            add(f"setup: {ex}")
        try:
            mat = self.default_material()
            add(f"material of the tab: {mat['name']}, k {mat['k']:g} W/(m K), rho {mat['rho']:g} kg/m3, cp {mat['cp']:g} J/(kg K)")
        except pf.ModelError as ex:
            add(f"material: {ex}")
        add(f"thickness {self.e_t.text()} {units.get(self.unit_name())['L']}, element size {self.e_h.text()}, unit system {self.unit_name()} (temperatures in {fam.temp})")
        if s is not None:
            add(f"analysis: {s['analysis']}" + (f", start {s['T0']:.2f} K, end {s['t_end']:g} s, {s['steps']} steps, theta {s['theta']}" if s["analysis"] == "transient" else ""))
            add(f"flat faces: {s.get('plate') or 'insulated'}")
        add("conditions:")
        for is_sup, items in ((True, self.supports), (False, self.loads)):
            for idx, it in enumerate(items):
                vals = {k: v for k, v in it.items() if k not in ("targets", "kind", "name")}
                add(f"  {self.cond_name(is_sup, idx)}: {it['kind']} {vals} on {self.names(it['targets'])}")
        if self.mesh is None:
            add("\nNo mesh yet.")
            return "\n".join(L)
        s_ = self.mesh["stats"]
        add("\n== Mesh ==")
        add(f"gmsh {s_.get('gmsh', '?')}, requested element size {s_['h']:g}, nodes {s_['n_nodes']}, triangles {s_['n_tris']}")
        add(f"edge length min/max: {s_['edge_min']:.6g} / {s_['edge_max']:.6g}; angle min/max {s_['angle_min']:.2f} / {s_['angle_max']:.2f} deg; "
            f"aspect max {s_['aspect_max']:.3f}")
        if self.result is None:
            add("\nNot solved yet.")
            return "\n".join(L)
        r = self.result
        b = r["balance"]
        add("\n== Solution ==")
        add(f"{'quadratic' if r['order'] == 2 else 'linear'} elements, {r['dofs']} unknowns, {r['elements']} elements")
        add(f"temperature: min {r['Tmin']:.6g} K, max {r['Tmax']:.6g} K, area average {r['Tmean']:.6g} K")
        add(f"heat balance (W): in {b['in']:.8g}, out {b['out']:.8g}, stored {b['stored']:.8g}, generated {b['generation']:.8g}, "
            f"flat faces convection {b['face_conv']:.8g} / radiation {b['face_rad']:.8g}, error {b['error']:.3e} ({b['relative_error']:.2e} of the flow)")
        for f in r["flows"]:
            add(f"  {f['name']} ({f['kind']}): {f['Q']:.8g} W")
        add(f"newton: {r.get('newton')}")
        add(f"run: {r.get('run')}")
        for n in sorted(set(r.get("notes") or [])):
            add("note: " + n)
        return "\n".join(L)


def chip_or(ok, text):
    return R.chip("OK", "ok") + f" {text}" if ok else R.chip("CHECK", "bad") + f" {text}"
