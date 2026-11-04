"""editor.py - the schematic editor of the Circuits add-on (QGraphicsScene): parts you place from the palette and wires you draw between pins.

The scene itself is the document: PartItem / WireItem hold the data, `to_json` / `from_json` save and load it, undo is a stack of JSON snapshots.
`connectivity()` turns the drawing into nets for the solver (wires join where their points meet a pin, a wire end or a wire's side).
"""
import json
import math

from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTransform
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

import parts as P

GRID = 20.0
PIN_HIT = 0.55            # in grid units
WIRE_COLOR = QColor("#2a9d8f")


def snap(v):
    return round(v / GRID) * GRID


def key(pt):
    return (round(pt[0] / GRID * 2) / 2, round(pt[1] / GRID * 2) / 2)


def orthogonalize(pts):
    out = [pts[0]]
    for q in pts[1:]:
        p0 = out[-1]
        if abs(p0[0] - q[0]) > 1e-6 and abs(p0[1] - q[1]) > 1e-6:
            out.append((q[0], p0[1]))
        out.append(q)
    res = []
    for q in out:                                              # drop repeated points
        if not res or abs(res[-1][0] - q[0]) > 1e-6 or abs(res[-1][1] - q[1]) > 1e-6:
            res.append(q)
    return res


class PartItem(QGraphicsItem):
    def __init__(self, kind, name, x=0, y=0, rot=0, mirror=False, prm=None):
        super().__init__()
        self.kind, self.name = kind, name
        self.defn = P.PARTS[kind]
        self.prm = P.default_params(kind)
        if prm:
            self.prm.update(prm)
        self.rot, self.mirror = rot, mirror
        self.readout = ""              # text from the meters / the solver
        self.glow = 0.0
        self.state = {}
        self.setPos(x, y)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setZValue(2)

    # geometry ------------------------------------------------------------------------------
    def xform(self):
        t = QTransform()
        t.rotate(90 * self.rot)
        if self.mirror:
            t.scale(-1, 1)
        return t

    def pin_local(self, i):
        _n, x, y = self.defn.pins[i]
        q = self.xform().map(QPointF(x, y))
        return QPointF(q.x() * GRID, q.y() * GRID)

    def pin_scene(self, i):
        return self.mapToScene(self.pin_local(i))

    def pin_names(self):
        return [p[0] for p in self.defn.pins]

    def boundingRect(self):
        x0, y0, x1, y1 = self.defn.bbox
        r = self.xform().mapRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        r = QRectF(r.x() * GRID, r.y() * GRID, r.width() * GRID, r.height() * GRID)
        return r.adjusted(-30, -34, 70, 34)

    def shape(self):
        x0, y0, x1, y1 = self.defn.bbox
        r = self.xform().mapRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        path = QPainterPath()
        path.addRect(QRectF(r.x() * GRID, r.y() * GRID, r.width() * GRID, r.height() * GRID))
        return path

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene() is not None:
            new = QPointF(snap(value.x()), snap(value.y()))
            sc = self.scene()
            if hasattr(sc, "part_moving"):
                sc.part_moving(self, new - self.pos())
            return new
        return super().itemChange(change, value)

    # painting ------------------------------------------------------------------------------
    def label_text(self):
        d = self.defn
        k = self.kind
        if k in ("R", "POT", "LAMP"):
            return P.eng(self.prm["r"], "Ω")
        if k == "C":
            return P.eng(self.prm["c"], "F")
        if k == "L":
            return P.eng(self.prm["l"], "H")
        if k == "BAT":
            return P.eng(self.prm["dc"], "V")
        if k == "WALL":
            return f"{self.prm['vrms']:g} V {self.prm['freq']:g} Hz"
        if k == "FGEN":
            return f"{self.prm['wave']} {P.eng(self.prm['amp'], 'V')} {P.eng(self.prm['freq'], 'Hz')}"
        if k == "LED":
            return self.prm["color"]
        if k == "ZENER":
            return P.eng(self.prm["vz"], "V")
        if k in ("BUCK", "BOOST"):
            return f"{P.eng(self.prm['vset'], 'V')} out"
        if k == "FUSE":
            return P.eng(self.prm["rating"], "A")
        if k == "SW":
            return "closed" if self.prm.get("closed") else "open"
        return ""

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.save()
        p.scale(GRID, GRID)
        p.rotate(90 * self.rot)
        if self.mirror:
            p.scale(-1, 1)
        if self.isSelected():
            r = self.defn.bbox
            p.setPen(QPen(QColor("#e76f51"), 0.06, Qt.PenStyle.DashLine))
            p.setBrush(QColor(231, 111, 81, 25))
            p.drawRect(QRectF(r[0], r[1], r[2] - r[0], r[3] - r[1]))
        st = dict(self.state)
        st["closed"] = self.prm.get("closed")
        P.draw_symbol(p, self.kind, self.prm, self.glow, st)
        p.restore()
        # pins
        p.setPen(QPen(QColor("#1d3557"), 1))
        for i in range(len(self.defn.pins)):
            q = self.pin_local(i)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(q, 2.6, 2.6)
        # text
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor("#222222"))
        r = self.boundingRect()
        cx = self.xform().mapRect(QRectF(*self.defn.bbox[:2], self.defn.bbox[2] - self.defn.bbox[0], self.defn.bbox[3] - self.defn.bbox[1]))
        top = cx.y() * GRID - 6
        left = cx.x() * GRID
        wid = cx.width() * GRID
        p.drawText(QRectF(left - 20, top - 14, wid + 40, 14), Qt.AlignmentFlag.AlignCenter, self.name)
        lab = self.label_text()
        bottom = (cx.y() + cx.height()) * GRID
        if lab:
            p.setPen(QColor("#555555"))
            p.drawText(QRectF(left - 30, bottom + 2, wid + 60, 14), Qt.AlignmentFlag.AlignCenter, lab)
        if self.readout:
            f2 = QFont("Consolas")
            f2.setPixelSize(13)
            f2.setBold(True)
            p.setFont(f2)
            p.setPen(QColor("#b5179e") if self.kind in ("VM", "AM", "OHM") else QColor("#d62828"))
            p.drawText(QRectF(left - 30, bottom + (14 if lab else 2), wid + 60, 16), Qt.AlignmentFlag.AlignCenter, self.readout)
        if self.kind == "SCOPE":
            p.setPen(QColor("#555555"))
            p.drawText(QRectF(left - 20, bottom + 2, wid + 40, 14), Qt.AlignmentFlag.AlignCenter, f"{P.eng(self.prm['timediv'], 's')}/div")

    def data(self):
        return {"kind": self.kind, "name": self.name, "x": self.pos().x() / GRID, "y": self.pos().y() / GRID, "rot": self.rot,
                "mirror": self.mirror, "prm": self.prm}


class WireItem(QGraphicsItem):
    def __init__(self, pts):
        super().__init__()
        self.pts = [tuple(q) for q in pts]
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(1)
        self.color = None

    def boundingRect(self):
        xs = [q[0] for q in self.pts]
        ys = [q[1] for q in self.pts]
        return QRectF(min(xs) - 6, min(ys) - 6, max(xs) - min(xs) + 12, max(ys) - min(ys) + 12)

    def shape(self):
        path = QPainterPath()
        for a, b in zip(self.pts, self.pts[1:]):
            r = QRectF(QPointF(min(a[0], b[0]) - 5, min(a[1], b[1]) - 5), QPointF(max(a[0], b[0]) + 5, max(a[1], b[1]) + 5))
            path.addRect(r)
        return path

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = QColor(self.color) if self.color else WIRE_COLOR
        p.setPen(QPen(QColor("#e76f51") if self.isSelected() else col, 2.4 if self.isSelected() else 2.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for a, b in zip(self.pts, self.pts[1:]):
            p.drawLine(QPointF(*a), QPointF(*b))

    def data(self):
        return [[q[0] / GRID, q[1] / GRID] for q in self.pts]


def on_segment(pt, a, b, tol=1e-6):
    (x, y), (x1, y1), (x2, y2) = pt, a, b
    if abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) > tol * max(1.0, abs(x2 - x1) + abs(y2 - y1)):
        return False
    return min(x1, x2) - tol <= x <= max(x1, x2) + tol and min(y1, y2) - tol <= y <= max(y1, y2) + tol


class CircuitScene(QGraphicsScene):
    changed = pyqtSignal()               # the circuit was edited (re-solve)
    selection_changed = pyqtSignal()
    say = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setSceneRect(-3000, -2000, 6000, 4000)
        self.place_kind = None
        self.wire_tool = False
        self.wiring = None               # list of points of the wire being drawn (scene coords), or None
        self.cursor_pt = (0.0, 0.0)
        self.flip_elbow = False
        self.undo_stack, self.redo_stack = [], []
        self._attach = None
        self.selectionChanged.connect(self._sel)

    def _sel(self):
        try:
            self.selection_changed.emit()
        except RuntimeError:
            pass

    # ------------------------------------------------------------------ items
    def parts(self):
        return [i for i in self.items() if isinstance(i, PartItem)]

    def wires(self):
        return [i for i in self.items() if isinstance(i, WireItem)]

    def new_name(self, kind):
        pre = P.PARTS[kind].prefix
        used = {p.name for p in self.parts()}
        n = 1
        while f"{pre}{n}" in used:
            n += 1
        return f"{pre}{n}"

    def add_part(self, kind, x, y, **kw):
        it = PartItem(kind, kw.pop("name", None) or self.new_name(kind), x, y, **kw)
        self.addItem(it)
        return it

    def drop_part(self, kind, x, y):
        self.push_undo()
        self.clearSelection()
        it = self.add_part(kind, x, y)
        it.setSelected(True)
        self.changed.emit()

    # ------------------------------------------------------------------ json / undo
    def to_json(self):
        return {"format": "openpara-circuit", "version": 1, "parts": [p.data() for p in sorted(self.parts(), key=lambda q: q.name)],
                "wires": [w.data() for w in self.wires()]}

    def from_json(self, d):
        for it in list(self.items()):
            self.removeItem(it)
        for p in d.get("parts", []):
            if p["kind"] in P.PARTS:
                self.add_part(p["kind"], p["x"] * GRID, p["y"] * GRID, name=p["name"], rot=p.get("rot", 0), mirror=p.get("mirror", False), prm=p.get("prm"))
        for w in d.get("wires", []):
            self.addItem(WireItem([(q[0] * GRID, q[1] * GRID) for q in w]))
        self.wiring = None

    def snapshot(self):
        return json.dumps(self.to_json())

    def push_undo(self):
        self.undo_stack.append(self.snapshot())
        del self.undo_stack[:-100]
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.snapshot())
        self.from_json(json.loads(self.undo_stack.pop()))
        self.changed.emit()

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.snapshot())
        self.from_json(json.loads(self.redo_stack.pop()))
        self.changed.emit()

    def clear_all(self):
        self.push_undo()
        self.from_json({})
        self.changed.emit()

    # ------------------------------------------------------------------ hit tests
    def pin_hit(self, pt, tol=PIN_HIT):
        best = None
        for p in self.parts():
            for i in range(len(p.defn.pins)):
                q = p.pin_scene(i)
                d = math.hypot(q.x() - pt[0], q.y() - pt[1]) / GRID
                if d <= tol and (best is None or d < best[0]):
                    best = (d, p, i, (q.x(), q.y()))
        return best

    def wire_hit(self, pt):
        """A point on an existing wire (vertex or side) near pt -> its snapped coordinates."""
        for w in self.wires():
            for a, b in zip(w.pts, w.pts[1:]):
                if on_segment(pt, a, b, 1e-6):
                    return pt
        return None

    # ------------------------------------------------------------------ attached wire ends follow a moving part
    def part_moving(self, part, delta):
        if delta.isNull() or self.wiring is not None:
            return
        if self._attach is None:
            self._attach = {}
        if part not in self._attach:
            lst = []
            pins = [(part.pin_scene(i).x(), part.pin_scene(i).y()) for i in range(len(part.defn.pins))]
            for w in self.wires():
                for idx, q in enumerate(w.pts):
                    if any(abs(q[0] - a) < 1e-6 and abs(q[1] - b) < 1e-6 for a, b in pins):
                        lst.append((w, idx))
            self._attach[part] = lst
        for w, idx in self._attach[part]:
            q = w.pts[idx]
            w.pts[idx] = (q[0] + delta.x(), q[1] + delta.y())
            w.prepareGeometryChange()
            w.update()

    # ------------------------------------------------------------------ mouse
    def mouse_pt(self, ev):
        return (snap(ev.scenePos().x()), snap(ev.scenePos().y()))

    def elbow(self, a, b):
        if abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6:
            return [b]
        return [(b[0], a[1]), b] if not self.flip_elbow else [(a[0], b[1]), b]

    def mousePressEvent(self, ev):
        pt = self.mouse_pt(ev)
        if ev.button() == Qt.MouseButton.RightButton:
            if self.wiring is not None or self.place_kind:
                self.cancel_modes()
                ev.accept()
                return
            super().mousePressEvent(ev)
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(ev)
            return
        if self.place_kind:
            self.push_undo()
            self.clearSelection()
            it = self.add_part(self.place_kind, pt[0], pt[1])
            it.setSelected(True)
            if self.place_kind == "GND" or True:
                pass
            self.changed.emit()
            ev.accept()
            return
        if self.wiring is not None:                              # continue / finish a wire
            end = self.pin_hit(pt, 0.6)
            if end:
                pt = end[3]
            pts = self.wiring + self.elbow(self.wiring[-1], pt)
            finish = bool(end) or self.wire_hit(pt) is not None
            if len(pts) > len(self.wiring):
                self.wiring = pts
            if finish:
                self.finish_wire()
            ev.accept()
            return
        hit = self.pin_hit((ev.scenePos().x(), ev.scenePos().y()))
        if hit:                                                  # start a wire at a pin
            self.clearSelection()
            self.wiring = [hit[3]]
            self.cursor_pt = hit[3]
            ev.accept()
            return
        if self.wire_tool:
            self.clearSelection()
            self.wiring = [self.wire_hit(pt) or pt]
            self.cursor_pt = pt
            ev.accept()
            return
        self._attach = None
        self._moved = False
        self._snap_before = self.snapshot()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        pt = self.mouse_pt(ev)
        self.cursor_pt = pt
        if self.place_kind or self.wiring is not None:
            self.update()
        if ev.buttons() & Qt.MouseButton.LeftButton and self.wiring is None and self._attach is not None or (
                ev.buttons() & Qt.MouseButton.LeftButton and self.selectedItems() and self.wiring is None):
            self._moved = True
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        if getattr(self, "_moved", False) and self.wiring is None:
            self._moved = False
            if self._attach:
                for lst in self._attach.values():
                    for w, _i in lst:
                        w.pts = orthogonalize(w.pts)
                        w.prepareGeometryChange()
            if getattr(self, "_snap_before", None) is not None:
                self.undo_stack.append(self._snap_before)
                self.redo_stack.clear()
            self._attach = None
            self.changed.emit()
        self._attach = None

    def mouseDoubleClickEvent(self, ev):
        if self.wiring is not None:
            self.finish_wire()
            ev.accept()
            return
        it = self.itemAt(ev.scenePos(), QTransform())
        if isinstance(it, PartItem) and it.kind == "SW":
            self.push_undo()
            it.prm["closed"] = not it.prm["closed"]
            it.update()
            self.changed.emit()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def finish_wire(self):
        pts = orthogonalize(self.wiring) if self.wiring else []
        self.wiring = None
        if len(pts) >= 2:
            self.push_undo()
            self.addItem(WireItem(pts))
            self.changed.emit()
        self.update()

    def cancel_modes(self):
        self.wiring = None
        self.place_kind = None
        self.wire_tool = False
        self.say.emit("")
        self.update()

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Escape:
            self.cancel_modes()
        elif k == Qt.Key.Key_Space and self.wiring is not None:
            self.flip_elbow = not self.flip_elbow
            self.update()
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        elif k == Qt.Key.Key_R and not (ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.rotate_selected()
        elif k == Qt.Key.Key_F:
            self.rotate_selected(flip=True)
        elif k == Qt.Key.Key_W:
            self.wire_tool = True
            self.say.emit("Wire tool: click a start point, click corners, click a pin or a wire to finish (Esc cancels).")
        elif k == Qt.Key.Key_Z and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.undo()
        elif k == Qt.Key.Key_Y and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.redo()
        elif k == Qt.Key.Key_A and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            for it in self.items():
                it.setSelected(True)
        else:
            super().keyPressEvent(ev)

    # ------------------------------------------------------------------ edits
    def delete_selected(self):
        sel = self.selectedItems()
        if not sel:
            return
        self.push_undo()
        for it in sel:
            self.removeItem(it)
        self.changed.emit()

    def rotate_selected(self, flip=False):
        sel = [i for i in self.selectedItems() if isinstance(i, PartItem)]
        if not sel:
            return
        self.push_undo()
        for p in sel:
            old = [(w, idx) for w in self.wires() for idx, q in enumerate(w.pts)
                   if any(abs(q[0] - p.pin_scene(i).x()) < 1e-6 and abs(q[1] - p.pin_scene(i).y()) < 1e-6 for i in range(len(p.defn.pins)))]
            pin_idx = {}
            for w, idx in old:
                q = w.pts[idx]
                for i in range(len(p.defn.pins)):
                    s = p.pin_scene(i)
                    if abs(q[0] - s.x()) < 1e-6 and abs(q[1] - s.y()) < 1e-6:
                        pin_idx[(id(w), idx)] = i
            if flip:
                p.mirror = not p.mirror
            else:
                p.rot = (p.rot + 1) % 4
            p.prepareGeometryChange()
            for w, idx in old:                                    # wires stay attached to the same pins
                s = p.pin_scene(pin_idx[(id(w), idx)])
                w.pts[idx] = (s.x(), s.y())
                w.pts = orthogonalize(w.pts)
                w.prepareGeometryChange()
            p.update()
        self.changed.emit()

    # ------------------------------------------------------------------ drawing the grid / wire preview / junction dots
    def drawBackground(self, p, rect):
        p.fillRect(rect, QColor("#fbfcfe"))
        p.setPen(QPen(QColor("#d5dde8"), 1.6))
        x0 = int(math.floor(rect.left() / GRID)) * GRID
        y0 = int(math.floor(rect.top() / GRID)) * GRID
        x = x0
        pts = []
        while x < rect.right():
            y = y0
            while y < rect.bottom():
                pts.append(QPointF(x, y))
                y += GRID
            x += GRID
        if len(pts) < 40000:
            p.drawPoints(pts)

    def junctions(self):
        counts = {}
        wires = self.wires()
        for w in wires:
            for idx, q in enumerate(w.pts):
                k = key(q)
                n = 1 if idx in (0, len(w.pts) - 1) else 2
                counts[k] = counts.get(k, 0) + n
        for w in wires:                                           # a wire end / pin on the side of another wire
            for q in (w.pts[0], w.pts[-1]):
                for w2 in wires:
                    if w2 is w:
                        continue
                    for a, b in zip(w2.pts, w2.pts[1:]):
                        if on_segment(q, a, b) and key(q) != key(a) and key(q) != key(b):
                            counts[key(q)] = counts.get(key(q), 0) + 2
        for part in self.parts():
            for i in range(len(part.defn.pins)):
                q = part.pin_scene(i)
                counts[key((q.x(), q.y()))] = counts.get(key((q.x(), q.y())), 0) + 1
        return [k for k, n in counts.items() if n >= 3]

    def drawForeground(self, p, rect):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(WIRE_COLOR)
        for k in self.junctions():
            p.drawEllipse(QPointF(k[0] * GRID, k[1] * GRID), 3.6, 3.6)
        if self.wiring is not None:
            p.setPen(QPen(QColor("#e76f51"), 2, Qt.PenStyle.DashLine))
            pts = self.wiring + self.elbow(self.wiring[-1], self.cursor_pt)
            for a, b in zip(pts, pts[1:]):
                p.drawLine(QPointF(*a), QPointF(*b))
        elif self.place_kind:
            p.setOpacity(0.5)
            p.save()
            p.translate(self.cursor_pt[0], self.cursor_pt[1])
            p.scale(GRID, GRID)
            P.draw_symbol(p, self.place_kind, P.default_params(self.place_kind))
            p.restore()
            p.setOpacity(1.0)
        hit = self.pin_hit(self.cursor_pt, 0.6) if (self.wiring is not None or self.wire_tool) else None
        if hit:
            p.setPen(QPen(QColor("#e76f51"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(*hit[3]), 6, 6)

    # ------------------------------------------------------------------ nets
    def connectivity(self):
        """-> (net_of_pin {(part, pin_index): net id}, net ids of the ground pins, wire -> net id). Net ids are small ints."""
        parent = {}

        def find(a):
            while parent.setdefault(a, a) != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        wires = self.wires()
        for wi, w in enumerate(wires):
            for q in w.pts:
                union(("w", wi), ("pt", key(q)))
        pins = []
        for part in self.parts():
            for i in range(len(part.defn.pins)):
                s = part.pin_scene(i)
                pt = (s.x(), s.y())
                pins.append((part, i, pt))
                union(("p", id(part), i), ("pt", key(pt)))
        # a pin or a wire end that lies on the side of a wire
        points = [(pt, ("p", id(part), i)) for part, i, pt in pins]
        for wi, w in enumerate(wires):
            points.append((w.pts[0], ("w", wi)))
            points.append((w.pts[-1], ("w", wi)))
        for wi, w in enumerate(wires):
            for a, b in zip(w.pts, w.pts[1:]):
                for pt, ident in points:
                    if ident == ("w", wi):
                        continue
                    if on_segment(pt, a, b):
                        union(ident, ("w", wi))
        roots = {}
        net_of_pin = {}
        for part, i, pt in pins:
            r = find(("p", id(part), i))
            roots.setdefault(r, len(roots) + 1)
            net_of_pin[(part, i)] = roots[r]
        wire_net = {}
        for wi, w in enumerate(wires):
            r = find(("w", wi))
            if r in roots:
                wire_net[w] = roots[r]
        gnd = {net_of_pin[(p, 0)] for p in self.parts() if p.kind == "GND"}
        for part in self.parts():                                  # the scope's GND pin is not a circuit ground by itself
            pass
        return net_of_pin, gnd, wire_net


class CircuitView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.pan = None
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.centerOn(0, 0)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and e.mimeData().text().startswith("opcirc-part:"):
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        t = e.mimeData().text()
        if t.startswith("opcirc-part:") and t[12:] in P.PARTS:
            sc = self.mapToScene(e.position().toPoint())
            self.scene().drop_part(t[12:], snap(sc.x()), snap(sc.y()))
            e.acceptProposedAction()
            self.setFocus()

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        cur = self.transform().m11()
        if 0.3 < cur * f < 5:
            self.scale(f, f)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self.pan = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.pan is not None:
            d = e.position() - self.pan
            self.pan = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self.pan = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(e)
