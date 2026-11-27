import faulthandler; faulthandler.dump_traceback_later(290, exit=True)
"""The Trainer window with the two distance-only model types: they are offered, size names and settings (seeds, learning rates) show only where they belong, a distance-only
type does not ask for torch, makes no copies and cannot continue from a model, a run trains in the background and its model is listed, exported, imported and removed."""
import os, sys, tempfile, time, json
HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
TMP = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(TMP, "user")
CORE = os.path.join(HERE, "core") if os.path.isdir(os.path.join(HERE, "core")) else HERE
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
ANN = os.path.join(ADD, "annotator", "app")
for p in (CORE, ANN, os.path.join(ADD, "trainer")):
    sys.path.insert(0, p)
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
app = QApplication([])
import numpy as np, cv2
import annotator_core as ac, dataset_zip as dz, share_zip as sz
sz.CONFIG_PATH = os.path.join(TMP, "cfg.json")
ME = sz.set_identity({}, "Tester")
sz.save_config({"name": "Tester", "id": ME["id"]})
import trainer_core as tc, trainer_tab as tt

MSG = []
tt.TrainerTab._ask_download = lambda self, text, choices: None
QMessageBox.information = staticmethod(lambda p, t, x, *a, **k: MSG.append((t, x)))
QMessageBox.warning = staticmethod(lambda p, t, x, *a, **k: MSG.append((t, x)))
QMessageBox.critical = staticmethod(lambda p, t, x, *a, **k: MSG.append(("ERR " + t, x)))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
W, H, K = 320, 240, 200.0


def ok(msg):
    print("ok:", msg, flush=True)


def wait(cond, secs=120):
    t0 = time.time()
    while not cond():
        app.processEvents(); time.sleep(0.05)
        assert time.time() - t0 < secs, "timed out"


def recording(name, n, seed, session, with_distance=True):
    rng = np.random.default_rng(seed)
    vid = os.path.join(TMP, name + ".avi")
    vw = cv2.VideoWriter(vid, cv2.VideoWriter_fourcc(*"MJPG"), 10, (W, H))
    truth = []
    for _ in range(n):
        img = np.full((H, W, 3), 90, np.uint8)
        t = []
        for cls in (0, 1):
            h = int(rng.integers(30, 110)); w = int(h * (0.6 if cls == 0 else 1.0))
            x = int(rng.integers(5 + cls * 160, 155 + cls * 160 - w)); y = int(rng.integers(5, H - h - 5))
            cv2.rectangle(img, (x, y), (x + w, y + h), (30, 60, 200) if cls == 0 else (200, 170, 30), -1)
            t.append((cls, (x + w / 2) / W, (y + h / 2) / H, w / W, h / H, K / h))
        vw.write(img); truth.append(t)
    vw.release()
    pr = ac.Project(os.path.join(TMP, name))
    for c in ("crate", "ball"):
        pr.add_class(c)
    pr.editor_id = ME["id"]
    pr.import_video(vid, stride=1, session_name=session)
    ids = sorted(pr.manifest["images"])
    for k, (i, t) in enumerate(zip(ids, truth)):
        picks = [({"distance_m": round(b[5], 3), "u": int(b[1] * W), "v": int(b[2] * H)} if with_distance and (k + j) % 4 else None) for j, b in enumerate(t)]
        pr.set_boxes(i, [b[:5] for b in t], distances=picks)
    z = os.path.join(TMP, name + ".zip")
    dz.export_zip(pr, z, ME)
    return z


def project(name, zips, val):
    tp = tc.TrainingProject(os.path.join(TMP, name + ".training"))
    for z in zips:
        plan = tp.plan_import(z, ME)
        assert not plan["conflicts"], plan["conflicts"]
        tp.apply_import(plan, None, ME)
    tp.set_role(val, "val")
    return tp



root = os.path.join(TMP, "Win.training")
tp0 = project("Win", [recording("a", 12, 1, "ra"), recording("b", 12, 2, "rb"), recording("c", 12, 3, "rc"), recording("d", 10, 4, "rd")], "rd")
tp0.set_settings({"distortions": {"enabled": True, "count": 2}})
tp0.save()
w = tt.make_tab(tp0.root)
w.show(); app.processEvents()
wait(lambda: w.env is not None)

# ---- the types
labels = [w.type_box.itemText(i) for i in range(w.type_box.count())]
assert labels[:2] == ["Classes + boxes", "Classes + boxes + distance"] and labels[2:] == ["Distance only: formula and regressors", "Distance only: neural network"], labels
assert "no torch" in tt.HINTS["type"] or "need no torch" in tt.HINTS["type"]
w.type_box.setCurrentIndex(w.type_box.findData("classical_regress")); app.processEvents()
sizes = [w.size_box.itemText(i) for i in range(w.size_box.count())]
assert sizes == ["All five, compared", "Formula k / height", "Log-linear regression", "k nearest neighbours", "Gradient boosting", "Gaussian process"], sizes
assert w.size_box.currentData() == "all" and w.tp.settings["model"]["type"] == "classical_regress"
assert not w.cont_on.isEnabled() and w.more["patience"].isHidden() and w.more["batch"].isHidden() and w.more["imgsz"].isHidden() and w.size_label.text() == "Regressor"
assert not w.seeds.isEnabled() and not w.lrs_box.isEnabled() and not w.cl_folds.isHidden() and w.net_loss.isHidden()
assert "no distorted copies are made" in w.dist_note.text()
ok("a distance-only type is offered after the YOLO types with sizes named for what they train; continue-from, early stopping and batch are off for it")

# ---- it does not ask for torch
assert w.env["problems"], "this computer has no torch: the YOLO types are not possible here"
assert "Training is not possible" not in w.env_label.text() and "numpy" in w.env_label.text() and w.btn_train.isEnabled(), w.env_label.text()
w.type_box.setCurrentIndex(w.type_box.findData("yolo")); app.processEvents()
assert "Training is not possible" in w.env_label.text() and w.cont_on.isEnabled() and not w.more["batch"].isHidden() and w.more["batch"].isEnabled() and w.dist_note.text() != "" and "no distorted copies are made" not in w.dist_note.text()
MSG.clear(); w.start()
assert MSG and "torch" in MSG[-1][1], MSG
ok("a distance-only type needs numpy and no torch: Start is allowed; the YOLO types still say torch is missing and refuse")

# ---- the network type: seeds and learning rates
w.type_box.setCurrentIndex(w.type_box.findData("nn_ladder")); app.processEvents()
assert [w.size_box.itemText(i) for i in range(3)] == ["The whole ladder (rungs 0 - 8)", "1986 baseline (rung 0)", "tanh (rung 1)"] and w.size_box.currentData() == "6", [w.size_box.itemText(i) for i in range(3)]
assert w.size_label.text() == "Recipe" and w.seeds.isEnabled() and w.lrs_box.isEnabled() and w.seeds.value() == 1 and w.lrs_box.currentData() is None and not w.net_loss.isHidden() and w.cl_folds.isHidden()
w.seeds.setValue(3); w.lrs_box.setCurrentIndex(w.lrs_box.findData("grid")); app.processEvents()
assert w.tp.settings["model"]["params"] == {"seeds": 3, "lrs": "grid"}, w.tp.settings["model"]["params"]
w.refresh_all(); app.processEvents()
assert w.seeds.value() == 3 and w.lrs_box.currentData() == "grid" and w.type_box.currentData() == "nn_ladder"
w.type_box.setCurrentIndex(w.type_box.findData("classical_regress")); app.processEvents()
assert not w.seeds.isEnabled() and not w.lrs_box.isEnabled()
ok("seeds and learning rates are for the network only and are kept in the project's settings")

# ---- a run
w.type_box.setCurrentIndex(w.type_box.findData("nn_ladder")); app.processEvents()
w.seeds.setValue(1); w.lrs_box.setCurrentIndex(0); w.epochs.setValue(4); app.processEvents()
w.start()
wait(lambda: w.job is not None or w._prep is None and "did not start" in w.run_label.text())
assert w.job is not None, (w.run_label.text(), w.log.toPlainText()[-500:], MSG[-2:])
wait(lambda: w.job is None and not w.btn_stop.isEnabled(), 150)
log = w.log.toPlainText()
assert w.run_label.text().startswith("Finished. The new model is saved"), (w.run_label.text(), log[-1200:])
assert "Done" in log and "validation median error" in log
assert w.models_list.count() == 1
txt = w.models_list.item(0).text()
assert txt.startswith("network, rung 6   distance only") and "distance error" in txt, txt
assert os.path.isfile(w.models_list.item(0).data(0x100)) and w.models_list.item(0).data(0x100).endswith(".opdm")
assert not os.path.exists(os.path.join(tc.annotator_models_dir(), "Scratch")) and not os.path.exists(os.path.join(tc.annotator_models_dir(), "Assist"))
ok("Start training runs the network in the background without torch; the model is listed as 'network, rung 6 - distance only' with its error")

# ---- the Train page followed the run (live.json) and says how it ended
assert os.path.isfile(os.path.join(w.tp.runs_dir, sorted(os.listdir(w.tp.runs_dir))[-1], "live.json"))
assert w.runs_table.rowCount() == 1 and w.runs_table.item(0, 0).text() == "0.001, seed 0" and w.runs_table.item(0, 1).text().endswith(" %"), (w.runs_table.rowCount(), w.runs_table.item(0, 1).text())
assert w.now_table.item(0, 1).text() == "4 of 4" and w.now_table.item(1, 1).text().endswith(" %") and w.now_table.item(2, 1).text().endswith(" %"), [w.now_table.item(r, 1).text() for r in range(4)]
assert w.live_plots["error"].spec["series"][0]["name"] == "Validation" and len(w.live_plots["error"].spec["series"][0]["points"]) == 4 and w.live_plots["error"].spec["hlines"]
assert len(w.live_plots["grad"].spec["series"]) == 2 and w.btn_stop.text() == "Stop" and not w.btn_stop.isEnabled() and w.btn_train.isEnabled()
ok("the Train page lists the run with its error, shows the last epoch and draws the error and the gradient norm of the four epochs")

# ---- the run has charts
assert [w.run_tabs.tabText(i) for i in range(3)] == ["Live charts", "Log", "Finished runs"] and w.run_tabs.currentWidget() is w.charts, "a finished network run opens its charts"
assert w.charts.data is not None and w.charts.data.keys == ["rung6"] and w.charts.run_box.count() == 1 and w.charts.fig_box.currentData() == "learning"
sp = w.charts.spec()
assert any(len(s["points"]) == 4 for s in sp["series"] if s["legend"]) and not sp["empty"], "four epochs of the run"
w.charts.fig_box.setCurrentIndex(w.charts.fig_box.findData("final")); app.processEvents()
assert w.charts.spec()["xcat"] == ["rung6"] and w.charts.plot.spec["hlines"]
ok("a finished network run opens the Charts tab on its learning curves (the four epochs it had) and the other figures draw the same run")

# ---- export, import, remove
w.models_list.setCurrentRow(0)
out = os.path.join(TMP, "exported", "net")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
w.export_model()
assert os.path.isfile(out + ".opdm") and w.status.text() == "Exported net.opdm."
w.remove_model()
assert w.models_list.count() == 0
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([out + ".opdm"], ""))
MSG.clear(); w.import_model()
assert w.models_list.count() == 1 and w.models_list.item(0).text().startswith("network, rung 6") and not MSG
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
ev = Ev([out + ".opdm"]); w.dragEnterEvent(ev)
assert ev.ok, "a dragged .opdm file is accepted"
ok("exporting writes one .opdm file, removing takes it from the list, importing it again lists it again (no code warning: it is numbers), and a dragged .opdm is accepted")

w.close()
print("trainer numeric qt ok", flush=True)
