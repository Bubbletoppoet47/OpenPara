"""
perf.py - how many cores OpenPara uses, and a watch for moments when the window stops answering.

Settings > Performance:
  cores      0 = Auto, else 1 ... the number of cores of this computer.
             The program is kept on that many cores (the process affinity; programs it starts, like the renderer, inherit it), and the math
             libraries and the solvers (FEA, CFD, meshing, studies) use ONE LESS than that when there are two or more, so a core stays free
             for the window.  Auto = every core for the program, all but one for calculations.
  slow_log   SlowWatch: when the window thread is blocked for longer than a moment, slow.log (in the user's data folder) gets the time, the
             length and the lines of code the window thread was in.

The libraries read their thread limits when they are loaded, so startup() runs before the heavy imports (environment variables); the limit
is also applied to libraries that are already loaded when threadpoolctl is installed, and to VTK.  Anything that is not possible on this
computer is skipped silently: the setting then does less, never breaks the program.
"""
import json
import os
import sys
import threading
import time
import traceback

THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS")
_state = {"limits": None, "original_mask": None}


def core_count():
    return os.cpu_count() or 1


def allowed_cores(cores):
    """How many cores the program may use for a setting (0 = Auto = all)."""
    n = core_count()
    return n if not cores or cores >= n else max(1, int(cores))


def compute_threads(cores):
    """How many threads the math libraries and solvers get: one less than the allowed cores, so the window keeps one (at least 1)."""
    a = allowed_cores(cores)
    return a - 1 if a > 1 else 1


def describe(cores):
    a, c = allowed_cores(cores), compute_threads(cores)
    head = f"Auto: {a} cores" if not cores else f"{a} of {core_count()} cores"
    return f"{head}; calculations use {c}, the window keeps {a - c if a > 1 else 'a share of the only one'}"


# ------------------------------------------------------------------------------------------------------ affinity
def _win_masks():
    import ctypes
    k = ctypes.windll.kernel32
    h = k.GetCurrentProcess()
    pm, sm = ctypes.c_size_t(), ctypes.c_size_t()
    if not k.GetProcessAffinityMask(h, ctypes.byref(pm), ctypes.byref(sm)):
        return None
    return k, h, pm.value, sm.value


def _lowest_bits(mask, n):
    out, got = 0, 0
    for b in range(mask.bit_length()):
        if mask >> b & 1:
            out |= 1 << b
            got += 1
            if got >= n:
                break
    return out


def set_affinity(n):
    """Keep the process on `n` cores (0 = as it was at start).  Returns the number of cores in effect, or None when this system cannot."""
    try:
        if sys.platform == "win32":
            m = _win_masks()
            if m is None:
                return None
            k, h, cur, _system = m
            if _state["original_mask"] is None:
                _state["original_mask"] = cur
            full = _state["original_mask"]
            want = full if not n else _lowest_bits(full, n)
            if want and k.SetProcessAffinityMask(h, want):
                return bin(want).count("1")
            return None
        if hasattr(os, "sched_getaffinity"):
            if _state["original_mask"] is None:
                _state["original_mask"] = sorted(os.sched_getaffinity(0))
            full = _state["original_mask"]
            want = full if not n else full[:n]
            os.sched_setaffinity(0, set(want))
            return len(want)
    except Exception:                                   # noqa: BLE001 - a computer that does not allow it just keeps all its cores
        return None
    return None


def current_affinity():
    try:
        if sys.platform == "win32":
            m = _win_masks()
            return bin(m[2]).count("1") if m else None
        if hasattr(os, "sched_getaffinity"):
            return len(os.sched_getaffinity(0))
    except Exception:                                   # noqa: BLE001
        pass
    return None


# ------------------------------------------------------------------------------------------------------ applying the setting
def apply(cores):
    """Apply the setting now.  Returns what was done: {"allowed", "threads", "affinity", "pool", "vtk"}."""
    a, t = allowed_cores(cores), compute_threads(cores)
    for v in THREAD_VARS:                               # read by libraries loaded later, and by the programs OpenPara starts
        os.environ[v] = str(t)
    done = {"allowed": a, "threads": t, "affinity": None, "pool": False, "vtk": False}
    done["affinity"] = set_affinity(0 if (not cores or cores >= core_count()) else a)
    try:                                                # libraries that are loaded already (numpy's BLAS, scipy ...)
        from threadpoolctl import threadpool_limits
        _state["limits"] = threadpool_limits(limits=t)  # kept: dropping the object would restore the old limits
        done["pool"] = True
    except Exception:                                   # noqa: BLE001 - not installed: the variables above are what is left
        pass
    try:
        from vtkmodules.vtkCommonCore import vtkSMPTools
        vtkSMPTools.Initialize(t)
        done["vtk"] = True
    except Exception:                                   # noqa: BLE001
        pass
    return done


def startup():
    """Before the heavy imports: read the saved choice and apply it."""
    try:
        import paths
        with open(os.path.join(paths.user_dir(), "settings.json"), encoding="utf-8") as f:
            c = json.load(f).get("cores", 0)
        c = int(c)
    except Exception:                                   # noqa: BLE001 - no file yet: Auto
        c = 0
    return apply(c)


# ------------------------------------------------------------------------------------------------------ the slow-moment watch
def log_path():
    import paths
    return os.path.join(paths.user_dir(), "slow.log")


class SlowWatch:
    """A heartbeat on the window thread (a QTimer) and a helper thread that looks at it.  When the window thread has not beaten for longer than
    `threshold` seconds, the helper takes the lines of code the window thread is in at that moment; when the beat returns, the stall is logged."""

    def __init__(self, threshold=0.15, beat_ms=50, path=None):
        self.threshold, self.beat_ms = threshold, beat_ms
        self.path = path
        self.running = False
        self.timer = None
        self.main_id = threading.get_ident()
        self.last = time.monotonic()
        self.stack = None
        self.count = 0

    def start(self):
        if self.running:
            return
        from PyQt6.QtCore import QTimer
        self.main_id = threading.get_ident()
        self.running = True
        self.last = time.monotonic()
        self.stack = None
        self.timer = QTimer()
        self.timer.setInterval(self.beat_ms)
        self.timer.timeout.connect(self.beat)
        self.timer.start()
        threading.Thread(target=self.watch, daemon=True).start()

    def stop(self):
        self.running = False
        if self.timer is not None:
            self.timer.stop()
            self.timer = None

    def beat(self):
        now = time.monotonic()
        gap = now - self.last - self.beat_ms / 1000.0
        if gap >= self.threshold:
            self.record(gap, self.stack)
        self.last, self.stack = now, None

    def watch(self):
        while self.running:
            time.sleep(0.03)
            if self.stack is None and time.monotonic() - self.last - self.beat_ms / 1000.0 > self.threshold:
                fr = sys._current_frames().get(self.main_id)
                if fr is not None:
                    self.stack = "".join(traceback.format_stack(fr)[-7:])

    def record(self, seconds, stack):
        self.count += 1
        try:
            p = self.path or log_path()
            if os.path.exists(p) and os.path.getsize(p) > 1_000_000:          # keep the file small: the newest half stays
                with open(p, encoding="utf-8", errors="replace") as f:
                    keep = f.read()[-400_000:]
                with open(p, "w", encoding="utf-8") as f:
                    f.write(keep)
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  window blocked for {seconds:.2f} s\n{stack or '  (not caught in time)'}\n")
        except OSError:
            pass


# ------------------------------------------------------------------------------------------------------ following the settings
_watch = {"obj": None, "hooked": False}


def slow_watch():
    return _watch["obj"]


def _changed(keys):
    import settings
    if "cores" in keys:
        apply(settings.get("cores"))
    if "slow_log" in keys:
        _slow(bool(settings.get("slow_log")))


def _slow(on):
    w = _watch["obj"]
    if on and w is None:
        w = _watch["obj"] = SlowWatch()
        w.start()
    elif on and not w.running:
        w.start()
    elif not on and w is not None:
        w.stop()


def follow_settings():
    """Once, when the window is made: the core limit and the slow-moment watch follow Settings > Performance from now on."""
    import settings
    if not _watch["hooked"]:
        settings.on_change(_changed)
        _watch["hooked"] = True
    _slow(bool(settings.get("slow_log")))
