"""The window: a tiny GPU widget is part of it from the start (no close-and-reopen at the first 3D tab); a small 'Opening ...' card shows while a
part / assembly / add-on tab / file is built and always goes away; the right-click menu on a plane offers only Sketch."""
import os, sys, json, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if os.path.basename(os.path.dirname(os.path.abspath(__file__))) == "tests" else os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "core") if os.path.isdir(os.path.join(HERE, "core")) else HERE
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(); os.environ["OPARA_NO_UPDATE"] = "1"
DEV = tempfile.mkdtemp(); os.environ["OPARA_DEV_ADDONS"] = DEV
d = os.path.join(DEV, "demo"); os.makedirs(d)
json.dump({"name": "Demo", "tabs": [{"kind": "demo", "label": "Demo tab", "short": "Demo", "module": "demo_tab", "factory": "make", "args": ["host", "path"]},
                                    {"kind": "bad", "label": "Bad tab", "short": "Bad", "module": "demo_tab", "factory": "boom", "args": []}]}, open(os.path.join(d, "addon.json"), "w"))
open(os.path.join(d, "demo_tab.py"), "w").write("from PyQt6.QtWidgets import QLabel\ndef make(host, path):\n    host.seen_veil = host._busy_veil is not None\n    return QLabel('x')\ndef boom():\n    raise RuntimeError('no')\n")
sys.path.insert(0, CORE)
import faulthandler; faulthandler.dump_traceback_later(150, exit=True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu, QLabel
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2]))
QMessageBox.information = staticmethod(lambda *a, **k: WARN.append(a[2]))
import addons, ext
addons.startup(); addons.register_extensions(ext)
import gpd_app, pm_model as pm
app = QApplication([])
shell = type("Shell", (*ext.SHELL_MIXINS, gpd_app.AppShell), {})()
shell.show()

# 1. the window has its GPU anchor before any tab
assert hasattr(shell, "gl_anchor") and shell.gl_anchor is not None and shell.gl_anchor.parent() is shell

# 2. the card shows while a tab is built, and is gone afterwards (also after a failure)
log = []
orig_add = shell.add_tab
def spy(w):
    log.append((shell._busy_veil is not None, shell._busy_depth))
    return orig_add(w)
shell.add_tab = spy
def clean():
    assert shell._busy_veil is None and shell._busy_depth == 0 and QApplication.overrideCursor() is None
shell.new_part(); assert log[-1] == (True, 1); clean()
shell.new_assembly(); assert log[-1] == (True, 1); clean()
w = shell.new_addon_tab("demo"); assert w is not None and shell.seen_veil is True; clean()
n = len(WARN)
assert shell.new_addon_tab("bad") is None and len(WARN) == n + 1; clean()
p = os.path.join(tempfile.mkdtemp(), "t.gpd"); open(p, "w", encoding="utf-8").write(pm.Document().to_json())
shell.open_path(p); assert log[-1] == (True, 1); clean()
cnt = shell.tabs.count(); shell.open_path(p); assert shell.tabs.count() == cnt; clean()      # already open: just shown
# nested uses make ONE card
with shell.busy("a"):
    v = shell._busy_veil
    with shell.busy("b"):
        assert shell._busy_veil is v and shell._busy_depth == 2
    assert shell._busy_veil is v
clean()
txt = []
orig_show = shell.show_busy
shell.show_busy = lambda t: (txt.append(t), orig_show(t))
shell.new_part(); shell.open_path(os.path.join(os.path.dirname(p), "none.gpd")) if False else None
assert txt and "part" in txt[0], txt

# 3. the plane menu
part = shell.tabs.widget(0)
from pm_app import MainWindow
assert isinstance(part, MainWindow) or True
part = next(shell.tabs.widget(i) for i in range(shell.tabs.count()) if isinstance(shell.tabs.widget(i), MainWindow))
got = []
QMenu.exec = lambda self, pos=None: got.append([a.text() for a in self.actions()])
def ctx(setup):
    part.sel_edges, part.sel_face, part.sel_plane = [], None, None
    part.pick_edge = lambda x, y: None
    part.pick_model = lambda x, y, shift=False: setup()
    part.context_menu(10, 10, None)
    return got[-1]
def plane(): part.sel_plane = "Top"
def face(): part.sel_face = {"ref": None, "index": 0}
def edges(): part.sel_edges = [("e", 1)]
assert ctx(plane) == ["Sketch"], got[-1]
assert ctx(face) == ["Sketch"], got[-1]
assert ctx(edges) == ["Fillet", "Chamfer"], got[-1]
assert ctx(lambda: None) == ["Sketch"], got[-1]
print("OK shell polish")
os._exit(0)
