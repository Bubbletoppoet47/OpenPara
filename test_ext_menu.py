"""Add-ons put items in the menu of another add-on's window (ext.add_menu_item), and a project folder is recognised by its marker file alone
when the add-on gives no format (File > Open Project Folder)."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(); os.environ["OPARA_NO_UPDATE"] = "1"
DEV = tempfile.mkdtemp(); os.environ["OPARA_DEV_ADDONS"] = DEV
d = os.path.join(DEV, "demo"); os.makedirs(d)
json.dump({"name": "Demo", "tabs": [{"kind": "demo", "label": "Demo tab", "short": "Demo", "module": "demo_tab", "factory": "make", "args": ["host", "path"],
                                      "project_folder": {"marker": "marker.txt"}}]}, open(os.path.join(d, "addon.json"), "w"))
open(os.path.join(d, "demo_tab.py"), "w").write("from PyQt6.QtWidgets import QLabel\ndef make(host, path):\n    w = QLabel('x'); w.path = path; return w\n")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import addons, ext
addons.startup(); addons.register_extensions(ext)
f = lambda w: None
ext.add_menu_item("annotator.file", "Do it", f); ext.add_menu_item("annotator.file", "Do it", f)
assert ext.MENU_ITEMS["annotator.file"].count(("Do it", f)) == 1          # added twice, listed once (the shipped Gimble add-on adds its own item here too)
import gpd_app
from PyQt6.QtWidgets import QApplication
app = QApplication([])
shell = gpd_app.AppShell()
proj = tempfile.mkdtemp(); open(os.path.join(proj, "marker.txt"), "w").write("{}")
w = shell.open_project_folder(proj)
assert w is not None and w.path == os.path.abspath(proj), w
assert shell.open_project_folder(proj) is w, "already open: shown, not opened twice"
print("OK ext menu")
os._exit(0)
