"""Drawings (dev add-on drawings): the window - the sheet dialog (standard sizes only, preview), the Model View command (the view follows the pointer and is put down where it is clicked,
Esc takes it away), the Projected View command (pick the parent, move to a side, click; the view slides along its axis only), the Details (scale typed or listed, display style,
orientation), what is drawn on the screen (pixels: the sheet, the lines, hidden lines dashed or not), undo and redo, the file, the PDF at true paper size, and the models a Workbench
block feeds in.   python test_dr_tab.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import pm_app
pm_app.apply_theme(app)
import dr_canvas as C
import dr_model as M
import dr_panels as PN
import dr_sheet as S
import dr_tab as T
import wb_example as ex

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


bar, _sid = ex.part_doc(100, 20, 10)
bar2, _s2 = ex.part_doc(150, 20, 10)
tmp = tempfile.mkdtemp(prefix="dr_tab_")

# ---------------------------------------------------------------------------------------------------------------------------- the sheet dialog
dlg = PN.NewDrawingDialog()
keys = [dlg.sizes.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dlg.sizes.count())]
ok(keys == [s[0] for s in S.SIZES] and len(keys) == 10, "the dialog lists the ten standard sizes (ANSI A-E, ISO A4-A0) and nothing else")
ok(dlg.result_sheet() == {"size": "ansi_a", "landscape": True, "first_angle": False}, "it starts on Letter, landscape, third angle")
ok(dlg.preview.size_key == "ansi_a" and dlg.preview.landscape, "the preview shows that sheet")
dlg.sizes.setCurrentRow(keys.index("iso_a3"))
dlg.port.setChecked(True)
dlg.proj.setCurrentIndex(1)
ok(dlg.result_sheet() == {"size": "iso_a3", "landscape": False, "first_angle": True} and dlg.preview.size_key == "iso_a3" and not dlg.preview.landscape,
   "A3, portrait, first angle: the result and the preview follow")
img = dlg.preview.grab().toImage()
cx, cy = img.width() // 2, (img.height() - 44) // 2
ok(QColor(img.pixel(cx, cy)).name() == "#ffffff" and QColor(img.pixel(4, 4)).name() == "#a9b1bf", "the preview draws a white sheet on the grey ground")
dlg.close()

# ---------------------------------------------------------------------------------------------------------------------------- the window
t = T.DrawingTab()
t.resize(1250, 800)
t.show()
settle()
cv = t.canvas
ok(t.d.sheet == {"size": "ansi_a", "landscape": True, "first_angle": False} and not t.d.views, "a new drawing is Letter landscape and empty")
ok([t.ribbon.tabText(i) for i in range(t.ribbon.count())] == ["View Layout", "Annotation", "Sketch"] and t.ribbon.tabPosition() == t.ribbon.TabPosition.South, "the ribbon is the Part window's: pages with the tab strip under the buttons")
ok(not t.act["undo"].isEnabled() and not t.act["delete"].isEnabled(), "nothing to undo and nothing to delete yet")
ok(t.left.currentIndex() == 0 and t.outline.tree.topLevelItemCount() == 1, "the left column opens on the Outline")
img = cv.grab().toImage()
sw, sh_ = t.d.sheet_dims()
p_in = cv.to_screen(sw / 2, sh_ - 5).toPoint()
p_out = cv.to_screen(-10, sh_ / 2).toPoint()
ok(QColor(img.pixel(p_in)).name() == "#ffffff" and QColor(img.pixel(p_out)).name() == "#a9b1bf", "the sheet is white on a grey canvas")

# the sheet dialog applied at the start: no undo step
PN.NewDrawingDialog.exec = lambda self: (self.sizes.setCurrentRow(keys.index("ansi_b")), self.land.setChecked(True), True)[2]
t.sheet_dialog(first=True)
ok(t.d.sheet["size"] == "ansi_b" and not t.undo_stack and t.is_dirty(), "the sheet picked when the drawing is new is its starting state (nothing to undo) and a change to keep")
PN.NewDrawingDialog.exec = lambda self: (self.sizes.setCurrentRow(keys.index("ansi_a")), True)[1]
t.sheet_dialog()
ok(t.d.sheet["size"] == "ansi_a" and t.is_dirty() and len(t.undo_stack) == 1, "Sheet Setup later is a change that can be undone")
t.do_undo()
ok(t.d.sheet["size"] == "ansi_b", "(and undone)")
t.do_redo()
t.undo_stack.clear()
t.redo_stack.clear()
t.version = t.saved_version

# ---------------------------------------------------------------------------------------------------------------------------- models from a Workbench block
r = t.sync_models([{"src": "n1", "name": "Bar", "kind": "part", "data": bar}])
ok(r["added"] == ["Bar"] and len(t.d.models) == 1 and t.d.models[0]["src"] == "n1", "a wired part becomes a model of the drawing")
ok(t.outline.tree.findItems("Bar", Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchExactly), "and shows in the Outline")
t.undo_stack.clear()
t.version = t.saved_version

# ---------------------------------------------------------------------------------------------------------------------------- Model View
t.open_command("model")
ok(t.left.currentIndex() == 1 and t.props.currentWidget() is t.model_panel, "Model View opens its panel in place of the Outline")
ok(t.model_panel.models.count() == 1 and t.model_panel.current_model() == "m1", "the models of the drawing are listed, the first is picked")
ok(not t.model_panel.sbtn["shaded"].isEnabled() and t.model_panel.sbtn["hlr"].isEnabled(), "the shaded styles are not offered yet; the line styles are")
ok(len(t.model_panel.obtn) == 9, "nine orientations: " + ", ".join(t.model_panel.obtn))
t.model_panel.pick_orientation("Front")
ok(len(t.d.views) == 1 and cv.float_id == t.d.views[0]["id"] and cv.mode == "model", "picking an orientation makes the view follow the pointer")
at = lambda x, y: cv.to_screen(x, y).toPoint()
QTest.mouseMove(cv, at(100, 120))
settle()
box = cv.r.view_box(t.d.views[0])
tol = 1.0 / cv.k
ok(near((box[0] + box[2]) / 2, cv.to_sheet(QPointF(at(100, 120)))[0], tol) and near((box[1] + box[3]) / 2, cv.to_sheet(QPointF(at(100, 120)))[1], tol), "the middle of its lines is at the pointer")
QTest.mouseMove(cv, at(140, 150))
settle()
box = cv.r.view_box(t.d.views[0])
ok(near((box[0] + box[2]) / 2, cv.to_sheet(QPointF(at(140, 150)))[0], tol), "and it follows the pointer")
ok(not t.undo_stack, "(nothing is in the undo list while the view is on the pointer)")
QTest.keyClick(cv, Qt.Key.Key_Escape)
settle()
ok(not t.d.views and cv.mode == "select" and not t.undo_stack and not t.is_dirty(), "Esc takes the view away: no view, no undo step, the drawing is not changed")
t.model_panel.pick_orientation("Front")
QTest.mouseMove(cv, at(100, 120))
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(100, 120))
settle()
v1 = t.d.views[0]
box = cv.r.view_box(v1)
ok(len(t.d.views) == 1 and cv.mode == "select" and cv.float_id is None and len(t.undo_stack) == 1 and t.is_dirty(), "a click puts the view down: one undo step, the drawing is changed")
ok(near((box[0] + box[2]) / 2, 100, tol) and near((box[1] + box[3]) / 2, 120, tol) and near(box[2] - box[0], 100.0, 1e-6) and near(box[3] - box[1], 10.0, 1e-6),
   f"it is where it was clicked, 100 x 10 mm at 1:1 ({v1['orient']}, {M.scale_text(v1['scale'])})")
ok(t.d.scale == 1.0 and v1["style"] == "hlv", "the first view sets the sheet scale; the style is the one picked in the panel (Hidden Lines Visible)")
ok(cv.sel == v1["id"] and t.act["delete"].isEnabled() and t.outline.cur_id == v1["id"] and t.outline.details.currentIndex() == 3, "it is selected, in the Outline and in the Details")
img = cv.grab().toImage()
def dark(x, y, im=None):
    im = im or img
    c = at(x, y)
    return min(QColor(im.pixel(c.x() + dx, c.y() + dy)).lightness() for dx in (-1, 0, 1) for dy in (-1, 0, 1)) < 140


light = lambda x, y: QColor(img.pixel(at(x, y))).lightness() > 240
ok(dark(box[0], 120) and dark(100, box[3]) and dark(100, box[1]) and light(100, 120), "the outline of the bar is drawn (dark pixels on its edges, white inside it)")
t.model_panel.pick_orientation("Isometric")
QTest.mouseMove(cv, at(200, 140))
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(200, 140))
settle()
iso = t.d.views[1]
ok(iso["orient"] == "Isometric" and near(iso["scale"], 1.0), "a second view uses the sheet scale")
# hidden lines of the isometric view: dashed with Hidden Lines Visible, not drawn with Hidden Lines Removed
pr = t.d.projection(iso)
hid = pr.hid
ok(len(hid) >= 1, "the isometric view of a box has hidden lines")
ent = max(hid, key=lambda e: abs(e["pts"][0][0] - e["pts"][-1][0]) + abs(e["pts"][0][1] - e["pts"][-1][1]))
s_, (ox, oy) = iso["scale"], iso["origin"]


def along(e, n=240):
    a, b = e["pts"][0], e["pts"][-1]
    return [(ox + s_ * (a[0] + (b[0] - a[0]) * i / n), oy + s_ * (a[1] + (b[1] - a[1]) * i / n)) for i in range(n + 1)]


def runs(samples):
    """How many dark runs along a line (a dashed line has many, a solid one has one)."""
    img2 = cv.grab().toImage()
    marks = []
    for x, y in samples:
        c = cv.to_screen(x, y).toPoint()
        marks.append(min(QColor(img2.pixel(c.x() + dx, c.y() + dy)).lightness() for dx in (-1, 0, 1) for dy in (-1, 0, 1)) < 150)
    return sum(1 for i in range(1, len(marks)) if marks[i] and not marks[i - 1]) + (1 if marks and marks[0] else 0), marks
cv.set_selected(None)
cv.zoom(2.0, at=cv.to_screen(200, 140))
n_dash, marks = runs(along(ent))
ok(n_dash >= 4 and not all(marks), f"Hidden Lines Visible: the hidden line is dashed ({n_dash} dashes along it)")
t.set_view_style(iso["id"], "hlr")
settle()
ok(len(t.d.projection(iso).hid) == 0, "Hidden Lines Removed: the view keeps no hidden line")
n_dash2, marks2 = runs(along(ent))
ok(sum(marks2) < sum(marks) * 0.3, "and nothing is drawn where it was")
t.set_view_style(iso["id"], "wireframe")
settle()
n_w, marks_w = runs(along(ent))
ok(n_w == 1 and all(marks_w), "Wireframe: every edge is drawn the same, solid")
t.set_view_style(iso["id"], "hlv")
cv.fit()
t.delete_view(iso["id"])
ok(len(t.d.views) == 1 and cv.sel is None, "Delete View takes the isometric view away again")
t.undo_stack.clear()
t.redo_stack.clear()
t.state = t.d.snapshot()
t.version = t.saved_version = 0
t.after_change(reset=True)
t.finish_command()
ok(t.left.currentIndex() == 0 and t.props.currentIndex() == 0, "OK closes the panel: the left column is the Outline again")

# ---------------------------------------------------------------------------------------------------------------------------- Projected View
v1 = t.d.views[0]
cv.set_selected(None)
t.open_command("projected")
ok(t.props.currentWidget() is t.proj_panel and cv.mode == "select", "Projected View with no view picked waits for one")
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(100, 120))
settle()
ok(cv.mode == "projected" and cv.proj_parent == v1["id"], "clicking a view makes it the parent: the pointer now picks the side")
QTest.mouseMove(cv, at(100, 120))
settle()
ok(cv.float_id is None, "over the parent itself there is no view yet")
QTest.mouseMove(cv, at(180, 123))
settle()
g = t.d.view(cv.float_id) if cv.float_id else None
ok(g is not None and g["side"] == "right" and g["kind"] == "projected", "to the right of the parent the view shown is the right one")
ok(near(g["origin"][1], v1["origin"][1]), "it is in line with its parent")
QTest.mouseMove(cv, at(110, 60))
settle()
g = t.d.view(cv.float_id)
ok(g["side"] == "down", "below the parent it is the view to the down side")
QTest.mouseMove(cv, at(100, 70))
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(100, 70))
settle()
pv = [v for v in t.d.views if v["kind"] == "projected"]
ok(len(pv) == 1 and pv[0]["side"] == "down" and near(pv[0]["origin"][0], v1["origin"][0]) and len(t.undo_stack) == 1, "a click puts it down: aligned with the parent, one undo step")
b = cv.r.view_box(pv[0])
ok(near(b[2] - b[0], 100.0) and near(b[3] - b[1], 20.0, 1e-6), "third angle: the view below the Front view is the Top view: 100 x 20 mm")
ok(cv.mode == "projected", "(the command stays open for another view from the same parent)")
QTest.keyClick(cv, Qt.Key.Key_Escape)
settle()
ok(cv.mode == "select" and len(t.d.projection(pv[0]).vis) > 0, "Esc ends it")
t.finish_command()
# dragging a projected view: only along its axis; its parent can be dragged anywhere and takes it along
cv.set_selected(None)
cx0, cy0 = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
x_before = t.d.view(pv[0]["id"])["origin"][0]
QTest.mousePress(cv, Qt.MouseButton.LeftButton, pos=at(b[0], cy0))                 # on the left edge of the projected view
QTest.mouseMove(cv, at(b[0] + 20, cy0 + 8))
QTest.mouseMove(cv, at(b[0] + 40, cy0 + 15))
QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, pos=at(b[0] + 40, cy0 + 15))
settle()
pv0 = t.d.view(pv[0]["id"])
b2 = cv.r.view_box(pv0)
ok(near((b2[0] + b2[2]) / 2, cx0, 1e-6) and near((b2[1] + b2[3]) / 2, cy0 + 15, 1.5 / cv.k) and near(pv0["origin"][0], x_before),
   "dragged sideways and up, a view below its parent only moved up (along its axis): it stays in line")
ok(len(t.undo_stack) == 2, "the drag is one undo step")
o_par, o_kid = list(v1["origin"]), list(pv0["origin"])
b1 = cv.r.view_box(v1)
QTest.mousePress(cv, Qt.MouseButton.LeftButton, pos=at(b1[0], 120))                 # the parent's left edge
QTest.mouseMove(cv, at(b1[0] + 15, 126))
QTest.mouseMove(cv, at(b1[0] + 30, 132))
QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, pos=at(b1[0] + 30, 132))
settle()
n_par, n_kid = t.d.view(v1["id"])["origin"], t.d.view(pv[0]["id"])["origin"]
ok(near(n_par[0] - o_par[0], 30.0, 1.5 / cv.k) and near(n_par[1] - o_par[1], 12.0, 1.5 / cv.k), "the parent view moves where it is dragged")
ok(near(n_kid[0] - o_kid[0], n_par[0] - o_par[0]) and near(n_kid[1] - o_kid[1], n_par[1] - o_par[1]) and near(n_kid[0], n_par[0]), "and its projected view goes with it, still in line")
t.do_undo()
ok(near(t.d.view(v1["id"])["origin"][0], o_par[0]) and near(t.d.view(pv[0]["id"])["origin"][1], o_kid[1]), "undo puts both back")

# ---------------------------------------------------------------------------------------------------------------------------- the Details
t.canvas.set_selected(v1["id"])
settle()
t.set_view_scale(v1["id"], "1:2")
b3 = cv.r.view_box(t.d.view(v1["id"]))
ok(near(b3[2] - b3[0], 50.0) and near(b3[3] - b3[1], 5.0), "a scale typed in the Details (1:2) makes the view half the size")
ok(t.outline.v_scale.currentText() == "1:2", "and the Details show it")
pv_now = t.d.view(pv[0]["id"])
ok(near(pv_now["origin"][0], t.d.view(v1["id"])["origin"][0]), "the projected view stays in line with the parent")
t.status.say("")
t.set_view_scale(v1["id"], "abc")
ok("not a scale" in t.status.text() and near(t.d.view(v1["id"])["scale"], 0.5), "a scale that is not a number is refused, with the reason, and the view keeps its scale")
t.set_view_scale(v1["id"], "2:1")
b3 = cv.r.view_box(t.d.view(v1["id"]))
ok(near(b3[2] - b3[0], 200.0), "2:1 doubles it")
t.set_view_scale(v1["id"], "1")
t.set_view_orient(v1["id"], "Right")
b4 = cv.r.view_box(t.d.view(v1["id"]))
ok(near(b4[2] - b4[0], 20.0) and near(b4[3] - b4[1], 10.0), "the Right view of the bar is 20 x 10 mm")
t.set_view_orient(v1["id"], "Front")
t.rename_view(v1["id"], "Front of the bar")
ok(t.d.view(v1["id"])["name"] == "Front of the bar" and t.outline.tree.findItems("Front of the bar   Front, 1:1", Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchStartsWith),
   "a view can be renamed; the Outline shows the new name")

# ---------------------------------------------------------------------------------------------------------------------------- undo and redo
n_views = len(t.d.views)
t.delete_view(pv[0]["id"])
ok(len(t.d.views) == n_views - 1, "Delete View removes the view")
t.do_undo()
ok(len(t.d.views) == n_views and any(v["id"] == pv[0]["id"] for v in t.d.views), "undo brings it back")
t.do_redo()
ok(len(t.d.views) == n_views - 1, "redo deletes it again")
t.do_undo()
img = cv.grab().toImage()
b = cv.r.view_box(t.d.view(pv[0]["id"]))
ok(dark(b[0], (b[1] + b[3]) / 2, img), "the restored view is drawn (the lines were drawn again after the undo)")

# ---------------------------------------------------------------------------------------------------------------------------- the file
p = os.path.join(tmp, "bar" + M.EXT)
ok(t.is_dirty() and t.save_to(p) and not t.is_dirty() and os.path.getsize(p) > 1000, "Save writes the drawing; it is not changed any more")
t2 = T.DrawingTab(p)
t2.resize(1250, 800)
t2.show()
settle()
ok([v["id"] for v in t2.d.views] == [v["id"] for v in t.d.views] and t2.d.sheet == t.d.sheet and t2.title() == "bar.opdraw" and not t2.is_dirty(), "it opens with the same sheet and views")
ok(not t2.d.cache, "(opened without building any model)")
img2 = t2.canvas.grab().toImage()
bb = t2.canvas.r.view_box(t2.d.view(v1["id"]))
c2 = t2.canvas.to_screen(bb[0], (bb[1] + bb[3]) / 2).toPoint()
ok(min(QColor(img2.pixel(c2.x() + dx, c2.y() + dy)).lightness() for dx in (-1, 0, 1) for dy in (-1, 0, 1)) < 140, "and shows its lines at once")
bad = os.path.join(tmp, "not.opdraw")
open(bad, "w").write("{}")
t3 = T.DrawingTab(bad)
ok("not an OpenPara drawing" in t3.status.text() and not t3.d.views, "a file that is not a drawing is refused with the reason")

# ---------------------------------------------------------------------------------------------------------------------------- the PDF
pdf = os.path.join(tmp, "bar.pdf")
ok(t.export_pdf(pdf) == pdf and os.path.getsize(pdf) > 500, "Export PDF writes the file")
import fitz
page = fitz.open(pdf)[0]
ok(near(page.rect.width, 11 * 72, 0.5) and near(page.rect.height, 8.5 * 72, 0.5), f"the page is the sheet: Letter landscape, 11 x 8.5 in ({page.rect.width:.1f} x {page.rect.height:.1f} pt)")
dr = page.get_drawings()
widths = sorted({round(d_["width"] or 0, 2) for d_ in dr if d_.get("width")})
ok(len(dr) >= 2 and any(near(w_, 0.5 * 72 / 25.4, 0.02) for w_ in widths), f"the lines are vector paths, visible edges 0.5 mm thick ({len(dr)} paths)")
longest = max((d_["rect"].width for d_ in dr), default=0)
fb = t.d.view(v1["id"])
want = (cv.r.view_box(fb)[2] - cv.r.view_box(fb)[0]) * 72 / 25.4
ok(any(near(d_["rect"].width, want, 0.6) for d_ in dr), f"the front view is {want / 72 * 25.4:.0f} mm wide on the page, as on the sheet")
t.set_sheet("iso_a3", False, False)
pdf2 = os.path.join(tmp, "a3.pdf")
t.export_pdf(pdf2)
pg2 = fitz.open(pdf2)[0]
ok(near(pg2.rect.width, 297 * 72 / 25.4, 0.6) and near(pg2.rect.height, 420 * 72 / 25.4, 0.6), "an A3 portrait sheet is a 297 x 420 mm page")
t.do_undo()
ok(t.d.sheet["size"] == "ansi_a", "(the sheet change undone)")
try:
    t.export_pdf(os.path.join(tmp, "nowhere", "x.pdf"))
    ok("Couldn't export" in t.status.text(), "a folder that is not there: the status line says it could not export")
except Exception as ex_:                                       # noqa: BLE001
    ok(False, f"export into a missing folder raised {ex_}")

# ---------------------------------------------------------------------------------------------------------------------------- models fed from wires
t.undo_stack.clear()
n = len(t.d.views)
r = t.sync_models([{"src": "n1", "name": "Bar", "kind": "part", "data": bar2}])
ok(r["refreshed"] == ["Bar"] and len(t.d.views) == n, "a wired part that changed is refreshed: the views stay, drawn again")
bx = cv.r.view_box(t.d.view(v1["id"]))
ok(near(bx[2] - bx[0], 150.0), "the Front view is now 150 mm long (the model is the new bar)")
r = t.sync_models([{"src": "n1", "name": "Bar", "kind": "part", "data": bar2}])
ok(r == {"added": [], "refreshed": [], "removed": [], "failed": []} and not t.undo_stack[1:], "the same data again changes nothing")
r = t.sync_models([{"src": "n1", "name": "Bar", "kind": "part", "data": {"bad": "model"}}])
ok(r["failed"] and "Bar" == r["failed"][0][0], "a model that cannot be built is reported, not raised")
r = t.sync_models([])
ok(r["removed"] == ["Bar"] and not t.d.models and not t.d.views, "a part that is no longer wired goes, with its views")

# ---------------------------------------------------------------------------------------------------------------------------- an assembly model
t.sync_models([{"src": "n2", "name": "Frame", "kind": "assembly", "data": ex.frame_asm(100, 20, 20)}])
t.open_command("model")
t.model_panel.pick_orientation("Top")
QTest.mouseMove(cv, at(120, 100))
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(120, 100))
settle()
fb = cv.r.view_box(t.d.views[0])
ok(len(t.d.views) == 1 and near(fb[2] - fb[0], 100.0, 1e-6) and near(fb[3] - fb[1], 20.0, 1e-6), "an assembly is drawn too: the Top view of the frame is 100 x 20 mm")
t.finish_command()

print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
