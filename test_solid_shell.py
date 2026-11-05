"""3D FEA loaded the real way: development add-on folder next to the installed Simulation add-on. File > New 3D FEA, Import from an open part tab,
Open Project Folder on a .gpv, and the Parametric Studies button."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for n in ("parametric", "solid_fea"):
    os.symlink(os.path.join(HERE, "dev_addons", n), os.path.join(DEV, n))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
import addons
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, gpd_app, ext

assert {"solid_fea", "parametric"} <= set(addons.dev_ids())
assert addons.install("simulation") or addons.is_installed("simulation")
addons.activate()
assert "solid" in addons.tab_kinds() and addons.tab_kinds()["solid"]["project_folder"]["format"] == "openpara-sim-solid"
import solid_tab

d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
sk.add_rect_corner(mm, (0, 0), (60, 10)); sk.solve_model(mm); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="8")); d.rebuild()
part = os.path.join(UD, "bar.gpd"); open(part, "w").write(d.to_json())
sh = gpd_app.AppShell([part])
labels = [a.text() for a in sh.menuBar().actions()[0].menu().actions()]
assert "New 3D FEA" in labels and "New 2D FEA" in labels, labels
w = sh.new_addon_tab("solid")
assert isinstance(w, solid_tab.SolidWindow) and w.kind == "solid"
w.threaded = False
assert w.create_project(os.path.join(UD, "p1"))
assert w.import_tab(sh.tabs.widget(0)), "an open part tab can be copied in (unsaved edits included)"
assert w.geom is not None and abs(w.geom["volume"] - 60 * 10 * 8) < 1e-3 and w.save()
folder = w.path
sh.close_tab(sh.tabs.indexOf(w))
t = sh.open_project_folder(folder)
assert isinstance(t, solid_tab.SolidWindow) and t.geom is not None, "a .gpv folder opens in the 3D FEA tab"
assert sh.open_path(folder) is t
t.refresh_study_button()
assert not t.study_box.isHidden()
t.threaded = False
st = t.open_study()
assert st is not None and sh.tabs.currentWidget() is st and st.adapter.label == "3D FEA"
# the 2D / 1D folders still open in their own tabs
import sim_tab
x = sim_tab.SimWindow("fea", shell=sh)
assert x.create_project(os.path.join(UD, "p2")) and x.import_file(part)
assert type(sh.open_project_folder(x.path)).__name__ == "SimWindow"
print("OK solid shell")
os._exit(0)
