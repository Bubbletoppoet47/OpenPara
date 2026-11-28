"""Slicing in a worker process (plan 5.6, proposal D8).

The engine is 345,000 lines of C++ working on meshes people made.  When it crashes, the process that hosts it ends.  So the engine runs in its
own process, and OpenPara only waits for it:

    parent (OpenPara)                                   worker (python -m orca_core.worker <folder>)
    -----------------                                   -----------------------------------------
    writes <folder>/job.json and the meshes     --->    reads them, runs the backend
    polls <folder>/progress.jsonl               <---    appends {"percent", "message"} lines
    creates <folder>/cancel to cancel           --->    the backend asks is_cancelled() and stops
    ends the worker if it does not stop         --->
    reads <folder>/result/ when done.json is there <--  writes result/, then done.json (last)
                                                <---    or error.json (what went wrong, in words)

No done.json and no error.json means the worker died: WorkerCrashed, with the last thing it reported and the end of its log.
Nothing here needs the compiled engine: the backend is a module that has run(job, folder, progress, is_cancelled) -> dict; the real one is
orca_core._engine, and the tests use orca_core._selftest_backend.
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback

import numpy as np

from . import errors
from .results import Result, Paths, Moves, Estimate, SliceWarning

DEFAULT_BACKEND = "orca_core._engine"
EXIT_OK, EXIT_ERROR, EXIT_CANCELLED, EXIT_INTERNAL = 0, 2, 3, 4


# ======================================================================= the files of a job folder
def write_job(folder, objects, settings, threads, until, backend=None):
    """Writes job.json and one .npz per object into folder.  objects: list of dicts with name, vertices (N,3), faces (M,3), transform (4,4),
    settings (dict)."""
    meta = {"settings": dict(settings), "threads": int(threads), "until": until, "backend": backend, "objects": []}
    for i, o in enumerate(objects):
        fn = "object%d.npz" % i
        np.savez(os.path.join(folder, fn), vertices=np.asarray(o["vertices"], dtype=np.float64), faces=np.asarray(o["faces"], dtype=np.int32))
        meta["objects"].append({"name": o["name"], "file": fn, "transform": np.asarray(o["transform"], dtype=np.float64).tolist(),
                                "settings": dict(o.get("settings") or {})})
    tmp = os.path.join(folder, "job.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    os.replace(tmp, os.path.join(folder, "job.json"))


def read_job(folder):
    """The job as the backend gets it: the same dict with the meshes loaded (each object has `vertices` and `faces` arrays)."""
    with open(os.path.join(folder, "job.json"), encoding="utf-8") as f:
        job = json.load(f)
    for o in job["objects"]:
        with np.load(os.path.join(folder, o["file"])) as z:
            o["vertices"], o["faces"] = z["vertices"], z["faces"]
        o["transform"] = np.asarray(o["transform"], dtype=np.float64)
    return job


def _write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


# ======================================================================= the worker side
def _load_backend(name):
    return importlib.import_module(name or os.environ.get("ORCA_CORE_BACKEND") or DEFAULT_BACKEND)


def worker_main(folder):
    """Runs one job in this process and writes its outcome into the folder.  Returns the exit code."""
    progress_path = os.path.join(folder, "progress.jsonl")
    cancel_path = os.path.join(folder, "cancel")
    prog = open(progress_path, "a", encoding="utf-8", buffering=1)

    def progress(percent, message=""):
        prog.write(json.dumps({"percent": float(percent), "message": str(message)}) + "\n")
        prog.flush()

    def is_cancelled():
        return os.path.exists(cancel_path)

    try:
        job = read_job(folder)
        backend = _load_backend(job.get("backend"))
        out = backend.run(job, folder, progress, is_cancelled)
        rdir = os.path.join(folder, "result")
        Result(out.get("gcode", ""), Paths.from_arrays(out["paths"]), Moves.from_arrays(out["moves"]), Estimate.from_dict(out.get("estimate", {})),
               [SliceWarning.from_dict(w) for w in out.get("warnings", [])], out.get("record", {})).save(rdir)
        _write_json_atomic(os.path.join(folder, "done.json"), {"result": "result"})
        return EXIT_OK
    except errors.Cancelled as e:
        _write_json_atomic(os.path.join(folder, "error.json"), {"kind": "cancelled", "message": str(e) or "Cancelled."})
        return EXIT_CANCELLED
    except errors.ConfigError as e:
        _write_json_atomic(os.path.join(folder, "error.json"), {"kind": "config", "message": e.message, "key": e.key, "object": e.object})
        return EXIT_ERROR
    except errors.SliceError as e:
        _write_json_atomic(os.path.join(folder, "error.json"), {"kind": "slice", "message": e.message, "object": e.object})
        return EXIT_ERROR
    except errors.EngineMissing as e:
        _write_json_atomic(os.path.join(folder, "error.json"), {"kind": "missing", "message": str(e)})
        return EXIT_ERROR
    except BaseException as e:                                   # noqa: BLE001  anything else is a bug; say what it was
        _write_json_atomic(os.path.join(folder, "error.json"), {"kind": "internal", "message": "%s: %s" % (type(e).__name__, e),
                                                                  "traceback": traceback.format_exc()})
        return EXIT_INTERNAL
    finally:
        prog.close()


# ======================================================================= the parent side
def _tail(path, n=2000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - n))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


class _ProgressReader:
    """Reads new lines of progress.jsonl.  A half-written last line is left for the next time."""
    def __init__(self, path):
        self.path, self.pos, self.last = path, 0, ""

    def read(self):
        try:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                data = f.read()
        except OSError:
            return []
        end = data.rfind(b"\n")
        if end < 0:
            return []
        self.pos += end + 1
        out = []
        for line in data[:end].splitlines():
            try:
                d = json.loads(line)
                out.append((float(d["percent"]), str(d.get("message", ""))))
            except (ValueError, KeyError, TypeError):
                continue
        if out:
            self.last = out[-1][1]
        return out


def _package_parent():
    """The folder that holds the orca_core package, so the worker can import it."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_job(objects, settings, threads=1, until="gcode", progress=None, cancel=None, timeout=None, backend=None, python=None,
            cancel_grace=3.0, poll=0.05, keep_folder=False, output_dir=None):
    """Slices in a worker process and returns the Result (its G-code file is in a folder that the caller owns: result.gcode_path).

    progress(percent, message) is called from this thread, whenever the worker reports.  cancel is a threading.Event, or any function that
    returns True once the slice should stop.  timeout is in seconds.  Raises errors.ConfigError, SliceError, SliceTimeout, Cancelled,
    WorkerCrashed or EngineMissing.  output_dir is where the G-code and the result tables are put (a new temporary folder when not given);
    keep_folder keeps the worker's own folder (for finding out what went wrong)."""
    folder = tempfile.mkdtemp(prefix="orca_job_")
    proc = None
    try:
        write_job(folder, objects, settings, threads, until, backend)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([_package_parent()] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env["PYTHONIOENCODING"] = "utf-8"
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x08000000                      # CREATE_NO_WINDOW: no black window next to OpenPara
        log = open(os.path.join(folder, "worker.log"), "wb")
        try:
            proc = subprocess.Popen([python or sys.executable, "-m", "orca_core.worker", folder], cwd=folder, env=env,
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kw)
        finally:
            log.close()
        reader = _ProgressReader(os.path.join(folder, "progress.jsonl"))
        is_cancel = (cancel.is_set if hasattr(cancel, "is_set") else cancel) if cancel is not None else (lambda: False)
        t0, cancel_asked, why = time.monotonic(), None, None
        while True:
            for pct, msg in reader.read():
                if progress is not None:
                    try:
                        progress(pct, msg)
                    except BaseException:                         # the caller's callback failed: stop the worker, then pass it on
                        _end(proc, folder, cancel_grace)
                        raise
            code = proc.poll()
            if code is not None:
                for pct, msg in reader.read():
                    if progress is not None:
                        progress(pct, msg)
                break
            now = time.monotonic()
            if cancel_asked is None:
                if is_cancel():
                    why = "cancel"
                elif timeout is not None and now - t0 > timeout:
                    why = "timeout"
                if why:
                    cancel_asked = now
                    open(os.path.join(folder, "cancel"), "w").close()      # the polite form: the backend sees it and stops by itself
            elif now - cancel_asked > cancel_grace:
                _end(proc, folder, 0)                                       # the hard form: end the worker (this is what frees its memory too)
                code = proc.returncode
                break
            time.sleep(poll)

        if why == "timeout":
            raise errors.SliceTimeout(None, "Slicing was stopped after %g seconds." % timeout)
        if why == "cancel":
            raise errors.Cancelled("Slicing was cancelled.")
        done, err = os.path.join(folder, "done.json"), os.path.join(folder, "error.json")
        if os.path.exists(done):
            res = Result.load(os.path.join(folder, "result"))
            out_dir = output_dir or tempfile.mkdtemp(prefix="orca_out_")
            res.save(out_dir)                                           # moves the G-code to a folder that outlives the job folder
            return Result.load(out_dir)
        if os.path.exists(err):
            with open(err, encoding="utf-8") as f:
                e = json.load(f)
            kind = e.get("kind")
            if kind == "config":
                raise errors.ConfigError(e.get("key", ""), e["message"], e.get("object"))
            if kind == "slice":
                raise errors.SliceError(e.get("object"), e["message"])
            if kind == "cancelled":
                raise errors.Cancelled(e["message"])
            if kind == "missing":
                raise errors.EngineMissing(e["message"])
            raise errors.OrcaCoreError("Slicing failed inside the engine wrapper: %s\n%s" % (e.get("message", ""), e.get("traceback", "")))
        raise errors.WorkerCrashed(code, reader.last, _tail(os.path.join(folder, "worker.log")))
    finally:
        if proc is not None and proc.poll() is None:
            _end(proc, folder, 0)
        if not keep_folder:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)


def _end(proc, folder, grace):
    """Ends the worker: asks (cancel file), waits `grace` seconds, then ends it."""
    if proc.poll() is not None:
        return
    try:
        open(os.path.join(folder, "cancel"), "w").close()
    except OSError:
        pass
    t = time.monotonic()
    while grace and proc.poll() is None and time.monotonic() - t < grace:
        time.sleep(0.02)
    if proc.poll() is None:
        proc.kill()                                                    # on Windows terminate() is the same; kill() is the same on both
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        pass


if __name__ == "__main__":
    sys.exit(worker_main(sys.argv[1]))
