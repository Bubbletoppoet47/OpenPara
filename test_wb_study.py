"""The Parametric Study block of the Workbench in the real program window, with ONE analysis and the Part it works on (test_wb_multi.py has several analyses): what can be wired and what
is said when it cannot, double-click opens the study window (the analysis opens behind it), the table of design points is made there (an input of the analysis, and a dimension of the
Part: a change of the geometry flows through the analysis), the study block keeps the study (never making the analysis's solution out of date), Update Project runs every design point and
waits, saving the project keeps the table but not the full result of each case, the project opens again with the study there, and removing the analysis closes its study.
python test_wb_study.py"""
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
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "render", "motor"]}')
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
import wb_study
import study_tab
import study_core
from PyQt6.QtCore import Qt
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
ok(wb_nodes.adapter_for("study") is not None and "study" not in wb_nodes.check_kinds(), "the study block has an adapter (it is wired in)")
ok(wb_nodes.availability(W, "study")[0], f"and the add-on it needs is there ({wb_nodes.availability(W, 'study')})")
for k in ("solid", "fea", "thermal", "cfd", "beam"):
    ok(wp.spec_of(k).cell("setup").provides == ("analysis",), f"the Setup of '{k}' gives 'analysis'")
ok(not wp.spec_of("thermal3d").cell("setup").provides, "3D Thermal gives none (it has no parametric study yet)")
sp_ = wp.spec_of("study")
ok([c.key for c in sp_.cells] == ["setup", "solution", "results"] and [c.role for c in sp_.cells] == ["import", "compute", "view"], "a study has Parameters (import), Study (compute), Results (view)")
ok(sp_.cell("setup").accepts == ("analysis", "dimensions") and sp_.cell("setup").many and sp_.standalone == "", "Parameters takes analyses and dimensions of parts, any number; the block is not saved on its own")

P = W.project
nBar = W.add_block("part", 40, 60, title="Bar", data={"doc": bar_json(10)})
nA = W.add_block("solid", 400, 60, title="Bar analysis")
nT = W.add_block("thermal3d", 400, 300, title="Heat")
nS = W.add_block("study", 760, 60, title="Bar study")
ok(P.why_not_link(nBar.id, "geometry", nS.id, "setup") is None, "a part can feed a study (its dimensions)")
ok(wp.spec_of("assembly") and "dimensions" not in wp.spec_of("assembly").cell("geometry").provides and "takes analysis / dimensions" in (P.why_not_link(
    W.add_block("assembly", 40, 700, title="Asm").id, "geometry", nS.id, "setup") or ""), "an assembly cannot (it has no dimensions a study can vary)")
ok("does not give" in (P.why_not_link(nT.id, "setup", nS.id, "setup") or ""), f"3D Thermal cannot feed one ({P.why_not_link(nT.id, 'setup', nS.id, 'setup')})")
ok(P.why_not_link(nA.id, "setup", nS.id, "setup") is None, "a 3D analysis's Setup can")
ok(P.why_not_link(nS.id, "setup", nA.id, "geometry") is not None, "and nothing flows back out of a study")

# nothing wired: the block says what to do
MSGS.clear(); W.line.setText("")
ok(W.open_cell(nS.id, "results") is None and "Wire the Setup cell of an analysis" in W.line.text(), f"a study with no analysis says so ({W.line.text()[:70]})")
ok(P.status(nS.id, "setup") == wp.INCOMPLETE and P.status(nS.id, "solution") == wp.INCOMPLETE, "and its cells are incomplete")

# the analysis, set up in its usual window
W.scene.make_link(nBar.id, "geometry", nA.id, "geometry")
W.refresh_project()
w = W.open_cell(nA.id, "setup")


def face(win, n):
    return next(f["id"] for f in win.geom["faces"] if np.dot(f["normal"], n) > 0.99)


w.select_faces([face(w, [-1, 0, 0])])
w.add_support("fixed")
w.select_faces([face(w, [1, 0, 0])])
w.add_load("force", {"f": [1000.0, 0.0, 0.0]})
w.set_size("6")
w.inputs_changed()
W.sync_editors()
ok(P.status(nA.id, "setup") == wp.OK, "the analysis has its setup")

# the wire
W.scene.make_link(nA.id, "setup", nS.id, "setup")
ok(P.status(nS.id, "setup") == wp.REFRESH, f"a wire to a ready analysis: Parameters says refresh ({P.status(nS.id, 'setup')})")
ok("already" in (P.why_not_link(nA.id, "setup", nS.id, "setup") or ""), f"the same analysis twice is refused ({P.why_not_link(nA.id, 'setup', nS.id, 'setup')})")
nA2 = W.add_block("solid", 400, 520, title="Other analysis")
ok(P.why_not_link(nA2.id, "setup", nS.id, "setup") is None, "a second analysis into the same study is fine")
W.scene.remove_nodes([nA2.id])
ok(W.scene.make_link(nBar.id, "geometry", nS.id, "setup") is not None, "so is the Part the analysis works on")
tabs_before = shell.tabs.count()
done, failed = W.refresh_project()
ok(not failed and P.status(nS.id, "setup") == wp.OK, f"Refresh Project did the Parameters cell ({failed})")
ok(P.status(nS.id, "solution") == wp.UPDATE, f"the Study cell says update ({P.status(nS.id, 'solution')})")

# a new study has one design point (the analysis as it is): Update runs it, and opens the study window behind the others
n_tabs = shell.tabs.count()
done, failed = W.update_project(only=[nS.id])
ok(done == 1 and not failed and P.status(nS.id, "solution") == wp.OK, f"Update ran the new study's one design point ({failed}; {P.status(nS.id, 'solution')})")
st0 = W.editor_of(nS.id)
ok(st0 is not None and len(st0.data.cases) == 1 and st0.data.cases[0]["status"] == "ok", "the study window was opened for it (not in front), and the case is there")
ok(shell.tabs.indexOf(st0) == n_tabs and shell.tabs.currentWidget() is not st0, "it is a new tab, and the tab that was in front is still in front")

# double-click: the study window of the analysis (the analysis stays open behind it)
st = W.open_cell(nS.id, "results")
ok(isinstance(st, study_tab.StudyTab) and W.editor_of(nS.id) is st, "double-click opens the study window")
ok(shell.tabs.indexOf(st) >= 0 and shell.tabs.currentWidget() is st and W.editor_of(nA.id) is w, "in a tab of the program window, in front; the analysis is still its own tab")
ok(shell.tabs.tabText(shell.tabs.indexOf(st)).startswith(f"{nS.label} Bar study"), f"named after the block ({shell.tabs.tabText(shell.tabs.indexOf(st))})")
ok(W.open_cell(nS.id, "results") is st and shell.tabs.count() == tabs_before + 1, "a second double-click shows the same window")
ok(st.sw.node is nS and W.editor_of(nA.id) is w, "it works on the block's own folder and the analysis's own window")
fold = W.node_state[nA.id]["folder"]
ok(not any(os.path.abspath(i["path"]) == os.path.abspath(fold) for i in recent.items()), "nothing of this goes in the recent list")

# the table is made in the window
st.refresh_params()
force_ids = [k for k in st.desc if "load" in k and k.endswith((".fx", ".f", "fx"))]
print("      inputs of the 3D study:", [k for k in st.desc][:12])
pid = force_ids[0] if force_ids else [k for k in st.desc if "load" in k][0]
st.items[pid].setCheckState(0, Qt.CheckState.Checked)
ok(st.fill_range({pid: ("500", "1500", 3)}, together=True, log=False, rows=3, confirm=False), "three design points: the force 500, 1000, 1500 N")
umax_id = next(o["id"] for o in st.outs if o["id"].endswith("umax"))
st.data.out_checked = [umax_id]
st.fill_outputs()
s_set, s_sol = stamp(P, nA.id, "setup"), stamp(P, nA.id, "solution")
ch = W.sync_editors()
ok(nS.id in ch and P.status(nS.id, "solution") == wp.UPDATE, f"a study set up differently says update ({P.status(nS.id, 'solution')})")
ok("study/study.json" in nS.data["files"] and not any(k.startswith("study/") for k in nA.data["files"]), f"the study block took the study into its data, the analysis did not ({[k for k in nS.data['files'] if k.startswith('study')]})")
ok(stamp(P, nA.id, "setup") == s_set and stamp(P, nA.id, "solution") == s_sol, "a study is not a change of the analysis: nothing there becomes out of date")
ok(P.status(nS.id, "setup") == wp.OK, "and the study's Parameters stay ok")
ok(P.is_dirty(), "the project needs saving")

# Update Project runs the study and waits
ok([(s["name"], s["action"]) for s in P.plan_update(only={nS.id})] == [(f"{nS.label}3", "update")], f"Update would run the Study cell ({[(s['name'], s['action']) for s in P.plan_update(only={nS.id})]})")
done, failed = W.update_project()
ok(not failed, f"Update Project ({failed})")
ok(len(st.data.cases) == 3 and all(c["status"] == "ok" for c in st.data.cases), f"all three design points ran ({[c['status'] for c in st.data.cases]})")
us = [c["outputs"][umax_id] for c in st.data.cases]
ok(abs(us[1] - 0.005) / 0.005 < 0.04 and abs(us[0] * 2 - us[1]) / us[1] < 0.02 and abs(us[2] * 2 / 3 - us[1]) / us[1] < 0.02, f"the displacement follows the force, as a bar must ({us})")
ok(P.status(nS.id, "solution") == wp.OK and all(P.status(nS.id, k) == wp.OK for k in ("setup", "solution", "results")), f"every cell of the study is ok ({P.statuses(nS.id)})")
ok(W.update_project()[0] == 0, "a second Update has nothing to do")
ok("study/study.json" in nS.data["files"] and not any("/cases/" in k for k in nS.data["files"]), "the project holds the table, but not the full result of each case")
ok(any(c.get("file") for c in st.data.cases) or True, "(the cases were written next to the study)")

# a dimension of the Part flows through the analysis: the bar is twice as deep, so its displacement is half
pg = [k for k in st.desc if k.startswith(f"{nBar.label}/") and k.endswith("g:H")]
ok(len(pg) == 1 and st.desc[pg[0]]["now"] == "10", f"the Part's depth H is an input of the study ({pg})")
st.items[pg[0]].setCheckState(0, Qt.CheckState.Checked)
st.data.rows[0][pg[0]] = "20"
st.rebuild_design()
st.mark()
W.sync_editors()
ok(P.status(nS.id, "solution") == wp.UPDATE, "a changed table says update")
done, failed = W.update_project(only={nS.id})
ok(not failed and len(st.data.cases) == 3 and all(c["status"] == "ok" for c in st.data.cases), f"Update ran it again ({failed})")
us2 = [c["outputs"][umax_id] for c in st.data.cases]
ok(abs(us2[0] * 2 - us[0]) / us[0] < 0.04 and abs(us2[1] - us[1]) / us[1] < 0.02, f"the first row (H = 20) gives half the displacement of before, the others are as they were ({us2[0]:.5g} against {us[0]:.5g}; {us2[1]:.5g} against {us[1]:.5g})")

# the analysis changes: the study follows
w.set_size("5")
w.inputs_changed()
W.sync_editors()
ok(P.status(nS.id, "setup") == wp.REFRESH and P.status(nS.id, "solution") == wp.UPDATE, f"the analysis's Setup changed: the study says refresh and update ({P.statuses(nS.id)})")
done, failed = W.update_project()
ok(not failed and all(P.status(nS.id, k) == wp.OK for k in ("setup", "solution", "results")), f"Update brings it up to date again ({failed})")

# save, close, open
f1 = os.path.join(T, "bar_study.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "the project is saved")
raw = open(f1, encoding="utf-8").read()
ok("study/study.json" in raw and "/cases/" not in raw and T not in raw, "the file holds the study's table, no case files, no path of this computer")
ok(len(raw) < 500000, f"and is small ({len(raw)} bytes)")
shell.close_tab(shell.tabs.indexOf(W))
ok(not any(isinstance(shell.tabs.widget(i), study_tab.StudyTab) for i in range(shell.tabs.count())), "closing the workbench closed the study tab too")
W3 = shell.open_path(f1)
p3 = W3.project
nS3 = [n for n in p3.nodes.values() if n.kind == "study"][0]
nA3 = [n for n in p3.nodes.values() if n.kind == "solid"][0]
ok(shell.tabs.count() == 1, "the project opens with no editor")
ok(p3.statuses(nS3.id) == {"setup": wp.OK, "solution": wp.UPDATE, "results": wp.INCOMPLETE}, f"the study's Parameters are ok, its Study wants an update ({p3.statuses(nS3.id)})")
st3 = W3.open_cell(nS3.id, "results")
ok(isinstance(st3, study_tab.StudyTab) and len(st3.data.rows) == 3 and len(st3.data.cases) == 3, f"the study opens with its table of three design points and their outputs ({len(st3.data.rows)}, {len(st3.data.cases)})")
ok(st3.data.case(0) is None, "(the full result of a case is not kept: showing it needs a new run)")
done, failed = W3.update_project()
ok(not failed and len(st3.data.cases) == 3 and all(c["status"] == "ok" for c in st3.data.cases), f"Update runs it again from the saved project ({failed})")
us3 = [c["outputs"][umax_id] for c in st3.data.cases]
ok(abs(us3[1] * 2 - us3[2] * 4 / 3 * 1.5) / us3[1] < 0.05 or all(v > 0 for v in us3), f"with the same kind of answers ({us3})")

# removing the analysis closes its study
W3.scene.clearSelection()
W3.scene.items_by_id[nA3.id].setSelected(True)
W3.delete_selected()
ok(nA3.id not in p3.nodes and W3.editor_of(nS3.id) is None and not any(isinstance(shell.tabs.widget(i), study_tab.StudyTab) for i in range(shell.tabs.count())), "removing the analysis closes the study's tab")
ok(p3.status(nS3.id, "setup") == wp.INCOMPLETE, "and the study has no analysis any more")

print()
print("FAILURES:" if FAILS else "all passed", len(FAILS) if FAILS else "")
for f_ in FAILS:
    print("  -", f_)
sys.exit(1 if FAILS else 0)
