"""The Annotator -> Trainer wire of the Workbench, in the real program window.

The Annotator block gives its Dataset and its Distances; ONE Annotator can be wired into a Trainer.  Refresh takes the dataset into the Trainer's own training project (pictures are
never in the project file), Update Project never trains.  The models a Trainer made are kept INSIDE the project file up to 500 MB each, a bigger one is LINKED (and said).  A change in
the Annotator makes the Trainer's cells say refresh; the program's own reading of the dataset is not such a change.
python test_wb_trainer.py"""
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
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
SAVE = {"path": ""}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (SAVE["path"], ""))
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


def video(name, shift=0):
    p = os.path.join(T, name)
    vw = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    for i in range(12):
        fr = np.full((120, 160, 3), 30 + i * 5 + shift, np.uint8)
        cv2.rectangle(fr, (30 + i * 3, 30), (90 + i * 3, 90), (0, 200, 0), -1)
        vw.write(fr)
    vw.release()
    return p


def make_dataset(folder, n_boxed=4, with_distance=True):
    """An annotator project folder with annotated pictures; the first ones have a LiDAR distance on their box."""
    pr = ac.Project(folder, default_classes=["cup", "bottle"])
    pr.editor_id = "tester1"
    pr.import_video(video(os.path.basename(folder) + ".mp4"), stride=3, session_name="setA")
    ids = sorted(pr.manifest["images"])
    for k, i in enumerate(ids[:n_boxed]):
        pr.set_boxes(i, [(k % 2, 0.5, 0.5, 0.3, 0.3)], distances=[{"distance_m": 2.0 + k, "u": 80, "v": 60}] if with_distance and k < 2 else None)
    pr.save_manifest()
    return pr


# ============================================================================================================================ the kinds and their wires
print("--- the kinds")
ann, trn = wp.KINDS["annotator"], wp.KINDS["trainer"]
ok([c.key for c in ann.cells] == ["document", "dataset", "distances"] and [c.role for c in ann.cells] == ["data"] * 3, "the Annotator has Document, Dataset and Distances")
ok(ann.cell("dataset").provides == ("dataset",) and ann.cell("distances").provides == ("distances",) and not ann.cell("document").provides, "the Dataset and the Distances can be wired out, the document cannot")
ok([c.key for c in trn.cells] == ["dataset", "distances", "setup", "training", "models"], "the Trainer has Dataset, Distances, Setup, Training and Models")
ok([c.role for c in trn.cells] == ["import", "import", "data", "data", "view"], f"two import cells, and Training is not a compute cell, so Update Project can never train ({[c.role for c in trn.cells]})")
ok(trn.cell("models").provides == ("models",) and trn.cell("distances").optional, "the Models give models; the Distances are optional")
ok(wb_nodes.adapter_for("trainer") is not None and "trainer" not in wb_nodes.check_kinds() and wb_nodes.availability(W, "trainer")[0], "the Trainer has an adapter and is offered")

nA = W.add_block("annotator", 60, 60, title="Cups")
nT = W.add_block("trainer", 400, 60, title="Cup trainer")
nA2 = W.add_block("annotator", 60, 260, title="Other")
ok(P.why_not_link(nA.id, "document", nT.id, "dataset"), "the Annotator's document is not wired into anything")
ok(P.why_not_link(nA.id, "dataset", nT.id, "distances"), "the Dataset does not go into the Distances cell")
ok(P.why_not_link(nA.id, "dataset", nT.id, "dataset") is None and P.why_not_link(nA.id, "distances", nT.id, "distances") is None, "the Dataset goes into the Dataset, the Distances into the Distances")
P.link(nA.id, "dataset", nT.id, "dataset")
P.link(nA.id, "distances", nT.id, "distances")
why = P.why_not_link(nA2.id, "dataset", nT.id, "dataset") or ""
ok("already has a source" in why, f"a second Annotator into the same Trainer is refused ({why})")
ok(P.why_not_link(nT.id, "models", nA.id, "document"), "and a Trainer cannot be wired back into an Annotator")
ok(st(nT.id, "dataset") == wp.INCOMPLETE, f"a Trainer whose Annotator has no dataset yet is incomplete ({st(nT.id, 'dataset')})")

# ============================================================================================================================ the Annotator gives its dataset
print("--- the Annotator")
proj = os.path.join(T, "Cups.annotator")
make_dataset(proj)
nA.data["link"] = wp.rel_link(proj, None)
s_doc, s_ds, s_di = stamp(nA.id), stamp(nA.id, "dataset"), stamp(nA.id, "distances")
ok(W.sync_editors() == [] and (stamp(nA.id), stamp(nA.id, "dataset"), stamp(nA.id, "distances")) == (s_doc, s_ds, s_di), "the first look at a linked folder changes nothing")
ok(st(nA.id, "dataset") == wp.OK and st(nA.id, "distances") == wp.OK and st(nA.id, "document") == wp.OK, "but it says ready: the folder has annotated pictures and boxes with a distance")
ad = wb_nodes.adapter_for("annotator")
c = ad.counts(proj)
ok(c["images"] == 4 and c["boxes"] == 4 and c["distances"] == 2, f"it counts what is in the folder ({c})")
ok(st(nT.id, "dataset") == wp.REFRESH and st(nT.id, "distances") == wp.REFRESH, f"the Trainer says refresh ({st(nT.id, 'dataset')}, {st(nT.id, 'distances')})")

# a distance picked changes the Distances cell only; a box changes all three
pr = ac.Project(proj)
img0 = sorted(pr.manifest["images"])[2]
time.sleep(0.02)
pr.set_distances(img0, [{"distance_m": 7.5, "u": 80, "v": 60}])
ok(W.sync_editors() == [nA.id] and stamp(nA.id, "distances") == s_di + 1 and stamp(nA.id) == s_doc and stamp(nA.id, "dataset") == s_ds, "picking a distance is a change of the Distances cell only")
ad.counts(proj)
ok(ad.counts(proj)["distances"] == 3, "and it is counted")
pr.set_boxes(img0, [(1, 0.4, 0.4, 0.2, 0.2)])
pr.save_manifest()
ok(W.sync_editors() == [nA.id] and stamp(nA.id) == s_doc + 1 and stamp(nA.id, "dataset") == s_ds + 1, "a change in the boxes is a change of the document and the Dataset")

# ============================================================================================================================ Refresh takes the dataset; Update never trains
print("--- Refresh and Update")
ok(W.refresh_project()[1] == [] and st(nT.id, "dataset") == wp.OK and st(nT.id, "distances") == wp.OK, f"Refresh Project takes the dataset ({st(nT.id, 'dataset')}, {st(nT.id, 'distances')})")
ftr = os.path.join(nodes_ws := wb_nodes.workspace_of(W, nT), "Trainer.training")
tpm = tc.TrainingProject(ftr)
ok(len(tpm.data.manifest["images"]) == 4 and tpm.data.classes[:2] == ["cup", "bottle"], f"the Trainer's own training project has the 4 pictures ({len(tpm.data.manifest['images'])})")
nd = sum(1 for i in tpm.data.manifest["images"] if any(pk for pk in tpm.data.get_distances(i)))
ok(nd == 3, f"with the boxes' distances ({nd} pictures)")
ok(W.sync_editors() == [], "reading the Annotator's folder (the program rewrote its manifest) is not a change of the Annotator")
ok(st(nT.id, "dataset") == wp.OK, "so the Trainer does not say refresh again")
ok(not os.listdir(os.path.join(ftr, "runs")) and st(nT.id, "training") == wp.INCOMPLETE and st(nT.id, "models") == wp.INCOMPLETE, "no training was started: Training and Models are still incomplete")
steps = P.plan_update()
ok([s for s in steps if s["node"] == nT.id] == [], "and there is nothing left for Update Project to do in the Trainer")
ok(W.update_project()[1] == [] and not os.listdir(os.path.join(ftr, "runs")), "Update Project did not train either")

# ============================================================================================================================ the window; a model inside the project
print("--- the Trainer window and its models")
w = W.open_cell(nT.id, "training")
ok(isinstance(w, tt.TrainerTab) and shell.tabs.indexOf(w) >= 0 and W.editor_of(nT.id) is w and w in shell.dependents(W), "double-click opens the Trainer in its usual tab")
ok(os.path.abspath(w.path) == os.path.abspath(ftr) and len(w.tp.data.manifest["images"]) == 4, "on the block's training project, with its pictures")
ok(getattr(w, "workbench_block", None) and w.workbench_block["annotator"] == f"{nA.label} Cups", f"it knows it is a block fed by {nA.label} Cups ({getattr(w, 'workbench_block', None)})")
ok(W.sync_editors() == [], "opening it is not a change")
ok(not nT.data.get("models") and st(nT.id, "training") == wp.INCOMPLETE, "no model yet")

pt = os.path.join(T, "best.pt")
open(pt, "wb").write(os.urandom(5000))
for _k in ("assist", "scratch"):
    os.makedirs(ml.folder_path(w.tp.models_dir, _k), exist_ok=True)       # (the training program makes these when it saves a model)
v = ml.save_version(w.tp.models_dir, "assist", pt, "m", "Tester", classes=["cup", "bottle"], scores={"map50": 0.61})
ok(v is not None and os.path.isfile(v), "(a model was trained: its file is in the training project)")
ok(W.sync_editors() == [nT.id], "the project sees it")
ms = nT.data.get("models") or []
ok(len(ms) == 1 and ms[0]["stored"] == "inside" and ms[0]["bytes"] == 5000 and ms[0]["key"] == "assist" and "b64" in ms[0]["blob"], f"and keeps it INSIDE the project ({[(m['file'], m['stored']) for m in ms]})")
ok(ms[0]["info"].get("classes") == ["cup", "bottle"] and ms[0]["info"].get("scores") == {"map50": 0.61}, "with its information (classes, scores)")
ok(st(nT.id, "training") == wp.OK and st(nT.id, "models") == wp.OK, f"Training and Models are ok now ({st(nT.id, 'training')}, {st(nT.id, 'models')})")
ok(W.sync_editors() == [], "and the same state again is not a change")

# the project file: settings and models, no pictures
f1 = os.path.join(T, "cups.opara")
SAVE["path"] = f1
ok(W.save(True) and os.path.isfile(f1), "Save writes the project")
raw = json.load(open(f1))
dn = next(n for n in raw["nodes"] if n["title"] == "Cup trainer")["data"]
ok(set(dn) <= {"settings", "models"} and len(dn["models"]) == 1, f"the .opara holds settings and models only ({sorted(dn)})")
ok(os.path.getsize(f1) < 60000, f"and no pictures ({os.path.getsize(f1)} bytes)")
mname = ms[0]["file"]
shell.close_tab(shell.tabs.indexOf(w))
ok(W.editor_of(nT.id) is None, "(the tab is closed)")
shell.tabs.setCurrentWidget(W)
W.load(f1)
P = W.project
nT = next(x for x in P.nodes.values() if x.kind == "trainer")
nA = next(x for x in P.nodes.values() if x.kind == "annotator" and x.title == "Cups")
ok(st(nT.id, "dataset") == wp.OK and st(nT.id, "training") == wp.OK and st(nT.id, "models") == wp.INCOMPLETE or st(nT.id, "models") == wp.OK, "after opening the file the cells are as they were")
ok(W.node_state.get(nT.id, {}).get("built") is None, "(nothing of the training project is built yet: the pictures are not in the project file)")
w = W.open_cell(nT.id, "training")
ok(w is not None and len(w.tp.data.manifest["images"]) == 4, "opening the Trainer takes the pictures again from the Annotator's folder")
back = [x["file"] for x in w.tp.list_models()]
ok(back == [mname], f"and the model is back in its Models ({back})")
ok(W.sync_editors() == [] and st(nT.id, "dataset") == wp.OK, "that is not a change either")

# ============================================================================================================================ too big for the file: linked
print("--- a model over the limit")
wb_models.MODEL_LIMIT = 6000
big = os.path.join(T, "big.pt")
open(big, "wb").write(os.urandom(9000))
os.makedirs(ml.folder_path(w.tp.models_dir, "scratch"), exist_ok=True)
vb = ml.save_version(w.tp.models_dir, "scratch", big, "l", "Tester", classes=["cup", "bottle"])
W.notes = []
ok(W.sync_editors() == [nT.id], "the project sees the second model")
mb_ = [m for m in nT.data["models"] if m["file"] == os.path.basename(vb)]
ok(len(mb_) == 1 and mb_[0]["stored"] == "linked" and "blob" not in mb_[0] and mb_[0]["link"]["abs"], f"it is LINKED, not kept inside ({[(m['file'], m['stored']) for m in nT.data['models']]})")
lf = wp.resolve_link(mb_[0]["link"], None)
ok(lf and os.path.getsize(lf) == 9000, f"its file is kept where the link says ({lf})")
ok(any("limit" in n and os.path.basename(vb) in n for n in W.notes), "and the person was told")
ok(len([m for m in nT.data["models"] if m["stored"] == "inside"]) == 1, "the small model is still inside")
SAVE["path"] = f1
W.save(True)
shell.close_tab(shell.tabs.indexOf(w))
W.load(f1)
P = W.project
nT = next(x for x in P.nodes.values() if x.kind == "trainer")
w = W.open_cell(nT.id, "training")
ok(sorted(x["file"] for x in w.tp.list_models()) == sorted([mname, os.path.basename(vb)]), "after opening again both models are in the Trainer, the linked one from its file")
shell.close_tab(shell.tabs.indexOf(w))
os.remove(lf)
W.load(f1)
P = W.project
nT = next(x for x in P.nodes.values() if x.kind == "trainer")
W.notes = []
w = W.open_cell(nT.id, "training")
ok([x["file"] for x in w.tp.list_models()] == [mname] and any("not where it was" in n for n in W.notes), "a linked model whose file is gone is left out and said")
wb_models.MODEL_LIMIT = 500 * 1024 * 1024

# ============================================================================================================================ the Annotator changes again; the block on its own; delete
print("--- the window as a block: ribbon, Take from Annotator, a run, export, import, remove")
from PyQt6.QtWidgets import QToolButton


def wait(cond, secs=90):
    t0 = time.time()
    while not cond():
        app.processEvents()
        time.sleep(0.05)
        assert time.time() - t0 < secs, "timed out"


nA = next(x for x in P.nodes.values() if x.kind == "annotator" and x.title == "Cups")
ok([w.ribbon.tabText(i) for i in range(w.ribbon.count())] == ["Data", "Model", "Models", "Train", "Setup"], "the window has the Annotator's layout: a ribbon of Data, Model, Models, Train and Setup")
ok(not w.take_btn.isHidden() and w.save_as_btn.isHidden(), "Take from Annotator is there, Save project as is not (the project is the block's)")
ok(f"Fed by {nA.label} Cups" in w.foot_lbl.text() and f"{nT.label} Cup trainer" in w.bar_lbl.text(), f"the status bar says where the data comes from ({w.foot_lbl.text()})")
ok(w.tp.publish_shared is False and not w.btn_stop.isEnabled(), "its models stay in the project (not also in the Annotator's Models folder)")
w.ribbon.setCurrentIndex(w.ribbon.page_index["Setup"])
ok(w.stack.currentIndex() == 1, "the Setup tab shows the Python and its packages")
w.ribbon.setCurrentIndex(w.ribbon.page_index["Train"])
ok(w.stack.currentIndex() == 0, "the other tabs show the run")

pr = ac.Project(proj)
pr.editor_id = "tester1"
pr.import_video(video("second.mp4", 40), stride=3, session_name="setB")
for k, i in enumerate([i for i in sorted(pr.manifest["images"]) if pr.manifest["images"][i].get("session_id") == "setB"][:4]):
    pr.set_boxes(i, [(k % 2, 0.5, 0.5, 0.3, 0.3)])
pr.save_manifest()
W.sync_editors()
ok(st(nT.id, "dataset") == wp.REFRESH, "a second set in the Annotator: the Trainer says refresh")
w.take_btn.click()
pump(4)
ok(st(nT.id, "dataset") == wp.OK and len(w.tp.data.manifest["images"]) == 8 and w.sets_table.rowCount() == 2, f"Take from Annotator takes it and the cells say so ({len(w.tp.data.manifest['images'])} pictures)")
w.sets_table.cellWidget(1, 3).setCurrentIndex(1)
ok(w.tp.data.session_role("setB") == "val", "(set B is the validation set)")
w.env = {"python": sys.executable, "torch": "x", "ultralytics": "x", "cuda": False, "gpu": None, "cuda_build": None, "ok": True, "problems": [], "warnings": []}
w._update_env_view()
w.type_box.setCurrentIndex(w.type_box.findData("fake"))
n0 = len(nT.data["models"])
runs0 = len(os.listdir(w.tp.runs_dir))
ok(W.update_project()[1] == [] and len(os.listdir(w.tp.runs_dir)) == runs0, "Update Project still starts nothing")
w.btn_train.click()
wait(lambda: w.running())
wait(lambda: w.job is None)
pump(6)
ok("in this project" in w.run_label.text(), f"a run from the ribbon finishes ({w.run_label.text()})")
newm = [m for m in nT.data["models"] if m["file"] == os.path.basename(w.models_list.item(0).data(Qt.ItemDataRole.UserRole))]
ok(len(nT.data["models"]) == n0 + 1 and len(newm) == 1 and newm[0]["stored"] == "inside", f"the block has the new model at once, inside the project ({len(nT.data['models'])} models)")
ok(ml.list_versions(tc.annotator_models_dir(), "assist") == [], "and the run did not put one in the Annotator's Models folder")
ok(st(nT.id, "training") == wp.OK and W.sync_editors() == [], "Training is ok and nothing is left to read back")

w.models_list.setCurrentRow(0)
newest = w.models_list.item(0).data(Qt.ItemDataRole.UserRole)
out_pt = os.path.join(T, "exported", "my_model.pt")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out_pt, ""))
w.export_model()
info_out = out_pt[:-3] + ".json"
ok(os.path.isfile(out_pt) and open(out_pt, "rb").read() == open(newest, "rb").read() and os.path.isfile(info_out), "Export writes the model as a .pt and its information as a .json")
ok(json.load(open(info_out)).get("classes") == ["cup", "bottle"], "with its classes")
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([out_pt], ""))
m0 = len(w.tp.list_models())
w.import_model()
ok(len(w.tp.list_models()) == m0 + 1 and w.models_list.count() == m0 + 1, "Import takes the file into the project")
ok(len(nT.data["models"]) == n0 + 2 and next(m for m in nT.data["models"] if m["file"] == "my_model.pt")["info"].get("classes") == ["cup", "bottle"], "and the block keeps it inside, with its information")
big2 = os.path.join(T, "big2.pt")
open(big2, "wb").write(os.urandom(3000))
wb_models.MODEL_LIMIT = 1000
W.notes = []
ok(w.import_model_files([big2]) == 1, "a model file can be dropped on the window too")
mm = next(m for m in nT.data["models"] if m["file"] == "big2.pt")
ok(mm["stored"] == "linked" and any("limit" in n for n in W.notes), "one over the limit is linked, and said")
wb_models.MODEL_LIMIT = 500 * 1024 * 1024
for want in ("my_model.pt", "big2.pt"):
    row = next(r for r in range(w.models_list.count()) if os.path.basename(w.models_list.item(r).data(Qt.ItemDataRole.UserRole)) == want)
    w.models_list.setCurrentRow(row)
    w.remove_model()
ok(not any(m["file"] in ("my_model.pt", "big2.pt") for m in nT.data["models"]) and len(nT.data["models"]) == n0 + 1, "Remove model takes it out of the project, linked ones too")

print("--- changes, export, delete")
pr = ac.Project(proj)
img1 = sorted(pr.manifest["images"])[0]
pr.set_boxes(img1, [(0, 0.3, 0.3, 0.2, 0.2), (1, 0.7, 0.7, 0.2, 0.2)])
pr.save_manifest()
W.sync_editors()
nA = next(x for x in P.nodes.values() if x.kind == "annotator" and x.title == "Cups")
ok(st(nT.id, "dataset") == wp.REFRESH, f"a change in the Annotator makes the Trainer say refresh ({st(nT.id, 'dataset')})")
ok(W.refresh_project()[1] == [] and st(nT.id, "dataset") == wp.OK, "Refresh takes it")
nbox = sum(len(w.tp.data.get_boxes(i)) for i in w.tp.data.manifest["images"])
ok(nbox == 9, f"the Trainer's window has the new boxes ({nbox} in all)")
adt = wb_nodes.adapter_for("trainer")
out = os.path.join(T, "out")
os.makedirs(out)
p1 = adt.export(W, nT, out)
ok(p1.endswith(".training") and os.path.isfile(os.path.join(p1, "training.json")) and not os.path.exists(os.path.join(p1, "runs")), f"saved on its own, the block is a .training folder ({os.path.basename(p1)})")
ok(any(f.endswith(".pt") for _r, _d, fs in os.walk(os.path.join(p1, "models")) for f in fs), "with its models")
W.scene.clearSelection()
sel = [it for it in W.scene.items() if hasattr(it, "nid") and it.nid == nT.id]
sel[0].setSelected(True)
ok(W.delete_selected() == 1 and nT.id not in P.nodes and shell.tabs.indexOf(w) < 0 and nT.id not in W.node_state, "Delete removes the block and closes its tab")
ok(os.path.isfile(os.path.join(proj, "manifest.json")), "the Annotator's folder is the person's: it stays")
av_real = addons.tab_kinds
addons.tab_kinds = lambda: {k: v for k, v in av_real().items() if k != "trainer"}
av = adt.available(W)
ok(av[0] is False and "Trainer" in av[1], f"a switched-off add-on is said ({av[1]})")
addons.tab_kinds = av_real

print()
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
