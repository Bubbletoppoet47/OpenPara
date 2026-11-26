import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
"""train_classical_job.py, run the way the Trainer runs it (a background process with a job.json): a frozen training copy of made-up pictures seen by a pinhole camera is read, the formula
and the four regressors are fitted on the training boxes and scored on the validation boxes with the shared harness, and the run folder gets what the specification asks for (results.csv, paired
differences, one result file per variant, predictions per box, the models, result.json).  Also: what happens with no distances, with a variant that is not known, with a package that is
missing, and that nothing is put in the Annotator's Models folder."""
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


def run_job(name, data_yaml, params=None, size="all", dist_train=None):
    run = os.path.join(TMP, "run_" + name)
    os.makedirs(run)
    models = os.path.join(TMP, "run_" + name + "_models")
    os.makedirs(models)
    job = {"data_yaml": data_yaml, "run_dir": run, "type": "classical_regress", "size": size, "imgsz": 640, "classes": ["person"], "models_dirs": [models], "trainer": "Tester",
           "lib_dir": ANN, "dist_counts": {"train": dist_train, "val": 0}, "params": params or {}}
    jp = os.path.join(run, "job.json")
    json.dump(job, open(jp, "w"))
    r = subprocess.run([sys.executable, "-u", os.path.join(TR, "train_classical_job.py"), jp], capture_output=True, text=True, timeout=250, cwd=run)
    return run, models, r


FAST = {"folds": 3, "n_boot": 200, "gp_max_rows": 300, "gp_restarts": 0, "boosting_learning_rates": [0.1], "boosting_depths": [2, 3], "boosting_max_iter": 60}
yaml_path, n_tr = frozen_copy(os.path.join(TMP, "frozen"), 220, 90, 1)
run, models, r = run_job("all", yaml_path, FAST, dist_train=n_tr)
log = r.stdout
assert r.returncode == 0, r.stdout + r.stderr
assert "Training       :" in log and "2 distorted copies" not in log and "distorted copies of pictures" in log, log[:600]
assert "Recordings     : 8 in training, 3 in validation" in log and "Cross-validation is grouped by recording" in log, log[:800]
res = json.load(open(os.path.join(run, "result.json")))
assert res["ok"] and res["kind"] == "classical_regress" and set(m["variant"] for m in res["models"]) == {"pinhole", "loglinear", "knn", "boosting", "gp"}, res
assert res["best_variant"] in dm.FAMILIES and res["info"]["dist_median_err"] < 0.08 and not res["failed"], res
ok("the job runs as a background process: it reads the frozen copy (original pictures only), prints the input check, fits five variants and writes result.json")

# the run folder
rows = list(csv.DictReader(open(os.path.join(run, "results.csv"))))
assert [x["variant"] for x in rows] == ["pinhole", "loglinear", "knn", "boosting", "gp"] and [x["id"] for x in rows] == ["2a", "2b", "2c", "2d", "2e"]
assert list(rows[0]) == ["variant", "id", "median_rel_err", "median_rel_err_lo", "median_rel_err_hi", "within20", "within20_lo", "within20_hi", "mae_m", "mae_m_lo", "mae_m_hi", "signed_bias", "parameters", "fit_seconds"]
for x in rows:
    assert float(x["median_rel_err_lo"]) <= float(x["median_rel_err"]) <= float(x["median_rel_err_hi"]) and float(x["median_rel_err"]) < 0.08, x
paired = list(csv.DictReader(open(os.path.join(run, "paired.csv"))))
assert [x["variant"] for x in paired] == ["loglinear", "knn", "boosting", "gp"] and all(x["versus"] == "pinhole" for x in paired)
for v in ("pinhole", "loglinear", "knn", "boosting", "gp"):
    rj = json.load(open(os.path.join(run, "variants", v, "result.json")))
    for key in ("arm", "variant", "seed", "split", "n", "metrics", "ci95", "config", "env", "train_rows", "train_seconds"):
        assert key in rj, (v, key)
    assert rj["arm"] == "2" and rj["variant"] == v and rj["split"] == "validation" and rj["grouped_bootstrap"] is True and rj["env"]["numpy"]
    preds = list(csv.DictReader(open(os.path.join(run, "variants", v, "predictions.csv"))))
    assert len(preds) == rj["n"] and list(preds[0]) == ["image", "class", "labelled_m", "predicted_m"]
    m = dm.load(os.path.join(run, "models", v + dm.EXT), trust_pickle=True)
    assert m.family == v
    assert rj["metrics"]["median_rel_err"] == eh.median_rel_err(np.array([float(p["predicted_m"]) for p in preds]), np.array([float(p["labelled_m"]) for p in preds])) or \
        abs(rj["metrics"]["median_rel_err"] - eh.median_rel_err(np.array([float(p["predicted_m"]) for p in preds]), np.array([float(p["labelled_m"]) for p in preds]))) < 1e-3
ok("the run folder has results.csv, paired.csv, a result file, the predictions of every validation box and the model of each variant; the files agree with each other")

pin = json.load(open(os.path.join(run, "variants", "pinhole", "result.json")))
assert pin["config"]["seed"] == 0 and pin["train_rows"] == len(dd.load_boxes(yaml_path, "train")) and pin["n"] == len(dd.load_boxes(yaml_path, "val"))
gp = json.load(open(os.path.join(run, "variants", "gp", "result.json")))
assert set(gp["calibration"]) == {"0.68", "0.95"} and "lidar_returns" in gp and "0-2" in gp["spread_by_range"] and gp["model_info"]["rows"] <= 300 and gp["model_info"]["subsampled_from"] == pin["train_rows"]
ll = json.load(open(os.path.join(run, "variants", "loglinear", "result.json")))
b = list(ll["model_info"]["coefficients"].values())[1]
assert abs(b + 1.0) < 0.1, b
ok(f"the Gaussian process reports its calibration and its spread by range, the log-linear model its coefficients (b = {b:.3f})")

# saved in the project, not in the Annotator's folder
saved = os.listdir(os.path.join(models, "Distance"))
assert len(saved) == 5 and all(f.endswith(dm.EXT) for f in saved), saved
assert not os.path.exists(os.path.join(models, "Assist")) and not os.path.exists(os.path.join(models, "Scratch")), os.listdir(models)
assert len(res["saved"]) == 5 and all(os.path.isfile(p) for p in res["saved"])
ok("the models are saved in the project's Distance folder, and in no other models folder")

# what the Trainer reads when only one variant is asked for, and the same seed gives the same numbers
run2, _m2, r2 = run_job("only_gp", yaml_path, FAST, size="gp", dist_train=n_tr)
res2 = json.load(open(os.path.join(run2, "result.json")))
assert r2.returncode == 0 and [m["variant"] for m in res2["models"]] == ["gp"] and not os.path.exists(os.path.join(run2, "paired.csv"))
gp2 = json.load(open(os.path.join(run2, "variants", "gp", "result.json")))
assert gp2["metrics"] == gp["metrics"] and gp2["ci95"] == gp["ci95"], "the same seed gives the same numbers"
run3, _m3, r3 = run_job("seed5", yaml_path, dict(FAST, seed=5), size="knn", dist_train=n_tr)
assert json.load(open(os.path.join(run3, "variants", "knn", "result.json")))["seed"] == 5
ok("one variant on its own works; a run is reproduced exactly by its seed")

# plain failures
empty_yaml, _n = frozen_copy(os.path.join(TMP, "nodist"), 30, 12, 2, with_distances=False)
run4, _m4, r4 = run_job("nodist", empty_yaml, FAST, dist_train=0)
res4 = json.load(open(os.path.join(run4, "result.json")))
assert r4.returncode == 1 and not res4["ok"] and "None of the training boxes has a distance" in res4["message"], res4
run5, _m5, r5 = run_job("badvariant", yaml_path, FAST, size="forest")
assert r5.returncode == 1 and "Unknown distance model" in json.load(open(os.path.join(run5, "result.json")))["message"]
ok("a copy without distances stops with a plain message; so does a variant that does not exist")

# a package that is missing
sys.path.insert(0, TR)
import importlib.util
import train_classical_job as tcj
real = importlib.util.find_spec
importlib.util.find_spec = lambda name, *a, **k: None if name in ("sklearn", "scipy") else real(name, *a, **k)
try:
    assert tcj.needs_missing("pinhole") == [] and tcj.needs_missing("knn") == []
    assert tcj.needs_missing("boosting") == ["scikit-learn"] and set(tcj.needs_missing("gp")) == {"scikit-learn", "scipy"}
finally:
    importlib.util.find_spec = real
ok("a variant whose package is missing is named as such (the others do not need it)")

print("classical job ok", flush=True)
