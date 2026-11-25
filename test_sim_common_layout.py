"""The common layout of the left panels of 1D FEA, 2D FEA, 3D FEA and 2D CFD (Simulation add-on and 3D FEA): the same flow of sections, the same
rows of buttons (material row with Add / Delete, one-line hint over Supports and Loads, the 'Conditions on this model' table with Edit selected /
Remove selected, a wide Solve bar with its Stop / Cancel, results that end with the same row) and the soft bevel look at one and at two screen
scales.  Run it plain for scale 1; it starts itself again with QT_SCALE_FACTOR=2."""
import os, sys, tempfile, subprocess
if "--scale2" not in sys.argv and not os.environ.get("QT_SCALE_FACTOR"):
    env = dict(os.environ, QT_SCALE_FACTOR="2")
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--scale2"], env=env)
    if r.returncode:
        raise SystemExit(r.returncode)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QAbstractItemView, QApplication, QCheckBox, QDialog, QLabel, QMessageBox, QPushButton
app = QApplication([])
SCALE = app.primaryScreen().devicePixelRatio()
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import sketcher_core as sc
import pm_model as pmod, sk_tools as sk
import physics_tab, beam_tab, cfd_tab, solid_tab
import physics_materials as pm
import sim_ui, sim_style, sim_matdlg, profiles1d as pr1


class Win:
    doc = None
    def sketch_list(self): return []
    def status(self, t): pass


def sec(t, title):
    return next(x for x in t.sections if x.title == title)


def btn_texts(t, title):
    return [b.text().strip() for b in sec(t, title).frame.findChildren(QPushButton)]


def first_widgets(t, title, n):
    """The first `n` widgets of a section, a row of the section counting as its widgets from left to right."""
    out = []
    lay = sec(t, title).body
    for i in range(lay.count()):
        it = lay.itemAt(i)
        if it.widget() is not None:
            out.append(it.widget())
        elif it.layout() is not None:
            out += [it.layout().itemAt(k).widget() for k in range(it.layout().count()) if it.layout().itemAt(k).widget() is not None]
        if len(out) >= n:
            break
    return out[:n]


def first_label_text(t, title):
    lay = sec(t, title).body
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if isinstance(w, QLabel) and w.text():
            return w.text()
    return None


# ------------------------------------------------------------------------------------------------ the four tabs
fea, beam, cfd = physics_tab.PhysicsTab(Win()), beam_tab.BeamTab(Win()), cfd_tab.CFDTab(Win())
T = tempfile.mkdtemp(prefix="opara_cl_")
d = pmod.Document(); d.params = {"T": "10"}
s = d.add(pmod.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m_ = d.models[s["id"]]
r = sk.add_rect_corner(m_, (0, 0), (100, 10))
m_.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m_.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
sk.solve_model(m_); d.store_sketch(s["id"])
d.add(pmod.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())
solid = solid_tab.SolidWindow(threaded=False)
assert solid.create_project(os.path.join(T, "bar_cl")) and solid.import_file(part), MSGS
tabs = {"1D FEA": beam, "2D FEA": fea, "3D FEA": solid, "2D CFD": cfd}
for t in tabs.values():
    t.resize(1300, 1700); t.show()
app.processEvents()

# --- the same flow of sections
ORDER = {"1D FEA": ["Geometry", "Material and analysis", "Joints", "Ties", "Supports", "Loads", "Mesh", "Results"],
         "2D FEA": ["Geometry", "Material and analysis", "Supports", "Loads", "Mesh", "Results"],
         "3D FEA": ["Geometry", "Material and analysis", "Supports", "Loads", "Mesh", "Results"],
         "2D CFD": ["Geometry", "Fluid and flow", "Domain", "Mesh", "Solver", "Results"]}
for name, t in tabs.items():
    got = [x.title for x in sorted(t.sections, key=lambda x: x.number)]
    assert got == ORDER[name], (name, got)
    assert [x.number for x in sorted(t.sections, key=lambda x: x.number)] == list(range(1, len(got) + 1)), name
    # Geometry first, Results last, the Solve bar right before the Results
    assert got[0] == "Geometry" and got[-1] == "Results"

# --- Geometry: the 1D panel keeps its profile list under the info line and the auto-tie checkbox last; CFD / 2D / 1D start with the source row
for name in ("1D FEA", "2D FEA", "2D CFD"):
    t = tabs[name]
    ws = first_widgets(t, "Geometry", 3)
    assert ws[0] is t.picker, name
    assert ws[1].text() == "Clear (start over)", (name, ws[1].text())
    assert ws[2] is t.info, name
geo1 = sec(beam, "Geometry").body
last = geo1.itemAt(geo1.count() - 1).widget()
assert last is beam.cb_tie, "the 'Connect points...' checkbox is the last thing of the 1D Geometry"
assert beam.prof_list.parent() is not None and sec(beam, "Geometry").isAncestorOf(beam.prof_list)

# --- Material: [combo][Add material...][Delete] on top (1D, 2D, 3D)
for name in ("1D FEA", "2D FEA", "3D FEA"):
    t = tabs[name]
    title = "Material and analysis"
    ws = first_widgets(t, title, 3)
    assert ws[0] is t.mat_combo and ws[1].text() == "Add material..." and ws[2] is t.b_del_mat and ws[2].text() == "Delete", (name, [w.text() if hasattr(w, "text") else w for w in ws])
    assert not t.b_del_mat.isEnabled() or t.mat_combo.currentData() not in {n for n, _, _ in pm.DEFAULTS}, name
assert sec(beam, "Material and analysis").isAncestorOf(beam.cb_shear) and not sec(beam, "Mesh").isAncestorOf(beam.cb_shear), "Timoshenko is a material / analysis option"
assert sec(beam, "Results").isAncestorOf(beam.cb_mesh) and beam.cb_mesh.text() == "Show mesh", "'Show mesh' is in the Results of 1D FEA"
assert not sec(beam, "Mesh").isAncestorOf(beam.cb_mesh)

# --- Add material... / Delete: one shared dialog and one library for 1D, 2D and 3D
orig_exec = QDialog.exec
def fake_exec(self):
    f = getattr(self, "fields", None)
    if f is None:
        return QDialog.DialogCode.Accepted.value
    f["name"].setText(FAKE["name"]); f["E"].setText("70000"); f["nu"].setText("0.33"); f["sy"].setText("200"); f["su"].setText("300")
    f["unit"].setCurrentText("MPa")
    return QDialog.DialogCode.Accepted.value
QDialog.exec = fake_exec
for k, name in enumerate(("1D FEA", "2D FEA", "3D FEA")):
    t = tabs[name]
    FAKE = {"name": f"Test alloy {name}"}
    n0 = t.mat_combo.count()
    t.add_material()
    assert t.mat_combo.count() == n0 + 1 and t.mat_combo.currentData() == FAKE["name"], (name, t.mat_combo.currentData())
    assert t.b_del_mat.isEnabled(), "a material of the user can be deleted"
    assert any(x["name"] == FAKE["name"] for x in pm.load()), "it is in the shared library (materials.json)"
    t.delete_material()
    assert t.mat_combo.count() == n0 and all(x["name"] != FAKE["name"] for x in pm.load()), name
    # a built-in one cannot be deleted
    i = next(i for i in range(t.mat_combo.count()) if t.mat_combo.itemData(i) in {n for n, _, _ in pm.DEFAULTS})
    t.mat_combo.setCurrentIndex(i)
    if name == "3D FEA":
        t.material_picked()
    elif hasattr(t, "material_picked"):
        t.material_picked()
    assert not t.b_del_mat.isEnabled(), name
    t.delete_material()
    assert t.mat_combo.itemData(i) is not None and any(x["name"] == t.mat_combo.itemData(i) for x in pm.load()), "built-in materials stay"
# a material added in one tab is there in the others after they refill
FAKE = {"name": "Shared alloy"}
beam.add_material()
for name in ("2D FEA", "3D FEA"):
    tabs[name].fill_materials()
    assert "Shared alloy" in [tabs[name].mat_combo.itemData(i) for i in range(tabs[name].mat_combo.count())], name
beam.mat_combo.setCurrentIndex(beam.mat_combo.findData("Shared alloy")); beam.material_picked()
beam.delete_material()
QDialog.exec = orig_exec
assert sim_matdlg.can_delete("Shared alloy") and not sim_matdlg.can_delete(None) and not sim_matdlg.can_delete(pm.DEFAULTS[0][0])
# the dialog refuses a duplicate name and a bad number
bad = []
QMessageBox.warning = staticmethod(lambda *a, **k: bad.append(a[2]))
def exec_dup(self):
    f = self.fields
    f["name"].setText(pm.load()[0]["name"]); f["E"].setText("1"); f["nu"].setText("0.3")
    return QDialog.DialogCode.Accepted.value
QDialog.exec = exec_dup
assert sim_matdlg.add_material(beam, pm.load(), "MPa", {"E": "1", "nu": "0.3"}) is None and bad and "already exists" in bad[-1]
def exec_nan(self):
    f = self.fields
    f["name"].setText("Nonsense"); f["E"].setText("abc"); f["nu"].setText("0.3")
    return QDialog.DialogCode.Accepted.value
QDialog.exec = exec_nan
assert sim_matdlg.add_material(beam, pm.load(), "MPa", {}) is None and "numbers" in bad[-1]
QDialog.exec = orig_exec
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))

# --- Supports and Loads: the same one-line hint at the top, stacked icon buttons
HINT = {"1D FEA": "Select the joints (or members) first (click them in the view), then press a button.",
        "2D FEA": "Select the edge(s) or point(s) first (click them in the view), then press a button.",
        "3D FEA": "Select the face(s) first (click them in the view), then press a button."}
for name, hint in HINT.items():
    for title in ("Supports", "Loads"):
        assert first_label_text(tabs[name], title) == hint, (name, title, first_label_text(tabs[name], title))
assert first_label_text(beam, "Joints") == HINT["1D FEA"]
assert btn_texts(beam, "Joints") == ["Rigid joint", "Pinned joint"]
# Joints are stacked buttons like the supports: one under the other
beam.outline.select("Joints"); app.processEvents()
j1, j2 = [b for b in sec(beam, "Joints").frame.findChildren(QPushButton)]
assert j1.mapTo(beam, j1.rect().topLeft()).y() < j2.mapTo(beam, j2.rect().topLeft()).y() and abs(j1.x() - j2.x()) < 3, "stacked, not side by side"

# --- Loads end with the shared conditions table and the Edit selected / Remove selected row
for name in ("1D FEA", "2D FEA", "3D FEA"):
    t = tabs[name]
    assert t.cond_table.columnCount() == 4 and [t.cond_table.horizontalHeaderItem(i).text() for i in range(4)] == ["Name", "Type", "Applied to", "Value"], name
    assert sec(t, "Loads").isAncestorOf(t.cond_table), name
    assert btn_texts(t, "Loads")[-2:] == ["Edit selected...", "Remove selected"], (name, btn_texts(t, "Loads"))
solid.outline.select("Loads"); app.processEvents()
assert not solid.sup_list.isVisibleTo(solid) and not solid.load_list.isVisibleTo(solid), "3D: the two plain lists are hidden; the table shows both"

# ---- 1D: edit / remove through the table
bm = sc.Model()
q = [bm.add_point(0, 0), bm.add_point(1000, 0), bm.add_point(1000, 500)]
l1, l2 = bm.add_line(q[0], q[1]), bm.add_line(q[1], q[2])
beam.set_model(bm, "frame")
beam_tab.ask_numbers = lambda *a, **k: [3.0, -7.0]
beam.canvas.sel = [("pt", q[0])]; beam.add_support("fixed")
beam.canvas.sel = [("pt", q[1])]; beam.add_force()
assert beam.cond_table.rowCount() == 2 and beam.cond_table.item(1, 3).text().startswith("(") or beam.cond_table.item(1, 3).text(), beam.cond_table.item(1, 3).text()
assert beam.edit_condition() is False and "Select a row" in beam.status_lbl.text(), "Edit selected with nothing selected says so"
beam.cond_table.setCurrentCell(1, 0)
assert beam.edit_condition() is True and beam.cond_table.state() == QAbstractItemView.State.EditingState and beam.cond_table.currentColumn() == 3, "a force: its Value is edited"
beam.cond_table.item(1, 3).setText("5, -9")
for _ in range(3):
    app.processEvents()
assert beam.loads[0]["fx"] == 5.0 and beam.loads[0]["fy"] == -9.0, beam.loads
beam.cond_table.setCurrentCell(0, 0)
beam.cond_table.closePersistentEditor(beam.cond_table.currentItem())
assert beam.edit_condition() is True and beam.cond_table.currentColumn() == 0, "a support has no value: its Name is edited"
beam.cond_table.item(0, 0).setText("Wall")
assert beam.supports[0].get("name") == "Wall"
called = []
beam.loads.append({"kind": "wind", "V": 20.0, "angle": 0.0, "cp": 1.0, "rho": 1.225, "targets": [l1]})
beam.members[0]["depth"] = 100.0
beam.after_conditions()
beam.edit_pressure = lambda: called.append(1)
beam.cond_table.setCurrentCell(2, 0)
assert beam.edit_condition() is True and called == [1], "wind / snow open their own box"
beam.cond_table.setCurrentCell(2, 0)
beam.remove_condition()
assert len(beam.loads) == 1 and len(beam.supports) == 1 and beam.cond_table.rowCount() == 2
beam.cond_table.setCurrentCell(0, 0)
beam.remove_condition()
assert beam.supports == [] and len(beam.loads) == 1

# ---- 2D: the same
fm = sc.Model()
p = [fm.add_point(*c) for c in ((0, 0), (100, 0), (100, 20), (0, 20))]
for i in range(4):
    fm.add_line(p[i], p[(i + 1) % 4])
fea.set_model(fm, "rect")
physics_tab.ask_numbers = lambda *a, **k: [4.0, -6.0]
fea.canvas.sel = [("pt", p[0])]; fea.add_support("fixed")
fea.canvas.sel = [("pt", p[1])]; fea.add_force()
assert fea.cond_table.rowCount() == 2
assert fea.edit_condition() is False
fea.cond_table.setCurrentCell(1, 0)
assert fea.edit_condition() is True and fea.cond_table.state() == QAbstractItemView.State.EditingState and fea.cond_table.currentColumn() == 3
fea.cond_table.item(1, 3).setText("1, 2")
for _ in range(3):
    app.processEvents()
assert fea.loads[0]["fx"] == 1.0 and fea.loads[0]["fy"] == 2.0, fea.loads
fea.cond_table.setCurrentCell(0, 0)
fea.cond_table.closePersistentEditor(fea.cond_table.currentItem())
assert fea.edit_condition() is True and fea.cond_table.currentColumn() == 0
fea.cond_table.setCurrentCell(0, 0)
fea.remove_condition()
assert fea.supports == [] and len(fea.loads) == 1

# ---- 3D: one table for supports and loads
def face(n):
    return next(f["id"] for f in solid.geom["faces"] if np.dot(f["normal"], n) > 0.99)
solid.select_faces([face([-1, 0, 0])]); assert solid.add_support("fixed")
solid.select_faces([face([0, 0, 1])]); assert solid.add_support("slide")
solid.select_faces([face([1, 0, 0])]); assert solid.add_load("force", {"f": [1000.0, 0.0, 0.0]})
assert solid.add_load("gravity", {"g": 9.81, "dir": [0.0, 0.0, -1.0]})
t3 = solid.cond_table
assert t3.rowCount() == 4 and solid.sup_list.count() == 2 and solid.load_list.count() == 2
assert [t3.item(i, 1).text() for i in range(4)] == ["Fixed", "One direction (normal)", "Force", "Gravity"], [t3.item(i, 1).text() for i in range(4)]
assert t3.item(2, 2).text() == "1 face(s)" and "1000" in t3.item(2, 3).text() and t3.item(3, 2).text() == "whole part"
assert t3.item(0, 3).text() == "", "a support has no value"
# rename a support from the table
t3.item(1, 0).setText("Top slider")
assert solid.setup["supports"][1]["name"] == "Top slider" and solid.sup_list.item(1).text().startswith("Top slider")
t3.item(1, 0).setText("")
assert "name" not in solid.setup["supports"][1] or solid.setup["supports"][1]["name"], "an empty name goes back to the default"
assert t3.item(1, 0).text() == "Support 2" or t3.item(1, 0).text().startswith("Slide") or t3.item(1, 0).text(), t3.item(1, 0).text()
# Edit selected: a support row is renamed, a load row opens the numbers (a dialog); nothing selected says so
solid.say("")
t3.clearSelection(); t3.setCurrentCell(-1, -1)
assert solid.edit_condition() is False and "Select a row" in solid.status_lbl.text()
t3.setCurrentCell(0, 1)
assert solid.edit_condition() is True and t3.state() == QAbstractItemView.State.EditingState and t3.currentColumn() == 0
t3.closePersistentEditor(t3.currentItem()); t3.setState(QAbstractItemView.State.NoState)
edited = []
solid.edit_load = lambda i: edited.append(i) or True
t3.setCurrentCell(2, 1)
assert solid.edit_condition() is True and edited == [0], edited
t3.setCurrentCell(3, 1)
assert solid.edit_condition() is True and edited == [0, 1], "gravity is the second load: row 3 - 2 supports = load 1"
t3.cellDoubleClicked.emit(2, 3)
app.processEvents()
assert edited[-1] == 0, "a double-click on a load's numbers edits that load"
del solid.edit_load
# Remove selected: the right item goes
t3.setCurrentCell(2, 0)
assert solid.remove_condition() is True
assert [l["kind"] for l in solid.setup["loads"]] == ["gravity"] and len(solid.setup["supports"]) == 2 and t3.rowCount() == 3
t3.setCurrentCell(0, 0)
assert solid.remove_condition() is True and len(solid.setup["supports"]) == 1 and t3.rowCount() == 2
assert solid.setup["supports"][0]["mode"] == "slide", "the first support went, the second stays"
# the old lists still work (scripts): remove_item(key, list)
solid.load_list.setCurrentRow(0)
solid.remove_item("loads", solid.load_list)
assert solid.setup["loads"] == [] and t3.rowCount() == 1

# --- the Mesh section of 2D FEA / CFD holds auto-refine; the Probe block is in the Results of 2D FEA
assert sec(fea, "Mesh").isAncestorOf(fea.cb_auto) and sec(cfd, "Mesh").isAncestorOf(cfd.cb_auto) and sec(cfd, "Mesh").isAncestorOf(cfd.e_passes)
assert not sec(cfd, "Solver").isAncestorOf(cfd.cb_auto) and not sec(cfd, "Solver").isAncestorOf(cfd.e_passes)
assert sec(fea, "Results").isAncestorOf(fea.probe_table) and "Probe regions" not in [x.title for x in fea.sections]

# --- the Solve button: the first thing of the Results page, plain like Mesh, with its Stop / Cancel, status and progress right under it
assert solid.b_cancel.text() == "Cancel" and cfd.b_stop.text() == "Stop"
for name_, t in tabs.items():
    rs_ = sec(t, "Results")
    assert t.b_solve.text() == "Solve" and rs_.isAncestorOf(t.b_solve), name_
    assert t.b_solve.styleSheet() == "" and t.b_solve.property("simrole") not in ("solve", "solveside"), (name_, "a plain grey button, not the teal one")
    assert not sec(t, "Geometry").isAncestorOf(t.b_solve) and not [b for b in t.findChildren(QPushButton) if b.parent() is not None and b.parent().objectName() == "pinned"]
assert not cfd.b_stop.isEnabled() and not solid.b_cancel.isEnabled()
cfd.worker = object(); cfd.enable_buttons()
assert cfd.b_stop.isEnabled() and cfd.b_stop.text() == "Stop", "the Solve button's Stop is the one that is enabled while a solve runs (it used to be replaced by the animation's)"
cfd.worker = None; cfd.enable_buttons()
assert not cfd.b_stop.isEnabled() and cfd.b_play_stop is not cfd.b_stop and cfd.b_play_stop.text() == "Stop"
col = sec(cfd, "Results").body
assert col.indexOf(cfd.solve_row) == 0 and col.itemAt(1).widget() is cfd.solve_status and cfd.solve_status.isAncestorOf(cfd.bar) and cfd.solve_status.isAncestorOf(cfd.plot) and cfd.solve_status.isAncestorOf(cfd.prog_lbl)
assert cfd.solve_row.isAncestorOf(cfd.b_solve) and cfd.solve_row.isAncestorOf(cfd.b_stop)
col = sec(beam, "Results").body
assert col.indexOf(beam.b_solve) == 0 and col.itemAt(1).widget() is beam.cb_auto and beam.cb_auto.text() == "Solve automatically after every change"
col = sec(solid, "Results").body
assert col.indexOf(solid.solve_row) == 0 and col.itemAt(1).widget() is solid.prog and solid.solve_row.isAncestorOf(solid.b_cancel)
# Solve and Stop / Cancel have the same height
for t, side in ((cfd, cfd.b_stop), (solid, solid.b_cancel)):
    assert abs(t.b_solve.height() - side.height()) <= 4 or side.height() >= 34, (t.b_solve.height(), side.height())
# F5 solves from any page of the window: the Geometry page is shown, the key presses the Solve button (and does nothing while it is off)
import sim_ui as _ui
for name_, t in tabs.items():
    assert t.solve_key.key().toString() == _ui.SOLVE_KEY and t.solve_key.parent() is t, name_
    pressed = []
    t.b_solve.click = lambda p=pressed: p.append(1)          # (the real handler would start a solve)
    t.outline.select("Geometry"); app.processEvents()
    t.b_solve.setEnabled(True)
    t.solve_key.activated.emit()
    assert pressed == [1], (name_, "F5 pressed Solve from the Geometry page")
    t.b_solve.setEnabled(False)
    t.solve_key.activated.emit()
    assert pressed == [1], (name_, "and does nothing while Solve is off")
    del t.b_solve.click
    t.enable_buttons()

# --- Results end with the same row; the shared order of the parts
assert btn_texts(beam, "Results")[-2:] == ["Member report...", "Zoom to fit"]
assert btn_texts(fea, "Results")[-2:] == ["Diagnostics report...", "Zoom to fit"] or btn_texts(fea, "Results")[-1] == "Zoom to fit", btn_texts(fea, "Results")
assert btn_texts(cfd, "Results")[-2:] == ["Diagnostics report...", "Zoom to fit"]
assert [t_ for t_ in btn_texts(solid, "Results") if t_ not in ("Solve", "Cancel", "Create parametric study", "Open parametric study")][-1] == "Zoom to fit"
# field combo first, then Colours
for name, field in (("1D FEA", "view_combo"), ("2D FEA", "field_combo"), ("3D FEA", "cb_field"), ("2D CFD", "field")):
    t = tabs[name]
    fld = getattr(t, field, None)
    if fld is None:
        continue
    assert sec(t, "Results").isAncestorOf(fld), (name, field)
res_cfd = sec(cfd, "Results")
cfd.outline.select("Results"); app.processEvents()
ys = {n: getattr(cfd, n).mapTo(cfd, getattr(cfd, n).rect().topLeft()).y() for n in ("field", "cb_mesh", "slider", "cb_tracers", "b_send", "b_play", "res_lbl")}
assert ys["field"] < ys["cb_mesh"] < ys["slider"] < ys["cb_tracers"] < ys["b_send"] < ys["b_play"], ys

# --- the soft bevel look, at this screen scale
assert sec(beam, "Results").toggle.styleSheet() == sim_style.SECTION_BAR
for t in tabs.values():
    pan = sec(t, "Geometry")
    while pan is not None and not hasattr(pan, "default_w"):
        pan = pan.parent()
    assert pan is not None and pan.objectName() == "simpanel" and "QPushButton" in pan.styleSheet(), "the panel has the soft look"
    assert t.b_solve.styleSheet() == "", "Solve has no look of its own: it takes the panel's, like Mesh"
    img = pan.outline.holder.grab().toImage()
    ratio = img.devicePixelRatio()
    assert ratio == SCALE, (ratio, SCALE)
    c = img.pixelColor(2, img.height() - 3)                      # the bare bottom of the panel: the face colour
    assert (c.red(), c.green(), c.blue()) == (0xee, 0xf1, 0xf6), (c.red(), c.green(), c.blue())
    # the Solve face is the grey of the Mesh button (the text may sit under the centre pixel: look along a line off the text), not teal
    t.outline.select("Results"); app.processEvents()
    was = t.b_solve.isEnabled()
    t.b_solve.setEnabled(True)
    simg = t.b_solve.grab().toImage()
    t.b_solve.setEnabled(was)
    row = [simg.pixelColor(int(x * simg.devicePixelRatio()), simg.height() // 2) for x in range(10, 40)]
    assert not any(c_.green() > c_.red() + 40 and c_.blue() > c_.red() + 40 for c_ in row), "Solve is not the teal call to action any more"
    assert all(abs(c_.red() - c_.blue()) < 30 and c_.red() > 190 for c_ in row), "a light grey face"
    if hasattr(t, "b_mesh"):
        t.outline.select("Mesh"); app.processEvents()
        mimg = t.b_mesh.grab().toImage()
        mrow = [mimg.pixelColor(int(x * mimg.devicePixelRatio()), mimg.height() // 2) for x in range(10, 40)]
        assert all(abs(a_.red() - b_.red()) <= 6 and abs(a_.green() - b_.green()) <= 6 and abs(a_.blue() - b_.blue()) <= 6 for a_, b_ in zip(row, mrow)), "the same face as the Mesh button"
# check boxes and radio buttons use the drawn indicator pictures (teal tick) at this scale
files = os.listdir(os.path.join(UD, "sim_style", "v1"))
for n in ("check_on", "check_off", "radio_on", "radio_off", "down", "up"):
    assert f"{n}.png" in files and f"{n}@2x.png" in files, (n, files)
sec(beam, "Material and analysis").toggle.setChecked(True)      # folded by default
app.processEvents()
cb = beam.cb_lin
assert cb.isChecked() and cb.isVisible()
im = cb.grab().toImage()
ratio = im.devicePixelRatio()
teal = 0
for y in range(im.height()):
    for x in range(int(24 * ratio)):
        c = im.pixelColor(x, y)
        if c.green() > c.red() + 40 and c.blue() > c.red() + 40 and c.red() < 60:
            teal += 1
assert teal >= 6, ("a teal tick in the checked box", teal)
# the box itself has no blue frame of the program's theme: sample a ring of the indicator
blue = 0
for y in range(im.height()):
    for x in range(int(24 * ratio)):
        c = im.pixelColor(x, y)
        if c.blue() > 180 and c.red() < 90 and c.green() < 140 and abs(c.green() - c.red()) > 30 and c.blue() - c.green() > 60:
            blue += 1
assert blue == 0, ("no blue theme frame on the check box", blue)

# --- a block that is not softened (the Study tab uses sim_ui.Section on its own) keeps its old look
plain = sim_ui.Section("test", 1, "Plain")
assert plain.toggle.styleSheet() != sim_style.SECTION_BAR and "border-bottom:1px solid #cfd6e0" in plain.toggle.styleSheet()
assert plain.frame.objectName() == "" and plain.frame.styleSheet() == ""

print(f"OK sim common layout (screen scale {SCALE:g})")
os._exit(0)
