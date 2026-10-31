"""Part Generator: the window, the single feature it makes, reopening it to edit, save / load."""
import faulthandler; faulthandler.dump_traceback_later(240, exit=True)
import math
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QDialog, QFormLayout, QLabel, QToolButton
app = QApplication([])
import gears, partgen, partgen_dialog, pm_app, pm_model as pm


def ok(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    assert c, m


w = pm_app.MainWindow(); w.new_doc(); d = w.doc
ok("Part Generator" in [b.text().replace("\n", " ") for b in w.ribbon.findChildren(QToolButton)], "ribbon button exists")

def readouts(dlg):
    L, F = QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole
    return {dlg.out_form.itemAt(i, L).widget().text(): dlg.out_form.itemAt(i, F).widget().text() for i in range(dlg.out_form.rowCount())}


# ---- the window on its own
dlg = partgen_dialog.PartGenDialog(d, None, w)
names = [dlg.types.item(i).data(0x100) for i in range(dlg.types.count()) if dlg.types.item(i).data(0x100)]
ok(names == ["Spur gear", "Helical gear", "Herringbone gear"], f"catalogue: {names}")
dlg.set_kind("Spur gear")
dlg.refresh()
ok(dlg.solid is not None and abs(dlg.solid.volume - gears.spur_gear({"module": 2, "teeth": 20, "pressure": 20, "width": 10, "bore": 8}).volume) < 1e-6, "default spur gear built")
reads = readouts(dlg)
ok(reads["Pitch diameter"].startswith("40.0000") and reads["Outside diameter"].startswith("44.0000") and reads["Root diameter"].startswith("35.0000")
   and reads["Base diameter"].startswith("37.58"), f"read-outs {reads}")


def type_in(dlg, key, text):
    dlg.edits[key].setText(text)
    dlg.edits[key].textEdited.emit(text)
    dlg.refresh()


type_in(dlg, "teeth", "10")
ok("undercut" in dlg.msg.text(), "warning for 10 teeth: " + dlg.msg.text()[:40])
type_in(dlg, "teeth", "2")
ok(dlg.solid is None and "3 teeth" in dlg.msg.text(), "2 teeth is refused: " + dlg.msg.text())
ok(not dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled(), "OK is off while the inputs are bad")
type_in(dlg, "teeth", "xyz")
ok(dlg.solid is None and dlg.msg.text() != "", "nonsense input is reported: " + dlg.msg.text())
type_in(dlg, "teeth", "30")
# size given as outside diameter: 64 mm for 30 teeth, module 2
dlg.edits["mode"].setCurrentIndex(dlg.edits["mode"].findData("outside"))
type_in(dlg, "size", "64")
reads = readouts(dlg)
ok(reads["Module (normal)"].startswith("2 ") and reads["Outside diameter"].startswith("64.0000"), f"outside-diameter mode gives module 2: {reads['Module (normal)']}")
dlg.set_kind("Herringbone gear")
ok("groove" in dlg.edits and "helix" in dlg.edits and "hand" in dlg.edits, "herringbone has helix, hand and groove boxes")
ok(dlg.raw["Spur gear"]["teeth"] == "30", "values typed for one type are kept when switching")
dlg.reject()

# ---- adding a part: patch exec so the "user" fills the window in
def add_gear(self):
    self.set_kind("Helical gear")
    type_in(self, "teeth", "24")
    type_in(self, "helix", "15")
    return QDialog.DialogCode.Accepted


partgen_dialog.PartGenDialog.exec = add_gear
n0 = len(d.features)
w.command("partgen")
ok(len(w.doc.features) == n0 + 1, "OK adds exactly one feature")
d = w.doc
f = d.feature(w.sel)
ok(f["kind"] == "partgen" and f["gen"] == "Helical gear" and f["params"]["teeth"] == "24" and f["params"]["helix"] == "15", f"feature keeps its parameters: {f['name']}")
ok(d.status[f["id"]] == "ok" and len(d.solid.solids()) == 1, "one solid built")
D = gears.dims({"module": 2, "teeth": 24, "pressure": 20, "width": 10, "helix": 15})
ok(abs(d.solid.bounding_box().max.X - D["ra"]) < 0.01, f"outside radius {D['ra']:.3f}")
v1 = d.solid.volume

# ---- reopening edits it (double click in the tree) and keeps the same feature
seen = {}


def edit_gear(self):
    seen["kind"], seen["teeth"], seen["locked"] = self.kind, self.raw[self.kind]["teeth"], not self.types.isEnabled()
    type_in(self, "teeth", "36")
    return QDialog.DialogCode.Accepted


partgen_dialog.PartGenDialog.exec = edit_gear
w.tree_double(w.tree.findItems(f["name"], 0x1 | 0x40 if False else pm_app.Qt.MatchFlag.MatchContains | pm_app.Qt.MatchFlag.MatchRecursive)[0], 0)
ok(seen == {"kind": "Helical gear", "teeth": "24", "locked": True}, f"dialog reopens on the saved values {seen}")
f2 = d.feature(f["id"])
ok(len(d.features) == n0 + 1 and f2["params"]["teeth"] == "36" and d.solid.volume > v1, "same feature, now 36 teeth")

# cancel changes nothing
partgen_dialog.PartGenDialog.exec = lambda self: QDialog.DialogCode.Rejected
w.partgen_dialog(f2)
ok(d.feature(f["id"])["params"]["teeth"] == "36", "Cancel changes nothing")

# the properties panel offers the edit button
w.sel = f["id"]; w.show_props()
ok(any(b.text().startswith("Edit in Part Generator") for b in w.props_lay.parent().findChildren(__import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton)), "properties panel has the Edit button")

# ---- formulas from the Globals, error shown on the feature, save / load
d.params["Teeth"] = "28"
d.feature(f["id"])["params"]["teeth"] = "Teeth"
d.rebuild()
ok(d.status[f["id"]] == "ok" and abs(gears.dims({"module": 2, "teeth": 28, "pressure": 20, "width": 10, "helix": 15})["da"] / 2 - d.solid.bounding_box().max.X) < 0.01, "teeth driven by a Global")
d.feature(f["id"])["params"]["bore"] = "500"
d.rebuild()
ok(d.status[f["id"]].startswith("error") and "bore" in d.status[f["id"]], "bad value -> red error: " + d.status[f["id"]])
d.feature(f["id"])["params"]["bore"] = "8"
d.rebuild()
back = pm.Document.from_json(d.to_json()); back.rebuild()
ok(abs(back.solid.volume - d.solid.volume) < 1e-6 and back.features[0]["params"] == d.features[0]["params"], "file round trip keeps the parameters")

# ---- placement
d2 = pm.Document()
g = d2.add(pm.new_feature("partgen", gen="Spur gear", params=partgen.defaults("Spur gear"), place={"plane": "Right", "ox": "5", "oy": "0", "oz": "3"}))
d2.rebuild()
bb = d2.solid.bounding_box()
ok(d2.status[g["id"]] == "ok" and abs(bb.min.X - 3) < 1e-6 and abs(bb.max.X - 13) < 1e-6, "gear axis along X, offset 3 along the axis")
print("\nOK")
