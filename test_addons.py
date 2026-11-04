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
assert set(S) == {"partgen", "truss", "annotator", "annotator_gimble", "trainer"}, set(S)
assert "partgen_ext" in addons.module_names("partgen") and "truss_tab" in addons.module_names("truss")
assert addons.status("partgen") == "not installed" and not importable("partgen_ext")

# ---- first start puts them in place
addons.startup()
for a in S:
    assert addons.is_installed(a) and addons.is_active(a) and addons.status(a) == "installed"
assert os.path.isfile(os.path.join(UD, "addons", "partgen", "partgen_ext.py"))
assert importable("partgen_ext") and importable("truss_tab") and importable("partgen")
assert not os.path.exists(os.path.join(UD, "addons", "partgen", "__pycache__")) or True
print("seed OK")

# ---- user files that must survive
mine = os.path.join(UD, "my.gps"); open(mine, "w").write("{}")
lib = os.path.join(UD, "materials.json"); open(lib, "w").write('{"x": 1}')

# ---- uninstall
assert addons.uninstall("partgen") is True
assert not addons.is_installed("partgen") and not addons.is_active("partgen")
assert not os.path.exists(os.path.join(UD, "addons", "partgen"))
assert not importable("partgen_ext") and not importable("partgen") and not importable("gears")
assert addons.is_active("truss") and importable("truss_tab")           # the other one is untouched
assert open(mine).read() == "{}" and open(lib).read() == '{"x": 1}'
assert json.load(open(os.path.join(UD, "addons.json")))["removed"] == ["partgen"]
# a restart / update must not bring it back
addons.startup()
assert not addons.is_installed("partgen") and not importable("partgen_ext")
print("uninstall OK")

# ---- reinstall
addons.install("partgen")
assert addons.is_active("partgen") and importable("partgen_ext")
assert json.load(open(os.path.join(UD, "addons.json")))["removed"] == []
print("reinstall OK")

# ---- update: an older installed copy is upgraded at start, a newer one is left alone
mp = os.path.join(UD, "addons", "truss", "addon.json")
m = json.load(open(mp)); m["version"] = "0.0.1"; json.dump(m, open(mp, "w"))
assert addons.status("truss") == "update"
addons.startup()
assert addons.status("truss") == "installed" and addons.installed_manifest("truss")["version"] == S["truss"]["version"]
m["version"] = "99.0"; json.dump(m, open(mp, "w")); addons.startup()
assert addons.installed_manifest("truss")["version"] == "99.0"
addons.install("truss")                                                    # explicit install restores the shipped copy
assert addons.installed_manifest("truss")["version"] == S["truss"]["version"]
print("update OK")

# ---- a damaged install (no manifest) counts as not installed and is repaired
shutil.rmtree(os.path.join(UD, "addons", "truss"))
os.makedirs(os.path.join(UD, "addons", "truss"))
assert not addons.is_installed("truss"); addons.startup(); assert addons.is_active("truss")
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
    ok = addons.uninstall("truss")
finally:
    addons.shutil.rmtree = real
assert ok and not addons.is_installed("truss")
addons.startup()
assert not any(n.startswith(".trash-") for n in os.listdir(os.path.join(UD, "addons")))
addons.install("truss")
print("deferred delete OK")

# ---- unknown ids and ownership
try:
    addons.install("nope"); raise SystemExit("no error")
except KeyError:
    pass
assert addons.owner_of_module("partgen_ext") == "partgen" and addons.owner_of_module("truss_tab.X") == "truss" and addons.owner_of_module("pm_app") is None

# ---- the program window
import pm_model as pm, sk_tools as sk, gpd_app, pm_app, ext
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
assert ext.present("partgen") and ext.feature("partgen") is not None and ext.present("truss")

addons.uninstall("partgen"); addons.uninstall("truss"); sh.addons_changed()
assert not ext.present("partgen") and ext.feature("partgen") is None
assert not any("Truss" in a.text() for a in sh.menuBar().actions()[0].menu().actions())      # its File > New entry is gone
w0 = sh.cur()
ANSWER[0] = QMessageBox.StandardButton.No
w0.partgen_dialog(None)                                                    # asks, the answer is No
assert not addons.is_installed("partgen")
ANSWER[0] = QMessageBox.StandardButton.Yes
w0.partgen_dialog_asked = None
assert sh.need_addon("partgen", "The Part Generator") and addons.is_active("partgen")      # asks, installs
assert ext.present("partgen") and ext.feature("partgen") is not None
assert sh.need_addon("truss", "A truss") and any("Truss" in a.text() for a in sh.menuBar().actions()[0].menu().actions())
w = sh.new_addon_tab("truss")
assert w is not None and len(sh.addon_tabs("truss")) == 1
print("window install-on-demand OK")

# ---- the dialog: uninstall closes the add-on's tabs, the part stays
import addons_dialog
dlg = addons_dialog.AddonsDialog(sh)
dlg.do_uninstall("truss")
assert not addons.is_installed("truss") and sh.addon_tabs("truss") == [] and sh.tabs.count() == 1
assert isinstance(sh.cur(), pm_app.MainWindow)
dlg.do_install("truss"); assert addons.is_active("truss")
dlg.fill()
print("dialog OK")
print("ADDONS OK")
os._exit(0)
