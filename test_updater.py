import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os, sys, json, zipfile, tempfile, threading, http.server, functools
os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(tmp, "user")
import paths, updater, version

# versions
assert updater.parse_version("v0.10.2") > updater.parse_version("0.9.9") and updater.is_newer("0.1.1", "0.1.0") and not updater.is_newer("0.1.0", "0.1.0")
assert updater.parse_version("1.2.3-beta") == (1, 2, 3)

# user data goes to the user folder; shipped material library is seeded once
assert paths.user_dir().startswith(tmp)
import physics_materials as pm, mat_lib, result_style
lp = pm.library_path(); assert lp.startswith(paths.user_dir()) and os.path.exists(lp), lp
assert mat_lib.user_path().startswith(paths.user_dir()) and result_style._settings_path().startswith(paths.user_dir())

# fake GitHub: a release feed and an app zip
srv_dir = os.path.join(tmp, "srv"); os.makedirs(srv_dir)
def make_zip(name, runtime=version.RUNTIME, valid=True):
    p = os.path.join(srv_dir, name)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("gpd_app.py", "print('new app')\n"); z.writestr("version.py", '__version__ = "9.9.9"\nRUNTIME = %d\n' % runtime)
        if valid: z.writestr("runtime.json", json.dumps({"runtime": runtime, "version": "9.9.9"}))
    return p
make_zip("OpenPara-app-9.9.9.zip"); make_zip("OpenPara-app-bad.zip", valid=False); make_zip("OpenPara-app-rt.zip", runtime=version.RUNTIME + 1)
open(os.path.join(srv_dir, "junk.zip"), "wb").write(b"not a zip")
H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=srv_dir)
class Q(H.func):
    def log_message(self, *a): pass
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=srv_dir)); port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
def asset(n): return {"name": n, "url": f"{base}/{n}", "browser_download_url": f"{base}/{n}", "size": os.path.getsize(os.path.join(srv_dir, n))}
rel = {"tag_name": "v9.9.9", "body": "notes", "html_url": "http://x/r", "draft": False,
       "assets": [asset("OpenPara-app-9.9.9.zip"), {"name": "OpenPara-Setup-9.9.9.exe", "url": base + "/s", "browser_download_url": base + "/s", "size": 1}]}
json.dump(rel, open(os.path.join(srv_dir, "latest.json"), "w"))
json.dump({"message": "Not Found"}, open(os.path.join(srv_dir, "none.json"), "w"))
r = updater.fetch_latest(base + "/latest.json")
assert r and r["version"] == "9.9.9" and r["app"]["name"] == "OpenPara-app-9.9.9.zip" and r["setup"] and updater.is_newer(r["version"])
assert updater.fetch_latest(base + "/none.json") is None and updater.fetch_latest("http://127.0.0.1:1/x", timeout=1) is None

# download with progress and cancel
dest = os.path.join(tmp, "dl.zip"); seen = []
updater.download(r["app"], dest, progress=lambda d, t: seen.append((d, t)))
assert seen and seen[-1][0] == r["app"]["size"], seen
try:
    updater.download(r["app"], dest + "2", progress=lambda d, t: False); assert False
except InterruptedError: pass

# installed layout + install, keep old, bad zips refused
root = os.path.join(tmp, "inst"); app = os.path.join(root, "app"); os.makedirs(os.path.join(root, "python")); os.makedirs(app)
open(os.path.join(app, "gpd_app.py"), "w").write("print('old app')\n"); open(os.path.join(app, "extra_old.py"), "w").write("x")
paths.CODE_DIR = app
assert updater.installed_layout() == (root, app)
paths.CODE_DIR = os.path.join(tmp, "src"); os.makedirs(paths.CODE_DIR); assert updater.installed_layout() is None   # a source folder cannot self-update
try: updater.zip_info(os.path.join(srv_dir, "OpenPara-app-bad.zip")); assert False
except ValueError: pass
try: updater.zip_info(os.path.join(srv_dir, "junk.zip")); assert False
except ValueError: pass
try: updater.install_app_zip(os.path.join(srv_dir, "OpenPara-app-rt.zip"), app); assert False
except RuntimeError: pass
assert "old app" in open(os.path.join(app, "gpd_app.py")).read(), "failed install must leave the old app"
updater.install_app_zip(dest, app)
assert "new app" in open(os.path.join(app, "gpd_app.py")).read() and not os.path.exists(os.path.join(app, "extra_old.py"))
assert os.path.exists(os.path.join(app + ".old", "extra_old.py")) and not os.path.exists(app + ".new")
updater.install_app_zip(dest, app)       # a second update replaces app.old
print("updater logic OK")

# window: Help menu, controller state
from PyQt6.QtWidgets import QApplication
qa = QApplication([])
import gpd_app, update_ui
sh = gpd_app.AppShell([])
titles = [a.text() for a in sh.menuBar().actions()]; assert any("Help" in t for t in titles), titles
assert sh.windowTitle() == "OpenPara"
assert sh.updates.auto_enabled(); sh.updates.set_auto(False); assert not update_ui.load_state()["auto"]
sh.updates.set_auto(True)
msgs = []
from PyQt6.QtWidgets import QMessageBox
QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(a[2]))
sh.updates.manual = True; sh.updates.checked(None); assert msgs and "Could not reach" in msgs[-1]
sh.updates.checked({"version": version.__version__, "notes": "", "page": "", "app": None, "setup": None}); assert "newest" in msgs[-1]
offered = []; sh.updates.offer = lambda rel: offered.append(rel)
sh.updates.checked({"version": "99.0.0", "notes": "", "page": "", "app": None, "setup": None}); assert offered
sh.updates.manual = False; update_ui.save_state({"skip": "99.0.0"}); sh.updates.checked({"version": "99.0.0", "notes": "", "page": "", "app": None, "setup": None}); assert len(offered) == 1, "skipped version must not be offered at start-up"
# start-up check: runs at EVERY start (a recent check does not block it), prompts when a newer version exists
import time as _t
from PyQt6.QtWidgets import QApplication as _A
from PyQt6.QtCore import QEventLoop, QTimer
update_ui.save_state({"auto": True, "last": _t.time()})                    # checked a minute ago
newer = {"version": "99.1.0", "notes": "", "page": "", "app": None, "setup": None}
update_ui.updater.fetch_latest = lambda *a, **k: newer
offered.clear(); sh.updates.manual = False
sh.updates.check_later(ms=10)
loop = QEventLoop(); QTimer.singleShot(1500, loop.quit); loop.exec()
assert offered and offered[-1]["version"] == "99.1.0", "start-up check must prompt even right after another check"
# a failed automatic check says why in the status bar, no pop-up
msgs.clear(); sh.updates.manual = False; sh.updates.checked(None)
assert not msgs and "check for updates" in sh.statusBar().currentMessage().lower(), sh.statusBar().currentMessage()
# switched off in Help: no start-up check
update_ui.save_state({"auto": False}); offered.clear(); sh.updates.check_later(ms=10)
loop = QEventLoop(); QTimer.singleShot(600, loop.quit); loop.exec(); assert not offered
print("update UI OK")
