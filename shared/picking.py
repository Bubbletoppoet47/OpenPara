"""Picking facets on screen without touching the graphics card: the camera's matrix turns facet centres into pixels, and rays through the mesh
(VTK's cell locator, on the CPU) find what is in front.  Used for click and box selection, and testable without a window.

Pixels here are OpenGL style: origin bottom-left, in the render window's own pixels (Qt's y runs down: use qt_to_gl).
"""
import numpy as np
import vtk

from tasks import tick


def window_size(plotter):
    w, h = plotter.render_window.GetSize()
    return max(int(w), 1), max(int(h), 1)


def matrix(plotter):
    w, h = window_size(plotter)
    m = plotter.renderer.GetActiveCamera().GetCompositeProjectionTransformMatrix(w / h, -1, 1)
    return np.array([[m.GetElement(i, j) for j in range(4)] for i in range(4)]), w, h


def project(plotter, pts):
    """-> px, py (pixels), ndc depth (-1 near .. 1 far), clip w (<= 0: behind the camera)."""
    M, w, h = matrix(plotter)
    hom = np.c_[np.asarray(pts, float), np.ones(len(pts))] @ M.T
    wv = hom[:, 3]
    ndc = hom[:, :3] / np.where(np.abs(wv) < 1e-300, 1e-300, wv)[:, None]
    return (ndc[:, 0] + 1) / 2 * w, (ndc[:, 1] + 1) / 2 * h, ndc[:, 2], wv


def unproject(plotter, px, py, z):
    M, w, h = matrix(plotter)
    inv = np.linalg.inv(M)
    px, py = np.atleast_1d(px).astype(float), np.atleast_1d(py).astype(float)
    ndc = np.c_[px / w * 2 - 1, py / h * 2 - 1, np.full(len(px), float(z)), np.ones(len(px))]
    p = ndc @ inv.T
    return p[:, :3] / p[:, 3:4]


def qt_to_gl(plotter, x, y, ratio=1.0):
    w, h = window_size(plotter)
    return x * ratio, h - y * ratio


class Picker:
    """Cell locator for one mesh (built once, reused for every click and box)."""

    def __init__(self, poly):
        self.poly = poly
        self.loc = vtk.vtkStaticCellLocator()
        self.loc.SetDataSet(poly)
        self.loc.BuildLocator()
        P = np.asarray(poly.points)
        T = poly.faces.reshape(-1, 4)[:, 1:]
        self.centres = P[T].mean(axis=1)
        self.diag = float(np.linalg.norm(P.max(0) - P.min(0))) if len(P) else 1.0

    def first_hit(self, o, e):
        """Index of the first facet the segment o -> e crosses, or -1."""
        t = vtk.mutable(0.0)
        x, pc = [0.0] * 3, [0.0] * 3
        sub, cid = vtk.mutable(0), vtk.mutable(0)
        hit = self.loc.IntersectWithLine(list(map(float, o)), list(map(float, e)), 1e-9 * self.diag, t, x, pc, sub, cid)
        return int(cid) if hit else -1


def click(plotter, picker, gx, gy):
    """Facet under the pixel (gx, gy), or -1."""
    o = unproject(plotter, gx, gy, -1.0)[0]
    e = unproject(plotter, gx, gy, 1.0)[0]
    return picker.first_hit(o, e)


def box(plotter, picker, gx0, gy0, gx1, gy1, hidden=False, progress=None):
    """Boolean mask of the facets whose centre lies in the pixel rectangle; hidden=False keeps only those that nothing is in front of."""
    x0, x1 = sorted((gx0, gx1))
    y0, y1 = sorted((gy0, gy1))
    px, py, z, wv = project(plotter, picker.centres)
    ok = (wv > 0) & (z >= -1) & (z <= 1) & (px >= x0) & (px <= x1) & (py >= y0) & (py <= y1)
    mask = np.zeros(len(picker.centres), bool)
    idx = np.where(ok)[0]
    if hidden or len(idx) == 0:
        mask[idx] = True
        return mask
    o = unproject(plotter, px[idx], py[idx], -1.0)
    c = picker.centres[idx]
    d = c - o
    ln = np.maximum(np.linalg.norm(d, axis=1), 1e-300)[:, None]
    e = c + d / ln * (1e-3 * picker.diag)                           # end a little beyond the centre, so the facet itself is hit if nothing else is
    for k, i in enumerate(idx.tolist()):
        if progress and k % 2000 == 0:
            progress("Finding visible facets", k / len(idx))
        mask[i] = picker.first_hit(o[k], e[k]) == i
    return mask


def grow(T, sel):
    """The selection plus every facet that touches it at a corner."""
    v = np.zeros(int(T.max()) + 1, bool)
    v[T[sel].ravel()] = True
    return v[T].any(axis=1)


def shrink(T, sel):
    """The selection minus the facets that touch an unselected facet."""
    v = np.zeros(int(T.max()) + 1, bool)
    v[T[~sel].ravel()] = True
    return sel & ~v[T].any(axis=1)
