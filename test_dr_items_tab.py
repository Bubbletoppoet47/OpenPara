"""Drawings (dev add-on drawings): Note, Balloon and the Sketch tools (Line, Rectangle, Circle, Arc) in the window - the text, size and leader of a note come from the panel; a leader snaps to
the edge it is clicked on and follows its view; balloons count on by themselves and end in an arrow on an edge or a dot on a face; lines, rectangles, circles and arcs are clicked
out and snap to corners; what is painted (pixels), selecting, dragging, the squares that change a leader or a line, double-click to edit, the Details, delete, undo, the file and the
PDF (text as text, lines as vectors).   python test_dr_items_tab.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import pm_app
pm_app.apply_theme(app)
import dr_annot as A
import dr_items as IT
import dr_model as M
import dr_panels as PN
import dr_tab as T

T.DrawingTab.ASK_SHEET = False
FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def settle():
    for _ in range(3):
        app.processEvents()


def plate(w, h, hole=True, r=8.0, at=(30.0, 30.0)):
    """A plate w x h x 10 (a rectangle on the Top plane, extruded), with a hole of radius r at `at`."""
    import pm_model as pm
    import sk_tools as sk
    d = pm.Document()
    d.params = {"H": "10"}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    rc = sk.add_rect_corner(m, (0, 0), (w, h))
    m.add_con("dim_h", [("ln", rc["lns"][0])], value=float(w))
    m.add_con("dim_v", [("ln", rc["lns"][1])], value=float(h))
    if hole:
        m.add_circle(m.add_point(*at), r)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    return json.loads(d.to_json())




tmp = tempfile.mkdtemp(prefix="dr_items_")
t = T.DrawingTab()
t.resize(1250, 800)
t.show()
settle()
cv = t.canvas
mid = t.d.add_model("Plate", "part", plate(100, 60), src="n1")
t.models_from_wires = True
t.model_panel.refresh()
t.model_panel.pick_orientation("Top")
at = lambda x, y: cv.to_screen(x, y).toPoint()
QTest.mouseMove(cv, at(100, 110))
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(100, 110))
settle()
v = t.d.views[0]
vid = v["id"]
s_, o_ = v["scale"], v["origin"]
S = lambda p: (o_[0] + s_ * p[0], o_[1] + s_ * p[1])           # a point of the view's frame on the sheet
ok(len(t.d.views) == 1 and near(s_, 1.0) and not t.d.notes and not t.d.balloons and not t.d.lines, "the Top view of a 100 x 60 plate with a hole of 16 mm is on the sheet; nothing else yet")
tol = 1.0 / cv.k                                       # one pixel, in mm: a click is on a whole pixel, so a point clicked is only this exact
P = lambda a, b, f=1.5: abs(a[0] - b[0]) <= f * tol and abs(a[1] - b[1]) <= f * tol
V = lambda a, b, f=1.5: abs(a - b) <= f * tol


def click(x, y):
    QTest.mouseMove(cv, at(x, y))
    QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(x, y))
    settle()


def move(x, y):
    QTest.mouseMove(cv, at(x, y))
    settle()


def drag(x0, y0, x1, y1, steps=4):
    QTest.mouseMove(cv, at(x0, y0))
    QTest.mousePress(cv, Qt.MouseButton.LeftButton, pos=at(x0, y0))
    for i in range(1, steps + 1):
        QTest.mouseMove(cv, at(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps))
        settle()
    QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, pos=at(x1, y1))
    settle()


def dclick(x, y):
    QTest.mouseMove(cv, at(x, y))
    QTest.mouseDClick(cv, Qt.MouseButton.LeftButton, pos=at(x, y))
    settle()


def key(k):
    QTest.keyClick(cv, k)
    settle()


def dark_count(x0, y0, x1, y1, im=None):
    """Dark pixels in the rectangle (sheet mm, any two corners)."""
    im = im or cv.grab().toImage()
    a, b = at(x0, y0), at(x1, y1)
    n = 0
    for px in range(min(a.x(), b.x()), max(a.x(), b.x()) + 1):
        for py in range(min(a.y(), b.y()), max(a.y(), b.y()) + 1):
            if QColor(im.pixel(px, py)).lightness() < 140:
                n += 1
    return n


def dark_at(x, y, im=None):
    im = im or cv.grab().toImage()
    c = at(x, y)
    return min(QColor(im.pixel(c.x() + dx, c.y() + dy)).lightness() for dx in (-1, 0, 1) for dy in (-1, 0, 1)) < 140


def blue_at(x, y, im=None):
    im = im or cv.grab().toImage()
    c = at(x, y)
    return any((lambda q: q.blue() - q.red() > 40)(QColor(im.pixel(c.x() + dx, c.y() + dy))) for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2))


def outline_texts():
    out = []

    def walk(it):
        out.append(it.text(0))
        for i in range(it.childCount()):
            walk(it.child(i))
    for i in range(t.outline.tree.topLevelItemCount()):
        walk(t.outline.tree.topLevelItem(i))
    return out


def seg_mid(shp, i=0, j=0):
    a, b = shp["segs"][i][j], shp["segs"][i][j + 1]
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


# ---------------------------------------------------------------------------------------------------------------------------- the ribbon
t.ribbon.setCurrentIndex(1)
ok(all(t.act[k].isEnabled() for k in ("note", "balloon")), "Note and Balloon are on the Annotation page, ready to use")
t.ribbon.setCurrentIndex(2)
ok(all(t.act[k].isEnabled() for k in ("select", "line", "rect", "circle", "arc")), "Select, Line, Rectangle, Circle and Arc are on the Sketch page, ready to use")
ok(t.act["select"].isChecked() and cv.tool is None, "Select is the tool that is on when no other is")
t.act["note"].click()
settle()
ok(cv.tool == "note" and t.act["note"].isChecked() and not t.act["select"].isChecked() and t.props.currentWidget() is t.tool_panel and t.tool_panel.title.text() == "Note", "Note opens its panel")
ok(t.tool_panel.opt_note.isVisibleTo(t.tool_panel) and not t.tool_panel.opt_balloon.isVisibleTo(t.tool_panel), "which has the text, the size and the leader of the note (not the balloon's number)")
ok(t.tool_panel.n_text.toPlainText() == "Note" and t.tool_panel.n_leader.currentData() == "straight" and t.tool_panel.n_size.currentText() == "14", "starting with a straight leader, 14 points, and the text 'Note'")
ok("leader" in t.hint_lbl.text() and "text goes" in t.hint_lbl.text(), "the hint bar says what to click for a note with a leader")

# ---------------------------------------------------------------------------------------------------------------------------- a note without a leader
t.tool_panel.n_leader.setCurrentIndex(0)
t.tool_panel.options_edited()
ok(cv.opts["leader"] is None and "Click on the sheet" in t.hint_lbl.text(), "no leader: the options of the canvas follow the panel, and the hint changes")
t.tool_panel.n_text.setPlainText("MATERIAL: STEEL")
t.tool_panel.n_size.setEditText("18")
t.tool_panel.options_edited()
ok(cv.opts["text"] == "MATERIAL: STEEL" and near(cv.opts["size"], 18.0), "the text and the size are taken")
n0 = len(t.undo_stack)
click(20, 30)
ok(len(t.d.notes) == 1 and cv.float_annot is None and len(t.undo_stack) == n0 + 1 and t.is_dirty(), "one click puts a note down (one undo step)")
n1 = t.d.notes[0]
ok(n1["id"] == "n1" and n1["text"] == "MATERIAL: STEEL" and near(n1["size"], 18.0) and n1["leader"] is None and P(n1["pos"], (20.0, 30.0)),
   f"its text, size and place are what was set ({n1['text']}, {n1['size']}, {n1['pos']})")
box1 = cv.r.shape(n1)["box"]
img = cv.grab().toImage()
ok(dark_count(box1[0], box1[1], box1[2], box1[3], img) > 120, "the text is drawn there")
ok(dark_count(box1[0] - 1, box1[3] + 3, box1[2] + 1, box1[3] + 12, img) == 0 and dark_count(box1[0] - 1, box1[1] - 12, box1[2] + 1, box1[1] - 3, img) == 0, "and nowhere else")
ok(near(box1[2] - box1[0], cv.r.metrics(18.0).width("MATERIAL: STEEL"), 1e-6) and 40 < box1[2] - box1[0] < 70, f"as wide as the font says ({box1[2] - box1[0]:.1f} mm)")
cap_px = 0
col = at(box1[0] + 3.0, 0).x()
im_cap = [py for py in range(at(0, box1[3] + 2).y(), at(0, box1[1] - 2).y()) if any(QColor(img.pixel(px, py)).lightness() < 140 for px in range(at(box1[0], 0).x(), at(box1[2], 0).x()))]
cap_mm = (max(im_cap) - min(im_cap) + 1) / cv.k
ok(abs(cap_mm - cv.r.metrics(18.0).cap) < 0.6, f"the capitals are as tall as 18 points make them ({cap_mm:.1f} mm; {cv.r.metrics(18.0).cap:.1f} expected)")
ok("Note added" in t.hint_lbl.text(), "the hint says it was added and what comes next")
ok(any(x == "Notes" for x in outline_texts()) and any(x.startswith("MATERIAL") for x in outline_texts()), "the Outline lists the note, in a folder of notes of the sheet")

# a note with no text is refused
t.tool_panel.n_text.setPlainText("   ")
t.tool_panel.options_edited()
c0 = len(t.d.notes)
click(20, 10)
ok(len(t.d.notes) == c0 and "text" in t.hint_lbl.text(), f"a note with no text is not made; the hint says why ({t.hint_lbl.text()[:50]})")
t.tool_panel.n_text.setPlainText("Break all\nsharp edges")
t.tool_panel.options_edited()

# ---------------------------------------------------------------------------------------------------------------------------- a note with a straight leader
t.tool_panel.n_size.setEditText("14")
t.tool_panel.n_leader.setCurrentIndex(1)
t.tool_panel.options_edited()
ok(cv.opts["leader"] == "straight" and "what the leader points at" in t.hint_lbl.text(), "with a straight leader: the hint says to click what it points at first")
n0 = len(t.undo_stack)
move(*S((70, 60)))
click(*S((70, 60)))
ok(cv.float_annot is not None and len(t.d.notes) == 2 and len(t.undo_stack) == n0, "a click on the top edge: the note follows the pointer (not in the undo list yet)")
n2 = t.d.notes[1]
ok(n2["leader"]["kind"] == "straight" and n2["leader"]["view"] == vid and near(n2["leader"]["p"][0], 70.0, tol) and near(n2["leader"]["p"][1], 60.0, 1e-6), f"the tip is ON the edge, in the view's frame ({n2['leader']['p']})")
move(170, 175)
ok(P(n2["pos"], (170.0, 175.0)), "the text follows the pointer")
im = cv.grab().toImage()
tip = S((70, 60))
shp2 = cv.r.shape(n2)
mid2 = seg_mid(shp2)
ok(blue_at(*mid2, im), "the leader is drawn to it, in the selection colour while it follows")
click(170, 175)
ok(cv.float_annot is None and len(t.undo_stack) == n0 + 1 and "Note added" in t.hint_lbl.text(), "a click puts it down: one undo step")
im = cv.grab().toImage()
shp2 = cv.r.shape(n2)
ok(dark_at(*seg_mid(shp2), im) and not blue_at(*seg_mid(shp2), im), "the leader is black now")
bx2 = shp2["box"]
ok(dark_count(*bx2, im=im) > 80, "and the text is next to it")
ok(len(shp2["segs"][0]) == 2 and abs(shp2["segs"][0][1][0] - (bx2[0] - IT.LEAD_GAP)) < 1e-6, "the leader goes to the middle of the left side of the text")
ok(dark_at(*tip, im), "it ends on the edge")
cv.zoom(4.0, at=cv.to_screen(*tip))
zimg = cv.grab().toImage()
ux, uy = shp2["heads"][0][1]
near_tip = (tip[0] + ux * 1.2, tip[1] + uy * 1.2)
far_pt = (tip[0] + ux * 8.0, tip[1] + uy * 8.0)
cnt = lambda p_: dark_count(p_[0] - 0.9, p_[1] - 0.9, p_[0] + 0.9, p_[1] + 0.9, zimg)
ok(cnt(near_tip) > cnt(far_pt) + 3, f"an arrow at the tip: the leader is thicker there ({cnt(near_tip)} against {cnt(far_pt)} pixels)")
cv.fit()
settle()

# Esc takes away what is half done
click(*S((20, 60)))
ok(cv.float_annot is not None and len(t.d.notes) == 3, "another note: the tip is set, the text follows")
key(Qt.Key.Key_Escape)
ok(cv.float_annot is None and len(t.d.notes) == 2 and cv.tool == "note", "Esc takes it away again and the tool stays")

# ---------------------------------------------------------------------------------------------------------------------------- a bent leader
t.tool_panel.n_text.setPlainText("Drill 16 thru")
t.tool_panel.n_leader.setCurrentIndex(2)
t.tool_panel.options_edited()
click(*S((100, 40)))
click(190, 105)
n3 = t.d.notes[2]
ok(n3["leader"]["kind"] == "bent" and n3["leader"]["view"] == vid and near(n3["leader"]["p"][0], 100.0, 1e-6), f"a bent leader, on the right edge of the plate ({n3['leader']['p']})")
shp3 = cv.r.shape(n3)
pts3 = shp3["segs"][0]
ok(len(pts3) == 3 and abs(pts3[1][1] - pts3[2][1]) < 1e-9 and abs(pts3[2][0] - pts3[1][0] - IT.LAND) < 1e-6, f"tip, a knee, and a level part of {IT.LAND} mm into the text")
im = cv.grab().toImage()
ok(dark_at((pts3[1][0] + pts3[2][0]) / 2.0, pts3[1][1], im) and dark_at(*seg_mid(shp3, 0, 0), im), "both parts are drawn")
ok(dark_count(*shp3["box"], im=im) > 60, "and the text")

# ---------------------------------------------------------------------------------------------------------------------------- balloons
t.ribbon.setCurrentIndex(1)
t.act["balloon"].click()
settle()
ok(cv.tool == "balloon" and t.tool_panel.title.text() == "Balloon" and t.tool_panel.opt_balloon.isVisibleTo(t.tool_panel) and not t.tool_panel.opt_note.isVisibleTo(t.tool_panel), "Balloon opens its panel, with the number of the next balloon")
ok(t.tool_panel.b_text.text() == "1" and cv.opts["balloon"] == "1", "which starts at 1")
click(20, 205)
ok(not t.d.balloons and "Click on a view" in t.hint_lbl.text(), "a click that is on no view makes no balloon, and the hint says what to do")
n0 = len(t.undo_stack)
click(*S((50, 0)))
ok(cv.float_annot is not None and len(t.d.balloons) == 1 and len(t.undo_stack) == n0, "a click on the bottom edge: the balloon follows the pointer")
b1 = t.d.balloons[0]
ok(b1["view"] == vid and b1["snap"] is True and b1["text"] == "1" and near(b1["tip"][1], 0.0, 1e-6), f"it points at the edge ({b1['tip']}), with an arrow, and its number is 1")
move(100, 40)
click(100, 40)
ok(cv.float_annot is None and len(t.undo_stack) == n0 + 1 and P(b1["pos"], (100.0, 40.0)), "a click puts the circle down: one undo step")
ok(t.tool_panel.b_text.text() == "2" and cv.opts["balloon"] == "2", "the next one is 2")
im = cv.grab().toImage()
ok(dark_at(100 + IT.BALLOON_R, 40, im) and dark_at(100 - IT.BALLOON_R, 40, im) and dark_at(100, 40 + IT.BALLOON_R, im), "the circle is drawn, 4.5 mm round its middle")
ok(dark_count(98.6, 38.2, 101.4, 41.8, im) > 6 and not dark_at(100 + 2.1, 40 + 2.1, im), "with the number in it, and white between the number and the circle")
ok(dark_at(100, 60, im) or dark_at(100, 55, im), "and a leader to the edge")
click(*S((60, 45)))
ok(t.d.balloons[1]["snap"] is False and cv.float_annot is not None, "a click on the face (not near a line): the balloon points at it with a dot")
click(30, 150)
b2 = t.d.balloons[1]
ok(b2["text"] == "2" and t.tool_panel.b_text.text() == "3", "numbered 2, the next is 3")
im = cv.grab().toImage()
tipb2 = t.d.balloon_tip(b2)
ok(dark_at(*tipb2, im) and cv.r.shape(b2)["dots"] and not cv.r.shape(b2)["heads"], "a dot at its end, not an arrow")
t.tool_panel.b_text.setText("A")
click(*S((100, 30)))
click(200, 60)
ok(t.d.balloons[2]["text"] == "A" and t.tool_panel.b_text.text() == "A", "a number can be typed in the panel (a letter does not count on)")
ok(any(x.startswith("Balloon  1") for x in outline_texts()) and any(x.startswith("Balloon  A") for x in outline_texts()), "the Outline lists the balloons, under their view")
tr_ = t.outline.tree
view_item = t.outline.items[vid]
ok(any(view_item.child(i).text(0).startswith("Balloon") for i in range(view_item.childCount())), "(under the view they point at)")

# ---------------------------------------------------------------------------------------------------------------------------- the Sketch tools
t.ribbon.setCurrentIndex(2)
t.act["rect"].click()
settle()
ok(cv.tool == "rect" and t.tool_panel.title.text() == "Rectangle" and t.act["rect"].isChecked() and not t.act["select"].isChecked(), "Rectangle opens")
n0 = len(t.undo_stack)
click(20, 170)
ok(cv.draft is not None and not t.d.lines and "opposite corner" in t.hint_lbl.text(), "one corner: nothing is made yet, the hint says what is next")
move(60, 200)
im = cv.grab().toImage()
ok(blue_at(40, 170, im) and blue_at(60, 185, im) and not blue_at(40, 185, im), "the rectangle follows the pointer (in the selection colour, an outline)")
click(60, 200)
ok(len(t.d.lines) == 1 and cv.draft is None and len(t.undo_stack) == n0 + 1, "the second corner makes it: one undo step")
r1 = t.d.lines[0]
ok(r1["type"] == "rect" and r1["id"] == "l1" and P(r1["p"][0], (20.0, 170.0)) and P(r1["p"][1], (60.0, 200.0)), f"two opposite corners ({r1['p']})")
im = cv.grab().toImage()
ok(dark_at(40, 170, im) and dark_at(40, 200, im) and dark_at(20, 185, im) and dark_at(60, 185, im), "its four sides are drawn")
ok(dark_count(30, 177, 50, 193, im) == 0, "and nothing inside")
t.act["circle"].click()
settle()
click(90, 180)
move(102, 180)
click(102, 180)
c1 = t.d.lines[1]
ok(c1["type"] == "circle" and P(c1["c"], (90, 180)) and V(c1["r"], 12.0, 2.5), f"a circle by its centre and a point on it ({c1['c']}, r {c1['r']:.2f})")
im = cv.grab().toImage()
ok(dark_at(102, 180, im) and dark_at(78, 180, im) and dark_at(90, 192, im) and dark_at(90, 168, im) and not dark_at(90, 180, im), "its outline is drawn, and not its inside")
ok(dark_at(90 + 12 * 0.7071, 180 + 12 * 0.7071, im), "round, not a square")
t.act["arc"].click()
settle()
click(140, 180)
ok("starts" in t.hint_lbl.text(), "an arc: the centre first, the hint asks for the start")
click(152, 180)
move(140, 192)
im = cv.grab().toImage()
ok(blue_at(140 + 12 * 0.7071, 180 + 12 * 0.7071, im), "the arc follows the pointer from the start")
click(140, 192)
a1_ = t.d.lines[2]
ok(a1_["type"] == "arc" and V(a1_["r"], 12.0, 2.5) and abs(a1_["a0"]) < 0.06 and abs(a1_["a1"] - 3.14159265 / 2) < 0.06, f"the arc runs from the start to the end, counter-clockwise ({a1_['a0']:.2f} to {a1_['a1']:.2f} rad)")
im = cv.grab().toImage()
ok(dark_at(140 + 12 * 0.7071, 180 + 12 * 0.7071, im) and not dark_at(140 - 12 * 0.7071, 180 + 12 * 0.7071, im) and not dark_at(140 + 12 * 0.7071, 180 - 12 * 0.7071, im), "drawn in its quarter only")
t.act["line"].click()
settle()
click(180, 60)
click(215, 85)
click(240, 60)
ok(len(t.d.lines) == 5 and t.d.lines[3]["type"] == "line" and t.d.lines[4]["p"][0] == t.d.lines[3]["p"][1], "a line carries on from its end: two lines, the second starts where the first ended")
key(Qt.Key.Key_Escape)
ok(cv.tool == "line" and cv.draft is None, "Esc ends the chain, the tool stays")
click(*[a + b for a, b in zip(S((100, 60)), (0.6, 0.4))])
move(200, 150)
click(200, 150)
ln_ = t.d.lines[5]
ok(abs(ln_["p"][0][0] - S((100, 60))[0]) < 1e-9 and abs(ln_["p"][0][1] - S((100, 60))[1]) < 1e-9, f"a point near a corner of the view snaps to it, exactly ({ln_['p'][0]})")
key(Qt.Key.Key_Escape)
move(*[a + b for a, b in zip(t.d.lines[3]["p"][1], (0.5, -0.5))])
ok(cv.snap_mark is not None and abs(cv.snap_mark[0] - t.d.lines[3]["p"][1][0]) < 1e-9 and abs(cv.snap_mark[1] - t.d.lines[3]["p"][1][1]) < 1e-9, "near the end of something that is drawn: it snaps to that, and shows a small square")
key(Qt.Key.Key_Escape)
ok(cv.tool is None and t.act["select"].isChecked() and not t.act["line"].isChecked(), "Esc again ends the tool: Select is on")
ok(len(t.d.lines) == 6 and "Drawn on the sheet" in outline_texts() and "Rectangle" in outline_texts() and "Arc" in outline_texts(), "(six items: the Outline lists them, in a folder of its own)")

# ---------------------------------------------------------------------------------------------------------------------------- selecting and dragging
click(*[(a + b) / 2.0 for a, b in zip(*[(box1[0], box1[1]), (box1[2], box1[3])])])
ok(cv.sel_annot == "n1" and t.outline.cur_id == "n1" and t.outline.details.currentIndex() == 5, "a click on the text of a note selects it, and its Details open")
ok(t.outline.n_text.toPlainText() == "MATERIAL: STEEL" and t.outline.n_size.currentText() == "18" and t.outline.n_leader.currentData() is None, "with its text, its size and its leader (none)")
im = cv.grab().toImage()
ok(blue_at(box1[0] + 5, (box1[1] + box1[3]) / 2.0, im) or dark_count(*box1, im=im) < 20, "the text is blue")
n0 = len(t.undo_stack)
drag((box1[0] + box1[2]) / 2.0, (box1[1] + box1[3]) / 2.0, (box1[0] + box1[2]) / 2.0 + 12.0, (box1[1] + box1[3]) / 2.0 - 8.0)
ok(len(t.undo_stack) == n0 + 1 and P(t.d.notes[0]["pos"], (32.0, 22.0), 2.5), f"dragged: moved by what the pointer moved ({t.d.notes[0]['pos']}), one undo step")
moved_pos = list(t.d.notes[0]["pos"])
t.do_undo()
ok(P(t.d.notes[0]["pos"], (20.0, 30.0)), "undo puts it back")
t.do_redo()
ok(t.d.notes[0]["pos"] == moved_pos, "redo moves it again")
t.do_undo()
# the tip of a leader
click(*seg_mid(cv.r.shape(t.d.notes[1])))
ok(cv.sel_annot == "n2" and cv.r.handles_of(t.d.notes[1])[0][0] == "tip", "a note with a leader: a click on the leader selects it, and a square is on the tip")
im = cv.grab().toImage()
tip2 = t.d.leader_tip(t.d.notes[1])
n0 = len(t.undo_stack)
ok(cv._handle_at(*tip2) == "tip" and cv._handle_at(tip2[0] + 10, tip2[1]) is None, "the square is on the tip, and only there")
drag(tip2[0], tip2[1], *S((20, 0)))
nn = t.d.notes[1]
ok(nn["leader"]["view"] == vid and V(nn["leader"]["p"][0], 20.0) and abs(nn["leader"]["p"][1]) < 1e-9 and len(t.undo_stack) == n0 + 1, f"the tip dragged onto the bottom edge: it snaps to it ({nn['leader']['p']})")
tip2 = t.d.leader_tip(nn)
drag(tip2[0], tip2[1], 230, 40)
ok(nn["leader"]["view"] is None and P(nn["leader"]["p"], (230, 40)), "dragged off the views: a point of the sheet")
t.do_undo()
t.do_undo()
ok(t.d.notes[1]["leader"]["view"] == vid and V(t.d.notes[1]["leader"]["p"][0], 70.0), "undo, undo: back on the top edge")
# a balloon: move the circle, drag the tip
bb = t.d.balloons[0]
cc = bb["pos"]
click(cc[0], cc[1])
ok(cv.sel_annot == "b1" and t.outline.details.currentIndex() == 6 and t.outline.bl_text.text() == "1", "a click inside a balloon selects it; its Details show the number")
drag(cc[0], cc[1], cc[0] + 20.0, cc[1] - 10.0)
ok(P(bb["pos"], (cc[0] + 20.0, cc[1] - 10.0), 2.5) and V(bb["tip"][0], 50.0) and abs(bb["tip"][1]) < 1e-9, "the circle is moved, its tip stays on the edge")
tipb = t.d.balloon_tip(bb)
drag(tipb[0], tipb[1], *S((90, 0)))
ok(V(bb["tip"][0], 90.0) and abs(bb["tip"][1]) < 1e-9 and bb["snap"] is True, "the tip dragged along the edge")
tipb = t.d.balloon_tip(bb)
drag(tipb[0], tipb[1], *S((70, 20)))
ok(bb["snap"] is False and P(bb["tip"], (70.0, 20.0)), "dragged onto the face: a dot, in the view's frame")
# drawn items
click(20, 185)
ok(cv.sel_annot == "l1" and t.outline.details.currentIndex() == 7 and abs(float(t.outline.i_size.text().split()[1].rstrip(",")) - 40.0) < 1.0, f"a click on a side of the rectangle selects it: {t.outline.i_size.text()}")
hs = {n: q for n, q in cv.r.handles_of(t.d.lines[0])}
ok(set(hs) == {"c0", "c1", "c2", "c3"} and cv._handle_at(*hs["c2"]) == "c2", "squares on its four corners")
keep_c0 = list(t.d.lines[0]["p"][0])
drag(hs["c2"][0], hs["c2"][1], 80, 205)
ok(t.d.lines[0]["p"][0] == keep_c0 and P(t.d.lines[0]["p"][1], (80.0, 205.0)), f"a corner dragged: the opposite one stays ({t.d.lines[0]['p']})")
click(t.d.lines[1]["c"][0] + t.d.lines[1]["r"], t.d.lines[1]["c"][1])
ok(cv.sel_annot == "l2", "the circle is selected by its outline")
hc = dict(cv.r.handles_of(t.d.lines[1]))
c1_c0 = list(t.d.lines[1]["c"])
drag(hc["r"][0], hc["r"][1], c1_c0[0] + 5.0, c1_c0[1])
ok(V(t.d.lines[1]["r"], 5.0, 2.5) and t.d.lines[1]["c"] == c1_c0, "the radius square: the circle shrinks round its centre")
c_before = list(t.d.lines[1]["c"])
drag(c_before[0], c_before[1] + t.d.lines[1]["r"], c_before[0] + 10.0, c_before[1] + t.d.lines[1]["r"] + 5.0)
ok(P(t.d.lines[1]["c"], (c_before[0] + 10.0, c_before[1] + 5.0), 2.5), "a drag on the line itself moves the circle")
click(140 + 12 * 0.7071, 180 + 12 * 0.7071)
ok(cv.sel_annot == "l3", "the arc is selected")
ha = dict(cv.r.handles_of(t.d.lines[2]))
ok(set(ha) == {"c", "s", "e"}, "centre, start and end squares")
r_arc = t.d.lines[2]["r"]
drag(ha["e"][0], ha["e"][1], ha["c"][0] - 12.0, ha["c"][1])
ok(abs(t.d.lines[2]["a1"] - 3.14159265) < 0.06 and V(t.d.lines[2]["r"], r_arc, 0.01), "the end square: the arc sweeps to a half circle, the radius stays")
click(180 + 17, 60 + 12.5)
ok(cv.sel_annot == "l4", "the first line of the chain is selected")
hl = dict(cv.r.handles_of(t.d.lines[3]))
second_before = [list(q) for q in t.d.lines[4]["p"]]
drag(hl["a"][0], hl["a"][1], 170, 40)
ok(P(t.d.lines[3]["p"][0], (170, 40)) and t.d.lines[4]["p"] == second_before, "a line's end dragged: the next line of the chain does not move (no constraints)")

# ---------------------------------------------------------------------------------------------------------------------------- delete
n0 = len(t.undo_stack)
nb = len(t.d.balloons)
click(*t.d.balloons[1]["pos"])
ok(cv.sel_annot == "b2", "a balloon is selected")
key(Qt.Key.Key_Delete)
ok(len(t.d.balloons) == nb - 1 and cv.sel_annot is None and len(t.undo_stack) == n0 + 1, "Delete takes it away: one undo step")
t.do_undo()
ok(len(t.d.balloons) == nb and any(b["id"] == "b2" for b in t.d.balloons), "undo brings it back")
ok(t.act["delete"].isEnabled() is False, "(nothing is selected now: Delete is grey)")
click(*[(a + b) / 2.0 for a, b in zip(*[(box1[0], box1[1]), (box1[2], box1[3])])])
ok(cv.sel_annot == "n1" and t.act["delete"].isEnabled(), "a note is selected: the Delete button of the ribbon is on")
t.act["delete"].click()
settle()
ok(not any(n["id"] == "n1" for n in t.d.notes), "and takes it away")
t.do_undo()
ok(any(n["id"] == "n1" for n in t.d.notes), "undo")

# ---------------------------------------------------------------------------------------------------------------------------- double-click to edit
asked = []
t.ask_text = lambda title, label, text, multiline=False: (asked.append((title, text, multiline)), "Changed\ntext" if multiline else "7")[1]
n0 = len(t.undo_stack)
bx = cv.r.shape(t.d.notes[0])["box"]
dclick((bx[0] + bx[2]) / 2.0, (bx[1] + bx[3]) / 2.0)
ok(asked and asked[-1][0] == "Note" and asked[-1][2] is True and asked[-1][1] == "MATERIAL: STEEL", "a double-click on a note asks for its text, in a box for several lines")
ok(t.d.notes[0]["text"] == "Changed\ntext" and len(t.undo_stack) == n0 + 1, "the answer is the new text: one undo step")
ok(cv.r.shape(t.d.notes[0])["box"][1] < bx[1] and len(cv.r.shape(t.d.notes[0])["lines"]) == 2, "two lines now: the note is taller")
bp = t.d.balloons[0]["pos"]
dclick(bp[0] + 20.0 * 0 + 0.0, bp[1])
ok(asked[-1][0] == "Balloon" and asked[-1][2] is False and t.d.balloons[0]["text"] == "7", "a double-click on a balloon asks for its number")
t.do_undo()
t.do_undo()
ok(t.d.notes[0]["text"] == "MATERIAL: STEEL" and t.d.balloons[0]["text"] == "1", "undo, undo")
t.ask_text = lambda title, label, text, multiline=False: None
dclick((bx[0] + bx[2]) / 2.0, (bx[1] + bx[3]) / 2.0)
ok(t.d.notes[0]["text"] == "MATERIAL: STEEL", "a cancelled dialog changes nothing")

# ---------------------------------------------------------------------------------------------------------------------------- the Details change them
click(*[(a + b) / 2.0 for a, b in zip(*[(box1[0], box1[1]), (box1[2], box1[3])])])
ok(cv.sel_annot == "n1", "a note is selected")
n0 = len(t.undo_stack)
t.outline.n_text.setPlainText("New text here")
t.outline.note_edited()
ok(t.d.notes[0]["text"] == "New text here" and len(t.undo_stack) == n0 + 1, "the text typed in the Details is the note's text: one undo step")
w18 = cv.r.shape(t.d.notes[0])["box"][2] - cv.r.shape(t.d.notes[0])["box"][0]
t.outline.n_size.setEditText("24")
t.outline.note_edited()
w24 = cv.r.shape(t.d.notes[0])["box"][2] - cv.r.shape(t.d.notes[0])["box"][0]
ok(near(t.d.notes[0]["size"], 24.0) and abs(w24 / w18 - 24.0 / 18.0) < 0.01, f"the size: 24 points, the note is a third wider than at 18 ({w24 / w18:.3f})")
t.outline.n_leader.setCurrentIndex(2)
t.outline.note_edited()
lt = t.d.leader_tip(t.d.notes[0])
ok(t.d.notes[0]["leader"]["kind"] == "bent" and t.d.notes[0]["leader"]["view"] is None and lt is not None and abs(lt[0] - (t.d.notes[0]["pos"][0] - 20.0)) < 1e-6 and abs(lt[1] - (t.d.notes[0]["pos"][1] - 14.0)) < 1e-6,
   "a leader that is added starts as a bent one, pointing at the sheet to the lower left of the text")
t.outline.n_leader.setCurrentIndex(1)
t.outline.note_edited()
ok(t.d.notes[0]["leader"]["kind"] == "straight", "straight")
t.outline.n_leader.setCurrentIndex(0)
t.outline.note_edited()
ok(t.d.notes[0]["leader"] is None, "no leader: it goes")
n0 = len(t.undo_stack)
t.outline.n_text.setPlainText("   ")
t.outline.note_edited()
ok(t.d.notes[0]["text"] == "New text here" and len(t.undo_stack) == n0 and "text" in t.status.full and t.outline.n_text.toPlainText() == "New text here", "an empty text is refused: the note and the box keep the old text, and the status line says why")
t.outline.n_text.setPlainText("MATERIAL: STEEL")
t.outline.n_size.setEditText("18")
t.outline.note_edited()
click(*t.d.balloons[0]["pos"])
t.outline.bl_text.setText("12")
t.outline.balloon_edited()
ok(t.d.balloons[0]["text"] == "12" and cv.r.shape(t.d.balloons[0])["circle"][1] > IT.BALLOON_R * 0.99, "a balloon's number in the Details")
t.outline.bl_text.setText("1")
t.outline.balloon_edited()

# ---------------------------------------------------------------------------------------------------------------------------- they follow their view
click(*S((50, 30)))
cv.set_selected(None)
b1 = t.d.balloons[0]
tip_b = t.d.balloon_tip(b1)
tip_n = t.d.leader_tip(t.d.notes[1])
n0 = len(t.undo_stack)
vx0 = list(t.d.view(vid)["origin"])
t.d.shift_view(vid, 7.0, -3.0)
t.canvas.r.cache.clear()
t.commit("move")
tb2, tn2 = t.d.balloon_tip(b1), t.d.leader_tip(t.d.notes[1])
ok(abs(tb2[0] - tip_b[0] - 7.0) < 1e-6 and abs(tb2[1] - tip_b[1] + 3.0) < 1e-6 and abs(tn2[0] - tip_n[0] - 7.0) < 1e-6, "the view moved: the tip of the balloon and the tip of the note's leader moved with it")
im = cv.grab().toImage()
ok(dark_at(*tn2, im), "and still end on the edge")
t.set_view_scale(vid, "2:1")
tb3 = t.d.balloon_tip(b1)
o3 = t.d.view(vid)["origin"]
ok(abs(tb3[0] - (o3[0] + 2.0 * b1["tip"][0])) < 1e-6 and abs(tb3[1] - (o3[1] + 2.0 * b1["tip"][1])) < 1e-6, "at another scale: still at the same point of the view")
t.set_view_scale(vid, "1:1")
# the view looks another way
t.set_view_orient(vid, "Front")
ok(not t.d.balloons and t.d.notes[1]["leader"]["view"] is None and "balloon" in t.status.full, f"the view looks another way: the balloons go (the status line says so), the note's leader stays where it pointed ({t.status.full[:70]})")
t.do_undo()
ok(len(t.d.balloons) == 3 and t.d.notes[1]["leader"]["view"] == vid, "undo brings them back")

# ---------------------------------------------------------------------------------------------------------------------------- the file
cv.set_selected_annot(None)
cv.set_selected(None)
path = os.path.join(tmp, "items.opdraw")
ok(t.save_to(path), "saved")
t2 = T.DrawingTab(path)
t2.resize(1250, 800)
t2.show()
settle()
ok(len(t2.d.notes) == len(t.d.notes) and len(t2.d.balloons) == len(t.d.balloons) and len(t2.d.lines) == len(t.d.lines), "the notes, balloons and drawn items are in the file")
ok([n["text"] for n in t2.d.notes] == [n["text"] for n in t.d.notes] and [b["text"] for b in t2.d.balloons] == [b["text"] for b in t.d.balloons], "they say the same")
ok(t2.d.counter["note"] == t.d.counter["note"] and t2.d.counter["balloon"] == t.d.counter["balloon"] and t2.d.counter["draw"] == t.d.counter["draw"], "and carry on counting")
t2.canvas.fit()
t.canvas.fit()
settle()
im1, im2 = t.canvas.grab().toImage(), t2.canvas.grab().toImage()
same = sum(1 for x in range(0, im1.width(), 3) for y in range(0, im1.height(), 3) if im1.pixel(x, y) == im2.pixel(x, y)) / ((im1.width() // 3 + 1) * (im1.height() // 3 + 1))
ok(same > 0.97, f"the opened drawing looks the same as the one that was saved ({same:.3f})")
t2.close()

# ---------------------------------------------------------------------------------------------------------------------------- the PDF
pdf = os.path.join(tmp, "items.pdf")
ok(t.export_pdf(pdf) == pdf and os.path.getsize(pdf) > 0, "exported")
import fitz
page = fitz.open(pdf)[0]
words = page.get_text()
ok("MATERIAL: STEEL" in words and "Drill 16 thru" in words and "Break all" in words and "sharp edges" in words, f"the notes are text in the PDF ({words.split()[:6]})")
ok(all(x in words.split() for x in ("1", "2", "A")), "so are the numbers of the balloons")
draw = page.get_drawings()
mm = 72.0 / 25.4
H_pt = page.rect.height


def has_path(x0, y0, x1, y1, tol_pt=1.5):
    """A vector path whose box is (x0, y0, x1, y1) of the sheet (mm, y up)."""
    for d_ in draw:
        r_ = d_["rect"]
        if abs(r_.x0 - x0 * mm) < tol_pt and abs(r_.x1 - x1 * mm) < tol_pt and abs(r_.y0 - (H_pt - y1 * mm)) < tol_pt and abs(r_.y1 - (H_pt - y0 * mm)) < tol_pt:
            return True
    return False


rp = t.d.lines[0]["p"]
ok(has_path(rp[0][0], rp[0][1], rp[1][0], rp[1][1]), "the rectangle is a vector path of the right size at the right place")
cc_ = t.d.lines[1]
ok(has_path(cc_["c"][0] - cc_["r"], cc_["c"][1] - cc_["r"], cc_["c"][0] + cc_["r"], cc_["c"][1] + cc_["r"], 2.0), "so is the circle (its box is the circle's)")
fills = [d for d in draw if d.get("fill") is not None]
ok(len(fills) >= 4, f"the arrows of the leaders are filled shapes ({len(fills)} fills)")
rects = page.search_for("Drill 16 thru")
hmm = rects[0].height * 25.4 / 72 if rects else 0
ok(rects and 3.0 < hmm < 8.0, f"14 points: the text is {hmm:.1f} mm tall")

t.shutdown()
print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
