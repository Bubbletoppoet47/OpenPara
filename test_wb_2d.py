"""A 2D analysis block of the Workbench (2D Static Structural) in the real program window, wired to a Part: the sketch is chosen in the analysis's own tab (the wire brings the part), the setup
(supports, loads) is read back into the project, Update meshes and solves in that tab, and a change of the part's sketch is taken by Refresh WITHOUT losing the supports and loads that still fit.
python test_wb_2d.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
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
shutil.copytree(os.path.join(HERE, "dev_addons", "workbench"), os.path.join(DEV, "workbench"), ignore=shutil.ignore_patterns("__pycache__"))
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
import pm_model as pm
import sim_project as sp
import sk_tools as sk
import wb_project as wp
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wb2_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
P = W.project


def plate(width, depth=10):
    """A plate `width` x 20, with ONE sketch, extruded."""
    d = pm.Document()
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (width, 20))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=float(width))
    m.add_con("dim_v", [("ln", r["lns"][1])], value=20.0)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth)))
    d.rebuild()
    return json.loads(d.to_json()), s["id"]


doc, sid = plate(100)
nPart = W.add_block("part", 40, 60, title="Plate", data={"doc": doc})
nA = W.add_block("fea", 400, 60, title="Plate 2D")
W.scene.make_link(nPart.id, "geometry", nA.id, "geometry")
done, failed = W.refresh_project(only={nA.id})
ok(done == 1 and not failed, f"Refresh copied the part into the analysis ({failed})")
ok(P.status(nA.id, "geometry") == wp.OK and P.status(nA.id, "setup") == wp.INCOMPLETE, "geometry ok; the setup waits for a sketch, supports and loads")

# the sketch is chosen in the analysis's own tab
w = W.open_cell(nA.id, "setup")
t = w.tab
ok(w is not None and t.model is None, "the analysis opens with no sketch imported yet")
t.picker.refresh()
ok(t.picker.combo.findData(sid) >= 0, "the part's sketch is in its list")
t.picker.select(sid)
t.picker.go()
ok(t.model is not None and w.meta.get("sid") == sid, "Import takes the sketch")
ch = W.sync_editors()
ok(ch == [nA.id], f"the project reads the choice back ({ch})")
ok(json.loads(wp.unpack_bytes(nA.data["files"]["simulation.json"]).decode())["meta"]["sid"] == sid, "with the sketch's id in the project")

# supports and loads: the left edge fixed, a pressure on the right edge
xs = {l: [t.model.pts[p][0] for p in t.model.lns[l][:2]] for l in t.model.lns}
left = next(l for l, x in xs.items() if max(x) < 1e-9)
right = next(l for l, x in xs.items() if min(x) > 99)
t.supports = [{"mode": "fixed", "targets": [("ln", left)]}]
t.loads = [{"kind": "pressure", "p": 0.5, "targets": [("ln", right)]}]
t.e_h.setText("4")
t.refresh_lists()
ch = W.sync_editors()
ok(ch == [nA.id], f"the supports and loads are read back ({ch})")
ok(P.status(nA.id, "setup") == wp.OK and P.status(nA.id, "solution") == wp.UPDATE, f"setup ok, solution says update ({P.statuses(nA.id)})")

# Update: mesh and solve in the tab
done, failed = W.update_project(only={nA.id})
ok(done == 1 and not failed, f"Update Project solved it ({failed})")
res = W.editor_of(nA.id).tab.result if W.editor_of(nA.id) is not None else None
ok(res is not None, "the result is in its tab")
ok(P.status(nA.id, "solution") == wp.OK and P.status(nA.id, "results") == wp.OK, f"solution and results ok ({P.statuses(nA.id)})")
import physics_store as pstore
_dest = os.path.join(T, "packed")
wp.unpack_folder(nA.data["files"], _dest)
_main = pstore.load(os.path.join(_dest, "state.sim"))["main"]
ok(not any(k in _main for k in ("mesh", "result", "last_mat", "auto_def")) and _main["supports"] and _main["loads"], "the project holds the supports and loads, and no mesh or result")
ok(W.update_project()[0] == 0, "a second Update has nothing to do")

# a solve that changes an input as a side effect (something derived): it is kept in the project, and does not make the solution out of date
t_now = W.editor_of(nA.id).tab
real_solve = t_now.run_solve


def solve_touching():
    real_solve()
    t_now.e_nld.setText("0.123")


t_now.run_solve = solve_touching
P.touch(nA.id, "setup")
ok(P.status(nA.id, "solution") == wp.UPDATE, "(the setup was touched: the solution is out of date)")
done, failed = W.update_project(only={nA.id})
ok(done == 1 and not failed and P.status(nA.id, "solution") == wp.OK, f"(Update solves it again: {failed})")
ok(W.update_project()[0] == 0 and P.plan_update() == [], "what the solve touched is not a change: nothing is out of date after it")
_dest2 = os.path.join(T, "packed2")
wp.unpack_folder(nA.data["files"], _dest2)
ok(pstore.load(os.path.join(_dest2, "state.sim"))["main"]["inputs"]["e_nld"] == "0.123", "and the project holds it")
t_now.run_solve = real_solve

# the part's sketch changes: the plate gets longer
doc2, sid2 = plate(120)
ok(sid2 == sid, f"(the sketch keeps its id in the new version: {sid2})")
nPart.data["doc"] = doc2
P.touch(nPart.id, "geometry")
ok(P.status(nA.id, "geometry") == wp.REFRESH, "the analysis says refresh")
done, failed = W.refresh_project(only={nA.id})
ok(done == 1 and not failed, f"Refresh took the new plate ({failed})")
w2 = W.editor_of(nA.id)
t2 = w2.tab
ok(w2 is not None and t2.model is not None, "its tab is open again, with the sketch imported again (the same one)")
xmax = max(p[0] for p in t2.model.pts.values())
ok(abs(xmax - 120) < 1e-6, f"it is the new plate (length {xmax:g})")
ok(len(t2.supports) == 1 and len(t2.loads) == 1, f"the support and the load are still there ({len(t2.supports)}, {len(t2.loads)})")
ok(P.status(nA.id, "setup") == wp.OK, f"so the setup is still ok ({P.status(nA.id, 'setup')})")
ok(P.status(nA.id, "solution") == wp.UPDATE, "and the solution says update again")
done, failed = W.update_project(only={nA.id})
ok(done == 1 and not failed and W.editor_of(nA.id).tab.result is not None, f"and Update solves the longer plate ({failed})")

# what is kept is what still fits the sketch; the element size too
t2 = W.editor_of(nA.id).tab
t2.e_h.setText("3")
nlines = {l: [t2.model.pts[p][0] for p in t2.model.lns[l][:2]] for l in t2.model.lns}
some_line = next(iter(nlines))
t2.supports.append({"mode": "fixed", "targets": [("ln", "no-such-edge")]})        # a support on an edge the sketch does not have
t2.supports.append({"mode": "fixed", "targets": [("ci", some_line)]})            # (a circle with the id of a line: not a circle of this sketch)
t2.loads.append({"kind": "pressure", "p": 0.1, "targets": [("ln", "no-such-edge")]})
t2.loads.append({"kind": "force", "fx": 1.0, "fy": 0.0, "targets": []})            # a load with no targets at all
t2.refresh_lists()
P.touch(nPart.id, "geometry")
W.refresh_project(only={nA.id})
t3 = W.editor_of(nA.id).tab
ok(len(t3.supports) == 1 and len(t3.loads) == 1, f"supports and loads that no longer fit are dropped, the others stay ({len(t3.supports)}, {len(t3.loads)})")
ok(t3.e_h.text() == "3", f"the element size is the one that was set ({t3.e_h.text()})")
ok("4 support(s) or load(s)" in W.line.text() and "dropped" in W.line.text(), f"and it is said, with the result of the Refresh ({W.line.text()[:120]})")
W.refresh_project()
ok("dropped" not in W.line.text(), "(the next Refresh does not repeat it)")

print()
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
