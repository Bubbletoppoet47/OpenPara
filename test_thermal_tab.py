"""The 2D Thermal tab (thermal_tab.py, with the Simulation window around it): registration and manifest, conditions typed in the unit family (metric degC / US
degF) and stored in SI, a steady bar against its closed form, a fin through the flat faces, heat generation, regions with their own material, radiation,
a transient plate against lumped cooling and its pictures (slider, global colour range, animation frames), probes and the node probe, splitting and merging
edges (conditions and heat generation follow), saving and reopening (the pickle whitelist), unit changes (convert and relabel), the study adapter, and
the project folder (.gph) through the Simulation window with the material of the part."""
import json
import math
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
TH = os.path.join(HERE, "dev_addons", "thermal2d")
sys.path[:0] = [HERE, SIM, TH, os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

import sketcher_core as sc
import physics_store as pstore
import sim_project as sp
import sim_tab
import unitctl
import units
import thermal_fem as tfem
import thermal_mat as tmat
import thermal_tab as tt
import thermal_units as tu

K0 = 273.15
MM = "Metric (mm, kg, N, s, MPa)"
INCH = "US (in, lbf, psi)"
T_ = tempfile.mkdtemp(prefix="opara_th_")


def close(a, b, rel=1e-6, ab=0.0):
    return abs(a - b) <= rel * max(abs(a), abs(b)) + ab


def host():
    h = sim_tab.SimHost.__new__(sim_tab.SimHost)
    h.doc = None
    h.m = sim_tab._HostModel()
    h._restoring = False
    h.status = lambda t: None
    h.sim = None
    h.sketch_list = lambda: []
    return h


def new_tab(unit=None, H=None):
    h = H or host()
    if unit:
        unitctl.set_units(unit, notify=False, persist=False)         # the program's unit system (File > Units)
    t = tt.ThermalTab(h)
    t.run_task = lambda title, fn: run_now(t, title, fn)
    return t


def run_now(tab, title, fn):
    """What PhysicsTab.run_task does, without the window and the thread: a message for the user is shown, a stopped run is 'cancelled'."""
    try:
        return "ok", fn(lambda *a, **k: None, lambda: False)
    except (tt.pg.Cancelled, tt.pf.Cancelled):
        return "cancelled", None
    except (tt.pg.GeometryError, tt.pf.ModelError) as ex:
        QMessageBox.warning(tab, title, str(ex))
        return "user", str(ex)


def bar(W=100.0, Hh=20.0, unit=None):
    m = sc.Model()
    if unit:
        m.unit_system = unit
    p = [m.add_point(*c) for c in ((0, 0), (W, 0), (W, Hh), (0, Hh))]
    ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]       # 0 bottom, 1 right, 2 top, 3 left
    return m, p, ls


ASKED = []


def answer(*vals):
    """The next input box (ask_values) returns these numbers."""
    def f(parent, title, note, labels, defaults):
        ASKED.append({"title": title, "labels": list(labels), "defaults": list(defaults)})
        return list(vals)
    tt.ask_values = f


def add(t, fn, sel, *vals):
    t.canvas.sel = list(sel)
    answer(*vals)
    getattr(t, fn)()


def flow(res, name):
    return next(f["Q"] for f in res["flows"] if f["name"] == name)


def mesh_solve(t, h):
    t.e_h.setText(str(h))
    t.run_mesh()
    assert t.mesh is not None, MSGS
    t.run_solve()
    assert t.result is not None, MSGS
    return t.result


# ================================================================================================================ 1. registration, manifest
mf = json.load(open(os.path.join(TH, "addon.json")))
assert mf["status"] == "workshopping" and mf["needs"] == ["simulation"] and mf["extension"] == "thermal_ext"
tab_spec = mf["tabs"][0]
assert tab_spec["kind"] == "thermal" and tab_spec["project_folder"] == {"marker": "simulation.json", "format": "openpara-sim-thermal"}
assert callable(getattr(tt, tab_spec["factory"])) and tab_spec["module"] == "thermal_tab"
import thermal_ext
thermal_ext.register(None)                              # at start-up: the folder kind and the converter, without Qt tabs
assert sp.EXT["thermal"] == ".gph" and sp.LABEL["thermal"] == "2D Thermal" and "thermal" in pstore.STATE_CONVERTERS
assert "thermal" not in sim_tab.KINDS or sim_tab.KINDS["thermal"][1] is tt.ThermalTab
tt.ensure_registered()
tt.ensure_registered()                                  # twice is harmless
assert sim_tab.KINDS["thermal"] == ("2D Thermal", tt.ThermalTab)
assert sp.kind_of_folder(sp.create(os.path.join(T_, "empty.gph"), "thermal") and os.path.join(T_, "empty.gph")) == "thermal"
print("1 ok: registration")

# ================================================================================================================ 2. steady bar, metric
t = new_tab(MM)
m, p, ls = bar()
t.set_model(m, "bar")
assert t.family().us is False and t.lscale() == 1e-3 and "°C" in t.lbl_T0.text() and "W/(m K)" in t.lbl_k.text()
assert t.mat_combo.currentData() == tmat.DEFAULT and close(float(t.e_k.text()), 167.0) and close(float(t.e_rho.text()), 2700.0)
add(t, "add_temperature", [("ln", ls[3])], 100.0)
assert ASKED[-1]["labels"] == ["Temperature (°C)"], ASKED[-1]
assert close(t.supports[0]["T"], 373.15) and t.supports[0]["kind"] == "temp"
add(t, "add_conv", [("ln", ls[1])], 25.0, 20.0)
assert ASKED[-1]["labels"][0].startswith("Convection coefficient h (W/(m2 K))") and ASKED[-1]["labels"][1] == "Fluid temperature (°C)"
assert t.loads[0]["kind"] == "conv" and close(t.loads[0]["h"], 25.0) and close(t.loads[0]["Tinf"], 293.15)
rows = [[t.cond_table.item(r, c).text() for c in range(4)] for r in range(t.cond_table.rowCount())]
assert rows[0][0] == "Temperature 1" and rows[0][1].startswith("Temperature (°C)") and rows[0][3] == "100", rows
assert rows[1][0] == "Convection 1" and rows[1][3] == "25, 20", rows
t.e_t.setText("1")
res = mesh_solve(t, 5)
A = 0.02 * 0.001
Q = (373.15 - 293.15) / (0.1 / (167.0 * A) + 1.0 / (25.0 * A))
assert close(flow(res, "Temperature 1"), Q, 1e-4) and close(flow(res, "Convection 1"), -Q, 1e-4), (flow(res, "Temperature 1"), Q)
assert close(res["Tmin"], 293.15 + Q / (25.0 * A), 1e-6) and close(res["Tmax"], 373.15, 1e-9)
b = res["balance"]
assert b["relative_error"] < 1e-9 and close(b["in"], Q, 1e-4) and close(b["out"], Q, 1e-4) and abs(b["stored"]) == 0.0
assert close(float(np.mean(res["qmag"])), Q / A, 2e-3), (np.mean(res["qmag"]), Q / A)
html = t.res_lbl.text()
assert "Highest temperature" in html and "100" in html and "Heat balance" in html and "Heat through each condition" in html and "°C" in html
assert "CHECK" not in html and "OK" in html
off = dict(res, balance=dict(res["balance"], relative_error=3e-2))
assert "CHECK" in t.report_html(off), "a steady balance that is off by 3 % is flagged"
for key in ("T", "q", "qx", "qy"):                      # every field can be drawn, in the family's units
    vals, kind, lo, hi, k = t.field_arrays(key, None)
    assert k is None and lo <= vals.min() + 1e-9 and hi >= vals.max() - 1e-9
    t.field.setCurrentIndex(t.field.findData(key))
    assert t.canvas.field == key and not t.canvas.grab().isNull()
vals, kind, lo, hi, k = t.field_arrays("T", None)
assert kind == "nodal" and close(hi, 100.0, 1e-9) and close(lo, Q / (25.0 * A) + 20.0, 1e-6)
t.field.setCurrentIndex(0)
assert not t.canvas.grab().isNull()
assert t.time_box.isHidden() and t.frame_count() == 0 and t.frame_of(None) is None and t.time_text(None) is None
# a heat flux into the bar's right side instead of the convection: Q = q * A_edge
t2 = new_tab(MM)
m2, p2, ls2 = bar()
t2.set_model(m2, "bar")
add(t2, "add_temperature", [("ln", ls2[3])], 20.0)
add(t2, "add_flux", [("ln", ls2[1])], 5000.0)
assert ASKED[-1]["labels"] == ["Heat flux (W/m2)"] and close(t2.loads[0]["q"], 5000.0)
r2 = mesh_solve(t2, 5)
assert close(flow(r2, "Heat flux 1"), 5000.0 * A, 1e-6) and close(flow(r2, "Temperature 1"), -5000.0 * A, 1e-6)
assert close(r2["Tmax"] - 293.15, 5000.0 * 0.1 / 167.0, 1e-6)           # q L / k
# a heat flow at a point
t3 = new_tab(MM)
m3, p3, ls3 = bar()
t3.set_model(m3, "bar")
add(t3, "add_temperature", [("ln", ls3[3])], 20.0)
add(t3, "add_power", [("pt", p3[1]), ("pt", p3[2])], 0.5)
assert ASKED[-1]["labels"] == ["Heat flow (W)"] and close(t3.loads[0]["P"], 0.5)
r3 = mesh_solve(t3, 5)
assert close(flow(r3, "Heat flow 1"), 1.0, 1e-9) and abs(flow(r3, "Temperature 1") + 1.0) < 1e-6 and r3["balance"]["relative_error"] < 1e-9
print("2 ok: steady bar, flux, heat flow at points")

# ================================================================================================================ 3. the table is editable, in the family's units
t.cond_table.item(0, 3).setText("150")
app.processEvents()
assert close(t.supports[0]["T"], 423.15) and t.result is None and t.canvas.field is None, "a changed value clears the result"
assert t.set_condition_value(1, "10; 30") and close(t.loads[0]["h"], 10.0) and close(t.loads[0]["Tinf"], 303.15)
for bad in ("abc", "10", "-5, 20", "10, -300"):                    # not understood: nothing changes
    before = json.dumps(t.loads, sort_keys=True, default=str)
    assert t.set_condition_value(1, bad) is False and json.dumps(t.loads, sort_keys=True, default=str) == before, bad
app.processEvents()
assert t.cond_table.item(1, 3).text() == "10, 30", "the table shows the value again"
assert t.set_condition_value(0, "-40") and close(t.supports[0]["T"], 233.15)
assert t.set_condition_value(0, "-300") is False and close(t.supports[0]["T"], 233.15)
add(t, "add_rad", [("ln", ls[0])], 0.8, 25.0)
assert t.loads[1]["kind"] == "rad" and close(t.loads[1]["eps"], 0.8) and close(t.loads[1]["Ts"], 298.15)
assert t.set_condition_value(2, "1.5, 20") is False and t.set_condition_value(2, "0.5, 50") and close(t.loads[1]["Ts"], 323.15)
t.rename_condition(2, "Bottom radiator")
assert t.cond_name(False, 1) == "Bottom radiator"
t.cond_table.setCurrentCell(2, 0)
t.remove_condition()
assert len(t.loads) == 1 and len(t.supports) == 1
# nothing selected: a message, no condition
n = len(t.supports)
t.canvas.sel = []
answer(10.0)
t.add_temperature()
assert len(t.supports) == n and MSGS[-1].startswith("Select")
# an impossible temperature is refused
add(t, "add_temperature", [("ln", ls[2])], -300.0)
assert len(t.supports) == n and "absolute zero" in MSGS[-1]
add(t, "add_conv", [("ln", ls[2])], -1.0, 20.0)
assert len(t.loads) == 1
add(t, "add_rad", [("ln", ls[2])], 1.5, 20.0)
assert len(t.loads) == 1
print("3 ok: the table and the input boxes")

# ================================================================================================================ 4. US family
tu_ = new_tab(INCH)
mu, pu, lu = bar(4.0, 1.0, INCH)                       # a 4 in x 1 in bar
tu_.set_model(mu, "bar")
fam = tu_.family()
assert fam.us and "°F" in tu_.lbl_T0.text() and "Btu/(hr ft F)" in tu_.lbl_k.text() and "(in)" in tu_.lbl_t.text()
assert close(float(tu_.e_k.text()), 167.0 / 1.730734666, 1e-5), tu_.e_k.text()
add(tu_, "add_temperature", [("ln", lu[3])], 212.0)
assert close(tu_.supports[0]["T"], 373.15, 1e-9) and ASKED[-1]["labels"] == ["Temperature (°F)"]
add(tu_, "add_conv", [("ln", lu[1])], 4.4, 68.0)
assert close(tu_.loads[0]["h"], 4.4 * 5.678263341, 1e-9) and close(tu_.loads[0]["Tinf"], 293.15, 1e-9)
assert tu_.cond_table.item(0, 3).text() == "212" and tu_.cond_table.item(1, 3).text() == "4.4, 68", [tu_.cond_table.item(r, 3).text() for r in range(2)]
tu_.e_t.setText("0.04")
tu_.e_h.setText("0.2")
tu_.run_mesh()
tu_.run_solve()
ru = tu_.result
Lm, Am = 4 * 0.0254, 0.0254 * 0.04 * 0.0254
Qu = (373.15 - 293.15) / (Lm / (167.0 * Am) + 1.0 / (tu_.loads[0]["h"] * Am))
assert close(flow(ru, "Temperature 1"), Qu, 1e-4), (flow(ru, "Temperature 1"), Qu)
assert "°F" in tu_.res_lbl.text() and "Btu/hr" in tu_.res_lbl.text() and "212" in tu_.res_lbl.text()
vals, kind, lo, hi, k = tu_.field_arrays("T", None)
assert close(hi, 212.0, 1e-9) and close(lo, fam.from_si("T", ru["Tmin"]), 1e-9)
tu_.cb_plate.setChecked(True)
for w_, v_ in ((tu_.e_hplate, "2"), (tu_.e_Tamb, "68"), (tu_.e_eps_plate, "0.5"), (tu_.e_Tsur, "32")):
    w_.setText(v_)
pl = tu_.read_setup(need_mesh=False)["plate"]
assert close(pl["h"], 2 * 5.678263341, 1e-9) and close(pl["Tinf"], 293.15, 1e-9) and close(pl["Ts"], 273.15, 1e-9) and pl["eps"] == 0.5, pl
tu_.cb_plate.setChecked(False)
assert "plate" not in tu_.read_setup(need_mesh=False)
print("3b ok: US family")

# ================================================================================================================ 5. a fin through the flat faces
tf_ = new_tab(MM)
m5, p5, ls5 = bar()
tf_.set_model(m5, "fin")
tf_.e_t.setText("1")
add(tf_, "add_temperature", [("ln", ls5[3])], 100.0)
tf_.cb_plate.setChecked(True)
assert not tf_.plate_box.isHidden()
for w, v in ((tf_.e_hplate, "50"), (tf_.e_Tamb, "20"), (tf_.e_eps_plate, "0"), (tf_.e_Tsur, "20")):
    w.setText(v)
r5 = mesh_solve(tf_, 4)
kk, th_, hh, L5 = 167.0, 0.001, 50.0, 0.1
mm_ = math.sqrt(2 * hh / (kk * th_))
Qfin = kk * th_ * 0.02 * mm_ * 80.0 * math.tanh(mm_ * L5)       # insulated tip
assert close(flow(r5, "Temperature 1"), Qfin, 5e-3), (flow(r5, "Temperature 1"), Qfin)
b5 = r5["balance"]
assert b5["relative_error"] < 1e-9 and b5["face_conv"] > 0 and close(b5["face_conv"], Qfin, 5e-3) and b5["face_rad"] == 0.0
assert "flat faces: convection" in tf_.res_lbl.text()
# radiation from the flat faces too: the loss grows and the balance still closes (Newton)
tf_.e_eps_plate.setText("0.9")
tf_.run_solve()
b5b = tf_.result["balance"]
assert b5b["face_rad"] > 0 and b5b["relative_error"] < 1e-8 and tf_.result["newton"]["converged"] and tf_.result["newton"]["iterations"] >= 2
assert flow(tf_.result, "Temperature 1") > Qfin
assert "Newton" in tf_.res_lbl.text()
bad = tf_.e_eps_plate.text()
tf_.e_eps_plate.setText("1.5")
try:
    tf_.read_setup()
    raise SystemExit("an emissivity above 1 must be refused")
except tt.pf.ModelError as ex:
    assert "between 0 and 1" in str(ex)
tf_.e_eps_plate.setText("x")
try:
    tf_.read_setup()
    raise SystemExit("not a number must be refused")
except tt.pf.ModelError:
    pass
tf_.e_eps_plate.setText(bad)
print("5 ok: fin and radiation from the faces")

# ================================================================================================================ 6. heat generation, regions with their own material
tg = new_tab(MM)
m6, p6, ls6 = bar()
tg.set_model(m6, "gen")
tg.e_t.setText("1")
add(tg, "add_temperature", [("ln", ls6[3]), ("ln", ls6[1])], 20.0)
tg.regions.setCurrentRow(0)
assert tg.reg_box.isEnabled() and "Heat generation (W/m3)" in tg.lbl_qv.text()
tg.e_qv.setText("1e6")
tg.region_q_edited()
assert close(tg.region_q[0], 1e6) and "[heat generation]" in tg.regions.item(0).text()
r6 = mesh_solve(tg, 4)
assert close(r6["Tmax"] - 293.15, 1e6 * 0.1 ** 2 / (8 * 167.0), 5e-3), r6["Tmax"] - 293.15
assert close(r6["balance"]["generation"], 1e6 * 0.1 * 0.02 * 0.001, 1e-9) and r6["balance"]["relative_error"] < 1e-9
assert close(flow(r6, "Temperature 1"), -2.0, 1e-6) and "generated inside" in tg.res_lbl.text()
tg.e_qv.setText("0")
tg.region_q_edited()
assert tg.region_q == {} and tg.result is None
tg.e_qv.setText("abc")
tg.region_q_edited()
assert tg.region_q == {} and tg.e_qv.text() == "0"
# two regions side by side, a different material each: series conduction
m7 = sc.Model()
pp = [m7.add_point(*c) for c in ((0, 0), (60, 0), (100, 0), (100, 20), (60, 20), (0, 20))]
l7 = [m7.add_line(pp[i], pp[(i + 1) % 6]) for i in range(6)] + [m7.add_line(pp[1], pp[4])]
tl = new_tab(MM)
tl.set_model(m7, "layers")
assert len(tl.geom["faces"]) == 2
tl.e_t.setText("1")
add(tl, "add_temperature", [("ln", l7[5])], 100.0)
add(tl, "add_temperature", [("ln", l7[2])], 20.0)
left = next(i for i, f in enumerate(tl.geom["faces"]) if f["centroid"][0] < 60)
right = 1 - left
fl, fr_ = tl.geom["faces"][left]["id"], tl.geom["faces"][right]["id"]
# every region has a material from the start (the default one), all set in Material and analysis
assert tl.region_mats == {fl: {"name": tmat.DEFAULT, "k": 167.0, "rho": 2700.0, "cp": 896.0}, fr_: {"name": tmat.DEFAULT, "k": 167.0, "rho": 2700.0, "cp": 896.0}}
assert not hasattr(tl, "reg_mat_combo") and tl.mat_table.rowCount() == 2 and tl.mat_table.item(left, 1).text() == tmat.DEFAULT
tl.mat_table.setCurrentCell(left, 0)
j = tl.mat_combo.findData("Copper")
assert j > 0
tl.mat_combo.setCurrentIndex(j)
assert tl.region_mats[fl]["k"] == 401.0 and tl.region_mats[fr_]["k"] == 167.0
assert tl.mat_table.item(left, 1).text() == "Copper" and "Copper" not in tl.regions.item(left).text(), "the material is shown in Material and analysis only"
assert tl.read_setup(need_mesh=False)["region_mats"] == {fl: {"k": 401.0, "rho": 8960.0, "cp": 385.0}, fr_: {"k": 167.0, "rho": 2700.0, "cp": 896.0}}
r7 = mesh_solve(tl, 4)
R1, R2 = 0.06 / (401.0 * A), 0.04 / (167.0 * A)
assert close(flow(r7, "Temperature 1"), 80.0 / (R1 + R2), 1e-4), (flow(r7, "Temperature 1"), 80.0 / (R1 + R2))
tl.mat_table.setCurrentCell(right, 0)                       # selecting the other region shows its material in the editor
assert tl.mat_combo.currentData() == tmat.DEFAULT and close(float(tl.e_k.text()), 167.0)
tl.mat_table.setCurrentCell(left, 0)
assert tl.mat_combo.currentData() == "Copper" and close(float(tl.e_k.text()), 401.0)
tl.material_for_all()                                       # 'Use for all regions'
assert tl.region_mats[fl] == tl.region_mats[fr_] and tl.region_mats[fr_]["name"] == "Copper" and tl.result is None
tl.mat_combo.setCurrentIndex(tl.mat_combo.findData(tmat.DEFAULT))
assert tl.region_mats[fl]["name"] == tmat.DEFAULT and tl.region_mats[fr_]["name"] == "Copper" and tl.result is None
print("6 ok: heat generation and regions")

# ================================================================================================================ 7. radiation conditions
tr = new_tab(MM)
m8, p8, ls8 = bar()
tr.set_model(m8, "rad")
tr.mat_combo.setCurrentIndex(tr.mat_combo.findData("Copper"))
tr.material_picked()
tr.e_t.setText("1")
add(tr, "add_temperature", [("ln", ls8[3])], 326.85)                    # 600 K
add(tr, "add_rad", [("ln", ls8[1])], 0.8, -153.15)                       # surroundings at 120 K
r8 = mesh_solve(tr, 5)
sig = 5.670374419e-8
Qr = 0.8 * sig * A * (r8["T"][np.isclose(r8["mesh"]["nodes"][:, 0], 100.0)].mean() ** 4 - 120.0 ** 4)
assert close(-flow(r8, "Radiation 1"), Qr, 2e-3) and r8["newton"]["converged"] and r8["newton"]["iterations"] >= 2
assert close(flow(r8, "Temperature 1"), -flow(r8, "Radiation 1"), 1e-6) and r8["balance"]["relative_error"] < 1e-8
assert close(600.0 - r8["Tmin"], -flow(r8, "Radiation 1") * 0.1 / (401.0 * A), 2e-3) and "Newton" in tr.res_lbl.text() and "converged" in tr.res_lbl.text()
# nothing to settle on: refused with a reason, no crash
tn = new_tab(MM)
m9, p9, ls9 = bar()
tn.set_model(m9, "none")
add(tn, "add_flux", [("ln", ls9[1])], 100.0)
tn.e_h.setText("5")
tn.run_mesh()
MSGS.clear()
tn.run_solve()
assert tn.result is None and MSGS and ("temperature" in MSGS[-1].lower() or "settle" in MSGS[-1].lower()), MSGS
print("7 ok: radiation condition, refused singular problem")

# ================================================================================================================ 8. transient plate: lumped cooling, the slider, the colour range
def lumped_tab(method=0, tend="300", steps="300", nfr="31", tcombo="s"):
    tl_ = new_tab(MM)
    m_, p_, l_ = bar()
    tl_.set_model(m_, "lump")
    tl_.e_t.setText("1")
    tl_.cb_plate.setChecked(True)
    for w, v in ((tl_.e_hplate, "20"), (tl_.e_Tamb, "20"), (tl_.e_eps_plate, "0"), (tl_.e_Tsur, "20")):
        w.setText(v)
    tl_.analysis_combo.setCurrentIndex(1)
    assert not tl_.tr_box.isHidden()
    tl_.e_T0.setText("100")
    tl_.e_tend.setText(tend)
    tl_.time_combo.setCurrentText(tcombo)
    tl_.e_steps.setText(steps)
    tl_.e_nframes.setText(nfr)
    tl_.method_combo.setCurrentIndex(method)
    return tl_


TAU = 2700.0 * 896.0 * 0.001 / (2 * 20.0)
exact = lambda ts: 293.15 + 80.0 * np.exp(-np.asarray(ts) / TAU)
tr1 = lumped_tab()
s8 = tr1.read_setup(need_mesh=False)
assert s8["analysis"] == "transient" and close(s8["T0"], 373.15) and s8["t_end"] == 300.0 and s8["steps"] == 300 and s8["theta"] == 0.5 and s8["frames"] == 31
assert s8["plate"] == {"h": 20.0, "eps": 0.0, "Tinf": 293.15, "Ts": 293.15}
r8t = mesh_solve(tr1, 10)
assert r8t["analysis"] == "transient" and r8t["frames"].shape == (31, len(r8t["T"])) and r8t["times"][0] == 0 and close(r8t["times"][-1], 300.0, 1e-12)
assert np.allclose(r8t["frames"][0], 373.15)
for k in (1, 7, 15, 30):
    assert np.max(np.abs(r8t["frames"][k] - exact(r8t["times"][k]))) < 2e-4 * 80, (k, np.max(np.abs(r8t["frames"][k] - exact(r8t["times"][k]))))
assert np.allclose(r8t["T"], r8t["frames"][-1])
assert float(np.max(r8t["qmag"])) < 1e-4, "uniform temperature: no heat flux"
b8 = r8t["balance"]
assert b8["relative_error"] < 1e-2 and close(b8["stored"], -b8["face_conv"], 2e-2), b8
html = tr1.res_lbl.text()
assert "Transient: 300 steps" in html and "Crank-Nicolson" in html and "(at the end)" in html and "Stored (heating up)" in html
off = dict(r8t, balance=dict(r8t["balance"], relative_error=3e-2))
assert "CHECK" not in tr1.report_html(off) and "CHECK" in tr1.report_html(dict(r8t, balance=dict(r8t["balance"], relative_error=0.2))), "Crank-Nicolson is allowed 5 %"
# the time controls
assert tr1.frame_count() == 31 and not tr1.time_box.isHidden() and tr1.time_slider.maximum() == 30 and tr1.time_slider.value() == 30
assert tr1.cb_anim.isEnabled() and tr1.time_lbl.text() == "t = 300 s", tr1.time_lbl.text()
tr1.field.setCurrentIndex(tr1.field.findData("T"))
tok = tr1.view_token
tr1.time_slider.setValue(10)
assert tr1.frame_idx == 10 and tr1.view_token > tok and tr1.time_lbl.text() == "t = 100 s" and tr1.frame_of(None) == 10
v10, kind, lo, hi, k = tr1.field_arrays("T", None)
assert k == 10 and np.allclose(v10, r8t["frames"][10] - K0)
lo0, hi0 = tr1.field_arrays("T", 0.0)[2:4]
lo1, hi1 = tr1.field_arrays("T", 1.0)[2:4]
assert (lo0, hi0) == (lo1, hi1) == (lo, hi) and close(hi, 100.0, 1e-9) and close(lo, exact(300.0) - K0, 1e-4), "one colour scale for the whole run"
assert [tr1.frame_of(x) for x in (0.0, 0.5, 1.0, -1.0, 2.0)] == [0, 15, 30, 0, 30]
tr1.canvas.resize(500, 300)
tr1.canvas.fit()
img_a, img_b = tr1.canvas.render_picture(True, 0.0).toImage(), tr1.canvas.render_picture(True, 1.0).toImage()
assert not img_a.isNull() and img_a != img_b, "the first and the last picture of the run differ"
for key in ("q", "qx", "qy"):
    assert tr1.field_arrays(key, None)[4] == 10
# the animation: all the frames are drawn first, then played
tr1.cb_anim.setChecked(True)
assert not tr1.anim_box.isHidden()
tr1.e_frames.setText("5")
assert tr1.render_frames(5) and len(tr1.canvas.anim_frames) == 5 and tr1.canvas.anim_frames[0].toImage() != tr1.canvas.anim_frames[4].toImage()
tr1.canvas.anim_idx = 2
assert not tr1.canvas.grab().isNull()
tr1.anim_play()
assert tr1.anim_timer.isActive()
tr1.anim_step()
tr1.anim_stop()
assert not tr1.anim_timer.isActive()
tr1.canvas.invalidate()
assert tr1.canvas.anim_frames is None, "a changed view drops the drawn frames"
tr1.cb_anim.setChecked(False)
# backward Euler, another time unit, bad inputs
tr2 = lumped_tab(method=1, tend="5", tcombo="min", steps="300")
assert tr2.read_setup(need_mesh=False)["t_end"] == 300.0 and tr2.read_setup(need_mesh=False)["theta"] == 1.0
r8b = mesh_solve(tr2, 10)
assert np.max(np.abs(r8b["frames"][-1] - exact(300.0))) < 0.02 * 80 and "backward Euler" in tr2.res_lbl.text() and tr2.time_lbl.text() == "t = 5 min", tr2.time_lbl.text()
for box, bad in (("e_steps", "0"), ("e_steps", "abc"), ("e_steps", "60000"), ("e_nframes", "1"), ("e_tend", "0"), ("e_tend", "x"), ("e_T0", "-300")):
    tx = lumped_tab()
    getattr(tx, box).setText(bad)
    try:
        tx.read_setup(need_mesh=False)
        raise SystemExit(f"{box} = {bad} must be refused")
    except tt.pf.ModelError:
        pass
# a steady result has nothing to animate
assert not t.cb_anim.isEnabled() and t.time_box.isHidden()
tfx = new_tab(MM)
mfx, pfx, lfx = bar()
tfx.set_model(mfx, "front")
tfx.e_t.setText("1")
add(tfx, "add_temperature", [("ln", lfx[3])], 100.0)
tfx.analysis_combo.setCurrentIndex(1)
for w_, v_ in ((tfx.e_T0, "20"), (tfx.e_tend, "40"), (tfx.e_steps, "80"), (tfx.e_nframes, "9")):
    w_.setText(v_)
rfx = mesh_solve(tfx, 5)
assert tfx.frame_count() == 9 and abs(np.diff(rfx["times"]) - 5.0).max() < 1e-9
for k_ in range(9):
    tfx.time_slider.setValue(k_)
    fx_ = tfx.flux_for(k_)
    assert np.allclose(fx_[2], tfem.flux_of(rfx, rfx["frames"][k_])[2], rtol=0, atol=0)
assert not np.allclose(tfx.flux_for(2)[2], tfx.flux_for(7)[2]), "the flux of different pictures differs (the heat front moves)"
lo_, hi_ = tfx.field_range("q")
assert close(hi_, max(float(tfem.flux_of(rfx, f_)[2].max()) for f_ in rfx["frames"]), 1e-12) and lo_ >= 0.0
assert close(tfx.field_arrays("q", 0.0)[3], tfx.family().from_si("q", hi_)) and close(tfx.field_arrays("q", 1.0)[3], tfx.family().from_si("q", hi_)), "one scale for the run"
lo_, hi_ = tfx.field_range("qx")
assert lo_ < 0.0 < hi_ * 1.0 + 1.0 and hi_ >= max(float(tfem.flux_of(rfx, f_)[0].max()) for f_ in rfx["frames"]) - 1e-9
tfy = new_tab(MM)
mfy, pfy, lfy = bar()
tfy.set_model(mfy, "loaded")
tfy.e_t.setText("1")
add(tfy, "add_temperature", [("ln", lfy[1])], 20.0)
add(tfy, "add_flux", [("ln", lfy[3])], 5000.0)
tfy.analysis_combo.setCurrentIndex(1)
for w_, v_ in ((tfy.e_T0, "20"), (tfy.e_tend, "100"), (tfy.e_steps, "50"), (tfy.e_nframes, "6")):
    w_.setText(v_)
rfy = mesh_solve(tfy, 5)
peak = [float(tfem.flux_of(rfy, f_)[2].max()) for f_ in rfy["frames"]]
assert peak[0] < 1.0 and peak[-1] > 0.6 * 5000.0 and peak == sorted(peak), peak          # nothing flows at first, then the heat moves through the bar
assert close(tfy.field_range("q")[1], peak[-1], 1e-12) and close(tfy.field_arrays("q", 0.0)[3], tfy.family().from_si("q", peak[-1]), 1e-12)
print("8 ok: transient plate, slider, colour range, animation")

# ================================================================================================================ 9. probes and the node probe
tp = new_tab(MM)
mp, pp_, lp = bar()
tp.set_model(mp, "probe")
tp.e_t.setText("1")
add(tp, "add_temperature", [("ln", lp[3])], 100.0)
add(tp, "add_conv", [("ln", lp[1])], 25.0, 20.0)
rp_ = mesh_solve(tp, 5)
tp.add_probe("rect", x0=-1.0, y0=-1.0, x1=101.0, y1=21.0)
tp.add_probe("circle", cx=500.0, cy=500.0, r=5.0)
assert tp.probe_table.rowCount() == 2 and tp.probe_table.item(0, 0).text() == "Probe 1" and tp.probe_table.item(0, 1).text() == "Rectangle"
ps = tfem.probe_stats(rp_, tp.probes)
assert close(ps[0]["avg"], rp_["Tmean"], 1e-9) and close(ps[0]["max"], 373.15, 1e-9) and close(ps[0]["q_avg"], float(np.mean(rp_["qmag"])), 5e-3)
assert ps[1]["avg"] is None
html = tp.res_lbl.text()
assert "Probe regions" in html and "Probe 1" in html and "no element inside" in html and "Average temperature" in html
tp.probe_table.item(0, 0).setText("Whole bar")
app.processEvents()
assert tp.probes[0]["name"] == "Whole bar" and "Whole bar" in tp.res_lbl.text()
tp.probe_table.item(0, 2).setText("0, 0, 50, 20")
app.processEvents()
assert (tp.probes[0]["x1"], tp.probes[0]["y1"]) == (50.0, 20.0)
assert tp.set_probe_geometry(0, "1, 2") is False
tp.probe_table.setCurrentCell(1, 0)
tp.remove_probe()
assert len(tp.probes) == 1 and tp.result is rp_, "a probe never clears the result"
# the probe averages of a transient run are those of the picture shown
tr1.add_probe("rect", x0=-1.0, y0=-1.0, x1=101.0, y1=21.0)
for kk_ in (10, 20):
    tr1.time_slider.setValue(kk_)
    want = tt.R.num(tr1.family().from_si("T", float(np.mean(r8t["frames"][kk_]))), 5)
    assert want in tr1.res_lbl.text() and f"t = {kk_ * 10} s" in tr1.res_lbl.text(), (kk_, want)
assert tt.R.num(tr1.family().from_si("T", float(np.mean(r8t["frames"][10]))), 5) not in tr1.res_lbl.text()
assert "CHECK" in tt.chip_or(False, "x") and "OK" in tt.chip_or(True, "x") and "CHECK" not in tt.chip_or(True, "x")
# the node probe
tp.canvas.resize(600, 400)
tp.canvas.fit()
idx = int(np.argmax(rp_["T"]))
nr = tp.node_results(idx)
assert close(nr["T"], rp_["T"][idx], 1e-12) and nr["t"] is None and nr["n_elems"] > 0 and close(nr["q"], float(np.mean(rp_["qmag"])), 0.02)
from PyQt6.QtCore import QPointF
sp_ = tp.node_screen(idx)
tp.pick_node(sp_)
assert tp.canvas.node_sel == idx and "Temperature" in tp.node_lbl.text() and f"Node {idx}" in tp.node_lbl.text() and "100" in tp.node_lbl.text()
tp.pick_node(QPointF(-500.0, -500.0))
assert tp.canvas.node_sel is None and tp.node_lbl.text() == ""
# and on a frame of a transient run
node = 5
tr1.canvas.node_sel = node
tr1.time_slider.setValue(19)
tr1.time_slider.setValue(20)
nt = tr1.node_results(node)
assert close(nt["T"], r8t["frames"][20][node], 1e-12) and close(nt["t"], r8t["times"][20], 1e-12) and "t = 200 s" in tr1.node_lbl.text()
print("9 ok: probes and the node probe")

# ================================================================================================================ 10. split and merge keep conditions and heat generation
ts = new_tab(MM)
ms, ps_, lsp = bar()
ts.set_model(ms, "split")
ts.e_t.setText("1")
add(ts, "add_temperature", [("ln", lsp[3])], 100.0)
add(ts, "add_conv", [("ln", lsp[1])], 25.0, 20.0)
ts.regions.setCurrentRow(0)
ts.e_qv.setText("2e5")
ts.region_q_edited()
r10a = mesh_solve(ts, 5)
info = ts.apply_split(("ln", lsp[1]), 8.0)
assert ts.mesh is None and ts.result is None and len(ts.loads[0]["targets"]) == 2, ts.loads
assert len(ts.region_q) == 1 and close(list(ts.region_q.values())[0], 2e5), ts.region_q
assert "[heat generation]" in ts.regions.item(0).text()
r10b = mesh_solve(ts, 5)
assert close(flow(r10b, "Convection 1"), flow(r10a, "Convection 1"), 2e-3) and close(flow(r10b, "Temperature 1"), flow(r10a, "Temperature 1"), 2e-3)
assert close(r10b["balance"]["generation"], 2e5 * 0.1 * 0.02 * 0.001, 1e-9)
ts.loads[0]["targets"] = ts.loads[0]["targets"][:1]                         # the condition on only one of the two pieces
MSGS.clear()
assert ts.merge_at(info["pt"]) is None and "only one of the two edges" in ts.status_lbl.text() + " ".join(MSGS)
ts.loads[0]["targets"] = [tuple(x) for x in (("ln", lsp[1]), tuple(info["second"]))]
assert ts.merge_at(info["pt"]) is not None and len(ts.loads[0]["targets"]) == 1 and close(list(ts.region_q.values())[0], 2e5)
assert ts.mesh is None
# a heat flow set on the point itself blocks the merge
ts.apply_split(("ln", lsp[1]), 8.0)
pt_ = ts.canvas.sel[0][1]
add(ts, "add_power", [("pt", pt_)], 1.0)
assert ts.merge_at(pt_) is None and "set on point" in ts.status_lbl.text()
print("10 ok: split and merge")

# ================================================================================================================ 11. saved and restored (the pickle whitelist), probes and regions with it
tv = new_tab(MM)
mv, pv, lv = bar()
tv.set_model(mv, "save")
tv.e_t.setText("2")
add(tv, "add_temperature", [("ln", lv[3])], 100.0)
add(tv, "add_conv", [("ln", lv[1])], 25.0, 20.0)
add(tv, "add_rad", [("ln", lv[0])], 0.6, 30.0)
tv.regions.setCurrentRow(0)
tv.e_qv.setText("3e4")
tv.region_q_edited()
tv.mat_combo.setCurrentIndex(tv.mat_combo.findData("Copper"))
tv.cb_plate.setChecked(True)
tv.e_hplate.setText("12")
tv.analysis_combo.setCurrentIndex(1)
tv.e_T0.setText("30")
tv.e_tend.setText("600")
tv.e_steps.setText("60")
tv.e_nframes.setText("13")
tv.add_probe("rect", x0=-1.0, y0=-1.0, x1=101.0, y1=21.0)
r11 = mesh_solve(tv, 6)
tv.time_slider.setValue(5)
f11 = os.path.join(T_, "state.sim")
assert pstore.save(f11, {"main": tv}) == ["main"]
st = pstore.load(f11)["main"]
tv2 = new_tab(MM)
tv2.import_state(st)
assert json.dumps(tv2.supports, sort_keys=True, default=str) == json.dumps(tv.supports, sort_keys=True, default=str)
assert json.dumps(tv2.loads, sort_keys=True, default=str) == json.dumps(tv.loads, sort_keys=True, default=str)
assert tv2.region_q == tv.region_q and tv2.region_mats == tv.region_mats and tv2.probes == tv.probes
for key in ("T", "frames", "times", "qmag", "k_el"):
    assert np.array_equal(tv2.result[key], tv.result[key]), key
assert tv2.result["balance"] == tv.result["balance"] and tv2.result["flows"] == tv.result["flows"] and np.array_equal(tv2.mesh["nodes"], tv.mesh["nodes"])
assert tv2.frame_idx == 5 and tv2.time_slider.value() == 5 and tv2.time_slider.maximum() == 12 and tv2.time_lbl.text() == tv.time_lbl.text()
assert tv2.analysis_combo.currentIndex() == 1 and not tv2.tr_box.isHidden() and not tv2.plate_box.isHidden() and tv2.e_hplate.text() == "12" and tv2.e_nframes.text() == "13"
assert tv2.field.currentData() == tv.field.currentData() == "T" and tv2.canvas.field == "T" and tv2.res_lbl.text() == tv.res_lbl.text()
assert tv2.read_setup() == tv.read_setup(), "the same problem comes back"
tv2.run_solve()
assert np.allclose(tv2.result["T"], tv.result["T"], rtol=0, atol=1e-9), "solving the restored tab gives the same answer"
assert not tv2.canvas.grab().isNull() and tv2.diagnostics_text().count("\n") > 30
# a tab saved while a mesh is missing / nothing is solved
tv3 = new_tab(MM)
mv3, _, _ = bar()
tv3.set_model(mv3, "bare")
pstore.save(f11, {"main": tv3})
tv4 = new_tab(MM)
tv4.import_state(pstore.load(f11)["main"])
assert tv4.mesh is None and tv4.result is None and tv4.supports == [] and tv4.geom is not None
# another tab's pickle with something that is not allowed is refused (the restricted unpickler)
import pickle
class Evil:
    def __reduce__(self):
        return (os.getcwd, ())
try:
    pstore._loads(pickle.dumps({"x": Evil()}))
    raise SystemExit("the whitelist must refuse it")
except pickle.UnpicklingError:
    pass
print("11 ok: save and restore")

# ================================================================================================================ 12. changing the program's unit system
tc = new_tab(MM)
mc, pc, lc = bar()
tc.set_model(mc, "units")
tc.e_t.setText("2")
add(tc, "add_temperature", [("ln", lc[3])], 100.0)
add(tc, "add_conv", [("ln", lc[1])], 25.0, 20.0)
tc.regions.setCurrentRow(0)
tc.e_qv.setText("1000")
tc.region_q_edited()
tc.add_probe("rect", x0=-1.0, y0=-1.0, x1=101.0, y1=21.0)
r12 = mesh_solve(tc, 5)
sup0, loadc = dict(tc.supports[0]), dict(tc.loads[0])
nodes0 = tc.mesh["nodes"].copy()
unitctl.set_units(INCH, notify=False, persist=False)
note = tc.change_units(MM, INCH, True)
assert tc.unit_name() == INCH and tc.family().us and note == ""
assert close(float(tc.e_t.text()), 2 / 25.4, 1e-9) and close(float(tc.e_k.text()), 167.0 / 1.730734666, 1e-8) and close(float(tc.e_rho.text()), 2700.0 / 16.01846337, 1e-8)
assert close(float(tc.e_h.text()), 5 / 25.4, 1e-9) and close(float(tc.e_cp.text()), 896.0 / 4186.8, 1e-8)
assert tc.supports[0] == sup0 and tc.loads[0] == loadc and close(tc.region_q[0], 1000.0), "the stored conditions are SI: nothing changes"
assert np.allclose(tc.mesh["nodes"], nodes0 / 25.4) and tc.result is not None and np.allclose(tc.result["mesh"]["nodes"], r12["mesh"]["nodes"] / 25.4)
assert close(tc.result["lscale"], 0.0254) and np.array_equal(tc.result["T"], r12["T"])
assert close(tc.probes[0]["x1"], 101.0 / 25.4, 1e-9)
assert tc.cond_table.item(0, 3).text() == "212" and tc.cond_table.item(1, 3).text() == "4.402754592, 68", \
    [tc.cond_table.item(r, 3).text() for r in range(2)]
tc.regions.setCurrentRow(0)
assert close(float(tc.e_qv.text()), 1000.0 / 10.34970717, 1e-7) and "Btu/(hr ft3)" in tc.lbl_qv.text()
vals, kind, lo, hi, k = tc.field_arrays("T", None)
assert close(hi, 212.0, 1e-9) and "°F" in tc.res_lbl.text()
tc.run_solve()
assert close(tc.result["Tmin"], r12["Tmin"], 1e-9) and close(flow(tc.result, "Temperature 1"), flow(r12, "Temperature 1"), 1e-9), "the same physics in inches"
unitctl.set_units(MM, notify=False, persist=False)
tc.change_units(INCH, MM, True)
assert close(float(tc.e_t.text()), 2.0, 1e-9) and close(float(tc.e_k.text()), 167.0, 1e-8) and close(float(tc.e_h.text()), 5.0, 1e-9) and tc.unit_name() == MM
assert close(tc.result["Tmax"], r12["Tmax"], 1e-9) and np.allclose(tc.mesh["nodes"], nodes0)
# a relabel keeps the typed numbers and re-reads the stored ones in the new family; the mesh and result no longer fit
unitctl.set_units(INCH, notify=False, persist=False)
note = tc.change_units(MM, INCH, False)
assert "cleared" in note and tc.mesh is None and tc.result is None and tc.unit_name() == INCH
assert close(float(tc.e_k.text()), 167.0 / 1.730734666, 1e-8) and tc.region_mats[0]["name"] == tmat.DEFAULT and tc.region_mats[0]["k"] == 167.0, \
    "a library material keeps its physical value in a relabel"
assert tc.e_t.text() == "2" and close(tc.supports[0]["T"], tu.family_of(INCH).to_si("T", 100.0), 1e-12)   # the "100" typed is now 100 degF
assert close(tc.loads[0]["h"], 25.0 * 5.678263341, 1e-9) and close(tc.region_q[0], 1000.0 * 10.34970717, 1e-9)
assert close(tc.loads[0]["Tinf"], tu.family_of(INCH).to_si("T", 20.0), 1e-12), "the fluid temperature typed as 20 is now 20 degF"
unitctl.set_units(MM, notify=False, persist=False)
# nothing imported yet: the boxes follow
tb = new_tab(MM)
tb.e_t.setText("1")
unitctl.set_units(INCH, notify=False, persist=False)
tb.convert_input_units(INCH)
assert close(float(tb.e_t.text()), 1 / 25.4, 1e-9) and close(float(tb.e_k.text()), 167.0 / 1.730734666, 1e-8) and "°F" in tb.lbl_T0.text()
unitctl.set_units(MM, notify=False, persist=False)
print("12 ok: unit changes")

# ================================================================================================================ 13. a slice of an assembly: the materials of the parts
tm_ = new_tab(MM)
m13 = sc.Model()
pp13 = [m13.add_point(*c) for c in ((0, 0), (60, 0), (100, 0), (100, 20), (60, 20), (0, 20))]
l13 = [m13.add_line(pp13[i], pp13[(i + 1) % 6]) for i in range(6)] + [m13.add_line(pp13[1], pp13[4])]
tm_.set_model(m13, "slice")
fa, fb = [f["id"] for f in tm_.geom["faces"]]
tm_.sim_apply_regions({fa: 0, fb: 1}, {fa: "Heat sink", fb: "Chip"}, {fa: {"name": "Aluminum 6061", "density": 2700.0}, fb: {"name": "Mystery alloy"}})
assert tm_.region_names == {fa: "Heat sink", fb: "Chip"} and set(tm_.region_mats) == {fa, fb} and tm_.region_mats[fa]["k"] == 167.0
assert tm_.region_mats[fb]["name"] == tmat.DEFAULT and tm_.unset_regions == {fb}, "a part with no thermal values carries the default material, marked"
assert tm_.missing_mats == ["Chip (Mystery alloy)"]
notes = tm_.sim_part_materials({fa: {}, fb: {}}, None)
assert any("Aluminum 6061" in n for n in notes) and any("Mystery alloy" in n and "default material" in n and "Material and analysis" in n for n in notes), notes
tm_.fill_regions()
assert "Heat sink" in tm_.regions.item(0).text() or "Heat sink" in tm_.regions.item(1).text()
rowb = next(r for r, f in enumerate(tm_.geom["faces"]) if f["id"] == fb)
assert "choose a material" in tm_.mat_table.item(rowb, 1).text() and "Chip" in tm_.mat_table.item(rowb, 0).text()
s13 = tm_.read_setup(need_mesh=False)
assert set(s13["region_mats"]) == {fa, fb} and s13["region_mats"][fa] == {"k": 167.0, "rho": 2700.0, "cp": 896.0}
tm_.mat_table.setCurrentCell(rowb, 0)                   # choosing a material for it takes the mark away
tm_.mat_combo.setCurrentIndex(tm_.mat_combo.findData("Copper"))
assert tm_.unset_regions == set() and "choose" not in tm_.mat_table.item(rowb, 1).text() and tm_.region_mats[fb]["k"] == 401.0
# one part: its material fills the tab
tm2 = new_tab(MM)
tm2.set_model(*bar()[:1], "one")
notes = tm2.sim_part_materials(None, {"name": "Copper", "density": 8960.0})
assert any("Copper" in n for n in notes) and close(float(tm2.e_k.text()), 401.0) and tm2.mat_combo.currentData() == "Copper"
assert all(m["name"] == "Copper" for m in tm2.region_mats.values()) and len(tm2.region_mats) == len(tm2.geom["faces"])
notes = tm2.sim_part_materials(None, {"name": "Unobtainium"})
assert any("Unobtainium" in n for n in notes) and close(float(tm2.e_k.text()), 401.0), "an unknown material leaves the boxes alone"
assert tm2.sim_part_materials(None, None) == []
# a model of two regions with one part material: both regions get it, and none stays marked
tm3 = new_tab(MM)
tm3.set_model(m13, "slice")
assert len(tm3.geom["faces"]) == 2
tm3.unset_regions = {tm3.geom["faces"][0]["id"]}
tm3.sim_part_materials(None, {"name": "Copper", "density": 8960.0})
assert [m["name"] for m in tm3.region_mats.values()] == ["Copper", "Copper"] and set(tm3.region_mats) == {f["id"] for f in tm3.geom["faces"]}
assert all(m["k"] == 401.0 for m in tm3.region_mats.values()) and tm3.unset_regions == set()
# the library: a material of your own, by name
n0 = len(tm2.library)
tm2.e_k.setText("12.5")
tm2.set_custom()
import PyQt6.QtWidgets as QW
QW.QInputDialog.getText = staticmethod(lambda *a, **k: ("My ceramic", True))
tm2.add_material()
assert len(tm2.library) == n0 + 1 and tm2.mat_combo.currentData() == "My ceramic" and "My ceramic" in [m["name"] for m in tmat.user_materials()]
assert tmat.find("My ceramic")["k"] == 12.5
assert tm2.region_mats[0]["name"] == "My ceramic" and tm2.region_mats[0]["k"] == 12.5
tm2.delete_material()
assert len(tm2.library) == n0 and tmat.find("My ceramic") is None
assert tm2.region_mats[0]["name"] == "(custom values)" and tm2.region_mats[0]["k"] == 12.5, "the region keeps its numbers when the material is deleted"
print("13 ok: slice materials and the library")

# ================================================================================================================ 14. the study adapter
import study_iface as si
tsd = new_tab(MM)
msd, psd, lsd = bar()
tsd.set_model(msd, "study")
tsd.e_t.setText("1")
ad = tsd.study_adapter()
assert isinstance(ad, si.StudyAdapter) and ad.key == "thermal" and ad.ready() == "The simulation has no conditions and no heat generation yet."
add(tsd, "add_temperature", [("ln", lsd[3])], 100.0)
add(tsd, "add_conv", [("ln", lsd[1])], 25.0, 20.0)
tsd.add_probe("rect", x0=-1.0, y0=-1.0, x1=101.0, y1=21.0)
tsd.e_h.setText("5")
ad = tsd.study_adapter()
assert ad.ready() is None
# any one of a temperature, a load or a heat generation is enough to study
for what in ("temp", "conv", "gen"):
    tw = new_tab(MM)
    mw, pw, lw = bar()
    tw.set_model(mw, "ready")
    assert tw.study_adapter().ready() == "The simulation has no conditions and no heat generation yet."
    if what == "temp":
        add(tw, "add_temperature", [("ln", lw[3])], 100.0)
    elif what == "conv":
        add(tw, "add_conv", [("ln", lw[1])], 25.0, 20.0)
    else:
        tw.region_q[tw.geom["faces"][0]["id"]] = 1e6
    assert tw.study_adapter().ready() is None, what
ps = {d["id"]: d for d in ad.params()}
assert {"thermal.e_k", "thermal.e_t", "thermal.e_h", "thermal.analysis_combo", "thermal.cb_plate", "thermal.sup0.T", "thermal.load0.h", "thermal.load0.Tinf", "thermal.gen0"} <= set(ps), sorted(ps)
assert ps["thermal.sup0.T"]["now"] == "100" and ps["thermal.load0.h"]["now"] == "25" and ps["thermal.load0.Tinf"]["now"] == "20" and ps["thermal.gen0"]["now"] == "0"
assert ps["thermal.cb_plate"]["kind"] == "bool" and ps["thermal.analysis_combo"]["kind"] == "choice" and "(°C)" in ps["thermal.sup0.T"]["label"]
outs = {o["id"]: o for o in ad.outputs()}
assert {"thermal.status", "thermal.Tmax", "thermal.flow0", "thermal.flow1", "thermal.probe0.avg", "thermal.probe0.q", "thermal.tris"} <= set(outs)
assert outs["thermal.Tmax"]["numeric"] and not outs["thermal.status"]["numeric"] and "°C" in outs["thermal.Tmax"]["label"]
before = (tsd.e_t.text(), repr(tsd.supports), repr(tsd.loads), tsd.mesh, tsd.result)
ctx = {}


def run_case(values, adp=None):
    adp = adp or ad
    spec = adp.prepare(values, ctx)
    assert spec["error"] is None, spec["error"]
    case = spec["run"](lambda *a, **k: None, lambda: False)
    assert case["status"].startswith("ok"), case
    return case


Qs = lambda dT, h=25.0, k=167.0: dT / (0.1 / (k * A) + 1.0 / (h * A))
c1 = run_case({})
o1 = ad.case_outputs(c1, ["thermal.Tmax", "thermal.Tmin", "thermal.flow0", "thermal.flow1", "thermal.balance", "thermal.status", "thermal.probe0.avg", "thermal.newton"])
assert close(o1["thermal.Tmax"], 100.0, 1e-9) and close(o1["thermal.flow0"], Qs(80.0), 1e-4) and close(o1["thermal.flow1"], -Qs(80.0), 1e-4)
assert o1["thermal.status"] == "ok" and o1["thermal.balance"] < 1e-9 and o1["thermal.newton"] is None and 98 < o1["thermal.probe0.avg"] < 100
# the case values are in the tab's units: 180 degC at the hot end, a stronger convection, copper
c2 = run_case({"thermal.sup0.T": "200"})
assert close(ad.case_outputs(c2, ["thermal.flow0"])["thermal.flow0"], Qs(180.0), 1e-4)
c3 = run_case({"thermal.load0.h": "50", "thermal.load0.Tinf": "0"})
assert close(ad.case_outputs(c3, ["thermal.flow0"])["thermal.flow0"], Qs(100.0, 50.0), 1e-4)
c4 = run_case({"thermal.e_k": "401"})
assert close(ad.case_outputs(c4, ["thermal.flow0"])["thermal.flow0"], Qs(80.0, k=401.0), 1e-4)
c5 = run_case({"thermal.gen0": "1e5"})
o5 = ad.case_outputs(c5, ["thermal.flow0", "thermal.flow1"])
assert close(-(o5["thermal.flow0"] + o5["thermal.flow1"]), 1e5 * 0.1 * 0.02 * 0.001, 1e-6) and o5["thermal.flow1"] < -Qs(80.0), "the generated heat leaves through the convection too"
assert (tsd.e_t.text(), repr(tsd.supports), repr(tsd.loads), tsd.mesh, tsd.result) == before, "a study never touches the tab on screen"
assert len(ctx["cache"]) == 1, "one mesh for every case with the same element size"
c6 = run_case({"thermal.e_h": "8"})
assert len(ctx["cache"]) == 2 and ad.case_outputs(c6, ["thermal.tris"])["thermal.tris"] < ad.case_outputs(c1, ["thermal.tris"])["thermal.tris"]
# a transient case: the lumped plate cooled for one time constant, set through the widgets
c7 = run_case({"thermal.cb_plate": "yes", "thermal.e_hplate": "20", "thermal.e_Tamb": "20", "thermal.e_eps_plate": "0", "thermal.analysis_combo": "Transient (changes with time)",
               "thermal.e_T0": "100", "thermal.e_tend": f"{TAU:.6f}", "thermal.e_steps": "200", "thermal.sup0.T": "100", "thermal.load0.h": "0"})
o7 = ad.case_outputs(c7, ["thermal.Tmin", "thermal.stored"])
r7_ = c7["result"]
assert r7_["analysis"] == "transient" and r7_["frames"].shape[0] == 40 and close(r7_["times"][-1], TAU, 1e-9) and r7_["setup"]["steps"] == 200
ref = new_tab(MM)                                       # the same case typed into a tab by hand: the same numbers
ref.import_state(ad.base_state())
ref.cb_plate.setChecked(True)
for w, v in ((ref.e_hplate, "20"), (ref.e_Tamb, "20"), (ref.e_eps_plate, "0"), (ref.e_T0, "100"), (ref.e_tend, f"{TAU:.6f}"), (ref.e_steps, "200")):
    w.setText(v)
ref.analysis_combo.setCurrentIndex(1)
ref.loads[0]["h"] = 0.0
ref.e_h.setText("5")
ref.run_mesh()
ref.run_solve()
assert np.allclose(ref.result["T"], r7_["T"], rtol=0, atol=1e-9) and np.allclose(ref.result["frames"], r7_["frames"], rtol=0, atol=1e-9)
assert 20.0 < o7["thermal.Tmin"] < 100.0 and close(o7["thermal.Tmin"], ref.result["Tmin"] - K0, 1e-9)
# bad input is reported, not raised
for bad in ({"thermal.e_t": "abc"}, {"thermal.nope": "1"}, {"thermal.sup0.T": "-500"}, {"thermal.load0.h": "-3"}, {"thermal.cb_plate": "maybe"},
            {"thermal.analysis_combo": "Sideways"}):
    sp_ = ad.prepare(bad, ctx)
    assert sp_["error"] and sp_["run"] is None, bad
# a case that cannot be solved comes back as failed (a heat flux alone: nothing to settle on), and its outputs are empty
tsd2 = new_tab(MM)
msd2, psd2, lsd2 = bar()
tsd2.set_model(msd2, "flux only")
add(tsd2, "add_flux", [("ln", lsd2[1])], 100.0)
tsd2.e_h.setText("5")
ad2 = tsd2.study_adapter()
spec = ad2.prepare({}, {})
cf = spec["run"](lambda *a, **k: None, lambda: False)
assert cf["status"] == "failed" and "temperature" in cf["error"].lower()
fo = ad2.case_outputs(cf, ["thermal.status", "thermal.Tmax"])
assert fo == {"thermal.status": "FAILED", "thermal.Tmax": None}
# a stopped run
try:
    ad.prepare({}, {})["run"](lambda *a, **k: None, lambda: True)
    raise SystemExit("cancel must stop the run")
except si.StudyCancelled:
    pass
# the case is shown on the tab (the pickled case is what the project keeps)
import pickle
c1b = pickle.loads(pickle.dumps(c1, protocol=4))
pstore._loads(pickle.dumps(c1, protocol=4))
ad.show(c1b)
assert tsd.result is c1b["result"] and tsd.mesh is c1b["mesh"] and tsd.canvas.field == "T" and "Highest temperature" in tsd.res_lbl.text()
assert ad.mesh_refinement()["sizes"] == ["thermal.e_h"] and ad.mesh_refinement()["count"] == "thermal.tris" and ad.mesh_refinement()["dim"] == 2
# in the US family the values are degF and Btu
unitctl.set_units(INCH, notify=False, persist=False)
adu = tu_.study_adapter()
pu_ = {d["id"]: d for d in adu.params()}
assert pu_["thermal.sup0.T"]["now"] == "212" and "(°F)" in pu_["thermal.sup0.T"]["label"] and "Btu/(hr ft2 F)" in pu_["thermal.load0.h"]["label"]
cu = adu.prepare({"thermal.sup0.T": "302"}, {})["run"](lambda *a, **k: None, lambda: False)
assert cu["status"].startswith("ok") and close(adu.case_outputs(cu, ["thermal.Tmax"])["thermal.Tmax"], 302.0, 1e-9)
cg = adu.prepare({"thermal.gen0": "1000"}, {})["run"](lambda *a, **k: None, lambda: False)
og = adu.case_outputs(cg, ["thermal.flow0", "thermal.flow1"])
V_ = (4 * 0.0254) * 0.0254 * (0.04 * 0.0254)
assert close(-(og["thermal.flow0"] + og["thermal.flow1"]) * 0.2930710702, 1000.0 * 10.34970717 * V_, 1e-6), "Btu/(hr ft3) in, watts through the body"
unitctl.set_units(MM, notify=False, persist=False)
print("14 ok: study adapter")

# ================================================================================================================ 15. the project folder (.gph) through the Simulation window
import pm_model as pm
import sk_tools as sk
import sim_source as ss


def make_part(path, w=100.0, h=10.0, material=None):
    d = pm.Document()
    d.params = {"W": str(w), "H": str(h)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (w, 20))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=w)
    m.add_con("dim_v", [("ln", r["lns"][1])], value=20.0)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    if material:
        d.material = material
    with open(path, "w", encoding="utf-8") as f:
        f.write(d.to_json())
    return d


part = os.path.join(T_, "src", "block.gpd")
os.makedirs(os.path.dirname(part))
make_part(part, material={"name": "Copper", "density": 8960.0, "E_MPa": 110000.0, "nu": 0.34, "Sy_MPa": 70.0, "Su_MPa": 220.0})
w = sim_tab.SimWindow("thermal")
assert w.kind == "thermal" and isinstance(w.tab, tt.ThermalTab) and not hasattr(w, "b_import")
assert w.create_project(os.path.join(T_, "block")) and w.path.endswith(".gph") and sp.kind_of_folder(w.path) == "thermal"
assert w.import_file(part)
sid = next(i for i, n in w.source_items() if i not in (sim_tab.SLICE_NEW, sim_tab.SLICE_LAST))
w.tab.picker.refresh()
w.tab.picker.select(sid)
w.tab.picker.go()
wt = w.tab
assert wt.model is not None and wt.mat_combo.currentData() == "Copper" and close(float(wt.e_k.text()), 401.0), "the material of the part (by its name)"
assert "Thermal material from the part: Copper" in w.status_lbl.text(), w.status_lbl.text()
wt.run_task = lambda title, fn: run_now(wt, title, fn)
lines = sorted(wt.model.lns)
mid_x = lambda i: sum(wt.model.pts[j][0] for j in wt.model.lns[i]) / 2.0          # a line is [point a, point b]
left, right = min(lines, key=mid_x), max(lines, key=mid_x)
add(wt, "add_temperature", [("ln", left)], 90.0)
add(wt, "add_conv", [("ln", right)], 100.0, 20.0)
wt.e_t.setText("5")
res_w = mesh_solve(wt, 5)
assert w.save() and os.path.isfile(sp.state_path(w.path)) and not w.is_dirty()
wt.region_q = {0: 5.0}                                   # a heat generation is part of what 'changed' means
assert w.is_dirty()
wt.region_q = {}
assert not w.is_dirty()
folder = w.path
shutil.move(os.path.dirname(part), os.path.dirname(part) + "_away")             # the original is gone: the project has its own copy
w2 = sim_tab.SimWindow.open_project(None, folder)
t2_ = w2.tab
assert w2.kind == "thermal" and isinstance(t2_, tt.ThermalTab) and t2_.model is not None and t2_.result is not None
assert np.array_equal(t2_.result["T"], res_w["T"]) and t2_.mat_combo.currentData() == "Copper" and t2_.e_t.text() == "5" and not w2.is_dirty()
assert abs(w2.source.doc.solid.volume - 100 * 20 * 10) < 1e-3
# the program's units change while the project is open: through the window
unitctl.set_units(INCH, notify=False, persist=False)
w2.units_changed(MM, INCH, units.DEFAULT_SPEED, units.DEFAULT_SPEED)
assert t2_.unit_name() == INCH and close(float(t2_.e_t.text()), 5 / 25.4, 1e-9) and t2_.result is not None and "°F" in t2_.lbl_T0.text()
assert "Units:" in w2.status_lbl.text()
unitctl.set_units(MM, notify=False, persist=False)
w2.units_changed(INCH, MM, units.DEFAULT_SPEED, units.DEFAULT_SPEED)
assert t2_.unit_name() == MM and close(float(t2_.e_t.text()), 5.0, 1e-9)
# saved in one unit system, opened in another: converted on opening
unitctl.set_units(INCH, notify=False, persist=False)
w3 = sim_tab.SimWindow.open_project(None, folder)
assert w3.tab.unit_name() == INCH and close(float(w3.tab.e_t.text()), 5 / 25.4, 1e-9) and close(w3.tab.result["Tmax"], res_w["Tmax"], 1e-12)
unitctl.set_units(MM, notify=False, persist=False)
# a slice of the copy gives the tab a sketch to work on, with the part's material on its region
w.meta["slice"] = {"plane": "Top", "offset": 5.0, "flip": False, "excluded": []}
shutil.move(os.path.dirname(part) + "_away", os.path.dirname(part))
js = w.slice_json(True)
assert js is not None and "Slice Top" in js[0]
w.on_imported(sim_tab.SLICE_NEW, js[1], js[0])
assert len(w.tab.geom["faces"]) >= 1 and w.tab.region_names and w.tab.region_mats and all(m["name"] == "Copper" and close(m["k"], 401.0) for m in w.tab.region_mats.values()), (w.tab.region_names, w.tab.region_mats)
assert "Thermal materials from the parts: Copper" in w.status_lbl.text(), w.status_lbl.text()
print("15 ok: project folder through the Simulation window")
shutil.rmtree(T_, ignore_errors=True)
shutil.rmtree(UD, ignore_errors=True)
print("OK thermal tab")
