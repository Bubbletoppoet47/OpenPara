"""The 3D FEA window (.gpv project): copy of a parametric part, face picking, supports and loads, mesh and solve, results, dimension edits that keep
the supports and loads on their faces, save and reopen, and a parametric study over a dimension and a load."""
import os, sys, tempfile, shutil, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, ext
import solid_tab, solid_study, study_ext, study_core as core
import sim_project as sp

T = tempfile.mkdtemp(prefix="opara_solid_")
d = pm.Document(); d.params = {"T": "10"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
r = sk.add_rect_corner(m, (0, 0), (100, 10))
m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
assert d.solid is not None
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())

w = solid_tab.SolidWindow(threaded=False)
assert not w.b_import.isEnabled() and not w.b_save.isEnabled() and not w.b_solve.isEnabled()
assert w.create_project(os.path.join(T, "bar_study")) and w.path.endswith(".gpv") and sp.kind_of_folder(w.path) == "solid"
assert w.import_file(part), MSGS
g = w.geom
assert len(g["faces"]) == 6 and abs(g["volume"] - 10000) < 1e-6 and w.faces.count() == 6 and w.dims.rowCount() >= 3
assert abs(w.setup["material"]["E"] - 200000) < 1 and w.e_E.text() == "200000", "the material of the part fills the boxes"
shutil.move(part, part + ".away")                         # the original is not needed any more
assert not w.ready() is None and "support" in w.ready().lower()

def face(n):
    return next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], n) > 0.99)
left, right, top = face([-1, 0, 0]), face([1, 0, 0]), face([0, 0, 1])
w.select_faces([left]); assert w.add_support("fixed")
w.select_faces([right]); assert w.add_load("force", {"f": [1000.0, 0.0, 0.0]})
assert w.ready() is None and w.sup_list.count() == 1 and w.load_list.count() == 1
w.picked(top, tuple(w.geom["faces"][top]["center"]))        # a click on the top face: selected, nearest vertex remembered
assert w.sel_faces == [top] and w.sel_vertex is not None
w.e_h.setText("6"); w.inputs_changed()
assert w.run_mesh() and w.mesh_q is not None and "tetrahedra" in w.mesh_lbl.text()
assert w.run_solve() and w.result is not None, w.status_lbl.text()
res = w.result
assert abs(res["umax"] - 1000 * 100 / (100 * 200000)) / 0.005 < 0.02 and res["equilibrium"] < 1e-6, res["umax"]
assert "Largest displacement" in w.res_lbl.text()
for i in range(3):
    w.cb_field.setCurrentIndex(i); w.show_field()
w.e_scale.setText("auto"); w.show_field(); w.e_scale.setText("0")
w.e_probe.setText("100, 5, 5")
i, dist, un, vm = w.probe_node()
assert dist < 6 and abs(un - 0.005) / 0.005 < 0.05, (dist, un)
# a pressure, gravity and a point load can be added; a support of another kind
w.select_faces([right]); w.add_load("pressure", {"p": 2.0}); w.add_load("gravity", {"g": 9.81, "dir": [0, 0, -1]})
w.add_load("point", {"f": [0, 0, -5.0]}, vertex=0)
assert w.load_list.count() == 4 and w.edit_load.__func__ is not None
w.remove_item("loads", w.load_list) if False else None
for _ in range(3):
    w.load_list.setCurrentRow(w.load_list.count() - 1); w.remove_item("loads", w.load_list)
assert w.load_list.count() == 1 and w.result is None, "editing the setup clears the result"

# a dimension edit: the bar gets twice as long; the support and the load follow their faces
key = next(k for k, lab, now in w.source.doc.cfg_candidates() if k.startswith("d:") and abs(float(now) - 100) < 1e-9)
assert w.set_dim(key, "200")
assert abs(w.geom["volume"] - 20000) < 1e-3 and w.setup["supports"] and w.setup["dims"] == {key: "200"}
assert w.run_solve(), w.status_lbl.text()
assert abs(w.result["umax"] / 0.005 - 2) < 0.04, w.result["umax"]
assert abs(w.result["reaction"][0] + 1000) < 1e-3
assert w.save() and os.path.isfile(sp.state_path(w.path)) and not w.is_dirty()

# reopen: the dimension edit, supports, loads and material come back; the part copy is used (the original is gone)
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w2.setup["dims"] == {key: "200"} and abs(w2.geom["volume"] - 20000) < 1e-3 and len(w2.setup["supports"]) == 1 and w2.load_list.count() == 1
assert w2.run_solve() and abs(w2.result["umax"] / 0.005 - 2) < 0.04

# the animation
gif = w2.export_animation(os.path.join(T, "a.gif"), frames=4)
if True:
    assert gif and os.path.getsize(gif) > 500, "animation written"

# ---- a parametric study: the length (a dimension of the part) and the force
ext.HOOKS.clear(); study_ext.register(ext)
w2.refresh_study_button()
assert not w2.study_box.isHidden() and w2.b_study.text() == "Create parametric study"
tab = w2.open_study()
tab.threaded = False
assert tab is not None and tab.adapter.label == "3D FEA" and w2.b_study.text() == "Open parametric study"
dd = tab.desc
geo = next(k for k in dd if k.startswith("geo.") and dd[k]["label"].startswith("Part: D1"))
assert "sf.mat.E" in dd and "sf.h" in dd and "sf.load0.fx" in dd and dd[geo]["now"] in ("200", "200.0"), (list(dd)[:12], dd[geo]["now"])
from PyQt6.QtCore import Qt
for pid in (geo, "sf.load0.fx"):
    tab.items[pid].setCheckState(0, Qt.CheckState.Checked)
assert tab.fill_grid({geo: "100, 200", "sf.load0.fx": "1000, 2000"}) and len(tab.data.rows) == 4
tab.data.out_checked = ["sf.status", "sf.umax", "sf.vm", "sf.fos_y"]; tab.fill_outputs()
before = (w2.result, w2.setup_json(), w2.geom)
assert tab.run_all()
cs = tab.data.cases
assert len(cs) == 4 and all(c["status"] == "ok" for c in cs), [(c["status"], c.get("error")) for c in cs]
u = {(c["values"][geo], c["values"]["sf.load0.fx"]): c["outputs"]["sf.umax"] for c in cs}
assert abs(u[("200", "1000")] / u[("100", "1000")] - 2) < 0.05 and abs(u[("100", "2000")] / u[("100", "1000")] - 2) < 0.02, u
assert w2.setup_json() == before[1] and w2.geom is before[2] and w2.result is before[0], "the live window is untouched"
# a case on the screen (a geometry case), then back
assert tab.show_case(0)                                   # L=100
assert abs(w2.geom["volume"] - 10000) < 1e-3 and w2.result is not None
assert tab.own_state is not None
tab.back_to_own()
assert abs(w2.geom["volume"] - 20000) < 1e-3 and w2.result is not None
# a failing case: remove the support's face by a huge change is hard; a bad value is reported
tab.data.rows = [{geo: "100", "sf.load0.fx": "abc"}, {geo: "100", "sf.load0.fx": "500"}]
assert tab.run_all() and [c["status"] for c in tab.data.cases] == ["failed", "ok"]
assert tab.save() and core.exists(w2.path)
study_ext._open.clear()
w3 = solid_tab.SolidWindow.open_project(None, w2.path, threaded=False)
t3 = study_ext.open_study(w3, threaded=False)
assert len(t3.data.cases) == 2 and t3.show_case(1) and w3.result is not None

shutil.rmtree(T, ignore_errors=True)
print("OK solid tab")
os._exit(0)
