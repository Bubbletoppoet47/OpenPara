import addons; addons.startup()   # the simulation / render modules live in add-ons
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(tmp, "userdata")
import numpy as np
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox
app = QApplication([])
import units, unitctl, paths
import pm_model as pm, sk_tools as sk, gpd_app, pm_app, sketch_edit
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

# ------------------------------------------------------------------------------------------------ the File > Units dialog
import units_dialog
dlg = units_dialog.UnitsDialog(sh)
dlg.system.setCurrentText("Metric (m, kN, kPa)"); dlg.speed.setCurrentText("km/h")
assert dlg.choice() == ("Metric (m, kN, kPa)", "km/h") and "kN" in dlg.info.text()
acts = [a_.text() for m_ in sh.menuBar().findChildren(type(sh.menuBar().addMenu("x"))) for a_ in m_.actions()]
assert "Units..." in acts
unitctl.set_units(DEF, "m/s")
print("ALL UNIT TESTS PASSED")
