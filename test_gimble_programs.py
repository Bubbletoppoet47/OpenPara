"""The Gimble's own programs (addons_src/gimble_link/pi: what runs on the rig's Raspberry Pi), run here with a stand-in camera, stand-in LiDAR
and a stand-in model: one place says where everything is on the drive; the tidy-up moves the old layout's files away without touching
anything recorded; the start screen shows what is on the drive and starts the right program; Record data writes a session; Test model
draws the predictions and REC VIDEO records them as a video with a table of every prediction; a model without a distance of its own shows
none."""
import os, sys, tempfile, time, json, shutil, hashlib, threading, csv
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
HERE = os.path.dirname(os.path.abspath(__file__))
PI = os.path.join(HERE, "addons_src", "gimble_link", "pi")
import numpy as np
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    print("OK gimble programs (skipped: no desktop to open the programs' windows on)", flush=True)
    os._exit(0)
os.environ["QT_QPA_PLATFORM"] = "xcb"          # OpenCV brings its own windows; they need a real (or virtual) desktop
try:
    import cv2
    cv2.namedWindow("probe"); cv2.destroyAllWindows()
except Exception:  # noqa: BLE001  (no OpenCV here, or one without windows)
    print("OK gimble programs (skipped: no OpenCV with windows here)", flush=True)
    os._exit(0)

# ---- what the add-on carries for the Pi
have = sorted(os.path.relpath(os.path.join(dp, f), PI).replace(os.sep, "/") for dp, dn, fn in os.walk(PI) for f in fn if "__pycache__" not in dp)
for need in ("Gimble.desktop", "Record data.desktop", "Test model.desktop", "README.md", "Tidy up (run once on Windows).bat", "app/VERSION",
             "app/gimble_menu.py", "app/gimble_pi.py", "app/gimble_detect.py", "app/gimble_paths.py", "app/gimble_tidy.py", "app/setup_pi.sh",
             "app/calibrate_lidar_camera.py", "app/lidar_camera_overlay.py", "app/lidar_receiver.py", "app/lidar_udp_reader.py",
             "app/view_dataset.py", "app/measure_targets.py", "app/calib_selftest.py"):
    assert need in have, need
assert not [f for f in have if f.startswith(("settings/", "model/", "dataset/"))], "no calibration, model or recording of the rig is in the program"
for f in ("Gimble.desktop", "Record data.desktop", "Test model.desktop"):
    t = open(os.path.join(PI, f), encoding="utf-8").read()
    assert "\r" not in t and '-ipath "*/app/gimble_' in t and "logs/gimble_log.txt" in t, f          # finds the program in app/, not an old copy
bat = open(os.path.join(PI, "Tidy up (run once on Windows).bat"), newline="").read()
assert bat.count("\r\n") > 20 and "\n" not in bat.replace("\r\n", ""), "Windows line ends"
doing = [l.strip() for l in bat.split("\r\n") if l.strip() and not l.strip().lower().startswith(("rem", "echo"))]
for word in ("rmdir", "rd ", "format", "dataset\\", '"dataset"', "calibration_data", "model", "test_videos", "captures", "*"):
    assert not [l for l in doing if word in l.lower()], word                  # it only moves named files of the old layout
assert [l for l in doing if "del " in l] == ['(goto) 2>nul & del "%~f0"'], "the only thing it deletes is itself, at the end"
assert 'if not exist "app\\gimble_menu.py"' in bat and sum("move /y" in l for l in doing) == 4, [l for l in doing if "move" in l]

# ---- a drive in the OLD layout (as it was), with things recorded on it; then the new programs are put next to them
T = tempfile.mkdtemp(prefix="opara_gp_")
ROOT = os.path.join(T, "media", "user", "DRIVE6", "Gimble_Pi")
os.makedirs(ROOT)
OLD_PROGRAMS = ["calib_selftest.py", "calibrate_lidar_camera.py", "gimble_detect.py", "gimble_pi.py", "lidar_camera_overlay.py", "lidar_receiver.py",
                "lidar_udp_reader.py", "measure_targets.py", "view_dataset.py", "setup_pi.sh", "start_gimble.sh", "README_PI.md", "1 Start Gimble.desktop",
                "2 Calibrate.desktop", "3 View Recorded Data.desktop", "4 Measure Wall Targets.desktop", "5 First-Time Setup.desktop", "6 Detect.desktop"]
for f in OLD_PROGRAMS:
    open(os.path.join(ROOT, f), "w").write("old " + f)
W, H = 640, 480
json.dump({"camera_index": 0, "resolution": {"width": W, "height": H}, "camera_matrix": [[400, 0, 320], [0, 400, 240], [0, 0, 1]],
           "distortion_coefficients": [0, 0, 0, 0, 0]}, open(os.path.join(ROOT, "camera_intrinsics.json"), "w"))
json.dump({"axis_map_rows_are_camera_xyz_in_lidar_axes": [[0, -1, 0], [0, 0, -1], [1, 0, 0]], "camera_position_m": [0, 0, 0], "yaw_pitch_roll_deg": [0, 0, 0],
           "calibration": {"saved": "2026-09-29 23:32:15", "views": 20}}, open(os.path.join(ROOT, "lidar_camera_extrinsics.json"), "w"))
open(os.path.join(ROOT, "lidar_camera_extrinsics.json.bak"), "w").write("bak")
json.dump({"range_min_m": 0.2, "range_max_m": 12.0}, open(os.path.join(ROOT, "gimble_settings.json"), "w"))
open(os.path.join(ROOT, "target_layout.json"), "w").write("{}")
open(os.path.join(ROOT, "gimble_log.txt"), "w").write("old log\n")
os.makedirs(os.path.join(ROOT, "__pycache__")); open(os.path.join(ROOT, "__pycache__", "gimble_pi.cpython-311.pyc"), "wb").write(b"x")
for s in ("20261002_160105", "20261002_183309"):
    for sub in ("images", "depth", "lidar"):
        os.makedirs(os.path.join(ROOT, "dataset", s, sub))
        open(os.path.join(ROOT, "dataset", s, sub, "000001.bin"), "wb").write(os.urandom(500))
    open(os.path.join(ROOT, "dataset", s, "index.csv"), "w").write("idx\n1\n")
os.makedirs(os.path.join(ROOT, "calibration_data", "20261001_214736")); open(os.path.join(ROOT, "calibration_data", "20261001_214736", "calibration_session.json"), "w").write("{}")
os.makedirs(os.path.join(ROOT, "model")); open(os.path.join(ROOT, "model", "gimble_model.onnx"), "wb").write(b"MODEL")
json.dump({"names": ["person"], "imgsz": 640, "round": 5}, open(os.path.join(ROOT, "model", "gimble_model.json"), "w"))
os.makedirs(os.path.join(T, "media", "user", "DRIVE6", "captures")); open(os.path.join(T, "media", "user", "DRIVE6", "captures", "a.jpg"), "wb").write(b"cap")
open(os.path.join(ROOT, "my notes.txt"), "w").write("mine")
def recorded():
    out = {}
    for top in ("dataset", "calibration_data", "model"):
        for dp, dn, fn in os.walk(os.path.join(ROOT, top)):
            for f in fn:
                out[os.path.relpath(os.path.join(dp, f), ROOT)] = hashlib.sha256(open(os.path.join(dp, f), "rb").read()).hexdigest()
    return out
BEFORE = recorded()
for dp, dn, fn in os.walk(PI):
    dn[:] = [d for d in dn if d != "__pycache__"]
    for f in fn:
        dest = os.path.join(ROOT, os.path.relpath(os.path.join(dp, f), PI))
        os.makedirs(os.path.dirname(dest), exist_ok=True); shutil.copyfile(os.path.join(dp, f), dest)

sys.path.insert(0, os.path.join(ROOT, "app"))
import gimble_paths as gpaths, gimble_tidy
assert gpaths.ROOT == ROOT and gpaths.APP == os.path.join(ROOT, "app") and gpaths.MODEL_FILE == os.path.join(ROOT, "model", "gimble_model.onnx")
assert gpaths.DATASET == os.path.join(ROOT, "dataset") and gpaths.TEST_VIDEOS == os.path.join(ROOT, "test_videos") and gpaths.version() == open(os.path.join(PI, "app", "VERSION")).read().strip()
# a setting that still lies in the main folder is used (copied to settings/), so the calibration is not lost by the move
p = gpaths.setting("camera_intrinsics.json")
assert p == os.path.join(ROOT, "settings", "camera_intrinsics.json") and json.load(open(p))["resolution"]["width"] == W and os.path.exists(os.path.join(ROOT, "camera_intrinsics.json"))

# ---- the tidy-up: the old layout's files go to old/before_tidy, nothing recorded is touched, a second time does nothing
n = gimble_tidy.tidy()
assert n == len(OLD_PROGRAMS) + 5 + 1 + 1 + 1, n                 # the old programs and launchers, 5 settings, the log, the Windows .bat, __pycache__
assert sorted(os.listdir(ROOT)) == ["Gimble.desktop", "README.md", "Record data.desktop", "Test model.desktop", "app", "calibration_data", "dataset",
                                    "logs", "model", "my notes.txt", "old", "settings"], sorted(os.listdir(ROOT))
old = os.path.join(ROOT, "old", "before_tidy")
assert open(os.path.join(old, "gimble_pi.py")).read() == "old gimble_pi.py" and os.path.isdir(os.path.join(old, "__pycache__"))
assert sorted(os.listdir(os.path.join(ROOT, "settings"))) == ["camera_intrinsics.json", "gimble_settings.json", "lidar_camera_extrinsics.json",
                                                             "lidar_camera_extrinsics.json.bak", "target_layout.json"]
assert open(os.path.join(ROOT, "logs", "gimble_log_before_tidy.txt")).read() == "old log\n"
assert recorded() == BEFORE and open(os.path.join(ROOT, "my notes.txt")).read() == "mine", "recordings, calibration captures, the model and your own files are untouched"
assert open(os.path.join(T, "media", "user", "DRIVE6", "captures", "a.jpg"), "rb").read() == b"cap"
assert gimble_tidy.tidy() == 0

# ---- stand-ins for the camera and the LiDAR
frames = []
for k in range(4):
    img = np.full((H, W, 3), 60 + 30 * k, np.uint8); cv2.rectangle(img, (200 + 20 * k, 150), (300 + 20 * k, 400), (40, 200, 240), -1); frames.append(img)
state = {"i": 0}
class FakeCap:
    def __init__(self, idx, *a): self.ok = idx == 0
    def isOpened(self): return self.ok
    def set(self, *a): return True
    def read(self):
        time.sleep(0.02); state["i"] = int(time.time() * 4) % len(frames)
        return True, frames[state["i"]].copy()
    def release(self): pass
cv2.VideoCapture = FakeCap
rng = np.random.default_rng(1)
cloud = np.column_stack([rng.uniform(2.0, 6.0, 4000), rng.uniform(-2, 2, 4000), rng.uniform(-1, 1, 4000), np.ones(4000)])     # x forward, 2-6 m away
class FakeRx:
    def __init__(self, *a, **k): pass
    def start(self): pass
    def stop(self): pass
    def alive(self, within=1.0): return True
    def snapshot(self, window=None, t_end=None): return cloud
import gimble_pi as gp
gp.LidarReceiver = FakeRx
def direct(app, steps):
    def run():
        t_end = time.time() + 60
        while app.frame is None and time.time() < t_end:
            time.sleep(0.05)
        t0 = time.time()
        for delay, fn in steps:
            time.sleep(max(0.0, t0 + delay - time.time())); fn()
    threading.Thread(target=run, daemon=True).start()

# ---- Record data: a session in dataset/, with the calibration and range read from settings/
app = gp.App(gp.build_parser().parse_args(["--windowed"]))
assert (app.rmin, app.rmax) == (0.2, 12.0) and "Calibrated 2026-09-29, 20 views" in app.calib_note and app.session_root == os.path.join(ROOT, "dataset")
shots = {}
direct(app, [(0.8, lambda: app.press("rec")), (2.3, lambda: shots.update(rec=app.compose(app.frame))), (2.6, lambda: app.press("rec")),
             (3.2, lambda: setattr(app, "running", False))])
app.run()
new = sorted(set(os.listdir(os.path.join(ROOT, "dataset"))) - {"20261002_160105", "20261002_183309"})
assert len(new) == 1, new
S = os.path.join(ROOT, "dataset", new[0])
rows = list(csv.DictReader(open(os.path.join(S, "index.csv"))))
assert 3 <= len(rows) <= 9 and all(os.path.isfile(os.path.join(S, r["image"])) and os.path.isfile(os.path.join(S, r["depth"])) and os.path.isfile(os.path.join(S, r["lidar"])) for r in rows)
assert int(rows[0]["depth_pixels"]) > 500 and json.load(open(os.path.join(S, "meta.json")))["depth_range_m"] == [0.2, 12.0]
d = cv2.imread(os.path.join(S, rows[0]["depth"]), cv2.IMREAD_UNCHANGED); assert d.dtype == np.uint16 and 2000 <= d[d > 0].min() and d.max() <= 6100
assert shots["rec"].shape == (480, 800, 3) and "Recording" in open(gpaths.LOG_FILE).read() and "samples saved" in open(gpaths.LOG_FILE).read()
now = recorded(); assert all(now.get(k) == v for k, v in BEFORE.items()), "an old recording is not changed by a new one"

# ---- Test model: a stand-in model that finds one box 4 m away; REC VIDEO records the picture and the predictions
import gimble_detect as gd
import onnx
from onnx import helper, numpy_helper, TensorProto
def write_model(path):
    """A real (tiny) model file in the Gimble's format: whatever the picture, one person at 0.91 and a second box below any threshold."""
    dets = np.zeros((300, 6), np.float32); dets[0] = (200, 230, 330, 500, 0.91, 0); dets[1] = (10, 10, 60, 60, 0.10, 0)      # in the letterboxed 640 x 640
    dist = np.zeros(300, np.float32); dist[0] = 4.2
    g = helper.make_graph([helper.make_node("Constant", [], ["dets"], value=numpy_helper.from_array(dets)),
                           helper.make_node("Constant", [], ["dist"], value=numpy_helper.from_array(dist))], "gimble",
                          [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
                          [helper.make_tensor_value_info("dets", TensorProto.FLOAT, [300, 6]), helper.make_tensor_value_info("dist", TensorProto.FLOAT, [300])])
    onnx.save(helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)], ir_version=9), path)
write_model(gpaths.MODEL_FILE)
def make(meta):
    json.dump(meta, open(os.path.join(ROOT, "model", "gimble_model.json"), "w"))
    a = gd.DetApp(gd.build_parser().parse_args(["--windowed"]))
    assert a.sess is not None and a.model_msg == "", a.model_msg          # the model in model/ is loaded as the Gimble does
    return a
app = make({"names": ["person"], "imgsz": 640, "round": 5})
assert app.args.model == gpaths.MODEL_FILE and app.has_dist and app.model_label() == "round 5" and app.live_keys[0] == "rec"
assert app.label_for("rec")[0] == "REC VIDEO"
direct(app, [(1.0, lambda: app.press("rec")), (1.3, lambda: shots.update(label=app.label_for("rec")[0])), (3.2, lambda: app.press("rec")),
             (3.6, lambda: setattr(app, "running", False))])
app.run()
V = os.path.join(ROOT, "test_videos")
vids = sorted(f for f in os.listdir(V) if f.endswith((".mp4", ".avi")))
assert len(vids) == 1 and shots["label"] == "STOP", (vids, shots.get("label"))
stem = os.path.splitext(vids[0])[0]
rows = list(csv.DictReader(open(os.path.join(V, stem + ".csv"))))
frames_n = len({r["frame"] for r in rows})
assert 12 <= frames_n <= 26, frames_n                                # about 2 seconds at 10 frames a second
r0 = rows[0]
assert r0["class"] == "person" and abs(float(r0["confidence"]) - 0.91) < 0.01 and abs(float(r0["model_distance_m"]) - 4.2) < 0.01
assert [int(r0[k]) for k in ("x1", "y1", "x2", "y2")] == [200, 150, 330, 420], r0                  # back in the camera picture's pixels
assert 2.0 <= float(r0["lidar_distance_m"]) <= 6.0, "the LiDAR's own distance inside the box is beside the model's"
info = json.load(open(os.path.join(V, stem + ".json")))
assert info["fps"] == 10.0 and info["frame_size"] == [640, 480] and info["model"]["round"] == 5 and info["video"] == vids[0]
assert os.path.getsize(os.path.join(V, vids[0])) > 20000 and "Video saved: test_videos/" in open(gpaths.LOG_FILE).read()

# a model that only finds boxes: no distance of its own on the screen or in the table
app = make({"names": ["person"], "imgsz": 640, "round": "Small 2026-11-11 02:59", "label": "Small 2026-11-11 02:59", "kind": "assist", "has_distance": False})
assert not app.has_dist and app.model_label() == "Small 2026-11-11 02:59"
direct(app, [(0.8, lambda: app.press("rec")), (2.0, lambda: app.press("quit")), (2.1, lambda: app.press("quit"))])       # QUIT (twice) while recording: the video is finished
app.run()
vids2 = sorted(f for f in os.listdir(V) if f.endswith((".mp4", ".avi")))
assert len(vids2) == 2
rows = list(csv.DictReader(open(os.path.join(V, os.path.splitext(vids2[1])[0] + ".csv"))))
assert rows and rows[0]["model_distance_m"] == "" and rows[0]["lidar_distance_m"] != ""
assert "boxes only - no distance of its own" in open(gpaths.LOG_FILE).read()

# ---- the start screen: says what is on the drive; each button starts the right program; a failed start is said
import gimble_menu as gm
m = gm.Menu(gm.build_parser().parse_args(["--windowed"]))
assert m.rec[0] == 3 and m.model[0] == "Small 2026-11-11 02:59" and "boxes only" in m.model[1] and m.videos == 2 and m.cal == ("Calibrated 2026-09-29, 20 views", True)
img = m.compose(); assert img.shape == (480, 800, 3) and [k for k, _r in m.buttons] == ["record", "test", "calibrate", "view", "measure", "setup", "quit"]
big = {k: r for k, r in m.buttons}
assert (big["record"][2] - big["record"][0]) > 300 and (big["record"][3] - big["record"][1]) > 200, "the two things the rig is for are the big buttons"
cmds = {k: m.command(k) for k in gm.PROGRAMS}
assert cmds["record"][1:] == [os.path.join(ROOT, "app", "gimble_pi.py"), "--screen", "800x480", "--windowed"]
assert cmds["test"][1] == os.path.join(ROOT, "app", "gimble_detect.py") and cmds["calibrate"][1:3] == [os.path.join(ROOT, "app", "gimble_pi.py"), "--calibrate"]
assert cmds["view"][1:] == [os.path.join(ROOT, "app", "view_dataset.py")] and cmds["measure"][1:] == [os.path.join(ROOT, "app", "measure_targets.py")]
started = []
m.start = lambda key: (started.append(key), 0)[1]
m.close_window = m.open_window = lambda: None
x0, y0, x1, y1 = big["test"]
m.pending = None; m.on_mouse(cv2.EVENT_LBUTTONDOWN, (x0 + x1) // 2, (y0 + y1) // 2, 0, None); assert m.pending == "test"
m.do("test"); m.do("record"); assert started == ["test", "record"]
m.start = lambda key: 3
m.do("record"); assert "ended with a problem (code 3)" in m.msg and "logs/gimble_log.txt" in m.msg
os.remove(gpaths.MODEL_FILE); m.refresh(); started.clear(); m.start = lambda key: (started.append(key), 0)[1]
m.do("test"); assert started == [] and "No model on the drive yet" in m.msg and m.model[0] == "No model yet", "without a model the test is not started; it says how to get one"
m.do("quit"); assert not m.running

shutil.rmtree(T, ignore_errors=True)
print("OK gimble programs", flush=True)
os._exit(0)
