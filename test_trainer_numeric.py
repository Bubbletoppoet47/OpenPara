import faulthandler; faulthandler.dump_traceback_later(290, exit=True)
"""Trainer, the two distance-only model types (a formula and four regressors; a small neural network): they are offered next to the YOLO types, need only numpy (no torch, no
ultralytics, no GPU), train on the originals of the frozen copy whatever the distortion settings say, are never continued from a model, take their settings from the project,
are saved as .opdm files in models/Distance (and not in the Annotator's Models folder), and are listed, exported, imported and removed like the other models."""
import os, sys, tempfile, time, json, csv
HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
TMP = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(TMP, "user")
CORE = os.path.join(HERE, "core") if os.path.isdir(os.path.join(HERE, "core")) else HERE
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
ANN = os.path.join(ADD, "annotator", "app")
TR = os.path.join(ADD, "trainer")
for p in (CORE, ANN, TR):
    sys.path.insert(0, p)
import numpy as np, cv2
import annotator_core as ac, dataset_zip as dz
import trainer_core as tc
import dist_models as dm

ME = {"id": "me123", "name": "Tester"}
W, H, K = 320, 240, 200.0                      # a made-up camera: distance in metres = K / height of the object in pixels


def ok(msg):
    print("ok:", msg, flush=True)


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


def wait(job, secs=200):
    t0 = time.time()
    while job.poll() is None and time.time() - t0 < secs:
        time.sleep(0.3)
    assert job.poll() is not None, "the job did not finish: " + job.read_log()[-800:]
    return job.poll(), job.result()


# ---------------------------------------------------------------- the types
types = tc.model_types()
assert list(types)[:2] == ["yolo", "yolo_distance"] and "classical_regress" in types and "nn_ladder" in types
for k in ("classical_regress", "nn_ladder"):
    sp = types[k]
    assert sp["numpy_only"] and sp["distance"] and not sp["distortions"] and not sp["continue"] and sp["models_key"] == "distance" and sp["default_size"] in sp["sizes"]
    assert all(s in sp["size_names"] for s in sp["sizes"]), k
assert types["classical_regress"]["sizes"][0] == "all" and "gp" in types["classical_regress"]["sizes"] and types["nn_ladder"]["default_size"] == "6" and "ladder" in types["nn_ladder"]["sizes"]
assert types["yolo"].get("numpy_only") is None and types["yolo"].get("distortions", True) and types["yolo"].get("continue", True)
assert tc.DEFAULTS["model"]["params"] == {}
ok("the two distance-only types are offered after the YOLO types; each says it needs numpy only, makes no distortions, cannot be continued and saves in Distance")

# ---------------------------------------------------------------- what the training Python needs
good = {"python": "py", "torch": None, "ultralytics": None, "numpy_version": "2.1", "sklearn_version": "1.5", "scipy_version": "1.14", "problems": ["torch is not installed ..."], "warnings": [], "started": True}
pr, wa = tc.env_problems(good, types["classical_regress"])
assert pr == [] and wa == [], (pr, wa)
assert tc.env_problems(good, types["yolo"])[0] == good["problems"], "the YOLO types still need torch"
nosk = dict(good, sklearn_version=None, scipy_version=None)
pr, wa = tc.env_problems(nosk, types["classical_regress"])
assert pr == [] and len(wa) == 1 and "scikit-learn and scipy are not installed" in wa[0] and "pip install scikit-learn scipy" in wa[0]
assert tc.env_problems(nosk, types["nn_ladder"]) == ([], []), "the network needs neither"
nonp = dict(good, numpy_version=None)
assert "numpy is not installed" in tc.env_problems(nonp, types["nn_ladder"])[0][0]
dead = dict(good, started=False, problems=["Python for training could not be started (py). Set OPARA_TRAIN_PYTHON ..."])
assert "could not be started" in tc.env_problems(dead, types["nn_ladder"])[0][0]
text = tc.env_text(good, types["nn_ladder"])
assert "numpy 2.1" in text and "scikit-learn 1.5" in text and "torch" not in text.lower()
ok("a distance-only type needs numpy and nothing else (scikit-learn and scipy are a warning for the two variants that use them); the YOLO types still need torch")

info = tc.check_env(sys.executable)                    # the real probe reports the three packages without importing them
assert info["started"] and info["numpy_version"] and ("sklearn_version" in info) and ("scipy_version" in info)
assert tc.env_problems(info, types["classical_regress"])[0] == []
ok(f"the real probe of this Python: numpy {info['numpy_version']}, scikit-learn {info['sklearn_version']}, scipy {info['scipy_version']}")

# ---------------------------------------------------------------- a run of each type
tp = project("Num", [recording("a", 12, 1, "ra"), recording("b", 12, 2, "rb"), recording("c", 12, 3, "rc"), recording("d", 10, 4, "rd")], "rd")
tp.set_settings({"distortions": {"enabled": True, "count": 2}, "model": {"type": "classical_regress", "size": "all", "epochs": 100, "continue_from": "/nowhere/old.pt"}})
job = tp.start_run("Tester", python=sys.executable)
spec_job = json.load(open(os.path.join(job.run_dir, "job.json")))
assert spec_job["type"] == "classical_regress" and spec_job["size"] == "all" and spec_job["models_key"] == "distance" and spec_job["start_weights"] is None and spec_job["params"] == {}
ds = os.path.join(job.run_dir, "dataset", "images", "train")
assert os.listdir(ds) and not any("_dist" in f for f in os.listdir(ds)), "no distorted copies for a distance-only model, though distortions are switched on"
code, res = wait(job)
log = open(job.log_path, encoding="utf-8").read()
assert code == 0 and res and res["ok"] and res["kind"] == "classical_regress", log[-1500:]
assert "Traceback" not in log and "torch" not in log.lower().replace("no torch", ""), log[-800:]
assert len(res["saved"]) >= 2 and all(p.startswith(tp.distance_dir()) for p in res["saved"]), res["saved"]
assert not os.path.exists(os.path.join(tc.annotator_models_dir(), "Scratch")) and not os.path.exists(os.path.join(tc.annotator_models_dir(), "Assist")), "nothing in the Annotator's Models folder"
ok(f"a Classical run starts, makes no distorted copies, ignores a model to continue from, trains in the background without torch and saves {len(res['saved'])} models in models/Distance")

lst = tp.list_models()
dist = [v for v in lst if v.get("kind") == "distance"]
assert len(dist) == len(res["saved"]) and len(lst) == len(dist)
assert all(v["file"].endswith(".opdm") and v["family"] in dm.FAMILIES and v["scores"] and "dist_median_err" in v["scores"] and v["classes"] == ["crate", "ball"] for v in dist), dist[:1]
ok("the project lists them next to its other models, with the family, the classes and the scores")

# the second type, with the settings of the window
tp.set_settings({"model": {"type": "nn_ladder", "size": "6", "epochs": 8, "params": {"seeds": 2, "lrs": [0.003, 0.01], "n_boot": 100}}})
job2 = tp.start_run("Tester", python=sys.executable)
j2 = json.load(open(os.path.join(job2.run_dir, "job.json")))
assert j2["type"] == "nn_ladder" and j2["params"] == {"seeds": 2, "lrs": [0.003, 0.01], "n_boot": 100} and j2["epochs"] == 8
code2, res2 = wait(job2)
assert code2 == 0 and res2["ok"] and res2["kind"] == "nn_ladder" and res2["runs"] == 4, open(job2.log_path, encoding="utf-8").read()[-1200:]
rs = list(csv.DictReader(open(os.path.join(job2.run_dir, "results.csv"))))
assert len(rs) == 4 and all(r["epochs_run"] == "8" for r in rs), "the epochs of the window are the epochs of the network"
assert len(tp.list_distance_models()) == len(dist) + 1
nn_model = [v for v in tp.list_distance_models() if v["family"] == "mlp"][0]
assert nn_model["id"] == "3" and nn_model["info"]["rung"] == 6
ok("a network run takes its seeds, learning rates and epochs from the project's settings, and its model is listed beside the others")

# export, import, remove
out = os.path.join(TMP, "out", "my model")
written = tp.export_model(nn_model["path"], out)
assert written.endswith(".opdm") and os.path.isfile(written) and not os.path.exists(written[:-5] + ".json")
tp2 = tc.TrainingProject(os.path.join(TMP, "Other.training"))
got = tp2.import_model(written)
assert got.startswith(tp2.distance_dir()) and [v["family"] for v in tp2.list_models()] == ["mlp"]
assert tp2.import_model(written) == got and len(tp2.list_models()) == 1, "the same file is not copied twice"
junk = os.path.join(TMP, "junk.opdm")
open(junk, "w").write("{}")
try:
    tp2.import_model(junk)
except ValueError as e:
    assert "not an OpenPara distance model" in str(e)
else:
    raise AssertionError
tp2.remove_model(got)
assert tp2.list_models() == [] and os.path.isfile(written), "removing deletes the project's copy only"
ok("a distance model exports as one file, imports into another project (once), a file that is not one is refused, and removing deletes only the project's copy")

# a copy with no distances
tp3 = project("NoDist", [recording("e", 10, 5, "re", with_distance=False), recording("f", 6, 6, "rf", with_distance=False)], "rf")
tp3.set_settings({"model": {"type": "nn_ladder", "size": "6"}})
try:
    tp3.start_run("Tester", python=sys.executable)
except ValueError as e:
    assert "None of the training boxes" in str(e) and "nothing to learn from" in str(e) and "Classes + boxes" not in str(e) and not str(e).endswith("\n"), str(e)
else:
    raise AssertionError("no distances must stop the run before it starts")
assert not os.path.isdir(tp3.runs_dir) or os.listdir(tp3.runs_dir) == []
ok("a project with no distances is refused before the run starts, in words that fit a distance-only model")

# the YOLO types are as they were
tp.set_settings({"model": {"type": "yolo", "size": "n", "params": {}}})
assert tp.settings["model"]["type"] == "yolo" and "classical_regress" in tc.model_types()
print("trainer numeric ok", flush=True)
