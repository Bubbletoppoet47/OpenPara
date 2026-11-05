"""Simulations are project folders (.gpb / .gpf / .gpc): File > Open Project Folder opens them in the Simulation add-on, File > New has an entry
per kind, the ribbon's Add > simulation starts a project that imports the part on screen, and a project is offered the add-on when it is missing.
File > Open lists no .gps any more."""
import os, sys, json, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import addons
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []; ANSWER = [QMessageBox.StandardButton.Yes]
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: ANSWER[0])
import pm_model as pm, sk_tools as sk, gpd_app, ext

assert addons.install("simulation") or addons.is_installed("simulation")
addons.activate()
import sim_project as sp, sim_tab

d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
sk.add_rect_corner(mm, (0, 0), (40, 20)); sk.solve_model(mm); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
part = os.path.join(UD, "bracket.gpd"); open(part, "w").write(d.to_json())
sh = gpd_app.AppShell([part])

f = sh.open_filter()
assert "*.gps" not in f and "*.gpd" in f and "*.gpa" in f, f
labels = [a.text() for a in sh.menuBar().actions()[0].menu().actions()]
for lab in ("New 1D FEA", "New 2D FEA", "New 2D CFD", "Open Project Folder..."):
    assert lab in labels, (lab, labels)

# File > New 2D FEA: an empty simulation (no project yet)
w = sh.new_addon_tab("fea")
assert isinstance(w, sim_tab.SimWindow) and w.kind == "fea" and not w.project_ok() and w.source is None
sh.close_tab(sh.tabs.indexOf(w))

# the ribbon: a simulation of the part on screen -> New project imports the live part (unsaved edits included)
w = sh.add_sim("fea")
assert isinstance(w, sim_tab.SimWindow) and w.candidate is sh.tabs.widget(0)
proj = os.path.join(UD, "bracket_study")
assert w.create_project(proj) and w.project_ok() and w.source is not None and w.source.type == "part"
assert w.path.endswith(".gpf") and abs(w.source.doc.solid.volume - 40 * 20 * 10) < 1e-3
w.tab.picker.refresh()
sid = next(i for i, n in w.source_items() if not str(i).startswith("__"))
w.tab.picker.select(sid); w.tab.picker.go()
assert w.save()
proj = w.path
sh.close_tab(sh.tabs.indexOf(w))

# opening the folder: File > Open Project Folder and open_path both land in a SimWindow; the same folder is not opened twice
os.makedirs(os.path.join(UD, "away"))
MOVED = os.path.join(UD, "away", "bracket.gpd")
os.replace(part, MOVED)
t1 = sh.open_project_folder(proj)
assert isinstance(t1, sim_tab.SimWindow) and t1.kind == "fea" and t1.source is not None and getattr(t1.tab, "model", None) is not None
t2 = sh.open_path(proj)
assert t2 is t1, "the same project is shown, not opened twice"
assert sh.tabs.tabText(sh.tabs.indexOf(t1)).startswith("bracket_study")
# every kind opens in its own tab type
for kind in ("beam", "cfd"):
    ww = sim_tab.SimWindow(kind)
    p = os.path.join(UD, f"k_{kind}")
    assert ww.create_project(p) and ww.import_file(MOVED)
    tt = sh.open_project_folder(ww.path)
    assert isinstance(tt, sim_tab.SimWindow) and tt.kind == kind, kind
# a folder that is no project, and a project whose marker has another format
n = len(MSGS)
assert sh.open_project_folder(UD) is None and len(MSGS) > n

# a project of an add-on that is not installed offers the install
for t in range(sh.tabs.count() - 1, 0, -1):
    sh.close_tab(t)
addons.uninstall("simulation"); sh.addons_changed()
assert not ext.present("simulation")
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.StandardButton.No)[1])
assert sh.open_project_folder(proj) is None and asked and "Simulation" in asked[0], asked
print("OK open types")
os._exit(0)
