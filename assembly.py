"""
assembly.py - the assembly workspace (one tab of the program).

  * Project tree: the assembly, its components (with their origin planes) and its mates.
  * Insert Components: pick part files (.gpd); the first one is fixed in place, the others float.
  * Move Component / Rotate Component: drag a component in the view; a component with mates slides only where the mates allow.
  * Mate: click two items (face, edge, point, or a component's origin plane in the tree), choose the mate type, press the green check.
  * Component patterns and Mirror Components: derived copies of the chosen components.
  * Edit Component opens the part in its own tab.
"""
import copy
import math
import os
import traceback

import numpy as np
from PyQt6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QBrush, QColor
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton, QRadioButton, QButtonGroup, QTabWidget,
                             QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import asm_model as am
import asm_refs
import asm_sub
import config_panels
import mini_tree
import icons
import pm_model as pm
import pm_app
import nav
import viewpick

try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
except Exception as _ex:                                   # the window still opens; the view says what is missing
    pv, QtInteractor = None, None
    VIEW_ERROR = f"{type(_ex).__name__}: {_ex}"
else:
    VIEW_ERROR = None

PALETTE = [(0.62, 0.70, 0.82), (0.84, 0.72, 0.60), (0.66, 0.80, 0.66), (0.80, 0.66, 0.80), (0.82, 0.80, 0.60), (0.60, 0.80, 0.82)]
SEL_COL, HI_COL = (0.45, 0.72, 1.0), (1.0, 0.45, 0.0)
MATE_NAMES = {"coincident": "Coincident", "parallel": "Parallel", "perpendicular": "Perpendicular", "tangent": "Tangent",
              "concentric": "Concentric", "lock": "Lock", "distance": "Distance", "angle": "Angle", "symmetric": "Symmetric"}
MATE_HELP = {"coincident": "face/face, point/point, point/face, edge/edge, ...", "parallel": "faces or edges parallel",
             "perpendicular": "faces or edges at 90 degrees", "tangent": "flat face, cylinder, sphere or straight edge touching a curved face",
             "concentric": "cylinders / circles share an axis", "lock": "the two components keep their position to each other",
             "distance": "type the distance", "angle": "type the angle", "symmetric": "pick two items, then the mirror plane"}


class ViewGeom:
    """The small bit of the sketch editor that the navigation code asks the app for: view size, rays and projection."""

    def __init__(self, plotter):
        self.pl = plotter
        self.size_fn = self.default_size

    def default_size(self):
        r = self.pl.devicePixelRatioF()
        return max(1.0, self.pl.width() * r), max(1.0, self.pl.height() * r)

    def matrix(self):
        W, H = self.size_fn()
        m = self.pl.camera.GetCompositeProjectionTransformMatrix(W / H, -1, 1)
        return np.array([[m.GetElement(i, j) for j in range(4)] for i in range(4)]), W, H

    def to_screen(self, P):
        M, W, H = self.matrix()
        P = np.atleast_2d(np.asarray(P, float))
        h = np.hstack([P, np.ones((len(P), 1))]) @ M.T
        return np.column_stack([(h[:, 0] / h[:, 3] + 1) / 2 * W, (h[:, 1] / h[:, 3] + 1) / 2 * H])

    def ray(self, px, py):
        M, W, H = self.matrix()
        inv = np.linalg.inv(M)
        pts = []
        for z in (-1.0, 1.0):
            v = inv @ np.array([2 * px / W - 1, 2 * py / H - 1, z, 1.0])
            pts.append(v[:3] / v[3])
        return pts[0], pts[1] - pts[0]

    @property
    def active(self):
        return False


class DragHook(QObject):
    """Left-button drags for Move / Rotate Component.  Installed before the navigation hook."""

    def __init__(self, plotter, win):
        super().__init__(plotter)
        self.win, self.pl = win, plotter
        self.state = None
        from PyQt6.QtWidgets import QWidget as _W
        for w in [plotter] + list(plotter.findChildren(_W)):
            w.installEventFilter(self)

    def xy(self, obj, ev):
        r = obj.devicePixelRatioF()
        p = ev.position()
        return p.x() * r, (obj.height() - p.y() - 1) * r

    def eventFilter(self, obj, ev):
        try:
            if self.win.mode not in ("move", "rotate"):
                return False
            t = ev.type()
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                x, y = self.xy(obj, ev)
                self.state = self.win.drag_begin(x, y)
            elif t == QEvent.Type.MouseMove and self.state is not None and (ev.buttons() & Qt.MouseButton.LeftButton):
                x, y = self.xy(obj, ev)
                self.win.drag_move(self.state, x, y)
            elif t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton and self.state is not None:
                self.win.drag_end(self.state)
                self.state = None
        except Exception:
            self.state = None
            self.win.say("Drag failed: " + traceback.format_exc(limit=2))
        return False


class AssemblyWindow(QMainWindow):
    ribbon_page = pm_app.MainWindow.ribbon_page
    add_sim = pm_app.MainWindow.add_sim
    add_render = pm_app.MainWindow.add_render
    make_menu = pm_app.MainWindow.make_menu

    def __init__(self, path=None, shell=None):
        super().__init__()
        self.shell = shell
        self.asm = am.Assembly()
        self.wire(self.asm)
        self.path = None
        self.undo, self.redo = [], []
        self.sel_comp = None
        self.mode = None                  # None | "move" | "rotate" | "mate" | "pattern" | "mirror"
        self.mate_sel, self.mate_type, self.mate_opts, self.mate_pre = [], None, {}, None
        self.mate_edit = None             # while editing: {'orig': mate, 'idx': position in the list}
        self.pat = None                   # the pattern / mirror being edited
        self.rg = None                    # the reference plane / axis being made
        self.world_geo = []
        asm_refs.init_vis(self)
        self.entries = {}                 # component id -> scene data
        self.hi_actors = []
        self.mesh_cache = {}              # (part path, id(solid)) -> (mesh, edge polylines, local bbox centre)
        self.part_cache = {}              # absolute path -> (mtime, Document)
        self.doc_memo = {}                # (part path, configuration) -> Document, cleared when parts may have changed
        self.busy = False
        self.cam = None
        self.nav = None
        self.hook = None
        self.act = {}
        self.menu_btns = {}
        self.plotter = None
        self.build_ui()
        if path and os.path.exists(path):
            self.open_file(path)
        self.update_all(fit=True)

    # ------------------------------------------------------------------ window
    def build_ui(self):
        self.flip_act = QAction("Zoom: wheel toward you = in", self)
        self.flip_act.setCheckable(True)
        self.flip_act.setChecked(True)
        self.flip_act.toggled.connect(lambda on: self.nav.flip_zoom(not on) if self.nav is not None else None)
        self.ribbon = QTabWidget()
        self.ribbon.setFixedHeight(104)
        self.ribbon.setDocumentMode(True)
        self.ribbon.setTabPosition(QTabWidget.TabPosition.South)
        self.ribbon.addTab(self.ribbon_page([
            ("insert", "▣", "Insert\nComponents", "Add parts (.gpd files) to the assembly", lambda: self.insert_dialog()),
            ("menu_cmd", "✥", "Move\nComponent", "Drag a component (Move) or turn it (Rotate)", [
                ("Move Component", lambda: self.set_mode("move")), ("Rotate Component", lambda: self.set_mode("rotate"))]),
            "|",
            ("mate", "⚯", "Mate", "Click two items, choose the mate, press the green check", lambda: self.mate_start()),
            "|",
            ("menu_cmd", "☷", "Linear Component\nPattern", "Repeat components in a line or around an axis", [
                ("Linear Component Pattern", lambda: self.pattern_start("linear")),
                ("Circular Component Pattern", lambda: self.pattern_start("circular"))]),
            ("mirror", "⧓", "Mirror\nComponents", "Mirror components about a plane or a flat face", lambda: self.pattern_start("mirror")),
            "|",
            ("edit", "✎", "Edit\nComponent", "Open the selected component's part in its own tab", lambda: self.edit_component()),
            "|",
            ("menu_cmd", "▱", "Reference\nGeometry", "Planes and axes built from the components (to mate to, mirror about...)", [
                ("Plane", lambda: asm_refs.start(self, "refplane")), ("Axis", lambda: asm_refs.start(self, "refaxis"))]),
        ]), "Assembly Features")
        self.ribbon.addTab(self.ribbon_page([
            ("mass", "⚖", "Mass\nProperties", "Mass, center of mass and moments of inertia of the whole assembly", lambda: self.mass_open()),
        ]), "Evaluate")
        self.ribbon.addTab(self.ribbon_page([("sim_fea", "▦", "2D FEA", "Plane stress / strain FEA of a slice through this assembly", lambda: self.add_sim("fea")),
                                    ("sim_cfd", "≋", "2D CFD", "Flow around a slice through this assembly", lambda: self.add_sim("cfd"))]), "Simulation")
        self.ribbon.addTab(self.ribbon_page([("render_new", "◉", "New render", "Photorealistic pictures and videos of this assembly: sun, lights, floor, cameras", lambda: self.add_render())]), "Renderer")
        self.left = QTabWidget()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.tree.currentItemChanged.connect(self.tree_selected)
        self.tree.itemDoubleClicked.connect(self.tree_double)
        self.tree.itemChanged.connect(self.tree_checked)
        self.left.setIconSize(QSize(26, 26))
        self.left.addTab(self.tree, icons.icon("tab tree", 26), "")
        self.left.setTabToolTip(0, "Assembly tree")
        self.props = QWidget()
        self.props_lay = QVBoxLayout(self.props)
        self.props_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.left.addTab(self.props, icons.icon("tab properties", 26), "")
        self.left.setTabToolTip(1, "Properties")
        self.cfg_panel = config_panels.ConfigPanel(self, "assembly")
        self.left.addTab(self.cfg_panel, icons.icon("tab configurations", 26), "")
        self.left.setTabToolTip(2, "Configurations")
        self.disp_panel = config_panels.DisplayPanel(self)
        self.left.addTab(self.disp_panel, icons.icon("tab display", 26), "")
        self.left.setTabToolTip(3, "Display")
        self.left.setMinimumWidth(340)
        self.left.setMaximumWidth(460)
        view = QWidget()
        vl = QVBoxLayout(view)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(self.ribbon)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self.left, 0)
        if pv is None:
            body.addWidget(QLabel("The 3D view needs:  pip install pyvista pyvistaqt\n\n" + (VIEW_ERROR or "")), 1)
        else:
            self.plotter = QtInteractor(self)
            right = QWidget()
            rl = QVBoxLayout(right)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(0)
            rl.addWidget(asm_refs.make_show_bar(self))
            rl.addWidget(self.plotter, 1)
            body.addWidget(right, 1)
            self.mini = mini_tree.MiniTree(self, self.plotter)
            try:
                self.plotter.set_background("#f7f9fc", top="#cfd9ea")
                self.plotter.renderer.enable_lightkit()
                self.plotter.enable_anti_aliasing("fxaa")
            except Exception:
                pass
            self.plotter.add_axes()
            self.ed = ViewGeom(self.plotter)
            self.hook = viewpick.ClickHook(self.plotter, self.on_click)
            self.drag_hook = DragHook(self.plotter, self)
            self.nav = nav.NavHook(self.plotter, self)         # installed last: it sees the mouse events first
            self.flip_act.blockSignals(True)
            self.flip_act.setChecked(self.nav.wheel_sign == 1)
            self.flip_act.blockSignals(False)
        vl.addLayout(body, 1)
        self.setCentralWidget(view)
        self.statusBar().showMessage("Insert Components to start the assembly.")
        from PyQt6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=lambda: self.set_mode(None))
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self.delete_selected)

    def say(self, text):
        self.statusBar().showMessage(text)

    def title(self):
        return os.path.basename(self.path) if self.path else "Assembly1"

    def undo_pop(self):
        if self.undo:
            self.undo.pop()

    # ----- what the Configurations and Display tabs ask of the window
    def cfg_model(self):
        return self.asm

    def cfg_choices(self, key):
        if key.startswith("c:"):
            c = self.asm.comp(key[2:])
            return self.asm.part_cfgs_fn(c) if c is not None else []
        return None

    def cfg_candidates(self):
        return self.asm.cfg_candidates()

    def config_changed(self):
        self.doc_memo.clear()
        self.asm._cache.clear()
        self.solve_all()
        self.update_all()
        self.show_comp_props()

    def display_items(self):
        out = []
        for k, c in enumerate(self.asm.components):
            if not c.get("derived"):
                out.append((c["name"], c, "hidden", PALETTE[k % len(PALETTE)]))
        return out

    def display_changed(self):
        self.update_all()

    def display_live(self):
        for cid, e in self.entries.items():
            c = self.asm.comp(cid)
            try:
                e["actor"].prop.opacity = self.opacity_of(c)
            except Exception:
                pass
        if self.plotter is not None:
            self.plotter.render()

    # ------------------------------------------------------------------ parts
    def abs(self, p):
        if os.path.isabs(p) or not self.path:
            return p
        return os.path.normpath(os.path.join(os.path.dirname(self.path), p))

    def wire(self, a):
        a.solid_fn = self.solid_of
        a.refgeo_fn = lambda c: (lambda d: d.refgeo if d is not None else {})(self.part_doc(c))
        a.part_cfg_fn = lambda c: (lambda d: d.cfg["active"] if d is not None else None)(self.part_base(c))
        a.part_cfgs_fn = lambda c: (lambda d: list(d.cfg["names"]) if d is not None else [])(self.part_base(c))

    def part_base(self, c):
        """The part's Document as it is in its own tab / file (whatever configuration is active there)."""
        if c.get("derived"):
            c = self.asm.comp(c["derived"]["src"]) or c
        p = self.abs(c["path"])
        if p.lower().endswith(".gpa"):
            try:
                return asm_sub.sub_doc(self, p, None)
            except asm_sub.SubLoop:
                if hasattr(self, "stack"):          # inside a sub-assembly load: let the loop be reported
                    raise
                return None
        if self.shell is not None:
            d = self.shell.part_doc(p)
            if d is not None:
                return d
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return None
        hit = self.part_cache.get(p)
        if hit is None or hit[0] != mt:
            try:
                d = pm.Document.from_json(open(p, encoding="utf-8").read())
                d.rebuild()
            except Exception:
                return None
            hit = (mt, d)
            self.part_cache[p] = hit
        return hit[1]

    def part_doc(self, c):
        """The Document of a component in the configuration the component asks for."""
        if c.get("derived"):
            c = self.asm.comp(c["derived"]["src"]) or c
        key = (c["path"], c.get("config"))
        if key in self.doc_memo:
            return self.doc_memo[key]
        if c["path"].lower().endswith(".gpa"):
            try:
                doc = asm_sub.sub_doc(self, self.abs(c["path"]), c.get("config"))
            except asm_sub.SubLoop:
                if hasattr(self, "stack"):
                    raise
                doc = None
            self.doc_memo[key] = doc
            return doc
        base = self.part_base(c)
        doc = base
        cfg = c.get("config")
        if base is not None and cfg and cfg in base.cfg["names"] and cfg != base.cfg["active"]:
            try:
                doc = base.copy()
                doc.cfg_apply(cfg)
                doc.rebuild()
            except Exception:
                doc = base
        self.doc_memo[key] = doc
        return doc

    def solid_of(self, c):
        if c.get("derived"):
            src = self.asm.comp(c["derived"].get("src"))
            c = src or c
        d = self.part_doc(c)
        return d.solid if d is not None else None

    # ------------------------------------------------------------------ files / undo
    def snapshot(self):
        self.undo.append((self.asm.to_json(), self.sel_comp))
        del self.undo[:-60]
        self.redo.clear()

    def restore(self, js, sel):
        a = am.Assembly.from_json(js)
        self.wire(a)
        self.doc_memo.clear()
        self.asm, self.sel_comp = a, sel
        self.mate_edit = None
        self.rg = None
        self.set_mode(None, quiet=True)
        self.solve_all()
        self.update_all()

    def do_undo(self):
        if self.undo:
            self.redo.append((self.asm.to_json(), self.sel_comp))
            self.restore(*self.undo.pop())

    def do_redo(self):
        if self.redo:
            self.undo.append((self.asm.to_json(), self.sel_comp))
            self.restore(*self.redo.pop())

    def new_doc(self):
        self.snapshot()
        self.asm = am.Assembly()
        self.wire(self.asm)
        self.path = None
        self.update_all(fit=True)

    def open_file(self, p):
        try:
            self.asm = am.Assembly.from_json(open(p, encoding="utf-8").read())
            self.wire(self.asm)
            self.doc_memo.clear()
            self.path = p
            self.undo, self.redo = [], []
            self.sel_comp = None
            self.solve_all()
            self.saved_json = self.asm.to_json()
        except Exception as ex:
            QMessageBox.warning(self, "Open", str(ex))

    def save(self, as_new=False):
        import sim_links
        old_base = sim_links.base_dir(self)
        if as_new or not self.path:
            p, _ = QFileDialog.getSaveFileName(self, "Save assembly", "assembly.gpa", "Assembly (*.gpa)")
            if not p:
                return False
            self.path = p if p.endswith(".gpa") else p + ".gpa"
        sim_links.rebase(self, old_base)
        base = os.path.dirname(self.path)
        for c in self.asm.components:                    # paths inside the file are relative to the assembly when they can be
            try:
                ap = self.abs(c["path"]) if not os.path.isabs(c["path"]) else c["path"]
                c["path"] = os.path.relpath(ap, base)
            except ValueError:
                pass
        open(self.path, "w", encoding="utf-8").write(self.asm.to_json())
        self.saved_json = self.asm.to_json()
        also = sim_links.save_open(self)
        self.say(f"Saved {self.path}" + (f"  (and the simulation{'s' if len(also) > 1 else ''} {', '.join(also)})" if also else ""))
        return True

    def is_dirty(self):
        return self.asm.to_json() != getattr(self, "saved_json", am.Assembly().to_json())

    # ------------------------------------------------------------------ the scene
    def solve_all(self):
        self.asm._cache.clear()
        try:
            self.asm.solve()
        except am.MateError as ex:
            self.say("Mate problem: " + str(ex))
        self.refresh_derived()

    def update_all(self, fit=False):
        self.refresh_tree()
        self.rebuild_scene(fit)
        self.cfg_panel.refresh()
        self.disp_panel.refresh()

    def entry_mesh(self, c):
        d = self.part_doc(c if not c.get("derived") else (self.asm.comp(c["derived"]["src"]) or c))
        solid = d.solid if d is not None else None
        if solid is None:
            return None
        src = c if not c.get("derived") else self.asm.comp(c["derived"]["src"])
        key = (src["path"], id(solid))
        hit = self.mesh_cache.get(key)
        if hit is None:
            verts, cells, face_id, off = [], [], [], 0
            for i, v, t in d.mesh(solid):
                verts.append(v)
                cells.append(np.hstack([np.full((len(t), 1), 3), t + off]).ravel())
                face_id += [i] * len(t)
                off += len(v)
            if not verts:
                return None
            m = pv.PolyData(np.vstack(verts), np.concatenate(cells))
            m.cell_data["face"] = np.array(face_id)
            polys = d.edge_lines(solid)
            bb = solid.bounding_box()
            lc = np.array([(bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, (bb.min.Z + bb.max.Z) / 2])
            hit = (m, polys, lc)
            if len(self.mesh_cache) > 80:
                self.mesh_cache.clear()
            self.mesh_cache[key] = hit
        return hit

    def pull_edges(self, *_a):
        """Move every outline a few pixels towards the viewer (in the world, so it does not depend on the graphics card's depth-offset
        support): the line where two parts touch lies exactly in the surface of the other part and would otherwise lose the depth test."""
        pl = self.plotter
        try:
            cam = pl.camera
            p, f = np.array(cam.position, float), np.array(cam.focal_point, float)
            v = p - f
            dist = float(np.linalg.norm(v))
            if dist < 1e-9:
                return
            if cam.GetParallelProjection():
                eps = 4.0 * 2.0 * cam.GetParallelScale() / max(300, pl.window_size[1])
                off = v / dist * eps * 2.0
            else:
                eps = 4.0 * 2.0 * dist * math.tan(math.radians(cam.GetViewAngle()) / 2) / max(300, pl.window_size[1])
                off = v / dist * eps
            for e in self.entries.values():
                if e.get("edges") is not None:
                    e["edges"].position = tuple(off)
        except Exception:
            pass

    def hook_edge_pull(self, pl):
        """Keep the outlines pulled towards the viewer whenever the camera moves or the window is resized."""
        try:
            old = getattr(self, "_pull_obs", None)
            if old is not None:
                old[0].RemoveObserver(old[1])
            cam = pl.camera
            self._pull_obs = (cam, cam.AddObserver("ModifiedEvent", self.pull_edges))
        except Exception:
            self._pull_obs = None
        self.pull_edges()

    def rebuild_scene(self, fit=False):
        pl = self.plotter
        if pl is None:
            return
        try:
            self.cam = None if fit else pl.camera_position
        except Exception:
            self.cam = None
        pl.clear()
        pl.add_axes()
        self.entries, self.hi_actors = {}, []
        for k, c in enumerate(self.asm.components):
            if c.get("hidden") or c.get("suppressed"):
                continue
            hit = self.entry_mesh(c)
            if hit is None:
                continue
            m, polys, lc = hit
            col = SEL_COL if c["id"] == self.sel_comp else self.base_color(c, k)
            a = pl.add_mesh(m, color=col, opacity=self.opacity_of(c), smooth_shading=False, pickable=True, show_edges=False, reset_camera=False,
                            ambient=0.28, diffuse=0.78, specular=0.30, specular_power=22)
            ml = pm_app.MainWindow.merged_lines(polys)
            ea = pl.add_mesh(ml, color=(0.13, 0.15, 0.20), line_width=1.6, pickable=False, reset_camera=False) if ml is not None else None
            if ea is not None:              # pull the outlines a little more towards the viewer, so a joint between two parts always shows its line
                try:
                    ea.mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-4.0, -4.0)
                except Exception:
                    pass
            self.entries[c["id"]] = {"actor": a, "edges": ea, "mesh": m, "polys": polys, "lc": lc, "k": k}
        self.hook_edge_pull(pl)
        asm_refs.draw_world(self, pl, pv)             # the origin, its planes, reference planes and axes
        self.update_poses(render=False)
        self.draw_highlights(render=False)
        if self.cam is not None:
            pl.camera_position = self.cam
        elif self.entries:
            pl.camera_position = "iso"
            pl.reset_camera()
        else:
            pl.camera_position = "iso"
            pl.reset_camera()
        try:
            pl.render()
        except Exception:
            pass

    def update_poses(self, render=True):
        for cid, e in self.entries.items():
            c = self.asm.comp(cid)
            if c is None:
                continue
            M = self.asm.T4(c)
            e["actor"].user_matrix = M
            if e["edges"] is not None:
                e["edges"].user_matrix = M
        for a, cid in self.hi_actors:
            c = self.asm.comp(cid)
            if c is not None:
                a.user_matrix = self.asm.T4(c)
        if render and self.plotter is not None:
            try:
                self.plotter.render()
            except Exception:
                pass

    def base_color(self, c, k):
        base = self.part_base(c)
        pd = base.display if base is not None else {}
        return c.get("color") or pd.get("color") or PALETTE[k % len(PALETTE)]

    def opacity_of(self, c):
        base = self.part_base(c)
        return float(c.get("opacity", 1.0)) * float((base.display if base is not None else {}).get("opacity", 1.0))

    def set_selected_color(self):
        for cid, e in self.entries.items():
            c = self.asm.comp(cid)
            col = SEL_COL if cid == self.sel_comp else self.base_color(c, e["k"])
            e["actor"].prop.color = col
        if self.plotter is not None:
            self.plotter.render()

    def draw_highlights(self, render=True):
        pl = self.plotter
        for a, _cid in self.hi_actors:
            try:
                pl.remove_actor(a)
            except Exception:
                pass
        self.hi_actors = []
        for it in self.mate_sel + (self.pat.get("hi", []) if self.pat else []) + (self.rg["refs"] if self.rg else []):
            if it["kind"] in ("plane", "axis", "origin") or it["cid"] == "@":
                a = asm_refs.highlight_extra(self, pl, pv, it)
                if a is not None:
                    self.hi_actors.append((a, "@"))
                continue
            e = self.entries.get(it["cid"])
            if e is None:
                continue
            a = None
            if it["kind"] == "face":
                cs = np.where(np.array(e["mesh"].cell_data["face"]) == it["idx"])[0]
                if len(cs):
                    a = pl.add_mesh(e["mesh"].extract_cells(cs), color=HI_COL, lighting=False, pickable=False, reset_camera=False)
            elif it["kind"] == "edge" and it["idx"] < len(e["polys"]):
                ml = pm_app.MainWindow.merged_lines([e["polys"][it["idx"]]])
                a = pl.add_mesh(ml, color=HI_COL, line_width=5, pickable=False, reset_camera=False)
            elif it["kind"] == "vertex":
                a = pl.add_mesh(pv.PolyData(np.array([it["pt"]])), color=HI_COL, point_size=12, render_points_as_spheres=True,
                                pickable=False, reset_camera=False)
            if a is not None:
                self.hi_actors.append((a, it["cid"]))
        if self.rg and self.rg.get("ent") is not None:                 # preview of the plane / axis being made
            try:
                pa, _ = asm_refs.shape_actor(self, pl, pv, self.rg["ent"], asm_refs.REF_COL, 0.3, asm_refs.scene_size(self), 1.4)
                self.hi_actors.append((pa, "@"))
            except Exception:
                pass
        self.update_poses(render=render)

    # ------------------------------------------------------------------ the tree
    def refresh_tree(self):
        self.busy = True
        self.tree.clear()
        a = self.asm
        root = QTreeWidgetItem(self.tree, [f"⬢  {os.path.splitext(self.title())[0]}"])
        root.setExpanded(True)
        for nm in ("Front", "Top", "Right"):
            p = QTreeWidgetItem(root, [f"▯  {nm} Plane"])
            p.setData(0, Qt.ItemDataRole.UserRole, ("wplane", nm))
            p.setFlags(p.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            p.setCheckState(0, Qt.CheckState.Checked if a.world_show.get(nm, True) else Qt.CheckState.Unchecked)
        o = QTreeWidgetItem(root, ["⊹  Origin"])
        o.setData(0, Qt.ItemDataRole.UserRole, ("worigin",))
        o.setFlags(o.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        o.setCheckState(0, Qt.CheckState.Checked if a.world_show.get("origin", True) else Qt.CheckState.Unchecked)
        if a.refs:
            rr = QTreeWidgetItem(root, [f"▱  Reference Geometry ({len(a.refs)})"])
            rr.setExpanded(True)
            for f in a.refs:
                it = QTreeWidgetItem(rr, [("▱  " if f["kind"] == "refplane" else "⁞  ") + f["name"]])
                it.setData(0, Qt.ItemDataRole.UserRole, ("aref", f["id"]))
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if f.get("show", True) else Qt.CheckState.Unchecked)
                try:
                    a.ref_entity(f["id"])
                except am.MateError as ex:
                    it.setForeground(0, QBrush(QColor("#c00000")))
                    it.setToolTip(0, str(ex))
        comps = QTreeWidgetItem(root, [f"▣  Components ({len(a.components)})"])
        comps.setExpanded(True)
        for c in a.components:
            tag = "(f)" if c.get("fixed") else ("(-)" if a.dof.get(c["id"], 6) else "")
            if c.get("suppressed"):
                tag = "(suppressed)"
            if c.get("derived"):
                tag = "(pattern)" if c["derived"].get("kind") != "mirror" else "(mirror)"
            it = QTreeWidgetItem(comps, [f"{tag + ' ' if tag else ''}{c['name']}{'  (hidden)' if c.get('hidden') else ''}"])
            it.setData(0, Qt.ItemDataRole.UserRole, ("comp", c["id"]))
            if self.d_ok(c) is False:
                it.setForeground(0, QBrush(QColor("#c00000")))
                it.setText(0, it.text(0) + "   ✖ part file not found")
            if not c.get("derived"):
                for nm in ("Front", "Top", "Right"):
                    p = QTreeWidgetItem(it, [f"▯  {nm} Plane"])
                    p.setData(0, Qt.ItemDataRole.UserRole, ("cplane", c["id"], nm))
                o = QTreeWidgetItem(it, ["⊹  Origin"])
                o.setData(0, Qt.ItemDataRole.UserRole, ("corigin", c["id"]))
                pd = self.part_doc(c)
                if getattr(pd, "is_sub", False):
                    inside = QTreeWidgetItem(it, [f"▣  Parts inside ({len(pd.leaf_names)})"])
                    for nm in pd.leaf_names:
                        QTreeWidgetItem(inside, [nm]).setFlags(Qt.ItemFlag.ItemIsEnabled)
                for g in (pd.features if pd is not None else []):
                    if g["kind"] in ("refplane", "refaxis") and g["id"] in pd.refgeo:
                        q = QTreeWidgetItem(it, [("▱  " if g["kind"] == "refplane" else "⁞  ") + g["name"]])
                        q.setData(0, Qt.ItemDataRole.UserRole, ("cref", c["id"], g["id"], g["kind"]))
            if c["id"] == self.sel_comp:
                self.tree.setCurrentItem(it)
        if a.patterns:
            pp = QTreeWidgetItem(root, [f"☷  Patterns ({len(a.patterns)})"])
            pp.setExpanded(True)
            for p in a.patterns:
                it = QTreeWidgetItem(pp, [p["name"]])
                it.setData(0, Qt.ItemDataRole.UserRole, ("pattern", p["id"]))
        import sim_links
        L = sim_links.sims(self)
        if L:
            si = QTreeWidgetItem(root, [f"∿  Simulations ({len(L)})"])
            si.setExpanded(True)
            for e in L:
                sit = QTreeWidgetItem(si, ["∿  " + sim_links.label(e) + ("   ✖ file not found" if sim_links.missing(self, e) else "")])
                sit.setData(0, Qt.ItemDataRole.UserRole, ("sim", e["path"]))
                sit.setToolTip(0, sim_links.abs_of(self, e) + "\nDouble-click to open")
                if sim_links.missing(self, e):
                    sit.setForeground(0, QBrush(QColor("#c00000")))
        R = sim_links.renders(self)
        if R:
            ri = QTreeWidgetItem(root, [f"◉  Renders ({len(R)})"])
            ri.setExpanded(True)
            for e in R:
                rit = QTreeWidgetItem(ri, ["◉  " + sim_links.label(e) + ("   ✖ file not found" if sim_links.missing(self, e) else "")])
                rit.setData(0, Qt.ItemDataRole.UserRole, ("render", e["path"]))
                rit.setToolTip(0, sim_links.abs_of(self, e) + "\nDouble-click to open")
                if sim_links.missing(self, e):
                    rit.setForeground(0, QBrush(QColor("#c00000")))
        mm = QTreeWidgetItem(root, [f"⚯  Mates ({len(a.mates)})"])
        mm.setExpanded(True)
        for m in a.mates:
            st = a.status.get(m["id"], "")
            names = ", ".join(sorted({"Assembly" if r["c"] == "@" else (a.comp(r["c"]) or {"name": "?"})["name"] for r in m["refs"]}))
            it = QTreeWidgetItem(mm, [f"{MATE_NAMES[m['type']]}{m['id'][1:]}  ({names})" + ("  ✖" if st.startswith("error") else "  (suppressed)" if m.get("suppressed") else "")])
            it.setData(0, Qt.ItemDataRole.UserRole, ("mate", m["id"]))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Unchecked if m.get("suppressed") else Qt.CheckState.Checked)
            if m.get("suppressed"):
                it.setForeground(0, QBrush(QColor("#888888")))
            if st.startswith("error"):
                it.setForeground(0, QBrush(QColor("#c00000")))
                it.setToolTip(0, st)
        self.busy = False
        if getattr(self, "mini", None) is not None:
            self.mini.sync()

    def d_ok(self, c):
        if c.get("derived"):
            return True
        return self.part_doc(c) is not None

    def tree_selected(self, cur, _prev):
        if self.busy or cur is None:
            return
        data = cur.data(0, Qt.ItemDataRole.UserRole) or (None,)
        if asm_refs.pick_from_data(self, data):
            return
        if self.mode in ("mate", "refgeo"):
            return
        if data[0] in ("comp", "cplane", "corigin", "cref"):
            self.sel_comp = data[1]
            self.set_selected_color()
            self.show_comp_props()
            self.left.setCurrentIndex(1)
        elif data[0] == "mate":
            self.show_mate_props(data[1])
        elif data[0] == "pattern":
            self.pattern_edit(data[1])

    def tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None:
            return
        data = it.data(0, Qt.ItemDataRole.UserRole) or (None,)
        menu = QMenu(self)
        if data[0] == "comp":
            self.component_menu(menu, data[1])
        elif data[0] == "render":
            menu.addAction("Open render").triggered.connect(lambda: self.open_linked_sim(data[1], "renders"))
            menu.addAction("Remove from this list (the file stays)").triggered.connect(lambda: self.unlink_sim(data[1], "renders"))
        elif data[0] == "sim":
            menu.addAction("Open simulation").triggered.connect(lambda: self.open_linked_sim(data[1]))
            menu.addAction("Remove from this list (the file stays)").triggered.connect(lambda: self.unlink_sim(data[1]))
        elif data[0] == "aref":
            menu.addAction("Edit").triggered.connect(lambda: asm_refs.start(self, "refplane", edit=data[1]))
            menu.addAction("Delete").triggered.connect(lambda: asm_refs.delete_ref(self, data[1]))
        elif data[0] == "mate":
            m = self.asm.mate(data[1])
            menu.addAction("Edit Mate").triggered.connect(lambda: self.mate_edit_start(data[1]))
            menu.addAction("Suppress" if not m.get("suppressed") else "Unsuppress").triggered.connect(lambda: self.mate_suppress(data[1]))
            menu.addAction("Delete Mate").triggered.connect(lambda: self.delete_mate(data[1]))
        elif data[0] == "pattern":
            menu.addAction("Edit").triggered.connect(lambda: self.pattern_edit(data[1]))
            menu.addAction("Delete").triggered.connect(lambda: self.pattern_delete(data[1]))
        if menu.actions():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def component_menu(self, menu, cid):
        c = self.asm.comp(cid)
        if c is None:
            return
        if not c.get("derived"):
            menu.addAction("Float" if c.get("fixed") else "Fix").triggered.connect(lambda: self.toggle_fixed(cid))
            menu.addAction("Edit Component").triggered.connect(lambda: (setattr(self, "sel_comp", cid), self.edit_component()))
        menu.addAction("Show" if c.get("hidden") else "Hide").triggered.connect(lambda: self.toggle_hidden(cid))
        if not c.get("derived"):
            menu.addAction("Delete Component").triggered.connect(lambda: self.delete_component(cid))

    # ------------------------------------------------------------------ component commands
    def insert_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Insert components", os.path.dirname(self.path) if self.path else "", "Parts and assemblies (*.gpd *.gpa);;Part (*.gpd);;Assembly (*.gpa)")
        if files:
            self.insert_files(files)

    def insert_files(self, files):
        self.snapshot()
        for f in files:
            if f.lower().endswith(".gpa"):
                if self.path and os.path.normcase(os.path.abspath(f)) == os.path.normcase(os.path.abspath(self.path)):
                    self.say("An assembly cannot contain itself.")
                    continue
                try:
                    ok = asm_sub.sub_doc(self, f, None) is not None
                except asm_sub.SubLoop:
                    self.say(f"{os.path.basename(f)} contains this assembly - inserting it would make a loop.")
                    continue
                if not ok:
                    self.say(f"{os.path.basename(f)} could not be opened.")
                    continue
            c = self.asm.add_component(f, fixed=not self.asm.components)
            d = self.part_doc(c)
            if d is None or d.solid is None:
                self.say(f"{os.path.basename(f)} has no solid yet (or could not be opened).")
            else:
                if len(self.asm.components) > 1:
                    bb = d.solid.bounding_box()
                    right = -1e18
                    for o in self.asm.components[:-1]:
                        od = self.part_doc(o)
                        if od is not None and od.solid is not None:
                            ob = od.solid.bounding_box()
                            right = max(right, o["pos"][0] + ob.max.X)
                    if right > -1e17:
                        c["pos"] = [right + 20 - bb.min.X, 0.0, 0.0]
            self.sel_comp = c["id"]
        self.solve_all()
        self.update_all(fit=len(self.asm.components) == len(files))
        self.say("The first component is fixed; the others float. Use Move Component, or Mate to put them together.")

    def toggle_fixed(self, cid):
        self.snapshot()
        c = self.asm.comp(cid)
        c["fixed"] = not c.get("fixed")
        self.solve_all()
        self.update_all()

    def toggle_hidden(self, cid):
        c = self.asm.comp(cid)
        c["hidden"] = not c.get("hidden")
        self.update_all()

    def delete_component(self, cid):
        c = self.asm.comp(cid)
        if c is None:
            return
        n = len([m for m in self.asm.mates if any(r["c"] == cid for r in m["refs"])])
        if QMessageBox.question(self, "Delete component", f"Delete {c['name']}" + (f" and its {n} mate(s)?" if n else "?")) != QMessageBox.StandardButton.Yes:
            return
        self.snapshot()
        self.asm.remove_component(cid)
        self.sel_comp = None
        self.solve_all()
        self.update_all()

    def mini_pick(self, data):
        return asm_refs.mini_pick(self, data)

    def open_linked_sim(self, path_key, attr="sims"):
        import sim_links
        e = next((x for x in sim_links.links(self, attr) if x["path"] == path_key), None)
        if e is not None and sim_links.open_sim(self, e) is None:
            self.say("That simulation file was not found: " + sim_links.abs_of(self, e))

    def unlink_sim(self, path_key, attr="sims"):
        import sim_links
        e = next((x for x in sim_links.links(self, attr) if x["path"] == path_key), None)
        if e is not None:
            self.snapshot()
            sim_links.remove(self, sim_links.abs_of(self, e), attr)
            self.refresh_tree()

    def tree_double(self, it, _c):
        data = it.data(0, Qt.ItemDataRole.UserRole) or ("",)
        if data[0] == "sim":
            self.open_linked_sim(data[1])
        elif data[0] == "render":
            self.open_linked_sim(data[1], "renders")
        elif data[0] == "comp":
            self.edit_component()
        elif data[0] == "mate" and self.mode is None:
            self.mate_edit_start(data[1])
        elif data[0] == "aref" and self.mode is None:
            asm_refs.start(self, "refplane", edit=data[1])

    def tree_checked(self, it, col):
        if self.busy:
            return
        data = it.data(0, Qt.ItemDataRole.UserRole) or ("",)
        on = it.checkState(0) == Qt.CheckState.Checked
        if data[0] in ("wplane", "worigin", "aref"):
            if data[0] == "wplane":
                self.asm.world_show[data[1]] = on
            elif data[0] == "worigin":
                self.asm.world_show["origin"] = on
            else:
                f = next((r for r in self.asm.refs if r["id"] == data[1]), None)
                if f is not None:
                    f["show"] = on
            QTimer.singleShot(0, self.rebuild_scene)
            return
        if data[0] != "mate" or self.mode is not None:
            QTimer.singleShot(0, self.update_all)
            return
        m = self.asm.mate(data[1])
        if m is not None and (it.checkState(0) == Qt.CheckState.Unchecked) != bool(m.get("suppressed")):
            QTimer.singleShot(0, lambda mid=data[1]: self.mate_suppress(mid))

    def delete_selected(self):
        cur = self.tree.currentItem()
        data = (cur.data(0, Qt.ItemDataRole.UserRole) if cur is not None else None) or ("",)
        if self.mode is None and data[0] == "mate" and self.tree.hasFocus():
            self.delete_mate(data[1])
            return
        if self.mode is None and data[0] == "aref" and self.tree.hasFocus():
            asm_refs.delete_ref(self, data[1])
            return
        if self.mode is None and self.sel_comp and self.tree.hasFocus():
            self.delete_component(self.sel_comp)

    def delete_mate(self, mid):
        self.snapshot()
        self.asm.mates = [m for m in self.asm.mates if m["id"] != mid]
        self.solve_all()
        self.update_all()

    def mate_suppress(self, mid):
        self.snapshot()
        m = self.asm.mate(mid)
        m["suppressed"] = not m.get("suppressed")
        self.solve_all()
        self.update_all()

    def edit_component(self):
        c = self.asm.comp(self.sel_comp) if self.sel_comp else None
        if c is None:
            self.say("Select a component first.")
            return
        if c.get("derived"):
            c = self.asm.comp(c["derived"]["src"])
        if self.shell is None:
            self.say("Edit Component works inside the full program window.")
            return
        self.shell.open_part(self.abs(c["path"]))

    def refresh_parts(self):
        """Called when this tab is shown again: pick up edited parts."""
        self.asm._cache.clear()
        self.doc_memo.clear()
        self.__dict__.pop("sub_cache", None)
        self.solve_all()
        self.mesh_cache.clear()
        self.update_all()

    # ------------------------------------------------------------------ properties
    def clear_props(self):
        while self.props_lay.count():
            it = self.props_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def num_edit(self, form, label, getter, setter):
        e = QLineEdit(f"{getter():.4f}".rstrip("0").rstrip("."))

        def done():
            try:
                v = float(e.text())
            except ValueError:
                e.setText(f"{getter():.4f}")
                return
            if abs(v - getter()) > 1e-9:
                self.snapshot()
                setter(v)
        e.editingFinished.connect(done)
        form.addRow(label, e)

    def show_comp_props(self):
        self.clear_props()
        c = self.asm.comp(self.sel_comp) if self.sel_comp else None
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)
        self.props_lay.addWidget(box)
        if c is None:
            form.addRow(QLabel("Nothing selected."))
            return
        form.addRow(QLabel(f"<b>{c['name']}</b>"))
        if c.get("derived"):
            form.addRow(QLabel("A copy made by a pattern or mirror (edit the pattern to change it)."))
            return
        form.addRow("File", QLabel(os.path.basename(c["path"])))
        fx = QCheckBox()
        fx.setChecked(bool(c.get("fixed")))
        fx.toggled.connect(lambda _v: self.toggle_fixed(c["id"]))
        form.addRow("Fixed", fx)
        form.addRow(QLabel(f"Degrees of freedom left: {self.asm.dof.get(c['id'], 6) if not c.get('fixed') else 0}"))
        if not c.get("fixed"):
            for i, ax in enumerate("XYZ"):
                self.num_edit(form, f"Position {ax} (mm)", lambda i=i: c["pos"][i], lambda v, i=i: self.set_pose(c, "pos", i, v))
            for i, ax in enumerate("XYZ"):
                self.num_edit(form, f"Rotation vector {ax} (deg)", lambda i=i: np.degrees(c["rv"][i]), lambda v, i=i: self.set_pose(c, "rv", i, np.radians(v)))

    def set_pose(self, c, key, i, v):
        c[key][i] = float(v)
        self.solve_all()
        self.update_all()

    # ------------------------------------------------------------------ view picking
    def view_vectors(self):
        cam = self.plotter.camera
        pos, foc, up = np.array(cam.position), np.array(cam.focal_point), np.array(cam.up)
        d = am.unit(foc - pos)
        right = am.unit(np.cross(d, up))
        up2 = np.cross(right, d)
        return d, right, up2

    def comp_at(self, actor):
        for cid, e in self.entries.items():
            if viewpick.same_actor(e["actor"], actor):
                return cid
        return None

    def surface_hit(self, x, y):
        r = viewpick.pick_surface(self.plotter, x, y)
        if r is None:
            return None
        pos, actor, cid_cell = r
        cid = self.comp_at(actor)
        if cid is None:
            return None
        return np.array(pos), cid, int(cid_cell)

    def pick_item(self, x, y):
        """What is under the cursor: {"cid", "kind": vertex | edge | face, "idx", "ref", "pt", "label"} or None."""
        h = self.surface_hit(x, y)
        if h is None:
            return None
        hit, cid, cell = h
        e = self.entries[cid]
        c = self.asm.comp(cid)
        solid = self.solid_of(c)
        if solid is None:
            return None
        M = self.asm.T4(c)
        wpp = viewpick.world_per_pixel(self.plotter)
        tol = max(0.4, 7.0 * wpp)
        # a vertex close to the hit point
        verts = solid.vertices()
        if verts:
            P = np.array([[v.center().X, v.center().Y, v.center().Z] for v in verts])
            W = (P @ M[:3, :3].T) + M[:3, 3]
            dist = np.linalg.norm(W - hit, axis=1)
            i = int(np.argmin(dist))
            if dist[i] <= tol:
                return {"cid": cid, "kind": "vertex", "idx": i, "pt": list(P[i]), "ref": {"c": cid, "k": "vertex", "r": am.vertex_ref(verts[i])},
                        "label": "Point"}
        # an edge close to the hit point
        best, bd = None, 1e18
        for i, pts in enumerate(e["polys"]):
            if len(pts) < 2:
                continue
            Wp = (pts @ M[:3, :3].T) + M[:3, 3]
            a, b = Wp[:-1], Wp[1:]
            ab = b - a
            t = np.clip(np.einsum("ij,ij->i", hit - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
            dd = np.linalg.norm(a + ab * t[:, None] - hit, axis=1).min()
            if dd < bd:
                best, bd = i, dd
        if best is not None and bd <= tol:
            return {"cid": cid, "kind": "edge", "idx": best, "pt": None, "ref": {"c": cid, "k": "edge", "r": am.edge_ref(solid.edges()[best])},
                    "label": "Edge"}
        fi = int(e["mesh"].cell_data["face"][cell])
        face = solid.faces()[fi]
        return {"cid": cid, "kind": "face", "idx": fi, "pt": None, "ref": {"c": cid, "k": "face", "r": am.face_ref(face)},
                "label": {"PLANE": "Face", "CYLINDER": "Cylindrical face", "SPHERE": "Spherical face"}.get(face.geom_type.name, "Face")}

    def on_click(self, x, y):
        if self.mode in ("move", "rotate"):
            return
        try:
            if self.mode == "mate":
                it = self.pick_item(x, y) or asm_refs.world_pick(self, x, y)
                if it is not None:
                    self.add_mate_ref(it["ref"], it)
                return
            if self.mode == "refgeo":
                it = self.pick_item(x, y) or asm_refs.world_pick(self, x, y)
                if it is not None:
                    asm_refs.rg_toggle(self, it)
                return
            if self.mode in ("pattern",):
                h = self.surface_hit(x, y)
                if h is not None:
                    self.pat_toggle_comp(h[1])
                return
            if self.mode == "mirror_plane":
                it = self.pick_item(x, y)
                if it is None or it["kind"] != "face":
                    it = asm_refs.world_pick(self, x, y)
                    it = it if it is not None and it["kind"] == "plane" else None
                if it is not None:
                    self.pat_set_plane(it)
                return
            if self.mode == "axis_pick":
                it = self.pick_item(x, y) or asm_refs.world_pick(self, x, y)
                if it is not None:
                    self.pat_set_entity(it)
                return
            h = self.surface_hit(x, y)
            self.sel_comp = h[1] if h is not None else None
            self.set_selected_color()
            self.refresh_tree()
            self.show_comp_props()
            if h is not None:
                self.left.setCurrentIndex(1)
        except Exception:
            self.say("Click failed: " + traceback.format_exc(limit=2))

    def context_menu(self, x, y, gpos):
        menu = QMenu(self)
        h = self.surface_hit(x, y)
        if h is not None:
            self.sel_comp = h[1]
            self.set_selected_color()
            self.refresh_tree()
            self.component_menu(menu, h[1])
        if menu.actions():
            menu.exec(gpos)

    # ------------------------------------------------------------------ move / rotate
    def set_mode(self, mode, quiet=False):
        if mode in ("move", "rotate") and not self.asm.components:
            self.say("Insert a component first.")
            return
        if self.mode == "mate" and mode != "mate" and self.mate_pre is not None:
            self.mate_cancel(quiet=True)
        if self.mode == "refgeo" and mode != "refgeo" and self.rg is not None:
            asm_refs.cancel(self, quiet=True)
        if self.mode in ("pattern", "mirror_plane", "axis_pick") and mode not in ("pattern", "mirror_plane", "axis_pick") and self.pat is not None:
            self.pattern_cancel(quiet=True)
        self.mode = mode
        if not quiet:
            self.say({"move": "Move Component: drag a component (Esc to stop).", "rotate": "Rotate Component: drag a component (Esc to stop).",
                      None: "Select a component by clicking it."}.get(mode, ""))

    def drag_begin(self, x, y):
        h = self.surface_hit(x, y)
        if h is None:
            return None
        hit, cid, _cell = h
        c = self.asm.comp(cid)
        if c.get("fixed") or c.get("derived"):
            self.say(f"{c['name']} is " + ("a pattern copy." if c.get("derived") else "fixed - right-click it and choose Float to move it."))
            return None
        self.snapshot()
        self.sel_comp = cid
        self.set_selected_color()
        R, t = self.asm.pose(c)
        d, right, up = self.view_vectors()
        return {"cid": cid, "x": x, "y": y, "hit": hit, "R": R, "t": t, "d": d, "right": right, "up": up,
                "cluster": self.asm.cluster(cid), "lc": self.entries[cid]["lc"]}

    def drag_move(self, st, x, y):
        c = self.asm.comp(st["cid"])
        if self.mode == "move":
            p_r, dirn = self.ed.ray(x, y)
            den = float(dirn @ st["d"])
            if abs(den) < 1e-9:
                return
            p1 = p_r + dirn * (float((st["hit"] - p_r) @ st["d"]) / den)
            R, t = st["R"], st["t"] + (p1 - st["hit"])
        else:
            dx, dy = x - st["x"], y - st["y"]
            Rd = am.axis_rotation(st["up"], dx * 0.01) @ am.axis_rotation(st["right"], -dy * 0.01)
            c0 = st["R"] @ st["lc"] + st["t"]
            R = Rd @ st["R"]
            t = c0 - R @ st["lc"]
        self.asm.solve(drag={st["cid"]: (R, t)}, limit=st["cluster"])
        self.refresh_derived()
        self.update_poses()

    def drag_end(self, st):
        self.asm.solve()
        self.refresh_derived()
        self.refresh_tree()
        self.update_poses()
        self.show_comp_props()

    # ------------------------------------------------------------------ mates
    def mate_start(self):
        if len(self.asm.components) < 2:
            self.say("Insert at least two components first.")
            return
        self.set_mode(None, quiet=True)
        self.mode = "mate"
        self.mate_sel, self.mate_type, self.mate_opts = [], None, {}
        self.mate_pre = {c["id"]: (list(c["pos"]), list(c["rv"])) for c in self.asm.components}
        self.draw_highlights()
        self.show_mate_panel()
        self.left.setCurrentIndex(1)
        self.say("Mate: click two items (faces, edges, points - or a component's planes in the tree).")

    def sel_item_from_ref(self, ref):
        """The pick-list entry (with what the highlight needs) for a stored mate reference."""
        cid, k = ref["c"], ref["k"]
        if k in ("plane", "axis") and "id" in (ref.get("r") or {}):
            if cid == "@":
                f = next((x for x in self.asm.refs if x["id"] == ref["r"]["id"]), None)
                nm = f["name"] if f else "?"
            else:
                c0 = self.asm.comp(cid)
                pd = self.part_doc(c0) if c0 else None
                nm = next((g["name"] for g in (pd.features if pd else []) if g["id"] == ref["r"]["id"]), "?")
            return {"cid": cid, "kind": k, "idx": -1, "label": nm, "ref": ref}
        if k == "plane":
            return {"cid": cid, "kind": "plane", "idx": -1, "label": f"{ref['r']['n']} Plane", "ref": ref}
        if k == "origin":
            return {"cid": cid, "kind": "origin", "idx": -1, "label": "Origin", "ref": ref}
        c = self.asm.comp(cid)
        solid = self.solid_of(c) if c else None
        idx, label, pt = -1, {"face": "Face", "edge": "Edge", "vertex": "Point"}[k], None
        if solid is not None:
            r = ref["r"]
            if k == "face":
                best, sc = -1, 1e18
                for i, f in enumerate(solid.faces()):
                    if f.geom_type.name != r["g"]:
                        continue
                    d = float(np.linalg.norm(np.array([f.center().X, f.center().Y, f.center().Z]) - np.array(r["c"])))
                    if d < sc:
                        best, sc = i, d
                idx = best
                label = {"PLANE": "Face", "CYLINDER": "Cylindrical face", "SPHERE": "Spherical face"}.get(r["g"], "Face")
            elif k == "edge":
                best, sc = -1, 1e18
                for i, ed in enumerate(solid.edges()):
                    if ed.geom_type.name != r["g"]:
                        continue
                    p = ed.position_at(0.5)
                    d = float(np.linalg.norm(np.array([p.X, p.Y, p.Z]) - np.array(r["m"])))
                    if d < sc:
                        best, sc = i, d
                idx = best
            else:
                best, sc = -1, 1e18
                for i, v in enumerate(solid.vertices()):
                    d = float(np.linalg.norm(np.array([v.center().X, v.center().Y, v.center().Z]) - np.array(r["p"])))
                    if d < sc:
                        best, sc = i, d
                idx = best
                if best >= 0:
                    v = solid.vertices()[best].center()
                    pt = [v.X, v.Y, v.Z]
        return {"cid": cid, "kind": k, "idx": idx, "pt": pt, "label": label, "ref": ref}

    def mate_edit_start(self, mid):
        m = self.asm.mate(mid)
        if m is None:
            return
        self.set_mode(None, quiet=True)
        self.mode = "mate"
        self.mate_sel = [self.sel_item_from_ref(r) for r in m["refs"]]
        self.mate_sel = [s for s in self.mate_sel if s["idx"] != -1 or s["kind"] in ("plane", "origin")]
        self.mate_type = m["type"]
        self.mate_opts = {"value": m["value"]} if m.get("value") is not None else {}
        self.mate_pre = {c["id"]: (list(c["pos"]), list(c["rv"])) for c in self.asm.components}
        idx = self.asm.mates.index(m)
        self.mate_edit = {"orig": copy.deepcopy(m), "idx": idx}
        del self.asm.mates[idx]                       # the other mates keep solving; this one is what the panel previews
        self.draw_highlights()
        self.mate_preview()
        self.show_mate_panel()
        self.left.setCurrentIndex(1)
        self.say("Edit mate: change the picks, type or value, then press OK. Click a picked item again to drop it.")

    def add_mate_ref(self, ref, item):
        for i, s in enumerate(self.mate_sel):
            if s["ref"] == ref:
                del self.mate_sel[i]
                break
        else:
            self.mate_sel.append({**item, "ref": ref})
            if len(self.mate_sel) > 3:
                del self.mate_sel[0]
        if self.mate_edit:
            self.mate_opts = {}
        if len(self.mate_sel) >= 2 and self.mate_type is None:
            self.mate_type = "coincident"
        self.draw_highlights()
        self.mate_preview()
        self.show_mate_panel()

    def mate_needed(self):
        return 3 if self.mate_type == "symmetric" else 2

    def build_mate(self):
        ty = self.mate_type
        need = self.mate_needed()
        if ty is None or len(self.mate_sel) < need:
            return None
        sel = self.mate_sel[-need:] if need == 3 else self.mate_sel[:2] if len(self.mate_sel) == 2 else self.mate_sel[-2:]
        m = {"id": "preview", "type": ty, "refs": [s["ref"] for s in sel], "suppressed": False}
        if ty in ("distance", "angle") and "value" in self.mate_opts:
            m["value"] = self.mate_opts["value"]
        return m

    def mate_preview(self):
        for cid, (pos, rv) in self.mate_pre.items():
            c = self.asm.comp(cid)
            c["pos"], c["rv"] = list(pos), list(rv)
        self.mate_error = ""
        m = self.build_mate()
        if m is not None:
            try:
                if len({r["c"] for r in m["refs"]}) < 2 and m["type"] != "symmetric":
                    raise am.MateError("pick items on two different components")
                o = self.mate_edit["orig"] if self.mate_edit else None
                if o is not None and o["type"] == m["type"] and o["refs"] == m["refs"]:
                    m = copy.deepcopy(o)                      # same picks and type: keep every option it already had
                    m["id"], m["suppressed"] = "preview", False
                    if "value" in self.mate_opts and m["type"] in ("distance", "angle") and self.mate_opts["value"] is not None:
                        m["value"] = self.mate_opts["value"]
                    if self.mate_opts.get("flip"):
                        self.flip_mate(m)
                else:
                    self.asm.prepare(m)
                    if self.mate_opts.get("flip"):
                        self.flip_mate(m)
                self.mate_opts.setdefault("value", m.get("value"))
                ok = self.asm.solve(extra=[m])
                if not ok:
                    self.mate_error = "These items cannot be mated with the other mates as they are."
                self.mate_built = m
            except am.MateError as ex:
                self.mate_error = str(ex)
                self.mate_built = None
        else:
            self.mate_built = None
        self.refresh_derived()
        if any(s["kind"] in ("plane", "axis", "origin") for s in self.mate_sel):
            self.draw_highlights(render=False)
        self.update_poses()

    @staticmethod
    def flip_mate(m):
        if "al" in m:
            m["al"] = "aligned" if m["al"] == "opposed" else "opposed"
        if "sgn" in m:
            m["sgn"] = -m["sgn"]
        if "tk" in m:
            m["tk"] = "int" if m["tk"] == "ext" else "ext"

    def show_mate_panel(self):
        self.clear_props()
        lab = QLabel("<b>Mate</b>")
        self.props_lay.addWidget(lab)
        lst = QListWidget()
        lst.setMaximumHeight(90)
        for s in self.mate_sel:
            c = self.asm.comp(s["cid"])
            lst.addItem(f"{s['label']}<{c['name'] if c else ('Assembly' if s['cid'] == '@' else '?')}>")
        self.props_lay.addWidget(lst)
        row = QHBoxLayout()
        b = QPushButton("✔  OK")
        b.clicked.connect(self.mate_ok)
        row.addWidget(b)
        b = QPushButton("✖  Cancel")
        b.clicked.connect(lambda: self.mate_cancel())
        row.addWidget(b)
        b = QPushButton("Clear picks")
        b.clicked.connect(self.mate_clear)
        row.addWidget(b)
        w = QWidget()
        w.setLayout(row)
        self.props_lay.addWidget(w)
        grp = QButtonGroup(self.props)
        for ty in am.TYPES:
            rb = QRadioButton(MATE_NAMES[ty])
            rb.setToolTip(MATE_HELP[ty])
            rb.setChecked(self.mate_type == ty)
            rb.toggled.connect(lambda on, ty=ty: on and self.set_mate_type(ty))
            grp.addButton(rb)
            self.props_lay.addWidget(rb)
        if self.mate_type in ("distance", "angle"):
            form = QFormLayout()
            e = QLineEdit(str(self.mate_opts.get("value", "")))

            def done():
                try:
                    self.mate_opts["value"] = float(e.text())
                except ValueError:
                    return
                self.mate_preview()
            e.editingFinished.connect(done)
            form.addRow("Distance (mm)" if self.mate_type == "distance" else "Angle (deg)", e)
            w = QWidget()
            w.setLayout(form)
            self.props_lay.addWidget(w)
        if self.mate_type in ("coincident", "distance", "tangent"):
            cb = QCheckBox("Flip (aligned / opposite side)")
            cb.setChecked(bool(self.mate_opts.get("flip")))
            cb.toggled.connect(lambda v: (self.mate_opts.__setitem__("flip", bool(v)), self.mate_preview(), self.show_mate_panel()))
            self.props_lay.addWidget(cb)
        if self.mate_type:
            hint = QLabel(MATE_HELP[self.mate_type])
            hint.setWordWrap(True)
            self.props_lay.addWidget(hint)
        if getattr(self, "mate_error", ""):
            er = QLabel(self.mate_error)
            er.setStyleSheet("color:#c00000;")
            er.setWordWrap(True)
            self.props_lay.addWidget(er)

    def set_mate_type(self, ty):
        if ty == self.mate_type:
            return
        self.mate_type = ty
        self.mate_opts = {}
        self.mate_preview()
        self.show_mate_panel()

    def mate_clear(self):
        self.mate_sel = []
        if self.mate_edit:
            self.mate_opts = {}
        self.draw_highlights()
        self.mate_preview()
        self.show_mate_panel()

    def mate_ok(self):
        m = getattr(self, "mate_built", None)
        if m is None or self.mate_error:
            self.say(self.mate_error or "Pick two items and a mate type first.")
            return
        for cid, (pos, rv) in self.mate_pre.items():          # undo the preview so the snapshot holds the old positions
            c = self.asm.comp(cid)
            c["pos"], c["rv"] = list(pos), list(rv)
        ed = self.mate_edit
        if ed:
            self.asm.mates.insert(ed["idx"], ed["orig"])      # the snapshot must still hold the old mate
        self.snapshot()
        m = dict(m)
        if ed:
            m["id"], m["suppressed"] = ed["orig"]["id"], bool(ed["orig"].get("suppressed"))
            self.asm.mates[ed["idx"]] = m
            self.mate_edit = None
        else:
            m["id"] = self.asm.next_id("M")
            self.asm.mates.append(m)
        self.solve_all()
        self.finish_mate()
        self.say(f"{MATE_NAMES[m['type']]} mate {'updated' if ed else 'added'}.")

    def finish_mate(self):
        self.mode, self.mate_sel, self.mate_pre, self.mate_type, self.mate_opts = None, [], None, None, {}
        self.update_all()
        self.show_comp_props()
        self.left.setCurrentIndex(0)

    def mate_cancel(self, quiet=False):
        if self.mate_edit:
            self.asm.mates.insert(self.mate_edit["idx"], self.mate_edit["orig"])
            self.mate_edit = None
        if self.mate_pre is not None:
            for cid, (pos, rv) in self.mate_pre.items():
                c = self.asm.comp(cid)
                if c is not None:
                    c["pos"], c["rv"] = list(pos), list(rv)
        self.solve_all()
        self.finish_mate()
        if not quiet:
            self.say("Mate cancelled.")

    def show_mate_props(self, mid):
        self.clear_props()
        m = self.asm.mate(mid)
        if m is None:
            return
        self.props_lay.addWidget(QLabel(f"<b>{MATE_NAMES[m['type']]}{mid[1:]}</b>"))
        st = self.asm.status.get(mid, "")
        if st.startswith("error"):
            er = QLabel(st)
            er.setStyleSheet("color:#c00000;")
            er.setWordWrap(True)
            self.props_lay.addWidget(er)
        for r in m["refs"]:
            c = self.asm.comp(r["c"])
            self.props_lay.addWidget(QLabel(f"{r['k']}  of  {c['name'] if c else ('the assembly' if r['c'] == '@' else '?')}"))
        if m["type"] in ("distance", "angle"):
            form = QFormLayout()
            e = QLineEdit(str(m.get("value")))

            def done():
                try:
                    v = float(e.text())
                except ValueError:
                    return
                if v != m.get("value"):
                    self.snapshot()
                    m["value"] = v
                    self.solve_all()
                    self.update_all()
            e.editingFinished.connect(done)
            form.addRow("Distance (mm)" if m["type"] == "distance" else "Angle (deg)", e)
            w = QWidget()
            w.setLayout(form)
            self.props_lay.addWidget(w)

    # ------------------------------------------------------------------ derived copies: patterns and mirror
    def refresh_derived(self):
        from asm_patterns import rebuild_derived
        try:
            rebuild_derived(self)
        except am.MateError as ex:
            self.say("Pattern problem: " + str(ex))

    def pattern_start(self, kind):
        from asm_patterns import start
        start(self, kind)

    def pattern_edit(self, pid):
        from asm_patterns import edit
        edit(self, pid)

    def pattern_delete(self, pid):
        from asm_patterns import delete
        delete(self, pid)

    def pattern_cancel(self, quiet=False):
        from asm_patterns import cancel
        cancel(self, quiet)

    def pat_toggle_comp(self, cid):
        from asm_patterns import toggle_comp
        toggle_comp(self, cid)

    def pat_set_plane(self, item):
        from asm_patterns import set_plane
        set_plane(self, item)

    def pat_set_entity(self, item):
        from asm_patterns import set_entity
        set_entity(self, item)

    # ------------------------------------------------------------------ evaluate
    def mass_open(self):
        from asm_patterns import mass_dialog
        mass_dialog(self)


def unused(*_a):
    return QApplication, QAbstractItemView, QToolButton, QSize


asm_sub.install_loader(AssemblyWindow)
