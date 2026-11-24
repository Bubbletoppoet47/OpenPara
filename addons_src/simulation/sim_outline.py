"""
sim_outline.py - the left column of the FEA windows in the style of ANSYS Mechanical: an OUTLINE (a tree: geometry, material, mesh, supports, loads, solution) on top and the DETAILS
of the item that is selected below it.  The divider between them can be dragged, and so can the divider between the column and the view.

It replaces the long column of numbered fold-down sections (sim_ui.Section).  The sections are not rewritten: every section becomes a node of the tree and its body is what the Details
show when the node is selected, so every button, table and field of a window works as before.  Nodes appear in the order a model is built: geometry, material, mesh, what acts on the
model, then the solution.

What a window gets without doing anything: the conditions of its table (cond_table: supports, loads, thermal conditions) become rows under their node, each with a lettered colour tag
(sim_tags); the marks in front of the nodes follow what exists (geometry, mesh, conditions, result); and the view shows only what the selected node or row is about.
A window may offer (all optional, looked at a few times a second while it is shown):
    outline_items()            -> {node key: [(text, tag)]}   instead of the conditions found in cond_table; tag is a dict:  {"kind", "colour", "letter", "item", "select": callable}
    outline_marks()            -> {node key: "ok" | "update" | "incomplete"}   instead of the generic marks (ANSYS: check, lightning, question mark)
    outline_selected(key, tag) the node (and the item, or None) that is selected now
    condition_refs()           -> [(group, item)] in the order of the rows of cond_table, when the window keeps them somewhere unusual
    condition_anchor(item)     -> where the condition sits in the model's own coordinates (the tag is drawn there), or None
    view_focus(focus, item, tags)   the view of a window that is not a plain canvas (the 3D windows): what to show (see FOCUS_OF), which item, which tags
A plain canvas (window.canvas) gets .focus, .focus_item and .tag_list and is repainted.
There is no legend and no explaining text: the details are the same fields the window always had.
"""
import time

from PyQt6.QtCore import QPointF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import sim_tags

ORDER = ("geometry", "material and analysis", "fluid and flow", "domain", "joints", "ties", "mesh", "supports", "loads", "conditions", "solver", "results", "test and diagnostics")
MARK_COLOURS = {"ok": "#2e7d32", "update": "#c98a00", "incomplete": "#1c6fd1"}
KIND_COLOURS = sim_tags.KIND_COLOURS
ROW_H = 24
# what the view shows for a node: the bare part for the pages about the part itself, the mesh alone, the supports alone, the loads alone, the solution alone
FOCUS_OF = {"geometry": "geometry", "material and analysis": "geometry", "fluid and flow": "geometry", "domain": "domain", "joints": "joints", "ties": "ties", "mesh": "mesh",
            "supports": "supports", "loads": "loads", "conditions": "conditions", "solver": "results", "results": "results", "test and diagnostics": "results"}
EXPECT_SECONDS = 600


def focus_of(key):
    return FOCUS_OF.get((key or "").strip().lower(), "geometry")


def rank(section):
    """Where a section goes in the outline: the order of ORDER, a title it does not know after the known ones that come before the solution, by its old number."""
    t = (section.title or "").strip().lower()
    if t in ORDER:
        return (ORDER.index(t), 0)
    return (ORDER.index("solver") - 1, getattr(section, "number", 0))


def mark_icon(kind):
    """A 14 px picture for a mark: a green check, an amber lightning bolt or a blue question mark (drawn, so it looks the same everywhere)."""
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    if kind not in MARK_COLOURS:
        return QIcon(pm)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    col = QColor(MARK_COLOURS[kind])
    if kind == "ok":
        p.setPen(QPen(col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(2.5, 7.5), QPointF(5.8, 10.8), QPointF(11.5, 3.5)]))
    elif kind == "update":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawPolygon(QPolygonF([QPointF(8.5, 0.8), QPointF(3, 7.6), QPointF(6.6, 7.6), QPointF(5.2, 13.2), QPointF(11.2, 5.6), QPointF(7.4, 5.6)]))
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(1, 1, 12, 12)
        p.setPen(QColor("white"))
        f = QFont()
        f.setPixelSize(10)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pm.rect(), int(Qt.AlignmentFlag.AlignCenter), "?")
    p.end()
    return QIcon(pm)


def swatch_icon(colour, letter=""):
    """A small coloured square for an inserted item (its colour is the colour of its tag on the model), with the tag's letter when it has one."""
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(colour))
    p.drawRoundedRect(0, 0, 14, 14, 3, 3)
    if letter:
        p.setPen(QColor("white"))
        f = QFont()
        f.setPixelSize(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pm.rect(), int(Qt.AlignmentFlag.AlignCenter), letter[:1])
    p.end()
    return QIcon(pm)



# ------------------------------------------------------------------------------------------------------------------------------ what every window gives without code of its own
def condition_refs(w):
    """[(group, item)] in the order of the rows of the window's conditions table: the supports first, then the loads (group "Supports" / "Loads"), or all of them under
    "Conditions" for a window that keeps them in one list."""
    fn = getattr(w, "condition_refs", None)
    if callable(fn):
        return list(fn())
    st = getattr(w, "setup", None)
    sup, lds = getattr(w, "supports", None), getattr(w, "loads", None)
    if isinstance(st, dict):
        sup = st.get("supports") if sup is None else sup
        lds = st.get("loads") if lds is None else lds
    if sup is not None and lds is not None:
        return [("Supports", s_) for s_ in sup] + [("Loads", l_) for l_ in lds]
    rows = getattr(w, "cond_rows", None)
    if callable(rows) and isinstance(st, dict):
        return [("Conditions", st[k][i]) for k, i in rows()]
    return []


def node_of(group, nodes):
    """The node of the outline the conditions of `group` are listed under."""
    if group in nodes:
        return group
    if "Conditions" in nodes:
        return "Conditions"
    return None


def select_row(table, r):
    try:
        table.setCurrentCell(r, 0)
        table.selectRow(r)
    except Exception:                                    # noqa: BLE001
        pass


def condition_tags(w):
    """The conditions of the window with their letters, colours and places: [tag dict] (see sim_tags), in the order of the table.  [] when the table and the lists do not agree
    (they are being refilled)."""
    t = getattr(w, "cond_table", None)
    refs = condition_refs(w)
    if t is None or not refs or t.rowCount() != len(refs):
        return []
    anchor = getattr(w, "condition_anchor", None)
    out = []
    for r, (group, item) in enumerate(refs):
        def cell(c, r=r):
            it = t.item(r, c)
            return it.text() if it is not None else ""
        typ = cell(1)
        kind = sim_tags.kind_of(group, typ)
        try:
            at = anchor(item) if callable(anchor) else None
        except Exception:                               # noqa: BLE001 - a place that cannot be found is no place
            at = None
        out.append({"letter": sim_tags.letter(r), "name": cell(0) or f"{group} {r + 1}", "type": typ, "where": cell(2), "value": cell(3), "group": group, "kind": kind,
                    "colour": sim_tags.colour_of(kind), "item": item, "row": r, "anchor": at, "select": (lambda r=r, t=t: select_row(t, r))})
    return out


def generic_items(w, nodes):
    """{node key: [(text, tag)]} from the conditions of the table, and the local element sizes of the Mesh (3D)."""
    items = {}
    for tg in condition_tags(w):
        k = node_of(tg["group"], nodes)
        if k is not None:
            items.setdefault(k, []).append((tg["name"], tg))
    return items


def _has_geometry(w):
    if getattr(w, "geom", None) is not None:
        return True
    return bool(getattr(w, "members", None))


def generic_marks(w, nodes):
    """The mark in front of every node: a check when it is as it should be, a lightning bolt when it can be done now (mesh, solve), a question mark when something it needs is not
    there yet (no geometry, no support or load)."""
    geom = _has_geometry(w)
    refs = condition_refs(w)
    n = {}
    for g, _it in refs:
        n[g] = n.get(g, 0) + 1
    needs_mesh = hasattr(w, "b_mesh")
    mesh = (getattr(w, "mesh", None) is not None) or (getattr(w, "mesh_q", None) is not None)
    result = getattr(w, "result", None) is not None
    marks = {}
    for key in nodes:
        low = key.strip().lower()
        if low == "mesh":
            marks[key] = "ok" if (mesh or (geom and not needs_mesh)) else ("update" if geom else "incomplete")
        elif low in ("supports", "loads", "conditions"):
            have = len(refs) if low == "conditions" else n.get(key, 0)
            marks[key] = "ok" if have else "incomplete"
        elif low not in ("results", "solver"):
            marks[key] = "ok" if geom else "incomplete"
    can_solve = geom and all(marks[k] == "ok" for k in marks if k.strip().lower() in ("supports", "loads", "conditions"))
    for key in nodes:
        if key.strip().lower() in ("results", "solver"):
            marks[key] = "ok" if result else ("update" if can_solve else "incomplete")
    return marks


class Outline(QWidget):
    """Outline on top, Details below, a draggable divider between them."""
    selected = pyqtSignal(str, object)               # (node key, the tag of the item or None)

    def __init__(self, kind="sim", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.nodes = {}                              # key -> {"section", "item"}
        self.items = {}                              # parent key -> [(text, tag)] shown now
        self.marks = {}
        self.window = None
        self.current = None                          # (key, tag)
        self.tags = []                               # the lettered tags of the conditions now (see sim_tags)
        self.expect = None                           # (node key, time): a node to show as soon as it is ready (the Solve / Mesh button was pressed)
        self._auto = False                           # True while the outline selects a node itself
        self.touched = False                         # True once somebody selected a node (until then a result that turns up is shown at once)
        self._busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(6)
        lay.addWidget(self.split, 1)

        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        tl.addWidget(self._bar("Outline"))
        self.tree = QTreeWidget()
        self.tree.setObjectName("simoutline")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setIndentation(16)
        self.tree.setIconSize(QSize(14, 14))
        self.tree.setUniformRowHeights(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setStyleSheet("QTreeWidget#simoutline { background:#ffffff; border:none; outline:0; } QTreeWidget#simoutline::item { height:%dpx; padding-left:2px; } "
                                "QTreeWidget#simoutline::item:selected { background:#cfe8ea; color:#12323a; } QTreeWidget#simoutline::item:hover { background:#e8f3f4; }" % ROW_H)
        self.tree.currentItemChanged.connect(self._clicked)
        tl.addWidget(self.tree, 1)
        self.split.addWidget(top)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        self.head = self._bar("Details")
        bl.addWidget(self.head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.holder = QWidget()
        self.holder.setObjectName("simcontent")
        self.hl = QVBoxLayout(self.holder)
        self.hl.setContentsMargins(6, 6, 6, 6)
        self.hl.setSpacing(0)
        self.holder.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.scroll.setWidget(self.holder)
        bl.addWidget(self.scroll, 1)
        self.split.addWidget(bottom)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([260, 520])
        self.timer = QTimer(self)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.sync)

    @staticmethod
    def _bar(text):
        lb = QLabel(text)
        lb.setStyleSheet("background:#e4ebf2; color:#16324f; font-weight:bold; padding:4px 8px; border-top:1px solid #c9d3df; border-bottom:1px solid #c9d3df;")
        return lb

    # ------------------------------------------------------------------ the nodes
    def add_section(self, section):
        """The section becomes a node of the outline; its body is what the Details show for it."""
        key = section.title
        section.embed(lambda k=key: self.select(k))
        it = QTreeWidgetItem(self.tree, [key])
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        it.setData(0, Qt.ItemDataRole.UserRole, (key, None))
        self.nodes[key] = {"section": section, "item": it}
        section.hide()
        self.hl.addWidget(section)
        it.setExpanded(True)
        return it

    def keys(self):
        return list(self.nodes)

    def select(self, key, tag=None):
        """Selects a node (or one of its items, by tag): the Details show its page."""
        n = self.nodes.get(key)
        if n is None:
            return False
        it = n["item"]
        if tag is not None:
            for i in range(it.childCount()):
                ch = it.child(i)
                if ch.data(0, Qt.ItemDataRole.UserRole)[1] is tag:
                    it = ch
                    break
        self.tree.setCurrentItem(it)
        return True

    def _clicked(self, cur, _prev):
        if cur is None or self._busy:
            return
        key, tag = cur.data(0, Qt.ItemDataRole.UserRole)
        if not self._auto:
            self.expect = None
            self.touched = True
        self.current = (key, tag)
        for k, n in self.nodes.items():
            n["section"].setVisible(k == key)
        self.head.setText(f"Details of “{cur.text(0)}”" if tag is not None else f"Details of “{key}”")
        self.holder.adjustSize()
        if tag is not None and callable(tag.get("select")):
            try:
                tag["select"]()
            except Exception:                         # noqa: BLE001 - an item that cannot be selected must not break the panel
                pass
        self._push_view()
        self.selected.emit(key, tag)
        w = self.window
        fn = getattr(w, "outline_selected", None) if w is not None else None
        if callable(fn):
            try:
                fn(key, tag)
            except Exception:                         # noqa: BLE001
                pass

    # ------------------------------------------------------------------ what the window says
    def attach(self, window):
        """The window that offers outline_items / outline_marks / outline_selected / view_focus; they are asked for while the column is shown."""
        self.window = window
        for attr, node in (("b_solve", "Results"), ("b_mesh", "Mesh")):
            b = getattr(window, attr, None)
            if b is not None and node in self.nodes:
                b.clicked.connect(lambda _=False, n=node: self.expect_node(n))
        t = getattr(window, "cond_table", None)
        if t is not None:
            m = t.model()
            for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset, m.dataChanged):
                sig.connect(self._soon)
        self.sync()
        self.timer.start()

    def _soon(self, *_a):
        QTimer.singleShot(0, self.sync)

    def expect_node(self, key):
        """The Solve / Mesh button was pressed: the node that shows its outcome is selected as soon as it is ready."""
        if key in self.nodes:
            self.expect = (key, time.monotonic())

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.window is not None:
            self.timer.start()
            self._view_current()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.timer.stop()

    def sync(self):
        w = self.window
        if w is None:
            return
        try:
            marks = w.outline_marks() if callable(getattr(w, "outline_marks", None)) else generic_marks(w, self.nodes)
        except Exception:                              # noqa: BLE001
            marks = {}
        before = dict(self.marks)
        self.set_marks(marks or {})
        res_key = next((k for k in self.nodes if k.strip().lower() == "results"), None)
        if res_key and not self.touched and before.get(res_key) != "ok" and self.marks.get(res_key) == "ok":
            self._select_auto(res_key)                  # a solved project is opened (or its solution arrives) and nobody looked elsewhere yet: show it
        try:
            if callable(getattr(w, "outline_items", None)):
                items = w.outline_items()
            else:
                items = generic_items(w, self.nodes)
        except Exception:                              # noqa: BLE001
            items = {}
        self.set_items(items or {})
        if self.expect is not None:
            key, t0 = self.expect
            if time.monotonic() - t0 > EXPECT_SECONDS:
                self.expect = None
            elif self.marks.get(key) == "ok":
                self.expect = None
                if not (self.current and self.current[0] == key and self.current[1] is None):
                    self._select_auto(key)
        self._view_current()

    def _select_auto(self, key):
        self._auto = True
        try:
            self.select(key)
        finally:
            self._auto = False

    # ------------------------------------------------------------------ the view
    def focus(self):
        """What the view shows now: a word of FOCUS_OF, and the item (the dict of the condition) when a row is selected, else None."""
        if self.current is None:
            return None, None
        key, tag = self.current
        return focus_of(key), (tag.get("item") if tag else None)

    def visible_tags(self):
        """The tags the view draws now: those of the selected node (all of its conditions) or just the selected row; none for the nodes that are not about conditions."""
        f, item = self.focus()
        if f not in ("supports", "loads", "conditions"):
            return []
        want = {"supports": "Supports", "loads": "Loads"}.get(f)
        out = [t for t in self.tags if (want is None or t["group"] == want)]
        if item is not None:
            out = [t for t in out if t["item"] is item]
        return out

    def _push_view(self):
        """Tells the view what to show.  -> True when there was a view to tell."""
        w = self.window
        if w is None or self.current is None:
            return False
        f, item = self.focus()
        tags = self.visible_tags()
        fn = getattr(w, "view_focus", None)
        try:
            if callable(fn):
                fn(f, item, tags)
            else:
                c = getattr(w, "canvas", None)
                if c is None:
                    return False
                c.focus, c.focus_item, c.tag_list = f, item, tags
                c.update()
        except RuntimeError:                           # the window is being closed
            return False
        self._pushed = (f, id(item), tuple((t["letter"], t.get("anchor")) for t in tags))
        return True

    def _view_current(self):
        """Tells the view again when what it was told is not what it should show now (the canvas was made after the column, a condition moved)."""
        f, item = self.focus()
        tags = self.visible_tags()
        if getattr(self, "_pushed", None) != (f, id(item), tuple((t["letter"], t.get("anchor")) for t in tags)):
            self._push_view()

    def set_marks(self, marks):
        if marks == self.marks:
            return
        self.marks = dict(marks)
        for k, n in self.nodes.items():
            n["item"].setIcon(0, mark_icon(self.marks.get(k, "")))

    def set_items(self, items):
        """The items inserted under the nodes: {node key: [(text, tag)]}.  Only a change of the list rebuilds the tree, and the selection is kept."""
        def sig_of(d):
            return {k: [(t, tg.get("kind"), tg.get("letter", ""), tg.get("value", "")) for t, tg in v] for k, v in d.items() if k in self.nodes}
        new_tags = [tg for v in items.values() for _t, tg in v if "letter" in tg]
        new_tags.sort(key=lambda t: t.get("row", 0))
        sig, old = sig_of(items), sig_of(self.items)
        self.tags = new_tags
        if sig == old:
            for k, v in items.items():                 # (the callables and the items may have changed even when the texts did not)
                self.items[k] = list(v)
                n = self.nodes.get(k)
                if n is not None:
                    for i in range(min(n["item"].childCount(), len(v))):
                        n["item"].child(i).setData(0, Qt.ItemDataRole.UserRole, (k, v[i][1]))
            if self.current is not None and self.current[1] is not None:
                for _t, tg in self.items.get(self.current[0], []):
                    if tg.get("item") is self.current[1].get("item"):
                        self.current = (self.current[0], tg)
            return
        keep = self.current
        keep_idx = None
        if keep is not None and keep[1] is not None:
            for i, (t, tg) in enumerate(items.get(keep[0], [])):
                if tg.get("item") is keep[1].get("item"):
                    keep_idx = i
        self._busy = True
        try:
            for k, n in self.nodes.items():
                it = n["item"]
                it.takeChildren()
                for text, tag in items.get(k, []):
                    ch = QTreeWidgetItem(it, [text])
                    ch.setData(0, Qt.ItemDataRole.UserRole, (k, tag))
                    ch.setIcon(0, swatch_icon(tag.get("colour") or KIND_COLOURS.get(tag.get("kind"), "#8b95a8"), tag.get("letter", "")))
                    if tag.get("tip"):
                        ch.setToolTip(0, tag["tip"])
                it.setExpanded(True)
            self.items = {k: list(v) for k, v in items.items() if k in self.nodes}
        finally:
            self._busy = False
        if keep_idx is not None and keep_idx < self.nodes[keep[0]]["item"].childCount():
            self.tree.setCurrentItem(self.nodes[keep[0]]["item"].child(keep_idx))
        elif keep is not None and keep[1] is not None:
            self.tree.setCurrentItem(self.nodes[keep[0]]["item"])                 # the item is gone: its folder is selected

    def item_texts(self, key):
        n = self.nodes.get(key)
        return [n["item"].child(i).text(0) for i in range(n["item"].childCount())] if n else []
