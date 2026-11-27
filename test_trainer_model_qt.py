import faulthandler; faulthandler.dump_traceback_later(200, exit=True)
"""The Model page of the Trainer window: the four kinds as ribbon buttons that follow the type, the layers table of a network (+ layer, - layer, neurons typed in, the parameters of
every layer and the total), the settings of a recipe and what differs from it (kept in the project, restored, replaced by the next recipe), the optimiser's own step size, the runs
caption (seeds x learning rates x rungs), your own learning rates, the rows of the classic regressors, and what the other kinds show.  python test_trainer_model_qt.py"""
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
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox
app = QApplication([])
import numpy as np, cv2
import annotator_core as ac, dataset_zip as dz, share_zip as sz
sz.CONFIG_PATH = os.path.join(TMP, "cfg.json")
ME = sz.set_identity({}, "Tester")
sz.save_config({"name": "Tester", "id": ME["id"]})
import np_net as nn
import trainer_core as tc, trainer_tab as tt

tt.TrainerTab._ask_download = lambda self, text, choices: None
QMessageBox.information = staticmethod(lambda p, t, x, *a, **k: None)
QMessageBox.warning = staticmethod(lambda p, t, x, *a, **k: None)
W, H, K = 320, 240, 200.0


def ok(msg):
    print("ok:", msg, flush=True)


def wait(cond, secs=60):
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




tp0 = project("Model", [recording("a", 8, 1, "ra"), recording("b", 8, 2, "rb")], "rb")
tp0.save()
w = tt.make_tab(tp0.root)
w.show(); app.processEvents()
wait(lambda: w.env is not None)
mp = lambda: w.tp.settings["model"].get("params")                                             # noqa: E731  (what the project keeps)


def pick_type(t):
    w.type_box.setCurrentIndex(w.type_box.findData(t)); app.processEvents()


def pick_size(d):
    w.size_box.setCurrentIndex(w.size_box.findData(d)); app.processEvents()


# ---- the four tabs and the four kinds
assert [w.ribbon.tabText(i) for i in range(w.ribbon.count())] == ["Data", "Model", "Train", "Setup"] and w.pages.count() == 4
assert list(w._kind_buttons) == ["yolo", "yolo_distance", "classical_regress", "nn_ladder"], list(w._kind_buttons)
assert [b.text() for b in w._kind_buttons.values()] == ["Detector", "Detector +\ndistance", "Distance:\nclassic", "Distance:\nnetwork"]
assert all(b.isCheckable() and b.toolTip() for b in w._kind_buttons.values())
w._kind_buttons["nn_ladder"].click(); app.processEvents()
assert w.type_box.currentData() == "nn_ladder" and [k for k, b in w._kind_buttons.items() if b.isChecked()] == ["nn_ladder"]
pick_type("classical_regress")
assert [k for k, b in w._kind_buttons.items() if b.isChecked()] == ["classical_regress"], "a change of the type is followed by the buttons"
w._kind_buttons["classical_regress"].click(); app.processEvents()
assert w.type_box.currentData() == "classical_regress" and w._kind_buttons["classical_regress"].isChecked(), "pressing the kind that is on keeps it on"
ok("the four kinds are buttons of the ribbon, one on at a time, and they follow the type of the project")

# ---- a network: the layers table
w._kind_buttons["nn_ladder"].click(); app.processEvents()
assert w.size_box.currentData() == "6" and w.size_label.text() == "Recipe" and w._rung() == 6 and w.net_hidden == [32, 16]
t = w.layers_table
assert t.rowCount() == 5 and [t.item(r, 0).text() for r in range(5)] == ["Input", "Hidden 1", "Hidden 2", "Output", "Total"], [t.item(r, 0).text() for r in range(t.rowCount())]
assert [t.item(r, 3).text() for r in range(5)] == ["0", "224", "528", "17", "769"] and t.item(0, 1).text() == "6" and t.item(3, 1).text() == "1" and t.item(3, 2).text() == "linear"
assert t.cellWidget(1, 1).value() == 32 and t.cellWidget(2, 1).value() == 16 and t.cellWidget(0, 1) is None, "the neurons of the hidden layers can be typed, the input and the output cannot"
assert w.rd_params.text() == "769" and w.rd_shape.text() == "32 - 16" and w.model_caption.text() == "2 hidden layers" and w.layer_bars.sizes == [6, 32, 16, 1]
assert w.kind_stack.currentIndex() == 0 and not w.layers_box.isHidden()
w.ribbon.show_page("Model"); app.processEvents()
assert w.pages.currentWidget() is w.model_page and w.foot_info.text() == "2 hidden layers, 769 parameters", (w.foot_info.text(), w.pages.currentIndex())
ok("a network shows its layers (input 6, the hidden layers, the output 1) with the parameters of each layer and the total, 769 for rung 6")

w.layer_add.click(); app.processEvents()
assert w.net_hidden == [32, 16, 16] and w.layers_table.rowCount() == 6 and w.rd_params.text() == f"{nn.count_params(6, [32, 16, 16], False):,}" == "1,041" and w.layer_bars.sizes == [6, 32, 16, 16, 1]
assert mp() == {"hidden": [32, 16, 16], "seeds": 1, "lrs": None}, mp()
w.layer_del.click(); w.layer_del.click(); w.layer_del.click(); app.processEvents()
assert w.net_hidden == [32] and w.rd_params.text() == f"{nn.count_params(6, [32], False):,}" and w.model_caption.text() == "1 hidden layer of 32", "the last hidden layer stays"
w.layer_add.click(); w.layer_add.click(); w.layer_add.click(); app.processEvents()
assert w.net_hidden == [32, 32, 32, 32] and w.rd_shape.text() == "32 x 4" and w.model_caption.text() == "4 hidden layers of 32"
ok("+ layer adds a hidden layer as wide as the last, - layer takes it away (one stays), and the parameters, the bars and the caption follow")

w.net_bn.setChecked(True); app.processEvents()
assert w.rd_params.text() == "3,681" and t.item(t.rowCount() - 1, 3).text() == "3,681" and t.item(1, 3).text() == "288", (w.rd_params.text(), t.item(1, 3).text())
assert mp() == {"hidden": [32, 32, 32, 32], "batch_norm": True, "seeds": 1, "lrs": None}, mp()
ok("4 hidden layers of 32 with batch norm come to 3,681 parameters (the number of the design board), and the project keeps only what differs from the recipe")

t.cellWidget(2, 1).setValue(8); app.processEvents()
assert w.net_hidden == [32, 8, 32, 32] and w.rd_shape.text() == "32 - 8 - 32 - 32" and w.rd_params.text() == f"{nn.count_params(6, [32, 8, 32, 32], True):,}" and t.cellWidget(2, 1).value() == 8
assert mp()["hidden"] == [32, 8, 32, 32]
ok("typing the neurons of a hidden layer changes the numbers and the shape, and the box typed in stays")

# ---- the recipe's other settings
w.net_opt.setCurrentIndex(w.net_opt.findData("plain")); app.processEvents()
assert abs(w.net_lr.value() - 0.03) < 1e-12 and not w.net_mom.isEnabled() and mp()["optimizer"] == "sgd" and "lrs" in mp() and mp()["lrs"] is None, (w.net_lr.value(), mp())
w.net_opt.setCurrentIndex(w.net_opt.findData("momentum")); app.processEvents()
assert abs(w.net_lr.value() - 0.03) < 1e-12 and w.net_mom.isEnabled() and abs(w.net_mom.value() - 0.9) < 1e-12 and mp()["momentum"] == 0.9
w.net_opt.setCurrentIndex(w.net_opt.findData("adamw")); app.processEvents()
assert abs(w.net_lr.value() - 0.001) < 1e-12 and not w.net_mom.isEnabled() and mp()["optimizer"] == "adamw" and "momentum" not in mp()
ok("the optimiser brings its usual step size (0.03 for gradient descent, 0.001 for Adam); momentum is a box only for 'with momentum'")

w.net_init.setCurrentIndex(w.net_init.findData("he")); w.net_act.setCurrentIndex(w.net_act.findData("silu")); app.processEvents()
assert w.net_init.currentData() == "glorot" and mp()["activation"] == "silu" and mp()["init"] == "glorot" and w.layers_table.item(1, 2).text() == "SiLU"
w.net_lr.setValue(0.01); w.net_lr.changed.emit(); app.processEvents()
assert mp()["lrs"] == 0.01, "a step size of your own (not the optimiser's usual) goes to the job as the one learning rate"
ok("SiLU goes with Glorot (as in the recipes); a learning rate typed in is the one rate the job tries")

# ---- kept in the project, restored, replaced by another recipe
kept = dict(mp())
w.refresh_all(); app.processEvents()
assert w.net_hidden == [32, 8, 32, 32] and w.net_bn.isChecked() and w.net_opt.currentData() == "adamw" and w.net_act.currentData() == "silu" and abs(w.net_lr.value() - 0.01) < 1e-12 and mp() == kept, (mp(), kept)
assert w.rd_params.text() == f"{nn.count_params(6, [32, 8, 32, 32], True):,}"
ok("reopening the window restores every setting that was changed by hand")

pick_size("1")
assert w._rung() == 1 and w.net_hidden == [32, 16] and not w.net_bn.isChecked() and w.net_act.currentData() == "tanh" and w.net_opt.currentData() == "plain" and abs(w.net_lr.value() - 0.03) < 1e-12
assert mp() == {"seeds": 1, "lrs": None}, mp()
assert w.rd_params.text() == "769" and w.layers_table.item(1, 2).text() == "tanh"
ok("another recipe fills the controls with its own settings and what was changed by hand is dropped")

# ---- the whole ladder and the demonstrations
pick_size("ladder")
assert w._rung() is None and mp() == {"seeds": 1, "lrs": None}
assert not any(x.isEnabled() for x in (w.net_loss, w.net_opt, w.net_lr, w.net_act, w.net_init, w.net_target, w.net_batch, w.net_bn, w.layer_add, w.layer_del, w.layers_table)), "the ladder has the settings of its rungs"
assert w.runs_caption.text() == "1 seed x 1 learning rate x 9 rungs = 9 runs", w.runs_caption.text()
w.seeds.setValue(2); app.processEvents()
assert w.runs_caption.text() == "2 seeds x 1 learning rate x 9 rungs = 18 runs" and w._run_count() == 18
w.lrs_box.setCurrentIndex(w.lrs_box.findData("grid")); app.processEvents()
assert w._run_count() == 2 * (6 * 8 + 3 * 5) == 126 and w.runs_caption.text() == "2 seeds x the learning-rate grid of each rung = 126 runs", w.runs_caption.text()
ok("the whole ladder has its settings greyed and counts its runs: 2 seeds with the grid are 126 runs (8 rates for the six gradient-descent rungs, 5 for the three Adam rungs)")

pick_size("demo_sigmoid")
assert w._rung() == "demo_sigmoid" and w.net_hidden == [32] * 8 and w.layer_bars.sizes == [6] + [32] * 8 + [1] and w.rd_shape.text() == "32 x 8" and w.model_caption.text() == "8 hidden layers of 32"
ok("a deep demonstration shows its eight hidden layers")

# ---- the learning rates
pick_size("6"); w.seeds.setValue(3); app.processEvents()
w.lrs_box.setCurrentIndex(w.lrs_box.findData(None)); app.processEvents()
assert w.runs_caption.text() == "3 seeds x 1 learning rate = 3 runs" and mp() == {"seeds": 3, "lrs": None}, (w.runs_caption.text(), mp())
w.lrs_box.setCurrentIndex(w.lrs_box.findData("grid")); app.processEvents()
assert w.runs_caption.text() == "3 seeds x 5 learning rates = 15 runs" and mp()["lrs"] == "grid"
pick_size("2")
assert w.runs_caption.text() == "3 seeds x 8 learning rates = 24 runs", "the grid of gradient descent has eight"
asked = []
QInputDialog.getText = staticmethod(lambda *a, **k: (asked.append(k.get("text")) or ("0.0003, 0.001, 0.003", True)))
w.lrs_box.setCurrentIndex(w.lrs_box.findData("own")); w._lrs_picked(); app.processEvents()
assert w._own_lrs == [0.0003, 0.001, 0.003] and w.lrs_box.currentText() == "3 values, 0.0003 to 0.003" and mp()["lrs"] == [0.0003, 0.001, 0.003], (w._own_lrs, w.lrs_box.currentText(), mp())
assert w.runs_caption.text() == "3 seeds x 3 learning rates = 9 runs"
w.refresh_all(); app.processEvents()
assert w._own_lrs == [0.0003, 0.001, 0.003] and w.lrs_box.currentData() == "own" and w.lrs_box.currentText() == "3 values, 0.0003 to 0.003"
ok("learning rates: the recipe's own, the specification's grid or a list of your own, counted in the caption and kept in the project")

QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
w._own_lrs = []; w.lrs_box.setCurrentIndex(w.lrs_box.findData("own")); w._lrs_picked(); app.processEvents()
assert w.lrs_box.currentData() is None and w._own_lrs == [] and mp()["lrs"] is None, "cancelling with no values of your own goes back to the recipe's rate"

# ---- the classic regressors
w._kind_buttons["classical_regress"].click(); app.processEvents()
assert w._kind() == "classic" and w.size_label.text() == "Regressor" and w.kind_stack.currentIndex() == 1 and w.layers_box.isHidden() and w.rd_params.text() == "-" and not w.rd_params.isEnabled()
assert not w.cl_folds.isHidden() and w.net_loss.isHidden() and w.net_lr.isHidden() and w.more["batch"].isHidden() and w.cont_on.isHidden() and "k / height" in w.about_label.text()
assert "One run" in w.runs_caption.text() and not w.seeds.isEnabled() and not w.chk_error.isEnabled()
pick_size("boosting")
assert w.cl_folds.isEnabled() and w.cl_blr.isEnabled() and w.cl_bdepth.isEnabled() and w.cl_biter.isEnabled() and not w.cl_gprows.isEnabled() and not w.cl_width.isEnabled()
pick_size("loglinear")
assert w.cl_width.isEnabled() and not w.cl_folds.isEnabled() and not w.cl_blr.isEnabled() and not w.cl_gprest.isEnabled()
pick_size("gp")
assert w.cl_gprows.isEnabled() and w.cl_gprest.isEnabled() and not w.cl_width.isEnabled() and not w.cl_bdepth.isEnabled()
pick_size("all")
assert all(getattr(w, n).isEnabled() for n in ("cl_folds", "cl_width", "cl_blr", "cl_bdepth", "cl_biter", "cl_gprows", "cl_gprest"))
ok("a regressor row is on only for the regressors that use it; the network's rows are gone, the seeds and the live charts are off")

w.cl_blr.setText("0.05, 0.2"); w.cl_blr.editingFinished.emit(); w.cl_bdepth.setText("3;5"); w.cl_bdepth.editingFinished.emit(); w.cl_folds.setValue(4); w.cl_width.setChecked(True); app.processEvents()
assert mp() == {"folds": 4, "loglinear_width": True, "boosting_learning_rates": [0.05, 0.2], "boosting_depths": [3, 5], "boosting_max_iter": 500, "gp_max_rows": 6000, "gp_restarts": 2}, mp()
w.cl_blr.setText("fast"); w.cl_blr.editingFinished.emit(); app.processEvents()
assert "boosting_learning_rates" not in mp(), "text that is not numbers is not sent (the job uses its own)"
w.refresh_all(); app.processEvents()
assert w.cl_folds.value() == 4 and w.cl_width.isChecked() and w.cl_bdepth.text() == "3, 5" and w.type_box.currentData() == "classical_regress"
ok("the tuning of the regressors is kept in the project, text that is not numbers is left out, and the window restores it")

# ---- the detectors
w._kind_buttons["yolo"].click(); app.processEvents()
assert w._kind() == "yolo" and w.size_label.text() == "Size" and w.kind_stack.currentIndex() == 1 and w.about_label.text().startswith("Classes + boxes.") and not w.more["batch"].isHidden() and w.layers_box.isHidden()
w._kind_buttons["yolo_distance"].click(); app.processEvents()
assert w.about_label.text().startswith("Classes + boxes + distance.") and mp() in ({}, None) and not w.cont_on.isHidden()
ok("a detector shows what it is, its size, epochs, batch and picture size, and none of the network's rows")

# ---- the data table
assert [w.data_table.horizontalHeaderItem(c).text() for c in range(4)] == ["Pictures", "Boxes", "Distance boxes", "Validation distance boxes"]
assert all(w.data_table.item(0, c) is not None and w.data_table.item(0, c).text() not in ("", "-") for c in range(4)), [w.data_table.item(0, c).text() for c in range(4)]
assert int(w.data_table.item(0, 0).text().replace(",", "")) == 16 and int(w.data_table.item(0, 1).text().replace(",", "")) == 32
ok("the Model page's data table counts the pictures, the boxes and the boxes with a distance")

w.close()
print("trainer model qt ok", flush=True)
