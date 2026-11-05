"""The Parametric Studies add-on loaded the real way (a development add-on folder next to the installed Simulation add-on): the button appears under
Solve, creates the study tab in the shell, works for 1D FEA and CFD too, and disappears when the add-on is not there."""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
os.symlink(os.path.join(HERE, "dev_addons", "parametric"), os.path.join(DEV, "parametric"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
import addons
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, gpd_app, ext, sketcher_core as sc

assert "parametric" in addons.dev_ids()
assert addons.install("simulation") or addons.is_installed("simulation")
addons.activate()
import sim_tab, sim_project as sp
assert ext.hooks("sim_study"), "the add-on registers the hook"

d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
r = sk.add_rect_corner(mm, (0, 0), (100, 20))
mm.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); sk.solve_model(mm); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
part = os.path.join(UD, "beam.gpd"); open(part, "w").write(d.to_json())
sh = gpd_app.AppShell([part])

# ---- 1D FEA: a beam along the part's sketch
w = sh.add_sim("beam")
assert w.create_project(os.path.join(UD, "b1")) and w.project_ok()
w.tab.picker.refresh()
w.tab.picker.select(s["id"]); w.tab.picker.go()
t = w.tab
assert getattr(t, "model", None) is not None, "a sketch is imported"
w.refresh_study_button()
assert not w.tab.study_box.isHidden() and w.b_study.text() == "Create parametric study"
n0 = sh.tabs.count()
t.run_task = getattr(t, "run_task", None) or None
tab = w.open_study()
assert tab is not None and sh.tabs.count() == n0 + 1 and sh.tabs.currentWidget() is tab, "the study opens as a tab"
assert w.b_study.text() == "Open parametric study" and os.path.isfile(os.path.join(w.path, "study", "study.json"))
assert tab.title().startswith("Study - b1")
assert sh.tabs.tabText(sh.tabs.indexOf(tab)).startswith("Study - b1")
assert w.open_study() is tab and sh.tabs.count() == n0 + 1
print("study tab opened for", tab.adapter.label, "params", len(tab.desc), "outputs", len(tab.outs), "ready:", tab.adapter.ready())

# ---- 2D CFD
c = sh.new_addon_tab("cfd")
assert c.create_project(os.path.join(UD, "c1")) and c.import_file(part)
c.tab.picker.refresh(); c.tab.picker.select(s["id"]); c.tab.picker.go()
print('cfd model', getattr(c.tab,'model',None), c.status_lbl.text())
c.refresh_study_button()
assert not c.tab.study_box.isHidden()
ct = c.open_study()
assert ct is not None and ct.adapter.label == "2D CFD" and "cfd.e_speed" in ct.desc, list(ct.desc)[:5]

# a coarse CFD study run: pickled to the project, shown again from disk
ct.refresh_params()
ct.tab().e_hb.setText("3") if False else None
tcf = c.tab
tcf.e_hb.setText(str(float(tcf.e_hb.text()) * 3)); tcf.e_hf.setText(str(float(tcf.e_hf.text()) * 3))
tcf.e_steps.setText("30"); tcf.cb_until.setChecked(False); tcf.cb_auto.setChecked(False)
ct.threaded = False
ct.data.checked = ["cfd.e_speed"]; ct.data.rows = [{"cfd.e_speed": tcf.e_speed.text()}, {"cfd.e_speed": str(float(tcf.e_speed.text()) * 2)}]
ct.data.out_checked = ["cfd.status", "cfd.along", "cfd.tris"]
assert ct.run_all(), "cfd run"
assert len(ct.data.cases) == 2 and all(x["status"] != "failed" for x in ct.data.cases), [(x["status"], x["error"]) for x in ct.data.cases]
assert ct.data.cases[1]["file"] and os.path.getsize(os.path.join(c.path, "study", "cases", ct.data.cases[1]["file"])) > 1000
import study_core
re = study_core.StudyData.load(c.path)
assert re.case(1)["result"] is not None
assert ct.show_case(1) and c.tab.result is not None

# ---- the add-on not there: no button
ext.HOOKS.clear()
w.refresh_study_button()
assert w.tab.study_box.isHidden()
print("OK parametric shell")
os._exit(0)
