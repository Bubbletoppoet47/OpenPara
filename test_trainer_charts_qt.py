import faulthandler; faulthandler.dump_traceback_later(290, exit=True)
"""The Charts pane of the Trainer window (trainer_charts.py) on real runs of the distance network: the runs of a project are listed, the figures and their choices (rungs, rung, metric, when)
follow each other, a rung keeps its colour when the others are left out, hovering a point says what is behind it, the table shows the numbers drawn, the drawing really has the colours,
a folder opened from disk joins the list, and a folder that is not a run is refused in a sentence.  python test_trainer_charts_qt.py"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
ANN, TR = os.path.join(ADD, "annotator", "app"), os.path.join(ADD, "trainer")
sys.path.insert(0, TR)
import cv2
import numpy as np
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication, QFileDialog

import chart_data as cd
import trainer_charts as tch

app = QApplication([])
TMP = tempfile.mkdtemp()
S, F, CAM, HORIZON, H_REAL = 640, 420.0, 1.2, 300.0, 1.7


def ok(msg):
    print("ok:", msg, flush=True)


def frozen_copy(root, n_train, n_val, seed, with_distances=True, copies=1):
    """A frozen copy as Trainer.freeze() writes it: 640 x 480 pictures (letterboxed to 640 they have 80 pixel bars), three people per picture, in recordings."""
    rng = np.random.default_rng(seed)
    rows, k = [], 0
    for split, n, recs in (("train", n_train, 8), ("val", n_val, 3)):
        os.makedirs(os.path.join(root, "images", split), exist_ok=True)
        os.makedirs(os.path.join(root, "labels", split), exist_ok=True)
        for i in range(n):
            rec = (f"{'a' if split == 'train' else 'z'}{i % recs}")
            name = f"gim_{rec}_{i:06d}"
            lab, drows = [], []
            for _ in range(3):
                d = float(np.exp(rng.uniform(np.log(2.5), np.log(20.0))))
                h = F * H_REAL / d
                w = 0.4 * h
                cx = rng.uniform(100, 540)
                y2 = HORIZON + F * CAM / d
                x1, y1, x2, y2o = cx - w / 2, y2 - h - 80, cx + w / 2, y2 - 80            # original pixels (the 80 pixel bar of the letterbox is above)
                xc, yc, bw, bh = (x1 + x2) / 2 / 640, (y1 + y2o) / 2 / 480, w / 640, h / 480
                lab.append(f"0 {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
                label = d * float(np.exp(rng.normal(0, 0.05)))
                if with_distances and rng.random() < 0.9:
                    drows.append((split, name, 0, "person", f"{xc:.6f}", f"{yc:.6f}", f"{bw:.6f}", f"{bh:.6f}", f"{label:.3f}"))
            names = [name] + ([f"{name}_dist{c + 1}" for c in range(copies)] if split == "train" else [])
            for nm in names:
                cv2.imwrite(os.path.join(root, "images", split, nm + ".jpg"), np.full((480, 640, 3), 120, np.uint8))
                open(os.path.join(root, "labels", split, nm + ".txt"), "w").write("\n".join(lab) + "\n")
                rows += [(a, nm) + r[2:] for a, r in zip([split] * len(drows), drows)]
            k += 1
    with open(os.path.join(root, "distances.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["split", "image", "class_id", "class", "xc", "yc", "w", "h", "distance_m"])
        w.writerows(rows)
    open(os.path.join(root, "data.yaml"), "w").write(f"path: {root.replace(os.sep, '/')}\ntrain: images/train\nval: images/val\nnc: 1\nnames:\n  0: person\n")
    return os.path.join(root, "data.yaml"), sum(1 for r in rows if r[0] == "train") // (1 + copies)



def run_job(name, data_yaml, params=None, size="6", dist_train=None):
    run = os.path.join(TMP, "run_" + name)
    os.makedirs(run)
    models = os.path.join(TMP, "run_" + name + "_models")
    os.makedirs(models)
    job = {"data_yaml": data_yaml, "run_dir": run, "type": "nn_ladder", "size": size, "imgsz": 640, "classes": ["person"], "models_dirs": [models], "trainer": "Tester",
           "lib_dir": ANN, "dist_counts": {"train": dist_train, "val": 0}, "params": params or {}}
    jp = os.path.join(run, "job.json")
    json.dump(job, open(jp, "w"))
    r = subprocess.run([sys.executable, "-u", os.path.join(TR, "train_nn_job.py"), jp], capture_output=True, text=True, timeout=270, cwd=run)
    return run, models, r



yaml_path, n_tr = frozen_copy(os.path.join(TMP, "frozen"), 220, 90, 1)
RUNS = os.path.join(TMP, "runs")
os.makedirs(RUNS)
for name, params, size in (("20261126_100000_nn_ladder_ladder", {"epochs": 3, "n_boot": 100, "seeds": 2, "lrs": [0.01]}, "ladder"),
                           ("20261126_110000_nn_ladder_0", {"lrs": [8.0, 0.1], "seeds": 2, "epochs": 6, "n_boot": 100}, "0"),
                           ("20261126_120000_nn_ladder_demos", {"epochs": 4, "n_boot": 50, "lrs": [0.005]}, "demos")):
    run, _m, r = run_job(name, yaml_path, params, size=size, dist_train=n_tr)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    shutil.move(run, os.path.join(RUNS, name))
os.makedirs(os.path.join(RUNS, "20261126_130000_not_a_run"))              # (a folder without the tables: not listed)


def pixels(widget, hexcol, tol=14):
    img = widget.grab().toImage()
    want = tuple(int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            if abs(c.red() - want[0]) <= tol and abs(c.green() - want[1]) <= tol and abs(c.blue() - want[2]) <= tol:
                n += 1
    return n


pane = tch.ChartsPane()
pane.resize(820, 560)
pane.show()
app.processEvents()
assert pane.data is None and pane.spec()["empty"] and pane.fig_box.count() == 6
assert "No run to draw" in pane.note.text()
pane.fig_box.setCurrentIndex(pane.fig_box.findData("momentum")); app.processEvents()
assert not pane.spec()["empty"] and len(pane.spec()["series"]) == 4 and pane.group_box.isHidden() and pane.key_box.isHidden() and pane.metric_box.isHidden()
pane.fig_box.setCurrentIndex(0); app.processEvents()
ok("with no run the pane says so in a sentence; the momentum toy needs none")

pane.set_runs_dir(RUNS)
names = [pane.run_box.itemText(i) for i in range(pane.run_box.count())]
assert names == ["20261126_120000_nn_ladder_demos", "20261126_110000_nn_ladder_0", "20261126_100000_nn_ladder_ladder"], names
assert pane.data is not None and pane.data.keys == ["demo_sigmoid", "demo_relu_he", "demo_bn"] and pane.run_box.currentIndex() == 0
ok("the runs of the project are listed newest first (a folder without the tables is not), and the newest is shown")

# the choices follow the figure
assert not pane.group_box.isHidden() and not pane.metric_box.isHidden() and pane.key_box.isHidden() and pane.when_box.isHidden()
assert [pane.metric_box.itemData(i) for i in range(pane.metric_box.count())] == ["val_err", "train_loss", "val_loss"]
pane.fig_box.setCurrentIndex(pane.fig_box.findData("layers")); app.processEvents()
assert [pane.metric_box.itemData(i) for i in range(pane.metric_box.count())] == ["grad_norm", "update_ratio", "weight_norm", "saturation", "dead"] and not pane.when_box.isHidden()
sp = pane.spec()
assert sp["ylog"] and {s["name"].split()[0] for s in sp["series"]} == {"demo_sigmoid", "demo_relu_he", "demo_bn"}
pane.metric_box.setCurrentIndex(pane.metric_box.findData("saturation")); pane.when_box.setCurrentIndex(1); app.processEvents()
sp = pane.spec()
assert not sp["ylog"] and "end of training" in sp["title"] and "Saturated" in sp["ylabel"]
pane.fig_box.setCurrentIndex(pane.fig_box.findData("sweep")); app.processEvents()
assert not pane.key_box.isHidden() and pane.group_box.isHidden() and pane.metric_box.isHidden() and pane.when_box.isHidden() and pane.key_box.count() == 3
ok("each figure shows only the boxes it uses (rungs, rung, metric, at); the layer metrics and the start / end of training change the chart")

# a rung keeps its colour
pane.fig_box.setCurrentIndex(pane.fig_box.findData("learning")); app.processEvents()
pane.load(os.path.join(RUNS, "20261126_100000_nn_ladder_ladder"))
assert pane.run_box.currentText() == "20261126_100000_nn_ladder_ladder" and pane.data.keys == [f"rung{i}" for i in range(9)]
groups = [pane.group_box.itemText(i) for i in range(pane.group_box.count())]
assert groups[0] == "All" and len(groups) == 10, groups                       # (no deep demonstrations in this run: no "ladder only" choice)
all_slots = [s["slot"] for s in pane.spec()["series"] if s["legend"]]
assert all_slots == list(range(8)), all_slots
pane.group_box.setCurrentIndex(pane.group_box.findText("rung3  log target")); app.processEvents()
one = [s for s in pane.spec()["series"] if s["legend"]]
assert len(one) == 1 and one[0]["slot"] == 3 and "log target" in one[0]["name"]
ok("a rung keeps its colour when the others are left out (rung 3 is the fourth colour whether or not rung 0 is drawn)")

# painting and hover
pane.group_box.setCurrentIndex(0); app.processEvents()
pane.plot.repaint(); app.processEvents()
assert pixels(pane.plot, tch.PALETTE[0]) > 40 and pixels(pane.plot, tch.PALETTE[1]) > 40 and pixels(pane.plot, tch.PALETTE[2]) > 40, "the first three series are really drawn in their colours"
pts = pane.plot._pts
assert pts and all(len(p) == 3 for p in pts)
x, y, tip = pts[len(pts) // 2]
assert pane.plot.tip_at(QPointF(x + 3, y - 2)) == tip and "epoch" in tip and "learning rate" in tip and pane.plot.tip_at(QPointF(2, 2)) == ""
ok("the chart is drawn in the palette's colours, and hovering a point says its rung, learning rate, seed, epoch and value")
pane.fig_box.setCurrentIndex(pane.fig_box.findData("final")); app.processEvents()
pane.plot.repaint(); app.processEvents()
leg = pane.plot._legend(700)[0]
assert any(item[0].get("hline") for item in leg), "the formula's line is in the legend"

# the table
pane.table_btn.setChecked(True); app.processEvents()
assert pane.stack.currentIndex() == 1 and pane.table.columnCount() == 5 and pane.table.rowCount() == 9 and pane.table.horizontalHeaderItem(3).text() == "low"
assert pane.table.item(0, 1).text() == "rung0" and float(pane.table.item(0, 2).text()) > 0
pane.table_btn.setChecked(False); app.processEvents()
assert pane.stack.currentIndex() == 0
ok("Table shows the numbers that are drawn (a row per rung, with the interval)")

# the diverging run
pane.load(os.path.join(RUNS, "20261126_110000_nn_ladder_0"))
pane.fig_box.setCurrentIndex(pane.fig_box.findData("sweep")); app.processEvents()
sp = pane.spec()
assert [s["name"] for s in sp["series"]] == ["median over the seeds", "runs that diverged"] and "red plus" in sp["note"]
pane.plot.repaint(); app.processEvents()
assert pixels(pane.plot, tch.PALETTE[7]) > 4, "the mark of the diverged runs is drawn"
ok("the learning-rate chart of a run with a rate that blew up marks it")

# opening folders
out = {"p": os.path.join(RUNS, "20261126_130000_not_a_run")}
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: out["p"])
pane.open_folder()
assert "not a distance-network run" in pane.note.text() and pane.data.dir.endswith("_nn_ladder_0")
elsewhere = os.path.join(TMP, "elsewhere")
os.makedirs(elsewhere)
shutil.copytree(os.path.join(RUNS, "20261126_100000_nn_ladder_ladder"), os.path.join(elsewhere, "my_ladder_run"))
out["p"] = os.path.join(elsewhere, "my_ladder_run")
pane.open_folder()
assert pane.data.dir == out["p"] and pane.run_box.currentText().startswith("my_ladder_run") and pane.data.keys[0] == "rung0"
pane.set_runs_dir(RUNS)
assert pane.run_box.itemText(0).endswith("(opened)") and pane.run_box.currentIndex() == 0 and pane.data.dir == out["p"], "a run opened from disk stays in the list while it is shown"
ok("a folder that is not a run is refused in a sentence (the run shown stays); a run folder opened from disk is shown and stays in the list")

# ---------------------------------------------------------------- the neurons-per-layer bars of the Model tab
from PyQt6.QtGui import QColor  # noqa: E402

bars = tch.LayerBars()
bars.resize(480, 300)
assert bars.labels() == [] and bars.grab().toImage().pixelColor(240, 150) == QColor(tch.SURFACE), "no layers: an empty surface"
bars.set_layers([6, 32, 32, 32, 32, 1])
assert bars.labels() == ["In", "H1", "H2", "H3", "H4", "Out"] and bars.sizes == [6, 32, 32, 32, 32, 1]
img = bars.grab().toImage()
slot = (480 - bars.LEFT - bars.RIGHT) / 6
y_low = 300 - bars.BOTTOM - 3
cols = [img.pixelColor(int(bars.LEFT + slot * (i + 0.5)), y_low) for i in range(6)]
want = [QColor(tch.INK)] + [QColor(tch.PALETTE[0])] * 4 + [QColor(tch.INK)]
assert cols == want, ([c.name() for c in cols], [c.name() for c in want])
tall = img.pixelColor(int(bars.LEFT + slot * 1.5), 300 - bars.BOTTOM - int((300 - bars.TOP - bars.BOTTOM) * 0.6))
short = img.pixelColor(int(bars.LEFT + slot * 5.5), 300 - bars.BOTTOM - int((300 - bars.TOP - bars.BOTTOM) * 0.6))
assert tall == QColor(tch.PALETTE[0]) and short in (QColor(tch.SURFACE), QColor(tch.GRID)), "a layer of 32 is tall, the output of 1 is short"
bars.set_layers([6, 8, 1])
assert bars.labels() == ["In", "H1", "Out"] and bars.grab().toImage() != img
bars.set_layers([4])
assert bars.labels() == [] and bars.grab().toImage().pixelColor(240, 150) == QColor(tch.SURFACE), "one number is not a network: nothing drawn"
ok("the layer bars: the input and the output in the ink, the hidden layers in the first colour of the palette, a bar as tall as its neurons, nothing for no network")

pane.close()
print("trainer charts qt ok", flush=True)
