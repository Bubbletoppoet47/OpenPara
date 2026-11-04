"""A development add-on folder (OPARA_DEV_ADDONS): its add-ons are used where they are, never copied or deleted, load next to the shipped ones,
open their tabs from the manifest (module / factory / class / args), may give the window helper methods (ext.add_shell_mixin), and a source copy
does not update itself (OPARA_NO_UPDATE=1)."""
import os, sys, json, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(); os.environ["OPARA_USER_DIR"] = UD
DEV = tempfile.mkdtemp(); os.environ["OPARA_DEV_ADDONS"] = DEV; os.environ["OPARA_NO_UPDATE"] = "1"
for name, mani, code in (
    ("demo", {"name": "Demo", "tabs": [{"kind": "demo", "label": "Demo tab", "short": "Demo", "module": "demo_tab", "factory": "make", "args": ["host", "path"]},
                                       {"kind": "demo2", "label": "Class tab", "short": "Cls", "module": "demo_tab", "class": "Plain", "args": [], "set_host": True},
                                       {"kind": "wrapper", "label": "Wrapper", "module": "demo_tab", "factory": "make", "args": ["host", "path"], "in_program": False}],
              "extension": "demo_ext"},
     {"demo_tab.py": "from PyQt6.QtWidgets import QLabel\nclass Plain(QLabel):\n    def __init__(self):\n        super().__init__('plain')\n"
                     "def make(host, path):\n    w = Plain(); w.helper_ok = host.demo_helper(); w.path = path; return w\n",
      "demo_ext.py": "class Mixin:\n    def demo_helper(self):\n        return 'helped'\n"
                     "def register(ext):\n    ext.add_shell_mixin(Mixin)\n"}),):
    d = os.path.join(DEV, name); os.makedirs(d)
    json.dump(mani, open(os.path.join(d, "addon.json"), "w"))
    for f, c in code.items():
        open(os.path.join(d, f), "w").write(c)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "addons_src", "partgen"))
import addons, ext
addons.startup(); addons.register_extensions(ext)
assert addons.is_dev("demo") and addons.is_active("demo") and addons.status("demo") == "installed" and "demo" in addons.known()
assert not os.path.exists(os.path.join(UD, "addons", "demo")), "used where it is, not copied"
assert set(addons.tab_kinds()) >= {"demo", "demo2"} and "wrapper" not in addons.tab_kinds()
assert addons.uninstall("demo") is False and os.path.isfile(os.path.join(DEV, "demo", "addon.json")), "a development add-on is never deleted"
import gpd_app
from PyQt6.QtWidgets import QApplication
app = QApplication([])
shell = type("Shell", (*ext.SHELL_MIXINS, gpd_app.AppShell), {})()
w = shell.new_addon_tab("demo")
assert w is not None and w.helper_ok == "helped" and w.kind == "demo" and shell.tabs.tabText(shell.tabs.count() - 1) == "Demo 1", shell.tabs.tabText(0)
w2 = shell.new_addon_tab("demo2")
assert w2.host is shell and shell.tabs.tabText(shell.tabs.count() - 1) == "Cls 1"
assert shell.new_addon_tab("demo").path is None and shell.tabs.tabText(shell.tabs.count() - 1) == "Demo 2"
assert shell.updates.auto_enabled() is False
print("OK dev addons")
os._exit(0)
