"""Mesh playground viewer: look at a mesh, select and delete facets, repair, refine / coarsen / remesh (by zone or by curvature), regularize,
subdivide, cut it, make a sketch from the cut and mesh the sketch.

    python viewer.py [file.stl]      (the full tabbed window, with the Voxel FEA and Mesh FEA tabs, is: python app.py)

Left: the tools.  Right: the 3D view (tab "3D") and the sketch made from a slice (tab "Sketch").
3D view: left drag turns, right drag / wheel zooms, middle drag pans.  In select mode (button or key S): left click selects a facet, left drag
draws a box, Shift adds, Ctrl removes; right drag turns the view.
Long jobs run in a background thread: the bar at the bottom shows what is happening and the time, Cancel stops it.
"""
import os
import sys
import time
import traceback

os.environ.setdefault("QT_API", "pyqt6")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QFrame, QCheckBox, QComboBox, QDialog, QDockWidget, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QProgressBar, QPushButton, QRubberBand, QScrollArea, QSlider, QTabWidget, QVBoxLayout, QWidget)

import look
import mesh2d as M2
import ui_kit
import picking as PK
import remesh as RM
import repair as R
import section as S
import shapes
from jobs import JobMixin, ProgressWindow, Worker
from tasks import Cancelled, sub, tick

MAX_UNDO = 20
SEL_COLOURS = ["#c9d3dc", "#ff7a00"]
BIG_SUBDIVISION = 2_000_000
MAX_SUBDIVISION = 8_000_000


from uiparts import button, row, spin  # noqa: F401  (the small widget helpers live in shared/ so other add-ons do not need the mesh viewer)


def triangles_in_order(m):
    """The mesh as plain triangles (same order as stored, so selections by number stay valid)."""
    return R.to_mesh(*R.arrays(m))


class Viewer(QMainWindow, JobMixin):
    def __init__(self, path=None, quiet=False, threaded=None):
        super().__init__()
        self.setWindowTitle("Mesh Playground")
        self.resize(1300, 800)
        self.quiet = quiet                  # tests: no message boxes
        self.threaded = (not quiet) if threaded is None else threaded
        self.last_error = ""
        self.mesh = None
        self.prev = None
        self.undo, self.redo = [], []
        self.zone_center = None
        self.sec = None
        self.sketch = None
        self.mesh2d = None
        self.actors = {}
        self.picking = False
        self.host = None
        self.corpus = None
        self.sel = np.zeros(0, bool)
        self.select_mode = False
        self.picker = None
        self.diagnosis = None
        self.problem_data = None
        self.busy = False
        self.thread = None
        self.worker = None
        self.job_cancelled = False
        self._drag = None

        self.tabs = QTabWidget()
        self.p3 = QtInteractor(self)
        look.set_bg(self.p3)
        self.p2 = QtInteractor(self)
        self.p2.set_background("white")
        self.tabs.addTab(self.p3.interactor, "3D")
        self.tabs.addTab(self.p2.interactor, "Sketch")
        self.setCentralWidget(self.tabs)
        self.band = QRubberBand(QRubberBand.Shape.Rectangle, self.p3.interactor)
        self.p3.interactor.installEventFilter(self)
        self.build_panel()
        self.build_statusbar()
        QShortcut(QKeySequence("S"), self, activated=lambda: self.sel_btn.toggle(), context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.slice_timer = QTimer(self)
        self.slice_timer.setSingleShot(True)
        self.slice_timer.timeout.connect(self.update_slice)
        self.statusBar().showMessage("Open an STL or load a test shape (the damaged ones are good for trying Repair).")
        if path:
            self.open_file(path)
        else:
            self.load_shape("bone")
        if not quiet:
            QTimer.singleShot(1500, self.report_renderer)

    def provide_mesh(self):
        """A copy of the current mesh for other tabs."""
        return None if self.mesh is None else self.mesh.copy()

    def send_to(self, kind):
        """Open the current mesh in a new analysis tab of the tabbed window (the same as File > Send this tab's mesh...)."""
        if self.host is None:
            return self.fail("Send", "This viewer is not inside the tabbed window - start it with python app.py.")
        if self.mesh is None:
            return self.fail("Send", "There is no mesh yet.")
        self.host.send_current(kind)

    # ------------------------------------------------------------------------------------------------------ panel
    def build_panel(self):
        w = QWidget()
        self.panel = w
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 2, 6, 6)
        lay.setSpacing(2)
        self.sections = []                   # the numbered, foldable blocks of the panel (the look of the FEA panels)

        def group(title):
            sec = ui_kit.Section("mesh", len(self.sections) + 1, title, True)
            self.sections.append(sec)
            lay.addWidget(sec)
            return sec.body

        g = group("Mesh")
        self.shape_box = QComboBox()
        self.shape_box.addItems(["blob", "torus", "bone", "scan", "bar", "blob_holes", "blob_flipped", "blob_spikes", "blob_fin",
                                 "blob_degenerate", "blob_floaters", "blob_all", "scan_all"])
        self.shape_box.setCurrentText("bone")
        g.addWidget(row(self.shape_box, button("Load test shape", lambda: self.load_shape(self.shape_box.currentText()))))
        g.addWidget(row(button("Open STL...", self.open_dialog), button("Save STL...", self.save_dialog)))
        g.addWidget(row(button("Send to Voxel FEA tab", lambda: self.send_to("voxel")), button("Send to Mesh FEA tab", lambda: self.send_to("tet"))))
        g.addWidget(row(button("Undo", self.do_undo), button("Redo", self.do_redo)))

        g = group("Select / delete facets")
        self.sel_btn = QPushButton("Select facets  (key S)")
        self.sel_btn.setCheckable(True)
        self.sel_btn.toggled.connect(self.set_select_mode)
        g.addWidget(self.sel_btn)
        self.cb_hidden = QCheckBox("Box select also takes hidden facets (through the model)")
        g.addWidget(self.cb_hidden)
        g.addWidget(row(button("Clear", self.sel_clear), button("Invert", self.sel_invert), button("Grow", self.sel_grow), button("Shrink", self.sel_shrink)))
        self.sel_lbl = QLabel("Click a facet, or drag a box. Shift adds, Ctrl removes.")
        self.sel_lbl.setWordWrap(True)
        g.addWidget(self.sel_lbl)
        g.addWidget(row(button("Delete selected", self.do_delete), button("Fill holes", self.do_fill_holes)))

        g = group("View")
        self.style_box = QComboBox()
        self.style_box.addItems(["Shaded", "Shaded + edges", "Wireframe"])
        self.style_box.currentIndexChanged.connect(lambda _=0: self.show_mesh(reset=False))
        g.addWidget(self.style_box)
        self.cb_problems = QCheckBox("Mark problems (open edges red, fins magenta, flipped orange)")
        self.cb_problems.setChecked(True)
        self.cb_problems.toggled.connect(lambda _=False: self.show_mesh(reset=False))
        g.addWidget(self.cb_problems)
        g.addWidget(button("Fit view", lambda: self.p3.reset_camera()))

        g = group("Diagnose")
        self.diag = QLabel("")
        self.diag.setWordWrap(True)
        g.addWidget(self.diag)

        g = group("Repair")
        self.hole_pct = spin(0, 100, 25, 0, 5, " %")
        g.addWidget(row("Fill holes up to", self.hole_pct, "of size"))
        self.cb_spikes = QCheckBox("Flatten spikes")
        self.cb_spikes.setChecked(True)
        g.addWidget(self.cb_spikes)
        g.addWidget(button("Repair", self.do_repair))
        self.repair_note = QLabel("")
        self.repair_note.setWordWrap(True)
        g.addWidget(self.repair_note)

        g = group("Facets")
        self.size = look.UnitSpin("L", 0.01, 1000, 3.0, 3, 0.5)
        g.addWidget(row("Target facet size", self.size))
        self.cb_zone = QCheckBox("Finer inside a zone (sphere)")
        self.cb_zone.toggled.connect(lambda _=False: self.draw_zone())
        g.addWidget(self.cb_zone)
        self.zone_btn = button("Pick zone centre, then click the surface", self.start_pick)
        g.addWidget(self.zone_btn)
        self.zone_r = look.UnitSpin("L", 0.1, 1000, 8.0, 2, 1)
        self.zone_s = look.UnitSpin("L", 0.01, 1000, 1.0, 3, 0.25)
        g.addWidget(row("Radius", self.zone_r, "size inside", self.zone_s))
        self.zone_r.valueChanged.connect(lambda _=0: self.draw_zone())
        self.zone_lbl = QLabel("Zone centre: not set")
        g.addWidget(self.zone_lbl)
        for t, f in (("Refine (smaller where needed)", self.do_refine), ("Coarsen (larger where allowed)", self.do_coarsen),
                     ("Remesh (both)", self.do_remesh)):
            g.addWidget(button(t, f))
        self.cb_after = QCheckBox("Regularize after coarsen / remesh")
        self.cb_after.setChecked(True)
        g.addWidget(self.cb_after)
        self.reduce_pct = spin(1, 99, 50, 0, 5, " %")
        g.addWidget(row(button("Reduce by", self.do_reduce), self.reduce_pct))
        g.addWidget(button("Show change vs previous (colour map)", self.show_deviation))

        g = group("Curvature (whole model)")
        self.c_max = look.UnitSpin("L", 0.01, 1000, 6.0, 3, 0.5)
        self.c_min = look.UnitSpin("L", 0.01, 1000, 1.5, 3, 0.25)
        self.c_ang = spin(2, 90, 20, 0, 5, "°")
        g.addWidget(row("Largest facet (flat parts)", self.c_max))
        g.addWidget(row("Smallest facet (tight curves)", self.c_min))
        g.addWidget(row("Turn per facet", self.c_ang))
        g.addWidget(button("Refine by curvature (only splits)", self.do_cur_refine))
        g.addWidget(button("Remesh by curvature (merges flat, splits curved)", self.do_cur_remesh))

        g = group("Regularize / subdivide")
        self.r_iter = spin(1, 30, 5, 0, 1)
        self.r_str = spin(0.05, 1.0, 0.5, 2, 0.1)
        self.r_crease = spin(5, 170, 40, 0, 5, "°")
        self.cb_flip = QCheckBox("Flip edges for better angles")
        self.cb_flip.setChecked(True)
        g.addWidget(row("Passes", self.r_iter, "Strength", self.r_str))
        g.addWidget(row("Keep creases sharper than", self.r_crease))
        g.addWidget(self.cb_flip)
        g.addWidget(button("Regularize (even out the triangles)", self.do_regularize))
        self.sub_level = spin(1, 5, 1, 0, 1)
        self.sub_level.valueChanged.connect(lambda _=0: self.update_sub_label())
        g.addWidget(row("Subdivision level", self.sub_level))
        self.cb_smooth_sub = QCheckBox("Smooth subdivision (rounds the surface a little)")
        g.addWidget(self.cb_smooth_sub)
        self.sub_lbl = QLabel("")
        g.addWidget(self.sub_lbl)
        g.addWidget(button("Subdivide", self.do_subdivide))

        g = group("Slice -> sketch -> mesh")
        self.axis = QComboBox()
        self.axis.addItems(["Z", "Y", "X"])
        self.axis.currentIndexChanged.connect(lambda _=0: self.slice_timer.start(150))
        g.addWidget(row("Cut across", self.axis))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(500)
        self.slider.valueChanged.connect(lambda _=0: self.slice_timer.start(150))
        g.addWidget(self.slider)
        self.slice_lbl = QLabel("")
        g.addWidget(self.slice_lbl)
        self.tol = spin(0.0, 20, 0.3, 2, 0.1, " % of size")
        g.addWidget(row("Sketch accuracy", self.tol))
        g.addWidget(button("Make sketch from slice", self.make_sketch))
        self.h2 = look.UnitSpin("L", 0.01, 1000, 2.0, 3, 0.5)
        g.addWidget(row("2D element size", self.h2))
        g.addWidget(button("Mesh the sketch", self.mesh_sketch))
        g.addWidget(row(button("Save sketch (DXF)...", self.save_dxf), button("Save 2D mesh...", self.save_mesh2d)))
        self.sketch_lbl = QLabel("")
        self.sketch_lbl.setWordWrap(True)
        g.addWidget(self.sketch_lbl)
        lay.addStretch(1)

        for b in w.findChildren(QPushButton):               # the action that moves the work on stands out, like Solve in the FEA tabs
            if b.text() == "Repair":
                ui_kit.primary(b)
                b.setMinimumHeight(34)
        sc = QScrollArea()
        sc.setWidget(w)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setMinimumWidth(380)
        dock = QDockWidget("", self)
        dock.setTitleBarWidget(QWidget())                    # no "Tools" strip: the bar on top says what this tab is
        dock.setWidget(sc)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.props_dock, self.panel_scroll = dock, sc
        bar = QWidget()                                      # the bar on top, as in the other tabs: what this is, and what is loaded
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(6, 5, 6, 5)
        bl.setSpacing(8)
        bl.addWidget(ui_kit.kind_chip("Mesh fixing", "#5f6b7a"))
        self.bar_lbl = QLabel("Nothing loaded yet")
        self.bar_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        bl.addWidget(self.bar_lbl, 1)
        self.setMenuWidget(bar)
        ui_kit.fit_dock(self, dock, w, lo=380, hi=560)
        self.update_sub_label()

    def build_statusbar(self):
        sb = self.statusBar()
        self.gpu_lbl = QLabel("Renderer: …")
        sb.addPermanentWidget(self.gpu_lbl)
        self.init_jobs()

    # ------------------------------------------------------------------------------------------------------ renderer (GPU) readout
    def report_renderer(self):
        txt = ""
        rw = self.p3.render_window
        try:
            if not rw.GetMapped() or rw.GetNeverRendered():              # nothing drawn yet: asking would crash VTK
                self.gpu_lbl.setText("Renderer: not drawn yet" if not self.quiet else "Renderer: unknown")
                self.renderer_name = ""
                if not self.quiet:
                    QTimer.singleShot(1500, self.report_renderer)
                return
            caps = rw.ReportCapabilities()
            for line in caps.splitlines():
                if "renderer string" in line.lower():
                    txt = line.split(":", 1)[1].strip()
                    break
        except Exception:
            pass
        self.renderer_name = txt
        if not txt:
            self.gpu_lbl.setText("Renderer: unknown")
            return
        weak = any(k in txt.lower() for k in ("intel", "llvmpipe", "software", "gdi generic", "basic render", "uhd", "iris"))
        self.gpu_lbl.setText(f"Renderer: {txt}" + ("   (not your fast GPU? see README, 'Using your graphics card')" if weak else ""))
        self.gpu_lbl.setStyleSheet("color: #c92a2a" if weak else "")

    def mesh_job(self, name, make, keep_undo=True, reset=False, note=None, clear_history=False):
        """make() runs now (reads the widgets) and returns f(progress) -> new mesh.  The mesh is checked in the thread, then shown."""
        try:
            f = make()
        except Exception as ex:
            return self.fail(name, ex)
        if f is None:
            return None
        n0 = self.mesh.n_cells if self.mesh is not None else 0

        def work(cb):
            m = f(sub(cb, 0.0, 0.85))
            m = triangles_in_order(m)
            ana = R.analyse(m, sub(cb, 0.85, 1.0))
            return m, ana

        def done(res):
            m, ana = res
            if clear_history:
                self.undo.clear()
                self.redo.clear()
                self.mesh = None
            self.set_mesh(m, (note or (lambda m_: f"{name}: {n0:,} -> {m_.n_cells:,} triangles"))(m), keep_undo=keep_undo, reset=reset, analysis=ana)
        return self.run_task(name, work, done)

    # ------------------------------------------------------------------------------------------------------ the mesh and its history
    def set_mesh(self, m, note="", keep_undo=True, reset=False, analysis=None):
        m = triangles_in_order(m) if not (m.is_all_triangles and not m.verts.size and not m.lines.size) else m
        if analysis is None:
            analysis = R.analyse(m)
        if self.mesh is not None and keep_undo:
            self.undo.append(self.mesh)
            del self.undo[:-MAX_UNDO]
            self.redo.clear()
        self.prev = self.mesh
        self.install(m, analysis, reset=reset or self.prev is None)
        if note:
            self.statusBar().showMessage(note)

    def install(self, m, analysis, reset=False):
        self.mesh = m
        if getattr(self, "bar_lbl", None) is not None:
            self.bar_lbl.setText(f"<b>{m.n_cells:,}</b> triangles")
        self.diagnosis = analysis["diag"]
        self.problem_data = analysis["problems"]
        self.sel = np.zeros(m.n_cells, bool)
        self.picker = None
        self.show_mesh(reset=reset)
        self.update_diag()
        self.update_slice()
        self.update_sel_label()
        self.update_sub_label()

    def go_history(self, source, target):
        if not source:
            return
        target.append(self.mesh)
        m = source.pop()
        self.prev = self.mesh
        self.run_task("History", lambda cb: R.analyse(m, cb), lambda ana: self.install(m, ana))

    def do_undo(self):
        self.go_history(self.undo, self.redo)

    def do_redo(self):
        self.go_history(self.redo, self.undo)

    # ------------------------------------------------------------------------------------------------------ files
    def load_shape(self, name):
        def make():
            if self.corpus is None:
                self.corpus = shapes.corpus()
            m = self.corpus[name].copy()
            return lambda cb: m
        self.mesh_job("Load", make, keep_undo=False, reset=True, clear_history=True, note=lambda m: f"Test shape '{name}' ({m.n_cells:,} triangles)")

    def open_file(self, path):
        def make():
            def f(cb):
                cb("Reading file", None)
                m = R.load(path)
                cb("Building triangles", None)
                return m
            return f
        self.mesh_job("Open", make, keep_undo=False, reset=True, clear_history=True,
                      note=lambda m: f"Opened {os.path.basename(path)} ({m.n_cells:,} triangles)")

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open mesh", "", "Meshes (*.stl *.obj *.ply *.vtk *.vtp);;All files (*)")
        if p:
            self.open_file(p)

    def save_dialog(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save mesh", "mesh.stl", "STL (*.stl)")
        if p:
            self.save_stl(p)

    def save_stl(self, p):
        m = self.mesh
        self.run_task("Save", lambda cb: (cb("Writing file", None), m.save(p))[1], lambda _r: self.statusBar().showMessage(f"Saved {p}"))

    # ------------------------------------------------------------------------------------------------------ display
    def clear_group(self, plotter, names):
        for n in names:
            a = self.actors.pop(n, None)
            if a is not None:
                plotter.remove_actor(a)

    def show_mesh(self, reset=False, scalars=None):
        if self.mesh is None:
            return
        p = self.p3
        self.clear_group(p, ["mesh", "open", "fin", "flip"])
        m = self.mesh
        st = self.style_box.currentText()
        kw = dict(show_edges=st == "Shaded + edges", style="wireframe" if st == "Wireframe" else "surface", smooth_shading=False, pickable=True)
        if scalars is not None:
            m.point_data["distance"] = scalars
            self.actors["mesh"] = p.add_mesh(m, scalars="distance", cmap="viridis", scalar_bar_args={"title": f"distance ({look.name('L')})"}, name="mesh", **kw)
        else:
            m.cell_data["sel"] = self.sel.astype(np.uint8)
            self.actors["mesh"] = p.add_mesh(m, scalars="sel", cmap=SEL_COLOURS, clim=[0, 1], show_scalar_bar=False, name="mesh", **kw)
        if self.cb_problems.isChecked() and self.problem_data is not None:
            pr = self.problem_data
            for key, col, nm in (("open", "red", "open"), ("nonmanifold", "magenta", "fin")):
                seg = pr[key]
                if len(seg):
                    pts = seg.reshape(-1, 3)
                    cells = np.hstack([np.full((len(seg), 1), 2), np.arange(len(pts)).reshape(-1, 2)]).ravel()
                    self.actors[nm] = p.add_mesh(pv.PolyData(pts, lines=cells), color=col, line_width=4, name=nm, pickable=False, render_lines_as_tubes=True)
            if len(pr["flipped"]):
                fl = pv.PolyData(pr["P"], np.hstack([np.full((len(pr["flipped"]), 1), 3), pr["T"][pr["flipped"]]]).ravel())
                self.actors["flip"] = p.add_mesh(fl, color="orange", name="flip", pickable=False)
        self.draw_zone()
        if reset:
            p.reset_camera()
        p.render()

    def update_diag(self):
        d = self.diagnosis
        lines = [R.describe(d), f"size {look.fmt('L', d['size'], 4)} · area {look.fmt('A', d['area'])}", "OK: one closed, oriented shell" if d["ok"] else "NEEDS REPAIR"]
        if d.get("min_angle") is not None:
            lines.append(f"worst triangle angle {d['min_angle']:.1f}° · edge length {d['edge_min']:.3g} .. {d['edge_max']:.3g}")
        self.diag.setText("\n".join(lines))

    def show_deviation(self):
        if self.prev is None:
            return self.fail("Compare", "There is no earlier version to compare with yet.")
        a, b = self.mesh, self.prev

        def work(cb):
            return RM.pts_to_mesh(np.asarray(a.points), b, progress=cb)

        def done(d):
            self.show_mesh(scalars=d)
            self.statusBar().showMessage(f"Distance to the previous version: max {look.fmt('L', d.max(), 4)}, mean {look.fmt('L', d.mean(), 4)}")
            self.last_dev = d
        self.last_dev = None
        self.run_task("Compare", work, done)
        return self.last_dev

    # ------------------------------------------------------------------------------------------------------ selecting and deleting facets
    def set_select_mode(self, on):
        self.select_mode = bool(on)
        w = self.p3.interactor
        try:
            if on:
                self.tabs.setCurrentIndex(0)
                self.p3.enable_custom_trackball_style(left=None, shift_left=None, control_left=None, right="rotate", control_right="rotate", shift_right="pan")
                w.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.p3.enable_trackball_style()
                w.unsetCursor()
        except Exception:
            pass

    def get_picker(self):
        if self.picker is None:
            self.picker = PK.Picker(self.mesh)
        return self.picker

    def apply_selection(self, mask, mode):
        """mode: 'replace', 'add' (Shift) or 'remove' (Ctrl)."""
        if mode == "add":
            self.sel = self.sel | mask
        elif mode == "remove":
            self.sel = self.sel & ~mask
        else:
            self.sel = mask.copy()
        self.refresh_selection()

    def refresh_selection(self):
        if self.actors.get("mesh") is not None and "sel" in self.mesh.cell_data:
            self.mesh.cell_data["sel"][:] = self.sel.astype(np.uint8)
            self.mesh.Modified()
        else:
            self.show_mesh(reset=False)
        self.update_sel_label()
        self.p3.render()

    def update_sel_label(self):
        n = int(self.sel.sum())
        self.sel_lbl.setText(f"{n:,} of {len(self.sel):,} facets selected" if n else "Nothing selected. Click a facet, or drag a box (Shift adds, Ctrl removes).")

    def select_click(self, gx, gy, mode="replace"):
        if self.mesh is None:
            return
        i = PK.click(self.p3, self.get_picker(), gx, gy)
        m = np.zeros(len(self.sel), bool)
        if i >= 0:
            m[i] = True
        if mode == "replace" and i < 0:
            self.apply_selection(m, "replace")
        elif i >= 0:
            self.apply_selection(m, "remove" if (mode == "add" and self.sel[i]) else mode)

    def select_box(self, gx0, gy0, gx1, gy1, mode="replace"):
        if self.mesh is None:
            return
        picker, hidden = self.get_picker(), self.cb_hidden.isChecked()
        plotter = self.p3
        self.run_task("Box select", lambda cb: PK.box(plotter, picker, gx0, gy0, gx1, gy1, hidden=hidden, progress=cb), lambda m: self.apply_selection(m, mode))

    def sel_clear(self):
        self.apply_selection(np.zeros(len(self.sel), bool), "replace")

    def sel_invert(self):
        self.apply_selection(~self.sel, "replace")

    def _T(self):
        return self.mesh.faces.reshape(-1, 4)[:, 1:]

    def sel_grow(self):
        if self.sel.any():
            self.apply_selection(PK.grow(self._T(), self.sel), "replace")

    def sel_shrink(self):
        if self.sel.any():
            self.apply_selection(PK.shrink(self._T(), self.sel), "replace")

    def do_delete(self):
        if not self.sel.any():
            return self.fail("Delete", "Nothing is selected.")
        sel, mesh = self.sel.copy(), self.mesh
        n = int(sel.sum())

        def make():
            def f(cb):
                P, T = R.arrays(mesh)
                P2, T2 = R.drop_unused(P, T[~sel])
                return R.to_mesh(P2, T2)
            return f
        self.mesh_job("Delete", make, note=lambda m: f"Deleted {n:,} facets ({mesh.n_cells:,} -> {m.n_cells:,}). The hole is open: press Fill holes to close it.")

    def do_fill_holes(self):
        mesh, frac = self.mesh, self.hole_pct.value() / 100.0

        def make():
            def f(cb):
                P, T = R.arrays(mesh)
                cb("Filling holes", None)
                notes = []
                P, T = R.fill_holes(P, T, frac * R.diag_of(P), notes, max_edges=5000)
                T = R.orient(P, T, [])
                P, T = R.drop_unused(P, T)
                self.fill_notes = notes
                return R.to_mesh(P, T)
            return f
        self.mesh_job("Fill holes", make, note=lambda m: "Fill holes: " + ("; ".join(getattr(self, "fill_notes", [])) or "no open loops within the size limit"))

    # ------------------------------------------------------------------------------------------------------ mouse in the 3D view
    def eventFilter(self, obj, ev):
        if obj is self.p3.interactor and self.select_mode and not self.busy and self.mesh is not None:
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
                if (a - b).manhattanLength() < 4:
                    self.select_click(*PK.qt_to_gl(self.p3, b.x(), b.y(), ratio), mode=mode)
                else:
                    (x0, y0), (x1, y1) = PK.qt_to_gl(self.p3, a.x(), a.y(), ratio), PK.qt_to_gl(self.p3, b.x(), b.y(), ratio)
                    self.select_box(x0, y0, x1, y1, mode=mode)
                return True
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------------------------------------------------ operations
    def do_repair(self):
        hole, spikes = self.hole_pct.value() / 100.0, self.cb_spikes.isChecked()
        mesh = self.mesh
        self.repair_report = None

        def make():
            def f(cb):
                fixed, rep = R.repair(mesh, hole_fraction=hole, spikes=spikes, progress=cb)
                self.repair_report = rep
                return fixed
            return f
        self.mesh_job("Repair", make, note=lambda m: "Repaired")
        if not self.threaded and self.repair_report:
            self.show_repair_note()
        elif self.threaded:
            QTimer.singleShot(0, self.after_repair)
        return self.repair_report

    def after_repair(self):
        if self.busy:
            QTimer.singleShot(200, self.after_repair)
        else:
            self.show_repair_note()

    def show_repair_note(self):
        rep = self.repair_report
        if rep:
            self.repair_note.setText("Before: " + R.describe(rep["before"]) + "\nDone: " + ("; ".join(rep["notes"]) or "nothing to do"))

    def zones(self):
        if not self.cb_zone.isChecked():
            return []
        if self.zone_center is None:
            raise ValueError("Pick the zone centre first (button, then click on the surface), or untick the zone.")
        return [{"kind": "sphere", "center": tuple(self.zone_center), "radius": self.zone_r.internal(), "size": self.zone_s.internal()}]

    def reg_args(self):
        return dict(iterations=int(self.r_iter.value()), strength=self.r_str.value(), crease_deg=self.r_crease.value(), flips=self.cb_flip.isChecked())

    def op(self, name, build, after=False, zones=True):
        """build(mesh, zones, progress) -> mesh, where the widget values are read now."""
        mesh = self.mesh
        reg = self.reg_args()
        use_after = after and self.cb_after.isChecked()

        def make():
            z = self.zones() if zones else None
            base = self.size.internal()

            def f(cb):
                m = build(mesh, z, cb if not use_after else sub(cb, 0.0, 0.8))
                if use_after:
                    m = RM.regularize(m, reference=mesh, progress=sub(cb, 0.8, 1.0), **reg)
                return m
            return f
        self.mesh_job(name, make, note=lambda m: f"{name}: {mesh.n_cells:,} -> {m.n_cells:,} triangles" + (" + regularized" if use_after else ""))

    def do_refine(self):
        base = self.size.internal()
        self.op("Refine", lambda m, z, cb: RM.refine(m, base, z, progress=cb))

    def do_coarsen(self):
        base = self.size.internal()
        self.op("Coarsen", lambda m, z, cb: RM.coarsen(m, base, z, progress=cb), after=True)

    def do_remesh(self):
        base = self.size.internal()
        self.op("Remesh", lambda m, z, cb: RM.remesh(m, base, z, progress=cb), after=True)

    def do_reduce(self):
        frac = self.reduce_pct.value() / 100.0
        self.op("Reduce", lambda m, z, cb: (tick(cb, "Reducing (quadric decimation)", None), RM.reduce(m, frac))[1], zones=False)

    def cur_zone(self):
        return [{"kind": "curvature", "size": self.c_min.internal(), "angle": float(np.radians(self.c_ang.value()))}]

    def do_cur_refine(self):
        mx, cz = self.c_max.internal(), self.cur_zone()
        self.op("Refine by curvature", lambda m, z, cb: RM.refine(m, mx, cz, progress=cb), zones=False)

    def do_cur_remesh(self):
        mx, cz = self.c_max.internal(), self.cur_zone()
        self.op("Remesh by curvature", lambda m, z, cb: RM.remesh(m, mx, cz, progress=cb), after=True, zones=False)

    def do_regularize(self):
        reg, mesh = self.reg_args(), self.mesh
        self.mesh_job("Regularize", lambda: (lambda cb: RM.regularize(mesh, reference=mesh, progress=cb, **reg)),
                      note=lambda m: f"Regularized ({int(m.field_data['flips'][0]) if 'flips' in m.field_data else 0} edge flips)")

    def update_sub_label(self):
        if self.mesh is None:
            self.sub_lbl.setText("")
            return
        n = RM.subdivide_count(self.mesh.n_cells, int(self.sub_level.value()))
        txt = f"{self.mesh.n_cells:,} -> {n:,} triangles"
        if n > MAX_SUBDIVISION:
            txt += "   TOO MANY: lower the level"
        elif n > BIG_SUBDIVISION:
            txt += "   (large: slow to draw)"
        self.sub_lbl.setText(txt)
        self.sub_lbl.setStyleSheet("color: #c92a2a" if n > BIG_SUBDIVISION else "")

    def do_subdivide(self):
        lvl, smooth, mesh = int(self.sub_level.value()), self.cb_smooth_sub.isChecked(), self.mesh
        if RM.subdivide_count(mesh.n_cells, lvl) > MAX_SUBDIVISION:
            return self.fail("Subdivide", f"Level {lvl} would make {RM.subdivide_count(mesh.n_cells, lvl):,} triangles; the limit is {MAX_SUBDIVISION:,}.")
        self.mesh_job("Subdivide", lambda: (lambda cb: RM.subdivide(mesh, lvl, smooth=smooth, progress=cb)),
                      note=lambda m: f"Subdivided level {lvl}: {mesh.n_cells:,} -> {m.n_cells:,} triangles")

    # ------------------------------------------------------------------------------------------------------ zone picking
    def start_pick(self):
        self.tabs.setCurrentIndex(0)
        self.sel_btn.setChecked(False)
        self.picking = True
        self.zone_btn.setText("Click on the surface...")
        self.p3.enable_surface_point_picking(callback=self.zone_picked, show_point=False, show_message=False, left_clicking=True)

    def zone_picked(self, pt, *args):
        if pt is None or not self.picking:
            return
        self.set_zone(np.asarray(pt, float))

    def set_zone(self, pt):
        self.picking = False
        self.zone_center = np.asarray(pt, float)
        self.zone_btn.setText("Pick zone centre, then click the surface")
        self.zone_lbl.setText("Zone centre: %.2f, %.2f, %.2f" % tuple(self.zone_center))
        self.cb_zone.setChecked(True)
        try:
            self.p3.disable_picking()
        except Exception:
            pass
        self.draw_zone()

    def draw_zone(self):
        self.clear_group(self.p3, ["zone"])
        if self.zone_center is not None and self.cb_zone.isChecked():
            sph = pv.Sphere(radius=self.zone_r.internal(), center=self.zone_center, theta_resolution=40, phi_resolution=40)
            self.actors["zone"] = self.p3.add_mesh(sph, color="#e8590c", opacity=0.25, name="zone", pickable=False)
            self.p3.render()

    # ------------------------------------------------------------------------------------------------------ slice -> sketch -> mesh
    def plane(self):
        k = "XYZ".index(self.axis.currentText())
        b = self.mesh.bounds
        lo, hi = b[2 * k], b[2 * k + 1]
        pos = lo + (hi - lo) * self.slider.value() / 1000.0
        o = np.array([(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2])
        o[k] = pos
        n = np.zeros(3)
        n[k] = 1.0
        return o, n, pos

    def update_slice(self):
        self.clear_group(self.p3, ["slice", "plane"])
        if self.mesh is None:
            return
        o, n, pos = self.plane()
        self.slice_lbl.setText(f"{self.axis.currentText()} = {look.fmt('L', pos, 4)}")
        try:
            self.sec = S.cut(self.mesh, o, n, which="all")
        except Exception as ex:
            self.sec = None
            self.slice_lbl.setText(self.slice_lbl.text() + f"   ({ex})")
            self.p3.render()
            return
        pts, cells = [], []
        for ring in M2.loops(self.sec.poly):
            r3 = self.sec.to3d(np.vstack([ring, ring[:1]]))
            cells += [len(r3)] + list(range(len(pts), len(pts) + len(r3)))
            pts += list(r3)
        self.actors["slice"] = self.p3.add_mesh(pv.PolyData(np.array(pts), lines=np.array(cells)), color="#1c7ed6", line_width=4, name="slice",
                                                pickable=False, render_lines_as_tubes=True)
        self.p3.render()

    def make_sketch(self):
        try:
            if self.sec is None:
                raise ValueError("The plane does not cut the mesh here (or the cut is not closed): repair the mesh or move the plane.")
            size = max(self.sec.poly.bounds[2] - self.sec.poly.bounds[0], self.sec.poly.bounds[3] - self.sec.poly.bounds[1])
            self.sketch = M2.simplify(self.sec.poly, self.tol.value() / 100.0 * size)
            self.mesh2d = None
            self.draw_sketch()
            lp = M2.loops(self.sketch)
            dev = self.sec.poly.hausdorff_distance(self.sketch)
            self.sketch_lbl.setText(f"Sketch: {len(lp)} loop(s), {sum(len(l) for l in lp)} lines, area {look.fmt('A', self.sketch.area)} "
                                    f"(cut {look.fmt('A', self.sec.poly.area)}), largest deviation {look.fmt('L', dev, 3)}")
            self.tabs.setCurrentIndex(1)
        except Exception as ex:
            self.fail("Sketch", ex)

    def draw_sketch(self):
        p = self.p2
        self.clear_group(p, ["s_lines", "s_pts", "s_mesh"])
        if self.sketch is None:
            return
        pts, cells, allp = [], [], []
        for ring in M2.loops(self.sketch):
            r = np.column_stack([ring, np.zeros(len(ring))])
            cells += [len(r) + 1] + list(range(len(pts), len(pts) + len(r))) + [len(pts)]
            pts += list(r)
            allp += list(r)
        self.actors["s_lines"] = p.add_mesh(pv.PolyData(np.array(pts), lines=np.array(cells)), color="black", line_width=2, name="s_lines")
        self.actors["s_pts"] = p.add_mesh(pv.PolyData(np.array(allp)), color="#1c7ed6", point_size=7, render_points_as_spheres=True, name="s_pts")
        if self.mesh2d is not None:
            nodes, tris = self.mesh2d
            g = pv.PolyData(np.column_stack([nodes, np.zeros(len(nodes))]), np.hstack([np.full((len(tris), 1), 3), tris]).ravel())
            self.actors["s_mesh"] = p.add_mesh(g, color="#d0ebff", show_edges=True, edge_color="#4263eb", name="s_mesh", lighting=False)
        p.view_xy()
        p.enable_parallel_projection()
        p.enable_image_style()
        p.reset_camera()
        p.render()

    def mesh_sketch(self):
        try:
            if self.sketch is None:
                self.make_sketch()
                if self.sketch is None:
                    return
            nodes, tris = M2.mesh_polygon(self.sketch, self.h2.internal())
            self.mesh2d = (nodes, tris)
            st = M2.stats(nodes, tris)
            self.draw_sketch()
            self.sketch_lbl.setText(self.sketch_lbl.text().split("\n")[0] + f"\nMesh: {st['triangles']} triangles, {st['nodes']} nodes, "
                                    f"edges {look.fmt('L', st['edge_min'], 3)} .. {look.fmt('L', st['edge_max'], 3)}, area {look.fmt('A', st['area'])}")
            self.tabs.setCurrentIndex(1)
        except Exception as ex:
            self.fail("Mesh sketch", ex)

    def save_dxf(self):
        if self.sketch is None:
            return self.fail("Save sketch", "Make a sketch first.")
        p, _ = QFileDialog.getSaveFileName(self, "Save sketch", "sketch.dxf", "DXF (*.dxf)")
        if p:
            M2.write_dxf(self.sketch, p)

    def save_mesh2d(self):
        if self.mesh2d is None:
            return self.fail("Save 2D mesh", "Mesh the sketch first.")
        p, _ = QFileDialog.getSaveFileName(self, "Save 2D mesh", "sketch_mesh.vtk", "VTK (*.vtk)")
        if p:
            nodes, tris = self.mesh2d
            pv.PolyData(np.column_stack([nodes, np.zeros(len(nodes))]), np.hstack([np.full((len(tris), 1), 3), tris]).ravel()).save(p)


def main():
    from app import main as app_main
    app_main()


if __name__ == "__main__":
    main()
