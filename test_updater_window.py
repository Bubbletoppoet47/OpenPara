"""The OpenPara Updater's window (updater_tool/ou_window.py), offscreen, against the same fake GitHub as test_updater_tool.py.

  A. the list: the last 5 builds, "Show all" for the rest, own channel only; the buttons follow the selection ("Go back to ..." for an earlier build);
  B. Update to the newest: asks, installs, starts the program, sees "started fine", drops the safety copy; while the program is open the buttons wait;
  C. Install an old build from the full list (going back): the add-ons of THAT build are put back, their site\\ packages stay, the program is not started
     when the person says "Not now";
  D. a build that does not start: the window says so and OFFERS Go back / Start safely / Copy report - it does not go back by itself; Go back uses the saved
     copy (no download of the program zip), restores the add-ons, starts, fine; "Start safely" starts with every add-on off;
  E. a build that needs another runtime: only its full installer is offered (and downloaded + started on request); without an installer on GitHub it says so;
  F. "Update now" from the program: the window waits until the program (a process id) has closed, then installs, starts and closes itself;
  G. Repair downloads the same build again; GitHub unreachable: a plain message, nothing is installed, Copy report still works.
"""
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import os
import shutil
import signal
import subprocess
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_updater_tool as T                       # noqa: E402  (the fake GitHub and the fake builds; nothing runs on import)

core = T.core
from PyQt6.QtGui import QGuiApplication             # noqa: E402
from PyQt6.QtWidgets import QApplication            # noqa: E402

import ou_window                                    # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(cond, timeout=60, what=""):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out: " + what)


class Script:
    """What the person answers, in order; remembers what was asked."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, title, text, buttons):
        self.asked.append((title, text, list(buttons)))
        assert self.answers, f"asked more than expected: {title}: {text[:120]} {buttons}"
        a = self.answers.pop(0)
        assert a in buttons, (a, buttons, text[:200])
        return a


def window(inst, script=None, **kw):
    w = ou_window.UpdaterWindow(inst, **kw)
    w.ask = script or Script()
    w.show()
    return w


def loaded(w):
    pump(lambda: w.builds or w.builds_error, what="the list of builds")
    pump(lambda: not w.busy, what="the list of builds (busy)")


def rows(w):
    return [w.table.item(r, 0).text() for r in range(w.table.rowCount())]


def select(w, version):
    for r in range(w.table.rowCount()):
        if w.table.item(r, 0).text() == version:
            w.table.selectRow(r)
            return
    raise AssertionError(f"{version} is not in the table: {rows(w)}")


def started_fine(inst, w):
    pump(lambda: core.read_run_state(inst).get("ok") and not w.busy, what="started fine")


def kill_by_command(inst):
    """A build from before the start note leaves no run_state.json: find its process by the command line."""
    for pth in os.listdir("/proc"):
        if pth.isdigit():
            try:
                if os.path.join(inst.app, "gpd_app.py") in open(f"/proc/{pth}/cmdline").read():
                    os.kill(int(pth), signal.SIGTERM)
            except OSError:
                pass
    time.sleep(0.3)


def finish(w, inst=None):
    if inst is not None:
        T.close_program(inst)
    w.poll.stop()
    w.close()


def main():
    # ============================================================ A. the list
    inst, user = T.make_install("0.8.6.106")
    code = lambda aid: T.read(os.path.join(user, "addons", aid, aid + "_ext.py")).strip()
    w = window(inst)
    loaded(w)
    assert rows(w) == ["0.8.6.108", "0.8.6.107", "0.8.6.106", "0.8.6.105", "0.8.6.104"], rows(w)
    notes = {w.table.item(r, 0).text(): w.table.item(r, 2).text() for r in range(w.table.rowCount())}
    assert notes["0.8.6.108"] == "newest" and notes["0.8.6.106"] == "installed" and notes["0.8.6.107"] == "", notes
    assert "Installed: 0.8.6.106" in w.info.text() and "Newest on GitHub: 0.8.6.108" in w.info.text()
    assert not w.b_all.isHidden() and w.b_all.text() == "Show all 9 builds", w.b_all.text()
    w.b_all.click()
    assert rows(w)[-1] == "0.8.6.100" and len(rows(w)) == 9 and w.b_all.text() == "Show only the last 5 builds", rows(w)
    assert all(not v.startswith("0.8.5") and not v.startswith("0.9") for v in rows(w)), "the other program's builds are not offered"
    w.b_all.click()
    assert len(rows(w)) == 5
    select(w, "0.8.6.108")
    assert w.b_update.isEnabled() and w.b_install.isEnabled() and w.b_install.text() == "Install 0.8.6.108" and w.b_repair.isEnabled() and w.b_safe.isEnabled()
    select(w, "0.8.6.106")
    assert not w.b_install.isEnabled() and w.b_repair.isEnabled(), "the installed build is not 'installed over itself': it is repaired"
    select(w, "0.8.6.104")
    assert w.b_install.isEnabled() and w.b_install.text() == "Go back to 0.8.6.104", w.b_install.text()
    finish(w)

    # ============================================================ B. update to the newest
    T.FAKE.hits.clear()
    sc = Script("Install", "Start")
    w = window(inst, sc)
    loaded(w)
    w.b_update.click()
    started_fine(inst, w)
    assert inst.version == "0.8.6.108" and inst.saved_version() is None, "a healthy start drops the safety copy"
    assert "Install 0.8.6.108" in sc.asked[0][1] and "Start OpenPara Playground now?" in sc.asked[1][1], sc.asked
    assert sc.asked[0][1].count("kept as a saved copy") == 1
    assert "started fine" in w.status.text(), w.status.text()
    assert core.read_run_state(inst)["version"] == "0.8.6.108"
    pump(lambda: w.program_open, what="the window notices the program")
    assert not w.b_update.isEnabled() and not w.b_install.isEnabled() and not w.b_repair.isEnabled() and not w.b_safe.isEnabled(), "buttons wait for the program to close"
    assert w.b_report.isEnabled() and "started fine" in w.status.text() and "Close it before changing anything" in w.status.text()
    w_open = window(inst)                                      # the updater opened (Help > Open the updater) while the program runs
    pump(lambda: w_open.program_open and "Waiting for OpenPara Playground to close" in w_open.status.text(), what="the second window waits")
    assert not w_open.b_update.isEnabled() and not w_open.b_install.isEnabled()
    finish(w_open)
    T.close_program(inst)
    pump(lambda: not w.program_open, what="the program closed")
    select(w, "0.8.6.107")
    assert w.b_install.isEnabled(), "closed: buttons are back"
    w.poll.stop()
    w.close()

    # ============================================================ C. an old build from the full list
    w = window(inst, Script("Go back", "Not now"))
    loaded(w)
    w.b_all.click()
    select(w, "0.8.6.100")
    assert w.b_install.text() == "Go back to 0.8.6.100"
    n_runs = core.read_run_state(inst)["started"]
    w.b_install.click()
    pump(lambda: inst.version == "0.8.6.100" and not w.busy, what="going back")
    text = w.ask.asked[0][1]
    assert "Go back from 0.8.6.108 to the earlier build 0.8.6.100" in text and "add-ons" in text and "not touched" in text, text
    assert code("foo") == "CODE = '0.8.6.100'" and code("bar") == "CODE = 'user-old'", "foo is set back to that build, bar had no copy in it"
    assert os.path.isfile(os.path.join(user, "addons", "foo", "site", "pkg", "__init__.py")), "site packages stay"
    assert core.read_run_state(inst)["started"] == n_runs and not core.program_running(inst), "'Not now': the program was not started"
    assert "Add-ons set back: foo" in w.status.text() and "left as they are: bar" in w.status.text(), w.status.text()
    assert inst.saved_version() == "0.8.6.108"
    w.poll.stop()
    w.close()

    # ============================================================ D. a build that does not start
    T.add_pg("0.8.6.112", kind="crash")
    sc = Script("Install", "Start", "Close")
    w = window(inst, sc)
    loaded(w)
    assert rows(w)[0] == "0.8.6.112"
    shutil.rmtree(inst.old, ignore_errors=True)                  # (a fresh start: the saved copy of the step before is not the one under test)
    w.b_update.click()
    pump(lambda: len(sc.asked) == 3 and not w.busy, what="the failed start")
    title, text, buttons = sc.asked[2]
    assert "0.8.6.112 did not start properly" in text and "The program closed (exit code 1)" in text and "Nothing was changed back" in text, text
    assert buttons == ["Go back to 0.8.6.100", "Start safely", "Copy report", "Close"], buttons
    assert inst.version == "0.8.6.112" and inst.saved_version() == "0.8.6.100", "NO automatic rollback: the broken build is still installed"
    assert not core.read_run_state(inst)["ok"]
    # the report
    sc.answers = ["Copy report", "Close"]
    w.did_not_start("manual", False)
    clip = QGuiApplication.clipboard().text()
    assert "Installed: 0.8.6.112" in clip and "this build crashes at start" in clip and "Saved earlier copy: 0.8.6.100" in clip, clip[:600]
    # Go back: the saved copy, no download of the program zip, the add-ons of that build, started, fine
    before = [h for h in T.FAKE.downloads() if "app-0.8.6.100" in h]
    sc.answers = ["Go back to 0.8.6.100"]
    w.did_not_start("manual", False)
    started_fine(inst, w)
    assert inst.version == "0.8.6.100" and [h for h in T.FAKE.downloads() if "app-0.8.6.100" in h] == before, "the saved copy was used, nothing downloaded"
    assert code("foo") == "CODE = '0.8.6.100'" and "started fine" in w.status.text()
    T.close_program(inst)
    pump(lambda: not w.program_open)
    # Start safely: every add-on off
    w.b_safe.click()
    pump(lambda: core.read_run_state(inst).get("ok") and not w.busy, what="the safe start")
    assert core.read_run_state(inst)["safe"] is True and "started fine" in w.status.text()
    finish(w, inst)

    # ============================================================ E. another runtime
    T.add_pg("0.8.6.113", runtime=2)
    T.add_pg("0.8.6.114", runtime=2, with_setup=False)
    sc = Script("Install", "Cancel")
    w = window(inst, sc)
    loaded(w)
    select(w, "0.8.6.113")
    w.b_install.click()
    pump(lambda: len(sc.asked) == 2 and not w.busy, what="the installer offer")
    title, text, buttons = sc.asked[1]
    assert "Only its full installer can put it in" in text and "Download the full installer" in text and buttons == ["Download and start", "Cancel"], (text, buttons)
    assert inst.version == "0.8.6.100", "nothing was changed"
    sc.answers = ["Install", "Download and start"]
    started = []
    real_popen = subprocess.Popen
    subprocess.Popen = lambda cmd, **k: (started.append(cmd), type("P", (), {"pid": 1})())[1]
    try:
        w.b_install.click()
        pump(lambda: started, what="the installer is started")
    finally:
        subprocess.Popen = real_popen
    assert os.path.basename(started[0][0]) == "OpenPara-Playground-Setup-0.8.6.113.exe" and open(started[0][0], "rb").read().startswith(b"MZ fake installer"), started
    assert inst.version == "0.8.6.100"
    w2 = window(inst, Script("Install", "OK"))
    loaded(w2)
    select(w2, "0.8.6.114")
    w2.b_install.click()
    pump(lambda: len(w2.ask.asked) == 2 and not w2.busy)
    assert "no full installer on GitHub any more" in w2.ask.asked[1][1] and inst.version == "0.8.6.100"
    finish(w2)
    finish(w)

    # ============================================================ F. "Update now" in the program: wait for it to close, install, start
    inst, user = T.make_install("0.8.6.106")
    code = lambda aid: T.read(os.path.join(user, "addons", aid, aid + "_ext.py")).strip()
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    w = window(inst, update_to="0.8.6.108", wait_pid=sleeper.pid)
    loaded(w)
    for _ in range(15):
        app.processEvents()
        time.sleep(0.05)
    assert inst.version == "0.8.6.106" and w.program_open and "Waiting for OpenPara Playground to close" in w.status.text(), "the program is still open: nothing is replaced"
    assert not w.ask.asked
    sleeper.kill()
    sleeper.wait()
    pump(lambda: inst.version == "0.8.6.108", what="the update after the program closed")
    started_fine(inst, w)
    assert not w.ask.asked, "an update the person asked for in the program needs no more questions"
    assert code("foo") == "CODE = 'user-old'", "a forward update leaves the add-ons alone"
    pump(lambda: not w.isVisible(), timeout=10, what="the window closes itself after a good start")
    finish(w, inst)

    # ============================================================ H. old builds: no note to wait for, no safe start
    inst, user = T.make_install("0.8.6.106")
    T.add_pg("0.8.6.90", kind="old")
    T.add_pg("0.8.6.91", kind="old_crash")
    os.environ["OPARA_UPDATER_WAIT"] = "3"
    try:
        sc = Script("Go back", "Start")
        w = window(inst, sc)
        loaded(w)
        w.b_all.click()
        select(w, "0.8.6.90")
        w.b_install.click()
        pump(lambda: len(sc.asked) == 2 and not w.busy and "is running" in w.status.text(), what="the old build is started")
        assert "cannot confirm that it started fine" in w.status.text() and len(sc.asked) == 2, "no 'did not start' question for a build that cannot report"
        assert inst.version == "0.8.6.90" and inst.saved_version() == "0.8.6.106", "no verdict: the safety copy stays"
        assert not w.b_safe.isEnabled() and "older than the safe start" in w.b_safe.toolTip(), "an old build would start with its add-ons: no safe start"
        kill_by_command(inst)
        # a build that does not start (and cannot say why): Go back is offered, a safe start is not
        sc.answers = ["Install", "Start", "Close"]
        w.b_all.click() if w.b_all.text().startswith("Show all") else None
        select(w, "0.8.6.91")
        w.b_install.click()
        pump(lambda: len(sc.asked) == 5 and not w.busy, what="the crash of the old build")
        title, text, buttons = sc.asked[4]
        assert "did not start properly" in text and buttons == ["Go back to 0.8.6.90", "Copy report", "Close"], buttons
        assert inst.version == "0.8.6.91"
        finish(w)
    finally:
        os.environ["OPARA_UPDATER_WAIT"] = "8"
        kill_by_command(inst)

    # ============================================================ G. repair, and GitHub unreachable
    inst, user = T.make_install("0.8.6.106")
    open(os.path.join(inst.app, "marker.txt"), "w").write("damaged")
    os.remove(os.path.join(inst.app, "gpd_app.py"))
    sc = Script("Repair", "Not now")
    w = window(inst, sc)
    loaded(w)
    assert w.b_repair.isEnabled() and not w.b_safe.isEnabled(), "a program folder without gpd_app.py cannot be started, only repaired"
    w.b_repair.click()
    pump(lambda: len(sc.asked) == 2 and not w.busy, what="the repair")
    assert "Repair OpenPara Playground 0.8.6.106" in sc.asked[0][1]
    assert T.read(os.path.join(inst.app, "marker.txt")) == "0.8.6.106" and os.path.isfile(os.path.join(inst.app, "gpd_app.py"))
    assert code("foo") == "CODE = '0.8.6.106'" and code("bar") == "CODE = 'user-old'", "repair also sets the installed add-ons back to this build's code"
    assert w.b_safe.isEnabled()
    finish(w)
    keep = core.API
    core.API = "http://127.0.0.1:9/none"
    try:
        w = window(inst, Script())
        loaded(w)
        assert w.builds == [] and "Could not reach GitHub" in w.status.text() and "Check the internet connection" in w.status.text(), w.status.text()
        assert not w.b_update.isEnabled() and not w.b_install.isEnabled() and not w.b_repair.isEnabled(), "nothing can be installed without the list"
        assert w.b_safe.isEnabled() and w.b_report.isEnabled(), "the program can still be started safely and the report copied"
        w.b_report.click()
        assert "GitHub: Could not reach GitHub" in QGuiApplication.clipboard().text()
        finish(w)
    finally:
        core.API = keep
    print("OK updater window")


if __name__ == "__main__":
    try:
        main()
    finally:
        T.FAKE.server.shutdown()
        shutil.rmtree(T.WORK, ignore_errors=True)
