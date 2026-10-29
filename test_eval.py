import faulthandler; faulthandler.dump_traceback_later(150, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk, evaluate
w = pm_app.MainWindow(); d = w.doc
w.sel_plane = "Top"; w.command("sketch"); sid = w.sel
m = w.ed.m; sk.add_rect_corner(m, (0, 0), (10, 20)); d.reports[sid] = sk.solve_model(m); d.store_sketch(sid); w.leave_sketch()
for f in list(d.features):
    if f["id"] != sid and f["kind"] != "sketch": d.features.remove(f)
d.features = [f for f in d.features if f["id"] == sid]
w.sel = sid; w.command("extrude"); e = d.feature(w.sel); e["depth"] = "30"; w.update_all()
s = d.solid; print("vol", s.volume, [round(x) for x in s.bounding_box().size])
p = evaluate.mass_properties(s, 7850.0)
V = p["volume"]; mass = V * 7850e-9
print("mass kg", p["mass"], mass)
bs = s.bounding_box().size; a, b, c = bs.X, bs.Y, bs.Z
print("pm", p["pm"], sorted([mass*(b*b+c*c)/12, mass*(a*a+c*c)/12, mass*(a*a+b*b)/12]))
assert np.allclose(sorted(p["pm"]), sorted([mass*(b*b+c*c)/12, mass*(a*a+c*c)/12, mass*(a*a+b*b)/12]), rtol=1e-6)
print(evaluate.mass_text("Part1", p, "US (in, lb)", 7850.0)[:700])
w.mass_open(); print(w.mass_dialog.out.toPlainText()[:120]); w.mass_dialog.mat.setCurrentIndex(2); print(d.material, w.mass_dialog.out.toPlainText().split("\n")[3:6])
d2 = pm.Document.from_json(d.to_json()); assert d2.material == d.material
# measure
w.measure_toggle(); assert w.measuring
sol = w.shown_solid()
faces = sol.faces(); verts = sol.vertices()
def it(kind, i, shape): return {"kind": kind, "idx": i, "shape": shape}
topf = max(faces, key=lambda f: f.center().Z); botf = min(faces, key=lambda f: f.center().Z)
w.meas_items = [it("face", 0, topf), it("face", 1, botf)]
for k in ("cc", "mx"): w.measure_panel.opt[k].setChecked(True)
w.measure_update(); print(w.measure_panel.out.toPlainText())
w.meas_items = [it("vertex", 0, verts[0]), it("vertex", 1, verts[-1])]; w.measure_update(); print(w.measure_panel.out.toPlainText())
w.measure_panel.unit.setCurrentText("in"); print(w.measure_panel.out.toPlainText().split("\n")[:4])
edges = sol.edges(); w.meas_items = [it("edge", 0, edges[0])]; w.measure_update(); print(w.measure_panel.out.toPlainText())
w.measure_toggle(); assert not w.measuring
print("OK")
