"""Drawings (dev add-on drawings): Linear Note Pattern in the window - the ribbon button, picking the note, the direction / spacing / number of notes (two directions) in the panel, a
direction taken from a line of a view, what is painted (pixels), the Details of a note, moving a pattern, refusals in words, undo, the file and the PDF (the text repeated as text).
python test_dr_pattern_tab.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import math
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



def copies(n):
    """The boxes of a note and of its copies, as the canvas draws them."""
    return cv.r.shape(n)["boxes"]


def lit(box, im=None):
    return dark_count(box[0], box[1], box[2], box[3], im or cv.grab().toImage())


def sheet_note(text, x, y, size=14.0):
    """A note without a leader, put down with the Note tool like a person does."""
    t.act["note"].click()
    settle()
    t.tool_panel.n_leader.setCurrentIndex(0)
    t.tool_panel.n_text.setPlainText(text)
    t.tool_panel.n_size.setEditText(str(size))
    t.tool_panel.options_edited()
    click(x, y)
    key(Qt.Key.Key_Escape)
    ok(cv.tool is None, f"the note '{text}' is on the sheet and the tool is ended")
    return t.d.notes[-1]


# ---------------------------------------------------------------------------------------------------------------------------- the button
t.ribbon.setCurrentIndex(1)
b = t.act["note_pattern"]
ok(b.isEnabled() and b.isCheckable() and "not built yet" not in b.toolTip() and "Linear Note" in b.text(), "Linear Note Pattern is on the Annotation page, ready to use")
t.act["note_pattern"].click()
settle()
ok(cv.tool == "note_pattern" and b.isChecked() and not t.act["select"].isChecked() and t.props.currentWidget() is t.tool_panel, "it opens its panel")
tp = t.tool_panel
ok(tp.title.text() == "Linear Note Pattern" and tp.opt_pattern.isVisibleTo(tp) and not tp.opt_note.isVisibleTo(tp) and not tp.opt_balloon.isVisibleTo(tp), "which has the pattern's boxes, not a note's or a balloon's")
ok("Click the note" in tp.p_note.text() and not tp.p_dir[1].isEnabled() and not tp.p_dir[2].isEnabled() and not tp.p_remove.isEnabled(), "before a note is clicked the boxes are off and the panel says what to click")
ok("note" in t.hint_lbl.text().lower() and "Click" in t.hint_lbl.text(), f"and so does the hint bar ({t.hint_lbl.text()[:50]})")
n_undo = len(t.undo_stack)
click(150, 30)
ok(not t.d.notes and len(t.undo_stack) == n_undo and "not a note" in t.hint_lbl.text(), "a click on the bare sheet takes nothing (and says so)")
click(*S((0.0, 45.0)))
ok(len(t.undo_stack) == n_undo and cv.pattern_note is None, "nor does a click on the edge of the view")
key(Qt.Key.Key_Escape)
ok(cv.tool is None and t.act["select"].isChecked() and not b.isChecked(), "Esc ends the tool")

# ---------------------------------------------------------------------------------------------------------------------------- the first pattern
note = sheet_note("R6 TYP", 20.0, 30.0)
nid = note["id"]
box0 = cv.r.shape(note)["box"]
w0 = box0[2] - box0[0]
ok(not note.get("pattern") and len(copies(note)) == 1, "a note on its own is one note")
n_undo = len(t.undo_stack)
t.act["note_pattern"].click()
settle()
click(box0[0] + 2.0, box0[3] - 1.0)
n = t.d.notes[0]
ok(n["pattern"] is not None and cv.pattern_note == nid and cv.sel_annot == nid and len(t.undo_stack) == n_undo + 1, "a click on the note gives it a pattern (one undo step) and keeps it selected")
bxs = copies(n)
ok(len(bxs) == 3 and near(n["pattern"]["a1"], 0.0) and near(bxs[1][0] - bxs[0][0], n["pattern"]["s1"]) and near(bxs[2][0] - bxs[0][0], 2.0 * n["pattern"]["s1"]), "three notes in a row, one spacing apart")
im = cv.grab().toImage()
ok(all(lit(bx, im) > 30 for bx in bxs), f"all three are drawn ({[lit(bx, im) for bx in bxs]} dark pixels)")
gap = (bxs[0][2] + 1.0, bxs[0][1], bxs[1][0] - 1.0, bxs[0][3])
ok(gap[2] > gap[0] and lit(gap, im) == 0, "and nothing is between them")
ok(tp.p_note.text() == "Note:  R6 TYP" and tp.p_dir[1].isEnabled() and tp.p_dir[2].isEnabled() and tp.p_remove.isEnabled(), "the panel names the note and its boxes are on")
d1, d2 = tp.p_dir[1], tp.p_dir[2]
ok(near(d1.angle.value(), 0.0) and near(d1.space.value(), n["pattern"]["s1"]) and d1.count.value() == 3 and d2.count.value() == 1, "direction 1 shows 0°, the spacing and 3 notes; direction 2 shows 1 note")
ok("Direction taken" not in t.hint_lbl.text() and "panel" in t.hint_lbl.text(), "the hint says to use the panel now")

# ---------------------------------------------------------------------------------------------------------------------------- the boxes of the panel
n_undo = len(t.undo_stack)
d1.count.setValue(5)
settle()
ok(len(copies(t.d.notes[0])) == 5 and t.d.notes[0]["pattern"]["c1"] == 5 and len(t.undo_stack) == n_undo + 1, "5 notes: five are drawn (one undo step)")
d1.space.setValue(30.0)
d1.space.editingFinished.emit()
settle()
bxs = copies(t.d.notes[0])
ok(near(bxs[4][0] - bxs[0][0], 120.0) and near(t.d.notes[0]["pattern"]["s1"], 30.0), "a spacing of 30 mm: the fifth is 120 mm from the first")
im = cv.grab().toImage()
ok(all(lit(bx, im) > 30 for bx in bxs) and bxs[4][2] < t.d.sheet_dims()[0], f"all five are drawn, on the sheet ({[lit(bx, im) for bx in bxs]})")
d1.vert.click()
settle()
bxs = copies(t.d.notes[0])
ok(near(t.d.notes[0]["pattern"]["a1"], 90.0) and all(near(bx[0], bxs[0][0]) for bx in bxs) and near(bxs[4][1] - bxs[0][1], 120.0), "Vertical: the notes are in a column, going up")
im = cv.grab().toImage()
ok(all(lit(bx, im) > 30 for bx in bxs), f"all five are drawn ({[lit(bx, im) for bx in bxs]})")
d1.count.setValue(3)
d1.space.setValue(-10.0)
d1.space.editingFinished.emit()
settle()
bxs = copies(t.d.notes[0])
ok(len(bxs) == 3 and near(bxs[2][1] - bxs[0][1], -20.0) and near(bxs[2][0], bxs[0][0]) and bxs[2][1] > 0.0, "a negative spacing: the column goes down")
im = cv.grab().toImage()
ok(all(lit(bx, im) > 30 for bx in bxs), "and is drawn there")
d1.horiz.click()
d1.space.setValue(30.0)
d1.space.editingFinished.emit()
d1.count.setValue(3)
settle()
ok(near(t.d.notes[0]["pattern"]["a1"], 0.0) and len(copies(t.d.notes[0])) == 3, "Horizontal and 3 notes again")
d1.angle.setValue(30.0)
d1.angle.editingFinished.emit()
settle()
bxs = copies(t.d.notes[0])
ok(near(bxs[1][0] - bxs[0][0], 30.0 * math.cos(math.radians(30.0))) and near(bxs[1][1] - bxs[0][1], 15.0), "an angle of 30°: each note is 26 mm along and 15 mm up from the one before")
d1.angle.setValue(0.0)
d1.angle.editingFinished.emit()
settle()

# a second direction
d2.count.setValue(2)
d2.space.setValue(-12.0)
d2.space.editingFinished.emit()
settle()
n = t.d.notes[0]
bxs = copies(n)
ok(len(bxs) == 6 and near(n["pattern"]["a2"], 90.0) and near(n["pattern"]["s2"], -12.0) and n["pattern"]["c2"] == 2, "a second row: 3 by 2 notes")
ok(near(bxs[3][1] - bxs[0][1], -12.0) and near(bxs[3][0], bxs[0][0]), "12 mm under the first row (a negative spacing along 90° goes down)")
im = cv.grab().toImage()
ok(all(lit(bx, im) > 30 for bx in bxs), f"all six are drawn ({[lit(bx, im) for bx in bxs]})")
rowgap = (bxs[0][0], bxs[3][3] + 0.5, bxs[2][2], bxs[0][1] - 0.5)
ok(rowgap[3] > rowgap[1] and lit(rowgap, im) == 0, "with clear space between the rows")
d2.horiz.click()
settle()
ok(near(t.d.notes[0]["pattern"]["a2"], 0.0), "direction 2 can be set the same way")
d2.vert.click()
settle()
ok(near(t.d.notes[0]["pattern"]["a2"], 90.0), "and back")
tb = tp.p_dir[1]
ok(tb.count.minimum() == 1 and tb.count.maximum() == IT.MAX_COPIES, "the number of notes is between 1 and 400")

# ---------------------------------------------------------------------------------------------------------------------------- refusals
before = dict(t.d.notes[0]["pattern"])
n_undo = len(t.undo_stack)
d1.count.setValue(300)
settle()
ok(t.d.notes[0]["pattern"] == before and len(t.undo_stack) == n_undo, "300 by 2 notes is too many: nothing changed, no undo step")
ok("at most 400" in t.status.full, f"the status line says why ({t.status.full[:60]})")
ok(d1.count.value() == before["c1"], "and the box shows what it was")
d1.space.setValue(0.0)
d1.space.editingFinished.emit()
settle()
ok(t.d.notes[0]["pattern"] == before and "at least 0.1" in t.status.full, f"no spacing between 3 notes: refused ({t.status.full[:60]})")
ok(near(d1.space.value(), before["s1"]), "and the box shows the spacing it was")

# ---------------------------------------------------------------------------------------------------------------------------- the direction of a line
d2.count.setValue(1)
settle()
d1.pick.click()
settle()
ok(cv.pattern_pick == 1 and d1.pick.isChecked() and "Click a line" in t.hint_lbl.text(), "Pick line: the next click on a line of a view gives the direction")
n_undo = len(t.undo_stack)
click(150, 30)
ok(cv.pattern_pick == 1 and t.d.notes[0]["pattern"]["a1"] == before["a1"] and len(t.undo_stack) == n_undo and "not a line" in t.hint_lbl.text(), "a click that is not on a line takes nothing, and the pick goes on")
move(*S((0.0, 45.0)))
ok(cv.hover_pick is not None and cv.hover_pick[1]["k"] == "line", "the line under the pointer is shown")
click(*S((0.0, 45.0)))
settle()
ok(cv.pattern_pick == 0 and not d1.pick.isChecked() and near(t.d.notes[0]["pattern"]["a1"], 90.0), f"the left edge of the plate is vertical: direction 1 is now 90° ({t.d.notes[0]['pattern']['a1']})")
ok(len(t.undo_stack) == n_undo + 1 and near(d1.angle.value(), 90.0), "one undo step; the box shows it")
d1.pick.click()
click(*S((70.0, 60.0)))
settle()
ok(near(t.d.notes[0]["pattern"]["a1"], 0.0), f"the top edge is horizontal: 0° ({t.d.notes[0]['pattern']['a1']})")
d1.pick.click()
settle()
ok(cv.pattern_pick == 1, "Pick line is on")
key(Qt.Key.Key_Escape)
ok(cv.pattern_pick == 0 and not d1.pick.isChecked() and cv.tool == "note_pattern" and cv.pattern_note == nid, "Esc takes back the pick only: the tool and the note stay")
d2.pick.click()
settle()
click(*S((0.0, 45.0)))
settle()
ok(near(t.d.notes[0]["pattern"]["a2"], 90.0) and cv.pattern_pick == 0, "a line can give direction 2 as well")

# ---------------------------------------------------------------------------------------------------------------------------- another note, then end
other = sheet_note("DEBURR", 20.0, 60.0)
t.act["note_pattern"].click()
settle()
ok(cv.pattern_note is None, "the tool starts with no note when none is selected")
bx3 = copies(t.d.notes[0])[2]
click((bx3[0] + bx3[2]) / 2.0, (bx3[1] + bx3[3]) / 2.0)
ok(cv.pattern_note == nid, "a click on the third copy takes the note, the same as a click on the note")
bo = cv.r.shape(t.d.notes[1])["box"]
click(bo[0] + 2.0, bo[3] - 1.0)
ok(cv.pattern_note == other["id"] and t.d.notes[1]["pattern"] is not None and tp.p_note.text() == "Note:  DEBURR", "another note: it gets a first pattern of its own and the panel follows")
ok(t.d.notes[0]["pattern"]["c1"] == 3, "the first note's pattern is as it was")
key(Qt.Key.Key_Escape)
ok(cv.tool == "note_pattern" and cv.pattern_note is None and "Click the note" in tp.p_note.text(), "Esc: the note is let go, the tool stays")
key(Qt.Key.Key_Escape)
ok(cv.tool is None, "Esc again ends the tool")
tp.p_dir[1].count.setValue(1)
t.d.set_pattern(other["id"], remove=True)
t.canvas.r.cache.clear()
t.commit("pattern")

# ---------------------------------------------------------------------------------------------------------------------------- the Details of a note
cv.set_selected_annot(nid)
settle()
ok(t.outline.details.currentIndex() == 5 and "notes" in t.outline.n_pat.text() and t.outline.n_pat_edit.text() == "Edit pattern..." and not t.outline.n_pat_off.isHidden(), f"the Details of a note with a pattern tell it ({t.outline.n_pat.text()})")
ok(t.outline.n_pat.text() == IT.pattern_text(t.d.notes[0]["pattern"]), "in the same words as everywhere")
cv.set_selected_annot(other["id"])
settle()
ok(t.outline.n_pat.text() == "none" and t.outline.n_pat_edit.text() == "Repeat..." and t.outline.n_pat_off.isHidden(), "a note without one says 'none' and offers to repeat it")
cv.set_selected_annot(nid)
settle()
t.outline.n_pat_edit.click()
settle()
ok(cv.tool == "note_pattern" and cv.pattern_note == nid and d1.count.value() == 3 and tp.p_note.text() == "Note:  R6 TYP", "Edit pattern...: the tool opens with this note")
key(Qt.Key.Key_Escape)
key(Qt.Key.Key_Escape)
cv.set_selected_annot(other["id"])
settle()
t.outline.n_pat_edit.click()
settle()
ok(cv.tool == "note_pattern" and cv.pattern_note == other["id"] and t.d.notes[1]["pattern"]["c1"] == 3, "Repeat... on a note without one: it gets the first pattern")
t.finish_tool()
cv.set_selected_annot(other["id"])
settle()
n_undo = len(t.undo_stack)
t.outline.n_pat_off.click()
settle()
ok(not t.d.notes[1]["pattern"] and len(t.undo_stack) == n_undo + 1 and t.outline.n_pat.text() == "none", "Remove pattern in the Details: the copies go, the note stays")
t.do_undo()
ok(t.d.notes[1]["pattern"] and len(copies(t.d.notes[1])) == 3, "undo brings the copies back")
t.do_redo()
ok(not t.d.notes[1]["pattern"], "redo takes them away again")
n_undo = len(t.undo_stack)
t.set_note_pattern(other["id"], remove=True)
ok(len(t.undo_stack) == n_undo, "taking away a pattern that is not there is not a step to undo")
t.set_note_pattern(nid, **t.d.notes[0]["pattern"])
t.set_note_pattern(nid, c1=t.d.notes[0]["pattern"]["c1"])
ok(len(t.undo_stack) == n_undo, "nor is setting what is already set")
t.set_note_pattern("n99", c1=2)
t.set_note_pattern(other["id"], c1=2, c2=2)
ok(len(t.undo_stack) == n_undo + 1 and t.d.notes[1]["pattern"]["c1"] == 2, "a pattern asked for by number: the first pattern, with these numbers (one step)")
t.do_undo()

# the panel's own button
cv.set_selected_annot(None)
t.act["note_pattern"].click()
bo = cv.r.shape(t.d.notes[0])["box"]
click(bo[0] + 2.0, bo[3] - 1.0)
n_undo = len(t.undo_stack)
tp.p_remove.click()
settle()
ok(not t.d.notes[0]["pattern"] and len(copies(t.d.notes[0])) == 1 and len(t.undo_stack) == n_undo + 1 and not d1.isEnabled(), "Remove the pattern: one note again; the boxes are off")
t.do_undo()
ok(cv.tool is None and t.d.notes[0]["pattern"] is not None and len(copies(t.d.notes[0])) == 3, "undo ends the tool and gives the pattern back")
bx = copies(t.d.notes[0])
ok(all(lit(b_) > 30 for b_ in bx), "all three are painted again")

# ---------------------------------------------------------------------------------------------------------------------------- moving and selecting
cv.set_selected_annot(None)
bx = copies(t.d.notes[0])
b2 = bx[1]
drag((b2[0] + b2[2]) / 2.0, (b2[1] + b2[3]) / 2.0, (b2[0] + b2[2]) / 2.0 + 10.0, (b2[1] + b2[3]) / 2.0 + 20.0)
n = t.d.notes[0]
bx2 = copies(n)
ok(cv.sel_annot == nid and all(P((bx2[i][0], bx2[i][1]), (bx[i][0] + 10.0, bx[i][1] + 20.0)) for i in range(3)), "dragging the second copy moves the whole note, and all its copies with it")
ok(P(n["pos"], (30.0, 50.0)) and n["pattern"]["c1"] == 3, "the note itself is 10 right and 20 up; the pattern is as it was")
im = cv.grab().toImage()
ok(all(lit(b_, im) > 30 for b_ in bx2) and all(lit(b_, im) == 0 for b_ in bx), "and they are painted in the new place, and no longer in the old")
t.do_undo()
ok(P(t.d.notes[0]["pos"], (20.0, 30.0)), "undo puts them back")

# ---------------------------------------------------------------------------------------------------------------------------- a note with a leader
t.act["note"].click()
settle()
t.tool_panel.n_leader.setCurrentIndex(t.tool_panel.n_leader.findData("straight"))
t.tool_panel.n_text.setPlainText("Drill 16 thru")
t.tool_panel.n_size.setEditText("14")
t.tool_panel.options_edited()
tipx, tipy = S((0.0, 45.0))
click(tipx, tipy)                                          # the left edge of the plate
click(tipx - 40.0, tipy - 25.0)
key(Qt.Key.Key_Escape)
ln = t.d.notes[-1]
ok(ln["leader"] and ln["leader"]["view"] == vid and not ln.get("pattern"), "a note with a leader to the edge of the plate")
t.act["note_pattern"].click()
bl = cv.r.shape(ln)["box"]
click((bl[0] + bl[2]) / 2.0, (bl[1] + bl[3]) / 2.0)
settle()
t.d.set_pattern(ln["id"], a1=90.0, s1=-12.0, c1=3)
t.commit("pattern")
shp = cv.r.shape(ln)
ok(len(shp["boxes"]) == 3 and len(shp["segs"]) == 3 and len(shp["heads"]) == 3, "three notes, three leaders, three arrows")
tip0 = t.d.leader_tip(ln)
ok(P(shp["segs"][0][0], tip0) and P(shp["segs"][1][0], (tip0[0], tip0[1] - 12.0)) and P(shp["segs"][2][0], (tip0[0], tip0[1] - 24.0)), "each leader ends 12 mm lower than the one before")
im = cv.grab().toImage()
ok(all(lit(bx_, im) > 30 for bx_ in shp["boxes"]), "all three texts are painted")
ok(dark_at(*shp["segs"][1][0], im) and dark_at(*shp["segs"][2][0], im), "and the tips of the copies' leaders are painted")
mid1 = seg_mid(shp, 1)
ok(dark_at(*mid1, im), "so is the middle of the second leader")
t.finish_tool()
import fitz
pdf_a = os.path.join(tmp, "leaders.pdf")
t.export_pdf(pdf_a)
fills_with = len([d_ for d_ in fitz.open(pdf_a)[0].get_drawings() if d_.get("fill") is not None])
t.d.set_pattern(ln["id"], remove=True)
t.commit("pattern")
t.export_pdf(pdf_a)
fills_without = len([d_ for d_ in fitz.open(pdf_a)[0].get_drawings() if d_.get("fill") is not None])
ok(fills_with - fills_without == 2, f"in the PDF the two copies have their arrows too: filled shapes {fills_without} -> {fills_with}")
t.do_undo()
t.do_undo()
t.do_undo()

# ---------------------------------------------------------------------------------------------------------------------------- the file
t.d.set_pattern(nid, c1=4, s1=25.0, a1=0.0, c2=2, s2=-8.0)
t.commit("pattern")
cv.set_selected_annot(None)
cv.set_selected(None)
path = os.path.join(tmp, "pattern.opdraw")
ok(t.save_to(path), "saved")
t2 = T.DrawingTab(path)
t2.resize(1250, 800)
t2.show()
settle()
ok(t2.d.notes[0]["pattern"] == t.d.notes[0]["pattern"] and len(t2.canvas.r.shape(t2.d.notes[0])["boxes"]) == 8, "the pattern is in the file: 4 by 2 notes after opening")
t2.canvas.fit()
t.canvas.fit()
settle()
im1, im2 = t.canvas.grab().toImage(), t2.canvas.grab().toImage()
same = sum(1 for x in range(0, im1.width(), 3) for y in range(0, im1.height(), 3) if im1.pixel(x, y) == im2.pixel(x, y)) / ((im1.width() // 3 + 1) * (im1.height() // 3 + 1))
ok(same > 0.97, f"the opened drawing looks the same as the one that was saved ({same:.3f})")
t2.close()

# ---------------------------------------------------------------------------------------------------------------------------- the PDF
pdf = os.path.join(tmp, "pattern.pdf")
ok(t.export_pdf(pdf) == pdf and os.path.getsize(pdf) > 0, "exported")
page = fitz.open(pdf)[0]
words = page.get_text().split()
ok(words.count("R6") == 8 and words.count("TYP") == 8, f"the note is text in the PDF, eight times ({words.count('R6')} R6, {words.count('TYP')} TYP)")
hits = sorted(page.search_for("R6 TYP"), key=lambda r: (round(r.y0), r.x0))
mm = 72.0 / 25.4
ok(len(hits) == 8, f"eight places for the text ({len(hits)})")
row1, row2 = hits[:4], hits[4:]
ok(all(abs((row1[i + 1].x0 - row1[i].x0) - 25.0 * mm) < 1.0 for i in range(3)), "25 mm between the notes of a row, at true paper size")
ok(abs((row2[0].y0 - row1[0].y0) - 8.0 * mm) < 1.0 and abs(row2[0].x0 - row1[0].x0) < 1.0, "the second row is 8 mm lower (the page's y goes down)")

t.shutdown()
print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
