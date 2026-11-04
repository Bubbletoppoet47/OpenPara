"""Assembly: clicking / right-clicking / dragging / double-clicking a component selects it but never switches the left panel to Properties; the
Properties tab (opened by hand) shows the selected component; the tools that need their panel still open it."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication, QLabel, QMenu
app = QApplication([])
import pm_model as pm, sk_tools as sk
import gpd_app


class playground:                       # the same tests as the Playground's, on the program window
    @staticmethod
    def Playground(_parent=None, quiet=True, first="sketch"):
        sh = gpd_app.AppShell()
        sh.new_assembly() if first == "assembly" else sh.new_part()
        return sh

tmp = tempfile.mkdtemp()


def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p


pa = make_part("base.gpd", ((0, 0), (60, 40)), 10); pb = make_part("block.gpd", ((0, 0), (10, 10)), 10)
pg = playground.Playground(None, quiet=True, first="assembly")
w = pg.tabs.currentWidget()
w.insert_files([pa, pb]); w.update_all(fit=True)
base, blk = w.asm.components
w.left.setCurrentIndex(0); w.sel_comp = None


def props_text():
    return " ".join(l.text() for l in w.findChildren(QLabel))


def tree_item(cid):
    it = [None]

    def walk(x):
        for i in range(x.childCount()):
            c = x.child(i)
            if (c.data(0, 0x100) or (None,))[:2] == ("comp", cid):
                it[0] = c
            walk(c)
    walk(w.tree.invisibleRootItem()); return it[0]


# click in the view
w.surface_hit = lambda x, y: (np.zeros(3), blk["id"], 0)
w.on_click(5, 5)
assert w.sel_comp == blk["id"] and w.left.currentIndex() == 0, "a click selects but stays on the tree tab"
assert w.tree.currentItem() is not None and w.tree.currentItem().text(0).endswith(blk["name"]) or blk["name"] in w.tree.currentItem().text(0)
# click on another component in the tree
it = tree_item(base["id"]); w.tree.setCurrentItem(it)
assert w.sel_comp == base["id"] and w.left.currentIndex() == 0, "a tree click selects but stays on the tree tab"
# double-click in the tree does nothing (no tab change, no new tab, nothing selected differently)
n = pg.tabs.count(); w.tree_double(tree_item(blk["id"]), 0)
assert w.left.currentIndex() == 0 and pg.tabs.count() == n and w.sel_comp == base["id"]
# right-click in the tree selects the component first, still no tab switch
shown = []
QMenu.exec = lambda self, *a, **k: shown.append([x.text() for x in self.actions()])
w.tree.itemAt = lambda pos: tree_item(blk["id"])
from PyQt6.QtCore import QPoint
w.tree.viewport().mapToGlobal(QPoint(0, 0))
w.tree_menu(QPoint(1, 1))
assert w.sel_comp == blk["id"] and w.left.currentIndex() == 0 and shown and any("Suppress" in t for t in shown[-1]), shown
# right-click in the view
w.sel_comp = base["id"]; w.context_menu(5, 5, QPoint(0, 0))
assert w.sel_comp == blk["id"] and w.left.currentIndex() == 0 and any("Suppress" in t for t in shown[-1])
# a left-drag selects without switching
w.sel_comp = None; w.set_mode(None, quiet=True)
st = w.drag_begin(5, 5, "move"); assert st is not None and w.sel_comp == blk["id"] and w.left.currentIndex() == 0
# opening Properties by hand shows the selected part; it follows the selection
w.left.setCurrentIndex(1); assert blk["name"] in props_text()
w.sel_comp = base["id"]; w.surface_hit = lambda x, y: (np.zeros(3), base["id"], 0); w.on_click(5, 5)
assert w.left.currentIndex() == 1 and base["name"] in props_text(), "Properties follows the selection once it is open"
# the tools that need their panel still open it
w.left.setCurrentIndex(0); w.sel_comp = blk["id"]
w.pattern_start("linear"); assert w.left.currentIndex() == 1; w.pattern_cancel(quiet=True)
w.left.setCurrentIndex(0); w.set_mode(None, quiet=True)
print("OK asm click select")
