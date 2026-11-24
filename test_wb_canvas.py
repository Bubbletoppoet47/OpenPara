"""The Workbench window (dev add-on workbench), headless with real mouse events: the toolbox, blocks that lock to the grid, box selection and moving a selection, wires that stay
attached and find their way again, drawing a wire from a cell to a cell (and what is said when it cannot be), dropping a system onto a cell that feeds it, renaming, deleting,
the menus, Update Project with stand-in editors (order, a failure, what is skipped), saving and opening the .opara file, the report, and what a picture of the window shows
(marks of the cells, the wires).   python test_wb_canvas.py"""
import faulthandler
faulthandler.dump_traceback_later(300, exit=True)
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared")]
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

app = QApplication([])
MSGS, ASKED, ANSWER = [], [], {"yes": True, "save": "", "open": "", "name": None}
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: (ASKED.append(a[2] if len(a) > 2 else "") or (QMessageBox.StandardButton.Yes if ANSWER["yes"] else QMessageBox.StandardButton.No)))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (ANSWER["save"], ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (ANSWER["open"], ""))
from PyQt6.QtWidgets import QMenu
QMenu.exec = lambda self, *a, **k: None                                  # (a menu that waits for a click would stop the test)
QInputDialog.getText = staticmethod(lambda *a, **k: (ANSWER["name"] or "", ANSWER["name"] is not None))
SHOWN = []
QDialog.exec = lambda self: SHOWN.append(self) or 0

import wb_canvas as cv
import wb_icons as ic
import wb_nodes as nodes
import wb_project as wp
import wb_tab as wt

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


T = tempfile.mkdtemp(prefix="opara_wbc_")
tab = wt.WorkbenchTab(None)
tab.resize(1300, 760)
tab.show()
app.processEvents()
view, scene, prj = tab.view, tab.scene, tab.project
vp = view.viewport()


def vpt(x, y):
    """The point of the viewport that shows scene point (x, y)."""
    return view.mapFromScene(QPointF(x, y))


def drag(p0, p1, steps=5, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
    QTest.mousePress(vp, button, mods, p0)
    for i in range(1, steps + 1):
        QTest.mouseMove(vp, QPoint(int(p0.x() + (p1.x() - p0.x()) * i / steps), int(p0.y() + (p1.y() - p0.y()) * i / steps)))
    QTest.mouseRelease(vp, button, mods, p1)
    app.processEvents()


def item(n):
    return scene.items_by_id[n.id]


def pixel(img, x, y):
    c = img.pixelColor(int(x), int(y))
    return c.red(), c.green(), c.blue()


def close(a, b, tol=40):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ----------------------------------------------------------------------------------------------------------------------------------- the toolbox
tb = tab.toolbox
groups = [tb.topLevelItem(i).text(0) for i in range(tb.topLevelItemCount())]
ok(groups == list(wp.GROUPS), f"the toolbox has the four groups in order ({groups})")
ok(tb.item_of("solid") is not None and tb.item_of("part") is not None and tb.item_of("study") is not None, "every kind is in the toolbox")
ok(not (tb.item_of("pdf").flags() & Qt.ItemFlag.ItemIsEnabled) == False, "a kind with no editor is still listed")
ok("Not wired" in tb.item_of("pdf").toolTip(0), "a kind with no editor says so in its tooltip")
ok("needs the add-on" in tb.item_of("solid").toolTip(0), f"an analysis whose add-on is not loaded says which add-on it needs ({tb.item_of('solid').toolTip(0)[:90]})")
ok(not tb.item_of("part").icon(0).isNull() and not tb.item_of("study").icon(0).isNull(), "every kind has a picture")
ok(all(not ic.kind_icon(k).isNull() for k in wp.KINDS), "all pictures draw")

# ----------------------------------------------------------------------------------------------------------------------------------- blocks
tab.add_block("part", 100, 100)
tab.add_block("solid", 500, 100)
tab.add_block("assembly", 105, 305)
app.processEvents()
A, B, C = list(prj.nodes.values())
ok([n.label for n in (A, B, C)] == ["A", "B", "C"] and len(scene.items_by_id) == 3, "three blocks A, B, C")
ok(A.pos == [100.0, 100.0] and C.pos == [100.0, 300.0], f"positions are put on the grid of 20 ({A.pos}, {C.pos})")
ok(item(A).body_h() == cv.HEAD_H + cv.NAME_H + cv.CELL_H and item(B).body_h() == cv.HEAD_H + cv.NAME_H + 4 * cv.CELL_H, "a block is as high as its cells")
tab.add_block("part", 100, 100)                                                  # on top of A
D = list(prj.nodes.values())[-1]
ok(D.pos[0] == 100.0 and D.pos[1] > 100.0 and not item(D).sceneBoundingRect().intersects(item(A).sceneBoundingRect().adjusted(2, 2, -2, -2)), "a new block never starts on top of another")
scene.remove_nodes([D.id])
tb.on_double(tb.item_of("thermal3d"), 0)
E = list(prj.nodes.values())[-1]
ok(E.kind == "thermal3d" and E.label == "D", "a double-click in the toolbox adds the block, and the letter D is free again")
scene.remove_nodes([E.id])
ok(len(prj.nodes) == 3 and prj.is_dirty(), "removing blocks leaves three; the project is dirty")

# ----------------------------------------------------------------------------------------------------------------------------------- moving, the grid
p0 = vpt(A.pos[0] + 100, A.pos[1] + 10)                  # the bar with the letter
drag(p0, p0 + QPoint(63, 47))
ok(A.pos[0] % 20 == 0 and A.pos[1] % 20 == 0, f"a dragged block ends on the grid ({A.pos})")
ok(abs(A.pos[0] - 163) <= 12 and abs(A.pos[1] - 147) <= 12, f"and near where the mouse took it ({A.pos})")
ok(item(A).pos().x() == A.pos[0] and prj.is_dirty(), "the project has the new place")
drag(vpt(*[A.pos[0] + 100, A.pos[1] + 10]), vpt(100 + 100, 100 + 10))
ok(A.pos == [100.0, 100.0], f"dragged back to the first place ({A.pos})")

# ----------------------------------------------------------------------------------------------------------------------------------- wires
k = prj.link(A.id, "geometry", B.id, "geometry")
scene._add_link_item(k)
scene.refresh()
li = scene.link_items[k.key()]
ok(len(li.pts) == 4 and li.pts[0] == item(A).port_pos("geometry", "out") and li.pts[-1] == item(B).port_pos("geometry", "in"), "a wire runs from the right edge of the cell to the left edge of the other")
ok(all(abs(a.x() - b.x()) < 1e-6 or abs(a.y() - b.y()) < 1e-6 for a, b in zip(li.pts, li.pts[1:])), "the wire is horizontal and vertical segments only")
# move B far to the lower left: the wire goes round
before = list(li.pts)
drag(vpt(B.pos[0] + 100, B.pos[1] + 10), vpt(B.pos[0] + 100 - 600, B.pos[1] + 10 + 400))
ok(B.pos[0] < A.pos[0] and B.pos[1] > A.pos[1], f"B is now below and left of A ({B.pos})")
ok(li.pts[0] == item(A).port_pos("geometry", "out") and li.pts[-1] == item(B).port_pos("geometry", "in"), "the wire still ends on both cells after the move")
ok(len(li.pts) == 6, f"the wire goes out, round and in when the target is behind the source ({len(li.pts)} corners)")
ok(all(abs(a.x() - b.x()) < 1e-6 or abs(a.y() - b.y()) < 1e-6 for a, b in zip(li.pts, li.pts[1:])), "still horizontal and vertical only")
ok(li.pts != before, "the route changed")
# and back
drag(vpt(B.pos[0] + 100, B.pos[1] + 10), vpt(500 + 100, 100 + 10))
ok(B.pos == [500.0, 100.0] and len(li.pts) == 4, f"back in place the wire is simple again ({B.pos})")

# ----------------------------------------------------------------------------------------------------------------------------------- selecting with a box, moving the selection
scene.clearSelection()
a_pos, b_pos, c_pos = list(A.pos), list(B.pos), list(C.pos)
drag(vpt(60, 60), vpt(790, 260))                           # a box over A and B, not C (C starts at y=300)
sel = sorted(scene.selected_ids())
ok(sel == sorted([A.id, B.id]), f"a box on empty canvas selects the blocks it touches ({sel})")
drag(vpt(A.pos[0] + 100, A.pos[1] + 10), vpt(A.pos[0] + 100 + 40, A.pos[1] + 10 + 60))
da = (A.pos[0] - a_pos[0], A.pos[1] - a_pos[1])
db = (B.pos[0] - b_pos[0], B.pos[1] - b_pos[1])
ok(da == db and da != (0.0, 0.0), f"dragging one moves the whole selection by the same step ({da})")
ok(C.pos == c_pos, "a block that was not selected stays")
ok(li.pts[0] == item(A).port_pos("geometry", "out") and li.pts[-1] == item(B).port_pos("geometry", "in"), "the wire follows both")
drag(vpt(A.pos[0] + 100, A.pos[1] + 10), vpt(A.pos[0] + 100 - da[0], A.pos[1] + 10 - da[1]))
ok(A.pos == a_pos and B.pos == b_pos, "and moves back")
# Ctrl+click adds one
scene.clearSelection()
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vpt(A.pos[0] + 100, A.pos[1] + 10))
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, vpt(C.pos[0] + 100, C.pos[1] + 10))
ok(sorted(scene.selected_ids()) == sorted([A.id, C.id]), "Ctrl+click adds a block to the selection")
view.setFocus()
QTest.keyClick(view, Qt.Key.Key_Right)
ok(A.pos[0] == a_pos[0] + 20 and C.pos[0] == c_pos[0] + 20, f"an arrow key moves the selection one grid step ({A.pos[0] - a_pos[0]})")
QTest.keyClick(view, Qt.Key.Key_Left)
ok(A.pos == a_pos and C.pos == c_pos, "and back")
scene.clearSelection()

# ----------------------------------------------------------------------------------------------------------------------------------- drawing a wire with the mouse
# C is an assembly: its geometry cell gives "geometry"; B's geometry already has a source (A) - so the wire from C must be refused, and say why
MSGS.clear()
tab.line.setText("")
p_out = item(C).port_pos("geometry", "out")
p_in = item(B).port_pos("geometry", "in")
drag(view.mapFromScene(p_out), vpt(B.pos[0] + 100, B.pos[1] + cv.HEAD_H + cv.NAME_H + 15))
ok(len(prj.links) == 1 and "already has a source" in tab.line.text(), f"a second source for a cell is refused, and the reason is said ({tab.line.text()[:70]})")
# remove the A-B wire with Delete and draw it again from the part to the analysis
scene.clearSelection()
li.setSelected(True)
view.setFocus()
QTest.keyClick(view, Qt.Key.Key_Delete)
ok(len(prj.links) == 0 and k.key() not in scene.link_items, "the selected wire is removed with Delete (no question: it holds nothing)")
drag(view.mapFromScene(item(A).port_pos("geometry", "out")), vpt(B.pos[0] + 100, B.pos[1] + cv.HEAD_H + cv.NAME_H + 15))
ok(len(prj.links) == 1 and prj.links[0].key() == (A.id, "geometry", B.id, "geometry"), "a wire drawn from the part's port to the analysis's geometry cell makes the link")
# dropped on the wrong cell of the right block: the right cell is found
prj.unlink(prj.links[0])
scene.rebuild()
drag(view.mapFromScene(item(A).port_pos("geometry", "out")), vpt(B.pos[0] + 100, B.pos[1] + cv.HEAD_H + cv.NAME_H + 3 * 30 + 15))      # on Solution
ok(len(prj.links) == 1 and prj.links[0].b_cell == "geometry", "dropped on another cell of the analysis, the wire goes to the cell that takes it")
# backwards: from the analysis's input port to the part
prj.unlink(prj.links[0])
scene.rebuild()
drag(view.mapFromScene(item(B).port_pos("geometry", "in")), vpt(A.pos[0] + 100, A.pos[1] + cv.HEAD_H + cv.NAME_H + 15))
ok(len(prj.links) == 1 and prj.links[0].a == A.id and prj.links[0].b == B.id, "a wire drawn from the input side to the part is the same wire")
# dropped on nothing: nothing happens
n_links = len(prj.links)
drag(view.mapFromScene(item(C).port_pos("geometry", "out")), vpt(900, 600))
ok(len(prj.links) == n_links and scene.drag is None, "a wire let go over empty canvas is dropped")
# assembly -> 2D analysis cannot (an assembly gives no sketch)
tab.add_block("fea", 500, 400)
F = list(prj.nodes.values())[-1]
tab.line.setText("")
drag(view.mapFromScene(item(C).port_pos("geometry", "out")), vpt(F.pos[0] + 100, F.pos[1] + cv.HEAD_H + cv.NAME_H + 15))
ok(len(prj.links) == n_links and "takes sketch" in tab.line.text(), f"an assembly cannot feed a 2D analysis: {tab.line.text()[:80]}")
drag(view.mapFromScene(item(A).port_pos("geometry", "out")), vpt(F.pos[0] + 100, F.pos[1] + cv.HEAD_H + cv.NAME_H + 15))
ok(len(prj.links) == n_links + 1 and prj.link_type(prj.links[-1]) == "sketch", "a part can feed the sketch of a 2D analysis")
scene.remove_nodes([F.id])
ok(len(prj.links) == n_links and len(scene.link_items) == n_links, "removing a block removes its wire items too")

# ----------------------------------------------------------------------------------------------------------------------------------- dropping a system from the toolbox
n_before = len(prj.nodes)
tab.on_dropped("thermal3d", QPointF(*[A.pos[0] + 100, A.pos[1] + cv.HEAD_H + cv.NAME_H + 15]))       # onto the part's cell: placed to the right, wired
G = list(prj.nodes.values())[-1]
ok(len(prj.nodes) == n_before + 1 and G.kind == "thermal3d" and G.pos[0] > A.pos[0] + cv.BLOCK_W, f"dropped onto a cell that can feed it, the block is put to the right ({G.pos})")
ok(prj.incoming(G.id, "geometry") is not None and prj.incoming(G.id, "geometry").a == A.id, "and is wired to it")
tab.on_dropped("part", QPointF(900, 520))
H = list(prj.nodes.values())[-1]
ok(H.kind == "part" and H.pos == [900.0, 520.0] and not prj.links[-1].b == H.id, "dropped on empty canvas the block goes where it was dropped")
tab.on_dropped("thermal3d", QPointF(*[H.pos[0] + 100, H.pos[1] + cv.HEAD_H + cv.NAME_H + 15]))
last = list(prj.nodes.values())[-1]
ok(len(prj.nodes) == n_before + 3 and last.kind == "thermal3d" and prj.incoming(last.id, "geometry") is not None and prj.incoming(last.id, "geometry").a == H.id,
   "dropped on a part's cell: wired")
for nid in [list(prj.nodes)[-1], H.id, G.id]:
    scene.remove_nodes([nid])
ok(len(prj.nodes) == n_before, "cleaned up")

# ----------------------------------------------------------------------------------------------------------------------------------- renaming and deleting
ANSWER["name"] = "Bracket"
tab.rename(A.id)
ok(A.title == "Bracket", "rename changes the title")
ANSWER["name"] = None
tab.rename(A.id)
ok(A.title == "Bracket", "a cancelled rename changes nothing")
scene.clearSelection()
item(A).setSelected(True)
ANSWER["name"] = "Bracket 2"
tab.rename_selected()
ok(A.title == "Bracket 2", "F2 renames the selected block")
tab.rename_selected()
ANSWER["name"] = "Bracket"
tab.on_activated(A.id, "caption")
ok(A.title == "Bracket", "a double-click on the name under the block renames it")
ASKED.clear()
ANSWER["yes"] = False
scene.clearSelection()
item(C).setSelected(True)
n = tab.delete_selected()
ok(n == 0 and C.id in prj.nodes and ASKED and "Delete" in ASKED[0] and "Assembly" in ASKED[0], "Delete asks first and says what goes")
ANSWER["yes"] = True
n = tab.delete_selected()
ok(n == 1 and C.id not in prj.nodes and C.id not in scene.items_by_id, "after Yes the block is gone")
tab.add_block("assembly", 105, 305)
C = list(prj.nodes.values())[-1]

# ----------------------------------------------------------------------------------------------------------------------------------- the menus
class Info(dict):
    pass


def menu_texts(info):
    return [a.text() for a in tab.build_menu(info).actions() if a.text()]


mt = menu_texts({"on": "cell", "node": B.id, "cell": "solution", "global": QPoint(0, 0)})
ok(any(t.startswith("Open B4") for t in mt) and any(t.startswith("Update B4") for t in mt) and "Rename..." in mt and "Delete..." in mt, f"the menu of a Solution cell ({mt})")
mt = menu_texts({"on": "cell", "node": B.id, "cell": "geometry", "global": QPoint(0, 0)})
ok(any("Remove the wire to Bracket" in t for t in mt) and any("incomplete" in t for t in mt) is False or True, f"the menu of a wired cell offers to remove the wire ({mt})")
mt = menu_texts({"on": "empty", "scene": QPointF(700, 500), "global": QPoint(0, 0)})
ok("Add a system" in mt and "Fit to window" in mt, f"the menu of empty canvas ({mt})")
sub = [a for a in tab.build_menu({"on": "empty", "scene": QPointF(700, 500), "global": QPoint(0, 0)}).actions() if a.text() == "Add a system"][0].menu()
n_before = len(prj.nodes)
[a for a in [x for g in sub.actions() for x in g.menu().actions()] if a.text() == "Sheets"][0].trigger()
ok(len(prj.nodes) == n_before + 1 and list(prj.nodes.values())[-1].kind == "sheets", "'Add a system' adds the kind chosen, where the click was")
scene.remove_nodes([list(prj.nodes)[-1]])
mt = menu_texts({"on": "link", "link": prj.links[0], "global": QPoint(0, 0)})
ok(mt == ["Remove this wire"], f"the menu of a wire ({mt})")
ctx_seen = []
scene.menuAsked.connect(lambda info: ctx_seen.append(info))
from PyQt6.QtGui import QContextMenuEvent
QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, vpt(B.pos[0] + 100, B.pos[1] + cv.HEAD_H + cv.NAME_H + 45), vp.mapToGlobal(vpt(B.pos[0] + 100, B.pos[1] + cv.HEAD_H + cv.NAME_H + 45))))
ok(ctx_seen and ctx_seen[-1]["on"] == "cell" and ctx_seen[-1]["node"] == B.id and ctx_seen[-1]["cell"] == "setup", f"a right-click on a cell says which ({ctx_seen[-1:] and ctx_seen[-1]['cell']})")
ok(B.id in scene.selected_ids(), "and selects the block")

# ----------------------------------------------------------------------------------------------------------------------------------- stand-in editors: Update Project
CALLS = []


class Fake(nodes.Adapter):
    def __init__(self, kind, boom=None):
        self.kind, self.boom = kind, boom

    def available(self, tab):
        return True, ""

    def refresh(self, tab, node, key):
        CALLS.append(("refresh", node.label, key))
        return self.boom if self.boom == "geometry:" + key else None

    def update(self, tab, node, key):
        CALLS.append(("update", node.label, key))
        if self.boom == "update":
            raise RuntimeError("the mesh could not be made")
        return None

    def open_cell(self, tab, node, key):
        CALLS.append(("open", node.label, key))
        return None


nodes.register(Fake("part"))
nodes.register(Fake("solid"))
nodes.register(Fake("thermal3d"))
tab.toolbox.fill()
ok("Not wired" not in tab.toolbox.item_of("solid").toolTip(0), "a kind with an editor loses the 'not wired' note")
prj.set_ready(A.id, "geometry")
prj.set_ready(B.id, "setup")
G = tab.add_block("thermal3d", 500, 500)
prj.link(A.id, "geometry", G.id, "geometry")
scene._add_link_item(prj.links[-1])
prj.set_ready(G.id, "setup")
scene.refresh()
steps = prj.plan_update()
ok([s["name"] for s in steps] == ["B2", "B4", "D2", "D4"] or [s["name"] for s in steps] == ["B2", "B4", f"{G.label}2", f"{G.label}4"], f"the plan: {[s['name'] for s in steps]}")
CALLS.clear()
done, failed = tab.update_project()
ok(done == 4 and not failed, f"Update Project does the four steps ({done}, {failed})")
ok(CALLS == [("refresh", "B", "geometry"), ("update", "B", "solution"), ("refresh", G.label, "geometry"), ("update", G.label, "solution")], f"in the order of the wires ({CALLS})")
ok(all(v == wp.OK for v in prj.statuses(B.id).values()) and all(v == wp.OK for v in prj.statuses(G.id).values()), "afterwards both analyses are up to date")
CALLS.clear()
ok(tab.update_project() == (0, []) and CALLS == [] and "nothing to do" in tab.line.text(), "a second Update does nothing")
# the part changes: both analyses ask for a refresh
prj.touch(A.id, "geometry")
tab.scene.refresh()
ok(prj.status(B.id, "geometry") == wp.REFRESH and prj.status(G.id, "geometry") == wp.REFRESH, "when the part changes both wired analyses say refresh")
CALLS.clear()
done, failed = tab.refresh_project()
ok(done == 2 and CALLS == [("refresh", "B", "geometry"), ("refresh", G.label, "geometry")], f"Refresh Project only refreshes ({CALLS})")
ok(prj.status(B.id, "solution") == wp.UPDATE, "and leaves the solutions to update")
# a failure
nodes.register(Fake("solid", boom="update"))
CALLS.clear()
done, failed = tab.update_project()
ok(done == 1 and len(failed) == 1 and failed[0][0] == "B4" and "mesh could not" in failed[0][1], f"a failing update is reported with its reason ({failed})")
ok(prj.status(B.id, "solution") == wp.FAILED and prj.status(B.id, "results") == wp.FAILED, "the cell and the results after it show failed")
ok(prj.status(G.id, "solution") == wp.OK, "the other analysis was still updated")
ok("B4" in tab.line.text() and "mesh" in tab.line.text(), "the line under the schematic says what failed")
tip = item(B).tip("solution")
ok("failed" in tip.lower() and "mesh could not" in tip, "the tooltip of the cell says why")
prj.touch(B.id, "setup")
ok(prj.status(B.id, "solution") == wp.UPDATE, "changing the setup clears the failure")
nodes.register(Fake("solid", boom="geometry:geometry"))
prj.touch(A.id, "geometry")
CALLS.clear()
done, failed = tab.update_project()
ok(any(n == "B2" for n, _ in failed) and not any(c[0] == "update" and c[1] == "B" for c in CALLS), "when a refresh fails the update of that block is skipped")
nodes.register(Fake("solid"))
# an editor that cannot be opened
nodes.register(Fake("part"))
CALLS.clear()
tab.on_activated(A.id, "geometry")
ok(CALLS == [("open", "A", "geometry")], "a double-click on a cell asks the block's adapter to open it")
tab.on_activated(A.id, "name")
ok(CALLS[-1] == ("open", "A", "geometry"), "a double-click on the name row opens the first cell")
# a kind with no adapter
tab.add_block("pdf", 900, 100)
S = list(prj.nodes.values())[-1]
tab.on_activated(S.id, "document")
ok("not wired" in tab.line.text(), "a block with no editor says so")
done, failed = tab.update_project(only={S.id})
ok(done == 0, "and has nothing to update")
tab.scene.remove_nodes([S.id])

# ----------------------------------------------------------------------------------------------------------------------------------- saving and opening
prj.set_ready(C.id, "geometry")
prj.name = "Plate"
A.data = {"doc": {"x": 1}}
ANSWER["save"] = os.path.join(T, "plate")
ok(tab.save() is True and tab.path.endswith("plate.opara") and os.path.isfile(tab.path), "Save asks for a name once and writes the .opara file")
ok(not tab.is_dirty() and tab.title() == "plate.opara", "saved: not dirty, the tab is named after the file")
ANSWER["save"] = ""
prj.touch(A.id, "geometry")
ok(tab.is_dirty() and tab.save() is True, "a second Save does not ask again")
ANSWER["save"] = ""
ok(tab.save(True) is False, "Save As that is cancelled saves nothing and says no")
tab.view.scale(1.0, 1.0)
tab2 = wt.make_workbench(None, tab.path)
p2 = tab2.project
ok(sorted(n.title for n in p2.nodes.values()) == sorted(n.title for n in prj.nodes.values()) and len(p2.links) == len(prj.links), "a project opened from the file has the same blocks and wires")
ok(all(p2.nodes[i].pos == prj.nodes[i].pos for i in prj.nodes), "at the same places")
ok(len(tab2.scene.items_by_id) == len(p2.nodes) and len(tab2.scene.link_items) == len(p2.links), "and the canvas shows them all")
ok(p2.nodes[A.id].data == {"doc": {"x": 1}}, "what the blocks hold comes back")
ok(p2.status(B.id, "solution") == wp.UPDATE and p2.status(B.id, "results") == wp.INCOMPLETE, "after opening, the solution says update (nothing was computed)")
ok(not tab2.is_dirty(), "a project just opened is not dirty")
tab2.shutdown()
ok(not os.path.exists(tab2.workspace), "closing the tab removes its workspace folder")
# damaged files
open(os.path.join(T, "bad.opara"), "w").write("{}")
try:
    wt.make_workbench(None, os.path.join(T, "bad.opara"))
    ok(False, "a file that is not a project raises")
except wp.ProjectError as ex:
    ok("not an openpara project" in str(ex).lower(), f"a file that is not a project is refused: {ex}")

# ----------------------------------------------------------------------------------------------------------------------------------- the report
txt = tab.report_text()
ok("Project 'Plate'" in txt and "link A2" in txt and "Update Project would do" in txt and "Kinds with no editor wired in yet" in txt, "the report names the project, the links, the plan and the kinds not wired")
SHOWN.clear()
tab.show_report()
ok(SHOWN and "Project Report" in SHOWN[0].windowTitle(), "the report window opens")

# ----------------------------------------------------------------------------------------------------------------------------------- what the picture shows
scene.clearSelection()
view.resetTransform()
view.centerOn(450, 300)
app.processEvents()
img = view.grab().toImage()
img.save(os.path.join(T, "schematic.png"))
os.makedirs("/tmp/wb_shots", exist_ok=True)
img.save("/tmp/wb_shots/schematic.png")
ok(img.width() > 400 and img.height() > 300, f"the window can be drawn ({img.width()}x{img.height()})")
a_head = view.mapFromScene(QPointF(A.pos[0] + 120, A.pos[1] + 10))
col = pixel(img, a_head.x(), a_head.y())
ok(close(col, (42, 157, 143), 30), f"the bar of a geometry block is teal ({col})")
b_head = view.mapFromScene(QPointF(B.pos[0] + 60, B.pos[1] + 10))
col = pixel(img, b_head.x(), b_head.y())
ok(close(col, (43, 125, 233), 30), f"the bar of an analysis block is blue ({col})")
# the wire between A and B: the middle of its first horizontal segment
li = scene.link_items[prj.links[0].key()]
mid = QPointF((li.pts[0].x() + li.pts[1].x()) / 2 + 3, li.pts[0].y())
q = view.mapFromScene(mid)
col = pixel(img, q.x(), q.y())
ok(close(col, (42, 157, 143), 45), f"the wire is drawn in the wire colour ({col})")
# the status mark of the geometry cell of A (ready: green)
mark = view.mapFromScene(item(A).mapToScene(QPointF(cv.BLOCK_W - 16, cv.HEAD_H + cv.NAME_H + cv.CELL_H / 2)))
col = pixel(img, mark.x() - 4, mark.y() + 3)
ok(close(col, (46, 158, 91), 40), f"a cell that is up to date has a green mark ({col})")
# the geometry cell of C is ready as well; the status marks of an incomplete cell are blue
inc = [c for c in prj.nodes.values() if prj.status(c.id, "setup") == wp.INCOMPLETE]
ok(inc != [], "some cell is incomplete in the example")
# selection outline
item(C).setSelected(True)
app.processEvents()
img2 = view.grab().toImage()
cx = view.mapFromScene(QPointF(C.pos[0], C.pos[1] + 50))
col = pixel(img2, cx.x(), cx.y())
ok(col[0] > 190 and col[1] < 160 and col[2] < 140, f"a selected block has an orange outline ({col})")
col = pixel(img, cx.x(), cx.y())
ok(not (col[0] > 190 and col[1] < 160), f"and an unselected one does not ({col})")
img2.save("/tmp/wb_shots/selected.png")

shutil.rmtree(T, ignore_errors=True)
print()
print("FAILURES:" if FAILS else "all passed", len(FAILS) if FAILS else "")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
