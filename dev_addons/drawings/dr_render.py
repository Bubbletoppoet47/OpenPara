"""dr_render.py - draws the CONTENT of a drawing (the views, later the annotations) with a QPainter.  The same code draws the screen and the PDF, so the paper is what the screen shows.

    Renderer(drawing)                 keeps the converted lines of the views between paints
    r.paint(p, min_px=None, ...)      p's transform maps sheet millimetres to the device (x to the right, y DOWN: a sheet point (x, y up) is drawn at (x, H - y)).
                                      min_px: the thinnest a line may be on screen, in pixels (the lines are 0.5 / 0.25 mm on paper; a PDF passes None)
    r.view_box(v)                     (xmin, ymin, xmax, ymax) of the lines of a view on the sheet, mm (y up)
    r.hit_view(x, y, tol)             the id of the view the point is on (its lines within tol mm, else inside its box), None when there is none
    r.segments(v)                     numpy (n, 2, 2) array of the visible segments of the view on the sheet (y up)

The line weights follow the usual drawing practice: visible edges thick, hidden edges thin and dashed; dimensions, extension lines and center lines thin; the numbers of a dimension
are text in the PDF (the same text as on the screen), at ISO 3.5 mm.

    r.paint(..., sel_annot, hover_annot, float_annot)     the dimensions and marks of the drawing are painted over the views (one selected, one hovered, one that follows the pointer)
    r.hit_annot(x, y, tol)                                the id of the dimension / mark the point is on (its lines or its number within tol mm), None when there is none
    r.paint_ref(p, vid, ref, col, ...)                    a picked point / line / circle / arc of a view, highlighted
    r.fmt(mm)                                             how a length reads in a dimension (the units of the program); settable
    r.shape(a) / r.metrics(size)                          the shape of any item drawn over the views (notes, balloons, drawing items too), text measured with the real font
    r.paint_shape(p, shp, col, floor)                     one shape (a draft that is not in the document yet)
    r.handles_of(a)                                       the points of an item a person can drag: [(name, (x, y))] - the tip of a leader, the ends of a line ...
"""
import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainterPath, QPen, QPolygonF

import dr_annot as A
import dr_items as IT
from dr_model import DrawingError

VISIBLE_W = 0.50                 # mm on paper
HIDDEN_W = 0.25
HIDDEN_DASH = (2.4, 1.2)         # dash and gap, mm
INK = QColor("#111111")
SELECT = QColor("#1a56c4")
HOVER = QColor("#6aa0e0")
GHOST = QColor("#7a8fb5")
LOST = QColor("#c0392b")
DIM_W = 0.25                     # dimension, extension and center lines, mm on paper
MARK_DASH = (6.0, 1.2, 1.2, 1.2)  # a centerline: long dash, gap, short dash, gap (mm)
FONT_PX = 100                    # the numbers are set at this size and scaled down to TEXT_H


def sheet_font():
    """The font of everything written on the sheet: the numbers of a dimension, notes, balloons.  The alternate letter forms that depend on the neighbours (a raised colon between capitals ...) are
    off: they have no letter of their own, so a PDF would hand a strange character to whoever copies the text."""
    f = QFont()
    f.setPixelSize(FONT_PX)
    for tag in ("calt", "case"):
        try:
            f.setFeature(QFont.Tag(tag), 0)
        except (AttributeError, TypeError):                           # a Qt without font features: the plain font
            break
    return f


def default_fmt(mm):
    """A length in the units of the program (File > Units), no unit written: 25.4 -> '1' in inches."""
    try:
        import unitctl
        return unitctl.num(unitctl.to_disp(mm), 4)
    except Exception:                                              # noqa: BLE001 (no units module: millimetres)
        return A.number_text(mm)


class Renderer:
    def __init__(self, drawing, fmt=None):
        self.d = drawing
        self.cache = {}                                           # view id -> (key, paths, segments)
        self.fmt = fmt or default_fmt
        self._metrics = {}

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
    def paint(self, p, min_px=None, selected=(), hover=None, ghost=(), show_box=True, sel_annot=None, hover_annot=None, float_annot=None):
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
        self._paint_annots(p, H, floor, sel_annot, hover_annot, float_annot)
        for vid in selected:
            try:
                v = self.d.view(vid)
            except Exception:                                      # noqa: BLE001 (a view that has just gone)
                continue
            if show_box and len(self.segments(v)):
                self._paint_box(p, v, H, floor)

    # ---- dimensions, center marks and centerlines
    def _view_of(self, a):
        try:
            return self.d.view(a["view"])
        except Exception:                                          # noqa: BLE001 (a view that has just gone)
            return None

    def _paint_annots(self, p, H, floor, sel, hover, float_):
        for a in self.d.dims + self.d.marks:
            v = self._view_of(a)
            if v is None:
                continue
            col = SELECT if a["id"] in (sel, float_) else HOVER if a["id"] == hover else LOST if a.get("lost") else INK
            s, o = v["scale"], v["origin"]
            try:
                if a["type"] in ("center_mark", "centerline"):
                    self._paint_mark(p, A.mark_shape(a, s, o), H, col, floor)
                else:
                    self._paint_dim(p, a, A.shape(a, s, o), H, col, floor)
            except (KeyError, ValueError, IndexError, ZeroDivisionError):      # a record that cannot be drawn (a damaged file) is skipped
                continue
        for a in self.d.balloons + self.d.notes + self.d.lines:
            col = SELECT if a["id"] in (sel, float_) else HOVER if a["id"] == hover else INK
            try:
                self._paint_shape(p, self.shape(a), H, col, floor)
            except (KeyError, ValueError, IndexError, ZeroDivisionError, TypeError, DrawingError):
                continue

    # ---- notes, balloons and drawing items
    def metrics(self, size):
        """How big text of `size` points is (dr_items.Metrics), measured with the font the text is painted in."""
        m = self._metrics.get(size)
        if m is None:
            fm = QFontMetricsF(sheet_font())
            k = size * IT.PT / FONT_PX
            m = IT.Metrics(size, width=lambda t: fm.horizontalAdvance(t) * k, cap=(fm.capHeight() or fm.ascent() * 0.72) * k, pitch=fm.lineSpacing() * k)
            self._metrics[size] = m
        return m

    def shape(self, a):
        """The shape of anything drawn over the views: what is painted and what is picked."""
        return self.d.item_shape(a, self.metrics)

    def handles_of(self, a):
        """What can be dragged on an item: a note's or a balloon's leader tip, the handles of a line / rectangle / circle / arc.  [(name, (x, y) on the sheet)]"""
        t = a.get("type")
        if t == "note":
            tip = self.d.leader_tip(a)
            return [("tip", tip)] if tip is not None else []
        if t == "balloon":
            tip = self.d.balloon_tip(a)
            return [("tip", tip)] if tip is not None else []
        if t in IT.DRAW_TYPES:
            return IT.handles(a)
        return []

    def paint_shape(self, p, shp, col, floor=0.0):
        self._paint_shape(p, shp, self.d.sheet_dims()[1], col, floor)

    def _paint_shape(self, p, shp, H, col, floor):
        kind = shp["kind"]
        w = max(IT.DRAW_W if kind in IT.DRAW_TYPES else DIM_W, floor)
        p.setPen(self._pen(col, w))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "circle":
            (cx, cy), r = shp["circle"]
            p.drawEllipse(QPointF(cx, H - cy), r, r)
        elif kind == "arc":
            (cx, cy), r, a0, a1 = shp["arc"]
            path = QPainterPath()
            path.moveTo(QPointF(cx + r * math.cos(a0), H - (cy + r * math.sin(a0))))
            path.arcTo(QRectF(cx - r, H - cy - r, 2 * r, 2 * r), math.degrees(a0), math.degrees(a1 - a0))
            p.drawPath(path)
        else:
            if kind == "balloon":
                (cx, cy), r = shp["circle"]
                p.drawEllipse(QPointF(cx, H - cy), r, r)
            self._poly(p, shp["segs"], H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(col))
        self._heads(p, shp["heads"], H)
        for (x, y), r in shp["dots"]:
            p.drawEllipse(QPointF(x, H - y), r, r)
        if shp["lines"]:
            f = sheet_font()
            k = shp["size"] * IT.PT / FONT_PX
            for text, (x, y) in shp["lines"]:
                p.save()
                p.translate(QPointF(x, H - y))
                p.scale(k, k)
                p.setFont(f)
                p.setPen(col)
                p.drawText(QPointF(0, 0), text)
                p.restore()

    def paint_handles(self, p, a, floor=0.0, k=1.0):
        """Small squares on what can be dragged of a selected item (k: pixels per mm, so they stay the same size on screen)."""
        H = self.d.sheet_dims()[1]
        half = 3.2 / max(k, 1e-9)
        p.setPen(self._pen(SELECT, max(0.15, floor)))
        p.setBrush(QBrush(QColor("#ffffff")))
        for _name, (x, y) in self.handles_of(a):
            p.drawRect(QRectF(x - half, H - y - half, 2 * half, 2 * half))

    def _pen(self, col, width, dash=None):
        pen = QPen(col)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dash:
            pen.setDashPattern([x / width for x in dash])
        return pen

    def _poly(self, p, segs, H):
        path = QPainterPath()
        for sg in segs:
            if len(sg) < 2:
                continue
            path.moveTo(QPointF(float(sg[0][0]), H - float(sg[0][1])))
            for q in sg[1:]:
                path.lineTo(QPointF(float(q[0]), H - float(q[1])))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _paint_mark(self, p, shp, H, col, floor):
        w = max(DIM_W, floor)
        p.setPen(self._pen(col, w, MARK_DASH if shp["style"] == "dashdot" else None))
        self._poly(p, shp["segs"], H)

    def _paint_dim(self, p, a, shp, H, col, floor):
        w = max(DIM_W, floor)
        p.setPen(self._pen(col, w))
        self._poly(p, shp["segs"], H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(col))
        self._heads(p, shp["heads"], H)
        self._text(p, A.text(a, self.fmt), shp["at"], shp["ang"], shp["anchor"], col, H)

    def _heads(self, p, heads, H):
        for tip, inward, size in heads:
            nx, ny = -inward[1], inward[0]
            bx, by = tip[0] + inward[0] * size, tip[1] + inward[1] * size
            half = size / 6.0
            p.drawPolygon(QPolygonF([QPointF(tip[0], H - tip[1]), QPointF(bx + nx * half, H - (by + ny * half)), QPointF(bx - nx * half, H - (by - ny * half))]))

    def _text(self, p, text, at, ang, anchor, col, H):
        """The numbers of a dimension: real text (a PDF keeps it as text), TEXT_H tall in capitals, centred / left / right of `at`, turned by ang (radians, y up)."""
        f = sheet_font()
        fm = QFontMetricsF(f)
        cap = fm.capHeight() or fm.ascent() * 0.72
        width = fm.horizontalAdvance(text)
        p.save()
        p.translate(QPointF(at[0], H - at[1]))
        p.rotate(-math.degrees(ang))
        k = A.TEXT_H / cap
        p.scale(k, k)
        p.setFont(f)
        p.setPen(col)
        x0 = -width / 2.0 if anchor == "center" else 0.0 if anchor == "left" else -width
        p.drawText(QPointF(x0, cap / 2.0), text)
        p.restore()

    def hit_annot(self, x, y, tol):
        """The item (dimension, mark, balloon, note, drawing item) whose lines (or number, or text) are within tol mm of the point; the nearest one - the one painted last when they are
        equally near; None when there is none."""
        best, bd = None, tol
        for a in self.d.sheet_items():
            try:
                if a.get("type") in IT.DRAW_TYPES or a.get("type") in ("note", "balloon"):
                    d = IT.distance(self.shape(a), (x, y))
                else:
                    v = self._view_of(a)
                    if v is None:
                        continue
                    shp = A.mark_shape(a, v["scale"], v["origin"]) if a["type"] in ("center_mark", "centerline") else A.shape(a, v["scale"], v["origin"])
                    d = A.distance(shp, (x, y))
            except (KeyError, ValueError, IndexError, ZeroDivisionError, TypeError, DrawingError):
                continue
            if d <= bd:
                best, bd = a["id"], d
        return best

    def paint_ref(self, p, vid, ref, col, width=0.7, floor=0.0):
        """A picked reference of a view (a point, a line, a circle, an arc) drawn over the view in a colour, so the person sees what a click took."""
        try:
            v = self.d.view(vid)
        except Exception:                                          # noqa: BLE001
            return
        H = self.d.sheet_dims()[1]
        s, (ox, oy) = v["scale"], v["origin"]
        T = lambda q: QPointF(ox + s * q[0], H - (oy + s * q[1]))
        k = ref["k"]
        w = max(width, floor)
        if k == "pt":
            c = T(ref["p"])
            r = max(1.0, floor * 3.0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            p.drawEllipse(c, r, r)
            return
        pen = QPen(col)
        pen.setWidthF(w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if k == "line":
            p.drawLine(T(ref["a"]), T(ref["b"]))
        elif k == "circle":
            c = T(ref["c"])
            p.drawEllipse(c, s * ref["r"], s * ref["r"])
        else:
            c, r = ref["c"], s * ref["r"]
            path = QPainterPath()
            a0 = ref["a0"]
            path.moveTo(QPointF(ox + s * c[0] + r * math.cos(a0), H - (oy + s * c[1] + r * math.sin(a0))))
            path.arcTo(QRectF(ox + s * c[0] - r, H - (oy + s * c[1]) - r, 2 * r, 2 * r), math.degrees(a0), math.degrees(ref["a1"] - a0))
            p.drawPath(path)

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
