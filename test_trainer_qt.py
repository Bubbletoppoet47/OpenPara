import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
"""The Trainer window: import zips, set roles, distortions, train a (fake) model in the background while the window stays usable,
stop it, close while it runs, save the project folder, reopen it."""
import os, sys, tempfile, time, json, shutil, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
TMP = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(TMP, "user")
CORE = os.path.join(HERE, "core") if os.path.isdir(os.path.join(HERE, "core")) else HERE
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
for p in (CORE, os.path.join(ADD, "annotator", "app"), os.path.join(ADD, "trainer")):
    sys.path.insert(0, p)
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
app = QApplication([])
import numpy as np, cv2
import annotator_core as ac, dataset_zip as dz, share_zip as sz, model_library as ml, ext
sz.CONFIG_PATH = os.path.join(TMP, "cfg.json")
ME = sz.set_identity({}, "Tester")
sz.save_config({"name": "Tester", "id": ME["id"]})
import trainer_core as tc, trainer_tab as tt

MSG = []
ASKED_DL = []
tt.TrainerTab._ask_download = lambda self, text, choices: ASKED_DL.append((text, choices)) or None   # the download question: not now
QMessageBox.information = staticmethod(lambda p, t, x, *a, **k: MSG.append((t, x)))
QMessageBox.warning = staticmethod(lambda p, t, x, *a, **k: MSG.append((t, x)))
QMessageBox.critical = staticmethod(lambda p, t, x, *a, **k: MSG.append(("ERR " + t, x)))
ASK = {"answer": QMessageBox.StandardButton.Yes}
QMessageBox.question = staticmethod(lambda *a, **k: ASK["answer"])

def pump(n=20, dt=0.05):
    for _ in range(n):
        app.processEvents(); time.sleep(dt)

def wait(cond, secs=60):
    t0 = time.time()
    while not cond():
        app.processEvents(); time.sleep(0.05)
        assert time.time() - t0 < secs, "timed out"

def video(name, shift=0):
    p = os.path.join(TMP, name)
    vw = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for i in range(12):
        f = np.full((240, 320, 3), 30 + i * 5 + shift, np.uint8); cv2.rectangle(f, (50 + i * 3, 60), (150 + i * 3, 160), (0, 200, 0), -1); vw.write(f)
    vw.release(); return p

def make_zip(name, vid, session, classes):
    pr = ac.Project(os.path.join(TMP, name)); [pr.add_class(c) for c in classes]; pr.editor_id = ME["id"]
    pr.import_video(vid, stride=3, session_name=session)
    for k, i in enumerate(sorted(pr.manifest["images"])[:4]):
        pr.set_boxes(i, [(k % len(classes), 0.5, 0.5, 0.3, 0.3)])
    z = os.path.join(TMP, name + ".zip"); dz.export_zip(pr, z, ME); return z

za = make_zip("A", video("a.mp4"), "setA", ["cup", "bottle"])
zb = make_zip("B", video("b.mp4", 40), "setB", ["bottle", "can"])

fake = os.path.join(TMP, "fake_train.py")
open(fake, "w").write(f'''import os, sys, time
sys.path.insert(0, {os.path.join(ADD, "trainer")!r})
import job_common as jc
job = jc.load_job()
print("fake training", job["classes"], job["counts"], flush=True)
for e in range(int(os.environ.get("FAKE_EPOCHS", "3"))):
    print("epoch", e, flush=True); time.sleep(float(os.environ.get("FAKE_SLEEP", "0.2")))
best = os.path.join(job["run_dir"], "best.pt"); open(best, "wb").write(b"w")
sys.exit(jc.finish(job, best, {{"epoch": 1, "total_epochs": 3, "map50": 0.6, "map50_95": 0.4}}))
''')
ext.add_model_trainer("fake", label="Fake model", script=fake, sizes=("n", "s"), default_size="n")

class Host:
    def __init__(self): self.cards = []
    @contextlib.contextmanager
    def busy(self, text):
        self.cards.append(text); yield
host = Host()

# ---- the add-on manifest is what the shell reads
man = json.load(open(os.path.join(ADD, "trainer", "addon.json")))
spec = man["tabs"][0]
assert spec["kind"] == "trainer" and spec["project_folder"] == {"marker": "training.json", "format": "openpara-training"}

# ---- a new window: empty, says what to do
w = tt.make_tab(None); w.host = host; w.resize(1200, 800); w.show(); pump(4)
assert isinstance(w, tt.TrainerTab) and w.title() == "Trainer" and not w.is_dirty() and w.temp_root
assert "No pictures yet" in w.data_info.text()
# the look of the family: the bar (what it is, which project, its commands on the right), three numbered foldable steps, the main action in teal
assert "not saved yet" in w.bar_lbl.text() and [b.text() for b in w.bar_buttons] == ["Import dataset zip...", "Save project as..."]
assert [(s.number, s.title) for s in w.sections] == [(1, "Data"), (2, "Distortions"), (3, "Model")]
assert not w.findChildren(tt.QGroupBox), "no grey group boxes"
assert "font-weight:600" in w.btn_train.styleSheet() and w.btn_train.text() == "Start training"
assert w.panel_scroll.viewport().width() >= w.panel.minimumSizeHint().width(), "the left panel shows its contents whole"
assert w.type_box.findData("fake") >= 0 and w.type_box.findData("yolo") >= 0 and w.type_box.findData("yolo_scratch") < 0
# only random-weight types are offered: nothing in the type box or its explanation offers a pretrained start
assert [w.type_box.itemText(i) for i in range(2)] == ["Classes + boxes", "Classes + boxes + distance"]
assert not any("pretrained" in w.type_box.itemText(i).lower() for i in range(w.type_box.count()))
assert "random weights" in tt.HINTS["type"] and "nothing pretrained" in tt.HINTS["type"]
# every type's name is shown whole in the type box, and the table's last column is not cut off
fm = w.type_box.fontMetrics()
assert max(fm.horizontalAdvance(w.type_box.itemText(i)) for i in range(4)) + 40 <= w.type_box.width(), w.type_box.width()
assert w.sets_table.columnWidth(3) >= 110 and not w.sets_table.horizontalScrollBar().isVisible()
import re
labels = {b.text() for b in w.findChildren(tt.QPushButton)}
assert "Export master zip..." not in labels and "My name..." not in labels and "Import dataset zip..." in labels
assert not hasattr(w, "start_box") and w.cont_on.text() == "Continue from existing model" and not w.cont_row.isEnabled()
hints = " ".join(l.text() for l in w.findChildren(tt.QLabel))
for word in ("lighter or darker", "grain", "JPEG quality", "distorted versions", "resized to this many pixels", "One epoch"):
    assert word in hints, word
assert w.dist_count.toolTip() and w.more["imgsz"].toolTip() and w.dist_checks["blur"].toolTip()
# the Training Python box lists what it found; this computer has no torch / ultralytics -> it says so and refuses to start
wait(lambda: w.env is not None)
assert w.py_box.count() >= 1 and sys.executable in [w.py_box.itemData(i) for i in range(w.py_box.count())]
assert w.env["problems"] and "torch" in w.env_label.text() and "Training is not possible" in w.env_label.text()
MSG.clear(); w.start()
assert MSG and "torch" in MSG[-1][1], MSG
# pretend the machine is fine from here on (the training Python is this one; the fake script needs neither torch nor a GPU)
w.env = {"python": sys.executable, "torch": "x", "ultralytics": "x", "cuda": False, "gpu": None, "cuda_build": None, "ok": True, "problems": [], "warnings": ["No GPU"]}
w._update_env_view()

# ---- import two zips (a name is already known, so nothing is asked)
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([za, zb], ""))
w.import_zip()
wait(lambda: not w._bg and w.status.text() == "" and w.sets_table.rowCount() == 2)
assert [w.sets_table.item(r, 0).text() for r in range(2)] == ["setA", "setB"]
assert any("Import finished" in t for t, _x in MSG)
assert w.is_dirty() and [w.class_list.item(i).text() for i in range(w.class_list.count())] == ["cup", "bottle", "can"]

assert "No validation pictures" in w.data_info.text(), w.data_info.text()
# ---- validation set chosen in the table
w.sets_table.cellWidget(1, 3).setCurrentIndex(1)
assert w.tp.data.session_role("setB") == "val" and "4 training and 4 validation" in w.data_info.text(), w.data_info.text()
# class unchecked -> the counts and the saved setting follow
w.class_list.item(2).setCheckState(tt.Qt.CheckState.Unchecked)
assert w.tp.settings["model"]["classes"] == ["cup", "bottle"]
w.class_list.item(2).setCheckState(tt.Qt.CheckState.Checked)
# ---- distortions: only types chosen, saved to the project
w.dist_on.setChecked(True); w.dist_checks["noise"].setChecked(False); w.dist_count.setValue(2)
d = w.tp.settings["distortions"]
assert d["enabled"] and d["count"] == 2 and d["types"]["noise"] is False and w.dist_box.isEnabled()
# ---- model settings
w.type_box.setCurrentIndex(w.type_box.findData("fake"))
assert [w.size_box.itemData(i) for i in range(w.size_box.count())] == ["n", "s"]
w.epochs.setValue(7); w.name_edit.setText("Beach_v1")
m = w.tp.settings["model"]; assert m["type"] == "fake" and m["size"] == "n" and m["epochs"] == 7 and m["name"] == "Beach_v1" and m["continue_from"] is None

# ---- train: the window stays usable, the log fills, the model is saved and the annotator's list gets it
os.environ["FAKE_SLEEP"] = "0.3"; os.environ["FAKE_EPOCHS"] = "3"
# before the start, the Distortions step says how much the start has to make
assert "The next training first makes 8 copies (4 training pictures x 2)" in w.dist_note.text(), w.dist_note.text()
w.start()
# the run is prepared in the background (distorted copies, the run's copy of the data): the window is not blocked, it shows a bar,
# Stop reads Cancel and the steps of the left panel wait
assert w.preparing() and not w.running() and not w.btn_train.isEnabled() and w.btn_stop.isEnabled() and w.btn_stop.text() == "Cancel"
assert not w.panel.isEnabled() and not w.prep_bar.isHidden() and not all(b.isEnabled() for b in w.bar_buttons)
wait(lambda: w.running())
assert not w.preparing() and w.btn_stop.text() == "Stop" and w.btn_stop.isEnabled() and not w.btn_train.isEnabled()
assert w.panel.isEnabled() and w.prep_bar.isHidden() and all(b.isEnabled() for b in w.bar_buttons)
assert sum(1 for v in w.tp.data.manifest["distortions"].values() if v) == 4        # training pictures only
lg = w.log.toPlainText()
assert "Distorted copies ready for 4 training pictures" in lg and "The run's copy of the data is ready:" in lg and "Prepared in" in lg, lg
assert "All 8 copies are made (4 training pictures x 2)" in w.dist_note.text(), w.dist_note.text()
wait(lambda: w.job is None)
pump(6)
assert "fake training ['cup', 'bottle', 'can']" in w.log.toPlainText() and "epoch 2" in w.log.toPlainText()
assert "Finished" in w.run_label.text() and w.btn_train.isEnabled() and not w.btn_stop.isEnabled()
assert w.models_list.count() == 1 and "mAP50 0.6" in w.models_list.item(0).text() and "Nano   classes + boxes   20" in w.models_list.item(0).text()
vs = ml.list_versions(tc.annotator_models_dir(), "assist")
assert len(vs) == 1 and vs[0]["classes"] == ["cup", "bottle", "can"] and vs[0]["trainer"] == "Beach_v1" and "Beach_v1" in vs[0]["file"], vs
# continue from existing model: the box lists it, ticking it greys out type and size, and the run carries its path
w._fill_continue(); assert w.cont_box.count() >= 1
w.cont_on.setChecked(True); assert w.cont_row.isEnabled() and not w.size_box.isEnabled() and not w.type_box.isEnabled()
assert os.path.basename(w.tp.settings["model"]["continue_from"]) == vs[0]["file"]
w.cont_on.setChecked(False); assert w.size_box.isEnabled() and w.tp.settings["model"]["continue_from"] is None
# ---- the two kinds of model.  A distance type shows how many boxes carry a distance, and says so when none does (this data has none)
w.type_box.setCurrentIndex(w.type_box.findData("yolo_distance"))
assert w.size_box.currentData() == "n" and w.tp.settings["model"]["type"] == "yolo_distance"
assert "Boxes with a distance - training: 0, validation: 0" in w.data_info.text() and "cannot be trained from this data" in w.data_info.text(), w.data_info.text()
MSG.clear(); w.start(); wait(lambda: not w.preparing())
assert not w.running() and MSG and "has a distance" in MSG[-1][1] and "Classes + boxes" in MSG[-1][1], MSG
assert w.run_label.text() == "Training did not start." and w.btn_train.isEnabled() and w.panel.isEnabled() and w.btn_stop.text() == "Stop"
w.type_box.setCurrentIndex(w.type_box.findData("yolo"))
assert "Boxes with a distance" not in w.data_info.text() and "cannot be trained" not in w.data_info.text()
# continuing a model.  One that has a distance model keeps it: picking it switches the type to Classes + boxes + distance and locks it.
# A classes + boxes model can go on as it is OR get a distance model on top, so the type stays free.
import pickle, zipfile
def fake_pt(path, kind):
    inside = {"two": {"opara_two_model": {"format": "opara-two-model-v1"}, "model": "yolo"}, "old": {"format": "gimble-det-dist-v1"},
              "plain": {"model": "yolo"}}[kind]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("archive/data.pkl", pickle.dumps(inside))
    return path
for d in ("scratch", "assist"):
    os.makedirs(ml.folder_path(w.tp.models_dir, d), exist_ok=True)
names = ["cup", "bottle", "can"]
vtwo = ml.save_version(w.tp.models_dir, "scratch", fake_pt(os.path.join(TMP, "two.pt"), "two"), "n", "Two", classes=names)
vold = ml.save_version(w.tp.models_dir, "scratch", fake_pt(os.path.join(TMP, "old.pt"), "old"), "n", "Old", classes=names)
vplain = ml.save_version(w.tp.models_dir, "assist", fake_pt(os.path.join(TMP, "plain.pt"), "plain"), "s", "Plain", classes=names)
assert [tc.checkpoint_kind(v) for v in (vtwo, vold, vplain)] == ["two", "old", "plain"]
w._fill_continue(); w.refresh_models()
labels = {w.cont_box.itemData(i): w.cont_box.itemText(i) for i in range(w.cont_box.count())}
assert labels[vtwo].endswith("(this project, with distance)") and labels[vold].endswith("(this project, with distance, earlier kind)"), labels
assert labels[vplain].endswith("(this project)"), labels
listed = [w.models_list.item(i).text() for i in range(w.models_list.count())]
assert any("classes + boxes + distance (earlier kind)" in t for t in listed) and any("Small   classes + boxes   20" in t for t in listed), listed
w.type_box.setCurrentIndex(w.type_box.findData("yolo"))
assert w.dist_only.isHidden() and w.dist_only_hint.isHidden()                     # nothing to keep or not: no model is continued
w.cont_box.setCurrentIndex(w.cont_box.findData(vtwo)); w.cont_on.setChecked(True)
assert w.type_box.currentData() == "yolo_distance" and w.tp.settings["model"]["type"] == "yolo_distance" and not w.type_box.isEnabled()
assert "Boxes with a distance" in w.data_info.text()
# the detector can be kept as it is (only the distance model is trained): offered with a distance type, on by default, and saved
assert not w.dist_only.isHidden() and w.dist_only.isChecked() and w.tp.settings["model"]["distance_only"] is True
w.dist_only.setChecked(False); assert w.tp.settings["model"]["distance_only"] is False
w.dist_only.setChecked(True)
# a classes + boxes model: the type is free.  As Classes + boxes + distance it gets a distance model on top; as Classes + boxes it goes on as it is
w.cont_box.setCurrentIndex(w.cont_box.findData(vplain))
assert w.type_box.currentData() == "yolo_distance" and w.type_box.isEnabled() and not w.dist_only.isHidden()
w.type_box.setCurrentIndex(w.type_box.findData("yolo"))
assert w.tp.settings["model"]["type"] == "yolo" and w.type_box.isEnabled() and w.dist_only.isHidden() and "Boxes with a distance" not in w.data_info.text()
assert os.path.normpath(w.tp.settings["model"]["continue_from"]) == os.path.normpath(vplain)
# the earlier one-network kind cannot be trained further: it says so when started, and nothing is left of the run
w.cont_box.setCurrentIndex(w.cont_box.findData(vold))
assert w.type_box.currentData() == "yolo_distance" and not w.type_box.isEnabled() and w.dist_only.isHidden()
runs_before = sorted(os.listdir(w.tp.runs_dir))
MSG.clear(); w.start(); wait(lambda: not w.preparing())
assert not w.running() and MSG and "earlier kind" in MSG[-1][1] and "cannot be trained further" in MSG[-1][1], MSG
assert sorted(os.listdir(w.tp.runs_dir)) == runs_before
w.cont_on.setChecked(False)
assert w.type_box.isEnabled() and w.dist_only.isHidden()
for v in (vtwo, vold, vplain):
    os.remove(v); os.remove(ml.info_path(v))
w._fill_continue(); w.refresh_models()
w.type_box.setCurrentIndex(w.type_box.findData("fake")); assert w.tp.settings["model"]["type"] == "fake" and w.size_box.currentData() == "n"
# ---- a long preparation: the window keeps working, shows how far it is and how long is left, and Cancel ends it
real_start = w.tp.start_run
seen = {"stops": 0}
def slow_start(me_name, progress_cb=None, python=None, stop=None, **kw):
    progress_cb("distortions", 0, 0)
    for k in range(40, 2000):                                 # 40 pictures already had their copies
        if stop():
            seen["stops"] += 1
            raise tc.Cancelled()
        progress_cb("distortions", k, 2000); time.sleep(0.02)
    raise SystemExit("was not cancelled")
w.tp.start_run = slow_start
w.start(); t0 = time.time()
assert w.preparing() and w.run_label.text() == "Preparing the training data ..."
from PyQt6.QtCore import QTimer
ticks = []
tm = QTimer(); tm.timeout.connect(lambda: ticks.append(time.time())); tm.start(50)       # the window's own events keep running meanwhile
wait(lambda: "left" in w.run_label.text(), 30)
tm.stop()
assert len(ticks) >= 20 and max(b - a for a, b in zip(ticks, ticks[1:])) < 1.0, (len(ticks), ticks[:3])
txt = w.run_label.text()
assert txt.startswith("Making distorted copies: ") and "of 2,000 training pictures (2 copies each) - about " in txt, txt
assert 0 < w.prep_bar.value() < 2000 and w.prep_bar.maximum() == 2000 and w.prep_bar.format().endswith("%")
assert w.can_close() is False and MSG[-1][1].startswith("The training data is still being prepared") and w.save() is False
n_runs = len(os.listdir(w.tp.runs_dir))
w.btn_stop.click()
assert "Cancelling" in w.run_label.text() and not w.btn_stop.isEnabled()
wait(lambda: not w.preparing(), 20)
assert seen["stops"] == 1 and not w.running() and w.job is None and "Cancelled before training started" in w.run_label.text()
assert w.btn_train.isEnabled() and w.panel.isEnabled() and w.prep_bar.isHidden() and w.btn_stop.text() == "Stop" and not w.btn_stop.isEnabled()
assert len(os.listdir(w.tp.runs_dir)) == n_runs and w.log.toPlainText().rstrip().endswith("Cancelled.")
# something going wrong while preparing is told, and the window is usable again
def broken_start(me_name, progress_cb=None, python=None, stop=None, **kw):
    progress_cb("copy", 3, 10); raise OSError("disk full")
w.tp.start_run = broken_start
MSG.clear(); w.start(); wait(lambda: not w.preparing())
assert MSG and "disk full" in MSG[-1][1] and w.btn_train.isEnabled() and w.panel.isEnabled() and "did not start" in w.run_label.text()
w.tp.start_run = real_start
# ---- stop
os.environ["FAKE_SLEEP"] = "3"; os.environ["FAKE_EPOCHS"] = "40"
w.start(); wait(lambda: "epoch 0" in w.log.toPlainText())
w.btn_stop.click(); wait(lambda: not w.running()); wait(lambda: w.job is None)
assert "Stopped" in w.run_label.text() and len(ml.list_versions(tc.annotator_models_dir(), "assist")) == 1
# ---- closing while it runs asks first
w.start(); wait(lambda: "epoch 0" in w.log.toPlainText())
ASK["answer"] = QMessageBox.StandardButton.No
assert w.can_close() is False and w.running()
assert w.save() is False                                                # no saving mid-run
ASK["answer"] = QMessageBox.StandardButton.Yes
assert w.can_close() is True and not w.running()
# ---- save: the temp project becomes a .training folder with everything in it
dest = os.path.join(TMP, "Mine.training")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (dest, ""))
temp = w.temp_root
assert w.save() is True and w.temp_root is None and w.path == dest and w.title() == "Mine" and not os.path.exists(temp) and not w.is_dirty()
assert os.path.isfile(os.path.join(dest, "training.json")) and w.sets_table.rowCount() == 2
# ---- export the master zip from the trainer, import it into a fresh annotator project
mz = os.path.join(TMP, "master.zip")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (mz, ""))
assert not hasattr(w, "export_zip")
w.tp.export_zip(mz, ME)           # the window has no export; the annotator exports. The core still can (used by this test)
pc = ac.Project(os.path.join(TMP, "C")); plan = dz.plan_zip(pc, mz, tempfile.mkdtemp(), ME); dz.apply_zip(pc, plan, None, ME)
assert len([i for i in pc.list_images() if pc.is_annotated(i)]) == 8
w.shutdown()
# ---- reopening the folder: settings, roles, models are all still there
w2 = tt.make_tab(dest); w2.host = host; pump(4)
assert w2.tp.data.session_role("setB") == "val" and w2.dist_on.isChecked() and w2.epochs.value() == 7 and w2.type_box.currentData() == "fake" and w2.name_edit.text() == "Beach_v1"
assert w2.models_list.count() == 1
w2.shutdown()
print("trainer qt ok")
