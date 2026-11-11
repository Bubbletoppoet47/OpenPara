import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
"""Trainer, classes + boxes + distance models: the LiDAR distances picked in the annotator travel through the zip into the frozen training
copy (distances.csv, matched to the label rows); a distance model needs distances and is saved with the Scratch models; a model is continued
as the kind it is.  With torch and ultralytics in the training Python a tiny model is really trained, saved and continued; without them
that part is skipped."""
import os, sys, tempfile, time, json, csv, pickle, zipfile
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
import annotator_core as ac, dataset_zip as dz, model_library as ml
import trainer_core as tc
import job_common as jc

ME = {"id": "me123", "name": "Tester"}
W, H, K = 320, 240, 200.0                      # a made-up camera: distance in metres = K / height of the object in pixels


def recording(name, n, seed, session, with_distance=True):
    """An annotated project of n pictures: a crate and a ball per picture; three boxes in four carry a distance."""
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
            if cls == 0:
                cv2.rectangle(img, (x, y), (x + w, y + h), (30, 60, 200), -1)
            else:
                cv2.ellipse(img, (x + w // 2, y + h // 2), (w // 2, h // 2), 0, 0, 360, (200, 170, 30), -1)
            t.append((cls, (x + w / 2) / W, (y + h / 2) / H, w / W, h / H, K / h))
        vw.write(img); truth.append(t)
    vw.release()
    pr = ac.Project(os.path.join(TMP, name))
    for c in ("crate", "ball"):
        pr.add_class(c)
    pr.editor_id = ME["id"]
    pr.import_video(vid, stride=1, session_name=session)
    ids = sorted(pr.manifest["images"])
    assert len(ids) == n, (len(ids), n)
    for k, (i, t) in enumerate(zip(ids, truth)):
        picks = [({"distance_m": round(b[5], 3), "u": int(b[1] * W), "v": int(b[2] * H)} if with_distance and (k + j) % 4 else None)
                 for j, b in enumerate(t)]
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


def fake_pt(path, distance):
    """A file shaped like a torch checkpoint (a zip with a pickle inside), with or without the distance model's format name."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("archive/data.pkl", pickle.dumps({"format": "gimble-det-dist-v1", "cfg": "yolo26n.yaml"} if distance else {"model": "yolo"}))
        z.writestr("archive/data/0", b"\0" * 64)


def job_of(job):
    with open(os.path.join(job.run_dir, "job.json"), encoding="utf-8") as f:
        return json.load(f)


# ---- the distances picked in the annotator reach the Trainer through the zip
tp = project("Dist", [recording("yard", 12, 1, "yard"), recording("street", 8, 2, "street")], "street")
s = tp.summary()
assert (s["train"], s["val"]) == (12, 8) and s["boxes"] == {"train": [12, 12], "val": [8, 8]}, s
assert s["dist"] == {"train": 18, "val": 12}, s                      # three boxes in four
assert tp.summary(["ball"])["dist"] == {"train": 9, "val": 6}

# ---- the frozen copy lists them, with exactly the numbers of the label rows (that is how a distance finds its box)
dest = os.path.join(TMP, "frozen")
y, c = tp.freeze(dest, None, False)
assert c["dist"] == {"train": 18, "val": 12} and (c["train"], c["val"]) == (12, 8), c
rows = list(csv.DictReader(open(os.path.join(dest, "distances.csv"), newline="", encoding="utf-8")))
assert len(rows) == 30 and {r["split"] for r in rows} == {"train", "val"} and {r["class"] for r in rows} == {"crate", "ball"}
for r in rows:
    lab = open(os.path.join(dest, "labels", r["split"], r["image"] + ".txt")).read().split("\n")
    assert f"{r['class_id']} {r['xc']} {r['yc']} {r['w']} {r['h']}" in lab, (r, lab)
    hpx = float(r["h"]) * H
    assert abs(float(r["distance_m"]) - K / hpx) < 0.02 * K / hpx, r      # the distance that was picked for that box
# a class filter keeps the distances of the classes that are trained, under their new numbers
y2, c2 = tp.freeze(os.path.join(TMP, "frozen2"), ["ball"], False)
rows2 = list(csv.DictReader(open(os.path.join(TMP, "frozen2", "distances.csv"), newline="", encoding="utf-8")))
assert c2["dist"] == {"train": 9, "val": 6} and len(rows2) == 15 and {(r["class_id"], r["class"]) for r in rows2} == {("0", "ball")}
# a distorted copy keeps its picture's distances (only its colours changed); validation pictures get no copies
tp.set_settings({"distortions": {"enabled": True, "count": 2}})
assert tp.prepare_distortions() == 12
y3, c3 = tp.freeze(os.path.join(TMP, "frozen3"), None, True)
assert c3["train"] == 36 and c3["dist"] == {"train": 54, "val": 12}, c3
tp.set_settings({"distortions": {"enabled": False}})

# ---- which kind a model file is, without torch
pd, py = os.path.join(TMP, "dist.pt"), os.path.join(TMP, "plain.pt")
fake_pt(pd, True); fake_pt(py, False)
assert tc.is_distance_checkpoint(pd) and not tc.is_distance_checkpoint(py)
assert not tc.is_distance_checkpoint(os.path.join(TMP, "missing.pt")) and not tc.is_distance_checkpoint(__file__)
assert tc.type_for_checkpoint(pd, "yolo") == "yolo_distance" and tc.type_for_checkpoint(pd, "yolo_distance_scratch") == "yolo_distance_scratch"
assert tc.type_for_checkpoint(py, "yolo_distance") == "yolo" and tc.type_for_checkpoint(py, "yolo_scratch") == "yolo_scratch"

# ---- a distance model cannot be trained from data without distances: it says so and names the other kind
plain = project("Plain", [recording("yard2", 6, 3, "yard2", False), recording("street2", 4, 4, "street2", False)], "street2")
assert plain.summary()["dist"] == {"train": 0, "val": 0}
try:
    plain.start_run("T", python=sys.executable, type="yolo_distance", size="n"); raise SystemExit("should refuse")
except ValueError as e:
    assert "has a distance" in str(e) and "Classes + boxes" in str(e), e
assert not os.listdir(plain.runs_dir)

# ---- the job a distance type starts
env = tc.check_env(tc.train_python())
REAL = env["ok"]
job = tp.start_run("Tester", python=sys.executable, type="yolo_distance", size="n", epochs=1, batch=4, imgsz=160)
j = job_of(job); job.stop()
assert j["distance"] and j["models_key"] == "scratch" and j["type"] == "yolo_distance" and j["dist_counts"] == {"train": 18, "val": 12}, j
assert j["pretrained"] == "yolo26{size}.pt" and j["cfg"] == "yolo26{size}.yaml" and not j["from_scratch"] and j["start_weights"] is None
assert os.path.isfile(os.path.join(job.run_dir, "dataset", "distances.csv"))
job = tp.start_run("Tester", python=sys.executable, type="yolo", size="n", epochs=1)
j = job_of(job); job.stop()
assert not j["distance"] and j["models_key"] == "assist" and j["type"] == "yolo"

# ---- a model is continued as the kind it is, whatever type was showing
for d in (tp.models_dir, ):
    for key in ml.FOLDERS:
        os.makedirs(ml.folder_path(d, key), exist_ok=True)
vd = ml.save_version(tp.models_dir, "scratch", pd, "n", "Tester", classes=["crate", "ball"])
vy = ml.save_version(tp.models_dir, "assist", py, "s", "Tester", classes=["crate", "ball"])
assert tc.checkpoint_info(sys.executable, vd) == {"size": "n", "classes": ["crate", "ball"], "distance": True}
assert tc.checkpoint_info(sys.executable, vy) == {"size": "s", "classes": ["crate", "ball"], "distance": False}
job = tp.start_run("Tester", python=sys.executable, type="yolo", size="m", epochs=1, continue_from=vd)
j = job_of(job); job.stop()
assert j["type"] == "yolo_distance" and j["distance"] and j["models_key"] == "scratch" and j["size"] == "n" and j["start_weights"] == vd, j
job = tp.start_run("Tester", python=sys.executable, type="yolo_distance_scratch", size="n", epochs=1, continue_from=vy)
j = job_of(job); job.stop()
assert j["type"] == "yolo" and not j["distance"] and j["models_key"] == "assist" and j["size"] == "s" and j["start_weights"] == vy, j

# ---- the distance score is kept with the saved model and shown with it
run = os.path.join(TMP, "run_x"); os.makedirs(run)
fjob = {"run_dir": run, "size": "n", "models_key": "scratch", "models_dirs": [tp.models_dir], "classes": ["crate", "ball"], "trainer": "Tester"}
assert jc.finish(fjob, pd, {"epoch": 3, "total_epochs": 5, "map50": 0.9, "map50_95": 0.7, "dist_median_err": 0.124, "dist_within_20": 0.8,
                            "dist_mae_m": 0.31}) == 0
res = json.load(open(os.path.join(run, "result.json")))
v = [x for x in ml.list_versions(tp.models_dir, "scratch") if x["path"] == res["saved"][0]][0]
assert v["scores"] == {"map50": 0.9, "map50_95": 0.7, "dist_median_err": 0.124, "dist_within_20": 0.8, "dist_mae_m": 0.31}, v
assert ml.distance_text(v["scores"]) == "   distance error 12%" and ml.distance_text({"map50": 0.5}) == "" and ml.distance_text(None) == ""
assert ml.describe(v).endswith("mAP50-95 0.7 - distance error 12%"), ml.describe(v)
os.remove(res["saved"][0]); os.remove(ml.info_path(res["saved"][0])); os.remove(vd); os.remove(ml.info_path(vd))

# ---- with torch and ultralytics: a tiny model is really trained from random weights, saved, and continued as its second round
if not REAL:
    print("no torch + ultralytics in the training Python: the real training part is skipped")
else:
    def wait(job, limit=200):
        t0 = time.time()
        while job.poll() is None and time.time() - t0 < limit:
            time.sleep(0.5)
        log = open(job.log_path, encoding="utf-8", errors="replace").read()
        assert job.poll() == 0, log[-3000:]
        return log, job.result()

    job = tp.start_run("Tester", python=tc.train_python(), type="yolo_distance_scratch", size="n", epochs=2, patience=5, batch=4, imgsz=160)
    log, res = wait(job)
    assert "Distance boxes : 18 training / 12 validation" in log and "random starting weights" in log and "epoch 2/2" in log, log[-3000:]
    assert res["ok"] and res["info"]["round"] == 1 and res["info"]["total_epochs"] == 2 and "dist_median_err" in res["info"], res
    assert res["info"]["distance_boxes"] == {"train": 18, "val": 12}
    assert len(res["saved"]) == 2 and all(tc.is_distance_checkpoint(p) for p in res["saved"]), res      # the project and the annotator's Models
    assert os.path.dirname(res["saved"][0]) == ml.folder_path(tp.models_dir, "scratch")
    assert os.path.dirname(res["saved"][1]) == ml.folder_path(tc.annotator_models_dir(), "scratch")
    v = ml.list_versions(tp.models_dir, "scratch")[0]
    assert v["size"] == "n" and v["classes"] == ["crate", "ball"] and "dist_median_err" in v["scores"] and "map50" in v["scores"], v
    cols = open(os.path.join(job.run_dir, "train", "results.csv")).readline()
    assert "train/dist_loss" in cols and "dist/median_rel_err" in cols
    # continued from the "classes + boxes" type box: it goes on as a distance model, round 2
    job2 = tp.start_run("Tester", python=tc.train_python(), type="yolo", size="m", epochs=1, batch=4, imgsz=160, continue_from=v["path"])
    log2, res2 = wait(job2)
    assert "CONTINUE (round 2)" in log2 and res2["ok"] and res2["info"]["round"] == 2, log2[-3000:]
    assert len(ml.list_versions(tp.models_dir, "scratch")) == 2 and not ml.list_versions(tp.models_dir, "assist")[1:]
    newest = max(ml.list_versions(tp.models_dir, "scratch"), key=lambda x: x["ts"])
    assert newest["based_on"] == v["file"], newest
    print("real training ok: round 1 and round 2 saved with the Scratch models")

print("trainer distance ok", flush=True)
