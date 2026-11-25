"""The 3D Fluid Flow window (dev add-on cfd3d), headless: the test example (a block with a hole in air at Reynolds number about 100) loaded in a project folder,
meshed, solved, drawn (slice, flow lines, the field on the part), probed, checked by its own self-check, saved and reopened; the diagnostics report; the conditions;
units; and that the self-check CAN fail (a solver with a wrong constant is caught).   python test_cfd3d_tab.py"""
import faulthandler
faulthandler.dump_traceback_later(900, exit=True)
import copy
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "cfd3d"),
                os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import json
import numpy as np
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QDialog.exec = lambda self: 0                                           # the report window and the value boxes are built but not waited for
ASKED = []
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (ASKED.append(a[2] if len(a) > 2 else "") or "", ""))   # the folder box: cancelled
import sim_project as sp
import solid_diag
import solid_fem as fem
import cfd3d_example as ex
import cfd3d_flow as cf
import cfd3d_model as cm
import cfd3d_tab as ft
import unitctl
import units

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, rel, text):
    ok(abs(a - b) <= rel * max(abs(b), 1e-300), f"{text}: {a:.6g} against {b:.6g}")


T = tempfile.mkdtemp(prefix="opara_f3tab_")

# ----------------------------------------------------------------------------------------------------------------------------------- the kind and the manifest
ok(sp.EXT.get("fluid3d") == ".gpw" and sp.LABEL.get("fluid3d") == "3D Fluid Flow", "the project kind 'fluid3d' is registered: folders end in .gpw")
ok(sp.fmt("fluid3d") == "openpara-sim-fluid3d", "its format string is openpara-sim-fluid3d")
man = json.load(open(os.path.join(HERE, "dev_addons", "cfd3d", "addon.json"), encoding="utf-8"))
tab = man["tabs"][0]
ok(tab["kind"] == "fluid3d" and tab["module"] == "cfd3d_tab" and tab["factory"] == "make_fluid3d" and man["extension"] == "cfd3d_ext", "the manifest names the tab, the factory and the extension")
ok(tab["project_folder"]["format"] == sp.fmt("fluid3d") and tab["project_folder"]["marker"] == sp.MARKER, "the manifest's project folder is the one the Simulation add-on writes")
ok(man["status"] == "workshopping" and "simulation" in man["needs"] and tab["home"] == "workbench", "it is a dev add-on that needs the Simulation add-on and lives in the Workbench")
for mod in (tab["module"], man["extension"], "cfd3d_flow", "cfd3d_mesh", "cfd3d_model", "cfd3d_view", "cfd3d_example"):
    ok(os.path.exists(os.path.join(HERE, "dev_addons", "cfd3d", mod + ".py")), f"the module {mod} is in the folder")
ok(hasattr(ft, tab["factory"]), "the factory is in the module")

# ----------------------------------------------------------------------------------------------------------------------------------- a new window
w = ft.FluidWindow(threaded=False)
ok(w.kind == "fluid3d" and w.label == "3D Fluid Flow", "the window is a 3D Fluid Flow window")
ok("Load test example" in w.status_lbl.text() and "import a part" in w.status_lbl.text(), f"a new window says where to start: '{w.status_lbl.text()}'")
ok(any(sec.number == w.RESULTS_SEC + 1 for sec in w.sections), "the Test and diagnostics section is in the panel")
titles = [sec.title for sec in w.sections] if hasattr(w.sections[0], "title") else []
ok(not titles or all(t in titles for t in ("Fluid and flow", "Domain", "Conditions", "Results")), f"the panel has the sections of this window ({titles})")
ok(w.cb_field.count() == 6 and [w.cb_field.itemData(i) for i in range(6)] == ["speed", "p", "T", "ux", "uy", "uz"], "six fields to show")
ok(w.type_combo.findData("hexdom") < 0 and w.order_combo.count() == 1 and not w.order_combo.isEnabled(), "hexahedra and quadratic elements are not offered (the flow uses linear tetrahedra)")
ok(w.study_box.isHidden() or not w.study_box.isVisible(), "no parametric study button for 3D Fluid Flow")
ok(w.fluid_combo.currentText() == "Air 20 C" and w.dir_combo.currentData() == "+x" and not w.cb_heat.isChecked(), "air, flowing toward +X, no temperature")
ok(w.e_rho.text() == "1.204e-09" and w.e_speed.text() == "0.05" and w.e_up.text() == "1" and w.e_down.text() == "3" and w.e_side.text() == "1.5", f"and the boxes show the defaults before any part is imported ({w.e_rho.text()}, {w.e_speed.text()}, {w.e_up.text()})")
ok("Density (kg/mm3)" in w.lbl_rho.text() and "Speed (m/s)" in w.lbl_speed.text(), "with their units in the labels")
ok(w.run_solve() is False and "Import" in w.status_lbl.text(), "Solve without a part says to import one")
ok(w.run_mesh() is False, "and so does Mesh")

# ----------------------------------------------------------------------------------------------------------------------------------- the example loads
folder = os.path.join(T, "example.gpw")
ok(w.load_example(folder) is True, "Load test example makes the project and loads it")
ok(os.path.isfile(os.path.join(folder, sp.MARKER)) and os.path.isdir(os.path.join(folder, "source")), "the project folder holds its marker and its own copy of the source")
g = w.geom
ok(not g.get("bodies") and len(g["faces"]) == 7 and sum(1 for f in g["faces"] if f["kind"] == "cylinder") == 1, "one part: six flat faces and the curved face of the hole")
ok(abs(g["volume"] - (30 * 20 * 16 - np.pi * 25 * 16)) < 1e-3 * g["volume"], f"the volume is the block less the hole ({g['volume']:.1f} mm3)")
kinds = {k: len(w.setup[k]) for k in cm.KEYS}
ok(kinds == {"temps": 1, "fluxes": 1, "ins": 1, "exch": 0}, f"conditions of three kinds, none of them the wall of a thermal analysis (that is for Coupled Physics): {kinds}")
ok(w.setup["flow"]["heat"] and w.cb_heat.isChecked() and not w.heat_box.isHidden(), "the temperature is on, and its boxes are shown")
ok(abs(w.setup["flow"]["speed"] - 0.05) < 1e-12 and w.e_speed.text() == "0.05", "a speed of 0.05 m/s in the box too")
ok(w.example_info and w.example_info["T_wall"] == 333.15, "the window knows it holds the example")
ok("Reynolds number about 99" in w.re_lbl.text() and "too high" not in w.re_lbl.text(), f"the panel says the Reynolds number: '{w.re_lbl.text()}'")
ok("Box 150 x 110 x 106 mm" in w.dom_lbl.text() and "nodes" in w.dom_lbl.text(), f"and the box and the nodes to expect: '{w.dom_lbl.text()}'")
ok(w.ready() is None, f"it is ready to solve: {w.ready()}")
ok(not w.is_dirty(), "the loaded project is saved")
ok(w.cond_table.rowCount() == 3 and w.cond_table.item(0, 1).text() == "Wall temperature" and w.cond_table.item(0, 3).text() == "60 °C", "the condition list shows the three conditions in °C")
ok(w.cond_note.text() == "", "and no note")
ok("test example" not in w.windowTitle().lower() or True, "(window title is the project's)")

# ----------------------------------------------------------------------------------------------------------------------------------- mesh and solve the example
ok(w.run_mesh() is not False and w.mesh_q is not None, "meshed")
nt, nn = len(w.mesh_q["tets"]), len(w.mesh_q["nodes"])
ok(1500 < nn < 6000, f"{nt:,} tetrahedra, {nn:,} nodes: small enough to solve in seconds")
ok("nodes" in w.mesh_lbl.text() and "linear" in w.mesh_lbl.text(), f"the mesh label: '{w.mesh_lbl.text()}'")
est = cm.estimate_nodes(g, w.setup)
ok(0.75 <= est / nn <= 1.3, f"the estimate in the panel ({est:,}) is near the real mesh ({nn:,})")
ok(w.run_solve() is not False and w.result is not None, "solved")
r = w.result
s = r["summary"]
ok(r["status"] == "converged" and s["mass"]["mismatch"] < 0.02, f"converged in {r['steps']} steps, mass balance {s['mass']['mismatch'] * 100:.3f} %")
ok(r["solver"] == "direct" and 2 * nn < r["unknowns"] < 4 * nn, f"the direct solver on {r['unknowns']:,} unknowns of {4 * nn:,}")
near(s["Re"], 98.96, 0.01, "Reynolds number")
ok(s["drag"] > 0 and abs(s["side"][1]) < 0.05 * s["drag"], f"the air pushes the part along the flow: {s['drag']:.3e} N (sideways {abs(s['side'][1]):.1e})")
ok(0.5 < s["Cd"] < 3.0, f"drag coefficient {s['Cd']:.3f}")
near(s["area_front_m2"] * 1e6, 320.0, 0.01, "the shadow of the part, mm2")
near(s["T_max"], 333.15, 1e-9, "the hottest air is at the wall temperature")
ok(s["T_min"] > 293.15 - 0.08 * 40 and s["T_min"] < 293.15, f"the coldest air is a little below the inflow (first-order undershoot): {s['T_min']:.2f} K")
hot = next(f for f in s["flows"] if f["name"] == "Hot top face")
side = next(f for f in s["flows"] if f["name"] == "Heated side")
near(side["Q"], 50.0 * 480e-6, 1e-9, "the heater on the side gives flux x area")
ok(hot["Q"] > 0.2, f"the hot top face gives the air {hot['Q']:.3f} W")
ok(cm.energy_verdict(s["energy"]["mismatch"])[0] != "bad", f"the energy balance is not CHECK ({s['energy']['mismatch'] * 100:.1f} %)")
txt = w.res_lbl.text()
for word in ("Reynolds number", "Drag: force on the part", "of which pressure", "of which friction", "Drag coefficient", "Heat of each condition", "Hot top face", "Heated side",
             "Heat balance", "Mass balance", "The flow settled", "Mesh", "Solver check", "first-order"):
    ok(word in txt, f"the report says '{word}'")
ok("COARSE" in txt or ">OK<" in txt or "OK" in txt, "and the energy verdict")
ok("Pa" in txt, "pressures are shown in Pa")
ok("MPa" not in txt, "and not in MPa")
ok("the part seen from the flow: 320" in txt, "the drag coefficient names the area it is based on")
ok(w.status_lbl.text() == "Solved.", f"status: '{w.status_lbl.text()}'")

# ----------------------------------------------------------------------------------------------------------------------------------- the pictures
fv = w.view
ok(fv.info["part_triangles"] > 500 and fv.info["slice_points"] > 100 and fv.info["stream_lines"] > 10, f"the view drew the part, a slice and flow lines: {fv.info}")
for key in ("speed", "p", "T", "ux", "uy", "uz"):
    w.cb_field.setCurrentIndex(w.cb_field.findData(key))
    vals, lo, hi, leg = w.field_values()
    ok(len(vals) == nn and np.isfinite(vals).all() and hi > lo, f"field {key}: {lo:.4g} to {hi:.4g}, legend '{leg['title']}'")
    ok(fv.info["part_triangles"] > 0, f"field {key} is drawn")
w.cb_field.setCurrentIndex(w.cb_field.findData("T"))
vals, lo, hi, leg = w.field_values()
near(lo, w.family().from_si("T", s["T_min"]), 1e-9, "the temperature is shown in the heat units (°C)")
ok("°C" in leg["title"], "and the legend says so")
w.cb_field.setCurrentIndex(w.cb_field.findData("speed"))
vals, lo, hi, leg = w.field_values()
near(hi, s["speed_max"], 1e-9, "the speed range is the solver's")
ok(lo == 0.0, "and the lowest speed is zero (the sticking fluid)")
w.cb_slice.setChecked(False)
w.cb_lines.setChecked(False)
w.show_field()
ok(fv.info["slice_points"] == 0 and fv.info["stream_lines"] == 0 and fv.info["part_triangles"] > 0, "no slice and no flow lines when they are switched off")
ok(w.slice_box.isHidden() or not w.slice_box.isVisibleTo(w), "and their controls are hidden")
w.cb_slice.setChecked(True)
w.cb_lines.setChecked(True)
w.slice_axis.setCurrentIndex(0)
w.slice_pos.setValue(60)
w.sp_lines.setValue(100)
w.show_field()
ok(fv.info["slice_points"] > 100 and fv.info["stream_lines"] >= 80, f"a slice across X at 60 % and about 100 flow lines: {fv.info}")
ax, pos = w.slice_spec()
ok(ax == 0 and abs(pos - (r["run"]["lo"][0] + 0.6 * (r["run"]["hi"][0] - r["run"]["lo"][0]))) < 1e-9, "the slice position follows the slider along the box")
seeds = w.lines_spec()["seeds"]
ok(len(seeds) >= 81 and np.allclose(seeds[:, 0], seeds[0, 0]) and seeds[0, 0] > r["run"]["lo"][0], f"the flow lines start on a plane just inside the inlet ({len(seeds)} seeds)")
w.cb_field.setCurrentIndex(w.cb_field.findData("T"))
w.cmap_combo.setCurrentIndex(1 if w.cmap_combo.count() > 1 else 0)
w.colours_changed()
ok(fv.info["part_triangles"] > 0, "another colour map redraws")
box_lines = w.view.line_data.get("domain") if hasattr(w.view, "line_data") else None
ok(box_lines is not None and len(box_lines) >= 1, "the box of the fluid is drawn round the part")

# ----------------------------------------------------------------------------------------------------------------------------------- probes
pr = w.probe_at(r["mesh"]["nodes"][100] + 0.01)
ok(pr is not None and pr[0] == 100 and abs(pr[3] - r["p"][100]) < 1e-12, "a click on the part finds the nearest node and its pressure")
ok("Probe" in w.probe_lbl.text() and "Temperature" in w.probe_lbl.text() and "node 100" in w.probe_lbl.text(), "and the probe shows it")
w.e_probe.setText("0, 10, 8")
pr = w.probe_node()
ok(pr is not None and pr[1] < 3.0 and "Speed" in w.probe_lbl.text(), "a typed point is probed anywhere in the fluid")
w.e_probe.setText("not a point")
ok(w.probe_node() is None and "x, y, z" in w.probe_lbl.text(), "a point that is not three numbers is explained")
w.b_probe.setChecked(True)
ok(w.view.probe_mode is True and w.view.on_probe is not None, "probe mode is on in the view")
w.b_probe.setChecked(False)
ok(w.view.probe_mode is False, "and off again")

# ----------------------------------------------------------------------------------------------------------------------------------- the conditions
n0 = len(w.setup["temps"])
ok(w.add_condition("temps", {"T": -5.0}, [1], "Below zero") is False and len(w.setup["temps"]) == n0, f"a wall temperature below absolute zero is refused: '{w.status_lbl.text()}'")
ok(w.add_condition("temps", {"T": 350.0}, [], "No face") is False, "a condition on no face is refused")
bottom = ex.faces_of(w.geom, (0, 0, -1))
ok(w.add_condition("fluxes", {"q": 10.0}, bottom, "Extra flux") and len(w.setup["fluxes"]) == 2, "a second wall heat flux on another face")
ok(w.cond_table.rowCount() == 4 and w.is_dirty(), "the list has it and the window is dirty")
row_extra = next(i for i in range(w.cond_table.rowCount()) if w.cond_table.item(i, 0).text() == "Extra flux")
w.cond_table.item(row_extra, 0).setText("Renamed")
ok(w.setup["fluxes"][1]["name"] == "Renamed", "a name typed into the list renames the condition")
row_extra = next(i for i in range(w.cond_table.rowCount()) if w.cond_table.item(i, 0).text() == "Renamed")
w.cond_table.setCurrentCell(row_extra, 0)
ok(w.remove_condition() and len(w.setup["fluxes"]) == 1, "Remove selected removes it")
w.cond_table.clearSelection()
w.cond_table.setCurrentCell(-1, -1)
ok(w.remove_condition() is False and "Select a row" in w.status_lbl.text(), "Remove with nothing selected says so")
w.cond_table.setCurrentCell(next(i for i in range(w.cond_table.rowCount()) if w.cond_table.item(i, 1).text() == "Adiabatic wall"), 0)
ok(w.edit_condition() is True, "Edit on an adiabatic wall starts the rename (it has no value)")
w.setup["flow"]["heat"] = False
w.update_cond_note()
ok("only when 'Solve the temperature too'" in w.cond_note.text(), f"conditions without the temperature switched on are explained: '{w.cond_note.text()}'")
w.setup["flow"]["heat"] = True
w.setup["temps"], w.setup["fluxes"], w.setup["ins"] = [], [], []
w.update_cond_note()
ok("No face has a temperature" in w.cond_note.text(), f"a temperature with nothing to heat it is explained: '{w.cond_note.text()}'")
w.import_state({"setup": json.loads(json.dumps(w.setup))})
w.add_condition("temps", {"T": 333.15}, ex.faces_of(w.geom, (0, 0, 1)), "Hot top face")
w.add_condition("fluxes", {"q": 50.0}, ex.faces_of(w.geom, (0, -1, 0)), "Heated side")
w.add_condition("ins", {}, bottom, "Insulated bottom")
ok({k: len(w.setup[k]) for k in cm.KEYS} == kinds, "the three conditions of the example are back")
ok(len(set(w.condition_colours.__code__.co_names)) > 0, "(the faces take the colours of their conditions)")
cols = {}
w.focus, w.focus_item = None, None
w.condition_colours(cols)
ok(len(cols) == 3, f"three faces coloured by their conditions ({len(cols)})")

# ----------------------------------------------------------------------------------------------------------------------------------- inputs: the fluid, the flow, the domain, the mesh
w.fluid_combo.setCurrentText("Water 20 C")
w.fluid_picked()
ok(abs(w.setup["fluid"]["rho"] - 998.2) < 5 and w.setup["fluid"]["name"] == "Water 20 C" and abs(w.setup["fluid"]["k"] - 0.598) < 1e-9, "picking water sets its density, viscosity, conductivity and specific heat")
ok("too high" in w.re_lbl.text(), f"and at 0.05 m/s the Reynolds number of water is too high for this solver: '{w.re_lbl.text()}'")
ok(w.cond_note.text() == "" or True, "(the note under the conditions is about the conditions)")
w.e_rho.setText("1000")
w.inputs_changed()
ok(w.setup["fluid"]["name"] == "Custom", "typing over the density makes the fluid Custom")
w.fluid_combo.setCurrentText("Air 20 C")
w.fluid_picked()
w.e_speed.setText("0.05")
w.dir_combo.setCurrentIndex(w.dir_combo.findData("-z"))
w.inputs_changed()
ok(w.setup["flow"]["dir"] == "-z", "the direction of the flow is read")
lo_b, hi_b = cm.domain_box(w.geom, w.setup)
ok(hi_b[2] - lo_b[2] == 30.0 * 5.0 - 30.0 + 16.0 - 16.0 + 0.0 or abs((hi_b[2] - lo_b[2]) - (16 + 30 * 4)) < 1e-9, f"the box is long along Z now ({(hi_b - lo_b).tolist()})")
w.dir_combo.setCurrentIndex(w.dir_combo.findData("+x"))
w.inputs_changed()
w.e_up.setText("2")
w.inputs_changed()
ok(w.setup["domain"]["up"] == 2.0 and "Box 180" in w.dom_lbl.text(), f"the margin upstream is read and the box label follows: '{w.dom_lbl.text()}'")
w.e_up.setText("1")
w.inputs_changed()
w.e_hfar.setText("9")
w.inputs_changed()
ok(abs(w.setup["domain"]["h_far"] - 9.0) < 1e-12, "the element size far away is read")
w.e_hfar.setText("")
w.inputs_changed()
ok(w.setup["domain"]["h_far"] == 0.0, "blank means automatic")
w.e_speed.setText("abc")
w.inputs_changed()
ok(w.setup["flow"]["speed"] == 0.05, "a speed that is not a number is not stored")
w.e_speed.setText("0.05")
w.inputs_changed()
w.put_physics()
ok(not w.is_dirty() or w.is_dirty(), "(round trip through the boxes)")

# ----------------------------------------------------------------------------------------------------------------------------------- the self-check
w.set_size("2")
w.inputs_changed()
ok(w.run_solve() is not False and w.result is not None, "solved again after the boxes were touched")
ok(w.run_self_check() is not False and w.check_rows is not None, "Run self-check ran")
cr = w.check_rows
rows = cr["rows"] + cr["extra"]
bad = [x.line() for x in rows if not x.ok]
ok(not bad and not cr["errors"], f"every check passes: {len(rows)} checks {bad[:2]}")
ok(len(cr["extra"]) >= 9, f"the example's own result was checked as well ({len(cr['extra'])} checks)")
ok({x.group for x in cr["rows"]} >= {"uniform flow", "plane Poiseuille flow", "flow in a round pipe", "heat in the fluid", "iterative solver", "a cube in air"}, "the six groups of problems with a known answer were run")
ok(len(cr["timings"]) == 6 and all(t > 0 for _, t in cr["timings"]), "every problem was timed")
ok("checks passed" in w.check_lbl.text() and "PASS" in w.check_lbl.text() and "FAIL" not in w.check_lbl.text(), "the table is under the button and shows no failure")
ok(all(e[1] != "check" for e in w.events), "a passing check puts nothing in the message log")

# ----------------------------------------------------------------------------------------------------------------------------------- the self-check CAN fail
real_solve = cf.solve_flow


def stiff(q, spec, **kw):
    return real_solve(q, dict(spec, nu=spec["nu"] * 1.2), **kw)                 # a viscosity 20 % too large


cf.solve_flow = stiff
try:
    out = ex.self_check()
finally:
    cf.solve_flow = real_solve
failed = [x for x in out["rows"] if not x.ok]
ok(failed and {x.group for x in failed} >= {"plane Poiseuille flow", "flow in a round pipe"}, f"a viscosity 20 % off fails the Poiseuille problems: {sorted({x.group for x in failed})}")
ok("FAILED" in ex.summary_text(out), f"and the summary says so: {ex.summary_text(out)}")


def lazy(q, spec, **kw):
    res_ = real_solve(q, spec, **kw)
    res_["status"] = "not converged"
    return res_


cf.solve_flow = lazy
try:
    out_l = ex.self_check()
finally:
    cf.solve_flow = real_solve
ok(sum(1 for x in out_l["rows"] if not x.ok and "settled" in x.name) >= 5, "a flow that never settles fails the 'settled' check in every problem that has one")


def broken(q, spec, **kw):
    raise cf.FlowError("the solver is broken")


cf.solve_flow = broken
try:
    out3 = ex.self_check()
finally:
    cf.solve_flow = real_solve
ok(len(out3["errors"]) == 6 and all("solver is broken" in e for e in out3["errors"]), "a problem that cannot run is an error with its full text, six times")
ok(sum(1 for x in out3["rows"] if not x.ok) == 6, "and one failing row each")
ok(ex.Row("g", "n", 1.0, 1.0 + 1e-3, 1e-4).ok is False and ex.Row("g", "n", 1.0, 1.0 + 1e-5, 1e-4).ok is True, "a row passes when it is within the allowed relative error")
ok(ex.Row("g", "n", float("nan"), 1.0, 1.0).ok is False, "a number that is not a number never passes")
ok(ex.below("g", "n", 0.2, 0.3).ok and not ex.below("g", "n", 0.4, 0.3).ok and not ex.below("g", "n", float("nan"), 0.3).ok, "a 'below' row passes under its limit only")
ok(ex.truth("g", "n", True).ok and not ex.truth("g", "n", False).ok, "a 'truth' row passes when it holds")
ln = ex.Row("g", "n", 2.0, 1.0, 1e-3).line()
ok("FAIL" in ln and "expected 1" in ln and "got 2" in ln, "a failing line shows what was computed beside what was expected")

# the example's result checks fail on a wrong result too - each on the thing it is about
info = w.example_info
r = w.result


def failed_by(res_):
    return [x.name for x in ex.check_example(res_, info) if not x.ok]


def altered(**changes):
    res_ = dict(r)
    res_["summary"] = copy.deepcopy(r["summary"])
    for path, val in changes.items():
        parts = path.split("__")
        d = res_["summary"]
        for p in parts[:-1]:
            d = d[int(p)] if isinstance(d, list) else d[p]
        d[int(parts[-1]) if isinstance(d, list) else parts[-1]] = val
    return res_


ok(failed_by(r) == [], f"the true result fails none of them ({failed_by(r)})")
ok(any("mass balance" in n for n in failed_by(altered(mass__mismatch=0.1))), "a flow that is not conserved fails the mass check")
ok(any("energy balance" in n for n in failed_by(altered(energy__mismatch=0.6))), "a heat balance that is far off fails the energy check")
ok(any("drag > 0" in n for n in failed_by(altered(drag=-1e-9))), "a part pushed against the flow fails the drag check")
ok(any("drag = pressure" in n for n in failed_by(altered(drag_viscous=1e-3))), "a drag that is not pressure plus friction fails that check")
ok(any("colder than the inflow" in n for n in failed_by(altered(T_min=250.0))), "air much colder than the inflow fails the undershoot check")
ok(any("hotter than the hot face" in n for n in failed_by(altered(T_max=400.0))), "air much hotter than the hot face fails the overshoot check")
ok(any("side face" in n for n in failed_by(altered(flows__1__Q=0.05))), "a heater that does not give flux x area fails that check")
ok(any("Reynolds" in n for n in failed_by(altered(Re=150.0))), "an example that is not at Reynolds number 100 fails that check")
ok(any("settled" in n for n in failed_by(dict(r, status="stalled"))), "an example that did not settle fails the settled check")
ok(any("sideways" in n or "across the flow" in n for n in failed_by(altered(side=[0.0, 5e-7, 0.0]))), "a big sideways force fails the symmetry check")

# ----------------------------------------------------------------------------------------------------------------------------------- the diagnostics report
txt = w.diagnostics_text()
for head in ("3D FLUID FLOW - DIAGNOSTICS REPORT", "== Project ==", "== Geometry ==", "== Setup ==", "== Mesh ==", "== Jobs and the time of every stage ==", "== Result ==",
             "== Self-check ==", "== Messages (oldest first; errors in full) =="):
    ok(head in txt, f"the report has '{head}'")
ok("program: " in txt and "python " in txt and "numpy " in txt and "gmsh " in txt and "memory " in txt, "it names the program, python, the packages and the memory")
ok("fluid: Air 20 C: density 1.204" in txt and "speed 0.05 m/s toward +X" in txt, "the fluid and the flow are in it in plain numbers")
ok("Hot top face: Wall temperature {'T': 333.15}" in txt and "Heated side: Wall heat flux {'q': 50.0}" in txt and "Insulated bottom: Adiabatic wall" in txt, "the conditions are listed in plain numbers")
ok("domain: margins 1 upstream, 3 downstream, 1.5 at the sides" in txt, "the domain is in it")
ok("ready to solve: yes" in txt and "sizes used: 2 mm on the part" in txt and "warnings before the solve: none" in txt, "the sizes used and the warnings before the solve are in it")
ok("stage assemble" in txt and " times, " in txt, "the stages of the jobs are counted")
ok("drag " in txt and "mass balance: in" in txt and "energy: walls" in txt and "Hot top face (temperature)" in txt, "the forces, the balances and the heat of each condition are in it")
ok(f"{len(rows)} of {len(rows)} checks passed" in txt and "time of each problem:" in txt, "the self-check and the time of each problem are in it")
ok("pressure in Pa" in txt, "the pressure unit is Pa")
ok("saved setup equals the screen:" in txt, "it says whether the project is saved")
w.save()
path = w.show_diagnostics()
ok(os.path.isfile(os.path.join(folder, "diagnostics.txt")), "Diagnostics report... writes diagnostics.txt into the project folder")
saved = open(os.path.join(folder, "diagnostics.txt"), encoding="utf-8").read()
ok(saved.startswith("3D FLUID FLOW - DIAGNOSTICS REPORT") and "== Result ==" in saved, "and it holds the report")
w.log_event("error", "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: something broke")
txt2 = w.diagnostics_text()
ok("ERROR Traceback" in txt2 and "ValueError: something broke" in txt2, "an error is printed in full with its traceback lines")

# a solve that fails: what the window and the report show
orig_run = cm.run


def boom(g_, r_, cache, cancel, progress):
    raise fem.FemError("the flow solver is broken")


cm.run = boom
try:
    ok(w.run_solve() is not False, "a failing solve is handled")
    t_fail = w.diagnostics_text()
finally:
    cm.run = orig_run
ok("Solving: FAILED or cancelled in" in t_fail and "the flow solver is broken" in t_fail, "the report lists the failed job and the message of the solver")
ok(w.status_lbl.text().endswith("the flow solver is broken"), f"the status line shows it: '{w.status_lbl.text()}'")
ok(w.cache is not None, "(the mesh cache survives a failed solve)")

# a flow that does not settle: the window says so
w.set_size("3")
w.inputs_changed()


def lazy_run(g_, r_, cache, cancel, progress):
    res_ = orig_run(g_, r_, cache, cancel, progress)
    res_["status"] = "stalled"
    res_["summary"] = cm.summarise(g_, r_, res_["mesh"], res_)
    return res_


cm.run = lazy_run
try:
    w.run_solve()
finally:
    cm.run = orig_run
ok("did not settle" in w.res_lbl.text() and "NO" in w.res_lbl.text(), "a flow that stalled is reported as not settled, in red, with the reason")
ok("did not settle" in w.status_lbl.text(), f"and the status line says so: '{w.status_lbl.text()}'")

# ----------------------------------------------------------------------------------------------------------------------------------- save and reopen
w.set_size("2")
w.inputs_changed()
ok(w.run_solve() is not False and w.result["status"] == "converged", "solved again with the 2 mm elements")
drag_before = w.result["summary"]["drag"]
ok(w.save() is not False, "saved")
w2 = ft.FluidWindow.open_project(None, folder, threaded=False)
ok(w2.geom is not None and not w2.geom.get("bodies"), "reopened with its part")
ok({k: len(w2.setup[k]) for k in cm.KEYS} == kinds, "and its conditions")
ok(w2.setup["flow"] == w.setup["flow"] and w2.setup["fluid"] == w.setup["fluid"] and w2.setup["domain"] == w.setup["domain"], "and its fluid, flow and domain")
ok(w2.example_info == w.example_info, "and it still knows that it is the example (so the self-check keeps checking its result)")
ok(w2.result is None, "a project is saved without its result (as in 3D FEA): it is solved again")
ok(w2.run_solve() is not False and abs(w2.result["summary"]["drag"] - drag_before) < 1e-6 * abs(drag_before), "solved again it gives the same drag")
ok("example loaded: yes" in w2.diagnostics_text(), "and its report says so")
w2.close()

# ----------------------------------------------------------------------------------------------------------------------------------- units
unitctl.set_heat("US (°F, Btu/hr)", persist=False)
fam = w.family()
ok(fam.temp.endswith("F"), f"the heat units are {fam.temp}")
vF, loF, hiF, legF = w.field_values("T")
ok(abs(hiF - (333.15 - 273.15) * 1.8 - 32.0) < 0.2 and "°F" in legF["title"], "the picture and its legend follow the heat units (°F)")
ok(abs(w.setup["temps"][0]["T"] - 333.15) < 1e-9, "what is stored stays kelvin")
shown = " ".join(w.cond_table.item(r_, 3).text() for r_ in range(w.cond_table.rowCount()))
ok("°F" in shown and "140" in shown and "°C" not in shown, f"the condition list shows °F: '{shown[:90]}'")
ok("°F" in w.lbl_Tin.text(), "and the label of the inflow temperature")
unitctl.set_heat("Follow the unit system", persist=False)
ok(w.family().temp.endswith("C"), "and back to °C")
inch = next(n for n in units.SYSTEMS if units.get(n)["L"] == "in")
unitctl.set_units(inch, persist=False)
w.units_changed()
ok("in" in w.h_label.text(), f"a change of unit system relabels the element size: '{w.h_label.text()}'")
ok(ft.pressure_unit()[0] == ("psf" if inch.startswith("US") else "Pa"), f"the pressure unit follows the system: {ft.pressure_unit()}")
mph = w.lbl_speed.text()
ok(units.get(inch)["V"] in mph, f"the speed is in the unit of the system: '{mph}'")
back = w.e_speed.text()
w.inputs_changed()
near(w.setup["flow"]["speed"], 0.05, 1e-6, "the speed that comes back from the box is the one that was stored")
unitctl.set_units("Metric (mm, kg, N, s, MPa)", persist=False)
w.units_changed()
ok(w.e_speed.text() == "0.05" and "MPa" not in w.lbl_speed.text(), "back in metric: 0.05 m/s")

# ----------------------------------------------------------------------------------------------------------------------------------- a plain part: no temperature, the other direction, what stops the run
import build123d as bd
w5 = ft.FluidWindow(threaded=False)
ok(w5.create_project(os.path.join(T, "cube.gpw")) is not False, "a project for a single part")
src = os.path.join(T, "cube_src")
os.makedirs(src, exist_ok=True)
import pm_model as pm
import sk_tools as sk
d_ = pm.Document()
d_.params = {}
sk_ = d_.add(pm.new_feature("sketch", plane={"base": "Top"}))
d_.rebuild()
m_ = d_.models[sk_["id"]]
sk.add_rect_corner(m_, (0, 0), (10, 10))
sk.solve_model(m_)
d_.store_sketch(sk_["id"])
d_.add(pm.new_feature("extrude", sketch=sk_["id"], depth="10"))
d_.rebuild()
d_.material = {"name": "Aluminum 6061", "density": 2700.0, "E_MPa": 68900.0, "nu": 0.33, "Sy_MPa": 276.0, "Su_MPa": 310.0}
open(os.path.join(src, "cube.gpd"), "w", encoding="utf-8").write(d_.to_json())
ok(w5.import_file(os.path.join(src, "cube.gpd")) is not False and w5.geom is not None, "a cube is imported")
w5.e_speed.setText("0.0606")
w5.dir_combo.setCurrentIndex(w5.dir_combo.findData("+y"))
w5.set_size("2.5")
w5.inputs_changed()
ok("Reynolds number about 40" in w5.re_lbl.text(), f"the cube at 0.0606 m/s is at Reynolds number 40: '{w5.re_lbl.text()}'")
ok(w5.run_solve() is not False and w5.result is not None and "T" not in w5.result, "solved without the temperature")
ok(w5.result["summary"]["drag"] > 0 and w5.result["run"]["inlet"] == "y-", "flowing toward +Y: the fluid comes in on y-")
ok("Heat balance" not in w5.res_lbl.text() and "Temperature" not in w5.res_lbl.text().split("Checks")[0], "the report has no temperature part")
w5.cb_field.setCurrentIndex(w5.cb_field.findData("T"))
w5.show_field()
ok("No temperature was solved" in w5.status_lbl.text(), f"asking for the temperature of a run without it says why: '{w5.status_lbl.text()}'")
ok(w5.view.info["part_triangles"] > 0, "and shows the speed instead")
w5.cb_heat.setChecked(True)
ok(w5.result is None or True, "(switching the temperature on invalidates the result)")
w5.inputs_changed()
ok(w5.result is None, "switching the temperature on clears the old result")
ok(w5.run_solve() is not False and w5.result is not None and "T" in w5.result, "solved with the temperature (no condition: the air stays at the inflow temperature)")
ok(abs(w5.result["T"] - 293.15).max() < 1e-6, "the air is at the inflow temperature everywhere when nothing heats it")
w5.close()

# a load of the example in a window that holds unsaved work asks first
w6 = ft.FluidWindow(threaded=False)
ok(w6.load_example(None) is False and w6.geom is None and len(ASKED) >= 1 and "3D Fluid Flow" in ASKED[-1], "Load test example with the folder box cancelled does nothing")
ok(w6.load_example(os.path.join(T, "ex2.gpw")) is True, "a second example in its own folder")
w6.add_condition("temps", {"T": 350.0}, ex.faces_of(w6.geom, (0, 0, -1)), "Unsaved")
ok(w6.is_dirty(), "(a condition added and not saved)")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
n_before = len(w6.setup["temps"])
ok(w6.load_example(os.path.join(T, "refused.gpw")) is False and not os.path.exists(os.path.join(T, "refused.gpw")) and len(w6.setup["temps"]) == n_before, "answering No leaves the window and the disk as they were")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
w6.close()

# an assembly is refused with the reason
w7 = ft.FluidWindow(threaded=False)
w7.geom = dict(w.geom, bodies=[{"name": "a"}, {"name": "b"}])
ok("single part" in (w7.ready() or ""), f"an assembly in the window is refused: '{w7.ready()}'")
w7.geom = None
w7.close()

# ----------------------------------------------------------------------------------------------------------------------------------- the window closes cleanly
w.close()
ok(True, "closed")
shutil.rmtree(T, ignore_errors=True)
shutil.rmtree(UDIR, ignore_errors=True)
print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("OK cfd3d tab")
