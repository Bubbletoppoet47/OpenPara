import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
"""Trainer core: zips from two annotator projects merge into a .training project (and back out as a master zip the annotator can import);
distortions skip validation pictures; a run trains on a frozen copy; a fake training script runs in the background and is stopped."""
import os, sys, tempfile, time, json, shutil
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
import annotator_core as ac, dataset_zip as dz, share_zip as sz, model_library as ml, ext
import trainer_core as tc

ME = {"id": "me123", "name": "Tester"}

def video(name, shift=0):
    p = os.path.join(TMP, name)
    vw = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for i in range(12):
        f = np.full((240, 320, 3), 30 + i * 5 + shift, np.uint8); cv2.rectangle(f, (50 + i * 3, 60), (150 + i * 3, 160), (0, 200, 0), -1); vw.write(f)
    vw.release()
    return p

def annotated_project(name, vid, session, classes, n=4):
    pr = ac.Project(os.path.join(TMP, name))
    for c in classes:
        pr.add_class(c)
    pr.editor_id = ME["id"]
    pr.import_video(vid, stride=3, session_name=session)
    ids = sorted(pr.manifest["images"])[:n]
    for k, i in enumerate(ids):
        pr.set_boxes(i, [(k % len(classes), 0.5, 0.5, 0.3, 0.3)])
    return pr, ids

# ---- two people annotate different recordings; each hands over a zip
pa, ida = annotated_project("A", video("a.mp4"), "setA", ["cup", "bottle"])
pb, idb = annotated_project("B", video("b.mp4", 40), "setB", ["bottle", "can"])
za, zb = os.path.join(TMP, "a.zip"), os.path.join(TMP, "b.zip")
assert dz.export_zip(pa, za, ME)["count"] == 4 and dz.export_zip(pb, zb, ME)["count"] == 4

# ---- the trainer merges both
tp = tc.TrainingProject(os.path.join(TMP, "My.training"))
assert os.path.isfile(os.path.join(tp.root, "training.json")) and tp.meta["format"] == "openpara-training"
for z in (za, zb):
    plan = tp.plan_import(z, ME)
    assert not plan["conflicts"], plan["conflicts"]
    tp.apply_import(plan, None, ME)
    assert not os.path.isdir(plan["_workdir"])
assert sorted(tp.data.classes) == ["bottle", "can", "cup"], tp.data.classes
assert len(tp.annotated_ids()) == 8 and {s["session_id"] for s in tp.sets()} == {"setA", "setB"}, tp.sets()
# importing the same zip again adds nothing
plan = tp.plan_import(za, ME); n0 = len(tp.annotated_ids()); tp.apply_import(plan, None, ME)
assert len(tp.annotated_ids()) == n0
assert len(tp.meta["imports"]) == 3
# class mapping: the boxes keep their class NAMES
names = {}
for i in tp.annotated_ids():
    for b in tp.data.get_boxes(i):
        names[tp.data.classes[b[0]]] = names.get(tp.data.classes[b[0]], 0) + 1
assert names == {"cup": 2, "bottle": 4, "can": 2}, names     # A: cup,bottle,cup,bottle   B: bottle,can,bottle,can

# ---- the trainer's master zip goes back into an annotator project (and another trainer)
master = os.path.join(TMP, "master.zip")
assert tp.export_zip(master, ME)["count"] == 8
pc = ac.Project(os.path.join(TMP, "C"))
plan = dz.plan_zip(pc, master, tempfile.mkdtemp(), ME); dz.apply_zip(pc, plan, None, ME)
assert len([i for i in pc.list_images() if pc.is_annotated(i)]) == 8 and sorted(pc.classes) == ["bottle", "can", "cup"]
tp2 = tc.TrainingProject(os.path.join(TMP, "Other.training"))
p2 = tp2.plan_import(master, ME); tp2.apply_import(p2, None, ME)
assert len(tp2.annotated_ids()) == 8

# ---- sets: setB is validation
tp.set_role("setB", "val")
s = tp.summary()
assert (s["train"], s["val"]) == (4, 4), s
assert tp.summary(["cup"])["classes"] == ["cup"]

# ---- distortions: training pictures only, regenerated when the settings change
tp.set_settings({"distortions": {"enabled": True, "count": 2, "types": {"noise": False, "jpeg": False}}})
made = tp.prepare_distortions()
d = tp.data.manifest["distortions"]
assert made == 4 and all(len(v) == 2 for k, v in d.items() if v), d
assert not any(tp.data.is_val_image(k) and v for k, v in d.items()), "validation got distortions"
sig1 = tp.meta["distortion_sig"]
tp.set_settings({"distortions": {"count": 3}})
tp.prepare_distortions()
assert tp.meta["distortion_sig"] != sig1 and all(len(v) == 3 for k, v in tp.data.manifest["distortions"].items() if v)
assert len(os.listdir(tp.data.dist_images_dir)) == 12            # old ones were cleared, not piled up
r = tc.distortion_ranges(tp.settings["distortions"])
assert r["noise_sigma"] == (0.0, 0.0) and r["jpeg_quality"] == (100, 100) and r["brightness"] == tuple(ac.DEFAULT_DISTORTION_RANGES["brightness"])
# switching a set to validation drops its copies; the freeze never puts distortions on the validation side
dest = os.path.join(TMP, "frozen")
y, c = tp.freeze(dest, None, True)
assert (c["train"], c["val"]) == (4 * 4, 4), c
# ---- what a start has to make is known beforehand, from the picture list alone
assert tp.summary()["distort_pictures"] == 4
assert tp.distortion_plan(4) == {"enabled": True, "count": 3, "pictures": 4, "ready": 4, "to_make": 0}
tp.set_settings({"distortions": {"count": 4}})
assert tp.distortion_plan(4) == {"enabled": True, "count": 4, "pictures": 4, "ready": 0, "to_make": 16}       # other settings: all are made again
# ---- making the copies reports its progress, can be stopped, and goes on from where it stopped
saves = []
real_save = tp.data.save_manifest
tp.data.save_manifest = lambda: (saves.append(1), real_save())[1]
prog = []
try:
    tp.prepare_distortions(lambda d, t: prog.append((d, t)), stop=lambda: len(prog) >= 2); raise SystemExit("should have stopped")
except tc.Cancelled:
    pass
have = sum(1 for v in tp.data.manifest["distortions"].values() if len(v) == 4)
assert prog[0] == (0, 4) and 1 <= have < 4 and prog[-1] == (have, 4), (prog, have)
assert len(os.listdir(tp.data.dist_images_dir)) == have * 4                    # what was made is recorded and kept
assert json.load(open(tp.data.manifest_path))["distortions"] == tp.data.manifest["distortions"]
assert tp.distortion_plan(4)["ready"] == have and tp.distortion_plan(4)["to_make"] == (4 - have) * 4
mt0 = {f: os.path.getmtime(os.path.join(tp.data.dist_images_dir, f)) for f in os.listdir(tp.data.dist_images_dir)}
prog.clear(); n_saves = len(saves)
assert tp.prepare_distortions(lambda d, t: prog.append((d, t))) == 4
assert prog[0] == (have, 4) and prog[-1] == (4, 4) and len(os.listdir(tp.data.dist_images_dir)) == 16
assert all(os.path.getmtime(os.path.join(tp.data.dist_images_dir, f)) == t for f, t in mt0.items())      # the kept ones were not made again
assert len(saves) - n_saves <= 2, "the picture list is written at the end, not after every picture"
tp.data.save_manifest = real_save
prog.clear(); assert tp.prepare_distortions(lambda d, t: prog.append((d, t))) == 4 and prog == [(4, 4)]     # nothing left to make
# a picture that cannot be read says which one
bad = sorted(k for k, v in tp.data.manifest["distortions"].items() if v)[0]
tp.set_settings({"distortions": {"count": 5}})
keep = open(tp.data.image_path(bad), "rb").read()
open(tp.data.image_path(bad), "wb").write(b"not a picture")
try:
    tp.prepare_distortions(); raise SystemExit("should fail")
except RuntimeError as e:
    assert bad in str(e) and "distorted copies" in str(e), e
open(tp.data.image_path(bad), "wb").write(keep)
assert tp.prepare_distortions() == 4 and all(len(v) == 5 for v in tp.data.manifest["distortions"].values() if v)   # the others were kept, this one follows
tp.set_settings({"distortions": {"count": 3}}); tp.prepare_distortions()
assert not [f for f in os.listdir(os.path.join(dest, "images", "val")) if "_dist" in f]
assert len([f for f in os.listdir(os.path.join(dest, "images", "train")) if "_dist" in f]) == 12
txt = open(y).read(); assert "nc: 3" in txt and "0: " in txt
# class filter: other classes' boxes are dropped, pictures stay as negatives
y2, c2 = tp.freeze(os.path.join(TMP, "frozen2"), ["can"], False)
assert c2["classes"] == ["can"] and (c2["train"], c2["val"]) == (4, 4)
lab = [open(os.path.join(TMP, "frozen2", "labels", "val", f)).read() for f in os.listdir(os.path.join(TMP, "frozen2", "labels", "val"))]
assert sum(1 for t in lab if t.strip()) == 2 and all(t.split()[0] == "0" for t in lab if t.strip())
tp.set_settings({"distortions": {"enabled": False}})

# ---- the environment check says what is missing
info = tc.check_env(sys.executable)
assert info["python"] == sys.executable and isinstance(info["problems"], list)
bad = tc.check_env(os.path.join(TMP, "no_such_python"))
assert not bad["ok"] and "could not be started" in bad["problems"][0]
print("env here:", tc.env_text(info).replace("\n", " | "))

# ---- a fake model type plugs in through ext (this is how the Gimble scratch trainer will) and runs in the background
fake = os.path.join(TMP, "fake_train.py")
open(fake, "w").write(f'''import os, sys, time
sys.path.insert(0, {TR!r})
import job_common as jc
job = jc.load_job()
print("fake training of", job["classes"], job["counts"], flush=True)
snap = open(job["data_yaml"]).read()
for e in range(int(os.environ.get("FAKE_EPOCHS", "3"))):
    print("epoch", e, flush=True); time.sleep(float(os.environ.get("FAKE_SLEEP", "0.2")))
os.makedirs(os.path.join(job["run_dir"], "train", "weights"), exist_ok=True)
best = os.path.join(job["run_dir"], "train", "weights", "best.pt"); open(best, "wb").write(b"weights")
sys.exit(jc.finish(job, best, {{"epoch": 2, "total_epochs": 3, "map50": 0.5, "map50_95": 0.3}}))
''')
ext.add_model_trainer("fake", label="Fake", script=fake, sizes=("n", "s"), default_size="n", models_key="assist")
mt = tc.model_types()
assert "fake" in mt and mt["yolo"]["label"] == "Classes + boxes  (pretrained)" and "not pretrained" in mt["yolo_scratch"]["label"] and not mt["yolo"]["from_scratch"] and mt["yolo_scratch"]["from_scratch"]
# the two kinds: classes + boxes (saved with the Assist models) and classes + boxes + distance (saved with the Scratch models)
assert list(mt)[:4] == ["yolo", "yolo_scratch", "yolo_distance", "yolo_distance_scratch"], list(mt)
for k in ("yolo", "yolo_scratch"):
    assert not mt[k]["distance"] and mt[k]["models_key"] == "assist" and mt[k]["script"] == tc.HELPER_SCRIPT
for k in ("yolo_distance", "yolo_distance_scratch"):
    assert mt[k]["distance"] and mt[k]["models_key"] == "scratch" and mt[k]["script"] == tc.DISTANCE_SCRIPT and os.path.isfile(tc.DISTANCE_SCRIPT)
    assert mt[k]["label"].startswith("Classes + boxes + distance  (") and mt[k]["default_size"] == "n"
assert mt["yolo_distance"]["pretrained"] == "yolo26{size}.pt" and not mt["yolo_distance"]["from_scratch"]
assert mt["yolo_distance_scratch"]["pretrained"] is None and mt["yolo_distance_scratch"]["from_scratch"] and not mt["fake"]["distance"]
assert tc.default_me()["name"] and not tc.default_me().get("name", "").count(" ")
job = tp.start_run("Tester", python=sys.executable, type="fake", size="n", epochs=3, classes=None)
txt = ""
t0 = time.time()
while job.poll() is None and time.time() - t0 < 60:
    time.sleep(0.1); txt += job.read_log()
txt += job.read_log()
assert job.poll() == 0, txt
assert "fake training of ['cup', 'bottle', 'can']" in txt, txt
res = job.result(); assert res and res["ok"] and len(res["saved"]) == 2, res
# the model is in the project's models AND the annotator's Models folder
assert [v["classes"] for v in tp.list_models()] == [["cup", "bottle", "can"]], tp.list_models()
vs = ml.list_versions(tc.annotator_models_dir(), "assist")
assert len(vs) == 1 and vs[0]["size"] == "n" and vs[0]["trainer"] == "Tester" and vs[0]["scores"]["map50"] == 0.5, vs
assert tp.newest_matching("assist", "n", vs[0]["classes"])["file"] == vs[0]["file"]

# ---- a second run continues from the version we choose when the classes match; the first run's frozen data is untouched by later imports
snap1 = os.path.join(job.run_dir, "dataset", "images", "train")
n1 = len(os.listdir(snap1))
os.environ["FAKE_SLEEP"] = "2"; os.environ["FAKE_EPOCHS"] = "30"
time.sleep(1.1)                                     # the version names are per minute but never overwrite
# without "continue", nothing is carried over
jobx = tp.start_run("Tester", python=sys.executable, type="fake", size="n", epochs=3); jobx.stop()
assert json.load(open(os.path.join(jobx.run_dir, "job.json")))["start_weights"] is None
# ---- starting a run tells each stage, and a stop before the training program leaves nothing of the run behind
stages = []
was_on = tp.settings["distortions"]["enabled"]
tp.set_settings({"distortions": {"enabled": True}})
n_ann, n_tr = len(tp.annotated_ids()), tp.summary()["distort_pictures"]
n_runs = len(os.listdir(tp.runs_dir))
jobp = tp.start_run("Tester", progress_cb=lambda st, d, t: stages.append((st, d, t)), python=sys.executable, type="fake", size="n", epochs=1); jobp.stop()
names = [st for st, _d, _t in stages]
assert [n for i, n in enumerate(names) if i == 0 or names[i - 1] != n] == ["distortions", "copy", "start"], names
assert ("distortions", n_tr, n_tr) in stages and ("copy", 0, n_ann) in stages and stages[-1] == ("start", 0, 0), stages
n_runs += 1
for when in ("distortions", "copy", "start"):
    hit = []
    def stop_at(st, d, t, when=when):
        if st == when:
            hit.append(1)
    try:
        tp.start_run("Tester", progress_cb=stop_at, python=sys.executable, stop=lambda: bool(hit), type="fake", size="n", epochs=1).stop()
        assert when == "start", when                                             # once the program is starting there is nothing left to cancel
        n_runs += 1
    except tc.Cancelled:
        assert when != "start"
    assert len(os.listdir(tp.runs_dir)) == n_runs, (when, os.listdir(tp.runs_dir))
tp.set_settings({"distortions": {"enabled": was_on}})
# continuing needs the same classes
try:
    tp.start_run("Tester", python=sys.executable, type="fake", continue_from=vs[0]["path"], classes=["cup"]); raise SystemExit("should refuse")
except ValueError as e:
    assert "same" in str(e) and "cup, bottle, can" in str(e), e
job2 = tp.start_run("Tester", python=sys.executable, type="fake", epochs=3, continue_from=vs[0]["path"], name="Beach_v2")
cfg = json.load(open(os.path.join(job2.run_dir, "job.json")))
assert cfg["start_weights"] == vs[0]["path"] and cfg["based_on"] == vs[0]["file"] and cfg["size"] == "n" and cfg["trainer"] == "Beach_v2", cfg
# from-scratch type flags the job
js = tp.start_run("Tester", python=sys.executable, type="yolo_scratch", size="s", epochs=1)
jc_ = json.load(open(os.path.join(js.run_dir, "job.json"))); js.stop()
assert jc_["from_scratch"] and jc_["pretrained"].endswith(".yaml") and jc_["start_weights"] is None, jc_
# the Pythons it can offer
ps = tc.find_pythons(); assert sys.executable in ps
assert "CPU-only" in " ".join(tc.check_env(sys.executable)["warnings"]) or not tc.check_env(sys.executable)["torch"]
# import while it runs: the running job's snapshot does not change
pd, _ = annotated_project("D", video("d.mp4", 80), "setD", ["cup"], 2)
zd = os.path.join(TMP, "d.zip"); dz.export_zip(pd, zd, ME)
p = tp.plan_import(zd, ME); tp.apply_import(p, None, ME)
assert len(tp.annotated_ids()) == 10
assert len(os.listdir(os.path.join(job2.run_dir, "dataset", "images", "train"))) == n1
assert job2.poll() is None
time.sleep(1.0); assert "epoch 0" in job2.read_log()
job2.stop()
assert job2.poll() is not None and job2.result() is None
assert len(ml.list_versions(tc.annotator_models_dir(), "assist")) == 1       # a stopped run saves nothing

# ---- refusals say why
tp3 = tc.TrainingProject(os.path.join(TMP, "Empty.training"))
for kw, word in (({}, "no training pictures"),):
    try:
        tp3.start_run("T", python=sys.executable, type="fake", size="n"); raise SystemExit("should refuse")
    except ValueError as e:
        assert word in str(e), e
tp.set_role("setA", "val")
tp.set_role("setB", "val"); tp.set_role("setD", "val")
try:
    tp.start_run("T", python=sys.executable, type="fake", size="n"); raise SystemExit("should refuse")
except ValueError as e:
    assert "no training pictures" in str(e)
for s_ in ("setA", "setB", "setD"):
    tp.set_role(s_, "train")
try:
    tp.start_run("T", python=sys.executable, type="fake", size="n"); raise SystemExit("should refuse")
except ValueError as e:
    assert "no validation pictures" in str(e), e
# reopening the folder gives the same project
tp4 = tc.TrainingProject(tp.root)
assert len(tp4.annotated_ids()) == 10 and tp4.settings["distortions"]["count"] == 3
print("trainer core ok")
