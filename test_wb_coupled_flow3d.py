"""Coupled Physics with a 3D Fluid Flow block in the Workbench, in the real program window: a Part (a 30 x 10 x 10 mm block) wired to a 3D Fluid Flow block (slow air along +x, the
upstream end held by the heat analysis, every other face a 'wall of the thermal analysis'), a 3D Thermal block (copper, the upstream end at 70 degC) and a 3D Static Structural block
(the downstream end held), all wired into a Coupled Physics block.  What is checked: the wiring is judged in words (a 3D flow alone, 2D with 3D, two flows, two parts); Update solves the
flow and the heat exchange in ONE coupled solve; the answers that are known (a body so conductive it is at one temperature gives walls at that temperature; the heat that leaves the
solid is the heat the fluid takes; the stress analysis carries the force the fluid pushes with); the three together; the structure moving the flow; changing the setup of the fluid
makes the block say update again; saving and opening the project computes nothing and the next Update gives the same answer.  (The fluid energy balance of the coarse mesh is a SOFT
check of the engine: it is read, not required.)
python test_wb_coupled_flow3d.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(1700, exit=True)
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
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "cfd3d", "coupled"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

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
import wb_coupled
import wb_example as ex
import wb_project as wp
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbcf3_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
import PyQt6.QtWidgets as qw


def checks_text(res):
    return "; ".join(f"{c['name']}: {c['ok']} ({c['detail']})" for c in res["checks"])


def hard_failed(res):
    return [c["name"] for c in res["checks"] if c.get("hard") and not c["ok"]]


ok(not addons.load_errors(), f"the add-ons load without errors ({addons.load_errors()})")
P = W.project
block_doc, _sid = ex.part_doc(*ex.BLOCK)
nPart = W.add_block("part", 40, 60, title="Block", data={"doc": block_doc})
nFl = W.add_block("fluid3d", 400, 60, title="Block air flow")
nTh = W.add_block("thermal3d", 400, 300, title="Block heat")
nSt = W.add_block("solid", 400, 540, title="Block pressure")
nC = W.add_block("coupled", 760, 260, title="Air and block")
for n in (nFl, nTh, nSt):
    W.scene.make_link(nPart.id, "geometry", n.id, "geometry")
done, failed = W.refresh_project()
ok(done == 3 and not failed, f"the three analyses took the part ({failed})")

# ---------------------------------------------------------------------------------------------------------------------------------- the setups, made in the usual windows
for node, fn in ((nFl, ex.setup_block_flow), (nTh, ex.setup_block_heat), (nSt, ex.setup_block_pressure)):
    ex.with_editor(W, node, fn)
print("statuses", P.statuses(nFl.id), P.statuses(nTh.id), P.statuses(nSt.id))
ok(all(P.status(n.id, "setup") == wp.OK for n in (nFl, nTh)), f"the flow and the heat analysis have their setup ({[P.status(n.id, 'setup') for n in (nFl, nTh)]})")
ok(P.status(nSt.id, "setup") != wp.OK, f"the stress analysis (supports, no load) waits until it is wired into Coupled Physics ({P.status(nSt.id, 'setup')})")

# ---------------------------------------------------------------------------------------------------------------------------------- the wiring, in words
ad = wb_coupled.CoupledAdapter()
ok(wb_coupled.ROLE["fluid3d"] == "fluid" and wb_coupled.DIM["fluid3d"] == 3, "the kind 'fluid3d' is a fluid of dimension 3 for Coupled Physics")
W.scene.make_link(nFl.id, "setup", nC.id, "physics")
why = ad.problems(W, nC)
ok(why is not None and "3D Thermal" in why and "3D Static Structural" in why, f"a 3D flow alone is refused in words: '{why}'")
ok(P.status(nC.id, "physics") != wp.OK, f"and Physics is not ok ({P.status(nC.id, 'physics')})")
W.scene.make_link(nTh.id, "setup", nC.id, "physics")
ok(ad.problems(W, nC) is None, f"a 3D flow and a 3D heat analysis of the same part fit ({ad.problems(W, nC)})")
rl = ad.roles(W, nC)
ok(rl["fluid"] is nFl and rl["thermal"] is nTh and rl["structural"] is None, "the block knows each analysis by its role")
lab = ad.labels(W, nC)
ok(lab["fluid"] and lab["thermal"] and not lab["structural"], f"and says so in words ({lab})")

# a 2D heat analysis with the 3D flow, a second flow, another part
nT2 = W.add_block("thermal", 760, 560, title="Flat heat")
W.scene.make_link(nT2.id, "setup", nC.id, "physics")
why = ad.problems(W, nC)
ok(why is not None, f"a second heat analysis is refused: '{why}'")
for k in list(P.links):
    if k.a == nT2.id:
        W.scene.remove_link(k)
for k in list(P.links):
    if k.a == nTh.id and k.b == nC.id:
        W.scene.remove_link(k)
W.scene.make_link(nT2.id, "setup", nC.id, "physics")
why = ad.problems(W, nC)
ok(why is not None and "2D" in why and "3D" in why, f"a 3D flow with a 2D heat analysis is refused in words: '{why}'")
for k in list(P.links):
    if k.a == nT2.id:
        W.scene.remove_link(k)
W.scene.make_link(nTh.id, "setup", nC.id, "physics")
nFl2 = W.add_block("fluid3d", 760, 700, title="Second flow")
W.scene.make_link(nFl2.id, "setup", nC.id, "physics")
why = ad.problems(W, nC)
ok(why is not None and "One Fluid Flow" in why, f"a second flow is refused in words: '{why}'")
for k in list(P.links):
    if k.a == nFl2.id:
        W.scene.remove_link(k)
doc_b, _sid_b = ex.part_doc(*ex.BLOCK)
nPartB = W.add_block("part", 40, 900, title="Other block", data={"doc": doc_b})
nThB = W.add_block("thermal3d", 400, 900, title="Other heat")
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
ok(r1 is not None and r1["ok"] and r1["dim"] == 3 and "fluid" in r1 and "thermal" in r1 and "structural" not in r1, "the result has the 3D flow and the heat parts")
ok(r1 is not None and not hard_failed(r1), "every hard check passes (read: " + (checks_text(r1) if r1 else "") + ")")
if r1 is not None:
    fl = r1["fluid"]
    h = fl["history"][-1]
    print("loop:", fl["iterations"], "iterations, mismatch", fl["mismatch"], "wall T", h["Tw_min"], h["Tw_max"], "Q", fl["Q_solid"], fl["Q_fluid"], "balance", fl.get("balance"))
    hx = [c for c in r1["checks"] if c["name"] == "Heat exchange converged"]
    ok(len(hx) == 1 and hx[0]["ok"] and fl["mismatch"] <= 0.01, f"the heat exchange converged in {fl['iterations']} passes (mismatch {fl['mismatch']:.2g})")
    ok(abs(h["Tw_min"] - 343.15) < 1.0 and abs(h["Tw_max"] - 343.15) < 1.0, f"a body this conductive is at one temperature, and the walls are at it (70 degC): {h['Tw_min'] - 273.15:.3f} .. {h['Tw_max'] - 273.15:.3f} degC")
    qs, qf = fl["Q_solid"], fl["Q_fluid"]
    ok(abs(qs - qf) <= 0.05 * max(abs(qs), abs(qf)), f"the heat that leaves the solid is the heat the fluid takes ({qs:.5g} W, {qf:.5g} W)")
    ok(r1.get("known") is None, "no known answer is set yet")
ok(all(P.status(n.id, k) == wp.OK for n in (nFl, nTh) for k in ("geometry", "setup", "solution")), f"every cell of the two analyses is ok ({[P.statuses(n.id) for n in (nFl, nTh)]})")
ok(P.status(nC.id, "solution") == wp.OK and P.status(nC.id, "results") == wp.OK, f"and the cells of the block ({P.statuses(nC.id)})")
wf = W.editor_of(nFl.id)
wt = W.editor_of(nTh.id)
ok(wf is None or getattr(wf, "coupled_flow_only", False) is False, "the fluid window is left as it was")
ok(wt is None or getattr(wt, "coupled_fluid", None) is None, "and so is the heat window")
html = wc.report_html()
ok("Fluid" in html and "Heat" in html and "3D" in html, "the window's report shows the flow and the heat")
ok(W.update_project()[0] == 0 and len(calls) == 1, "a second Update has nothing to do")

# changing the setup of the flow makes the block say update again
wf = W.open_cell(nFl.id, "setup")
sp0 = wf.setup["flow"]["speed"]
wf.e_speed.setText(f"{sp0 * 1.5:.6g}")
wf.inputs_changed()
W.sync_editors()
ok(P.status(nC.id, "physics") == wp.REFRESH and P.status(nC.id, "solution") == wp.UPDATE, f"another speed: refresh and update ({P.statuses(nC.id)})")
wf.e_speed.setText(f"{sp0:.6g}")
wf.inputs_changed()
W.sync_editors()
ok(P.status(nC.id, "physics") in (wp.REFRESH, wp.OK), f"the old speed again ({P.statuses(nC.id)})")

# ---------------------------------------------------------------------------------------------------------------------------------- the three together, with the known answer
W.scene.make_link(nSt.id, "setup", nC.id, "physics")
ok(ad.problems(W, nC) is None, "the stress analysis is wired in as well: they fit")
ok(P.status(nSt.id, "setup") == wp.OK, f"wired in, the stress analysis needs supports but no load: its Setup is ok ({P.status(nSt.id, 'setup')})")
wc = W.editor_of(nC.id)
wc.options["known"] = dict(ex.KNOWN_BLOCK)
wc.save()
done, failed = W.refresh_project()
ok(not failed, f"Refresh Project ({failed})")
done, failed = W.update_project(only={nFl.id, nTh.id, nSt.id, nC.id})
ok(not failed and len(calls) == 2, f"Update: one more coupled solve ({failed}, {len(calls)}) {MSGS[-3:]}")
wc = W.editor_of(nC.id)
r2 = wc.result
ok(r2 is not None and r2["ok"] and "structural" in r2 and not hard_failed(r2), "three together: every hard check passes (read: " + (checks_text(r2) if r2 else "") + ")")
sj = [c for c in (r2["checks"] if r2 else []) if c["name"].startswith("Pressure force")]
ok(len(sj) == 1 and sj[0]["ok"], f"the force the stress analysis carries is the force of the fluid ({sj[0]['detail'] if sj else None})")
ws = W.editor_of(nSt.id)
ok(ws is None or (getattr(ws, "coupled_in", None) is None and getattr(ws, "coupled_cfd", None) is None), "the stress window is left as it was")
kn = r2.get("known") if r2 else None
ok(kn is not None and kn["ok"], f"the known answer (the walls are at 70 degC): {kn}")
if r1 is not None and r2 is not None:
    ok(abs(r2["fluid"]["Q_fluid"] - r1["fluid"]["Q_fluid"]) <= 1e-6 * abs(r1["fluid"]["Q_fluid"]) + 1e-12, "the flow and the heat are the same with the stress analysis added (the heat does not depend on it)")

# ---------------------------------------------------------------------------------------------------------------------------------- the structure moves the flow (a soft body, with the heat exchange as well)
wc.cb_moves.setChecked(True)
W.sync_editors()
ok(wc.options["moves_flow"] and P.status(nC.id, "solution") == wp.UPDATE, f"'the structure moves the flow' is an option of the block, and the block says update ({P.statuses(nC.id)})")
done, failed = W.update_project(only={nFl.id, nTh.id, nSt.id, nC.id})
ok(not failed and len(calls) == 3, f"Update: one more coupled solve ({failed}, {len(calls)}) {MSGS[-3:]}")
r4 = wc.result
ok(r4 is not None and r4["ok"] and "fsi" in r4 and r4["fsi"]["converged"] and r4["fsi"]["iterations"] >= 2,
   "the body moves the flow: converged in " + (f"{r4['fsi']['iterations']} passes" if r4 and "fsi" in r4 else "?") + "; every check: " + (checks_text(r4) if r4 else ""))
if r4 is not None and "fsi" in r4:
    ok(not hard_failed(r4), "every hard check passes (the heat exchange and the pressure of the last pass, and the moved flow)")
    ok(0.0005 * ex.BLOCK[0] < r4["fsi"]["umax"] < 0.05 * ex.BLOCK[0], f"the largest displacement is {r4['fsi']['umax']:.4g} mm: a visible, small part of the body")
    ok(abs(r4["fluid"]["Q_fluid"] - r2["fluid"]["Q_fluid"]) <= 0.05 * abs(r2["fluid"]["Q_fluid"]),
       f"the heat the fluid takes is near what the unmoved body takes ({r4['fluid']['Q_fluid']:.6g} against {r2['fluid']['Q_fluid']:.6g} W)")
    ok("moves the flow" in wc.report_html() and "Passes" in wc.report_html(), "the window's report has the passes")
    kn4 = r4.get("known")
    ok(kn4 is not None and kn4["ok"], f"the known answer holds with the moved flow too: {kn4}")
ws = W.editor_of(nSt.id)
ok(ws is None or (getattr(ws, "coupled_in", None) is None and getattr(ws, "coupled_cfd", None) is None), "the windows are left as they were")

# ---------------------------------------------------------------------------------------------------------------------------------- save, open, update
f1 = os.path.join(T, "flow3d.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "the project is saved")
shell.close_tab(shell.tabs.indexOf(W))
W3 = shell.open_path(f1)
p3 = W3.project
nC3 = next(n for n in p3.nodes.values() if n.kind == "coupled")
nF3 = next(n for n in p3.nodes.values() if n.kind == "fluid3d" and n.title == "Block air flow")
ok(p3.status(nC3.id, "setup") == wp.OK and p3.status(nC3.id, "solution") != wp.OK, f"opened: nothing is computed, the solution wants an update ({p3.statuses(nC3.id)})")
n_before = len(calls)
done, failed = W3.update_project()
ok(not failed and len(calls) == n_before + 1, f"Update Project computes it again ({failed}) {MSGS[-3:]}")
ok(W3.editor_of(nC3.id).options["moves_flow"], "the option 'the structure moves the flow' was saved with the block")
ok(W3.editor_of(nC3.id).options.get("known", {}).get("expected") == 70.0, "and so was the known answer")
wf3 = W3.editor_of(nF3.id)
import cfd3d_model as cm3
ex_f = cm3.exch_fids(cm3.resolve(wf3.geom, wf3.setup)) if wf3 is not None else []
ok(wf3 is not None and wf3.setup["flow"]["heat"] and len(ex_f) == 5, f"the walls of the thermal analysis were saved with the fluid window ({ex_f})")
r3 = W3.editor_of(nC3.id).result
ok(r3 is not None and r3["ok"] and not hard_failed(r3), "the reopened project solves and every hard check passes")
if r3 is not None and r4 is not None and "fsi" in r4 and "fsi" in r3:
    ok(abs(r3["fluid"]["Q_fluid"] - r4["fluid"]["Q_fluid"]) <= 1e-4 * abs(r4["fluid"]["Q_fluid"]) and r3["fsi"]["iterations"] == r4["fsi"]["iterations"],
       f"the same answer from the saved project ({r3['fluid']['Q_fluid']:.6g} against {r4['fluid']['Q_fluid']:.6g} W, {r3['fsi']['iterations']} passes against {r4['fsi']['iterations']})")
    ok(abs(r3["fsi"]["umax"] - r4["fsi"]["umax"]) <= 1e-4 * r4["fsi"]["umax"], "and the same displacement")
else:
    ok(False, "the saved project gave the moved flow again")

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
