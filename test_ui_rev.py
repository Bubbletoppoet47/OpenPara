import faulthandler; faulthandler.dump_traceback_later(150, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk
w = pm_app.MainWindow(); d = w.doc
w.sel_plane = "Front"; w.command("sketch"); sid = w.sel
m = w.ed.m; sk.add_rect_corner(m, (10, 0), (20, 30)); d.reports[sid] = sk.solve_model(m); d.store_sketch(sid); w.leave_sketch()
w.sel = sid; w.command("revolve"); f = d.feature(w.sel)
print("revolve", d.status[f["id"]], round(d.solid.volume))
cbs = w.props_lay.parent().findChildren(QComboBox); print("combos", [c.currentText() for c in cbs])
# boss to pattern: cylinder sketch on Top
w.sel_plane = "Top"; w.command("sketch"); s2 = w.sel
m = w.ed.m; sk.add_circle(m, (30, 0), (33, 0)); d.reports[s2] = sk.solve_model(m); d.store_sketch(s2); w.leave_sketch()
w.sel = s2; w.command("extrude"); e = d.feature(w.sel); e["depth"] = "5"; w.update_all()
v0 = d.solid.volume
for key in ("pattern_linear", "pattern_circular", "mirror"):
    w.sel = e["id"]; w.command(key); p = d.feature(w.sel)
    print(key, d.status[p["id"]], round(d.solid.volume - v0, 1), [c.text() for c in w.props_lay.parent().findChildren(QCheckBox)])
    assert d.status[p["id"]] == "ok"
# edge mode
print("OK")
