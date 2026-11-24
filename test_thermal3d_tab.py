"""The 3D Thermal window (dev add-on thermal3d), headless: the test example (an assembly of four bodies) loaded in a project folder, solved, checked by its own
self-check, saved and reopened; the diagnostics report; conditions and what stops a solve; units; the picture slider, the animation, the probe; and that the self-check
CAN fail (a solver with a wrong constant is caught).   python test_thermal3d_tab.py"""
import faulthandler
faulthandler.dump_traceback_later(300, exit=True)
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "thermal3d"),
                os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QDialog.exec = lambda self: 0                                           # the report window is built but not waited for
ASKED = []
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (ASKED.append(a[2] if len(a) > 2 else "") or "", ""))   # the folder box: cancelled
import sim_project as sp
import solid_diag
import solid_fem as fem
import thermal3d_example as ex
import thermal3d_fem as tf
import thermal3d_model as tm
import thermal3d_tab as tt
import thermal_units as tu
import unitctl
import units

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, rel, text):
    ok(abs(a - b) <= rel * max(abs(b), 1e-300), f"{text}: {a:.6g} against {b:.6g}")


T = tempfile.mkdtemp(prefix="opara_t3tab_")

# ----------------------------------------------------------------------------------------------------------------------------------- the kind and the manifest
ok(sp.EXT.get("thermal3d") == ".gpt" and sp.LABEL.get("thermal3d") == "3D Thermal", "the project kind 'thermal3d' is registered: folders end in .gpt")
ok(sp.fmt("thermal3d") == "openpara-sim-thermal3d", "its format string is openpara-sim-thermal3d")
import json
man = json.load(open(os.path.join(HERE, "dev_addons", "thermal3d", "addon.json"), encoding="utf-8"))
tab = man["tabs"][0]
ok(tab["kind"] == "thermal3d" and tab["module"] == "thermal3d_tab" and tab["factory"] == "make_thermal3d" and man["extension"] == "thermal3d_ext", "the manifest names the tab, the factory and the extension")
ok(tab["project_folder"]["format"] == sp.fmt("thermal3d") and tab["project_folder"]["marker"] == sp.MARKER, "the manifest's project folder is the one the Simulation add-on writes")
ok(man["status"] == "workshopping" and "simulation" in man["needs"], "it is a dev add-on that needs the Simulation add-on")
for mod in (tab["module"], man["extension"], "thermal3d_fem", "thermal3d_model", "thermal3d_example"):
    ok(os.path.exists(os.path.join(HERE, "dev_addons", "thermal3d", mod + ".py")), f"the module {mod} is in the folder")

# ----------------------------------------------------------------------------------------------------------------------------------- the example loads
w = tt.ThermalWindow(threaded=False)
ok(w.kind == "thermal3d" and w.label == "3D Thermal", "the window is a 3D Thermal window")
ok("Load test example" in w.status_lbl.text() and "import a part" in w.status_lbl.text(), f"a new window says where to start: '{w.status_lbl.text()}'")
ok(any(sec.number == w.RESULTS_SEC + 1 for sec in w.sections), "the Test and diagnostics section is in the panel")
folder = os.path.join(T, "example.gpt")
ok(w.load_example(folder) is True, "Load test example makes the project and loads it")
ok(os.path.isfile(os.path.join(folder, sp.MARKER)) and os.path.isdir(os.path.join(folder, "source")), "the project folder holds its marker and its own copy of the source")
g = w.geom
ok([b["name"] for b in g["bodies"]] == ["plate<1>", "pad<1>", "fin<1>", "block<1>"], "four bodies: plate, pad, fin, block")
ok(abs(g["volume"] - (80 * 60 * 6 - 4 * np.pi * 16 * 6 - np.pi * 36 * 6 + np.pi * 144 * 10 + 2 * 40 * 30 + 12 * 16 * 12)) < 1e-3 * g["volume"], f"the volume is the sum of the parts' ({g['volume']:.1f} mm3)")
ok(sum(1 for f in g["faces"] if f["kind"] == "cylinder") == 6, "the holes and the pad make six curved faces")
kinds = {k: len(w.setup[k]) for k in tm.KEYS}
ok(kinds == {"temps": 1, "fluxes": 0, "powers": 1, "convs": 2, "rads": 2, "ins": 1}, f"conditions of five kinds: {kinds}")
ok(w.setup["analysis"] == "transient" and w.setup["theta"] == 1.0 and w.setup["steps"] == 30, "a transient run of 30 backward-Euler steps")
ok(w.setup["body_mats"].get("pad<1>", {}).get("gen") == 5e5, "the pad generates heat (500 kW/m3)")
ok(w.example_info and w.example_info["power"] == 25.0, "the window knows it holds the example")
ok(w.ready() is None, f"it is ready to solve: {w.ready()}")
ok(not w.is_dirty(), "the loaded project is saved")

# ----------------------------------------------------------------------------------------------------------------------------------- solve the example
ok(w.run_mesh() is not False and w.mesh_q is not None, "meshed")
nt, nn = len(w.mesh_q["tets"]), len(w.mesh_q["nodes"])
ok(2000 < nt < 20000, f"{nt} tetrahedra, {nn} nodes: small enough to solve in seconds")
ok(w.run_solve() is not False and w.result is not None, "solved")
r = w.result
b = r["balance"]
ok(b["relative_error"] < 1e-9, f"the heat balance closes: {b['relative_error']:.1e}")
heater = next(f for f in r["flows"] if f["kind"] == "power")
near(heater["Q"], 25.0, 1e-12, "the heater gives its 25 W")
cold = next(f for f in r["flows"] if f["kind"] == "temp")
ok(-cold["Q"] > 0.85 * (25.0 + b["generation"]), f"the cooled hole takes most of the heat: {-cold['Q']:.2f} W of {25.0 + b['generation']:.2f}")
ok(r["Tmin"] >= 293.15 - 1e-9 and r["Tmax"] > 300.0, f"temperatures from {r['Tmin']:.2f} to {r['Tmax']:.2f} K")
ok(max(r["bodies"], key=lambda x: x["Tmax"])["name"] == "Copper", "the copper pad is the hottest body")
fr = r["frames"]
ok(fr is not None and len(fr) == 31 and tm.frame_count(r) == 31 and abs(r["times"][-1] - 1800.0) < 1e-9, "31 pictures from 0 to 1800 s")
ok(np.allclose(fr[0], 293.15), "the first picture is the start temperature")
ok(r["newton"] is not None and r["newton"]["converged"] and r["newton"]["unconverged_steps"] == 0, f"radiation converged in every step ({r['newton']['iterations']} iterations)")
ok(r["run"]["solver"] == "direct", "the example is solved with the direct solver")
ok(not r["notes"], f"no warnings: {r['notes']}")
ok(not w.time_box.isHidden(), "the time slider is on for a transient result")
ok(w.slider.maximum() == 30 and w.slider.value() == 30, "the slider runs over the 31 pictures and stands on the last")

# ----------------------------------------------------------------------------------------------------------------------------------- the self-check
ok(w.run_self_check() is not False and w.check_rows is not None, "Run self-check ran")
cr = w.check_rows
rows = cr["rows"] + cr["extra"]
bad = [x.line() for x in rows if not x.ok]
ok(not bad and not cr["errors"], f"every check passes: {len(rows)} checks {bad[:2]}")
ok(len(cr["extra"]) >= 6, f"the example's own result was checked as well ({len(cr['extra'])} checks)")
ok({x.group for x in cr["rows"]} >= {"wall", "composite wall", "heat generated in a bar", "cube cooling in air (transient)", "radiating plate", "pipe wall"}, "the six problems with a closed form were run")
ok(len(cr["timings"]) == 6 and all(t > 0 for _, t in cr["timings"]), "every problem was timed")
ok("checks passed" in w.check_lbl.text() or "PASS" in w.check_lbl.text(), "the table is under the button")
ok("FAIL" not in w.check_lbl.text(), "and shows no failure")
ok(all(e[1] != "check" for e in w.events), "a passing check puts nothing in the message log (the numbers are in the report)")

# ----------------------------------------------------------------------------------------------------------------------------------- the self-check CAN fail
real_sigma = tf.SIGMA
tf.SIGMA = real_sigma * 1.05
try:
    out = ex.self_check()
finally:
    tf.SIGMA = real_sigma
failed = [x for x in out["rows"] if not x.ok]
ok(failed and all(x.group in ("radiating plate",) for x in failed), f"a Stefan-Boltzmann constant 5% too large fails the radiation checks only: {[x.name for x in failed]}")
ok("FAILED" in ex.summary_text(out), f"and the summary says so: {ex.summary_text(out)}")
real_k = tm.run
orig_run = tm.run


def skewed(g_, r_, cache, cancel, progress):
    res = orig_run(g_, r_, cache, cancel, progress)
    res["flows"] = [dict(f, Q=f["Q"] * 1.01) for f in res["flows"]]
    return res


tm.run = skewed
try:
    out2 = ex.self_check()
finally:
    tm.run = orig_run
ok(sum(1 for x in out2["rows"] if not x.ok) >= 6, f"flows that are 1% off fail in several of the problems ({sum(1 for x in out2['rows'] if not x.ok)} rows)")


def broken(g_, r_, cache, cancel, progress):
    raise fem.FemError("the solver is broken")


tm.run = broken
try:
    out3 = ex.self_check()
finally:
    tm.run = orig_run
ok(len(out3["errors"]) == 6 and all("solver is broken" in e for e in out3["errors"]), "a problem that cannot run is an error with its full text, six times")
ok(sum(1 for x in out3["rows"] if not x.ok) == 6, "and one failing row each")
ok(ex.Row("g", "n", 1.0, 1.0 + 1e-3, 1e-4).ok is False and ex.Row("g", "n", 1.0, 1.0 + 1e-5, 1e-4).ok is True, "a row passes when it is within the allowed relative error")
ok(ex.Row("g", "n", 1.0, 1.5, 0.4, relative=False).ok is False and ex.Row("g", "n", 1.0, 1.5, 0.6, relative=False).ok is True, "or the allowed absolute one")
ok(ex.Row("g", "n", float("nan"), 1.0, 1.0).ok is False, "a number that is not a number never passes")
ok("FAIL" in ex.Row("g", "n", 2.0, 1.0, 1e-3).line() and "expected 1" in ex.Row("g", "n", 2.0, 1.0, 1e-3).line() and "got 2" in ex.Row("g", "n", 2.0, 1.0, 1e-3).line(), "a failing line shows what was computed beside what was expected")

# the example's result checks can fail on a wrong result too - and each one on the thing it is about
import copy
info = w.example_info


def failed(res_):
    return [x.name for x in ex.check_example(res_, info) if not x.ok]


def with_bodies(fn):
    res_ = dict(r)
    res_["bodies"] = copy.deepcopy(r["bodies"])
    fn(res_["bodies"])
    return res_


ok(failed(r) == [], "the true result fails none of them")
bad_res = dict(r)
bad_res["balance"] = dict(r["balance"], relative_error=1e-3)
ok(any(n.startswith("heat balance") for n in failed(bad_res)), "a heat balance that does not close fails the balance check")
bad_res = dict(r)
bad_res["flows"] = [dict(f, Q=(24.0 if f["kind"] == "power" else f["Q"])) for f in r["flows"]]
ok(any("asked for on the pad" in n for n in failed(bad_res)), "a heater that does not give its 25 W fails that check")
bad_res = dict(r)
bad_res["Tmin"] = 250.0
ok(any("no point colder" in n for n in failed(bad_res)), "a part colder than the fluid fails that check")
bad_res = dict(r)
bad_res["frames"] = np.array(r["frames"])[::-1].copy()
ok(any("never cools" in n for n in failed(bad_res)), "a hottest point that cools while it is heated fails that check")
bad_res = with_bodies(lambda bs: bs[info["pad"]].__setitem__("Tmax", 280.0))
ok(failed(bad_res) == [n for n in failed(bad_res) if "hottest body" in n] and len(failed(bad_res)) == 1, f"the pad not being the hottest body fails that check only: {failed(bad_res)}")
bad_res = with_bodies(lambda bs: bs[0].__setitem__("volume_m3", bs[0]["volume_m3"] * 1.1))
ok(failed(bad_res) and all("volume of the mesh" in n for n in failed(bad_res)), f"a mesh whose volume is 7% off the geometry's fails the volume check only: {failed(bad_res)}")
bad_res = with_bodies(lambda bs: bs[info["pad"]].__setitem__("volume_m3", bs[info["pad"]]["volume_m3"] * 1.1))
ok(any("rate x its volume" in n for n in failed(bad_res)), "a pad whose volume does not match the heat it generates fails the generation check")
bad_res = dict(r)
bad_res["newton"] = dict(r["newton"], converged=False)
ok(any("Newton" in n for n in failed(bad_res)), "a radiation iteration that did not converge fails that check")

# ----------------------------------------------------------------------------------------------------------------------------------- the diagnostics report
txt = w.diagnostics_text()
for head in ("3D THERMAL - DIAGNOSTICS REPORT", "== Project ==", "== Geometry ==", "== Setup ==", "== Mesh ==", "== Jobs and the time of every stage ==", "== Result ==",
             "== Self-check ==", "== Messages (oldest first; errors in full) =="):
    ok(head in txt, f"the report has '{head}'")
ok("program: " in txt and "python " in txt and "numpy " in txt and "gmsh " in txt and "memory " in txt, "it names the program, python, the packages and the memory")
ok(all(n in txt for n in ("plate<1>", "pad<1>", "fin<1>", "block<1>")) and "assembly of 4 bodies" in txt, "it lists the four bodies")
ok("Cooled bolt hole" in txt and "Heater on the pad" in txt and "{'P': 25.0}" in txt, "the conditions are listed in plain numbers")
ok("5,560" in txt or f"{nt:,} tetrahedra" in txt, "the mesh size is in it")
ok("stage factor" in txt and " times, " in txt and txt.count("stage factor") == 1, "the 60-odd factorisations are one line (count, total, mean, longest)")
ok("heat balance W: in" in txt and "solver: {" in txt and "newton: {" in txt, "the heat balance, the solver and Newton are in it")
ok(f"{len(rows)} of {len(rows)} checks passed" in txt, "the self-check summary is in it")
ok("time of each problem:" in txt, "and the time of each problem")
ok("sizes of the bodies" in txt, "the element sizes of the bodies are given (not a misleading single size)")
ok(r["sizes"] == [4.0, 4.0, 4.0, 4.0] and "element size asked for: plate<1> 4 mm, pad<1> 4 mm, fin<1> 4 mm, block<1> 4 mm" in txt, f"the Mesh part of the report gives the size asked for in every body: {r['sizes']}")
ok("Element size" in w.res_lbl.text() and "7.59" not in w.res_lbl.text(), "the window's report gives the 4 mm of the bodies, not the automatic size it did not use")
ok("saved setup equals the screen: yes" in txt, "it says whether the project is saved")
ok("Heater on the pad (power): 25 over" in txt and f"Cooled bolt hole (temp): {cold['Q']:.8g}" in txt, "the heat through every condition is in it, with its sign")
kept_ins = list(w.setup["ins"])
w.setup["ins"] = []
ok("saved setup equals the screen: NO - changes not saved" in w.diagnostics_text(), "a change that is not saved is said so")
w.setup["ins"] = kept_ins
ok("saved setup equals the screen: yes" in w.diagnostics_text(), "and not said when it is saved again")
path = w.show_diagnostics()
ok(os.path.isfile(os.path.join(folder, "diagnostics.txt")), "Diagnostics report... writes diagnostics.txt into the project folder")
saved = open(os.path.join(folder, "diagnostics.txt"), encoding="utf-8").read()
ok(saved.startswith("3D THERMAL - DIAGNOSTICS REPORT") and "== Result ==" in saved, "and it holds the report")
ok(solid_diag.write_report(None, "x") is None and solid_diag.write_report(os.path.join(T, "nope"), "x") is None, "no folder, no file (and no error)")

# a failure is in the report in full
w.log_event("error", "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: something broke")
txt2 = w.diagnostics_text()
ok("ERROR Traceback" in txt2 and "ValueError: something broke" in txt2, "an error is printed in full with its traceback lines")

# a self-check that fails or cannot run: what the window and the report show
tf.SIGMA = real_sigma * 1.05
try:
    w.run_self_check()
finally:
    tf.SIGMA = real_sigma
ok("FAIL" in w.check_lbl.text(), "the table under the button shows FAIL")
fails_logged = [e for e in w.events if e[1] == "check"]
ok(fails_logged and all(e[2].startswith("FAIL") for e in fails_logged), f"and each failing line is in the message log ({len(fails_logged)})")
ok("FAILED" in w.status_lbl.text(), f"the status line says so: '{w.status_lbl.text()}'")
tm.run = broken
try:
    w.run_self_check()
finally:
    tm.run = orig_run
txt_bad = w.diagnostics_text()
chk_part = txt_bad.split("== Self-check ==")[1].split("== Messages")[0]
ok("the solver is broken" in chk_part and "Traceback (most recent call last):" in chk_part, "a problem that could not run is in the report's self-check part with its traceback")
ok("Traceback (most recent call last):" in txt_bad.split("== Messages")[1], "and its traceback is among the messages")
ok(w.run_self_check() is not False and all(x.ok for x in w.check_rows["rows"] + w.check_rows["extra"]), "and a self-check with the real solver passes again")

# a solve that fails: what the report shows
w.log_event("note", "marker before the failure")
orig_run2 = tm.run
tm.run = broken


def _boom(g_, r_, cache, cancel, progress):
    raise RuntimeError("something unexpected in the solver")


try:
    ok(w.run_solve() is not False, "a failing solve is handled")
    t_fail = w.diagnostics_text()
    ok(w.result is not None, "(the result of the earlier solve stays until the setup changes)")
    tm.run = _boom
    w.run_solve()
    t_crash = w.diagnostics_text()
finally:
    tm.run = orig_run2
ok("Solving: FAILED or cancelled in" in t_fail and "ERROR the solver is broken" in t_fail, "the report lists the failed job and the message of the solver")
ok("Traceback (most recent call last):" in t_crash and "RuntimeError: something unexpected in the solver" in t_crash, "an unexpected exception is in the report with its traceback")
ok(w.status_lbl.text() == "RuntimeError: something unexpected in the solver", "while the status line shows only its last line")

# ----------------------------------------------------------------------------------------------------------------------------------- save and reopen
ok(w.save() is not False, "saved")
w2 = tt.ThermalWindow.open_project(None, folder, threaded=False)
ok(w2.geom is not None and len(w2.geom["bodies"]) == 4, "reopened with its four bodies")
ok({k: len(w2.setup[k]) for k in tm.KEYS} == kinds, "and its conditions")
ok(w2.example_info == w.example_info, "and it still knows that it is the example (so the self-check keeps checking its result)")
ok(w2.result is None, "a project is saved without its result (as in 3D FEA): it is solved again")
ok(w2.run_solve() is not False and np.allclose(w2.result["T"], r["T"], atol=1e-9) and tm.frame_count(w2.result) == 31, "solved again it gives the same temperatures, 31 pictures")
ok(w2.run_self_check() is not False and not [x for x in w2.check_rows["rows"] + w2.check_rows["extra"] if not x.ok] and len(w2.check_rows["extra"]) >= 6, "the self-check of the reopened project passes, example checks included")
ok("example loaded: yes" in w2.diagnostics_text(), "and its report says so")
w2.close()

# ----------------------------------------------------------------------------------------------------------------------------------- the pictures, the animation and the probe
w.apply_frame(0)
vals0, leg = w.field_values(0)
ok(np.allclose(vals0, w.family().from_si("T", 293.15)), "picture 0 is the start temperature in the units shown")
w.apply_frame(15)
ok(w.slider.value() == 15 and "picture 16 of 31" in w.time_lbl.text() and "min" in w.time_lbl.text(), f"the slider and its label follow: '{w.time_lbl.text()}'")
v15, _ = w.field_values(15)
vlast, leg = w.field_values(30)
ok(vlast.max() > v15.max() > vals0.max(), "the part heats up from picture to picture")
ok(leg["lo"] <= vals0.min() + 1e-9 and leg["hi"] >= vlast.max() - 1e-9, "one colour scale for the whole run")
w.cb_field.setCurrentIndex(1)
q30, legq = w.field_values(30)
ok(w.field_key() == "qmag" and q30.max() > 0 and "Heat flux" in legq["title"], "the heat flux magnitude can be shown")
w.cb_field.setCurrentIndex(0)
w.e_dur.setText("0.3")
w.anim_play()
ok(w.anim_timer.isActive(), "Play starts the timer")
for _ in range(40):
    w.anim_step()
ok(w.cur_frame() in range(31), "stepping stays in range")
w.anim_stop()
ok(not w.anim_timer.isActive(), "Stop stops it")
w.apply_frame(30)
pr = w.probe_at(r["nodes"][100] + 0.01)
ok(pr is not None and pr[0] == 100 and abs(pr[2] - w.nodal(30)["T"][100]) < 1e-12, "a click on the part finds the nearest node and its temperature")
w.e_probe.setText("40, 30, 16")
pr = w.probe_node()
ok(pr is not None and 293.15 <= pr[2] <= r["Tmax"] and "Probe" in w.probe_lbl.text() and "in Copper" in w.probe_lbl.text(), "a typed point in the pad is probed and named by its body")
w.e_probe.setText("not a point")
ok(w.probe_node() is None and "x, y, z" in w.probe_lbl.text(), "a point that is not three numbers is explained")
png = os.path.join(T, "anim")
res_exp = w.export_animation((os.path.join(T, "anim.gif"), "gif"), 1.0)
ok(res_exp is None or os.path.exists(res_exp), "the animation exports a file, or says that this computer has no 3D view")

# ----------------------------------------------------------------------------------------------------------------------------------- units
unitctl.set_heat("US (°F, Btu/hr)", persist=False)
fam = w.family()
ok(fam.temp.endswith("F"), f"the heat units are {fam.temp}")
vF, legF = w.field_values(30)
ok(abs(vF.max() - (r["Tmax"] - 273.15) * 1.8 - 32.0) < 0.2 and "°F" in legF["title"], "the picture and its legend follow the heat units (°F)")
ok(abs(w.setup["temps"][0]["T"] - 293.15) < 1e-9, "what is stored stays kelvin")
shown = " ".join(w.cond_table.item(r_, 3).text() for r_ in range(w.cond_table.rowCount()))
ok("°F" in shown and "68" in shown and "°C" not in shown, f"the condition list shows °F: '{shown[:90]}'")
unitctl.set_heat("Follow the unit system", persist=False)
ok(w.family().temp.endswith("C"), "and back to °C")
inch = next(n for n in units.SYSTEMS if units.get(n)["L"] == "in")
unitctl.set_units(inch, persist=False)
ok(w.h_label is not None and "in" in w.h_label.text(), f"a change of unit system relabels the element size: '{w.h_label.text()}'")
unitctl.set_units("mm" if units.valid("mm") else units.DEFAULT, persist=False)

# ----------------------------------------------------------------------------------------------------------------------------------- what stops a solve, and conditions
w3 = tt.ThermalWindow(threaded=False)
ok(w3.run_solve() is False and "Import" in w3.status_lbl.text(), "Solve without a part says to import one")
ok(ex.run_self_check(w3) is not False, "the self-check needs no part")
ok(w3.check_rows is not None and not [x for x in w3.check_rows["rows"] if not x.ok] and w3.check_rows["extra"] == [], "and with no example loaded only the closed-form problems are checked")
ok("No job has run" not in w3.diagnostics_text() and "Nothing imported yet." in w3.diagnostics_text(), "the report of an empty window is still a report")
w3.close()

w4 = tt.ThermalWindow(threaded=False)
ok(w4.load_example(None) is False and w4.geom is None and len(ASKED) == 1 and "3D Thermal" in ASKED[0], "Load test example with the folder box cancelled does nothing")
w4.close()

# a plain part: the conditions, and what stops the run
import build123d as bd
w5 = tt.ThermalWindow(threaded=False)
sub = os.path.join(T, "bar")
pf = os.path.join(T, "bar_src")
os.makedirs(pf, exist_ok=True)
ex._part(os.path.join(pf, "bar.gpd"), [("rect", (0, 0), (100, 20))], 20, ex.AL)
ok(w5.create_project(os.path.join(T, "bar.gpt")) is not False, "a project for a single part")
ok(w5.import_file(os.path.join(pf, "bar.gpd")) is not False and w5.geom is not None and not w5.geom.get("bodies"), "a single part is imported")
ok(w5.run_solve() is False, "no condition: it will not solve")
msg0 = w5.status_lbl.text()
ok("temperature" in msg0.lower() or "condition" in msg0.lower() or "fix" in msg0.lower(), f"and says why: '{msg0}'")
left = ex.faces_of(w5.geom, normal=(-1, 0, 0))
right = ex.faces_of(w5.geom, normal=(1, 0, 0))
ok(len(left) == 1 and len(right) == 1, "the two ends of the bar are faces")
ok(w5.add_condition("temps", {"T": 373.15}, left, "Hot end"), "a fixed temperature on the left end")
ok(w5.add_condition("temps", {"T": 293.15}, right, "Cold end"), "and on the right end")
ok(w5.add_condition("temps", {"T": -5.0}, right, "Below zero") is False and len(w5.setup["temps"]) == 2, f"a temperature below absolute zero is refused: '{w5.status_lbl.text()}'")
ok(w5.add_condition("convs", {"h": -1.0, "Tinf": 293.15}, right, "Negative h") is False and len(w5.setup["convs"]) == 0, "so is a negative film coefficient")
ok(w5.add_condition("temps", {"T": 400.0}, [], "No face") is False, "a condition on no face is refused")
w5.setup["analysis"] = "steady"
w5.refresh_lists()
ok(w5.run_solve() is not False and w5.result is not None, "steady solve of the bar")
r5 = w5.result
k5 = w5.setup["material"]["k"]
ok(abs(k5 - 167.0) < 1e-9, f"the part's own material (aluminium) gave the conductivity: {k5} W/(m K)")
near(next(f for f in r5["flows"] if f["name"] == "Hot end")["Q"], k5 * 4e-4 * 80.0 / 0.1, 1e-6, "k A dT / L through the bar")
ok(r5["balance"]["relative_error"] < 1e-9 and tm.frame_count(r5) == 1, "balanced, and a steady result has one picture")
ok(w5.time_box.isHidden() or not w5.time_box.isVisible(), "no time slider for a steady result")
w5.anim_play()
ok(not w5.anim_timer.isActive(), "Play on a steady result does nothing")
ok(w5.export_animation(os.path.join(T, "x.gif"), 1.0) is None, "and neither does Export animation")
ok(w5.run_self_check() is not False and w5.check_rows["extra"] == [], "no example, no example checks")
# Load test example in a window that holds unsaved work asks first
w5.add_condition("temps", {"T": 350.0}, left, "Unsaved")
ok(w5.is_dirty(), "(a condition added and not saved)")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
n_before = len(w5.setup["temps"])
ok(w5.load_example(os.path.join(T, "refused.gpt")) is False and not os.path.exists(os.path.join(T, "refused.gpt")) and len(w5.setup["temps"]) == n_before, "answering No leaves the window and the disk as they were")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
ok(w5.load_example(os.path.join(T, "replaced.gpt")) is True and len(w5.geom["bodies"]) == 4 and w5.path.endswith("replaced.gpt"), "answering Yes loads the example in its own new folder")
ok(os.path.isdir(os.path.join(T, "bar.gpt")) and os.path.isfile(os.path.join(T, "bar.gpt", sp.MARKER)), "and the project that was open is left on disk")
w5.close()

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
print("OK thermal3d tab")
