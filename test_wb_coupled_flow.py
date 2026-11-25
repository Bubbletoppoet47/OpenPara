"""Coupled Physics with a 2D Fluid Flow block in the Workbench, in the real program window: a Part (a 20 mm square) wired to a 2D Fluid Flow block (slow air, one wall held at 50 degC,
the others 'walls of the thermal analysis'), a 2D Thermal block (the same square, a very good conductor held at 50 degC on that edge) and a 2D Static Structural block (that edge held),
all wired into a Coupled Physics block.  What is checked: the wiring is judged in words (a fluid alone, 3D with 2D, two parts, two fluids); Update solves the flow, the heat exchange
and the pressure in ONE coupled solve; the answers that are known (a body so conductive it is at one temperature gives walls at that temperature; the heat that leaves the solid
is the heat the fluid takes; the stress analysis carries the force the fluid pushes with); changing the setup of the fluid makes the block say update again; the window's report;
saving and opening the project computes nothing and the next Update gives the same answer.
python test_wb_coupled_flow.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(1500, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "coupled"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
import addons
import ext
addons.startup()
addons.register_extensions(ext)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import gpd_app
import pm_model as pm
import sk_tools as sk
import units
import wb_coupled
import wb_nodes
import wb_project as wp
import thermal_tab as tt
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbcf_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
import PyQt6.QtWidgets as qw


def square_doc(size):
    """(the part as JSON, the id of its sketch): a square of `size` mm, 10 mm deep."""
    d = pm.Document()
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (size, size))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=float(size))
    m.add_con("dim_v", [("ln", r["lns"][1])], value=float(size))
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="10"))
    d.rebuild()
    return json.loads(d.to_json()), s["id"]


def left_line(t):
    """The id of the line of the square that lies on x = 0."""
    return next(l for l in t.model.lns if max(t.model.pts[p_][0] for p_ in t.model.lns[l][:2]) < 1e-9)


def pick_sketch(w, sid):
    w.tab.picker.refresh()
    w.tab.picker.select(sid)
    w.tab.picker.go()


def checks_text(res):
    return "; ".join(f"{c['name']}: {c['ok']} ({c['detail']})" for c in res["checks"])


ok(not addons.load_errors(), f"the add-ons load without errors ({addons.load_errors()})")
P = W.project
doc, sid = square_doc(20)
nPart = W.add_block("part", 40, 60, title="Square", data={"doc": doc})
nFl = W.add_block("cfd", 400, 60, title="Air flow")
nTh = W.add_block("thermal", 400, 300, title="Square heat")
nSt = W.add_block("fea", 400, 540, title="Square stress")
nC = W.add_block("coupled", 760, 260, title="Flow and heat")
for n in (nFl, nTh, nSt):
    W.scene.make_link(nPart.id, "geometry", n.id, "geometry")
done, failed = W.refresh_project()
ok(done == 3 and not failed, f"the three analyses took the part ({failed})")

# ---------------------------------------------------------------------------------------------------------------------------------- the setups, made in the usual windows
wfl, wth, wst = W.open_cell(nFl.id, "setup"), W.open_cell(nTh.id, "setup"), W.open_cell(nSt.id, "setup")
for w in (wfl, wth, wst):
    pick_sketch(w, sid)
cf, th, fe = wfl.tab, wth.tab, wst.tab
LEFT = ("ln", left_line(cf))
cf.e_speed.setText(f"{units.speed_from_si(0.03, cf.unit_name()):.6g}")
for e, v in ((cf.e_hb, "3"), (cf.e_hf, "12"), (cf.e_ml, "3"), (cf.e_mr, "8"), (cf.e_mb, "3"), (cf.e_mt, "3"), (cf.e_cfl, "2"), (cf.e_steps, "250"),
             (cf.e_tol, "1e-6"), (cf.e_ramp, "5"), (cf.e_every, "1000")):
    e.setText(v)
cf.cb_until.setChecked(False)
cf.cb_auto.setChecked(False)
cf.cb_heat.setChecked(True)
keys = sorted({e["src"] for e in cf.geom["edges"]})
others = [k for k in keys if k != LEFT]
cf.set_wall_condition([LEFT], "temp", "50")
cf.set_wall_condition(others, "coupled", "")
ok(cf.coupled_keys() == sorted(others) and len(others) == 3, f"the fluid has three walls of the thermal analysis and one at 50 degC ({cf.coupled_keys()})")
ok(wfl.is_dirty(), "a wall condition of the fluid makes its window say 'changed' (it is part of what is saved)")

th.canvas.sel = [("ln", left_line(th))]
tt.ask_values = lambda parent, title, note, labels, defaults: [50.0]
th.add_temperature()
th.e_h.setText("2")
th.e_t.setText("1")
th.ensure_region_materials()
for f in th.region_mats:
    th.region_mats[f]["k"] = 400.0

fe.canvas.sel = [("ln", left_line(fe))]
fe.add_support("fixed")
fe.e_alpha.setText("1.2e-5")
fe.e_tref.setText("20")
fe.e_h.setText("2")
fe.cb_auto.setChecked(False)
W.sync_editors()
print("statuses", P.statuses(nFl.id), P.statuses(nTh.id), P.statuses(nSt.id))

# ---------------------------------------------------------------------------------------------------------------------------------- the wiring, in words
ad = wb_coupled.CoupledAdapter()
W.scene.make_link(nFl.id, "setup", nC.id, "physics")
why = ad.problems(W, nC)
ok(why is not None and "Thermal" in why and "Static Structural" in why, f"a fluid alone is refused in words: '{why}'")
ok(P.status(nC.id, "physics") != wp.OK, f"and Physics is not ok ({P.status(nC.id, 'physics')})")
W.scene.make_link(nTh.id, "setup", nC.id, "physics")
ok(ad.problems(W, nC) is None, f"a fluid and a heat analysis of the same sketch fit ({ad.problems(W, nC)})")
ok(ad.roles(W, nC)["fluid"] is nFl and ad.roles(W, nC)["thermal"] is nTh and ad.roles(W, nC)["structural"] is None, "the block knows each analysis by its role")
lab = ad.labels(W, nC)
ok(lab["fluid"] and lab["thermal"] and not lab["structural"], f"and says so in words ({lab})")

# a 3D heat analysis with the 2D flow, two flows, another part
nT3 = W.add_block("thermal3d", 760, 560, title="Solid heat")
W.scene.make_link(nT3.id, "setup", nC.id, "physics")
why = ad.problems(W, nC)
ok(why is not None, f"a second heat analysis is refused: '{why}'")
for k in list(P.links):
    if k.a == nT3.id:
        W.scene.remove_link(k)
nFl2 = W.add_block("cfd", 760, 700, title="Second flow")
W.scene.make_link(nFl2.id, "setup", nC.id, "physics")
why = ad.problems(W, nC)
ok(why is not None and "One Fluid Flow" in why, f"a second flow is refused in words: '{why}'")
for k in list(P.links):
    if k.a == nFl2.id:
        W.scene.remove_link(k)
doc_b, _sid_b = square_doc(20)
nPartB = W.add_block("part", 40, 900, title="Other square", data={"doc": doc_b})
nThB = W.add_block("thermal", 400, 900, title="Other heat")
W.scene.make_link(nPartB.id, "geometry", nThB.id, "geometry")
for k in list(P.links):
    if k.a == nTh.id and k.b == nC.id:
        W.scene.remove_link(k)
W.scene.make_link(nThB.id, "setup", nC.id, "physics")
why = ad.problems(W, nC)
ok(why is not None and "same geometry" in why, f"analyses of different parts are refused: '{why[:130] if why else why}'")
for k in list(P.links):
    if k.a == nThB.id:
        W.scene.remove_link(k)
W.scene.make_link(nTh.id, "setup", nC.id, "physics")
ok(ad.problems(W, nC) is None, "wired as before, the problem is gone")

# ---------------------------------------------------------------------------------------------------------------------------------- one coupled solve: flow + heat
import coupled_tab
calls = []
orig_solve = coupled_tab.CoupledWindow.solve


def counting(self, *a, **k):
    calls.append(1)
    return orig_solve(self, *a, **k)


coupled_tab.CoupledWindow.solve = counting
done, failed = W.refresh_project()
ok(not failed and P.status(nC.id, "physics") == wp.OK, f"Refresh Project: Physics is ok ({failed})")
done, failed = W.update_project(only={nFl.id, nTh.id, nC.id})
ok(not failed and len(calls) == 1, f"Update: ONE coupled solve ({failed}, {len(calls)}) {MSGS[-3:]}")
wc = W.editor_of(nC.id)
r1 = wc.result if wc is not None else None
ok(r1 is not None and r1["ok"] and r1["dim"] == 2 and "fluid" in r1 and "thermal" in r1 and "structural" not in r1, "the result has the fluid and the heat parts")
ok(r1 is not None and all(c["ok"] for c in r1["checks"]), "every check passes: " + (checks_text(r1) if r1 else ""))
if r1 is not None:
    h = r1["fluid"]["history"][-1]
    print("loop:", r1["fluid"]["iterations"], "iterations, mismatch", r1["fluid"]["mismatch"], "wall T", h["Tw_min"], h["Tw_max"], "Q", r1["fluid"]["Q_solid"], r1["fluid"]["Q_fluid"], "keys", sorted(r1["fluid"]))
    ok(abs(h["Tw_min"] - 323.15) < 1.0 and abs(h["Tw_max"] - 323.15) < 1.0, f"a body this conductive is at one temperature, and the walls are at it (50 degC): {h['Tw_min'] - 273.15:.3f} .. {h['Tw_max'] - 273.15:.3f} degC")
    qs, qf = r1["fluid"]["Q_solid"], r1["fluid"]["Q_fluid"]
    ok(abs(qs - qf) <= 0.02 * max(abs(qs), abs(qf)), f"the heat that leaves the solid is the heat the fluid takes ({qs:.5g} W, {qf:.5g} W)")
ok(all(P.status(n.id, k) == wp.OK for n in (nFl, nTh) for k in ("geometry", "setup", "solution")), f"every cell of the two analyses is ok ({[P.statuses(n.id) for n in (nFl, nTh)]})")
ok(P.status(nC.id, "solution") == wp.OK and P.status(nC.id, "results") == wp.OK, f"and the cells of the block ({P.statuses(nC.id)})")
ok(cf.worker is None and cf.coupled_flow_only is False and th.coupled_fluid is None, "the windows are left as they were")
html = wc.report_html()
ok("Fluid" in html and "Heat" in html and "2D" in html, "the window's report shows the flow and the heat")
ok(W.update_project()[0] == 0 and len(calls) == 1, "a second Update has nothing to do")

# changing the setup of the flow makes the block say update again
cf.e_speed.setText(f"{units.speed_from_si(0.06, cf.unit_name()):.6g}")
W.sync_editors()
ok(P.status(nC.id, "physics") == wp.REFRESH and P.status(nC.id, "solution") == wp.UPDATE, f"another speed: refresh and update ({P.statuses(nC.id)})")
cf.e_speed.setText(f"{units.speed_from_si(0.03, cf.unit_name()):.6g}")
W.sync_editors()

# ---------------------------------------------------------------------------------------------------------------------------------- the three together
W.scene.make_link(nSt.id, "setup", nC.id, "physics")
ok(ad.problems(W, nC) is None, "the stress analysis is wired in as well: they fit")
ok(P.status(nSt.id, "setup") == wp.OK, f"wired in, the stress analysis needs supports but no load: its Setup is ok ({P.status(nSt.id, 'setup')})")
done, failed = W.update_project(only={nFl.id, nTh.id, nSt.id, nC.id})
ok(not failed and len(calls) == 2, f"Update: one more coupled solve ({failed}, {len(calls)}) {MSGS[-3:]}")
r2 = wc.result
ok(r2 is not None and r2["ok"] and "structural" in r2 and all(c["ok"] for c in r2["checks"]), "three together: every check passes: " + (checks_text(r2) if r2 else ""))
ok(fe.result is not None and fe.result.get("cfd_tally"), "the stress analysis carries the pressure of the fluid on its edges")
ok(fe.coupled_in is None and fe.coupled_cfd is None, "and its window is left as it was")
if r1 is not None and r2 is not None:
    ok(abs(r2["fluid"]["Q_fluid"] - r1["fluid"]["Q_fluid"]) <= 1e-9 * abs(r1["fluid"]["Q_fluid"]) + 1e-12, "the flow and the heat are the same with the stress analysis added (the heat does not depend on it)")
sj = [c for c in r2["checks"] if c["name"].startswith("Pressure force")]
ok(len(sj) == 1 and sj[0]["ok"], f"the force the stress analysis carries is the force of the fluid ({sj[0]['detail'] if sj else None})")

# ---------------------------------------------------------------------------------------------------------------------------------- the structure moves the flow (a soft body, with the heat exchange as well)
fe.e_E.setText("2e-8")                                                                   # MPa: the flow bends the body by about a percent of its size
wc.cb_moves.setChecked(True)
W.sync_editors()
ok(wc.options["moves_flow"] and P.status(nC.id, "solution") == wp.UPDATE, f"'the structure moves the flow' is an option of the block, and a softer body makes the block say update ({P.statuses(nC.id)})")
done, failed = W.update_project(only={nFl.id, nTh.id, nSt.id, nC.id})
ok(not failed and len(calls) == 3, f"Update: one more coupled solve ({failed}, {len(calls)}) {MSGS[-3:]}")
r4 = wc.result
ok(r4 is not None and r4["ok"] and "fsi" in r4 and r4["fsi"]["converged"] and r4["fsi"]["iterations"] >= 2, "the body moves the flow: converged in " + (f"{r4['fsi']['iterations']} passes" if r4 and "fsi" in r4 else "?") + "; every check: " + (checks_text(r4) if r4 else ""))
if r4 is not None and "fsi" in r4:
    ok(all(c["ok"] for c in r4["checks"]), "every check passes (the heat exchange and the pressure of the last pass, and the moved flow)")
    ok(0.001 * 20.0 < r4["fsi"]["umax"] < 0.05 * 20.0, f"the largest displacement is {r4['fsi']['umax']:.4g} mm: a visible, small part of the body")
    ok(abs(r4["fluid"]["Q_fluid"] - r2["fluid"]["Q_fluid"]) <= 0.05 * abs(r2["fluid"]["Q_fluid"]) and r4["fluid"]["Q_fluid"] != r2["fluid"]["Q_fluid"],
       f"the heat the fluid takes changed a little with the moved body ({r4['fluid']['Q_fluid']:.6g} against {r2['fluid']['Q_fluid']:.6g} W)")
    ok("moves the flow" in wc.report_html() and "Passes" in wc.report_html(), "the window's report has the passes")
ok(cf.mesh.get("deformed"), "the fluid window shows the moved body")
ok(fe.coupled_in is None and fe.coupled_cfd is None and th.coupled_fluid is None and cf.deformed_shapes is None, "and the windows are left as they were")

# ---------------------------------------------------------------------------------------------------------------------------------- save, open, update
f1 = os.path.join(T, "flow.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "the project is saved")
shell.close_tab(shell.tabs.indexOf(W))
W3 = shell.open_path(f1)
p3 = W3.project
nC3 = next(n for n in p3.nodes.values() if n.kind == "coupled")
nF3 = next(n for n in p3.nodes.values() if n.kind == "cfd")
ok(p3.status(nC3.id, "setup") == wp.OK and p3.status(nC3.id, "solution") != wp.OK, f"opened: nothing is computed, the solution wants an update ({p3.statuses(nC3.id)})")
n_before = len(calls)
done, failed = W3.update_project()
ok(not failed and len(calls) == n_before + 1, f"Update Project computes it again ({failed}) {MSGS[-3:]}")
ok(W3.editor_of(nC3.id).options["moves_flow"], "the option 'the structure moves the flow' was saved with the block")
cf3 = W3.editor_of(nF3.id).tab
ok(cf3.coupled_keys() == sorted(others) and cf3.cb_heat.isChecked(), f"the walls of the thermal analysis were saved with the fluid window ({cf3.coupled_keys()})")
r3 = W3.editor_of(nC3.id).result
ok(r3 is not None and r3["ok"] and all(c["ok"] for c in r3["checks"]), "the reopened project solves and every check passes")
if r3 is not None and r4 is not None and "fsi" in r4 and "fsi" in r3:
    ok(abs(r3["fluid"]["Q_fluid"] - r4["fluid"]["Q_fluid"]) <= 1e-6 * abs(r4["fluid"]["Q_fluid"]) and r3["fsi"]["iterations"] == r4["fsi"]["iterations"],
       f"the same answer from the saved project ({r3['fluid']['Q_fluid']:.6g} against {r4['fluid']['Q_fluid']:.6g} W, {r3['fsi']['iterations']} passes against {r4['fsi']['iterations']})")
    ok(abs(r3["fsi"]["umax"] - r4["fsi"]["umax"]) <= 1e-6 * r4["fsi"]["umax"], "and the same displacement")
else:
    ok(False, "the saved project gave the moved flow again")

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
