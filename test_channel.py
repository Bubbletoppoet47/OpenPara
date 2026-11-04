"""The Playground channel: the same program with its own name, data folder, update feed (newest dev- pre-release) and add-on address."""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["OPARA_CHANNEL"] = "release"          # whatever channel.json says (a playground build carries one)
os.environ.pop("OPARA_DEV_ADDONS", None)
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import channel, updater, addons, paths, version

# ---- the normal program is unchanged
assert not channel.is_playground() and channel.app_name() == "OpenPara" and channel.asset_prefix() == "OpenPara-"
assert channel.tag_for("0.8.5") == "v0.8.5" and channel.version_of_tag("v0.8.5") == "0.8.5"
assert updater.feed_url() == updater.API_LATEST
assert addons.release_base().endswith(f"/v{version.__version__}/")
assert addons.dev_dir() is None and channel.dev_addons_dir() is None and channel.shared_dir() is None

# ---- the playground
os.environ["OPARA_CHANNEL"] = "playground"
os.environ["OPARA_PLAYGROUND_MODE"] = "full"                    # dev_addons/ and shared/ are loaded in Full dev mode only (test_playground_modes.py covers Testing)
assert channel.is_playground() and channel.app_name() == "OpenPara Playground" and channel.asset_prefix() == "OpenPara-Playground-"
assert channel.tag_for("0.8.5.37") == "dev-0.8.5.37" and channel.version_of_tag("dev-0.8.5.37") == "0.8.5.37"
assert updater.feed_url() == updater.API_DEV_LIST
assert addons.release_base().endswith(f"/dev-{version.__version__}/")
assert paths.app_name() == "OpenPara Playground"
dev = addons.dev_dir()
assert dev and dev.endswith("dev_addons"), dev
ids = addons.dev_ids()
for a in ("simulation", "fea3d", "mesh", "circuits", "dev_host"):
    assert a in ids, (a, ids)
assert channel.shared_dir().endswith("shared")
addons.activate()
assert channel.shared_dir() in sys.path
assert addons.status("simulation") == "installed" and addons.is_dev("simulation")
# a build marks itself with channel.json
os.environ.pop("OPARA_CHANNEL")
tmp = tempfile.mkdtemp()
real = channel.HERE
channel.HERE = tmp
assert not channel.is_playground()
json.dump({"channel": "playground"}, open(os.path.join(tmp, "channel.json"), "w"))
assert channel.is_playground()
channel.HERE = real
os.environ["OPARA_CHANNEL"] = "playground"

# ---- versions: a dev build is newer than the release it grows from and older than the next release
assert updater.is_newer("0.8.5.37", "0.8.5") and updater.is_newer("0.8.5.38", "0.8.5.37")
assert not updater.is_newer("0.8.5", "0.8.5.37") and updater.is_newer("0.8.6", "0.8.5.37")
assert addons._vkey("0.8.5.37") > addons._vkey("0.8.5") and addons._vkey("0.8.6") > addons._vkey("0.8.5.37")

# ---- the update feed: a list of releases, newest first; the newest dev- one counts, plain releases do not
def asset(name):
    return {"name": name, "browser_download_url": "http://x/" + name, "url": "http://x/api/" + name, "size": 5}
FEED = [
    {"tag_name": "v0.8.5", "html_url": "http://x/r", "body": "release", "assets": [asset("OpenPara-app-0.8.5.zip")]},
    {"tag_name": "dev-0.8.5.40", "prerelease": True, "html_url": "http://x/d40", "body": "forty",
     "assets": [asset("OpenPara-Playground-app-0.8.5.40.zip"), asset("OpenPara-Playground-Setup-0.8.5.40.exe")]},
    {"tag_name": "dev-0.8.5.39", "prerelease": True, "assets": []},
]
STATE = {"body": FEED}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        b = json.dumps(STATE["body"]).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_port}/releases"
r = updater.fetch_latest(url)
assert r["version"] == "0.8.5.40" and r["notes"] == "forty" and r["app"]["name"].startswith("OpenPara-Playground-app-")
assert r["setup"]["name"].endswith(".exe"), r
STATE["body"] = [FEED[0]]                                    # only plain releases: nothing for the playground
assert updater.fetch_latest(url) is None
# the normal program still takes a single release object (the "latest" feed) and its own file names
os.environ["OPARA_CHANNEL"] = "release"
STATE["body"] = FEED[0]
r = updater.fetch_latest(url)
assert r["version"] == "0.8.5" and r["app"]["name"] == "OpenPara-app-0.8.5.zip" and r["setup"] is None
srv.shutdown()

# ---- the window, the card, the About box
os.environ["OPARA_CHANNEL"] = "playground"
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import splash
sp = splash.Splash()
assert sp.playground
sp.grab()
os.environ["OPARA_CHANNEL"] = "release"
assert not splash.Splash().playground
print("channel OK")
