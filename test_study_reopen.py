"""A parametric study can be closed and opened again (it used to fail with "wrapped C/C++ object of type StudyTab has been deleted"); closing
the simulation tab closes its study first; closing a study while it runs asks, stops the run and keeps the finished cases."""
import os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "render", "motor"]}')          # the big add-ons are not needed here (no download, no disk)
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
os.symlink(os.path.join(HERE, "dev_addons", "parametric"), os.path.join(DEV, "parametric"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import addons
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
ASK = []
for n in ("information", "warning", "critical"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: ASK.append(a[2])))
QMessageBox.question = staticmethod(lambda *a, **k: (ASK.append(a[2]), QMessageBox.StandardButton.Yes)[1])
import pm_model as pm, sk_tools as sk, gpd_app
assert addons.install("simulation") or addons.is_installed("simulation")
addons.activate()
import ext
addons.register_extensions(ext)
import sim_tab, profiles1d as pr1, study_ext, study_tab


def purge():
    """What the real program does between two clicks: Qt deletes the widgets of closed tabs."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    app.processEvents()


d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
p1, p2 = mm.add_point(0, 0), mm.add_point(1000, 0); mm.add_line(p1, p2)
sk.solve_model(mm); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
part = os.path.join(UD, "p.gpd"); open(part, "w").write(d.to_json())
sh = gpd_app.AppShell([part])
w = sh.add_sim("beam")
assert w.create_project(os.path.join(UD, "b1"))
w.tab.picker.refresh(); w.tab.picker.select(s["id"]); w.tab.picker.go()
t = w.tab
ends = list(t.model.lns[next(iter(t.model.lns))][:2])
t.set_profiles([0], pr1.compute("rect", {"b": 20.0, "h": 40.0}))
t.supports = [{"mode": "fixed", "targets": [ends[0]]}]
t.loads = [{"kind": "force", "fx": 0.0, "fy": -100.0, "targets": [ends[1]]}]
proj = w.path

# ---- 1. open, close, open again (three times: every reopen makes a fresh tab)
st = w.open_study()
assert isinstance(st, study_tab.StudyTab) and w.open_study() is st, "open twice: the same tab is shown"
for k in range(3):
    assert sh.close_tab(sh.tabs.indexOf(st)); purge()
    st2 = w.open_study()
    assert isinstance(st2, study_tab.StudyTab) and st2 is not st and sh.tabs.indexOf(st2) >= 0, f"reopen {k + 1}"
    st = st2
# also after the profile was changed and changed back in between (how it was first seen)
assert sh.close_tab(sh.tabs.indexOf(st)); purge()
t.set_profiles([0], pr1.compute("pipe", {"d": 60.3, "t": 3.9})); t.set_profiles([0], pr1.compute("rect", {"b": 20.0, "h": 40.0}))
st = w.open_study(); assert sh.tabs.indexOf(st) >= 0

# ---- 2. closing a study that is running: asked, the run stops, what was finished is kept and saved, the simulation tab is usable again
st.refresh_params()
st.items["beam.load0.fy"].setCheckState(0, Qt.CheckState.Checked)
assert st.fill_range({"beam.load0.fy": ("-100", "-900", 300)}, together=True, log=False, rows=300, confirm=False)
st.data.out_checked = ["beam.status", "beam.umax"]; st.fill_outputs()
assert st.run_all() and st.running()
t0 = time.time()
while len(st.data.cases) < 15 and time.time() - t0 < 60:
    app.processEvents(); time.sleep(0.002)
assert st.running() and len(st.data.cases) >= 15
ASK.clear()
assert sh.close_tab(sh.tabs.indexOf(st)), "the user agreed to stop"
assert any("A study is running" in a for a in ASK), ASK
assert not w.tab.isEnabled() is True or w.tab.isEnabled(), "(the simulation tab is enabled again)"
assert w.tab.isEnabled() and sh.tabs.indexOf(w) >= 0
purge()
import study_core
kept = study_core.StudyData.load(proj)
assert 15 <= len(kept.cases) < 300 and all(c["status"] == "ok" for c in kept.cases), len(kept.cases)
time.sleep(0.3); app.processEvents()                       # nothing arrives from a worker after its tab is gone
st = w.open_study()
assert len(st.data.cases) == len(kept.cases) and st.res_table.rowCount() == len(kept.cases), "the reopened study shows the kept cases"

# ---- 3. closing the simulation tab closes its study first; the project opens again with its study
assert sh.dependents(w) == [st]
n = sh.tabs.count()
assert sh.close_tab(sh.tabs.indexOf(w)) and sh.tabs.count() == n - 2, "both tabs are gone"
purge()
w2 = sh.open_path(proj)
assert isinstance(w2, sim_tab.SimWindow) and w2.path == proj
st3 = w2.open_study()
assert isinstance(st3, study_tab.StudyTab) and len(st3.data.cases) == len(kept.cases)
assert sh.close_tabs() and sh.tabs.count() == 0

# ---- 4. the same kind of mistake in the simulation tab: the part it was made from is closed before the project is created
part_tab = sh.open_path(part)
w3 = sh.add_sim("beam")
assert w3.candidate is part_tab and sh.is_open(part_tab)
assert sh.close_tab(sh.tabs.indexOf(part_tab)); purge()
assert not sh.is_open(part_tab), "a closed tab is reported as closed, without an error"
assert w3.candidate_ok() is False
assert w3.create_project(os.path.join(UD, "b2")) and w3.project_ok(), "the project is made; the source is imported afterwards"
print("OK study reopen")
import shutil; shutil.rmtree(UD, ignore_errors=True); shutil.rmtree(DEV, ignore_errors=True)
os._exit(0)
