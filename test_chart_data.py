import faulthandler; faulthandler.dump_traceback_later(290, exit=True)
"""chart_data.py on real runs of train_nn_job.py (made-up pictures seen by a pinhole camera): the learning curves, the learning-rate sweep with a rate that diverges, the layer-by-layer numbers
of the deep demonstrations, the error and the epochs by rung with the formula beside them, and the momentum toy against the roots of its equation.  No Qt.
python test_chart_data.py"""
import csv
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
ANN, TR = os.path.join(ADD, "annotator", "app"), os.path.join(ADD, "trainer")
sys.path.insert(0, TR)
import cv2
import numpy as np

import chart_data as cd
import np_net as nn

assert "PyQt6" not in sys.modules, "the chart data must not need Qt"
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


def go(name, params, size):
    run, _models, r = run_job(name, yaml_path, params, size=size, dist_train=n_tr)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    return cd.RunData(run)


# ---------------------------------------------------------------- a rung with two learning rates and two seeds
d6 = go("rung6", {"seeds": 2, "lrs": [0.003, 0.01], "epochs": 30, "n_boot": 100}, "6")
assert cd.is_run(d6.dir) and d6.ok and d6.keys == ["rung6"] and d6.slot("rung6") == 0 and d6.label("rung6").startswith("rung6")
ch = d6.chosen("rung6")
assert ch is not None and len(d6.runs_at("rung6", ch["lr"])) == 2
ok("a run folder is read: one rung, four runs, one of them chosen, two at its learning rate")

sp = cd.figure("learning", d6, metric="val_err")
thick = [s for s in sp["series"] if s["legend"]]
thin = [s for s in sp["series"] if not s["legend"]]
assert len(thick) == 1 and len(thin) == 1 and len(thick[0]["points"]) == 30 and len(thin[0]["points"]) == 30 and thick[0]["slot"] == 0 and not sp["ylog"] and sp["y0"], sp["note"]
c = d6.curve(ch["curve"])
assert abs(thick[0]["points"][-1][1] - c["val_median_rel_err"][-1] * 100) < 1e-9 and abs(thick[0]["points"][0][1] - c["val_median_rel_err"][0] * 100) < 1e-9
assert abs(thick[0]["points"][-1][1] - float(ch["median_rel_err"]) * 100) < 1e-4, "the last point of the curve is the error the table gives"
ok(f"learning curves: the chosen run thick (30 epochs), the other seed at its rate thin; the last point is the table's error ({thick[0]['points'][-1][1]:.2f} %)")
sp = cd.figure("learning", d6, metric="train_loss")
assert sp["ylog"] and all(y > 0 for s in sp["series"] for _x, y, _t in s["points"]) and sp["series"][-1]["points"][-1][1] < sp["series"][-1]["points"][0][1]
ok("the training loss is on a log axis and goes down")

sw = cd.figure("sweep", d6, key="rung6")
med = sw["series"][0]
assert [p[0] for p in med["points"]] == [0.003, 0.01] and len(med["band"]) == 2 and sw["xlog"] and sw["spans"] == [(0.003, 0.01, "no run diverged")] and sw["vlines"][0][0] == float(ch["lr"])
assert all(lo <= y <= hi + 1e-9 for (_x, y, _t), (_x2, lo, hi) in zip(med["points"], med["band"]))
ok("the sweep has a point and a band per learning rate (the band holds the median), one stable region and the chosen rate marked")

fin = cd.figure("final", d6)
assert fin["xcat"] == ["rung6"] and len(fin["hlines"]) == 1 and fin["hlines"][0][1].startswith("formula") and fin["series"][0]["points"][0][0] == 0.0
(x, y, _t), (_x, lo, hi) = fin["series"][0]["points"][0], fin["series"][0]["whisk"][0]
assert lo <= y <= hi
ok(f"error by rung: the rung's error with its interval ({lo:.2f} - {hi:.2f} %) and the formula's line at {fin['hlines'][0][0]:.2f} %")

# ---------------------------------------------------------------- a learning rate that blows up
dd_ = go("diverge", {"lrs": [8.0, 0.1], "seeds": 2, "epochs": 10, "n_boot": 100}, "0")
sw = cd.figure("sweep", dd_, key="rung0")
names = [s["name"] for s in sw["series"]]
assert names == ["median over the seeds", "runs that diverged"] and [p[0] for p in sw["series"][0]["points"]] == [0.1], names
assert [p[0] for p in sw["series"][1]["points"]] == [8.0] and "2 of 2" in sw["series"][1]["points"][0][2] and sw["spans"] == [(0.1, 0.1, "no run diverged")]
assert sw["vlines"] == [(0.1, "chosen 0.1")]
lc = cd.figure("learning", dd_)
assert "diverged" not in lc["note"] or "not drawn" in lc["note"]
ok("a learning rate where every run diverged has no error point but a mark at the top that says '2 of 2 runs diverged'; it is outside the stable region")

# ---------------------------------------------------------------- the whole ladder, and the deep demonstrations
lad = go("ladder", {"epochs": 3, "n_boot": 100}, "ladder")
assert lad.keys == [f"rung{i}" for i in range(9)] and [g[0] for g in lad.groups()][:1] == ["All"]
fe = cd.figure("final", lad)
assert fe["xcat"] == lad.keys and len(fe["series"][0]["points"]) == 9
ep = cd.figure("epochs", lad)
assert ep["xcat"] == lad.keys and sum(len(s["points"]) for s in ep["series"]) == 9, "each rung is either reached or not reached"
lc = cd.figure("learning", lad)
assert len([s for s in lc["series"] if s["legend"]]) == 8 and "left out" in lc["note"], "nine rungs: eight get a colour, and the note says the ninth is left out"
only = cd.figure("learning", lad, keys=["rung3"])
assert len([s for s in only["series"] if s["legend"]]) == 1
ok(f"the ladder: nine rungs in the error chart, each rung in the epochs chart once, and a cap of eight colours that says what it leaves out")

demos = go("demos", {"epochs": 4, "n_boot": 50, "lrs": [0.005]}, "demos")
assert demos.keys == ["demo_sigmoid", "demo_relu_he", "demo_bn"] and [g[0] for g in demos.groups()][:1] == ["All"]
g = cd.figure("layers", demos, metric="grad_norm", when="start")
by = {s["name"].split()[0]: s["points"] for s in g["series"]}
assert set(by) == {"demo_sigmoid", "demo_relu_he", "demo_bn"} and g["ylog"] and all(len(p) == 9 for p in by.values()), {k: len(v) for k, v in by.items()}
sig, rel = [p[1] for p in by["demo_sigmoid"]], [p[1] for p in by["demo_relu_he"]]
print(f"   gradient norm by layer: sigmoid {['%.2g' % v for v in sig]}\n                           relu+he {['%.2g' % v for v in rel]}\n                           bn      {['%.2g' % p[1] for p in by['demo_bn']]}")
assert sig[0] < 1e-6 * sig[-1], "a deep sigmoid network: the gradient of the first layer is millions of times smaller than that of the last"
assert rel[0] > 0.1 * rel[-1] and by["demo_bn"][0][1] > 0.1 * by["demo_bn"][-1][1], "ReLU with He initialisation, and batch normalisation, keep it level"
for metric in ("update_ratio", "weight_norm", "saturation", "dead"):
    gm = cd.figure("layers", demos, metric=metric, when="end")
    assert gm["series"] and not gm["empty"], metric
sat = cd.figure("layers", demos, metric="saturation", when="end")
assert all(0 <= p[1] <= 100 for s in sat["series"] for p in s["points"]) and not sat["ylog"]
dead = cd.figure("layers", demos, metric="dead", when="end")
rel_dead = [p[1] for s in dead["series"] if s["name"].startswith("demo_relu_he") for p in s["points"]]
assert rel_dead and all(0 <= v <= 100 for v in rel_dead)
ok("the deep demonstrations, layer by layer: the sigmoid gradient fades towards the first layer; every layer metric is there; saturation and dead units are percentages")

# ---------------------------------------------------------------- the table view
head, rows = cd.table_rows(cd.figure("final", lad))
assert head == ["series", "x", "y", "low", "high"] and len(rows) == 9 and rows[0][1] == "rung0"
head2, rows2 = cd.table_rows(cd.figure("learning", d6))
assert head2 == ["series", "x", "y"] and len(rows2) == 30, "the thin lines are not in the table"
ok("every chart has a table of its numbers (the thin lines of other seeds are left out)")

# ---------------------------------------------------------------- the toy
tm = cd.figure("momentum", None)
assert len(tm["series"]) == 4 and tm["ylog"] and len(tm["vlines"]) == 2
for eta in cd.TOY_ETA_LAM:
    mc = cd.critical_mu(eta)
    assert abs(nn.damping_regime(eta, 1.0, mc)["discriminant"]) < 1e-9, "at the critical momentum the two roots meet"
    under = [mu for mu in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95) if mu > mc + 0.1]
    for mu in under:
        m, p = cd.settle_steps(eta, mu), cd.predicted_steps(eta, mu)
        assert m is not None and p is not None and 0.6 < m / p < 1.5, (eta, mu, m, p)
    over = cd.settle_steps(eta, 0.0)
    best = min(cd.settle_steps(eta, mu) for mu in np.arange(0.0, 0.99, 0.01) if cd.settle_steps(eta, mu))
    assert abs(min(np.arange(0.0, 0.99, 0.01), key=lambda mu: cd.settle_steps(eta, mu) or 1e9) - mc) < 0.15, (eta, mc)
    assert best < over, "momentum settles faster than none"
ok("the toy: the roots predict the measured steps to settle within 40 % where the loss oscillates, and the fastest settling is at the critical momentum (+- 0.15)")
assert cd.figure("sweep", None)["empty"] and cd.figure("learning", cd.RunData(os.path.join(TMP, "nothing")))["empty"]
ok("no run: the chart says so in a sentence")

# ---------------------------------------------------------------- the live charts (the run that is training)
def fake_rows(n, n_hidden=3, ylog_bad=False):
    out = []
    for e in range(1, n + 1):
        r = {"epoch": e, "val_median_rel_err": 0.5 / e + 0.05, "train_median_rel_err": 0.4 / e + 0.03, "train_loss": 1.0 / e, "val_loss": 1.2 / e}
        for l in range(1, n_hidden + 1):
            r[f"grad_norm_{l}"] = (0.0 if ylog_bad and e == 2 else 10.0 ** (-l) / e)
            r[f"saturation_{l}"], r[f"dead_{l}"] = 0.1 * l, 0.02 * l
        out.append(r)
    return out


lr_rows = fake_rows(12)
le = cd.live_error(lr_rows, 40, 0.075)
assert [s["name"] for s in le["series"]] == ["Validation", "Training"] and all(len(s["points"]) == 12 for s in le["series"]) and le["y0"] and le["xint"]
assert abs(le["series"][0]["points"][0][1] - 55.0) < 1e-9 and abs(le["hlines"][0][0] - 7.5) < 1e-9 and "7.5" in le["hlines"][0][1]
assert le["spans"] == [(12.0, 40.0, "")], "the epochs still to come are shaded and the axis runs to the last epoch"
assert cd.live_error(fake_rows(40), 40)["spans"] == [] and cd.live_error(lr_rows, None)["spans"] == []
assert cd.live_error([], 40)["empty"] and not cd.live_error(lr_rows, 40)["empty"]
ok("live error chart: validation and training error in percent, the target as a line, the epochs still to come shaded; nothing yet says so in a sentence")

lg = cd.live_grad(lr_rows, 40, 3)
assert lg["ylog"] and [s["name"] for s in lg["series"]] == ["Hidden 1", "Hidden 3"] and lg["series"][1]["dash"] and not lg["series"][0]["dash"]
assert lg["series"][0]["points"][0][1] > lg["series"][1]["points"][0][1], "the gradient of the last hidden layer is the smaller one here"
assert [s["name"] for s in cd.live_grad(lr_rows, 40, 1)["series"]] == ["Hidden 1"], "one hidden layer: one line"
holes = cd.live_grad(fake_rows(5, ylog_bad=True), 40, 3)
assert all(len(s["points"]) == 4 for s in holes["series"]), "a zero cannot be drawn on a log axis: that epoch is left out, the rest is kept"
assert cd.live_grad([], 40, 3)["empty"] and cd.live_grad([{"epoch": 1}], 40, 3)["empty"] == "No gradient numbers yet."
ok("live gradient chart: first and last hidden layer on a log axis, zeros left out, one line for a network with one hidden layer")

lu = cd.live_units(lr_rows, 40, 3)
assert [s["name"] for s in lu["series"]] == ["Saturated", "Dead"] and lu["series"][1]["dash"]
assert abs(lu["series"][0]["points"][0][1] - 20.0) < 1e-9 and abs(lu["series"][1]["points"][0][1] - 4.0) < 1e-9, "the mean over the hidden layers, in percent"
assert cd.live_units([], 40, 3)["empty"] and lu["spans"] == [(12.0, 40.0, "")]
assert all(len(s["points"]) == 12 for s in lu["series"])
ok("live units chart: saturated and dead units as the mean over the hidden layers, in percent")

print("chart data ok", flush=True)
