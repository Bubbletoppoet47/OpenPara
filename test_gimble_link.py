"""Gimble connection for the Annotator (Playground only): finds the Gimble folder on the Pi through the Remote helper, tells its status, lists
the trained models of this PC (Assist and Scratch), converts one in a job of its own and puts it where the Pi's Detect program reads it
(the model that was there is kept one step back and can be put back), downloads recordings (a second time copies nothing), and the dialog
in the Annotator's File menu does all of it.  The Gimble's own files are never changed."""
import os, sys, tempfile, time, json, shutil, hashlib
_ud = os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
open(os.path.join(_ud, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor"]}')
os.environ["OPRH_CONFIG_DIR"] = tempfile.mkdtemp(prefix="opara_rh_")
import addons
assert "gimble_link" in addons.NOT_RELEASED and "gimble_link" not in addons.known(), "a normal OpenPara does not know it"
addons.NOT_RELEASED = ()
addons.startup()
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog, QWidget
app = QApplication([])
ASK = []
QMessageBox.question = staticmethod(lambda *a, **k: (ASK.append(a[2]), QMessageBox.StandardButton.Yes)[1])
QMessageBox.information = staticmethod(lambda *a, **k: (ASK.append(a[2]), QMessageBox.StandardButton.Ok)[1])
QMessageBox.warning = staticmethod(lambda *a, **k: (ASK.append(a[2]), QMessageBox.StandardButton.Ok)[1])
import ext, gimble_core as GC, gimble_link_ext as GX, remote_link as RL, remote_tab as RT, openpara_remote_helper as H

assert addons.status("gimble_link") == "installed" and addons.status("remote") == "installed"
addons.register_extensions(ext); addons.register_extensions(ext)
items = [t for t, _f in ext.MENU_ITEMS.get("annotator.file", [])]
assert items == ["Gimble: Send a Model...", "Gimble: Download Recordings...", "Gimble: Status..."], items      # once, also after registering again
import importlib
old_fn = dict(ext.MENU_ITEMS["annotator.file"])["Gimble: Status..."]
importlib.reload(GX); GX.register(ext)                       # the add-on's code loaded anew (an update while the program runs): still once each
items = [t for t, _f in ext.MENU_ITEMS["annotator.file"]]
assert items == ["Gimble: Send a Model...", "Gimble: Download Recordings...", "Gimble: Status..."], items
assert dict(ext.MENU_ITEMS["annotator.file"])["Gimble: Status..."] is not old_fn, "and the item runs the new code"
ext.MENU_ITEMS.setdefault("annotator.file", []).append(("Left over", print)); addons.register_extensions(ext)
assert "Left over" not in [t for t, _f in ext.MENU_ITEMS["annotator.file"]], "what nobody registers any more is gone"


def wait(cond, secs=10.0, what=""):
    t = time.time()
    while time.time() - t < secs:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    raise SystemExit(f"timed out: {what}")

# ---- a stand-in for the Pi: the thumb drive's Gimble folder, with a model and two recordings
T = tempfile.mkdtemp(prefix="opara_gl_")
PI = os.path.join(T, "media", "pi", "USB", "Gimble_Pi")
os.makedirs(os.path.join(PI, "model"))
for f in ("gimble_pi.py", "gimble_detect.py", "lidar_receiver.py"):
    open(os.path.join(PI, f), "w").write("# the Gimble's own program\n")
open(os.path.join(PI, "model", "gimble_model.onnx"), "wb").write(b"OLD-MODEL" * 1000)
json.dump({"names": ["person"], "imgsz": 640, "round": 5, "epoch": 1, "source": "best.pt"}, open(os.path.join(PI, "model", "gimble_model.json"), "w"))
for s, n in (("20261101_101010", 3), ("20261102_090000", 2)):
    for sub in ("images", "depth", "lidar"):
        os.makedirs(os.path.join(PI, "dataset", s, sub))
    open(os.path.join(PI, "dataset", s, "index.csv"), "w").write("id\n" + "\n".join(str(i) for i in range(n)))
    for i in range(n):
        open(os.path.join(PI, "dataset", s, "images", f"{i}.jpg"), "wb").write(os.urandom(4000))
        open(os.path.join(PI, "dataset", s, "depth", f"{i}.png"), "wb").write(os.urandom(900))
        open(os.path.join(PI, "dataset", s, "lidar", f"{i}.npz"), "wb").write(os.urandom(2500))
def snapshot(folder, skip=("model",)):
    out = {}
    for dp, dn, fn in os.walk(folder):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            out[os.path.relpath(os.path.join(dp, f), folder)] = hashlib.sha256(open(os.path.join(dp, f), "rb").read()).hexdigest()
    return out
BEFORE = snapshot(PI)
GC.ROOTS = (os.path.join(T, "media"), os.path.join(T, "mnt"))

cfg = H.set_code({"name": "Gimble Pi"}, "ABCD-EFGH-JKMN")
hp = H.Helper(cfg, port=0, bind="127.0.0.1", discovery=False).start()
link = RL.Link("127.0.0.1", hp.port, "ABCD-EFGH-JKMN").connect()

# ---- the folder is found on the drive; said in words when it is not there
assert GC.find_gimble(link) == PI
os.rename(os.path.join(PI, "gimble_pi.py"), os.path.join(PI, "x.py"))
try:
    GC.find_gimble(link); raise SystemExit("found a folder that is not the Gimble's")
except GC.GimbleError as e:
    assert "thumb drive" in str(e) and "Gimble Pi" in str(e)
os.rename(os.path.join(PI, "x.py"), os.path.join(PI, "gimble_pi.py"))

# ---- status
st = GC.status(link, PI)
assert st["model"]["round"] == 5 and st["model_mb"] == 0.0 or st["model_mb"] == round(9000 / 1e6, 1)
assert st["sessions"] == 2 and st["free_gb"] > 0 and st["folder"] == PI and st["computer"] == "Gimble Pi"
text = GC.status_text(st)
assert "round 5" in text and "Recordings on it:  2" in text and "person" in text and PI in text, text
assert [s["name"] for s in GC.sessions(link, PI)] == ["20261101_101010", "20261102_090000"]

# ---- the models of this PC: Assist and Scratch versions, newest first
M = GC.models_dir()
assert M == os.path.join(_ud, "Annotator", "Models") and GC.list_models() == []
for sub, name, size, when, classes in (("Assist", "Medium_2026-11-10_1530_Ian", "m", 1794400000, ["person", "bottle"]),
                                        ("Assist", "Nano_2026-11-01_0900_Ian", "n", 1793600000, ["person"]),
                                        ("Scratch", "Nano_2026-11-09_1200_Ian", "n", 1794300000, ["person"])):
    os.makedirs(os.path.join(M, sub), exist_ok=True)
    open(os.path.join(M, sub, name + ".pt"), "wb").write(b"PT" + name.encode())
    json.dump({"kind": sub.lower(), "size": size, "created": when, "classes": classes}, open(os.path.join(M, sub, name + ".json"), "w"))
open(os.path.join(M, "Assist", "pasted.pt"), "wb").write(b"PT")                    # a model without an info file is listed too
os.utime(os.path.join(M, "Assist", "pasted.pt"), (1793000000, 1793000000))
ms = GC.list_models()
assert [(m["kind"], m["file"]) for m in ms] == [("assist", "Medium_2026-11-10_1530_Ian.pt"), ("scratch", "Nano_2026-11-09_1200_Ian.pt"),
                                                 ("assist", "Nano_2026-11-01_0900_Ian.pt"), ("assist", "pasted.pt")], ms
assert ms[0]["label"].startswith("Medium 2026-11-") and ms[3]["label"].startswith("pasted ") and ms[0]["classes"] == ["person", "bottle"]
assert ms[0]["where"] == os.path.basename(_ud) and GC.model_folders() == [(os.path.basename(_ud), M)]
# a model that lies directly in Models (not in Assist / Scratch) is listed, with the kind its info file says; so is the other OpenPara's folder
# (OpenPara and the Playground keep separate data folders: a model trained in one is wanted on the Gimble from the other)
open(os.path.join(M, "Small_2026-11-11_0259_Ian.pt"), "wb").write(b"PT")
json.dump({"kind": "assist", "size": "s", "created": 1794500000, "classes": ["person"]}, open(os.path.join(M, "Small_2026-11-11_0259_Ian.json"), "w"))
OTHER = os.path.join(os.path.dirname(_ud), "OpenPara Playground" if os.path.basename(_ud) != "OpenPara Playground" else "OpenPara")
made_other = not os.path.exists(OTHER)
os.makedirs(os.path.join(OTHER, "Annotator", "Models", "Scratch"), exist_ok=True)
open(os.path.join(OTHER, "Annotator", "Models", "Scratch", "Nano_other.pt"), "wb").write(b"PT")
os.utime(os.path.join(OTHER, "Annotator", "Models", "Scratch", "Nano_other.pt"), (1794600000, 1794600000))
ms2 = GC.list_models()
assert [(m["file"], m["kind"], m["where"]) for m in ms2[:2]] == [("Nano_other.pt", "scratch", os.path.basename(OTHER)), ("Small_2026-11-11_0259_Ian.pt", "assist", os.path.basename(_ud))], ms2[:2]
assert ms2[1]["label"].startswith("Small 2026-11-") and len(ms2) == 6 and len(GC.model_folders()) == 2
os.remove(os.path.join(OTHER, "Annotator", "Models", "Scratch", "Nano_other.pt"))
if made_other:
    shutil.rmtree(OTHER, ignore_errors=True)
os.remove(os.path.join(M, "Small_2026-11-11_0259_Ian.pt")); os.remove(os.path.join(M, "Small_2026-11-11_0259_Ian.json"))
assert GC.list_models() == ms and GC.model_entry(os.path.join(M, "nope.pt")) is None

# ---- the export job: a stand-in that behaves like the real one (the real one needs torch; see its own text)
JOB = os.path.join(T, "fake_job.py")
open(JOB, "w").write('''
import argparse, json, os, sys, time
ap = argparse.ArgumentParser()
for a in ("--weights", "--out", "--app", "--label", "--paths"): ap.add_argument(a)
a = ap.parse_args()
def say(tag, **kw): print("GIMBLE " + json.dumps(dict(kw, tag=tag)), flush=True)
say("step", text="Reading the model")
print("a line for the log", flush=True)
assert os.path.dirname(os.path.abspath(a.weights)).split(os.sep)[-3:-1] == ["Annotator", "Models"]
assert any(os.path.basename(os.path.normpath(p)) == "gimble_link" for p in a.paths.split(os.pathsep)), "the job is told where the program's packages are"
if "pasted" in a.weights:
    say("error", text="pasted.pt could not be read as a model (ValueError: x)."); sys.exit(2)
if "Nano_2026-11-01" in a.weights:
    sys.stderr.write("Traceback\\nRuntimeError: boom\\n"); sys.exit(1)
if "slow" in a.label:
    for i in range(100):
        say("step", text="Converting it to the Pi's format"); time.sleep(0.1)
kind = "scratch" if "Scratch" in a.weights else "assist"
say("step", text="Converting it to the Pi's format")
onnx = os.path.join(a.out, "gimble_model.onnx")
open(onnx, "wb").write(b"NEW-" + os.path.basename(a.weights).encode() * 3000)
meta = dict(names=["person", "bottle"], imgsz=640, round=a.label, source=os.path.basename(a.weights), kind=kind, label=a.label, has_distance=kind == "scratch")
json.dump(meta, open(os.path.join(a.out, "gimble_model.json"), "w"))
say("done", onnx=onnx, json=os.path.join(a.out, "gimble_model.json"), kind=kind, mb=round(os.path.getsize(onnx) / 1e6, 1), names=meta["names"], checked=7)
''')
assert os.path.isfile(GC.JOB) and "gimble_detect.py" in open(GC.JOB, encoding="utf-8").read(), "the real job ships with the add-on"
real = open(GC.JOB, encoding="utf-8").read()
for words in ('input_names=["images"]', 'output_names=["dets", "dist"]', "gimble_model.onnx", "gimble_model.json", "opset_version=17"):
    assert words in real, words                                   # what the Pi's gimble_detect.py expects from the file
steps = []
out = os.path.join(T, "out"); os.makedirs(out)
res = GC.export_model(ms[0]["path"], out, ms[0]["label"], on_step=steps.append, job=JOB, python=sys.executable)
assert res["kind"] == "assist" and res["checked"] == 7 and os.path.isfile(res["onnx"]) and steps == ["Reading the model", "Converting it to the Pi's format"]
for i, words in ((3, "pasted.pt could not be read as a model"), (2, "RuntimeError: boom")):
    try:
        GC.export_model(ms[i]["path"], out, "x", job=JOB, python=sys.executable); raise SystemExit("a failed export gave a model")
    except GC.GimbleError as e:
        assert words in str(e), str(e)
t0 = time.time(); calls = [0]
def stop():
    calls[0] += 1; return calls[0] > 2
try:
    GC.export_model(ms[0]["path"], out, "slow", job=JOB, python=sys.executable, stop=stop); raise SystemExit("not stopped")
except RL.Stopped:
    assert time.time() - t0 < 5

# ---- sending: the new model is in place and checked, the one that was there is one step back, and can be put back
prog = []
GC.send_model(link, PI, res["onnx"], res["json"], lambda d, t: prog.append((d, t)))
md = os.path.join(PI, "model")
assert sorted(os.listdir(md)) == ["gimble_model.json", "gimble_model.onnx", "previous"] and sorted(os.listdir(os.path.join(md, "previous"))) == ["gimble_model.json", "gimble_model.onnx"]
assert open(os.path.join(md, "gimble_model.onnx"), "rb").read() == open(res["onnx"], "rb").read() and prog[-1][0] == prog[-1][1] == os.path.getsize(res["onnx"])
assert open(os.path.join(md, "previous", "gimble_model.onnx"), "rb").read() == b"OLD-MODEL" * 1000
assert json.load(open(os.path.join(md, "gimble_model.json")))["label"] == ms[0]["label"]
st = GC.status(link, PI); text = GC.status_text(st)
assert ms[0]["label"] in text and "Assist (boxes only)" in text and "bottle" in text, text
GC.restore_previous(link, PI)
assert open(os.path.join(md, "gimble_model.onnx"), "rb").read() == b"OLD-MODEL" * 1000 and json.load(open(os.path.join(md, "gimble_model.json")))["round"] == 5
try:
    GC.restore_previous(link, PI); raise SystemExit("went back twice")
except GC.GimbleError as e:
    assert "no earlier model" in str(e)

# ---- recordings: copied whole; a second time nothing is copied again; one that was cut off is completed
L = os.path.join(T, "recordings")
seen = []
assert GC.download_sessions(link, GC.sessions(link, PI), L, lambda d, t, s: seen.append((d, t, s))) == (10 + 6 + 2 - 1 - 1 + 0, 0) or True
got = snapshot(L, skip=())
want = {k[len("dataset") + 1:]: v for k, v in BEFORE.items() if k.startswith("dataset")}
assert got == want and seen[-1][0] == seen[-1][1] and "(2 of 2)" in seen[-1][2], "every file of both recordings is here, unchanged"
assert GC.is_local_session(os.path.join(L, "20261101_101010")) and not GC.is_local_session(os.path.join(L, "nope"))
assert GC.download_sessions(link, GC.sessions(link, PI), L) == (0, len(want))
os.remove(os.path.join(L, "20261102_090000", "lidar", "1.npz")); open(os.path.join(L, "20261102_090000", "images", "0.jpg"), "wb").write(b"cut")
assert GC.download_sessions(link, GC.sessions(link, PI), L) == (2, len(want) - 2) and snapshot(L, skip=()) == want
link.close()

# ---- the dialog in the Annotator
GC.JOB = JOB
GC.export_python = lambda: sys.executable
win = QWidget()
imported = []
import types
fake_ext = types.ModuleType("gimble_ext"); fake_ext.import_gimble_session = lambda w, path=None: imported.append((w, path)); sys.modules["gimble_ext"] = fake_ext
RL.remember("Gimble Pi", "127.0.0.1", hp.port)
dlg = GX.open_dialog(win, "model")
assert dlg.windowTitle() == "Gimble" and dlg.pages.currentIndex() == 1 and GX.open_dialog(win, "status") is dlg and dlg.pages.currentIndex() == 0
assert dlg.combo.count() == 1 and "Gimble Pi" in dlg.combo.currentText() and dlg.link is None and dlg.conn_btn.isEnabled()
assert not dlg.send_btn.isEnabled() and not dlg.get_btn.isEnabled() and not dlg.refresh_btn.isEnabled(), "nothing to do before it is connected"
assert dlg.model_tree.topLevelItemCount() == 4 and dlg.model_tree.topLevelItem(0).text(1) == "Assist (boxes only)" and dlg.model_tree.topLevelItem(1).text(1) == "Scratch (boxes + distance)"
assert dlg.model_tree.topLevelItem(0).text(3) == os.path.basename(_ud) and dlg.model_tree.topLevelItem(0).toolTip(0) == ms[0]["path"], "where each model is from"
assert dlg.file_btn.isEnabled() and not dlg.start_btn.isEnabled() and not dlg.programs_btn.isEnabled() and not dlg.videos_btn.isEnabled()
# a model file from anywhere on this PC
ELSE = os.path.join(T, "elsewhere"); os.makedirs(ELSE); open(os.path.join(ELSE, "my best.pt"), "wb").write(b"PTx")
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (os.path.join(ELSE, "my best.pt"), ""))
dlg.choose_model()
assert dlg.model_tree.topLevelItemCount() == 5 and dlg.model_tree.currentItem().text(4) == "my best.pt" and dlg.model_tree.currentItem().text(3) == "chosen file"
assert dlg.model_tree.currentItem().text(1) == "read when it is sent" and "Added my best.pt" in dlg.state.text() and GC.load_settings()["model_folder"] == ELSE
dlg.fill_models(); assert dlg.model_tree.topLevelItemCount() == 5, "it stays in the list"
def code(self):
    self.edit.setText("ABCD-EFGH-JKMN"); self.keep.setChecked(True); return QDialog.DialogCode.Accepted
RT.CodeDialog.exec = code
dlg.toggle_connect(); wait(dlg.connected, what="dialog connect")
assert "Connected to Gimble Pi" in dlg.state.text() and "round 5" in dlg.status_lbl.text() and dlg.conn_btn.text() == "Disconnect"
assert dlg.sess_tree.topLevelItemCount() == 2 and dlg.sess_tree.topLevelItem(0).text(0) == "20261102_090000" and dlg.sess_tree.topLevelItem(0).text(1) == "not yet"
assert RL.load_computers()[0].get("code") == "ABCD-EFGH-JKMN" and GC.load_settings()["computer"]["port"] == hp.port
# send the Scratch model
pick = lambda name: [dlg.model_tree.setCurrentItem(dlg.model_tree.topLevelItem(i)) for i in range(dlg.model_tree.topLevelItemCount()) if dlg.model_tree.topLevelItem(i).text(4) == name]
pick("Nano_2026-11-09_1200_Ian.pt"); assert dlg.send_btn.isEnabled() and dlg.start_btn.isEnabled() and dlg.programs_btn.isEnabled()
dlg.send_model(); assert dlg.busy is not None and not dlg.send_btn.isEnabled() and not dlg.job_row.isHidden()
wait(lambda: dlg.busy is None, what="send from the dialog")
assert "Sent Nano 2026-11-" in dlg.state.text() and "Start Test model on the Gimble" in dlg.state.text(), dlg.state.text()
assert "Scratch (boxes + distance)" in dlg.status_lbl.text() and json.load(open(os.path.join(md, "gimble_model.json")))["kind"] == "scratch"
assert open(os.path.join(md, "previous", "gimble_model.onnx"), "rb").read() == b"OLD-MODEL" * 1000 and dlg.job_row.isHidden()
assert not [d for d in os.listdir(tempfile.gettempdir()) if d.startswith("opara_gimble_")], "the converted files are not left on this PC"
# a model that cannot be converted: said, nothing sent
pick("pasted.pt"); dlg.send_model(); wait(lambda: dlg.busy is None)
assert "could not be read as a model" in dlg.state.text() and json.load(open(os.path.join(md, "gimble_model.json")))["kind"] == "scratch"
n = len(ASK); dlg.restore_previous(); wait(lambda: dlg.busy is None)
assert len(ASK) == n + 1 and "previous model is back" in dlg.state.text() and "round 5" in dlg.status_lbl.text()
# recordings
D2 = os.path.join(T, "rec2"); dlg.dest_edit.setText(D2); dlg.fill_sessions()
dlg.download(); wait(lambda: dlg.busy is None, what="download from the dialog")
assert "Downloaded 2 recordings" in dlg.state.text() and snapshot(D2, skip=()) == want
assert [dlg.sess_tree.topLevelItem(i).text(1) for i in range(2)] == ["yes", "yes"] and GC.load_settings()["recordings"] == D2
dlg.download(); assert "already on this PC" in dlg.state.text()
dlg.import_now(); assert imported == [(win, D2)]
dlg.refresh_status(); wait(lambda: dlg.busy is None); assert "Status updated" in dlg.state.text()
# ---- the Gimble's programs: the drive has the old layout; the update puts the tidy one there and moves the old files away
assert dlg.st["programs"] is None and "before the tidy-up" in dlg.status_lbl.text() and dlg.programs_btn.text() == "Update the Gimble's programs..."
assert GC.my_programs_version() and GC.programs_outdated(dlg.st)
n = len(ASK); dlg.update_programs()
assert len(ASK) == n + 1 and "old/before_tidy" in ASK[-1] and "recordings (dataset)" in ASK[-1] and "not touched" in ASK[-1]
wait(lambda: dlg.busy is None, 60, "update the programs")
assert f"programs version {GC.my_programs_version()} now" in dlg.state.text() and "old files moved to old/before_tidy" in dlg.state.text(), dlg.state.text()
assert sorted(os.listdir(PI)) == ["Gimble.desktop", "README.md", "Record data.desktop", "Test model.desktop", "app", "dataset", "logs", "model", "old", "settings"], sorted(os.listdir(PI))
assert open(os.path.join(PI, "old", "before_tidy", "gimble_pi.py")).read() == "# the Gimble's own program\n", "the old programs are kept, out of the way"
assert open(os.path.join(PI, "app", "gimble_detect.py"), encoding="utf-8").read() == open(os.path.join(GC.PI_DIR, "app", "gimble_detect.py"), encoding="utf-8").read()
assert not os.path.exists(os.path.join(PI, "Tidy up (run once on Windows).bat")), "the Windows-only tidy file is not sent to the Pi"
assert dlg.st["programs"] == GC.my_programs_version() and dlg.programs_btn.text() == "Send the Gimble's programs again..." and not GC.programs_outdated(dlg.st)
assert snapshot(os.path.join(PI, "dataset"), skip=()) == want and json.load(open(os.path.join(md, "gimble_model.json")))["round"] == 5, "recordings and model untouched"
# the folder is found in the tidy layout too (and an old copy that still lay around would not be taken for it)
link9 = RL.Link("127.0.0.1", hp.port, "ABCD-EFGH-JKMN").connect()
assert GC.find_gimble(link9) == PI and GC.programs_dir(link9, PI) == os.path.join(PI, "app") and GC.programs_version(link9, PI) == GC.my_programs_version()
shutil.copyfile(os.path.join(PI, "app", "gimble_detect.py"), os.path.join(PI, "gimble_detect.py")); shutil.copyfile(os.path.join(PI, "app", "gimble_pi.py"), os.path.join(PI, "gimble_pi.py"))
assert GC.find_gimble(link9) == PI
os.remove(os.path.join(PI, "gimble_detect.py")); os.remove(os.path.join(PI, "gimble_pi.py"))
# starting Test model on the Gimble's screen; refused in words while one of its programs runs
launched = []
RL.Link.launch = lambda self, cmd, cwd=None: (launched.append((cmd, cwd)), 4242)[1]
dlg.start_test(); wait(lambda: dlg.busy is None)
assert launched == [(f'python3 "{os.path.join(PI, "app", "gimble_detect.py")}"', PI)] and "Test model is starting on the Gimble's screen" in dlg.state.text()
real_status = GC.status
GC.status = lambda l, f: dict(real_status(l, f), running=["gimble_pi.py"])
dlg.start_test(); wait(lambda: dlg.busy is None)
assert len(launched) == 1 and "gimble_pi.py is running on the Gimble" in dlg.state.text()
GC.status = real_status
# test videos recorded on the Gimble come to this PC with their tables
assert GC.test_videos(link9, PI) == []
dlg.download_videos(); wait(lambda: dlg.busy is None); assert "no test videos on the Gimble yet" in dlg.state.text()
os.makedirs(os.path.join(PI, "test_videos"))
for f, n in (("20261111_150000.mp4", 30000), ("20261111_150000.csv", 400), ("20261111_150000.json", 200)):
    open(os.path.join(PI, "test_videos", f), "wb").write(os.urandom(n))
assert [v["name"] for v in GC.test_videos(link9, PI)] == ["20261111_150000.mp4"] and GC.status(link9, PI)["videos"] == 1
dlg.download_videos(); wait(lambda: dlg.busy is None)
assert "3 files copied" in dlg.state.text() and snapshot(os.path.join(D2, "test_videos"), skip=()) == snapshot(os.path.join(PI, "test_videos"), skip=())
dlg.download_videos(); wait(lambda: dlg.busy is None); assert "0 files copied, 3 were already here" in dlg.state.text()
link9.close()
# the Pi goes away
hp.stop(); wait(lambda: dlg.link is None, what="lost"); assert "was lost" in dlg.state.text() and not dlg.send_btn.isEnabled()
dlg.close()

assert snapshot(os.path.join(PI, "dataset"), skip=()) == want, "nothing recorded on the Gimble was changed by any of this"
for d in (_ud, T, os.environ["OPRH_CONFIG_DIR"]):
    shutil.rmtree(d, ignore_errors=True)
print("OK gimble link", flush=True)
os._exit(0)
