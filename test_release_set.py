"""What a normal OpenPara shows of the add-ons that are not released yet (addons.NOT_RELEASED: Visualize, Motor Control, Remote Computer and
the Gimble connection): nothing - they are
not installed from the program folder, have no ribbon tab, no menu item and no File > New entry - while the released ones (Simulation,
Parametric Studies ...) are all there.  The Playground shows them in Full dev mode only."""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer"]}')     # not needed here (no download, no disk)
os.environ["OPARA_NO_UPDATE"] = "1"
for k in ("OPARA_CHANNEL", "OPARA_PLAYGROUND_MODE", "OPARA_DEV_ADDONS"):
    os.environ.pop(k, None)
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
BOX = []
for n in ("information", "warning", "critical"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: BOX.append(a[2])))
import addons, channel, ext, gpd_app

assert channel.name_of_channel() == "release"
assert addons.status("simulation") == "installed" and addons.status("parametric") == "installed", "the released add-ons of the program folder are put in place"
assert not addons.is_installed("render") and not addons.is_installed("motor"), "the unreleased ones are not"
assert "render" not in addons.known() and "motor" not in addons.known() and not ext.present("render")
assert set(addons.NOT_RELEASED) == {"render", "motor", "remote", "gimble_link"}
for aid in ("remote", "gimble_link"):                    # remote control of another computer and the Gimble connection stay in the Playground
    assert aid not in addons.known() and not addons.is_installed(aid) and not ext.present(aid) and not addons.offered(aid), aid
assert not any("Gimble:" in t for t, _f in ext.MENU_ITEMS.get("annotator.file", [])), "the Annotator's File menu has no Gimble connection items"
try:
    addons.install("render"); raise SystemExit("an unreleased add-on was installed")
except KeyError:
    pass
sh = gpd_app.AppShell([])
def texts(name):
    m = next(a.menu() for a in sh.menuBar().actions() if a.text().replace("&", "") == name)
    return [a.text().replace("&", "") for a in m.actions() if a.text()]
f = texts("File")
assert "New 1D FEA" in f and "New 2D FEA" in f and "New 2D CFD" in f and "New Parametric Study..." in f, f
assert not any("Visualize" in t or "Motor" in t or "Remote" in t for t in f + texts("Add") + texts("Help")), (f, texts("Add"))
assert "Parametric study of this simulation" in texts("Add")
assert sorted(addons.tab_kinds()) == ["beam", "cfd", "fea"], sorted(addons.tab_kinds())
wp = sh.new_part()
tabs = [wp.ribbon.tabText(i) for i in range(wp.ribbon.count())]
assert tabs == ["Part Features", "Sketch", "Evaluate", "Simulation"], tabs
wa = sh.new_assembly()
assert "Visualize" not in [wa.ribbon.tabText(i) for i in range(wa.ribbon.count())]
assert not any("Visualize" in b.text() or "Motor" in b.text() for b in sh.start.buttons), [b.text() for b in sh.start.buttons]
assert sh.add_render() is None and BOX and "not part of this version" in BOX[-1], BOX      # (only reachable from code: nothing in the window leads here)
import addons_dialog
d = addons_dialog.AddonsDialog(sh)
from PyQt6.QtWidgets import QLabel
words = " ".join(l.text() for l in d.findChildren(QLabel))
assert "Parametric Studies" in words and "Simulation" in words and "Renderer" not in words and "Motor Control" not in words
assert "Remote Computer" not in words and "Gimble connection" not in words

# the Playground: Testing mode is the release; Full dev mode offers them too
os.environ["OPARA_CHANNEL"] = "playground"
assert "render" not in addons.known() and not addons.offered("motor")
os.environ["OPARA_PLAYGROUND_MODE"] = "full"
assert {"render", "motor", "remote", "gimble_link"} <= set(addons.known()) and addons.offered("render") and addons.offered("remote")
shutil.rmtree(UD, ignore_errors=True)
print("OK release set")
os._exit(0)
