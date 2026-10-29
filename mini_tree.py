"""
mini_tree.py - the small see-through copy of the tree that floats in the top left of the 3D view.
It lists the same items as the big tree.  While something is being picked (a mate, a plane, a pattern...) a click on an item adds it to the
picks; otherwise a click selects the item in the big tree.  Needs from the owner window:  tree (QTreeWidget)  and  mini_pick(data) -> bool.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

WIDTH = 250


class MiniTree(QFrame):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        self.map = {}
        self.open = False
        self.expanded = {}
        self.setObjectName("minitree")
        self.setStyleSheet("#minitree{background:rgba(255,255,255,120); border:1px solid rgba(110,135,175,150); border-radius:6px;}"
                           "QTreeWidget{background:transparent; border:none; color:#1d2a44;}"
                           "QTreeWidget::item:hover{background:rgba(120,160,230,90);} QTreeWidget::item:selected{background:rgba(120,160,230,140); color:#102040;}"
                           "QToolButton{background:transparent; border:none; color:#1d2a44; font-weight:bold; padding:3px 8px; text-align:left;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        self.btn = QToolButton()
        self.btn.setToolTip("A small copy of the tree: pick planes, origins, components... here while a command asks for them")
        self.btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn.clicked.connect(self.toggle)
        lay.addWidget(self.btn)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.itemClicked.connect(self.clicked)
        self.tree.itemExpanded.connect(lambda it: self.expanded.__setitem__(self.key(it), True))
        self.tree.itemCollapsed.connect(lambda it: self.expanded.__setitem__(self.key(it), False))
        lay.addWidget(self.tree)
        self.move(8, 8)
        self.apply()

    def key(self, it):
        names, p = [], it
        while p is not None:
            names.append(p.text(0).split("(")[0].strip())
            p = p.parent()
        return tuple(names)

    def toggle(self):
        self.open = not self.open
        self.apply()

    def apply(self):
        self.btn.setText(("▾  Tree" if self.open else "▸  Tree"))
        self.tree.setVisible(self.open)
        if self.open:
            h = 30 + max(60, min(320, 22 * self.tree.model().rowCount() + 8 + 22 * 12))
            ph = self.parent().height() if self.parent() is not None else 400
            self.setFixedSize(WIDTH, max(120, min(h, ph - 20)))
        else:
            self.setFixedSize(110, 28)
        self.raise_()

    def sync(self):
        """Copy the big tree (call after it was rebuilt)."""
        self.map = {}
        self.tree.blockSignals(True)
        self.tree.clear()

        def copy(src, dst):
            for i in range(src.childCount()):
                s = src.child(i)
                if s.text(0).startswith("━"):
                    continue
                d = QTreeWidgetItem(dst, [s.text(0)])
                d.setData(0, Qt.ItemDataRole.UserRole, s.data(0, Qt.ItemDataRole.UserRole))
                d.setForeground(0, s.foreground(0))
                self.map[id(d)] = s
                copy(s, d)
                d.setExpanded(self.expanded.get(self.key(d), True))
        for i in range(self.owner.tree.topLevelItemCount()):
            s = self.owner.tree.topLevelItem(i)
            d = QTreeWidgetItem(self.tree, [s.text(0)])
            d.setData(0, Qt.ItemDataRole.UserRole, s.data(0, Qt.ItemDataRole.UserRole))
            self.map[id(d)] = s
            copy(s, d)
            d.setExpanded(self.expanded.get(self.key(d), True))
        self.tree.blockSignals(False)
        self.apply()

    def clicked(self, item, _col=0):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is not None and self.owner.mini_pick(data):
            return
        src = self.map.get(id(item))
        if src is not None:
            self.owner.tree.setCurrentItem(src)
