"""
runstate.py - the program says how its start went (the OpenPara Updater reads this) and keeps a crash log.

A program that cannot start, on Windows, simply vanishes: no console, no window, no message.  So:
  begin()     the first thing the program does (gpd_app.py, when it is started as the program): writes run_state.json in the data folder
              {pid, version, token, started, ok: false}, opens gpd_crash.log for faulthandler (a hard crash - a Qt or DLL fault - leaves its Python
              traceback there) and installs an early error hook: an error before the window is up is written to gpd_error.log and, on Windows, shown in a
              box that says where to look and that the OpenPara Updater can repair or go back.
  mark_ok()   about 4 seconds after the window is up and the event loop is running: ok = true.  The updater that started the program with
              OPARA_START_TOKEN waits for exactly this note; when it does not come it tells the person and offers "Go back" (a button, never by itself).
  end()       at a normal exit.
No Qt here.  Every function swallows its own errors: the note is a convenience and must never be the reason the program does not start.
"""
import atexit
import datetime
import faulthandler
import json
import os
import sys
import time
import traceback

import channel
import paths

FILE = "run_state.json"
ERROR_LOG = "gpd_error.log"
CRASH_LOG = "gpd_crash.log"

_STATE = {}
_CRASH_FH = None


def state_path():
    return os.path.join(paths.user_dir(), FILE)


def _write():
    """Atomic write; Windows may hold the file for a moment while the updater reads it, so a few tries."""
    p = state_path()
    for i in range(5):
        try:
            tmp = p + f".{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_STATE, f)
            os.replace(tmp, p)
            return True
        except OSError:
            time.sleep(0.05)
    return False


def read():
    try:
        with open(state_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def log_error(text):
    try:
        with open(os.path.join(paths.user_dir(), ERROR_LOG), "a", encoding="utf-8") as fh:
            fh.write(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except OSError:
        pass


def _open_crash_log():
    """faulthandler writes a Python traceback here when the process dies from a fault (a segfault in a DLL, a Qt abort).  Kept short."""
    global _CRASH_FH
    try:
        p = os.path.join(paths.user_dir(), CRASH_LOG)
        if os.path.exists(p) and os.path.getsize(p) > 100000:
            with open(p, encoding="utf-8", errors="replace") as f:
                keep = f.read()[-50000:]
            with open(p, "w", encoding="utf-8") as f:
                f.write(keep)
        _CRASH_FH = open(p, "a", encoding="utf-8", buffering=1)
        _CRASH_FH.write(f"--- start {datetime.datetime.now():%Y-%m-%d %H:%M:%S} pid {os.getpid()}\n")
        faulthandler.enable(file=_CRASH_FH, all_threads=True)
    except Exception:                                                  # noqa: BLE001
        _CRASH_FH = None


def _tell_person(text):
    """Windows only: a box that says the program could not start (otherwise it vanishes).  Never in tests (OPARA_NO_STARTUP_BOX)."""
    if sys.platform != "win32" or os.environ.get("OPARA_NO_STARTUP_BOX"):
        return
    try:
        import ctypes
        last = [ln for ln in text.strip().splitlines() if ln.strip()][-1:] or ["(no text)"]
        msg = (f"{channel.app_name()} could not start.\n\n{last[0][:300]}\n\nThe details are in\n{os.path.join(paths.user_dir(), ERROR_LOG)}\n\n"
               f"To get going again, open \"{channel.app_name()} Updater\" from the Start menu: it can put back an earlier build (Go back), repair this one "
               "or start it safely with every add-on off.")
        ctypes.windll.user32.MessageBoxW(None, msg, channel.app_name(), 0x10)        # MB_ICONERROR
    except Exception:                                                  # noqa: BLE001
        pass


def early_hook(et, ev, tb):
    """An uncaught error before the program's own error window exists (it is replaced by gpd_app.install_excepthook once the window is being made)."""
    text = "".join(traceback.format_exception(et, ev, tb))
    log_error("The program could not start:\n" + text)
    _STATE["failed"] = text.strip().splitlines()[-1][:300] if text.strip() else "error"
    _write()
    _tell_person(text)


def begin():
    """Called first when the program is started as the program (not when a test imports gpd_app)."""
    try:
        import version
        _STATE.clear()
        _STATE.update({"pid": os.getpid(), "version": version.__version__, "token": os.environ.get("OPARA_START_TOKEN") or None, "started": time.time(),
                       "ok": False, "ended": None, "safe": channel.safe_start()})
        _write()
        _open_crash_log()
        sys.excepthook = early_hook
        atexit.register(end)
    except Exception:                                                  # noqa: BLE001
        pass


def mark_ok():
    """The window is up and the event loop has been running for a while."""
    try:
        if not _STATE:
            return
        _STATE["ok"] = True
        _STATE["ok_at"] = time.time()
        _write()
    except Exception:                                                  # noqa: BLE001
        pass


def end():
    try:
        if _STATE and not _STATE.get("ended"):
            _STATE["ended"] = time.time()
            _write()
    except Exception:                                                  # noqa: BLE001
        pass
