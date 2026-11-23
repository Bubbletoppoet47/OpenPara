"""The OpenPara Updater (updater_tool/): the core, the command line and the program-side hand-off, against a fake GitHub.

Everything runs against a small local server that talks like GitHub's releases API (pagination, checksums, both channels in one list), so nothing here
touches the real GitHub.  The "program" the updater installs is a tiny gpd_app.py that uses the REAL runstate.py to write its "started fine" note; a build
can be made to crash, to hang, or to need another runtime.

  1. the list of builds: each program sees only its own channel, newest first by version NUMBER, drafts / pre-releases / builds without a program zip left
     out, more than one page of releases (a window shows the last 5, "Show all" the rest);
  2. a download is checked (checksum, size); a zip that points outside the folder, belongs to the other program or has no runtime.json is refused;
     a build that needs another runtime says only its full installer can put it in (and carries the build to download);
  3. the swap: the old program is kept as app.old, a failed swap puts it back, the saved copy goes back without a download;
  4. going back also restores the add-on CODE of that build for the installed add-ons and keeps their site\\ packages; one add-on failing leaves it as it was;
  5. start + wait for the note: ok with the right token, a crash / a silent exit / a hang are told apart, an old note with another token is not believed;
  6. the command line end to end, a broken build included: the broken build STAYS installed (no automatic rollback) and --go-back is what puts the
     earlier program back;  a build that needs another runtime exits 2;  an open program is not touched;
  7. the tool refreshes itself from app\\updater_tool only when that is newer and only when it passes its self-test;
  8. the program side: update_now / hand_over / seed_tool (no updater: the old in-program path), the early error hook, the started-fine note, safe start.
"""
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "updater_tool")
sys.path.insert(0, HERE)
sys.path.insert(0, TOOL)
WORK = tempfile.mkdtemp(prefix="opara_ut_")
os.environ["OPARA_USER_DIR"] = os.path.join(WORK, "user0")
os.environ["OPARA_UPDATER_PYTHON"] = sys.executable
os.environ["OPARA_UPDATER_WAIT"] = "8"
os.environ["OPARA_UPDATER_NO_REFRESH"] = "1"
os.environ["OPARA_NO_STARTUP_BOX"] = "1"
os.environ.pop("OPARA_START_TOKEN", None)
os.environ.pop("OPARA_SAFE_START", None)


# ====================================================================================================== a fake GitHub
class Fake:
    def __init__(self):
        self.releases = []
        self.big = []
        self.files = {}
        self.hits = []
        self.corrupt = set()                 # served with the last byte changed: the checksum does not match
        self.short = set()                   # served cut in half
        handler = self._handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server.fake = self
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def _handler():
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                fake = self.server.fake
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                fake.hits.append(u.path)
                if u.path in ("/releases", "/big/releases"):
                    rel = fake.releases if u.path == "/releases" else fake.big
                    per, page = int(q.get("per_page", ["30"])[0]), int(q.get("page", ["1"])[0])
                    body = json.dumps(rel[(page - 1) * per: page * per]).encode()
                    self.send_response(200)
                elif u.path.startswith("/dl/"):
                    name = urllib.parse.unquote(u.path[4:])                # "<tag>/<file name>": every release has its own files
                    body = fake.files.get(name)
                    if body is None:
                        self.send_response(404)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    short_name = name.split("/")[-1]
                    if name in fake.corrupt or short_name in fake.corrupt:
                        body = body[:-1] + bytes([body[-1] ^ 1])
                    if name in fake.short or short_name in fake.short:
                        body = body[: len(body) // 2]
                    self.send_response(200)
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        return H

    def downloads(self):
        return [h for h in self.hits if h.startswith("/dl/")]

    def asset(self, tag, name, data, digest=True):
        self.files[f"{tag}/{name}"] = data
        a = {"name": name, "browser_download_url": f"{self.base}/dl/{tag}/{urllib.parse.quote(name)}", "size": len(data), "url": f"{self.base}/api/{name}"}
        if digest:
            a["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
        return a

    def release(self, tag, assets, prerelease=False, draft=False, day=1, into=None):
        r = {"tag_name": tag, "draft": draft, "prerelease": prerelease, "published_at": f"2026-11-{day:02d}T10:00:00Z", "body": f"notes of {tag}",
             "html_url": f"https://example.invalid/releases/{tag}", "assets": assets}
        (self.releases if into is None else into).append(r)
        return r


# ====================================================================================================== fake builds
REAL = {n: open(os.path.join(HERE, n), encoding="utf-8").read() for n in ("runstate.py", "channel.py", "paths.py")}      # what a real program folder has
APP = r'''
import os, sys, time
KIND = %(kind)r
if KIND == "import_error":
    import this_module_does_not_exist_anywhere
if KIND == "old_crash":                  # a build from before the start note: it knows nothing of run_state.json
    raise SystemExit(1)
if KIND == "old":
    time.sleep(60)
    raise SystemExit(0)
import runstate
runstate.begin()
if KIND == "crash":
    raise RuntimeError("this build crashes at start")
if KIND == "silent_exit":
    sys.exit(0)
if KIND != "hang":
    time.sleep(0.4)
    runstate.mark_ok()
t0 = time.time()
while time.time() - t0 < 60:
    time.sleep(0.1)
runstate.end()
'''


def app_files(version, channel="playground", runtime=1, kind="good"):
    f = {"gpd_app.py": APP % {"repo": HERE, "kind": kind}, "version.py": f'__version__ = "{version}"\nRUNTIME = {runtime}\n',
         "runtime.json": json.dumps({"runtime": runtime, "version": version}), "marker.txt": version}
    if channel == "playground":
        f["channel.json"] = '{"channel": "playground"}'
    if not kind.startswith("old"):
        f.update(REAL)
    else:                                # an old build: a channel.py that does not know the safe-start switch, no runstate.py
        f["channel.py"] = "# an older channel.py: it does not know the safe-start switch\nimport os\n"
    return f


def zip_bytes(files, evil=None):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, t in files.items():
            z.writestr(n, t)
        if evil:
            z.writestr(zipfile.ZipInfo(evil), "owned")
    return b.getvalue()


def addon_zip(aid, version):
    return zip_bytes({"addon.json": json.dumps({"id": aid, "name": aid, "version": version, "extension": aid + "_ext"}), aid + "_ext.py": f"CODE = {version!r}\n"})


FAKE = Fake()
os.environ["OPARA_UPDATER_API"] = FAKE.base + "/releases"
import ou_core as core                                         # noqa: E402  (reads OPARA_UPDATER_API when imported)
import openpara_updater as tool                                # noqa: E402

PG_VERSIONS = [f"0.8.6.{n}" for n in (100, 101, 102, 103, 104, 105, 106, 107, 108)]       # note: 0.8.6.9 style numbers sort by NUMBER, see below
REL_VERSIONS = ["0.8.2", "0.8.3", "0.8.4", "0.8.5"]


def add_pg(version, kind="good", runtime=1, evil=None, with_setup=True, digest=True, day=None, addons=("foo", "gone")):
    t = f"dev-{version}"
    assets = [FAKE.asset(t, f"OpenPara-Playground-app-{version}.zip", zip_bytes(app_files(version, "playground", runtime, kind), evil), digest)]
    if with_setup:
        assets.append(FAKE.asset(t, f"OpenPara-Playground-Setup-{version}.exe", b"MZ fake installer " + version.encode() * 50))
    for a in addons:
        assets.append(FAKE.asset(t, f"addon-{a}.zip", addon_zip(a, version)))
    return FAKE.release(f"dev-{version}", assets, prerelease=True, day=day or (1 + int(version.split(".")[-1]) % 28))


def add_rel(version, kind="good", runtime=1):
    assets = [FAKE.asset(f"v{version}", f"OpenPara-app-{version}.zip", zip_bytes(app_files(version, "release", runtime, kind))),
              FAKE.asset(f"v{version}", f"OpenPara-Setup-{version}.exe", b"MZ fake installer " + version.encode() * 50)]
    return FAKE.release(f"v{version}", assets, day=1 + len(version) % 20)


for v in PG_VERSIONS:
    add_pg(v)
for v in REL_VERSIONS:
    add_rel(v)
add_rel("0.9.0-rc1").update(prerelease=True)                    # a pre-release of the normal program: never offered to OpenPara
FAKE.release("v0.8.99", [FAKE.asset("v0.8.99", "OpenPara-app-0.8.99.zip", zip_bytes(app_files("0.8.99", "release")))], draft=True)          # a draft (with a zip)
FAKE.release("dev-0.8.6.199", [FAKE.asset("dev-0.8.6.199", "OpenPara-Playground-app-0.8.6.199.zip", zip_bytes(app_files("0.8.6.199")))], prerelease=True, draft=True)
FAKE.release("v0.8.0", [FAKE.asset("v0.8.0", "OpenPara-Playground-app-0.8.0.zip", zip_bytes(app_files("0.8.0")))])      # a normal release that wrongly carries a Playground zip
FAKE.release("v0.8.1", [FAKE.asset("v0.8.1", "OpenPara-Setup-0.8.1.exe", b"x")])      # a release with no program zip (cannot be put in by the updater)
FAKE.release("dev-0.8.6.99", [FAKE.asset("dev-0.8.6.99", "OpenPara-Playground-Setup-0.8.6.99.exe", b"x")], prerelease=True)      # a dev build whose zip is gone
import random                                                   # GitHub does not list in version order
random.Random(7).shuffle(FAKE.releases)


# ====================================================================================================== an installation
def make_install(version="0.8.6.106", channel="playground", kind="good", runtime=1, addons=True):
    root = tempfile.mkdtemp(prefix="Install_" + channel + "_", dir=WORK)
    os.makedirs(os.path.join(root, "python"))
    app = os.path.join(root, "app")
    os.makedirs(app)
    for n, t in app_files(version, channel, runtime, kind).items():
        with open(os.path.join(app, n), "w", encoding="utf-8") as f:
            f.write(t)
    user = tempfile.mkdtemp(prefix="user_", dir=WORK)
    os.environ["OPARA_USER_DIR"] = user
    if addons:
        for aid, with_site in (("foo", True), ("bar", True)):
            d = os.path.join(user, "addons", aid)
            os.makedirs(d)
            json.dump({"id": aid, "name": aid, "version": "0.0.1", "extension": aid + "_ext"}, open(os.path.join(d, "addon.json"), "w"))
            open(os.path.join(d, aid + "_ext.py"), "w").write("CODE = 'user-old'\n")
            if with_site:
                os.makedirs(os.path.join(d, "site", "pkg"))
                open(os.path.join(d, "site", "pkg", "__init__.py"), "w").write("PKG = 'big download'\n")
    inst = core.Install(root, channel)
    inst.test_user = user
    inst.user_dir = lambda: user                       # (the updater reads its data folder from the environment: several installs live in one test)
    return inst, user


def launch(inst, **k):
    os.environ["OPARA_USER_DIR"] = inst.test_user      # the program the updater starts finds its data folder the same way
    return core.launch(inst, **k)


def env_for(inst, user, extra=None):
    e = dict(os.environ, OPARA_UPDATER_ROOT=inst.root, OPARA_USER_DIR=user, OPARA_UPDATER_CHANNEL=inst.channel, OPARA_UPDATER_API=core.API,
             OPARA_UPDATER_PYTHON=sys.executable, OPARA_UPDATER_WAIT="8", OPARA_UPDATER_NO_REFRESH="1", OPARA_NO_STARTUP_BOX="1")
    e.pop("OPARA_START_TOKEN", None)
    e.pop("OPARA_SAFE_START", None)
    e.update(extra or {})
    return e


def close_program(inst):
    """The person closes the program."""
    st = core.read_run_state(inst)
    pid = st.get("pid")
    if pid and core.pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        assert core.wait_for_exit(pid, timeout=10), "the fake program did not end"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def cli(inst, user, *args, extra=None, timeout=120):
    p = subprocess.run([sys.executable, os.path.join(TOOL, "openpara_updater.py"), "--cli", *args], env=env_for(inst, user, extra), capture_output=True, text=True,
                       timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as ex:
        return ex
    raise AssertionError(f"{exc.__name__} was not raised")


def main():
    # ============================================================================================== 1. the list of builds
    inst, user = make_install()
    builds = core.list_builds(inst)
    vs = [b["version"] for b in builds]
    assert vs == [f"0.8.6.{n}" for n in range(108, 99, -1)], vs
    assert all(b["tag"].startswith("dev-") for b in builds) and "0.8.6.99" not in vs, "only this program's builds, only those with a program zip"
    assert builds[0]["setup"] and builds[0]["app"]["name"] == "OpenPara-Playground-app-0.8.6.108.zip" and set(builds[0]["addons"]) == {"foo", "gone"}
    assert core.SHOW_FIRST == 5 and len(vs) > core.SHOW_FIRST
    rinst, ruser = make_install("0.8.4", "release")
    rb = core.list_builds(rinst)
    assert [b["version"] for b in rb] == ["0.8.5", "0.8.4", "0.8.3", "0.8.2"], [b["version"] for b in rb]       # no rc1, no draft, no dev, no zip-less 0.8.1
    assert core.vkey("dev-0.8.6.9") < core.vkey("dev-0.8.6.12") and core.vkey("v0.10.2") > core.vkey("v0.9.9"), "numbers, not text"
    # more than one page of releases (GitHub pages hold 100)
    for n in range(130):
        FAKE.release(f"dev-0.7.0.{n + 1}", [FAKE.asset(f"dev-0.7.0.{n + 1}", f"OpenPara-Playground-app-0.7.0.{n + 1}.zip", b"zip")], prerelease=True, into=FAKE.big)
    keep = core.API
    core.API = FAKE.base + "/big/releases"
    try:
        many = core.list_builds(inst)
        assert len(many) == 130 and many[0]["version"] == "0.7.0.130" and many[-1]["version"] == "0.7.0.1", (len(many), many[0]["version"])
        assert FAKE.hits.count("/big/releases") == 2, "two pages were asked for"
    finally:
        core.API = keep
    # GitHub cannot be reached: a plain message, nothing raised from deep inside
    keep = core.API
    core.API = "http://127.0.0.1:9/none"
    try:
        ex = raises(core.UpdaterError, core.list_builds, inst, 3)
        assert "Could not reach GitHub" in str(ex), str(ex)
    finally:
        core.API = keep

    # ============================================================================================== 2. downloads and zips
    d = os.path.join(WORK, "dl")
    os.makedirs(d)
    a = builds[0]["app"]
    got = core.download(a, os.path.join(d, "ok.zip"))
    assert os.path.getsize(got) == a["size"] and core.inspect_zip(got)["version"] == "0.8.6.108"
    FAKE.corrupt.add(a["name"])
    ex = raises(core.UpdaterError, core.download, a, os.path.join(d, "bad.zip"))
    assert "checksum" in str(ex) and not os.path.exists(os.path.join(d, "bad.zip")) and not os.path.exists(os.path.join(d, "bad.zip.part")), "nothing is left behind"
    FAKE.corrupt.clear()
    nodigest = add_pg("0.8.6.150", digest=False)
    FAKE.short.add("OpenPara-Playground-app-0.8.6.150.zip")
    asset150 = nodigest["assets"][0]
    ex = raises(core.UpdaterError, core.download, asset150, os.path.join(d, "short.zip"))
    assert "incomplete" in str(ex) and not os.path.exists(os.path.join(d, "short.zip")), str(ex)
    FAKE.short.clear()
    FAKE.releases.remove(nodigest)
    cancelled = raises(core.Cancelled, core.download, a, os.path.join(d, "c.zip"), None, lambda: True)
    assert not os.path.exists(os.path.join(d, "c.zip.part"))
    # zips that must be refused
    evil = os.path.join(d, "evil.zip")
    open(evil, "wb").write(zip_bytes(app_files("0.8.6.1"), evil="../../outside_marker.txt"))
    assert "outside the program folder" in str(raises(core.UpdaterError, core.inspect_zip, evil))
    assert "outside" in str(raises(core.UpdaterError, core.extract_safe, evil, os.path.join(d, "x")))
    assert not os.path.exists(os.path.join(WORK, "outside_marker.txt")) and not os.path.exists(os.path.join(d, "x", "..", "..", "outside_marker.txt"))
    abs_zip = os.path.join(d, "abs.zip")
    open(abs_zip, "wb").write(zip_bytes(app_files("0.8.6.1"), evil="C:/Windows/x.txt"))
    assert "outside" in str(raises(core.UpdaterError, core.inspect_zip, abs_zip))
    notzip = os.path.join(d, "not.zip")
    open(notzip, "wb").write(b"this is not a zip")
    assert "damaged" in str(raises(core.UpdaterError, core.inspect_zip, notzip))
    noruntime = os.path.join(d, "nort.zip")
    f = app_files("0.8.6.1")
    del f["runtime.json"]
    open(noruntime, "wb").write(zip_bytes(f))
    assert "not an OpenPara program zip" in str(raises(core.UpdaterError, core.inspect_zip, noruntime))
    # the other program's zip, and another runtime
    rel_zip = os.path.join(d, "rel.zip")
    open(rel_zip, "wb").write(zip_bytes(app_files("0.8.5", "release")))
    ex = raises(core.UpdaterError, core.check_zip_for, inst, core.inspect_zip(rel_zip))
    assert "not to OpenPara Playground" in str(ex) and not isinstance(ex, core.NeedsInstaller), str(ex)
    pg_zip = os.path.join(d, "pg.zip")
    open(pg_zip, "wb").write(zip_bytes(app_files("0.8.6.1", "playground")))
    assert "belongs to OpenPara Playground, not to OpenPara" in str(raises(core.UpdaterError, core.check_zip_for, rinst, core.inspect_zip(pg_zip)))
    rt2 = os.path.join(d, "rt2.zip")
    open(rt2, "wb").write(zip_bytes(app_files("0.8.6.7", "playground", runtime=2)))
    ex = raises(core.NeedsInstaller, core.check_zip_for, inst, core.inspect_zip(rt2), {"version": "0.8.6.7"})
    assert "full installer" in str(ex) and ex.build == {"version": "0.8.6.7"}

    # ============================================================================================== 3. the swap and the saved copy
    inst, user = make_install("0.8.6.106")
    FAKE.hits.clear()
    b108 = next(b for b in core.list_builds(inst) if b["version"] == "0.8.6.108")
    b106 = next(b for b in core.list_builds(inst) if b["version"] == "0.8.6.106")
    res = core.install_build(inst, b108)
    assert inst.version == "0.8.6.108" and inst.saved_version() == "0.8.6.106" and not res["saved"] and not os.path.exists(inst.new)
    assert read(os.path.join(inst.app, "marker.txt")) == "0.8.6.108" and read(os.path.join(inst.old, "marker.txt")) == "0.8.6.106"
    assert len(FAKE.downloads()) == 1
    # the saved copy goes back without a download, and again the other way round
    res = core.install_build(inst, b106)
    assert res["saved"] and inst.version == "0.8.6.106" and inst.saved_version() == "0.8.6.108" and len(FAKE.downloads()) == 1, "no download for the saved copy"
    res = core.install_build(inst, b108, use_saved=False)
    assert not res["saved"] and len(FAKE.downloads()) == 2, "use_saved=False downloads"
    # a saved copy of another runtime is not used for a build it does not fit: it downloads
    shutil.rmtree(inst.old)
    os.makedirs(inst.old)
    for n, t in app_files("0.8.6.106", "playground", runtime=2).items():
        open(os.path.join(inst.old, n), "w").write(t)
    FAKE.hits.clear()
    core.install_build(inst, b106)
    assert len(FAKE.downloads()) == 1 and inst.runtime == 1, "the saved copy has another runtime: the build is downloaded instead"
    # a damaged download changes nothing
    before = sorted(os.listdir(inst.app))
    FAKE.corrupt.add(b108["app"]["name"])
    ex = raises(core.UpdaterError, core.install_build, inst, b108, use_saved=False)        # (the saved copy is 0.8.6.108 now: it would be used otherwise)
    FAKE.corrupt.clear()
    assert inst.version == "0.8.6.106" and sorted(os.listdir(inst.app)) == before and not os.path.exists(inst.new), "a damaged download leaves the program alone"
    # a failed swap puts the old program back
    real_replace = os.replace
    calls = []

    def failing_replace(src, dst, *a, **k):
        if src == inst.new and dst == inst.app:
            calls.append(1)
            raise PermissionError("the folder is in use")
        return real_replace(src, dst, *a, **k)
    core._retry.__defaults__ = (6, 0.0)                    # the retries need no real waiting here
    os.replace = failing_replace
    try:
        ex = raises(core.UpdaterError, core.install_build, inst, b108, use_saved=False)
    finally:
        os.replace = real_replace
    assert len(calls) == 6 and "Your version was put back" in str(ex), (len(calls), str(ex))
    assert inst.version == "0.8.6.106" and read(os.path.join(inst.app, "marker.txt")) == "0.8.6.106" and not os.path.exists(inst.new), "the old program is back"
    # replacing the program folder fails at the first step: nothing changed, the message says so
    os.replace = lambda s, dst, *a, **k: (_ for _ in ()).throw(PermissionError("locked")) if s == inst.app else real_replace(s, dst, *a, **k)
    try:
        ex = raises(core.UpdaterError, core.install_build, inst, b108, use_saved=False)
    finally:
        os.replace = real_replace
        core._retry.__defaults__ = (6, 0.7)
    assert "Your version is unchanged" in str(ex) and inst.version == "0.8.6.106" and not os.path.exists(inst.new)
    # a zip without gpd_app.py is not a program
    nogpd = os.path.join(d, "nogpd.zip")
    open(nogpd, "wb").write(zip_bytes({k: v for k, v in app_files("0.8.6.5").items() if k != "gpd_app.py"}))
    assert "not an OpenPara program zip" in str(raises(core.UpdaterError, core.inspect_zip, nogpd))

    # ============================================================================================== 4. add-ons of a build
    inst, user = make_install("0.8.6.108")
    b105 = next(b for b in core.list_builds(inst) if b["version"] == "0.8.6.105")
    code = lambda aid: read(os.path.join(user, "addons", aid, aid + "_ext.py")).strip()
    site = lambda aid: os.path.join(user, "addons", aid, "site", "pkg", "__init__.py")
    res = core.restore_addons(inst, b105)
    assert res["restored"] == ["foo"] and res["skipped"] == ["bar"] and not res["failed"], res
    assert code("foo") == "CODE = '0.8.6.105'" and code("bar") == "CODE = 'user-old'", "foo gets the code of that build, bar (not in that build) is left"
    assert os.path.isfile(site("foo")) and os.path.isfile(site("bar")), "the downloaded packages stay"
    assert json.load(open(os.path.join(user, "addons", "foo", "addon.json")))["version"] == "0.8.6.105"
    assert not [n for n in os.listdir(os.path.join(user, "addons")) if n.startswith(".")], "no staging folders are left"
    # one add-on that fails (damaged) stays as it was, with its packages
    inst, user = make_install("0.8.6.108")
    FAKE.corrupt.add("addon-foo.zip")
    res = core.restore_addons(inst, b105)
    FAKE.corrupt.clear()
    assert list(res["failed"]) == ["foo"] and "checksum" in res["failed"]["foo"] and res["restored"] == [], res
    assert code("foo") == "CODE = 'user-old'" and os.path.isfile(site("foo")), "a failed add-on is left exactly as it was"
    assert not [n for n in os.listdir(os.path.join(user, "addons")) if n.startswith(".")]
    # install_build restores add-ons only when asked (going back / repair), not for a forward update
    inst, user = make_install("0.8.6.106")
    core.install_build(inst, next(b for b in core.list_builds(inst) if b["version"] == "0.8.6.108"))
    assert code("foo") == "CODE = 'user-old'", "an update leaves the add-ons alone (the program offers to update them)"
    res = core.install_build(inst, b105, restore_addons_too=True)
    assert res["addons"]["restored"] == ["foo"] and code("foo") == "CODE = '0.8.6.105'" and inst.version == "0.8.6.105"
    # going back to the saved copy of a build that is not on GitHub any more: the program comes back, no add-on is touched
    ghost = {"version": "0.8.6.108", "tag": "x", "date": "", "app": None, "setup": None, "addons": {}}
    res = core.install_build(inst, ghost, restore_addons_too=True)
    assert res["saved"] and inst.version == "0.8.6.108" and res["addons"]["restored"] == []

    # ============================================================================================== 5. start and wait for the note
    inst, user = make_install("0.8.6.106")
    p = launch(inst, token="tok-1")
    out = core.wait_started(inst, p, "tok-1", timeout=15)
    assert out[0] == "ok", out
    st = core.read_run_state(inst)
    assert st["token"] == "tok-1" and st["ok"] and st["version"] == "0.8.6.106" and st["safe"] is False and core.program_running(inst)
    close_program(inst)
    assert not core.program_running(inst), "a program that was closed is not running"
    # an old note with another token is not believed (a note left by a program that was started before)
    inst_h, user_h = make_install("0.8.6.107", kind="hang")
    json.dump({"pid": 1, "token": "tok-2", "ok": True}, open(os.path.join(user_h, "run_state.json"), "w"))
    ph = launch(inst_h, token="tok-3")
    out = core.wait_started(inst_h, ph, "tok-3", timeout=2.5)
    assert out[0] == "timeout" and "No sign of life" in out[2], out
    ph.kill()
    ph.wait()
    # a crash and a silent exit are told apart from a hang, and the crash is in the error log
    inst_c, user_c = make_install("0.8.6.107", kind="crash")
    pc = launch(inst_c, token="tok-4")
    out = core.wait_started(inst_c, pc, "tok-4", timeout=15)
    assert out[0] == "exited" and "exit code 1" in out[2], out
    assert "this build crashes at start" in read(os.path.join(user_c, "gpd_error.log")) and "The program could not start" in read(os.path.join(user_c, "gpd_error.log"))
    assert core.read_run_state(inst_c)["ok"] is False and "crashes at start" in core.read_run_state(inst_c)["failed"]
    inst_s, user_s = make_install("0.8.6.107", kind="silent_exit")
    out = core.wait_started(inst_s, launch(inst_s, token="tok-5"), "tok-5", timeout=15)
    assert out[0] == "exited" and "exit code 0" in out[2], out
    # an old build (no runstate.py): never called broken for the missing note
    inst_o, user_o = make_install("0.8.6.100", kind="old")
    po = launch(inst_o, token="t9")
    out = core.wait_started(inst_o, po, "t9", timeout=20, grace=1.5)
    assert out[0] == "running" and "cannot confirm" in out[2] and not core.supports_start_note(inst_o), out
    po.kill()
    po.wait()
    inst_oc, _ = make_install("0.8.6.100", kind="old_crash")
    assert core.wait_started(inst_oc, launch(inst_oc, token="t10"), "t10", timeout=20, grace=1.5)[0] == "exited"
    inst_r, _ = make_install("0.8.6.100")
    assert core.supports_start_note(inst_r) and core.supports_safe_start(inst_r)
    # a build that DOES report but says nothing is a hang, whatever the grace
    inst_h3, _ = make_install("0.8.6.107", kind="hang")
    ph3 = launch(inst_h3, token="t11")
    assert core.wait_started(inst_h3, ph3, "t11", timeout=2.5, grace=0.5)[0] == "timeout", "a build that reports is judged by the note, not by the grace"
    ph3.kill()
    ph3.wait()
    # cancel
    inst_h2, _ = make_install("0.8.6.107", kind="hang")
    ph = launch(inst_h2, token="t6")
    assert core.wait_started(inst_h2, ph, "t6", timeout=20, cancel=lambda: True)[0] == "cancelled"
    ph.kill()
    ph.wait()
    # safe start reaches the program
    inst_f, user_f = make_install("0.8.6.106")
    pf = launch(inst_f, token="t7", safe=True)
    assert core.wait_started(inst_f, pf, "t7", timeout=15)[0] == "ok" and core.read_run_state(inst_f)["safe"] is True
    close_program(inst_f)
    # the lock: one updater at a time
    assert core.take_lock(inst_f) and core.take_lock(inst_f)
    lockp = os.path.join(user_f, "updater.lock")
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    json.dump({"pid": sleeper.pid}, open(lockp, "w"))
    assert not core.take_lock(inst_f), "another live updater holds the lock"
    sleeper.kill()
    sleeper.wait()
    assert core.take_lock(inst_f), "a dead holder does not block"
    core.drop_lock(inst_f)
    assert not os.path.exists(lockp)

    # ============================================================================================== 6. the command line, end to end
    inst, user = make_install("0.8.6.106")
    rc, out = cli(inst, user, "--list")
    assert rc == 0 and out.count("0.8.6.10") >= 1 and "(4 earlier builds; --all shows them)" in out and "0.8.6.100" not in out, out
    assert "0.8.6.106" in out and "installed" in out
    rc, out = cli(inst, user, "--list", "--all")
    assert rc == 0 and "0.8.6.100" in out and "earlier builds" not in out, out
    rc, out = cli(inst, user, "--report")
    assert rc == 0 and "Installed: 0.8.6.106" in out and "Installed add-ons: bar 0.0.1, foo 0.0.1" in out, out
    # update to the newest: installed, started, "started fine", the safety copy is dropped
    FAKE.hits.clear()
    rc, out = cli(inst, user, "--update")
    assert rc == 0 and "started fine" in out and "0.8.6.106 -> 0.8.6.108" in out, out
    assert inst.version == "0.8.6.108" and inst.saved_version() is None, "a healthy start drops the safety copy"
    assert core.program_running(inst) and core.read_run_state(inst)["version"] == "0.8.6.108"
    assert "started the program" in read(os.path.join(user, "updater.log"))
    # the program is open: the files are not touched
    rc, out = cli(inst, user, "--install", "0.8.6.103")
    assert rc == 1 and "is running; close it first" in out and inst.version == "0.8.6.108", out
    close_program(inst)
    rc, out = cli(inst, user, "--update", "--no-start")
    assert rc == 0 and "is already the newest build" in out and inst.version == "0.8.6.108", out
    # going back to an earlier build: that build's zip and add-ons, started, fine
    rc, out = cli(inst, user, "--install", "0.8.6.103")
    assert rc == 0 and "0.8.6.108 -> 0.8.6.103 (add-ons of that build are put back)" in out and "Add-ons put back: foo" in out, out
    assert inst.version == "0.8.6.103" and code("foo") == "CODE = '0.8.6.103'" and os.path.isfile(site("foo"))
    close_program(inst)
    # an unknown build
    rc, out = cli(inst, user, "--install", "0.8.6.7")
    assert rc == 1 and "was not found on GitHub" in out and inst.version == "0.8.6.103"
    # repair: the same build again, add-ons set back
    open(os.path.join(inst.app, "marker.txt"), "w").write("damaged")
    os.remove(os.path.join(inst.app, "version.py"))
    rc, out = cli(inst, user, "--repair", "--no-start")
    assert rc == 0 and read(os.path.join(inst.app, "marker.txt")) == "0.8.6.103" and os.path.isfile(os.path.join(inst.app, "version.py")), out
    # an old build (from before the start note) cannot say it started fine: the updater does not call it broken, does not drop the safety copy, and refuses
    # a "safe start" that the build would not understand
    inst_o, user_o = make_install("0.8.6.106")
    add_pg("0.8.6.90", kind="old")
    add_pg("0.8.6.91", kind="old_crash")
    rc, out = cli(inst_o, user_o, "--install", "0.8.6.90", extra={"OPARA_UPDATER_WAIT": "3"})
    assert rc == 0 and "cannot confirm that it started fine" in out and "did not start properly" not in out, (rc, out)
    assert inst_o.version == "0.8.6.90" and inst_o.saved_version() == "0.8.6.106", "no verdict: the safety copy stays"
    assert not core.supports_start_note(inst_o) and not core.supports_safe_start(inst_o)
    for pth in os.listdir("/proc"):                                    # the old program does not write a note, so it is found by its command line
        if pth.isdigit():
            try:
                if os.path.join(inst_o.app, "gpd_app.py") in open(f"/proc/{pth}/cmdline").read():
                    os.kill(int(pth), signal.SIGTERM)
            except OSError:
                pass
    time.sleep(0.5)
    rc, out = cli(inst_o, user_o, "--start-safe")
    assert rc == 1 and "older than the safe start" in out and not core.program_running(inst_o), (rc, out)
    rc, out = cli(inst_o, user_o, "--install", "0.8.6.91", "--no-start")
    assert rc == 0
    rc, out = cli(inst_o, user_o, "--start", extra={"OPARA_UPDATER_WAIT": "3"})
    assert rc == 3 and "did not start properly" in out and "exit code 1" in out, (rc, out)
    # a BROKEN build: it is installed, it does not start, the updater says so and does NOT go back by itself
    inst, user = make_install("0.8.6.106")
    add_pg("0.8.6.109", kind="crash")
    rc, out = cli(inst, user, "--update")
    assert rc == 3 and "did not start properly" in out and "--cli --go-back" in out, (rc, out)
    assert inst.version == "0.8.6.109" and inst.saved_version() == "0.8.6.106", "no automatic rollback: the broken build is still installed, the earlier one is kept"
    rc, out = cli(inst, user, "--go-back")
    assert rc == 0 and inst.version == "0.8.6.106" and "from the saved copy" in out and "started fine" in out, out
    close_program(inst)
    # a build that hangs (never says it started fine) is reported as such
    add_pg("0.8.6.110", kind="hang")
    rc, out = cli(inst, user, "--install", "0.8.6.110", extra={"OPARA_UPDATER_WAIT": "3"})
    assert rc == 3 and "No sign of life" in out and inst.version == "0.8.6.110", (rc, out)
    close_program(inst)
    # another runtime: exit 2, nothing changed, the installer is named
    add_pg("0.8.6.111", runtime=2)
    rc, out = cli(inst, user, "--install", "0.8.6.111", "--no-start")
    assert rc == 2 and "full installer can put it in" in out and "OpenPara-Playground-Setup-0.8.6.111.exe" in out and inst.version == "0.8.6.110", (rc, out)
    # the other channel never installs: the release channel's list has no dev builds
    rinst, ruser = make_install("0.8.4", "release")
    rc, out = cli(rinst, ruser, "--install", "0.8.6.108", "--no-start")
    assert rc == 1 and "was not found on GitHub" in out and rinst.version == "0.8.4", out
    rc, out = cli(rinst, ruser, "--update", "--no-start")
    assert rc == 0 and rinst.version == "0.8.5", out

    # ============================================================================================== 7. the tool refreshes itself
    tdir = os.path.join(WORK, "tool_a", "updater_tool")
    shutil.copytree(TOOL, tdir, ignore=shutil.ignore_patterns("__pycache__"))
    app_tool = os.path.join(WORK, "tool_a", "app", "updater_tool")

    def make_app_tool(version, break_with=None):
        shutil.rmtree(app_tool, ignore_errors=True)
        shutil.copytree(TOOL, app_tool, ignore=shutil.ignore_patterns("__pycache__"))
        p = os.path.join(app_tool, "ou_core.py")
        t = read(p).replace("TOOL_VERSION = 1", f"TOOL_VERSION = {version}")
        open(p, "w", encoding="utf-8").write(t)
        if break_with == "syntax":
            open(os.path.join(app_tool, "ou_window.py"), "a").write("\ndef broken(:\n")
        elif break_with == "import":
            open(os.path.join(app_tool, "ou_window.py"), "a").write("\nimport a_module_that_does_not_exist_at_all\n")
    make_app_tool(1)
    assert not tool.refresh_from_app(tdir, app_tool), "the same version is not copied"
    make_app_tool(0)
    assert not tool.refresh_from_app(tdir, app_tool), "an older version is never copied"
    make_app_tool(2, "syntax")
    assert not tool.refresh_from_app(tdir, app_tool) and tool.tool_version_of(tdir) == 1 and not os.path.exists(tdir + ".new"), "a tool that does not compile is not used"
    make_app_tool(2, "import")
    assert not tool.refresh_from_app(tdir, app_tool) and tool.tool_version_of(tdir) == 1 and "a_module_that_does_not_exist" not in read(os.path.join(tdir, "ou_window.py")), \
        "a tool that fails its self-test: the old one is put back"
    assert not os.path.exists(tdir + ".bak") or tool.tool_version_of(tdir + ".bak") in (0, 1)
    make_app_tool(2)
    # (the refresh runs the new tool's self-test with this Python, which has PyQt6: it passes)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    assert tool.refresh_from_app(tdir, app_tool) and tool.tool_version_of(tdir) == 2 and tool.tool_version_of(tdir + ".bak") == 1, "a newer, sound tool replaces the folder"
    assert not tool.refresh_from_app(tdir, tdir) and not tool.refresh_from_app(tdir, os.path.join(WORK, "nowhere"))
    # through the entry point: the program folder has a newer tool; the updater that starts is the new one
    root = os.path.join(WORK, "tool_b")
    inst_b, user_b = make_install("0.8.6.106")
    shutil.copytree(TOOL, os.path.join(inst_b.root, "updater_tool"), ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(TOOL, os.path.join(inst_b.app, "updater_tool"), ignore=shutil.ignore_patterns("__pycache__"))
    p = os.path.join(inst_b.app, "updater_tool", "ou_core.py")
    text = read(p).replace("TOOL_VERSION = 1", "TOOL_VERSION = 3")
    open(p, "w", encoding="utf-8").write(text)
    e = env_for(inst_b, user_b)
    e.pop("OPARA_UPDATER_NO_REFRESH")
    r = subprocess.run([sys.executable, os.path.join(inst_b.root, "updater_tool", "openpara_updater.py"), "--cli", "--report"], env=e, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "updater 3 -" in r.stdout and tool.tool_version_of(os.path.join(inst_b.root, "updater_tool")) == 3, (r.stdout, r.stderr)

    # ============================================================================================== 8. the program side
    import paths
    import updater
    import update_ui
    inst_p, user_p = make_install("0.8.6.106")
    saved_code_dir = paths.CODE_DIR
    paths.CODE_DIR = inst_p.app                                                # as if the program ran from root\app
    try:
        assert updater.installed_layout() == (inst_p.root, inst_p.app)
        assert updater.tool_script() is None and updater.tool_command("--x") is None, "an install without the updater has none"
        assert not updater.seed_tool(), "nothing to seed from"
        # seeding: the program folder carries the tool; an install updated in the program (no updater yet) gets it
        shutil.copytree(TOOL, os.path.join(inst_p.app, "updater_tool"), ignore=shutil.ignore_patterns("__pycache__"))
        assert updater.seed_tool() and os.path.isfile(os.path.join(inst_p.root, "updater_tool", "openpara_updater.py"))
        assert updater.tool_script() == os.path.join(inst_p.root, "updater_tool", "openpara_updater.py")
        assert updater.tool_command("--list") == [sys.executable, updater.tool_script(), "--list"]
        open(os.path.join(inst_p.root, "updater_tool", "mine.txt"), "w").write("kept")
        assert not updater.seed_tool() and os.path.isfile(os.path.join(inst_p.root, "updater_tool", "mine.txt")), "an existing updater is never overwritten by the seed"
        # update_now / hand_over / open_updater without Qt windows
        from PyQt6.QtWidgets import QApplication, QWidget
        app = QApplication.instance() or QApplication([])

        class Shell(QWidget):
            closed = 0
            ok = True

            def close_for_restart(self):
                Shell.closed += 1
                return Shell.ok
        spawned, installed, quits = [], [], []
        ctl = update_ui.UpdateController(Shell())
        ctl.install = lambda rel: installed.append(rel["version"])
        real_popen, real_quit = subprocess.Popen, QApplication.quit
        subprocess.Popen = lambda cmd, **k: (spawned.append((cmd, k)), type("P", (), {"pid": 1})())[1]
        QApplication.quit = staticmethod(lambda: quits.append(1))
        try:
            rel = {"version": "0.8.6.108", "app": {"name": "x"}}
            assert ctl.updater_available()
            ctl.update_now(rel)
            assert not installed and len(spawned) == 1 and quits == [1], "with the updater: the program closes and the updater is started"
            cmd, kw = spawned[0]
            assert cmd[:2] == [sys.executable, updater.tool_script()] and cmd[2:] == ["--update-to", "0.8.6.108", "--wait-pid", str(os.getpid())], cmd
            assert kw["cwd"] == inst_p.root and Shell.closed == 1
            Shell.ok = False                                                    # the person cancels at "save your document?"
            spawned.clear()
            quits.clear()
            ctl.update_now(rel)
            assert not spawned and not quits and not installed, "cancelled: nothing is started and the program stays"
            Shell.ok = True
            ctl.open_updater()
            assert spawned[-1][0][2:] == [] and not quits, "Help > Open the updater: the program keeps running"
            # the spawn fails after the window closed: the program is started again rather than leave nothing
            spawned.clear()
            quits.clear()
            n = [0]

            def flaky(cmd, **k):
                n[0] += 1
                if n[0] == 1:
                    raise OSError("no such file")
                spawned.append(cmd)
                return type("P", (), {"pid": 1})()
            subprocess.Popen = flaky
            ctl.update_now(rel)
            assert spawned and spawned[0] == updater.restart_command() and quits == [1], (spawned, quits)
        finally:
            subprocess.Popen = real_popen
            QApplication.quit = real_quit
        # an install WITHOUT the updater keeps updating in the program as before
        shutil.rmtree(os.path.join(inst_p.root, "updater_tool"))
        installed.clear()
        spawned.clear()
        ctl.update_now(rel)
        assert installed == ["0.8.6.108"] and not spawned and not ctl.updater_available(), "no updater: the old in-program update"
    finally:
        paths.CODE_DIR = saved_code_dir

    # the early error hook, the started-fine note and safe start, in a real start of a process
    ud = tempfile.mkdtemp(prefix="rs_", dir=WORK)
    child = r'''
import os, sys, json, time
sys.path.insert(0, %(here)r)
import runstate
runstate.begin()
st = runstate.read()
assert st["pid"] == os.getpid() and st["ok"] is False and st["token"] == "T1" and st["ended"] is None, st
assert sys.excepthook is runstate.early_hook
runstate.mark_ok()
st = runstate.read()
assert st["ok"] is True and st["ok_at"] >= st["started"], st
open(os.path.join(os.environ["OPARA_USER_DIR"], "crash_marker"), "w").write(open(os.path.join(os.environ["OPARA_USER_DIR"], "gpd_crash.log")).read())
raise ValueError("an error before the window")
''' % {"here": HERE}
    r = subprocess.run([sys.executable, "-c", child], env=dict(os.environ, OPARA_USER_DIR=ud, OPARA_START_TOKEN="T1", OPARA_NO_STARTUP_BOX="1"), capture_output=True, text=True, timeout=60)
    st = json.load(open(os.path.join(ud, "run_state.json")))
    assert r.returncode == 1 and st["ok"] is True and st["ended"] and "an error before the window" in st["failed"], (r.returncode, r.stderr, st)
    log = read(os.path.join(ud, "gpd_error.log"))
    assert "The program could not start" in log and "ValueError: an error before the window" in log and "Traceback" in log
    assert read(os.path.join(ud, "crash_marker")).startswith("--- start "), "gpd_crash.log is open from the first moment"
    # safe start: add-ons off, the Playground in Testing, nothing installed, the title says so; without it nothing changes
    probe = r'''
import os, sys, json
sys.path.insert(0, %(here)r)
import channel, addons
addons.status = lambda aid: "update"
print(json.dumps({"safe": channel.safe_start(), "mode": channel.mode(), "title": channel.title(), "full_dev": channel.is_full_dev(),
                  "outdated": addons.outdated(), "dev_dir": addons.dev_dir()}))
class Boom(Exception): pass
def refuse(*a, **k): raise Boom("must not install in a safe start")
addons.install = refuse
addons.startup()
addons.activate()                                                  # (an install from the Add-ons window calls this too)
base = os.path.join(os.environ["OPARA_USER_DIR"], "addons")
on_path = [p for p in sys.path if p.startswith(base)]
sys.path.insert(0, addons.installed_path("partgen"))              # even a folder that is on the path does not make an add-on active in a safe start
print(json.dumps({"errors": dict(addons.STARTUP_ERRORS), "active": [a for a in addons.known() if addons.is_active(a)], "on_path": on_path}))
''' % {"here": HERE}
    def run_probe(safe):
        ud2 = tempfile.mkdtemp(prefix="sp_", dir=WORK)
        os.makedirs(os.path.join(ud2, "addons", "partgen"))
        json.dump({"id": "partgen", "name": "Part Generator", "version": "0.0.1", "extension": "partgen_ext"}, open(os.path.join(ud2, "addons", "partgen", "addon.json"), "w"))
        e = dict(os.environ, OPARA_USER_DIR=ud2, OPARA_CHANNEL="playground", OPARA_PLAYGROUND_MODE="full", OPARA_NO_UPDATE="1")
        if safe:
            e["OPARA_SAFE_START"] = "1"
        r = subprocess.run([sys.executable, "-c", probe], env=e, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        lines = [json.loads(x) for x in r.stdout.strip().splitlines()]
        return lines
    a1, a2 = run_probe(True)
    assert a1["safe"] and a1["mode"] == "testing" and not a1["full_dev"] and "safe start" in a1["title"] and a1["outdated"] == [] and a1["dev_dir"] is None, a1
    assert a2["errors"] == {} and a2["active"] == [] and a2["on_path"] == [], "a safe start installs nothing (addons.install would have raised) and activates nothing"
    b1, b2 = run_probe(False)
    assert not b1["safe"] and b1["mode"] == "full" and b1["full_dev"] and "safe start" not in b1["title"], b1
    assert b2["errors"] and "must not install" in list(b2["errors"].values())[0], "the same start without the switch does try to install the shipped add-ons"
    assert b2["on_path"] and "partgen" in b2["active"], "... and activates the installed ones"
    print("OK updater tool")


if __name__ == "__main__":
    try:
        main()
    finally:
        FAKE.server.shutdown()
        shutil.rmtree(WORK, ignore_errors=True)
