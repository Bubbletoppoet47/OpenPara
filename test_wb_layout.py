"""The layout rules of the Workbench canvas (dev add-on workbench), headless with real mouse events: two blocks never overlap and always keep the gap between them (a block that is
dragged stops at its neighbour and slides along it, a whole selection too, the arrow keys the same, a new block goes to the nearest free place), a file made before the rule is
moved apart when it is opened, and the wires never pass behind a block: they run on horizontal and vertical pieces only and find their way round - a property test on random layouts
(wb_route.py) and the picture of the canvas itself.   python test_wb_layout.py"""
import faulthandler
faulthandler.dump_traceback_later(300, exit=True)
import os
import random
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared")]
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QMenu

app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMenu.exec = lambda self, *a, **k: None
QDialog.exec = lambda self: 0

import wb_canvas as cv
import wb_project as wp
import wb_route as wr
import wb_tab as wt

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


T = tempfile.mkdtemp(prefix="opara_wbl_")

# ----------------------------------------------------------------------------------------------------------------------------------- the router, alone
R0 = [(100, 100, 300, 216), (500, 100, 700, 306)]              # two blocks, 200 apart
p0, p1 = (300.0, 175.0), (500.0, 175.0)
road = wr.route(p0, p1, R0)
ok(road == [p0, p1], f"between two blocks in a free row the wire is straight ({road})")
road = wr.route((300.0, 175.0), (500.0, 250.0), R0)
ok(road is not None and road[0] == (300.0, 175.0) and road[-1] == (500.0, 250.0) and wr.crossings(road, R0) == [], f"a wire to another height has corners and crosses nothing ({road})")
ok(all(abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9 for a, b in zip(road, road[1:])), "its pieces are horizontal or vertical")

# a block in the way: the straight line would go through the middle one
R1 = [(100, 100, 300, 216), (360, 100, 540, 216), (600, 100, 800, 216)]
road = wr.route((300.0, 175.0), (600.0, 175.0), R1)
ok(road is not None and wr.crossings(road, R1) == [], f"a block in the way: the wire goes round it ({road})")
ok(any(y < 100 or y > 216 for _x, y in road), "round: over or under the block in the middle")
ok(len(road) <= 6, f"with the fewest corners it can ({len(road)} points)")
# the wire keeps its distance (half the gap) from the block it passes
ys = [y for _x, y in road]
ok(min(abs(y - 100) for y in ys if y < 100) >= wr.CLEAR - 1e-6 if any(y < 100 for y in ys) else min(abs(y - 216) for y in ys if y > 216) >= wr.CLEAR - 1e-6, "and it runs in the channel, not along the edge")

# a target to the left of the source
R2 = [(300, 100, 500, 216), (100, 100, 200, 216)]
road = wr.route((500.0, 175.0), (100.0, 175.0), R2)
ok(road is not None and wr.crossings(road, R2) == [] and road[0] == (500.0, 175.0) and road[-1] == (100.0, 175.0), f"a target behind the source: out, round and in ({len(road)} points)")
# two blocks on top of each other: the router has no road and says so
ok(wr.route((300.0, 175.0), (500.0, 175.0), [(100, 100, 300, 216), (280, 150, 700, 300)]) is None, "ports inside the keep-out area of another block: no road (the plain route is drawn instead)")
# simplify
ok(wr.simplify([(0, 0), (10, 0), (20, 0), (20, 10), (20, 10)]) == [(0, 0), (20, 0), (20, 10)], "simplify keeps the corners only")

# the property test: random blocks that keep the gap, random ports on them, a wire from each right edge to each left edge of another block
rnd = random.Random(7)
n_paths = n_fail = n_none = 0
bad = []
for trial in range(60):
    rects = []
    for _ in range(rnd.randint(2, 9)):
        for _try in range(60):
            x, y, h = rnd.randrange(0, 1400, 20), rnd.randrange(0, 900, 20), rnd.choice([116, 146, 176, 206, 236])
            r = (x, y, x + 200, y + h)
            if all(r[0] >= o[2] + wr.GAP - 1e-6 or r[2] <= o[0] - wr.GAP + 1e-6 or r[1] >= o[3] + wr.GAP - 1e-6 or r[3] <= o[1] - wr.GAP + 1e-6 for o in rects):
                rects.append(r)
                break
    for a in rects:
        for b in rects:
            if a is b:
                continue
            q0 = (a[2], a[1] + rnd.choice([75, 105, 135]))
            q1 = (b[0], b[1] + rnd.choice([75, 105, 135]))
            if q0[1] > a[3] or q1[1] > b[3]:
                continue
            road = wr.route(q0, q1, rects)
            n_paths += 1
            if road is None:
                n_none += 1
                continue
            hv = all(abs(u[0] - v[0]) < 1e-6 or abs(u[1] - v[1]) < 1e-6 for u, v in zip(road, road[1:]))
            if not (hv and road[0] == q0 and road[-1] == q1 and wr.crossings(road, rects) == []):
                n_fail += 1
                bad.append((rects, q0, q1, road))
ok(n_paths > 300 and n_fail == 0 and n_none == 0, f"{n_paths} wires on random layouts: every one starts and ends on its ports, is horizontal and vertical only and crosses no block ({n_fail} bad, {n_none} without a road)")

# ----------------------------------------------------------------------------------------------------------------------------------- the canvas
tab = wt.WorkbenchTab(None)
tab.resize(1300, 800)
tab.show()
app.processEvents()
view, scene, prj = tab.view, tab.scene, tab.project
vp = view.viewport()


def vpt(x, y):
    return view.mapFromScene(QPointF(x, y))


def drag(p0, p1, steps=8, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
    QTest.mousePress(vp, button, mods, p0)
    for i in range(1, steps + 1):
        QTest.mouseMove(vp, QPoint(int(p0.x() + (p1.x() - p0.x()) * i / steps), int(p0.y() + (p1.y() - p0.y()) * i / steps)))
    QTest.mouseRelease(vp, button, mods, p1)
    app.processEvents()


def item(n):
    return scene.items_by_id[n.id]


def head(n):
    """The scene point on the bar of a block (to take it with the mouse)."""
    return (n.pos[0] + 100, n.pos[1] + 10)


def all_clear():
    its = list(scene.items_by_id.values())
    for i, a in enumerate(its):
        for b in its[i + 1:]:
            if not cv.clear_of(a.keep(), [b.keep()]):
                return False
    return True


def gap_between(a, b):
    """The distance between the keep-out areas of two blocks (the larger of the horizontal and the vertical gap: negative = they overlap)."""
    ra, rb = item(a).keep(), item(b).keep()
    return max(rb.left() - ra.right(), ra.left() - rb.right(), rb.top() - ra.bottom(), ra.top() - rb.bottom())


ok(cv.GAP == 40.0 and cv.GAP == wr.GAP, "the mandatory gap between blocks is 40")
tab.add_block("part", 100, 100)
tab.add_block("solid", 500, 100)
tab.add_block("assembly", 100, 400)
app.processEvents()
A, B, C = list(prj.nodes.values())
ok(all_clear(), "three blocks, all clear of each other")

# --- dragging a block onto another: it stops at the gap
drag(vpt(*head(B)), vpt(head(B)[0] - 330, head(B)[1] + 0))              # 330 to the left: it would be on top of A (A is at x 100..300; B at 500..700 -> would reach 170)
app.processEvents()
ok(all_clear(), f"a block dragged onto another never overlaps it ({B.pos} next to {A.pos})")
ok(abs(gap_between(A, B) - cv.GAP) < 1e-6, f"it stops exactly at the gap ({gap_between(A, B)})")
ok(B.pos[0] % 20 == 0 and B.pos[1] % 20 == 0 and item(B).pos().x() == B.pos[0], "and is on the grid, the project has the place")
# slides along it: the mouse goes on diagonally, down
bx, by = B.pos
drag(vpt(*head(B)), vpt(head(B)[0] - 120, head(B)[1] + 100))
ok(all_clear() and B.pos[1] > by and abs(gap_between(A, B) - cv.GAP) < 1e-6 or all_clear() and B.pos[1] > by and gap_between(A, B) >= cv.GAP - 1e-6, f"a block pushed against another slides along it ({(bx, by)} -> {B.pos})")
# the mouse goes on in the other direction (away): the block follows again
drag(vpt(*head(B)), vpt(head(B)[0] + 400, head(B)[1] - 100))
ok(all_clear() and B.pos[0] > bx, f"and when the mouse goes away the block follows ({B.pos})")
# back to its first place
drag(vpt(*head(B)), vpt(500 + 100, 100 + 10))
ok(all_clear() and B.pos == [500.0, 100.0], f"back where it was ({B.pos})")

# --- a block cannot be dragged THROUGH another (it would have to jump over it)
drag(vpt(*head(C)), vpt(head(C)[0], head(C)[1] - 400))                    # C is below A: straight up through A
ok(all_clear() and C.pos[1] > A.pos[1], f"a block does not jump over another ({C.pos})")
drag(vpt(*head(C)), vpt(100 + 100, 400 + 10))
ok(C.pos == [100.0, 400.0], "back")

# --- a selection moves as one and stops as one
scene.clearSelection()
drag(vpt(60, 60), vpt(740, 360))                                         # box over A and B
ok(sorted(scene.selected_ids()) == sorted([A.id, B.id]), "A and B are selected")
pa, pb = list(A.pos), list(B.pos)
drag(vpt(*head(A)), vpt(head(A)[0] + 40, head(A)[1] + 200))              # down: they would reach C (at y 400)
da, db = (A.pos[0] - pa[0], A.pos[1] - pa[1]), (B.pos[0] - pb[0], B.pos[1] - pb[1])
ok(all_clear() and da == db and da[1] > 0, f"the selection moves by the same step ({da}) and nothing overlaps")
ok(gap_between(A, C) >= cv.GAP - 1e-6, f"and stops at C ({gap_between(A, C)})")
drag(vpt(*head(A)), vpt(head(A)[0] - da[0], head(A)[1] - da[1]))
ok(A.pos == pa and B.pos == pb and all_clear(), "and goes back")
scene.clearSelection()

# --- the arrow keys
view.setFocus()
scene.clearSelection()
item(B).setSelected(True)
QTest.keyClick(view, Qt.Key.Key_Left)
ok(B.pos[0] == 480.0 and all_clear(), f"an arrow key moves a block one step ({B.pos})")
for _ in range(15):
    QTest.keyClick(view, Qt.Key.Key_Left)
ok(all_clear() and abs(gap_between(A, B) - cv.GAP) < 1e-6 and B.pos[0] == 340.0, f"keys against a neighbour stop at the gap ({B.pos})")
for _ in range(20):
    QTest.keyClick(view, Qt.Key.Key_Right)
drag(vpt(*head(B)), vpt(500 + 100, 100 + 10))
ok(B.pos == [500.0, 100.0], "and the block is back")
scene.clearSelection()

# --- adding blocks: the nearest free place
n0 = len(prj.nodes)
for _ in range(6):
    tab.add_block("part", 100, 100)                                      # always on the same, taken place
app.processEvents()
ok(len(prj.nodes) == n0 + 6 and all_clear(), f"six blocks added to the same taken place: all clear of each other ({len(prj.nodes)} blocks)")
ok(all(abs(n.pos[0] - 100) <= 800 and abs(n.pos[1] - 100) <= 800 for n in prj.nodes.values()), "and none of them is far from where it was asked for")
scene.remove_nodes([n.id for n in list(prj.nodes.values())[3:]])
ok(len(prj.nodes) == 3 and all_clear(), "removed again")
tab.add_block("part")                                                      # no place given: the next free place
D = list(prj.nodes.values())[-1]
ok(all_clear() and D.pos[0] > 500, f"a block with no place asked goes to the right of the others ({D.pos})")
scene.remove_nodes([D.id])

# --- the toolbox drop and the mouse: a block dropped on another (the same path)
x, y = scene.free_pos(150, 120, "study")
ok(cv.clear_of(QRectF(x, y, cv.BLOCK_W, cv.HEAD_H + cv.NAME_H + 3 * cv.CELL_H + cv.CAP_H), [item(n).keep() for n in (A, B, C)]), f"free_pos finds a place with the gap for a block of its height ({x}, {y})")

# ----------------------------------------------------------------------------------------------------------------------------------- the wires
k = prj.link(A.id, "geometry", B.id, "geometry")
scene._add_link_item(k)
scene.refresh()
li = scene.link_items[k.key()]


def wire_ok(l):
    pts = [(p.x(), p.y()) for p in l.pts]
    rects = scene.keep_rects()
    hv = all(abs(u[0] - v[0]) < 1e-6 or abs(u[1] - v[1]) < 1e-6 for u, v in zip(pts, pts[1:]))
    return hv and wr.crossings(pts, rects) == []


ok(wire_ok(li) and li.pts[0] == item(A).port_pos("geometry", "out") and li.pts[-1] == item(B).port_pos("geometry", "in"), "a wire between two free blocks: horizontal and vertical pieces, crosses no block")
# put C between A and B in the straight line, by hand (C goes right of A: the wire from A to B must round it)
scene.free_move = True
item(C).setPos(QPointF(320, 100))                                          # between A (100..300) and B (500..700): 320..520 is too close to B, so B goes right first
scene.free_move = False
scene.free_move = True
item(B).setPos(QPointF(700, 100))
item(C).setPos(QPointF(380, 100))
scene.free_move = False
scene.reroute_all()
app.processEvents()
ok(all_clear(), "A, C, B in a row with the gap")
ok(wire_ok(li), f"a block between the two ends: the wire goes round it, over or under ({len(li.pts)} points)")
ok(any(p.y() < item(C).pos().y() or p.y() > item(C).pos().y() + item(C).body_h() + cv.CAP_H for p in li.pts), "round: some corner is above or below the block in the middle")
ok(li.pts[0] == item(A).port_pos("geometry", "out") and li.pts[-1] == item(B).port_pos("geometry", "in"), "and still on both cells")
# the picture: the wire's colour is not seen inside the block in the middle, but is seen outside it
img = QImage(1400, 900, QImage.Format.Format_ARGB32)
img.fill(0xFFFFFFFF)
pa_ = QPainter(img)
pa_.setRenderHint(QPainter.RenderHint.Antialiasing, False)
scene.render(pa_, QRectF(0, 0, 1400, 900), QRectF(0, 0, 1400, 900))
pa_.end()
wire_rgb = cv.WIRE.rgb() & 0xFFFFFF
c_top, c_bot = item(C).pos().y(), item(C).pos().y() + item(C).body_h()
inside = 0
for xx in range(int(item(C).pos().x()) + 8, int(item(C).pos().x() + cv.BLOCK_W) - 8, 4):
    for yy in range(int(c_top) + 4, int(c_bot) - 4, 4):
        if (img.pixel(xx, yy) & 0xFFFFFF) == wire_rgb:
            inside += 1
ok(inside == 0, f"in the picture nothing of the wire is seen on the body of the block it passes ({inside} pixels of its colour)")
seen = 0
for u, v in zip(li.pts, li.pts[1:]):
    if abs(u.y() - v.y()) < 1e-6 and (u.y() < c_top or u.y() > c_bot + cv.CAP_H) and abs(u.x() - v.x()) > 40:
        mx, my = int((u.x() + v.x()) / 2), int(u.y())
        if any((img.pixel(mx, yy) & 0xFFFFFF) == wire_rgb for yy in (my - 1, my)):
            seen += 1
ok(seen >= 1, f"but the wire is drawn where it goes round ({seen} run{'s' if seen != 1 else ''} seen in the picture)")

# --- moving the middle block away: the wire is straight again; moving it with the mouse onto the wire's line: the wire goes round again, live
drag(vpt(*head(C)), vpt(head(C)[0] + 0, head(C)[1] + 300))
ok(all_clear() and wire_ok(li), f"the middle block taken away: the wire is clear ({len(li.pts)} points)")
ok(len(li.pts) <= 4, "and simple again")
drag(vpt(*head(C)), vpt(head(C)[0] + 0, head(C)[1] - 300))
ok(all_clear() and wire_ok(li), f"the block taken back into the way: the wire goes round it again ({len(li.pts)} points)")

# --- every wire of a bigger project keeps clear of every block: ten blocks put in a small area (the file is nudged apart when it is opened), seven wires
shutil.rmtree(T, ignore_errors=True)
big = wp.Project("Big")
rr = random.Random(3)
ns = {}
for kind in ("part", "part", "assembly", "solid", "solid", "solid", "thermal3d", "fea", "sheets", "study"):
    ns.setdefault(kind, []).append(big.add_node(kind, pos=(float(rr.randrange(0, 600, 20)), float(rr.randrange(0, 400, 20)))))
made = 0
for a_, c_, b_, d_ in (("part", "geometry", "solid", "geometry"), ("assembly", "geometry", "thermal3d", "geometry"), ("part", "sketch", "fea", "geometry")):
    try:
        big.link(ns[a_][0].id, c_, ns[b_][0].id, d_)
        made += 1
    except Exception:                                                        # noqa: BLE001
        pass
try:
    big.link(ns["part"][1].id, "geometry", ns["solid"][1].id, "geometry")
    made += 1
except Exception:                                                            # noqa: BLE001
    pass
try:
    big.link(ns["assembly"][0].id, "geometry", ns["solid"][2].id, "geometry")
    made += 1
except Exception:                                                            # noqa: BLE001
    pass
bpath = os.path.join(tempfile.mkdtemp(prefix="opara_wbl_"), "big" + wp.EXT)
big.write(bpath)
tab2 = wt.WorkbenchTab(None)
tab2.resize(1300, 800)
tab2.show()
app.processEvents()
tab2.load(bpath)
app.processEvents()
sc2 = tab2.scene
its = list(sc2.items_by_id.values())
ok(len(its) == 10 and all(cv.clear_of(a.keep(), [b.keep() for b in its if b is not a]) for a in its), f"ten blocks put close together: all clear of each other once opened ({len(sc2.moved_apart)} were moved)")
rects2 = sc2.keep_rects()
bad2 = 0
for l in sc2.link_items.values():
    pts = [(p.x(), p.y()) for p in l.pts]
    if wr.crossings(pts, rects2) or not all(abs(u[0] - v[0]) < 1e-6 or abs(u[1] - v[1]) < 1e-6 for u, v in zip(pts, pts[1:])):
        bad2 += 1
ok(made >= 3 and len(sc2.link_items) == made and bad2 == 0, f"and its {len(sc2.link_items)} wires cross no block ({bad2} do)")
# the same after the user moves blocks about with the mouse: 12 random drags, and the layout is always valid
rr = random.Random(11)
valid = True
for _ in range(12):
    n = rr.choice(list(tab2.project.nodes.values()))
    it2 = sc2.items_by_id[n.id]
    c0 = tab2.view.mapFromScene(QPointF(n.pos[0] + 100, n.pos[1] + 10))
    c1 = c0 + QPoint(rr.randrange(-300, 300), rr.randrange(-200, 200))
    QTest.mousePress(tab2.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c0)
    for i in range(1, 7):
        QTest.mouseMove(tab2.view.viewport(), QPoint(int(c0.x() + (c1.x() - c0.x()) * i / 6), int(c0.y() + (c1.y() - c0.y()) * i / 6)))
    QTest.mouseRelease(tab2.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c1)
    app.processEvents()
    its = list(sc2.items_by_id.values())
    rects2 = sc2.keep_rects()
    if not all(cv.clear_of(a.keep(), [b.keep() for b in its if b is not a]) for a in its):
        valid = False
    for l in sc2.link_items.values():
        pts = [(p.x(), p.y()) for p in l.pts]
        if wr.crossings(pts, rects2) or not all(abs(u[0] - v[0]) < 1e-6 or abs(u[1] - v[1]) < 1e-6 for u, v in zip(pts, pts[1:])):
            valid = False
ok(valid, "12 drags of random blocks with the mouse: after each of them no block overlaps another and no wire crosses a block")
shutil.rmtree(os.path.dirname(bpath), ignore_errors=True)

# ----------------------------------------------------------------------------------------------------------------------------------- a file from before the rule
old = wp.Project("Old")
n1 = old.add_node("part", pos=(100.0, 100.0))
n2 = old.add_node("solid", pos=(100.0, 100.0))                             # exactly on the first
n3 = old.add_node("assembly", pos=(180.0, 160.0))                          # on both
n4 = old.add_node("study", pos=(1000.0, 100.0))                            # alone
old.link(n1.id, "geometry", n2.id, "geometry")
path = os.path.join(tempfile.mkdtemp(prefix="opara_wbl_"), "old" + wp.EXT)
old.write(path)
tab3 = wt.WorkbenchTab(None)
tab3.resize(1300, 800)
tab3.show()
app.processEvents()
tab3.load(path)
app.processEvents()
its3 = list(tab3.scene.items_by_id.values())
ok(all(cv.clear_of(a.keep(), [b.keep() for b in its3 if b is not a]) for a in its3), "a project made before the rule: when it is opened, blocks on top of each other are moved apart")
p3 = tab3.project
ok(p3.nodes[n1.id].pos == [100.0, 100.0] and p3.nodes[n4.id].pos == [1000.0, 100.0], "the block at the top left and the one that was alone stay where they were")
ok(sorted(tab3.scene.moved_apart) == sorted([n2.id, n3.id]), f"the scene knows which blocks moved ({tab3.scene.moved_apart})")
ok("moved apart" in tab3.line.text(), f"and the status line says so ({tab3.line.text()[-90:]})")
placed = all(tab3.scene.items_by_id[i].pos().x() == p3.nodes[i].pos[0] and tab3.scene.items_by_id[i].pos().y() == p3.nodes[i].pos[1] for i in p3.nodes)
ok(p3.nodes[n2.id].pos != [100.0, 100.0] and placed, "the project holds the new places")
l3 = list(tab3.scene.link_items.values())[0]
pts3 = [(p.x(), p.y()) for p in l3.pts]
ok(wr.crossings(pts3, tab3.scene.keep_rects()) == [], "and the wire of that project crosses no block")

# a project that is already tidy is left alone
tab4 = wt.WorkbenchTab(None)
tab4.resize(1300, 800)
tab4.show()
app.processEvents()
tidy = wp.Project("Tidy")
t1 = tidy.add_node("part", pos=(100.0, 100.0))
t2 = tidy.add_node("solid", pos=(340.0, 100.0))                            # exactly the gap away
path2 = os.path.join(os.path.dirname(path), "tidy" + wp.EXT)
tidy.write(path2)
tab4.load(path2)
ok(tab4.scene.moved_apart == [] and tab4.project.nodes[t2.id].pos == [340.0, 100.0] and "moved apart" not in tab4.line.text(), "blocks exactly the gap apart are left alone, and nothing is said")

shutil.rmtree(os.path.dirname(path), ignore_errors=True)
shutil.rmtree(UDIR, ignore_errors=True)
print()
if FAILS:
    print(f"FAILURES: {len(FAILS)}")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
