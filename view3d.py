"""
view3d.py - the look and the selection of the 3D views: the part window, the assembly window and the 3D simulation windows (planning/design/viewport).

    part_rgb() hover_rgb() select_rgb()      the three colours of File > Settings > 3D View, as (r, g, b) floats
    KINDS, pick_px(kind), filter_of(kind)    the geometry selector: General, Point, Edge, Face, Body; the reach of each; what a tool may pick
    SelectorBar                              the five buttons that sit beside "Show"; .kind, .set_kind(), signal changed(kind)
    face_outline(mesh)                       the lines along the edge of a face (holes too), for the hover outline
    HoverLayer(plotter)                      the one thing drawn under the cursor: an outline, a line, a point, or a filled face; .clear()
    Shadow(plotter)                          the soft floor shadow: .update(meshes), .clear(), .set_enabled(on)

Nothing here knows about a window; a window gives it a plotter, meshes and pixels.
"""
import numpy as np

import settings

try:
    import pyvista as pv
except Exception:                                    # pragma: no cover - only without pyvista
    pv = None

# how a part's surface is lit: brighter shadows than before, so a neutral grey reads as grey (a mid-grey face, a lighter side) and not as dark
SHADING = dict(ambient=0.50, diffuse=0.65, specular=0.22, specular_power=22)

KINDS = ("general", "point", "edge", "face", "body")
KIND_NAMES = {"general": "General", "point": "Point", "edge": "Edge", "face": "Face", "body": "Body"}
KIND_TIPS = {
    "general": "General: pick whatever is under the cursor (a corner, an edge or a face).",
    "point": "Point: pick corners only. The reach for a point is wider (File > Settings > Picking & Snapping).",
    "edge": "Edge: pick edges only. The reach for an edge is wider (File > Settings > Picking & Snapping).",
    "face": "Face: pick faces only. A click never lands on a neighbouring edge or corner.",
    "body": "Body: pick a whole part (a whole component in an assembly).",
}


# ------------------------------------------------------------------------------------------------------------ colours and reach
def part_rgb():
    return settings.rgb("part_color")


def hover_rgb():
    return settings.rgb("hover_color")


def select_rgb():
    return settings.rgb("select_color")


def pick_px(kind):
    """How far from the cursor (screen pixels) a point or an edge may be and still be picked, for the chosen kind of the selector."""
    key = {"point": "pick_point_px", "edge": "pick_edge_px"}.get(kind, "pick3d_px")
    return float(settings.get(key))


def filter_of(kind):
    """What a tool (a mate, a reference, a measure) may pick under the chosen kind: {"face", "edge", "vertex"} -> bool.  Body is not a thing a tool
    can use, so it allows all three."""
    if kind in ("point", "edge", "face"):
        return {"face": kind == "face", "edge": kind == "edge", "vertex": kind == "point"}
    return {"face": True, "edge": True, "vertex": True}


# ------------------------------------------------------------------------------------------------------------ the outline of a face
def _surface(grid):
    """The surface of an unstructured grid (what extract_cells gives) as PolyData, without the version warning."""
    try:
        return grid.extract_surface(algorithm="dataset_surface")
    except TypeError:
        return grid.extract_surface()


def face_outline(mesh):
    """The lines along the border of a face's triangles (the borders of its holes too) as a PolyData of lines, or None.  A seam where the
    triangulation of a round face is cut open is not a border: the points are merged first, so only the true outline is left."""
    if pv is None or mesh is None or mesh.n_cells == 0:
        return None
    try:
        surf = mesh if isinstance(mesh, pv.PolyData) else _surface(mesh)
        surf = surf.clean(point_merging=True, tolerance=1e-7)
        edges = surf.extract_feature_edges(boundary_edges=True, feature_edges=False, manifold_edges=False, non_manifold_edges=False)
        return edges if edges.n_cells else None
    except Exception:
        return None


def _lift(mesh, amount_of_diag):
    """The mesh moved a hair along its point normals (so an outline drawn on a face is not hidden by it)."""
    try:
        m = mesh.compute_normals(cell_normals=False, point_normals=True, split_vertices=False, inplace=False)
        diag = float(np.linalg.norm(np.array(m.bounds[1::2]) - np.array(m.bounds[0::2]))) or 1.0
        m.points = m.points + m.point_data["Normals"] * (diag * amount_of_diag)
        return m
    except Exception:
        return mesh


class HoverLayer:
    """What is drawn under the cursor: ONE actor at a time.  show_outline(face mesh) draws the outline of a face; show_lines(lines) an edge;
    show_point(xyz) a dot; show_fill(mesh) a filled face (a body); clear() takes it away.  `matrix` puts it where its component sits."""

    LINE_PX = 3.0

    def __init__(self, plotter):
        self.pl = plotter
        self.actor = None
        self.key = None

    def clear(self, render=False):
        a, self.actor, self.key = self.actor, None, None
        if a is not None and self.pl is not None:
            try:
                self.pl.remove_actor(a)
            except Exception:
                pass
            if render:
                try:
                    self.pl.render()
                except Exception:
                    pass

    def _lines(self, lines, matrix):
        a = self.pl.add_mesh(lines, color=hover_rgb(), line_width=self.LINE_PX, lighting=False, pickable=False, reset_camera=False)
        self._bias(a)
        return self._place(a, matrix)

    @staticmethod
    def _bias(a):
        try:
            mp = a.GetMapper()
            mp.SetResolveCoincidentTopologyToPolygonOffset()
            mp.SetRelativeCoincidentTopologyLineOffsetParameters(-6.0, -6.0)
            mp.SetRelativeCoincidentTopologyPolygonOffsetParameters(-6.0, -6.0)
        except Exception:
            pass

    @staticmethod
    def _place(a, matrix):
        if matrix is not None:
            try:
                a.user_matrix = np.array(matrix)
            except Exception:
                pass
        return a

    def show_outline(self, face_mesh, matrix=None, key=None):
        """The outline of a face; True when there was an outline to draw."""
        self.clear()
        lines = face_outline(_lift(face_mesh, 4e-4) if hasattr(face_mesh, "compute_normals") else face_mesh)
        if lines is None:
            return False
        self.actor, self.key = self._lines(lines, matrix), key
        return True

    def show_lines(self, lines, matrix=None, key=None):
        self.clear()
        if lines is None:
            return False
        self.actor, self.key = self._lines(lines, matrix), key
        return True

    def show_point(self, xyz, matrix=None, key=None):
        self.clear()
        a = self.pl.add_mesh(pv.PolyData(np.array([xyz], float)), color=hover_rgb(), point_size=11, render_points_as_spheres=True, lighting=False,
                             pickable=False, reset_camera=False)
        self._bias(a)
        self.actor, self.key = self._place(a, matrix), key
        return True

    def show_fill(self, mesh, matrix=None, key=None):
        """A filled (translucent) mesh, for a hovered body."""
        self.clear()
        a = self.pl.add_mesh(_lift(mesh, 2e-4) if hasattr(mesh, "compute_normals") else mesh, color=hover_rgb(), opacity=0.35, lighting=False, pickable=False,
                             reset_camera=False)
        self._bias(a)
        self.actor, self.key = self._place(a, matrix), key
        return True


# ------------------------------------------------------------------------------------------------------------ the floor shadow
LIGHT = np.array([0.35, -0.25, -1.0])            # where the light travels: down, a little to the right and away (Z is up)
SHADOW_RES = 256                                 # the picture is this many pixels along its long side
SHADOW_GIVE_UP = 900000                          # more triangles than this in the whole scene: no shadow is drawn (the scene is too big to flatten quickly)
SHADOW_MAX_TRIS = 120000                         # more triangles than this: the smallest are left out (they are covered by their neighbours)


def _blur(a, sigma):
    """A gaussian blur of a 2D array (scipy when there is, else three box passes)."""
    if sigma <= 0.3:
        return a
    try:
        from scipy.ndimage import gaussian_filter
        return gaussian_filter(a, sigma, mode="constant")
    except Exception:
        k = max(1, int(round(sigma * 1.7)))
        out = a.astype(float)
        for _ in range(3):
            for ax in (0, 1):
                c = np.cumsum(np.pad(out, [(k + 1, k) if i == ax else (0, 0) for i in range(2)]), axis=ax)
                out = (np.take(c, range(2 * k + 1, c.shape[ax]), axis=ax) - np.take(c, range(0, c.shape[ax] - 2 * k - 1), axis=ax)) / (2 * k + 1)
        return out


def shadow_image(points, tris, res=SHADOW_RES):
    """The soft shadow of a mesh on the floor under its lowest point, as (RGBA uint8 array [row = y, col = x], (xmin, xmax, ymin, ymax) of the picture,
    floor z).  Rows run along +y, columns along +x.  None when there is nothing to shadow."""
    P = np.asarray(points, float)
    T = np.asarray(tris, int).reshape(-1, 3)
    if len(P) == 0 or len(T) == 0:
        return None
    zmin, zmax = float(P[:, 2].min()), float(P[:, 2].max())
    L = LIGHT / abs(LIGHT[2])
    t = (P[:, 2] - zmin)                                       # height above the floor; the light covers L * t sideways on the way down
    Q = P[:, :2] + L[:2] * t[:, None]                          # where each point's shadow falls on the floor
    ext = float(max(np.ptp(Q[:, 0]), np.ptp(Q[:, 1]), 1e-9))
    pad = 0.30 * ext
    x0, x1 = float(Q[:, 0].min()) - pad, float(Q[:, 0].max()) + pad
    y0, y1 = float(Q[:, 1].min()) - pad, float(Q[:, 1].max()) + pad
    side = max(x1 - x0, y1 - y0)
    w, h = max(8, int(round(res * (x1 - x0) / side))), max(8, int(round(res * (y1 - y0) / side)))
    px = np.column_stack([(Q[:, 0] - x0) / (x1 - x0) * (w - 1), (Q[:, 1] - y0) / (y1 - y0) * (h - 1)])
    if len(T) > SHADOW_MAX_TRIS:                               # keep the largest on the floor
        A = px[T]
        area = np.abs(np.cross(A[:, 1] - A[:, 0], A[:, 2] - A[:, 0]))
        T = T[np.argsort(-area)[:SHADOW_MAX_TRIS]]
    height = max(zmax - zmin, 1e-9)
    low = (t[T].mean(axis=1) < 0.08 * max(height, 0.25 * ext))     # triangles near the floor make the dark contact shadow
    from PIL import Image, ImageDraw
    out = []
    for sel in (np.ones(len(T), bool), low):
        img = Image.new("L", (w, h), 0)
        dr = ImageDraw.Draw(img)
        Ts = T[sel]
        if len(Ts):
            A = px[Ts]
            span = np.maximum(A.max(axis=1) - A.min(axis=1), 0).max(axis=1)
            for tri in A[span > 1.0]:
                dr.polygon([tuple(v) for v in tri], fill=255)
            small = px[np.unique(Ts[span <= 1.0])]
            if len(small):
                xs, ys = np.clip(np.rint(small[:, 0]).astype(int), 0, w - 1), np.clip(np.rint(small[:, 1]).astype(int), 0, h - 1)
                m = np.asarray(img)
                m = m.copy()
                m[ys, xs] = 255
                img = Image.fromarray(m)
        out.append(np.asarray(img, float) / 255.0)
    wide = _blur(out[0], 0.035 * res)
    near = _blur(out[1], 0.012 * res)
    alpha = np.clip(0.38 * wide / max(wide.max(), 1e-9) * (wide > 0) + 0.34 * near, 0, 0.62)
    # the soft part must not stop at the edge of the picture
    alpha[0, :] = alpha[-1, :] = alpha[:, 0] = alpha[:, -1] = 0
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., :3] = (20, 24, 34)
    rgba[..., 3] = np.rint(alpha * 255).astype(np.uint8)
    return rgba, (x0, x1, y0, y1), zmin


class Shadow:
    """The soft shadow on the floor under a model.  update(meshes) draws it (again) for [(PolyData of triangles, 4x4 matrix or None)]; it is hidden
    when the view looks from below the floor, and when File > Settings > 3D View has it off."""

    def __init__(self, plotter):
        self.pl = plotter
        self.actor = None
        self.floor = None
        self.obs = None
        self.last = None

    def enabled(self):
        return bool(settings.get("shadow"))

    def clear(self):
        a, self.actor = self.actor, None
        if a is not None and self.pl is not None:
            try:
                self.pl.remove_actor(a, render=False)
            except Exception:
                pass

    def set_enabled(self, on):
        """The setting changed: draw it again from the last meshes, or take it away."""
        if on and self.last is not None:
            self.update(self.last)
        elif not on:
            self.clear()
            try:
                self.pl.render()
            except Exception:
                pass

    def update(self, meshes):
        self.last = meshes
        self.clear()
        if pv is None or self.pl is None or not self.enabled():
            return
        pts, tris, off = [], [], 0
        for m, mat in meshes or []:
            try:
                if m is None or m.n_cells == 0:
                    continue
                surf = m if isinstance(m, pv.PolyData) else _surface(m)
                if not surf.is_all_triangles:
                    surf = surf.triangulate()
                p = np.asarray(surf.points, float)
                if mat is not None:
                    M = np.asarray(mat, float)
                    p = p @ M[:3, :3].T + M[:3, 3]
                f = np.asarray(surf.faces).reshape(-1, 4)[:, 1:]
                pts.append(p)
                tris.append(f + off)
                off += len(p)
            except Exception:
                continue
        if not pts or sum(len(t) for t in tris) > SHADOW_GIVE_UP:       # nothing to shadow, or too big for the picture to be worth the wait
            return
        try:
            res = shadow_image(np.vstack(pts), np.vstack(tris))
        except Exception:
            return
        if res is None:
            return
        rgba, (x0, x1, y0, y1), zf = res
        quad = pv.PolyData(np.array([[x0, y0, zf], [x1, y0, zf], [x1, y1, zf], [x0, y1, zf]], float), faces=np.array([4, 0, 1, 2, 3]))
        quad.active_texture_coordinates = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
        tex = pv.Texture(rgba)
        try:
            self.actor = self.pl.add_mesh(quad, texture=tex, lighting=False, pickable=False, reset_camera=False, show_scalar_bar=False)
            self.actor.SetUseBounds(False)              # the floor is not part of the model: it does not change where "fit" looks
            mp = self.actor.GetMapper()
            mp.SetResolveCoincidentTopologyToPolygonOffset()
            mp.SetRelativeCoincidentTopologyPolygonOffsetParameters(4.0, 4.0)
        except Exception:
            self.actor = None
            return
        self.floor = zf
        self._watch()
        self.refresh_visibility()

    def _watch(self):
        if self.obs is not None:
            return
        try:
            self.obs = self.pl.camera.AddObserver("ModifiedEvent", lambda *_a: self.refresh_visibility())
        except Exception:
            self.obs = None

    def refresh_visibility(self):
        """Seen from below the floor the picture would cover the model, so it is hidden there."""
        if self.actor is None or self.floor is None:
            return
        try:
            self.actor.SetVisibility(bool(self.pl.camera.position[2] > self.floor))
        except Exception:
            pass


# ------------------------------------------------------------------------------------------------------------ the selector bar
BAR_CSS = ("QToolButton{background:rgba(255,255,255,170); border:1px solid #8793ad; border-radius:9px; padding:2px 5px;}"
           "QToolButton:hover{background:rgba(255,255,255,240);}"
           "QToolButton:checked{background:#ffffff; border:2px solid #2f6fed;}"
           "QToolButton:disabled{background:rgba(255,255,255,90); border-color:#cbd3e0;}")


class SelectorBar:
    """General / Point / Edge / Face / Body: five exclusive buttons.  Make it with SelectorBar.make(parent, on_change); .widget goes in a layout."""

    @classmethod
    def make(cls, parent=None, on_change=None):
        return cls(parent, on_change)

    def __init__(self, parent=None, on_change=None):
        from PyQt6.QtCore import QSize
        from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton, QWidget
        import icon_kit
        self.on_change = on_change
        self.kind = "general"
        self.allowed = set(KINDS)
        self.widget = QWidget(parent)
        self.widget.setObjectName("selectbar")
        self.widget.setStyleSheet("#selectbar{background:transparent;}" + BAR_CSS)
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.group = QButtonGroup(self.widget)
        self.group.setExclusive(True)
        self.buttons = {}
        for k in KINDS:
            b = QToolButton()
            b.setCheckable(True)
            b.setAutoRaise(False)
            ic = icon_kit.qicon("sel_" + k, 24)
            if ic is not None:
                b.setIcon(ic)
            b.setIconSize(QSize(20, 20))
            b.setFixedSize(30, 24)
            b.setToolTip(KIND_TIPS[k])
            b.setAccessibleName(KIND_NAMES[k])
            b.setChecked(k == "general")
            b.clicked.connect(lambda _c=False, kk=k: self.set_kind(kk))
            self.group.addButton(b)
            self.buttons[k] = b
            row.addWidget(b)

    def set_kind(self, kind, quiet=False):
        """Choose a kind (quiet: no change signal, for a tool that sets it)."""
        if kind not in KINDS or kind not in self.allowed:
            return
        changed = kind != self.kind
        self.kind = kind
        for k, b in self.buttons.items():
            b.setChecked(k == kind)
        if changed and not quiet and self.on_change is not None:
            self.on_change(kind)

    def set_enabled(self, on):
        self.widget.setEnabled(bool(on))

    def allow(self, kinds, why=""):
        """Only these kinds can be chosen (the others are greyed, their tip says `why`); the chosen kind falls back to General when it is not allowed."""
        self.allowed = set(kinds)
        for k, b in self.buttons.items():
            ok = k in kinds
            b.setEnabled(ok)
            b.setToolTip(KIND_TIPS[k] if ok else (why or "Not used here."))
        if self.kind not in kinds:
            self.set_kind("general" if "general" in kinds else next(iter(kinds)))
