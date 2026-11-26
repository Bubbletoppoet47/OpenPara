"""Opening a simulation block of the Workbench brings its GEOMETRY up to date with the part wired into it - and does nothing else: the solve is never run.
A block whose part did not change opens as it is (no refresh), a block with no wire opens as it is, a part that is empty again leaves the block as it was and says why,
and an analysis that is already open in its tab is refreshed too (the setup follows the faces).  python test_wb_open_refresh.py"""
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
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d"):
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


import asm_model as am
import assembly
import gpd_app
import pm_model as pm
import recent
import sk_tools as sk
import wb_analysis
import wb_nodes
import wb_project as wp
import wb_tab
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wba_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
import PyQt6.QtWidgets as qw


def bar_json(depth):
    """A bar 100 x 10 (a rectangle on the top plane) extruded by the parameter H."""
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
    return json.loads(d.to_json())


def stamp(p, nid, key):
    return p.cell(nid, key)["stamp"]


ok(not addons.load_errors(), f"the add-ons load without errors ({addons.load_errors()})")
for k in ("solid", "thermal3d", "fea", "cfd", "beam", "thermal"):
    ok(wb_nodes.adapter_for(k) is not None, f"the kind '{k}' has an adapter")
ok(all(wb_nodes.availability(W, k)[0] for k in ("solid", "thermal3d", "fea", "cfd", "beam", "thermal")), f"and the add-ons they need are there ({[wb_nodes.availability(W, k) for k in ('solid', 'thermal3d', 'fea')]})")
import addons as _addons
_real_kinds = _addons.tab_kinds
_addons.tab_kinds = lambda: {k: v for k, v in _real_kinds().items() if k != "solid"}
_av = wb_nodes.availability(W, "solid")
ok(_av[0] is False and "add-on" in _av[1] and wb_nodes.availability(W, "thermal3d")[0], f"an analysis whose add-on is switched off says so, the others are still there ({_av[1][:80]})")
_addons.tab_kinds = _real_kinds
ok(all(k not in wb_nodes.check_kinds() for k in ("part", "assembly", "solid", "thermal3d", "fea", "cfd", "beam", "thermal")), f"the analyses are wired (not wired: {wb_nodes.check_kinds()})")


P = W.project
import solid_tab

nBar = W.add_block("part", 40, 60, title="Bar", data={"doc": bar_json(10)})
nA = W.add_block("solid", 400, 60, title="Bar analysis")
nFree = W.add_block("solid", 400, 260, title="Free analysis")

# ---- a block with no wire opens as it is: nothing to refresh from
w0 = W.open_cell(nFree.id, "setup")
ok(w0 is not None and P.status(nFree.id, "geometry") == wp.INCOMPLETE, f"a block with no wire opens as it is ({P.status(nFree.id, 'geometry')})")
W.close_all_editors() if hasattr(W, "close_all_editors") else None

# ---- wired, never refreshed: opening it takes the geometry (and only that)
W.scene.make_link(nBar.id, "geometry", nA.id, "geometry")
ok(P.status(nA.id, "geometry") == wp.REFRESH, "wired to the part: the geometry says refresh")
solves = []
orig_solve = wb_analysis.AnalysisAdapter.solve
wb_analysis.AnalysisAdapter.solve = lambda self, w: solves.append(1) or orig_solve(self, w)
orig_update = wb_analysis.AnalysisAdapter.update
wb_analysis.AnalysisAdapter.update = lambda self, tab, node, key: solves.append(2) or orig_update(self, tab, node, key)
w = W.open_cell(nA.id, "setup")
ok(isinstance(w, solid_tab.SolidWindow), "double-click opens the 3D FEA window")
ok(P.status(nA.id, "geometry") == wp.OK, f"and the geometry was refreshed by opening it ({P.status(nA.id, 'geometry')})")
ok(w.geom is not None and abs(w.geom["volume"] - 10000) < 1e-6, "it shows the part (volume 10000 mm3)")
ok(not solves and w.result is None, "nothing was solved")
ok(P.status(nA.id, "solution") in (wp.INCOMPLETE, wp.UPDATE), f"the solution cell is not ok ({P.status(nA.id, 'solution')})")

# ---- the setup is made, solved on request; then the part changes
def face(win, n):
    return next(f["id"] for f in win.geom["faces"] if np.dot(f["normal"], n) > 0.99)


w.select_faces([face(w, [-1, 0, 0])]); ok(w.add_support("fixed"), "a fixed support")
w.select_faces([face(w, [1, 0, 0])]); ok(w.add_load("force", {"f": [1000.0, 0.0, 0.0]}), "a force")
w.set_size("6"); w.inputs_changed(); W.sync_editors()
done, failed = W.update_project()
ok(done == 1 and not failed and w.result is not None, f"Update Project solves it ({failed})")
solves.clear()
ok(all(P.status(nA.id, k) == wp.OK for k in ("geometry", "setup", "solution")), "all ok")

# ---- opening it again when the part did not change: no refresh, the window and its result stay
st0 = stamp(P, nA.id, "geometry")
w_same = W.open_cell(nA.id, "setup")
ok(w_same is w and stamp(P, nA.id, "geometry") == st0 and w.result is not None, "the part did not change: opening only shows the tab, the result stays")

# ---- the part is edited: opening the analysis refreshes the geometry only
ped = W.open_cell(nBar.id, "geometry")
ped.doc.params["H"] = "20"
ped.update_all()
W.sync_editors()
ok(P.status(nA.id, "geometry") == wp.REFRESH, "the analysis says refresh")
w2 = W.open_cell(nA.id, "setup")
ok(P.status(nA.id, "geometry") == wp.OK, f"opening it refreshed the geometry ({P.status(nA.id, 'geometry')})")
ok(w2 is not None and abs(w2.geom["volume"] - 20000) < 1e-6, f"the window shows the new part (volume {w2.geom['volume']:.0f})")
ok("geometry was refreshed" in W.line.text() and "Nothing was solved" in W.line.text(), f"and it says so: the geometry was refreshed and nothing was solved ({W.line.text()[:90]})")
ok(len(w2.setup["supports"]) == 1 and len(w2.setup["loads"]) == 1, "the supports and loads followed their faces")
ok(not solves, f"and still nothing was solved ({solves})")
ok(w2.result is None and P.status(nA.id, "solution") == wp.UPDATE, f"the old answer is gone and the solution says update ({P.status(nA.id, 'solution')})")
# whichever cell is double-clicked
ped.doc.params["H"] = "30"; ped.update_all(); W.sync_editors()
w3 = W.open_cell(nA.id, "solution")
ok(P.status(nA.id, "geometry") == wp.OK and abs(w3.geom["volume"] - 30000) < 1e-6 and not solves, "double-clicking the Solution cell does the same (and still does not solve)")

# ---- a refresh that fails: the block opens as it was, with the reason
nP2 = W.add_block("part", 40, 460, title="Second bar", data={"doc": bar_json(10)})
nB = W.add_block("solid", 400, 460, title="Second analysis")
W.scene.make_link(nP2.id, "geometry", nB.id, "geometry")
ok(P.status(nB.id, "geometry") == wp.REFRESH, "a second analysis waits for its first refresh")
said = []
orig_say = W.say
W.say = lambda t, *a, **k: said.append(t) or orig_say(t, *a, **k)
orig_refresh = wb_analysis.AnalysisAdapter.refresh
wb_analysis.AnalysisAdapter.refresh = lambda self, tab, node, key: "the part could not be copied (test)"
wb = W.open_cell(nB.id, "setup")
wb_analysis.AnalysisAdapter.refresh = orig_refresh
ok(wb is not None and not solves, "it opens anyway, and nothing is solved")
ok(P.status(nB.id, "geometry") == wp.FAILED, f"the geometry cell says failed ({P.status(nB.id, 'geometry')})")
ok(said and "could not be refreshed" in said[-1] and "the part could not be copied (test)" in said[-1], f"and the reason is the last thing said, not buried by the editor's hint ({said[-1:]})")
W.say = orig_say

# ---- the 2D kinds are analysis blocks too
for k in ("fea", "thermal", "cfd", "beam", "thermal3d", "fluid3d"):
    ok(getattr(wb_nodes.adapter_for(k), "simulation", False), f"'{k}' is an analysis block: opening it refreshes its geometry")
for k in ("part", "assembly", "sheets", "drawing", "pdf", "annotator", "study", "coupled"):
    a = wb_nodes.adapter_for(k)
    ok(a is None or not getattr(a, "simulation", False), f"'{k}' is not")

print("FAILED:" if FAILS else "ALL PASSED", FAILS)
sys.exit(1 if FAILS else 0)
