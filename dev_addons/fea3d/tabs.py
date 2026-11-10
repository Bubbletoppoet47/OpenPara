"""The Voxel FEA tab.  Several can be open at once; each has its own tools and 3D view.

The shape comes from a Mesh tab ("Import from tab"), a mesh file, a voxel array, or a built-in test model.  The sidebar goes top to bottom:
    1. Geometry       where the shape comes from
    2. Voxels         voxel size (or a fill target that finds it), uniform or adaptive bricks, a block cut from the middle
    3. Material       OpenPara's material library, or custom
    4. Supports and loads   choose a view (X, Y, Z), drag a box over the nodes (through the whole depth), put them in groups:
                      fixed support, prescribed displacement, force
    5. Solve          solver, run, and refinement (shrink the voxel until the result settles)
    6. Results        summary, field to colour, deformed shape, cut-open view, how the apparent modulus is measured
Every solid voxel (or brick) is one element, its corners are the nodes: the voxel grid is the mesh, there is no separate meshing step.
Look and units follow OpenPara (theme, File > Units, result colours, material library)."""
import os
import time

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PyQt6.QtCore import QEvent, QRect, QTimer, Qt
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QFrame, QComboBox, QDockWidget, QFileDialog, QGroupBox, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                             QPlainTextEdit, QPushButton, QRubberBand, QScrollArea, QSlider, QVBoxLayout, QWidget)

import fem3d as F
import lattice as LT
import look
import octree as OT
import picking as PK
import repair as R
import solid
import verify as VF
import voxel as VX
from jobs import JobMixin
from tasks import sub, tick
import ui_kit
from uiparts import button, narrow, row, spin, stack

AXES = ["X", "Y", "Z"]
# (name, key, kind of value, where it lives): the same list style as OpenPara's FEA tab
FIELDS = [("Displacement magnitude", "umag", "L", "node"), ("Displacement X", "ux", "L", "node"), ("Displacement Y", "uy", "L", "node"), ("Displacement Z", "uz", "L", "node"),
          ("von Mises stress", "von Mises", "S", "cell"), ("Normal stress X", "sxx", "S", "cell"), ("Normal stress Y", "syy", "S", "cell"), ("Normal stress Z", "szz", "S", "cell"),
          ("Shear stress XY", "txy", "S", "cell"), ("Shear stress YZ", "tyz", "S", "cell"), ("Shear stress XZ", "txz", "S", "cell"),
          ("Principal stress 1 (largest)", "s1", "S", "cell"), ("Principal stress 3 (smallest)", "s3", "S", "cell"), ("Maximum shear", "tmax", "S", "cell"),
          ("Strain energy density", "strain energy", "S", "cell"), ("Brick size", "brick size", "L", "cell")]
SIGNED = {"ux", "uy", "uz", "sxx", "syy", "szz", "txy", "tyz", "txz", "s1", "s3"}
NODE_COLOURS = {"sel": "#ff7a00", "all": "#8da0bf"}
MAX_SHOWN = 150_000
VIEWUP = {0: (0, 0, 1), 1: (0, 0, 1), 2: (0, 1, 0)}


def voxel_surface(occ, h, origin):
    g = pv.ImageData(dimensions=tuple(int(x) + 1 for x in occ.shape), spacing=(h, h, h), origin=tuple(float(x) for x in origin))
    g.cell_data["occ"] = occ.ravel(order="F").astype(np.uint8)
    return g.threshold(0.5, scalars="occ").extract_surface(algorithm="dataset_surface")


def look_along(plotter, axis):
    """Orthographic view along X, Y or Z (axis None: isometric, perspective), then fit the model in the window."""
    if axis is None:
        plotter.disable_parallel_projection()
        plotter.view_isometric()
        plotter.reset_camera()
        return
    cam = plotter.renderer.GetActiveCamera()
    b = np.array(plotter.bounds if hasattr(plotter, "bounds") else plotter.renderer.bounds, float)
    if not np.all(np.isfinite(b)) or b[1] < b[0]:
        b = np.array([-1, 1, -1, 1, -1, 1], float)
    centre = (b[0::2] + b[1::2]) / 2
    diag = max(float(np.linalg.norm(b[1::2] - b[0::2])), 1e-6)
    d = np.zeros(3)
    d[axis] = 1.0
    cam.SetFocalPoint(*centre)
    cam.SetPosition(*(centre + d * diag * 2.0))
    cam.SetViewUp(*VIEWUP[axis])
    plotter.enable_parallel_projection()
    plotter.reset_camera()
    plotter.renderer.ResetCameraClippingRange()


class VoxelTab(QMainWindow, JobMixin):
    KIND = "voxel"
    TITLE = "Voxel FEA"

    def __init__(self, host=None, quiet=False, threaded=None):
        super().__init__()
        self.host, self.quiet = host, quiet
        self.threaded = (not quiet) if threaded is None else threaded
        self.src = {"kind": None, "mesh": None, "occ": None, "h": 1.0, "origin": np.zeros(3), "label": "nothing loaded yet", "tab": None}
        self.vox = None                     # (occ, origin, None, h, geometry model or None)
        self.cache = None
        self.nodes = None                   # the nodes that can be selected
        self.result = None
        self.actors = {}
        self.overlay = []
        self.groups = []
        self.sel_ops = []
        self.select_mode = False
        self._drag = None
        self._loading = False
        self.counter = 0
        self.checks = None
        self.plotter = QtInteractor(self)
        look.set_bg(self.plotter)
        self.setCentralWidget(self.plotter.interactor)
        self.band = QRubberBand(QRubberBand.Shape.Rectangle, self.plotter.interactor)
        self.plotter.interactor.installEventFilter(self)
        self.panel = QWidget()
        self.lay = QVBoxLayout(self.panel)
        self.lay.setContentsMargins(6, 2, 6, 6)
        self.lay.setSpacing(2)
        self.sections = []                  # the numbered, foldable steps of the panel (the look of the 1D / 2D FEA panels)
        self.last_box = None
        self.build_ui()
        self.lay.addStretch(1)
        self.polish_panel()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setWidget(self.panel)
        sc.setMinimumWidth(360)
        dock = QDockWidget("", self)
        dock.setTitleBarWidget(QWidget())   # no "Tools" strip: the bar on top says what this tab is
        dock.setWidget(sc)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.props_dock, self.panel_scroll = dock, sc
        self.make_bar()
        ui_kit.fit_dock(self, dock, self.panel, lo=360, hi=560)
        self.init_jobs()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.refresh_display)
        look.on_units_changed(self.units_changed)
        self.statusBar().showMessage("Bring in a shape first: 'Import from tab', a file, or a test model.")

    # ------------------------------------------------------------------------------------------------------ small helpers
    def box(self, title):
        """A step of the panel: "3. Material" becomes the numbered, foldable section 3 (its fold is remembered).  Returns the layout to fill."""
        num, _, name = title.partition(". ")
        if not name or not num.isdigit():
            num, name = len(self.sections) + 1, title
        sec = ui_kit.Section(self.KIND, int(num), name, True)
        self.sections.append(sec)
        self.lay.addWidget(sec)
        self.last_box = sec.body
        return sec.body

    PRIMARY = ("Voxelise and show", "Reduce, mesh and show", "Run")          # the buttons that move the work on: teal, like Solve in the FEA tabs

    def polish_panel(self):
        """After the panel is built: the main actions stand out, long drop-downs do not set the panel's width, plain labels wrap."""
        for b in self.panel.findChildren(QPushButton):
            if b.text() in self.PRIMARY:
                ui_kit.primary(b)
                b.setMinimumHeight(34)
        for c in self.panel.findChildren(QComboBox):
            if not c.isEditable() and max((len(c.itemText(i)) for i in range(c.count())), default=0) > 26:
                ui_kit.tame_combo(c, 26)

    def make_bar(self):
        """The bar on top, as in the other tabs: what this is, and what is loaded."""
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(8)
        lay.addWidget(ui_kit.kind_chip(self.TITLE, "#7c4dcc"))
        self.bar_lbl = QLabel("Nothing loaded yet")
        self.bar_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        lay.addWidget(self.bar_lbl, 1)
        ui_kit.top_bar(self, bar)

    def note(self, lay, text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#506080; font-size:11px;")
        lay.addWidget(lb)
        return lb

    def delayed_refresh(self, *_a):
        self.refresh_timer.start(150)

    def units_changed(self, *_a):
        try:
            self.update_estimate()
            self.refresh_group_list()
            if self.result is not None:
                self.show_result_text()
                self.refresh_display()
        except RuntimeError:
            pass

    def put(self, name, mesh, **kw):
        a = self.actors.pop(name, None)
        if a is not None:
            self.plotter.remove_actor(a)
        if mesh is not None:
            self.actors[name] = self.plotter.add_mesh(mesh, name=name, **kw)

    def clear_scene(self):
        for n in list(self.actors):
            self.put(n, None)
        self.overlay = []
        try:
            self.plotter.remove_scalar_bar()
        except Exception:
            pass

    def cleanup(self):
        try:
            self.plotter.close()
        except Exception:
            pass

    def build_ui(self):
        self.build_source_box()
        self.build_voxel_box()
        self.build_material_box()
        self.build_nodes_box()
        self.build_solve_box()
        self.build_results_box()
        self.build_verify_box()

    # ------------------------------------------------------------------------------------------------------ 1. geometry
    def build_source_box(self):
        lay = self.box("1. Geometry")
        self.src_lbl = QLabel(self.src["label"])
        self.src_lbl.setWordWrap(True)
        lay.addWidget(self.src_lbl)
        self.import_btn = QPushButton("Import from tab...")
        self.import_btn.clicked.connect(self.import_menu)
        lay.addWidget(self.import_btn)
        lay.addWidget(button("Refresh from that tab", self.refresh_from_tab))
        lay.addWidget(button("Open mesh file...", self.open_mesh_dialog))
        lay.addWidget(button("Open voxel array (.npy)...", self.open_voxel_dialog))
        self.model_combo = QComboBox()
        self.model_combo.addItems(list(LT.TEST_MODELS))
        lay.addWidget(row(self.model_combo, button("Load test model", self.load_test_model)))
        self.note(lay, "The shape must be a closed mesh (no holes) - repair it in a Mesh tab first. A copy is taken: later changes in the Mesh tab show up here only when you import again.")

    def update_source_label(self):
        s = self.src
        extra = ""
        if s["kind"] == "mesh":
            b = s["mesh"].bounds
            extra = (f"\nMesh: {s['mesh'].n_cells:,} triangles, {look.fmt('L', b[1] - b[0], 4)} x {look.fmt('L', b[3] - b[2], 4)} x {look.fmt('L', b[5] - b[4], 4)}"
                     + (f"\n{s['open']} open edges - fix the holes first" if s.get("open") else "  ·  closed"))
        elif s["kind"] == "voxels":
            extra = f"\nVoxels: {s['occ'].shape[0]} x {s['occ'].shape[1]} x {s['occ'].shape[2]}, voxel {look.fmt('L', s['h'])}, {int(s['occ'].sum()):,} solid"
        self.src_lbl.setText(f"From: {s['label']}{extra}")
        if getattr(self, "bar_lbl", None) is not None:
            self.bar_lbl.setText(f"of <b>{s['label']}</b>" if s["kind"] else "Nothing loaded yet")
        self.src_lbl.setStyleSheet("color:#b00020;" if s.get("open") else "")

    def reset_discretisation(self):
        self.nodes = None
        self.vox = None
        self.result = None
        self.sel_ops = []

    def set_source_mesh(self, mesh, label, tab=None):
        n_open = 0
        try:
            n_open = mesh.extract_feature_edges(boundary_edges=True, non_manifold_edges=False, feature_edges=False, manifold_edges=False).n_cells
        except Exception:
            pass
        self.src = {"kind": "mesh", "mesh": mesh, "occ": None, "h": self.src["h"], "origin": np.zeros(3), "label": label, "tab": tab, "open": n_open}
        self.reset_discretisation()
        self.on_source_changed()

    def set_source_voxels(self, occ, h, origin, label, tab=None):
        self.src = {"kind": "voxels", "mesh": None, "occ": occ, "h": float(h), "origin": np.asarray(origin, float), "label": label, "tab": tab}
        self.reset_discretisation()
        self.on_source_changed()

    def on_source_changed(self):
        self.update_source_label()
        if self.src["kind"] == "voxels":
            self.h_spin.set_internal(self.src["h"])
            self.h_spin.setEnabled(False)
        else:
            self.h_spin.setEnabled(True)
        self.update_estimate()
        self.show_source()
        self.refresh_group_list()

    def show_source(self):
        self.clear_scene()
        if self.src["kind"] == "mesh":
            self.put("source", self.src["mesh"], color="#c9d3dc", smooth_shading=True)
            self.plotter.reset_camera()
        elif self.src["kind"] == "voxels":
            self.put("source", voxel_surface(self.src["occ"], self.src["h"], self.src["origin"]), color="#c9d3dc")
            self.plotter.reset_camera()
        self.draw_overlays()

    def sources(self):
        return [] if self.host is None else self.host.sources_for(self)

    def import_menu(self):
        menu = QMenu(self)
        items = self.sources()
        if not items:
            a = menu.addAction("(no other tab has a shape to import)")
            a.setEnabled(False)
        for title, tab, kind, info in items:
            menu.addAction(f"{title}   -   {info}", lambda t=tab, k=kind, ti=title: self.import_from(t, k, ti))
        menu.exec(self.import_btn.mapToGlobal(self.import_btn.rect().bottomLeft()))

    def import_from(self, tab, kind, title):
        if kind == "mesh":
            m = tab.provide_mesh()
            if m is None:
                return self.fail("Import", "That tab has no mesh yet.")
            self.set_source_mesh(m, f"tab '{title}' (mesh)", tab)
        else:
            v = tab.provide_voxels()
            if v is None:
                return self.fail("Import", "That tab has no voxels yet - voxelise it first.")
            self.set_source_voxels(v[0], v[1], v[2], f"tab '{title}' (voxels)", tab)
        self.statusBar().showMessage(f"Imported from '{title}'.")

    def refresh_from_tab(self):
        tab = self.src.get("tab")
        if tab is None or (self.host is not None and not self.host.has_tab(tab)):
            return self.fail("Refresh", "This shape did not come from a tab (or that tab was closed). Use 'Import from tab...'.")
        title = self.host.title_of(tab) if self.host else "tab"
        self.import_from(tab, "mesh" if self.src["kind"] == "mesh" else "voxels", title)

    def open_mesh_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open mesh", "", "Meshes (*.stl *.obj *.ply *.vtk *.vtp);;All files (*)")
        if p:
            self.open_mesh(p)

    def open_mesh(self, path):
        def work(cb):
            cb("Reading file", None)
            return R.load(path)
        self.run_task("Open", work, lambda m: self.set_source_mesh(R.to_mesh(*R.arrays(m)), os.path.basename(path)))

    def open_voxel_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open voxel array", "", "NumPy arrays (*.npy)")
        if p:
            self.open_voxels(p)

    def open_voxels(self, path):
        a = np.load(path)
        if a.ndim != 3:
            return self.fail("Open voxel array", "The array must be 3-dimensional (x, y, z).")
        self.set_source_voxels(a > 0, self.h_spin.internal(), np.zeros(3), f"{os.path.basename(path)} (voxel size from the Voxel size box)")
        self.do_voxelise()

    def load_test_model(self, name=None):
        name = name or self.model_combo.currentText()
        occ, h = LT.TEST_MODELS[name]()
        self.set_source_voxels(occ, h, np.zeros(3), f"test model '{name}'")
        self.do_voxelise()

    def provide_mesh(self):
        return None

    def provide_voxels(self):
        if self.vox is None:
            return None
        return self.vox[0], self.vox[3], self.vox[1]

    # ------------------------------------------------------------------------------------------------------ 2. voxels
    def build_voxel_box(self):
        lay = self.box("2. Voxels")
        self.h_spin = look.UnitSpin("L", 1e-4, 1e4, 0.5, 5, 0.01)
        self.h_spin.valueChanged.connect(self.update_estimate)
        self.limit_spin = spin(1000, 50_000_000, 1_500_000, 0, 100000, " elements")
        lay.addWidget(row("Voxel size", self.h_spin))
        lay.addWidget(row("Refuse above", self.limit_spin))
        self.fill_spin = spin(50, 100, 95, 1, 1, " %")
        lay.addWidget(row("Fill target: volume within", self.fill_spin))
        lay.addWidget(button("Find the voxel size for the fill target", self.do_fill))
        self.fill_lbl = QLabel("")
        self.fill_lbl.setWordWrap(True)
        lay.addWidget(self.fill_lbl)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Uniform voxels", "Adaptive voxels (small near the surface, big inside)"])
        self.mode_combo.currentIndexChanged.connect(self.mode_changed)
        lay.addWidget(self.mode_combo)
        self.levels_combo = QComboBox()
        self.levels_combo.addItems(["2 x the voxel", "4 x the voxel", "8 x the voxel", "16 x the voxel"])
        self.levels_combo.setCurrentIndex(1)
        self.grade_spin = spin(0.25, 3.0, 1.0, 2, 0.25)
        self.adapt_box = QWidget()
        al = QVBoxLayout(self.adapt_box)
        al.setContentsMargins(0, 0, 0, 0)
        al.addWidget(row("Biggest brick", self.levels_combo))
        al.addWidget(row("Growth with depth", self.grade_spin))
        self.note(al, "A brick of side s is only used where it is solid all through and every part of it is at least 'growth' x s from the outside, so the skin and thin struts stay at the voxel size. "
                      "Growth 1 keeps the accuracy of the uniform grid; lower gives fewer bricks and a stiffer, less accurate answer.")
        self.adapt_box.setVisible(False)
        lay.addWidget(self.adapt_box)
        self.crop_spins = []
        for _a in AXES:
            s = spin(5, 100, 100, 0, 5, " %")
            s.valueChanged.connect(self.update_estimate)
            self.crop_spins.append(s)
        lay.addWidget(stack("Block from the middle (X, Y, Z)", *self.crop_spins))
        self.est_lbl = QLabel("")
        self.est_lbl.setWordWrap(True)
        lay.addWidget(self.est_lbl)
        lay.addWidget(button("Voxelise and show", self.do_voxelise))
        self.note(lay, "Every solid voxel is one brick element; the corners are the nodes. 4 or more voxels across the thinnest strut gives a good stiffness. "
                       "A flat-ended block cut from the middle (under 100 %) gives clean end faces for supports and loads.")

    def mode_changed(self, *_a):
        self.adapt_box.setVisible(self.adaptive())
        self.update_estimate()

    def adaptive(self):
        return self.mode_combo.currentIndex() == 1

    def crop_values(self):
        return tuple(s.value() / 100.0 for s in self.crop_spins)

    def update_estimate(self, *_a):
        s = self.src
        crop = float(np.prod(self.crop_values()))
        note = "  (adaptive: the real count comes after voxelising)" if self.adaptive() else ""
        if s["kind"] == "mesh":
            try:
                e = VX.estimate(s["mesh"], self.h_spin.internal())
                n = int(e["elements"] * crop)
                over = n > self.limit_spin.value() and not self.adaptive()
                self.est_lbl.setText(f"About {n:,} solid voxels  ·  {int(3 * n * 1.25):,} unknowns  ·  about {n * VX.BYTES_PER_ELEMENT / 1e9:.2f} GB{note}")
                self.est_lbl.setStyleSheet("color:#b00020;" if over else "")
            except Exception as ex:
                self.est_lbl.setText(f"(no estimate: {ex})")
        elif s["kind"] == "voxels":
            n = int(s["occ"].sum() * crop)
            self.est_lbl.setText(f"Fixed by the source: voxel {look.fmt('L', s['h'])}  ·  about {n:,} solid voxels{note}")
            self.est_lbl.setStyleSheet("")
        else:
            self.est_lbl.setText("")

    def voxels_at(self, h, a, cb=None):
        """(occ, origin, h) at voxel size h inside the block cut from the middle.  A mesh is voxelised in that block (kept for next time)."""
        s, crop = a["src"], a["crop"]
        if s["kind"] is None:
            raise ValueError("Bring in a shape first.")
        if s["kind"] == "voxels":
            occ, origin = s["occ"], s["origin"]
            if min(crop) < 0.999:
                n = np.array(occ.shape)
                keep = np.maximum((n * np.array(crop)).round().astype(int), 1)
                lo = (n - keep) // 2
                sl = tuple(slice(int(lo[i]), int(lo[i] + keep[i])) for i in range(3))
                occ, origin = np.ascontiguousarray(occ[sl]), np.asarray(origin, float) + lo * s["h"]
            return occ, origin, s["h"]
        key = (id(s["mesh"]), round(h, 9), tuple(round(c, 6) for c in crop))
        if self.cache is not None and self.cache[0] == key:
            return self.cache[1], self.cache[2], h
        e = VX.estimate(s["mesh"], h)
        n = int(e["elements"] * float(np.prod(crop)))
        if not a["adaptive"] and n > a["limit"]:
            raise ValueError(f"About {n:,} elements at voxel size {look.fmt('L', h, 4)} - more than the limit of {int(a['limit']):,}. Use a larger voxel or raise the limit.")
        b = np.asarray(s["mesh"].bounds, float)
        lo, hi = b[0::2], b[1::2]
        mid, half = (lo + hi) / 2, (hi - lo) / 2 * np.array(crop)
        occ, origin = VX.voxelise(s["mesh"], h, cb, box=(mid - half, mid + half))
        self.cache = (key, occ, origin)
        return occ, origin, h

    def geometry(self, occ, h, origin, a, cb=None):
        """The elements without a stiffness matrix: a uniform voxel model, or the adaptive bricks."""
        if a["adaptive"]:
            m = OT.AdaptiveModel(occ, h, origin, a["levels"], a["grade"], cb)
            if m.ne > a["limit"]:
                raise ValueError(f"{m.ne:,} bricks is more than the limit of {int(a['limit']):,}. Use a larger voxel, a lower growth value, or raise the limit.")
            return m
        if int(occ.sum()) > a["limit"]:
            raise ValueError(f"{int(occ.sum()):,} elements is more than the limit of {int(a['limit']):,}.")
        return None

    def do_voxelise(self):
        a = self.run_args()
        h = self.h_spin.internal()

        def work(cb):
            occ, origin, hh = self.voxels_at(h, a, sub(cb, 0.0, 0.5))
            geo = self.geometry(occ, hh, origin, a, sub(cb, 0.5, 0.9))
            if geo is not None:
                return occ, origin, hh, geo, geo.grid(), geo.node_xyz()
            return occ, origin, hh, None, voxel_surface(occ, hh, origin), VX.node_positions(occ, hh, origin)

        def done(res):
            occ, origin, hh, geo, surf, nodes = res
            self.vox = (occ, origin, None, hh, geo)
            self.result = None
            self.clear_scene()
            if geo is not None:
                self.put("voxels", surf, scalars="brick size", cmap="viridis_r", show_edges=True, line_width=0.4, show_scalar_bar=False)
            else:
                self.put("voxels", surf, color="#c9d3dc", show_edges=False)
            self.plotter.reset_camera()
            self.set_nodes(nodes)
            msg = f"{int(occ.sum()):,} solid voxels in a {occ.shape[0]} x {occ.shape[1]} x {occ.shape[2]} grid ({occ.mean() * 100:.1f} % bone), {len(nodes):,} nodes."
            if geo is not None:
                msg = geo.summary() + f"; {len(nodes):,} nodes can be selected."
            self.statusBar().showMessage(msg)
        self.run_task("Voxelise", work, done)

    def do_fill(self):
        s = self.src
        if s["kind"] != "mesh":
            return self.fail("Voxel size", "This needs a mesh as the source (a voxel array has a fixed voxel size).")
        tol = 1.0 - self.fill_spin.value() / 100.0
        mesh, limit = s["mesh"], self.limit_spin.value()
        vol = abs(solid.mesh_volume(mesh))
        b = mesh.bounds
        size = (b[1] - b[0], b[3] - b[2], b[5] - b[4])
        adaptive = self.adaptive()

        def work(cb):
            rows = []
            hh = min(size) / 12.0
            for k in range(14):
                tick(cb, f"Voxel size {hh:.4g}: checking the volume", k / 14)
                if VX.estimate(mesh, hh)["elements"] > limit * (8 if adaptive else 1) :
                    return hh / 0.8, rows, False, "reached the element limit"
                occ, _o = VX.voxelise(mesh, hh)
                v = float(occ.sum()) * hh ** 3
                rows.append((hh, v, (v - vol) / vol, int(occ.sum())))
                if abs(rows[-1][2]) <= tol:
                    return hh, rows, True, ""
                hh *= 0.8
            return rows[-1][0], rows, False, "no match after 14 steps"

        def done(res):
            h, rows, ok, why = res
            lines = [f"{'size':>10} {'volume error':>13} {'voxels':>10}"] + [f"{look.fmt('L', r_[0], 4):>10} {r_[2] * 100:>+12.2f}% {r_[3]:>10,}" for r_ in rows]
            lines.append((f"Found: voxel size {look.fmt('L', h, 4)}, volume within {abs(rows[-1][2]) * 100:.2f} % of the mesh." if ok else f"Stopped: {why}. Best so far {look.fmt('L', h, 4)}."))
            self.fill_lbl.setText("\n".join(lines[-3:]) if len(lines) > 4 else "\n".join(lines))
            self.fill_lbl.setToolTip("\n".join(lines))
            self.h_spin.set_internal(h)
            self.fill_rows = rows
            self.statusBar().showMessage(lines[-1])
        self.run_task("Find the voxel size", work, done)

    # ------------------------------------------------------------------------------------------------------ 3. material
    def build_material_box(self):
        lay = self.box("3. Material")
        self.mat = look.MaterialBox(10000.0, 0.3)
        lay.addWidget(self.mat)
        self.note(lay, "Pick OpenPara's library material, or type your own values (for trabecular bone tissue, enter the modulus you use).")

    # ------------------------------------------------------------------------------------------------------ 4. supports and loads
    def build_nodes_box(self):
        lay = self.box("4. Supports and loads")
        self.note(lay, "Pick a view, switch on Select, and drag a box over the nodes: it takes every node inside the box through the whole model "
                       "(Shift adds, Ctrl removes, right mouse button turns the view). Then put them in a group.")
        self.view_buttons = [button(f"Along {name}", lambda ax=ax: self.set_view(ax)) for ax, name in enumerate(AXES)]
        lay.addWidget(row("View", *self.view_buttons, button("Iso", lambda: self.set_view(None))))
        self.sel_btn = QPushButton("Select nodes with a box")
        self.sel_btn.setCheckable(True)
        self.sel_btn.toggled.connect(self.set_select_mode)
        lay.addWidget(self.sel_btn)
        self.depth_lo = spin(0, 100, 0, 0, 5, " %")
        self.depth_hi = spin(0, 100, 100, 0, 5, " %")
        lay.addWidget(row("Depth from", self.depth_lo, "to", self.depth_hi))
        self.sel_lbl = QLabel("Nothing selected.")
        self.sel_lbl.setWordWrap(True)
        lay.addWidget(self.sel_lbl)
        self.show_all = QCheckBox("Show all nodes")
        self.show_all.toggled.connect(self.refresh_overlays)
        lay.addWidget(row(self.show_all, button("Clear selection", self.clear_selection)))
        self.group_list = QListWidget()
        self.group_list.setMinimumHeight(96)
        self.group_list.currentRowChanged.connect(self.group_selected)
        lay.addWidget(self.group_list)
        lay.addWidget(row(button("New group", self.new_group), button("Delete group", self.delete_group)))
        lay.addWidget(row(button("Group = selection", lambda: self.assign(False)), button("Add selection to group", lambda: self.assign(True))))
        self.g_name = QLineEdit()
        self.g_kind = QComboBox()
        self.g_kind.addItems(list(F.KINDS.values()))
        self.g_axes = [QCheckBox(a) for a in AXES]
        self.g_disp = [look.UnitSpin("L", -1e6, 1e6, 0.0, 5, 0.01) for _ in AXES]
        self.g_force = [look.UnitSpin("F", -1e9, 1e9, 0.0, 4, 1.0) for _ in AXES]
        narrow(*self.g_disp, *self.g_force)
        self.g_disp_row = stack("Move by (x, y, z)", *self.g_disp)
        self.g_force_row = stack("Total force (x, y, z)", *self.g_force)
        lay.addWidget(row("Name", self.g_name))
        lay.addWidget(row("Kind", self.g_kind))
        lay.addWidget(row("Acts along", *self.g_axes))
        lay.addWidget(self.g_disp_row)
        lay.addWidget(self.g_force_row)
        self.g_name.editingFinished.connect(self.group_edited)
        self.g_kind.currentIndexChanged.connect(self.group_edited)
        for w in self.g_axes:
            w.toggled.connect(self.group_edited)
        for w in self.g_disp + self.g_force:
            w.valueChanged.connect(self.group_edited)
        self.note(lay, "Support: the chosen directions cannot move. Move by: the chosen directions are pushed by that distance. "
                       "Total force: shared equally among the group's nodes. For a compression test: a support group on one end, a 'move by' group on the other.")

    def set_view(self, axis):
        look_along(self.plotter, axis)
        self.plotter.render()

    # ---- selection with a box
    def set_select_mode(self, on):
        self.select_mode = bool(on)
        w = self.plotter.interactor
        try:
            if on:
                self.plotter.enable_custom_trackball_style(left=None, shift_left=None, control_left=None, right="rotate", control_right="rotate", shift_right="pan")
                w.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.plotter.enable_trackball_style()
                w.unsetCursor()
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        if obj is self.plotter.interactor and self.select_mode and not self.busy and self.nodes is not None:
            t = ev.type()
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                self._drag = ev.position().toPoint()
                self.band.setGeometry(QRect(self._drag, self._drag))
                self.band.show()
                return True
            if t == QEvent.Type.MouseMove and self._drag is not None:
                self.band.setGeometry(QRect(self._drag, ev.position().toPoint()).normalized())
                return True
            if t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton and self._drag is not None:
                a, b = self._drag, ev.position().toPoint()
                self._drag = None
                self.band.hide()
                mods = ev.modifiers()
                mode = "add" if mods & Qt.KeyboardModifier.ShiftModifier else "remove" if mods & Qt.KeyboardModifier.ControlModifier else "replace"
                ratio = obj.devicePixelRatioF() if hasattr(obj, "devicePixelRatioF") else 1.0
                if (a - b).manhattanLength() >= 4:
                    (x0, y0), (x1, y1) = PK.qt_to_gl(self.plotter, a.x(), a.y(), ratio), PK.qt_to_gl(self.plotter, b.x(), b.y(), ratio)
                    self.select_box(x0, y0, x1, y1, mode)
                return True
        return super().eventFilter(obj, ev)

    def select_box(self, gx0, gy0, gx1, gy1, mode="replace"):
        """A box on screen (OpenGL pixels): every node inside it, through the depth range, is selected."""
        if self.nodes is None:
            return
        M, w, h = PK.matrix(self.plotter)
        rect = (gx0 / w * 2 - 1, gy0 / h * 2 - 1, gx1 / w * 2 - 1, gy1 / h * 2 - 1)
        cam = self.plotter.renderer.GetActiveCamera()
        d = np.array(cam.GetFocalPoint()) - np.array(cam.GetPosition())
        d /= max(np.linalg.norm(d), 1e-30)
        t = self.nodes @ d
        t0, t1 = float(t.min()), float(t.max())
        lo, hi = sorted((self.depth_lo.value(), self.depth_hi.value()))
        depth = None if lo <= 0 and hi >= 100 else (t0 + (t1 - t0) * lo / 100.0 - 1e-9, t0 + (t1 - t0) * hi / 100.0 + 1e-9)
        reg = F.Region.view(M, rect, d, depth)
        if mode == "replace":
            self.sel_ops = [("add", reg)]
        else:
            self.sel_ops.append(("add" if mode == "add" else "sub", reg))
        self.refresh_overlays()

    def selection_mask(self):
        if self.nodes is None:
            return np.zeros(0, bool)
        return F.apply_ops(self.sel_ops, self.nodes)

    def clear_selection(self):
        self.sel_ops = []
        self.refresh_overlays()

    # ---- groups
    def current_group(self):
        i = self.group_list.currentRow()
        return self.groups[i] if 0 <= i < len(self.groups) else None

    def new_group(self):
        self.counter += 1
        self.groups.append(F.Group(f"Group {self.counter}", "fixed", [True, True, True]))
        self.refresh_group_list(select=len(self.groups) - 1)

    def delete_group(self):
        g = self.current_group()
        if g is not None:
            self.groups.remove(g)
            self.refresh_group_list()

    def assign(self, add):
        g = self.current_group()
        if g is None:
            return self.fail("Group", "Make a group first (New group), pick it in the list, then assign the selection.")
        if not self.sel_ops:
            return self.fail("Group", "Nothing is selected.")
        g.ops = (g.ops + self.sel_ops) if add else list(self.sel_ops)
        self.refresh_group_list(select=self.groups.index(g))

    def group_text(self, g):
        n = int(g.mask(self.nodes).sum()) if self.nodes is not None and g.ops else 0
        extra = ""
        if g.kind == "disp":
            extra = "  " + ", ".join(f"{AXES[a]} {look.fmt('L', g.values[a], 4)}" for a in range(3) if g.axes[a])
        elif g.kind == "force":
            extra = "  " + ", ".join(f"{AXES[a]} {look.fmt('F', g.values[a], 4)}" for a in range(3) if g.axes[a])
        return f"{g.describe()}{extra}  -  {n:,} nodes" if g.ops else f"{g.describe()}{extra}  -  no nodes yet"

    def refresh_group_list(self, select=None):
        cur = self.group_list.currentRow() if select is None else select
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for g in self.groups:
            self.group_list.addItem(QListWidgetItem(self.group_text(g)))
        self.group_list.blockSignals(False)
        if self.groups:
            self.group_list.setCurrentRow(min(max(cur, 0), len(self.groups) - 1))
        self.group_selected(self.group_list.currentRow())
        self.refresh_overlays()

    def group_selected(self, _row):
        g = self.current_group()
        self._loading = True
        en = g is not None
        for w in [self.g_name, self.g_kind] + self.g_axes + self.g_disp + self.g_force:
            w.setEnabled(en)
        if en:
            self.g_name.setText(g.name)
            self.g_kind.setCurrentIndex(list(F.KINDS).index(g.kind))
            for a in range(3):
                self.g_axes[a].setChecked(bool(g.axes[a]))
                self.g_disp[a].set_internal(g.values[a] if g.kind == "disp" else 0.0)
                self.g_force[a].set_internal(g.values[a] if g.kind == "force" else 0.0)
            self.g_disp_row.setVisible(g.kind == "disp")
            self.g_force_row.setVisible(g.kind == "force")
        self._loading = False

    def group_edited(self, *_a):
        g = self.current_group()
        if g is None or self._loading:
            return
        g.name = self.g_name.text().strip() or g.name
        g.kind = list(F.KINDS)[self.g_kind.currentIndex()]
        g.axes = [w.isChecked() for w in self.g_axes]
        src = self.g_disp if g.kind == "disp" else self.g_force if g.kind == "force" else None
        g.values = [w.internal() for w in src] if src else [0.0, 0.0, 0.0]
        self.g_disp_row.setVisible(g.kind == "disp")
        self.g_force_row.setVisible(g.kind == "force")
        i = self.groups.index(g)
        self.group_list.item(i).setText(self.group_text(g))
        self.refresh_overlays()

    # ---- the nodes in the picture
    def node_points(self, pts):
        if len(pts) > MAX_SHOWN:
            pts = pts[np.linspace(0, len(pts) - 1, MAX_SHOWN).astype(int)]
        return pv.PolyData(np.asarray(pts, float))

    def draw_overlays(self):
        for n in self.overlay:
            self.put(n, None)
        self.overlay = []
        if self.nodes is None or len(self.nodes) == 0:
            self.update_sel_label()
            return
        if self.show_all.isChecked():
            self.put("ov_all", self.node_points(self.nodes), color=NODE_COLOURS["all"], point_size=3, render_points_as_spheres=True)
            self.overlay.append("ov_all")
        for k, g in enumerate(self.groups):
            if g.ops:
                m = g.mask(self.nodes)
                if m.any():
                    self.put(f"ov_g{k}", self.node_points(self.nodes[m]), color=F.COLOURS[g.kind], point_size=6, render_points_as_spheres=True)
                    self.overlay.append(f"ov_g{k}")
        m = self.selection_mask()
        if m.any():
            self.put("ov_sel", self.node_points(self.nodes[m]), color=NODE_COLOURS["sel"], point_size=8, render_points_as_spheres=True)
            self.overlay.append("ov_sel")
        self.update_sel_label()

    def refresh_overlays(self, *_a):
        self.draw_overlays()
        self.plotter.render()

    def update_sel_label(self):
        if self.nodes is None:
            self.sel_lbl.setText("Make the voxels first (step 2) - then the nodes can be selected.")
        else:
            n = int(self.selection_mask().sum()) if self.sel_ops else 0
            self.sel_lbl.setText(f"{n:,} of {len(self.nodes):,} nodes selected." if n else f"Nothing selected ({len(self.nodes):,} nodes). Switch on Select and drag a box.")

    def set_nodes(self, xyz):
        self.nodes = xyz
        self.sel_ops = []
        self.refresh_group_list()

    # ------------------------------------------------------------------------------------------------------ 5. solve
    def build_solve_box(self):
        lay = self.box("5. Solve")
        self.solver_combo = QComboBox()
        self.solver_combo.addItems(["Automatic", "Direct (PARDISO or SuperLU)", "Multigrid + CG (needs pyamg)", "Plain CG (no extra packages, slow on thin struts)",
                                      "Parallel multigrid (Numba, all cores) - voxel grids", "Domain decomposition (slabs solved in parallel) - voxel grids"])
        lay.addWidget(self.solver_combo)
        self.refine_check = QCheckBox("Refine until the result settles")
        self.refine_check.setToolTip("Runs again with a 0.8 times smaller voxel until the apparent modulus changes by less than the tolerance.")
        self.refine_check.toggled.connect(lambda on: self.refine_box.setVisible(on))
        lay.addWidget(self.refine_check)
        self.refine_box = QWidget()
        rl = QVBoxLayout(self.refine_box)
        rl.setContentsMargins(14, 0, 0, 0)
        self.tol_spin = spin(0.05, 50, 2.0, 2, 0.5, " %")
        self.steps_spin = spin(2, 12, 6, 0, 1)
        rl.addWidget(row("Stop when the modulus changes by less than", self.tol_spin))
        rl.addWidget(row("Most steps", self.steps_spin))
        self.refine_box.setVisible(False)
        lay.addWidget(self.refine_box)
        lay.addWidget(button("Run", self.do_run))

    def run_args(self):
        E, nu = self.mat.values()
        ax = self.axis_combo.currentIndex() - 1 if hasattr(self, "axis_combo") else -1
        return dict(E=E, nu=nu, axis=None if ax < 0 else ax, method=["auto", "direct", "amg", "cg", "gmg", "dd"][self.solver_combo.currentIndex()], limit=self.limit_spin.value(),
                    groups=list(self.groups), area=self.area_spin.internal() if hasattr(self, "area_spin") else 0.0,
                    length=self.len_spin.internal() if hasattr(self, "len_spin") else 0.0, src=self.src, crop=self.crop_values(),
                    adaptive=self.adaptive(), levels=self.levels_combo.currentIndex() + 1, grade=self.grade_spin.value())

    def run_once(self, h, a, cb):
        t0 = time.time()
        occ, origin, hh = self.voxels_at(h, a, sub(cb, 0.0, 0.1))
        model = self.geometry(occ, hh, origin, a, sub(cb, 0.1, 0.2))
        if model is not None:
            model.assemble(a["E"], a["nu"], True, sub(cb, 0.2, 0.3))
        else:
            model = VX.Model(occ, hh, a["E"], a["nu"], origin)
        if not a["groups"]:
            raise ValueError("There are no supports or loads. Select nodes (step 4) and put them in groups: a support and a displacement or force.")
        sol = F.solve(model, a["groups"], a["method"], progress=sub(cb, 0.3, 0.95))
        axis = a["axis"] if a["axis"] is not None else F.auto_axis(a["groups"])
        if axis is None:
            raise ValueError("To measure a modulus, one direction needs both a support and a loaded group (displacement or force) acting along it.")
        area = a["area"] or None
        app = F.apparent(model, a["groups"], sol, axis, area, a["length"] or None)
        return {"model": model, "sol": sol, "app": app, "fields": model.fields(sol["u"]), "groups": a["groups"], "h": hh, "axis": axis, "elements": model.ne,
                "E": a["E"], "occ": occ, "origin": origin, "seconds": time.time() - t0, "refine": None}

    def do_run(self):
        a = self.run_args()
        h = self.h_spin.internal()
        if not a["groups"]:
            return self.fail("Run", "Make the supports and loads first (step 4).")
        if self.refine_check.isChecked():
            return self.do_refine(a, h)
        self.run_task("Run", lambda cb: self.run_once(h, a, cb), self.finish_run)

    def do_refine(self, a, h0):
        if a["src"]["kind"] != "mesh":
            return self.fail("Refine", "Refinement needs a mesh as the source (a voxel array has a fixed voxel size).")
        tol, steps = self.tol_spin.value() / 100.0, int(self.steps_spin.value())
        sizes = [h0 * 0.8 ** k for k in range(steps)]
        last = {}

        def work(cb):
            def run(h):
                r = self.run_once(h, a, sub(cb, 0, 1))
                last["r"] = r
                return r["app"]["E_app"], r["elements"]
            rows, ok, why = F.converge(run, sizes, tol, cb)
            return rows, ok, why, last.get("r")

        def done(res):
            rows, ok, why, r = res
            if r is not None:
                r["refine"] = {"rows": rows, "ok": ok, "why": why}
                self.h_spin.set_internal(r["h"])
                self.finish_run(r)
            else:
                self.fail("Refine", why)
        self.run_task("Refine", work, done)

    def finish_run(self, r):
        self.result = r
        self.vox = (r["occ"], r["origin"], None, r["h"], r["model"] if isinstance(r["model"], OT.AdaptiveModel) else None)
        nodes = r["model"].node_xyz()
        if self.nodes is None or len(self.nodes) != len(nodes):
            self.nodes = nodes
        self.show_result_text()
        self.refresh_group_list()
        self.statusBar().showMessage(f"E_apparent = {look.fmt('S', r['app']['E_app'])}")
        self.refresh_display(reset=True)

    # ------------------------------------------------------------------------------------------------------ 6. results
    def build_results_box(self):
        lay = self.box("6. Results")
        self.field_combo = QComboBox()
        for name, key, kind, where in FIELDS:
            self.field_combo.addItem(name, key)
        self.field_combo.setCurrentIndex(4)
        self.field_combo.currentIndexChanged.connect(self.delayed_refresh)
        lay.addWidget(self.field_combo)
        lay.addWidget(row("Colours", look.cmap_combo(self.delayed_refresh)))
        self.def_check = QCheckBox("Show deformed shape")
        self.def_check.setChecked(True)
        self.def_check.toggled.connect(self.delayed_refresh)
        lay.addWidget(self.def_check)
        self.def_edit = QLineEdit("")
        self.def_edit.setPlaceholderText("auto")
        self.def_edit.editingFinished.connect(self.delayed_refresh)
        lay.addWidget(row("Deformation scale", self.def_edit))
        self.edges_check = QCheckBox("Show brick edges")
        self.edges_check.toggled.connect(self.delayed_refresh)
        lay.addWidget(self.edges_check)
        self.cut_check = QCheckBox("Cut the model open")
        self.cut_check.toggled.connect(self.delayed_refresh)
        self.cut_axis = QComboBox()
        self.cut_axis.addItems(AXES)
        self.cut_axis.currentIndexChanged.connect(self.delayed_refresh)
        self.cut_slider = QSlider(Qt.Orientation.Horizontal)
        self.cut_slider.setRange(0, 100)
        self.cut_slider.setValue(50)
        self.cut_slider.valueChanged.connect(self.delayed_refresh)
        lay.addWidget(self.cut_check)
        lay.addWidget(row("Cut across", self.cut_axis))
        lay.addWidget(row("Position", self.cut_slider))
        self.res_lbl = QLabel("")
        self.res_lbl.setWordWrap(True)
        self.res_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.res_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.res_lbl)
        adv = QGroupBox("Advanced: how the modulus is measured")
        adv.setCheckable(True)
        adv.setChecked(False)
        al = QVBoxLayout(adv)
        self.axis_combo = QComboBox()
        self.axis_combo.addItems(["Automatic", "Along X", "Along Y", "Along Z"])
        self.area_spin = look.UnitSpin("A", 0.0, 1e12, 0.0, 4, 1.0)
        self.len_spin = look.UnitSpin("L", 0.0, 1e9, 0.0, 4, 1.0)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(row("Direction", self.axis_combo))
        il.addWidget(row("Area (0 = automatic)", self.area_spin))
        il.addWidget(row("Length (0 = automatic)", self.len_spin))
        self.note(il, "E = (reaction force / area) / (movement / length). Automatic: the direction that has both a support and a loaded group, "
                      "the area is the bounding rectangle of the support and loaded groups, the length the distance between them.")
        inner.setVisible(False)
        adv.toggled.connect(inner.setVisible)
        al.addWidget(inner)
        lay.addWidget(adv)

    def show_result_text(self):
        r = self.result
        if r is None:
            self.res_lbl.setText("")
            return
        app, sol, model = r["app"], r["sol"], r["model"]
        f = F.AXES
        uf = model.full(sol["u"]).reshape(-1, 3)
        umax = float(np.linalg.norm(uf, axis=1).max())
        vm = float(r["fields"]["von Mises"].max())
        L = [f"<b>Apparent modulus along {AXES[r['axis']]}: {look.fmt('S', app['E_app'])}</b> ({app['E_app'] / r['E']:.4f} of the material E)",
             f"Reaction at '{app['support']}': {look.fmt('F', app['F'])}; '{app['load']}' moves {look.fmt('L', app['d'])} over {look.fmt('L', app['L'])}",
             f"Area {look.fmt('A', app['A'])}; strain {app['strain'] * 100:.3g} %; stress {look.fmt('S', app['stress'])}",
             f"max |u| = {look.fmt('L', umax)}", f"max von Mises = {look.fmt('S', vm)}", f"solve residual = {sol['residual']:.2e}",
             f"Solver: {sol['method']}, {sol['iterations']} iterations" + (f", {r['seconds']:.1f} s" if r.get("seconds") else "")]
        eq = sol.get("equilibrium")
        if eq:
            tot = [eq["reaction"][a] + eq["applied"][a] for a in range(3)]
            L.append("equilibrium (reactions + applied): " + ", ".join(f"sum F{'xyz'[a]} = {look.fmt('F', tot[a], 3)}" for a in range(3)))
            scale = max([abs(v) for v in eq["reaction"]] + [abs(v) for v in eq["applied"]] + [1e-30])
            if max(abs(v) for v in tot) > 1e-6 * scale:
                L.append("<b style='color:#b00020'>WARNING: the force balance is off, so this result cannot be trusted. Check that the supports stop all rigid-body motion.</b>")
        if sol["reactions"]:
            L.append("<b>Reactions</b>")
            for name, v in sol["reactions"].items():
                L.append(f"{name}: " + ", ".join(f"F{'xyz'[a]} {look.fmt('F', v[a], 4)}" for a in range(3)))
        if isinstance(model, OT.AdaptiveModel):
            L.append("Bricks: " + model.summary())
        for n in sol["notes"]:
            L.append(n.replace("WARNING", "<b style='color:#b00020'>WARNING</b>"))
        rf = r.get("refine")
        if rf:
            L.append("<br><b>Auto-refinement</b>")
            L.append("<pre style='margin:0'>" + f"{'size':>9} {'elements':>9} {'modulus':>13} {'change':>8}\n" + "\n".join(
                f"{look.fmt('L', s_, 4):>9} {n:>9,} {look.fmt('S', E, 5):>13} {'' if ch is None else f'{ch * 100:+.2f}%':>8}" for s_, n, E, ch in rf["rows"]) + "</pre>")
            col = "#1a7a1a" if rf["ok"] else "#b36b00"
            L.append(f"<b style='color:{col}'>{'Settled' if rf['ok'] else 'Not settled'}: {rf['why']}</b>")
        self.res_lbl.setText("<br>".join(L))

    def result_values(self, g, u_full, key, kind, where):
        fac = look.factor(kind)
        if where == "node":
            if key == "umag":
                return np.linalg.norm(u_full, axis=1) / fac
            return u_full[:, "xyz".index(key[1])] / fac
        return self.result["fields"][key] / fac

    def refresh_display(self, reset=False):
        r = self.result
        if r is None:
            return
        model = r["model"]
        u_full = model.full(r["sol"]["u"]).reshape(-1, 3)
        name, key, kind, where = FIELDS[self.field_combo.currentIndex()]
        scale = 0.0
        if self.def_check.isChecked():
            umax = float(np.linalg.norm(u_full, axis=1).max())
            xyz = model.node_xyz_all()
            size = float(np.ptp(xyz, axis=0).max())
            try:
                scale = float(self.def_edit.text()) if self.def_edit.text().strip() else (0.05 * size / umax if umax > 0 else 1.0)
            except ValueError:
                scale = 0.0
        g = model.grid(r["sol"]["u"], scale)
        vals = self.result_values(g, u_full, key, kind, where)
        (g.point_data if where == "node" else g.cell_data)[key] = vals
        if self.cut_check.isChecked():
            ax = self.cut_axis.currentIndex()
            c = model.centres()[:, ax]
            lo, hi = c.min(), c.max()
            keep = c <= lo + (hi - lo) * self.cut_slider.value() / 100.0
            if keep.any() and not keep.all():
                g = g.extract_cells(np.nonzero(keep)[0])
        v = g.point_data[key] if where == "node" else g.cell_data[key]
        hi = float(np.percentile(v, 99.5)) if len(v) else 1.0
        lo = float(np.percentile(v, 0.5)) if key in SIGNED else float(v.min()) if len(v) and key == "brick size" else 0.0
        title = f"{name} ({look.name(kind)})"
        self.clear_scene()
        self.put("result", g, scalars=key, cmap=look.cmap(), clim=[lo, hi if hi > lo else lo + 1e-9], show_edges=self.edges_check.isChecked(), line_width=0.4,
                 scalar_bar_args={"title": title, "vertical": False})
        self.draw_overlays()
        if reset:
            self.plotter.reset_camera()

    # ------------------------------------------------------------------------------------------------------ verification
    def build_verify_box(self):
        lay = self.box("Verification")
        lay.addWidget(button("Run the built-in checks", self.run_checks))
        self.verify_out = QPlainTextEdit()
        self.verify_out.setReadOnly(True)
        self.verify_out.setMinimumHeight(190)
        self.verify_out.setPlaceholderText("Compares the solver with exact answers (solid block, bars, beam theory, force groups, adaptive bricks against uniform ones). Takes about a minute.")
        lay.addWidget(self.verify_out)

    def run_checks(self, runner=None):
        runner = runner or VF.voxel_checks

        def done(rows):
            self.checks = rows
            ok = sum(1 for r in rows if r["ok"] is True)
            bad = sum(1 for r in rows if r["ok"] is False)
            self.verify_out.setPlainText(f"{ok} passed, {bad} failed\n\n" + VF.format_rows(rows))
            self.statusBar().showMessage(f"Checks: {ok} passed, {bad} failed.")
        self.run_task("Checks", runner, done)
