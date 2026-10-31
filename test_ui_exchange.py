"""File > Import STEP / Export in the real program window (the file dialogs are replaced by fixed answers).  python test_ui_exchange.py"""
import faulthandler; faulthandler.dump_traceback_later(600, exit=True)
import os
import struct
import tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
app = QApplication([])
import numpy as np
from build123d import Box, Cylinder, Pos
import exchange as ex
import exchange_dialog as xd
import gpd_app


def ok(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    assert c, m


tmp = tempfile.mkdtemp()
vol = lambda s: sum(x.volume for x in s.solids())
plate = Box(40, 30, 10) - Pos(10, 0, 0) * Cylinder(4, 10)
sh = gpd_app.AppShell([])
acts = [a.text() for a in sh.menuBar().actions()[0].menu().actions()]
ok("Import STEP..." in acts and "Export (STEP, STL)..." in acts, "File menu has Import STEP... and Export")

# ---- import one solid
step = os.path.join(tmp, "plate.step")
ex.export_step(step, [("plate", plate)])
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (step, ""))
n0 = sh.tabs.count()
sh.import_step()
w = sh.tabs.currentWidget()
ok(sh.tabs.count() == n0 + 1 and abs(vol(w.doc.solid) - vol(plate)) < 1e-6 * vol(plate), "importing a one-solid STEP opens a new part with that solid")
ok(w.doc.features[0]["kind"] == "imported", "its first feature is the imported body")
ok(w.is_dirty(), "the new part is unsaved (closing it asks)")

# ---- export that part as STEP and STL through the dialog code, with the dialog and file chooser answered
out_step, out_stl = os.path.join(tmp, "o.step"), os.path.join(tmp, "o.stl")
class Fake(xd.ExportDialog):
    mode = "step"
    def exec(self):
        self.fmt.setCurrentIndex(0 if Fake.mode == "step" else 1)
        return 1
xd.ExportDialog = Fake
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ((out_step if Fake.mode == "step" else out_stl), ""))
sh.export_file()
ok(abs(vol(ex.read_step(out_step)[0][1]) - vol(plate)) < 1e-6 * vol(plate), "File > Export, STEP, of a part: the file holds the same solid")
Fake.mode = "stl"
sh.export_file()
n = struct.unpack("<I", open(out_stl, "rb").read()[80:84])[0]
ok(n > 50 and os.path.getsize(out_stl) == 84 + 50 * n, f"File > Export, STL, of a part: a valid binary STL with {n} triangles")

# ---- a STEP with two solids -> one assembly in a folder
two = os.path.join(tmp, "two.step")
ex.export_step(two, [("base", Box(20, 20, 5)), ("pin", Pos(0, 0, 10) * Cylinder(3, 15))])
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (two, ""))
class Box2(QMessageBox):
    def exec(self):
        self.done_btn = [b for b in self.buttons() if b.text().startswith("One assembly")][0]
        return 0
    def clickedButton(self):
        return self.done_btn
xd.QMessageBox = Box2
folder = os.path.join(tmp, "asmdir")
os.makedirs(folder)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: folder)
sh.import_step()
asm = sh.tabs.currentWidget()
ok(hasattr(asm, "asm") and len(asm.asm.components) == 2, f"two solids open as an assembly with {len(asm.asm.components)} components")
ok(os.path.exists(os.path.join(folder, "two.gpa")) and os.path.exists(os.path.join(folder, "base.gpd")) and os.path.exists(os.path.join(folder, "pin.gpd")), "the assembly and its two parts were saved in the folder")
items, is_asm, _b = xd.export_items(asm)
ok(is_asm and len(items) == 2, "export items of the assembly tab: two placed solids")
zs = sorted(round(s.bounding_box().center().Z, 2) for _n, s in items)
ok(zs == [0.0, 10.0], f"they keep their positions in the original file (centres z = {zs})")
out_asm = os.path.join(tmp, "asm_out.step")
Fake.mode = "step"
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out_asm, ""))
sh.export_file()
back = ex.read_step(out_asm)
ok(len(back) == 2 and abs(sum(vol(s) for _n, s in back) - (20 * 20 * 5 + np.pi * 9 * 15)) < 1.0, "File > Export of the assembly: two solids, total volume kept")
print("ALL OK")
os._exit(0)
