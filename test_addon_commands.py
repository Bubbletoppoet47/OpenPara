"""Add-on integration: an add-on puts its own commands in the program window's menus and on the start page (ext.add_command); an add-on that
cannot be loaded never stops the program or the other add-ons, and says so in File > Add-ons and on the start page; a tab that says it belongs
to another tab (depends_on) is closed with it."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "render", "motor"]}')          # the big add-ons are not needed here (no download, no disk)
os.environ["OPARA_NO_UPDATE"] = "1"
DEV = tempfile.mkdtemp(prefix="opara_dev_"); os.environ["OPARA_DEV_ADDONS"] = DEV


def addon(aid, manifest, files):
    d = os.path.join(DEV, aid); os.makedirs(d)
    json.dump(manifest, open(os.path.join(d, "addon.json"), "w"))
    for n, text in files.items():
        open(os.path.join(d, n), "w").write(text)


addon("good", {"name": "Good add-on", "status": "working", "description": "Puts commands in the menus.", "extension": "good_ext",
               "tabs": [{"kind": "good", "label": "Good doc", "short": "Good", "module": "good_ext", "factory": "make", "args": ["host", "path"],
                         "file_types": [".good"]}]},
      {"good_ext.py": """
from PyQt6.QtWidgets import QLabel
RAN = []
def make(host, path):
    w = QLabel('doc'); w.path = path; return w
class Child(QLabel):
    def __init__(self, owner):
        super().__init__('child'); self.owner = owner; self.shut = False
    def title(self): return 'child'
    def depends_on(self): return self.owner
    def shutdown(self): self.shut = True
def register(ext):
    ext.add_command('file.new', 'New Good Thing...', lambda shell: RAN.append(('new', shell)), tip='Makes a good thing')
    ext.add_command('add', 'Good analysis', lambda shell: RAN.append(('add', shell)), key='Ctrl+Alt+G')
    ext.add_command('help', 'About the good add-on', lambda shell: RAN.append(('help', shell)))
    ext.add_command('help', 'About the good add-on', lambda shell: RAN.append(('help2', shell)))      # same text again: replaced, not doubled
"""})
addon("broken", {"name": "Broken add-on", "description": "Its extension raises.", "extension": "broken_ext"},
      {"broken_ext.py": "import does_not_exist_anywhere_12345\ndef register(ext):\n    pass\n"})
addon("later", {"name": "Later add-on", "description": "Registers after the broken one.", "extension": "later_ext"},
      {"later_ext.py": "def register(ext):\n    ext.add_command('view', 'Later view', lambda shell: None)\n"})

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import faulthandler; faulthandler.dump_traceback_later(200, exit=True)
from PyQt6.QtWidgets import QApplication, QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
import addons, ext
addons.startup()
addons.register_extensions(ext)                    # must not raise although one add-on is broken

# ---- 1. a broken add-on is isolated and reported; the others load
errs = addons.load_errors()
assert list(errs) == ["broken"] and "does_not_exist_anywhere_12345" in errs["broken"], errs
assert [c["text"] for c in ext.commands("view")] == ["Later view"], "the add-on after the broken one still registered"
assert len(ext.commands("help")) == 1, "the same place + text is listed once"
try:
    ext.add_command("nowhere", "x", lambda s: None); raise SystemExit("an unknown place must be refused")
except ValueError:
    pass

import gpd_app
app = QApplication([])
shell = gpd_app.AppShell()
import good_ext


def menu(name):
    return next(a.menu() for a in shell.menuBar().actions() if a.text().replace("&", "") == name)


def act(name, text):
    return next(a for a in menu(name).actions() if a.text() == text)


# ---- 2. the commands are in the menus, run with the program window, and the start page offers the "file.new" one
fnames = [a.text() for a in menu("File").actions()]
assert fnames.index("New Good doc") < fnames.index("New Good Thing...") < fnames.index("Open..."), fnames
act("File", "New Good Thing...").trigger(); act("Add", "Good analysis").trigger(); act("Help", "About the good add-on").trigger()
assert good_ext.RAN == [("new", shell), ("add", shell), ("help2", shell)], good_ext.RAN
assert act("Add", "Good analysis").shortcut().toString() == "Ctrl+Alt+G" and act("File", "New Good Thing...").statusTip() == "Makes a good thing"
assert act("View", "Later view") is not None
sb = [b for b in shell.start.buttons if b.text() == "New Good Thing..."]
assert len(sb) == 1 and sb[0].toolTip() == "Makes a good thing"
sb[0].click(); assert good_ext.RAN[-1] == ("new", shell)
assert "Broken add-on" in shell.start.warn.text(), shell.start.warn.text()

# ---- 3. registering again (an add-on was installed or removed) does not double anything
shell.addons_changed()
assert [a.text() for a in menu("File").actions()].count("New Good Thing...") == 1 and len(ext.commands("add")) == 1
assert [b.text() for b in shell.start.buttons].count("New Good Thing...") == 1

# ---- 4. File > Add-ons: what each add-on adds, the load error with its details, no Install / Uninstall for a Playground add-on
import addons_dialog
dlg = addons_dialog.AddonsDialog(shell)
g, b = dlg.row_info["good"], dlg.row_info["broken"]
assert "Adds: File &gt; New Good doc" in g["text"] or "Adds: File > New Good doc" in g["text"], g["text"]
assert "opens .good files" in g["text"] and "adds to other windows" in g["text"] and "Playground add-on (Full dev mode), working" in g["text"]
assert g["buttons"] == [] and b["buttons"] == ["Details..."] and "Could not be loaded" in b["text"], (g["buttons"], b["buttons"])
shown = []
gpd_app.show_error_text = lambda parent, text, title="Error", head=None: shown.append((text, head))
dlg.show_error("broken")
assert "does_not_exist_anywhere_12345" in shown[0][0] and "Broken add-on" in shown[0][1]
shell.report_addon_errors()
assert "Broken add-on" in shown[1][1] and "does_not_exist_anywhere_12345" in shown[1][0]
assert addons.adds("simulation") and any("1D FEA" in x for x in addons.adds("simulation")), addons.adds("simulation")

# ---- 5. a tab that belongs to another tab is closed (and shut down) with it; "close the others" keeps what the kept tab needs
owner = shell.new_addon_tab("good")
child = good_ext.Child(owner); shell.add_tab(child)
other = shell.new_addon_tab("good")
assert shell.dependents(owner) == [child]
assert shell.close_tabs(keep=child) and shell.tabs.count() == 2 and shell.tabs.indexOf(owner) >= 0, "the kept tab's owner stays"
assert shell.close_tab(shell.tabs.indexOf(owner)) and shell.tabs.count() == 0 and child.shut, "closing the owner closes its child first"

# ---- 6. an add-on tab that cannot start: a short message, the full error in the log
addons.tab_kinds = lambda: {"boom": {"aid": "good", "label": "Boom", "module": "good_ext", "factory": "nope", "args": []}}
assert shell.new_addon_tab("boom") is None and "nope" in gpd_app.error_log_tail() and "Could not start Boom" in gpd_app.error_log_tail()
print("OK add-on commands")
import shutil; shutil.rmtree(UD, ignore_errors=True); shutil.rmtree(DEV, ignore_errors=True)
os._exit(0)
