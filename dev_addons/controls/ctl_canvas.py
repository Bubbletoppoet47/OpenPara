"""ctl_canvas.py - the drawing surface for electrical circuits and mechanical systems (Qt).

Parts live on a grid.  Two-terminal parts (source, R, L, C, wire, mass, spring, damper) are placed with two clicks; one-terminal parts (ground,
wall, applied force, output probes) with one.  The same widget, read-only, shows the generated analog of a drawn system.
A paint error must never escape (it would close the whole program), so painting is guarded.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

import ctl_circuit as ckt

GRID = 28
INK = QColor("#1d2b3a")
SEL = QColor("#1f5fbf")
DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))                      # rot 0..3: right, down, left, up
DEFAULT_ROT = {"GND": 1, "WALL": 2, "F": 0, "VO": 0, "X": 3}
LABELS = {"V": "Source Vi", "R": "Resistor R", "L": "Inductor L", "C": "Capacitor C", "W": "Wire", "GND": "Ground", "VO": "Output Vo",
          "M": "Mass M", "K": "Spring K", "B": "Damper B", "WALL": "Wall", "F": "Force F", "X": "Output x"}


def new_part(kind, a, b=None, rot=None, parts=()):
    p = {"kind": kind, "a": tuple(a), "b": tuple(b) if b is not None else None, "name": "", "value": "", "rot": DEFAULT_ROT.get(kind, 0) if rot is None else rot}
    if kind in ckt.VALUED or kind in ("V", "VO", "X", "F"):
        p["name"] = ckt.default_name(kind, parts) if kind not in ("F",) else "F"
    return p


def parts_to_json(parts):
    return [{"kind": p["kind"], "a": list(p["a"]), "b": list(p["b"]) if p.get("b") is not None else None, "name": p.get("name", ""),
             "value": p.get("value", ""), "rot": p.get("rot", 0)} for p in parts]


def parts_from_json(rows):
    out = []
    for r in rows or []:
        try:
            k = r["kind"]
            if k not in ckt.ELECTRICAL + ckt.MECHANICAL:
                continue
            a = (int(r["a"][0]), int(r["a"][1]))
            b = (int(r["b"][0]), int(r["b"][1])) if r.get("b") is not None else None
            if (k in ckt.TWO) != (b is not None):
                continue
            out.append({"kind": k, "a": a, "b": b, "name": str(r.get("name", "")), "value": str(r.get("value", "")), "rot": int(r.get("rot", 0)) % 4})
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / n))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


class Canvas(QWidget):
    edited = pyqtSignal()                      # the drawing changed
    tool_reset = pyqtSignal()                  # right click with a part tool: go back to Select

    def __init__(self, readonly=False):
        super().__init__()
        self.readonly = readonly
        self.parts = []
        self.tool = "select"
        self.rot = 0
        self.sel = None
        self.pending = None
        self.hover = None
        self.drag = None
        self.setMinimumSize(320, 220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.empty_text = ""

    # ------------------------------------------------------------------ geometry
    def _view(self):
        """(origin x, origin y, pixels per grid unit)."""
        if not self.readonly or not self.parts:
            return 24.0, 24.0, float(GRID)
        xs, ys = [], []
        for p in self.parts:
            for k in ("a", "b"):
                if p.get(k) is not None:
                    xs.append(p[k][0])
                    ys.append(p[k][1])
            if p["b"] is None:
                d = DIRS[p.get("rot", 0) % 4]
                xs.append(p["a"][0] + 3 * d[0])
                ys.append(p["a"][1] + 3 * d[1])
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        bw, bh = max(x1 - x0, 1), max(y1 - y0, 1)
        sc = min(GRID * 1.5, (self.width() - 90) / bw, (self.height() - 90) / bh)
        sc = max(sc, 8.0)
        return (self.width() - bw * sc) / 2 - x0 * sc, (self.height() - bh * sc) / 2 - y0 * sc, sc

    def to_px(self, g):
        ox, oy, sc = self._view()
        return QPointF(ox + g[0] * sc, oy + g[1] * sc)

    def to_grid(self, pos):
        ox, oy, sc = self._view()
        return (round((pos.x() - ox) / sc), round((pos.y() - oy) / sc))

    # ------------------------------------------------------------------ editing
    def set_parts(self, parts):
        self.parts = parts
        self.sel = None
        self.pending = None
        self.update()

    def set_tool(self, tool):
        self.tool = tool
        self.pending = None
        self.update()

    def _changed(self):
        self.edited.emit()
        self.update()

    def add_part(self, kind, a, b=None):
        self.parts.append(new_part(kind, a, b, self.rot if b is None else None, self.parts))
        self._changed()

    def delete_selected(self):
        if self.sel is not None and 0 <= self.sel < len(self.parts):
            del self.parts[self.sel]
            self.sel = None
            self._changed()

    def rotate_selected(self):
        if self.sel is None or not (0 <= self.sel < len(self.parts)):
            self.rot = (self.rot + 1) % 4
            self.update()
            return
        p = self.parts[self.sel]
        if p["b"] is None:
            p["rot"] = (p.get("rot", 0) + 1) % 4
        else:
            ax, ay = p["a"]
            dx, dy = p["b"][0] - ax, p["b"][1] - ay
            p["b"] = (ax - dy, ay + dx)
        self._changed()

    def hit(self, pos):
        best, best_d = None, 14.0
        for i in range(len(self.parts) - 1, -1, -1):
            p = self.parts[i]
            a = self.to_px(p["a"])
            if p["b"] is not None:
                b = self.to_px(p["b"])
                d = _seg_dist((pos.x(), pos.y()), (a.x(), a.y()), (b.x(), b.y()))
            else:
                dd = DIRS[p.get("rot", 0) % 4]
                tip = QPointF(a.x() + dd[0] * 36, a.y() + dd[1] * 36)
                d = _seg_dist((pos.x(), pos.y()), (a.x(), a.y()), (tip.x(), tip.y()))
            if d < best_d:
                best, best_d = i, d
        return best

    def mousePressEvent(self, ev):
        if self.readonly:
            return
        self.setFocus()
        g = self.to_grid(ev.position())
        if ev.button() == Qt.MouseButton.RightButton:
            if self.pending is not None:
                self.pending = None
                self.update()
            elif self.tool != "select":
                self.tool_reset.emit()
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if self.tool == "select":
            self.sel = self.hit(ev.position())
            if self.sel is not None:
                p = self.parts[self.sel]
                self.drag = (g, p["a"], p["b"], False)
            self.update()
        elif self.tool == "wire":
            if self.pending is None:
                self.pending = g
            elif g != self.pending:
                (px, py), (gx, gy) = self.pending, g
                if px != gx and py != gy:
                    self.parts.append(new_part("W", (px, py), (gx, py), parts=self.parts))
                    self.parts.append(new_part("W", (gx, py), (gx, gy), parts=self.parts))
                else:
                    self.parts.append(new_part("W", (px, py), (gx, gy), parts=self.parts))
                self.pending = g
                self._changed()
        elif self.tool in ckt.TWO:
            if self.pending is None:
                self.pending = g
            else:
                b = self._axis(self.pending, g)
                if abs(b[0] - self.pending[0]) + abs(b[1] - self.pending[1]) >= 2:
                    self.add_part(self.tool, self.pending, b)
                    self.pending = None
        else:
            self.add_part(self.tool, g)

    @staticmethod
    def _axis(a, g):
        dx, dy = g[0] - a[0], g[1] - a[1]
        return (a[0] + dx, a[1]) if abs(dx) >= abs(dy) else (a[0], a[1] + dy)

    def mouseDoubleClickEvent(self, ev):
        if self.tool == "wire":
            self.pending = None
            self.update()

    def mouseMoveEvent(self, ev):
        g = self.to_grid(ev.position())
        if self.drag is not None and self.sel is not None and 0 <= self.sel < len(self.parts):
            g0, a0, b0, _moved = self.drag
            dx, dy = g[0] - g0[0], g[1] - g0[1]
            p = self.parts[self.sel]
            p["a"] = (a0[0] + dx, a0[1] + dy)
            if b0 is not None:
                p["b"] = (b0[0] + dx, b0[1] + dy)
            self.drag = (g0, a0, b0, self.drag[3] or (dx or dy) != 0)
            self.update()
        elif g != self.hover:
            self.hover = g
            if self.pending is not None or self.tool != "select":
                self.update()

    def mouseReleaseEvent(self, ev):
        if self.drag is not None and self.drag[3]:
            self.edited.emit()
        self.drag = None

    def keyPressEvent(self, ev):
        k = ev.key()
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        elif k == Qt.Key.Key_R:
            self.rotate_selected()
        elif k == Qt.Key.Key_Escape:
            self.pending = None
            self.update()
        else:
            super().keyPressEvent(ev)

    def leaveEvent(self, ev):
        self.hover = None
        self.update()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            self.draw(p)
        except Exception:                      # noqa: BLE001 - an error escaping a paint event would close the whole program
            pass
        finally:
            p.end()

    def draw(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        ox, oy, sc = self._view()
        if not self.readonly:
            p.setPen(QPen(QColor("#d3dae5"), 2))
            x = ox
            while x < w:
                y = oy
                while y < h:
                    p.drawPoint(QPointF(x, y))
                    y += sc
                x += sc
        f = QFont("Segoe UI")
        f.setPixelSize(13)
        p.setFont(f)
        if not self.parts:
            p.setPen(QColor("#7a8696"))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return
        for i, part in enumerate(self.parts):
            self.draw_part(p, part, i == self.sel)
        self.draw_junctions(p)
        if not self.readonly and self.hover is not None:
            hp = self.to_px(self.hover)
            p.setPen(QPen(QColor("#9bb4d8"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if self.pending is not None:
                a = self.to_px(self.pending)
                if self.tool == "wire":
                    mid = QPointF(hp.x(), a.y())
                    p.drawLine(a, mid)
                    p.drawLine(mid, hp)
                elif self.tool in ckt.TWO:
                    p.drawLine(a, self.to_px(self._axis(self.pending, self.hover)))
                p.drawEllipse(a, 5, 5)
            p.drawEllipse(hp, 4, 4)

    def draw_junctions(self, p):
        count = {}
        for part in self.parts:
            for k in ("a", "b"):
                if part.get(k) is not None:
                    count[tuple(part[k])] = count.get(tuple(part[k]), 0) + 1
        dots = {q for q, n in count.items() if n >= 3}
        for part in self.parts:
            if part["kind"] == "W":
                for q in count:
                    if ckt._on_segment(q, tuple(part["a"]), tuple(part["b"])):
                        dots.add(q)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(INK)
        for q in dots:
            p.drawEllipse(self.to_px(q), 4, 4)

    def label_of(self, part):
        if part.get("label"):
            return part["label"]
        name = (part.get("name") or "").strip()
        v = (part.get("value") or "").strip()
        if part["kind"] in ("V", "VO", "X", "F"):
            return name
        if v and ckt.parse_value(v) is not None:
            return "%s = %s" % (name, v) if name else v
        return v or name

    def draw_part(self, p, part, selected):
        col = SEL if selected else INK
        pen = QPen(col, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        kind = part["kind"]
        a = self.to_px(part["a"])
        text = self.label_of(part)
        if part["b"] is not None:
            b = self.to_px(part["b"])
            dx, dy = b.x() - a.x(), b.y() - a.y()
            L = math.hypot(dx, dy)
            if L < 1:
                return
            p.save()
            p.translate(a)
            p.rotate(math.degrees(math.atan2(dy, dx)))
            self.draw_two(p, kind, L, col)
            p.restore()
            if text and kind != "W":
                cx, cy = (a.x() + b.x()) / 2, (a.y() + b.y()) / 2
                if kind == "M":
                    off = 0.0
                else:
                    off = 30.0 if kind == "V" else 24.0
                nx, ny = dy / L, -dx / L
                if ny > 0.01 or (abs(ny) < 0.01 and nx < 0):                 # labels go above or to the right
                    nx, ny = -nx, -ny
                p.setPen(col)
                if abs(nx) > 0.5:                                           # beside a vertical part: start (or end) the text clear of the symbol
                    left = nx > 0
                    r = QRectF(cx + nx * (off - 4) - (0 if left else 140), cy - 10, 140, 20)
                    p.drawText(r, (Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignVCenter, text)
                else:
                    r = QRectF(cx + nx * off - 70, cy + ny * off - 10, 140, 20)
                    p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        else:
            d = DIRS[part.get("rot", 0) % 4]
            p.save()
            p.translate(a)
            p.rotate(90 * (part.get("rot", 0) % 4))
            reach = self.draw_one(p, kind, col)
            p.restore()
            if text:
                p.setPen(col)
                tx, ty = a.x() + d[0] * (reach + 16), a.y() + d[1] * (reach + 12)
                p.drawText(QRectF(tx - 40, ty - 10, 80, 20), Qt.AlignmentFlag.AlignCenter, text)

    def draw_two(self, p, kind, L, col):
        body = min(L * 0.62, 84.0)
        x0 = (L - body) / 2
        if kind == "W":
            p.drawLine(QPointF(0, 0), QPointF(L, 0))
        elif kind == "R":
            pts = [QPointF(x0 + body * (2 * i + 1) / 12, -8 if i % 2 == 0 else 8) for i in range(6)]
            path = QPainterPath(QPointF(0, 0))
            for q in [QPointF(x0, 0)] + pts + [QPointF(x0 + body, 0), QPointF(L, 0)]:
                path.lineTo(q)
            p.drawPath(path)
        elif kind == "L":
            n = 4
            w = body / n
            p.drawLine(QPointF(0, 0), QPointF(x0, 0))
            p.drawLine(QPointF(x0 + body, 0), QPointF(L, 0))
            for i in range(n):
                p.drawArc(QRectF(x0 + i * w, -w / 2, w, w), 0, 180 * 16)
        elif kind == "C":
            m = L / 2
            p.drawLine(QPointF(0, 0), QPointF(m - 5, 0))
            p.drawLine(QPointF(m + 5, 0), QPointF(L, 0))
            p.drawLine(QPointF(m - 5, -15), QPointF(m - 5, 15))
            p.drawLine(QPointF(m + 5, -15), QPointF(m + 5, 15))
        elif kind == "V":
            m = L / 2
            p.drawLine(QPointF(0, 0), QPointF(m - 16, 0))
            p.drawLine(QPointF(m + 16, 0), QPointF(L, 0))
            p.drawEllipse(QPointF(m, 0), 16, 16)
            p.drawLine(QPointF(m - 9, 0), QPointF(m - 3, 0))                 # + beside terminal a
            p.drawLine(QPointF(m - 6, -3), QPointF(m - 6, 3))
            p.drawLine(QPointF(m + 3, 0), QPointF(m + 9, 0))                 # - beside terminal b
        elif kind == "M":
            p.setBrush(QColor("#d9ecd0"))
            p.drawRect(QRectF(0, -19, L, 38))
        elif kind == "K":
            lead = min(14.0, L * 0.2)
            n = 8
            path = QPainterPath(QPointF(0, 0))
            path.lineTo(QPointF(lead, 0))
            span = L - 2 * lead
            for i in range(n):
                path.lineTo(QPointF(lead + span * (2 * i + 1) / (2 * n), -9 if i % 2 == 0 else 9))
            path.lineTo(QPointF(L - lead, 0))
            path.lineTo(QPointF(L, 0))
            p.drawPath(path)
        elif kind == "B":
            p.drawLine(QPointF(0, 0), QPointF(L * 0.3, 0))
            path = QPainterPath(QPointF(L * 0.66, -10))
            path.lineTo(QPointF(L * 0.3, -10))
            path.lineTo(QPointF(L * 0.3, 10))
            path.lineTo(QPointF(L * 0.66, 10))
            p.drawPath(path)
            p.drawLine(QPointF(L * 0.5, -6), QPointF(L * 0.5, 6))
            p.drawLine(QPointF(L * 0.5, 0), QPointF(L, 0))

    def draw_one(self, p, kind, col):
        """Draws a one-terminal symbol reaching out along +x from the terminal; returns how far it reaches (pixels)."""
        if kind == "GND":
            p.drawLine(QPointF(0, 0), QPointF(10, 0))
            for i, hh in enumerate((13, 8, 3)):
                p.drawLine(QPointF(10 + 5 * i, -hh), QPointF(10 + 5 * i, hh))
            return 22
        if kind == "WALL":
            p.drawLine(QPointF(0, 0), QPointF(8, 0))
            p.drawLine(QPointF(8, -36), QPointF(8, 36))
            for y in range(-32, 36, 9):
                p.drawLine(QPointF(8, y), QPointF(18, y + 9))
            return 18
        if kind == "F":
            p.drawLine(QPointF(0, 0), QPointF(46, 0))
            p.setBrush(col)
            p.drawPolygon([QPointF(50, 0), QPointF(38, -6), QPointF(38, 6)])
            p.setBrush(Qt.BrushStyle.NoBrush)
            return 50
        if kind == "X":
            p.drawLine(QPointF(0, 0), QPointF(26, 0))
            p.setBrush(col)
            p.drawPolygon([QPointF(32, 0), QPointF(22, -5), QPointF(22, 5)])
            p.setBrush(Qt.BrushStyle.NoBrush)
            return 32
        if kind == "VO":
            p.drawLine(QPointF(0, 0), QPointF(14, 0))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(18, 0), 4, 4)
            p.setBrush(Qt.BrushStyle.NoBrush)
            return 22
        return 10
