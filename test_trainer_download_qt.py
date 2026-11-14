import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
"""The Trainer window downloads torch and ultralytics for OpenPara's own Python: the question when the tab finds them missing (with the size,
and a GPU / CPU choice only when an NVIDIA GPU is there), the progress row, Cancel, a failure said in words, the check running again by
itself, the buttons, removing, and a Python you picked yourself never being offered a download.  pip is pointed at fake wheels."""
import os, sys, tempfile, time, zipfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
TMP = tempfile.mkdtemp(prefix="opara_tdl_")
os.environ["OPARA_USER_DIR"] = os.path.join(TMP, "user")
for p in (HERE, os.path.join(HERE, "addons_src", "annotator", "app"), os.path.join(HERE, "addons_src", "trainer")):
    sys.path.insert(0, p)
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import trainer_core as tc, trainer_tab as tt
tc.NEED_FREE_GB = {k: 0.01 for k in tc.NEED_FREE_GB}       # not dependent on how much room this computer has

MSG, ASKED, ANSWER = [], [], {"kind": "cpu"}
QMessageBox.information = staticmethod(lambda p, t, x, *a, **k: MSG.append((t, x)))
QMessageBox.warning = staticmethod(lambda p, t, x, *a, **k: MSG.append(("WARN " + t, x)))
QMessageBox.question = staticmethod(lambda *a, **k: ASK["answer"])
ASK = {"answer": QMessageBox.StandardButton.Yes}
tt.TrainerTab._ask_download = lambda self, text, choices: (ASKED.append((text, choices)), ANSWER["kind"])[1]


def wait(cond, secs=60, what=""):
    t0 = time.time()
    while not cond():
        app.processEvents(); time.sleep(0.05)
        assert time.time() - t0 < secs, "timed out " + what


def wheel(index, name, version, requires=(), files=None):
    path = os.path.join(index, f"{name}-{version}-py3-none-any.whl")
    with zipfile.ZipFile(path, "w") as z:
        for fn, text in (files or {f"{name}/__init__.py": f'__version__ = "{version}"\n'}).items():
            z.writestr(fn, text)
        z.writestr(f"{name}-{version}.dist-info/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n" + "".join(f"Requires-Dist: {r}\n" for r in requires))
        z.writestr(f"{name}-{version}.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{name}-{version}.dist-info/RECORD", "")


idx = os.path.join(TMP, "index"); os.makedirs(idx)
wheel(idx, "torch", "9.9.0", [], {"torch/__init__.py": '__version__ = "9.9.0"\nclass version:\n    cuda = None\nclass cuda:\n    @staticmethod\n    def is_available():\n        return False\n'})
wheel(idx, "torchvision", "9.9.1", ["torch==9.9.0"])
wheel(idx, "ultralytics", "9.9.9", ["torch>=1.8", "torchvision>=0.9"])
os.environ["OPARA_TRAIN_PIP_ARGS"] = f'--no-index --find-links "{idx}"'
os.environ["PATH"] = os.path.join(TMP, "emptybin") + os.pathsep + os.environ["PATH"]    # no nvidia-smi: no GPU
os.makedirs(os.path.join(TMP, "emptybin"))

# ---- the tab opens, scans, finds that OpenPara's own Python has neither, and asks once - with the size, and no GPU question without a GPU
w = tt.make_tab()
w.show()
wait(lambda: w.env is not None, what="scan")
wait(lambda: ASKED, what="the question")
text, choices = ASKED[0]
assert "torch and ultralytics" in text and "No NVIDIA GPU was found" in text and tc.DOWNLOAD_TEXT["cpu"] in text and "you can keep working" in text, text
assert [k for _l, k in choices] == ["cpu"] and tc.DOWNLOAD_TEXT["cuda"] not in text, choices
# it said yes: the download runs in the background, the row shows what it is doing and Cancel works
wait(lambda: w._pkg is None and any(t == "Download" for t, _x in MSG), what="download")
assert "torch 9.9.0 and ultralytics 9.9.9 are installed" in MSG[-1][1] and "CPU version" in MSG[-1][1], MSG[-1]
assert w.env["ok"] and w.env["torch"] == "9.9.0" and w.env["python"] == sys.executable
assert "Training is not possible" not in w.env_label.text()
assert w.btn_pkg_install.isHidden() and not w.btn_pkg_remove.isHidden() and w.pkg_box.isHidden()
assert "torch 9.9.0" in w.py_box.currentText() and len(ASKED) == 1, "asked once, on its own"
assert tc.has_packages()
w.btn_train.setEnabled(True)

# ---- the button asks again later; removing is confirmed, takes the packages away and does not ask on its own again
ASK["answer"] = QMessageBox.StandardButton.No
w.remove_downloaded(); assert tc.has_packages(), "No keeps them"
ASK["answer"] = QMessageBox.StandardButton.Yes
w.remove_downloaded()
wait(lambda: w.env is not None and not w.env["ok"] and not tc.has_packages(), what="rescan after removing")
assert "Training is not possible" in w.env_label.text() and "press the button below" in w.env_label.text()
assert not w.btn_pkg_install.isHidden() and w.btn_pkg_remove.isHidden() and w.btn_pkg_install.text() == "Download torch and ultralytics..."
pump = lambda n=10: [(app.processEvents(), time.sleep(0.05)) for _ in range(n)]
pump(12); assert len(ASKED) == 1, "removing on purpose is not followed by the question again"

# ---- an NVIDIA GPU: the question offers both, the GPU one first
tc.nvidia_gpu = lambda: "NVIDIA GeForce RTX 4090"
calls = []
real_install = tc.install_packages
def fake_install(kind, need_torch=True, need_ultralytics=True, progress=None, stop=None):
    calls.append((kind, need_torch, need_ultralytics))
    progress("Downloading torch-9.9.0 (2.5 GB) ...")
    t0 = time.time()
    while not stop():
        time.sleep(0.05)
        assert time.time() - t0 < 30
    raise tc.Cancelled()
tc.install_packages = fake_install
ANSWER["kind"] = "cuda"
w.offer_download()
text, choices = ASKED[-1]
assert "NVIDIA GeForce RTX 4090" in text and tc.DOWNLOAD_TEXT["cuda"] in text and tc.DOWNLOAD_TEXT["cpu"] in text, text
assert [k for _l, k in choices] == ["cuda", "cpu"] and choices[0][0] == "Download the GPU version", choices
# ... it is downloading: the row shows it, the buttons step aside, a second press does nothing, Cancel ends it and nothing is installed
wait(lambda: w._pkg is not None and w._pkg["text"].startswith("Downloading torch-9.9.0"), what="progress text")
assert not w.pkg_box.isHidden() and w.btn_pkg_install.isHidden() and w.btn_pkg_remove.isHidden()
w._pkg_show(); assert "Downloading torch-9.9.0 (2.5 GB)" in w.pkg_text.text() and w.pkg_text.text().endswith(")")
n = len(ASKED); w.offer_download(); assert len(ASKED) == n, "no second download while one runs"
w.cancel_download()
assert not w.pkg_cancel.isEnabled() and "Cancelling" in w._pkg["text"]
wait(lambda: w._pkg is None, what="cancel")
assert calls == [("cuda", True, True)] and "cancelled" in w.status.text() and w.pkg_box.isHidden() and not tc.has_packages()
assert not w.btn_pkg_install.isHidden(), "the button is back"

# ---- a failure is said in words and the button stays
def failing(kind, need_torch=True, need_ultralytics=True, progress=None, stop=None):
    raise tc.InstallError("The download did not work (pip ended with code 1):\nERROR: No matching distribution found for torch")
tc.install_packages = failing
ANSWER["kind"] = "cpu"
MSG.clear(); w.offer_download()
wait(lambda: w._pkg is None and MSG, what="failure")
assert MSG[-1][0] == "WARN Download" and "No matching distribution" in MSG[-1][1] and not w.btn_pkg_install.isHidden()
def exploding(*a, **k):
    raise RuntimeError("boom")
tc.install_packages = exploding
MSG.clear(); w.offer_download(); wait(lambda: w._pkg is None and MSG, what="unexpected failure")
assert "failed unexpectedly: boom" in MSG[-1][1]

# ---- closing the tab while it downloads asks, and then stops it
tc.install_packages = fake_install
w.offer_download(); wait(lambda: w._pkg is not None and w._pkg["text"].startswith("Downloading"), what="progress again")
ASK["answer"] = QMessageBox.StandardButton.No
assert w.can_close() is False and not w._pkg["stop"]
ASK["answer"] = QMessageBox.StandardButton.Yes
state = w._pkg
assert w.can_close() is True and state["stop"]
wait(lambda: w._pkg is None, what="stopped by closing")

# ---- a Python you picked yourself: no offer, no button
tc.install_packages = real_install
other = os.path.join(TMP, "other_python"); open(other, "w").write(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n'); os.chmod(other, 0o755)
w.env = tc.check_env(other); w._update_env_view()
assert not w.env["ok"] and w.btn_pkg_install.isHidden() and "press the button below" not in w.env_label.text()
n = len(ASKED); w.offer_download(); assert len(ASKED) == n, "never installs into a Python the person chose"

# ---- only ultralytics missing: the question says so, is smaller, and torch is not asked for
tc.nvidia_gpu = lambda: None
w.env = {"python": sys.executable, "torch": "2.6", "ultralytics": None, "cuda": False, "gpu": None, "ok": False, "problems": ["x"], "warnings": []}
w._update_env_view()
assert w.btn_pkg_install.text() == "Download ultralytics..." and not w.btn_pkg_install.isHidden()
tc.install_packages = fake_install; calls.clear()
w.offer_download()
assert "Training needs ultralytics, and" in ASKED[-1][0] and "about 0.2 GB" in ASKED[-1][0] and "NVIDIA" not in ASKED[-1][0], ASKED[-1][0]
wait(lambda: calls, what="ultralytics only"); assert calls == [("cpu", False, True)]
w.cancel_download(); wait(lambda: w._pkg is None)

print("trainer download qt ok")
import sys as _s; _s.stdout.flush()
shutil.rmtree(TMP, ignore_errors=True)
os._exit(0)
