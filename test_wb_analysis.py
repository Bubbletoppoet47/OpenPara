"""The analysis blocks of the Workbench in the real program window: a Part wired to a 3D Static Structural block (Refresh copies it into the analysis, the setup is made in the
usual tab and read back, Update solves in that tab), the part edited (the analysis says refresh / update and a second Update gives the new answer), saving the project and opening
it again (nothing is computed, nothing is lost, the setup is still there), closing the tab (the solution is out of date again), saving the block on its own as a .gpv folder
that opens and solves in the program, an Assembly (its parts live inside it) wired to a 3D Thermal block, and the 2D analyses (opened, saved, exported; solving needs a sketch).
python test_wb_analysis.py"""
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

# ------------------------------------------------------------------------------------------------------------------------------------ Part -> 3D Static Structural
P = W.project
nBar = W.add_block("part", 40, 60, title="Bar", data={"doc": bar_json(10)})
nA = W.add_block("solid", 400, 60, title="Bar analysis")
ok(P.status(nBar.id, "geometry") == wp.OK and P.status(nA.id, "geometry") == wp.INCOMPLETE, "the part is ok, the analysis has no geometry yet")
W.scene.make_link(nBar.id, "geometry", nA.id, "geometry")
ok(P.status(nA.id, "geometry") == wp.REFRESH, f"a wire to the part: the analysis says refresh ({P.status(nA.id, 'geometry')})")
plan = [(s["name"], s["action"]) for s in P.plan_update()]
ok(plan == [(f"{nA.label}2", "refresh")], f"Update would refresh the geometry cell ({plan})")
done, failed = W.refresh_project()
ok(done == 1 and not failed, f"Refresh Project did it ({failed})")
ok(P.status(nA.id, "geometry") == wp.OK, "the geometry cell is ok")
files = nA.data["files"]
ok("simulation.json" in files and any(k.startswith("source/") and k.endswith(".gpd") for k in files), f"the analysis holds a project folder with its own copy of the part ({sorted(files)})")
man = json.loads(files["simulation.json"]["text"])
ok(man["source"]["orig"] is None and man["format"] == "openpara-sim-solid", "no path of a file on this computer in it")
ok("opara_wb" not in json.dumps(files), "nor a temporary folder of the workbench")
ok(P.status(nA.id, "setup") == wp.INCOMPLETE and P.status(nA.id, "solution") == wp.INCOMPLETE, "setup and solution wait for the setup")

# the setup is made in the usual window
w = W.open_cell(nA.id, "setup")
import solid_tab
ok(isinstance(w, solid_tab.SolidWindow) and shell.tabs.indexOf(w) >= 0, "double-click opens the 3D FEA window in a tab")
ok(shell.tabs.tabText(shell.tabs.indexOf(w)).startswith(f"{nA.label} Bar analysis"), f"named after the block ({shell.tabs.tabText(shell.tabs.indexOf(w))})")
ok(w.geom is not None and abs(w.geom["volume"] - 10000) < 1e-6, "it shows the part that was copied in (volume 10000 mm3)")
fp = W.node_state[nA.id]["folder"]
ok(not any(os.path.abspath(i["path"]) == os.path.abspath(fp) for i in recent.items()), "its project folder is not in the recent list")
tabs, cur = shell.session_tabs()
ok(all(t["path"] != os.path.abspath(fp) for t in tabs), "nor in the session")
s_geo, s_set = stamp(P, nA.id, "geometry"), stamp(P, nA.id, "setup")
ok(W.sync_editors() == [], "opening it is not a change")


def face(win, n):
    return next(f["id"] for f in win.geom["faces"] if np.dot(f["normal"], n) > 0.99)


left, right = face(w, [-1, 0, 0]), face(w, [1, 0, 0])
w.select_faces([left])
ok(w.add_support("fixed"), "a fixed support on the left end")
w.select_faces([right])
ok(w.add_load("force", {"f": [1000.0, 0.0, 0.0]}), "a force of 1000 N on the right end")
w.set_size("6")
w.inputs_changed()
ch = W.sync_editors()
ok(ch == [nA.id], f"the project reads the setup back ({ch})")
ok(stamp(P, nA.id, "setup") == s_set + 1 and stamp(P, nA.id, "geometry") == s_geo, "the setup changed, the geometry did not")
ok(P.status(nA.id, "setup") == wp.OK, f"the setup is ok ({P.status(nA.id, 'setup')})")
ok(P.status(nA.id, "solution") == wp.UPDATE, f"and the solution says update ({P.status(nA.id, 'solution')})")
st_text = nA.data["files"]["state.sim"]["text"]
ok('"supports"' in st_text and '"loads"' in st_text and '"fixed"' in st_text, "the project file holds the supports and loads")
ok(W.sync_editors() == [], "the same state again is not a change")

done, failed = W.update_project()
ok(done == 1 and not failed, f"Update Project solved ({failed})")
ok(w.result is not None and abs(w.result["umax"] - 0.005) / 0.005 < 0.03, f"the answer is the bar's: u = F L / (A E) = 0.005 mm ({w.result['umax'] if w.result else None})")
ok(all(P.status(nA.id, k) == wp.OK for k in ("geometry", "setup", "solution", "results")), f"every cell is ok ({P.statuses(nA.id)})")
ok(W.update_project()[0] == 0, "a second Update has nothing to do")

# the part is edited: the analysis follows
ped = W.open_cell(nBar.id, "geometry")
ped.doc.params["H"] = "20"
ped.update_all()
W.sync_editors()
ok(P.status(nA.id, "geometry") == wp.REFRESH and P.status(nA.id, "solution") == wp.UPDATE, f"the analysis says refresh and update ({P.statuses(nA.id)})")
ok(abs(w.result["umax"] - 0.005) / 0.005 < 0.03, "(the old result is still in its tab)")
plan = [(s["name"], s["action"]) for s in P.plan_update()]
ok(plan == [(f"{nA.label}2", "refresh"), (f"{nA.label}4", "update")], f"Update would refresh, then solve ({plan})")
done, failed = W.update_project()
ok(done == 2 and not failed, f"it did both ({failed})")
w2 = W.editor_of(nA.id)
ok(w2 is not None and w2.result is not None, "the analysis is open again with a result")
ok(w2 is not w and shell.tabs.indexOf(w) < 0 and sum(isinstance(shell.tabs.widget(i), solid_tab.SolidWindow) for i in range(shell.tabs.count())) == 1, "in a new tab: the old one was closed for the refresh, there is one analysis tab")
ok(abs(w2.geom["volume"] - 20000) < 1e-6, f"on the new part (volume {w2.geom['volume']:.0f})")
ok(len(w2.setup["supports"]) == 1 and len(w2.setup["loads"]) == 1, "the supports and loads followed their faces")
ok(abs(w2.result["umax"] - 0.0025) / 0.0025 < 0.04, f"the new answer: half the displacement, A is doubled ({w2.result['umax']:.5f})")
ok(all(P.status(nA.id, k) == wp.OK for k in ("geometry", "setup", "solution", "results")), "every cell is ok again")
src_gpd = [k for k in nA.data["files"] if k.startswith("source/") and k.endswith(".gpd")][0]
ok('"H": "20"' in nA.data["files"][src_gpd]["text"], "the copy in the project is the new part")

# saving the project and opening it: nothing computed, nothing lost
f1 = os.path.join(T, "bar.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "the project is saved")
raw = open(f1, encoding="utf-8").read()
ok("opara_wb" not in raw and T not in raw, "no temporary folder, no path of this computer in the file")
ok(len(raw) < 400000, f"and it is small ({len(raw)} bytes): no mesh, no result")
shell.close_tab(shell.tabs.indexOf(W))
ok(not any(isinstance(shell.tabs.widget(i), solid_tab.SolidWindow) for i in range(shell.tabs.count())), "closing the workbench closed the analysis tab too")
W3 = shell.open_path(f1)
p3 = W3.project
nA3 = [n for n in p3.nodes.values() if n.kind == "solid"][0]
ok(shell.tabs.count() == 1, "the project opens with no editor")
ok(p3.statuses(nA3.id) == {"geometry": wp.OK, "setup": wp.OK, "solution": wp.UPDATE, "results": wp.INCOMPLETE}, f"geometry and setup are ok, the solution wants an update ({p3.statuses(nA3.id)})")
done, failed = W3.update_project()
ok(done == 1 and not failed, f"Update Project computes it again ({failed})")
w3 = W3.editor_of(nA3.id)
ok(abs(w3.result["umax"] - 0.0025) / 0.0025 < 0.04, f"the same answer from the saved project ({w3.result['umax']:.5f})")

# closing the analysis tab: the result is gone, the solution says so
ok(shell.close_tab(shell.tabs.indexOf(w3)), "the analysis tab is closed")
W3.sync_editors()
ok(p3.status(nA3.id, "solution") == wp.UPDATE and p3.status(nA3.id, "setup") == wp.OK, f"the solution says update again, the setup is still ok ({p3.statuses(nA3.id)})")

# saved on its own
out = os.path.join(T, "out")
os.makedirs(out)
pdir = W3.export_node(nA3.id, out)
ok(pdir and pdir.endswith(".gpv") and os.path.isdir(pdir), f"the analysis is saved on its own as a project folder ({os.path.basename(pdir or '')})")
import sim_project as sp
ok(sp.kind_of_folder(pdir) == "solid" and sp.source_file(pdir) and os.path.isfile(sp.source_file(pdir)), "which has its own copy of the part")
w4 = solid_tab.SolidWindow.open_project(None, pdir, threaded=False)
ok(len(w4.setup["supports"]) == 1 and w4.run_solve() and abs(w4.result["umax"] - 0.0025) / 0.0025 < 0.04, f"it opens and solves in the program on its own ({w4.result['umax'] if w4.result else None})")
ok(W3.export_node(nA3.id, out) != pdir, "saving again does not overwrite")

# ------------------------------------------------------------------------------------------------------------------------------------ Assembly -> 3D Thermal
nAsm = W3.add_block("assembly", 40, 300, title="Rod")
sw = W3.open_cell(nAsm.id, "geometry")
import wb_parts
wb_parts.choose_sources = lambda tab, items, parent=None: ("project", [i for i in items if i["name"] == "Bar"]) if any(i["name"] == "Bar" for i in items) else ("browse", None)
nBar3 = [n for n in p3.nodes.values() if n.kind == "part"][0]
sw.insert_dialog()
ok(len(sw.asm.components) == 1 and am.is_embedded(sw.asm.components[0]["path"]), "an assembly with a copy of the bar in it")
W3.sync_editors()
nT = W3.add_block("thermal3d", 400, 300, title="Rod heat")
W3.scene.make_link(nAsm.id, "geometry", nT.id, "geometry")
ok(p3.status(nT.id, "geometry") == wp.REFRESH, "the thermal block waits for a refresh")
done, failed = W3.refresh_project(only={nT.id})
ok(done == 1 and not failed, f"refreshed from the assembly ({failed})")
tf = nT.data["files"]
srcs = [k for k in tf if k.startswith("source/")]
ok(any(k.endswith(".gpa") for k in srcs) and any(k.endswith(".gpd") for k in srcs), f"the assembly came as plain files in the project folder ({srcs})")
ok("embedded:" not in "".join(v.get("text", "") for k, v in tf.items() if k.startswith("source/") and k.endswith(".gpa")), "with no 'embedded:' reference left in them")
wt = W3.open_cell(nT.id, "setup")
import thermal3d_tab
ok(isinstance(wt, thermal3d_tab.ThermalWindow) and wt.geom is not None, "the 3D Thermal window shows the assembly")
ok(abs(wt.geom["volume"] - 20000) < 1e-3, f"it is the bar with its thickness of 20 (volume {wt.geom['volume']:.0f})")


def tface(win, n):
    return next(f["id"] for f in win.geom["faces"] if np.dot(f["normal"], n) > 0.99 and f.get("kind", "") != "x")


tl, tr = tface(wt, [-1, 0, 0]), tface(wt, [1, 0, 0])
ok(wt.add_condition("temps", {"T": 373.15}, [tl], "Hot end") and wt.add_condition("temps", {"T": 293.15}, [tr], "Cold end"), "a hot end and a cold end")
W3.sync_editors()
ok(p3.status(nT.id, "setup") == wp.OK, f"the setup is ok ({p3.statuses(nT.id)})")
done, failed = W3.update_project(only={nT.id})
ok(done == 1 and not failed, f"3D Thermal solved from the workbench ({failed})")
ok(wt.result is not None and abs(wt.result["Tmax"] - 373.15) < 0.5 and abs(wt.result["Tmin"] - 293.15) < 0.5, f"between the two temperatures ({wt.result and (wt.result['Tmin'], wt.result['Tmax'])})")

# ------------------------------------------------------------------------------------------------------------------------------------ the 2D analyses
for kind, ext_ in (("fea", ".gpf"), ("cfd", ".gpc"), ("beam", ".gpb"), ("thermal", ".gph")):
    n2 = W3.add_block(kind, 40 + 220 * ("fea cfd beam thermal".split().index(kind)), 560, title=f"Sketch {kind}")
    W3.scene.make_link(nBar3.id, "geometry", n2.id, "geometry")
    done, failed = W3.refresh_project(only={n2.id})
    ok(done == 1 and not failed, f"{kind}: refreshed from the part ({failed})")
    ok(any(k.startswith("source/") and k.endswith(".gpd") for k in n2.data["files"]), f"{kind}: the project folder has its own copy of the part")
    ok("opara_wb" not in json.dumps(n2.data["files"]) and json.loads(n2.data["files"]["simulation.json"]["text"])["source"]["orig"] is None, f"{kind}: and no path of this computer")
    w2d = W3.open_cell(n2.id, "setup")
    ok(w2d is not None and shell.tabs.indexOf(w2d) >= 0, f"{kind}: opens in its tab")
    ok(W3.sync_editors() == [], f"{kind}: opening it is not a change")
    err = W3.run_step(n2.id, "solution", "update")
    ok(err and "sketch" in err.lower(), f"{kind}: Update says what is missing: '{err}'")
    pd2 = W3.export_node(n2.id, out)
    ok(pd2 and pd2.endswith(ext_) and sp.kind_of_folder(pd2) == kind, f"{kind}: saved on its own as {os.path.basename(pd2 or '')}")

# ------------------------------------------------------------------------------------------------------------------------------------ an analysis that is not ready says why
nN = W3.add_block("solid", 40, 800, title="Empty analysis")
W3.scene.make_link(nBar3.id, "geometry", nN.id, "geometry")
ok(W3.refresh_project(only={nN.id})[0] == 1, "(a second analysis of the bar, with no supports or loads)")
err = W3.run_step(nN.id, "solution", "update")
ok(err and "support" in err.lower(), f"Update says what is missing ({err})")
ok(p3.status(nN.id, "solution") == wp.FAILED, "and the solution cell shows failed")
ok(W3.editor_of(nN.id) is not None, "(it opened the analysis to look)")

# a refresh closes the analysis tab for the copy and opens it again (on the new geometry)
ped3 = W3.open_cell(nBar3.id, "geometry")
ped3.doc.params["H"] = "30"
ped3.update_all()
W3.sync_editors()
old_ed = W3.editor_of(nN.id)
ok(old_ed is not None and p3.status(nN.id, "geometry") == wp.REFRESH, "(the analysis is open, and the part has changed under it)")
done, failed = W3.refresh_project(only={nN.id})
new_ed = W3.editor_of(nN.id)
ok(done == 1 and not failed and new_ed is not None and new_ed is not old_ed and shell.tabs.indexOf(old_ed) < 0, f"Refresh alone: the analysis is open again in a new tab ({failed})")
ok(abs(new_ed.geom["volume"] - 30000) < 1e-6, f"and shows the new geometry (volume {new_ed.geom['volume']:.0f})")

# deleting a block closes its analysis tab
ed_n = W3.editor_of(nN.id)
W3.scene.clearSelection()
[it for it in W3.scene.items() if hasattr(it, "nid") and it.nid == nN.id][0].setSelected(True)
ok(W3.delete_selected() == 1 and nN.id not in p3.nodes, "Delete removes the analysis block")
ok(shell.tabs.indexOf(ed_n) < 0 and nN.id not in W3.node_state and nN.id not in W3.editors, "its tab is closed and what the workbench knew of it is gone")

# ------------------------------------------------------------------------------------------------------------------------------------ the 2D state: inputs kept, meshes and results left out
import pickle
import physics_store as pstore


class FakeTab:
    model = object()

    def __init__(self, supports, result):
        self.st = {"model_json": "{}", "supports": supports, "loads": [{"f": 1}], "inputs": {"e_E": "200000"}, "mesh": {"nodes": list(range(50000))}, "result": {"u": list(range(50000))},
                   "frames": [1, 2, 3]}

    def export_state(self):
        return dict(self.st)


folder = os.path.join(T, "fake.gpf")
os.makedirs(folder)
open(os.path.join(folder, "simulation.json"), "w").write(json.dumps({"format": "openpara-sim-fea", "kind": "fea", "source": None, "meta": {"sid": None}}))
pstore.save(os.path.join(folder, "state.sim"), {"main": FakeTab([{"mode": "fixed"}], None)})
big = os.path.getsize(os.path.join(folder, "state.sim"))
packed = wb_analysis.pack(folder)
small = len(wp.unpack_bytes(packed["state.sim"]))
ok(small < big / 3, f"the packed state is a fraction of the saved one ({small} against {big} bytes): the mesh and the result are left out")
dest = os.path.join(T, "fake_out")
wp.unpack_folder(packed, dest)
back = pstore.load(os.path.join(dest, "state.sim"))["main"]
ok("mesh" not in back and "result" not in back and "frames" not in back, "no mesh, result or frames in it")
ok(back["supports"] == [{"mode": "fixed"}] and back["loads"] == [{"f": 1}] and back["inputs"] == {"e_E": "200000"} and back["model_json"] == "{}", "and every input is")
d1 = wb_analysis.digests(folder)
pstore.save(os.path.join(folder, "state.sim"), {"main": FakeTab([{"mode": "fixed"}], None)})
ok(wb_analysis.digests(folder) == d1, "saving the same inputs again (new time, same everything) is not a change")
t2 = FakeTab([{"mode": "fixed"}], None)
t2.st["result"] = {"u": [1, 2, 3]}
t2.st["mesh"] = {"nodes": [1]}
pstore.save(os.path.join(folder, "state.sim"), {"main": t2})
ok(wb_analysis.digests(folder) == d1, "a different mesh or result is not a change either")
t3 = FakeTab([{"mode": "fixed"}, {"mode": "roller"}], None)
pstore.save(os.path.join(folder, "state.sim"), {"main": t3})
d3 = wb_analysis.digests(folder)
ok(d3["setup"] != d1["setup"] and d3["geometry"] == d1["geometry"], "another support is a change of the setup, not of the geometry")
ok(wb_analysis.ready_fea(wb_analysis.state_object(folder)) and not wb_analysis.ready_fea({"main": {"supports": [{"a": 1}], "loads": []}}), "a 2D FEA setup is ready with a support and a load")
ok(wb_analysis.ready_solid({"setup": {"supports": [1], "loads": [1]}}) and not wb_analysis.ready_solid({"setup": {"supports": [1], "loads": []}}), "a 3D one too")
ok(wb_analysis.ready_beam({"main": {"members": [1], "supports": [1]}}) and not wb_analysis.ready_beam({"main": {"members": [], "supports": [1]}}), "a beam with members and a support")

# a solve that starts and gives no result is a failure with a reason
w9 = W3.open_cell(nA3.id, "setup")
real = w9.run_solve
w9.run_solve = lambda: True
err = W3.run_step(nA3.id, "solution", "update")
ok(err and "result" in err and p3.status(nA3.id, "solution") == wp.FAILED, f"a solve that gives no result is a failure with its reason ({err})")
w9.run_solve = real

print()
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
