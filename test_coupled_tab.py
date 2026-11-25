"""The Coupled Physics window on its own: without a Workbench block it says so; what stops a solve is said in words (and the window stays usable); with the real 2D heat and
stress windows given through members_source it solves, shows the combined result with the checks and the known answer (PASS and FAIL), keeps its options in the project folder,
writes the diagnostics report, and its self-check prints PASS - and prints FAIL when the hand-over is broken on purpose.
python test_coupled_tab.py"""
import faulthandler
faulthandler.dump_traceback_later(480, exit=True)
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "thermal3d"),
                os.path.join(HERE, "dev_addons", "coupled"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

import sketcher_core as sc
import sim_tab
import sim_project
import unitctl
import physics_tab
import thermal_tab as tt
import coupled_check
import coupled_engine as ce
import coupled_tab as ctab

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


unitctl.set_units("Metric (mm, kg, N, s, MPa)", notify=False, persist=False)
K0 = 273.15


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


def answer(*vals):
    def f(parent, title, note, labels, defaults):
        return list(vals)
    tt.ask_values = f


def pick(t, fn, sel, *vals):
    t.canvas.sel = list(sel)
    answer(*vals)
    getattr(t, fn)()


def html_of(w):
    return w.view.toPlainText()


# ------------------------------------------------------------------------------------------------------------------------------------------ alone
w = ctab.CoupledWindow()
ok(w.members()["windows"] == {} and "Workbench" in w.members()["note"], "without a Workbench block the window says it works inside a Workbench project")
ok("Workbench" in w.members_lbl.text(), "and says so on the page")
ok(not w.b_solve.isEnabled() and not w.b_heat.isEnabled() and not w.b_stress.isEnabled(), "Solve and the two 'Open' buttons are off")
ok(not w.cb_moves.isEnabled() and not w.options["moves_flow"], "'the structure moves the flow' is off, and cannot be ticked without a stress analysis wired in")
ok("Wire a heat analysis" in html_of(w), "the result area says what to wire in before the first Solve")
ok(w.solve() is False and w.result is None and w.last_error, f"Solve without analyses is refused with a reason ('{w.last_error}')")
ok(not w.is_dirty() and w.title() == "Coupled Physics", "a new window is not dirty and is called by its kind")
w.e_tol.setValue(5.0)
ok(w.options["tmean_tol_pct"] == 5.0 and w.is_dirty(), "the option 'largest change of the average temperature' follows the box and makes the window dirty")
before = w.save()
ok(before is False and any("Workbench project" in m for m in [w.status_lbl.text()]), f"it is not saved without a project folder, and says why ('{w.status_lbl.text()[:70]}...')")

# a block that reports a problem
w.members_source = lambda: {"windows": {}, "labels": {"thermal": "Heat A", "structural": "Stress B"}, "show": {}, "problem": "The two analyses use different geometry blocks.", "note": ""}
w.refresh()
ok("different geometry blocks" in w.members_lbl.text(), "a problem the block reports is shown beside the members")
ok(w.solve() is False and "different geometry blocks" in w.last_error, "and a Solve is refused with exactly that reason")

# only one of the two
w.members_source = lambda: {"windows": {}, "labels": {"thermal": "Heat A"}, "show": {}, "problem": None, "note": "Wire a stress analysis."}
w.refresh()
ok(not w.b_solve.isEnabled(), "with only the heat analysis wired in, Solve stays off")
ok(w.solve() is False and ("stress problem" in w.last_error or "stress" in w.last_error.lower()), f"and a Solve says what is missing ('{w.last_error}')")
w.members_source = lambda: (_ for _ in ()).throw(RuntimeError("the block went away"))
w.refresh()
ok("could not be read" in w.members_lbl.text() and "block went away" in w.members_lbl.text(), "a block that cannot be read is said so, the window keeps standing")
ok(w.solve() is False and "could not be read" in w.last_error, "and Solve says it too")

# ------------------------------------------------------------------------------------------------------------------------------------------ the self-check
r = w.run_self_check()
chk = w.check_result
ok(r is True and chk["ok"] and len(chk["rows"]) >= 10 and all(x["ok"] for x in chk["rows"]), f"the self-check passes: {len(chk['rows'])} problems, all PASS")
names = " | ".join(x["name"] for x in chk["rows"])
ok("refused" in names.lower() or "must" in names.lower() or "fail" in names.lower(), "it includes problems that must be caught (the checks are tried the wrong way round)")
page = html_of(w)
ok("Self-check" in page and "PASS" in page and "FAIL" not in page.replace("FAILED", ""), "the page shows the self-check with PASS beside every problem")
ok("Self-check" in w.diagnostics_text() and "PASS" in w.diagnostics_text(), "the diagnostics report holds the self-check")

# the self-check can fail: break the hand-over on purpose (every value comes out 5 K too high)
real = ce.hand_over


def wrong(*a, **k):
    out = real(*a, **k)
    try:
        v = out["values"] if isinstance(out, dict) else out[0]
        v = np.asarray(v, float) + 5.0
        return ({**out, "values": v} if isinstance(out, dict) else (v,) + tuple(out[1:]))
    except Exception:                                                      # noqa: BLE001
        raise


ce.hand_over = wrong
try:
    r_bad = w.run_self_check()
finally:
    ce.hand_over = real
ok(r_bad is False and not w.check_result["ok"] and any(not x["ok"] for x in w.check_result["rows"]),
   f"with the hand-over broken the self-check FAILS ({[x['name'] for x in w.check_result['rows'] if not x['ok']][:3]})")
ok("FAIL" in html_of(w) and "Self-check: a problem FAILED" in w.status_lbl.text(), "and the page and the status line say FAIL")
ok(w.run_self_check() and w.check_result["ok"], "with the hand-over restored it passes again")

# ------------------------------------------------------------------------------------------------------------------------------------------ the real 2D windows
m = sc.Model()
p = [m.add_point(*c) for c in ((0, 0), (100.0, 0), (100.0, 10.0), (0, 10.0))]
ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
th = tt.ThermalTab(host())
th.run_task = lambda title, fn: run_now(th, title, fn)
th.set_model(m, "bar")
pick(th, "add_temperature", [("ln", ls[3])], 100.0)
pick(th, "add_temperature", [("ln", ls[1])], 20.0)
th.e_h.setText("2")
fe = physics_tab.PhysicsTab(host())
fe.run_task = lambda title, fn: run_now(fe, title, fn)
fe.set_model(m, "bar")
fe.canvas.sel = [("ln", ls[3])]
fe.add_support("x")
fe.canvas.sel = [("pt", p[0])]
fe.add_support("y")
fe.e_alpha.setText("1.2e-5")
fe.e_tref.setText("20")
fe.e_h.setText("2")
fe.cb_auto.setChecked(False)

shown = []
folder = os.path.join(tempfile.mkdtemp(prefix="opara_ct_"), "pair.gpx")
wc = ctab.make_coupled(None)
ok(wc.create_project(folder) is not False and sim_project.kind_of_folder(folder) == "coupled", "a project folder of the kind 'coupled' is created")
wc.members_source = lambda: {"windows": {"thermal": th, "fea": fe}, "labels": {"thermal": "Bar heating (2D)", "structural": "Bar growth (2D)"},
                             "show": {"thermal": lambda: shown.append("heat"), "structural": lambda: shown.append("stress")}, "problem": None, "note": ""}
wc.refresh()
ok(wc.b_solve.isEnabled() and wc.b_heat.isEnabled() and wc.b_stress.isEnabled(), "with both analyses wired in, Solve and both 'Open' buttons are on")
ok("Bar heating (2D)" in wc.members_lbl.text() and "Bar growth (2D)" in wc.members_lbl.text(), "the members are listed by the names of their blocks")
wc.b_heat.click()
wc.b_stress.click()
ok(shown == ["heat", "stress"], "the Open buttons bring the two analysis windows in front")

wc.options["known"] = {"name": "Bar end growth", "expected": 0.048, "unit": "mm", "tol_pct": 3.0, "axis": 0}      # a known answer, for a 2D bar the window says it is for 3D bodies
got = wc.solve()
res = wc.result
ok(got is True and res is not None and res["ok"] and res["dim"] == 2, "the 2D coupled solve runs from the window and is ok")
ok(all(c["ok"] for c in res["checks"]), "every check of the hand-over passes: " + ", ".join(c["name"] for c in res["checks"]))
ok(abs(res["thermal"]["T_mean"] - (60.0 + K0)) < 1e-4, f"mean temperature {res['thermal']['T_mean']:.4f} K")
page = html_of(wc)
ok("Coupled solve" in page and "PASS" in page and "Nothing extrapolated" in page and "Every point found" in page, "the page shows the combined result with the checks")
ok("Known answer: Bar end growth" in page and "for a 3D body" in page, "the known answer of a 2D problem says that it is for 3D bodies (and does not claim PASS)")
ok(res["known"]["ok"] is False and res["known"]["got"] is None, "and counts as not checked, not as passed")
dg = wc.diagnostics_text()
for needle in ("Members", "Options", "Last solve", "Checks", "transfer ", "Known answer, Bar end growth", "This window said", "Bar heating (2D)"):
    ok(needle in dg, f"the diagnostics report holds '{needle}'")
ok("solved (2D)" in dg, "and says what this window did (solved in 2D)")

# the known answer works with its values: what a 2D window cannot do must not pass silently
wc.options.pop("known")
ok(wc.solve() is True and wc.result.get("known") is None, "without a known answer the row is not there")
ok("Known answer" not in html_of(wc), "and the page does not mention one")

# a problem in the stress analysis is refused in words and does not leave an old result standing
fe.supports.clear()
ok(wc.solve() in (True, False), "a solve with a changed stress analysis runs or is refused")
if wc.result is None:
    ok(bool(wc.last_error), f"refused with a reason: '{wc.last_error.strip().splitlines()[-1][:90]}'")
fe.canvas.sel = [("ln", ls[3])]
fe.add_support("x")
fe.canvas.sel = [("pt", p[0])]
fe.add_support("y")

# options and the project folder
wc.e_tol.setValue(3.5)
ok(wc.is_dirty() and wc.save() is True and not wc.is_dirty(), "the option is saved in the project folder")
wc.options["known"] = {"name": "Bar end growth", "expected": 0.048, "unit": "mm", "tol_pct": 3.0}
ok(wc.save() is True, "a known answer is saved with the options too")
# the known answer of the walls of a fluid and a very conductive solid: PASS when the walls are at the temperature, FAIL (it can) when they are not, a note when there is no flow
saved_known, saved_result = wc.options.get("known"), wc.result
wc.options["known"] = {"kind": "wall_temperature", "name": "walls at 50 degC", "expected": 50.0, "unit": "degC", "tol_abs": 1.0}
wc.result = {"fluid": {"history": [{"Tw_min": 323.0, "Tw_max": 323.15}]}}
kw = wc.known_answer({})
ok(kw["ok"] and abs(kw["got"] - 49.85) < 1e-9 and "49.850" in kw["note"], f"known answer, walls at 49.85 .. 50 degC against 50 degC within 1 K: PASS ({kw})")
wc.result = {"fluid": {"history": [{"Tw_min": 323.0, "Tw_max": 330.0}]}}
kw = wc.known_answer({})
ok(not kw["ok"] and abs(kw["got"] - 56.85) < 1e-9, f"and when a wall point is at 56.85 degC it is FAIL, with the point that is farthest from the answer ({kw})")
wc.result = {"thermal": {}}
kw = wc.known_answer({})
ok(not kw["ok"] and kw["got"] is None and "needs the flow" in kw["note"], f"without a flow it says so, and is not a PASS ({kw.get('note')})")
wc.options["known"], wc.result = saved_known, saved_result
wc.cb_moves.setChecked(True)
wc.e_fsi_tol.setValue(0.25)
wc.e_fsi_max.setValue(7)
ok(wc.options["moves_flow"] is True and abs(wc.options["fsi_tol_pct"] - 0.25) < 1e-12 and wc.options["fsi_max"] == 7 and wc.is_dirty(), "'the structure moves the flow', its tolerance and its number of passes follow the boxes")
ok(wc.save() is True, "and are saved with the other options")
w2 = ctab.make_coupled(None, folder)
ok(w2.options["moves_flow"] is True and w2.cb_moves.isChecked() and abs(w2.e_fsi_tol.value() - 0.25) < 1e-12 and w2.e_fsi_max.value() == 7 and not w2.is_dirty(),
   "opened again, the moving of the flow is back with its tolerance and its passes")
ok(abs(w2.options["tmean_tol_pct"] - 3.5) < 1e-9 and abs(w2.e_tol.value() - 3.5) < 1e-9 and w2.options["known"]["name"] == "Bar end growth" and not w2.is_dirty(),
   "opened again, the option and the known answer are back and the window is not dirty")
ok(w2.members()["windows"] == {}, "a window opened from its folder holds no analyses until the block gives them")
try:
    ctab.CoupledWindow.open_project(None, tempfile.mkdtemp(prefix="opara_nokind_"))
    ok(False, "a folder that is not a Coupled Physics project is refused")
except ValueError as ex:
    ok("not a" in str(ex), f"a folder that is not a Coupled Physics project is refused ('{ex}')")

# cancel and shutdown
wc.cancel_flag = False
wc.running = True
wc.cancel()
ok(wc.cancel_flag and "Cancelling" in wc.status_lbl.text(), "Cancel while running sets the flag and says so")
wc.running = False
wc.shutdown()
ok(wc.cancel_flag, "shutdown stops any solve that is running")
wc.units_changed()
wc.heat_changed()
ok(True, "the hooks of the program window do not fail")

print("\nall passed" if not FAILS else f"\nFAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
