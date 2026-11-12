import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
"""Trainer, classes + boxes + distance models: the LiDAR distances picked in the annotator travel through the zip into the frozen training
copy (distances.csv, matched to the label rows); a distance model needs distances and is saved with the Scratch models.
It is TWO models trained one after the other - a stock YOLO detector, then a separate distance model - saved as one file: the detector's
.pt with the distance model added.  A model that has a distance model keeps it when continued; a classes + boxes model can get one on top.
With torch and ultralytics in the training Python tiny models are really trained from random weights, saved, read back, continued and
converted for the Gimble; without them that part is skipped."""
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


def fake_pt(path, kind):
    """A file shaped like a torch checkpoint (a zip with a pickle inside): "two" = a detector with a distance model added, "old" = the
    earlier one-network distance model, "plain" = a classes + boxes model."""
    inside = {"two": {"opara_two_model": {"format": "opara-two-model-v1"}, "model": "yolo"},
              "old": {"format": "gimble-det-dist-v1", "cfg": "yolo26n.yaml"}, "plain": {"model": "yolo"}}[kind]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("archive/data.pkl", pickle.dumps(inside))
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
pd, po, py = os.path.join(TMP, "two.pt"), os.path.join(TMP, "old.pt"), os.path.join(TMP, "plain.pt")
fake_pt(pd, "two"); fake_pt(po, "old"); fake_pt(py, "plain")
assert [tc.checkpoint_kind(p) for p in (pd, po, py)] == ["two", "old", "plain"]
assert tc.is_distance_checkpoint(pd) and tc.is_distance_checkpoint(po) and not tc.is_distance_checkpoint(py)
assert tc.checkpoint_kind(os.path.join(TMP, "missing.pt")) == "plain" and tc.checkpoint_kind(__file__) == "plain"
# a model with a distance model keeps it; a classes + boxes model goes on as it is or gets a distance model on top (the type is kept)
assert tc.type_for_checkpoint(pd, "yolo") == "yolo_distance" and tc.type_for_checkpoint(po, "yolo") == "yolo_distance"
assert tc.type_for_checkpoint(py, "yolo_distance") == "yolo_distance" and tc.type_for_checkpoint(py, "yolo") == "yolo"
assert tc.type_for_checkpoint(py, "something_else") == "yolo"

# ---- a distance model cannot be trained from data without distances: it says so and names the other kind
plain = project("Plain", [recording("yard2", 6, 3, "yard2", False), recording("street2", 4, 4, "street2", False)], "street2")
assert plain.summary()["dist"] == {"train": 0, "val": 0}
try:
    plain.start_run("T", python=sys.executable, type="yolo_distance", size="n"); raise SystemExit("should refuse")
except ValueError as e:
    assert "has a distance" in str(e) and "Classes + boxes" in str(e), e
assert not os.listdir(plain.runs_dir)

# ---- the job a distance type starts: random weights (a description to build from, no weights), both stages in one script
env = tc.check_env(tc.train_python())
REAL = env["ok"]
job = tp.start_run("Tester", python=sys.executable, type="yolo_distance", size="n", epochs=1, batch=4, imgsz=160)
j = job_of(job); job.stop()
assert j["distance"] and j["models_key"] == "scratch" and j["type"] == "yolo_distance" and j["dist_counts"] == {"train": 18, "val": 12}, j
assert j["cfg"] == "yolo26{size}.yaml" and j["fallback"] == "yolo11{size}.yaml" and j["start_weights"] is None and not j["distance_only"]
assert "pretrained" not in j and "from_scratch" not in j, j
assert os.path.isfile(os.path.join(job.run_dir, "dataset", "distances.csv"))
job = tp.start_run("Tester", python=sys.executable, type="yolo", size="n", epochs=1)
j = job_of(job); job.stop()
assert not j["distance"] and j["models_key"] == "assist" and j["type"] == "yolo" and not j["distance_only"]

# ---- continuing
for d in (tp.models_dir, ):
    for key in ml.FOLDERS:
        os.makedirs(ml.folder_path(d, key), exist_ok=True)
vd = ml.save_version(tp.models_dir, "scratch", pd, "n", "Tester", classes=["crate", "ball"])
vo = ml.save_version(tp.models_dir, "scratch", po, "n", "Older", classes=["crate", "ball"])
vy = ml.save_version(tp.models_dir, "assist", py, "s", "Tester", classes=["crate", "ball"])
assert tc.checkpoint_info(sys.executable, vd) == {"size": "n", "classes": ["crate", "ball"], "distance": True}
assert tc.checkpoint_info(sys.executable, vy) == {"size": "s", "classes": ["crate", "ball"], "distance": False}
# a model with a distance model goes on with it, whatever type was showing; by default its detector is kept and only the distance trains
job = tp.start_run("Tester", python=sys.executable, type="yolo", size="m", epochs=1, continue_from=vd)
j = job_of(job); job.stop()
assert j["type"] == "yolo_distance" and j["distance"] and j["models_key"] == "scratch" and j["size"] == "n" and j["start_weights"] == vd, j
assert j["distance_only"] is True
job = tp.start_run("Tester", python=sys.executable, type="yolo", size="m", epochs=1, continue_from=vd, distance_only=False)
j = job_of(job); job.stop()
assert j["type"] == "yolo_distance" and j["distance_only"] is False, j
# a classes + boxes model: with the distance type it gets a distance model on top (saved with the Scratch models) ...
job = tp.start_run("Tester", python=sys.executable, type="yolo_distance", size="n", epochs=1, continue_from=vy)
j = job_of(job); job.stop()
assert j["type"] == "yolo_distance" and j["distance"] and j["distance_only"] and j["models_key"] == "scratch" and j["size"] == "s", j
assert j["start_weights"] == vy and j["based_on"] == os.path.basename(vy)
# ... and with the classes + boxes type it goes on as it is
job = tp.start_run("Tester", python=sys.executable, type="yolo", size="n", epochs=1, continue_from=vy)
j = job_of(job); job.stop()
assert j["type"] == "yolo" and not j["distance"] and not j["distance_only"] and j["models_key"] == "assist" and j["size"] == "s", j
# the earlier one-network kind cannot be trained further: refused at once, before anything is prepared, and no run folder is left
runs = sorted(os.listdir(tp.runs_dir))
for typ in ("yolo", "yolo_distance"):
    try:
        tp.start_run("Tester", python=sys.executable, type=typ, size="n", epochs=1, continue_from=vo); raise SystemExit("should refuse")
    except ValueError as e:
        assert "earlier kind" in str(e) and "cannot be trained further" in str(e), e
assert sorted(os.listdir(tp.runs_dir)) == runs
os.remove(vo); os.remove(ml.info_path(vo))

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
os.remove(res["saved"][0]); os.remove(ml.info_path(res["saved"][0])); os.remove(vd); os.remove(ml.info_path(vd)); os.remove(vy); os.remove(ml.info_path(vy))

# ---- a run that saved something else than was asked for says so in its result; a model whose detector was kept has no epoch of its own
run2 = os.path.join(TMP, "run_y"); os.makedirs(run2)
fjob2 = dict(fjob, run_dir=run2)
assert jc.finish(fjob2, pd, {"dist_median_err": 0.2, "round": 2}, warning="only the detector was saved") == 0
res = json.load(open(os.path.join(run2, "result.json")))
assert res["ok"] and res["warning"] == "only the detector was saved" and res["info"]["round"] == 2, res
os.remove(res["saved"][0]); os.remove(ml.info_path(res["saved"][0]))

# ---- with torch and ultralytics: really trained from random weights, in two stages
if not REAL:
    print("no torch + ultralytics in the training Python: the real training part is skipped")
else:
    faulthandler.cancel_dump_traceback_later(); faulthandler.dump_traceback_later(1500, exit=True)
    import torch
    import distance_model as dm
    PY = tc.train_python()
    KW = dict(python=PY, size="n", batch=4, imgsz=160, patience=5)

    def wait(job, limit=400):
        t0 = time.time()
        while job.poll() is None and time.time() - t0 < limit:
            time.sleep(0.5)
        log = open(job.log_path, encoding="utf-8", errors="replace").read()
        assert job.poll() == 0, log[-3000:]
        return log, job.result()

    def newest(key):
        return max(ml.list_versions(tp.models_dir, key), key=lambda x: x["ts"])

    def detector_weights(path):
        ck = torch.load(path, map_location="cpu", weights_only=False)
        return {k: v.float() for k, v in (ck.get("ema") or ck["model"]).state_dict().items()}

    # the distance model itself: an untrained one answers the usual distance for every box, with or without looking at the picture
    for pic in (True, False):
        net = dm.DistanceNet(3, pic, start_m=4.0).eval()
        rois = torch.tensor([[0, 10.0, 20, 60, 90], [1, 0, 0, 160, 160], [1, 150, 150, 170, 175]])
        d = net.metres(torch.rand(2, 3, 160, 160), rois, torch.tensor([0.0, 2, 1]))
        assert d.shape == (3,) and torch.allclose(d, torch.full((3,), 4.0), atol=1e-4), d
        assert net.metres(torch.rand(1, 3, 64, 64), torch.zeros(0, 5), torch.zeros(0)).shape == (0,)
        assert dm.net_of({"config": net.config(), "state_dict": net.state_dict()}).use_picture is pic
    sc = dm.distance_scores([1.0, 3.3, 12.0], [1.0, 3.0, 10.0])
    assert sc["n"] == 3 and abs(sc["median"] - 0.1) < 1e-9 and abs(sc["within20"] - 1.0) < 1e-9 and [b[1] for b in sc["bins"]] == [1, 1, 0, 1, 0], sc
    assert dm.distance_scores([], [])["n"] == 0

    # 1. a new model: the detector, then the distance model, then both together
    job = tp.start_run("Tester", type="yolo_distance", epochs=2, **KW)
    log, res = wait(job)
    for text in ("=== Stage 1 of 3: the detector", "(random weights, nothing pretrained)", "=== Stage 2 of 3: the distance model",
                 "Distance boxes : 18 training (in 12 pictures) / 12 validation (in 8 pictures)", "new, random weights", "distance epoch 2/2",
                 "[box and class alone:", "Distance model kept:", "By distance:", "By class:", "=== Stage 3 of 3: the two models together",
                 "of the 12 validation boxes that have a distance"):
        assert text in log, (text, log[-4000:])
    assert ".pt" not in log.split("=== Stage 2")[0].split("Start from")[1].split("\n")[0], log[:1500]      # built from a description, not weights
    info = res["info"]
    assert res["ok"] and "warning" not in res and info["round"] == 1 and info["total_epochs"] == 2 and info["dist_total_epochs"] == 2, res
    assert info["dist_inputs"] in ("picture", "boxes") and 0 <= info["dist_median_err"] and "dist_other_err" in info and 0 <= info["dist_found"] <= 1
    assert info["distance_boxes"] == {"train": 18, "val": 12} and "map50" in info
    assert len(res["saved"]) == 2 and all(tc.checkpoint_kind(p) == "two" for p in res["saved"]), res      # the project and the annotator's Models
    assert os.path.dirname(res["saved"][0]) == ml.folder_path(tp.models_dir, "scratch")
    assert os.path.dirname(res["saved"][1]) == ml.folder_path(tc.annotator_models_dir(), "scratch")
    v = newest("scratch")
    assert v["size"] == "n" and v["classes"] == ["crate", "ball"] and "dist_median_err" in v["scores"] and "map50" in v["scores"], v
    assert "val/median_rel_err" in open(os.path.join(job.run_dir, "distance", "results.csv")).readline()
    assert os.path.isfile(os.path.join(job.run_dir, "train", "results.csv"))                              # the detector's own, stock
    # the file is the detector's own .pt with the distance model added: stock Ultralytics reads it as a detector ...
    from ultralytics import YOLO
    y = YOLO(v["path"])
    assert [y.names[k] for k in sorted(y.names)] == ["crate", "ball"]
    # ... and both parts are read back and used one after the other
    two, entry = dm.load(v["path"])
    assert entry["format"] == dm.FORMAT and entry["names"] == ["crate", "ball"] and entry["imgsz"] == 160 and entry["round"] == 1, entry
    assert entry["inputs"] == info["dist_inputs"] and two.names == ["crate", "ball"]
    out = two.infer(torch.rand(2, 3, 160, 160), conf=0.0)
    assert len(out) == 2 and all(o.shape[1] == 7 for o in out) and all(len(o) for o in out)
    assert all(dm.D_MIN <= float(o[:, 6].min()) and float(o[:, 6].max()) <= dm.D_MAX for o in out)
    # the Annotator reads it as a model that gives a distance, and finds its size without an info file
    import gimble_assist, model_registry as mr
    ga = gimble_assist.GimbleAssist(v["path"], device="cpu")
    assert ga.class_names == ["crate", "ball"] and ga.imgsz == 160 and ga.meta["round"] == 1
    pic = os.path.join(job.run_dir, "dataset", "images", "val", sorted(os.listdir(os.path.join(job.run_dir, "dataset", "images", "val")))[0])
    dets = ga.predict_detections(pic, 0.0)
    assert dets and all(len(d) == 7 and 0 <= d[0] <= 1 and dm.D_MIN <= d[6] <= dm.D_MAX for d in dets), dets[:3]
    assert len(ga.predict_boxes(pic, 0.0)[0]) == 5
    assert mr.detect_size("scratch", v["path"]) == "n" and mr.detect_size("helper", v["path"]) == "n"

    # 2. continued, as it comes: the detector is kept exactly as it is and only the distance model trains (its second round)
    job2 = tp.start_run("Tester", type="yolo", epochs=2, continue_from=v["path"], **KW)
    log2, res2 = wait(job2)
    assert "Kept as it is: " + v["file"] in log2 and "Nothing is trained in this stage." in log2, log2[-3000:]
    assert "continuing the distance model of " + v["file"] in log2 and "distance epoch 2/2" in log2 and "=== Stage 3 of 3" in log2
    assert not os.path.exists(os.path.join(job2.run_dir, "train")), "no detector training in this run"
    v2 = newest("scratch")
    assert res2["ok"] and res2["info"]["round"] == 2 and v2["based_on"] == v["file"] and tc.checkpoint_kind(v2["path"]) == "two", res2
    assert res2["info"]["map50"] == v["scores"]["map50"] and "epoch" not in res2["info"]              # the detector's score came along
    a, b = detector_weights(v["path"]), detector_weights(v2["path"])
    assert a.keys() == b.keys() and all(torch.equal(a[k], b[k]) for k in a), "the detector was changed"
    assert dm.load(v2["path"])[1]["round"] == 2

    # 3. continued with the detector trained further too
    job3 = tp.start_run("Tester", type="yolo_distance", epochs=1, continue_from=v2["path"], distance_only=False, **KW)
    log3, res3 = wait(job3)
    assert f"(continuing {v2['file']})" in log3 and "continuing the distance model of " + v2["file"] in log3 and res3["info"]["round"] == 3, log3[-3000:]
    v3 = newest("scratch")
    a, b = detector_weights(v2["path"]), detector_weights(v3["path"])
    assert any(not torch.equal(a[k], b[k]) for k in a), "the detector was not trained"

    # 4. classification first, the distance model on top afterwards: a Classes + boxes model, then continued with the distance type
    job4 = tp.start_run("Tester", type="yolo", epochs=1, **KW)
    log4, res4 = wait(job4)
    va = newest("assist")
    assert res4["ok"] and tc.checkpoint_kind(va["path"]) == "plain" and "(random weights, nothing pretrained)" in log4, log4[-2000:]
    job5 = tp.start_run("Tester", type="yolo_distance", epochs=1, continue_from=va["path"], **KW)
    log5, res5 = wait(job5)
    v5 = newest("scratch")
    assert "Kept as it is: " + va["file"] in log5 and "new, random weights" in log5 and res5["info"]["round"] == 1, log5[-3000:]
    assert tc.checkpoint_kind(v5["path"]) == "two" and v5["based_on"] == va["file"] and tc.checkpoint_kind(va["path"]) == "plain"
    a, b = detector_weights(va["path"]), detector_weights(v5["path"])
    assert all(torch.equal(a[k], b[k]) for k in a)

    # 5. the distance stage fails after a detector was trained: the detector is not lost - it is saved as a Classes + boxes model, with a warning
    import train_distance_job as tdj
    jf = dict(job_of(job), run_dir=os.path.join(TMP, "run_fail"), models_dirs=[tp.models_dir])
    os.makedirs(jf["run_dir"])
    json.dump(jf, open(os.path.join(jf["run_dir"], "job.json"), "w"))
    real_det, real_dist, argv = tdj.thj.train_detector, tdj.train_distance, sys.argv
    tdj.thj.train_detector = lambda job: (va["path"], {"epoch": 1, "total_epochs": 1, "map50": 0.1, "map50_95": 0.05})
    def broken(*a, **k):
        raise RuntimeError("out of memory (made up)")
    tdj.train_distance = broken
    n_assist, n_scratch = len(ml.list_versions(tp.models_dir, "assist")), len(ml.list_versions(tp.models_dir, "scratch"))
    try:
        sys.argv = ["x", os.path.join(jf["run_dir"], "job.json")]
        assert tdj.main() == 0
    finally:
        tdj.thj.train_detector, tdj.train_distance, sys.argv = real_det, real_dist, argv
    rf = json.load(open(os.path.join(jf["run_dir"], "result.json")))
    assert rf["ok"] and "out of memory (made up)" in rf["warning"] and "saved on its own" in rf["warning"], rf
    assert len(ml.list_versions(tp.models_dir, "assist")) == n_assist + 1 and len(ml.list_versions(tp.models_dir, "scratch")) == n_scratch
    assert os.path.dirname(rf["saved"][0]) == ml.folder_path(tp.models_dir, "assist")

    # 6. converted for the Gimble: the two models become the one file the Pi runs, giving boxes and a distance per box
    try:
        import onnxruntime as ort
    except ImportError:
        ort = None
        print("no onnxruntime: the conversion for the Gimble is skipped")
    if ort:
        import subprocess
        outd = os.path.join(TMP, "pi_out")
        r = subprocess.run([PY, os.path.join(ADD, "gimble_link", "gimble_export_job.py"), "--weights", v2["path"], "--out", outd, "--app", ANN],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
        meta = json.load(open(os.path.join(outd, "gimble_model.json")))
        assert meta["has_distance"] is True and meta["kind"] == "scratch" and meta["names"] == ["crate", "ball"] and meta["imgsz"] == 160, meta
        assert meta["round"] == 2
        sess = ort.InferenceSession(os.path.join(outd, "gimble_model.onnx"), providers=["CPUExecutionProvider"])
        x = torch.rand(1, 3, 160, 160)
        dets, dist = sess.run(None, {"images": x.numpy()})
        assert dets.shape[1] == 6 and dist.shape == (dets.shape[0],) and len(dets) > 0
        ref = dm.load(v2["path"])[0].infer(x, conf=0.0)[0].numpy()
        import numpy as np
        assert len(ref) == len(dets) and np.abs(np.sort(ref[:, 6]) - np.sort(dist)).max() < 0.05, (ref[:5], dist[:5])
        print("converted for the Gimble: boxes and distances equal to the two models run one after the other")
    print("real training ok: two stages from random weights, distance only, both continued, distance added on top of a detector")

print("trainer distance ok", flush=True)
