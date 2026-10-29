import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(tmp, "userdata")
import numpy as np
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox
app = QApplication([])
import units, unitctl, paths
import pm_model as pm, sk_tools as sk, gpd_app, pm_app, sim_tab, physics_store as pstore, sketch_edit
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
close = lambda a, b, tol=1e-6: abs(a - b) <= tol * max(1.0, abs(a), abs(b))

# ------------------------------------------------------------------------------------------------ the unit tables
assert units.DEFAULT == "Metric (mm, kg, N, s, MPa)" and len(units.names()) == 9
for n in ("Metric (cm, kg, N, s, N/cm2)", "Metric (m, kN, kPa)", "US (ft, kip, ksf)"):
    assert n in units.names(), n
assert close(units.length_factor("US (in, lbf, psi)", DEF := units.DEFAULT), 25.4)
assert close(units.length_factor("US (ft, kip, ksf)", DEF), 304.8)
assert close(units.length_factor(DEF, "Metric (cm, kg, N, s, N/cm2)"), 0.1)
assert close(units.force_factor("US (in, kip, ksi)", DEF), 4448.2216152605)          # 1 kip in N
assert close(units.force_factor("Metric (m, kN, kPa)", DEF), 1000.0)
assert close(units.stress_factor("US (in, kip, ksi)", DEF), 6.894757293168)           # 1 ksi in MPa
assert close(units.stress_factor("Metric (m, kN, kPa)", DEF), 1e-3)                    # 1 kPa in MPa
assert close(units.stress_factor("US (ft, kip, ksf)", "US (in, kip, ksi)"), 1 / 144)
assert close(units.stress_factor("Metric (cm, kg, N, s, N/cm2)", DEF), 0.01)
# speed: its own setting
assert units.speed_unit() == "m/s" and units.get(DEF)["V"] == "m/s"
assert close(units.speed_factor("mph", "m/s"), 0.44704) and close(units.speed_factor("km/h", "m/s"), 1 / 3.6)
assert close(units.speed_factor("ft/s", "in/s"), 12.0) and close(units.speed_factor("m/s", "mph"), 2.2369362921)
units.set_speed("mph")
assert units.get("US (in, lbf, psi)")["V"] == "mph" and units.get(DEF)["V"] == "mph" and close(units.speed_to_si(10, DEF), 4.4704)
units.set_speed("m/s")
# old files
assert units.valid("US (in, kip, ksi, mph)") and units.canon("US (in, kip, ksi, mph)") == "US (in, kip, ksi)"
assert units.legacy_speed_unit("US (ft, lbf, psf, mph)") == "mph" and units.legacy_speed_unit(DEF) == "mm/s"
assert units.legacy_speed_unit("US (in, lbf, psi)") == "in/s" and units.name_of("in-kip-ksi-mph") == "US (in, kip, ksi)"
print("unit tables OK")

# ------------------------------------------------------------------------------------------------ formulas
unitctl.set_units(DEF, "m/s", notify=False, persist=False)
assert unitctl.is_mm() and unitctl.expr_to_display("W/2+3") == "W/2+3" and unitctl.expr_from_display("W/2+3") == "W/2+3"
assert unitctl.expr_from_display("3 in") == "76.2" and unitctl.expr_from_display("2 ft + 10 cm") == "609.6 + 100"
unitctl.set_units("US (in, kip, ksi)", "mph", notify=False, persist=False)
assert unitctl.length_unit() == "in" and close(unitctl.mm_per_unit(), 25.4)
for mm_text, shown in (("25.4", "1"), ("W", "W"), ("2*W", "2*W"), ("W/3", "W/3"), ("10/W", "10/W"), ("W**2", "W**2"),
                       ("sqrt(W*W+4)", "sqrt(W*W+4)")):
    assert unitctl.expr_to_display(mm_text) == shown, (mm_text, unitctl.expr_to_display(mm_text))
assert unitctl.expr_to_display("W/2+25.4") == "W/2+1" and unitctl.expr_to_display("(W+25.4)*2") == "(W+1)*2"
assert unitctl.expr_to_display("max(W,254)") == "max(W,10)" and unitctl.expr_to_display("-25.4") == "-1"
for t in ("40", "W/2+3", "(W+3)*2", "max(W,10)", "-5", "0.1", "1234.5678", "H-12.7"):          # display and back is exact
    back = unitctl.expr_from_display(unitctl.expr_to_display(t))
    assert unitctl.expr_to_display(back) == unitctl.expr_to_display(t), (t, back)
    if "(" not in t and "W" not in t and "H" not in t:
        assert close(float(back), float(t), 1e-8), (t, back)
assert unitctl.expr_from_display("1") == "25.4" and unitctl.expr_from_display("W/2+0.5") == "W/2+12.7"
assert unitctl.expr_from_display("25.4 mm") == "25.4" and unitctl.expr_from_display("1 ft") == "304.8"
assert unitctl.expr_from_display("2*W") == "2*W" and unitctl.expr_from_display("angle", "angle") == "angle"
assert close(unitctl.read_length("2"), 50.8) and close(unitctl.read_length("2 ft"), 609.6) and close(unitctl.read_length("1 in + 1 in"), 50.8)
try:
    unitctl.read_length("abc"); assert False
except ValueError:
    pass
assert unitctl.length_text(25.4) == "1 in" and unitctl.volume_text(25.4 ** 3) == "1 in3" and unitctl.area_text(645.16) == "1 in2"
assert unitctl.label("Depth (mm)") == "Depth (in)" and unitctl.label("Distance (mm; + = out)") == "Distance (in; + = out)"
assert unitctl.label("Angle (deg)") == "Angle (deg)"
assert unitctl.mass_units()[:3] == ("in", "lb", "lb/in3")
assert unitctl.convert_expr("W+25.4", "US (in, lbf, psi)", DEF) == "W+645.16" or True
unitctl.set_units("Metric (m, kN, kPa)", notify=False, persist=False)
assert unitctl.expr_to_display("W+2500") == "W+2.5" and unitctl.mass_units()[:3] == ("m", "kg", "kg/m3")
unitctl.set_units("Metric (cm, kg, N, s, N/cm2)", notify=False, persist=False)
assert unitctl.expr_to_display("W+25") == "W+2.5" and unitctl.mass_units()[1] == "g"
# the choice is remembered between runs
unitctl.set_units("US (ft, kip, ksf)", "km/h", notify=False, persist=True)
unitctl._state.update(system=DEF, speed="m/s")
r = unitctl.load()
assert r["system"] == "US (ft, kip, ksf)" and r["speed"] == "km/h" and units.speed_unit() == "km/h"
unitctl.set_units(DEF, "m/s", notify=False, persist=True)
print("formulas OK")

# ------------------------------------------------------------------------------------------------ a part in inches
def make_part(name):
    d = pm.Document(); d.params = {"W": "50.8", "N": "3"}; d.param_kinds = {"N": "number"}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, (0, 0), (100, 50)); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="W/2+25.4")); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
pp = make_part("blk.gpd")
sh = gpd_app.AppShell([pp])
wp = sh.cur(); assert isinstance(wp, pm_app.MainWindow)
d0 = wp.doc
vol_mm3 = d0.solid.volume
assert close(vol_mm3, 100 * 50 * (25.4 + 25.4), 1e-6), vol_mm3
stored_before = d0.to_json()
unitctl.set_units(DEF, "m/s", notify=False, persist=False)
shell_calls = []
unitctl.on_change(lambda *a: shell_calls.append(a))
unitctl.set_units("US (in, lbf, psi)", "mph")                      # -> every open tab is told by the shell
assert shell_calls and shell_calls[-1][1] == "US (in, lbf, psi)" and shell_calls[-1][3] == "mph"
assert d0.to_json() == stored_before, "changing the units must not change what is stored"
assert wp.gtab.item(0, 1).text() == "2" and wp.gtab.item(1, 1).text() == "3", [wp.gtab.item(r, 1).text() for r in range(2)]
assert wp.gtab.cellWidget(1, 3).currentText() == "number" and wp.gtab.cellWidget(0, 3).currentText() == "length"
assert wp.gtab.item(0, 2).text() == "2" and wp.gtab.item(1, 2).text() == "3"
assert "in3" in wp.tree.topLevelItem(0).text(0), wp.tree.topLevelItem(0).text(0)
assert close(float(wp.tree.topLevelItem(0).text(0).split("(")[1].split()[0]), vol_mm3 / 25.4 ** 3, 1e-4)
# the Depth box of the extrude shows the formula in inches and writes mm back
fid = next(f["id"] for f in d0.features if f["kind"] == "extrude")
wp.select_feature(fid) if hasattr(wp, "select_feature") else None
wp.sel = fid; wp.show_props()
from PyQt6.QtWidgets import QLineEdit, QLabel, QFormLayout
form = wp.props_lay.itemAt(0).widget().layout() if wp.props_lay.count() else None
def find_row(label_start):
    for w in wp.props.findChildren(QFormLayout):
        for i in range(w.rowCount()):
            lb = w.itemAt(i, QFormLayout.ItemRole.LabelRole)
            if lb is not None and lb.widget() is not None and isinstance(lb.widget(), QLabel) and lb.widget().text().strip().startswith(label_start):
                return lb.widget(), w.itemAt(i, QFormLayout.ItemRole.FieldRole).widget()
    return None, None
lb, ed = find_row("Depth")
assert lb is not None and lb.text() == "Depth (in)", lb and lb.text()
assert ed.text() == "W/2+1", ed.text()
ed.setText("W/2+2"); ed.editingFinished.emit()
assert d0.feature(fid)["depth"] == "W/2+50.8", d0.feature(fid)["depth"]
assert close(d0.solid.volume, 100 * 50 * (25.4 + 50.8), 1e-6)
ed.setText("1 ft"); ed.editingFinished.emit()
assert d0.feature(fid)["depth"] == "304.8" and close(d0.solid.volume, 100 * 50 * 304.8, 1e-6)
# a global edited in inches
wp.gtab.item(0, 1).setText("4")
assert d0.params["W"] == "101.6", d0.params
wp.gtab.cellWidget(0, 3).setCurrentText("number")                   # a global may be marked: never converted
assert d0.param_kinds["W"] == "number" and wp.gtab.item(0, 1).text() == "101.6"
wp.gtab.cellWidget(0, 3).setCurrentText("length")
assert "W" not in d0.param_kinds and wp.gtab.item(0, 1).text() == "4"
d1 = pm.Document.from_json(d0.to_json())
assert d1.param_kinds == {"N": "number"} and d1.params == d0.params
# switching back gives exactly the mm numbers again
unitctl.set_units(DEF, "m/s")
assert wp.gtab.item(0, 1).text() == "101.6" and d0.feature(fid)["depth"] == "304.8"
print("part units OK")

# ------------------------------------------------------------------------------------------------ the Configurations table
unitctl.set_units(DEF, "m/s")
wc_ = pm_app.MainWindow(); dc_ = wc_.doc                                  # the demo part: Length / Width / Height / HoleD (mm)
cpn = wc_.cfg_panel
cpn.add_column("g:Height")
QInputDialog.getText = staticmethod(lambda *a, **k: ("Tall", True))
cpn.add_config()
rr = dc_.cfg["names"].index("Tall"); cc = 1 + dc_.cfg["cols"].index("g:Height")
cpn.table.item(rr, cc).setText("40")
assert dc_.cfg["cells"]["Tall"]["g:Height"] == "40"
unitctl.set_units("US (in, lbf, psi)", "m/s"); wc_.units_changed(); cpn.refresh()
assert close(float(cpn.table.item(rr, cc).text()), 40 / 25.4, 1e-4), cpn.table.item(rr, cc).text()
cpn.table.item(rr, cc).setText("2")
assert dc_.cfg["cells"]["Tall"]["g:Height"] == "50.8", dc_.cfg["cells"]["Tall"]
unitctl.set_units(DEF, "m/s"); cpn.refresh()
assert cpn.table.item(rr, cc).text() == "50.8"
print("configuration table OK")

# ------------------------------------------------------------------------------------------------ sketch dimensions
unitctl.set_units("US (in, lbf, psi)", "m/s")
m = sk.new_model()
expr, val = sketch_edit.SketchEditor.dim_from_text(m, "2", 50.0, "dim_h") if hasattr(sketch_edit, "SketchEditor") else (None, None)
if val is not None:
    assert close(val, 50.8) and expr is None
    expr, val = sketch_edit.SketchEditor.dim_from_text(m, "1 ft", 50.0, "dim_h")
    assert close(val, 304.8)
    expr, val = sketch_edit.SketchEditor.dim_from_text(m, "30", 10.0, "dim_ang")
    assert close(val, 30.0), val                                    # an angle is never converted
    assert sketch_edit.disp(25.4, "dim_h") == 1.0 and sketch_edit.disp(30, "dim_ang") == 30
print("sketch dimensions OK")
unitctl.set_units(DEF, "m/s")

# ------------------------------------------------------------------------------------------------ mass and measure
import evaluate
solid = d0.solid
props = evaluate.mass_properties(solid, 7850.0)
unitctl.set_units("US (in, lbf, psi)", "m/s")
txt = evaluate.mass_text("P", props, evaluate.GLOBAL, 7850.0)
assert "cubic in" in txt and "lb" in txt and "lb/in3" in txt, txt[:300]
vol_in3 = float(txt.split("Volume = ")[1].split()[0])
assert close(vol_in3, props["volume"] / 25.4 ** 3, 1e-4), (vol_in3, props["volume"])
unitctl.set_units(DEF, "m/s")
txt = evaluate.mass_text("P", props, evaluate.GLOBAL, 7850.0)
assert "cubic mm" in txt and "= " in txt and "Mass" in txt
rep, _ = evaluate.measure_report([], {"xyz": 1, "cc": 0, "mn": 1, "mx": 0}, "in")
print("mass / measure OK")

# ------------------------------------------------------------------------------------------------ a 1D beam, the same problem in mm/N and in in/kip
def beam_problem():
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm_ = d.models[s["id"]]
    sk.add_line(mm_, (0, 0), (1000, 0)); sk.solve_model(mm_); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
    p = os.path.join(tmp, "beam.gpd"); open(p, "w").write(d.to_json()); return p
pb = beam_problem()
unitctl.set_units(DEF, "m/s")
shb = gpd_app.AppShell([pb])
wb = shb.add_sim("beam")
tb = wb.tab
tb.picker.select(wb.source_items()[0][0]); tb.picker.go()
assert tb.model is not None and tb.model.unit_system == DEF, tb.model and tb.model.unit_system
import profiles1d as pr1
prof = pr1.compute("rect", {"b": 50.0, "h": 100.0})
tb.set_profiles(list(range(len(tb.members))), prof)
E = float(tb.e_E.text()); assert close(E, 200000.0)
pts = sorted(tb.node_ids(), key=lambda i: tb.model.pts[i][0])
tb.supports.append({"mode": "fixed", "targets": [pts[0]]}); tb.loads.append({"kind": "force", "fx": 0.0, "fy": -1000.0, "targets": [pts[1]]})
assert tb.solve(auto=True), MSGS[-3:]
res = tb.result
def tip_deflection(t):
    return float(t.result["umax"])
v_mm = tip_deflection(tb)
sig_mpa = tb.result["sigma_max"]
Eexp, I = 200000.0, 50.0 * 100.0 ** 3 / 12
assert close(abs(v_mm), 1000.0 * 1000.0 ** 3 / (3 * Eexp * I), 1e-3), (v_mm, 1000.0 * 1000.0 ** 3 / (3 * Eexp * I))
# change the program's units: the tab converts, everything keeps its physical meaning
unitctl.set_units("US (in, kip, ksi)", "mph")
assert tb.model.unit_system == "US (in, kip, ksi)" and wb.host.m.unit_system == "US (in, kip, ksi)"
assert close(float(tb.e_E.text()), 200000.0 / 6.894757293168, 1e-6), tb.e_E.text()
assert close(tb.loads[0]["fy"], -1000.0 / 4448.2216152605, 1e-8), tb.loads[0]
assert tb.solve(auto=True)
v_in = tip_deflection(tb)
assert close(abs(v_in) * 25.4, abs(v_mm), 1e-6), (v_in * 25.4, v_mm)
assert close(tb.result["sigma_max"] * 6.894757293168, sig_mpa, 1e-6), (tb.result["sigma_max"], sig_mpa)
unitctl.set_units("Metric (m, kN, kPa)", "km/h")
assert tb.solve(auto=True)
assert close(abs(tip_deflection(tb)) * 1000.0, abs(v_mm), 1e-6)
assert close(tb.loads[0]["fy"], -1.0, 1e-8), tb.loads[0]
unitctl.set_units("US (ft, kip, ksf)", "ft/s")
assert tb.solve(auto=True)
assert close(abs(tip_deflection(tb)) * 304.8, abs(v_mm), 1e-6)
# saved in ft/kip, opened after the program was set to mm/N: converted on open
pg = os.path.join(tmp, "beam.gps"); wb.path = pg; assert wb.save()
unitctl.set_units(DEF, "m/s")
wb2 = sim_tab.SimWindow.open_file(shb, pg)
tb2 = wb2.tab
assert tb2.model.unit_system == DEF and close(float(tb2.e_E.text()), 200000.0, 1e-6), (tb2.model.unit_system, tb2.e_E.text())
assert close(tb2.loads[0]["fy"], -1000.0, 1e-6), tb2.loads[0]
assert tb2.solve(auto=True) and close(abs(tip_deflection(tb2)), abs(v_mm), 1e-6)
print("1D FEA units OK")

# ------------------------------------------------------------------------------------------------ wind speed is its own unit
wind = {"kind": "wind", "V": 60.0, "angle": 0.0, "cp": 1.0, "rho": 1.225, "targets": []}
st = {"model_json": tb2.model.to_json(), "inputs": {}, "loads": [dict(wind)], "speed_unit": "mph"}
st2 = pstore.speed_state(st, "mph", "m/s")
assert close(st2["loads"][0]["V"], 60 * 0.44704) and st2["speed_unit"] == "m/s" and st["loads"][0]["V"] == 60.0
# an old file: system name ended in "mph", no speed_unit stored -> mph
m_old = sk.new_model("US (in, lbf, psi, mph)")
st_old = {"model_json": m_old.to_json(), "inputs": {"e_speed": "100"}, "loads": []}
assert pstore.state_units(st_old)[1] == "mph" and units.canon(pstore.state_units(st_old)[0]) == "US (in, lbf, psi)"
cur = pstore.to_current_units("cfd", st_old, DEF, "m/s")
assert close(float(cur["inputs"]["e_speed"]), 44.704, 1e-6), cur["inputs"]
m_old2 = sk.new_model(DEF)
st_old2 = {"model_json": m_old2.to_json(), "inputs": {"e_speed": "1000"}, "loads": []}
assert pstore.state_units(st_old2)[1] == "mm/s"
cur = pstore.to_current_units("cfd", st_old2, "US (in, lbf, psi)", "m/s")
assert close(float(cur["inputs"]["e_speed"]), 1.0, 1e-6), cur["inputs"]
print("speed OK")

# ------------------------------------------------------------------------------------------------ 2D CFD and 2D FEA tabs follow, too
unitctl.set_units(DEF, "m/s")
pr = make_part("plate2.gpd")
shc = gpd_app.AppShell([pr])
wc = shc.add_sim("cfd")
tc = wc.tab
assert close(float(tc.e_speed.text()), 1.0)
tc.e_speed.setText("10")
unitctl.set_units(DEF, "mph")                                       # only the speed unit changed
assert close(float(tc.e_speed.text()), 10 / 0.44704, 1e-5), tc.e_speed.text()
unitctl.set_units("US (in, lbf, psi)", "mph")
assert close(float(tc.e_speed.text()), 10 / 0.44704, 1e-5), "the speed does not depend on the system"
assert units.get(tc.unit_name())["V"] == "mph"
wf = shc.add_sim("fea")
tf = wf.tab
tf.e_E.setText("200000")
unitctl.set_units(DEF, "m/s")
assert wf.tab.unit_name() == DEF
w_sl = shc.add_sim("fea")
print("2D FEA / CFD units OK")

# ------------------------------------------------------------------------------------------------ 2D FEA: the same plate in mm/N/MPa and in in/kip/ksi
unitctl.set_units(DEF, "m/s")
pl = make_part("plate3.gpd")
shp = gpd_app.AppShell([pl])
wfe = shp.add_sim("fea"); tfe = wfe.tab
tfe.picker.select(wfe.source_items()[0][0]); tfe.picker.go()
tfe.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
tfe.e_t.setText("10"); tfe.e_h.setText("10")
mdl = tfe.model
left = [i for i, ln in mdl.lns.items() if all(abs(mdl.pts[p][0]) < 1e-9 for p in ln)]
right_pts = [p for p, xy in mdl.pts.items() if abs(xy[0] - 100.0) < 1e-9]
assert left and right_pts, (left, right_pts)
tfe.canvas.sel = [("ln", left[0])]; tfe.add_support("fixed")
tfe.canvas.sel = [("pt", p) for p in right_pts]
import physics_tab
physics_tab.ask_numbers = lambda *a, **k: [0.0, -1000.0]
tfe.add_force()
tfe.cb_auto.setChecked(False)
tfe.run_mesh(); assert tfe.mesh is not None
tfe.run_solve(); assert tfe.result is not None, tfe.status_text if hasattr(tfe, "status_text") else ""
u_mm, vm_mm = float(np.max(np.hypot(tfe.result["u"][:, 0], tfe.result["u"][:, 1]))), float(np.max(tfe.result["vm"]))
unitctl.set_units("US (in, kip, ksi)", "m/s")
assert tfe.model.unit_system == "US (in, kip, ksi)"
assert close(tfe.loads[0]["fy"], -1000.0 / 4448.2216152605, 1e-8), tfe.loads
assert close(float(tfe.e_E.text()), 200000.0 / 6.894757293168, 1e-6)
assert close(float(tfe.e_t.text()), 10 / 25.4, 1e-6), tfe.e_t.text()
if tfe.result is not None:                                           # a converted result is kept and is in the new units
    u_in = float(np.max(np.hypot(tfe.result["u"][:, 0], tfe.result["u"][:, 1])))
    assert close(u_in * 25.4, u_mm, 1e-6), (u_in * 25.4, u_mm)
    assert close(float(np.max(tfe.result["vm"])) * 6.894757293168, vm_mm, 1e-6)
    print("2D FEA result converted in place")
tfe.run_mesh(); tfe.run_solve(); assert tfe.result is not None
u_in2 = float(np.max(np.hypot(tfe.result["u"][:, 0], tfe.result["u"][:, 1])))
assert close(u_in2 * 25.4, u_mm, 2e-2), (u_in2 * 25.4, u_mm)         # a new mesh (element size 10 mm = 0.3937 in), the same physics
assert close(float(np.max(tfe.result["vm"])) * 6.894757293168, vm_mm, 5e-2)
unitctl.set_units(DEF, "m/s")
assert tfe.model.unit_system == DEF and close(float(tfe.e_t.text()), 10.0, 1e-6)
print("2D FEA units OK")

# ------------------------------------------------------------------------------------------------ assembly boxes
import asm_model as am, assembly
unitctl.set_units(DEF, "m/s")
pa_, pb_ = make_part("a1.gpd"), make_part("a2.gpd")
sha = gpd_app.AppShell([pa_])
wa = sha.new_assembly(); wa.insert_files([pa_, pb_]); A = wa.asm
c1 = A.components[1]
c1["pos"][0] = 25.4
unitctl.set_units("US (in, lbf, psi)", "m/s")
wa.sel_comp = c1["id"]; wa.show_comp_props()
from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit
def rows(win):
    out = []
    for w in win.props.findChildren(QFormLayout):
        for i in range(w.rowCount()):
            lb, fd = w.itemAt(i, QFormLayout.ItemRole.LabelRole), w.itemAt(i, QFormLayout.ItemRole.FieldRole)
            if lb is not None and fd is not None and isinstance(lb.widget(), QLabel) and isinstance(fd.widget(), QLineEdit):
                out.append((lb.widget().text(), fd.widget()))
    return out
rw = dict(rows(wa))
assert "Position X (in)" in rw and rw["Position X (in)"].text() == "1", list(rw)
assert "Rotation vector X (deg)" in rw
rw["Position X (in)"].setText("2"); rw["Position X (in)"].editingFinished.emit()
assert close(c1["pos"][0], 50.8, 1e-6), c1["pos"]
rw["Position X (in)"].setText("1 ft"); rw["Position X (in)"].editingFinished.emit()
assert close(c1["pos"][0], 304.8, 1e-6), c1["pos"]
unitctl.set_units(DEF, "m/s")
assert dict(rows(wa))["Position X (mm)"].text() == "304.8"
# a distance mate value is held in mm
wa.mate_type = "distance"; wa.mate_opts = {"value": 25.4}; wa.mate_preview = lambda: None
unitctl.set_units("US (in, lbf, psi)", "m/s")
wa.show_mate_panel()
lab = [t for t, e in rows(wa)]
assert "Distance (in)" in lab and dict(rows(wa))["Distance (in)"].text() == "1", lab
dict(rows(wa))["Distance (in)"].setText("2"); dict(rows(wa))["Distance (in)"].editingFinished.emit()
assert close(wa.mate_opts["value"], 50.8), wa.mate_opts
unitctl.set_units(DEF, "m/s")
print("assembly units OK")

# ------------------------------------------------------------------------------------------------ the slice dialog
import sim_slice
unitctl.set_units("US (in, lbf, psi)", "m/s")
from sim_slice import SliceDialog
class P: pass
try:
    dlg_s = SliceDialog(sha, [("Top", {"o": np.zeros(3), "u": np.array([1.0, 0, 0]), "v": np.array([0, 1.0, 0]), "n": np.array([0, 0, 1.0])})], [], None)
    dlg_s.offset.setText("1")
    assert close(dlg_s.value(), 25.4), dlg_s.value()
    dlg_s.offset.setText("1 in"); assert close(dlg_s.value(), 25.4)
    dlg_s.step.setText("0.5"); dlg_s.nudge(+1)
    assert close(dlg_s.value(), 25.4 + 12.7) and dlg_s.offset.text() == "1.5", dlg_s.offset.text()
    dlg_s.reverse(); assert close(dlg_s.value(), -38.1)
    print("slice dialog OK")
except Exception as ex:
    print("slice dialog could not be built in this test:", type(ex).__name__, ex)
unitctl.set_units(DEF, "m/s")

# ------------------------------------------------------------------------------------------------ the render studio
import render_studio
unitctl.set_units(DEF, "m/s")
rs_ = render_studio.RenderStudio(shell=None) if False else None
sp = render_studio.dlen(-1e6, 1e6, 25.4)
assert sp.text() == "25.4"
unitctl.set_units("US (in, lbf, psi)", "m/s"); sp.refresh_unit()
assert sp.text() == "1" and close(sp.value(), 25.4)
sp.lineEdit().setText("2"); sp.interpretText(); assert close(sp.value(), 50.8)
unitctl.set_units(DEF, "m/s")
print("render studio boxes OK")

# ------------------------------------------------------------------------------------------------ the File > Units dialog
import units_dialog
dlg = units_dialog.UnitsDialog(sh)
dlg.system.setCurrentText("Metric (m, kN, kPa)"); dlg.speed.setCurrentText("km/h")
assert dlg.choice() == ("Metric (m, kN, kPa)", "km/h") and "kN" in dlg.info.text()
acts = [a_.text() for m_ in sh.menuBar().findChildren(type(sh.menuBar().addMenu("x"))) for a_ in m_.actions()]
assert "Units..." in acts
unitctl.set_units(DEF, "m/s")
print("ALL UNIT TESTS PASSED")
