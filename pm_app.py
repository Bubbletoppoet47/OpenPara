"""
pm_app.py - a small parametric modeller with a SolidWorks-style workflow.

  * FeatureManager tree on the left: Origin planes, Sketches, Boss-Extrude, Cut-Extrude, Fillet, Chamfer, in build order.
    Errors turn a feature red, later features are greyed (not built), a rollback bar steps back in the history.
  * Pick a plane in the tree or a face in the view, press Sketch, edit the sketch in the Properties panel, press Boss / Cut.
  * Every number is an expression ("W/2 + 3") that can use the Globals (Equations) table; change a global and the part rebuilds.
  * Fillet / Chamfer: press the button, click the edges in the view.
Run:  python pm_app.py [file.gpd]        needs: pip install build123d pyvista pyvistaqt PyQt6
"""
import os
import sys
import traceback

import numpy as np
from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtGui import QAction, QBrush, QColor, QKeySequence
from PyQt6.QtWidgets import (QWidgetAction, QApplication, QFrame, QTabWidget, QToolButton, QCheckBox, QComboBox, QDockWidget, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QToolBar,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import pm_model as pm
import unitctl
import evaluate
import config_panels
import sketch_edit
import icons
import nav
import mini_tree
import part_refgeo
import viewpick

try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
except Exception as _ex:                                   # the window still opens; the view says what is missing
    pv, QtInteractor = None, None
    VIEW_ERROR = f"{type(_ex).__name__}: {_ex}"
else:
    VIEW_ERROR = None

PART = (0.62, 0.70, 0.82)
SKETCH_COL, SKETCH_SEL = (0.95, 0.55, 0.05), (0.1, 0.45, 1.0)
FACE_SEL, EDGE_SEL = (0.3, 0.65, 1.0), (1.0, 0.45, 0.0)
PLANE_COL = {"Front": (0.35, 0.60, 0.95), "Top": (0.45, 0.80, 0.45), "Right": (0.90, 0.55, 0.40)}
ICON = {"sketch": "✎", "extrude": "▣", "cut": "▢", "fillet": "◜", "chamfer": "◿",
        "revolve": "◔", "revolve_cut": "◒", "pattern": "☷", "mirror": "⧓", "refplane": "▱", "refaxis": "⁞"}


class MainWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.doc = pm.Document()
        self.path = None
        self.undo, self.redo = [], []
        self.sel = None                  # selected feature id
        self.sel_plane = None            # "Front" | "Top" | "Right"
        self.sel_face = None             # {"ref": face ref (None for a curved face), "index": face index in the shown solid}
        self.sel_edges = []              # edge refs picked in the view (Shift adds); Fillet / Chamfer / Convert Entities use them
        self.nav = None
        self.mass_units = "Metric (mm, g)"
        self.measure_unit = unitctl.length_unit()
        self.measuring = False
        self.meas_items, self.meas_segs, self.meas_sig = [], [], None
        self.measure_panel = self.mass_dialog = None
        qs = QSettings("GenParametricDesigner", "Modeller")
        self.vis = {k: qs.value("show_" + k, "1") in ("1", 1, True, "true") for k in ("planes", "origin", "refgeo", "sketches", "dims", "edges")}
        self.plane_show = {"Front": True, "Top": True, "Right": True}
        self.show_origin_item = True
        self.rg_edit = None              # reference plane / axis feature whose references are being picked
        self.actor_refs = {}
        self.edge_polys = []             # outline polylines of the edges in the view (for picking)
        self.busy = False
        self.cam = None
        self.actor_part = None
        self.actor_planes = {}
        self.setWindowTitle("Parametric Modeller")
        self.resize(1300, 800)
        self.build_ui()
        if path and os.path.exists(path):
            self.open_file(path)
        else:
            self.demo()
        self.update_all(fit=True)
        self.saved_json = self.doc.to_json()

    def title(self):
        return os.path.basename(self.path) if self.path else "Part1"

    def is_dirty(self):
        return self.doc.to_json() != getattr(self, "saved_json", None)

    # ------------------------------------------------------------------ window
    def build_ui(self):
        # (the File / Edit / View menus live in the program window, gpd_app.py)
        self.flip_act = QAction("Zoom: wheel toward you = in", self)
        self.flip_act.setCheckable(True)
        self.flip_act.setChecked(True)
        self.flip_act.setToolTip("Untick to reverse the mouse-wheel zoom direction")
        self.flip_act.toggled.connect(lambda on: self.nav.flip_zoom(not on) if self.nav is not None else None)
        # ---- the ribbon: Features / Sketch tabs of big buttons, greyed ones are not built yet
        self.ribbon = QTabWidget()
        self.ribbon.setFixedHeight(104)
        self.ribbon.setDocumentMode(True)
        self.ribbon.setTabPosition(QTabWidget.TabPosition.South)
        self.act = {}
        self.menu_btns = {}
        self.ribbon.addTab(self.ribbon_page([
            ("extrude", "▣", "Extruded\nBoss/Base", "Add material from a sketch", lambda: self.command("extrude")),
            ("revolve", "◔", "Revolved\nBoss/Base", "Spin a sketch around an axis to add material", lambda: self.command("revolve")),
            "|",
            ("cut", "▢", "Extruded\nCut", "Remove material with a sketch", lambda: self.command("cut")),
            (None, "◎", "Hole\nWizard", "", None), ("revolve_cut", "◒", "Revolved\nCut", "Spin a sketch around an axis to remove material", lambda: self.command("revolve_cut")),
            "|",
            ("fillet", "◜", "Fillet", "Round edges: press, then click edges", lambda: self.command("fillet")),
            ("chamfer", "◿", "Chamfer", "Bevel edges: press, then click edges", lambda: self.command("chamfer")),
            ("menu_cmd", "☷", "Linear\nPattern", "Repeat features in a line or around an axis", [
                ("Linear Pattern", lambda: self.command("pattern_linear")), ("Circular Pattern", lambda: self.command("pattern_circular"))]),
            (None, "◫", "Shell", "", None), ("mirror", "⧓", "Mirror", "Mirror features about a plane or a flat face", lambda: self.command("mirror")),
            "|",
            ("menu_cmd", "▱", "Reference\nGeometry", "Planes and axes to sketch on, mirror about or mate to", [
                ("Plane", lambda: self.command("refplane")), ("Axis", lambda: self.command("refaxis"))]),
        ]), "Part Features")
        T = lambda name: (lambda: self.set_tool(name))
        self.menu_btns = {}
        self.ribbon.addTab(self.ribbon_page([
            ("sketch", "✎", "Sketch", "Start a sketch on the selected plane or face", lambda: self.command("sketch")),
            ("exit", "✔", "Exit\nSketch", "Leave the sketch (Esc with the Select tool also leaves it)", lambda: self.leave_sketch()),
            ("normal", "⊡", "Normal To", "Turn the view to face the sketch plane", lambda: self.ed.normal_to() if self.ed.active else None),
            "|",
            ("menu", "➤", "Select", "Select: click to pick (Shift adds, drag a point to move it, drag on empty space for a box) - or Box Select, where every drag is a box", [
                ("Select", "select"), ("Box Select", "box_select")]),
            ("menu", "╱", "Line", "Line: click points, each click continues the chain (double-click or Esc ends it)", [
                ("Line", "line"), ("Centerline", "centerline"), ("Midpoint Line", "midline")]),
            ("menu", "▭", "Rectangle", "Rectangles", [
                ("Corner Rectangle", "rect_corner"), ("Center Rectangle", "rect_center"), ("3 Point Corner Rectangle", "rect_3pt"),
                ("3 Point Center Rectangle", "rect_3pt_center"), ("Parallelogram", "parallelogram")]),
            ("menu", "◯", "Circle", "Circles", [("Circle", "circle"), ("Perimeter Circle", "circle_3pt")]),
            ("menu", "⌒", "Arc", "Arcs", [("Centerpoint Arc", "arc_center"), ("Tangent Arc", "arc_tangent"), ("3 Point Arc", "arc_3pt")]),
            ("menu", "⬭", "Slot", "Slots", [("Straight Slot", "slot_straight"), ("Centerpoint Straight Slot", "slot_center"),
                                         ("Centerpoint Arc Slot", "slot_arc_center"), ("3 Point Arc Slot", "slot_arc_3pt")]),
            ("tool_polygon", "⬡", "Polygon", "Click the centre, then a corner (asks for the number of sides)", T("polygon")),
            ("tool_point", "•", "Point", "Click to place a point", T("point")),
            "|",
            ("tool_fillet", "◜", "Sketch\nFillet", "Round a corner where two lines meet: click the corner", T("fillet")),
            ("tool_trim", "✂", "Trim\nEntities", "Click the piece of a line, arc or circle to cut away", T("trim")),
            (None, "⧉", "Offset\nEntities", "Select entities first, then press (distance, both sides, linked)", lambda: self.ed.command_offset()),
            (None, "⧓", "Mirror\nEntities", "Select entities, press, then click the line to mirror about", lambda: self.ed.command_mirror() and self.sync_tool()),
            ("menu_cmd", "⁝⁝", "Sketch\nPattern", "Copy the selection", [
                ("Linear Sketch Pattern", lambda: self.ed.command_linear()), ("Circular Sketch Pattern", lambda: self.ed.command_circular())]),
            (None, "✥", "Move\nEntities", "Select entities first, then enter how far", lambda: self.ed.command_move()),
            (None, "┄", "Construction", "Make the selected lines / arcs / circles construction geometry (or normal again)", lambda: self.ed.command_construction()),
            (None, "⤓", "Convert\nEntities", "Copy the edges of the part that lie in this plane into the sketch", lambda: self.ed.command_convert()),
            "|",
            ("menu_rel", "⟂", "Add\nRelation", "Select entities then pick a relation - or pick the relation then click entities", [
                ("Horizontal", "horizontal"), ("Vertical", "vertical"), ("Parallel", "parallel"), ("Perpendicular", "perpendicular"),
                ("Collinear", "collinear"), ("Coincident", "coincident"), ("Concentric", "concentric"), ("Tangent", "tangent"),
                ("Equal", "equal"), ("Fix", "fixed"), ("Midpoint", "midpoint")]),
            ("menu_rel", "↔", "Dimension", "Click the entities, then type a value, a symbol or an equation (e.g. Width/2)", [
                ("Horizontal", "dim_h"), ("Vertical", "dim_v"), ("Length / distance", "dim_len"), ("Radius", "dim_rad"),
                ("Diameter", "dim_dia"), ("Angle", "dim_ang")]),
        ]), "Sketch")
        self.ribbon.addTab(self.ribbon_page([
            ("mass", "⚖", "Mass\nProperties", "Mass, volume, center of mass and moments of inertia", lambda: self.mass_open()),
            ("measure", "↔", "Measure", "Measure points, edges and faces: click one or two items in the view", lambda: self.measure_toggle()),
        ]), "Evaluate")
        self.ribbon.addTab(self.ribbon_page([("sim_beam", "┼", "1D FEA\n(frames)", "Frames and trusses from a sketch of this part", lambda: self.add_sim("beam")),
                                    ("sim_fea", "▦", "2D FEA", "Plane stress / strain FEA of a sketch or a slice of this part", lambda: self.add_sim("fea")),
                                    ("sim_cfd", "≋", "2D CFD", "Flow around a sketch or a slice of this part", lambda: self.add_sim("cfd"))]), "Simulation")
        self.ribbon.addTab(self.ribbon_page([("render_new", "◉", "New render", "Photorealistic pictures and videos of this part: sun, lights, floor, cameras", lambda: self.add_render())]), "Render")
        self.ribbon.setCurrentIndex(0)
        # ---- the left panel: FeatureManager / PropertyManager / Equations
        self.left = QTabWidget()
        self.left.setTabPosition(QTabWidget.TabPosition.North)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.tree.currentItemChanged.connect(self.tree_selected)
        self.tree.itemChanged.connect(self.tree_check)
        self.tree.itemDoubleClicked.connect(self.tree_double)
        self.left.setIconSize(QSize(26, 26))
        self.left.addTab(self.tree, icons.icon("tab tree", 26), "")
        self.left.setTabToolTip(0, "Part tree")
        pmw = QWidget()
        pml = QVBoxLayout(pmw)
        pml.setContentsMargins(6, 6, 6, 6)
        head = QHBoxLayout()
        self.b_ok = QPushButton("✔ OK")
        self.b_ok.clicked.connect(self.pm_ok)
        self.b_cancel = QPushButton("✖ Cancel")
        self.b_cancel.clicked.connect(self.pm_cancel)
        head.addWidget(self.b_ok)
        head.addWidget(self.b_cancel)
        head.addStretch(1)
        pml.addLayout(head)
        self.props_title = QLabel("")
        self.props_title.setStyleSheet("font-weight:bold; font-size:13px; padding:4px 0;")
        pml.addWidget(self.props_title)
        self.props = QWidget()
        self.props_lay = QVBoxLayout(self.props)
        self.props_lay.setContentsMargins(0, 0, 0, 0)
        pml.addWidget(self.props, 1)
        self.left.addTab(pmw, icons.icon("tab properties", 26), "")
        self.left.setTabToolTip(1, "Properties")
        gw = QWidget()
        gl = QVBoxLayout(gw)
        gl.setContentsMargins(6, 6, 6, 6)
        gl.addWidget(QLabel("Equations (global variables). Use the names in any number field."))
        self.gtab = QTableWidget(0, 4)
        self.gtab.setHorizontalHeaderLabels(["Name", "Equation", "Value", "Type"])
        self.gtab.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.gtab.itemChanged.connect(self.global_edited)
        gl.addWidget(self.gtab)
        row = QHBoxLayout()
        b = QPushButton("+ Add")
        b.clicked.connect(self.global_add)
        row.addWidget(b)
        b = QPushButton("Delete")
        b.clicked.connect(self.global_del)
        row.addWidget(b)
        gl.addLayout(row)
        self.eq_dialog = QDialog(self)                      # the Equations folder of the tree opens this
        self.eq_dialog.setWindowTitle("Equations")
        self.eq_dialog.setWindowFlag(Qt.WindowType.Tool, True)
        self.eq_dialog.resize(420, 360)
        QVBoxLayout(self.eq_dialog).addWidget(gw)
        self.cfg_panel = config_panels.ConfigPanel(self, "part")
        self.left.addTab(self.cfg_panel, icons.icon("tab configurations", 26), "")
        self.left.setTabToolTip(2, "Configurations")
        self.disp_panel = config_panels.DisplayPanel(self)
        self.left.addTab(self.disp_panel, icons.icon("tab display", 26), "")
        self.left.setTabToolTip(3, "Display")
        self.left.setMinimumWidth(340)
        self.left.setMaximumWidth(460)
        # ---- the view
        view = QWidget()
        vl = QVBoxLayout(view)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(self.ribbon)
        bar = QWidget()
        bar.setObjectName("showbar")
        bar.setStyleSheet("#showbar{background:#cfd9ea; border:none;}")      # same blue as the top of the 3D view, so the button floats in it
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(6, 3, 6, 0)
        bl.addStretch(1)
        sb = QToolButton()
        sb.setText("Show  ▾")
        sb.setToolTip("Choose what is drawn in the view (tick as many as you like; click elsewhere to close)")
        sb.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        sb.setStyleSheet("QToolButton{background:rgba(255,255,255,170); border:1px solid #8fa6c8; border-radius:9px; padding:2px 14px; color:#1d2a44;}"
                         "QToolButton:hover{background:rgba(255,255,255,240);} QToolButton::menu-indicator{image:none;}")
        sm = QMenu(sb)
        self.show_checks = {}
        for key, label in (("planes", "Planes"), ("origin", "Origin"), ("refgeo", "Reference geometry"), ("sketches", "Sketches"), ("dims", "Sketch dimensions"),
                           ("edges", "Part edges")):
            cbx = QCheckBox(label)
            cbx.setChecked(self.vis[key])
            cbx.setStyleSheet("QCheckBox{padding:4px 14px 4px 10px;} QCheckBox:hover{background:#dbe8fa;}")
            cbx.toggled.connect(lambda on, k=key: self.set_show(k, on))
            wa = QWidgetAction(sm)               # a widget inside the menu: ticking it does not close the menu
            wa.setDefaultWidget(cbx)
            sm.addAction(wa)
            self.show_checks[key] = cbx
        sb.setMenu(sm)
        bl.addWidget(sb)
        bl.addStretch(1)
        bar.setFixedHeight(28)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self.left, 0)
        self.plotter = None
        self.ed = None
        if pv is None:
            body.addWidget(QLabel("The 3D view needs:  pip install pyvista pyvistaqt\n\n" + (VIEW_ERROR or "")), 1)
        else:
            self.plotter = QtInteractor(self)
            right = QWidget()
            rl = QVBoxLayout(right)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(0)
            rl.addWidget(bar)                 # the Show button sits over the 3D view only, so the tree reaches up to the ribbon
            rl.addWidget(self.plotter, 1)
            body.addWidget(right, 1)
            self.mini = mini_tree.MiniTree(self, self.plotter)
            try:
                self.plotter.set_background("#f7f9fc", top="#cfd9ea")
                try:
                    self.plotter.renderer.enable_lightkit()
                except Exception:
                    pass
                try:
                    self.plotter.enable_anti_aliasing("fxaa")
                except Exception:
                    pass
                try:   # push faces back a little and pull edge lines forward, so the outline of a cut shows on its walls and floor
                    import vtk
                    vtk.vtkMapper.SetResolveCoincidentTopologyToPolygonOffset()
                    vtk.vtkMapper.SetResolveCoincidentTopologyPolygonOffsetParameters(1.5, 1.5)
                    vtk.vtkMapper.SetResolveCoincidentTopologyLineOffsetParameters(-2.0, -2.0)
                except Exception:
                    pass
            except Exception:
                pass
            self.plotter.add_axes()
            self.hook = viewpick.ClickHook(self.plotter, self.on_click)
            self.ed = sketch_edit.SketchEditor(self)
            self.sk_hook = sketch_edit.SketchHook(self.plotter, self.ed)
            self.nav = nav.NavHook(self.plotter, self)         # installed last: it sees the mouse events first
            self.flip_act.blockSignals(True)
            self.flip_act.setChecked(self.nav.wheel_sign == 1)
            self.flip_act.blockSignals(False)
        vl.addLayout(body, 1)
        self.setCentralWidget(view)
        self.mode_label = QLabel("Editing Part")
        self.statusBar().addPermanentWidget(self.mode_label)
        self.statusBar().addPermanentWidget(QLabel("   MMGS   "))
        self.statusBar().showMessage("Select a plane, then press Sketch.")
        self.created_new = None          # feature id made by the command now open in the PropertyManager
        from PyQt6.QtGui import QShortcut
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=lambda: self.ed.cancel() if self.ed is not None and self.ed.active else None)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=lambda: self.ed.delete_selected() if self.ed is not None and self.ed.active else None)

    def add_sim(self, kind):
        sh = self.window()
        if hasattr(sh, "add_sim"):
            sh.add_sim(kind)

    def add_render(self):
        sh = self.window()
        if hasattr(sh, "add_render"):
            sh.add_render()

    def ribbon_page(self, items):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(2)
        for it in items:
            if it == "|":
                f = QFrame()
                f.setFrameShape(QFrame.Shape.VLine)
                f.setFrameShadow(QFrame.Shadow.Sunken)
                lay.addWidget(f)
                continue
            key, glyph, text, tip, fn = it
            b = QToolButton()
            ic = icons.icon(text)
            b.setText(text if ic is not None else f"{glyph}\n{text}")
            if ic is not None:
                b.setIcon(ic)
                b.setIconSize(QSize(36, 36))
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setToolTip(tip or text.replace("\n", " "))
            b.setAutoRaise(True)
            b.setMinimumWidth(66)
            b.setMinimumHeight(70)
            b.setStyleSheet("QToolButton{font-size:11px; padding:2px;} QToolButton:disabled{color:#a0a0a0;}")
            if key in ("menu", "menu_cmd", "menu_rel"):
                self.make_menu(b, key, glyph, text, fn)
                lay.addWidget(b)
                continue
            if key and key.startswith("tool_"):
                b.setCheckable(True)
                b.setAutoExclusive(True)
                b.setStyleSheet(b.styleSheet() + " QToolButton:checked{background:#cfe3fb; border:1px solid #6aa0e0;}")
            if fn is None:
                b.setEnabled(False)
            else:
                b.clicked.connect(lambda _c=False, f=fn: f())
            if key:
                self.act[key] = b
            lay.addWidget(b)
        lay.addStretch(1)
        from PyQt6.QtWidgets import QScrollArea
        sc_ = QScrollArea()
        sc_.setWidget(page)
        sc_.setWidgetResizable(True)
        sc_.setFrameShape(QFrame.Shape.NoFrame)
        sc_.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return sc_

    def make_menu(self, b, kind, glyph, text, entries):
        """A SolidWorks-style button with a drop-down: the button repeats the last choice, the arrow opens the list."""
        menu = QMenu(b)
        names = []
        state = {"last": None}
        ic = icons.icon(text)
        if ic is not None:
            b.setText(text)
            b.setIcon(ic)
            b.setIconSize(QSize(36, 36))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

        def run(label, what):
            if kind == "menu_cmd":
                what()
                return
            if kind == "menu_rel":
                self.relation_command(what)
            else:
                self.set_tool(what)
            state["last"] = (label, what)
            if b.icon().isNull():
                b.setText(f"{glyph}\n{label.replace(' ', chr(10), 1) if len(label) > 11 else label}")
        for label, what in entries:
            menu.addAction(label).triggered.connect(lambda _c=False, l=label, w=what: run(l, w))
            if kind != "menu_cmd":
                names.append(what)
        b.setMenu(menu)
        b.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        b.setCheckable(kind == "menu")
        b.setStyleSheet(b.styleSheet() + " QToolButton:checked{background:#cfe3fb; border:1px solid #6aa0e0;}")
        b.clicked.connect(lambda _c=False: run(*(state["last"] or entries[0])) if kind != "menu_cmd" else b.showMenu())
        self.menu_btns[b] = names

    def pm_ok(self):
        self.created_new = None
        self.rg_edit = None
        self.left.setCurrentIndex(0)

    def pm_cancel(self):
        if self.created_new and self.doc.feature(self.created_new) is not None:
            self.do_undo()
        self.created_new = None
        self.rg_edit = None
        self.left.setCurrentIndex(0)

    def enter_sketch(self, fid):
        """Open a sketch for editing: face the plane, show the sketch tools."""
        f = self.doc.feature(fid)
        if f is None or f["kind"] != "sketch" or self.ed is None:
            return
        if self.doc.status.get(fid) != "ok":
            self.say("This sketch cannot be opened: " + self.doc.status.get(fid, "not built"))
            return
        self.sel, self.sel_face, self.sel_plane = fid, None, None
        self.ed.begin(fid)
        self.ribbon.setCurrentIndex(1)
        self.left.setCurrentIndex(1)
        self.show_props()
        self.set_tool("select")
        self.mode_label.setText("Editing Sketch")
        self.say("Sketch open: pick a tool in the ribbon. Alt+drag orbits, middle drag pans, wheel zooms. Esc ends a tool, Exit Sketch leaves.")

    def set_tool(self, name):
        if self.ed is None or not self.ed.active:
            return
        if name == "polygon":
            r = sketch_edit.ask_form(self, "Polygon", [("Number of sides", float(self.ed.poly_n))])
            if r is None:
                return
            self.ed.poly_n = max(3, int(round(r[0][0])))
        elif name == "fillet":
            r = sketch_edit.ask_form(self, "Sketch fillet", [(unitctl.label("Radius (mm)"), unitctl.to_disp(float(self.ed.fillet_r)))], evaluator=self.ed.eval_field)
            if r is None or r[0][0] <= 0:
                return
            self.ed.fillet_r = unitctl.from_disp(r[0][0])
        self.ed.reset_tool(name)
        self.sync_tool()
        self.ed.say_prompt()
        self.ed.redraw()

    def relation_command(self, name):
        """Add Relation / Dimension: with entities already selected the relation is made at once, else click the entities."""
        if self.ed is None or not self.ed.active:
            return
        self.ed.start_relation(name)
        self.sync_tool()

    def sync_tool(self):
        t = self.ed.tool if self.ed is not None else "select"
        b = self.act.get("tool_" + t)
        if b is not None:
            b.setChecked(True)
        else:
            sel = self.act.get("tool_select")
            if sel is not None and t != "select":
                sel.setAutoExclusive(False)
                sel.setChecked(False)
                sel.setAutoExclusive(True)
        for mb, names in self.menu_btns.items():
            if mb.isCheckable():
                mb.setChecked(t in names)

    def undo_pop(self):
        if self.undo:
            self.undo.pop()

    def leave_sketch(self):
        self.created_new = None
        if self.ed is not None and self.ed.active:
            self.ed.end()
        self.mode_label.setText("Editing Part")
        self.left.setCurrentIndex(0)
        self.ribbon.setCurrentIndex(0)
        self.draw()

    def say(self, text):
        self.statusBar().showMessage(text)

    # ------------------------------------------------------------------ document handling
    def demo(self):
        d = self.doc
        d.params = {"Length": "60", "Width": "40", "Height": "15", "HoleD": "Width/4"}
        s = d.add(pm.new_feature("sketch", plane={"base": "Top"}, entities=[{"kind": "rect", "cx": 0, "cy": 0, "w": "Length", "h": "Width"}]))
        d.add(pm.new_feature("extrude", sketch=s["id"], depth="Height"))
        d.rebuild()

    def snapshot(self):
        self.undo.append((self.doc.to_json(), self.sel))
        self.undo = self.undo[-60:]
        self.redo = []

    def restore(self, js, sel):
        self.doc = pm.Document.from_json(js)
        self.rg_edit = None
        self.sel, self.sel_face, self.sel_plane = sel, None, None
        self.update_all()

    def do_undo(self):
        if self.undo:
            self.redo.append((self.doc.to_json(), self.sel))
            self.restore(*self.undo.pop())

    def do_redo(self):
        if self.redo:
            self.undo.append((self.doc.to_json(), self.sel))
            self.restore(*self.redo.pop())

    def new_doc(self):
        self.snapshot()
        self.doc, self.path, self.sel, self.sel_face, self.sel_plane = pm.Document(), None, None, None, None
        self.update_all(fit=True)

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open", "", "Part (*.gpd);;All files (*)")
        if p:
            self.open_file(p)
            self.update_all(fit=True)

    def open_file(self, p):
        try:
            self.doc = pm.Document.from_json(open(p, encoding="utf-8").read())
            self.path = p
            self.sel = self.sel_face = self.sel_plane = None
            self.undo, self.redo = [], []
            self.setWindowTitle(f"Parametric Modeller - {os.path.basename(p)}")
        except Exception as ex:
            QMessageBox.warning(self, "Open", str(ex))

    def save(self, as_new=False):
        import sim_links
        old_base = sim_links.base_dir(self)
        if as_new or not self.path:
            p, _ = QFileDialog.getSaveFileName(self, "Save part", self.path or "part.gpd", "Part (*.gpd)")
            if not p:
                return False
            self.path = p if p.endswith(".gpd") else p + ".gpd"
        import sim_links
        sim_links.rebase(self, old_base)
        open(self.path, "w", encoding="utf-8").write(self.doc.to_json())
        self.saved_json = self.doc.to_json()
        self.setWindowTitle(f"Parametric Modeller - {os.path.basename(self.path)}")
        also = sim_links.save_open(self)
        self.say(f"Saved {self.path}" + (f"  (and the simulation{'s' if len(also) > 1 else ''} {', '.join(also)})" if also else ""))
        return True

    # ------------------------------------------------------------------ commands (the toolbar)
    def command(self, key):
        d = self.doc
        if key in ("refplane", "refaxis"):
            self.rg_start(key)
            return
        if key == "sketch":
            plane = None
            cur = d.feature(self.sel) if self.sel else None
            if cur is not None and cur["kind"] == "refplane" and self.sel_face is None:
                self.make_sketch({"ref": cur["id"]})
                return
            if self.sel_face is not None:
                if self.sel_face.get("ref") is None:
                    self.say("That face is curved - a sketch needs a flat face.")
                    return
                plane = {"face": self.sel_face["ref"]}
            elif self.sel_plane:
                plane = {"base": self.sel_plane}
            else:
                m = QMenu(self)
                for nm in ("Front", "Top", "Right"):
                    m.addAction(nm, lambda n=nm: self.make_sketch({"base": n}))
                m.exec(self.cursor().pos())
                return
            self.make_sketch(plane)
        elif key in ("extrude", "cut"):
            sk = d.feature(self.sel) if self.sel else None
            if sk is None or sk["kind"] != "sketch":
                sks = [f for f in d.features if f["kind"] == "sketch"]
                sk = sks[-1] if sks else None
            if sk is None:
                self.say("Make a sketch first.")
                return
            self.snapshot()
            f = d.add(pm.new_feature(key, sketch=sk["id"], depth="10", end1="blind"))
            self.sel = f["id"]
            self.created_new = f["id"]
            self.update_all()
            self.left.setCurrentIndex(1)
        elif key in ("revolve", "revolve_cut"):
            sk = d.feature(self.sel) if self.sel else None
            if sk is None or sk["kind"] != "sketch":
                sks = [f for f in d.features if f["kind"] == "sketch"]
                sk = sks[-1] if sks else None
            if sk is None:
                self.say("Make a sketch first.")
                return
            self.snapshot()
            f = d.add(pm.new_feature(key, sketch=sk["id"], angle="360", axis="auto", merge=True))
            self.sel = f["id"]
            self.created_new = f["id"]
            self.update_all()
            self.left.setCurrentIndex(1)
            self.say("Spins about a centerline of the sketch if there is one, otherwise about the sketch's vertical axis.")
        elif key in ("pattern_linear", "pattern_circular", "mirror"):
            if d.solid is None:
                self.say("Make a solid first.")
                return
            srcs = [g["id"] for g in d.features if g["kind"] in ("extrude", "cut", "revolve", "revolve_cut")]
            pick = [self.sel] if self.sel in srcs else srcs[-1:]
            self.snapshot()
            if key == "mirror":
                f = d.add(pm.new_feature("mirror", features=pick, source="features", plane={"base": "Right"}))
            elif key == "pattern_linear":
                f = d.add(pm.new_feature("pattern", ptype="linear", features=pick, source="features", dir1="X", count="3", spacing="10"))
            else:
                f = d.add(pm.new_feature("pattern", ptype="circular", features=pick, source="features", axis="Z", count="4", angle="360"))
            self.sel = f["id"]
            self.created_new = f["id"]
            self.update_all()
            self.left.setCurrentIndex(1)
        elif key in ("fillet", "chamfer"):
            if d.solid is None:
                self.say("Make a solid first.")
                return
            self.snapshot()
            f = d.add(pm.new_feature(key, size="2", edges=list(self.sel_edges)))
            self.sel_edges = []
            self.sel = f["id"]
            self.created_new = f["id"]
            self.update_all()
            self.left.setCurrentIndex(1)
            self.say(("Edges from your selection are used. " if f["edges"] else "")
                     + "Click edges to add or remove them (Shift is not needed). Pick another item in the tree when done.")

    def make_sketch(self, plane):
        self.snapshot()
        f = self.doc.add(pm.new_feature("sketch", plane=plane))
        self.sel, self.sel_face, self.sel_plane = f["id"], None, None
        self.created_new = f["id"]
        self.update_all()
        self.enter_sketch(f["id"])

    # ------------------------------------------------------------------ the tree
    def tree_selected(self, item, _prev=None):
        if self.busy or item is None:
            return
        kind, key = item.data(0, Qt.ItemDataRole.UserRole) or (None, None)
        if kind == "equations":
            self.eq_dialog.show()
            self.eq_dialog.raise_()
            return
        if kind == "plane":
            self.sel, self.sel_plane, self.sel_face = None, key, None
        elif kind == "feature":
            if self.rg_edit and key != self.rg_edit:
                self.rg_edit = None
            self.sel, self.sel_plane = key, None
        else:
            return
        self.show_props()
        self.draw()

    def edit_material(self):
        import mat_lib
        dlg = mat_lib.MaterialDialog(self, self.doc.material)
        if dlg.exec() and dlg.result_material():
            self.snapshot()
            self.doc.material = dlg.result_material()
            self.refresh_tree()
            self.show_props()

    def tree_double(self, item, _col=0):
        kind, key = item.data(0, Qt.ItemDataRole.UserRole) or (None, None)
        if kind == "material":
            self.edit_material()
            return
        if kind == "sim":
            self.open_linked_sim(key)
            return
        if kind == "render":
            self.open_linked_sim(key, "renders")
            return
        if kind != "feature":
            return
        f = self.doc.feature(key)
        if f is not None and f["kind"] == "sketch":
            self.enter_sketch(key)
        elif part_refgeo.is_ref(f):
            self.left.setCurrentIndex(1)
            self.rg_begin(f)
        else:
            self.left.setCurrentIndex(1)

    def refresh_tree(self):
        d = self.doc
        self.busy = True
        self.tree.clear()
        root = QTreeWidgetItem(self.tree, ["⬢  Part1" + (f"   ({unitctl.volume_text(d.solid.volume, 5)})" if d.solid is not None else "")])
        root.setExpanded(True)
        QTreeWidgetItem(root, [f"▣  Solid Bodies({1 if d.solid is not None else 0})"])
        QTreeWidgetItem(root, ["∑  Equations" + (f"  ({len(d.params)})" if d.params else "")]).setData(0, Qt.ItemDataRole.UserRole, ("equations", None))
        mi = QTreeWidgetItem(root, [f"◈  Material <{self.doc.material['name']}>"])
        mi.setData(0, Qt.ItemDataRole.UserRole, ("material", None))
        mi.setToolTip(0, "Double-click (or right-click > Edit Material...) to change the material")
        for nm in ("Front", "Top", "Right"):
            it = QTreeWidgetItem(root, [f"▯  {nm} Plane"])
            it.setData(0, Qt.ItemDataRole.UserRole, ("plane", nm))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if self.plane_show.get(nm, True) else Qt.CheckState.Unchecked)
            if self.sel_plane == nm:
                self.tree.setCurrentItem(it)
        oi = QTreeWidgetItem(root, ["⊹  Origin"])
        oi.setData(0, Qt.ItemDataRole.UserRole, ("origin", None))
        oi.setFlags(oi.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        oi.setCheckState(0, Qt.CheckState.Checked if self.show_origin_item else Qt.CheckState.Unchecked)
        import sim_links
        L = sim_links.sims(self)
        if L:
            si = QTreeWidgetItem(root, [f"∿  Simulations ({len(L)})"])
            si.setData(0, Qt.ItemDataRole.UserRole, ("sims", None))
            for e in L:
                sit = QTreeWidgetItem(si, ["∿  " + sim_links.label(e) + ("   ✖ file not found" if sim_links.missing(self, e) else "")])
                sit.setData(0, Qt.ItemDataRole.UserRole, ("sim", e["path"]))
                sit.setToolTip(0, sim_links.abs_of(self, e) + "\nDouble-click to open")
                if sim_links.missing(self, e):
                    sit.setForeground(0, QBrush(QColor(200, 0, 0)))
        R = sim_links.renders(self)
        if R:
            ri = QTreeWidgetItem(root, [f"◉  Renders ({len(R)})"])
            ri.setData(0, Qt.ItemDataRole.UserRole, ("renders", None))
            for e in R:
                rit = QTreeWidgetItem(ri, ["◉  " + sim_links.label(e) + ("   ✖ file not found" if sim_links.missing(self, e) else "")])
                rit.setData(0, Qt.ItemDataRole.UserRole, ("render", e["path"]))
                rit.setToolTip(0, sim_links.abs_of(self, e) + "\nDouble-click to open")
                if sim_links.missing(self, e):
                    rit.setForeground(0, QBrush(QColor(200, 0, 0)))
        used = {f["sketch"] for f in d.features if f.get("sketch")}
        item_of = {}

        def add_feature(parent, f, i):
            st = d.status.get(f["id"], "")
            tag = {"ok": "", "suppressed": "  (suppressed)", "rolled back": "", "not built": "  (not built)"}.get(st, "  ✖")
            sk = f["kind"] == "sketch"
            under = ""
            if sk:
                under = "(-) "                       # an under-defined sketch: dimensions are only expressions here
            it = QTreeWidgetItem(parent, [f"{'' if sk else ICON[f['kind']] + '  '}{under}{f['name']}{tag}"])
            it.setData(0, Qt.ItemDataRole.UserRole, ("feature", f["id"]))
            if sk:
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if self.sketch_flag(f) else Qt.CheckState.Unchecked)
            elif part_refgeo.is_ref(f):
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if f.get("show", True) else Qt.CheckState.Unchecked)
            if st.startswith("error"):
                it.setForeground(0, QBrush(QColor(200, 0, 0)))
                it.setToolTip(0, st)
            elif st in ("not built", "suppressed", "rolled back"):
                it.setForeground(0, QBrush(QColor(150, 150, 150)))
            if f["id"] == self.sel:
                self.tree.setCurrentItem(it)
            item_of[f["id"]] = it
            return it

        for i, f in enumerate(d.features):
            if f["kind"] == "sketch" and f["id"] in used:
                continue                              # shown under the feature that uses it
            it = add_feature(root, f, i)
            if f.get("sketch"):
                sk = d.feature(f["sketch"])
                if sk is not None:
                    add_feature(it, sk, d.features.index(sk))
                    it.setExpanded(True)
        # rollback bar (the blue line): after the last built feature
        if d.rollback is not None:
            last = d.features[d.rollback]
            anchor = item_of.get(last["id"])
            bar = QTreeWidgetItem(root, ["━━━━━━━━━━━━━━━━━━━━━━"])
            bar.setForeground(0, QBrush(QColor(0, 110, 200)))
            bar.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if anchor is not None and anchor.parent() is root:
                root.takeChild(root.indexOfChild(bar))
                root.insertChild(root.indexOfChild(anchor) + 1, bar)
        else:
            bar = QTreeWidgetItem(root, ["━━━━━━━━━━━━━━━━━━━━━━"])
            bar.setForeground(0, QBrush(QColor(0, 110, 200)))
            bar.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.tree.expandAll()
        self.busy = False
        if getattr(self, "mini", None) is not None:
            self.mini.sync()

    def open_linked_sim(self, path_key, attr="sims"):
        import sim_links
        e = next((x for x in sim_links.links(self, attr) if x["path"] == path_key), None)
        if e is None:
            return
        if sim_links.open_sim(self, e) is None:
            self.say("That simulation file was not found: " + sim_links.abs_of(self, e))

    def unlink_sim(self, path_key, attr="sims"):
        import sim_links
        e = next((x for x in sim_links.links(self, attr) if x["path"] == path_key), None)
        if e is not None:
            self.snapshot()
            sim_links.remove(self, sim_links.abs_of(self, e), attr)
            self.refresh_tree()

    def tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None:
            return
        kind, key = it.data(0, Qt.ItemDataRole.UserRole) or (None, None)
        if kind == "render":
            m = QMenu(self)
            m.addAction("Open render", lambda: self.open_linked_sim(key, "renders"))
            m.addAction("Remove from this list (the file stays)", lambda: self.unlink_sim(key, "renders"))
            m.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if kind == "sim":
            m = QMenu(self)
            m.addAction("Open simulation", lambda: self.open_linked_sim(key))
            m.addAction("Remove from this list (the file stays)", lambda: self.unlink_sim(key))
            m.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if kind == "material":
            m = QMenu(self)
            m.addAction("Edit Material...", self.edit_material)
            m.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if kind != "feature":
            return
        f = self.doc.feature(key)
        m = QMenu(self)
        if part_refgeo.is_ref(f):
            m.addAction("Edit references", lambda: (self.left.setCurrentIndex(1), self.rg_begin(f)))
            m.addSeparator()
        m.addAction("Roll back to here", lambda: self.set_rollback(key))
        m.addAction("Roll forward (to the end)", lambda: self.set_rollback(None))
        m.addSeparator()
        m.addAction("Unsuppress" if f["suppressed"] else "Suppress", lambda: self.toggle_suppress(key))
        m.addAction("Delete", lambda: self.delete_feature(key))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def set_rollback(self, fid):
        self.snapshot()
        idx = None if fid is None else next(i for i, f in enumerate(self.doc.features) if f["id"] == fid)
        if idx == len(self.doc.features) - 1:
            idx = None
        self.doc.rollback = idx
        self.update_all()

    def toggle_suppress(self, fid):
        self.snapshot()
        f = self.doc.feature(fid)
        f["suppressed"] = not f["suppressed"]
        self.update_all()

    def delete_feature(self, fid):
        users = [g["name"] for g in self.doc.features if g.get("sketch") == fid]
        if users and QMessageBox.question(self, "Delete", f"{', '.join(users)} use this sketch and will fail. Delete anyway?") != QMessageBox.StandardButton.Yes:
            return
        self.snapshot()
        self.doc.remove(fid)
        if self.sel == fid:
            self.sel = None
        self.update_all()

    # ------------------------------------------------------------------ properties panel
    def clear_props(self):
        while self.props_lay.count():
            w = self.props_lay.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def expr_edit(self, form, label, feat, key, store=None, kind=None):
        """A box for a number / formula.  A length (label with '(mm)', or an Offset) is shown and read in the current unit
        (File > Units) and kept in mm; a count or an angle is shown as it is."""
        if kind is None:
            kind = "length" if ("(mm)" in label or key == "offset") else "number"
        tgt0 = feat if store is None else store
        shown = unitctl.expr_to_display(str(tgt0[key]), kind)
        e = QLineEdit(shown)
        e.setToolTip("A number or an expression using the Globals, e.g.  Width/2 + 3"
                     + ("\nA length is in " + unitctl.length_unit() + "; you can also type  3 in,  25 mm,  2 ft ..." if kind == "length" else ""))

        def done():
            tgt = feat if store is None else store
            if e.text() == shown:
                return                                         # nothing was typed: keep the stored value exactly
            new = unitctl.expr_from_display(e.text(), kind)
            if str(tgt[key]) != new:
                self.snapshot()
                tgt[key] = new
                self.update_all(keep_props=True)
        e.editingFinished.connect(done)
        form.addRow(unitctl.label(label) if kind == "length" else label, e)
        return e

    def combo(self, form, label, feat, key, options, default):
        cb = QComboBox()
        for val, text in options:
            cb.addItem(text, val)
        cur = feat.get(key) or default
        cb.setCurrentIndex(max(0, [v for v, _ in options].index(cur) if cur in [v for v, _ in options] else 0))

        def ch(_i):
            self.snapshot()
            feat[key] = cb.currentData()
            self.update_all()
        cb.currentIndexChanged.connect(ch)
        form.addRow(label, cb)
        return cb

    def extrude_panel(self, form, f):
        """Properties of Boss-Extrude / Cut-Extrude: contour, end conditions, second direction, draft, thin feature."""
        d = self.doc
        k = f["kind"]
        sks = [g for g in d.features if g["kind"] == "sketch"]
        cb = QComboBox()
        for g in sks:
            cb.addItem(g["name"], g["id"])
        ids = [g["id"] for g in sks]
        cb.setCurrentIndex(ids.index(f["sketch"]) if f["sketch"] in ids else 0)

        def ch(_i):
            self.snapshot()
            f["sketch"], f["pts"] = cb.currentData(), []
            self.update_all()
        cb.currentIndexChanged.connect(ch)
        form.addRow("Sketch", cb)
        sk_ = d.feature(f["sketch"])
        info = d.region_info(sk_) if sk_ is not None and sk_["id"] in d.models else []
        if len(info) > 1:
            form.addRow(QLabel("Contours  (tick the regions to use):"))
            chosen = f.get("pts") or []
            polys = d.region_polys(sk_)
            import pm_model
            for n, (area, pt) in enumerate(info):
                c = QCheckBox(f"Region {n + 1}   area {unitctl.area_text(area, 5)}")
                on = (not chosen) or any(pm_model._inside(p, polys[n][0], polys[n][1]) for p in chosen)
                c.setChecked(on)

                def tog(_v, n=n):
                    allpts = [list(i2[1]) for i2 in info]
                    cur = [list(q) for q in (f.get("pts") or allpts)]
                    has = [q for q in cur if pm_model._inside(q, polys[n][0], polys[n][1])]
                    cur = [q for q in cur if q not in has] if has else cur + [list(info[n][1])]
                    if not cur:
                        self.say("At least one contour must stay selected.")
                        self.show_props()
                        return
                    self.snapshot()
                    f["pts"] = cur
                    self.update_all()
                c.toggled.connect(tog)
                form.addRow(c)
        ends = [("blind", "Blind"), ("mid", "Mid Plane"), ("through", "Through All"), ("face", "Up To Face")]
        cur = d.end_condition(f, 1)
        e1 = self.combo(form, "End condition", f, "end1", ends, cur)
        del e1
        if cur in ("blind", "mid"):
            self.expr_edit(form, "Depth (mm)", f, "depth")
        if cur == "face" or (f.get("dir2") and d.end_condition(f, 2) == "face"):
            lab = QLabel("Face: " + ("chosen" if f.get("to_face") else "none yet - click a flat face in the view, then press the button"))
            form.addRow(lab)
            b = QPushButton("Use the selected face")

            def useface():
                if self.sel_face is None or self.sel_face.get("ref") is None:
                    self.say("Click a flat face of the part first.")
                    return
                self.snapshot()
                f["to_face"] = self.sel_face["ref"]
                self.update_all()
            b.clicked.connect(useface)
            form.addRow(b)
        self.check(form, "Reverse direction", f, "reverse")
        if cur != "mid":
            self.check(form, "Direction 2", f, "dir2")
            if f.get("dir2"):
                self.combo(form, "  End condition 2", f, "end2", [x for x in ends if x[0] != "mid"], d.end_condition(f, 2))
                if d.end_condition(f, 2) == "blind":
                    f.setdefault("depth2", "10")
                    self.expr_edit(form, "  Depth 2 (mm)", f, "depth2")
        self.check(form, "Draft", f, "draft_on")
        if f.get("draft_on"):
            f.setdefault("draft", "3")
            self.expr_edit(form, "  Angle (deg)", f, "draft")
            self.check(form, "  Draft outward", f, "draft_out")
        self.check(form, "Thin feature", f, "thin")
        if f.get("thin"):
            f.setdefault("thickness", "2")
            self.expr_edit(form, "  Wall (mm)", f, "thickness")
            self.combo(form, "  Wall on", f, "thin_side", [("inside", "Inside the outline"), ("outside", "Outside the outline"),
                                                           ("mid", "Both sides")], "inside")
        if k == "extrude":
            f.setdefault("merge", True)
            self.check(form, "Merge result", f, "merge")
        else:
            self.check(form, "Flip side to cut (keep what is inside)", f, "flip_side")

    def revolve_panel(self, form, f):
        d = self.doc
        sks = [g for g in d.features if g["kind"] == "sketch"]
        cb = QComboBox()
        for g in sks:
            cb.addItem(g["name"], g["id"])
        ids = [g["id"] for g in sks]
        cb.setCurrentIndex(ids.index(f["sketch"]) if f["sketch"] in ids else 0)

        def ch(_i):
            self.snapshot()
            f["sketch"], f["pts"], f["axis"] = cb.currentData(), [], "auto"
            self.update_all()
        cb.currentIndexChanged.connect(ch)
        form.addRow("Sketch", cb)
        sk_ = d.feature(f["sketch"])
        m = d.models.get(sk_["id"]) if sk_ is not None else None
        opts = [("auto", "Centerline (or vertical axis)"), ("sy", "Sketch vertical axis"), ("sx", "Sketch horizontal axis")]
        cur = f.get("axis", "auto")
        if m is not None:
            for lid in m.lns:
                opts.append((f"ln{lid}", f"Line {lid}"))
        if isinstance(cur, dict):
            cur = f"ln{cur['ln']}"
        cbx = QComboBox()
        for v, t in opts:
            cbx.addItem(t, v)
        vals = [v for v, _ in opts]
        cbx.setCurrentIndex(vals.index(cur) if cur in vals else 0)

        def cha(_i):
            self.snapshot()
            v = cbx.currentData()
            f["axis"] = {"ln": int(v[2:])} if v.startswith("ln") else v
            self.update_all()
        cbx.currentIndexChanged.connect(cha)
        form.addRow("Axis", cbx)
        self.expr_edit(form, "Angle (deg)", f, "angle")
        self.check(form, "Reverse direction", f, "reverse")
        if f["kind"] == "revolve":
            f.setdefault("merge", True)
            self.check(form, "Merge result", f, "merge")

    def repeat_panel(self, form, f):
        """Properties of Linear / Circular Pattern and Mirror."""
        d = self.doc
        k = f["kind"]
        self.combo(form, "Repeat", f, "source", [("features", "Chosen features"), ("body", "The whole body")], "features")
        if f.get("source", "features") == "features":
            form.addRow(QLabel("Features (tick to repeat):"))
            for g in d.features:
                if g["kind"] not in ("extrude", "cut", "revolve", "revolve_cut"):
                    continue
                if d.features.index(g) >= d.features.index(f):
                    break
                c = QCheckBox(g["name"])
                c.setChecked(g["id"] in f.get("features", []))

                def tog(v, gid=g["id"]):
                    self.snapshot()
                    cur = [x for x in f.get("features", []) if x != gid]
                    f["features"] = cur + [gid] if v else cur
                    self.update_all()
                c.toggled.connect(tog)
                form.addRow(c)
        if k == "mirror":
            pl = f.get("plane") or {"base": "Right"}
            cbp = QComboBox()
            opts = [("Front", "Front plane"), ("Top", "Top plane"), ("Right", "Right plane"), ("face", "A flat face")]
            opts += [("ref:" + g["id"], g["name"]) for g in d.features if g["kind"] == "refplane" and d.features.index(g) < d.features.index(f)]
            for v, t in opts:
                cbp.addItem(t, v)
            cur = pl.get("base", "ref:" + pl["ref"] if "ref" in pl else "face")
            cbp.setCurrentIndex(max(0, [o[0] for o in opts].index(cur) if cur in [o[0] for o in opts] else 0))

            def chp(_i):
                v = cbp.currentData()
                if v == "face":
                    if self.sel_face is None or self.sel_face.get("ref") is None:
                        self.say("Click a flat face of the part first, then choose this.")
                        self.show_props()
                        return
                    newp = {"face": self.sel_face["ref"]}
                elif v.startswith("ref:"):
                    newp = {"ref": v[4:]}
                else:
                    newp = {"base": v}
                self.snapshot()
                f["plane"] = newp
                self.update_all()
            cbp.currentIndexChanged.connect(chp)
            form.addRow("Mirror about", cbp)
            return
        axes = [("X", "X"), ("Y", "Y"), ("Z", "Z"), ("edge", "Selected edge")]
        for kk, vv in (("count2", "2"), ("spacing2", "10"), ("dir2", "Y"), ("angle", "360")):
            f.setdefault(kk, vv)
        if f.get("ptype") == "linear":
            self.combo(form, "Direction", f, "dir1", axes, "X")
            self.expr_edit(form, "Copies", f, "count")
            self.expr_edit(form, "Spacing (mm)", f, "spacing")
            self.check(form, "Reverse direction", f, "reverse")
            self.check(form, "Second direction", f, "dir2_on")
            if f.get("dir2_on"):
                self.combo(form, "  Direction 2", f, "dir2", axes[:3], "Y")
                self.expr_edit(form, "  Copies 2", f, "count2")
                self.expr_edit(form, "  Spacing 2 (mm)", f, "spacing2")
        else:
            self.combo(form, "Axis", f, "axis", axes, "Z")
            self.expr_edit(form, "Copies", f, "count")
            self.expr_edit(form, "Angle (deg)", f, "angle")
            self.check(form, "Reverse direction", f, "reverse")
        if "edge" in (f.get("dir1"), f.get("axis")):
            form.addRow(QLabel("Edge: " + ("chosen" if f.get("edge1") else "none yet - click an edge in the view, then press the button")))
            b = QPushButton("Use the selected edge")

            def usee():
                if not self.sel_edges:
                    self.say("Click an edge of the part first.")
                    return
                self.snapshot()
                f["edge1"] = self.sel_edges[0]
                self.update_all()
            b.clicked.connect(usee)
            form.addRow(b)

    def check(self, form, label, feat, key):
        c = QCheckBox()
        c.setChecked(bool(feat.get(key)))

        def tog(v):
            self.snapshot()
            feat[key] = bool(v)
            self.update_all()
        c.toggled.connect(tog)
        form.addRow(label, c)

    def show_props(self):
        self.clear_props()
        d = self.doc
        f = d.feature(self.sel) if self.sel else None
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)
        self.props_lay.addWidget(box)
        if f is None:
            self.props_title.setText("Properties")
            msg = "Plane " + self.sel_plane + "  -  press Sketch." if self.sel_plane else (
                "Face selected  -  press Sketch to draw on it." if self.sel_face else (
                    f"{len(self.sel_edges)} edge(s) selected  -  press Fillet or Chamfer." if self.sel_edges else "Nothing selected."))
            form.addRow(QLabel(msg))
            return
        self.props_title.setText(f"{f['name']}  ({f['kind']})")
        st = d.status.get(f["id"], "")
        if st.startswith("error"):
            lab = QLabel(st)
            lab.setStyleSheet("color:#c00000;")
            lab.setWordWrap(True)
            form.addRow(lab)
        k = f["kind"]
        if k == "sketch":
            pl = f["plane"]
            form.addRow("On", QLabel(pl["base"] + " plane" if "base" in pl else (d.feature(pl["ref"]) or {"name": "a deleted plane"})["name"] if "ref" in pl else "a face"))
            if "base" in pl:
                self.expr_edit(form, "Offset", pl, "offset") if "offset" in pl else None
            self.sketch_table(f)
        elif k in ("extrude", "cut"):
            self.extrude_panel(form, f)
        elif k in ("revolve", "revolve_cut"):
            self.revolve_panel(form, f)
        elif k in ("pattern", "mirror"):
            self.repeat_panel(form, f)
        elif part_refgeo.is_ref(f):
            self.ref_panel(form, f)
        else:
            self.expr_edit(form, "Radius (mm)" if k == "fillet" else "Distance (mm)", f, "size")
            form.addRow("Edges", QLabel(f"{len(f['edges'])} selected  (click edges in the view)"))
            b = QPushButton("Clear edges")

            def clr():
                self.snapshot()
                f["edges"] = []
                self.update_all(keep_props=True)
            b.clicked.connect(clr)
            form.addRow(b)

    def sketch_table(self, sk):
        """Properties of a sketch: how well it is defined, its dimensions (editable) and its relations (deletable)."""
        d = self.doc
        m, rep = d.models.get(sk["id"]), d.reports.get(sk["id"])
        if m is None:
            return
        lab = QLabel(("CONFLICT: some relations fight each other (shown red)." if rep.conflicts else
                      "Fully defined." if rep.dof == 0 else f"Under defined: {rep.dof} degrees of freedom left.") if rep else "")
        lab.setStyleSheet("font-weight:bold; color:" + ("#c00000" if rep and rep.conflicts else "#1a7f1a" if rep and rep.dof == 0 else "#1f4fb4"))
        self.props_lay.addWidget(lab)
        dims = [c for c in m.cons if c["type"] in sketch_edit.DIMS]
        t = QTableWidget(len(dims), 2)
        t.setHorizontalHeaderLabels(["Dimension", "Value / equation"])
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.setMaximumHeight(170)
        for r, c in enumerate(dims):
            n = QTableWidgetItem(str(c.get("name", c["type"])))
            n.setToolTip(c["type"] + "  -  double-click to rename; the name can be used in formulas and is listed in Configurations")
            t.setItem(r, 0, n)
            ang = c["type"] == "dim_ang"
            if c.get("expr"):
                shown = unitctl.expr_to_display(str(c["expr"]), "number" if ang else "length")
            else:
                shown = f"{(c['value'] if ang else unitctl.to_disp(c['value'])):.6g}"
            t.setItem(r, 1, QTableWidgetItem(shown))
        t.horizontalHeaderItem(1).setText("Value / equation" + ("" if unitctl.is_mm() else f" ({unitctl.length_unit()})"))
        ids = [c["id"] for c in dims]
        shown_txt = {(r, 1): t.item(r, 1).text() for r in range(len(dims))}

        def edited(item):
            r = item.row()
            if item.column() == 1 and item.text() != shown_txt.get((r, 1)):
                self.set_sketch_dimension(sk["id"], ids[r], item.text())
            elif item.column() == 0 and item.text() != str(dims[r].get("name", dims[r]["type"])):
                self.snapshot()
                try:
                    self.doc.rename_dimension(sk["id"], ids[r], item.text())
                except pm.ModelError as ex:
                    self.undo_pop()
                    self.say(f"Not renamed: {ex}")
                    self.show_props()
                    return
                self.doc.models.pop(sk["id"], None)
                self.update_all()
        t.itemChanged.connect(edited)
        self.props_lay.addWidget(t)
        rels = [c for c in m.cons if c["type"] not in sketch_edit.DIMS]
        self.props_lay.addWidget(QLabel(f"Relations ({len(rels)}):"))
        from PyQt6.QtWidgets import QListWidget
        lw = QListWidget()
        lw.setMaximumHeight(150)
        for c in rels:
            lw.addItem(f"{c['type']}{'  (auto)' if c.get('auto') else ''}   {' '.join(k + str(i) for k, i in c['refs'])}")
        self.props_lay.addWidget(lw)
        b = QPushButton("Delete selected relation")

        def dele():
            r = lw.currentRow()
            if 0 <= r < len(rels):
                self.snapshot()
                m.delete([("con", rels[r]["id"])])
                self.finish_sketch_edit(sk["id"])
        b.clicked.connect(dele)
        self.props_lay.addWidget(b)

    def set_sketch_dimension(self, sid, cid, txt):
        m = self.doc.models.get(sid)
        c = m.con_by_id(cid) if m else None
        if not c:
            return
        self.snapshot()
        try:
            expr, val = sketch_edit.SketchEditor.dim_from_text(m, txt, c["value"], c["type"])
        except ValueError as ex:
            self.undo_pop()
            self.say(str(ex))
            return
        c["value"] = val
        if expr:
            c["expr"] = expr
            if expr.isidentifier():
                c["name"] = expr
        else:
            c.pop("expr", None)
        self.finish_sketch_edit(sid)

    def finish_sketch_edit(self, sid):
        import sk_tools
        self.doc.reports[sid] = sk_tools.solve_model(self.doc.models[sid])
        self.doc.store_sketch(sid)
        self.update_all()

    # ----- what the Configurations and Display tabs ask of the window
    def cfg_model(self):
        return self.doc

    def cfg_choices(self, key):
        return None

    def cfg_candidates(self):
        return self.doc.cfg_candidates()

    def config_changed(self):
        self.update_all(keep_props=True)

    def display_items(self):
        return [(self.title().rsplit(".", 1)[0], self.doc.display, None, PART)]

    def display_changed(self):
        self.draw()
        self.disp_panel.refresh()

    def display_live(self):
        a = self.actor_part
        if a is not None:
            try:
                a.prop.opacity = float(self.doc.display.get("opacity", 1.0))
                self.plotter.render()
            except Exception:
                pass

    def units_changed(self, *_a):
        """File > Units was changed: everything that shows a length is redrawn in the new unit (nothing stored changes)."""
        self.measure_unit = unitctl.length_unit()
        if self.mass_dialog is not None:
            self.mass_dialog.units_changed()
        if self.measure_panel is not None:
            self.measure_panel.units_changed()
        self.refresh_tree()
        self.refresh_globals()
        try:
            self.cfg_panel.refresh()
        except Exception:
            pass
        self.show_props()
        if self.ed is not None and self.ed.active:
            self.ed.redraw()
        if self.doc.solid is not None:
            self.say(f"Units: {unitctl.length_unit()}  -  volume {unitctl.volume_text(self.doc.solid.volume, 5)}")

    def refresh_globals(self):
        """The Globals table.  A 'length' global is shown in the current unit (File > Units) although it is kept in mm; a 'number'
        (a count, a ratio) or an 'angle' is shown as it is."""
        self.busy = True
        t = self.gtab
        t.setRowCount(len(self.doc.params))
        t.setHorizontalHeaderLabels(["Name", f"Equation ({unitctl.length_unit()})", "Value", "Type"])
        for r, (k, e) in enumerate(self.doc.params.items()):
            kind = self.doc.param_kinds.get(k, "length")
            t.setItem(r, 0, QTableWidgetItem(k))
            t.setItem(r, 1, QTableWidgetItem(unitctl.expr_to_display(str(e), kind)))
            val = self.doc.values.get(k)
            if val is not None and kind == "length":
                val = unitctl.to_disp(val)
            v = QTableWidgetItem(f"{val:.6g}" if val is not None else "?")
            v.setFlags(Qt.ItemFlag.ItemIsEnabled)
            t.setItem(r, 2, v)
            cb = QComboBox()
            cb.addItems(["length", "number", "angle"])
            cb.setCurrentText(kind)
            cb.setToolTip("length: shown in the program's unit (File > Units).  number / angle: never converted (a count, a ratio, degrees)")
            cb.currentTextChanged.connect(lambda txt, k=k: self.global_kind(k, txt))
            t.setCellWidget(r, 3, cb)
        self.busy = False

    def global_kind(self, name, kind):
        """The Type of a global was changed: its number is kept (in mm / as it is) and only its meaning changes."""
        if self.busy:
            return
        self.snapshot()
        if kind == "length":
            self.doc.param_kinds.pop(name, None)
        else:
            self.doc.param_kinds[name] = kind
        self.update_all(keep_props=True)

    def global_edited(self, _item):
        if self.busy:
            return
        self.snapshot()
        new, old = {}, self.doc.params
        shown = {}
        for r in range(self.gtab.rowCount()):
            k = (self.gtab.item(r, 0).text() if self.gtab.item(r, 0) else "").strip()
            e = (self.gtab.item(r, 1).text() if self.gtab.item(r, 1) else "").strip()
            if k and k.isidentifier():
                kind = self.doc.param_kinds.get(k, "length")
                if k in old and e == unitctl.expr_to_display(str(old[k]), kind):
                    new[k] = old[k]                                # not edited: keep the stored text exactly
                else:
                    new[k] = unitctl.expr_from_display(e, kind) if e else "0"
        self.doc.param_kinds = {k: v for k, v in self.doc.param_kinds.items() if k in new}
        self.doc.params = new
        self.update_all(keep_props=True)

    def global_add(self):
        self.snapshot()
        n = 1
        while f"P{n}" in self.doc.params:
            n += 1
        self.doc.params[f"P{n}"] = unitctl.expr_from_display("10")        # 10 in the current unit, kept in mm
        self.update_all(keep_props=True)

    def global_del(self):
        r = self.gtab.currentRow()
        if r >= 0 and self.gtab.item(r, 0):
            self.snapshot()
            self.doc.params.pop(self.gtab.item(r, 0).text(), None)
            self.update_all(keep_props=True)

    # ------------------------------------------------------------------ rebuild + draw
    def update_all(self, fit=False, keep_props=False):
        self.doc.rebuild()
        if self.ed is not None and self.ed.active and (self.doc.feature(self.ed.sk_id) is None or self.ed.sk_id not in self.doc.planes):
            self.ed.end()
            self.mode_label.setText("Editing Part")
            self.ribbon.setCurrentIndex(0)
        errs = [f"{f['name']}: {s[7:]}" for f in self.doc.features for s in [self.doc.status.get(f["id"], "")] if s.startswith("error")]
        self.refresh_tree()
        self.refresh_globals()
        self.cfg_panel.refresh()
        self.disp_panel.refresh()
        if not keep_props:
            self.show_props()
        self.draw(fit)
        if errs:
            self.say("Rebuild error - " + errs[0])
        elif self.doc.solid is not None:
            self.say(f"Rebuilt: {len([f for f in self.doc.features if self.doc.status.get(f['id']) == 'ok'])} features, "
                     f"volume {unitctl.volume_text(self.doc.solid.volume, 5)}")

    def shown_solid(self):
        """The solid drawn in the view: the part (while a fillet / chamfer is selected it shows the rounded result, as a preview)."""
        return self.doc.solid

    def pick_solid(self):
        """The solid whose edges can be picked: the part, or - while a fillet / chamfer is selected - the part before it."""
        d = self.doc
        f = d.feature(self.sel) if self.sel else None
        if f is not None and f["kind"] in ("fillet", "chamfer") and d.status.get(f["id"]) == "ok":
            i = d.features.index(f)
            return d.after.get(d.features[i - 1]["id"]) if i > 0 else None
        return d.solid

    # ------------------------------------------------------------------ what is shown
    def sketch_flag(self, f):
        """The sketch's own checkbox in the tree (a sketch no feature uses is on by default, one a feature uses is off)."""
        if f.get("show") is not None:
            return bool(f["show"])
        return not any(g.get("sketch") == f["id"] for g in self.doc.features)

    def sketch_shown(self, f):
        """Is the sketch drawn?  Show > Sketches off hides all of them; with it on, each sketch's checkbox in the tree decides.
        Selecting a sketch does not show it.  Only the sketch that is open for editing is always drawn (by the sketch editor)."""
        if self.ed is not None and self.ed.active and self.ed.sk_id == f["id"]:
            return True
        return bool(self.vis["sketches"]) and self.sketch_flag(f)

    def set_show(self, key, on):
        self.vis[key] = bool(on)
        QSettings("GenParametricDesigner", "Modeller").setValue("show_" + key, "1" if on else "0")
        self.refresh_tree()
        self.draw()

    def tree_check(self, item, _col=0):
        """The checkbox of a sketch / plane / origin in the tree."""
        if self.busy:
            return
        kind, key = item.data(0, Qt.ItemDataRole.UserRole) or (None, None)
        on = item.checkState(0) == Qt.CheckState.Checked
        if kind == "plane":
            self.plane_show[key] = on
        elif kind == "origin":
            self.show_origin_item = on
        elif kind == "feature":
            f = self.doc.feature(key)
            if f is not None and (f["kind"] == "sketch" or part_refgeo.is_ref(f)):
                f["show"] = on
        self.draw()

    @staticmethod
    def merged_lines(polys):
        """Many polylines -> one PolyData (one actor draws them all: much faster than one actor each)."""
        polys = [p for p in polys if len(p) >= 2]
        if not polys:
            return None
        pts = np.vstack(polys)
        cells, off = [], 0
        for p in polys:
            cells += [len(p)] + list(range(off, off + len(p)))
            off += len(p)
        pd = pv.PolyData()
        pd.points = pts
        pd.lines = np.array(cells)
        return pd

    def edge_pts(self, ref, solid, n=24):
        e = self.doc.resolve_edge(ref, solid)
        return np.array([tuple(e.position_at(j / (n - 1))) for j in range(n)])

    def draw(self, fit=False):
        pl = self.plotter
        if pl is None:
            return
        try:
            self.cam = None if fit else pl.camera_position
        except Exception:
            self.cam = None
        pl.clear()
        pl.add_axes()
        d = self.doc
        solid = self.shown_solid()
        pick = self.pick_solid()
        self.actor_part, self.view_cells, self.edge_polys = None, None, []
        if solid is not None:
            verts, cells, face_id, off = [], [], [], 0
            for i, v, t in d.mesh(solid):
                verts.append(v)
                cells.append(np.hstack([np.full((len(t), 1), 3), t + off]).ravel())
                face_id += [i] * len(t)
                off += len(v)
            if verts:
                m = pv.PolyData(np.vstack(verts), np.concatenate(cells))
                m.cell_data["face"] = np.array(face_id)
                self.view_cells = m
                self.actor_part = pl.add_mesh(m, color=d.display.get("color") or PART, opacity=float(d.display.get("opacity", 1.0)),
                                              smooth_shading=False, pickable=True, show_edges=False, reset_camera=False,
                                              ambient=0.28, diffuse=0.78, specular=0.30, specular_power=22)
                if self.measuring:
                    for it in self.meas_items:
                        if it["kind"] == "face":
                            cs = np.where(np.array(face_id) == it["idx"])[0]
                            if len(cs):
                                pl.add_mesh(m.extract_cells(cs), color=FACE_SEL, lighting=False, pickable=False, reset_camera=False)
                if self.sel_face is not None and solid is d.solid:
                    cs = np.where(np.array(face_id) == self.sel_face["index"])[0]
                    if len(cs):
                        pl.add_mesh(m.extract_cells(cs), color=FACE_SEL, lighting=False, pickable=False, reset_camera=False)
        if pick is not None:
            self.edge_polys = d.edge_lines(pick)
            if self.vis["edges"]:
                ml = self.merged_lines(self.edge_polys)
                if ml is not None:
                    pl.add_mesh(ml, color=(0.13, 0.15, 0.20) if pick is solid else (0.45, 0.50, 0.60), line_width=2.0 if pick is solid else 1.2,
                                pickable=False, reset_camera=False)
            f = d.feature(self.sel) if self.sel else None
            hot = list(self.sel_edges) + (list(f["edges"]) if f is not None and f["kind"] in ("fillet", "chamfer") else [])
            polys = []
            for ref in hot:
                try:
                    polys.append(self.edge_pts(ref, pick))
                except Exception:
                    pass
            ml = self.merged_lines(polys)
            if ml is not None:
                pl.add_mesh(ml, color=EDGE_SEL, line_width=5, pickable=False, reset_camera=False)
        if self.measuring:
            if self.meas_sig is not solid:
                self.meas_sig, self.meas_items, self.meas_segs = solid, [], []
            mp = [self.edge_polys[it["idx"]] for it in self.meas_items if it["kind"] == "edge" and it["idx"] < len(self.edge_polys)]
            ml = self.merged_lines(mp)
            if ml is not None:
                pl.add_mesh(ml, color=EDGE_SEL, line_width=5, pickable=False, reset_camera=False)
            vp = [tuple(it["shape"].center()) for it in self.meas_items if it["kind"] == "vertex"]
            vp += [p for sg in self.meas_segs for p in (tuple(sg[0]), tuple(sg[1]))]
            if vp:
                pl.add_mesh(pv.PolyData(np.array(vp)), color=EDGE_SEL, point_size=11, render_points_as_spheres=True, pickable=False, reset_camera=False)
            ml = self.merged_lines([np.array(sg) for sg in self.meas_segs])
            if ml is not None:
                pl.add_mesh(ml, color=(0.95, 0.45, 0.05), line_width=3, pickable=False, reset_camera=False)
        # sketches (up to the rollback bar): the visible ones, the selected one thicker
        normal, chosen = [], []
        for f in d.features:
            if f["kind"] == "sketch" and d.status.get(f["id"]) == "ok" and not (self.ed is not None and self.ed.active and self.ed.sk_id == f["id"]):
                if self.sketch_shown(f):
                    (chosen if f["id"] == self.sel else normal).extend(d.sketch_lines(f))
        for polys, col, w in ((normal, SKETCH_COL, 2.2), (chosen, SKETCH_SEL, 3.5)):
            ml = self.merged_lines(polys)
            if ml is not None:
                pl.add_mesh(ml, color=col, line_width=w, pickable=False, reset_camera=False)
        # origin planes (small, translucent; click to select) and the origin
        size = 30.0
        if solid is not None:
            b = solid.bounding_box()
            size = 0.75 * max(b.size.X, b.size.Y, b.size.Z, 10.0)
        self.actor_planes = {}
        if self.vis["planes"]:
            for nm, plane in pm.BASE_PLANES.items():
                if not self.plane_show.get(nm, True) and self.sel_plane != nm:
                    continue
                sq = pv.Plane(center=(0, 0, 0), direction=tuple(plane.z_dir), i_size=size, j_size=size)
                sel = self.sel_plane == nm
                a_ = pl.add_mesh(sq, color=PLANE_COL[nm], opacity=0.45 if sel else 0.12, pickable=True, lighting=False, reset_camera=False)
                self.actor_planes[nm] = a_
        self.draw_refgeo(pl, pv, solid, size)
        if self.vis["origin"] and self.show_origin_item:
            L = 0.45 * size
            for vec, col in (((L, 0, 0), (0.85, 0.2, 0.2)), ((0, L, 0), (0.2, 0.7, 0.2)), ((0, 0, L), (0.2, 0.35, 0.9))):
                pl.add_mesh(pv.Line((0, 0, 0), vec), color=col, line_width=2.5, pickable=False, reset_camera=False)
            pl.add_mesh(pv.PolyData(np.array([[0.0, 0.0, 0.0]])), color=(0.8, 0.15, 0.55), point_size=9, render_points_as_spheres=True,
                        pickable=False, reset_camera=False)
        if self.cam is not None:
            pl.camera_position = self.cam
        else:
            pl.camera_position = "iso"
            pl.reset_camera()
        if self.ed is not None and self.ed.active:
            self.ed.redraw()
        else:
            pl.render()

    # ------------------------------------------------------------------ clicks in the view
    # ------------------------------------------------------------------ evaluate: mass properties and measure
    def mass_open(self):
        if self.doc.solid is None:
            self.say("Make a solid first.")
            return
        if self.mass_dialog is not None:
            self.mass_dialog.close()
        self.mass_dialog = evaluate.MassDialog(self)
        self.mass_dialog.show()

    def measure_toggle(self):
        if self.measuring:
            self.measure_stop()
            return
        if self.ed is not None and self.ed.active:
            self.say("Leave the sketch first.")
            return
        self.measuring = True
        if "measure" in self.act:
            self.act["measure"].setCheckable(True)
            self.act["measure"].setChecked(True)
        self.sel_edges, self.sel_face, self.sel_plane = [], None, None
        if self.measure_panel is None:
            self.measure_panel = evaluate.MeasurePanel(self)
        self.measure_panel.show()
        self.measure_clear()
        self.say("Measure: click points, edges or faces in the view (two items give a distance).")

    def measure_stop(self):
        self.measuring = False
        if "measure" in self.act:
            self.act["measure"].setChecked(False)
        if self.measure_panel is not None:
            self.measure_panel.hide()
        self.meas_items, self.meas_segs = [], []
        self.draw()

    def measure_clear(self):
        self.meas_items, self.meas_segs = [], []
        self.measure_update()

    def measure_update(self):
        if self.measure_panel is None:
            return
        text, self.meas_segs = evaluate.measure_report(self.meas_items, self.measure_panel.options(), unitctl.length_unit())
        self.measure_panel.out.setPlainText(text)
        self.draw()

    def measure_pick(self, x, y):
        solid = self.shown_solid()
        if solid is None or self.ed is None:
            return
        ed = self.ed
        wpp = viewpick.world_per_pixel(self.plotter)
        item = None
        verts = solid.vertices()
        if verts:
            pts = np.array([tuple(v.center()) for v in verts])
            scr = np.array(ed.to_screen(pts))
            dd = np.hypot(scr[:, 0] - x, scr[:, 1] - y)
            for i in np.argsort(dd)[:3]:
                if dd[i] > 9.0 * self.plotter.devicePixelRatioF():
                    break
                hit = viewpick.pick_actor(self.plotter, scr[i][0], scr[i][1], self.actor_part) if self.actor_part is not None else None
                if hit is None or np.linalg.norm(np.array(hit) - pts[i]) <= max(0.5, 6.0 * wpp):
                    item = {"kind": "vertex", "idx": int(i), "shape": verts[i]}
                    break
        if item is None:
            ei = self.pick_edge(x, y)
            ps = self.pick_solid()
            if ei is not None and ps is not None:
                item = {"kind": "edge", "idx": int(ei), "shape": ps.edges()[ei]}
        if item is None:
            r = viewpick.pick_surface(self.plotter, x, y)
            if r is not None and self.actor_part is not None and viewpick.same_actor(self.actor_part, r[1]):
                idx = int(self.view_cells.cell_data["face"][r[2]])
                item = {"kind": "face", "idx": idx, "shape": solid.faces()[idx]}
        if item is None:
            return
        same = [it for it in self.meas_items if it["kind"] == item["kind"] and it["idx"] == item["idx"]]
        if same:
            self.meas_items = [it for it in self.meas_items if it not in same]
        elif len(self.meas_items) >= 2:
            self.meas_items = [item]
        else:
            self.meas_items.append(item)
        self.measure_update()

    def on_click(self, x, y):
        if self.ed is not None and self.ed.active:
            return
        if self.measuring:
            try:
                self.measure_pick(x, y)
            except Exception:
                self.say("Measure failed: " + traceback.format_exc(limit=2))
            return
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        try:
            self.pick_model(x, y, shift)
        except Exception:
            self.say("Click failed: " + traceback.format_exc(limit=2))

    def context_menu(self, x, y, gpos):
        """Right click in the view."""
        menu = QMenu(self)
        if self.ed is not None and self.ed.active:
            acts = self.ed.context_actions(x, y)
        else:
            ei = self.pick_edge(x, y)
            if ei is not None and not self.sel_edges:
                self.pick_model(x, y)
            acts = []
            if self.sel_edges:
                acts += [("Fillet", lambda: self.command("fillet")), ("Chamfer", lambda: self.command("chamfer"))]
            if self.sel_face is not None:
                acts += [("Sketch on this face", lambda: self.command("sketch"))]
            if not acts:
                acts = [("Sketch", lambda: self.command("sketch")), ("Fillet", lambda: self.command("fillet"))]
        for label, fn in acts:
            menu.addAction(label).triggered.connect(lambda _c=False, f=fn: f())
        menu.exec(gpos)

    def pick_edge(self, x, y):
        """Index of the edge (in the shown solid) closest to the pixel and not hidden behind the part, or None."""
        solid = self.pick_solid()
        if solid is None or not self.edge_polys or self.ed is None:
            return None
        ed = self.ed
        tol = 8.0 * self.plotter.devicePixelRatioF()
        cands = []
        for i, pts in enumerate(self.edge_polys):
            try:
                dist, j, t = ed.seg_dist(ed.to_screen(pts), x, y)
            except Exception:
                continue
            if dist <= tol:
                cands.append((dist, i, pts[j] + (pts[j + 1] - pts[j]) * t))
        cands.sort(key=lambda c: c[0])
        wpp = viewpick.world_per_pixel(self.plotter)
        for dist, i, q in cands[:5]:
            if self.actor_part is None or self.pick_solid() is not self.shown_solid():
                return i
            sx, sy = ed.to_screen(q)[0]
            hit = viewpick.pick_actor(self.plotter, sx, sy, self.actor_part)
            if hit is None or np.linalg.norm(np.array(hit) - q) <= max(0.5, 6.0 * wpp):
                return i
        return None

    def pick_model(self, x, y, shift=False):
        """A click on the part: an edge when the cursor is close to one, else the face (or a plane).  Works in a sketch too."""
        pl = self.plotter
        sketching = self.ed is not None and self.ed.active
        if not sketching and self.rg_feature() is not None:
            self.rg_pick(x, y)
            return
        f = self.doc.feature(self.sel) if self.sel else None
        solid = self.shown_solid()
        ei = self.pick_edge(x, y)
        if ei is not None and self.pick_solid() is not None:
            ref = self.doc.edge_ref(self.pick_solid().edges()[ei])
            if f is not None and f["kind"] in ("fillet", "chamfer") and not sketching:
                keep = [q for q in f["edges"] if not self.same_edge(q, ref)]
                self.snapshot()
                f["edges"] = keep if len(keep) < len(f["edges"]) else keep + [ref]
                self.update_all(keep_props=True)
                return
            keep = [q for q in self.sel_edges if not self.same_edge(q, ref)]
            if len(keep) < len(self.sel_edges):
                self.sel_edges = keep                      # clicking a selected edge again removes it
            elif shift or (f is not None and f["kind"] in ("fillet", "chamfer")):
                self.sel_edges = self.sel_edges + [ref]
            else:
                self.sel_edges = [ref]
            self.sel_face, self.sel_plane = None, None
            if not sketching:
                self.sel = None
                self.refresh_tree()
                self.show_props()
            self.draw()
            n = len(self.sel_edges)
            self.say(f"{n} edge(s) selected" + ("  -  press Convert Entities to copy them into the sketch." if sketching
                                                  else "  -  press Fillet or Chamfer (Shift-click adds more edges)."))
            return
        r = viewpick.pick_surface(pl, x, y)
        if r is None:
            if not shift:
                self.sel_face = self.sel_plane = None
                self.sel_edges = []
            if not sketching:
                self.show_props()
            self.draw()
            return
        pos, actor, cid = r
        if not sketching and self.select_ref_from_view(actor):
            return
        if not sketching:
            for nm, a in self.actor_planes.items():
                if viewpick.same_actor(a, actor) and not (self.actor_part is not None and viewpick.same_actor(self.actor_part, actor)):
                    self.sel, self.sel_plane, self.sel_face, self.sel_edges = None, nm, None, []
                    self.refresh_tree()
                    self.show_props()
                    self.draw()
                    self.say(f"{nm} plane selected - press Sketch.")
                    return
        if self.actor_part is None or not viewpick.same_actor(self.actor_part, actor):
            return
        idx = int(self.view_cells.cell_data["face"][cid])
        face = solid.faces()[idx]
        flat = face.geom_type.name == "PLANE"
        self.sel_face = {"ref": self.doc.face_ref(face) if flat else None, "index": idx}
        self.sel_plane, self.sel_edges = None, ([] if not shift else self.sel_edges)
        if sketching:
            self.say("Face selected - press Convert Entities to copy its outline into the sketch.")
        else:
            self.say("Face selected - press Sketch to draw on it." if flat else "Curved face selected (a sketch needs a flat face).")
            if not (f is not None and f["kind"] == "sketch"):
                self.sel = None
            self.refresh_tree()
            self.show_props()
        self.draw()

    @staticmethod
    def same_edge(a, b):
        return np.linalg.norm(np.array(a["m"]) - np.array(b["m"])) < 1e-3

    def nearest_edge(self, solid, p):
        tol = 10 * viewpick.world_per_pixel(self.plotter)
        best, bd = None, 1e18
        for e, pts in zip(solid.edges(), self.doc.edge_lines(solid)):
            a, b = pts[:-1], pts[1:]
            ab = b - a
            t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
            dist = float(np.min(np.linalg.norm(a + ab * t[:, None] - p, axis=1)))
            if dist < bd:
                best, bd = e, dist
        return best if bd <= tol else None


THEME = """
QMainWindow, QWidget { font-family: 'Segoe UI', 'Noto Sans', sans-serif; font-size: 12px; color: #1f2a3c; }
QMainWindow { background: #f3f5f9; }
QToolBar { background: #ffffff; border-bottom: 1px solid #d5dbe6; spacing: 4px; padding: 2px 6px; }
QToolBar QToolButton { padding: 4px 10px; border-radius: 4px; }
QToolBar QToolButton:hover { background: #e6efff; }
QTabWidget::pane { border: 0; background: #ffffff; }
QTabBar::tab { background: transparent; padding: 5px 16px; margin: 0 2px; border-top-left-radius: 5px; border-top-right-radius: 5px; color: #4a5872; }
QTabBar::tab:selected { background: #ffffff; color: #1a56c4; font-weight: 600; border-bottom: 2px solid #2b7de9; }
QTabBar::tab:hover:!selected { background: #e9eefa; }
QToolButton { border: 1px solid transparent; border-radius: 6px; padding: 2px; }
QToolButton:hover { background: #e6efff; border-color: #bcd3f7; }
QToolButton:pressed { background: #cfe0fb; }
QToolButton::menu-button { border: 0; width: 12px; }
QTreeWidget, QTableWidget, QListWidget { background: #ffffff; border: 1px solid #d5dbe6; border-radius: 4px; alternate-background-color: #f7f9fc; }
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected { background: #cfe0fb; color: #12223f; }
QHeaderView::section { background: #eef2f9; border: 0; border-bottom: 1px solid #d5dbe6; padding: 3px 6px; color: #4a5872; }
QLineEdit, QComboBox, QDoubleSpinBox { background: #ffffff; border: 1px solid #c8d0de; border-radius: 4px; padding: 3px 6px; }
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border-color: #2b7de9; }
QPushButton { background: #ffffff; border: 1px solid #c8d0de; border-radius: 5px; padding: 4px 12px; }
QPushButton:hover { background: #e6efff; border-color: #2b7de9; }
QStatusBar { background: #ffffff; border-top: 1px solid #d5dbe6; }
QMenu { background: #ffffff; border: 1px solid #c8d0de; padding: 4px; }
QMenu::item { padding: 5px 22px; border-radius: 4px; }
QMenu::item:selected { background: #cfe0fb; color: #12223f; }
QCheckBox::indicator:checked { background: #2b7de9; border: 1px solid #1a56c4; border-radius: 3px; }
QCheckBox::indicator:unchecked { background: #ffffff; border: 1px solid #98a4ba; border-radius: 3px; }
QScrollBar:horizontal { height: 8px; background: transparent; }
QScrollBar::handle:horizontal { background: #c3cde0; border-radius: 4px; }
"""


def apply_theme(app):
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    app.setStyleSheet(THEME)


part_refgeo.install(MainWindow)


def main():
    import gpd_app
    gpd_app.main()


if __name__ == "__main__":
    main()
