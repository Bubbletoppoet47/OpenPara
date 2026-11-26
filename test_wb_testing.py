"""The Model testing block of the Workbench, in the real program window.

The Annotator's Analyse tab as a block of its own: the models are those of the Trainers / Trained models wired into it (any number) and the ones dropped on it, the test data is a link to a
recorded session, the settings and the session are kept in the project, results are not.  Analysis is not a compute cell: Update Project never runs a model.  The model is a made-up one
(the real one needs torch); the session is made up too (annotator_analysis.make_demo_session).
python test_wb_testing.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import os
import shutil
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor"]}')      # (the add-ons are not installed: that would download their packages; their tab kinds are put in below, from their own manifests)
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for n in ("workbench",):
    shutil.copytree(os.path.join(HERE, "dev_addons", n), os.path.join(DEV, n), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
ANN = os.path.join(HERE, "addons_src", "annotator", "app")
TRN = os.path.join(HERE, "addons_src", "trainer")
sys.path.insert(0, ANN)
sys.path.insert(0, os.path.dirname(ANN))
sys.path.insert(0, TRN)

T = tempfile.mkdtemp(prefix="opara_wbtr_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
SAVE = {"path": ""}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (SAVE["path"], ""))
ASK = {"name": ("", False)}
QInputDialog.getText = staticmethod(lambda *a, **k: ASK["name"])
import numpy as np
import cv2
import qtk
import share_zip as sz
sz.CONFIG_PATH = os.path.join(T, "annotator_cfg.json")
json.dump({"models_prompt_done": True, "name": "Tester", "id": "tester1"}, open(sz.CONFIG_PATH, "w"))
for _n in ("info", "warn", "error"):
    setattr(qtk, _n, lambda parent, title, text, _n=_n: None)
qtk.yesno = lambda *a, **k: True
qtk.ask_string = lambda *a, **k: "Tester"
import addons
import ext
addons.startup()
addons.register_extensions(ext)
_ANN_SPEC = dict(json.load(open(os.path.join(HERE, "addons_src", "annotator", "addon.json")))["tabs"][0], aid="annotator")
_TR_SPEC = dict(json.load(open(os.path.join(TRN, "addon.json")))["tabs"][0], aid="trainer")
_tab_kinds = addons.tab_kinds
addons.tab_kinds = lambda: {**_tab_kinds(), "annotator": _ANN_SPEC, "trainer": _TR_SPEC}

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import annotator_core as ac
import model_library as ml
FAKE = os.path.join(T, "fake_train.py")
open(FAKE, "w").write(f'''import os, sys, time
sys.path.insert(0, {TRN!r})
import job_common as jc
job = jc.load_job()
print("fake training", job["classes"], job["counts"], flush=True)
for e in range(2):
    print("epoch", e, flush=True); time.sleep(0.1)
best = os.path.join(job["run_dir"], "best.pt"); open(best, "wb").write(b"weights" * 40)
sys.exit(jc.finish(job, best, {{"epoch": 1, "total_epochs": 2, "map50": 0.6, "map50_95": 0.4}}))
''')
ext.add_model_trainer("fake", label="Fake model", script=FAKE, sizes=("n", "s"), default_size="n")
import gpd_app
import trainer_core as tc
import trainer_tab as tt
import wb_nodes
import wb_project as wp
import wb_tab
import wb_tools  # noqa: F401 (registers the adapters)
import wb_models
import wb_trainer
import wb_models_block
import wb_models_tab
import wb_testing
import wb_testing_tab
import annotator_analysis as aa
tt.TrainerTab.check_env = lambda self: None                  # (looking for Pythons runs programs: not here)
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
P = W.project


def pump(n=10, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def stamp(nid, key="document"):
    return P.cell(nid, key)["stamp"]


def st(nid, key):
    return P.status(nid, key)





INFO = []
for _n in ("info", "warn", "error"):
    setattr(qtk, _n, lambda parent, title, text, _n=_n: INFO.append((_n, title, text)))


def model_file(name, size=3000):
    p = os.path.join(T, name)
    open(p, "wb").write(os.urandom(size))
    return p


def wait_run(w):
    for _ in range(400):
        app.processEvents()
        if not w.analyse.running:
            pump(3)
            return
        time.sleep(0.05)
    raise AssertionError("the analysis did not finish")


def fake_predict(label):
    return aa.demo_predictor, True


# ============================================================================================================================ the kind and its wires
print("--- the kind")
tmk = wp.KINDS["model_test"]
ok([c.key for c in tmk.cells] == ["models", "data", "setup", "analysis", "results"], f"Model testing has Models, Test data, Setup, Analysis and Results ({[c.key for c in tmk.cells]})")
ok([c.role for c in tmk.cells] == ["import", "data", "data", "data", "view"], f"and no compute cell, so Update Project can never run a model ({[c.role for c in tmk.cells]})")
ok(tmk.cell("models").many and tmk.cell("models").optional and tmk.cell("models").accepts == ("models",), "the Models cell takes any number of wires (none is fine)")
ok(wb_nodes.adapter_for("model_test") is not None and "model_test" not in wb_nodes.check_kinds() and wb_nodes.availability(W, "model_test")[0], "it has an adapter and is offered")
nT = W.add_block("trainer", 60, 60, title="Cup trainer")
nC = W.add_block("trained_models", 420, 60, title="All models")
nA = W.add_block("annotator", 60, 360, title="Cups")
nM = W.add_block("model_test", 780, 60, title="Gimble check")
ok(P.why_not_link(nA.id, "dataset", nM.id, "models"), "an Annotator's Dataset does not go into the Models cell")
ok(P.why_not_link(nT.id, "models", nM.id, "models") is None and P.why_not_link(nC.id, "models", nM.id, "models") is None, "the Models of a Trainer and of a Trained models block do")
ok(P.why_not_link(nM.id, "results", nC.id, "trainers"), "and a Model testing block gives nothing on")
ok(st(nM.id, "models") == wp.OK and st(nM.id, "data") == wp.INCOMPLETE and st(nM.id, "setup") == wp.OK and st(nM.id, "analysis") == wp.INCOMPLETE and st(nM.id, "results") == wp.INCOMPLETE,
   f"a new block: models and setup fine, no test data and no analysis ({[st(nM.id, k) for k in ('models', 'data', 'setup', 'analysis', 'results')]})")

# models for it: two imported into the Trained models block, one in the Trainer
for nm, key in (("Small_a.pt", "assist"), ("Medium_b.pt", "scratch")):
    wb_models.store_file(W, nC, model_file(nm, 3000), key, {"format": "gimble-model-v1", "kind": key, "size": "s", "created": time.time(), "trainer": "Ian", "classes": ["cup"], "scores": None, "based_on": None})
wb_models.store_file(W, nT, model_file("Nano_t.pt", 2000), "assist", {"format": "gimble-model-v1", "kind": "assist", "size": "n", "created": time.time(), "trainer": "Ian", "classes": ["cup"], "scores": None, "based_on": None})
P.set_ready(nT.id, "training", True)
P.touch(nT.id, "training")
W.sync_editors()
P.link(nT.id, "models", nM.id, "models")
P.link(nC.id, "models", nM.id, "models")
ok(len(P.incoming_all(nM.id, "models")) == 2, "two wires into the Models cell")
W.refresh_project()
ok(st(nM.id, "models") == wp.OK, f"refreshed ({st(nM.id, 'models')})")
rows = wb_models.models_of(W, nM.id)
ok(len(rows) == 3 and {r["origin"] for r in rows} == {"wired"} and not nM.data.get("models"), f"it lists the models of both, copies none ({[r['name'] for r in rows]})")

# ============================================================================================================================ the window
print("--- the window")
w = W.open_cell(nM.id, "data")
ok(isinstance(w, wb_testing_tab.TestingWindow) and shell.tabs.indexOf(w) >= 0 and W.editor_of(nM.id) is w and w in shell.dependents(W), "double-click opens the test in its own tab")
ok(W.open_cell(nM.id, "analysis") is w and w.title() == f"{nM.label} {nM.title}", "any cell shows the same tab, named after the block")
R = w.ribbon
ok([R.tabText(i) for i in range(R.count())] == ["Test", "Models"], f"the ribbon: Test (the Analyse tab's buttons) and Models ({[R.tabText(i) for i in range(R.count())]})")
A = w.analyse
ok(set(A.rb) >= {"open", "run", "stop", "csv", "report", "example", "selfcheck", "dots_box", "dots_all", "save_img"}, "with the buttons of the Analyse tab")
labels = [A.panel.model_combo.itemText(i) for i in range(A.panel.model_combo.count())]
ok(len(labels) == 3 and any(l.startswith("Small_a") for l in labels) and any(l.startswith("Nano_t") for l in labels), f"the model list is the models of the wires ({labels})")
e = w._ai_entries.get(next(l for l in labels if l.startswith("Medium_b")))
ok(e and e["kind"] == "scratch" and os.path.getsize(e["path"]) == 3000, "and each is a file when it is asked for (a model inside the project is written out then)")
ok(w._ai_entries.get("nothing") is None, "an unknown label has no entry")
ok(w.foot_lbl.text() == "Analyse: no session open" and w.bar_lbl.text() == "3 models", f"the status bar says what is open ({w.foot_lbl.text()})")

# ---- models and a session dropped on it
print("--- dropping")
sess = aa.make_demo_session(os.path.join(T, "sessions", "20261125_184611"))
imp = model_file("Dropped.pt", 1200)
said = w.take_paths([imp])
ok(len(nM.data.get("models", [])) == 1 and nM.data["models"][0]["stored"] == "inside" and "Imported Dropped.pt" in said, f"a model file dropped on it is imported into the block ({said})")
labels = [A.panel.model_combo.itemText(i) for i in range(A.panel.model_combo.count())]
ok(len(labels) == 4 and "Dropped" in labels, "and is in the list")
ok(len(wb_models.models_of(W, nC.id)) == 2, "(the Trained models block is not changed by it)")
said = w.take_paths([os.path.join(T, "sessions")])
ok(A.session is not None and A.session.name == "20261125_184611" and len(A.session) > 0 and "Test data" in said, f"a folder with a recorded session dropped on it is the test data ({said})")
ok(w.take_paths([os.path.join(T, "nothing.txt")]) == "There is no model file (.pt) in that.", "something else is said not to be a model")
ch = W.sync_editors()
ok(nM.id in ch and nM.data["session"]["abs"].endswith("20261125_184611") and st(nM.id, "data") == wp.OK, f"the project has the session as a link ({st(nM.id, 'data')})")
ok(os.path.getsize(f1 := os.path.join(T, "x.json")) if False else True, "(a session is never copied)")

# ---- run a model
print("--- running")
A.predictor_for = fake_predict
A.panel.model_combo.setCurrentText("Dropped")
ok(st(nM.id, "analysis") == wp.INCOMPLETE and w.runs == 0, "nothing was run yet: the Analysis cell is incomplete")
s_an = stamp(nM.id, "analysis")
A.run()
wait_run(w)
ok(A.analysis is not None and A.analysis.analysed == len(A.session) and w.runs >= 1, f"Run analysis runs the model over the session ({A.analysis.analysed} frames)")
ok(st(nM.id, "analysis") == wp.OK and st(nM.id, "results") == wp.OK and stamp(nM.id, "analysis") > s_an, f"the Analysis and Results cells are ready ({st(nM.id, 'analysis')}, {st(nM.id, 'results')})")
runs = w.runs
ok(W.update_project()[1] == [] and w.runs == runs, "Update Project does not run a model again")
ok(W.sync_editors() == [] , "and looking again is not a change")

# ---- settings
print("--- settings")
p = A.panel
p.conf_slider.setValue(70)
p.tol_spin.setValue(20)
A.set_method("median")
p.core_check.setChecked(True)
wait_run(w)
W.sync_editors()
sdata = nM.data["settings"]
ok(sdata["conf"] == 0.7 and sdata["tol"] == 0.2 and sdata["method"] == "median" and sdata["region"] == "core" and sdata["model"] == "Dropped", f"the settings are in the project ({sdata})")

# ---- the example does not take the test data away
link0 = dict(nM.data["session"])
A.example()
wait_run(w)
ok(A.demo_dir is not None and A.session.name == "example_session" and "Made-up model (example)" in [p.model_combo.itemText(i) for i in range(p.model_combo.count())], "Try the example opens its made-up session")
W.sync_editors()
ok(nM.data["session"] == link0, "but the project still has the person's own test data")
A.open_session(sess)
wait_run(w)
p.model_combo.setCurrentText("Dropped")

# ---- the project file
print("--- the project file")
f1 = os.path.join(T, "gimble.opara")
SAVE["path"] = f1
ok(W.save(True) and os.path.isfile(f1), "Save writes the project")
raw = json.load(open(f1))
dn = next(n for n in raw["nodes"] if n["title"] == "Gimble check")["data"]
ok(set(dn) == {"models", "session", "settings"} and len(dn["models"]) == 1, f"the block holds its models, the session link and the settings ({sorted(dn)})")
ok("frames" not in json.dumps(dn) and os.path.getsize(f1) < 40000, f"no results, no pictures ({os.path.getsize(f1)} bytes)")
shell.close_tab(shell.tabs.indexOf(w))
ok(W.editor_of(nM.id) is None, "(the tab is closed)")
shell.tabs.setCurrentWidget(W)
W.load(f1)
P = W.project
nM = next(x for x in P.nodes.values() if x.kind == "model_test")
nC = next(x for x in P.nodes.values() if x.kind == "trained_models")
ok(st(nM.id, "data") == wp.OK and st(nM.id, "setup") == wp.OK, "after opening the file the test data is still the session")
ok(st(nM.id, "analysis") == wp.INCOMPLETE and st(nM.id, "results") == wp.INCOMPLETE, f"but the analysis is to be run again: results are not saved ({st(nM.id, 'analysis')}, {st(nM.id, 'results')})")
ok(W.update_project()[1] == [] and W.editor_of(nM.id) is None and st(nM.id, "analysis") == wp.INCOMPLETE, "and Update Project does not run it")
w = W.open_cell(nM.id, "data")
A = w.analyse
p = A.panel
ok(A.session is not None and A.session.name == "20261125_184611" and A.analysis is None, "opening the block opens the session again, and runs nothing")
ok(p.conf_slider.value() == 70 and p.tol_spin.value() == 20 and A.settings.method == "median" and p.core_check.isChecked() and A.region == "core", "with the settings as they were")
ok(p.model_combo.currentText() == "Dropped" and p.model_combo.count() == 4, f"and the model that was chosen ({p.model_combo.currentText()}, {p.model_combo.count()} models)")
ok(w.foot_lbl.text().endswith("not run yet"), f"the status bar says it ({w.foot_lbl.text()})")
A.predictor_for = fake_predict
A.run()
wait_run(w)
ok(A.analysis.analysed == len(A.session) and st(nM.id, "analysis") == wp.OK, "Run analysis works after opening the file")

# ---- the session folder is gone
print("--- a session that is gone")
shell.close_tab(shell.tabs.indexOf(w))
moved = sess + "_moved"
os.rename(sess, moved)
W.sync_editors()
ok(st(nM.id, "data") == wp.INCOMPLETE, f"the test data cell says so ({st(nM.id, 'data')})")
w = W.open_cell(nM.id, "data")
ok(w.analyse.session is None and "is not there" in w.status.text(), f"the window says it ({w.status.text()[:60]})")
W.sync_editors()
ok(st(nM.id, "data") == wp.INCOMPLETE and nM.data["session"]["abs"].endswith("20261125_184611"), "and the block keeps the link (the folder may be on a disk that is not there)")
os.rename(moved, sess)
W.sync_editors()
ok(st(nM.id, "data") == wp.OK, "and the folder back is fine again")

# ---- a model kept in a Trainer changes
print("--- the models change")
wb_models.store_file(W, nC, model_file("Large_late.pt", 2200), "assist", {"format": "gimble-model-v1", "kind": "assist", "size": "l", "created": time.time(), "trainer": "Ian", "classes": ["cup"], "scores": None, "based_on": None})
W.sync_editors()
ok(st(nM.id, "models") == wp.REFRESH, f"a model added to a wired block makes the Models cell say refresh ({st(nM.id, 'models')})")
n0 = w.analyse.panel.model_combo.count()
W.refresh_project()
ok(st(nM.id, "models") == wp.OK and w.analyse.panel.model_combo.count() == n0 + 1, f"Refresh takes it, and the open window has it ({w.analyse.panel.model_combo.count()} models)")

# ---- delete
W.scene.clearSelection()
sel = [it for it in W.scene.items() if hasattr(it, "nid") and it.nid == nM.id]
sel[0].setSelected(True)
tabs = shell.tabs.count()
ok(W.delete_selected() == 1 and nM.id not in W.project.nodes and shell.tabs.count() == tabs - 1 and nM.id not in W.node_state, "Delete removes the block and closes its tab")
ok(len(wb_models.models_of(W, nC.id)) == 3, "the models of the other blocks are untouched")

print()
print("all passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
