"""Drawings (dev add-on drawings): the Annotation tools in the window - Smart Dimension (click a line, a circle, an arc, or two things; the dimension follows the pointer and a click puts it
down; drag it later), Center Mark and Centerline, what is drawn (pixels: extension lines, the dimension line, arrows, the numbers, the cross, the dash-dot line), selecting / deleting /
dragging a dimension, Esc, undo, the numbers staying the model's when the scale changes, dimensions following a model that changes (and turning red when their geometry is gone), the file,
and the PDF (vector, the numbers are text).   python test_dr_dims_tab.py"""
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


tmp = tempfile.mkdtemp(prefix="dr_dims_")
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
s_, o_ = v["scale"], v["origin"]
S = lambda p: (o_[0] + s_ * p[0], o_[1] + s_ * p[1])           # a point of the view's frame on the sheet
ok(len(t.d.views) == 1 and near(s_, 1.0) and not t.d.dims, "the Top view of a 100 x 60 plate with a hole of 16 mm is on the sheet at 1:1, no dimension yet")
tol = 1.0 / cv.k


def click(x, y):
    QTest.mouseMove(cv, at(x, y))
    QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(x, y))
    settle()


def move(x, y):
    QTest.mouseMove(cv, at(x, y))
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


def dv(x, y, im=None):
    """dark_at for a point of the view's own frame."""
    return dark_at(*S((x, y)), im)


def tinted(x, y, test, im=None):
    """Some pixel next to a point of the view's frame whose colour passes `test(QColor)`."""
    im = im or cv.grab().toImage()
    c = at(*S((x, y)))
    return any(test(QColor(im.pixel(c.x() + dx, c.y() + dy))) for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2))


def outline_texts():
    out = []

    def walk(it):
        out.append(it.text(0))
        for i in range(it.childCount()):
            walk(it.child(i))
    for i in range(t.outline.tree.topLevelItemCount()):
        walk(t.outline.tree.topLevelItem(i))
    return out


# ---------------------------------------------------------------------------------------------------------------------------- the ribbon
ok(all(t.act[k].isEnabled() for k in ("dim", "center_mark", "centerline")), "Smart Dimension, Center Mark and Centerline are on the Annotation page, ready to use")
ok(not t.act["dim"].isChecked() and cv.tool is None, "no tool is open")
t.ribbon.setCurrentIndex(1)
t.act["dim"].click()
settle()
ok(cv.tool == "dim" and t.act["dim"].isChecked() and not t.act["center_mark"].isChecked(), "Smart Dimension opens (its button stays pressed)")
ok(t.props.currentWidget() is t.tool_panel and t.left.currentIndex() == 1 and t.tool_panel.title.text() == "Smart Dimension", "its panel is the Part window's property panel, with OK and Cancel")
ok("circle" in t.tool_panel.what.text() and "parallel" in t.tool_panel.what.text() and "angle" in t.tool_panel.what.text(), "which says what each click measures")
ok("Click a line" in t.hint_lbl.text(), "and the hint bar says what to click")

# ---------------------------------------------------------------------------------------------------------------------------- a length
n0 = len(t.undo_stack)
move(*S((50, 60)))
ok(cv.hover_pick is not None and cv.hover_pick[1]["k"] == "line", "the pointer over an edge: the edge lights up")
click(*S((50, 60)))
ok(cv.float_annot is not None and len(t.d.dims) == 1 and len(t.undo_stack) == n0, "a click on the top edge: its dimension follows the pointer (not in the undo list yet)")
d1 = t.d.dims[0]
ok(d1["type"] == "linear" and near(A.value(d1), 100.0), "the length of the edge: 100")
move(*S((50, 75)))
ok(d1["side"] == 1 and near(d1["dist"], 15.0, tol) and d1["mode"] == "h", f"it follows the pointer: 15 mm above the edge, horizontal ({d1['dist']:.1f})")
img = cv.grab().toImage()
ok(tinted(20, 75, lambda q: q.blue() - q.red() > 40, img) and tinted(80, 75, lambda q: q.blue() - q.red() > 40, img), "the dimension line is drawn (in the selection colour while it follows the pointer)")
click(*S((50, 75)))
ok(cv.float_annot is None and len(t.undo_stack) == n0 + 1 and t.is_dirty() and cv.tool == "dim", "a click puts it down: one undo step, the tool stays open for the next one")
img = cv.grab().toImage()
ok(dark_at(*S((0, 68)), img) and dark_at(*S((100, 68)), img), "the extension lines go up from the edge's ends")
ok(not dark_at(*S((-5, 68)), img) and not dark_at(*S((50, 66)), img), "nothing else is drawn between them")
cv.zoom(3.0, at=cv.to_screen(*S((1.5, 75))))                    # look closely at an end
zimg = cv.grab().toImage()
colw = lambda xv: dark_count(*S((xv, 73.5)), *S((xv, 76.5)), im=zimg)
ok(colw(2.4) >= colw(14.0) + 3, f"an arrow at the end: thicker than the line ({colw(2.4)} against {colw(14.0)} pixels)")
cv.fit()
settle()
img = cv.grab().toImage()
txt = dark_count(*S((44, 76.3)), *S((56, 79.3)), im=img)
ok(txt > 12, f"the number is written above the line ({txt} dark pixels)")
ok("100" in " ".join(outline_texts()), f"the Outline lists it under its view ({[x for x in outline_texts() if '100' in x]})")
ok(near(A.value(t.d.dims[0]), 100.0) and A.text(t.d.dims[0]) == "100", "it says 100")

# ---------------------------------------------------------------------------------------------------------------------------- a diameter
n1 = len(t.undo_stack)
click(*S((38, 30)))
ok(cv.float_annot is not None and t.d.dims[-1]["type"] == "diameter" and near(A.value(t.d.dims[-1]), 16.0), "a click on the hole: its diameter, 16")
click(*S((70, 50)))
dd = t.d.dims[-1]
ok(cv.float_annot is None and len(t.undo_stack) == n1 + 1 and A.text(dd) == "⌀16", "put down: ⌀16")
img = cv.grab().toImage()
ok(dv(30 + 26.8, 30 + 13.4, img), "a leader runs from the hole out to its label")
ok(abs(dd["lab"][0] - 40) < 1.0 and abs(dd["lab"][1] - 20) < 1.0, f"the label is where it was clicked, measured from the centre ({dd['lab']})")

# ---------------------------------------------------------------------------------------------------------------------------- a distance between two lines
n2 = len(t.undo_stack)
click(*S((0, 45)))
ok(cv.float_annot is not None and t.d.dims[-1]["type"] == "linear" and near(A.value(t.d.dims[-1]), 60.0), "the left edge: 60 long (it follows the pointer)")
nd = len(t.d.dims)
click(*S((100, 15)))
ok(len(t.d.dims) == nd and cv.float_annot is not None and near(A.value(t.d.dims[-1]), 100.0) and len(t.d.dims[-1]["refs"]) == 2,
   "a second click on the right edge: the dimension is now the distance between the two (100)")
move(*S((50, -12)))
click(*S((50, -12)))
dl = t.d.dims[-1]
ok(cv.float_annot is None and len(t.undo_stack) == n2 + 1 and dl["side"] == -1 and near(dl["dist"], 12.0, tol), "placed 12 mm below the plate: one undo step")
img = cv.grab().toImage()
ok(dark_at(*S((20, -12)), img) and dark_at(*S((80, -12)), img) and dark_at(*S((0, -6)), img), "its line is below the plate, with extension lines down from the edges")

# ---------------------------------------------------------------------------------------------------------------------------- an angle
n3 = len(t.undo_stack)
click(*S((70, 60)))
click(*S((100, 40)))
da = t.d.dims[-1]
ok(cv.float_annot == da["id"] and da["type"] == "angle" and near(A.value(da), 90.0), "the top edge and the right edge: the angle between them, 90°")
click(*S((88, 48)))
ok(cv.float_annot is None and len(t.undo_stack) == n3 + 1 and near(A.value(da), 90.0) and near(da["rho"], (12 ** 2 + 12 ** 2) ** 0.5, 0.5), f"inside the corner, the arc as far out as the pointer ({da['rho']:.1f})")
img = cv.grab().toImage()
ok(dv(88, 48, img), "the arc is drawn round the corner, through the point that was clicked")
ok(A.text(da) == "90°", "it says 90°")

# ---------------------------------------------------------------------------------------------------------------------------- Esc, one thing at a time
n4 = len(t.undo_stack)
nd = len(t.d.dims)
click(*S((50, 0)))
ok(cv.float_annot is not None and len(t.d.dims) == nd + 1 and cv.picks, "the bottom edge picked")
QTest.keyClick(cv, Qt.Key.Key_Escape)
settle()
ok(cv.float_annot is None and len(t.d.dims) == nd and not cv.picks and cv.tool == "dim" and len(t.undo_stack) == n4, "Esc takes away what is half done; the tool is still open")
click(*S((60, 30)))
ok(cv.float_annot is None and len(t.d.dims) == nd and "Nothing" in t.hint_lbl.text(), "a click on nothing says so")
move(*S((0, 0)))
click(*S((0, 0)))
ok(not cv.float_annot and len(cv.picks) == 1 and cv.picks[0][1]["k"] == "pt" and len(t.d.dims) == nd, "a corner is a point: one point alone measures nothing, the next click is waited for")
click(*S((100, 60)))
ok(cv.float_annot is not None and t.d.dims[-1]["type"] == "linear" and near(A.value(t.d.dims[-1]), (100 ** 2 + 60 ** 2) ** 0.5), "two corners: the distance between them (the diagonal)")
move(*S((60, 80)))
ok(t.d.dims[-1]["mode"] == "h" and near(A.value(t.d.dims[-1]), 100.0), "with the pointer above them it is measured horizontally")
move(*S((130, 30)))
ok(t.d.dims[-1]["mode"] == "v" and near(A.value(t.d.dims[-1]), 60.0), "beside them, vertically")
QTest.keyClick(cv, Qt.Key.Key_Escape)
settle()
QTest.keyClick(cv, Qt.Key.Key_Escape)
settle()
ok(cv.tool is None and not t.act["dim"].isChecked() and t.props.currentIndex() == 0 and len(t.d.dims) == nd, "Esc once more ends the tool: its button is up and the Outline is back")

# ---------------------------------------------------------------------------------------------------------------------------- center marks and centerlines
n5 = len(t.undo_stack)
t.act["center_mark"].click()
settle()
ok(cv.tool == "center_mark" and t.act["center_mark"].isChecked() and t.tool_panel.title.text() == "Center Mark", "Center Mark opens")
click(*S((60, 40)))
ok(not t.d.marks and "circle" in t.hint_lbl.text(), "a click that is not on a circle: nothing, and the hint says what to click")
click(*S((38, 30)))
ok(len(t.d.marks) == 1 and t.d.marks[0]["type"] == "center_mark" and len(t.undo_stack) == n5 + 1, "a click on the hole: a center mark, one undo step")
img = cv.grab().toImage()
ok(dv(30, 30, img) and dv(30 + 10, 30, img) and dv(30, 30 - 10, img) and not dv(30 + 12.5, 30, img), "a cross, a little larger than the hole (it reaches 3 mm past it)")
click(*S((30, 30)))
ok(len(t.d.marks) == 2, "the centre of the hole works too")
t.d.remove_annot(t.d.marks[1]["id"])
t.act["centerline"].click()
settle()
ok(cv.tool == "centerline" and not t.act["center_mark"].isChecked(), "Centerline replaces it")
n6 = len(t.undo_stack)
click(*S((70, 60)))
click(*S((0, 45)))
ok(len(t.d.marks) == 1 and "parallel" in t.hint_lbl.text(), "a line that meets the first one: not a centerline, and the hint says so (the line just clicked is the first one now)")
click(*S((100, 15)))
ok(len(t.d.marks) == 2 and t.d.marks[-1]["type"] == "centerline" and len(t.undo_stack) == n6 + 1, "left edge, then right edge: a centerline between them")
img = cv.grab().toImage()
marks = [dv(50, y, img) for y in [-2.9 + 0.5 * i for i in range(0, 124)]]
runs = sum(1 for i in range(1, len(marks)) if marks[i] and not marks[i - 1])
ok(runs >= 4 and 0.2 < sum(marks) / len(marks) < 0.95, f"it is dash-dot (dark runs: {runs}, {100 * sum(marks) // len(marks)} % dark)")
ok(dv(50, -2.0, img) and dv(50, -1.0, img), "and it starts a little before the edges (3 mm)")
QTest.keyClick(cv, Qt.Key.Key_Escape)
settle()
QTest.keyClick(cv, Qt.Key.Key_Escape)
settle()
ok(cv.tool is None, "(tool closed)")

# ---------------------------------------------------------------------------------------------------------------------------- select, drag, delete
d1 = t.d.dims[0]
click(*S((20, 75)))
ok(cv.sel_annot == d1["id"] and cv.sel is None and t.outline.cur_kind == "annot" and t.outline.cur_id == d1["id"] and t.outline.details.currentIndex() == 4,
   "a click on a dimension selects it: in the Outline and in the Details")
ok(t.outline.a_value.text() == "100" and t.outline.a_type.text() == "Dimension" and t.outline.a_view.text() == v["name"] and t.act["delete"].isEnabled(), "the Details say what it is and what it says")
img = cv.grab().toImage()
ok(tinted(20, 75, lambda q: q.blue() - q.red() > 60, img), "it is drawn in the selection colour")
n7 = len(t.undo_stack)
QTest.mousePress(cv, Qt.MouseButton.LeftButton, pos=at(*S((20, 75))))
QTest.mouseMove(cv, at(*S((20, 80))))
QTest.mouseMove(cv, at(*S((20, 85))))
QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, pos=at(*S((20, 85))))
settle()
ok(near(d1["dist"], 25.0, 2 * tol) and len(t.undo_stack) == n7 + 1, f"dragged up 10 mm: now 25 mm from the edge, one undo step ({d1['dist']:.1f})")
ok(near(d1["t"], 0.0) and near(A.value(d1), 100.0), "grabbed by its line, the number stays in the middle of it; it still says 100")
t.do_undo()
settle()
ok(near(t.d.dims[0]["dist"], 15.0, 2 * tol), "undo puts it back")
t.do_redo()
settle()
ok(near(t.d.dims[0]["dist"], 25.0, 2 * tol), "redo moves it again")
d1id = d1["id"]
nd = len(t.d.dims)
cv.set_selected_annot(None)
click(*S((50, 85 + 2.65)))
ok(cv.sel_annot == d1id, "a click on the number selects its dimension")
n8 = len(t.undo_stack)
dist_before = t.d.dims[0]["dist"]
QTest.mousePress(cv, Qt.MouseButton.LeftButton, pos=at(*S((50, 87.65))))
QTest.mouseMove(cv, at(*S((60, 87.65))))
QTest.mouseMove(cv, at(*S((70, 87.65))))
QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, pos=at(*S((70, 87.65))))
settle()
dn = t.d.dims[0]
ok(near(dn["t"], 20.0, 2 * tol) and near(dn["dist"], dist_before, 1e-9) and len(t.undo_stack) == n8 + 1, f"dragged by its number: the number slid 20 mm along the line, the line stayed ({dn['t']:.1f}, {dn['dist']:.1f})")
cv.set_selected_annot(None)
click(*S((20, 85)))
ok(cv.sel_annot == d1id, "it is where it was dragged to")
QTest.keyClick(cv, Qt.Key.Key_Delete)
settle()
ok(len(t.d.dims) == nd - 1 and cv.sel_annot is None and not any(a["id"] == d1id for a in t.d.dims), "Delete removes the selected dimension")
t.do_undo()
settle()
ok(len(t.d.dims) == nd and any(a["id"] == d1id for a in t.d.dims), "undo brings it back")
cv.set_selected_annot(d1id)
t.act["delete"].click()
settle()
ok(len(t.d.dims) == nd - 1, "the Delete button of the ribbon deletes it too")
t.do_undo()
settle()
# a click on empty sheet and on a view
click(150, 30)
ok(cv.sel_annot is None and cv.sel is None, "a click on empty sheet selects nothing")
click(*S((100, 30)))
ok(cv.sel == v["id"] and cv.sel_annot is None, "a click on the plate itself selects the view (not a dimension)")

# ---------------------------------------------------------------------------------------------------------------------------- the scale
vid = v["id"]
dsc = t.d.dims[0]
lv = t.d.view(vid)
before = A.shape(dsc, lv["scale"], lv["origin"])["segs"][-1]
t.set_view_scale(vid, "2:1")
settle()
lv = t.d.view(vid)
dsc = t.d.dims[0]
after = A.shape(dsc, lv["scale"], lv["origin"])["segs"][-1]
len_b = abs(before[1][0] - before[0][0])
len_a = abs(after[1][0] - after[0][0])
ok(near(len_a, 2 * len_b, 1e-6) and A.text(dsc) == "100" and near(dsc["dist"], 25.0, 2 * tol), f"at 2:1 the dimension line is twice as long ({len_b:.0f} -> {len_a:.0f} mm on paper), the number still says 100 and its distance from the edge is the same")
t.set_view_scale(vid, "1:1")
settle()
ok(near(t.d.view(vid)["scale"], 1.0) and near(A.value(t.d.dims[0]), 100.0), "back at 1:1")

# ---------------------------------------------------------------------------------------------------------------------------- the model changes
out = t.sync_models([{"src": "n1", "name": "Plate", "kind": "part", "data": plate(150, 60)}])
ok(out["refreshed"] == ["Plate"] and out["lost"] == 0, "the plate wired into the block grew to 150: its views are drawn again, nothing is lost")
settle()
lens = sorted(round(A.value(a), 3) for a in t.d.dims if a["type"] == "linear")
ok(lens.count(150.0) == 2, f"the dimension of its top edge and the one between its side edges say 150 ({lens})")
ok(len(t.d.marks) == 2, "the center mark and the centerline are still there")
dia = [a for a in t.d.dims if a["type"] == "diameter"][0]
ok(near(A.value(dia), 16.0) and tuple(dia["refs"][0]["c"]) == (30.0, 30.0), "the hole did not change: ⌀16 is still there")
ang = [a for a in t.d.dims if a["type"] == "angle"][0]
ok(near(A.value(ang), 90.0), "and so is the 90° of the corner")
no_hole = plate(150, 60, hole=False)
out = t.sync_models([{"src": "n1", "name": "Plate", "kind": "part", "data": no_hole}])
settle()
ok(out["lost"] == 2 and "lost" in t.status.full, f"the hole is gone from the model: the sync reports 2 lost and the status line says so ({t.status.full[:70]})")
lost = t.d.lost_annots()
ok(len(lost) == 2 and {a["type"] for a in lost} == {"diameter", "center_mark"}, f"the hole is gone: its diameter and its center mark are lost ({[a['type'] for a in lost]})")
ok(any("(lost)" in x for x in outline_texts()), "the Outline says so")
img = cv.grab().toImage()
ok(tinted(30 + 26.8, 30 + 13.4, lambda q: q.red() - q.green() > 50, img), "the lost dimension is drawn in red")
t.canvas.set_selected_annot(dia["id"])
ok("not in the model" in t.outline.a_state.text() and t.outline.details.currentIndex() == 4, "its Details say why")
t.do_undo()
settle()
ok(len(t.d.lost_annots()) == 0 and any(a["type"] == "diameter" and not a["lost"] for a in t.d.dims), "undo brings the hole and the dimension back")
# the status line of a refresh that loses things
t.d.refresh_model(t.d.models[0]["id"], no_hole)
t.refresh_views()
settle()
ok("lost" in t.status.full.lower(), f"Refresh Views says what was lost ({t.status.full[:90]})")
t.do_undo()
settle()
ok(not t.d.lost_annots(), "(undone)")

# ---------------------------------------------------------------------------------------------------------------------------- another direction: nothing to hold on to
dm_n = len(t.d.annots())
t.set_view_orient(v["id"], "Front")
settle()
ok(not t.d.annots() and "removed" in t.status.full, f"the view looks from the front now: its dimensions and marks are gone, and the status line says so ({t.status.full[:80]})")
t.do_undo()
settle()
ok(len(t.d.annots()) == dm_n and t.d.view(v["id"])["orient"] == "Top", "undo brings the direction and the dimensions back")

# ---------------------------------------------------------------------------------------------------------------------------- the file
t.canvas.set_selected_annot(None)
t.canvas.set_selected(None)
path = os.path.join(tmp, "dims.opdraw")
ok(t.save_to(path), "saved")
t2 = T.DrawingTab(path)
t2.resize(1250, 800)
t2.show()
settle()
ok(len(t2.d.dims) == len(t.d.dims) and len(t2.d.marks) == len(t.d.marks), "the dimensions and marks are in the file")
ok([A.text(a) for a in t2.d.dims] == [A.text(a) for a in t.d.dims], f"they say the same: {[A.text(a) for a in t2.d.dims]}")
ok(any("⌀16" in x for x in [PN.annot_text(a) for a in t2.d.dims]) and any("Center Mark" in x for x in [PN.annot_text(a) for a in t2.d.marks]), "and the Outline lists them")
t2.canvas.fit()
t.canvas.fit()
settle()
im1, im2 = t.canvas.grab().toImage(), t2.canvas.grab().toImage()
same = sum(1 for x in range(0, im1.width(), 3) for y in range(0, im1.height(), 3) if im1.pixel(x, y) == im2.pixel(x, y)) / ((im1.width() // 3 + 1) * (im1.height() // 3 + 1))
ok(same > 0.97, f"the opened drawing looks the same as the one that was saved ({same:.3f})")
t2.close()

# ---------------------------------------------------------------------------------------------------------------------------- the PDF
pdf = os.path.join(tmp, "dims.pdf")
ok(t.export_pdf(pdf) == pdf and os.path.getsize(pdf) > 0, "exported")
import fitz
page = fitz.open(pdf)[0]
words = page.get_text()
ok("150" in words and "⌀16" in words and "90°" in words, f"the numbers of the dimensions are text in the PDF ({words.split()[:8]})")
draw = page.get_drawings()
ok(len(draw) > 6, f"and the lines are vector drawings ({len(draw)} paths)")
fills = [d for d in draw if d.get("fill") is not None]
ok(len(fills) >= 4, f"with filled arrowheads ({len(fills)} fills)")
rects = page.search_for("150")
top = [r for r in rects if r.y0 < page.rect.height / 2.0]
ok(bool(top), "the number 150 is on the sheet where the top dimension is (above the plate)")
hmm = rects[0].height * 25.4 / 72
ok(4.0 < hmm < 8.0, f"3.5 mm lettering: the text box is {hmm:.1f} mm tall")

t.shutdown()
print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
