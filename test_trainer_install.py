"""The Trainer downloads torch and ultralytics for OpenPara's own Python (no Qt here; the window is in test_trainer_qt.py).

pip is pointed at a folder of fake wheels (OPARA_TRAIN_PIP_ARGS="--no-index --find-links ..."): a torch that says 9.9.0 and reports no GPU,
a torchvision, an ultralytics that asks for torch, torchvision, two small packages, one for another platform (marker) and one extra
(dev) - the last two do not exist in the folder, so pip would fail if the Trainer asked for them.  Checked: what is downloaded and what is
not (torch only once), the environment check and the training script seeing the packages, a Python you picked yourself NOT getting them,
cancel / failure / full disk leaving nothing behind, a torch that is there but cannot be loaded, removing, and the GPU question."""
import os, sys, shutil, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="opara_tinst_")
os.environ["OPARA_USER_DIR"] = os.path.join(TMP, "user")
TR = os.path.join(HERE, "addons_src", "trainer")
sys.path[:0] = [HERE, TR, os.path.join(HERE, "addons_src", "annotator", "app")]
import trainer_core as tc, paths


def wheel(index, name, version, requires=(), files=None):
    path = os.path.join(index, f"{name}-{version}-py3-none-any.whl")
    di = f"{name}-{version}.dist-info"
    meta = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n" + "".join(f"Requires-Dist: {r}\n" for r in requires)
    with zipfile.ZipFile(path, "w") as z:
        for fn, text in (files or {f"{name}/__init__.py": f'__version__ = "{version}"\n'}).items():
            z.writestr(fn, text)
        z.writestr(f"{di}/METADATA", meta)
        z.writestr(f"{di}/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{di}/RECORD", "")
    return path


TORCH_INIT = ('__version__ = "9.9.0"\nclass version:\n    cuda = None\nclass cuda:\n    @staticmethod\n    def is_available():\n        return False\n')


def make_index(name="index", torch_init=TORCH_INIT, skip=()):
    idx = os.path.join(TMP, name)
    os.makedirs(idx)
    for args in (("torch", "9.9.0", ["fakedep>=1.0"], {"torch/__init__.py": torch_init}),
                 ("torchvision", "9.9.1", ["torch==9.9.0"], None),
                 ("fakedep", "1.0", [], None),
                 ("fakedep2", "1.0", [], None),
                 ("fakedep4", "1.0", ["torch>=1"], None),                      # a dependency that asks for torch (like ultralytics-thop does)
                 ("ultralytics_thop", "9.0", ["torch"], None),
                 ("ultralytics", "9.9.9", ["torch>=1.8", "torchvision>=0.9", "fakedep2>=1.0", 'fakedep3; sys_platform == "nonexistent-os"',
                                          'fakeextra; extra == "dev"', "torch (>=1.8) ; python_version >= '3.8'", "fakedep4", "ultralytics-thop>=2.0.18"],
                  None)):
        if args[0] not in skip:
            wheel(idx, args[0], args[1], args[2], args[3])
    return idx


def use_index(idx):
    os.environ["OPARA_TRAIN_PIP_ARGS"] = f'--no-index --find-links "{idx}"'


def leftovers():
    d = tc.packages_dir()
    return [p for p in (d + ".new", d + ".download") if os.path.exists(p)]


def names(d):
    return sorted(n for n in os.listdir(d) if not n.endswith(".dist-info"))


# ---- where things live; only OpenPara's own Python is ever installed into
assert tc.packages_dir() == paths.train_packages_dir() == os.path.join(TMP, "user", "Trainer", "packages")
assert not tc.has_packages()
assert tc.is_own_python(sys.executable) and tc.is_own_python(paths.python_exe()) and not tc.is_own_python("") and not tc.is_own_python(None)
other = os.path.join(TMP, "other_python")                           # another python (a wrapper script, so it is not the same file)
open(other, "w").write(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n'); os.chmod(other, 0o755)
assert not tc.is_own_python(other)
assert tc.torch_index("cuda") == "https://download.pytorch.org/whl/" + tc.CUDA_TAG
assert tc.torch_index("cpu") == ("https://download.pytorch.org/whl/cpu" if sys.platform.startswith("linux") else None)
assert set(tc.DOWNLOAD_TEXT) == {"cpu", "cuda"} and "GB" in tc.DOWNLOAD_TEXT["cuda"]

# ---- what is missing, from a check_env result
info = tc.check_env(sys.executable)
assert info["torch"] is None and info["ultralytics"] is None, info
assert tc.missing_packages(info) == (True, True) and tc.can_download(info)
assert "pip install torch" in info["problems"][0] and "pip install ultralytics" in info["problems"][1]
assert tc.missing_packages({"torch": "2", "ultralytics": None}) == (False, True)
assert not tc.can_download(dict(info, python=other)), "a Python you picked is never installed into"
assert not tc.can_download(dict(info, torch="2", ultralytics="8"))
assert tc.missing_packages({"torch": None, "torch_error": "OSError: [WinError 126] x", "ultralytics": None}) == (False, True)

# ---- the wheel's own list of needs: torch and torchvision left out, extras left out, markers kept for pip to judge
idx = make_index()
reqs = tc._wheel_requirements(os.path.join(idx, "ultralytics-9.9.9-py3-none-any.whl"))
assert reqs == ["fakedep2>=1.0", 'fakedep3; sys_platform == "nonexistent-os"', "fakedep4", "ultralytics-thop>=2.0.18"], reqs

# ---- the download: torch (+ what it needs) once, ultralytics (+ what it needs), put in place, nothing left behind
use_index(idx)
said = []
PIP = []
real_pip = tc._run_pip
tc._run_pip = lambda args, *a, **k: (PIP.append(list(args)), real_pip(args, *a, **k))[1]
tc.install_packages("cpu", progress=said.append)
d = tc.packages_dir()
assert names(d) == ["fakedep", "fakedep2", "fakedep4", "torch", "torchvision", "ultralytics", "ultralytics_thop"], names(d)
# torch is asked for ONCE; ultralytics alone; its needs; and the one that wants torch without its needs
assert sum(1 for a in PIP if "torch" in a) == 1 and PIP[0][0] == "download" and "torch" in PIP[0] and "torchvision" in PIP[0], PIP
assert any("--no-deps" in a and "ultralytics" in a for a in PIP) and any("--no-deps" in a and "-r" in a for a in PIP), PIP
assert said.count("Unpacking torch ...") == 1, "a torch that a dependency dragged in is not unpacked over the first one: " + str(said)
tc._run_pip = real_pip
assert tc.has_packages() and not leftovers() and not os.path.exists(os.path.join(d, "fakedep3"))
assert any("torch" in t and "big one" in t for t in said) and any("ultralytics" in t for t in said) and any("Unpacking" in t for t in said), said
assert any(t.startswith("Putting the files in place") for t in said)
assert os.path.isdir(os.path.join(d, "torch-9.9.0.dist-info")), "the package descriptions come along"
info = tc.check_env(sys.executable)
assert info["torch"] == "9.9.0" and info["ultralytics"] == "9.9.9" and info["ok"] and not info["problems"], info
assert not info["cuda"] and info["gpu"] is None
assert tc.missing_packages(info) == (False, False) and not tc.can_download(info)
assert "CPU-only" in " ".join(info["warnings"]), info["warnings"]

# ---- the packages reach the training Python only when it is OpenPara's own
assert tc.child_env(sys.executable)[tc.PACKAGES_VAR] == d
assert tc.PACKAGES_VAR not in tc.child_env(other)
other_info = tc.check_env(other)
assert other_info["torch"] is None and not other_info["ok"], "a Python you picked keeps to its own packages"
os.environ[tc.PACKAGES_VAR] = "/somewhere/else"
assert tc.PACKAGES_VAR not in tc.child_env(other); assert tc.child_env(sys.executable)[tc.PACKAGES_VAR] == d
del os.environ[tc.PACKAGES_VAR]
# a training script (job_common is imported first, as every job does) sees torch and ultralytics
run = os.path.join(TMP, "run1"); os.makedirs(run)
script = os.path.join(TMP, "probe_job.py")
open(script, "w").write(f"import sys\nsys.path.insert(0, {TR!r})\nimport job_common\nimport torch, ultralytics, torchvision, fakedep2\n"
                        "print('SEEN', torch.__version__, ultralytics.__version__, torchvision.__version__, fakedep2.__version__)\n")
job = tc.Job.start(run, script, sys.executable)
job.proc.wait(timeout=60)
assert "SEEN 9.9.0 9.9.9 9.9.1 1.0" in job.read_log(), open(job.log_path).read()
job2 = tc.Job.start(run, script, other); job2.proc.wait(timeout=60)
assert job2.proc.returncode != 0 and "No module named 'torch'" in job2.read_log(), "the other Python is not given the folder"

# ---- removing
tc.remove_packages()
assert not tc.has_packages() and not os.path.exists(d)
assert tc.check_env(sys.executable)["torch"] is None

# ---- only ultralytics is missing (torch came with the Python): torch is not fetched
tc.install_packages("cpu", need_torch=False, progress=said.append)
assert names(d) == ["fakedep", "fakedep2", "fakedep4", "ultralytics", "ultralytics_thop"], names(d)
assert "torch" not in names(d), "a torch that a dependency dragged in must not shadow the Python's own"
# ... and the other way: then torch alone is added to what is there
tc.install_packages("cpu", need_ultralytics=False)
assert names(d) == ["fakedep", "fakedep2", "fakedep4", "torch", "torchvision", "ultralytics", "ultralytics_thop"] and not leftovers(), names(d)
assert tc.check_env(sys.executable)["ok"]
tc.remove_packages()

# ---- cancel: nothing is left, nothing is put in place
calls = []
def stop_now():
    calls.append(1); return True
try:
    tc.install_packages("cpu", stop=stop_now)
    raise SystemExit("cancel did not stop it")
except tc.Cancelled:
    pass
assert not tc.has_packages() and not leftovers() and calls

# ---- a failed download (a needed package is not in the index): said in words, nothing left; what was there before stays
idx2 = make_index("index2", skip=("fakedep2",)); use_index(idx2)
try:
    tc.install_packages("cpu")
    raise SystemExit("it should have failed")
except tc.InstallError as e:
    msg = str(e)
    assert "did not work" in msg and "fakedep2" in msg and "No download exists" in msg, msg
assert not tc.has_packages() and not leftovers()
use_index(idx)
tc.install_packages("cpu"); before = names(d)
use_index(idx2)
try:
    tc.install_packages("cpu", need_torch=False)
except tc.InstallError:
    pass
assert names(d) == before and not leftovers(), "a failed download changes nothing that was installed"
use_index(idx); tc.remove_packages()

# ---- pip's certificate and network complaints are explained
assert "certificate" in tc._pip_hint("SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed'))")
assert "online" in tc._pip_hint("ConnectionError: Max retries exceeded with url") and "disk is full" in tc._pip_hint("OSError: [Errno 28] No space left on device")
assert tc._pip_hint("something else") == ""

# ---- not enough free disk: refused before anything is downloaded
real = shutil.disk_usage
shutil.disk_usage = lambda p: type("U", (), {"free": 1_000_000_000, "total": 10**12, "used": 0})()
try:
    tc.install_packages("cuda")
    raise SystemExit("it should have refused")
except tc.InstallError as e:
    assert "not enough free disk space" in str(e) and "12 GB" in str(e) and "1.0 GB" in str(e), str(e)
finally:
    shutil.disk_usage = real
assert not tc.has_packages() and not leftovers()

# ---- a torch that is there but cannot be loaded (Windows: the Visual C++ files are missing) is said so, and is not downloaded again
idx3 = make_index("index3", torch_init='raise OSError(\'[WinError 126] The specified module could not be found. Error loading "fbgemm.dll" or one of its dependencies.\')\n')
use_index(idx3); tc.install_packages("cpu")
info = tc.check_env(sys.executable)
assert not info["ok"] and "cannot be loaded" in info["problems"][0] and "WinError 126" in info["problems"][0] and "Visual C++" in info["problems"][0], info["problems"]
assert tc.missing_packages(info) == (False, False) and not tc.can_download(info), "broken is not missing"
assert info["ultralytics"] == "9.9.9"
tc.remove_packages()

# ---- the GPU question
bin_dir = os.path.join(TMP, "bin"); os.makedirs(bin_dir)
old_path = os.environ["PATH"]
os.environ["PATH"] = bin_dir                                         # nothing there: no NVIDIA GPU as far as the Trainer can tell
assert tc.nvidia_gpu() is None
smi = os.path.join(bin_dir, "nvidia-smi")
open(smi, "w").write('#!/bin/sh\necho "NVIDIA GeForce RTX 4090"\n'); os.chmod(smi, 0o755)
assert tc.nvidia_gpu() == "NVIDIA GeForce RTX 4090"
open(smi, "w").write("#!/bin/sh\nexit 9\n")
assert tc.nvidia_gpu() is None, "nvidia-smi that fails means no usable GPU"
os.environ["PATH"] = old_path

# ---- the Gimble's model export runs on OpenPara's own Python too: it gets the downloaded packages (and only then)
sys.path[:0] = [os.path.join(HERE, "addons_src", "gimble_link"), os.path.join(HERE, "addons_src", "remote"), os.path.join(HERE, "shared")]
import gimble_core as gc
job_py = os.path.join(TMP, "export_probe.py")
open(job_py, "w").write("import sys, os, json\npaths = sys.argv[sys.argv.index('--paths') + 1].split(os.pathsep)\n"
                        "for p in reversed(paths):\n    sys.path.insert(0, p)\n"
                        "try:\n    import opara_marker\n    seen = opara_marker.VALUE\nexcept ImportError:\n    seen = None\n"
                        "print('GIMBLE ' + json.dumps({'tag': 'done', 'seen': seen}))\n")
os.makedirs(tc.packages_dir())
open(os.path.join(tc.packages_dir(), "opara_marker.py"), "w").write("VALUE = 'from the packages folder'\n")
assert gc.export_model("m.pt", TMP, job=job_py)["seen"] == "from the packages folder"
assert gc.export_model("m.pt", TMP, job=job_py, python=other)["seen"] is None, "a Python that was named is left alone"
shutil.rmtree(tc.packages_dir())
assert gc.export_model("m.pt", TMP, job=job_py)["seen"] is None

print("ok")
shutil.rmtree(TMP, ignore_errors=True)
