import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QFormLayout
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk
w = pm_app.MainWindow(); d = w.doc
# a sketch with two separate rectangles -> contour list
w.sel_plane = "Top"; w.command("sketch"); sid = w.sel
m = w.ed.m; sk.add_rect_corner(m, (0, 0), (10, 10)); sk.add_rect_corner(m, (30, 0), (50, 10)); w.doc.reports[sid] = sk.solve_model(m); w.doc.store_sketch(sid); w.leave_sketch()
w.sel = sid; w.command("extrude"); f = w.doc.feature(w.sel); f["depth"] = "5"; w.update_all()
def boxes(): return [c for c in w.props_lay.parent().findChildren(QCheckBox)]
print("checkboxes:", [c.text() for c in boxes()])
v0 = w.doc.solid.volume
reg = [c for c in boxes() if c.text().startswith("Region")]
reg[0].setChecked(False)
print("one region unticked:", round(w.doc.solid.volume), "was", round(v0)); assert w.doc.solid.volume < v0
def row_widget(label):
    for form in w.props_lay.parent().findChildren(QFormLayout):
        for r in range(form.rowCount()):
            li = form.itemAt(r, QFormLayout.ItemRole.LabelRole)
            if li is not None and li.widget() is not None and li.widget().text().strip() == label:
                return form.itemAt(r, QFormLayout.ItemRole.FieldRole).widget()
for text in ("Direction 2", "Draft", "Thin feature", "Reverse direction"):
    row_widget(text).setChecked(True)
    print(text, w.doc.status[f["id"]][:70])
cbs = w.props_lay.parent().findChildren(QComboBox)
print("combos:", [c.currentText() for c in cbs])
for c in cbs:
    if c.findText("Through All") >= 0:
        c.setCurrentIndex(c.findText("Through All"))
print("final", w.doc.status[f["id"]][:60])
print("OK")
