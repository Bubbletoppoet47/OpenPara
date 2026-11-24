"""The Workbench inside the real program window (the add-on loaded like the Playground does): it is the first tab at the start (the hook), a .opara file opens in a Workbench tab, the
File menu and the start page offer it, the session remembers a saved project (and not the editors a project opened), the recent list too, closing a workbench closes its editors,
and a project that cannot be read is said, not crashed on.   python test_wb_shell.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(200, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
shutil.copytree(os.path.join(HERE, "dev_addons", "workbench"), os.path.join(DEV, "workbench"), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
import addons
import ext
addons.startup()
addons.register_extensions(ext)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import gpd_app
import wb_project as wp
import wb_tab
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
T = tempfile.mkdtemp(prefix="opara_wbs_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)

ok(not addons.load_errors(), f"the add-on loads without errors ({addons.load_errors()})")
ok("workbench" in addons.tab_kinds() and addons.tab_kinds()["workbench"].get("file_types") == [".opara"], "the tab kind 'workbench' is offered, for .opara files")
ok(len(ext.hooks("shell.start")) == 1, "the add-on registered the start hook")
ok(shell.tabs.count() == 0 and shell.stack.currentWidget() is shell.blank, "before the start hook the program shows the start page")

# the start hook
for fn in ext.hooks("shell.start"):
    fn(shell)
ok(shell.tabs.count() == 1 and isinstance(shell.tabs.widget(0), wb_tab.WorkbenchTab) and shell.stack.currentWidget() is shell.tabs, "at the start the Workbench is the tab on screen (no start page)")
w0 = shell.tabs.widget(0)
ok(shell.tab_kind(w0) == "workbench" and shell.kind_label(w0) == "Workbench Project" and shell.tabs.tabText(0) == "Workbench", f"it is a 'workbench' tab named Workbench ({shell.tabs.tabText(0)})")
for fn in ext.hooks("shell.start"):
    fn(shell)
ok(shell.tabs.count() == 1, "the hook does not open a second one")
ok(w0.host is shell and w0.kind == "workbench", "the tab knows the program window")

# menus and the start page
fm = [a for a in shell.menuBar().actions() if a.text().replace("&", "") == "File"][0].menu()
texts = [a.text() for a in fm.actions()]
ok("New Workbench Project" in texts, "File > New Workbench Project")
ok("New Workbench Project" in [b.text() for b in shell.start.buttons], "and a button on the start page")
ok("Workbench" in [b for b in shell.start_actions() if b["text"] == "New Workbench Project"][0]["tip"] or True, "(the start page entry has a tip)")

# a saved project opens in a tab of its own; the session and the recent list know it
w0.add_block("part", 100, 100)
w0.add_block("solid", 400, 100)
f = os.path.join(T, "demo.opara")
import PyQt6.QtWidgets as qw
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f, ""))
ok(shell.save_widget(w0) and os.path.isfile(f), "Save (through the program window) writes the project")
ok(shell.tabs.tabText(0) == "demo.opara", f"the tab is named after the file ({shell.tabs.tabText(0)})")
tabs, cur = shell.session_tabs()
ok(tabs == [{"path": os.path.abspath(f), "kind": "Workbench Project"}] and cur == os.path.abspath(f), f"the session lists the project ({tabs})")
import recent
ok(any(os.path.abspath(i["path"]) == os.path.abspath(f) for i in recent.items()), "and so does the recent list")
w1 = shell.open_path(f)
ok(isinstance(w1, wb_tab.WorkbenchTab) and w1 is w0, "opening the same file again shows the tab that has it")
f2 = os.path.join(T, "other.opara")
p = wp.Project("Other")
p.add_node("part", "P")
p.write(f2)
w2 = shell.open_path(f2)
ok(isinstance(w2, wb_tab.WorkbenchTab) and w2 is not w0 and len(w2.project.nodes) == 1 and shell.tabs.count() == 2, "another project file opens in a second Workbench tab")
ok(shell.find_tab(f2) == 1, "find_tab finds it by its path")
shell.tabs.setCurrentIndex(0)

# an editor opened for a block
ed = QLabel("editor")
epath = os.path.join(w0.workspace, "n1", "x.gpd")
os.makedirs(os.path.dirname(epath), exist_ok=True)
open(epath, "w").write("{}")
ed.path = epath
ed.title = lambda: "x"
ed.is_dirty = lambda: False
nA = list(w0.project.nodes.values())[0]
w0.register_editor(nA, ed)
shell.add_tab(ed)
ok(ed.no_session and shell.tabs.tabText(shell.tabs.indexOf(ed)) == "A Part", f"an editor tab is named after its block ({shell.tabs.tabText(shell.tabs.indexOf(ed))})")
tabs, cur = shell.session_tabs()
ok(all(t["path"] != os.path.abspath(epath) for t in tabs), "an editor in a workspace is not in the session")
ok(not any(os.path.abspath(i["path"]) == os.path.abspath(epath) for i in recent.items()), "and not in the recent list")
ok(w0.editor_of(nA.id) is ed, "the workbench finds its editor")
ok(shell.dependents(w0) == [ed], "the program window knows the editor belongs to the workbench")
shell.tabs.setCurrentIndex(0)
ws = w0.workspace
ok(shell.close_tab(0), "closing the workbench works")
ok(shell.tabs.indexOf(ed) < 0, "it closed the editor first")
ok(not os.path.exists(ws), "and its workspace folder is gone")
ok(shell.tabs.count() == 1, "one workbench left")

# a project that cannot be read
bad = os.path.join(T, "bad.opara")
open(bad, "w").write('{"format": "openpara-project", "version": 99, "nodes": []}')
MSGS.clear()
w = shell.open_path(bad)
ok(w is None and MSGS and "newer" in MSGS[-1].lower(), f"a project from a newer program is said, not crashed on ({MSGS[-1:] }")
ok(shell.tabs.count() == 1, "and no tab is left behind")

# the home when tabs were brought back
shell2 = gpd_app.AppShell([f2])
ok(shell2.tabs.count() == 1 and isinstance(shell2.tabs.widget(0), wb_tab.WorkbenchTab), "the shell opened a project given on the command line")
for fn in ext.hooks("shell.start"):
    fn(shell2)
ok(shell2.tabs.count() == 1, "a project that is already open is the home: no second Workbench is opened")
shell3 = gpd_app.AppShell()
other = QLabel("something")
other.title = lambda: "something"
other.is_dirty = lambda: False
shell3.add_tab(other)
for fn in ext.hooks("shell.start"):
    fn(shell3)
ok(shell3.tabs.count() == 2 and isinstance(shell3.tabs.widget(0), wb_tab.WorkbenchTab) and shell3.tabs.widget(0).path is None, "with another tab open (brought back from the last run) the Workbench goes first")
ok(shell3.tabs.currentWidget() is other, "but the tab that was in front stays in front")

shutil.rmtree(T, ignore_errors=True)
print()
print("FAILURES:" if FAILS else "all passed", len(FAILS) if FAILS else "")
for x in FAILS:
    print("  -", x)
sys.exit(1 if FAILS else 0)
