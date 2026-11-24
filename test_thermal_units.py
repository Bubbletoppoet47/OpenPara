"""The 2D Thermal tab on the units of File > Units > Heat transfer (heatunits.py, thermal_units.py): the default ('Follow the unit system') is what the tab
always did; a preset or custom units change how the boxes, labels, conditions, report, legend and studies show and read numbers while the model, the mesh and
the result (SI) stay exactly as they are; a change converts the boxes physically; a saved state remembers its units (and one saved before that follows its unit
system); a unit system change does not touch the boxes when the heat units do not follow it; the average heat flux of the conditions (the radiative one in its
own unit); an older program without the heat units still works."""
import os
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

import sketcher_core as sc
import physics_store as pstore
import sim_tab
import unitctl
import units
import heatunits as hu
import thermal_tab as tt
import thermal_units as tu

MM = "Metric (mm, kg, N, s, MPa)"
INCH = "US (in, lbf, psi)"
US, METRIC = hu.US, hu.METRIC
close = lambda a, b, rel=1e-6, ab=0.0: abs(a - b) <= rel * max(abs(a), abs(b)) + ab


def host():
    h = sim_tab.SimHost.__new__(sim_tab.SimHost)
    h.doc = None
    h.m = sim_tab._HostModel()
    h._restoring = False
    h.status = lambda t: None
    h.sim = None
    h.sketch_list = lambda: []
    return h


def run_now(tab, title, fn):
    try:
        return "ok", fn(lambda *a, **k: None, lambda: False)
    except (tt.pg.Cancelled, tt.pf.Cancelled):
        return "cancelled", None
    except (tt.pg.GeometryError, tt.pf.ModelError) as ex:
        QMessageBox.warning(tab, title, str(ex))
        return "user", str(ex)


def new_tab(unit=MM):
    unitctl.set_units(unit, notify=False, persist=False)
    t = tt.ThermalTab(host())
    t.run_task = lambda title, fn: run_now(t, title, fn)
    return t


def bar(W=100.0, Hh=20.0):
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (W, 0), (W, Hh), (0, Hh))]
    ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]       # 0 bottom, 1 right, 2 top, 3 left
    return m, ls


def answer(*vals):
    def f(parent, title, note, labels, defaults):
        return list(vals)
    tt.ask_values = f


def add(t, fn, sel, *vals):
    t.canvas.sel = list(sel)
    answer(*vals)
    getattr(t, fn)()


def heat(name, custom=None):
    """File > Units > Heat transfer was changed (without the window): the tab hears of it as the Simulation window passes it on."""
    unitctl.set_heat(name, custom, notify=False, persist=False)


def solved_bar():
    """A bar: 100 degC on the left, convection (25 W/(m2 K), 20 degC fluid) on the right, radiation (0.6, 30 degC) at the bottom, a heat flux on the top."""
    t = new_tab(MM)
    m, ls = bar()
    t.set_model(m, "bar")
    t.e_t.setText("1")
    add(t, "add_temperature", [("ln", ls[3])], 100.0)
    add(t, "add_conv", [("ln", ls[1])], 25.0, 20.0)
    add(t, "add_rad", [("ln", ls[0])], 0.6, 30.0)
    add(t, "add_flux", [("ln", ls[2])], 500.0)
    t.e_h.setText("5")
    t.run_mesh()
    assert t.mesh is not None, MSGS
    t.run_solve()
    assert t.result is not None, MSGS
    return t


def boxes(t):
    return {n: float(getattr(t, n).text()) for n in ("e_k", "e_rho", "e_cp", "e_T0", "e_hplate", "e_Tamb", "e_Tsur")}


# ================================================================================================================ 1. the default is what the tab always did
assert unitctl.heat() == hu.FOLLOW
t = solved_bar()
assert t.cur_heat.name == METRIC and t.family().name == METRIC and "°C" in t.lbl_T0.text() and "W/(m K)" in t.lbl_k.text()
assert "heat transfer: " + METRIC in t.units_note.text()
b0 = boxes(t)
assert b0 == {"e_k": 167.0, "e_rho": 2700.0, "e_cp": 896.0, "e_T0": 20.0, "e_hplate": 10.0, "e_Tamb": 20.0, "e_Tsur": 20.0}, b0
setup0, T0, mesh0 = t.read_setup(), np.array(t.result["T"]), t.mesh
for q in hu.QUANTITIES:
    assert t.family().unit(q) == hu.PRESETS[METRIC][q]
fi = tu.family_of(INCH)
assert fi.us and fi.name == US and fi.temp == "°F" and fi.unit("qr") == "Btu/(hr ft2)" and tu.family_of(MM).unit("qr") == "W/m2"
# each quantity of the family does what the old two-family tables did (the US numbers are the same ones, to ten digits)
for q, (m_, u_, f_) in tu.QUANTITIES.items():
    assert fi.unit(q) == u_ and abs(fi.factor(q) / f_ - 1) < 3e-10, (q, fi.factor(q), f_)
print("1 ok: the default")

# ================================================================================================================ 2. a preset: the boxes convert, the problem stays
heat(US)                                              # the unit system is still metric (mm): the heat units do not follow it now
assert t.family().name == US and t.cur_heat.name == METRIC, "nothing happens until the tab is told"
t.heat_units_changed()
assert t.cur_heat.name == US and t.family().temp == "°F"
b1 = boxes(t)
assert close(b1["e_T0"], 68.0, 1e-12) and close(b1["e_Tamb"], 68.0, 1e-12) and close(b1["e_Tsur"], 68.0, 1e-12)
assert close(b1["e_k"], 167.0 / 1.730734666, 1e-8) and close(b1["e_rho"], 2700.0 / 16.01846337, 1e-8) and close(b1["e_cp"], 896.0 / 4186.8, 1e-8)
assert close(b1["e_hplate"], 10.0 / 5.678263341, 1e-8)
assert "°F" in t.lbl_T0.text() and "Btu/(hr ft F)" in t.lbl_k.text() and "Btu/(hr ft2 F)" in t.lbl_hplate.text() and "lb/ft3" in t.lbl_rho.text()
assert "(mm)" in t.lbl_t.text() and "heat transfer: " + US in t.units_note.text(), "the sketch length unit is the unit system's, not the heat units'"
assert t.read_setup() == setup0, "the same problem: every number the solver gets is SI and has not moved"
assert np.array_equal(t.result["T"], T0) and t.mesh is not None and t.mesh["nodes"].shape == mesh0["nodes"].shape
rows = [[t.cond_table.item(r, c).text() for c in range(4)] for r in range(t.cond_table.rowCount())]
assert any("°F" in r[1] and r[3] == "212" for r in rows), rows
conv = next(r for r in rows if r[0].startswith("Convection"))
assert "Btu/(hr ft2 F)" in conv[1] and conv[3].split(",")[1].strip() == "68" and close(float(conv[3].split(",")[0]), 25.0 / 5.678263341, 1e-3), conv
html = t.res_lbl.text()
assert "°F" in html and "Btu/hr" in html and "212" in html and "Btu/(hr ft2)" in html, "the report is in the new units"
fam = t.family()
assert close(fam.from_si("T", t.result["Tmax"]), 212.0, 1e-9)
assert not t.canvas.grab().isNull()
print("2 ok: a preset")

# ================================================================================================================ 3. back again: the boxes return, nothing drifted
heat(hu.FOLLOW)
t.heat_units_changed()
assert t.cur_heat.name == METRIC
b2 = boxes(t)
for n, v in b0.items():
    assert close(b2[n], v, 1e-12), (n, b2[n], v)
assert t.read_setup() == setup0 and np.array_equal(t.result["T"], T0)
t.canvas.sel = [("ln", 2)]                             # something a reload of the tab would clear
t.heat_units_changed()                                # told again with nothing changed: nothing happens
assert t.cur_heat.name == METRIC and boxes(t) == b2 and t.canvas.sel == [("ln", 2)]
t.canvas.sel = []
print("3 ok: back again")

# ================================================================================================================ 4. custom units, quantity by quantity
heat(hu.CUSTOM, {"T": "K", "P": "kW", "q": "W/cm2", "qr": "kW/m2", "k": "W/(mm K)", "h": "W/(cm2 K)", "rho": "g/cm3", "cp": "kJ/(kg K)", "qv": "kW/m3"})
t.heat_units_changed()
assert t.cur_heat.name == hu.CUSTOM and t.family().temp == "K"
b3 = boxes(t)
assert close(b3["e_T0"], 293.15, 1e-12) and close(b3["e_k"], 0.167, 1e-12) and close(b3["e_rho"], 2.7, 1e-12) and close(b3["e_cp"], 0.896, 1e-12)
assert close(b3["e_hplate"], 10.0 / 1e4, 1e-12) and close(b3["e_Tsur"], 293.15, 1e-12)
assert "(K)" in t.lbl_T0.text() and "W/(mm K)" in t.lbl_k.text() and "g/cm3" in t.lbl_rho.text() and "kJ/(kg K)" in t.lbl_cp.text() and "W/(cm2 K)" in t.lbl_hplate.text()
assert t.read_setup() == setup0
assert "kW" in t.res_lbl.text() and "373.15" in t.res_lbl.text()
# a value typed now is read in the new units: 0.5 W/(mm K) is 500 W/(m K)
t.e_k.setText("0.5")
v = t.read_material_boxes()
assert close(v["k"], 500.0, 1e-12), v
t.e_k.setText("0.167")
print("4 ok: custom units")

# ================================================================================================================ 5. the average heat flux of the conditions, the radiative one in its own unit
html = t.res_lbl.text()
assert "Average heat flux" in html
res = t.result
by = {f["kind"]: f for f in res["flows"]}
A = 0.001 * 0.1                                       # depth 1 mm x the 100 mm long edges (bottom, top), metres
for kind, f in by.items():
    if kind == "temp":
        assert "area" not in f
    else:
        assert close(f["area"], {"conv": 0.001 * 0.02, "rad": A, "flux": A}[kind], 1e-12), (kind, f["area"])
# radiation: kW/m2 ; convection and flux: W/cm2
qr = by["rad"]["Q"] / by["rad"]["area"] / 1e3
assert t.res_lbl.text().count("kW/m2") >= 1 and tt.R.num(qr, 4) + " kW/m2" in html, (qr, html)
qc = by["conv"]["Q"] / by["conv"]["area"] / 1e4
assert tt.R.num(qc, 4) + " W/cm2" in html, (qc, html)
assert tt.R.num(500.0 / 1e4, 4) + " W/cm2" in html, "the heat flux condition shows the 500 W/m2 it was given"
# in the other presets the same numbers read in their units
heat(US)
t.heat_units_changed()
html = t.res_lbl.text()
assert tt.R.num(by["rad"]["Q"] / by["rad"]["area"] / 3.154590745, 4) + " Btu/(hr ft2)" in html, html
heat(hu.FOLLOW)
t.heat_units_changed()
# the flux is for the conditions that have an edge: a temperature or a heat flow shows none, even when its record carries an area
import re
crafted = dict(res)
crafted["flows"] = [dict(f, area=1.0e-3) for f in res["flows"]]
t.show_solution(crafted, restored=True)
assert re.search(r"Temperature 1</td><td[^>]*>[^<]*</td><td[^>]*></td>", t.res_lbl.text()), t.res_lbl.text()
assert re.search(r"Convection 1</td><td[^>]*>[^<]*</td><td[^>]*>[^<]+ W/m2</td>", t.res_lbl.text())
t.show_solution(res, restored=True)
# a result saved before the area was kept: no flux column entries, no failure
old = dict(t.result)
old["flows"] = [{k: v for k, v in f.items() if k != "area"} for f in old["flows"]]
t.show_solution(old, restored=True)
assert "Average heat flux" in t.res_lbl.text() and "W/m2" not in t.res_lbl.text().split("Heat balance")[0].split("Heat through each condition")[1]
t.show_solution(res, restored=True)
print("5 ok: average heat flux")

# ================================================================================================================ 6. saved states remember their units
heat(US)
t.heat_units_changed()
st = t.export_state()
assert st["heat_units"] == hu.PRESETS[US]
heat(hu.FOLLOW)                                       # the program's choice changes while the file is closed
t2 = new_tab(MM)
t2.import_state(st)
assert t2.cur_heat.name == METRIC and boxes(t2)["e_T0"] == 20.0 and close(boxes(t2)["e_k"], 167.0, 1e-9), boxes(t2)
assert t2.read_setup() == setup0 and np.array_equal(t2.result["T"], T0)
assert "°C" in t2.lbl_T0.text() and t2.res_lbl.text() != "" and not t2.canvas.grab().isNull()
# the same state opened where the choice is the one it was saved in: nothing converted
heat(US)
t3 = new_tab(MM)
t3.import_state(st)
assert close(boxes(t3)["e_T0"], 68.0, 1e-12) and t3.cur_heat.name == US and t3.read_setup() == setup0
# a state saved before the units were recorded was written in the units of its unit system
heat(hu.FOLLOW)
t4 = new_tab(INCH)
m4, ls4 = bar()
m4.unit_system = INCH
t4.set_model(m4, "inch bar")
assert t4.cur_heat.name == US
t4.e_T0.setText("68")
t4.e_hplate.setText("10")
s4 = t4.export_state()
assert s4["heat_units"] == hu.PRESETS[US]
s4.pop("heat_units")
heat(hu.CUSTOM, {"T": "K", "k": "W/(m K)"})
t5 = new_tab(INCH)
t5.import_state(s4)
assert t5.cur_heat.temp == "K" and close(float(t5.e_T0.text()), 293.15, 1e-12) and close(float(t5.e_hplate.text()), 10.0 * 5.678263341, 1e-8), (t5.e_T0.text(), t5.e_hplate.text())
# the state records the units of the boxes, which are the ones shown
assert t5.export_state()["heat_units"] == dict(hu.PRESETS[METRIC], T="K")
print("6 ok: saved states")

# ================================================================================================================ 7. a unit system change
heat(hu.CUSTOM, hu.PRESETS[METRIC])                  # metric heat units whatever the system
t6 = solved_bar()
b6 = boxes(t6)
unitctl.set_units(INCH, notify=False, persist=False)
t6.change_units(MM, INCH, True)
assert t6.unit_name() == INCH and boxes(t6) == b6, "the heat units do not follow the system: the boxes keep their numbers"
assert "°C" in t6.lbl_T0.text() and "(in)" in t6.lbl_t.text() and close(float(t6.e_t.text()), 1 / 25.4, 1e-9)
assert t6.result is not None
heat(hu.FOLLOW)                                      # now they do: the same change converts the boxes
t7 = solved_bar()
assert t7.cur_heat.name == METRIC
unitctl.set_units(INCH, notify=False, persist=False)
t7.change_units(MM, INCH, True)
assert t7.cur_heat.name == US and close(float(t7.e_T0.text()), 68.0, 1e-12) and t7.result is not None
unitctl.set_units(MM, notify=False, persist=False)
t7.change_units(INCH, MM, True)
assert t7.cur_heat.name == METRIC and close(float(t7.e_T0.text()), 20.0, 1e-9) and close(float(t7.e_k.text()), 167.0, 1e-8)
# a state that says what units its boxes are in is converted from THOSE, whatever its unit system would have used
import thermal_store as tstore
heat(hu.FOLLOW)
t13 = solved_bar()
heat(US)
t13.heat_units_changed()
st13 = t13.export_state()
assert st13["heat_units"] == hu.PRESETS[US] and st13["inputs"]["e_T0"] == "68"
cv = tstore.convert_state(st13, MM, INCH, True)                      # to the US system, where the US units are the choice too: the boxes stay
assert cv["inputs"]["e_T0"] == "68" and cv["heat_units"] == hu.PRESETS[US]
heat(METRIC)
cv = tstore.convert_state(st13, MM, INCH, True)                      # the choice is metric now: 68 degF is 20 degC
assert close(float(cv["inputs"]["e_T0"]), 20.0, 1e-9) and cv["heat_units"] == hu.PRESETS[METRIC]
heat(hu.FOLLOW)
# a relabel: the numbers stay; the SI conditions are read again in the new units
heat(hu.FOLLOW)
t8 = solved_bar()
unitctl.set_units(INCH, notify=False, persist=False)
t8.change_units(MM, INCH, False)
assert t8.mesh is None and t8.result is None
temps = [s["T"] for s in t8.supports if s["kind"] == "temp"]
assert close(temps[0], tu.family_of(INCH).to_si("T", 100.0), 1e-12), "the 100 typed is 100 degF now"
print("7 ok: unit system changes")

# ================================================================================================================ 8. the Simulation window passes the change on
heat(hu.FOLLOW)
t9 = solved_bar()
w = sim_tab.SimWindow.__new__(sim_tab.SimWindow)
w.tab = t9
heat(US)
sim_tab.SimWindow.heat_changed(w, (hu.FOLLOW, {}), (US, {}))
assert t9.cur_heat.name == US and close(float(t9.e_T0.text()), 68.0, 1e-12)
class NoHook:
    pass
w.tab = NoHook()
sim_tab.SimWindow.heat_changed(w, (US, {}), (hu.FOLLOW, {}))          # a solver tab without heat numbers is left alone
heat(hu.FOLLOW)
# before anything is imported only the boxes hold numbers
t10 = new_tab(MM)
assert t10.model is None and close(float(t10.e_T0.text()), 20.0)
heat(US)
t10.heat_units_changed()
assert close(float(t10.e_T0.text()), 68.0, 1e-12) and "°F" in t10.lbl_T0.text() and t10.cur_heat.name == US
heat(hu.FOLLOW)
t10.heat_units_changed()
assert close(float(t10.e_T0.text()), 20.0, 1e-12)
print("8 ok: the window and an empty tab")

# ================================================================================================================ 9. studies and the legend use the same units
heat(hu.FOLLOW)
t11 = solved_bar()                                   # solved and typed in the metric units ...
heat(hu.CUSTOM, dict(hu.PRESETS[US], P="kBtu/hr"))
t11.heat_units_changed()                             # ... and now in degF, kBtu/hr, ...
fam11 = t11.family()
assert fam11.unit("P") == "kBtu/hr" and fam11.temp == "°F" and t11.cur_heat.name == hu.CUSTOM
ad = t11.study_adapter()
outs = {o["id"]: o["label"] for o in ad.outputs()}
assert "(°F)" in outs["thermal.Tmax"] and "(kBtu/hr)" in outs["thermal.heat_in"] and "(Btu/(hr ft2))" in outs["thermal.qmax"], outs
pars = {d["id"]: d for d in ad.params()}
assert pars["thermal.sup0.T"]["now"] == "212" and "(°F)" in pars["thermal.sup0.T"]["label"], pars["thermal.sup0.T"]
case = ad.prepare({"thermal.sup0.T": "302"}, {})["run"](lambda *a, **k: None, lambda: False)       # 302 degF typed = 150 degC
got = ad.case_outputs(case, ["thermal.Tmax", "thermal.heat_in"])
assert close(got["thermal.Tmax"], 302.0, 1e-9)
assert close(got["thermal.heat_in"], case["result"]["balance"]["in"] / (1055.05585262 * 1e3 / 3600.0), 1e-9), got
heat(hu.FOLLOW)
print("9 ok: study adapter")

# ================================================================================================================ 10. a program without the heat units
saved = tu.hu
tu.hu = None
try:
    f_ = tu.family_of(INCH)
    assert isinstance(f_, tu.Family) and f_.us and f_.temp == "°F" and f_.unit("qr") == "Btu/(hr ft2)" and f_.key == ("family", True)
    assert tu.family_of(MM).key == ("family", False) and tu.family_of(MM).unit("qr") == "W/m2"
    assert isinstance(tu.state_family({"heat_units": {"T": "K"}}, INCH), tu.Family), "the saved units are not understood: the unit system's family"
    t12 = new_tab(MM)
    assert t12.family().name.startswith("Metric") and t12.box_units() is None
finally:
    tu.hu = saved
assert tu.family_of(INCH).name == US
print("10 ok: older program")
unitctl.set_units(MM, notify=False, persist=False)
print("OK thermal units")
