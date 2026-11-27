import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
"""train_nn_job.py, the part the Trainer window watches: live.json (the list of runs with their state and the curves of the run that is going, written while it trains) and the
stop_after_run flag (finish the run that is going, start no other, make the model from the runs that finished).  The job is run the way the Trainer runs it, a background
process with a job.json, on a frozen copy of made-up pictures.
python test_nn_live.py"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
ANN, TR = os.path.join(ADD, "annotator", "app"), os.path.join(ADD, "trainer")
sys.path.insert(0, TR)
import cv2
import numpy as np

import dist_models as dm
import trainer_core as tc

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


def start_job(name, data_yaml, params, dist_train, flag_first=False):
    run = os.path.join(TMP, "run_" + name)
    os.makedirs(run)
    models = os.path.join(TMP, "run_" + name + "_models")
    os.makedirs(models)
    job = {"data_yaml": data_yaml, "run_dir": run, "type": "nn_ladder", "size": "6", "imgsz": 640, "classes": ["person"], "models_dirs": [models], "trainer": "Tester",
           "lib_dir": ANN, "dist_counts": {"train": dist_train, "val": 0}, "params": params}
    jp = os.path.join(run, "job.json")
    json.dump(job, open(jp, "w"))
    if flag_first:
        asker(run)()
    p = subprocess.Popen([sys.executable, "-u", os.path.join(TR, "train_nn_job.py"), jp], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=run)
    return p, run, models


def asker(run):
    """What the window does when the person presses Stop once: Job.stop_after_run on a job that has this run folder."""
    stub = types.SimpleNamespace(run_dir=run, stop=lambda: None, STOP_AFTER_FILE=tc.Job.STOP_AFTER_FILE)
    return lambda: tc.Job.stop_after_run(stub)


def live_of(run):
    try:
        with open(os.path.join(run, "live.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None                                    # (not there yet, or caught between two writes: the window draws the old picture)


yaml_path, n_tr = frozen_copy(os.path.join(TMP, "frozen"), 220, 90, 1)

# ---------------------------------------------------------------- a whole run: live.json from the first second to the last
P = {"seeds": 1, "lrs": [0.003, 0.01], "epochs": 400, "n_boot": 50}
p, run, models = start_job("whole", yaml_path, P, n_tr)
seen, snaps = [], []
while p.poll() is None:
    d = live_of(run)
    if d:
        snaps.append(d)
    time.sleep(0.03)
out = p.stdout.read()
assert p.returncode == 0, out[-1500:]
last = live_of(run)
snaps.append(last)
assert last["version"] == 1 and last["epochs"] == 400 and last["n_hidden"] == 2 and last["target_err"] > 0, last
assert [(x["tag"], x["rung"], x["lr"], x["seed"]) for x in last["runs"]] == [("lr0.003_s0", "rung6", 0.003, 0), ("lr0.01_s0", "rung6", 0.01, 0)], last["runs"]
assert [x["status"] for x in last["runs"]] == ["done", "done"] and all(x["epoch"] == 400 and x["val_err"] is not None and 0 < x["val_err"] < 1 for x in last["runs"]), last["runs"]
ok("live.json is there when the job starts, and at the end it lists every run as done, with its learning rate, seed, epochs and validation error")

first = snaps[0]
assert first["version"] == 1 and len(first["runs"]) == 2 and {x["status"] for x in first["runs"]} <= {"queued", "running", "done"}
states = [tuple(x["status"] for x in d["runs"]) for d in snaps]
assert ("running", "queued") in states, "the first run was seen going while the second waited"
mid = [d for d in snaps if d["runs"][0]["status"] == "running" and 0 < d["runs"][0]["epoch"] < 400]
assert mid, "an epoch between the first and the last was seen while the job went"
rows = mid[-1]["current"]["rows"]
assert rows and [r["epoch"] for r in rows] == list(range(1, len(rows) + 1)), "the rows of the run that is going are its epochs in order"
assert {"epoch", "val_median_rel_err", "train_median_rel_err", "train_loss", "val_loss", "grad_norm_1", "grad_norm_3", "saturation_1", "dead_2"} <= set(rows[-1]), set(rows[-1])
assert all(isinstance(v, (int, float)) or v is None for r in rows for v in r.values())
ok("while a run goes, live.json has its epochs so far with the error of both sets, the loss, and the gradient, saturation and dead units of each layer")

res = json.load(open(os.path.join(run, "result.json")))
assert res["ok"] and res["runs"] == 2 and res.get("stopped_early") is None and res.get("planned") == 2, res
ok("a job that ends by itself has no stopped_early in its result")

# ---------------------------------------------------------------- Stop pressed once: the run that is going finishes, no other starts, the model is made
P = {"seeds": 1, "lrs": [0.003, 0.01, 0.03], "epochs": 300, "n_boot": 50}
p, run, models = start_job("stopafter", yaml_path, P, n_tr)
ask, asked = asker(run), None
while p.poll() is None:
    d = live_of(run)
    if d and asked is None and [x["status"] for x in d["runs"]][:2] == ["done", "running"] and d["runs"][1]["epoch"] >= 1:
        ask()
        asked = d["runs"][1]["epoch"]
    time.sleep(0.02)
out = p.stdout.read()
assert asked is not None, "the second run was seen going"
assert p.returncode == 0, out[-1500:]
assert os.path.exists(os.path.join(run, "stop_after_run"))
last = live_of(run)
assert [x["status"] for x in last["runs"]] == ["done", "done", "skipped"], last["runs"]
assert last["runs"][1]["epoch"] == 300, "the run that was going ran to its last epoch"
res = json.load(open(os.path.join(run, "result.json")))
assert res["ok"] and res["runs"] == 2 and res["stopped_early"] == 2 and res["planned"] == 3, res
assert "Stopped after the run that was going: 2 of 3 runs finished" in out, out[-900:]
assert len(list(csv.DictReader(open(os.path.join(run, "results.csv"))))) == 2
assert os.path.isfile(os.path.join(run, "models", "rung6" + dm.EXT)), os.listdir(os.path.join(run, "models"))
ok("Stop pressed once: the run that was going finishes all its epochs, the third is skipped, and the model is made from the two (stopped_early 2 of 3 in the result)")

# ---------------------------------------------------------------- Stop before anything finished
p, run, models = start_job("stopfirst", yaml_path, {"seeds": 1, "lrs": [0.003, 0.01], "epochs": 5}, n_tr, flag_first=True)
out = p.communicate(timeout=120)[0]
assert p.returncode == 1, out[-800:]
res = json.load(open(os.path.join(run, "result.json")))
assert res["ok"] is False and "Stopped before any run had finished" in res["message"], res
assert [x["status"] for x in live_of(run)["runs"]] == ["skipped", "skipped"]
ok("a stop asked before any run began ends with a plain message and no model, and the runs are marked skipped")

# ---------------------------------------------------------------- the window's side: the flag file
stub_run = os.path.join(TMP, "stub")
os.makedirs(stub_run)
asker(stub_run)()
assert os.path.isfile(os.path.join(stub_run, tc.Job.STOP_AFTER_FILE)) and tc.Job.STOP_AFTER_FILE == "stop_after_run"
bad = types.SimpleNamespace(run_dir=os.path.join(TMP, "no", "such", "dir"), stop=lambda: calls.append("stop"), STOP_AFTER_FILE=tc.Job.STOP_AFTER_FILE)
calls = []
tc.Job.stop_after_run(bad)
assert calls == ["stop"], "when the flag cannot be written the job is stopped the old way"
ok("Job.stop_after_run writes the flag in the run folder, and stops the job outright when it cannot")

print("nn live ok", flush=True)
