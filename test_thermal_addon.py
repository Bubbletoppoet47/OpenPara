"""The 2D Thermal dev add-on, loaded the real way (development add-on folder, next to the shipped Simulation add-on): File > New 2D Thermal, the extension
registers the .gph project kind at start-up, Open Project Folder finds a thermal project by its marker and opens it in the thermal window, and a project
saved from one shell opens in another."""
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import os, sys, tempfile, shutil, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
os.symlink(os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(DEV, "thermal2d"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
import addons
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import gpd_app, ext

addons.startup(); addons.register_extensions(ext); addons.activate()
assert "thermal2d" in addons.dev_ids() and addons.is_dev("thermal2d") and addons.is_active("thermal2d"), addons.load_errors()
assert "thermal2d" not in addons.load_errors(), addons.load_errors()
assert addons.is_active("simulation"), "the thermal add-on needs the Simulation add-on, which ships with the program"
spec = addons.tab_kinds().get("thermal")
assert spec is not None and spec["label"] == "2D Thermal" and spec["aid"] == "thermal2d" and spec["project_folder"]["format"] == "openpara-sim-thermal"
assert {"beam", "fea", "cfd", "thermal"} <= set(addons.tab_kinds())
import sim_project as sp
assert sp.EXT["thermal"] == ".gph" and sp.kind_of_folder(os.path.join(UD, "nothing")) is None      # registered by the extension, before any thermal tab exists

sh = gpd_app.AppShell()
labels = [a.text() for a in sh.menuBar().actions()[0].menu().actions()]
assert "New 2D Thermal" in labels, labels
import thermal_tab as tt, sim_tab
w = sh.new_addon_tab("thermal")
assert isinstance(w, sim_tab.SimWindow) and w.kind == "thermal" and isinstance(w.tab, tt.ThermalTab) and sh.tabs.tabText(sh.tabs.count() - 1).startswith("2D Thermal")
folder = os.path.join(UD, "plate")
assert w.create_project(folder) and w.path.endswith(".gph")
# a sketch to work on (a slice-free import of a one-sketch part)
import pm_model as pm, sk_tools as sk
d = pm.Document(); d.params = {}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
r = sk.add_rect_corner(m, (0, 0), (60, 20)); m.add_con("dim_h", [("ln", r["lns"][0])], value=60.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=20.0)
sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="5")); d.rebuild()
part = os.path.join(UD, "plate.gpd")
open(part, "w").write(d.to_json())
assert w.import_file(part)
sid = next(i for i, n in w.source_items() if i not in (sim_tab.SLICE_NEW, sim_tab.SLICE_LAST))
w.tab.picker.refresh(); w.tab.picker.select(sid); w.tab.picker.go()
t = w.tab
ln = sorted(t.model.lns)
mid_x = lambda i: sum(t.model.pts[j][0] for j in t.model.lns[i]) / 2.0
t.canvas.sel = [("ln", min(ln, key=mid_x))]
tt.ask_values = lambda *a, **k: [100.0]
t.add_temperature()
t.canvas.sel = [("ln", max(ln, key=mid_x))]
tt.ask_values = lambda *a, **k: [20.0, 20.0]
t.add_conv()
t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
t.e_h.setText("4"); t.run_mesh(); t.run_solve()
assert t.result is not None and t.result["balance"]["relative_error"] < 1e-9
assert w.save() and sp.kind_of_folder(folder if os.path.isdir(folder) else w.path) == "thermal"
path = w.path
# opened by the program from the marker alone
sh2 = gpd_app.AppShell()
w2 = sh2.open_project_folder(path)
assert w2 is not None and w2.kind == "thermal" and isinstance(w2.tab, tt.ThermalTab) and w2.path == os.path.abspath(path)
assert w2.tab.result is not None and abs(w2.tab.result["Tmax"] - 373.15) < 1e-9 and len(w2.tab.supports) == 1 and len(w2.tab.loads) == 1
assert sh2.open_project_folder(path) is w2, "already open: shown, not opened twice"
# a project of another kind is not taken for a thermal one
f_ = os.path.join(UD, "other.gpf")
sp.create(f_, "fea")
w3 = sh2.open_project_folder(f_)
assert w3 is not None and w3.kind == "fea"
print("OK thermal add-on")
os._exit(0)
