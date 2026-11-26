"""Drawings (dev add-on drawings): the display style and the scale belong to ONE view, not to the sheet.  The style buttons and the scale field of the Model View panel change the view
that follows the pointer or is selected (undo takes the change back; with no view they set what the next one starts with), the Projected View panel does the same for the views projected
from a parent (they start as the parent's), the status strip names the selected view's scale, and nothing in the window talks about a sheet scale.   python test_dr_view_panels.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel

app = QApplication([])
import pm_app
pm_app.apply_theme(app)
import dr_model as M
import dr_panels as PN
import dr_tab as T
import wb_example as ex

T.DrawingTab.ASK_SHEET = False
FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, tol=1e-9):
    return abs(a - b) <= tol


def settle():
    for _ in range(3):
        app.processEvents()


bar, _sid = ex.part_doc(100, 20, 10)
t = T.DrawingTab()
t.resize(1250, 800)
t.show()
settle()
cv = t.canvas
mp, pp = t.model_panel, t.proj_panel
t.sync_models([{"src": "n1", "name": "Bar", "kind": "part", "data": bar}])
t.undo_stack.clear()
t.redo_stack.clear()
t.version = t.saved_version
at = lambda x, y: cv.to_screen(x, y).toPoint()


def put(x, y):
    QTest.mouseMove(cv, at(x, y))
    QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(x, y))
    settle()


def set_scale_text(panel, text):
    panel.scale.setCurrentText(text)
    panel.scale.lineEdit().editingFinished.emit()
    settle()


def checked(panel):
    return [k for k, b in panel.sbtn.items() if b.isChecked()]


# ---------------------------------------------------------------------------------------------------------------------------- no sheet scale anywhere
t.open_command("model")
texts = [w.text() for w in t.findChildren(QLabel)] + [w.toolTip() for w in t.findChildren(PN.QWidget)]
ok(not any("sheet scale" in x.lower() for x in texts), "no label or tip says 'sheet scale' (a view has its own scale)")
ok(mp.scale.lineEdit().placeholderText() == "set by the first view", "the scale field of the Model View panel says the first view sets the scale of new ones")
t.outline.tree.setCurrentItem(t.outline.tree.topLevelItem(0))
ok(not hasattr(t.outline, "sh_scale"), "the Details of the sheet have no scale row")
ok("These set the style and the scale of the next view" in mp.target.text(), "with no view picked the panel says that the buttons set the next view")

# ---------------------------------------------------------------------------------------------------------------------------- Model View: the view on the pointer
mp.sbtn["hlr"].click()
settle()
ok(checked(mp) == ["hlr"] and mp.start_style == "hlr" and not t.d.views and not t.undo_stack, "a style picked with no view: it is the start of the next one (nothing changes, nothing to undo)")
mp.pick_orientation("Front")
f1 = t.d.views[0]
ok(f1["style"] == "hlr" and cv.float_id == f1["id"] and checked(mp) == ["hlr"], "the view that follows the pointer starts with the style the panel shows")
ok(mp.target.text() == f"These change {f1['name']}.", "and the panel says it is the view the buttons change")
mp.sbtn["wireframe"].click()
settle()
ok(f1["style"] == "wireframe" and not t.undo_stack, "a style button changes the view on the pointer at once, with no undo step (it is not on the sheet yet)")
set_scale_text(mp, "1:2")
ok(near(f1["scale"], 0.5) and not t.undo_stack and checked(mp) == ["wireframe"], "so does the scale field")
put(100, 120)
ok(len(t.d.views) == 1 and len(t.undo_stack) == 1 and f1["style"] == "wireframe" and near(f1["scale"], 0.5), "put down: one undo step, with the style and the scale that were set")
ok(cv.sel == f1["id"] and mp.target.text() == f"These change {f1['name']}." and mp.scale.currentText() == "1:2", "it is selected: the panel shows its style and scale")

# ---------------------------------------------------------------------------------------------------------------------------- Model View: the selected view
n0 = len(t.undo_stack)
mp.sbtn["hlv"].click()
settle()
ok(f1["style"] == "hlv" and len(t.undo_stack) == n0 + 1 and t.is_dirty(), "a style button changes the selected view: one undo step")
set_scale_text(mp, "1:4")
ok(near(f1["scale"], 0.25) and len(t.undo_stack) == n0 + 2 and mp.scale.currentText() == "1:4", "the scale field changes the selected view: one undo step")
ok("1:4" in t.sheet_lbl.text() and f1["name"] in t.sheet_lbl.text(), f"the strip under the sheet names the selected view and its scale ({t.sheet_lbl.text()})")
d1 = t.outline.v_scale.currentText() if t.outline.cur_kind == "view" else None
ok(d1 == "1:4" and t.outline.v_style.currentData() == "hlv", "and the Details of the view say the same")
set_scale_text(mp, "nonsense")
ok(near(f1["scale"], 0.25) and mp.scale.currentText() == "1:4" and t.status.full, f"a scale that is not a scale changes nothing and the field goes back ({t.status.full[:40]})")
V = lambda vid: t.d.view(vid)                                       # undo restores copies of the views: look the view up again
t.do_undo()
settle()
ok(near(V(f1["id"])["scale"], 0.5) and mp.scale.currentText() == "1:2", "undo takes the scale back and the panel follows")
t.do_undo()
settle()
ok(V(f1["id"])["style"] == "wireframe" and checked(mp) == ["wireframe"], "undo takes the style back and the panel follows")
t.do_redo()
t.do_redo()
settle()
f1 = V(f1["id"])
ok(f1["style"] == "hlv" and near(f1["scale"], 0.25), "redo puts both back")

# ---------------------------------------------------------------------------------------------------------------------------- two views, two styles, two scales
mp.pick_orientation("Isometric")
f2 = t.d.views[1]
ok(f2["style"] == "hlv" and near(f2["scale"], 0.25), "the next view starts as the panel shows (the style and the scale of the view that was selected)")
mp.sbtn["hlr"].click()
set_scale_text(mp, "1:1")
put(200, 60)
ok(f2["style"] == "hlr" and near(f2["scale"], 1.0) and f1["style"] == "hlv" and near(f1["scale"], 0.25), "the second view has its own style and scale: the first one did not change")
cv.set_selected(f1["id"])
settle()
ok(checked(mp) == ["hlv"] and mp.scale.currentText() == "1:4" and f1["name"] in mp.target.text(), "selecting the first view shows its style and scale in the panel")
cv.set_selected(f2["id"])
settle()
ok(checked(mp) == ["hlr"] and mp.scale.currentText() == "1:1" and "1:1" in t.sheet_lbl.text() and f2["name"] in t.sheet_lbl.text(), "the second view shows its own, and so does the strip")
cv.set_selected(None)
settle()
ok(checked(mp) == ["hlr"] and "These set the style and the scale of the next view" in mp.target.text() and t.sheet_lbl.text().count("1:") == 0, "with no view selected the panel is back to the start values and the strip names no scale")
mp.sbtn["shaded"].click()
settle()
ok(f1["style"] == "hlv" and f2["style"] == "hlr" and mp.start_style == "shaded", "a style picked with no view selected touches neither view")
t.finish_command()

# ---------------------------------------------------------------------------------------------------------------------------- Projected View
t.undo_stack.clear()
t.redo_stack.clear()
cv.set_selected(None)
t.d.remove_view(f2["id"])
cv.r.cache.clear()
t.after_change(reset=True)
t.undo_stack.clear()
t.redo_stack.clear()
t.open_command("projected")
ok(t.props.currentWidget() is t.proj_panel and pp.same.isChecked() and pp.style_choice() is None and pp.scale_choice() is None, "Projected View starts on 'same as parent' with no scale of its own")
b1 = cv.r.view_box(f1)
cxp, cyp = (b1[0] + b1[2]) / 2, (b1[1] + b1[3]) / 2
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(cxp, cyp))
settle()
ok(cv.mode == "projected" and cv.proj_parent == f1["id"], "the parent is picked")
ok(pp.scale.lineEdit().placeholderText() == "like the parent: 1:4" and checked(pp) == ["hlv"], "the panel shows the parent's scale and style")
QTest.mouseMove(cv, at(cxp, cyp - 30))
settle()
ghost = t.d.view(cv.float_id)
ok(ghost["style"] == "hlv" and near(ghost["scale"], 0.25), "the view that follows the pointer starts as its parent")
pp.sbtn["wireframe"].click()
settle()
ok(not pp.same.isChecked() and ghost["style"] == "wireframe" and cv.proj_style == "wireframe" and f1["style"] == "hlv" and not t.undo_stack,
   "a style button: 'same as parent' goes off, the view on the pointer takes the style, the parent keeps its own")
set_scale_text(pp, "1:2")
ghost = t.d.view(cv.float_id)
ok(near(ghost["scale"], 0.5) and near(cv.proj_scale, 0.5) and near(f1["scale"], 0.25) and not t.undo_stack, "the scale field: the view on the pointer takes it, the parent keeps its own")
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(cxp, cyp - 30))
settle()
kids = [v for v in t.d.views if v["kind"] == "projected"]
ok(len(kids) == 1 and kids[0]["style"] == "wireframe" and near(kids[0]["scale"], 0.5) and len(t.undo_stack) == 1, "put down: the projected view has the style and the scale set in the panel (one undo step)")
k1 = kids[0]
ok(cv.sel == k1["id"] and pp.target.text() == f"These change {k1['name']}." and pp.scale.currentText() == "1:2" and checked(pp) == ["wireframe"], "it is selected and the panel shows it")
pp.sbtn["hlr"].click()
settle()
ok(k1["style"] == "hlr" and f1["style"] == "hlv" and len(t.undo_stack) == 2, "the buttons now change the view just put down (one undo step), not its parent")
set_scale_text(pp, "1:5")
ok(near(k1["scale"], 0.2) and near(f1["scale"], 0.25) and len(t.undo_stack) == 3, "the scale field too")
pp.same.click()
settle()
ok(pp.same.isChecked() and k1["style"] == f1["style"] == "hlv" and checked(pp) == ["hlv"], "'Same as parent' gives the view just put down its parent's style")
t.do_undo()
settle()
ok(t.d.view(k1["id"])["style"] == "hlr", "undo")
QTest.keyClick(cv, Qt.Key.Key_Escape)
settle()
t.finish_command()

# ---------------------------------------------------------------------------------------------------------------------------- the file keeps them
t2 = M.Drawing.from_json(t.d.to_json())
ok([(v["style"], v["scale"]) for v in t2.views] == [(v["style"], v["scale"]) for v in t.d.views], "every view keeps its own style and scale in the file")

print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
