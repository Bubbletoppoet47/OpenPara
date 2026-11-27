"""Reopen my tabs after an update: session.py (what is kept, when it comes back), the window that writes the list and reopens the tabs at the start, the
restart that the program asks for, and Settings > General."""
import faulthandler
import json
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_NO_UPDATE"] = "1"
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "render", "motor"]}')
DEV = tempfile.mkdtemp(prefix="opara_dev_")                          # a small add-on whose project is a folder (like a simulation or a Visualize project)
os.environ["OPARA_DEV_ADDONS"] = DEV
_d = os.path.join(DEV, "demo")
os.makedirs(_d)
json.dump({"name": "Demo", "tabs": [{"kind": "demo", "label": "Demo tab", "short": "Demo", "module": "demo_tab", "factory": "make", "args": ["host", "path"],
                                      "project_folder": {"marker": "marker.txt"}}]}, open(os.path.join(_d, "addon.json"), "w"))
open(os.path.join(_d, "demo_tab.py"), "w").write("from PyQt6.QtWidgets import QLabel\ndef make(host, path):\n    w = QLabel('x'); w.path = path; return w\n")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
faulthandler.dump_traceback_later(170, exit=True)
import session


def ok(c, m=""):
    assert c, m
    print("  ok  ", m)


# ---- session.py: what is kept
print("session.py")
ok(session.read() == {}, "no file: nothing")
session.write([{"path": "/a/one.gpd", "kind": "Part"}, {"path": "/a/two.gpd", "kind": "Part"}], "/a/two.gpd", "0.8.6.101")
d = session.read()
ok([t["path"] for t in d["tabs"]] == ["/a/one.gpd", "/a/two.gpd"] and d["current"] == "/a/two.gpd" and d["version"] == "0.8.6.101" and not d["restart"], "written and read back, in order")
ok(session.to_restore(d, "0.8.6.102") == (d["tabs"], "/a/two.gpd"), "another version (an update): the tabs and the one in front")
ok(session.to_restore(d, "0.8.6.101") == ([], ""), "the same version: a normal start stays empty")
ok(session.to_restore(d, "0.8.6.102", on=False) == ([], ""), "the setting off: nothing")
session.write(d["tabs"], "", "0.8.6.101", restart=True)
ok(session.to_restore(session.read(), "0.8.6.101")[0] == d["tabs"], "closed for a restart: the tabs come back even in the same version")
ok(session.to_restore({}, "1") == ([], "") and session.to_restore({"tabs": [], "version": "0"}, "1") == ([], ""), "nothing saved, nothing to restore")
open(os.path.join(UD, session.FILE), "w").write("{not json")
ok(session.read() == {}, "a damaged file is no list")
open(os.path.join(UD, session.FILE), "w").write(json.dumps({"version": "1", "tabs": [{"path": "x.gpd"}, {"nope": 1}, 5, {"path": ""}], "current": 7}))
d = session.read()
ok([t["path"] for t in d["tabs"]] == ["x.gpd"] and d["current"] == "", "entries that are not a file are dropped")

# ---- the window
print("the window")
from PyQt6.QtWidgets import QApplication, QMessageBox
ASK = []
QMessageBox.information = staticmethod(lambda *a, **k: ASK.append(a[2]))
QMessageBox.question = staticmethod(lambda *a, **k: (ASK.append(a[2]), QMessageBox.StandardButton.Yes)[1])
QMessageBox.warning = staticmethod(lambda *a, **k: ASK.append(a[2]))
import addons
import ext
addons.startup()
addons.register_extensions(ext)
import gpd_app
import pm_model as pm
import settings
import version

app = QApplication([])
work = tempfile.mkdtemp(prefix="opara_work_")
paths = []
for n in ("one", "two", "three"):
    p = os.path.join(work, n + ".gpd")
    open(p, "w", encoding="utf-8").write(pm.Document().to_json())
    paths.append(p)
FILE = os.path.join(UD, session.FILE)
if os.path.exists(FILE):
    os.remove(FILE)
settings.reset()
ok(settings.get("reopen_tabs") is True, "the setting is on by default")

s1 = gpd_app.AppShell()
s1.show()
s1.open_path(paths[0])
ok(not os.path.exists(FILE), "before the start is finished nothing is written (the last list must not be overwritten by the first tab)")
ok(s1.restore_session() == 0, "a first start: nothing to restore")
for p in paths[1:]:
    s1.open_path(p)
s1.tabs.setCurrentIndex(1)
d = session.read()
ok([t["path"] for t in d["tabs"]] == [os.path.abspath(p) for p in paths], "every open file is listed, in tab order")
ok(d["current"] == os.path.abspath(paths[1]) and d["version"] == version.__version__ and not d["restart"], "the tab in front and the version are kept")
ok(d["tabs"][0]["kind"] == "Part", "the kind of each tab is kept")
new = s1.new_part()                                                  # a document that was never saved has no file: it is not in the list
ok(len(session.read()["tabs"]) == 3, "an unsaved document is not listed")
pn = os.path.join(work, "new.gpd")
new.path = pn
open(pn, "w", encoding="utf-8").write(new.doc.to_json())
s1.refresh_titles()
ok(len(session.read()["tabs"]) == 4, "once it has a file it is listed")
s1.tabs.setCurrentIndex(0)
s1.close_tab(s1.tabs.indexOf(new))
ok([t["path"] for t in session.read()["tabs"]] == [os.path.abspath(p) for p in paths], "a tab that is closed leaves the list")
s1.tabs.tabBar().moveTab(0, 2)
s1.save_session()
ok([os.path.basename(t["path"]) for t in session.read()["tabs"]] == ["two.gpd", "three.gpd", "one.gpd"], "the order of the tabs is kept (tabs can be dragged)")
s1.tabs.setCurrentIndex(2)
ok(session.read()["current"] == os.path.abspath(paths[0]), "the tab in front changes with a click")

# a normal quit: the list stays as it was (the tabs going away with the window must not empty it)
before = open(FILE, encoding="utf-8").read()
s1.close()
ok(open(FILE, encoding="utf-8").read() == before, "closing the window does not empty the list")
ok(session.to_restore(session.read(), version.__version__)[0] == [], "a normal start in the same version: no tabs")

# ---- an update: another version wrote the list
d = session.read()
session.write(d["tabs"], d["current"], "0.0.1-older")
s2 = gpd_app.AppShell()
s2.show()
ok(s2.restore_session() == 3 and s2.tabs.count() == 3, "after an update every tab is opened again")
ok([os.path.basename(s2.tabs.widget(i).path) for i in range(3)] == ["two.gpd", "three.gpd", "one.gpd"], "in the same order")
ok(os.path.basename(s2.tabs.currentWidget().path) == "one.gpd", "and the tab that was in front is in front")
ok(session.read()["version"] == version.__version__, "the list now says the new version (the next normal start stays empty)")
s2.close()

# the setting off: nothing comes back
d = session.read()
session.write(d["tabs"], d["current"], "0.0.1-older")
settings.set_many({"reopen_tabs": False})
s3 = gpd_app.AppShell()
s3.show()
ok(s3.restore_session() == 0 and s3.tabs.count() == 0, "with Settings > General switched off nothing comes back")
ok(session.read()["tabs"] == [] and session.read()["version"] == version.__version__, "and the list starts again from what is open now")
s3.close()
settings.set_many({"reopen_tabs": True})

# a file that is gone, and one that is not a document: the others still come back and one note says which
session.write([{"path": paths[0], "kind": "Part"}, {"path": os.path.join(work, "missing.gpd"), "kind": "Part"}, {"path": paths[2], "kind": "Part"}], paths[2], "0.0.1-older")
ASK.clear()
s4 = gpd_app.AppShell()
s4.show()
ok(s4.restore_session() == 2 and s4.tabs.count() == 2, "a file that is gone does not stop the others")
ok(len(ASK) == 1 and "missing.gpd" in ASK[0] and "one.gpd" not in ASK[0], "one note names it")
s4.close()

# a project folder of an add-on comes back like a file
proj = os.path.join(work, "job.demo")
os.makedirs(proj)
open(os.path.join(proj, "marker.txt"), "w").write("{}")
session.write([], "", version.__version__)
s7 = gpd_app.AppShell()
s7.show()
s7.restore_session()
s7.open_path(paths[0])
s7.open_project_folder(proj)
d = session.read()
ok([os.path.basename(t["path"]) for t in d["tabs"]] == ["one.gpd", "job.demo"] and d["tabs"][1]["kind"] == "Demo tab project", "a project folder is listed with its kind")
session.write(d["tabs"], d["current"], "0.0.1-older")
s7.close()
s8 = gpd_app.AppShell()
s8.show()
ok(s8.restore_session() == 2 and s8.tabs.count() == 2 and s8.tabs.widget(1).path == proj and s8.tabs.currentWidget().path == proj, "and it is opened again, in front")
s8.close()

# ---- a restart that the program asks for (the same version): the tabs come back
settings.reset()
session.write([], "", version.__version__)
s5 = gpd_app.AppShell()
s5.show()
s5.restore_session()
s5.open_path(paths[0])
s5.open_path(paths[1])
ok(s5.close_for_restart() is True and session.read()["restart"] is True, "closed for a restart: the list says so")
ok(session.to_restore(session.read(), version.__version__)[0] != [], "and the same version brings the tabs back")
s6 = gpd_app.AppShell()
s6.show()
ok(s6.restore_session() == 2, "the restart reopens the tabs")
ok(session.read()["restart"] is False, "and the flag is used up")
# the restart is cancelled (unsaved changes, Cancel): the program keeps running and nothing is left behind
w = s6.tabs.widget(0)
w.is_dirty = lambda: True
w.save = lambda *a, **k: False
orig = s6.confirm_exit
s6.confirm_exit = lambda: False
ok(s6.close_for_restart() is False and session.read()["restart"] is False and s6._restart_asked is False, "a cancelled restart leaves no flag")
s6.confirm_exit = orig
s6.close()

# ---- Settings > General
print("settings")
import settings_dialog
dlg = settings_dialog.SettingsDialog()
names = [dlg.sections.item(i).text() for i in range(dlg.sections.count())]
ok(names[0] == "General" and names[1:] == ["Curves & Surfaces", "Outlines", "Dimensions", "3D View", "Picking & Snapping", "Navigation", "Performance"], names)
ok(dlg.reopen.isChecked() and dlg.reopen.text() == "Reopen my tabs after an update", "the tick is on")
dlg.reopen.setChecked(False)
dlg.apply()
ok(settings.get("reopen_tabs") is False, "Apply keeps it")
dlg.reset_defaults()
ok(dlg.reopen.isChecked(), "Reset to defaults ticks it again")
settings.reset()
print("OK session")
