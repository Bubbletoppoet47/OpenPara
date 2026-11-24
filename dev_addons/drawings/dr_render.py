"""dr_render.py - draws the CONTENT of a drawing (the views, later the annotations) with a QPainter.  The same code draws the screen and the PDF, so the paper is what the screen shows.

    Renderer(drawing)                 keeps the converted lines of the views between paints
    r.paint(p, min_px=None, ...)      p's transform maps sheet millimetres to the device (x to the right, y DOWN: a sheet point (x, y up) is drawn at (x, H - y)).
                                      min_px: the thinnest a line may be on screen, in pixels (the lines are 0.5 / 0.25 mm on paper; a PDF passes None)
    r.view_box(v)                     (xmin, ymin, xmax, ymax) of the lines of a view on the sheet, mm (y up)
    r.hit_view(x, y, tol)             the id of the view the point is on (its lines within tol mm, else inside its box), None when there is none
    r.segments(v)                     numpy (n, 2, 2) array of the visible segments of the view on the sheet (y up)

The line weights follow the usual drawing practice: visible edges thick, hidden edges thin and dashed.
"""
import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPen

VISIBLE_W = 0.50                 # mm on paper
HIDDEN_W = 0.25
HIDDEN_DASH = (2.4, 1.2)         # dash and gap, mm
INK = QColor("#111111")
SELECT = QColor("#1a56c4")
HOVER = QColor("#6aa0e0")
GHOST = QColor("#7a8fb5")


class Renderer:
    def __init__(self, drawing):
        self.d = drawing
        self.cache = {}                                           # view id -> (key, paths, segments)

    # ---- the lines of a view on the sheet
    def _key(self, v):
        return (id(v["geom"]), v["scale"], tuple(v["origin"]), v["style"])

    def _entry(self, v):
        key = self._key(v)
        c = self.cache.get(v["id"])
        if c is not None and c[0] == key:
            return c
        pr = self.d.projection(v)
        s, (ox, oy) = v["scale"], v["origin"]
        vis = [_sheet_ent(e, s, ox, oy) for e in pr.vis]
        hid = [_sheet_ent(e, s, ox, oy) for e in pr.hid]
        segs = []
        for e in vis:
            pts = e["pts"]
            segs += [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        arr = np.array(segs, float) if segs else np.zeros((0, 2, 2))
        c = (key, vis, hid, arr)
        self.cache[v["id"]] = c
        return c

    def segments(self, v):
        return self._entry(v)[3]

    def view_box(self, v):
        seg = self.segments(v)
        if not len(seg):
            return (v["origin"][0], v["origin"][1], v["origin"][0], v["origin"][1])
        p = seg.reshape(-1, 2)
        return (float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max()))

    def hit_view(self, x, y, tol, skip=()):
        """The view whose lines pass within tol mm of the point; else the smallest view whose box (grown by tol) holds it; None when there is none."""
        best, best_d = None, None
        boxes = []
        for v in self.d.views:
            if v["id"] in skip:
                continue
            seg = self.segments(v)
            if not len(seg):
                continue
            x0, y0, x1, y1 = self.view_box(v)
            if not (x0 - tol <= x <= x1 + tol and y0 - tol <= y <= y1 + tol):
                continue
            dist = _dist_to_segments(np.array([x, y]), seg)
            boxes.append(((x1 - x0) * (y1 - y0), v["id"]))
            if dist <= tol and (best_d is None or dist < best_d):
                best, best_d = v["id"], dist
        if best is not None:
            return best
        return min(boxes)[1] if boxes else None

    # ---- painting
    def paint(self, p, min_px=None, selected=(), hover=None, ghost=(), show_box=True):
        H = self.d.sheet_dims()[1]
        k = _scale_of(p)
        floor = (min_px / k) if (min_px and k > 0) else 0.0
        for v in self.d.views:
            col = INK
            if v["id"] in ghost:
                col = GHOST
            elif v["id"] in selected:
                col = SELECT
            elif v["id"] == hover:
                col = HOVER
            self._paint_view(p, v, H, col, floor)
        for vid in selected:
            try:
                v = self.d.view(vid)
            except Exception:                                      # noqa: BLE001 (a view that has just gone)
                continue
            if show_box and len(self.segments(v)):
                self._paint_box(p, v, H, floor)

    def _paint_view(self, p, v, H, col, floor):
        _key, vis, hid, _arr = self._entry(v)
        wire = v["style"] == "wireframe"
        if hid:
            if wire:                                               # a wireframe shows every edge alike
                self._stroke(p, hid, H, col, max(VISIBLE_W, floor), None)
            else:
                dash = [HIDDEN_DASH[0] / max(HIDDEN_W, floor), HIDDEN_DASH[1] / max(HIDDEN_W, floor)]
                self._stroke(p, hid, H, col, max(HIDDEN_W, floor), dash)
        self._stroke(p, vis, H, col, max(VISIBLE_W, floor), None)

    def _stroke(self, p, ents, H, col, width, dash):
        pen = QPen(col)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dash:
            pen.setDashPattern(dash)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        for e in ents:
            _add_entity(path, e, H)
        p.drawPath(path)

    def _paint_box(self, p, v, H, floor):
        x0, y0, x1, y1 = self.view_box(v)
        m = 2.5
        pen = QPen(SELECT)
        pen.setWidthF(max(0.15, floor * 0.6))
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(x0 - m, H - (y1 + m), (x1 - x0) + 2 * m, (y1 - y0) + 2 * m))


def _scale_of(p):
    t = p.worldTransform()
    return math.hypot(t.m11(), t.m12())


def _sheet_ent(e, s, ox, oy):
    """An entity on the sheet: its polyline, and for a circle / arc its centre and radius (drawn exactly, not as the polyline)."""
    out = {"t": e["t"], "pts": [(ox + s * x, oy + s * y) for x, y in e["pts"]]}
    if e["t"] in ("circle", "arc"):
        out["c"] = (ox + s * e["c"][0], oy + s * e["c"][1])
        out["r"] = s * e["r"]
    if e["t"] == "arc":
        out["a0"], out["a1"] = e["a0"], e["a1"]
    return out


def _add_entity(path, e, H):
    """One entity into a QPainterPath (a circle or an arc exactly, anything else as the polyline it was measured as)."""
    t, pts = e["t"], e["pts"]
    if t == "circle":
        path.addEllipse(QPointF(e["c"][0], H - e["c"][1]), e["r"], e["r"])
        return
    if t == "arc":
        cx, cy, r = e["c"][0], e["c"][1], e["r"]
        path.moveTo(QPointF(pts[0][0], H - pts[0][1]))
        path.arcTo(QRectF(cx - r, H - cy - r, 2 * r, 2 * r), math.degrees(e["a0"]), math.degrees(e["a1"] - e["a0"]))
        return
    path.moveTo(QPointF(pts[0][0], H - pts[0][1]))
    for x, y in pts[1:]:
        path.lineTo(QPointF(x, H - y))


def _dist_to_segments(q, seg):
    a, b = seg[:, 0, :], seg[:, 1, :]
    ab = b - a
    ab2 = np.maximum((ab * ab).sum(axis=1), 1e-18)
    t = np.clip(((q - a) * ab).sum(axis=1) / ab2, 0.0, 1.0)
    return float(np.linalg.norm(a + ab * t[:, None] - q, axis=1).min())
