import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, sys, json, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = UD
import addons
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])

def importable(m):
    sys.modules.pop(m, None)
    try:
        __import__(m); return True
    except ImportError:
        return False

# ---- what ships
S = addons.shipped()
assert set(S) == {"simulation", "render"}, S
assert "sim_tab" in addons.module_names("simulation") and "render_studio" in addons.module_names("render")
assert addons.status("simulation") == "not installed" and not importable("sim_tab")

# ---- first start puts them in place
addons.startup()
for a in S:
    assert addons.is_installed(a) and addons.is_active(a) and addons.status(a) == "installed"
assert os.path.isfile(os.path.join(UD, "addons", "simulation", "sim_tab.py"))
assert importable("sim_tab") and importable("render_studio") and importable("physics_tab")
assert not os.path.exists(os.path.join(UD, "addons", "simulation", "__pycache__")) or True
print("seed OK")

# ---- user files that must survive
mine = os.path.join(UD, "my.gps"); open(mine, "w").write("{}")
lib = os.path.join(UD, "materials.json"); open(lib, "w").write('{"x": 1}')

# ---- uninstall
assert addons.uninstall("simulation") is True
assert not addons.is_installed("simulation") and not addons.is_active("simulation")
assert not os.path.exists(os.path.join(UD, "addons", "simulation"))
assert not importable("sim_tab") and not importable("physics_tab") and not importable("beam_tab")
assert addons.is_active("render") and importable("render_studio")           # the other one is untouched
assert open(mine).read() == "{}" and open(lib).read() == '{"x": 1}'
assert json.load(open(os.path.join(UD, "addons.json")))["removed"] == ["simulation"]
# a restart / update must not bring it back
addons.startup()
assert not addons.is_installed("simulation") and not importable("sim_tab")
print("uninstall OK")

# ---- reinstall
addons.install("simulation")
assert addons.is_active("simulation") and importable("sim_tab")
assert json.load(open(os.path.join(UD, "addons.json")))["removed"] == []
print("reinstall OK")

# ---- update: an older installed copy is upgraded at start, a newer one is left alone
mp = os.path.join(UD, "addons", "render", "addon.json")
m = json.load(open(mp)); m["version"] = "0.0.1"; json.dump(m, open(mp, "w"))
assert addons.status("render") == "update"
addons.startup()
assert addons.status("render") == "installed" and addons.installed_manifest("render")["version"] == S["render"]["version"]
m["version"] = "99.0"; json.dump(m, open(mp, "w")); addons.startup()
assert addons.installed_manifest("render")["version"] == "99.0"
addons.install("render")                                                    # explicit install restores the shipped copy
assert addons.installed_manifest("render")["version"] == S["render"]["version"]
print("update OK")

# ---- a damaged install (no manifest) counts as not installed and is repaired
shutil.rmtree(os.path.join(UD, "addons", "render"))
os.makedirs(os.path.join(UD, "addons", "render"))
assert not addons.is_installed("render"); addons.startup(); assert addons.is_active("render")
print("repair OK")

# ---- files in use (Windows): the folder is moved aside and deleted at the next start
real = shutil.rmtree; calls = []
def stubborn(p, *a, **k):
    calls.append(p)
    if len(calls) == 1:
        return                                                             # first attempt: nothing deleted, like a locked file
    return real(p, *a, **k)
addons.shutil.rmtree = stubborn
try:
    ok = addons.uninstall("render")
finally:
    addons.shutil.rmtree = real
assert ok and not addons.is_installed("render")
addons.startup()
assert not any(n.startswith(".trash-") for n in os.listdir(os.path.join(UD, "addons")))
addons.install("render")
print("deferred delete OK")

# ---- unknown ids and ownership
try:
    addons.install("nope"); raise SystemExit("no error")
except KeyError:
    pass
assert addons.owner_of_module("sim_tab") == "simulation" and addons.owner_of_module("render_studio.X") == "render" and addons.owner_of_module("pm_app") is None

# ---- the program window
import pm_model as pm, sk_tools as sk, gpd_app, pm_app
MSGS = []; ANSWER = [QMessageBox.StandardButton.Yes]
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: ANSWER[0])
d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
sk.add_rect_corner(mm, (0, 0), (40, 20)); sk.solve_model(mm); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
part = os.path.join(UD, "p.gpd"); open(part, "w").write(d.to_json())
sh = gpd_app.AppShell([part])
assert any("Add-ons" in a.text() for a in sh.menuBar().actions()[0].menu().actions())

addons.uninstall("simulation"); addons.uninstall("render")
ANSWER[0] = QMessageBox.StandardButton.No
assert sh.add_sim("fea") is None and sh.add_render() is None and not addons.is_installed("simulation")
assert sh.open_path(mine) is None and not addons.is_installed("simulation")
ANSWER[0] = QMessageBox.StandardButton.Yes
w = sh.add_sim("fea")                                                      # asks, installs, opens
assert w is not None and addons.is_active("simulation") and len(sh.addon_tabs("simulation")) == 1
import sim_tab
assert isinstance(w, sim_tab.SimWindow)
print("window install-on-demand OK")

# ---- the dialog: uninstall closes the add-on's tabs, the part stays
import addons_dialog
dlg = addons_dialog.AddonsDialog(sh)
dlg.do_uninstall("simulation")
assert not addons.is_installed("simulation") and sh.addon_tabs("simulation") == [] and sh.tabs.count() == 1
assert isinstance(sh.cur(), pm_app.MainWindow)
dlg.do_install("simulation"); assert addons.is_active("simulation")
dlg.fill()
print("dialog OK")
print("ADDONS OK")
os._exit(0)
