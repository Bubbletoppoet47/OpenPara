"""STEP files open like any other file: File > Open lists them, a drop on the window and a name on the command line open them, and they come in as a new,
unsaved part (the same flow as File > Import STEP).  Units in the file are honoured, a file that is not STEP is refused with a message and no tab,
several solids ask how to open.   python test_open_step.py"""
import faulthandler; faulthandler.dump_traceback_later(600, exit=True)
import os
import sys
import tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_CHANNEL"] = "release"
os.environ["OPARA_NO_UPDATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
app = QApplication([])
from build123d import Box, Cylinder, Pos, Unit, export_step
import exchange as ex
import exchange_dialog as xd
import gpd_app


def ok(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    assert c, m


tmp = tempfile.mkdtemp(prefix="opara_st_")
vol = lambda s: sum(x.volume for x in s.solids())
plate = Box(40, 30, 10) - Pos(10, 0, 0) * Cylinder(4, 10)
MSGS = []
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
sh = gpd_app.AppShell([])

# ---- the Open dialog lists STEP
f = sh.open_filter()
all_types = f.split(";;")[0]
ok("*.step" in all_types and "*.stp" in all_types and "*.gpd" in all_types and "*.gpa" in all_types, "File > Open: 'All supported files' includes .step and .stp")
ok("STEP (*.step *.stp)" in f.split(";;"), "File > Open has its own STEP entry")
ok(xd.is_step("A.STEP") and xd.is_step("b.stp") and not xd.is_step("c.gpd") and not xd.is_step("steps.txt"), "what counts as a STEP file (any letter case)")

# ---- open_path: one solid -> a new unsaved part
one = os.path.join(tmp, "plate.step")
ex.export_step(one, [("plate", plate)])
n0 = sh.tabs.count()
w = sh.open_path(one)
ok(sh.tabs.count() == n0 + 1 and sh.tabs.currentWidget() is w, "opening a STEP file makes one new tab and shows it")
ok(abs(vol(w.doc.solid) - vol(plate)) < 1e-6 * vol(plate), "its solid has the volume of the original")
ok(w.doc.features[0]["kind"] == "imported" and w.doc.features[0].get("source") == "plate.step", "its first feature is the imported body, remembering the file name")
ok(w.is_dirty() and not w.path, "it is a new part that was never saved (closing it asks, Save asks for a name)")
# opening the same STEP file again is a second new part (the file is not the document)
w2 = sh.open_path(one)
ok(w2 is not w and sh.tabs.count() == n0 + 2, "opening it again makes another new part")
# the part can be saved as .gpd and opened again: the body travels inside the file
gpd = os.path.join(tmp, "plate.gpd")
open(gpd, "w", encoding="utf-8").write(w.doc.to_json())
w3 = sh.open_path(gpd)
ok(abs(vol(w3.doc.solid) - vol(plate)) < 1e-6 * vol(plate), "saved as .gpd and opened: the same solid, no STEP file needed")
# the next File > Open starts in the STEP file's folder
import recent
ok(os.path.normcase(os.path.abspath(recent.last_folder())) == os.path.normcase(os.path.abspath(tmp)), "the Open dialog now starts in the STEP file's folder")

# ---- File > Open with several files of different kinds, one of them .stp
stp = os.path.join(tmp, "tube.stp")
ex.export_step(stp, [("tube", Cylinder(10, 30) - Cylinder(6, 30))])
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([stp, gpd], ""))
n0 = sh.tabs.count()
sh.open_dialog()
ok(sh.tabs.count() == n0 + 1 or sh.find_tab(gpd) is not None, "File > Open with a .stp and a .gpd opens both")
tube = sh.tabs.widget(n0)
ok(abs(vol(tube.doc.solid) - vol(Cylinder(10, 30) - Cylinder(6, 30))) < 1e-6 * 3000, "the .stp is the tube")

# ---- units in the file are honoured: a file in inches, feet or metres comes in as millimetres
for unit, k in ((Unit.IN, 25.4), (Unit.FT, 304.8), (Unit.M, 1000.0)):
    p = os.path.join(tmp, f"box_{unit.name}.step")
    export_step(Box(1, 2, 3), p, unit=unit)
    wu = sh.open_path(p)
    bb = wu.doc.solid.bounding_box()
    ok(abs(bb.size.X - 1 * k) < 1e-6 * k and abs(bb.size.Y - 2 * k) < 1e-6 * k and abs(bb.size.Z - 3 * k) < 1e-6 * k, f"a file in {unit.name.lower()} comes in as {k:g} mm per unit ({bb.size.X:g} x {bb.size.Y:g} x {bb.size.Z:g} mm)")

# ---- drag and drop of a file onto the window
mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile(stp)])
n0 = sh.tabs.count()
ev = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
sh.dropEvent(ev)
for _ in range(20):
    app.processEvents()
ok(sh.tabs.count() == n0 + 1 and abs(vol(sh.tabs.currentWidget().doc.solid) - vol(Cylinder(10, 30) - Cylinder(6, 30))) < 1e-6 * 3000, "dropping a .stp on the window opens it as a new part")

# ---- on the command line
sh2 = gpd_app.AppShell([one])
ok(sh2.tabs.count() >= 1 and any(getattr(sh2.tabs.widget(i), "doc", None) is not None and sh2.tabs.widget(i).doc.features and sh2.tabs.widget(i).doc.features[0]["kind"] == "imported" for i in range(sh2.tabs.count())), "a STEP file given on the command line opens")

# ---- files that are not STEP: a message, and no tab
bad = os.path.join(tmp, "notstep.step")
open(bad, "w").write("this is not a STEP file\n")
empty = os.path.join(tmp, "empty.step")
open(empty, "w").close()
surf = os.path.join(tmp, "surface.step")
from build123d import Face
export_step(Face.make_rect(10, 10), surf)
n0 = sh.tabs.count()
for name, p, words in (("text", bad, "does not look like a STEP file"), ("empty", empty, "empty"), ("surface only", surf, "no solids")):
    MSGS.clear()
    r = sh.open_path(p)
    ok(r is None and sh.tabs.count() == n0 and len(MSGS) == 1 and words in MSGS[0], f"a {name} file: no tab, one message that says why ({MSGS[0][:80] if MSGS else ''})")

# ---- several solids: the question, and its answers
two = os.path.join(tmp, "two.step")
ex.export_step(two, [("base", Box(20, 20, 5)), ("pin", Pos(0, 0, 10) * Cylinder(3, 15))])
state = {"pick": "One part per solid"}


class Ask(QMessageBox):
    def exec(self):
        self.chosen = next((b for b in self.buttons() if b.text() == state["pick"]), None) if state["pick"] != "Cancel" else self.button(QMessageBox.StandardButton.Cancel)
        return 0

    def clickedButton(self):
        return self.chosen


xd.QMessageBox = Ask
n0 = sh.tabs.count()
r = sh.open_path(two)
ok(sh.tabs.count() == n0 + 2 and r is sh.tabs.widget(n0), "'One part per solid': two new parts (open_path gives the first)")
state["pick"] = "One part with all solids"
n0 = sh.tabs.count()
r = sh.open_path(two)
ok(sh.tabs.count() == n0 + 1 and abs(vol(r.doc.solid) - (20 * 20 * 5 + 3.14159265358979 * 9 * 15)) < 1e-3, "'One part with all solids': one part holding both")
state["pick"] = "Cancel"
n0 = sh.tabs.count()
ok(sh.open_path(two) is None and sh.tabs.count() == n0, "Cancel: nothing opens")

print("test_open_step OK")
