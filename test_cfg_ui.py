import faulthandler; faulthandler.dump_traceback_later(150, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QInputDialog
app = QApplication([])
import pm_app, pm_model as pm
w = pm_app.MainWindow(); d = w.doc          # the demo part: Length/Width/Height/HoleD
print("tabs", w.left.count(), [w.left.tabToolTip(i) for i in range(w.left.count())])
cp = w.cfg_panel
print("candidates", [l for _k, l, _v in w.cfg_candidates()])
for key in ("g:Height", "g:Width"):
    w.cfg_panel.add_column(key)
QInputDialog.getText = staticmethod(lambda *a, **k: ("Tall", True))
cp.add_config()
print("names", d.cfg["names"], "cols", [d.cfg_label(k) for k in d.cfg["cols"]])
r = d.cfg["names"].index("Tall"); col = 1 + d.cfg["cols"].index("g:Height")
cp.table.item(r, col).setText("40")
print("Tall height cell", d.cfg["cells"]["Tall"]["g:Height"], "active", d.cfg["active"], "vol", round(d.solid.volume))
v0 = d.solid.volume
cp.activate("Tall"); print("active", d.cfg["active"], "vol", round(w.doc.solid.volume), "expected", 60 * 40 * 40)
assert abs(w.doc.solid.volume - 60 * 40 * 40) < 1 and w.doc.solid.volume != v0
cp.activate("Default"); print("back", round(w.doc.solid.volume)); assert abs(w.doc.solid.volume - v0) < 1
# display
w.doc.display["color"] = [0.9, 0.2, 0.2]; w.doc.display["opacity"] = 0.5; w.display_changed(); print("display ok", w.doc.display)
w.disp_panel.table.cellWidget(0, 2).setValue(30); print("opacity", w.doc.display["opacity"])
# equations dialog from the tree
w.eq_dialog.show(); print("eq visible", w.eq_dialog.isVisible())
# undo restores
w.do_undo(); print("after undo", w.doc.cfg["active"])
js = w.doc.to_json(); d2 = pm.Document.from_json(js); print("roundtrip names", d2.cfg["names"], d2.display)
print("OK")

# --- activation check boxes
from PyQt6.QtCore import Qt as _Q
t=cp.table; names=cp.m.cfg["names"]; act=cp.m.cfg["active"]
other=[n for n in names if n!=act][0]; ro=names.index(other); ra=names.index(act)
t.item(ro,0).setCheckState(_Q.CheckState.Checked)
assert cp.m.cfg["active"]==other, "activate by checkbox"
t=cp.table
assert t.item(ro,0).checkState()==_Q.CheckState.Checked and t.item(ra,0).checkState()==_Q.CheckState.Unchecked
t.item(ro,0).setCheckState(_Q.CheckState.Unchecked)
app.processEvents()
assert cp.m.cfg["active"]==other and cp.table.item(ro,0).checkState()==_Q.CheckState.Checked, "can't uncheck active"
print("CHECKBOX OK")
