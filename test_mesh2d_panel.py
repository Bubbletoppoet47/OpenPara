"""The Mesh page of the 2D FEA and 2D Thermal windows (sim_meshui + sim_meshhost): the same widgets, in the same order, with the same words as the 3D window; a smaller size on the edges,
points and regions you select (the mesh really is finer there); the minimum size and refinement at curves; the element order that reaches the solver; the quality box; saving
and reopening (a file from before the advanced options keeps its linear elements); changing the unit system; the studies; the Diagnostics report."""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"),
                os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel, QLayout, QMessageBox, QPushButton, QTableWidget
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

import physics_fea as pf
import physics_geom as pg
import physics_tab
import sim_mesh2d as sm2
import sim_tab
import sketcher_core as sc
import study_iface as si
import thermal_tab as tt
import unitctl
import units

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


def run_now(tab, title, fn):
    try:
        return "ok", fn(lambda *a, **k: None, lambda: False)
    except (pg.Cancelled, pf.Cancelled):
        return "cancelled", None
    except (pg.GeometryError, pf.ModelError) as ex:
        QMessageBox.warning(tab, title, str(ex))
        return "user", str(ex)


def rect(w=100.0, h=20.0, hole=None):
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (w, 0), (w, h), (0, h))]
    ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]            # 0 bottom, 1 right, 2 top, 3 left
    ci = None
    if hole:
        c = m.add_point(*hole[:2])
        ci = m.add_circle(c, hole[2])
    return m, p, ls, ci


def new_fea(model=None):
    t = physics_tab.PhysicsTab(host())
    t.run_task = lambda title, fn: run_now(t, title, fn)
    if model is not None:
        t.set_model(model, "plate")
    t.resize(1200, 900)
    t.show()
    app.processEvents()
    return t


def new_th(model=None):
    unitctl.set_units("Metric (mm, kg, N, s, MPa)", notify=False, persist=False)
    t = tt.ThermalTab(host())
    t.run_task = lambda title, fn: run_now(t, title, fn)
    if model is not None:
        t.set_model(model, "plate")
    t.resize(1200, 900)
    t.show()
    app.processEvents()
    return t


def mesh_section(t):
    return next(s for s in t.sections if s.title == "Mesh")


def texts(box):
    """Every text of a layout tree, in the order it is laid out: labels, tick boxes, buttons, the headers of a table."""
    out = []

    def walk_layout(lay):
        for i in range(lay.count()):
            it = lay.itemAt(i)
            if it.layout() is not None:
                walk_layout(it.layout())
            elif it.widget() is not None:
                walk_widget(it.widget())

    def walk_widget(w):
        if isinstance(w, (QLabel, QCheckBox, QPushButton)):
            out.append(w.text())
        elif isinstance(w, QTableWidget):
            out.append("|".join(w.horizontalHeaderItem(i).text() for i in range(w.columnCount())))
        elif w.layout() is not None:
            walk_layout(w.layout())
    walk_widget(box)
    return out


def ok(c, msg):
    assert c, msg
    print("ok:", msg)


# =============================================================================================================================== 1. the page: the same as the 3D window
import build123d as b123
import solid_tab
fea = new_fea(rect()[0])
th = new_th(rect()[0])
w3 = solid_tab.SolidWindow(threaded=False)
w3.resize(1300, 1500)
w3.show()
app.processEvents()

for name, t in (("2D FEA", fea), ("2D Thermal", th)):
    sec = mesh_section(t)
    t.outline.select("Mesh")
    app.processEvents()
    ok(sec.isAncestorOf(t.e_h) and sec.isAncestorOf(t.cb_adv) and sec.isAncestorOf(t.b_mesh) and sec.isAncestorOf(t.mesh_lbl) and sec.isAncestorOf(t.quality_box), f"{name}: the Mesh page holds the size, the options, Mesh, the line and the quality box")
    ok(t.cb_adv.text() == "Advanced mesh options" and not t.cb_adv.isChecked() and not t.adv_box.isVisibleTo(t), f"{name}: the options are hidden until the box is ticked")
    ok(not hasattr(t, "elements_row"), f"{name}: no separate Elements row any more")
    ys = [x.mapTo(t, x.rect().topLeft()).y() for x in (t.e_h, t.cb_adv, t.b_mesh, t.mesh_lbl)]
    ok(ys == sorted(ys) and len(set(ys)) == 4, f"{name}: size, options, Mesh button, mesh line - top to bottom ({ys})")
    t.cb_adv.setChecked(True)
    app.processEvents()
    ys = [x.mapTo(t, x.rect().topLeft()).y() for x in (t.e_h, t.cb_adv, t.adv_box, t.b_mesh)]
    ok(t.adv_box.isVisibleTo(t) and ys == sorted(ys), f"{name}: the options open between the size and the Mesh button")
    ok([t.order_combo.itemData(i) for i in range(t.order_combo.count())] == [2, 1] and t.order_combo.currentData() == 2, f"{name}: quadratic first, linear second")
    ok(t.order_combo.itemText(0) == "Quadratic (6-node triangles)" and t.order_combo.itemText(1) == "Linear (3-node triangles)", f"{name}: the order texts are the ones a saved file knows")
    ok(t.e_growth.text() == "1.3" and not t.cb_curv.isChecked() and not t.sp_curv.isEnabled() and t.e_hmin.text() == "", f"{name}: defaults - growth 1.3, curvature refinement off (the plain 2D mesh does not do it), no minimum size")
    ok(t.type_combo is None and t.follows_combo is None, f"{name}: hex-dominant and 'Mesh follows' are 3D only")
    t.cb_adv.setChecked(False)

w3.outline.select("Mesh")
w3.cb_adv.setChecked(True)
app.processEvents()
t3 = texts(w3.adv_box)
t2 = texts(fea.adv_box)
fea.cb_adv.setChecked(True)
t2 = texts(fea.adv_box)
only3 = ("Mesh type", "Mesh follows")
rows3 = [x for x in t3 if x not in only3]
ok(len(rows3) == len(t2), f"the 3D options and the 2D options have as many rows ({len(rows3)} / {len(t2)})")
TXT_2D = list(t2)
ok(texts(th.adv_box) == t2, "the 2D FEA and the 2D Thermal window show the very same options")
diff = [(a, b_) for a, b_ in zip(rows3, t2) if a != b_]
for a, b_ in diff:
    print("   3D:", a, "|| 2D:", b_)
ok(all(("faces" in a or "surfaces" in a or "Minimum size" in a) for a, b_ in diff), "only the words that name what is refined differ (faces / surfaces against edges, points and regions)")
ok("Element order" in t2 and "Minimum size (mm)" in t2 or any(x.startswith("Minimum size") for x in t2), "the labels are the 3D ones: Element order, Minimum size, Growth rate")
ok("Growth rate" in t2 and "Set on selection" in t2 and "Remove selected size" in t2 and "Where|Size" in t2, "Growth rate, Set on selection, Remove selected size and the Where | Size list")
ok(fea.cb_auto.text() == "Adaptive mesh (h)" and fea.cb_auto.text() == w3.cb_adapt.text(), "the adaptive tick box has the 3D words")
fea.cb_auto.setChecked(True)
app.processEvents()
ok(texts(fea.auto_box)[0] == "Maximum loops" and "Largest mesh (elements)" in texts(fea.auto_box), "its two numbers are called Maximum loops and Largest mesh (elements)")
ok(not hasattr(th, "cb_auto"), "the Thermal window has no adaptive mesh (there is no refinement loop for it)")
fea.cb_auto.setChecked(False)
fea.cb_adv.setChecked(False)
w3.close()

# =============================================================================================================================== 2. a smaller size on a selection - and the mesh really is finer there
def nodes_on(mesh, axis, value, tol=1e-6):
    n = np.asarray(mesh["nodes"])
    return int(np.sum(np.abs(n[:, axis] - value) < tol))


for name, maker in (("2D FEA", new_fea), ("2D Thermal", new_th)):
    m, p, ls, _ = rect(100.0, 20.0)
    t = maker(m)
    t.outline.select("Mesh")
    t.e_h.setText("8")
    t.cb_adv.setChecked(True)
    app.processEvents()
    t.canvas.sel = [("ln", ls[0])]
    t.e_face_h.setText("2")
    STATUS.clear()
    t.b_face_size.click()
    ok(t.face_table.rowCount() == 1 and t.face_table.item(0, 0).text() == f"Line {ls[0]}" and float(t.face_table.item(0, 1).text()) == 2.0, f"{name}: the size is in the list ({t.face_table.item(0, 0).text()})")
    ok(sm2.options(t.mesh_opts)["local"] == [{"targets": [("ln", ls[0])], "h": 2.0}], f"{name}: the options hold it")
    t.run_mesh()
    ok(t.mesh is not None, f"{name}: meshed")
    nb, nt = nodes_on(t.mesh, 1, 0.0), nodes_on(t.mesh, 1, 20.0)
    ok(nb >= 45 and nt <= 20 and nb > 2.5 * nt, f"{name}: the bottom edge got {nb} nodes (size 2 = about 51), the top edge {nt} (size 8 = about 13)")
    ok(t.quality_box.isVisibleTo(t) and "radius ratio" in t.quality_lbl.text() and f"{t.mesh['stats']['n_tris']:,} triangles" in t.quality_lbl.text(), f"{name}: the quality box is shown after a mesh, with the number of triangles")
    ok(f"{t.mesh['stats']['n_tris']:,} triangles" in t.mesh_lbl.text() and "quadratic" in t.mesh_lbl.text(), f"{name}: the line under Mesh says what was made ({t.mesh_lbl.text()})")
    # the size can be edited in the list; a bad number is undone
    t.face_table.item(0, 1).setText("3")
    ok(sm2.options(t.mesh_opts)["local"][0]["h"] == 3.0, f"{name}: a size is edited in the list")
    STATUS.clear()
    t.face_table.item(0, 1).setText("abc")
    app.processEvents()
    ok(STATUS and "number" in STATUS[-1] and sm2.options(t.mesh_opts)["local"][0]["h"] == 3.0 and t.face_table.item(0, 1).text() == "3", f"{name}: a size that is not a number is refused and the list shows the old one")
    # a size that is not smaller than the element size is refused
    t.canvas.sel = [("ln", ls[2])]
    t.e_face_h.setText("9")
    STATUS.clear()
    ok(t.set_face_size() is False and "smaller than the element size" in STATUS[-1] and t.face_table.rowCount() == 1, f"{name}: a local size above the element size is refused ({STATUS[-1]})")
    # a point and a region as targets; the same targets again change the size instead of adding a row
    t.canvas.sel = [("pt", p[2])]
    t.regions.setCurrentRow(0)
    t.regions.item(0).setSelected(True)
    t.e_face_h.setText("4")
    ok(t.set_face_size() and t.face_table.rowCount() == 2, f"{name}: a point and a region together are one entry")
    ok("Point" in t.face_table.item(1, 0).text() and "Region 1" in t.face_table.item(1, 0).text(), f"{name}: it is named by what it is on ({t.face_table.item(1, 0).text()})")
    t.e_face_h.setText("5")
    ok(t.set_face_size() and t.face_table.rowCount() == 2 and float(t.face_table.item(1, 1).text()) == 5.0, f"{name}: the same selection again changes its size")
    t.regions.item(0).setSelected(False)
    t.canvas.sel = []
    STATUS.clear()
    ok(t.set_face_size() is False and "Select" in STATUS[-1], f"{name}: nothing selected: it says so")
    t.face_table.setCurrentCell(1, 0)
    ok(t.remove_face_size() and t.face_table.rowCount() == 1, f"{name}: Remove selected size")
    STATUS.clear()
    t.face_table.setCurrentCell(-1, -1)
    ok(t.remove_face_size() is False and "Select a row" in STATUS[-1], f"{name}: Remove with nothing chosen says so")
    # the minimum size: a local size below it is refused when meshing
    t.e_hmin.setText("3.5")
    t.e_hmin.editingFinished.emit()
    ok("minimum size" in STATUS[-1].lower(), f"{name}: a minimum size above a local size is refused ({STATUS[-1]})")
    MSGS.clear()
    t.run_mesh()
    ok(MSGS and "minimum size" in MSGS[-1].lower(), f"{name}: and Mesh says why it cannot mesh")
    t.e_hmin.setText("")
    t.e_hmin.editingFinished.emit()
    t.face_table.setCurrentCell(0, 0)
    t.remove_face_size()
    ok(t.face_table.rowCount() == 0 and sm2.options(t.mesh_opts) is None, f"{name}: no sizes left: the plain mesh again")
    t.run_mesh()
    ok(abs(nodes_on(t.mesh, 1, 0.0) - nodes_on(t.mesh, 1, 20.0)) <= 2, f"{name}: the plain mesh has the same count on both long edges")
    # Advanced off: the sizes are kept in the list but the mesh is plain
    t.canvas.sel = [("ln", ls[0])]
    t.e_face_h.setText("2")
    t.set_face_size()
    t.cb_adv.setChecked(False)
    app.processEvents()
    ok(t.mesher_options() is None and not t.quality_box.isVisibleTo(t) and not t.adv_box.isVisibleTo(t), f"{name}: Advanced off: the plain mesh, no quality box")
    t.run_mesh()
    ok(abs(nodes_on(t.mesh, 1, 0.0) - nodes_on(t.mesh, 1, 20.0)) <= 2, f"{name}: with Advanced off the local size is not used")
    t.cb_adv.setChecked(True)
    app.processEvents()
    ok(t.face_table.rowCount() == 1, f"{name}: ticking it again finds the size still there")

# =============================================================================================================================== 3. refinement at curves, the order that reaches the solver
m, p, ls, ci = rect(100.0, 60.0, hole=(50.0, 30.0, 10.0))
fea = new_fea(m)
fea.e_h.setText("10")
fea.cb_adv.setChecked(True)
fea.cb_curv.setChecked(True)
fea.sp_curv.setValue(24)
ok(fea.sp_curv.isEnabled(), "the number per circle is enabled with the tick box")
fea.run_mesh()
nn = np.asarray(fea.mesh["nodes"])
on_circle = int(np.sum(np.abs(np.hypot(nn[:, 0] - 50.0, nn[:, 1] - 30.0) - 10.0) < 1e-6))
ok(on_circle == 24, f"24 elements around the hole were asked for and got {on_circle}")
fea.sp_curv.setValue(12)
fea.run_mesh()
nn = np.asarray(fea.mesh["nodes"])
ok(int(np.sum(np.abs(np.hypot(nn[:, 0] - 50.0, nn[:, 1] - 30.0) - 10.0) < 1e-6)) == 12, "and 12 when 12 were asked for")
fea.cb_curv.setChecked(False)
fea.run_mesh()
nn = np.asarray(fea.mesh["nodes"])
plain = int(np.sum(np.abs(np.hypot(nn[:, 0] - 50.0, nn[:, 1] - 30.0) - 10.0) < 1e-6))
ok(plain < 12, f"with the tick box off the hole gets the plain {plain} nodes")

# the order: linear only with Advanced on
fea.cb_adv.setChecked(False)
ok(fea.element_order() == 2 and fea.read_material()["order"] == 2, "Advanced off: quadratic")
fea.cb_adv.setChecked(True)
fea.order_combo.setCurrentIndex(fea.order_combo.findData(1))
fea.order_combo.activated.emit(fea.order_combo.currentIndex())
ok(fea.element_order() == 1 and fea.read_material()["order"] == 1 and fea.mesh_opts["order"] == 1, "Advanced on, linear chosen: linear reaches the solver")
fea.supports = [{"mode": "fixed", "targets": [("ln", ls[3])]}]
fea.loads = [{"kind": "force", "fx": 0.0, "fy": -50.0, "targets": [("pt", p[2])]}]
fea.run_mesh()
fea.run_solve()
ok(fea.result is not None and fea.result["order"] == 1 and "linear" in fea.mesh_lbl.text(), "a solve with linear elements says so")
ok("linear" in fea.quality_lbl.text(), "and so does the quality box")
fea.cb_adv.setChecked(False)
fea.run_solve()
ok(fea.result["order"] == 2 and "quadratic" in fea.mesh_lbl.text(), "Advanced off again: the next solve is quadratic")

# the thermal tab: the order reaches its solver setup too
m, p, ls, _ = rect()
th = new_th(m)
th.cb_adv.setChecked(True)
th.order_combo.setCurrentIndex(th.order_combo.findData(1))
th.order_combo.activated.emit(th.order_combo.currentIndex())
ok(th.element_order() == 1, "2D Thermal: linear chosen under Advanced")
th.cb_adv.setChecked(False)
ok(th.element_order() == 2, "2D Thermal: Advanced off: quadratic")

# =============================================================================================================================== 4. saving and reopening
m, p, ls, ci = rect(100.0, 60.0, hole=(50.0, 30.0, 10.0))
for name, maker in (("2D FEA", new_fea), ("2D Thermal", new_th)):
    t = maker(m)
    t.e_h.setText("10")
    t.cb_adv.setChecked(True)
    t.order_combo.setCurrentIndex(t.order_combo.findData(1))
    t.e_hmin.setText("0.5")
    t.e_growth.setText("1.6")
    t.cb_curv.setChecked(True)
    t.sp_curv.setValue(18)
    t.canvas.sel = [("ln", ls[0]), ("ci", ci)]
    t.e_face_h.setText("3")
    t.set_face_size()
    st = t.export_state()
    ok(st["mesh_opts"]["advanced"] and st["mesh_opts"]["order"] == 1 and st["mesh_opts"]["hmin"] == 0.5 and st["mesh_opts"]["growth"] == 1.6 and st["mesh_opts"]["curv"] == 18, f"{name}: the saved state holds the options")
    import json
    st = json.loads(json.dumps(st, default=lambda o: None if isinstance(o, np.ndarray) else o.tolist() if hasattr(o, "tolist") else str(o)))
    t2 = maker()
    t2.import_state(st)
    app.processEvents()
    mo = sm2.complete(t2.mesh_opts)
    ok(t2.cb_adv.isChecked() and not t2.adv_box.isHidden() and t2.order_combo.currentData() == 1 and t2.e_hmin.text() == "0.5" and t2.e_growth.text() == "1.6", f"{name}: reopened - the boxes show the options")
    ok(t2.cb_curv.isChecked() and t2.sp_curv.value() == 18 and t2.sp_curv.isEnabled(), f"{name}: reopened - curvature refinement is on with its number")
    ok(len(mo["local"]) == 1 and mo["local"][0]["h"] == 3.0 and sorted(mo["local"][0]["targets"]) == sorted([("ln", ls[0]), ("ci", ci)])
       and all(isinstance(x, tuple) for x in mo["local"][0]["targets"]), f"{name}: reopened - the local size and its targets (as tuples again, after the JSON file)")
    ok(t2.face_table.rowCount() == 1 and t2.element_order() == 1, f"{name}: reopened - the list and the order")
    # a file from before the advanced options: the order was a box of its own
    old = dict(st)
    old.pop("mesh_opts")
    old["inputs"] = dict(old["inputs"], order_combo="Linear (3-node triangles)")
    t3 = maker()
    t3.import_state(old)
    ok(t3.cb_adv.isChecked() and t3.element_order() == 1 and t3.order_combo.currentData() == 1, f"{name}: an old file with linear elements opens with the advanced options on and linear elements")
    old["inputs"] = dict(old["inputs"], order_combo="Quadratic (6-node triangles)")
    t4 = maker()
    t4.import_state(old)
    ok(not t4.cb_adv.isChecked() and t4.element_order() == 2 and sm2.options(t4.mesh_opts) is None, f"{name}: an old file with quadratic elements opens with the plain mesh")
    old["inputs"].pop("order_combo")
    t5 = maker()
    t5.import_state(old)
    ok(not t5.cb_adv.isChecked() and t5.element_order() == 2, f"{name}: an old file with no order at all: the plain mesh")

# =============================================================================================================================== 5. the unit system changes
import physics_store as pstore
import thermal_store as tstore
for name, maker, conv in (("2D FEA", new_fea, pstore.convert_fea_state), ("2D Thermal", new_th, tstore.convert_state)):
    m, p, ls, ci = rect(100.0, 60.0)
    m.unit_system = "Metric (mm, kg, N, s, MPa)"
    t = maker(m)
    t.e_h.setText("10")
    t.cb_adv.setChecked(True)
    t.e_hmin.setText("1")
    t.e_hmin.editingFinished.emit()
    t.canvas.sel = [("ln", ls[0])]
    t.e_face_h.setText("2")
    t.set_face_size()
    st = conv(t.export_state(), "Metric (mm, kg, N, s, MPa)", "US (in, lbf, psi)", True)
    f = 1.0 / 25.4
    ok(abs(st["mesh_opts"]["hmin"] - 1.0 * f) < 1e-9 and abs(st["mesh_opts"]["local"][0]["h"] - 2.0 * f) < 1e-9, f"{name}: converting to inches scales the minimum size and the local size ({st['mesh_opts']['hmin']:.5g}, {st['mesh_opts']['local'][0]['h']:.5g})")
    ok(abs(float(st["inputs"]["e_h"]) - 10 * f) < 1e-6, f"{name}: like the element size")
    st2 = conv(t.export_state(), "Metric (mm, kg, N, s, MPa)", "US (in, lbf, psi)", False)
    ok(st2["mesh_opts"]["hmin"] == 1.0 and st2["mesh_opts"]["local"][0]["h"] == 2.0, f"{name}: a relabel keeps the numbers (like the element size)")

# =============================================================================================================================== 6. the studies and the Diagnostics report
m, p, ls, ci = rect(100.0, 20.0)
t = new_fea(m)
t.supports = [{"mode": "fixed", "targets": [("ln", ls[3])]}]
t.loads = [{"kind": "force", "fx": 0.0, "fy": -2.0, "targets": [("pt", p[2])]}]
t.e_h.setText("8")
ad = t.study_adapter()
ctx = {}
spec = ad.prepare({}, ctx)
ok(spec["error"] is None, "the FEA study prepares a case")
spec["run"](lambda *a, **k: None, lambda: False)
ok(len(ctx["cache"]) == 1, "the first case made one mesh")
t.cb_adv.setChecked(True)
t.canvas.sel = [("ln", ls[0])]
t.e_face_h.setText("2")
t.set_face_size()
spec = ad.prepare({}, ctx)
case = spec["run"](lambda *a, **k: None, lambda: False)
ok(len(ctx["cache"]) == 2, "a local size is another mesh in the cache (the key holds the options)")
refined = ad.case_outputs(case, ["fea.tris"])["fea.tris"]
t.cb_adv.setChecked(False)
base = ad.case_outputs(ad.prepare({}, {})["run"](lambda *a, **k: None, lambda: False), ["fea.tris"])["fea.tris"]
ok(refined > 1.5 * base, f"the study mesh with the local size has more triangles ({refined}) than the plain one ({base})")

tw = new_th(rect()[0])
tad = tw.study_adapter()
ok("thermal.order_combo" in {d["id"] for d in tad.params()}, "the Thermal study still offers the element order")
tw.cb_adv.setChecked(False)
tw.run_task = lambda title, fn: run_now(tw, title, fn)
sc_ = tad.scratch(None) if hasattr(tad, "scratch") else None
if sc_ is not None:
    tad.apply(sc_, {"thermal.order_combo": "Linear (3-node triangles)"})
    ok(sc_.cb_adv.isChecked() and sc_.element_order() == 1, "a study that sets the order to linear turns the advanced options on in its scratch tab")

d = t.diagnostics_text()
ok("mesh options: plain" in d, "the Diagnostics report says the mesh is plain")
t.cb_adv.setChecked(True)
d = t.diagnostics_text()
ok("mesh options: advanced" in d and "local size 2" in d and "Line" in d, "and lists the options and the local sizes when they are on")

# =============================================================================================================================== 7. the 2D CFD window: what applies to it
import cfd_tab
import physics_cfd as pcfd


def new_cfd(model):
    t = cfd_tab.CFDTab(host())
    t.run_task = lambda title, fn: run_now(t, title, fn)
    t.set_model(model, "cylinder")
    t.resize(1200, 900)
    t.show()
    app.processEvents()
    return t


def cylinder(r=5.0):
    m = sc.Model()
    c = m.add_point(0.0, 0.0)
    ci = m.add_circle(c, r)
    return m, ci


m, ci = cylinder()
cf = new_cfd(m)
cf.outline.select("Mesh")
app.processEvents()
tc = texts(cf.adv_box)
ok(cf.order_combo is None and cf.type_combo is None and cf.follows_combo is None, "CFD: no element order (the CFD elements are fixed), no mesh type, no 'follows'")
no_order = [x for x in TXT_2D if x != "Element order"]
ok(len(tc) == len(no_order), f"CFD: the 2D options without the order row ({len(tc)} / {len(no_order)})")
ok([x for x in tc if "single edges" not in x] == [x for x in no_order if "single edges" not in x], "CFD: the same labels, in the same order (minimum size, growth rate, curvature, set on selection, the list)")
ok(any("single edges and points of the bodies" in x for x in tc) and not any("region" in x.lower() for x in tc), "CFD: local sizes go on edges and points of the bodies, no regions")
cf.cb_adv.setChecked(True)
app.processEvents()
ys = [x.mapTo(cf, x.rect().topLeft()).y() for x in (cf.e_hb, cf.e_hf, cf.cb_adv, cf.adv_box, cf.b_mesh, cf.mesh_lbl)]
ok(ys == sorted(ys) and len(set(ys)) == 6, f"CFD: the options sit under the sizes and the boundary layer, over the Mesh button ({ys})")
ok(cf.element_order() == 2 and cf.read_mesh_options()["order"] == 2, "CFD: the order is not an option")

cf.e_hb.setText("2")
cf.e_hf.setText("10")
cf.cb_until.setChecked(False)


def circle_nodes(mesh, r=5.0):
    nn = np.asarray(mesh["nodes"])
    return int(np.sum(np.abs(np.hypot(nn[:, 0], nn[:, 1]) - r) < 1e-6))


cf.run_mesh()
ok(cf.mesh is not None, "CFD: meshed")
plain = circle_nodes(cf.mesh)
ok(plain <= 20, f"CFD: the plain mesh puts {plain} nodes round the cylinder (size 2: about 16)")
ok("triangles" in cf.mesh_lbl.text() and "quadratic velocity" in cf.mesh_lbl.text(), f"CFD: the line under Mesh ({cf.mesh_lbl.text()})")
cf.cb_curv.setChecked(True)
cf.sp_curv.setValue(48)
cf.run_mesh()
ok(circle_nodes(cf.mesh) == 48, f"CFD: 48 elements round the cylinder were asked for and got {circle_nodes(cf.mesh)}")
ok("radius ratio" in cf.quality_lbl.text() and "quadratic velocity" in cf.quality_lbl.text(), "CFD: the quality box is filled")
cf.cb_curv.setChecked(False)
cf.canvas.sel = [("ci", ci)]
cf.e_face_h.setText("0.5")
ok(cf.set_face_size() and cf.face_table.rowCount() == 1, "CFD: a local size on the circle")
cf.run_mesh()
ok(circle_nodes(cf.mesh) >= 55, f"CFD: size 0.5 on the circle (31.4 long) gave {circle_nodes(cf.mesh)} nodes")
STATUS.clear()
cf.e_face_h.setText("3")
ok(cf.set_face_size() is False and "smaller than the element size" in STATUS[-1], "CFD: a local size above the size at the body is refused")
cf.canvas.sel = []
STATUS.clear()
cf.e_face_h.setText("1")
ok(cf.set_face_size() is False and "body" in STATUS[-1], f"CFD: nothing selected: {STATUS[-1]}")
cf.cb_adv.setChecked(False)
cf.run_mesh()
ok(circle_nodes(cf.mesh) == plain, "CFD: Advanced off: the plain mesh again")
# save, reopen, units
cf.cb_adv.setChecked(True)
cf.e_hmin.setText("0.2")
cf.e_hmin.editingFinished.emit()
st = cf.export_state()
ok(st["mesh_opts"]["advanced"] and st["mesh_opts"]["hmin"] == 0.2 and len(st["mesh_opts"]["local"]) == 1, "CFD: the saved state holds the options")
cf2 = cfd_tab.CFDTab(host())
cf2.import_state(st)
ok(cf2.cb_adv.isChecked() and cf2.e_hmin.text() == "0.2" and cf2.face_table.rowCount() == 1 and cf2.face_table.item(0, 0).text() == f"Circle {ci}", "CFD: reopened with the options and the list")
import json
old = dict(st)
old.pop("mesh_opts")
cf3 = cfd_tab.CFDTab(host())
cf3.import_state(old)
ok(not cf3.cb_adv.isChecked() and sm2.options(cf3.mesh_opts) is None, "CFD: an old file opens with the plain mesh")
conv = pstore.convert_cfd_state(st, "Metric (mm, kg, N, s, MPa)", "US (in, lbf, psi)", True)
ok(abs(conv["mesh_opts"]["hmin"] - 0.2 / 25.4) < 1e-9 and abs(conv["mesh_opts"]["local"][0]["h"] - 0.5 / 25.4) < 1e-9, "CFD: units: the minimum size and the local size are converted")

# a minimum size: with Advanced on, no elements smaller than it are made away from the walls' fields
cf.cb_adv.setChecked(True)
cf.face_table.setCurrentCell(0, 0)
cf.remove_face_size()
cf.e_hmin.setText("1.5")
cf.e_hmin.editingFinished.emit()
cf.canvas.sel = []
cf.cb_curv.setChecked(True)
cf.sp_curv.setValue(100)
cf.run_mesh()
nmin = circle_nodes(cf.mesh)
ok(16 < nmin <= 26, f"CFD: a minimum size of 1.5 limits the curvature refinement ({nmin} nodes round the cylinder of 31.4 round, 100 asked for)")
# the study uses the same options, and a case without them is another mesh in its cache
cf.e_steps.setText("3")
cf.cb_until.setChecked(False)
cf.cb_auto.setChecked(False)
ad = cf.study_adapter()
ctxc = {}
case = ad.prepare({}, ctxc)["run"](lambda *a, **k: None, lambda: False)
ok(case.get("mesh") is not None and circle_nodes(case["mesh"]) == nmin, f"CFD study: the case is meshed with the options ({case.get('error', '')[:80]})")
cf.cb_adv.setChecked(False)
case2 = ad.prepare({}, ctxc)["run"](lambda *a, **k: None, lambda: False)
ok(circle_nodes(case2["mesh"]) == plain and len(ctxc["cache"]) == 2, "CFD study: with Advanced off it is the plain mesh, kept apart in the cache")

print("ALL OK")
