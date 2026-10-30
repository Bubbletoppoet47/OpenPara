"""Small helpers for clicking in a pyvista / VTK viewport (used by the measure tool and the slice window).

ClickHook   calls on_click(x, y) for a left-button click that did not move (a drag still rotates the view); uses Qt mouse events
pick_surface(plotter, x, y)  -> (world point, actor, cell id) of the surface under the pixel, or None
world_per_pixel(plotter)     -> how many model units one screen pixel covers at the middle of the view
"""
import math
import time

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QWidget

try:
    from vtkmodules.vtkRenderingCore import vtkCellPicker
except Exception:                                    # pragma: no cover - only without VTK
    vtkCellPicker = None


class ClickHook(QObject):
    """Calls on_click(x, y) (VTK display pixels, origin bottom-left) for a left click that did not move.  Uses Qt's own mouse events
    on the viewport widget, so it does not depend on how VTK forwards events; a drag still rotates the view."""

    def __init__(self, plotter, on_click, slop=4, on_move=None):
        super().__init__(plotter)
        self.plotter, self.on_click, self.slop = plotter, on_click, slop
        self.on_move, self._t_move = on_move, 0.0
        self.down = None
        self.enabled = True
        self.ok = True
        self._last = None
        try:
            for w in [plotter] + list(plotter.findChildren(QWidget)):
                w.installEventFilter(self)
        except Exception:
            self.ok = False

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                p = ev.position()
                self.down = (p.x(), p.y())
            elif t == QEvent.Type.MouseMove and self.on_move is not None and self.enabled and not ev.buttons():
                now = time.monotonic()
                if now - self._t_move >= 0.06:               # at most ~16 picks a second
                    self._t_move = now
                    p = ev.position()
                    ratio = obj.devicePixelRatioF()
                    self.on_move(int(round(p.x() * ratio)), int(round((obj.height() - p.y() - 1) * ratio)))
            elif t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton and self.down is not None:
                p = ev.position()
                x0, y0 = self.down
                self.down = None
                stamp = (ev.timestamp(), round(p.x()), round(p.y()))
                if stamp == self._last:                          # the same event seen through the parent widget as well
                    return False
                self._last = stamp
                if self.enabled and abs(p.x() - x0) <= self.slop and abs(p.y() - y0) <= self.slop:
                    ratio = obj.devicePixelRatioF()
                    self.on_click(int(round(p.x() * ratio)), int(round((obj.height() - p.y() - 1) * ratio)))
        except Exception:
            pass
        return False


def pick_surface(plotter, x, y, tolerance=0.0005):
    if vtkCellPicker is None:
        return None
    picker = vtkCellPicker()
    picker.SetTolerance(tolerance)
    picker.PickFromListOff()
    ok = picker.Pick(x, y, 0, plotter.renderer)
    if not ok or picker.GetCellId() < 0:
        picker.SetTolerance(0.004)                           # a second try with a wider reach
        ok = picker.Pick(x, y, 0, plotter.renderer)
    cid = picker.GetCellId()
    if not ok or cid < 0:
        return None
    return tuple(picker.GetPickPosition()), picker.GetActor(), int(cid)


def pick_actor(plotter, x, y, actor, tolerance=0.0005):
    """World point where the pixel hits `actor` (nearest surface of that actor only), or None."""
    if vtkCellPicker is None:
        return None
    picker = vtkCellPicker()
    picker.SetTolerance(tolerance)
    picker.PickFromListOn()
    picker.AddPickList(actor)
    if not picker.Pick(x, y, 0, plotter.renderer) or picker.GetCellId() < 0:
        return None
    return tuple(picker.GetPickPosition())


def same_actor(a, b):
    """True when two Python wrappers stand for the same VTK actor."""
    if a is b:
        return True
    try:
        return a.GetAddressAsString("") == b.GetAddressAsString("")
    except Exception:
        return False


def world_per_pixel(plotter):
    try:
        cam = plotter.camera
        h = max(1, plotter.window_size[1])
        if cam.GetParallelProjection():
            return 2.0 * cam.GetParallelScale() / h
        return 2.0 * cam.GetDistance() * math.tan(math.radians(cam.GetViewAngle()) / 2.0) / h
    except Exception:
        return 0.0


def project_display(plotter, pts):
    """Screen position (pixels, origin bottom-left, the same as a click's x, y) of world points (N, 3); NaN for a point behind the camera.
    This is the true picture of the view, so a distance measured here is a distance in pixels whatever the zoom or the angle."""
    import numpy as np
    pts = np.asarray(pts, float).reshape(-1, 3)
    ren = plotter.renderer
    cam = ren.GetActiveCamera()
    w, h = ren.GetSize()
    aspect = w / max(1.0, float(h))
    mat = cam.GetCompositeProjectionTransformMatrix(aspect, -1, 1)
    M = np.array([[mat.GetElement(i, j) for j in range(4)] for i in range(4)])
    hom = np.hstack([pts, np.ones((len(pts), 1))]) @ M.T
    with np.errstate(divide="ignore", invalid="ignore"):
        x = hom[:, 0] / hom[:, 3]
        y = hom[:, 1] / hom[:, 3]
    out = np.stack([(x + 1) * 0.5 * w, (y + 1) * 0.5 * h], axis=1)
    out[hom[:, 3] <= 1e-12] = np.nan
    return out


def seg_distance_px(P, a, b):
    """Distance in pixels from point P (2,) to each segment a[i]-b[i] (arrays (N, 2))."""
    import numpy as np
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", P - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
    return np.linalg.norm(a + ab * t[:, None] - P, axis=1)
