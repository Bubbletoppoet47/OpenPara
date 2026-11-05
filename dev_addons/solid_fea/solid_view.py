"""solid_view.py - the 3D view of the 3D FEA window: the part with its faces coloured, click-to-pick a face, and the result as a coloured surface."""
import numpy as np

try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
except Exception:                                   # pragma: no cover
    pv, QtInteractor = None, None



def _surface(g):
    try:
        return g.extract_surface(algorithm="dataset_surface")
    except TypeError:
        return g.extract_surface()


GREY = (0.78, 0.80, 0.84)
PICK = (1.0, 0.62, 0.1)
SUPPORT = (0.25, 0.5, 0.95)
LOAD = (0.9, 0.25, 0.25)


class SolidView:
    def __init__(self, parent):
        self.plotter = None
        self.widget = None
        self.on_pick = None                        # fn(face id, (x, y, z))
        self.cell_face = np.zeros(0, int)
        self.rgb = np.zeros((0, 3))
        self.actor = None
        self.poly = None
        self.result_actor = None
        self._down = None
        self.probe_mode = False
        self.on_probe = None                       # fn((x, y, z)) while probe_mode is on
        self.mesh_actor = None
        if QtInteractor is None:
            return
        try:
            self.plotter = QtInteractor(parent)
            self.widget = self.plotter
            self.plotter.set_background("white")
            self.plotter.iren.add_observer("LeftButtonPressEvent", self._press)
            self.plotter.iren.add_observer("LeftButtonReleaseEvent", self._release)
        except Exception:
            self.plotter = None
            self.widget = None

    # ------------------------------------------------------------------ the part
    def set_geometry(self, P, T, F):
        self.cell_face = F
        self.rgb = np.tile(GREY, (len(T), 1))
        if self.plotter is None:
            return
        self.clear_result()
        if self.actor is not None:
            self.plotter.remove_actor(self.actor)
            self.actor = None
        if not len(T):
            return
        faces = np.hstack([np.full((len(T), 1), 3), T]).ravel()
        self.poly = pv.PolyData(P, faces)
        self.poly.cell_data["rgb"] = (self.rgb * 255).astype(np.uint8)
        self.actor = self.plotter.add_mesh(self.poly, scalars="rgb", rgb=True, show_edges=False, pickable=True, reset_camera=False)
        self.plotter.reset_camera()
        self.plotter.render()

    def colour_faces(self, colours):
        """colours: {face id: (r, g, b)}; every other face is grey."""
        self.rgb = np.tile(GREY, (len(self.cell_face), 1))
        for fid, c in colours.items():
            self.rgb[self.cell_face == fid] = c
        if self.plotter is not None and self.poly is not None:
            self.poly.cell_data["rgb"] = (self.rgb * 255).astype(np.uint8)
            self.plotter.render()

    # ------------------------------------------------------------------ picking
    def _press(self, *_a):
        try:
            self._down = self.plotter.iren.interactor.GetEventPosition()
        except Exception:
            self._down = None

    def _release(self, *_a):
        try:
            up = self.plotter.iren.interactor.GetEventPosition()
        except Exception:
            return
        if self._down is None or abs(up[0] - self._down[0]) > 3 or abs(up[1] - self._down[1]) > 3:
            return                                               # it was a rotation or a pan
        self.pick_at(up[0], up[1])

    def pick_at(self, x, y):
        """Picks the face under the display point (x, y); calls on_pick(face id, point).  The face id, or None."""
        if self.plotter is None or self.actor is None:
            return None
        import vtk
        pk = vtk.vtkCellPicker()
        pk.SetTolerance(0.0005)
        if self.probe_mode:                                      # a probe reads the result surface on screen, not a face of the part
            shown = self.result_actor if self.result_actor is not None else self.mesh_actor
            if shown is None:
                if self.on_probe:
                    self.on_probe(None)
                return None
            pk.AddPickList(shown)
            pk.PickFromListOn()
            if not pk.Pick(x, y, 0, self.plotter.renderer):
                return None
            if self.on_probe and self.result_actor is not None:
                self.on_probe(tuple(pk.GetPickPosition()))
            return -1
        pk.AddPickList(self.actor)
        pk.PickFromListOn()
        if not pk.Pick(x, y, 0, self.plotter.renderer):
            return None
        cid = pk.GetCellId()
        if cid < 0 or cid >= len(self.cell_face):
            return None
        fid = int(self.cell_face[cid])
        if self.on_pick:
            self.on_pick(fid, tuple(pk.GetPickPosition()))
        return fid

    # ------------------------------------------------------------------ results
    def clear_result(self):
        if self.plotter is not None and self.result_actor is not None:
            self.plotter.remove_actor(self.result_actor)
            try:
                self.plotter.remove_scalar_bar()
            except Exception:
                pass                                         # no bar yet
        self.result_actor = None
        if self.plotter is not None and self.mesh_actor is not None:
            self.plotter.remove_actor(self.mesh_actor)
        self.mesh_actor = None
        if self.actor is not None:
            self.actor.SetVisibility(True)

    def show_result(self, nodes, conn, u, values, title, scale=0.0, edges=False):
        """The deformed part as a surface coloured by `values` (one per node)."""
        if self.plotter is None:
            return False
        self.clear_result()
        pts = nodes + scale * u
        cells = np.hstack([np.full((len(conn), 1), 4), conn[:, :4]]).ravel().astype(np.int64)
        g = pv.UnstructuredGrid(cells, np.full(len(conn), pv.CellType.TETRA, np.uint8), pts)
        g.point_data[title] = values
        surf = _surface(g)
        self.result_actor = self.plotter.add_mesh(surf, scalars=title, cmap="turbo", show_edges=edges, reset_camera=False,
                                                  scalar_bar_args={"title": title, "vertical": False})
        if self.actor is not None:
            self.actor.SetVisibility(False)
        self.plotter.render()
        return True

    def show_mesh(self, nodes, conn):
        """The meshed part before any result: a plain light-grey surface with the mesh edges and no colour bar."""
        if self.plotter is None:
            return False
        self.clear_result()
        cells = np.hstack([np.full((len(conn), 1), 4), conn[:, :4]]).ravel().astype(np.int64)
        g = pv.UnstructuredGrid(cells, np.full(len(conn), pv.CellType.TETRA, np.uint8), nodes)
        self.mesh_actor = self.plotter.add_mesh(_surface(g), color=GREY, show_edges=True, edge_color=(0.35, 0.38, 0.42), reset_camera=False)
        if self.actor is not None:
            self.actor.SetVisibility(False)
        self.plotter.render()
        return True

    @staticmethod
    def render_frames(nodes, conn, u, values, title, scale, frames, edges=False, size=(900, 600)):
        """Pictures of the deformation growing from 0 to `scale` (an off-screen render: works when the window is hidden).  [numpy RGB images]"""
        if pv is None:
            return []
        cells = np.hstack([np.full((len(conn), 1), 4), conn[:, :4]]).ravel().astype(np.int64)
        ct = np.full(len(conn), pv.CellType.TETRA, np.uint8)
        lo, hi = float(np.min(values)), float(np.max(values))
        if hi <= lo:
            hi = lo + 1.0
        out = []
        pl = pv.Plotter(off_screen=True, window_size=list(size))
        try:
            for k in range(frames):
                a = k / max(frames - 1, 1)
                g = pv.UnstructuredGrid(cells, ct, nodes + scale * a * u)
                g.point_data[title] = values
                pl.clear()
                pl.set_background("white")
                pl.add_mesh(_surface(g), scalars=title, cmap="turbo", clim=[lo, hi], show_edges=edges,
                            scalar_bar_args={"title": title, "vertical": False})
                if k == 0:
                    pl.reset_camera()
                out.append(np.asarray(pl.screenshot(return_img=True))[:, :, :3].copy())
        finally:
            pl.close()
        return out

    def screenshot(self):
        if self.plotter is None:
            return None
        self.plotter.render()
        return self.plotter.screenshot(return_img=True)

    def close(self):
        if self.plotter is not None:
            try:
                self.plotter.close()
            except Exception:
                pass
