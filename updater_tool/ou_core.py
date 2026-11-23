"""
ou_core.py - what the OpenPara Updater does.  No Qt and NO import of OpenPara's own code (only the standard library): this has to work when OpenPara
itself cannot start.

The installer puts it next to the program:   <install folder>\\python\\   <install folder>\\app\\   <install folder>\\updater_tool\\
Every program file the updater changes is in  app\\ ; the user's own data (settings, add-ons, projects) is never touched, except the code of the
installed add-ons when an OLDER build is put back (see restore_addons).

What it can do
    list_builds     the builds on GitHub of this program (OpenPara: releases v0.x.y; Playground: pre-releases dev-0.x.y.z), newest first
    install_build   download a build's program zip (checked: size, SHA-256 when GitHub gives it, zip content), then swap it in for app\\; the folder it
                    replaces is kept as app.old (a safety copy) until the new build has started fine; or use that saved copy without downloading
    restore_addons  put the add-on code of a build (from the same GitHub release) back for the add-ons that are installed
    launch / wait_started   start the program and wait for its "started fine" note (run_state.json, written by OpenPara 4 s after its window is up)
    report_text     a text to copy: versions, the tail of the error logs, the add-ons, what the updater did
A rollback is never automatic: the window offers it, the person presses the button.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

TOOL_VERSION = 1
REPO = "Bubbletoppoet47/OpenPara"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
API = os.environ.get("OPARA_UPDATER_API") or f"https://api.github.com/repos/{REPO}/releases"      # the tests point it at a local fake server
SHOW_FIRST = 5                                    # the window shows this many builds, the rest after "Show all"
RUN_STATE = "run_state.json"
LOG_NAME = "updater.log"


class UpdaterError(Exception):
    """A problem with a plain-words message (shown as it is)."""


class NeedsInstaller(UpdaterError):
    """The build needs another bundled Python / packages than the installed one: only its full installer can put it in."""
    def __init__(self, message, build=None):
        super().__init__(message)
        self.build = build


class Cancelled(UpdaterError):
    pass


# ---------------------------------------------------------------------------------------------------- the installation
def vkey(text):
    """'v0.8.6' / 'dev-0.8.6.115' / '0.8.6.115' -> a tuple that sorts by version."""
    s = str(text)
    s = s[4:] if s.startswith("dev-") else s.lstrip("vV")
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", s) if p != "")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


class Install:
    """The installation this updater belongs to.  The program folder may be damaged (that is what the updater is for): nothing here needs it to work."""

    def __init__(self, root, channel=None):
        self.root = os.path.abspath(root)
        self.app = os.path.join(self.root, "app")
        self.old = self.app + ".old"
        self.new = self.app + ".new"
        ch = (channel or os.environ.get("OPARA_UPDATER_CHANNEL") or _read_json(os.path.join(self.app, "channel.json")).get("channel") or "").strip().lower()
        if not ch:                                              # no channel.json (damaged app folder): the installer's folder name says it
            ch = "playground" if "playground" in os.path.basename(self.root).lower() else "release"
        self.channel = "playground" if ch == "playground" else "release"
        self.name = "OpenPara Playground" if self.is_playground else "OpenPara"

    @property
    def is_playground(self):
        return self.channel == "playground"

    @property
    def prefix(self):
        """Start of the file names of this program's zip and installer on GitHub."""
        return "OpenPara-Playground-" if self.is_playground else "OpenPara-"

    @property
    def tag_prefix(self):
        return "dev-" if self.is_playground else "v"

    def user_dir(self):
        d = os.environ.get("OPARA_USER_DIR")
        if not d:
            base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
            d = os.path.join(base, self.name)
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d

    def python_exe(self):
        """The program's own Python (a renamed pythonw.exe), else any python."""
        env = os.environ.get("OPARA_UPDATER_PYTHON")
        if env:
            return env
        for n in ("OpenPara.exe", "pythonw.exe", "python.exe"):
            p = os.path.join(self.root, "python", n)
            if os.path.isfile(p):
                return p
        return sys.executable

    def info_of(self, folder):
        """{'version', 'runtime'} of a program folder (app\\ or app.old\\): runtime.json, else version.py; None where it cannot be read."""
        d = _read_json(os.path.join(folder, "runtime.json"))
        ver, rt = d.get("version"), d.get("runtime")
        if ver is None or rt is None:
            try:
                with open(os.path.join(folder, "version.py"), encoding="utf-8") as f:
                    text = f.read()
                m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
                r = re.search(r"^RUNTIME\s*=\s*(\d+)", text, re.M)
                ver = ver or (m.group(1) if m else None)
                rt = rt if rt is not None else (int(r.group(1)) if r else None)
            except OSError:
                pass
        return {"version": str(ver) if ver is not None else None, "runtime": int(rt) if rt is not None else None}

    @property
    def version(self):
        return self.info_of(self.app)["version"]

    @property
    def runtime(self):
        return self.info_of(self.app)["runtime"]

    def saved_version(self):
        """The version of the safety copy app.old (None when there is none)."""
        return self.info_of(self.old)["version"] if os.path.isdir(self.old) else None


def find_install(root=None, channel=None):
    """The Install of this updater: `root`, or the folder above updater_tool\\ (OPARA_UPDATER_ROOT overrides it: tests)."""
    root = root or os.environ.get("OPARA_UPDATER_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(root):
        raise UpdaterError(f"The folder {root} does not exist.")
    if not (os.path.isdir(os.path.join(root, "python")) or os.path.isdir(os.path.join(root, "app")) or os.path.isdir(os.path.join(root, "app.old"))):
        raise UpdaterError("This updater belongs to a copy of OpenPara that was installed with the installer (it has the folders python\\ and app\\). "
                           "A copy that runs from source updates with git.")
    return Install(root, channel)


# ---------------------------------------------------------------------------------------------------- the log
def log_line(inst, text):
    """One line in <user data folder>\\updater.log (kept short); never raises."""
    try:
        p = os.path.join(inst.user_dir(), LOG_NAME)
        old = ""
        if os.path.exists(p) and os.path.getsize(p) > 100000:
            with open(p, encoding="utf-8", errors="replace") as f:
                old = f.read()[-50000:]
            with open(p, "w", encoding="utf-8") as f:
                f.write(old)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------- GitHub
class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub redirects asset downloads to another host; that host must not get a token."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        r = super().redirect_request(req, fp, code, msg, headers, newurl)
        if r is not None:
            r.headers.pop("Authorization", None)
            r.unredirected_hdrs.pop("Authorization", None)
        return r


def _request(url, accept=None):
    h = {"User-Agent": "OpenPara-updater"}
    if accept:
        h["Accept"] = accept
    tok = os.environ.get("OPARA_GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return urllib.request.Request(url, headers=h)


def _open(req, timeout):
    return urllib.request.build_opener(_NoAuthOnRedirect).open(req, timeout=timeout)


def _build_of(inst, r):
    """One GitHub release -> {'tag','version','date','notes','page','app','setup','addons': {id: asset}} or None (not a build of this program)."""
    if not isinstance(r, dict) or r.get("draft"):
        return None
    tag = str(r.get("tag_name") or "")
    if inst.is_playground:
        if not tag.startswith("dev-"):
            return None
    elif tag.startswith("dev-") or r.get("prerelease") or not re.match(r"^[vV]?\d", tag):
        return None
    b = {"tag": tag, "version": tag[4:] if tag.startswith("dev-") else tag.lstrip("vV"), "date": str(r.get("published_at") or r.get("created_at") or "")[:10],
         "notes": r.get("body") or "", "page": r.get("html_url") or RELEASES_PAGE, "app": None, "setup": None, "addons": {}}
    for a in r.get("assets") or []:
        n = str(a.get("name") or "")
        if n.startswith(inst.prefix + "app-") and n.endswith(".zip"):
            b["app"] = a
        elif n.startswith(inst.prefix + "Setup-") and n.endswith(".exe"):
            b["setup"] = a
        elif n.startswith("addon-") and n.endswith(".zip"):
            b["addons"][n[len("addon-"):-len(".zip")]] = a
    return b


def list_builds(inst, timeout=20, max_pages=10):
    """Every build of this program that can be put in (it has a program zip), newest first.  Raises UpdaterError when GitHub cannot be reached."""
    out, page = [], 1
    while page <= max_pages:
        sep = "&" if "?" in API else "?"
        url = f"{API}{sep}per_page=100&page={page}"
        try:
            with _open(_request(url, "application/vnd.github+json"), timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            hint = " (GitHub allows only a few requests an hour without a sign-in; try again later)" if ex.code in (403, 429) else ""
            raise UpdaterError(f"GitHub answered {ex.code} when the list of builds was asked for{hint}.")
        except (urllib.error.URLError, OSError, ValueError) as ex:
            raise UpdaterError(f"Could not reach GitHub to get the list of builds ({ex}). Check the internet connection.")
        if not isinstance(data, list) or not data:
            break
        for r in data:
            b = _build_of(inst, r)
            if b is not None and b["app"] is not None:
                out.append(b)
        if len(data) < 100:
            break
        page += 1
    seen, uniq = set(), []
    for b in sorted(out, key=lambda b: vkey(b["version"]), reverse=True):
        if b["version"] not in seen:
            seen.add(b["version"])
            uniq.append(b)
    return uniq


def download(asset, dest, progress=None, cancel=None, timeout=30):
    """Saves a release asset (checked against its size and, when GitHub gives one, its SHA-256).  progress(done, total).  -> dest"""
    url = asset["url"] if os.environ.get("OPARA_GITHUB_TOKEN") and asset.get("url") else asset["browser_download_url"]
    part = dest + ".part"
    h = hashlib.sha256()
    done = 0
    try:
        with _open(_request(url, "application/octet-stream"), timeout) as r, open(part, "wb") as fh:
            total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
            while True:
                if cancel and cancel():
                    raise Cancelled("Cancelled.")
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except Cancelled:
        _remove(part)
        raise
    except (urllib.error.URLError, OSError) as ex:
        _remove(part)
        raise UpdaterError(f"The download of {asset.get('name', 'the file')} failed ({ex}).")
    want = str(asset.get("digest") or "")
    if want.startswith("sha256:") and want[7:].lower() != h.hexdigest():
        _remove(part)
        raise UpdaterError(f"The download of {asset.get('name', 'the file')} is damaged (its checksum does not match). Nothing was changed; try again.")
    if asset.get("size") and done != int(asset["size"]):
        _remove(part)
        raise UpdaterError(f"The download of {asset.get('name', 'the file')} is incomplete ({done} of {asset['size']} bytes). Nothing was changed; try again.")
    os.replace(part, dest)
    return dest


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------- the zip
def _unsafe(name):
    n = name.replace("\\", "/")
    return n.startswith("/") or re.match(r"^[A-Za-z]:", n) is not None or ".." in n.split("/")


def inspect_zip(path):
    """{'version','runtime','channel'} of a program zip.  Raises UpdaterError (plain words) for anything that is not a sound OpenPara program zip."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as ex:
        raise UpdaterError(f"The download is damaged (it is not a zip file: {ex}).")
    with z:
        names = z.namelist()
        for need in ("gpd_app.py", "version.py", "runtime.json"):
            if need not in names:
                raise UpdaterError("This file is not an OpenPara program zip.")
        if any(_unsafe(n) for n in names):
            raise UpdaterError("The zip has file names that point outside the program folder; it was not used.")
        if z.testzip() is not None:
            raise UpdaterError("The download is damaged (a file inside does not match its checksum).")
        try:
            d = json.loads(z.read("runtime.json").decode("utf-8"))
            info = {"version": str(d.get("version", "")), "runtime": int(d.get("runtime", 0))}
        except (ValueError, TypeError, AttributeError):
            raise UpdaterError("The zip's runtime.json cannot be read.")
        ch = "release"
        if "channel.json" in names:
            try:
                ch = "playground" if json.loads(z.read("channel.json").decode("utf-8")).get("channel") == "playground" else "release"
            except (ValueError, AttributeError):
                pass
        info["channel"] = ch
    return info


def check_zip_for(inst, info, build=None):
    """Refuses a zip that belongs to the other program, or needs another bundled runtime (then only that build's full installer can put it in)."""
    if info["channel"] != inst.channel:
        raise UpdaterError(f"This build belongs to {'OpenPara Playground' if info['channel'] == 'playground' else 'OpenPara'}, not to {inst.name}; "
                           "the two have separate names, data folders and update sources and are never mixed.")
    have = inst.runtime
    if have is not None and info["runtime"] != have:
        raise NeedsInstaller(f"Build {info['version']} needs another bundled Python / packages than the ones installed here (runtime {info['runtime']}, "
                             f"installed {have}). Only its full installer can put it in.", build)


def _chmod_retry(func, path, exc_info):
    try:
        os.chmod(path, 0o700)
        func(path)
    except OSError:
        pass


def _rmtree(path):
    if os.path.lexists(path):
        shutil.rmtree(path, onerror=_chmod_retry)


def _retry(fn, tries=6, wait=0.7):
    """Windows may hold a folder for a moment (a virus scan, the search indexer): try a few times."""
    for i in range(tries):
        try:
            return fn()
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(wait)


def extract_safe(zip_path, dest):
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if _unsafe(n):
                raise UpdaterError("The zip has file names that point outside the program folder; it was not used.")
        z.extractall(dest)


def swap_in(inst, zip_path, log=None):
    """Puts the zip's files in app\\.  The folder it replaces is kept as app.old (a safety copy).  Nothing changes when anything fails."""
    say = log or (lambda t: None)
    _rmtree(inst.new)
    try:
        extract_safe(zip_path, inst.new)
    except UpdaterError:
        _rmtree(inst.new)
        raise
    except (OSError, zipfile.BadZipFile) as ex:
        _rmtree(inst.new)
        raise UpdaterError(f"The program files could not be unpacked ({ex}). Your version is unchanged.")
    if not os.path.isfile(os.path.join(inst.new, "gpd_app.py")):
        _rmtree(inst.new)
        raise UpdaterError("The unpacked program has no gpd_app.py; it was not used. Your version is unchanged.")
    had_app = os.path.isdir(inst.app)
    _rmtree(inst.old)
    if os.path.lexists(inst.old):
        _rmtree(inst.new)
        raise UpdaterError(f"The old safety copy {inst.old} could not be removed (a program is using it?). Close OpenPara and try again.")
    if had_app:
        try:
            _retry(lambda: os.replace(inst.app, inst.old))
        except OSError as ex:
            _rmtree(inst.new)
            raise UpdaterError("The program folder could not be replaced: something still uses it (OpenPara is open, or a virus scanner holds the files). "
                               f"Close OpenPara and try again. Your version is unchanged. ({ex})")
    try:
        _retry(lambda: os.replace(inst.new, inst.app))
    except OSError as ex:
        if had_app:
            try:
                os.replace(inst.old, inst.app)                   # put the old program back
            except OSError:
                pass
        _rmtree(inst.new)
        raise UpdaterError(f"The new program files could not be put in place ({ex}). Your version was put back.")
    say("program files replaced; the old ones are kept as app.old")
    return inst.old if had_app else None


def use_saved_copy(inst, log=None):
    """Swaps app\\ and the safety copy app.old (what the updater kept when it replaced the program): going back without downloading."""
    if not os.path.isdir(inst.old):
        raise UpdaterError("There is no saved copy of the earlier program on this computer.")
    tmp = inst.app + ".swap"
    _rmtree(tmp)
    had_app = os.path.isdir(inst.app)
    try:
        if had_app:
            _retry(lambda: os.replace(inst.app, tmp))
        _retry(lambda: os.replace(inst.old, inst.app))
    except OSError as ex:
        if had_app and not os.path.isdir(inst.app) and os.path.isdir(tmp):
            os.replace(tmp, inst.app)
        raise UpdaterError(f"The saved copy could not be put back ({ex}). Close OpenPara and try again.")
    if had_app:
        try:
            os.replace(tmp, inst.old)
        except OSError:
            _rmtree(tmp)
    (log or (lambda t: None))("the saved copy was put back")


def discard_saved_copy(inst):
    _rmtree(inst.old)
    _rmtree(inst.new)


# ---------------------------------------------------------------------------------------------------- add-ons of a build
def installed_addons(inst):
    """{id: folder} of the add-ons installed in the user's data folder (they have an addon.json)."""
    base = os.path.join(inst.user_dir(), "addons")
    out = {}
    try:
        for n in sorted(os.listdir(base)):
            if not n.startswith(".") and os.path.isfile(os.path.join(base, n, "addon.json")):
                out[n] = os.path.join(base, n)
    except OSError:
        pass
    return out


def restore_addons(inst, build, progress=None, cancel=None, log=None):
    """Puts the add-on CODE of `build` back for every add-on that is installed and that the build's release carries.  The packages an add-on downloaded
    (its site\\ folder) are kept.  -> {'restored': [ids], 'skipped': [ids], 'failed': {id: message}}"""
    say = log or (lambda t: None)
    res = {"restored": [], "skipped": [], "failed": {}}
    tmp = tempfile.mkdtemp(prefix="opara_addons_")
    try:
        todo = installed_addons(inst)
        for i, (aid, folder) in enumerate(todo.items()):
            asset = build["addons"].get(aid)
            if asset is None:
                res["skipped"].append(aid)                       # this build had no such add-on: left as it is
                continue
            if progress:
                progress(f"Add-on {aid}...", i / max(1, len(todo)))
            stage = os.path.join(os.path.dirname(folder), f".{aid}.stage")
            prev = os.path.join(os.path.dirname(folder), f".{aid}.prev")
            moved_site = None
            try:
                z = download(asset, os.path.join(tmp, asset["name"]), cancel=cancel)
                with zipfile.ZipFile(z) as zf:
                    if zf.testzip() is not None or "addon.json" not in zf.namelist():
                        raise UpdaterError("the add-on file is damaged")
                _rmtree(stage)
                _rmtree(prev)
                extract_safe(z, stage)
                site = os.path.join(folder, "site")
                if os.path.isdir(site):
                    os.replace(site, os.path.join(stage, "site"))
                    moved_site = os.path.join(stage, "site")
                os.replace(folder, prev)
                os.replace(stage, folder)
                moved_site = None
                _rmtree(prev)
                res["restored"].append(aid)
                say(f"add-on {aid} put back")
            except Cancelled:
                raise
            except (UpdaterError, OSError, zipfile.BadZipFile) as ex:
                res["failed"][aid] = str(ex)
                if moved_site and os.path.isdir(moved_site) and os.path.isdir(folder) and not os.path.isdir(os.path.join(folder, "site")):
                    try:
                        os.replace(moved_site, os.path.join(folder, "site"))     # the packages go back where they were
                    except OSError:
                        pass
                if not os.path.isdir(folder) and os.path.isdir(prev):
                    try:
                        os.replace(prev, folder)
                    except OSError:
                        pass
                _rmtree(stage)
                say(f"add-on {aid} could not be put back: {ex}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return res


# ---------------------------------------------------------------------------------------------------- one build in
def install_build(inst, build, restore_addons_too=False, progress=None, cancel=None, log=None, use_saved=True):
    """Puts `build` in: the saved copy when it is that version (no download), else the program zip from GitHub.  -> {'zip': bool, 'saved': bool, 'addons': dict|None}
    Raises NeedsInstaller (another bundled runtime), UpdaterError (plain message) or Cancelled.  The old program is kept as app.old."""
    say = log or (lambda t: None)
    prog = progress or (lambda text, frac: None)
    out = {"saved": False, "addons": None, "version": build["version"]}
    saved = inst.info_of(inst.old) if os.path.isdir(inst.old) else {"version": None, "runtime": None}
    saved_fits = saved["version"] == build["version"] and (saved["runtime"] is None or inst.runtime is None or saved["runtime"] == inst.runtime)
    if use_saved and saved_fits:
        prog("Putting the saved copy back...", 0.5)
        use_saved_copy(inst, say)
        out["saved"] = True
    else:
        tmp = tempfile.mkdtemp(prefix="opara_update_")
        try:
            asset = build["app"]
            prog(f"Downloading {build['version']}...", 0.0)
            z = download(asset, os.path.join(tmp, asset["name"]), progress=lambda d, t: prog(f"Downloading {build['version']}...", (d / t * 0.7) if t else 0.0),
                         cancel=cancel)
            prog("Checking the download...", 0.72)
            info = inspect_zip(z)
            check_zip_for(inst, info, build)
            if info["version"] != build["version"]:
                say(f"note: the zip says version {info['version']}, the release is {build['version']}")
            prog("Replacing the program files...", 0.8)
            swap_in(inst, z, say)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if restore_addons_too:
        prog("Putting the add-ons of this build back...", 0.9)
        out["addons"] = restore_addons(inst, build, progress=prog, cancel=cancel, log=say)
    prog("Done.", 1.0)
    return out


def download_installer(inst, build, progress=None, cancel=None):
    """The full installer of a build (for a build that needs another bundled runtime).  -> path"""
    if not build.get("setup"):
        raise UpdaterError("This build has no full installer on GitHub (it was removed). Open the releases page and choose another build.")
    tmp = tempfile.mkdtemp(prefix="opara_setup_")
    return download(build["setup"], os.path.join(tmp, build["setup"]["name"]), progress=progress, cancel=cancel)


# ---------------------------------------------------------------------------------------------------- the program
def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)          # (own copy: its argument types are set here and nowhere else)
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k.OpenProcess(0x00100000 | 0x1000, 0, pid)              # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102             # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:                                                            # a child that has ended and was not waited for is a zombie: not alive
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def read_run_state(inst):
    return _read_json(os.path.join(inst.user_dir(), RUN_STATE))


def program_running(inst):
    """True while the program of this installation is running (its run_state.json names a live process that has not ended)."""
    st = read_run_state(inst)
    return bool(st) and not st.get("ended") and pid_alive(st.get("pid"))


def wait_for_exit(pid, timeout=120, cancel=None, tick=0.3):
    """Waits until process `pid` has ended.  -> True when it has, False after the timeout / cancel."""
    end = time.time() + timeout
    while pid_alive(pid):
        if (cancel and cancel()) or time.time() > end:
            return False
        time.sleep(tick)
    return True


def launch(inst, token=None, safe=False, args=()):
    """Starts the program (detached, so closing the updater does not close it).  -> the Popen"""
    exe = inst.python_exe()
    env = dict(os.environ)
    env.pop("OPARA_START_TOKEN", None)
    env.pop("OPARA_SAFE_START", None)
    if token:
        env["OPARA_START_TOKEN"] = token
    if safe:
        env["OPARA_SAFE_START"] = "1"
    cmd = [exe, os.path.join(inst.app, "gpd_app.py"), *args]
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200              # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(cmd, cwd=inst.root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **kw)


def supports_start_note(inst):
    """True when the installed build writes the "started fine" note (runstate.py is in its program folder).  A build from before the updater existed - an old
    release put back by "Go back" - cannot tell the updater anything."""
    return os.path.isfile(os.path.join(inst.app, "runstate.py"))


def supports_safe_start(inst):
    """True when the installed build knows the safe-start switch (OPARA_SAFE_START in its channel.py); an older one would simply start with its add-ons."""
    try:
        with open(os.path.join(inst.app, "channel.py"), encoding="utf-8", errors="replace") as f:
            return "OPARA_SAFE_START" in f.read()
    except OSError:
        return False


def wait_started(inst, proc, token, timeout=120, cancel=None, tick=0.25, reports=None, grace=15.0):
    """Waits for the "started fine" note of the program started with `token`.  -> ('ok'|'running'|'exited'|'timeout'|'cancelled', seconds, detail)
    A build that cannot send the note (reports=False; by default looked up) is never called broken for the missing note: it is 'running' when it is still
    there after `grace` seconds (the updater cannot confirm more than that) and 'exited' when it closed before."""
    if reports is None:
        reports = supports_start_note(inst)
    t0 = time.time()
    while True:
        st = read_run_state(inst)
        if reports and st.get("token") == token and st.get("ok"):
            return "ok", time.time() - t0, ""
        rc = proc.poll() if proc is not None else None
        if rc is not None:
            st = read_run_state(inst)                              # one more look: the note may have been written just before the exit
            if reports and st.get("token") == token and st.get("ok"):
                return "ok", time.time() - t0, ""
            return "exited", time.time() - t0, f"The program closed (exit code {rc})."
        if cancel and cancel():
            return "cancelled", time.time() - t0, ""
        secs = time.time() - t0
        if not reports and secs >= min(grace, timeout):
            return "running", secs, (f"This build is older than the start note, so the updater cannot confirm that it started fine; it is still running "
                                     f"after {int(secs)} seconds.")
        if secs > timeout:
            return "timeout", secs, f"No sign of life after {int(timeout)} seconds."
        time.sleep(tick)


# ---------------------------------------------------------------------------------------------------- one updater at a time
def take_lock(inst):
    """Only one updater window / run per installation.  -> True when this process holds the lock, False when another live updater does."""
    p = os.path.join(inst.user_dir(), "updater.lock")
    other = _read_json(p).get("pid")
    if other and int(other) != os.getpid() and pid_alive(other):
        return False
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "started": time.time()}, f)
    except OSError:
        pass
    return True


def drop_lock(inst):
    p = os.path.join(inst.user_dir(), "updater.lock")
    if _read_json(p).get("pid") == os.getpid():
        _remove(p)


# ---------------------------------------------------------------------------------------------------- the report
def _tail(path, n=40, max_chars=6000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return "(none)"
    lines = text.splitlines()[-n:]
    s = "\n".join(lines)
    return s[-max_chars:] if len(s) > max_chars else s


def report_text(inst, builds_error=None, extra=""):
    """A text that says what is installed and what went wrong, to copy into a message."""
    import platform
    ud = inst.user_dir()
    cur = inst.info_of(inst.app)
    lines = [f"{inst.name} updater {TOOL_VERSION} - {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
             f"Installed: {cur['version'] or 'not readable'} (runtime {cur['runtime']}), channel {inst.channel}",
             f"Saved earlier copy: {inst.saved_version() or 'none'}",
             f"Install folder: {inst.root}", f"Data folder: {ud}",
             f"Python {platform.python_version()} on {platform.system()} {platform.release()}"]
    if builds_error:
        lines.append(f"GitHub: {builds_error}")
    st = read_run_state(inst)
    if st:
        lines.append("Last start: " + json.dumps({k: st.get(k) for k in ("version", "pid", "ok", "started", "ok_at", "ended")}))
    ads = []
    for aid, folder in installed_addons(inst).items():
        m = _read_json(os.path.join(folder, "addon.json"))
        ads.append(f"{aid} {m.get('version', '?')}")
    lines.append("Installed add-ons: " + (", ".join(ads) if ads else "none"))
    if extra:
        lines.append(extra)
    for title, name in (("Updater log", LOG_NAME), ("Error log (gpd_error.log)", "gpd_error.log"), ("Crash log (gpd_crash.log)", "gpd_crash.log")):
        lines += ["", f"--- {title}, newest at the bottom", _tail(os.path.join(ud, name))]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------- plain Windows dialogs (no Qt)
def message_box(text, title="OpenPara Updater", question=False):
    """A Windows message box without Qt (the fallback when the window cannot be made).  -> True for Yes / OK.  Elsewhere the text is printed."""
    if os.name == "nt":
        import ctypes
        flags = 0x00000004 if question else 0x00000000            # MB_YESNO / MB_OK
        flags |= 0x00000020 if question else 0x00000040           # MB_ICONQUESTION / MB_ICONINFORMATION
        return ctypes.windll.user32.MessageBoxW(None, text, title, flags) in (1, 6)
    try:
        print(f"{title}: {text}")
    except Exception:                                               # noqa: BLE001
        pass
    return True
