import faulthandler; faulthandler.dump_traceback_later(290, exit=True)
"""train_nn_job.py, run the way the Trainer runs it (a background process with a job.json) on a frozen copy of made-up pictures seen by a pinhole camera: one rung with several learning
rates and seeds, a learning rate that blows up (counted, not dropped), the whole ladder, the deep demonstrations, the run folder and what is in it, the model file answering what the
predictions file says, the same seed giving the same numbers, and the plain messages for settings and data that cannot be used."""
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

import dist_data as dd
import dist_models as dm
import eval_harness as eh
import np_net as nn

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


def table(path):
    return list(csv.DictReader(open(path)))


yaml_path, n_tr = frozen_copy(os.path.join(TMP, "frozen"), 220, 90, 1)
train, val = dd.load_boxes(yaml_path, "train"), dd.load_boxes(yaml_path, "val")

# ---------------------------------------------------------------- one rung, two learning rates, two seeds
P = {"seeds": 2, "lrs": [0.003, 0.01], "epochs": 30, "n_boot": 200}
run, models, r = run_job("rung6", yaml_path, P, size="6", dist_train=n_tr)
assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
res = json.load(open(os.path.join(run, "result.json")))
assert res["ok"] and res["kind"] == "nn_ladder" and res["best_variant"] == "rung6" and res["runs"] == 4 and res["diverged"] == 0 and not res["failed"], res
assert "Recordings     : 8 in training, 3 in validation" in r.stdout and "the formula k / height" in r.stdout and "The learning rate of each rung is the one with" in r.stdout, r.stdout[:1500]
ok("the job runs as a background process, trains 2 learning rates x 2 seeds of rung 6 and writes result.json")

runs = table(os.path.join(run, "results.csv"))
assert len(runs) == 4 and {(x["lr"], x["seed"]) for x in runs} == {("0.003", "0"), ("0.003", "1"), ("0.01", "0"), ("0.01", "1")}
assert sum(x["chosen"] == "yes" for x in runs) == 1 and all(x["diverged"] == "False" and x["epochs_run"] == "30" and float(x["median_rel_err"]) < 0.25 for x in runs), runs
sweep = table(os.path.join(run, "lr_sweep.csv"))
assert [x["lr"] for x in sweep] == ["0.003", "0.01"] and all(x["seeds"] == "2" and x["diverged"] == "0" for x in sweep)
rungs = table(os.path.join(run, "rungs.csv"))
assert [x["rung"] for x in rungs] == ["rung6", "formula"] and rungs[0]["seeds"] == "2" and float(rungs[0]["seed_min"]) <= float(rungs[0]["seed_median"]) <= float(rungs[0]["seed_max"])
assert float(rungs[0]["median_rel_err_lo"]) <= float(rungs[0]["median_rel_err"]) <= float(rungs[0]["median_rel_err_hi"])
paired = table(os.path.join(run, "paired.csv"))
assert [(x["variant"], x["versus"]) for x in paired] == [("rung6", "formula")]
chosen = [x for x in runs if x["chosen"] == "yes"][0]
assert chosen["lr"] == rungs[0]["lr"] and min(sweep, key=lambda x: float(x["median_rel_err"]))["lr"] == chosen["lr"], "the learning rate of the lowest median error is the one chosen"
ok("results.csv has a row per run, lr_sweep.csv a row per learning rate, rungs.csv the chosen rate with the formula beside it, paired.csv the difference from the formula")

# a curve
curve = table(os.path.join(run, chosen["curve"]))
assert [int(x["epoch"]) for x in curve] == list(range(1, 31))
need = {"train_loss", "val_loss", "val_median_rel_err", "val_within20", "lr", "momentum", "grad_norm_1", "grad_norm_3", "update_ratio_1", "weight_norm_2", "saturation_1", "dead_2", "epoch_seconds"}
assert need <= set(curve[0]), need - set(curve[0])
assert float(curve[-1]["train_loss"]) < float(curve[0]["train_loss"]) and abs(float(curve[-1]["val_median_rel_err"]) - float(chosen["median_rel_err"])) < 1e-6
ok("every epoch of every run is in its curve file, with the quantities of the specification")

# the result file of the chosen run, and the model
rj = json.load(open(os.path.join(run, "variants", "rung6", "result.json")))
for key in ("arm", "variant", "seed", "split", "n", "metrics", "ci95", "config", "env", "train_rows", "train_seconds", "across_seeds", "n_seeds", "n_diverged", "lr", "selection", "epochs_to_target"):
    assert key in rj, key
assert rj["arm"] == "3" and rj["variant"] == "rung6" and rj["n_seeds"] == 2 and rj["config"]["optimizer"] == "adam" and rj["config"]["hidden"] == [32, 16] and rj["across_seeds"]["n"] == 2
assert rj["n"] == len(val) and rj["train_rows"] == len(train) and abs(rj["metrics"]["median_rel_err"] - float(chosen["median_rel_err"])) < 1e-5
preds = table(os.path.join(run, "variants", "rung6", "predictions.csv"))
model = dm.load(os.path.join(run, "models", "rung6" + dm.EXT))
assert model.family == "mlp" and model.id == "3" and model.n_params() == 769
again = model.predict_boxes(val)
assert np.allclose(again, [float(p["predicted_m"]) for p in preds], atol=1e-3) and len(preds) == len(val)
assert abs(eh.median_rel_err(again, val.dist) - rj["metrics"]["median_rel_err"]) < 1e-3
ok(f"the result file follows the schema; the saved network, read back from its file, answers what predictions.csv says (769 parameters, {rj['metrics']['median_rel_err'] * 100:.1f}% median error)")

# a network answers from raw boxes in the original picture too (what a detector hands over)
xyxy = np.array([[300.0, 100.0, 340.0, 200.0]])
assert 0.2 <= float(model.predict_m_orig(xyxy, 640, 480)[0]) <= 60.0
ok("the model answers a box of the original picture (what a detector hands over)")

# saved in the project, not in the Annotator's folders
saved = os.listdir(os.path.join(models, "Distance"))
assert len(saved) == 1 and saved[0].startswith("mlp_rung6_") and saved[0].endswith(dm.EXT) and not os.path.exists(os.path.join(models, "Assist")) and not os.path.exists(os.path.join(models, "Scratch"))
ok("the model is saved in the project's Distance folder and in no other models folder")

# the same seed, the same numbers
run2, _m, r2 = run_job("rung6_again", yaml_path, P, size="6", dist_train=n_tr)
a, b = table(os.path.join(run, "results.csv")), table(os.path.join(run2, "results.csv"))
assert [(x["lr"], x["seed"], x["median_rel_err"], x["final_train_loss"]) for x in a] == [(x["lr"], x["seed"], x["median_rel_err"], x["final_train_loss"]) for x in b]
ok("a second run with the same settings gives the same numbers to the last digit")

# ---------------------------------------------------------------- a learning rate that blows up is counted
run3, m3, r3 = run_job("diverge", yaml_path, {"lrs": [8.0, 0.1], "seeds": 2, "epochs": 10, "n_boot": 100}, size="0", dist_train=n_tr)
assert r3.returncode == 0, r3.stdout[-800:] + r3.stderr[-800:]
res3 = json.load(open(os.path.join(run3, "result.json")))
runs3 = table(os.path.join(run3, "results.csv"))
bad = [x for x in runs3 if x["lr"] == "8"]
assert len(runs3) == 4 and len(bad) == 2 and all(x["diverged"] == "True" and x["diverged_epoch"] and x["median_rel_err"] == "" for x in bad), runs3
assert res3["runs"] == 4 and res3["diverged"] == 2 and "DIVERGED" in r3.stdout and "2 of 4 runs diverged" in r3.stdout
sw = {x["lr"]: x for x in table(os.path.join(run3, "lr_sweep.csv"))}
assert sw["8"]["diverged"] == "2" and sw["8"]["median_rel_err"] == "" and sw["0.1"]["diverged"] == "0"
assert table(os.path.join(run3, "rungs.csv"))[0]["lr"] == "0.1"
curve = table(os.path.join(run3, bad[0]["curve"]))
assert len(curve) == int(bad[0]["epochs_run"]) <= 5, "a diverged run stops at once and its curve is kept"
ok(f"a learning rate that is too high gives diverged runs: they are in the table, in the counts and in the log, not left out (diverged at epoch {bad[0]['diverged_epoch']})")

run4, m4, r4 = run_job("alldiverge", yaml_path, {"lrs": [8.0], "epochs": 10}, size="0", dist_train=n_tr)
res4 = json.load(open(os.path.join(run4, "result.json")))
assert r4.returncode == 1 and not res4["ok"] and "diverged" in res4["message"]
ok("when every run of every rung diverges the job says so and stops with a failure (nothing is saved)")

# ---------------------------------------------------------------- the whole ladder
run5, m5, r5 = run_job("ladder", yaml_path, {"epochs": 3, "n_boot": 100}, size="ladder", dist_train=n_tr)
assert r5.returncode == 0, r5.stdout[-800:] + r5.stderr[-800:]
rungs5 = table(os.path.join(run5, "rungs.csv"))
assert [x["rung"] for x in rungs5] == [f"rung{k}" for k in range(9)] + ["formula"]
pr = table(os.path.join(run5, "paired.csv"))
assert len(pr) == 9 + 8 and [(x["variant"], x["versus"]) for x in pr if x["versus"] != "formula"] == [(f"rung{k}", f"rung{k - 1}") for k in range(1, 9)]
assert len(os.listdir(os.path.join(m5, "Distance"))) == 9 and len(os.listdir(os.path.join(run5, "models"))) == 9
cfgs = {k: json.load(open(os.path.join(run5, "variants", f"rung{k}", "result.json")))["config"] for k in range(9)}
assert cfgs[0]["activation"] == "sigmoid" and cfgs[0]["optimizer"] == "sgd" and cfgs[6]["optimizer"] == "adam" and cfgs[7]["batch_norm"] and cfgs[8]["early_stopping"] and cfgs[8]["optimizer"] == "adamw"
ok("the ladder trains the nine rungs in order with the settings of each, saves nine models, and pairs every rung with the one before and with the formula")

# the learning-rate grid
run6, m6, r6 = run_job("grid", yaml_path, {"lrs": "grid", "epochs": 2, "n_boot": 50}, size="6", dist_train=n_tr)
assert r6.returncode == 0 and len(table(os.path.join(run6, "lr_sweep.csv"))) == 5 and len(table(os.path.join(run6, "results.csv"))) == 5
run7, m7, r7 = run_job("grid_sgd", yaml_path, {"lrs": "grid", "epochs": 2, "n_boot": 50}, size="1", dist_train=n_tr)
assert r7.returncode == 0 and len(table(os.path.join(run7, "lr_sweep.csv"))) == 8
ok("lrs = grid runs the specification's grid: 5 learning rates for Adam, 8 for gradient descent")

# the deep demonstrations
run8, m8, r8 = run_job("demo", yaml_path, {"epochs": 4, "n_boot": 50}, size="demo_sigmoid", dist_train=n_tr)
assert r8.returncode == 0, r8.stdout[-600:] + r8.stderr[-600:]
mod8 = dm.load(os.path.join(run8, "models", "demo_sigmoid" + dm.EXT))
assert mod8.cfg["hidden"] == [32] * 8 and mod8.n_params() == nn.count_params(train.X().shape[1], [32] * 8)
cur8 = table(os.path.join(run8, "runs", "demo_sigmoid", "lr0.03_s0", "curve.csv"))
assert "grad_norm_9" in cur8[0] and "grad_norm_1" in cur8[0] and "saturation_8" in cur8[0], "a gradient norm per layer, for the 8 hidden layers and the output"
ok("a deep demonstration has 8 hidden layers and logs the gradient of every layer (the picture of a vanishing gradient)")

# settings replaced
run9, m9, r9 = run_job("override", yaml_path, {"epochs": 3, "n_boot": 50, "activation": "silu", "hidden": [8, 8, 8], "batch": 64}, size="5", dist_train=n_tr)
assert r9.returncode == 0, r9.stdout[-600:]
c9 = json.load(open(os.path.join(run9, "variants", "rung5", "result.json")))
assert c9["config"]["activation"] == "silu" and c9["config"]["hidden"] == [8, 8, 8] and c9["config"]["batch"] == 64 and c9["overrides"]["activation"] == "silu" and c9["parameters"] == nn.count_params(train.X().shape[1], [8, 8, 8])
ok("a setting of a rung can be replaced (activation, widths, batch) and the result file says which")

# ---------------------------------------------------------------- what cannot be done
run10, m10, r10 = run_job("badsize", yaml_path, {}, size="rung9", dist_train=n_tr)
assert r10.returncode == 1 and "Unknown rung" in json.load(open(os.path.join(run10, "result.json")))["message"]
empty_yaml, _n = frozen_copy(os.path.join(TMP, "nodist"), 30, 12, 2, with_distances=False)
run11, m11, r11 = run_job("nodist", empty_yaml, {"epochs": 2}, size="6", dist_train=0)
assert r11.returncode == 1 and "None of the training boxes has a distance" in json.load(open(os.path.join(run11, "result.json")))["message"]
run12, m12, r12 = run_job("badopt", yaml_path, {"epochs": 2, "optimizer": "lbfgs"}, size="6", dist_train=n_tr)
assert r12.returncode == 1 and json.load(open(os.path.join(run12, "result.json")))["ok"] is False
ok("a rung that does not exist, a copy without distances and an optimiser that does not exist each stop with a message and a failed result")

print("nn job ok", flush=True)
