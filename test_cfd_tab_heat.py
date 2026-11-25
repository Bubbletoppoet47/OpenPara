"""The temperature in the 2D CFD window (cfd_tab.py): the controls, the conditions on the walls, the solve (the worker's own path), the picture and numbers it shows,
the units (File > Units > Heat transfer), the saved state and the diagnostics.  The numbers themselves are checked in test_cfd_temperature.py; here it is the window
that must hand them over right: a 20 mm square in a slow air stream, its four sides held at 50 degC, the air arriving at 20 degC.
python test_cfd_tab_heat.py"""
import faulthandler
faulthandler.dump_traceback_later(1500, exit=True)
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
import sketcher_core as sc
import cfd_tab
import sim_tab
import physics_cfd as pcfd
import physics_cfd_heat as pheat
import heatunits as hu
import unitctl
import units

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


POPUPS = []
for _n in ("warning", "information", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: POPUPS.append(str(a[2]) if len(a) > 2 else "")))


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
    return "ok", fn(lambda *a, **k: None, lambda: False)


def square_model(a=20.0):
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (a, 0), (a, a), (0, a))]
    for i in range(4):
        m.add_line(p[i], p[(i + 1) % 4])
    return m


def new_tab():
    t = cfd_tab.CFDTab(host())
    t.run_task = lambda title, fn: run_now(t, title, fn)
    t.set_model(square_model(), "a 20 mm square")
    t.resize(1200, 900)
    t.show()
    app.processEvents()
    return t


def wait(t, limit=900):
    t0 = time.time()
    while t.worker is not None and time.time() - t0 < limit:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    return t.worker is None


def set_case(t, steps=250):
    t.e_speed.setText(f"{units.speed_from_si(0.03, t.unit_name()):.6g}")
    for e, v in ((t.e_hb, "3"), (t.e_hf, "12"), (t.e_ml, "3"), (t.e_mr, "8"), (t.e_mb, "3"), (t.e_mt, "3"), (t.e_cfl, "2"), (t.e_steps, str(steps)),
                 (t.e_tol, "1e-6"), (t.e_ramp, "5"), (t.e_every, "1000")):
        e.setText(v)
    t.cb_until.setChecked(False)
    t.cb_auto.setChecked(False)


# ---------------------------------------------------------------------------------------------------------------------------------- the controls
t = new_tab()
ok(t.cb_heat.isChecked() is False and t.heat_box.isHidden(), "heat transfer is off by default and its controls are hidden")
ok(t.read_heat() is None, "with it off the solve has no heat dict")
ok(t.field.findData("T") >= 0 and "emperature" in t.field.itemText(t.field.findData("T")), "the temperature is a choice of the result list")
d = t.diagnostics_text()
ok("heat transfer: off" in d, "the diagnostics say heat transfer is off")

t.cb_heat.setChecked(True)
app.processEvents()
ok(not t.heat_box.isHidden(), "ticking it shows the conductivity, the specific heat, the inlet temperature and the wall conditions")
k_si, cp_si, tin_si = t.heat_si()
ok(abs(k_si - 0.0253) < 1e-9 and abs(cp_si - 1006.0) < 1e-6 and abs(tin_si - 293.15) < 1e-9, f"the fluid library fills the air values ({k_si:g} W/(m K), {cp_si:g} J/(kg K)); the inlet is 20 degC = {tin_si:.2f} K")
t.fluid_combo.setCurrentText("Water 20 C")
app.processEvents()
k_si, cp_si, _ = t.heat_si()
ok(abs(k_si - 0.598) < 1e-9 and abs(cp_si - 4182.0) < 1e-6, "choosing water changes the density, the viscosity, the conductivity and the specific heat together")
ok("Prandtl number" in t.heat_note.text() and "7.01" in t.heat_note.text(), f"the note gives the Prandtl number of water: {t.heat_note.text()}")
t.fluid_combo.setCurrentText("Air 20 C")
t.e_k.textEdited.emit("0.03")
t.e_k.setText("0.03")
ok(t.fluid_combo.currentText() == "Custom", "typing a conductivity makes the fluid Custom (as typing a density does)")
t.fluid_combo.setCurrentText("Air 20 C")
app.processEvents()

POPUPS.clear()
try:
    t.read_heat()
    ok(False, "heat transfer on with no wall condition is refused")
except pcfd.ModelError as ex:
    ok("no wall has a temperature" in str(ex), f"heat transfer on with no wall condition is refused in words: {ex}")

keys = sorted({e["src"] for e in t.geom["edges"]})
ok(len(keys) == 4, "the square has four edges")
for bad, kind, what in (("abc", "temp", "must be a number"), ("-300", "temp", "absolute zero"), ("", "temp", "must be a number")):
    try:
        t.set_wall_condition(keys, kind, bad)
        ok(False, f"'{bad}' {kind} must be refused")
    except pcfd.ModelError as ex:
        ok(what in str(ex), f"'{bad}' as a temperature is refused: {ex}")
try:
    t.set_wall_condition([], "temp", "50")
    ok(False, "no edge selected is refused")
except pcfd.ModelError as ex:
    ok("Select at least one edge" in str(ex), f"no edge selected is refused: {ex}")
try:
    t.set_wall_condition(keys, "banana", "50")
    ok(False, "an unknown kind is refused")
except pcfd.ModelError as ex:
    ok("Unknown heat condition" in str(ex), "an unknown kind of condition is refused")
ok(t.heat_walls == {}, "none of the refused conditions was kept")

t.canvas.sel = list(keys)
t.selection_changed()
ok(t.b_heat_set.isEnabled() and not t.b_heat_off.isEnabled(), "with edges selected 'Set' is available, 'Remove' only when one of them has a condition")
t.set_wall_condition(keys[:2], "flux", "100")
t.set_wall_condition(keys, "temp", "50")
ok(all(abs(c["v"] - 323.15) < 1e-9 and c["kind"] == "temp" for c in t.heat_walls.values()) and len(t.heat_walls) == 4,
   "four sides at 50 degC are kept in kelvin (a later condition replaces the earlier one)")
ok(t.heat_list.count() == 4 and "50 °C" in t.heat_list.item(0).text() and "fixed temperature" in t.heat_list.item(0).text(), f"the list says it: {t.heat_list.item(0).text()}")
ok(t.b_heat_off.isEnabled(), "'Remove from selected' is available now")
t.remove_wall_conditions([keys[0]])
ok(len(t.heat_walls) == 3 and keys[0] not in t.heat_walls, "Remove takes the condition off one edge")
t.set_wall_condition(keys, "temp", "50")
h = t.read_heat()
ok(set(h["walls"]) == set(keys) and abs(h["T_in"] - 293.15) < 1e-9 and h["walls"][keys[0]] == {"kind": "temp", "T": 323.15}, "read_heat gives the solver its dict in SI")
d = t.diagnostics_text()
ok("heat transfer: ON" in d and "fixed temperature 323.15 K" in d, "the diagnostics list the heat setup")

# ---------------------------------------------------------------------------------------------------------------------------------- a solve (the worker's own path)
set_case(t)
t.run_mesh()
ok(t.mesh is not None, "meshed")
t0 = time.time()
t.run_solve()
ok(t.worker is not None, "the solve started on its worker thread")
ok(wait(t), "the solve finished")
res = t.result
ok(res is not None and res["status"] == "converged", f"the flow converged ({res['status'] if res else None}, {res['steps'] if res else None} steps, {time.time() - t0:.0f} s)")
hres = res.get("heat") if res else None
ok(hres is not None and not res.get("heat_error"), "the temperature came with it")
Tn = hres["T"]
ok(abs(Tn.min() - 293.15) < 1e-6 and abs(Tn.max() - 323.15) < 1e-6, f"the temperature runs from the inlet 20 degC to the walls 50 degC ({Tn.min() - 273.15:.3f} .. {Tn.max() - 273.15:.3f})")
ok(abs(hres["balance"]["relative"]) < 0.01, f"the heat from the walls and the heat carried away agree ({100 * hres['balance']['relative']:.1f} %)")
ok("Temperature" in t.res_lbl.text() and "difference" in t.res_lbl.text() and "20" in t.res_lbl.text() and "50" in t.res_lbl.text(), "the result text has the temperature range and the energy balance")
ok(all("T_a" in res["walls"][k] and res["walls"][k]["heat_kind"] == "temp" for k in keys), "the wall tables carry the temperature for the other windows")
ok(t.setup_used["heat"]["T_in"] == 293.15 and t.transfer_info()["heat"] is hres, "the setup used and the transfer info keep the heat setup and result")

t.field.setCurrentIndex(t.field.findData("T"))
app.processEvents()
fd = t.field_data()
ok(fd is not None and fd["unit"] == "°C" and abs(fd["values"].min() - 20.0) < 1e-6 and abs(fd["values"].max() - 50.0) < 1e-6 and len(fd["values"]) == len(t.mesh["nodes"]),
   f"the picture's values are the temperature in °C at the mesh corners ({fd['values'].min():.3f} .. {fd['values'].max():.3f} {fd['unit']})")
t.canvas.focus = None                                  # (the sidebar's choice of what to draw: everything)
t.canvas.update()
app.processEvents()
t.grab()
print("     canvas focus", t.canvas.focus, "raster", t.canvas.raster is not None, "base", None if t.canvas.base is None else (t.canvas.base["lo"], t.canvas.base["hi"]))
ok(t.canvas.base is not None and abs(t.canvas.base["lo"] - 20.0) < 1e-6 and abs(t.canvas.base["hi"] - 50.0) < 1e-6, "the canvas painted it with the legend range 20 .. 50")

t.canvas.sel = [keys[0]]
t.selection_changed()
txt = t.sel_lbl.text()
ok("temperature" in txt and "°C" in txt and "heat into the fluid" in txt and "h =" in txt, f"selecting an edge shows its temperature, heat and transfer coefficient: {txt[-170:]}")
hh = float(txt.split("h = ")[1].split()[0])
ok(2.0 < hh < 60.0, f"h of that edge is of the order of air in slow forced convection ({hh:.1f} W/(m2 K))")

# units: the heat-transfer units of File > Units
unitctl.set_heat("US (°F, Btu/hr)", notify=True, persist=False)
app.processEvents()
ok(abs(float(t.e_Tin.text()) - 68.0) < 1e-3, f"changing the heat units to °F rewrites the inlet temperature box (20 degC -> {t.e_Tin.text()})")
ok(abs(t.heat_walls[keys[0]]["v"] - 323.15) < 1e-9 and "122 °F" in t.heat_list.item(0).text(), f"the stored conditions stay in kelvin and the list is shown in °F: {t.heat_list.item(0).text()}")
ok("Btu" in t.lbl_k.text() and "°F" in t.lbl_Tin.text(), f"the labels carry the units: {t.lbl_k.text()} | {t.lbl_Tin.text()}")
k_si, cp_si, tin_si = t.heat_si()
ok(abs(k_si - 0.0257) < 1e-4 and abs(cp_si - 1006.0) < 0.5 and abs(tin_si - 293.15) < 1e-3, f"the boxes still mean the same physical values ({k_si:.5g}, {cp_si:.5g}, {tin_si:.3f} K)")
fd = t.field_data()
ok(fd["unit"] == "°F" and abs(fd["values"].min() - 68.0) < 1e-3 and abs(fd["values"].max() - 122.0) < 1e-3, f"the picture follows: {fd['values'].min():.2f} .. {fd['values'].max():.2f} {fd['unit']}")
st = t.export_state()
unitctl.set_heat("Follow the unit system", notify=True, persist=False)
app.processEvents()
ok(abs(float(t.e_Tin.text()) - 20.0) < 1e-3, "and back to °C")

# ---------------------------------------------------------------------------------------------------------------------------------- the saved state
t2 = cfd_tab.CFDTab(host())
t2.run_task = lambda title, fn: run_now(t2, title, fn)
t2.import_state(st)                                   # saved while the boxes were in °F, loaded while the choice is °C
app.processEvents()
ok(t2.cb_heat.isChecked() and not t2.heat_box.isHidden(), "a saved tab comes back with heat transfer on and its controls shown")
ok(abs(float(t2.e_Tin.text()) - 20.0) < 1e-3 and abs(t2.heat_si()[0] - 0.0257) < 1e-9, f"its boxes, saved in °F, are read back in the units of today ({t2.e_Tin.text()} °C)")
ok(t2.heat_walls == {k: v for k, v in t.heat_walls.items()} and len(t2.heat_walls) == 4, "the wall conditions came back")
ok(t2.result is not None and t2.result.get("heat") is not None and abs(t2.result["heat"]["Tmax"] - 323.15) < 1e-6, "and the result with its temperature")
t2.field.setCurrentIndex(t2.field.findData("T"))
fd = t2.field_data()
ok(fd["unit"] == "°C" and abs(fd["values"].max() - 50.0) < 1e-6, "which can be drawn again")
st2 = t2.export_state()
ok(st2["heat_units"]["T"] == "°C" and len(st2["heat_walls"]) == 4, "saving again records the units the boxes are in")
# an older save (no heat at all) still loads
old = dict(st)
for k_ in ("heat_walls", "heat_units"):
    old.pop(k_, None)
old["inputs"] = {k: v for k, v in old["inputs"].items() if k not in ("cb_heat", "e_k", "e_cp", "e_Tin")}
t3 = cfd_tab.CFDTab(host())
t3.import_state(old)
ok(not t3.cb_heat.isChecked() and t3.heat_walls == {} and t3.e_k.text(), "a tab saved before heat transfer existed loads with it off")
# changing the program's unit system converts the tab, heat included
had = dict(t2.heat_walls)
t2.change_units("Metric (mm, kg, N, s, MPa)", "US (in, lbf, psi)", True)
ok(set(t2.heat_walls) == set(had) and all(abs(t2.heat_walls[k]["v"] - had[k]["v"]) < 1e-9 for k in had), "converting the unit system keeps the wall conditions in kelvin")
ok(t2.result is not None and t2.result.get("heat") is not None, "and the temperature result")

# ---------------------------------------------------------------------------------------------------------------------------------- the diagnostics and a failure
d = t.diagnostics_text()
ok("== Temperature" in d and "energy balance" in d and "Prandtl number" in d, "the diagnostics report has the temperature section with the energy balance")
bad = dict(t.read_heat(), k=-1.0)
r2 = {"status": "converged", "steps": 1}
mesh_ok = t.mesh
res_bad = dict(t.result)
res_bad.pop("heat", None)
cfd_tab.run_heat(mesh_ok, res_bad, bad)
ok("conductivity" in res_bad.get("heat_error", "") and "u" in res_bad, "a bad temperature setup keeps the flow and says what is wrong")
t.result = res_bad
t.show_result(res_bad)
ok("Temperature not found" in t.res_lbl.text(), "the window shows that in the result text")
res_bad2 = dict(t.result)
res_bad2.pop("heat_error", None)
cfd_tab.run_heat(mesh_ok, res_bad2, dict(t.read_heat(), walls={(" nowhere", 99): {"kind": "temp", "T": 300.0}}))
ok(any("no wall in the mesh" in n for n in res_bad2["heat"]["notes"]), "a condition on an edge that is not a wall is reported, not silently dropped")
t.result = res

# mutation: a window that forgets to convert the temperature for display must fail the picture check
orig = hu.from_si
hu.from_si = lambda q, unit, v: v
try:
    fd_bad = t.field_data()
    ok(not (abs(fd_bad["values"].min() - 20.0) < 1e-6), "mutation: without the unit conversion the picture check fails (the check can fail)")
finally:
    hu.from_si = orig

# ---------------------------------------------------------------------------------------------------------------------------------- Clear
t.worker = None
t.clear_state()
ok(t.heat_walls == {} and t.heat_list.count() == 0, "Clear (start over) takes the wall conditions away")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    for f in FAILS:
        print("  -", f)
    os._exit(1)
print("OK cfd tab heat")
os._exit(0)
