"""The Coupled Physics block of the Workbench in the real program window: a Part wired to a 3D Thermal and a 3D Static Structural block, both wired into a Coupled Physics block;
the stress analysis needs supports but no load once it is wired in, the wiring is checked in words (one of each, the same dimension, the same geometry), Update solves both together
and the answer is the bar's (the far end grows alpha (Tmean - Tref) L = 0.048 mm), the analyses' own Solution cells are answered by the same solve (one solve, not three), changing
a setup makes the block say update again, saving and opening the project computes nothing and the second Update gives the same answer, and the block saves on its own.
python test_wb_coupled.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(560, exit=True)
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


def widget_gone(w):
    """True when a Qt widget was deleted (touching it raises)."""
    try:
        w.isVisible()
        return False
    except RuntimeError:
        return True


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import gpd_app
import pm_model as pm
import sk_tools as sk
import wb_coupled
import wb_nodes
import wb_project as wp
import wb_tab
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbc_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
import PyQt6.QtWidgets as qw


def bar_json(depth):
    return bar_doc(depth)[0]


def bar_doc(depth):
    """(the part as JSON, the id of its sketch)."""
    d = pm.Document()
    d.params = {"H": str(depth)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (100, 10))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0)
    m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    return json.loads(d.to_json()), s["id"]


def face(win, n):
    return next(f["id"] for f in win.geom["faces"] if np.dot(f["normal"], n) > 0.99)


ok(not addons.load_errors(), f"the add-ons load without errors ({addons.load_errors()})")
ok(wb_nodes.adapter_for("coupled") is not None and wb_nodes.availability(W, "coupled")[0], f"the kind 'coupled' has an adapter and its add-on is there ({wb_nodes.availability(W, 'coupled')})")
ok("coupled" not in wb_nodes.check_kinds(), "it is wired into the workbench")
sp = wp.spec_of("coupled")
ok(sp.group == "Analysis Systems" and [c.key for c in sp.cells] == ["physics", "setup", "solution", "results"], "four cells: Physics, Setup, Solution, Results")
ok(all("coupling" in wp.spec_of(k).cell("setup").provides for k in ("solid", "fea", "thermal", "thermal3d", "cfd")) and "coupling" not in wp.spec_of("beam").cell("setup").provides,
   "the Setup of the heat, stress and fluid analyses give 'coupling'; the beam one does not (yet)")

P = W.project
nBar = W.add_block("part", 40, 60, title="Bar", data={"doc": bar_json(10)})
nHeat = W.add_block("thermal3d", 400, 60, title="Bar heating")
nStress = W.add_block("solid", 400, 300, title="Bar stress")
nC = W.add_block("coupled", 760, 160, title="Bar thermal stress")
ok(P.status(nC.id, "physics") == wp.INCOMPLETE and P.status(nC.id, "setup") == wp.OK, f"a new block: Physics incomplete (nothing wired), Setup ok ({P.statuses(nC.id)})")
W.scene.make_link(nBar.id, "geometry", nHeat.id, "geometry")
W.scene.make_link(nBar.id, "geometry", nStress.id, "geometry")
done, failed = W.refresh_project()
ok(done == 2 and not failed, f"the two analyses took the part ({failed})")

# the setups, made in the usual windows
wh = W.open_cell(nHeat.id, "setup")
wh.add_condition("temps", {"T": 373.15}, [face(wh, [-1, 0, 0])], "Hot end")
wh.add_condition("temps", {"T": 293.15}, [face(wh, [1, 0, 0])], "Cold end")
wh.setup["analysis"] = "steady"
ws = W.open_cell(nStress.id, "setup")
ok(ws.add_support("disp", [face(ws, [-1, 0, 0])], {"ux": 0.0, "uy": None, "uz": None}) and ws.add_support("disp", [face(ws, [0, -1, 0])], {"ux": None, "uy": 0.0, "uz": None})
   and ws.add_support("disp", [face(ws, [0, 0, -1])], {"ux": None, "uy": None, "uz": 0.0}), "three symmetry planes hold the bar against rigid movement, no load")
ws.e_alpha.setText("1.2e-5")
ws.e_tref.setText("20")
ws.inputs_changed()
W.sync_editors()
ok(P.status(nHeat.id, "setup") == wp.OK, "the heat analysis is set up")
ok(P.status(nStress.id, "setup") == wp.INCOMPLETE, f"on its own the stress analysis has nothing that drives it: incomplete ({P.status(nStress.id, 'setup')})")

# wiring them in
ok(W.scene.make_link(nHeat.id, "setup", nC.id, "physics") is not None, "the heat Setup is wired into Physics")
ok(P.status(nStress.id, "setup") == wp.INCOMPLETE, "(the stress analysis is not wired in yet)")
ok(W.scene.make_link(nStress.id, "setup", nC.id, "physics") is not None, "the stress Setup is wired into Physics")
ok(P.status(nStress.id, "setup") == wp.OK, f"wired in, the stress analysis needs supports but no load: its Setup is ok ({P.status(nStress.id, 'setup')})")
ok(P.status(nC.id, "physics") == wp.REFRESH, f"Physics says refresh ({P.status(nC.id, 'physics')})")
ok(W.scene.make_link(nStress.id, "setup", nC.id, "physics") is None, "the same wire twice is refused")
nStudyless = P.why_not_link(nBar.id, "geometry", nC.id, "physics")
ok(nStudyless is not None and "gives geometry" in nStudyless, f"a geometry wire cannot go into Physics: '{nStudyless}'")

plan = [(s["name"], s["action"]) for s in P.plan_update()]
ok((f"{nC.label}2", "refresh") in plan and (f"{nC.label}4", "update") in plan, f"Update refreshes Physics and updates the Solution of the block ({plan})")
done, failed = W.refresh_project()
ok(not failed and P.status(nC.id, "physics") == wp.OK, f"Refresh Project: Physics is ok ({failed})")
ok(P.status(nC.id, "solution") == wp.UPDATE, f"the solution says update ({P.status(nC.id, 'solution')})")

# one solve for the three Solution cells
import coupled_tab
calls = []
orig_solve = coupled_tab.CoupledWindow.solve


def counting(self, *a, **k):
    calls.append(1)
    return orig_solve(self, *a, **k)


coupled_tab.CoupledWindow.solve = counting
done, failed = W.update_project()
ok(not failed, f"Update Project ({failed})")
ok(len(calls) == 1, f"the three Solution cells were answered by ONE coupled solve ({len(calls)})")
wc = W.editor_of(nC.id)
ok(isinstance(wc, coupled_tab.CoupledWindow) and wc.result is not None and wc.result["ok"] and all(c["ok"] for c in wc.result["checks"]), "the Coupled Physics window has the result, every check passes")
ok(all(P.status(n.id, k) == wp.OK for n in (nHeat, nStress) for k in ("geometry", "setup", "solution")) and all(P.status(nC.id, k) == wp.OK for k in ("physics", "setup", "solution", "results")),
   f"every cell is ok ({[P.statuses(n.id) for n in (nHeat, nStress, nC)]})")
r3 = ws.result
n3, u3 = np.asarray(r3["nodes"], float), np.asarray(r3["u"], float)
end = np.abs(n3[:, 0] - n3[:, 0].max()) < 1e-6
dx = float(u3[end, 0].mean())
ok(abs(dx - 0.048) / 0.048 < 0.02, f"the answer is the bar's: the far end grows alpha (Tmean - Tref) L = 0.048 mm ({dx:.5f})")
ok(float(np.median(np.asarray(r3["vm_node"], float))) < 1.0, "and the bar is free of stress in the middle (median von Mises below 1 MPa)")
ok(W.update_project()[0] == 0, "a second Update has nothing to do")

# a change in a setup makes the block say update
before = len(calls)
ws.e_alpha.setText("2.4e-5")
ws.inputs_changed()
W.sync_editors()
ok(P.status(nC.id, "physics") == wp.REFRESH and P.status(nC.id, "solution") == wp.UPDATE, f"another coefficient of expansion: refresh and update ({P.statuses(nC.id)})")
done, failed = W.update_project()
ok(not failed and len(calls) == before + 1, f"one more solve ({failed})")
u4 = np.asarray(ws.result["u"], float)
ok(abs(float(u4[np.abs(np.asarray(ws.result['nodes'], float)[:, 0] - n3[:, 0].max()) < 1e-6, 0].mean()) - 0.096) / 0.096 < 0.02, "twice the coefficient, twice the growth")

# the wiring is checked in words
nHeat2 = W.add_block("thermal", 400, 560, title="Sketch heating")
W.scene.make_link(nHeat2.id, "setup", nC.id, "physics")
why = wb_coupled.CoupledAdapter().problems(W, nC)
ok(why is not None and "One Thermal and one Static Structural" in why, f"a second heat analysis is refused in words: '{why}'")
ok(P.status(nC.id, "physics") == wp.INCOMPLETE, f"the new analysis has no geometry and no setup yet, so Physics is incomplete ({P.status(nC.id, 'physics')})")
ok("One Thermal" in (wb_coupled.CoupledAdapter().refresh(W, nC, "physics") or ""), "and Refresh of Physics gives the same words")
for k in list(P.links):
    if k.a == nHeat2.id:
        W.scene.remove_link(k)
nPart2 = W.add_block("part", 40, 600, title="Other", data={"doc": bar_json(10)})
nOther = W.add_block("solid", 760, 560, title="Other stress")
W.scene.make_link(nPart2.id, "geometry", nOther.id, "geometry")
for k in list(P.links):
    if k.a == nStress.id and k.b == nC.id:
        W.scene.remove_link(k)
W.scene.make_link(nOther.id, "setup", nC.id, "physics")
why = wb_coupled.CoupledAdapter().problems(W, nC)
ok(why is not None and "same geometry" in why, f"analyses of different parts are refused: '{why[:120] if why else why}'")
for k in list(P.links):
    if k.a == nOther.id:
        W.scene.remove_link(k)
W.scene.make_link(nStress.id, "setup", nC.id, "physics")
ok(wb_coupled.CoupledAdapter().problems(W, nC) is None, "wired as before, the problem is gone")

# ------------------------------------------------------------------------------------------------------------------------------------ the same in 2D, from the sketch of a part
doc2, sid2 = bar_doc(10)
nPart2d = W.add_block("part", 40, 900, title="Plate", data={"doc": doc2})
nHeat2d = W.add_block("thermal", 400, 900, title="Plate heating")
nStress2d = W.add_block("fea", 400, 1140, title="Plate stress")
nC2 = W.add_block("coupled", 760, 1000, title="Plate thermal stress")
W.scene.make_link(nPart2d.id, "geometry", nHeat2d.id, "geometry")
W.scene.make_link(nPart2d.id, "geometry", nStress2d.id, "geometry")
done, failed = W.refresh_project(only={nHeat2d.id, nStress2d.id})
ok(done == 2 and not failed, f"the two 2D analyses took the part's sketch ({failed})")
wt2, wf2 = W.open_cell(nHeat2d.id, "setup"), W.open_cell(nStress2d.id, "setup")
for w2 in (wt2, wf2):
    w2.tab.picker.refresh()
    w2.tab.picker.select(sid2)
    w2.tab.picker.go()
tt2, tf2 = wt2.tab, wf2.tab
xs = {l: [tt2.model.pts[p_][0] for p_ in tt2.model.lns[l][:2]] for l in tt2.model.lns}
left2 = next(l for l, x in xs.items() if max(x) < 1e-9)
right2 = next(l for l, x in xs.items() if min(x) > 99)
tt2.supports = [{"kind": "temp", "T": 373.15, "targets": [("ln", left2)]}, {"kind": "temp", "T": 293.15, "targets": [("ln", right2)]}]
tt2.e_h.setText("2")
tt2.refresh_lists()
xs = {l: [tf2.model.pts[p_][0] for p_ in tf2.model.lns[l][:2]] for l in tf2.model.lns}
leftf = next(l for l, x in xs.items() if max(x) < 1e-9)
ends = {pid for l in tf2.model.lns for pid in tf2.model.lns[l][:2]}                 # the corners of the bar (the sketch may hold other points)
ys = {pid: tf2.model.pts[pid] for pid in ends}
corner = min(ys, key=lambda k: ys[k][0] ** 2 + ys[k][1] ** 2)
tf2.supports = [{"mode": "x", "targets": [("ln", leftf)]}, {"mode": "y", "targets": [("pt", corner)]}]
tf2.e_alpha.setText("1.2e-5")
tf2.e_tref.setText("20")
tf2.e_h.setText("2")
tf2.cb_auto.setChecked(False)
tf2.refresh_lists()
W.sync_editors()
ok(P.status(nStress2d.id, "setup") == wp.INCOMPLETE, "the 2D stress analysis has supports but no load: incomplete on its own")
W.scene.make_link(nHeat2d.id, "setup", nC2.id, "physics")
W.scene.make_link(nStress2d.id, "setup", nC2.id, "physics")
ok(P.status(nStress2d.id, "setup") == wp.OK, "wired in, it is ready")
ok(wb_coupled.CoupledAdapter().problems(W, nC2) is None, "a 2D heat analysis and a 2D stress analysis of the same sketch fit")
n_calls = len(calls)
done, failed = W.update_project(only={nHeat2d.id, nStress2d.id, nC2.id})
ok(not failed and len(calls) == n_calls + 1, f"Update: one coupled solve ({failed}) {MSGS[-3:]}")
wc2 = W.editor_of(nC2.id)
ok(wc2 is not None and wc2.result is not None and wc2.result["ok"] and wc2.result["dim"] == 2 and all(c["ok"] for c in wc2.result["checks"]), "the 2D result is there and every check passes")
ok(W.hosted_by(nStress2d.id) == nC2.id and W.hosted_by(nHeat2d.id) == nC2.id, "the two 2D analyses are shown inside the window of the Coupled block (no tab of their own)")
ok(all(w_ is not wt2 and w_ is not wf2 for w_ in (W.editor_of(nHeat2d.id), W.editor_of(nStress2d.id))) and all(widget_gone(w_) or shell.tabs.indexOf(w_) < 0 for w_ in (wt2, wf2)), "and the tabs they had are gone")
tf2 = W.editor_of(nStress2d.id).tab                                                       # (the window that the block shows now: it holds the setup that was made in the tab, and the result)
nodes2 = np.asarray((tf2.result.get("mesh") or tf2.mesh)["nodes"], float)               # (quadratic elements: the result has the mid-nodes too)
ux = np.asarray(tf2.result["u"])[:, 0]
dx2d = float(ux[np.abs(nodes2[:, 0] - nodes2[:, 0].max()) < 1e-9].mean())
ok(abs(dx2d - 0.048) / 0.048 < 0.02, f"2D: the right end grows alpha (Tmean - Tref) L = 0.048 mm ({dx2d:.5f})")
ok("2D" in wc2.report_html() and "Heat analysis" in wc2.report_html(), "the window's report shows the heat and stress parts")
# a 2D heat analysis with a 3D stress analysis
W.scene.make_link(nStress.id, "setup", nC2.id, "physics")
why = wb_coupled.CoupledAdapter().problems(W, nC2)
ok(why is not None and "One Thermal and one Static Structural" in why, f"a second stress analysis is refused: '{why}'")
for k in list(P.links):
    if k.a == nStress2d.id and k.b == nC2.id:
        W.scene.remove_link(k)
why = wb_coupled.CoupledAdapter().problems(W, nC2)
ok(why is not None and "2D" in why and "3D" in why, f"a 2D heat analysis with a 3D stress analysis is refused in words: '{why[:140] if why else why}'")
for k in list(P.links):
    if k.a == nStress.id and k.b == nC2.id:
        W.scene.remove_link(k)
W.scene.make_link(nStress2d.id, "setup", nC2.id, "physics")
ok(wb_coupled.CoupledAdapter().problems(W, nC2) is None, "wired as before, the 2D block is fine again")

# saving the project and opening it: nothing computed, nothing lost
f1 = os.path.join(T, "coupled.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "the project is saved")
raw = open(f1, encoding="utf-8").read()
ok("opara_wb" not in raw and T not in raw, "no temporary folder, no path of this computer in the file")
shell.close_tab(shell.tabs.indexOf(W))
W3 = shell.open_path(f1)
p3 = W3.project
nC3 = next(n for n in p3.nodes.values() if n.kind == "coupled")
ok(p3.status(nC3.id, "setup") == wp.OK and p3.status(nC3.id, "solution") != wp.OK, f"opened: nothing is computed, the solution wants an update ({p3.statuses(nC3.id)})")
n_before = len(calls)
done, failed = W3.update_project()
ok(not failed, f"Update Project computes it again ({failed})")
wsx = next(W3.editor_of(n.id) for n in p3.nodes.values() if n.kind == "solid")
nn, uu = np.asarray(wsx.result["nodes"], float), np.asarray(wsx.result["u"], float)
dx2 = float(uu[np.abs(nn[:, 0] - nn[:, 0].max()) < 1e-6, 0].mean())
ok(abs(dx2 - 0.096) / 0.096 < 0.02, f"the same answer from the saved project ({dx2:.5f})")
ok(len(calls) == n_before + 2, f"one solve for each of the two Coupled Physics blocks ({len(calls) - n_before})")

# the block on its own
out = os.path.join(T, "out")
os.makedirs(out)
a = wb_nodes.adapter_for("coupled")
dest = a.export(W3, nC3, out)
ok(dest.endswith(".gpx") and os.path.isfile(os.path.join(dest, "simulation.json")) and json.load(open(os.path.join(dest, "simulation.json")))["format"] == "openpara-sim-coupled", f"saved on its own as a .gpx project folder ({os.path.basename(dest)})")

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
