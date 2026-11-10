"""Playground: Testing (default) vs Full dev, the first start (settings copy + add-ons), the always-present Open Project Folder."""
import faulthandler; faulthandler.dump_traceback_later(150, exit=True)
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
T = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(T, "pg")
os.environ["OPARA_NORMAL_USER_DIR"] = os.path.join(T, "normal")
os.environ["OPARA_CHANNEL"] = "playground"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
for k in ("OPARA_PLAYGROUND_MODE", "OPARA_DEV_ADDONS", "OPARA_NO_UPDATE"):
    os.environ.pop(k, None)
import channel, addons, playground, paths
addons.SRC_DIR = os.path.join(T, "no_addons_src")          # a build has no addons_src/: nothing is installed unless downloaded

# ---- Testing is the default: no experimental add-ons, no shared/
assert channel.mode() == "testing" and not channel.is_full_dev()
assert channel.dev_addons_dir() is None and channel.shared_dir() is None and addons.dev_ids() == []
assert channel.title() == "OpenPara Playground (testing)"
addons.activate()
assert not {"mesh", "fea3d", "circuits", "towers"} & set(addons.tab_kinds()), addons.tab_kinds()
assert "simulation" in addons.known() and "simulation" in addons.CATALOG, "the Simulation add-on ships in Testing"
# ---- Full dev: switched on, remembered, everything there
channel.set_mode("full")
assert json.load(open(os.path.join(paths.user_dir(), "playground.json")))["mode"] == "full"
assert channel.mode() == "full" and channel.is_full_dev() and channel.title() == "OpenPara Playground (full dev)"
assert channel.dev_addons_dir().endswith("dev_addons") and "fea3d" in addons.dev_ids() and "simulation" not in addons.dev_ids()
addons.activate()
assert {"circuits", "mesh", "towers"} <= set(addons.tab_kinds())
channel.set_mode("nonsense")                                   # ignored
assert channel.mode() == "full"
os.environ["OPARA_PLAYGROUND_MODE"] = "testing"                # the environment wins (tests, scripts)
assert channel.mode() == "testing" and addons.dev_ids() == []
del os.environ["OPARA_PLAYGROUND_MODE"]
channel.set_mode("testing")
# the normal program has no modes
os.environ["OPARA_CHANNEL"] = "release"
assert channel.mode() == "testing" and not channel.is_full_dev() and channel.title() == "OpenPara"
os.environ["OPARA_CHANNEL"] = "playground"

# ---- the first start: settings copy
nd = os.environ["OPARA_NORMAL_USER_DIR"]
os.makedirs(os.path.join(nd, "addons", "x"))
for n, c in (("gpd_materials.json", "[1]"), ("settings.json", "{}"), ("gpd_error.log", "boom"), ("addons.json", "{}"), ("update_state.json", "{}")):
    open(os.path.join(nd, n), "w").write(c)
assert playground.first_run_pending()
assert playground.copyable_settings() == ["gpd_materials.json", "settings.json"], playground.copyable_settings()
open(os.path.join(paths.user_dir(), "settings.json"), "w").write("{mine}")        # what the Playground already has is never overwritten
assert playground.copy_settings() == ["gpd_materials.json"]
assert open(os.path.join(paths.user_dir(), "settings.json")).read() == "{mine}"
assert open(os.path.join(nd, "gpd_materials.json")).read() == "[1]" and os.listdir(nd).count("gpd_materials.json") == 1      # the source is untouched
assert playground.addons_to_offer() == [a for a in addons.CATALOG if addons.offered(a)] and "simulation" in playground.addons_to_offer()

# ---- the window: menus, the questions, the mode switch
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication([])
import ext, gpd_app
asked = []
answers = {"Welcome": QMessageBox.StandardButton.Yes, "Add-ons": QMessageBox.StandardButton.Yes, "Settings copied": QMessageBox.StandardButton.No,
           "Playground mode": QMessageBox.StandardButton.No, "Open Project Folder": QMessageBox.StandardButton.No}
def fake_q(parent, title, text, *a, **k):
    asked.append((title, text))
    return next(v for kk, v in answers.items() if title.startswith(kk))
QMessageBox.question = staticmethod(fake_q)
QMessageBox.information = staticmethod(lambda *a, **k: asked.append(("info", a[2])))
import addons_dialog
done = []
addons_dialog.install_with_progress = lambda parent, aid: (done.append(aid), True)[1]
os.remove(os.path.join(paths.user_dir(), "gpd_materials.json"))
shell = gpd_app.AppShell.__new__(gpd_app.AppShell)
shell.addons_changed = lambda: done.append("changed")
shell.restart_program = lambda: done.append("restart")
gpd_app.AppShell.offer_first_run(shell)
assert [t for t, _ in asked] == ["Welcome to the Playground", "Add-ons", "Settings copied"], asked
assert done[:-1] == [a for a in addons.CATALOG if addons.offered(a)] and done[-1] == "changed", done        # what a normal OpenPara offers
assert "parametric" in done and "render" not in done and "motor" not in done, done
assert not playground.first_run_pending()
assert os.path.exists(os.path.join(paths.user_dir(), "gpd_materials.json"))
asked.clear(); done.clear()
gpd_app.AppShell.offer_first_run(shell)                        # only once
assert not asked and not done
# mode switch asks to restart; "Yes" restarts
answers["Playground mode"] = QMessageBox.StandardButton.Yes
gpd_app.AppShell.set_playground_mode(shell, "full")
assert channel.mode() == "full" and done == ["restart"], done
gpd_app.AppShell.set_playground_mode(shell, "full"); assert done == ["restart"]        # no change, nothing asked
channel.set_mode("testing")

# ---- Open Project Folder: with nothing installed, the folder's marker names the add-on that opens it
f = os.path.join(T, "My.training"); os.makedirs(f)
json.dump({"format": "openpara-training"}, open(os.path.join(f, "training.json"), "w"))
assert addons.project_hint(f) == "trainer"
g = os.path.join(T, "Other"); os.makedirs(g)
json.dump({"format": "something-else"}, open(os.path.join(g, "training.json"), "w"))
assert addons.project_hint(g) is None
a = os.path.join(T, "Ann.annotator"); os.makedirs(a); open(os.path.join(a, "manifest.json"), "w").write("{}")
assert addons.project_hint(a) == "annotator"
asked.clear(); done.clear()
answers["Open Project Folder"] = QMessageBox.StandardButton.No
assert gpd_app.AppShell.open_project_folder(shell, f) is None
assert asked and "Trainer" in asked[0][1] and "not installed" in asked[0][1] and not done, asked
asked.clear()
assert gpd_app.AppShell.open_project_folder(shell, g) is None and asked[0][0] == "info"        # nobody can open it: the plain message
print("playground modes OK")
