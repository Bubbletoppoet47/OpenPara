"""The Playground's "Watch for new builds": a check every few minutes (a conditional request), the usual update window when a newer build is out,
quiet when it fails, nothing when a window is open, "Later" is remembered per build.  The normal program has no watch."""
import faulthandler; faulthandler.dump_traceback_later(180, exit=True)
import os, sys, json, tempfile, threading, http.server
os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(tmp, "user")
os.environ["OPARA_CHANNEL"] = "playground"
os.environ.pop("OPARA_NO_UPDATE", None)
import paths, updater, version, channel, playground
os.makedirs(paths.user_dir(), exist_ok=True)
playground.mark_first_run_done()

# a fake GitHub feed with an ETag: counts the requests and the conditional ones
HITS = {"all": 0, "cond": 0, "304": 0}
FEED = [{"tag_name": "dev-" + version.__version__, "body": "", "html_url": "http://x", "draft": False, "assets": []}]
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        HITS["all"] += 1
        tag = "W/\"%d\"" % len(json.dumps(FEED))
        if self.headers.get("If-None-Match") == tag:
            HITS["cond"] += 1; HITS["304"] += 1
            self.send_response(304); self.send_header("ETag", tag); self.end_headers(); return
        body = json.dumps(FEED).encode()
        self.send_response(200); self.send_header("ETag", tag); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{httpd.server_address[1]}/feed"

cache = {}
a = updater.fetch_latest(url, cache=cache)
assert a and a["version"] == version.__version__ and cache["etag"] and HITS["all"] == 1
b = updater.fetch_latest(url, cache=cache)
assert b == a and HITS["304"] == 1, "an unchanged feed is answered 304 and the last release is used"
FEED.append({"tag_name": "dev-99.0.0.1", "body": "new", "html_url": "http://x", "draft": False, "assets": []})
c = updater.fetch_latest(url, cache=cache)
assert c["version"] == "99.0.0.1" and cache["rel"] is c and HITS["304"] == 1, "a changed feed is read again"
assert updater.fetch_latest(url)["version"] == "99.0.0.1", "without a cache it works as before"
assert updater.fetch_latest("http://127.0.0.1:1/x", timeout=1, cache=cache) is None
print("OK conditional request")

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QEventLoop, QTimer
qa = QApplication([])
import gpd_app, update_ui
sh = gpd_app.AppShell([])
up = sh.updates
msgs = []
QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(a[2]))
offered = []
up.offer = lambda rel: offered.append(rel)
def settle(ms=1500):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()
def wait_check():
    for _ in range(100):
        settle(50)
        if up.thread is None or not up.thread.isRunning():
            break
    settle(50)

# the menu entry and its state
assert up.watch_available() and sh.watch_upd.isCheckable() and not sh.watch_upd.isChecked() and not up.timer.isActive()
assert not up.watch_enabled()
# watching is off: a tick does nothing
up.watch_tick(); settle(100); assert up.thread is None and not offered
# switch it on: remembered, the timer runs every 5 minutes, and it looks right away
newer = {"version": "99.1.0", "notes": "", "page": "", "app": None, "setup": None}
calls = []
def fake_fetch(*a, **k):
    calls.append(k.get("cache") is up.etag_cache)
    return newer
update_ui.updater.fetch_latest = fake_fetch
sh.watch_upd.setChecked(True)
assert update_ui.load_state()["watch"] is True and up.timer.isActive() and up.timer.interval() == 5 * 60 * 1000 and up.watch_enabled()
wait_check()
assert offered and offered[-1]["version"] == "99.1.0" and calls and calls[-1], "it looked at once, with the conditional-request cache"
# the same build is offered again at the next look (nobody said Later)
n = len(offered); up.watch_tick(); wait_check(); assert len(offered) == n + 1
# Later for this build: only a newer build asks again
st = update_ui.load_state(); st["watch_later"] = "99.1.0"; update_ui.save_state(st)
n = len(offered); up.watch_tick(); wait_check(); assert len(offered) == n, "put off: not asked again"
up.manual = True; up.checked(newer); assert len(offered) == n + 1, "Check for updates still offers it"
newer = {"version": "99.2.0", "notes": "", "page": "", "app": None, "setup": None}
n = len(offered); up.watch_tick(); wait_check(); assert len(offered) == n + 1 and offered[-1]["version"] == "99.2.0"
# the build that is installed is not offered; Skip this version is respected
newer = {"version": version.__version__, "notes": "", "page": "", "app": None, "setup": None}
n = len(offered); up.watch_tick(); wait_check(); assert len(offered) == n and not msgs, "no pop-up for 'you have the newest' during a watch"
newer = {"version": "99.3.0", "notes": "", "page": "", "app": None, "setup": None}
st = update_ui.load_state(); st["skip"] = "99.3.0"; update_ui.save_state(st)
n = len(offered); up.watch_tick(); wait_check(); assert len(offered) == n
# a failed look says nothing (no pop-up, no status-bar message)
newer = None
msgs.clear(); sh.statusBar().clearMessage(); n = len(offered)
up.watch_tick(); wait_check()
assert not msgs and sh.statusBar().currentMessage() == "" and len(offered) == n
# in the way: a window that must be answered, a busy program, a 3D FEA job
newer = {"version": "99.4.0", "notes": "", "page": "", "app": None, "setup": None}
real = QApplication.activeModalWidget
QApplication.activeModalWidget = staticmethod(lambda: object())
n = len(offered); up.watch_tick(); settle(200); assert up.thread is not None and not up.thread.isRunning() or up.thread is None
assert len(offered) == n and up.in_the_way()
QApplication.activeModalWidget = real
assert not up.in_the_way()
sh._busy_depth = 1; assert up.in_the_way() and up.watch_busy(); sh._busy_depth = 0
class FakeTabs:
    def __init__(self, w): self.w = w
    def count(self): return 1
    def widget(self, i): return self.w
class Job: job = object()
real_tabs = sh.tabs; sh.tabs = FakeTabs(Job()); assert up.in_the_way(); sh.tabs = real_tabs
assert not up.in_the_way()
# the answer to a check that finishes while a window is open is not shown (the next look asks again)
QApplication.activeModalWidget = staticmethod(lambda: object())
up.watching = True; n = len(offered); up.checked(newer); assert len(offered) == n and not up.watching
QApplication.activeModalWidget = real
# the real window: Later after a watched look is remembered for that build; after a manual check it is not
which = {"text": "Later"}
QMessageBox.exec = lambda self: 0
QMessageBox.clickedButton = lambda self: next(b for b in self.buttons() if b.text() == which["text"])
rel = {"version": "99.5.0", "notes": "", "page": "", "app": None, "setup": None}
st = update_ui.load_state(); st.pop("watch_later", None); update_ui.save_state(st)
up.watched_offer = False; update_ui.UpdateController.offer(up, rel)
assert "watch_later" not in update_ui.load_state(), "Later after a manual check is not remembered"
up.watched_offer = True; update_ui.UpdateController.offer(up, rel)
assert update_ui.load_state()["watch_later"] == "99.5.0"
which["text"] = "Skip this version"; up.watched_offer = True; update_ui.UpdateController.offer(up, dict(rel, version="99.6.0"))
assert update_ui.load_state()["skip"] == "99.6.0"
# switched off: the timer stops and the setting is kept
sh.watch_upd.setChecked(False)
assert update_ui.load_state()["watch"] is False and not up.timer.isActive() and not up.watch_enabled()
up.watch_tick(); settle(100); assert not offered[len(offered):]
# switched on again forgets the put-off build
st = update_ui.load_state(); st["watch_later"] = "99.4.0"; update_ui.save_state(st)
up.set_watch(True); assert "watch_later" not in update_ui.load_state(); up.set_watch(False)
# a source copy (OPARA_NO_UPDATE=1) never updates itself: no watch
os.environ["OPARA_NO_UPDATE"] = "1"
assert not up.watch_available() and not up.watch_enabled(); up.set_watch(True); assert not up.timer.isActive()
os.environ.pop("OPARA_NO_UPDATE")
up.set_watch(False)
print("OK watch")

# the normal program has no watch menu entry and no watch
os.environ["OPARA_CHANNEL"] = "release"
assert not up.watch_available()
sh2 = gpd_app.AppShell([])
assert not hasattr(sh2, "watch_upd") and not sh2.updates.timer.isActive()
print("OK test_update_watch")
os._exit(0)
