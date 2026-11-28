"""orca_core worker process (plan 5.6, tests T8 and T9 of chapter 11, as far as they can be tested without the compiled engine).

A stand-in backend (orca_core._selftest_backend) behaves in the ways an engine can: finish, report progress, stop when asked, ignore being
asked, end the process silently, really crash (a read at address 0), raise each kind of error.  The point: whatever it does, the caller
(this process, standing in for OpenPara) stays alive, gets a sentence and a typed error, and the worker is gone afterwards."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, sys, threading, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engines", "orca_core", "python"))
import orca_core as oc
from orca_core import errors

BACKEND = "orca_core._selftest_backend"
CUBE = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [0, 0, 10], [10, 0, 10], [10, 10, 10], [0, 10, 10]], float)
FACES = np.array([[0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6], [0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2], [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]])


def job(mode="ok", **kw):
    j = oc.Job(settings={"_selftest": mode, "wall_loops": "3"}, threads=2)
    j.add_object(CUBE, FACES, name="cube", **kw)
    return j


def alive(pid):
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except ImportError:
        if os.name == "nt":
            return None                      # cannot ask without psutil; the checks that need it are skipped on Windows
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        # a zombie child still answers; read its state
        try:
            return open("/proc/%d/stat" % pid).read().split(")")[-1].split()[0] != "Z"
        except OSError:
            return True


def raises(kind, f):
    try:
        f()
    except kind as e:
        return e
    except BaseException as e:               # noqa: BLE001
        raise SystemExit("expected %s, got %s: %s" % (kind.__name__, type(e).__name__, e))
    raise SystemExit("expected %s, nothing was raised" % kind.__name__)


# ---- 1. a normal run: result, record, progress in order, nothing left behind in the job folder
seen = []
t0 = time.time()
r = job().slice(progress=lambda p, m: seen.append((p, m)), backend=BACKEND)
print("a normal run took %.2f s" % (time.time() - t0))
assert len(r.paths) == 100 and r.paths.n_layers == 50 and os.path.isfile(r.gcode_path) and r.gcode_path.endswith("plate_1.gcode")
assert [p for p, _ in seen] == sorted(p for p, _ in seen) and seen[0] == (0.0, "start") and seen[-1] == (100.0, "done"), seen
assert r.record["settings"]["wall_loops"] == "3" and r.record["threads"] == 2 and r.warnings[0].level == "tip"
assert abs(r.paths.by_role()["Outer wall"][0] - 2000.0) < 0.01, "50 layers x a 40 mm loop"
import glob, tempfile
before = set(glob.glob(os.path.join(tempfile.gettempdir(), "orca_job_*")))
job().slice(backend=BACKEND)
assert set(glob.glob(os.path.join(tempfile.gettempdir(), "orca_job_*"))) == before, "the worker's folder is removed"

# a transform moves the part: the paths follow it
T = np.eye(4); T[:3, 3] = [100, 50, 5]
r2 = job(transform=T).slice(backend=BACKEND)
assert abs(r2.paths.points[:, 0].min() - 100) < 1e-4 and abs(r2.paths.points[:, 2].max() - 15) < 1e-3 and abs(r2.paths.points[:, 2].min() - 5.2) < 1e-3, (r2.paths.points.min(0), r2.paths.points.max(0))

# an output folder of the caller's own
od = os.path.join(tempfile.mkdtemp(), "mine")
r3 = job().slice(backend=BACKEND, output_dir=od)
assert os.path.dirname(r3.gcode_path) == od

# ---- 2. errors that are the engine's way of saying no: typed, with the key and the object, and the worker is not blamed
e = raises(errors.ConfigError, lambda: job("config").slice(backend=BACKEND))
assert e.key == "sparse_infill_density" and e.object == "cube" and "between 0 %" in str(e)
e = raises(errors.SliceError, lambda: job("slice").slice(backend=BACKEND))
assert e.object == "cube" and "layer 3" in str(e) and not isinstance(e, errors.SliceTimeout)
e = raises(errors.OrcaCoreError, lambda: job("boom").slice(backend=BACKEND))
assert "RuntimeError: a bug" in str(e) and "Traceback" in str(e), "a bug is reported with where it was"

# ---- 3. T8 crash safety: the process ends, silently or by a real crash; this process lives and says what happened
e = raises(errors.WorkerCrashed, lambda: job("crash").slice(backend=BACKEND))
assert e.exit_code == 77 and e.last_progress == "start" and "ended unexpectedly" in str(e)
if os.name != "nt":
    e = raises(errors.WorkerCrashed, lambda: job("segfault").slice(backend=BACKEND))
    assert e.exit_code == -11, e.exit_code            # SIGSEGV
# the engine is not there: said in words, as the error of the kind it is
e = raises(errors.EngineMissing, lambda: job().slice(backend="orca_core._engine"))
assert "not built" in str(e) or "not written" in str(e)
# a backend that does not exist at all is a bug, reported as one and not as a crash
e = raises(errors.OrcaCoreError, lambda: job().slice(backend="orca_core.no_such_backend"))
assert not isinstance(e, errors.WorkerCrashed) and "no_such_backend" in str(e)

# ---- 4. T9 cancel and progress
# 4a. the polite form: the backend sees the flag and stops by itself, within a moment
cancel = threading.Event()
threading.Timer(0.6, cancel.set).start()
t0 = time.time()
raises(errors.Cancelled, lambda: job("hang").slice(cancel=cancel, backend=BACKEND))
dt = time.time() - t0
assert 0.5 < dt < 4, dt
# 4b. the hard form: a backend that does not look; the worker is ended after the grace time, and is gone
cancel = threading.Event()
threading.Timer(0.6, cancel.set).start()
t0 = time.time()
j = job("deaf")
holder = {}
def run_keep():
    return j.slice(cancel=cancel, backend=BACKEND, cancel_grace=0.5, keep_folder=True)
raises(errors.Cancelled, run_keep)
dt = time.time() - t0
assert 1.0 < dt < 5, dt
folders = sorted(glob.glob(os.path.join(tempfile.gettempdir(), "orca_job_*")), key=os.path.getmtime)
pidfile = os.path.join(folders[-1], "pid")
pid = int(open(pidfile).read())
a = alive(pid)
assert a in (False, None), "the worker must be gone after a cancel"
import shutil
for f in set(folders) - before:
    shutil.rmtree(f, ignore_errors=True)
# 4c. a function works as well as an Event; and cancel before anything started
raises(errors.Cancelled, lambda: job("hang").slice(cancel=lambda: True, backend=BACKEND))
# 4d. a time limit
t0 = time.time()
e = raises(errors.SliceTimeout, lambda: job("hang").slice(timeout=0.7, backend=BACKEND))
assert isinstance(e, errors.SliceError) and "0.7" in str(e) and time.time() - t0 < 5
# 4e. a progress function that fails stops the worker and the failure reaches the caller
def bad(p, m):
    raise KeyError("the window was closed")
raises(KeyError, lambda: job("slow").slice(progress=bad, backend=BACKEND))
# 4f. progress while it runs: several updates, in order, before the end
seen = []
job("slow").slice(progress=lambda p, m: seen.append(p), backend=BACKEND)
assert len(seen) > 10 and seen == sorted(seen) and seen[-1] == 100, seen[:5]

# ---- 5. nothing was left running or lying about
assert set(glob.glob(os.path.join(tempfile.gettempdir(), "orca_job_*"))) == before, "no job folders left"

# ---- 6. meshes the engine could not take are refused before any process starts, in words
def bad_mesh(v, f, *words):
    j = oc.Job()
    try:
        j.add_object(v, f, name="broken")
    except ValueError as e:
        for w in words:
            assert w in str(e), (w, str(e))
        return
    raise SystemExit("a broken mesh was accepted: %s" % (words,))
bad_mesh(np.zeros((0, 3)), FACES, "no vertices")
bad_mesh(CUBE, np.zeros((0, 3), int), "no triangles")
v = CUBE.copy(); v[3, 1] = np.nan
bad_mesh(v, FACES, "not a number")
f = FACES.copy(); f[0, 0] = 8
bad_mesh(CUBE, f, "does not exist")
f = FACES.copy(); f[0, 0] = -1
bad_mesh(CUBE, f, "does not exist")
bad_mesh(CUBE, FACES + 0.5, "whole numbers")
try:
    oc.Job().slice(); raise SystemExit("an empty job was run")
except ValueError as e:
    assert "nothing to slice" in str(e)
try:
    job().add_object(CUBE, FACES, transform=np.zeros((3, 3))); raise SystemExit("a bad transform was accepted")
except ValueError as e:
    assert "4 x 4" in str(e)
assert len(job().mesh_hashes()[0]) == 64 and job().mesh_hashes() == job().mesh_hashes()

print("orca_core worker: ok")
