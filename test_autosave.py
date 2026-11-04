"""AutoSave switch: saves after changes have settled (once for a burst), never during a drag or with a dialog open, keeps Undo / Redo, retries a
failed save without popping a dialog, is remembered per file, leaves no temporary files, and is offered on every tab that has a file."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog
app = QApplication([])
import autosave, fileio, pm_model as pm, sk_tools as sk
import gpd_app


class playground:                       # the same tests as the Playground's, on the program window
    @staticmethod
    def Playground(_parent=None, quiet=True, first="sketch"):
        sh = gpd_app.AppShell()
        sh.new_assembly() if first == "assembly" else sh.new_part()
        return sh

tmp = tempfile.mkdtemp()
autosave.STORE = os.path.join(tmp, "autosave.json")
target = os.path.join(tmp, "part.gpd")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (target, ""))

writes = []
_orig = fileio.write_text
fileio.write_text = lambda p, t, e="utf-8": (writes.append(p), _orig(p, t, e))[1]

pg = playground.Playground(None, quiet=True, first="sketch")
A = pg.autosave
w = pg.tabs.currentWidget()
assert A.available(w) and A.switch.isEnabled() and not A.switch.isChecked(), "off by default"
# --- turning it on for an untitled part asks for a name first, then saves it
assert w.path is None
assert A.set_on(w, True) and w.path == target and os.path.isfile(target) and A.is_on(w) and A.switch.isChecked()
n0 = len(writes)
# --- a change is saved once it has settled; a burst of edits writes once
def edit():
    d = w.doc
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, (0, 0), (5, 5)); sk.solve_model(m); d.store_sketch(s["id"])
    w.update_all()
for _ in range(4):
    w.snapshot(); edit()
assert pg.tab_dirty(w)
A.tick(); assert len(writes) == n0, "not on the first look (the change may still be settling)"
A.tick(); assert len(writes) == n0 + 1, "the burst of four edits is written once"
assert not pg.tab_dirty(w) and json.loads(open(target).read())["features"].__len__() == len(w.doc.features)
A.tick(); A.tick(); assert len(writes) == n0 + 1, "nothing changed, nothing written"
assert "Saved" in A.status.text()
# --- Undo / Redo keep working across saves, and the undone state is saved too
nu = len(w.undo); assert nu >= 4
w.do_undo(); assert len(w.undo) == nu - 1 and pg.tab_dirty(w)
A.tick(); A.tick()
assert len(json.loads(open(target).read())["features"]) == len(w.doc.features), "the undone part is what is on disk"
w.do_redo(); A.tick(); A.tick(); assert len(w.redo) == 0 and len(json.loads(open(target).read())["features"]) == len(w.doc.features)
# --- not while the mouse is held (a drag) or a dialog is open
w.snapshot(); edit(); n = len(writes)
real = QApplication.mouseButtons
QApplication.mouseButtons = staticmethod(lambda: Qt.MouseButton.LeftButton)
for _ in range(4): A.tick()
assert len(writes) == n, "no save during a drag"
QApplication.mouseButtons = real
A.tick(); A.tick(); assert len(writes) == n + 1
# --- a failing save: no dialog, a red message, retried later, saved when it works again
orig_save = w.save
def boom(*a, **k): raise OSError("disk is full")
w.save = boom
w.snapshot(); edit()
A.tick(); A.tick()
assert A.state(w)["bad"] and "disk is full" in A.status.text() and A.status.styleSheet().find("c00000") >= 0
w.save = orig_save
for _ in range(autosave.RETRY_TICKS + 3): A.tick()
assert not A.state(w)["bad"] and not pg.tab_dirty(w), "saved after the problem went away"
# --- no temporary files left behind
assert not [f for f in os.listdir(tmp) if f.endswith(".tmp")], os.listdir(tmp)
# --- remembered per file: a new window opening the same file starts with it on
assert autosave._key(target) in json.load(open(autosave.STORE))
pg2 = playground.Playground(None, quiet=True, first="sketch")
w2 = pg2.tabs.currentWidget(); w2.open_file(target) if hasattr(w2, 'open_file') else None
pg2.autosave.tick(); assert pg2.autosave.is_on(w2), "remembered"
# --- turning it off stops saving and forgets it
A.set_on(w, False); assert not A.is_on(w) and autosave._key(target) not in json.load(open(autosave.STORE))
w.snapshot(); edit(); n = len(writes)
for _ in range(4): A.tick()
assert len(writes) == n and pg.tab_dirty(w)
# --- the switch follows the tab on screen, and is disabled where there is no file
kinds = {}
for kind in ("sketch", "assembly", "truss"):
    t = pg.new_part() if kind == "sketch" else pg.new_assembly() if kind == "assembly" else pg.new_addon_tab("truss")
    if t is None:
        kinds[kind] = "add-on not installed"
        continue
    pg.tabs.setCurrentWidget(t)
    A.sync()
    kinds[kind] = "toggle" if A.switch.isEnabled() else "no file"
    assert A.switch.isEnabled() == pg.saveable(t)
print(kinds)
assert kinds.get("sketch") == "toggle" and kinds.get("assembly") == "toggle"
print("OK autosave")
