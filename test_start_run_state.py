"""The real program (gpd_app.py started as the program, offscreen) says how its start went - what the OpenPara Updater waits for.

  1. a normal start with OPARA_START_TOKEN: run_state.json gets {pid, version, token, ok: false} at once and ok = true a few seconds after the window is
     up; gpd_crash.log is open (faulthandler); no "could not start" in the error log;
  2. a start with OPARA_SAFE_START=1 (the updater's "Start safely"): the same note, with safe = true, no token needed; the window title says so; the add-ons
     are off (none is active, nothing was installed into the data folder);
  3. a Playground in Full dev mode starts the dev add-ons - and a safe start of it does not (Testing mode, no add-on code imported).
"""
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = tempfile.mkdtemp(prefix="opara_rs_")
sys.path.insert(0, HERE)
import version  # noqa: E402


def start(name, extra):
    ud = os.path.join(WORK, name)
    os.makedirs(ud)
    env = dict(os.environ, OPARA_USER_DIR=ud, OPARA_NO_UPDATE="1", QT_QPA_PLATFORM="offscreen", OPARA_NO_STARTUP_BOX="1")
    for k in ("OPARA_START_TOKEN", "OPARA_SAFE_START", "OPARA_CHANNEL", "OPARA_PLAYGROUND_MODE"):
        env.pop(k, None)
    env.update(extra)
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "gpd_app.py")], env=env, cwd=WORK, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p, ud


def state(ud):
    try:
        return json.load(open(os.path.join(ud, "run_state.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_ok(p, ud, timeout=200):
    end = time.time() + timeout
    seen_begin = None
    while time.time() < end:
        st = state(ud)
        if st and seen_begin is None:
            seen_begin = dict(st)
        if st.get("ok"):
            return seen_begin, st
        assert p.poll() is None, ("the program ended before it said it started fine", p.returncode, p.stdout.read()[-2500:])
        time.sleep(0.25)
    raise AssertionError(("no 'started fine' note", state(ud), p.poll()))


procs = []
try:
    a, ud_a = start("normal", {"OPARA_START_TOKEN": "tok-real-1"})
    b, ud_b = start("safe", {"OPARA_SAFE_START": "1"})
    c, ud_c = start("pg_full", {"OPARA_CHANNEL": "playground", "OPARA_PLAYGROUND_MODE": "full"})
    d, ud_d = start("pg_safe", {"OPARA_CHANNEL": "playground", "OPARA_PLAYGROUND_MODE": "full", "OPARA_SAFE_START": "1"})
    procs = [a, b, c, d]
    # ---- 1. a normal start
    first, st = wait_ok(a, ud_a)
    assert first["ok"] is False and first["pid"] == a.pid and first["token"] == "tok-real-1" and first["version"] == version.__version__, first
    assert st["ok"] is True and st["ok_at"] - st["started"] >= 3.5, "the note comes when the window has been up for a few seconds, not at once: " + json.dumps(st)
    assert st["safe"] is False and st["ended"] is None and not first.get("failed")
    assert open(os.path.join(ud_a, "gpd_crash.log"), encoding="utf-8").read().startswith("--- start "), "gpd_crash.log is open"
    log = os.path.join(ud_a, "gpd_error.log")
    assert not os.path.exists(log) or "could not start" not in open(log, encoding="utf-8").read(), open(log).read()[-800:]
    # ---- 2. a safe start
    first, st = wait_ok(b, ud_b)
    assert st["safe"] is True and st["token"] is None and st["ok"] is True and st["pid"] == b.pid, st
    assert not os.path.isdir(os.path.join(ud_b, "addons")) or not os.listdir(os.path.join(ud_b, "addons")), "a safe start installs nothing"
    assert state(ud_a)["safe"] is False
    assert os.path.exists(os.path.join(ud_a, "session.json")) and not os.path.exists(os.path.join(ud_b, "session.json")), \
        "a normal start keeps the tab list; a safe start neither reopens nor rewrites it"
    # ---- 3. the Playground: Full dev starts the dev add-ons, a safe start does not
    _, st_c = wait_ok(c, ud_c)
    _, st_d = wait_ok(d, ud_d)
    assert st_c["safe"] is False and st_d["safe"] is True
    # a normal Playground start put the add-ons that ship in place (data folder); the safe one left the folder without add-ons
    assert os.path.isdir(os.path.join(ud_c, "addons")) and os.listdir(os.path.join(ud_c, "addons")), "the normal start installs the shipped add-ons"
    assert not os.path.isdir(os.path.join(ud_d, "addons")) or not os.listdir(os.path.join(ud_d, "addons")), "the safe start installs none"
    print("OK real start says started fine")
finally:
    for p in procs:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
    for p in procs:
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
    shutil.rmtree(WORK, ignore_errors=True)
