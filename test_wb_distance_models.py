"""Distance-only models in the Workbench: a Trainer block keeps them inside the project file like any other model (one .opdm file each, up to 500 MB), a Trained models block lists
them as "Distance only" beside the YOLO models, they can be imported, dropped and exported as .opdm files (no question about code: they are numbers), a Trainer that is built again
from the project file gets them back in its models/Distance folder, and Model testing leaves them out until it has a detector slot for them.
python test_wb_distance_models.py"""
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
ASKED = []
QMessageBox.question = staticmethod(lambda *a, **k: ASKED.append(a[2] if len(a) > 2 else "") or QMessageBox.StandardButton.Yes)
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


import dist_models as dm
import dist_data as dd
import eval_harness as eh

S, F, CAM, HORIZON = 640, 420.0, 1.2, 300.0


def scene(n, seed, recordings=6):
    rng = np.random.default_rng(seed)
    d = np.exp(rng.uniform(np.log(2.5), np.log(20.0), n))
    h = F * 1.7 / d
    w = 0.4 * h
    cx = rng.uniform(100, 540, n)
    y2 = HORIZON + F * CAM / d
    xyxy = np.stack([cx - w / 2, y2 - h, cx + w / 2, y2], 1)
    label = d * np.exp(rng.normal(0, 0.05, n))
    rec = rng.integers(0, recordings, n)
    return dd.Boxes(dd.geometry(xyxy, S), np.zeros(n, int), label, xyxy, [f"gim_rec{r:02d}_{k:06d}" for k, r in enumerate(rec)], 1, ["person"], S)


TRAIN, VAL = scene(300, 1), scene(120, 2)


def distance_model_file(folder, family, name):
    os.makedirs(folder, exist_ok=True)
    m = dm.make(family, S, 1, ["person"], 0)
    if family == "mlp":
        m.fit(TRAIN, VAL, rung=6, epochs=3, hidden=(8, 4))
    else:
        m.fit(TRAIN)
    err = eh.median_rel_err(m.predict_boxes(VAL), VAL.dist)
    return m.save(os.path.join(folder, name), scores={"dist_median_err": round(err, 4), "dist_within_20": 0.9, "dist_mae_m": 0.4},
                  extra={"trained": {"rows": len(TRAIN), "trainer": "Tester", "classes": ["person"], "seconds": 0.1}})


def names(w, mode="all"):
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


# ============================================================================================================================ a Trainer makes distance models
print("--- a Trainer with distance-only models")
nT = W.add_block("trainer", 60, 60, title="Distance trainer")
nC = W.add_block("trained_models", 420, 60, title="All models")
nM = W.add_block("model_test", 780, 60, title="Tester")
P.link(nT.id, "models", nC.id, "trainers")
P.link(nT.id, "models", nM.id, "models")
w1 = W.open_cell(nT.id, "training")
dist_dir = w1.tp.distance_dir()
f_pin = distance_model_file(dist_dir, "pinhole", "pinhole_2026-11-26_0500.opdm")
f_net = distance_model_file(dist_dir, "mlp", "mlp_rung6_2026-11-26_0500.opdm")
ok(len(w1.tp.list_models()) == 2 and all(v["kind"] == "distance" for v in w1.tp.list_models()), "(the Trainer's project lists the two files it made)")
ch = W.sync_editors()
ok(nT.id in ch and len(nT.data["models"]) == 2, f"the block takes them into the project: {[m['file'] for m in nT.data['models']]}")
e = {m["file"]: m for m in nT.data["models"]}["pinhole_2026-11-26_0500.opdm"]
ok(e["key"] == "distance" and e["stored"] == "inside" and "text" in e["blob"] and e["bytes"] == os.path.getsize(f_pin), f"inside the file, key distance ({e['key']}, {e['stored']}, {e['bytes']} bytes)")
ok(e["info"]["kind"] == "distance" and e["info"]["size"] == "formula k / height" and e["info"]["classes"] == ["person"] and e["info"]["trainer"] == "Tester" and e["info"]["scores"]["dist_median_err"] < 0.1, f"with its information read from the file ({e['info']['size']}, {e['info']['scores']})")
e2 = {m["file"]: m for m in nT.data["models"]}["mlp_rung6_2026-11-26_0500.opdm"]
ok(e2["info"]["size"] == "network, rung 6" and e2["info"]["family"] == "mlp" and e2["info"]["pickled"] is False, f"a network says which rung ({e2['info']['size']})")
ok("pinhole" in e["blob"]["text"] and json.loads(e["blob"]["text"])["family"] == "pinhole", "a distance model is text (numbers), so it can be read in the .opara file itself")
ok(st(nT.id, "training") == wp.OK, f"the Training cell is ready ({st(nT.id, 'training')})")
ok(W.sync_editors() == [], "looking again is no change")

# ============================================================================================================================ Trained models lists them
print("--- the Trained models window")
W.refresh_project()
rows = wb_models.models_of(W, nC.id, shared=False)
ok(len(rows) == 2 and {r["kind"] for r in rows} == {"Distance only"} and {r["size_text"] for r in rows} == {"formula k / height", "network, rung 6"}, f"listed as Distance only ({[(r['name'], r['kind'], r['size_text']) for r in rows]})")
w = W.open_cell(nC.id, "library")
ok(w.table.rowCount() == 2 and {w.table.item(i, 1).text() for i in range(2)} == {"Distance only"}, "the window shows the kind")
pick(w, "pinhole_2026-11-26_0500")
ok(w.fields["kind"].text() == "Distance only" and w.fields["size"].text() == "formula k / height" and "distance error" in w.fields["scores"].text() and w.fields["classes"].text() == "person", f"the details ({w.fields['scores'].text()})")
ok(len(names(w, "embedded")) == 2 and len(names(w, "github")) == 0 and w.bar_lbl.text() == "2 embedded, 0 from GitHub", "they are embedded, not GitHub")
ok(wb_models.shared_entries() == [] or all(m["key"] != "distance" for m in wb_models.shared_entries()), "the shared Models folder has none, and listing it does not trip over the new kind")

# ---- export and import
names(w, "all")
pick(w, "pinhole_2026-11-26_0500")
dest = os.path.join(T, "out", "my_formula")
SAVE["path"] = dest
w.export_model()
ok(os.path.isfile(dest + ".opdm") and not os.path.exists(dest + ".json") and not os.path.exists(dest + ".pt") and "Exported my_formula.opdm." == w.status.text(), f"Export writes one .opdm file ({w.status.text()})")
back = dm.load(dest + ".opdm")
ok(back.family == "pinhole" and np.allclose(back.predict_boxes(VAL), dm.load(f_pin).predict_boxes(VAL)), "that answers what the original answers")
ASKED.clear()
nC_models = len(nC.data.get("models", []))
ok(w.import_paths([dest + ".opdm"]) == 1 and len(nC.data["models"]) == nC_models + 1, "importing the file into the list takes it")
ent = nC.data["models"][-1]
ok(ent["key"] == "distance" and ent["stored"] == "inside" and ent["info"]["size"] == "formula k / height" and not ASKED, f"as a distance model, with no question about code ({ASKED})")
ok(w.import_paths([dest + ".opdm"]) == 0 and "here already" in w.status.text(), "the same file again is not taken twice")
junk = os.path.join(T, "junk.opdm")
open(junk, "w").write('{"hello": 1}')
ok(w.import_paths([junk]) == 0 and "not an OpenPara distance model" in w.status.text(), f"a .opdm that is not a distance model is refused ({w.status.text()})")
pt = os.path.join(T, "Small.pt")
open(pt, "wb").write(os.urandom(500))
ASKED.clear()
ok(w.import_paths([pt]) == 1 and len(ASKED) == 1 and "code" in ASKED[0], "a .pt file still asks about code")
ASKED.clear()
ok(w.import_paths([dest + ".opdm", os.path.join(T, "nothing.txt")]) == 0 and not ASKED, "and a .opdm alone does not")
class Url:
    def __init__(self, p): self.p = p
    def toLocalFile(self): return self.p
class Mime:
    def __init__(self, ps): self.ps = ps
    def urls(self): return [Url(p) for p in self.ps]
class Ev:
    def __init__(self, ps): self.m = Mime(ps); self.ok = False
    def mimeData(self): return self.m
    def acceptProposedAction(self): self.ok = True
ev = Ev([f_net]); w.dragEnterEvent(ev)
ok(ev.ok, "a dragged .opdm is accepted by the window")

# ============================================================================================================================ the project file
print("--- the project file")
f1 = os.path.join(T, "dist.opara")
SAVE["path"] = f1
ok(W.save(True) and os.path.isfile(f1), "Save writes the project")
raw = json.load(open(f1))
tr = next(n for n in raw["nodes"] if n["title"] == "Distance trainer")["data"]["models"]
ok(len(tr) == 2 and all(m["key"] == "distance" and "blob" in m for m in tr), "the Trainer's two models are inside the .opara")
size_file = os.path.getsize(f1)
ok(size_file < 5 * 1024 * 1024, f"which is small ({size_file // 1024} KB)")
shell.close_tab(shell.tabs.indexOf(w))
shell.close_tab(shell.tabs.indexOf(w1))
shell.tabs.setCurrentWidget(W)
W.load(f1)
P = W.project
nT = next(x for x in P.nodes.values() if x.kind == "trainer" and x.title == "Distance trainer")
nC = next(x for x in P.nodes.values() if x.kind == "trained_models")
nM = next(x for x in P.nodes.values() if x.kind == "model_test")
ok(len(wb_models.models_of(W, nC.id, shared=False)) == 4, f"after opening the file the models are there: the Trainer's two, the .opdm and the .pt imported ({len(wb_models.models_of(W, nC.id, shared=False))})")
# the Trainer is built again from the file: its project gets them back
w1 = W.open_cell(nT.id, "training")
v2 = w1.tp.list_models()
ok(len(v2) == 2 and all(v["kind"] == "distance" and v["file"].endswith(".opdm") for v in v2) and all(os.path.dirname(v["path"]) == w1.tp.distance_dir() for v in v2), f"a Trainer built from the file has them in its models/Distance ({[v['file'] for v in v2]})")
a = next(v for v in v2 if v["family"] == "pinhole")
ok(open(a["path"], "rb").read() == open(f_pin, "rb").read(), "byte for byte")
ok(dm.load(a["path"]).family == "pinhole", "and it loads")
W.sync_editors()
ok(len(nT.data["models"]) == 2, "reading the Trainer back changes nothing")
w1.tp.remove_model(a["path"])
w1.refresh_models()
ok(nT.id in W.sync_editors(), "removing one in the Trainer window is a change of the block")
ok(len(nT.data["models"]) == 1 and nT.data["models"][0]["file"].startswith("mlp_"), f"({[m['file'] for m in nT.data['models']]})")

# ============================================================================================================================ Model testing
print("--- Model testing")
wt = W.open_cell(nM.id, "models")
ok(wt is not None and "distance-only" in wt.bar_lbl.text() and "not testable yet" in wt.bar_lbl.text(), f"the Model testing window says they wait ({wt.bar_lbl.text()})")
ok(wt.ai_choice.count() == 0 and wt.analyse.panel.model_combo.count() == 0, "and does not offer them to the Analyse tab (they find no boxes)")
ok(len(wb_models.models_of(W, nM.id)) == 1, "(the block still has them wired in)")

print()
print("all passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
