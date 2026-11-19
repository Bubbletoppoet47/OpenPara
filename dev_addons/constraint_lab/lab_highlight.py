"""lab_highlight.py - Constraint Lab: a picked or hovered face is shown by recolouring the face's own triangles.

The assembly window draws a picked face as a COPY of its triangles, lifted a hair along their normals and drawn over the part (part_refgeo.add_face_highlight).
It is a separate piece, so on a large part it hovers visibly off the face (and a thin sheet shows the gap).  In the baked outline drawing every part is one
mesh with a colour per cell, so the better way is to change the colour of the face's own cells: nothing floats, nothing can z-fight, and edges and points are
drawn exactly as before.  The lab window mixes this in (LabWindow); the real assembly window is not changed.  The ribbon button "Face Recolour" switches back
to the old lifted copy for comparison, and the old copy is also what the classic outline drawing (no per-cell colours) still gets.

Four methods of AssemblyWindow are overridden, the rest is inherited: draw_highlights, on_hover / clear_hover (the face branch only differs), and paint (the
part colour is re-applied under the tints)."""
import numpy as np
import pyvista as pv

import asm_refs
import assembly
import part_refgeo
import pm_app


class FaceTint:
    face_tint = True                  # True: recolour the face's own triangles; False: the old lifted copy
    HOVER_MIX = 0.8                   # the hover colour over the part colour (the old hover copy had opacity 0.8)

    # ------------------------------------------------------------------ the colours
    def _tints(self):
        return self.__dict__.setdefault("_tint_sel", set())            # {(component id, face number)} picked

    def part_colour(self, cid, e):
        """The colour the part has when nothing is highlighted (the same rule rebuild_scene follows)."""
        c = self.asm.comp(cid)
        if self.pat is not None and (c.get("derived") or {}).get("pat") == self.pat["data"]["id"]:
            return assembly.PREVIEW_COL
        return assembly.SEL_COL if cid == self.sel_comp else self.base_color(c, e["k"])

    def retint(self, cid, col=None):
        """Paint the surface cells of one part: its own colour everywhere, the hover colour on the hovered face, the pick colour on the picked faces."""
        e = self.entries.get(cid)
        if e is None or e.get("baked") is None:
            return
        mb, n_lines = e["baked"]
        face = np.asarray(mb.cell_data["face"])
        base = np.array(self.rgb255(col if col is not None else self.part_colour(cid, e)), float)
        arr = np.array(mb.cell_data["rgb"])
        arr[n_lines:] = base.astype(np.uint8)
        hv = self.__dict__.get("_tint_hover")
        if hv is not None and hv[0] == cid:
            arr[face == hv[1]] = np.round(self.HOVER_MIX * np.array(self.rgb255(self.HOVER_COL)) + (1 - self.HOVER_MIX) * base).astype(np.uint8)
        for c2, idx in self._tints():
            if c2 == cid:
                arr[face == idx] = self.rgb255(assembly.HI_COL)
        mb.cell_data["rgb"] = arr
        mb.GetCellData().Modified()
        mb.Modified()

    def tintable(self, e):
        return self.face_tint and e is not None and e.get("baked") is not None

    # ------------------------------------------------------------------ overridden: scene, paint
    def rebuild_scene(self, fit=False):
        self.__dict__["_tint_sel"], self.__dict__["_tint_hover"] = set(), None          # the meshes are new: nothing is tinted yet
        super().rebuild_scene(fit)

    def paint(self, e, col):
        super().paint(e, col)
        for cid, ee in self.entries.items():
            if ee is e:
                self.retint(cid, col)                                                       # the part colour changed: the tints go back on top
                break

    def set_face_tint(self, on):
        self.face_tint = bool(on)
        self.clear_hover(render=False)
        self.draw_highlights()

    # ------------------------------------------------------------------ overridden: the picks (assembly.py draw_highlights, face branch changed)
    def draw_highlights(self, render=True):
        pl = self.plotter
        for a, _cid in self.hi_actors:
            try:
                pl.remove_actor(a)
            except Exception:
                pass
        self.hi_actors = []
        old, new = set(self._tints()), set()
        for it in self.mate_sel + (self.pat.get("hi", []) if self.pat else []) + (self.rg["refs"] if self.rg else []) + (self.measure_items if self.mode == "measure" else []):
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
                if self.tintable(e):
                    new.add((it["cid"], it["idx"]))                                    # recolour its own triangles: no extra actor
                else:
                    cs = np.where(np.array(e["mesh"].cell_data["face"]) == it["idx"])[0]
                    if len(cs):
                        a = part_refgeo.add_face_highlight(pl, e["mesh"].extract_cells(cs), assembly.HI_COL)
            elif it["kind"] == "edge" and it["idx"] < len(e["polys"]):
                ml = pm_app.MainWindow.merged_lines([e["polys"][it["idx"]]])
                a = pl.add_mesh(ml, color=assembly.HI_COL, line_width=5, pickable=False, reset_camera=False)
                self.pull_actors.append((a, it["cid"]))
            elif it["kind"] == "vertex":
                a = pl.add_mesh(pv.PolyData(np.array([it["pt"]])), color=assembly.HI_COL, point_size=12, render_points_as_spheres=True,
                                pickable=False, reset_camera=False)
                self.pull_actors.append((a, it["cid"]))
            if a is not None:
                self.hi_actors.append((a, it["cid"]))
        self.__dict__["_tint_sel"] = new
        for cid in {c for c, _ in old | new}:                                          # every part that had or now has a picked face
            self.retint(cid)
        if self.rg and self.rg.get("ent") is not None:                 # preview of the plane / axis being made
            try:
                pa, _ = asm_refs.shape_actor(self, pl, pv, self.rg["ent"], asm_refs.REF_COL, 0.3, asm_refs.scene_size(self), 1.4)
                self.hi_actors.append((pa, "@"))
            except Exception:
                pass
        self.draw_measure_lines()
        self.update_poses(render=render)

    # ------------------------------------------------------------------ overridden: the hover (assembly.py on_hover / clear_hover, face branch changed)
    def clear_hover(self, render=True):
        hv = self.__dict__.get("_tint_hover")
        if hv is not None:
            self.__dict__["_tint_hover"] = None
            self.retint(hv[0])
            if render and self.plotter is not None:
                try:
                    self.plotter.render()
                except Exception:
                    pass
        super().clear_hover(render)

    def on_hover(self, x, y):
        """The cursor moved over the view while picking: light up the face / edge / point a click would take."""
        if self.mode not in ("mate", "refgeo", "pattern", "mirror_plane", "axis_pick", "measure") or not assembly.settings.get("hover") or self.plotter is None:
            if self.hover_actor is not None or self.__dict__.get("_tint_hover") is not None:
                self.clear_hover()
            return
        it = self.pick_item(x, y)
        key = None if it is None else (it["cid"], it["kind"], it["idx"])
        if key == self.hover_key:
            return
        self.clear_hover(render=False)
        self.hover_key = key
        if it is None:
            self.plotter.render()
            return
        pl, e = self.plotter, self.entries.get(it["cid"])
        a = None
        if e is not None:
            if it["kind"] == "face":
                if self.tintable(e):
                    self.__dict__["_tint_hover"] = (it["cid"], it["idx"])               # recolour its own triangles: no extra actor
                    self.retint(it["cid"])
                else:
                    cs = np.where(np.array(e["mesh"].cell_data["face"]) == it["idx"])[0]
                    if len(cs):
                        a = part_refgeo.add_face_highlight(pl, e["mesh"].extract_cells(cs), self.HOVER_COL)
                        a.prop.opacity = 0.8
            elif it["kind"] == "edge" and it["idx"] < len(e["polys"]):
                a = pl.add_mesh(pm_app.MainWindow.merged_lines([e["polys"][it["idx"]]]), color=self.HOVER_COL, line_width=4, pickable=False, reset_camera=False)
            elif it["kind"] == "vertex":
                a = pl.add_mesh(pv.PolyData(np.array([it["pt"]])), color=self.HOVER_COL, point_size=10, render_points_as_spheres=True,
                                pickable=False, reset_camera=False)
            if a is not None:
                try:
                    a.user_matrix = e["actor"].user_matrix       # it sits where its component sits
                    if it["kind"] != "face":                    # lines and points get the same depth bias as the outlines
                        self.hover_pull = (a, np.array(e["actor"].user_matrix))
                        a.user_matrix = getattr(self, "_pull_S", np.eye(4)) @ self.hover_pull[1]
                except Exception:
                    pass
                self.hover_actor = a
        pl.render()
