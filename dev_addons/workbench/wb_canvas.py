"""wb_canvas.py - the PROJECT SCHEMATIC: the blocks (systems) of a project on a canvas, and the wires between their cells.

It behaves like the Circuits tab: blocks go anywhere and lock to a grid of 20; click and drag on empty canvas to draw a box that selects every block it touches (Ctrl+click
adds one), and a selection moves as one; a wire stays on its two cells and finds its way again when a block is moved far away.  A block looks like a system of ANSYS
Workbench: a bar with its letter, the name of the system, then its cells in rows (picture, name, and the mark that says whether the cell is up to date), and its own name
under it.  The pictures are drawn here in OpenPara's colours.

The canvas never changes the data of a node: it changes the Project (wb_project) - the places of the blocks, their names, the nodes that are added or removed, the links - and
tells the window above it through signals (cell double-clicked, menu asked, message, edited).
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPainterPathStroker, QPen
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView

import wb_icons as ic
import wb_project as wp

GRID = 20.0
BLOCK_W = 200.0
HEAD_H = 20.0
NAME_H = 40.0
CELL_H = 30.0
CAP_H = 26.0
GUTTER = 18.0
PORT_R = 4.5
PORT_HIT = 10.0
MIME = "opara-wb-kind:"
WIRE = QColor("#2a9d8f")
SELECTED = QColor("#e76f51")
BG = QColor("#fbfcfe")
DOT = QColor("#d5dde8")


def snap(v):
    return round(v / GRID) * GRID


def _font(px, bold=False):
    f = QFont()
    f.setPixelSize(px)
    f.setBold(bold)
    return f


# ---------------------------------------------------------------------------------------------------------------------------- a block
class SystemItem(QGraphicsItem):
    def __init__(self, nid):
        super().__init__()
        self.nid = nid
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self.hover = None                                   # the key of the cell under the mouse, "name" or "caption"
        self.links = []                                     # the LinkItems on this block
        self._linking = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ---- the shape
    def node(self):
        return self.scene().project.nodes[self.nid]

    def cells(self):
        sp = self.node().spec
        return list(sp.cells) if sp else []

    def body_h(self):
        return HEAD_H + NAME_H + max(1, len(self.cells())) * CELL_H

    def boundingRect(self):
        return QRectF(-PORT_R - 4, -4, BLOCK_W + 2 * PORT_R + 8, self.body_h() + CAP_H + 12)

    def shape(self):
        """What a click lands on: the body, the name under it, and each wire dot as it is drawn - whole, so the half of a dot that sticks out of the body is the dot's
        and not the wire's that arrives under it (a block is above its wires)."""
        p = QPainterPath()
        p.addRect(QRectF(0, 0, BLOCK_W, self.body_h()))
        p.addRect(QRectF(0, self.body_h(), BLOCK_W, CAP_H + 4))
        r = PORT_R + 1.0                                    # the dot and its outline: no bigger than it looks
        for i, c in enumerate(self.cells()):
            cy = self.cell_y(i) + CELL_H / 2
            if c.provides:
                p.addEllipse(QPointF(BLOCK_W, cy), r, r)
            if c.accepts:
                p.addEllipse(QPointF(0, cy), r, r)
        return p

    def cell_y(self, i):
        return HEAD_H + NAME_H + i * CELL_H

    def port_pos(self, key, side):
        """Where a wire meets the cell `key` (scene coordinates): side "out" on the right edge, "in" on the left edge."""
        i = next((j for j, c in enumerate(self.cells()) if c.key == key), 0)
        return self.mapToScene(QPointF(BLOCK_W if side == "out" else 0.0, self.cell_y(i) + CELL_H / 2))

    def where(self, pos):
        """What a point (item coordinates) is on: a cell key, "head", "name", "caption", or None."""
        x, y = pos.x(), pos.y()
        if x < -PORT_HIT / 2 or x > BLOCK_W + PORT_HIT / 2:
            return None
        if y < 0:
            return None
        if y < HEAD_H:
            return "head"
        if y < HEAD_H + NAME_H:
            return "name"
        i = int((y - HEAD_H - NAME_H) // CELL_H)
        cs = self.cells()
        if 0 <= i < len(cs):
            return cs[i].key
        if self.body_h() <= y <= self.body_h() + CAP_H + 4:
            return "caption"
        return None

    def port_at(self, pos):
        """(cell key, "out" | "in") when the point is on a wire port of a cell that has one, else None."""
        for i, c in enumerate(self.cells()):
            cy = self.cell_y(i) + CELL_H / 2
            if c.provides and math.hypot(pos.x() - BLOCK_W, pos.y() - cy) <= PORT_HIT:
                return c.key, "out"
            if c.accepts and math.hypot(pos.x(), pos.y() - cy) <= PORT_HIT:
                return c.key, "in"
        return None

    # ---- the look
    def paint(self, p, opt, widget=None):
        sc = self.scene()
        prj = sc.project
        node = prj.nodes[self.nid]
        sp = node.spec
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        H = self.body_h()
        body = QRectF(0, 0, BLOCK_W, H)
        sel = self.isSelected()
        grp = ic.GROUP_COLOR.get(sp.group, ic.GREY) if sp else ic.GREY
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 40, 80, 30))
        p.drawRoundedRect(body.translated(3, 4), 7, 7)
        clip = QPainterPath()
        clip.addRoundedRect(body, 7, 7)
        p.save()
        p.setClipPath(clip)
        p.fillRect(body, QColor("#ffffff"))
        p.fillRect(QRectF(0, 0, BLOCK_W, HEAD_H), grp)                                           # the bar with the letter
        p.fillRect(QRectF(0, HEAD_H, GUTTER, H - HEAD_H), QColor("#eef2f9"))                    # the numbers of the rows
        p.restore()
        p.setPen(QColor("#ffffff"))
        p.setFont(_font(13, True))
        p.drawText(QRectF(8, 0, 40, HEAD_H), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), node.label)
        p.setFont(_font(10))
        p.setPen(QColor(255, 255, 255, 215))
        p.drawText(QRectF(40, 0, BLOCK_W - 48, HEAD_H), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), sp.group if sp else "")
        # the name of the system
        top = HEAD_H
        p.setPen(QColor("#6a7790"))
        p.setFont(_font(10))
        p.drawText(QRectF(0, top, GUTTER, NAME_H), int(Qt.AlignmentFlag.AlignCenter), "1")
        if self.hover == "name":
            p.fillRect(QRectF(GUTTER, top, BLOCK_W - GUTTER, NAME_H), QColor("#e6efff"))
        ic.paint_kind(p, node.kind, QRectF(GUTTER + 8, top + 6, 28, 28))
        p.setPen(QColor("#12223f"))
        p.setFont(_font(12, True))
        label = sp.label if sp else f"Unknown: {node.kind}"
        p.drawText(QRectF(GUTTER + 44, top, BLOCK_W - GUTTER - 50, NAME_H), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   QFontMetrics(_font(12, True)).elidedText(label, Qt.TextElideMode.ElideRight, int(BLOCK_W - GUTTER - 52)))
        # the cells
        sts = prj.statuses(self.nid)
        for i, c in enumerate(self.cells()):
            y = self.cell_y(i)
            p.setPen(QPen(QColor("#dfe6f1"), 1))
            p.drawLine(QPointF(0, y), QPointF(BLOCK_W, y))
            bg = QColor("#e6efff") if self.hover == c.key else (QColor("#f4f8fe") if i % 2 else QColor("#ffffff"))
            p.fillRect(QRectF(GUTTER, y + 0.5, BLOCK_W - GUTTER, CELL_H - 0.5), bg)
            p.setPen(QColor("#6a7790"))
            p.setFont(_font(10))
            p.drawText(QRectF(0, y, GUTTER, CELL_H), int(Qt.AlignmentFlag.AlignCenter), str(i + 2))
            ic.paint_cell(p, c.key, QRectF(GUTTER + 8, y + 6, 18, 18))
            p.setPen(QColor("#1f2a3c"))
            p.setFont(_font(12))
            p.drawText(QRectF(GUTTER + 34, y, BLOCK_W - GUTTER - 64, CELL_H), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), c.label)
            ic.paint_status(p, sts.get(c.key, wp.INCOMPLETE), QPointF(BLOCK_W - 16, y + CELL_H / 2), 8.0)
        if sp is None:
            p.setPen(QColor("#6a7790"))
            p.setFont(_font(11))
            p.drawText(QRectF(GUTTER + 8, self.cell_y(0), BLOCK_W - GUTTER - 16, CELL_H), int(Qt.AlignmentFlag.AlignVCenter), "This program cannot open it")
        # the outline
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(ic.ORANGE if sel else QColor("#8fa3c4"), 2.4 if sel else 1.4))
        p.drawRoundedRect(body, 7, 7)
        # the wire ports
        drag = sc.drag
        for i, c in enumerate(self.cells()):
            cy = self.cell_y(i) + CELL_H / 2
            for side, kinds in (("out", c.provides), ("in", c.accepts)):
                if not kinds:
                    continue
                used = (prj.outgoing(self.nid, c.key) if side == "out" else [prj.incoming(self.nid, c.key)])
                used = [u for u in used if u is not None]
                hot = drag is not None and drag.get("targets") and (self.nid, c.key, side) in drag["targets"]
                p.setBrush(QBrush(WIRE if used else QColor("#ffffff")))
                p.setPen(QPen(ic.ORANGE if hot else WIRE, 2.4 if hot else 1.5))
                p.drawEllipse(QPointF(BLOCK_W if side == "out" else 0, cy), PORT_R + (1.5 if hot else 0), PORT_R + (1.5 if hot else 0))
        # the name under the block
        p.setPen(QColor("#1d3557"))
        p.setFont(_font(12, True))
        p.drawText(QRectF(0, H + 4, BLOCK_W, CAP_H - 4), int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                   QFontMetrics(_font(12, True)).elidedText(node.title, Qt.TextElideMode.ElideMiddle, int(BLOCK_W - 6)))

    # ---- the mouse
    def hoverMoveEvent(self, ev):
        w = self.where(ev.pos())
        if w != self.hover:
            self.hover = w
            self.update()
        self.setToolTip(self.tip(w))
        super().hoverMoveEvent(ev)

    def hoverLeaveEvent(self, ev):
        if self.hover is not None:
            self.hover = None
            self.update()
        super().hoverLeaveEvent(ev)

    def tip(self, w):
        prj = self.scene().project
        node = prj.nodes[self.nid]
        sp = node.spec
        if sp is None:
            return f"'{node.title}' is a kind of node this program does not know ({node.kind}). It is kept in the file as it is."
        if w in ("name", "head"):
            return f"{node.label}: {sp.label}\n{sp.tip}" if sp.tip else f"{node.label}: {sp.label}"
        if w == "caption":
            return "The name of this system. Double-click or press F2 to change it."
        cs = sp.cell(w) if w else None
        if cs is None:
            return ""
        st = prj.status(self.nid, w)
        t = f"{node.cell_name(w)}  {cs.label}\n{wp.STATUS_TEXT[st]}"
        k = prj.incoming(self.nid, w)
        if k is not None:
            src = prj.nodes[k.a]
            t += f"\nTakes the {prj.link_type(k)} of {src.cell_name(k.a_cell)} ({src.title})"
        n = len(prj.outgoing(self.nid, w))
        if n:
            t += f"\nFeeds {n} other cell{'s' if n != 1 else ''}"
        if st == wp.INCOMPLETE:
            t += "\n" + prj.why_incomplete(self.nid, w)
        if st == wp.FAILED:
            t += "\n" + prj.cell(self.nid, w)["failed"]
        return t

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            port = self.port_at(ev.pos())
            if port is not None:
                self._linking = True
                self.scene().begin_link(self, port[0], port[1], ev.scenePos())
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._linking:
            self.scene().drag_link(ev.scenePos())
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._linking:
            self._linking = False
            self.scene().end_link(ev.scenePos())
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        w = self.where(ev.pos())
        if w is not None:
            self.scene().activated.emit(self.nid, w)
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def itemChange(self, change, value):
        sc = self.scene()
        if sc is not None and change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QPointF(snap(value.x()), snap(value.y()))
        if sc is not None and change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for l in self.links:
                l.update_path()
            sc.item_moved(self)
        return super().itemChange(change, value)


# ---------------------------------------------------------------------------------------------------------------------------- a wire
def route(p0, p1, a_bottom, b_bottom):
    """The corners of a wire from the right edge of a cell (p0) to the left edge of another (p1): straight across with one bend when the target is to the right, else
    out, down under both blocks, back and in.  Always horizontal and vertical segments."""
    x0, y0, x1, y1 = p0.x(), p0.y(), p1.x(), p1.y()
    if x1 >= x0 + 2 * GRID:
        xm = min(max(snap((x0 + x1) / 2), x0 + GRID / 2), x1 - GRID / 2)
        return [QPointF(x0, y0), QPointF(xm, y0), QPointF(xm, y1), QPointF(x1, y1)]
    ym = snap(max(a_bottom, b_bottom) + 2 * GRID) if abs(y0 - y1) < 2 * CELL_H else (y0 + y1) / 2
    return [QPointF(x0, y0), QPointF(x0 + GRID, y0), QPointF(x0 + GRID, ym), QPointF(x1 - GRID, ym), QPointF(x1 - GRID, y1), QPointF(x1, y1)]


class LinkItem(QGraphicsPathItem):
    def __init__(self, link, a_item, b_item):
        super().__init__()
        self.link, self.a_item, self.b_item = link, a_item, b_item
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setZValue(0)
        a_item.links.append(self)
        b_item.links.append(self)
        self.pts = []
        self.update_path()

    def detach(self):
        for it in (self.a_item, self.b_item):
            if self in it.links:
                it.links.remove(self)

    def update_path(self):
        p0 = self.a_item.port_pos(self.link.a_cell, "out")
        p1 = self.b_item.port_pos(self.link.b_cell, "in")
        self.pts = route(p0, p1, self.a_item.pos().y() + self.a_item.body_h(), self.b_item.pos().y() + self.b_item.body_h())
        path = QPainterPath(self.pts[0])
        for q in self.pts[1:]:
            path.lineTo(q)
        self.prepareGeometryChange()
        self.setPath(path)

    def shape(self):
        st = QPainterPathStroker()
        st.setWidth(12)
        return st.createStroke(self.path())

    def boundingRect(self):
        return self.shape().boundingRect().adjusted(-8, -8, 8, 8)

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = SELECTED if self.isSelected() else WIRE
        p.setPen(QPen(col, 3.0 if self.isSelected() else 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self.path())                              # just a wire: no arrowhead (the dots at its ends are drawn by the blocks, above it)

    def hoverMoveEvent(self, ev):
        prj = self.scene().project
        k = self.link
        na, nb = prj.nodes[k.a], prj.nodes[k.b]
        self.setToolTip(f"{na.cell_name(k.a_cell)} ({na.title}) -> {nb.cell_name(k.b_cell)} ({nb.title}): the {prj.link_type(k)}\nSelect it and press Delete to remove it.")
        super().hoverMoveEvent(ev)


# ---------------------------------------------------------------------------------------------------------------------------- the scene
class SchematicScene(QGraphicsScene):
    activated = pyqtSignal(str, str)           # a block was double-clicked: node id, the cell key (or "name" / "head" / "caption")
    menuAsked = pyqtSignal(object)             # the context menu was asked: {"on": "cell"|"node"|"link"|"empty", "node", "cell", "link", "global": QPoint, "scene": QPointF}
    message = pyqtSignal(str)                  # a short sentence for the status line
    edited = pyqtSignal()                      # the project changed through the canvas (a block moved, a wire made ...)

    def __init__(self, project):
        super().__init__()
        self.project = project
        self.items_by_id = {}
        self.link_items = {}
        self.drag = None                                    # a wire being drawn
        self._building = False
        self.setSceneRect(QRectF(-1000, -800, 4000, 3000))
        self.rebuild()

    # ---- building
    def rebuild(self):
        """Draws the whole project again (after it was opened)."""
        self._building = True
        try:
            self.clear()
            self.items_by_id, self.link_items = {}, {}
            for n in self.project.nodes.values():
                self._add_item(n)
            for k in self.project.links:
                self._add_link_item(k)
        finally:
            self._building = False
        self.fit_rect()

    def _add_item(self, node):
        it = SystemItem(node.id)
        self.addItem(it)
        self.items_by_id[node.id] = it
        was = self._building
        self._building = True
        it.setPos(QPointF(node.pos[0], node.pos[1]))
        self._building = was
        return it

    def _add_link_item(self, k):
        a, b = self.items_by_id.get(k.a), self.items_by_id.get(k.b)
        if a is None or b is None or a.node().spec is None or b.node().spec is None:
            return None
        li = LinkItem(k, a, b)
        self.addItem(li)
        self.link_items[k.key()] = li
        return li

    def fit_rect(self):
        r = self.itemsBoundingRect()
        base = QRectF(-1000, -800, 4000, 3000)
        self.setSceneRect(base.united(r.adjusted(-600, -500, 600, 500)))

    def refresh(self):
        """The marks of the cells follow the project (call after anything that changes a status)."""
        for it in self.items_by_id.values():
            it.update()
        self.update()

    # ---- what changes the project
    def item_moved(self, item):
        if self._building:
            return
        self.project.move_node(item.nid, item.pos().x(), item.pos().y())
        self.fit_rect()
        self.edited.emit()

    def free_pos(self, x, y, kind=None):
        """The nearest free place at or below (x, y) for a new block (blocks never start on top of each other)."""
        sp = wp.spec_of(kind) if kind else None
        h = HEAD_H + NAME_H + CELL_H * max(1, len(sp.cells) if sp else 1) + CAP_H
        x, y = snap(x), snap(y)
        for _ in range(400):
            r = QRectF(x - 8, y - 8, BLOCK_W + 16, h + 16)
            if not any(r.intersects(QRectF(it.pos().x(), it.pos().y(), BLOCK_W, it.body_h() + CAP_H)) for it in self.items_by_id.values()):
                break
            y += GRID
        return x, y

    def add_node(self, kind, x=None, y=None, title=None, data=None, select=True):
        if x is None:
            x, y = self.project.free_spot()
        x, y = self.free_pos(x, y, kind)
        n = self.project.add_node(kind, title, (x, y), data)
        it = self._add_item(n)
        if select:
            self.clearSelection()
            it.setSelected(True)
        self.fit_rect()
        self.edited.emit()
        return n

    def remove_nodes(self, ids):
        for nid in list(ids):
            it = self.items_by_id.pop(nid, None)
            if it is None:
                continue
            for li in list(it.links):
                self._drop_link_item(li)
            self.removeItem(it)
            self.project.remove_node(nid)
        self.edited.emit()
        self.refresh()

    def _drop_link_item(self, li):
        li.detach()
        self.link_items.pop(li.link.key(), None)
        self.removeItem(li)

    def make_link(self, a, a_cell, b, b_cell):
        """Links two cells; the reason is said (message) when it cannot be done.  -> the Link or None."""
        try:
            k = self.project.link(a, a_cell, b, b_cell)
        except wp.ProjectError as ex:
            self.message.emit(str(ex))
            return None
        self._add_link_item(k)
        self.edited.emit()
        self.refresh()
        return k

    def remove_link(self, k):
        li = self.link_items.get(k.key())
        if li is not None:
            self._drop_link_item(li)
        self.project.unlink(k)
        self.edited.emit()
        self.refresh()

    def selected_ids(self):
        return [it.nid for it in self.selectedItems() if isinstance(it, SystemItem)]

    def selected_links(self):
        return [it.link for it in self.selectedItems() if isinstance(it, LinkItem)]

    def compatible_cell(self, nid, provides, side="in"):
        """The first free cell of a node that can take one of the data kinds (side "in"), or give one (side "out"); None when there is none."""
        n = self.project.nodes.get(nid)
        if n is None or n.spec is None:
            return None
        for c in n.spec.cells:
            if side == "in" and set(c.accepts) & set(provides) and self.project.incoming(nid, c.key) is None:
                return c.key
            if side == "out" and set(c.provides) & set(provides):
                return c.key
        return None

    # ---- drawing a wire with the mouse
    def begin_link(self, item, key, side, pos):
        n = item.node()
        c = n.spec.cell(key)
        kinds = c.provides if side == "out" else c.accepts
        targets = set()
        for nid, other in self.items_by_id.items():
            if nid == item.nid or other.node().spec is None:
                continue
            for oc in other.node().spec.cells:
                a, ac, b, bc = (item.nid, key, nid, oc.key) if side == "out" else (nid, oc.key, item.nid, key)
                if self.project.why_not_link(a, ac, b, bc) is None:
                    targets.add((nid, oc.key, "in" if side == "out" else "out"))
        self.drag = {"item": item, "key": key, "side": side, "from": item.port_pos(key, side), "to": pos, "kinds": kinds, "targets": targets, "path": QPainterPath()}
        self.clearSelection()
        self.update()

    def drag_link(self, pos):
        if self.drag is not None:
            self.drag["to"] = pos
            self.update()

    def end_link(self, pos):
        d, self.drag = self.drag, None
        self.update()
        if d is None:
            return None
        for it in self.items(pos):
            if isinstance(it, SystemItem) and it is not d["item"]:
                w = it.where(it.mapFromScene(pos))
                cs = it.node().spec.cell(w) if it.node().spec and w else None
                other = w if cs is not None else None
                if other is None or not self._can_end(d, it, other):
                    other = self.compatible_cell(it.nid, d["kinds"], "in" if d["side"] == "out" else "out") if it.node().spec else None
                if other is None:
                    self.message.emit(self.why_not(d, it, w))
                    return None
                a, ac, b, bc = (d["item"].nid, d["key"], it.nid, other) if d["side"] == "out" else (it.nid, other, d["item"].nid, d["key"])
                return self.make_link(a, ac, b, bc)
        return None

    def _can_end(self, d, it, key):
        a, ac, b, bc = (d["item"].nid, d["key"], it.nid, key) if d["side"] == "out" else (it.nid, key, d["item"].nid, d["key"])
        return self.project.why_not_link(a, ac, b, bc) is None

    def why_not(self, d, it, w):
        key = w if w and it.node().spec and it.node().spec.cell(w) else (it.node().spec.cells[0].key if it.node().spec and it.node().spec.cells else "")
        a, ac, b, bc = (d["item"].nid, d["key"], it.nid, key) if d["side"] == "out" else (it.nid, key, d["item"].nid, d["key"])
        return self.project.why_not_link(a, ac, b, bc) or "That link cannot be made."

    # ---- the menu
    def contextMenuEvent(self, ev):
        info = {"global": ev.screenPos(), "scene": ev.scenePos(), "on": "empty", "node": None, "cell": None, "link": None}
        for it in self.items(ev.scenePos()):
            if isinstance(it, SystemItem):
                w = it.where(it.mapFromScene(ev.scenePos()))
                info.update(on="cell" if (w and it.node().spec and it.node().spec.cell(w)) else "node", node=it.nid, cell=w)
                if not it.isSelected():
                    self.clearSelection()
                    it.setSelected(True)
                break
            if isinstance(it, LinkItem):
                info.update(on="link", link=it.link)
                self.clearSelection()
                it.setSelected(True)
                break
        self.menuAsked.emit(info)
        ev.accept()

    # ---- the background and the wire being drawn
    def drawBackground(self, p, rect):
        p.fillRect(rect, BG)
        p.setPen(QPen(DOT, 1.6))
        x0 = int(math.floor(rect.left() / GRID)) * GRID
        y0 = int(math.floor(rect.top() / GRID)) * GRID
        pts = []
        x = x0
        while x < rect.right():
            y = y0
            while y < rect.bottom():
                pts.append(QPointF(x, y))
                y += GRID
            x += GRID
        if len(pts) < 40000:
            p.drawPoints(pts)

    def drawForeground(self, p, rect):
        d = self.drag
        if d is None:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        a, b = d["from"], d["to"]
        path = QPainterPath(a)
        mx = (a.x() + b.x()) / 2
        path.lineTo(QPointF(mx, a.y()))
        path.lineTo(QPointF(mx, b.y()))
        path.lineTo(b)
        p.setPen(QPen(ic.ORANGE, 2.2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


# ---------------------------------------------------------------------------------------------------------------------------- the view
class SchematicView(QGraphicsView):
    dropped = pyqtSignal(str, QPointF)         # a kind of node was dropped from the toolbox: kind, scene point
    deleteAsked = pyqtSignal()                 # Delete was pressed
    renameAsked = pyqtSignal()                 # F2 was pressed

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemShape)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.pan = None
        self.centerOn(300, 150)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and e.mimeData().text().startswith(MIME):
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        t = e.mimeData().text()
        if t.startswith(MIME):
            self.dropped.emit(t[len(MIME):], self.mapToScene(e.position().toPoint()))
            e.acceptProposedAction()
            self.setFocus()

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        if 0.25 < self.transform().m11() * f < 3:
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

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.deleteAsked.emit()
            return
        if e.key() == Qt.Key.Key_F2:
            self.renameAsked.emit()
            return
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) and self.scene().selectedItems():
            dx = {Qt.Key.Key_Left: -GRID, Qt.Key.Key_Right: GRID}.get(e.key(), 0.0)
            dy = {Qt.Key.Key_Up: -GRID, Qt.Key.Key_Down: GRID}.get(e.key(), 0.0)
            for it in self.scene().selectedItems():
                if isinstance(it, SystemItem):
                    it.setPos(it.pos() + QPointF(dx, dy))
            return
        super().keyPressEvent(e)

    def fit_all(self):
        r = self.scene().itemsBoundingRect()
        if r.isEmpty():
            self.resetTransform()
            self.centerOn(300, 150)
            return
        self.fitInView(r.adjusted(-40, -40, 40, 40), Qt.AspectRatioMode.KeepAspectRatio)
        if self.transform().m11() > 1.0:
            self.resetTransform()
            self.centerOn(r.center())
