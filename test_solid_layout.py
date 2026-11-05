"""3D FEA window: numbered sections like 2D FEA, material list, global units in inputs and results, grey mesh before Solve, click probe;
and the shared results formatter (sim_report)."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk
import sim_report as R, solid_tab, unitctl, units

# --- the formatter
assert R.num(1234.5678) == "1234.6" and R.num(0.000012345) == "1.2345e-5" and R.num(None) == "n/a" and R.num(0) == "0"
h = R.summary(2.5, None, [("Largest displacement", "0.01", "mm")])
assert "Summary" in h and "n/a" in h and "mm" in h
assert "Converged" in R.refine_block([{"pass": 1, "n": 10, "umax": 1.0, "vmax": 2.0, "change": None}, {"pass": 2, "n": 20, "umax": 1.01, "vmax": 2.0, "change": 0.01}],
                                      "stopped", True, "mm", "MPa")
assert "CHECK" in R.solver_block("direct", 1e-3, False, "x")

# --- a bar and its 3D window
T = tempfile.mkdtemp(prefix="opara_sl_")
d = pm.Document(); d.params = {"T": "10"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
r = sk.add_rect_corner(m, (0, 0), (100, 10))
m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())
w = solid_tab.SolidWindow(threaded=False)
assert w.create_project(os.path.join(T, "bar_l")) and w.import_file(part)

# sections 1..7, in the order of 2D FEA, with the Solve button before the results
nums = [s_.number for s_ in w.sections]
assert nums == sorted(nums) == [1, 2, 3, 4, 5, 6, 7], nums
titles = [s_.title for s_ in w.sections]
assert titles[:3] == ["Geometry", "Material and analysis", "Supports"] and titles[-1] == "Results"

# material list
assert w.mat_combo.count() > 2 and w.mat_combo.itemData(0) is None
names = [w.mat_combo.itemData(i) for i in range(w.mat_combo.count())]
alu = next(n for n in names if n and "alumin" in n.lower())
w.mat_combo.setCurrentIndex(names.index(alu)); w.material_picked()
assert 60000 < w.setup["material"]["E"] < 80000, w.setup["material"]

def face(n):
    return next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], n) > 0.99)
w.select_faces([face([-1, 0, 0])]); w.add_support("fixed")
w.select_faces([face([1, 0, 0])]); w.add_load("force", {"f": [1000.0, 0.0, 0.0]})
w.e_h.setText("6"); w.inputs_changed()
assert w.run_mesh()
if w.view.plotter is not None:
    assert w.view.mesh_actor is not None and w.view.result_actor is None, "meshed only: plain grey surface, no result colours"
assert w.run_solve()
t = w.res_lbl.text()
for word in ("Summary", "Largest von Mises stress", "Largest displacement", "Mesh", "Solver check", "OK"):
    assert word in t, word
assert "MPa" in t and "mm" in t

# global units: US customary; the labels, fields and results follow
n0 = w.result["vm_max"]
unitctl.set_units("in-lb-psi" if units.valid("in-lb-psi") else next(n for n in units.SYSTEMS if units.get(n)["L"] == "in"), persist=False)
L = units.get(unitctl.system())["L"]
assert L == "in" and "(in" in w.h_label.text() and units.get(unitctl.system())["S"] in w.mat_labels["E"].text()
assert units.get(unitctl.system())["S"] in w.res_lbl.text() and "in" in w.res_lbl.text()
w.read_inputs(); assert abs(w.setup["h"] - 6) < 1e-6, "typed values keep their meaning across a unit change"
w.e_probe.setText(f"{100 / 25.4}, {5 / 25.4}, {5 / 25.4}")
i, dist, un, vm = w.probe_node()
assert dist < 6 and "Probe" in w.probe_lbl.text() and "Displacement" in w.probe_lbl.text() and "Stress" in w.probe_lbl.text()
unitctl.set_units("mm" if units.valid("mm") else units.DEFAULT, persist=False)

# click probe
p = w.result["nodes"][i]
assert w.probe_at(tuple(p)) is not None and w.last_probe["i"] == i
print("OK solid layout")
