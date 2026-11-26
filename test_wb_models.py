"""The Trained models block of the Workbench, in the real program window.

ONE list of every model: the ones trained in the Trainers wired into it (they stay in the Trainer), the ones imported into it (inside the project file up to 500 MB, linked above that) and
the ones in the shared Models folder (downloaded from GitHub; listed, never copied).  The window filters the list (all / embedded / GitHub), sorts it, imports (files, a folder, drops),
exports, renames and removes.  A change in the list makes what is wired downstream say refresh.
python test_wb_models.py"""
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




def model_file(name, size=3000):
    p = os.path.join(T, name)
    open(p, "wb").write(os.urandom(size))
    return p


def names(w, mode="all"):
    """The model names the window's list shows for a filter."""
    w.filter_box.setCurrentIndex([k for k, _t, _tip in wb_models_tab.FILTERS].index(mode))
    pump(2)
    return [w.table.item(i, 0).text() for i in range(w.table.rowCount())]


def pick(w, name):
    for i in range(w.table.rowCount()):
        if w.table.item(i, 0).text() == name:
            w.table.selectRow(i)
            pump(1)
            return True
    return False


# ============================================================================================================================ the kind and its wires
print("--- the kind")
tm = wp.KINDS["trained_models"]
ok([c.key for c in tm.cells] == ["trainers", "library", "models"] and [c.role for c in tm.cells] == ["import", "data", "view"], f"Trained models has From trainers, Library and Models ({[c.key for c in tm.cells]})")
ok(tm.cell("trainers").many and tm.cell("trainers").optional and tm.cell("trainers").accepts == ("models",) and tm.cell("models").provides == ("models",), "it takes any number of Trainers (none is fine) and gives models")
ok(wb_nodes.adapter_for("trained_models") is not None and "trained_models" not in wb_nodes.check_kinds() and wb_nodes.availability(W, "trained_models")[0], "it has an adapter and is offered")
nT = W.add_block("trainer", 60, 60, title="Cup trainer")
nT2 = W.add_block("trainer", 60, 260, title="Other trainer")
nA = W.add_block("annotator", 60, 460, title="Cups")
nC = W.add_block("trained_models", 420, 60, title="All models")
nC2 = W.add_block("trained_models", 780, 60, title="Second list")
ok(P.why_not_link(nA.id, "dataset", nC.id, "trainers"), "an Annotator's Dataset does not go into the From trainers cell")
ok(P.why_not_link(nT.id, "models", nC.id, "trainers") is None and P.why_not_link(nT2.id, "models", nC.id, "trainers") is None, "the Models of any number of Trainers do")
ok(P.why_not_link(nC.id, "library", nC2.id, "trainers"), "the Library is not wired out, the Models are")
ok(P.why_not_link(nC.id, "models", nC2.id, "trainers") is None, "a Trained models block can be wired into another")

# ============================================================================================================================ an empty block
print("--- an empty block")
ok(st(nC.id, "trainers") == wp.OK and st(nC.id, "library") == wp.INCOMPLETE and st(nC.id, "models") == wp.INCOMPLETE, f"nothing in the list: Library and Models are incomplete ({st(nC.id, 'library')}, {st(nC.id, 'models')})")
ok(wb_models.models_of(W, nC.id, shared=False) == [], "the list is empty")

# ============================================================================================================================ a Trainer's model: listed, not copied
print("--- a model of a Trainer")
w1 = W.open_cell(nT.id, "training")
pt = model_file("Small_trained.pt", 5000)
for _k in ("assist", "scratch"):
    os.makedirs(ml.folder_path(w1.tp.models_dir, _k), exist_ok=True)
v = ml.save_version(w1.tp.models_dir, "assist", pt, "s", "Tester", classes=["cup", "bottle"], scores={"map50": 0.61, "map50_95": 0.4})
ok(W.sync_editors() == [nT.id] and len(nT.data["models"]) == 1, "the Trainer has a model (inside its block)")
P.link(nT.id, "models", nC.id, "trainers")
W.sync_editors()
rows = wb_models.models_of(W, nC.id, shared=False)
ok(len(rows) == 1 and rows[0]["origin"] == "wired" and rows[0]["from"] == f"{nT.label} {nT.title}" and rows[0]["name"].startswith("Small_"), f"Trained models lists it, as a model of the Trainer ({[(r['name'], r['origin'], r['from']) for r in rows]})")
ok(not nC.data.get("models"), "and did not copy it: the block holds no model of its own")
ok(st(nC.id, "trainers") == wp.REFRESH and st(nC.id, "library") == wp.OK, f"the wire says refresh, and the Library is ready ({st(nC.id, 'trainers')}, {st(nC.id, 'library')})")
ok(W.refresh_project()[1] == [] and st(nC.id, "trainers") == wp.OK and st(nC.id, "models") == wp.OK, f"Refresh Project takes it ({st(nC.id, 'trainers')}, {st(nC.id, 'models')})")
ok(W.sync_editors() == [], "and that is not a change")
s_lib = stamp(nC.id, "library")
pt2 = model_file("Medium_trained.pt", 4000)
ml.save_version(w1.tp.models_dir, "assist", pt2, "m", "Tester", classes=["cup", "bottle"])
ch = W.sync_editors()
ok(nT.id in ch and nC.id in ch, "a second model in the Trainer ...")
ok(stamp(nC.id, "library") > s_lib and len(wb_models.models_of(W, nC.id, shared=False)) == 2, "... is a change of the Library, and the list has both")
ok(st(nC.id, "trainers") == wp.REFRESH, "and the wire says refresh again")
W.refresh_project()
ok(st(nC.id, "trainers") == wp.OK, "until it is refreshed")

# ============================================================================================================================ the window
print("--- the window")
w = W.open_cell(nC.id, "library")
ok(isinstance(w, wb_models_tab.ModelsWindow) and shell.tabs.indexOf(w) >= 0 and W.editor_of(nC.id) is w and w in shell.dependents(W), "double-click opens the list in its own tab")
ok(W.open_cell(nC.id, "models") is w, "a second double-click shows the same tab")
ok(w.title() == f"{nC.label} {nC.title}", f"the tab is named after the block ({w.title()})")
ok(w.table.rowCount() == 2 and w.table.columnCount() == 6, f"the list shows the two models of the Trainer ({w.table.rowCount()} rows)")
ok([w.table.horizontalHeaderItem(i).text() for i in range(6)] == ["Model", "Kind", "Size", "Stored", "Made", "From"], "with Model, Kind, Size, Stored, Made and From")
pick(w, next(n for n in names(w) if n.startswith("Small_")))
ok(w.fields["size"].text() == "Small" and w.fields["classes"].text() == "cup, bottle" and "mAP50-95 0.4" in w.fields["scores"].text() and w.fields["from"].text() == f"{nT.label} {nT.title}", f"the details on the left ({w.fields['size'].text()}, {w.fields['scores'].text()})")
ok(w.fields["stored"].text() == "Inside the project" and w.fields["bytes"].text() == "5 KB", f"stored inside, {w.fields['bytes'].text()}")
ok(set(w.buttons) == {"import_model", "import_folder", "export_model", "rename_model", "remove_model"}, "the ribbon: import model, import folder, export, rename, remove")
ok(w.foot_lbl.text().startswith("Project: ") and "Not used by" in w.foot_lbl.text(), f"the status bar says which project and who uses it ({w.foot_lbl.text()})")

# ---- importing a model file
print("--- importing")
n0 = len(nC.data.get("models", []))
imp = model_file("Nano_imported.pt", 2500)
json.dump({"format": "gimble-model-v1", "kind": "assist", "size": "n", "created": time.time() - 86400, "trainer": "Ian", "classes": ["cup"], "scores": {"map50": 0.5}, "based_on": None}, open(ml.info_path(imp), "w"))
s_lib = stamp(nC.id, "library")
ok(w.import_paths([imp]) == 1 and len(nC.data["models"]) == n0 + 1, "a model file is imported")
e = nC.data["models"][-1]
ok(e["stored"] == "inside" and "b64" in e["blob"] and e["bytes"] == 2500 and e["info"]["trainer"] == "Ian" and e["info"]["size"] == "n", f"inside the project, with its own information ({e['stored']}, {e['info'].get('trainer')})")
ok(stamp(nC.id, "library") == s_lib + 1, "that is a change of the Library")
ok("Nano_imported" in names(w) and w.table.rowCount() == 3, f"and it is in the list ({names(w)})")
pick(w, "Nano_imported")
ok(w.fields["trainer"].text() == "Ian" and w.fields["from"].text() == "Imported" and w.fields["size"].text() == "Nano", "with its details")
ok(w.import_paths([imp]) == 0 and len(nC.data["models"]) == n0 + 1, "the same file again is not taken twice")
ok("here already" in w.status.text(), f"and it is said ({w.status.text()})")
ok(w.import_paths([os.path.join(T, "nothing.txt")]) == 0 and "no model file" in w.status.text(), "a file that is no model is left out")

d1 = os.path.join(T, "models_folder")
os.makedirs(os.path.join(d1, "deeper"))
for nm, sub in (("A_model.pt", ""), ("B_model.pt", ""), ("C_model.pt", "deeper")):
    model_file(os.path.join("models_folder", sub, nm), 1500)
open(os.path.join(d1, "notes.txt"), "w").write("not a model")
ok(w.import_paths([d1]) == 3 and {"A_model", "B_model", "C_model"} <= set(names(w)), "a folder: every .pt in it and under it")
ok(len(w.model_files([d1])) == 3, "(the other files in it are not models)")

# a model too big for the file is linked
wb_models.MODEL_LIMIT = 6000
big = model_file("Big_model.pt", 9000)
nnotes = len(W.notes)
ok(w.import_paths([big]) == 1, "a model over the limit is imported too")
eb = next(m for m in nC.data["models"] if m["file"] == "Big_model.pt")
ok(eb["stored"] == "linked" and "blob" not in eb and os.path.isfile(wp.resolve_link(eb["link"], W.path)), f"but linked, not kept in the file ({eb['stored']})")
ok(len(W.notes) > nnotes and "linked" in W.notes[-1], "and the person is told")
pick(w, "Big_model")
ok(w.fields["stored"].text().startswith("Linked"), f"the list says so ({w.fields['stored'].text()})")
wb_models.MODEL_LIMIT = 500 * 1024 * 1024

# ---- the list: the filter and the sorting
print("--- GitHub models, the filter and the sorting")
shared_dir = tc.annotator_models_dir()
for _k in ("Assist", "Scratch"):
    os.makedirs(os.path.join(shared_dir, _k), exist_ok=True)
gh = model_file("Large_github.pt", 3500)
vgh = ml.save_version(shared_dir, "assist", gh, "l", "Ian", classes=["cup", "bottle", "person"], scores={"map50": 0.7})
ok(vgh is not None, "(a model was downloaded from GitHub into the shared Models folder)")
s_lib = stamp(nC.id, "library")
ch = W.sync_editors()
ok(nC.id in ch and nC2.id in ch and stamp(nC.id, "library") == s_lib + 1, "every Trained models block sees it: a change of the Library")
ok(any(r["origin"] == "shared" for r in wb_models.models_of(W, nC.id)) and not nC.data.get("models", [None])[0].get("path"), "listed, never copied into the project")
w.reload()
allm, emb, ghm = names(w, "all"), names(w, "embedded"), names(w, "github")
ok(len(allm) == 8 and len(emb) == 7 and len(ghm) == 1, f"all {len(allm)}, embedded {len(emb)}, GitHub {len(ghm)}")
ok(ghm[0].startswith("Large_") and all(not n.startswith("Large_") for n in emb), "the filter splits GitHub models from the embedded ones")
ok("GITHUB" in w.list_head.text().upper() and w.bar_lbl.text() == "7 embedded, 1 from GitHub", f"{w.bar_lbl.text()}")
pick(w, ghm[0])
ok(w.fields["stored"].text() == "GitHub / shared folder" and w.fields["classes"].text() == "cup, bottle, person" and w.fields["from"].text() == "GitHub / shared folder", "a GitHub model has its details too")
names(w, "all")
w.table.sortItems(0, Qt.SortOrder.AscendingOrder)
col = [w.table.item(i, 0).text() for i in range(w.table.rowCount())]
ok(col == sorted(col, key=str.lower), f"sorted by name ({col[:3]} ...)")
w.table.sortItems(4, Qt.SortOrder.AscendingOrder)
made = [w.table.item(i, 4).text() for i in range(w.table.rowCount())]
ok(made == sorted(made), f"sorted by the date it was made ({made[:2]} ... {made[-1]})")

# ---- what cannot be changed here
print("--- what is not this block's")
MSGS.clear()
n_models = len(nC.data["models"])
pick(w, ghm[0])
w.remove_model()
w.rename_model()
ok(len(MSGS) == 2 and "shared Models folder" in MSGS[0] and len(nC.data["models"]) == n_models and os.path.isfile(v) and os.path.isfile(vgh), "a GitHub model is not removed or renamed from a project")
MSGS.clear()
pick(w, next(n for n in names(w) if n.startswith("Small_")))
w.remove_model()
ok(len(MSGS) == 1 and nT.label in MSGS[0] and len(nT.data["models"]) == 2, f"nor is a model of a Trainer: that is changed in the Trainer ({MSGS})")
MSGS.clear()
w.table.clearSelection()
w.table.setCurrentCell(-1, -1)
w.rename_model()
ok(len(MSGS) == 1 and "Choose a model" in MSGS[0], "with nothing chosen the person is asked to choose")

# ---- rename, remove, export
print("--- rename, remove, export")
pick(w, "Nano_imported")
s_lib = stamp(nC.id, "library")
ASK["name"] = ("Gimble nano", True)
w.rename_model()
ok("Gimble nano" in names(w) and "Nano_imported" not in names(w) and stamp(nC.id, "library") == s_lib + 1, "Rename gives the model another name (a change of the Library)")
ok(any(m["file"] == "Nano_imported.pt" and m.get("name") == "Gimble nano" for m in nC.data["models"]), "its file keeps its name")
ASK["name"] = ("", False)
pick(w, "Gimble nano")
w.rename_model()
ok("Gimble nano" in names(w), "cancelling changes nothing")

dest = os.path.join(T, "out", "nano.pt")
SAVE["path"] = dest
pick(w, "Gimble nano")
w.export_model()
ok(os.path.getsize(dest) == 2500 and json.load(open(ml.info_path(dest)))["classes"] == ["cup"], "Export writes the .pt and its information beside it")
dest2 = os.path.join(T, "out", "small.pt")
SAVE["path"] = dest2
pick(w, next(n for n in names(w) if n.startswith("Small_")))
w.export_model()
ok(os.path.getsize(dest2) == 5000 and json.load(open(ml.info_path(dest2)))["scores"]["map50"] == 0.61, "so does a model of a Trainer")
dest3 = os.path.join(T, "out", "large.pt")
SAVE["path"] = dest3
pick(w, ghm[0])
w.export_model()
ok(os.path.getsize(dest3) == 3500, "and a GitHub model")
dest4 = os.path.join(T, "out", "big.pt")
SAVE["path"] = dest4
pick(w, "Big_model")
w.export_model()
ok(os.path.getsize(dest4) == 9000, "and a linked one")

s_lib = stamp(nC.id, "library")
n_models = len(nC.data["models"])
pick(w, "A_model")
w.remove_model()
ok(len(nC.data["models"]) == n_models - 1 and "A_model" not in names(w) and stamp(nC.id, "library") == s_lib + 1, "Remove takes a model out of the block")
ok(len(wb_models.models_of(W, nC.id)) == 7, "the others are still there")

# ---- the project file holds them
print("--- the project file")
f1 = os.path.join(T, "models.opara")
SAVE["path"] = f1
ok(W.save(True) and os.path.isfile(f1), "Save writes the project")
raw = json.load(open(f1))
dn = next(n for n in raw["nodes"] if n["title"] == "All models")["data"]
ok(len(dn["models"]) == n_models - 1 and sum(1 for m in dn["models"] if "blob" in m) == n_models - 2, f"the models imported are in the .opara ({len(dn['models'])}, one linked)")
ok("path" not in json.dumps(dn) and "Large_" not in json.dumps(dn), "the GitHub models are not")
ok(len(next(n for n in raw["nodes"] if n["title"] == "Cup trainer")["data"]["models"]) == 2, "and the Trainer's two models are in the Trainer's block, once")
names_before = sorted(r["name"] for r in wb_models.models_of(W, nC.id))
shell.close_tab(shell.tabs.indexOf(w))
ok(W.editor_of(nC.id) is None, "(the tab is closed)")
shell.tabs.setCurrentWidget(W)
W.load(f1)
P = W.project
nC = next(x for x in P.nodes.values() if x.kind == "trained_models" and x.title == "All models")
nC2 = next(x for x in P.nodes.values() if x.kind == "trained_models" and x.title == "Second list")
nT = next(x for x in P.nodes.values() if x.kind == "trainer" and x.title == "Cup trainer")
ok(sorted(r["name"] for r in wb_models.models_of(W, nC.id)) == names_before, "after opening the file the list is the same")
ok(st(nC.id, "library") == wp.OK and st(nC.id, "trainers") == wp.OK, f"and the cells are as they were ({st(nC.id, 'library')}, {st(nC.id, 'trainers')})")
ok(W.sync_editors() == [], "looking again is not a change")
ents = [m for m in nC.data["models"] if m["file"] == "Nano_imported.pt"]
p = wb_models.entry_path(W, nC.id, ents[0])
ok(p and os.path.getsize(p) == 2500, "a model of the file can be written out again")
ok(wb_models.entry_path(W, nC.id, next(m for m in nC.data["models"] if m["file"] == "Big_model.pt")) is not None, "and the linked one is found next to the project")

# ---- a list wired into another, and the downstream cells
print("--- wired on")
P.link(nC.id, "models", nC2.id, "trainers")
W.refresh_project()
r2 = wb_models.models_of(W, nC2.id)
ok(len(r2) == len(wb_models.models_of(W, nC.id)) and any(r["origin"] == "shared" for r in r2), f"the second list has all of them ({len(r2)}), the GitHub ones too")
ok(st(nC2.id, "trainers") == wp.OK and st(nC2.id, "models") == wp.OK, "and says ok")
s2 = stamp(nC2.id, "library")
ml.save_version(shared_dir, "assist", model_file("Medium_github.pt", 3300), "m", "Ian", classes=["cup"])
ch = W.sync_editors()
ok(nC.id in ch and nC2.id in ch and stamp(nC2.id, "library") == s2 + 1, "a model downloaded later is a change of both lists")
ok(st(nC2.id, "trainers") == wp.REFRESH, f"and the second list says refresh ({st(nC2.id, 'trainers')})")
rows2 = wb_models.models_of(W, nC2.id)
ok(len({r["id"] for r in rows2}) == len(rows2), "no model is listed twice")
ok(W.update_project()[1] == [] and not os.listdir(os.path.join(wb_nodes.workspace_of(W, nT), "Trainer.training", "runs")), "Update Project never trains")

# ---- saved on its own, deleted
print("--- export, delete")
out = os.path.join(T, "export")
ex = W.export_node(nC.id, out)
pts = [f for f in os.listdir(ex)] if ex else []
pts = [f for f in pts if f.endswith(".pt")]
ok(ex and os.path.isdir(ex) and len(pts) == 6 and all(os.path.isfile(os.path.join(ex, f[:-3] + ".json")) for f in pts), f"saved on its own, the block is a folder of model files, each with its information ({len(pts)} models)")
ok(not any(f.startswith("Large_") for f in os.listdir(ex)), "without the GitHub models")
w = W.open_cell(nC.id, "library")
ok(w is not None, "(its window is open)")
W.scene.clearSelection()
sel = [it for it in W.scene.items() if hasattr(it, "nid") and it.nid == nC.id]
sel[0].setSelected(True)
tabs = shell.tabs.count()
ok(W.delete_selected() == 1 and nC.id not in W.project.nodes and shell.tabs.count() == tabs - 1 and nC.id not in W.node_state, "Delete removes the block and closes its tab")
ok(os.path.isfile(vgh) and os.path.isfile(v), "the models of the Trainer and the shared folder are untouched")

print()
print("all passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
