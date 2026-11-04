"""
nav.py - mouse navigation like SolidWorks and a view cube like Blender / Dune3D.

  Middle button drag   rotate          Ctrl + middle drag   pan          Shift + middle drag   zoom
  Mouse wheel          zoom toward the cursor (direction can be flipped)
  Left button          never moves the view (it selects / sketches)
  Right click          a context menu (the app supplies it)
  View cube (top right of the view)  click a face / edge / corner to snap to that view; the arrows turn the view by 90 degrees;
                       the small house button goes to the isometric view.

The cube is drawn by VTK on its own layer in the same window (so it always shows, also over the 3D view); clicks on it are handled
here from the Qt mouse events, with the same projection maths as the drawing.
"""
import math

import numpy as np
from PyQt6.QtCore import QEvent, QObject, QSettings, Qt

try:
    import pyvista as pv
    from vtkmodules.vtkInteractionStyle import vtkInteractorStyleUser
    from vtkmodules.vtkRenderingCore import (vtkActor, vtkActor2D, vtkCamera, vtkPolyDataMapper, vtkPolyDataMapper2D, vtkRenderer)
    from vtkmodules.vtkRenderingCore import vtkBillboardTextActor3D
except Exception:                                        # no VTK: nothing here is used
    pv = None

WHEEL_STEP = 1.18

FACES = [("Right", (1, 0, 0)), ("Left", (-1, 0, 0)), ("Back", (0, 1, 0)), ("Front", (0, -1, 0)), ("Top", (0, 0, 1)), ("Bottom", (0, 0, -1))]
BASE = {"Right": (0.80, 0.84, 0.90), "Left": (0.80, 0.84, 0.90), "Back": (0.78, 0.82, 0.88), "Front": (0.86, 0.89, 0.94),
        "Top": (0.93, 0.95, 0.98), "Bottom": (0.70, 0.74, 0.80)}
HOVER = (1.0, 0.72, 0.25)


def face_quad(n):
    n = np.array(n, float)
    h = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(h, n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return [n - u - v, n + u - v, n + u + v, n - u + v]


def view_dirs(cam):
    """(right, up, toward the viewer) unit vectors of a camera."""
    fwd = np.array(cam.GetFocalPoint()) - np.array(cam.GetPosition())
    fwd /= max(np.linalg.norm(fwd), 1e-12)
    up = np.array(cam.GetViewUp())
    right = np.cross(fwd, up)
    right /= max(np.linalg.norm(right), 1e-12)
    up = np.cross(right, fwd)
    return right, up, -fwd


class ViewCube:
    SIZE, MARGIN = 150, 10

    def __init__(self, app):
        self.app = app
        self.pl = app.plotter
        self.hover = None                    # ("face", name) | ("edge", i) | ("corner", i) | ("arrow", name) | ("home",)
        self.ren = vtkRenderer()
        self.ren.SetLayer(2)
        self.ren.InteractiveOff()
        self.cam = vtkCamera()
        self.cam.ParallelProjectionOn()
        self.cam.SetParallelScale(2.1)
        self.ren.SetActiveCamera(self.cam)
        rw = self.pl.render_window
        rw.SetNumberOfLayers(3)
        rw.AddRenderer(self.ren)
        self.box = (0, 0, 1, 1)
        self.layout()
        self.corners = [np.array([sx, sy, sz], float) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        self.edges = []                      # (corner index a, corner index b, adjacent face names)
        for i, a in enumerate(self.corners):
            for j, b in enumerate(self.corners):
                if j > i and int(np.sum(np.abs(a - b) > 0)) == 1:
                    fs = [nm for nm, n in FACES if np.dot(n, a) > 0.5 and np.dot(n, b) > 0.5]
                    self.edges.append((i, j, fs))
        self.cam.SetParallelScale(2.1)
        self.cam.SetClippingRange(1, 30)
        self.build()
        self.cam_obs = self.pl.camera.AddObserver("ModifiedEvent", lambda *_: self.sync())
        self.sync()

    # ------------------------------------------------------------------ geometry
    def layout(self):
        W, H = self.app.ed.size_fn()
        r = self.pl.devicePixelRatioF()
        s, m = int(self.SIZE * r), int(self.MARGIN * r)
        self.box = (W - m - s, H - m - s, W - m, H - m)
        self.ren.SetViewport(self.box[0] / W, self.box[1] / H, self.box[2] / W, self.box[3] / H)
        if getattr(self, "button_actors", None) is not None and hasattr(self, "face_actors"):
            self.build_buttons()

    @property
    def side(self):
        return self.box[2] - self.box[0]

    def project(self, v, right, up):
        """cube point -> device pixel (bottom-left origin)."""
        k = self.side / (2 * self.cam.GetParallelScale())
        cx, cy = (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2
        return np.array([cx + k * float(np.dot(v, right)), cy + k * float(np.dot(v, up))])

    def inside(self, px, py):
        b = self.box
        return b[0] <= px <= b[2] and b[1] <= py <= b[3]

    # ------------------------------------------------------------------ hit test
    def arrows(self):
        """name -> (centre pixel, size) of the little buttons around the cube."""
        b, s = self.box, self.side
        r = self.pl.devicePixelRatioF()
        a = 9 * r
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return {"up": (np.array([cx, b[3] - a - 2 * r]), a), "down": (np.array([cx, b[1] + a + 2 * r]), a),
                "left": (np.array([b[0] + a + 2 * r, cy]), a), "right": (np.array([b[2] - a - 2 * r, cy]), a),
                "home": (np.array([b[0] + a + 2 * r, b[3] - a - 2 * r]), a)}

    def hit(self, px, py):
        if not self.inside(px, py):
            return None
        P = np.array([px, py])
        for nm, (c, a) in self.arrows().items():
            if abs(P[0] - c[0]) <= a and abs(P[1] - c[1]) <= a:
                return ("home",) if nm == "home" else ("arrow", nm)
        right, up, toward = view_dirs(self.pl.camera)
        vis = {nm for nm, n in FACES if np.dot(n, toward) > 1e-6}
        r = self.pl.devicePixelRatioF()
        best = None
        for i, c in enumerate(self.corners):
            if any(np.dot(n, c) > 0.5 and nm in vis for nm, n in FACES):
                d = np.linalg.norm(self.project(c, right, up) - P)
                if d < 11 * r and (best is None or d < best[0]):
                    best = (d, ("corner", i))
        if best:
            return best[1]
        for k, (i, j, fs) in enumerate(self.edges):
            if not any(f in vis for f in fs):
                continue
            a, b = self.project(self.corners[i], right, up), self.project(self.corners[j], right, up)
            ab = b - a
            t = np.clip(np.dot(P - a, ab) / max(np.dot(ab, ab), 1e-12), 0, 1)
            d = np.linalg.norm(a + ab * t - P)
            if d < 7 * r and (best is None or d < best[0]):
                best = (d, ("edge", k))
        if best:
            return best[1]
        for nm, n in FACES:
            if nm not in vis:
                continue
            q = np.array([self.project(v, right, up) for v in face_quad(n)])
            if self.in_poly(P, q):
                return ("face", nm)
        return None

    @staticmethod
    def in_poly(p, q):
        x, y = p
        c = False
        for k in range(len(q)):
            x1, y1, x2, y2 = q[k][0], q[k][1], q[(k + 1) % len(q)][0], q[(k + 1) % len(q)][1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
        return c

    # ------------------------------------------------------------------ what a hit does
    def direction_of(self, h):
        """View direction (from the part toward the viewer) for a face / edge / corner hit, and its up vector."""
        if h[0] == "face":
            d = np.array(dict(FACES)[h[1]], float)
        elif h[0] == "edge":
            d = sum(np.array(dict(FACES)[f], float) for f in self.edges[h[1]][2])
        else:
            c = self.corners[h[1]]
            d = c.copy()
        d = d / np.linalg.norm(d)
        up = np.array([0.0, 0.0, 1.0])
        if abs(d[2]) > 0.99:
            up = np.array([0.0, 1.0, 0.0]) * (1 if d[2] > 0 else -1)
        return d, up

    def click(self, h):
        cam = self.pl.camera
        if h[0] in ("face", "edge", "corner"):
            d, up = self.direction_of(h)
            self.set_view(d, up)
        elif h[0] == "home":
            self.set_view(np.array([1.0, -1.0, 0.8]) / np.linalg.norm([1.0, -1.0, 0.8]), np.array([0.0, 0.0, 1.0]))
        elif h[0] == "arrow":
            right, up, toward = view_dirs(cam)
            ang = {"left": 90, "right": -90}.get(h[1], 0)
            if h[1] in ("left", "right"):
                cam.Azimuth(ang)
            else:
                cam.Elevation(90 if h[1] == "up" else -90)
            cam.OrthogonalizeViewUp()
            self.finish()

    def set_view(self, d, up):
        cam = self.pl.camera
        f = np.array(cam.GetFocalPoint())
        dist = max(float(np.linalg.norm(np.array(cam.GetPosition()) - f)), 1e-6)
        cam.SetPosition(*(f + d * dist))
        cam.SetViewUp(*up)
        cam.OrthogonalizeViewUp()
        self.finish()

    def finish(self):
        self.pl.renderer.ResetCameraClippingRange()
        self.sync()
        self.pl.render()

    # ------------------------------------------------------------------ drawing
    # The cube is an object in space that is built ONCE (build): six faces, twelve edges, the face labels, a marker for a hovered corner.  Turning the
    # model only turns the cube's camera to the same angle (sync), and hovering only recolours the piece that was entered or left (_style).  The little
    # buttons are screen-fixed; they are rebuilt only when the window changes size (build_buttons).
    DEFAULT_EDGE = (0.25, 0.28, 0.35)
    BUTTON = (0.45, 0.50, 0.60)

    def sync(self):
        """Turn the cube like the model (called whenever the main camera changes): only the camera of the cube moves."""
        try:
            right, up, toward = view_dirs(self.pl.camera)
            c = self.cam
            c.SetPosition(*(toward * 12))
            c.SetFocalPoint(0, 0, 0)
            c.SetViewUp(*up)
        except Exception:
            pass

    def _prop(self, actor, color, width=1.0, points=False):
        p = actor.GetProperty()
        p.SetColor(*color)
        if points:
            p.SetPointSize(width)
            p.SetRenderPointsAsSpheres(True)
        else:
            p.SetLineWidth(width)

    def _actor(self, mesh, color, width=1.0, points=False, lit=False):
        m = vtkPolyDataMapper()
        m.SetInputData(mesh)
        a = vtkActor()
        a.SetMapper(m)
        p = a.GetProperty()
        p.SetLighting(lit)
        if lit:
            p.SetAmbient(0.82)                         # the cube lies in the light of the viewer: faces turned to you are a little brighter
            p.SetDiffuse(0.18)
            p.SetSpecular(0.0)
        self._prop(a, color, width, points)
        self.ren.AddActor(a)
        return a

    def build(self):
        """Create the cube once."""
        self.face_actors, self.edge_actors, self.label_actors = {}, [], []
        for nm, n in FACES:
            mesh = pv.PolyData(np.array(face_quad(n)), faces=np.array([4, 0, 1, 2, 3]))
            self.face_actors[nm] = self._actor(mesh, BASE[nm], lit=True)
        for (i, j, fs) in self.edges:
            seg = pv.lines_from_points(np.array([self.corners[i] * 1.002, self.corners[j] * 1.002]))
            self.edge_actors.append(self._actor(seg, self.DEFAULT_EDGE, 1.5))
        for nm, n in FACES:                                 # the labels lie flat on their faces; the ones on the far side are hidden by the depth test
            self.label_actors.append(self._actor(self.face_label(nm, np.array(n, float)), (0.12, 0.14, 0.2), 2.0))
        self.corner_actor = self._actor(pv.PolyData(np.array([self.corners[0] * 1.01])), HOVER, 14.0, points=True)
        self.corner_actor.SetVisibility(False)
        self.button_actors = {}
        self.build_buttons()

    def _style(self, h, on):
        """Draw the piece `h` as hovered (on) or as normal."""
        if not h:
            return
        if h[0] == "face":
            a = self.face_actors[h[1]]
            self._prop(a, HOVER if on else BASE[h[1]])
        elif h[0] == "edge":
            self._prop(self.edge_actors[h[1]], HOVER if on else self.DEFAULT_EDGE, 5.0 if on else 1.5)
        elif h[0] == "corner":
            if on:
                self.corner_actor.GetMapper().GetInput().GetPoints().SetPoint(0, *(self.corners[h[1]] * 1.01))
                self.corner_actor.GetMapper().GetInput().Modified()
            self.corner_actor.SetVisibility(bool(on))
        elif h[0] in ("arrow", "home"):
            nm = "home" if h[0] == "home" else h[1]
            if nm in self.button_actors:
                self.button_actors[nm].GetProperty().SetColor(*(HOVER if on else self.BUTTON))

    def build_buttons(self):
        """The five little buttons around the cube (screen-fixed 2D shapes)."""
        for act in getattr(self, "button_actors", {}).values():
            self.ren.RemoveViewProp(act)
        self.button_actors = {}
        for nm, (c, a) in self.arrows().items():
            lc = c - np.array([self.box[0], self.box[1]])
            s = a * 0.8
            if nm == "up":
                pts = [(lc[0] - s, lc[1] - s * 0.6), (lc[0] + s, lc[1] - s * 0.6), (lc[0], lc[1] + s * 0.7)]
            elif nm == "down":
                pts = [(lc[0] - s, lc[1] + s * 0.6), (lc[0] + s, lc[1] + s * 0.6), (lc[0], lc[1] - s * 0.7)]
            elif nm == "left":
                pts = [(lc[0] + s * 0.6, lc[1] - s), (lc[0] + s * 0.6, lc[1] + s), (lc[0] - s * 0.7, lc[1])]
            elif nm == "right":
                pts = [(lc[0] - s * 0.6, lc[1] - s), (lc[0] - s * 0.6, lc[1] + s), (lc[0] + s * 0.7, lc[1])]
            else:                                                        # a little house
                pts = [(lc[0] - s, lc[1] - s * 0.8), (lc[0] + s, lc[1] - s * 0.8), (lc[0] + s, lc[1] + s * 0.1),
                       (lc[0], lc[1] + s * 0.9), (lc[0] - s, lc[1] + s * 0.1)]
            poly = pv.PolyData(np.array([(x, y, 0.0) for x, y in pts]))
            n = len(pts)
            poly.faces = np.array([n] + list(range(n)))
            m = vtkPolyDataMapper2D()
            m.SetInputData(poly)
            act = vtkActor2D()
            act.SetMapper(m)
            act.GetProperty().SetColor(*self.BUTTON)
            self.ren.AddViewProp(act)
            self.button_actors[nm] = act
        self._style(self.hover, True)

    def face_label(self, name, n):
        """Letters as flat vector lines lying just above a face (depth-tested, so they can never poke through the cube)."""
        from vtkmodules.vtkRenderingFreeType import vtkVectorText
        vt = vtkVectorText()
        vt.SetText(name)
        vt.Update()
        pts = pv.wrap(vt.GetOutput())
        if pts.n_points == 0:
            return pv.PolyData()
        lo, hi = np.array(pts.bounds[0::2]), np.array(pts.bounds[1::2])
        mid = (lo + hi) / 2
        scale = min(1.30 / max(hi[0] - lo[0], 1e-6), 0.50 / max(hi[1] - lo[1], 1e-6))
        up = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.5 else np.array([0.0, 1.0, 0.0])
        right = np.cross(up, n)
        xy = (np.array(pts.points) - mid) * scale
        world = n * 1.012 + xy[:, 0:1] * right + xy[:, 1:2] * up
        return pv.PolyData(world, faces=pts.faces)

    def set_hover(self, h):
        if h != self.hover:
            self._style(self.hover, False)
            self.hover = h
            self._style(h, True)
            self.pl.render()


class NavHook(QObject):
    """Mouse navigation (see the module text).  Installed last on the view so that it sees the events first."""

    def __init__(self, plotter, app):
        super().__init__(plotter)
        self.pl, self.app = plotter, app
        self.mode = None                     # "rotate" | "pan" | "zoom" while the middle button is down
        self.last = None
        self.moved = False
        self.press_pos = None
        s = QSettings("GenParametricDesigner", "Modeller")
        try:
            self.wheel_sign = -1 if s.value("flip_zoom", "0") in ("1", 1, True, "true") else 1
        except Exception:
            self.wheel_sign = 1
        # the wheel as asked: rolling toward you zooms in  ->  sign for angleDelta().y() < 0 is zoom in
        self.lock = QSettings("GenParametricDesigner", "Modeller").value("lock_view", "0") in ("1", 1, True, "true")   # Show > Lock view
        self.cube = None
        try:
            from PyQt6.QtWidgets import QWidget as _W
            iren = getattr(plotter, "iren", None)
            inter = getattr(iren, "interactor", None) or iren
            inter.SetInteractorStyle(vtkInteractorStyleUser())
            for w in [plotter] + list(plotter.findChildren(_W)):
                w.installEventFilter(self)
        except Exception:
            pass
        try:
            self.cube = ViewCube(app)
        except Exception:
            self.cube = None

    def set_lock(self, on):
        """Lock view: a plain middle-button drag pans (instead of rotating), so sketching does not need Ctrl held down."""
        self.lock = bool(on)
        QSettings("GenParametricDesigner", "Modeller").setValue("lock_view", "1" if on else "0")

    def flip_zoom(self, flipped):
        self.wheel_sign = -1 if flipped else 1
        QSettings("GenParametricDesigner", "Modeller").setValue("flip_zoom", "1" if flipped else "0")

    # ------------------------------------------------------------------ camera moves
    def xy(self, obj, ev):
        r = obj.devicePixelRatioF()
        p = ev.position()
        return p.x() * r, (obj.height() - p.y() - 1) * r

    def world_per_pixel(self):
        cam = self.pl.camera
        H = max(1.0, self.app.ed.size_fn()[1])
        if cam.GetParallelProjection():
            return 2.0 * cam.GetParallelScale() / H
        return 2.0 * cam.GetDistance() * math.tan(math.radians(cam.GetViewAngle()) / 2.0) / H

    def rotate(self, dx, dy):
        cam = self.pl.camera
        cam.Azimuth(-dx * 0.35)
        cam.Elevation(-dy * 0.35)
        cam.OrthogonalizeViewUp()
        self.refresh()

    def pan(self, dx, dy):
        cam = self.pl.camera
        right, up, _ = view_dirs(cam)
        k = self.world_per_pixel()
        shift = -right * dx * k - up * dy * k
        cam.SetPosition(*(np.array(cam.GetPosition()) + shift))
        cam.SetFocalPoint(*(np.array(cam.GetFocalPoint()) + shift))
        self.refresh()

    def point_under(self, px, py):
        """World point under the pixel on the plane through the focal point (facing the camera)."""
        cam = self.pl.camera
        p0, d = self.app.ed.ray(px, py)
        f = np.array(cam.GetFocalPoint())
        _, _, toward = view_dirs(cam)
        den = float(toward @ d)
        if abs(den) < 1e-12:
            return f
        return p0 + d * (float((f - p0) @ toward) / den)

    def zoom(self, factor, px=None, py=None):
        cam = self.pl.camera
        factor = min(max(factor, 0.2), 5.0)
        before = self.point_under(px, py) if px is not None else None
        if cam.GetParallelProjection():
            cam.SetParallelScale(max(1e-4, cam.GetParallelScale() / factor))
        else:
            cam.Dolly(factor)
        if before is not None:
            shift = before - self.point_under(px, py)
            cam.SetPosition(*(np.array(cam.GetPosition()) + shift))
            cam.SetFocalPoint(*(np.array(cam.GetFocalPoint()) + shift))
        self.refresh()

    def refresh(self):
        self.pl.renderer.ResetCameraClippingRange()
        self.pl.render()

    # ------------------------------------------------------------------ events
    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if t == QEvent.Type.Resize and self.cube is not None:
                self.cube.layout()
                self.cube.sync()
                return False
            if t == QEvent.Type.Wheel:
                px, py = self.xy(obj, ev)
                steps = ev.angleDelta().y() / 120.0
                if steps:
                    self.zoom(WHEEL_STEP ** (-steps * self.wheel_sign), px, py)
                return True
            if t == QEvent.Type.MouseButtonPress:
                px, py = self.xy(obj, ev)
                if ev.button() == Qt.MouseButton.LeftButton and self.cube is not None:
                    h = self.cube.hit(px, py)
                    if h is not None:
                        self.cube.click(h)
                        return True
                if ev.button() == Qt.MouseButton.MiddleButton:
                    mods = ev.modifiers()
                    self.mode = ("zoom" if mods & Qt.KeyboardModifier.ShiftModifier else
                                 "pan" if (mods & Qt.KeyboardModifier.ControlModifier) or self.lock else "rotate")
                    self.last = (px, py)
                    return True
                if ev.button() == Qt.MouseButton.RightButton:
                    self.press_pos, self.moved = (px, py), False
                    return getattr(self.app, "drag_hook", None) is None      # a window with a drag hook (the assembly) wants the right button too
                return False
            if t == QEvent.Type.MouseMove:
                px, py = self.xy(obj, ev)
                if self.mode:
                    dx, dy = px - self.last[0], py - self.last[1]
                    self.last = (px, py)
                    if self.mode == "rotate":
                        self.rotate(dx, dy)
                    elif self.mode == "pan":
                        self.pan(dx, dy)
                    else:
                        self.zoom(math.exp(dy * 0.006))
                    return True
                if self.press_pos is not None and math.hypot(px - self.press_pos[0], py - self.press_pos[1]) > 4:
                    self.moved = True
                if self.cube is not None and not (ev.buttons() & Qt.MouseButton.LeftButton):
                    self.cube.set_hover(self.cube.hit(px, py))
                return False
            if t == QEvent.Type.MouseButtonRelease:
                if ev.button() == Qt.MouseButton.MiddleButton and self.mode:
                    self.mode = None
                    return True
                if ev.button() == Qt.MouseButton.RightButton and self.press_pos is not None:
                    px, py = self.xy(obj, ev)
                    pos, self.press_pos = self.press_pos, None
                    if not self.moved and hasattr(self.app, "context_menu"):
                        self.app.context_menu(px, py, ev.globalPosition().toPoint())
                    return getattr(self.app, "drag_hook", None) is None
        except Exception:
            import traceback
            self.mode = None
            try:
                self.app.say("Navigation failed: " + traceback.format_exc(limit=2))
            except Exception:
                pass
        return False


def lock_checkbox(win):
    """The 'Lock view' tick box of the Show menu of a window that has a NavHook in win.nav (made after the view)."""
    from PyQt6.QtWidgets import QCheckBox
    cbx = QCheckBox("Lock view (middle drag pans)")
    cbx.setToolTip("Tick while sketching: a plain middle-button drag moves the view sideways instead of rotating it (no Ctrl needed)")
    cbx.setStyleSheet("QCheckBox{padding:4px 14px 4px 10px;} QCheckBox:hover{background:#dbe8fa;}")
    cbx.toggled.connect(lambda on: win.nav.set_lock(on) if getattr(win, "nav", None) is not None else None)
    win.lock_cb = cbx
    return cbx


def sync_lock_checkbox(win):
    cb = getattr(win, "lock_cb", None)
    if cb is not None and getattr(win, "nav", None) is not None:
        cb.blockSignals(True)
        cb.setChecked(win.nav.lock)
        cb.blockSignals(False)
