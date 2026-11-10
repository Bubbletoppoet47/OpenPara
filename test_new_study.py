"""File > New Parametric Study: save the project, import the source, and the study opens for 1D FEA, 2D FEA and 2D CFD - even before a sketch,
supports or a profile exist."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "render", "motor"]}')          # the big add-ons are not needed here (no download, no disk)
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import addons
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
app = QApplication([])
boxes = []
for n in ("information", "warning", "critical"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: boxes.append(a[1:3])))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, gpd_app, ext
addons.install("simulation"); addons.activate()
import sim_tab, study_tab, study_ext

d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
p1, p2 = mm.add_point(0, 0), mm.add_point(1000, 0); mm.add_line(p1, p2)
sk.solve_model(mm); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
part = os.path.join(UD, "p.gpd"); open(part, "w").write(d.to_json())
sh = gpd_app.AppShell([part])
act = [a for a in sh.menuBar().actions()[0].menu().actions() if a.text() == "New Parametric Study..."]
assert len(act) == 1, "the File menu entry (put there by the add-on itself, through ext.add_command)"
assert any(b.text() == "New Parametric Study..." for b in sh.start.buttons) or sh.tabs.count(), "and a button on the start page"
assert not hasattr(gpd_app.AppShell, "new_param_study"), "the program window itself knows nothing about studies"

for kind, label, ext_ in (("beam", "1D FEA (frames and trusses) - of a part", ".gpb"), ("fea", "2D FEA", None), ("cfd", "2D CFD", None)):
    proj = os.path.join(UD, "study_" + kind)
    QInputDialog.getItem = staticmethod(lambda *a, label=label, **k: (label, True))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, proj=proj, **k: (proj, ""))
    sh.tabs.setCurrentIndex(0)
    n0 = sh.tabs.count()
    boxes.clear()
    st = study_ext.new_study(sh)
    assert isinstance(st, study_tab.StudyTab), (kind, boxes)
    assert sh.tabs.indexOf(st) >= 0 and sh.tabs.count() == n0 + 2, "the simulation tab and the study tab are both there"
    folder = [p for p in os.listdir(UD) if p.startswith("study_" + kind)][0]
    assert os.path.isfile(os.path.join(UD, folder, "study", "study.json")), "the study file is made"
    assert os.path.isdir(os.path.join(UD, folder, "source")), "the source is copied into the project"
    print(kind, "opened; note:", st.head.text()[-70:].replace("\n", " "))
    sh.tabs.setCurrentWidget(st)

# cancelling the save window does not leave a half-made tab or an error
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
n0 = sh.tabs.count(); sh.tabs.setCurrentIndex(0)
assert study_ext.new_study(sh) is None and sh.tabs.count() == n0
print("ALL OK")
