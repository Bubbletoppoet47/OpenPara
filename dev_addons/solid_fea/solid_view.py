"""solid_view.py - the 3D view of the 3D FEA window: the part with its faces coloured, click-to-pick a face, the result as a coloured surface
(the same colour scheme and legend look as 1D FEA), an X / Y / Z axes triad in the bottom-left corner, and the pictures of an animation.

The result surface is built once; an animation only moves its points and recolours them (set_ramp), so a frame is cheap.
"""
import time

import numpy as np

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QImage, QPainter

import legend_draw
import result_style
import settings
import sim_tags
import view3d
import viewpick

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


GREY = (0.60, 0.60, 0.60)                           # the neutral part colour (the setting "Part colour" of File > Settings > 3D View says what is really used: view3d.part_rgb())
PICK = (0.0, 0.706, 1.0)                            # the selected-face colour (the setting "Selected colour": view3d.select_rgb())
SUPPORT = (0.25, 0.5, 0.95)
LOAD = (0.9, 0.25, 0.25)
BODY_COLOURS = [(0.78, 0.80, 0.84), (0.84, 0.78, 0.62), (0.66, 0.80, 0.72), (0.76, 0.70, 0.84), (0.86, 0.74, 0.76), (0.66, 0.78, 0.86),
                (0.80, 0.82, 0.62), (0.70, 0.74, 0.62)]      # the bodies of an assembly, in soft colours that do not look like a support, a load or a pick
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
        self._focus_mesh_of = None
        self.res = None                            # the result surface on show (see show_result)
        self.legend_spec = None                    # {"title", "labels", "subtitle"} of the colour legend on show
        self.legend = None                         # the legend picture in the corner: {"rep", "widget", "w", "h"}
        self.legend_note = False                   # True when the legend had to fall back to one line of text
        self.axes_on = False
        self.lines = {}                            # name -> actor of a line overlay (see set_lines)
        self.line_data = {}                        # name -> its segments (kept for the tests and when there is no 3D view)
        self.focus = None                          # what the selected node of the outline shows (sim_outline.FOCUS_OF); None: the view shows what it always did
        self.mesh_source = None                    # fn() -> (nodes, cells) of the mesh to draw while the focus is "mesh", or None (set by the window)
        self.focus_mesh_actor = None
        self.tags = []                             # the lettered tags (sim_tags) to draw now
        self.tag_names = []                        # names of the point-label actors of the tags on the model
        self.tag_logo = None                       # the list of the tags in the upper-left corner: {"rep", "widget", "w", "h"}
        self.kind = "general"                      # the geometry selector (view3d.KINDS): what a click or the hover takes
        self.on_select = None                      # fn(item) for a click that took an edge, a point or a body (item = {"kind", "idx", ...}) or nothing (None, for those kinds)
        self.edges = []                            # the edges of the part as polylines (n, 3): see set_topology
        self.verts = np.zeros((0, 3))              # the corners of the part
        self.face_body = np.zeros(0, int)          # the body (part) of every face: 0 for a single part, -1 for a face inside an assembly
        self.diag = 1.0
        self.hover_layer = None
        self._t_move = 0.0
        self.mark_actors = {}                      # name -> actors of the edges and points drawn over the part (see set_marks)
        self.mark_data = {}                        # name -> the items last given to set_marks
        if QtInteractor is None:
            return
        try:
            self.plotter = QtInteractor(parent)
            self.widget = self.plotter
            self.plotter.set_background("white")
            self.plotter.iren.add_observer("LeftButtonPressEvent", self._press)
            self.plotter.iren.add_observer("LeftButtonReleaseEvent", self._release)
            self.plotter.iren.add_observer("MouseMoveEvent", self._move)
            self.hover_layer = view3d.HoverLayer(self.plotter)
        except Exception:
            self.plotter = None
            self.widget = None
            return
        self.axes_on = draw_axes(self.plotter)
        self._resized = _Resized(self.place_all)
        self.plotter.installEventFilter(self._resized)

    # ------------------------------------------------------------------ the part
    def set_geometry(self, P, T, F, keep_camera=False):
        """keep_camera: the part is the same part with other faces (a split was changed): the view stays where it is."""
        keep_camera = keep_camera and self.actor is not None
        self.cell_face = F
        self.rgb = np.tile(view3d.part_rgb(), (len(T), 1))
        self.diag = float(np.linalg.norm(np.ptp(np.asarray(P, float), axis=0))) if len(P) else 1.0
        if self.plotter is None:
            return
        self.clear_hover()
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
        self.actor = self.plotter.add_mesh(self.poly, scalars="rgb", rgb=True, show_edges=False, pickable=True, reset_camera=False, **view3d.SHADING)
        if not keep_camera:
            self.plotter.reset_camera()
        self.apply_focus()
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
        """colours: {face id: (r, g, b)}; every other face has the neutral part colour (File > Settings > 3D View)."""
        self.rgb = np.tile(view3d.part_rgb(), (len(self.cell_face), 1))
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
        """Picks what is under the display point (x, y) as the geometry selector says: a face calls on_pick(face id, point); an edge, a point or a body calls
        on_select({"kind", "idx"}); nothing under a Point / Edge / Body pick calls on_select(None).  What was picked: the face id, the index of the edge, the corner or
        the body, or None."""
        if self.plotter is None or self.actor is None:
            return None
        if self.probe_mode:                                      # a probe reads the result surface on screen, not a face of the part
            import vtk
            pk = vtk.vtkCellPicker()
            pk.SetTolerance(0.0005)
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
        it = self.what_is_under(x, y)
        if it is None:
            if self.kind in ("point", "edge", "body") and self.on_select:
                self.on_select(None)
            return None
        if it["kind"] == "face":
            if self.on_pick:
                self.on_pick(it["idx"], it["point"])
        elif self.on_select:
            self.on_select(it)
        return it["idx"]

    # ------------------------------------------------------------------ the geometry selector: what is under the cursor
    def set_kind(self, kind):
        if kind in view3d.KINDS:
            self.kind = kind
            self.clear_hover(render=True)

    def set_topology(self, edges, verts, face_body):
        """The corners, the edges (polylines) and the body of every face of the part on show: what the Point / Edge / Body picks and the hover look in."""
        self.edges = [np.asarray(e, float).reshape(-1, 3) for e in edges]
        self.verts = np.asarray(verts, float).reshape(-1, 3)
        self.face_body = np.asarray(face_body, int)
        pts, owner, a, b = [], [], [], []
        n = 0
        for k, e in enumerate(self.edges):
            if len(e) < 2:
                continue
            a += list(range(n, n + len(e) - 1))
            b += list(range(n + 1, n + len(e)))
            owner += [k] * (len(e) - 1)
            pts.append(e)
            n += len(e)
        self._ep = np.vstack(pts) if pts else np.zeros((0, 3))
        self._ea, self._eb, self._eo = np.array(a, int), np.array(b, int), np.array(owner, int)
        self.clear_hover()

    def _world_tol(self, px=6.0):
        return max(px * viewpick.world_per_pixel(self.plotter), 2e-3 * self.diag)

    def _visible(self, xyz, sx, sy):
        """True when the point xyz (which shows at the pixel sx, sy) is not behind the part."""
        try:
            hit = viewpick.pick_actor(self.plotter, sx, sy, self.actor)
        except Exception:                                        # noqa: BLE001
            return True
        return hit is None or np.linalg.norm(np.asarray(hit) - xyz) <= self._world_tol()

    def vertex_at(self, x, y, reach):
        """Index of the corner within `reach` pixels of the cursor and not hidden behind the part, or None."""
        if not len(self.verts):
            return None
        scr = viewpick.project_display(self.plotter, self.verts)
        dd = np.hypot(scr[:, 0] - x, scr[:, 1] - y)
        dd[np.isnan(dd)] = np.inf
        for i in np.argsort(dd)[:3]:
            if dd[i] > reach * self.dpr():
                break
            if self._visible(self.verts[i], scr[i][0], scr[i][1]):
                return int(i)
        return None

    def edge_at(self, x, y, reach):
        """Index of the edge within `reach` pixels of the cursor and not hidden behind the part, or None."""
        if not len(self._ep):
            return None
        scr = viewpick.project_display(self.plotter, self._ep)
        A, B = scr[self._ea], scr[self._eb]
        ok = ~(np.isnan(A).any(axis=1) | np.isnan(B).any(axis=1))
        if not ok.any():
            return None
        d = np.full(len(A), np.inf)
        d[ok] = viewpick.seg_distance_px(np.array([x, y], float), A[ok], B[ok])
        tol = reach * self.dpr()
        seen = set()
        for k in np.argsort(d)[:12]:
            if d[k] > tol:
                break
            e = int(self._eo[k])
            if e in seen:
                continue
            seen.add(e)
            P0, P1, a, b = self._ep[self._ea[k]], self._ep[self._eb[k]], A[k], B[k]
            ab = b - a
            t = float(np.clip(np.dot(np.array([x, y]) - a, ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0))
            q = P0 + (P1 - P0) * t
            sx, sy = a + ab * t
            if self._visible(q, sx, sy):
                return e
            if len(seen) >= 5:
                break
        return None

    def what_is_under(self, x, y, kind=None):
        """What a click at the display point (x, y) would take as the selector says (the hover outlines the same thing): {"kind": "point" | "edge" | "face" |
        "body", "idx": corner / edge / face id / body index, "point": where the surface was hit, "face": its face} or None."""
        if self.plotter is None or self.actor is None or not self.actor.GetVisibility():
            return None
        kind = kind or self.kind
        if kind in ("general", "point"):
            v = self.vertex_at(x, y, view3d.pick_px("point") if kind == "point" else view3d.pick_px("general"))
            if v is not None:
                return {"kind": "point", "idx": v, "point": tuple(self.verts[v])}
            if kind == "point":
                return None
        if kind in ("general", "edge"):
            e = self.edge_at(x, y, view3d.pick_px("edge") if kind == "edge" else 8.0)
            if e is not None:
                return {"kind": "edge", "idx": e}
            if kind == "edge":
                return None
        r = viewpick.pick_surface(self.plotter, x, y)
        if r is None or not viewpick.same_actor(self.actor, r[1]):
            return None
        cid = int(r[2])
        if cid < 0 or cid >= len(self.cell_face):
            return None
        fid = int(self.cell_face[cid])
        if kind == "body":
            b = int(self.face_body[fid]) if fid < len(self.face_body) else 0
            if b < 0:
                return None
            return {"kind": "body", "idx": b, "face": fid, "point": tuple(r[0])}
        return {"kind": "face", "idx": fid, "point": tuple(r[0])}

    # ------------------------------------------------------------------ the hover outline
    def _move(self, *_a):
        now = time.monotonic()
        if now - self._t_move < 0.05 or self.plotter is None:
            return
        self._t_move = now
        try:
            x, y = self.plotter.iren.interactor.GetEventPosition()
        except Exception:                                        # noqa: BLE001
            return
        self.on_hover(x, y)

    def clear_hover(self, render=False):
        if self.hover_layer is not None:
            self.hover_layer.clear(render=render)

    def on_hover(self, x, y):
        """The cursor is at the display point (x, y): outline what a click would pick (a face by its border, an edge, a corner, a whole body).  Returns the item."""
        hl = self.hover_layer
        if hl is None:
            return None
        try:
            if (not settings.get("hover")) or self.probe_mode or self.actor is None or not self.actor.GetVisibility():
                if hl.actor is not None:
                    hl.clear(render=True)
                return None
            it = self.what_is_under(x, y)
            key = None if it is None else (it["kind"], it["idx"])
            if key == hl.key and (hl.actor is not None or key is None):
                return it
            hl.clear()
            hl.key = key
            if it is not None:
                k = it["kind"]
                if k == "face":
                    cs = np.where(np.asarray(self.cell_face) == it["idx"])[0]
                    if len(cs):
                        hl.show_outline(self.poly.extract_cells(cs), key=key)
                elif k == "edge":
                    hl.show_lines(self._lines_poly([self.edges[it["idx"]]]), key=key)
                elif k == "point":
                    hl.show_point(it["point"], key=key)
                elif k == "body":
                    cs = np.where(np.isin(np.asarray(self.cell_face), np.where(self.face_body == it["idx"])[0]))[0]
                    if len(cs):
                        hl.show_fill(self.poly.extract_cells(cs), key=key)
            self.plotter.render()
            return it
        except Exception:                                        # noqa: BLE001 - the hover is a nicety: it never breaks the window
            return None

    @staticmethod
    def _lines_poly(polys):
        pts, cells, n = [], [], 0
        for e in polys:
            if len(e) < 2:
                continue
            pts.append(e)
            cells += [len(e)] + list(range(n, n + len(e)))
            n += len(e)
        if not pts:
            return None
        return pv.PolyData(np.vstack(pts), lines=np.array(cells, np.int64))

    # ------------------------------------------------------------------ edges and points drawn over the part (the selected ones, the ones with a condition)
    def set_marks(self, groups):
        """groups = {name: [{"edges": [polyline (n, 3)], "points": [xyz], "colour": (r, g, b), "width": px}]}: the edges and points drawn over the part; a name that is
        not given again is taken away."""
        self.mark_data = {k: list(v) for k, v in groups.items()}
        if self.plotter is None:
            return
        for name in list(self.mark_actors):
            for a in self.mark_actors.pop(name):
                try:
                    self.plotter.remove_actor(a)
                except Exception:                                # noqa: BLE001
                    pass
        for name, items in groups.items():
            acts = []
            for it in items:
                col = it.get("colour") or view3d.hover_rgb()
                ln = self._lines_poly(it.get("edges") or [])
                if ln is not None:
                    a = self.plotter.add_mesh(ln, color=col, line_width=float(it.get("width", 4.0)), lighting=False, pickable=False, reset_camera=False)
                    view3d.HoverLayer._bias(a)
                    acts.append(a)
                pts = [p for p in (it.get("points") or [])]
                if pts:
                    a = self.plotter.add_mesh(pv.PolyData(np.asarray(pts, float).reshape(-1, 3)), color=col, point_size=float(it.get("size", 11.0)),
                                              render_points_as_spheres=True, lighting=False, pickable=False, reset_camera=False)
                    view3d.HoverLayer._bias(a)
                    acts.append(a)
            self.mark_actors[name] = acts
        self.plotter.render()

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
        self.apply_focus()

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
        self.apply_focus()
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
        self.mesh_actor = self.plotter.add_mesh(_surface(g), color=view3d.part_rgb(), show_edges=True, edge_color=(0.35, 0.38, 0.42), reset_camera=False, **view3d.SHADING)
        if self.actor is not None:
            self.actor.SetVisibility(False)
        self.apply_focus()
        return True

    # ------------------------------------------------------------------ what the selected node of the outline shows
    def set_focus(self, focus, tags=()):
        """focus: a word of sim_outline.FOCUS_OF (None: as before the outline).  tags: the lettered tags to draw (sim_tags)."""
        self.focus = focus
        self.tags = list(tags)
        self.apply_focus()

    def apply_focus(self):
        """The part, the mesh, the result and the legend show or hide as the focus says: the bare part for the pages about the part, only the mesh for Mesh, only the result
        for Results; the tags of the conditions go with Supports / Loads."""
        f = self.focus
        if self.plotter is None:
            return
        try:
            self._set_focus_mesh(f == "mesh")
            if self.result_actor is not None:
                self.result_actor.SetVisibility(f in (None, "results"))
            if self.mesh_actor is not None:
                self.mesh_actor.SetVisibility(f is None)
            if self.actor is not None:
                if f is None:
                    show = self.result_actor is None and self.mesh_actor is None
                elif f == "results":
                    show = self.result_actor is None
                elif f == "mesh":
                    show = self.focus_mesh_actor is None
                else:
                    show = True
                self.actor.SetVisibility(show)
            for acts in self.mark_actors.values():
                for a in acts:
                    a.SetVisibility(bool(self.actor is not None and self.actor.GetVisibility()))
            if self.legend is not None:
                try:
                    self.legend["widget"].SetEnabled(f in (None, "results"))
                except Exception:                                        # noqa: BLE001
                    pass
            self._put_tags()
            self.plotter.render()
        except Exception:                                                # noqa: BLE001 - a view that cannot draw must not break the window
            pass

    def _set_focus_mesh(self, on):
        data = self.mesh_source() if (on and callable(self.mesh_source)) else None
        if data is None:
            if self.focus_mesh_actor is not None:
                self.plotter.remove_actor(self.focus_mesh_actor)
                self.focus_mesh_actor = None
                self._focus_mesh_of = None
            return
        if self.focus_mesh_actor is not None and self._focus_mesh_of is not None and self._focus_mesh_of[0] is data[0] and self._focus_mesh_of[1] is data[1]:
            return
        if self.focus_mesh_actor is not None:
            self.plotter.remove_actor(self.focus_mesh_actor)
        nodes, conn = data
        self.focus_mesh_actor = self.plotter.add_mesh(_surface(_grid(nodes, conn)), color=view3d.part_rgb(), show_edges=True, edge_color=(0.35, 0.38, 0.42),
                                                      reset_camera=False, pickable=False, **view3d.SHADING)
        self._focus_mesh_of = data

    def _put_tags(self):
        """The chips on the model (a point label at the condition, with the colour and the letter of its tag) and the list in the upper-left corner."""
        for n in self.tag_names:
            try:
                self.plotter.remove_actor(n)
            except Exception:                                            # noqa: BLE001
                pass
        self.tag_names = []
        for t in self.tags:
            a = t.get("anchor")
            if a is None or len(a) != 3:
                continue
            name = f"tag_{t['letter']}"
            try:
                self.plotter.add_point_labels(np.array([a], float), [t["letter"]], name=name, font_size=14, bold=True, text_color="white", shape="rounded_rect",
                                              shape_color=t["colour"], shape_opacity=1.0, show_points=False, always_visible=True, pickable=False, margin=3,
                                              reset_camera=False, render=False)
                self.tag_names.append(name)
            except Exception:                                            # noqa: BLE001
                break
        self._put_tag_list()

    def _put_tag_list(self):
        if not self.tags:
            if self.tag_logo is not None:
                try:
                    self.tag_logo["widget"].Off()
                except Exception:                                        # noqa: BLE001
                    pass
                self.tag_logo = None
            return
        import vtk
        from vtk.util import numpy_support
        img, h = sim_tags.corner_image(self.tags, self.dpr())
        arr = np.ascontiguousarray(qimage_array(img)[::-1])
        im = vtk.vtkImageData()
        im.SetDimensions(arr.shape[1], arr.shape[0], 1)
        im.GetPointData().SetScalars(numpy_support.numpy_to_vtk(arr.reshape(-1, 4), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        if self.tag_logo is None:
            rep = vtk.vtkLogoRepresentation()
            rep.SetShowBorder(0)
            rep.ProportionalResizeOff()
            rep.GetImageProperty().SetOpacity(1.0)
            widget = vtk.vtkLogoWidget()
            widget.SetInteractor(self.plotter.iren.interactor)
            widget.SetRepresentation(rep)
            widget.SelectableOff()
            widget.ResizableOff()
            widget.ProcessEventsOff()
            widget.On()
            self.tag_logo = {"rep": rep, "widget": widget}
        self.tag_logo["rep"].SetImage(im)
        self.tag_logo["w"], self.tag_logo["h"] = arr.shape[1], arr.shape[0]
        self.place_tag_list()

    def place_tag_list(self):
        if self.plotter is None or self.tag_logo is None:
            return
        W, H = self.plotter.window_size
        if W < 10 or H < 10:
            return
        fw, fh = min(1.0, self.tag_logo["w"] / W), min(1.0, self.tag_logo["h"] / H)
        rep = self.tag_logo["rep"]
        rep.SetPosition(0.0, 1.0 - fh)
        rep.SetPosition2(fw, fh)

    def place_all(self):
        self.place_legend()
        self.place_tag_list()

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
