"""solid_view.py - the 3D view of the 3D FEA window: the part with its faces coloured, click-to-pick a face, the result as a coloured surface
(the same colour scheme and legend look as 1D FEA), an X / Y / Z axes triad in the bottom-left corner, and the pictures of an animation.

The result surface is built once; an animation only moves its points and recolours them (set_ramp), so a frame is cheap.
"""
import numpy as np

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QImage, QPainter

import legend_draw
import result_style

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
NO_DATA = (153, 153, 153)                           # a value that does not exist (no yield strength for a safety factor)
LEGEND_W = 240                                      # the legend is drawn in a picture this wide (its text wraps inside it) and put top right
AXES_BOX = (0.0, 0.0, 0.2, 0.2)                     # the axes triad: bottom-left corner, as a fraction of the view


def _cells(conn):
    return np.hstack([np.full((len(conn), 1), 4), conn[:, :4]]).ravel().astype(np.int64)


def _grid(nodes, conn):
    """The mesh as a VTK grid.  `conn` is the connectivity of tetrahedra, or {"cells", "types"} for a mesh with hexahedra and pyramids too (corner nodes)."""
    if isinstance(conn, dict):
        return pv.UnstructuredGrid(conn["cells"], conn["types"], np.asarray(nodes, float))
    return pv.UnstructuredGrid(_cells(conn), np.full(len(conn), pv.CellType.TETRA, np.uint8), np.asarray(nodes, float))


def _result_surface(nodes, conn):
    """The outside of the mesh as a surface, and for every surface point the node of the mesh it came from."""
    surf = _surface(_grid(nodes, conn))
    return surf, np.asarray(surf.point_data["vtkOriginalPointIds"]).astype(np.int64)


def qimage_array(q):
    """A QImage as an (h, w, 4) RGBA uint8 array."""
    q = q.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = q.width(), q.height()
    raw = np.frombuffer(bytes(q.constBits().asarray(q.sizeInBytes())), dtype=np.uint8).reshape(h, q.bytesPerLine() // 4, 4)
    return raw[:, :w].copy()


def draw_axes(plotter):
    """The X / Y / Z triad in the bottom-left corner; it turns with the camera.  True when it could be added."""
    try:
        plotter.add_axes(line_width=3, color="black", interactive=False, viewport=AXES_BOX)
        return True
    except Exception:                                # an older pyvista
        try:
            plotter.add_axes()
            return True
        except Exception:
            return False


class _Resized(QObject):
    """Calls fn when the widget it watches changes size."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def eventFilter(self, _o, ev):
        if ev.type() == QEvent.Type.Resize:
            try:
                self.fn()
            except Exception:                         # noqa: BLE001 - a repaint helper must never break the window
                pass
        return False


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
        self.res = None                            # the result surface on show (see show_result)
        self.legend_spec = None                    # {"title", "labels", "subtitle"} of the colour legend on show
        self.legend = None                         # the legend picture in the corner: {"rep", "widget", "w", "h"}
        self.legend_note = False                   # True when the legend had to fall back to one line of text
        self.axes_on = False
        self.lines = {}                            # name -> actor of a line overlay (see set_lines)
        self.line_data = {}                        # name -> its segments (kept for the tests and when there is no 3D view)
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
            return
        self.axes_on = draw_axes(self.plotter)
        self._resized = _Resized(self.place_legend)
        self.plotter.installEventFilter(self._resized)

    # ------------------------------------------------------------------ the part
    def set_geometry(self, P, T, F, keep_camera=False):
        """keep_camera: the part is the same part with other faces (a split was changed): the view stays where it is."""
        keep_camera = keep_camera and self.actor is not None
        self.cell_face = F
        self.rgb = np.tile(GREY, (len(T), 1))
        if self.plotter is None:
            return
        self.clear_result()
        for name in list(self.lines):
            self.set_lines(name, [])
        if self.actor is not None:
            self.plotter.remove_actor(self.actor)
            self.actor = None
        if not len(T):
            return
        faces = np.hstack([np.full((len(T), 1), 3), T]).ravel()
        self.poly = pv.PolyData(P, faces)
        self.poly.cell_data["rgb"] = (self.rgb * 255).astype(np.uint8)
        self.actor = self.plotter.add_mesh(self.poly, scalars="rgb", rgb=True, show_edges=False, pickable=True, reset_camera=False)
        if not keep_camera:
            self.plotter.reset_camera()
        self.plotter.render()

    def set_lines(self, name, segs, color=(0.1, 0.12, 0.2), width=1.5):
        """Draws line segments [(p0, p1)] over the part under `name` ('grid' = the outlines of the patches of split faces, 'preview' = the grid that
        Split would cut); an empty list takes them away."""
        old = self.lines.pop(name, None)
        self.line_data[name] = list(segs)
        if self.plotter is None:
            return
        if old is not None:
            self.plotter.remove_actor(old)
        if not len(segs):
            self.plotter.render()
            return
        P = np.array([p for s in segs for p in s], float).reshape(-1, 3)
        cells = np.hstack([np.full((len(segs), 1), 2), np.arange(0, 2 * len(segs), 2)[:, None], np.arange(1, 2 * len(segs), 2)[:, None]]).ravel()
        poly = pv.PolyData(P, lines=cells)
        self.lines[name] = self.plotter.add_mesh(poly, color=color, line_width=width, pickable=False, reset_camera=False, show_scalar_bar=False)
        self.plotter.render()

    def colour_faces(self, colours):
        """colours: {face id: (r, g, b)}; every other face is grey."""
        self.rgb = np.tile(GREY, (len(self.cell_face), 1))
        for fid, c in colours.items():
            self.rgb[self.cell_face == fid] = c
        if self.plotter is not None and self.poly is not None:
            self.poly.cell_data["rgb"] = (self.rgb * 255).astype(np.uint8)
            self.plotter.render()

    def fit(self):
        """Zoom to fit: the whole part in view, the viewing direction unchanged."""
        if self.plotter is not None:
            self.plotter.reset_camera()
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

    # ------------------------------------------------------------------ the colour legend (drawn like the 1D FEA one)
    def dpr(self):
        try:
            return float(self.plotter.devicePixelRatioF())
        except Exception:
            return 1.0

    def legend_picture(self, spec, dpr=1.0):
        """The legend as a transparent QImage (logical size LEGEND_W wide) and its logical height, cut to what is drawn."""
        h_all = 300
        img = QImage(int(LEGEND_W * dpr), int(h_all * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(0)
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            rect = legend_draw.draw_legend(p, LEGEND_W, h_all, spec["title"], spec["labels"], result_style.colours,
                                           subtitle=spec.get("subtitle"), desired_h=160, font_pt=9)
        finally:
            p.end()
        h = max(40, min(h_all, rect.y() + rect.height() + 8))
        return img.copy(0, 0, int(LEGEND_W * dpr), int(h * dpr)), h

    def set_legend(self, spec):
        """Shows `spec` as the colour legend, top right of the view (None removes it)."""
        self.legend_spec = spec
        if self.plotter is None:
            return
        if spec is None:
            self._drop_legend()
            return
        try:
            self._put_legend(spec)
        except Exception:                                        # noqa: BLE001 - the picture overlay is not there: one line of text instead
            self._drop_legend()
            self._text_legend(spec)

    def _put_legend(self, spec):
        import vtk
        from vtk.util import numpy_support
        dpr = self.dpr()
        img, h = self.legend_picture(spec, dpr)
        arr = np.ascontiguousarray(qimage_array(img)[::-1])      # VTK images start at the bottom row
        im = vtk.vtkImageData()
        im.SetDimensions(arr.shape[1], arr.shape[0], 1)
        im.GetPointData().SetScalars(numpy_support.numpy_to_vtk(arr.reshape(-1, 4), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        if self.legend is None:
            rep = vtk.vtkLogoRepresentation()
            rep.SetShowBorder(0)
            rep.ProportionalResizeOff()
            rep.GetImageProperty().SetOpacity(1.0)                 # the logo widget draws at 20 % unless told otherwise
            widget = vtk.vtkLogoWidget()
            widget.SetInteractor(self.plotter.iren.interactor)
            widget.SetRepresentation(rep)
            widget.SelectableOff()
            widget.ResizableOff()
            widget.ProcessEventsOff()
            widget.On()
            self.legend = {"rep": rep, "widget": widget}
        rep = self.legend["rep"]
        rep.SetImage(im)
        self.legend["w"], self.legend["h"] = arr.shape[1], arr.shape[0]
        self.legend_note = False
        self._clear_text_legend()
        self.place_legend()

    def place_legend(self):
        """Puts the legend picture in the top right corner of the view at its true pixel size (called again when the window changes size)."""
        if self.plotter is None or self.legend is None:
            return
        W, H = self.plotter.window_size
        if W < 10 or H < 10:
            return
        w, h = self.legend["w"], self.legend["h"]
        fw, fh = min(1.0, w / W), min(1.0, h / H)
        rep = self.legend["rep"]
        rep.SetPosition(1.0 - fw, 1.0 - fh)
        rep.SetPosition2(fw, fh)
        self.plotter.render()

    def _drop_legend(self):
        if self.legend is not None:
            try:
                self.legend["widget"].Off()
            except Exception:
                pass
            self.legend = None
        self._clear_text_legend()

    def _text_legend(self, spec):
        lab = spec["labels"]
        text = f"{spec['title']}\n{lab[0][1]} (top) ... {lab[-1][1]} (bottom)"
        try:
            self.plotter.add_text(text, position="upper_right", font_size=9, color="black", name="legend_text")
            self.legend_note = True
        except Exception:
            pass

    def _clear_text_legend(self):
        if self.legend_note:
            try:
                self.plotter.remove_actor("legend_text")
            except Exception:
                pass
            self.legend_note = False

    # ------------------------------------------------------------------ results
    def clear_result(self):
        if self.plotter is not None and self.result_actor is not None:
            self.plotter.remove_actor(self.result_actor)
        self.result_actor = None
        self.res = None
        if self.plotter is not None and self.mesh_actor is not None:
            self.plotter.remove_actor(self.mesh_actor)
        self.mesh_actor = None
        self.set_legend(None)
        if self.actor is not None:
            self.actor.SetVisibility(True)

    def _rgb(self, values):
        """Node values -> colours of the surface points: lo..hi along the shared colour scheme (flipped for a safety factor); a missing value is grey."""
        R = self.res
        v = np.asarray(values, float)[R["orig"]]
        span = R["hi"] - R["lo"]
        t = (v - R["lo"]) / span if span > 0 else np.zeros_like(v)
        if R["flip"]:
            t = 1.0 - t
        rgb = result_style.ramp(np.nan_to_num(t, nan=0.0)).round().astype(np.uint8)
        bad = np.isnan(v)
        if bad.any():
            rgb[bad] = NO_DATA
        return rgb

    def frame_arrays(self, ramp, values):
        """(surface points, colours) with the load at `ramp` (0..1) of its full value; `values` are the node values for that ramp."""
        R = self.res
        return (R["nodes"] + R["scale"] * ramp * R["u"])[R["orig"]], self._rgb(values)

    def show_result(self, nodes, conn, u, values, scale=0.0, edges=False, lo=0.0, hi=1.0, flip=False, legend=None):
        """The deformed part as a surface coloured by `values` (one per node) between lo and hi; `legend` is the picture in the corner."""
        if self.plotter is None:
            return False
        self.clear_result()
        surf, orig = _result_surface(nodes, conn)
        self.res = {"nodes": np.asarray(nodes, float), "u": np.asarray(u, float), "orig": orig, "scale": float(scale), "lo": float(lo),
                    "hi": float(hi), "flip": bool(flip), "edges": bool(edges), "conn": conn}
        pts, rgb = self.frame_arrays(1.0, values)
        surf.points = pts
        surf.point_data["rgb"] = rgb
        self.result_actor = self.plotter.add_mesh(surf, scalars="rgb", rgb=True, show_edges=edges, reset_camera=False, show_scalar_bar=False)
        try:
            self.res["ds"] = self.result_actor.mapper.dataset
        except Exception:                                        # an older pyvista
            self.res["ds"] = pv.wrap(self.result_actor.GetMapper().GetInput())
        if self.actor is not None:
            self.actor.SetVisibility(False)
        self.set_legend(legend)
        self.plotter.render()
        return True

    def set_ramp(self, ramp, values):
        """Animation: the load at `ramp` of its full value (deformation and colours); the legend keeps the final range."""
        if self.plotter is None or self.res is None:
            return False
        ds = self.res["ds"]
        pts, rgb = self.frame_arrays(ramp, values)
        ds.points[:] = pts
        ds.point_data["rgb"][:] = rgb
        ds.GetPoints().Modified()
        ds.GetPointData().GetArray("rgb").Modified()
        ds.Modified()
        self.plotter.render()
        return True

    def show_mesh(self, nodes, conn):
        """The meshed part before any result: a plain light-grey surface with the mesh edges and no colour bar."""
        if self.plotter is None:
            return False
        self.clear_result()
        g = _grid(nodes, conn)
        self.mesh_actor = self.plotter.add_mesh(_surface(g), color=GREY, show_edges=True, edge_color=(0.35, 0.38, 0.42), reset_camera=False)
        if self.actor is not None:
            self.actor.SetVisibility(False)
        self.plotter.render()
        return True

    # ------------------------------------------------------------------ animation pictures
    def export_session(self, max_px=1280):
        """Draws the pictures of an animation off screen (works when the window is hidden): the part as it is on screen now, from the same
        viewpoint, with the legend and the axes.  None when there is no result on show."""
        if pv is None or self.res is None or self.plotter is None:
            return None
        return ExportSession(self, max_px)

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


class ExportSession:
    """One off-screen plotter that draws the frames of an animation; frame(ramp, values, bg) -> QImage."""

    def __init__(self, view, max_px=1280):
        R = view.res
        W, H = view.plotter.window_size
        W, H = max(int(W), 200), max(int(H), 150)
        k = min(1.0, max_px / max(W, H))
        self.size = (max(2, int(W * k) // 2 * 2), max(2, int(H * k) // 2 * 2))
        self.view = view
        self.spec = view.legend_spec
        surf, orig = _result_surface(R["nodes"], R["conn"])
        self.orig = orig
        self.pl = pv.Plotter(off_screen=True, window_size=list(self.size))
        self.pl.set_background("white")
        surf.points = view.frame_arrays(1.0, np.zeros(len(R["nodes"])))[0]
        surf.point_data["rgb"] = np.zeros((len(orig), 3), np.uint8)
        self.actor = self.pl.add_mesh(surf, scalars="rgb", rgb=True, show_edges=R["edges"], show_scalar_bar=False)
        try:
            self.ds = self.actor.mapper.dataset
        except Exception:
            self.ds = pv.wrap(self.actor.GetMapper().GetInput())
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.pl.enable_anti_aliasing("fxaa")
        except Exception:
            pass
        draw_axes(self.pl)
        try:
            self.pl.camera_position = view.plotter.camera_position
        except Exception:
            self.pl.reset_camera()
        self.pl.render()

    def frame(self, ramp, values, bg=None):
        """bg: None = white; a grey level 0..255 while the exporter draws the same frame on white and on black (transparent formats)."""
        pts, rgb = self.view.frame_arrays(ramp, values)
        self.ds.points[:] = pts
        self.ds.point_data["rgb"][:] = rgb
        self.ds.GetPoints().Modified()
        self.ds.GetPointData().GetArray("rgb").Modified()
        self.ds.Modified()
        g = 1.0 if bg is None else float(bg) / 255.0
        self.pl.set_background([g, g, g])
        self.pl.render()                                           # screenshot() returns the last picture unless the scene is drawn again
        arr = np.ascontiguousarray(np.asarray(self.pl.screenshot(return_img=True))[:, :, :3])
        h, w = arr.shape[:2]
        q = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        if self.spec is not None:
            p = QPainter(q)
            try:
                p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                legend_draw.draw_legend(p, w, h, self.spec["title"], self.spec["labels"], result_style.colours,
                                        subtitle=self.spec.get("subtitle"), desired_h=160, font_pt=9)
            finally:
                p.end()
        return q

    def close(self):
        try:
            self.pl.close()
        except Exception:
            pass
