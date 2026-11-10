"""The Mesh FEA tab: the Voxel FEA tab's functions, with a tetrahedral solid instead of voxels.   NOT YET RUN by its author.

Same six steps as the Voxel FEA tab (supports, loads, groups, solvers, refinement, result fields, cut view, modulus measurement, checks):
    1. Geometry   a closed triangle mesh (STL etc.) from a Mesh tab or a file, or a test shape
    2. Mesh       adaptive triangle regularisation (quadric error decimation: flat areas lose triangles first, curved and thin areas keep them)
                  with a deviation report, then tetrahedra inside the reduced surface (uniform, or graded: small at the surface, bigger inside)
    3. Material   4. Supports and loads (box selection through the depth, groups)   5. Solve   6. Results
It is a subclass of VoxelTab, so everything that is not about voxels is the same code."""
import time

import numpy as np
import pyvista as pv
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSlider, QVBoxLayout, QWidget

import compat  # noqa: F401  (adds extract_surface_compat to pyvista datasets)
import fem3d as F
import look
import repair as R
import shapes as SH
import tabs as TB
import tet as TT
import verify as VF
from tasks import sub
from uiparts import button, row, spin, stack

FIELDS = [(("Element size" if k == "brick size" else n), k, kd, w) for n, k, kd, w in TB.FIELDS]
SURFACE_ABOVE = 200_000                    # more tetrahedra than this are drawn as their outer surface only
EDGES_BELOW = 60_000                       # element edges are drawn only up to this many faces


def _cube():
    return pv.Box(bounds=(0, 10, 0, 10, 0, 10), level=0, quads=False).triangulate().subdivide(3, subfilter="linear").clean()


TEST_SHAPES = {
    "Cube (10 mm)": _cube,
    "Bar 100 x 10 x 10 mm (beam theory)": lambda: SH.box_bar(),
    "Torus": lambda: SH.torus(),
    "Blob": lambda: SH.blob(),
    "Long bone-like shape": lambda: SH.bone(),
}


class MeshFEATab(TB.VoxelTab):
    KIND = "tet"
    TITLE = "Mesh FEA"

    # ------------------------------------------------------------------------------------------------------ small helpers
    def mc(self):
        if not hasattr(self, "_mc"):
            self._mc = {}
        return self._mc

    def order(self):
        return 2 if self.order_combo.currentIndex() == 0 else 1

    def build_ui(self):
        self.build_source_box()
        self.build_voxel_box()                    # (this tab's "2. Mesh"; the name is kept so the parent's build order still works)
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
        self.model_combo = QComboBox()
        self.model_combo.addItems(list(TEST_SHAPES))
        lay.addWidget(row(self.model_combo, button("Load test shape", self.load_test_model)))
        self.note(lay, "The shape must be a closed mesh (no holes, no surface cutting through itself) - repair it in a Mesh tab first. "
                       "A copy is taken: later changes in the Mesh tab show up here only when you import again.")

    def on_source_changed(self):
        self.update_source_label()
        self.update_estimate()
        self.show_source()
        self.refresh_group_list()

    def reset_discretisation(self):
        super().reset_discretisation()
        self.mc().clear()

    def load_test_model(self, name=None):
        name = name or self.model_combo.currentText()
        m = TEST_SHAPES[name]()
        self.set_source_mesh(R.to_mesh(*R.arrays(m)), f"test shape '{name}'")

    # ------------------------------------------------------------------------------------------------------ 2. mesh
    def advanced(self, lay, title="Advanced parameters"):
        """A tick box that shows or hides a block of the less common inputs; returns the layout to put them in."""
        chk = QCheckBox(title)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(14, 0, 0, 0)
        inner.setVisible(False)
        chk.toggled.connect(inner.setVisible)
        lay.addWidget(chk)
        lay.addWidget(inner)
        return il

    def solver_tol_value(self):
        try:
            v = float(self.solver_tol.currentText().strip())
        except ValueError:
            raise ValueError("The solver tolerance must be a number such as 1e-6.")
        if not 1e-12 <= v <= 1e-1:
            raise ValueError("The solver tolerance must be between 1e-12 and 0.1.")
        return v

    def build_voxel_box(self):
        lay = self.box("2. Mesh")
        self.tri_spin = spin(1000, 5_000_000, 60_000, 0, 10_000, " triangles")
        self.tri_spin.valueChanged.connect(self.update_estimate)
        lay.addWidget(row("Surface triangles (target)", self.tri_spin))
        lay.addWidget(button("Reduce the surface and show the deviation", self.do_reduce))
        self.fill_lbl = QLabel("")
        self.fill_lbl.setWordWrap(True)
        self.fill_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.fill_lbl)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Uniform tetrahedra (as small as the surface triangles everywhere)", "Graded tetrahedra (small at the surface, bigger inside)"])
        lay.addWidget(self.mode_combo)
        self.est_lbl = QLabel("")
        self.est_lbl.setWordWrap(True)
        lay.addWidget(self.est_lbl)
        lay.addWidget(button("Reduce, mesh and show", self.do_mesh))
        self.note(lay, "Flat areas lose their triangles first, thin and curved areas keep them. Check the deviation report before meshing.")
        al = self.advanced(lay)
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["Quadric decimation (VTK, always available)", "fast_simplification (if installed, faster)"])
        al.addWidget(self.engine_combo)
        self.keepvol_check = QCheckBox("Favour keeping the volume")
        self.keepvol_check.setChecked(True)
        al.addWidget(self.keepvol_check)
        self.dev_spin = look.UnitSpin("L", 1e-6, 1e4, 0.02, 5, 0.005)
        al.addWidget(row("Largest deviation allowed", self.dev_spin))
        al.addWidget(button("Find the triangle count for that deviation", self.do_find))
        self.note(al, "The deviation is measured both ways (reduced surface to original and back), sampled on large meshes.")
        self.levels_combo = QComboBox()
        self.levels_combo.addItems(["2 x the surface size", "4 x the surface size", "8 x the surface size", "16 x the surface size"])
        self.levels_combo.setCurrentIndex(1)
        self.levels_combo.currentIndexChanged.connect(self.update_estimate)
        self.grade_spin = spin(0.1, 3.0, 0.5, 2, 0.1)
        self.adapt_box = QWidget()
        gl = QVBoxLayout(self.adapt_box)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.addWidget(row("Graded: biggest element", self.levels_combo))
        gl.addWidget(row("Graded: growth with depth", self.grade_spin))
        self.note(gl, "Near the surface the tetrahedra are as big as the surface triangles; further in they grow by 'growth' per unit of distance up to the biggest element. Lower growth = more elements, better answer.")
        self.adapt_box.setVisible(False)
        al.addWidget(self.adapt_box)
        self.order_combo = QComboBox()
        self.order_combo.addItems(["Quadratic tetrahedra (10 nodes, accurate, default)", "Linear tetrahedra (4 nodes, stiff and cheap)"])
        self.order_combo.currentIndexChanged.connect(self.update_estimate)
        al.addWidget(self.order_combo)
        self.limit_spin = spin(1000, 20_000_000, 400_000, 0, 50_000, " elements")
        al.addWidget(row("Refuse above", self.limit_spin))
        self.crop_spins = []
        for _a in TB.AXES:
            sp = spin(5, 100, 100, 0, 5, " %")
            sp.valueChanged.connect(self.update_estimate)
            self.crop_spins.append(sp)
        al.addWidget(stack("Block from the middle (X, Y, Z)", *self.crop_spins))
        self.note(al, "The block cut is capped with new flat faces (clean ends for supports and loads); on a very porous surface the caps can be rough.")
        self.mode_combo.currentIndexChanged.connect(self.mode_changed)

    def update_estimate(self, *_a):
        s = self.src
        if s["kind"] != "mesh":
            self.est_lbl.setText("")
            return
        frac = float(np.prod(self.crop_values()))
        have = int(s["mesh"].n_cells * frac ** (2.0 / 3.0))
        target = min(int(self.tri_spin.value()), max(have, 1))
        mode = "graded" if self.adaptive() else "uniform"
        nt, nd, gb = TT.estimate(target, mode, self.order())
        over = nt > self.limit_spin.value()
        self.est_lbl.setText(f"Original: {s['mesh'].n_cells:,} triangles (about {have:,} after the block cut).  Rough guess for {target:,} triangles: about {nt:,} tetrahedra, "
                             f"{nd:,} unknowns, the matrix alone about {gb:.1f} GB (the solver needs 2 to 3 times that).")
        self.est_lbl.setStyleSheet("color:#b00020;" if over else "")

    # ---- the pipeline (these run in the worker thread)
    def crop_surface(self, a, cb=None):
        s = a["src"]
        if s["kind"] != "mesh":
            raise ValueError("Bring in a closed mesh first.")
        key = ("crop", id(s["mesh"]), tuple(round(c, 6) for c in a["crop"]))
        mc = self.mc()
        if mc.get("crop_key") == key:
            return mc["crop"]
        m = TT.crop_block(s["mesh"], a["crop"], cb)
        mc.clear()
        mc.update(crop_key=key, crop=m)
        return m

    def reduced_surface(self, target, a, cb=None):
        crop = self.crop_surface(a, sub(cb, 0.0, 0.3))
        target = int(min(target, crop.n_cells))
        mc = self.mc()
        key = (mc["crop_key"], target, a["engine"], a["keep"])
        if mc.get("red_key") == key:
            return mc["red"], mc["red_info"]
        surf, info = TT.reduce_surface(crop, target, a["engine"], a["keep"], sub(cb, 0.3, 1.0))
        for k in ("tet_key", "tet"):
            mc.pop(k, None)
        mc.update(red_key=key, red=surf, red_info=info)
        return surf, info

    def tets_for(self, target, a, cb=None):
        """(nodes, conn, tet info, reduced surface, surface info) - kept for next time while nothing that matters changes."""
        surf, rinfo = self.reduced_surface(target, a, sub(cb, 0.0, 0.4))
        mc = self.mc()
        mode = "graded" if a["adaptive"] else "uniform"
        key = (mc["red_key"], mode, a["biggest"], round(a["grade"], 4), a["order"])
        if mc.get("tet_key") == key:
            return mc["tet"] + (surf, rinfo)
        nodes, conn, tinfo = TT.tetrahedralise(surf, mode, a["biggest"], a["grade"], a["order"], sub(cb, 0.4, 1.0))
        if len(conn) > a["limit"]:
            raise ValueError(f"{len(conn):,} tetrahedra is more than the limit of {int(a['limit']):,}. Use fewer surface triangles, graded elements, or raise the limit.")
        mc.update(tet_key=key, tet=(nodes, conn, tinfo))
        return nodes, conn, tinfo, surf, rinfo

    def build_nodes_box(self):
        super().build_nodes_box()
        lay = self.last_box                       # the layout of the step the parent just built
        depth_row = self.depth_lo.parentWidget()
        lay.removeWidget(depth_row)
        al = self.advanced(lay)
        al.addWidget(depth_row)
        self.note(al, "Depth range: the box selects only nodes between these percentages of the model's depth along the viewing direction.")

    def run_args(self):
        E, nu = self.mat.values()
        ax = self.axis_combo.currentIndex() - 1 if hasattr(self, "axis_combo") else -1
        return dict(E=E, nu=nu, axis=None if ax < 0 else ax, method=["auto", "direct", "amg", "cg"][self.solver_combo.currentIndex()], limit=self.limit_spin.value(),
                    groups=list(self.groups), area=self.area_spin.internal() if hasattr(self, "area_spin") else 0.0,
                    length=self.len_spin.internal() if hasattr(self, "len_spin") else 0.0, src=self.src, crop=self.crop_values(), adaptive=self.adaptive(),
                    biggest=2.0 ** (self.levels_combo.currentIndex() + 1), grade=self.grade_spin.value(), order=self.order(), target=int(self.tri_spin.value()),
                    engine="fast" if self.engine_combo.currentIndex() == 1 else "vtk", keep=self.keepvol_check.isChecked(), dev=self.dev_spin.internal(),
                    tol=self.solver_tol_value(), maxit=int(self.solver_maxit.value()))

    def args_or_fail(self, what):
        try:
            a = self.run_args()
        except ValueError as ex:
            self.fail(what, str(ex))
            return None
        if a["src"]["kind"] != "mesh":
            self.fail(what, "Bring in a closed mesh first (step 1).")
            return None
        return a

    def mesh_text(self, rinfo, tinfo):
        s = (f"surface {rinfo['triangles_in']:,} to {rinfo['triangles_out']:,} triangles ({rinfo['engine']}, {rinfo['seconds']:.1f} s"
             + (f", {rinfo['retries']} retr{'y' if rinfo['retries'] == 1 else 'ies'} with a gentler reduction" if rinfo["retries"] else "") + "); "
             f"{tinfo['tets']:,} tetrahedra from gmsh ({tinfo['algorithm']}, {tinfo['seconds']:.1f} s), {tinfo['nodes']:,} nodes; "
             f"element quality (1 = regular): worst {tinfo['q_min']:.3f}, 1 % below {tinfo['q_p1']:.3f}, {tinfo['slivers']:,} slivers under 0.02")
        return s

    # ---- reduce only
    def do_reduce(self):
        a = self.args_or_fail("Reduce")
        if a is None:
            return

        def work(cb):
            surf, info = self.reduced_surface(a["target"], a, sub(cb, 0.0, 0.5))
            crop = self.mc()["crop"]
            dev = TT.Reference(crop).deviation(surf, sub(cb, 0.5, 1.0))
            return surf, info, dev

        def done(res):
            surf, info, dv = res
            if info.get("open_edges") or info.get("nonmanifold_edges"):
                warn = f"\nWARNING: the reduced surface has {info.get('open_edges', 0)} open and {info.get('nonmanifold_edges', 0)} non-manifold edges."
            else:
                warn = ""
            txt = (f"{info['triangles_in']:,} to {info['triangles_out']:,} triangles ({info['engine']}, {info['seconds']:.1f} s)\n"
                   f"Deviation: largest {look.fmt('L', dv['max'], 4)}, 99.9 % under {look.fmt('L', dv['p999'], 4)}, mean {look.fmt('L', dv['mean'], 4)}  ({dv['samples']:,} points)\n"
                   f"Volume change {dv['volume_change'] * 100:+.3f} %  -  triangle edge median {look.fmt('L', info['median_edge'], 4)}{warn}")
            self.fill_lbl.setTextFormat(Qt.TextFormat.PlainText)
            self.fill_lbl.setText(txt)
            self.clear_scene()
            self.put("surface", surf, color="#c9d3dc", smooth_shading=False, show_edges=surf.n_cells <= EDGES_BELOW, line_width=0.4)
            self.plotter.reset_camera()
            self.statusBar().showMessage(f"Surface reduced to {info['triangles_out']:,} triangles, largest deviation {look.fmt('L', dv['max'], 4)}.")
        self.run_task("Reduce the surface", work, done)

    def do_find(self):
        a = self.args_or_fail("Find the triangle count")
        if a is None:
            return

        def work(cb):
            crop = self.crop_surface(a, sub(cb, 0.0, 0.05))
            ref = TT.Reference(crop)
            return TT.count_for_deviation(ref, a["dev"], engine=a["engine"], keep_volume=a["keep"], progress=sub(cb, 0.05, 1.0))

        def done(res):
            n, rows, ok = res
            lines = [f"{'asked':>10} {'got':>10} {'largest dev.':>14} {'99 % under':>12} {'volume':>8}"]
            lines += [f"{r_[0]:>10,} {r_[1]:>10,} {look.fmt('L', r_[2], 4):>14} {look.fmt('L', r_[3], 4):>12} {r_[4] * 100:>+7.2f}%" for r_ in rows]
            lines.append(f"Found: about {n:,} triangles keep every point within {look.fmt('L', a['dev'], 4)}." if ok
                         else f"Not reached even with every triangle ({n:,}): the original is already coarser than that, or the deviation limit is below its own roughness.")
            self.fill_lbl.setText("<pre style='margin:0'>" + "\n".join(lines) + "</pre>")
            self.fill_lbl.setTextFormat(Qt.TextFormat.RichText)
            self.tri_spin.setValue(n)
            self.statusBar().showMessage(lines[-1])
        self.run_task("Find the triangle count", work, done)

    # ---- mesh and show
    def do_mesh(self):
        a = self.args_or_fail("Mesh")
        if a is None:
            return

        def work(cb):
            nodes, conn, tinfo, surf, rinfo = self.tets_for(a["target"], a, sub(cb, 0.0, 0.9))
            model = TT.TetModel(nodes, conn)
            g = model.grid()
            shown = g.extract_surface_compat() if model.ne > SURFACE_ABOVE else g
            return model, shown, tinfo, rinfo

        def done(res):
            model, shown, tinfo, rinfo = res
            self.result = None
            self.clear_scene()
            self.put("mesh", shown, scalars="element size", cmap="viridis_r", show_edges=shown.n_cells <= EDGES_BELOW, line_width=0.3, show_scalar_bar=False)
            self.plotter.reset_camera()
            self.set_nodes(model.node_xyz())
            self.fill_lbl.setTextFormat(Qt.TextFormat.PlainText)
            self.fill_lbl.setText(self.mesh_text(rinfo, tinfo))
            self.statusBar().showMessage(model.summary() + f"; {len(model.nodes):,} nodes can be selected.")
        self.run_task("Mesh", work, done)

    # ------------------------------------------------------------------------------------------------------ 5. solve
    def build_solve_box(self):
        lay = self.box("5. Solve")
        self.solver_combo = QComboBox()
        self.solver_combo.addItems(["Automatic", "Direct (PARDISO or SuperLU)", "Multigrid + CG (needs pyamg)", "Plain CG (no extra packages, slow)"])
        lay.addWidget(self.solver_combo)
        lay.addWidget(button("Run", self.do_run))
        al = self.advanced(lay)
        self.solver_tol = QComboBox()
        self.solver_tol.setEditable(True)
        self.solver_tol.addItems(["1e-4", "1e-5", "1e-6", "1e-7", "1e-8"])
        self.solver_tol.setCurrentText("1e-6")
        self.solver_tol.setToolTip("The iterative solvers stop when the unbalanced force, as a fraction of the applied load, is below this. Smaller = slower. Ignored by the direct solver.")
        al.addWidget(row("Solver tolerance", self.solver_tol))
        self.solver_maxit = spin(50, 200000, 4000, 0, 500, " iterations")
        al.addWidget(row("Most iterations", self.solver_maxit))
        self.refine_check = QCheckBox("Refine until the result settles")
        self.refine_check.setToolTip("Runs again with 1.5625 times more surface triangles (and so finer tetrahedra) until the apparent modulus changes by less than the tolerance. "
                                     "The last step uses every triangle of the (cropped) original.")
        self.refine_check.toggled.connect(lambda on: self.refine_box.setVisible(on))
        al.addWidget(self.refine_check)
        self.refine_box = QWidget()
        rl = QVBoxLayout(self.refine_box)
        rl.setContentsMargins(14, 0, 0, 0)
        self.tol_spin = spin(0.05, 50, 2.0, 2, 0.5, " %")
        self.steps_spin = spin(2, 12, 6, 0, 1)
        rl.addWidget(row("Stop when the modulus changes by less than", self.tol_spin))
        rl.addWidget(row("Most steps", self.steps_spin))
        self.refine_box.setVisible(False)
        al.addWidget(self.refine_box)
        self.note(al, "A force is shared equally among the group's nodes, which is only approximate with 10-node tetrahedra. For measuring a modulus use 'Move by' on the loaded end.")

    def run_once(self, target, a, cb):
        t0 = time.time()
        if not a["groups"]:
            raise ValueError("There are no supports or loads. Select nodes (step 4) and put them in groups: a support and a displacement or force.")
        nodes, conn, tinfo, surf, rinfo = self.tets_for(target, a, sub(cb, 0.0, 0.55))
        model = TT.TetModel(nodes, conn)
        model.assemble(a["E"], a["nu"], sub(cb, 0.55, 0.65))
        sol = F.solve(model, a["groups"], a["method"], tol=a["tol"], maxit=a["maxit"], progress=sub(cb, 0.65, 0.95))
        axis = a["axis"] if a["axis"] is not None else F.auto_axis(a["groups"])
        if axis is None:
            raise ValueError("To measure a modulus, one direction needs both a support and a loaded group (displacement or force) acting along it.")
        app = F.apparent(model, a["groups"], sol, axis, a["area"] or None, a["length"] or None)
        return {"model": model, "sol": sol, "app": app, "fields": model.fields(sol["u"]), "groups": a["groups"], "h": rinfo["median_edge"], "axis": axis, "elements": model.ne,
                "E": a["E"], "seconds": time.time() - t0, "refine": None, "target": int(target), "tinfo": tinfo, "rinfo": rinfo}

    def do_run(self):
        a = self.args_or_fail("Run")
        if a is None:
            return
        if not a["groups"]:
            return self.fail("Run", "Make the supports and loads first (step 4).")
        if self.refine_check.isChecked():
            return self.do_refine(a)
        self.run_task("Run", lambda cb: self.run_once(a["target"], a, cb), self.finish_run)

    def do_refine(self, a):
        tol, steps = self.tol_spin.value() / 100.0, int(self.steps_spin.value())
        last, lens = {}, {}

        def work(cb):
            n_max = self.crop_surface(a, sub(cb, 0.0, 0.02)).n_cells
            targets = []
            for k in range(steps):
                t = int(min(a["target"] * 1.5625 ** k, n_max))
                if targets and t <= targets[-1]:
                    break
                targets.append(t)
                if t >= n_max:
                    break

            def run(t):
                r = self.run_once(t, a, sub(cb, 0, 1))
                last["r"] = r
                lens[t] = r["h"]
                return r["app"]["E_app"], r["elements"]
            rows, ok, why = F.converge(run, targets, tol, cb)
            return [(lens.get(s_, s_), n, E, ch) for s_, n, E, ch in rows], ok, why, last.get("r")

        def done(res):
            rows, ok, why, r = res
            if r is None:
                return self.fail("Refine", why)
            r["refine"] = {"rows": rows, "ok": ok, "why": why}
            self.tri_spin.setValue(r["target"])
            self.finish_run(r)
        self.run_task("Refine", work, done)

    def finish_run(self, r):
        self.result = r
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
        self.res_lbl = QLabel("")
        self.res_lbl.setWordWrap(True)
        self.res_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.res_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.res_lbl)
        al = self.advanced(lay)
        self.def_edit = QLineEdit("")
        self.def_edit.setPlaceholderText("auto")
        self.def_edit.editingFinished.connect(self.delayed_refresh)
        al.addWidget(row("Deformation scale", self.def_edit))
        self.edges_check = QCheckBox("Show element edges (surface faces, up to a limit)")
        self.edges_check.toggled.connect(self.delayed_refresh)
        al.addWidget(self.edges_check)
        self.cut_check = QCheckBox("Cut the model open")
        self.cut_check.toggled.connect(self.delayed_refresh)
        self.cut_axis = QComboBox()
        self.cut_axis.addItems(TB.AXES)
        self.cut_axis.currentIndexChanged.connect(self.delayed_refresh)
        self.cut_slider = QSlider(Qt.Orientation.Horizontal)
        self.cut_slider.setRange(0, 100)
        self.cut_slider.setValue(50)
        self.cut_slider.valueChanged.connect(self.delayed_refresh)
        al.addWidget(self.cut_check)
        al.addWidget(row("Cut across", self.cut_axis))
        al.addWidget(row("Position", self.cut_slider))
        self.axis_combo = QComboBox()
        self.axis_combo.addItems(["Automatic", "Along X", "Along Y", "Along Z"])
        self.area_spin = look.UnitSpin("A", 0.0, 1e12, 0.0, 4, 1.0)
        self.len_spin = look.UnitSpin("L", 0.0, 1e9, 0.0, 4, 1.0)
        al.addWidget(row("Modulus direction", self.axis_combo))
        al.addWidget(row("Area (0 = automatic)", self.area_spin))
        al.addWidget(row("Length (0 = automatic)", self.len_spin))
        self.note(al, "E = (reaction force / area) / (movement / length). Automatic: the direction that has both a support and a loaded group, "
                      "the area is the bounding rectangle of the support and loaded groups, the length the distance between them.")

    def show_result_text(self):
        super().show_result_text()
        r = self.result
        if r is None or "tinfo" not in r:
            return
        col = "#b00020" if r["tinfo"]["q_min"] < 0.01 else "#506080"
        self.res_lbl.setText(self.res_lbl.text() + f"<br><span style='color:{col}'><b>Mesh:</b> {self.mesh_text(r['rinfo'], r['tinfo'])}</span>")

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
            size = float(np.ptp(model.node_xyz_all(), axis=0).max())
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
        if g.n_cells > SURFACE_ABOVE:
            g = g.extract_surface_compat()                  # a very large solid is drawn as its outer skin (the cut view still shows the cut face)
        v = g.point_data[key] if where == "node" else g.cell_data[key]
        hi = float(np.percentile(v, 99.5)) if len(v) else 1.0
        lo = float(np.percentile(v, 0.5)) if key in TB.SIGNED else float(v.min()) if len(v) and key == "brick size" else 0.0
        title = f"{name} ({look.name(kind)})"
        self.clear_scene()
        self.put("result", g, scalars=key, cmap=look.cmap(), clim=[lo, hi if hi > lo else lo + 1e-9], show_edges=self.edges_check.isChecked() and g.n_cells <= EDGES_BELOW,
                 line_width=0.4, scalar_bar_args={"title": title, "vertical": False})
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
        self.verify_out.setPlaceholderText("Compares the tetrahedral solver with exact answers (single element patch tests, solid block, beam theory, convergence). Takes a few minutes.")
        lay.addWidget(self.verify_out)

    def run_checks(self, runner=None):
        super().run_checks(runner or VF.tet_checks)

    def open_mesh_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open mesh", "", "Meshes (*.stl *.obj *.ply *.vtk *.vtp);;All files (*)")
        if p:
            self.open_mesh(p)
