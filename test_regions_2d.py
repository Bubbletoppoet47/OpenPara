"""2D FEA (static structural): the regions.  Every region is tinted and named in the view; selecting one in the view, in the table of the Material page, in the list of the Geometry
page or in the Outline selects it everywhere; every region has its own material (a table on the Material page, the regions under Material and analysis in the Outline, 'bonded'
where regions touch); the boxes show and edit the selected region's material; regions that touch are fully bonded (the mesh shares its nodes; a bar of steel and aluminium in series
extends by the sum of the two extensions).  The Supports page and the Loads page each have their own table with only their own conditions.  The 2D Thermal window keeps its own
regions."""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

import physics_fea as pf
import physics_tab
import sim_tab
import sketcher_core as sc
import thermal_tab as tt


STATUS = []


def host():
    h = sim_tab.SimHost.__new__(sim_tab.SimHost)
    h.doc = None
    h.m = sim_tab._HostModel()
    h._restoring = False
    h.status = lambda t: STATUS.append(t)
    h.sim = None
    h.sketch_list = lambda: []
    return h


def ok(c, msg):
    assert c, msg
    print("ok:", msg)


def settle(n=3):
    for _ in range(n):
        app.processEvents()
    QTest.qWait(60)


def two_rects():
    """Two rectangles side by side sharing the edge x = 60: steel-ish 0..60 and 60..100, 20 high."""
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (60, 0), (100, 0), (100, 20), (60, 20), (0, 20))]
    ln = [m.add_line(p[0], p[1]), m.add_line(p[1], p[2]), m.add_line(p[2], p[3]), m.add_line(p[3], p[4]), m.add_line(p[4], p[5]), m.add_line(p[5], p[0]), m.add_line(p[1], p[4])]
    return m, p, ln


def plate(hole=False):
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (100, 0), (100, 20), (0, 20))]
    ln = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
    if hole:
        c = m.add_point(50, 10)
        m.add_circle(c, 4.0)
    return m, p, ln


def new_tab(model):
    t = physics_tab.PhysicsTab(host())
    t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
    t.resize(1250, 800)
    t.set_model(model, "test")
    t.show()
    settle()
    t.canvas.fit()
    settle()
    return t


def face_at_x(t, x):
    return next(f["id"] for f in t.geom["faces"] if abs(f["centroid"][0] - x) < 10)


def combo_of(t, fid):
    for r in range(t.region_table.rowCount()):
        if t.region_table.item(r, 0).data(Qt.ItemDataRole.UserRole) == fid:
            return t.region_table.cellWidget(r, 1)


def outline_rows(t):
    n = t.material_node()
    return t.outline.item_texts(n)


# ======================================================================================================== two regions that touch
m, p, ln = two_rects()
t = new_tab(m)
fl, fr = face_at_x(t, 30), face_at_x(t, 80)
ok(len(t.included_faces()) == 2 and fl != fr, "two material regions")
ok([g["id"] for g in t.bonded_with(t.face_by_id(fl))] == [fr] and [g["id"] for g in t.bonded_with(t.face_by_id(fr))] == [fl], "they touch along an edge: bonded to each other")
ok(t.region_table.rowCount() == 2, "the Material page lists both in a table")
ok(t.region_table.horizontalHeaderItem(1).text() == "Material" and t.region_table.horizontalHeaderItem(2).text() == "Bonded to", "with a Material column and a Bonded to column")
ok({t.region_table.item(r, 2).text() for r in range(2)} == {t.region_title(t.face_by_id(fl)), t.region_title(t.face_by_id(fr))}, "each row says which region it is bonded to")
ok(set(t.region_mats) == {fl, fr}, "with two regions every one has a material of its own")
t.outline.select("Material and analysis")
settle()
ok(t.region_note.isVisibleTo(t) and "fully bonded" in t.region_note.text(), "the Material page says that regions that touch are fully bonded")
rows = outline_rows(t)
ok(len(rows) == 2 and all("bonded" in r_ for r_ in rows) and rows[0].startswith("Region 1 · ") and rows[1].startswith("Region 2 · "), f"the Outline lists the regions under Material and analysis, each 'bonded': {rows}")
ok(t.outline.item_texts("Supports") == [] and t.outline.item_texts("Loads") == [], "and nothing is mixed into Supports and Loads")

# the view: tinted regions
cv = t.canvas
img = cv.grab().toImage()
def pixel_at_world(x, y):
    sp = cv.w2s(x, y)
    return img.pixelColor(int(sp.x()), int(sp.y()))
a = pixel_at_world(10, 4)               # near the lower left corner of region 1 (away from the name)
b = pixel_at_world(95, 4)               # near the lower right corner of region 2
ok((a.red(), a.green(), a.blue()) != (b.red(), b.green(), b.blue()), f"the two regions have different tints: {a.getRgb()[:3]} and {b.getRgb()[:3]}")
ok(a.getRgb()[:3] != (255, 255, 255) and b.getRgb()[:3] != (255, 255, 255), "and neither is the white background")
ok(physics_tab.label_point(t.face_by_id(fl)) is not None and abs(physics_tab.label_point(t.face_by_id(fl))[0] - 30) < 1, "each name sits inside its region")

# material of each region from the table: steel left, aluminium right
cb = combo_of(t, fr)
cb.setCurrentIndex(cb.findData("Aluminium 6061-T6"))
settle()
E1, E2 = t.region_mats[fl]["E_MPa"], t.region_mats[fr]["E_MPa"]
ok(E1 == 200000.0 and abs(E2 - 68900.0) < 1 and t.region_mats[fr]["name"] == "Aluminium 6061-T6", f"region 2 is aluminium now (E {E2})")
ok(t.region_mat_name(t.face_by_id(fr)) == "Aluminium 6061-T6" and "Aluminium 6061-T6" in outline_rows(t)[1], "the Outline shows the material of each region")
ok(t.material_summary().startswith("2 materials"), f"the page's one-line summary: {t.material_summary()}")

# selecting: view -> table, list, Outline, boxes
t.select_region(fr, via="view")
settle()
ok(t.sel_region == fr and cv.hl_face == fr, "a region selected in the view is the selected one")
ok(t.region_table.item(t.region_table.currentRow(), 0).data(Qt.ItemDataRole.UserRole) == fr, "its row is the selected row of the table")
ok(t.regions.currentRow() == fr, "and of the list on the Geometry page")
ok(t.outline.current is not None and t.outline.current[1] is not None and t.outline.current[1]["item"] is t.face_by_id(fr), "and its row is the selected row of the Outline")
ok(t.props_lbl.text() == "<b>Properties of Region %d</b>" % (fr + 1) and abs(float(t.e_E.text()) - 68900.0) < 1, "the boxes show its numbers")
ok(t.outline.head.text() == "Details of “Material and analysis”", f"the Details are those of the page: {t.outline.head.text()}")
# table -> view
t.region_table.setCurrentCell(0, 0)
settle()
first = t.region_table.item(0, 0).data(Qt.ItemDataRole.UserRole)
ok(t.sel_region == first and cv.hl_face == first and t.outline.current[1]["item"] is t.face_by_id(first), "a row picked in the table selects the region in the view and in the Outline")
# Outline -> view and table
tag = next(tg for _t, tg in t.outline.items[t.material_node()] if tg["item"] is t.face_by_id(fr))
t.outline.select(t.material_node(), tag)
settle()
ok(t.sel_region == fr and cv.hl_face == fr and t.region_table.item(t.region_table.currentRow(), 0).data(Qt.ItemDataRole.UserRole) == fr and t.regions.currentRow() == fr, "a row picked in the Outline selects the region in the view, the table and the list")
# list -> everything
t.regions.setCurrentRow(fl)
settle()
ok(t.sel_region == fl and cv.hl_face == fl and t.region_table.item(t.region_table.currentRow(), 0).data(Qt.ItemDataRole.UserRole) == fl, "a region picked in the list of the Geometry page too")

# a click in the view, inside a region (on the pages about the part)
sp = cv.w2s(80, 12)
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(sp.x()), int(sp.y())))
settle()
ok(t.sel_region == fr, "a click inside region 2 in the view selects it")
sp = cv.w2s(30, 12)
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(sp.x()), int(sp.y())))
settle()
ok(t.sel_region == fl and t.outline.current[1]["item"] is t.face_by_id(fl), "a click inside region 1 selects it (and its row in the Outline)")
t.outline.select("Supports")
settle()
sp = cv.w2s(80, 12)
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(sp.x()), int(sp.y())))
settle()
ok(t.sel_region == fl and t.outline.current[0] == "Supports", "on the Supports page a click inside a region does not leave the page")
t.outline.select("Material and analysis")
settle()

# typing in the boxes changes the selected region only
t.select_region(fr, via="table")
settle()
t.e_E.setText("70000")
t.e_E.textEdited.emit("70000")
settle()
ok(abs(t.region_mats[fr]["E_MPa"] - 70000.0) < 1e-6 and t.region_mats[fr]["name"] is None and t.region_mats[fl]["E_MPa"] == 200000.0, "typing E changes the selected region only; it is custom values now")
ok(combo_of(t, fr).currentText() == "(custom values)" and "custom values" in outline_rows(t)[1], "the table and the Outline say so")
t.e_sy.setText("123")
t.e_sy.textEdited.emit("123")
ok(abs(t.region_mats[fr]["Sy_MPa"] - 123.0) < 1e-6, "the yield strength too")
t.select_region(fl, via="table")
settle()
ok(abs(float(t.e_E.text()) - 200000.0) < 1e-6 and abs(float(t.e_sy.text()) - 250.0) < 1e-6, "the other region keeps its numbers")
# material chosen with the box above the numbers
t.select_region(fr, via="table")
t.mat_combo.setCurrentIndex(t.mat_combo.findData("Structural steel (A36)"))
settle()
ok(t.region_mats[fr]["name"] == "Structural steel (A36)" and combo_of(t, fr).currentData() == "Structural steel (A36)" and t.region_mats[fl]["name"] == "Structural steel (A36)", "the material list above the numbers gives the selected region a material")

# bonded: the mesh shares its nodes, and the answer is that of two bars in series
cb = combo_of(t, fr)
cb.setCurrentIndex(cb.findData("Aluminium 6061-T6"))
settle()
t.e_h.setText("4")
t.run_mesh()
mesh = t.mesh
nodes, tris, tf = np.asarray(mesh["nodes"]), np.asarray(mesh["tris"]), np.asarray(mesh["tri_face"])
on = [n for n in np.where(np.abs(nodes[:, 0] - 60.0) < 1e-6)[0]]
used_l, used_r = set(tris[tf == fl].ravel()), set(tris[tf == fr].ravel())
ok(len(on) >= 4 and all(n in used_l and n in used_r for n in on), f"fully bonded: the {len(on)} mesh nodes on the shared edge belong to both regions")
ok(len(nodes) == len({(round(a_, 6), round(b_, 6)) for a_, b_ in nodes}), "no node is doubled")
mat = t.read_material()
ok(mat["region_mats"] is not None and len(mat["region_mats"]) == 2, "the solver is given a material for each region")
res = pf.solve(t.mesh, mat, [{"mode": "fixed", "targets": [("ln", ln[5])]}], [{"kind": "pressure", "p": -5.0, "targets": [("ln", ln[2])]}])
nd, u = np.asarray(res["mesh"]["nodes"]), np.asarray(res["u"])
tip = u[np.abs(nd[:, 0] - 100.0) < 1e-6, 0].mean()
exact = 5.0 * 60.0 / E1 + 5.0 * 40.0 / 68900.0
ok(abs(tip / exact - 1) < 0.01, f"steel and aluminium in series extend by the sum of the two extensions: {tip:.6f} against {exact:.6f}")
joint = u[np.abs(nd[:, 0] - 60.0) < 1e-6, 0]
ok(abs(joint.mean() / (5.0 * 60.0 / E1) - 1) < 0.03, "and the joint moves as the steel part alone does")

# save and open: the materials and the selection come back
st = t.export_state()
t2 = new_tab(two_rects()[0])
t2.import_state(st)
settle()
fl2, fr2 = face_at_x(t2, 30), face_at_x(t2, 80)
ok(t2.region_mats[fr2]["name"] == "Aluminium 6061-T6" and t2.region_mats[fl2]["name"] == "Structural steel (A36)", "a saved window opens with the materials of its regions")
ok(combo_of(t2, fr2).currentData() == "Aluminium 6061-T6" and "Aluminium 6061-T6" in outline_rows(t2)[1], "and the table and the Outline show them")
ok(t2.edit_target() == t2.sel_region and abs(float(t2.e_E.text()) - t2.region_mats[t2.sel_region]["E_MPa"]) < 1e-6, "the boxes show the selected region")

# a file from before every region had a material of its own (two regions, no region materials, the boxes saved with E = 70000): both start with the saved numbers
old_st = dict(t.export_state(), region_mats={}, region_names={})
old_st["inputs"] = dict(old_st["inputs"], e_E="70000")
t3 = new_tab(two_rects()[0])
t3.import_state(old_st)
settle()
ok(all(abs(e["E_MPa"] - 70000.0) < 1e-6 for e in t3.region_mats.values()) and len(t3.region_mats) == 2, "an old file with two regions: both regions start with the saved numbers")
ok(abs(float(t3.e_E.text()) - 70000.0) < 1e-6 and abs(t3.read_material()["E"] - 70000.0) < 1e-6, "and the boxes still show them")

# a region switched off: one material region left, the other is no material
item = t.regions.item(fr)
item.setCheckState(Qt.CheckState.Unchecked)
settle()
ok(len(t.included_faces()) == 1 and t.region_table.rowCount() == 1 and len(outline_rows(t)) == 1 and "bonded" not in outline_rows(t)[0], "one region switched off: one row in the table and the Outline, not bonded to anything")
ok(t.sel_region == fl and abs(float(t.e_E.text()) - 200000.0) < 1e-6, "and the steel region is the one shown")
item.setCheckState(Qt.CheckState.Checked)
settle()
ok(len(t.included_faces()) == 2 and fr in t.region_mats and len(outline_rows(t)) == 2, "switched on again: it is a region with a material")

# ======================================================================================================== one region: as before
m, p, ln = plate()
t = new_tab(m)
ok(t.region_table.rowCount() == 1 and not t.region_mats and t.sel_region is None, "one region: a row in the table, no material of its own (the boxes are its material)")
ok(len(outline_rows(t)) == 1 and "bonded" not in outline_rows(t)[0], f"the Outline lists it, not bonded: {outline_rows(t)}")
t.e_E.setText("70000")
mat = t.read_material()
ok(mat["E"] == 70000.0 and mat["region_mats"] is None, "typing E is the material of the whole model")
cb = combo_of(t, t.included_faces()[0]["id"])
cb.setCurrentIndex(cb.findData("Aluminium 6061-T6"))
settle()
ok(t.mat_combo.currentData() == "Aluminium 6061-T6" and abs(float(t.e_E.text()) - 68900.0) < 1 and not t.region_mats, "choosing a material in the table sets the material of the model")
ok("Aluminium 6061-T6" in outline_rows(t)[0], "and the Outline shows it")

# a plate with a hole: the hole is not material and not a row
m, p, ln = plate(hole=True)
t = new_tab(m)
ok(len(t.geom["faces"]) == 2 and len(t.included_faces()) == 1 and t.region_table.rowCount() == 1 and not t.region_mats, "a hole is not a region with a material")

# ======================================================================================================== the Supports and Loads pages
m, p, ln = two_rects()
t = new_tab(m)
physics_tab.ask_numbers = lambda *a, **k: [4.0, -6.0]
t.canvas.sel = [("ln", ln[5])]
t.add_support("fixed")
t.loads.append({"kind": "pressure", "p": 2.0, "targets": [("ln", ln[2])]})
t.loads.append({"kind": "force", "fx": 1.0, "fy": 2.0, "targets": [("pt", p[3])]})
t.refresh_lists()
settle()
ok(t.sup_table.rowCount() == 1 and t.load_table.rowCount() == 2, "the Supports page lists the support, the Loads page the two loads")
ok(t.sup_table.item(0, 0).text() == "Fixed 1" and [t.load_table.item(r, 0).text() for r in range(2)] == ["Pressure 1", "Force 1"], "each with its name")
ok(t.sup_table.horizontalHeaderItem(2).text() == "Applied to" and t.load_table.item(0, 3).text() == "2", "name, type, applied to, value")
ok(t.sup_table.parent() is not None and t.cond_table.rowCount() == 3 and not t.cond_table.isVisibleTo(t), "behind them the list of all conditions is not shown")
t.outline.select("Supports")
settle()
ok(t.outline.item_texts("Supports") == ["Fixed 1"] and t.outline.item_texts("Loads") == ["Pressure 1", "Force 1"], "the Outline: the support under Supports, the loads under Loads")
# a row picked in the Outline is the selected row of the page's table
tag = next(tg for _t, tg in t.outline.items["Loads"] if tg["name"] == "Force 1")
t.outline.select("Loads", tag)
settle()
ok(t.load_table.currentRow() == 1 and t.cond_table.currentRow() == 2 and t.sup_table.currentRow() < 0, "a load picked in the Outline is the selected row of the Loads page")
# Remove selected on the Loads page removes that load only
t.remove_condition_in("Loads")
settle()
ok([x["kind"] for x in t.loads] == ["pressure"] and len(t.supports) == 1 and t.load_table.rowCount() == 1 and t.sup_table.rowCount() == 1, "Remove selected on the Loads page removes the selected load and nothing else")
# Remove with nothing selected says so
t.load_table.setCurrentCell(-1, -1)
t.load_table.clearSelection()
STATUS.clear()
ok(t.remove_condition_in("Loads") is False and any("Select a row" in x for x in STATUS) and len(t.loads) == 1, "Remove selected with nothing selected says so and removes nothing")
# rename in the table of a page
t.load_table.item(0, 0).setText("Right end")
settle()
ok(t.loads[0].get("name") == "Right end" and t.cond_table.item(1, 0).text() == "Right end" and t.outline.item_texts("Loads") == ["Right end"], "renaming a load in its table renames it everywhere")
# edit the value in the table of a page
t.load_table.item(0, 3).setText("3.5")
settle()
ok(t.loads[0]["p"] == 3.5 and t.load_table.item(0, 3).text() == "3.5", "the value of a pressure can be edited in the table")
t.load_table.setCurrentCell(0, 0)
ok(t.edit_condition_in("Loads") is True and t.load_table.currentColumn() == 3, "Edit selected on the Loads page edits the value")
t.sup_table.setCurrentCell(0, 0)
t.sup_table.closePersistentEditor(t.sup_table.currentItem())
ok(t.edit_condition_in("Supports") is True and t.sup_table.currentColumn() == 0, "on the Supports page a row without a value lets you rename it")
t.remove_condition_in("Supports")
settle()
ok(t.supports == [] and t.sup_table.rowCount() == 0 and t.load_table.rowCount() == 1, "and Remove selected removes the support")

# ======================================================================================================== the thermal window keeps its own regions
th = tt.ThermalTab(host())
ok(th.REGION_VIEW is False and not hasattr(th, "region_table"), "the 2D Thermal window has its own regions (no table of the structural window)")

print("OK regions and the Supports / Loads pages")
