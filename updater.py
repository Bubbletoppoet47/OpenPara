"""
updater.py - checks GitHub for a newer OpenPara and installs it.

A release on GitHub carries  OpenPara-app-<version>.zip  (the program files, a few MB; it has runtime.json inside) and the full installer
OpenPara-Setup-<version>.exe.  An installed copy (folder with  python\\  and  app\\ ) replaces its app folder from the zip; when the zip needs
another bundled runtime (version.RUNTIME) the full installer is needed instead.  No GitHub account is needed while the repository is public;
while it is private, the environment variable OPARA_GITHUB_TOKEN (a read token) is used.
The functions here have no Qt in them (tested with a local fake server); gpd_app.py shows the dialogs.
"""
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
import zipfile

import paths
import version

REPO = "Bubbletoppoet47/OpenPara"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"


def parse_version(text):
    """'v1.2.3' -> (1, 2, 3); anything that is not a number counts as 0."""
    nums = re.findall(r"\d+", str(text).split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(latest, current=None):
    return parse_version(latest) > parse_version(current or version.__version__)


def token():
    return os.environ.get("OPARA_GITHUB_TOKEN") or None


def _request(url, accept=None, tok=None):
    h = {"User-Agent": "OpenPara-updater"}
    if accept:
        h["Accept"] = accept
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return urllib.request.Request(url, headers=h)


class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub redirects asset downloads to another host; that host must not get our token."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        r = super().redirect_request(req, fp, code, msg, headers, newurl)
        if r is not None:
            r.headers.pop("Authorization", None)
            r.unredirected_hdrs.pop("Authorization", None)
        return r


def _open(req, timeout):
    return urllib.request.build_opener(_NoAuthOnRedirect).open(req, timeout=timeout)


def fetch_latest(url=API_LATEST, tok=None, timeout=8):
    """The newest release as {'version','notes','page','app':asset|None,'setup':asset|None}, or None when there is none / no network."""
    tok = tok or token()
    try:
        with _open(_request(url, "application/vnd.github+json", tok), timeout) as r:
            rel = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(rel, dict) or not rel.get("tag_name") or rel.get("draft"):
        return None
    out = {"version": rel["tag_name"].lstrip("vV"), "notes": rel.get("body") or "", "page": rel.get("html_url") or RELEASES_PAGE,
           "app": None, "setup": None}
    for a in rel.get("assets", []):
        n = a.get("name", "")
        if n.startswith("OpenPara-app-") and n.endswith(".zip"):
            out["app"] = a
        elif n.startswith("OpenPara-Setup-") and n.endswith(".exe"):
            out["setup"] = a
    return out


def download(asset, dest, tok=None, progress=None, timeout=30):
    """Saves a release asset; progress(done_bytes, total_bytes) may return False to cancel."""
    tok = tok or token()
    url = asset["url"] if tok else asset["browser_download_url"]
    req = _request(url, "application/octet-stream", tok)
    done = 0
    with _open(req, timeout) as r, open(dest, "wb") as fh:
        total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress and progress(done, total) is False:
                raise InterruptedError("cancelled")
    return dest


def installed_layout():
    """(root, app_dir) when this copy was installed by the installer (root has python\\ and app\\), else None."""
    app_dir = paths.CODE_DIR
    root = os.path.dirname(app_dir)
    if os.path.basename(app_dir).lower() == "app" and os.path.isdir(os.path.join(root, "python")):
        return root, app_dir
    return None


def zip_info(zip_path):
    """{'runtime': int, 'version': str} from the runtime.json inside an app zip (raises ValueError for a zip that is not an app zip)."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            if "gpd_app.py" not in names or "version.py" not in names or "runtime.json" not in names:
                raise ValueError("this is not an OpenPara program zip")
            if z.testzip() is not None:
                raise ValueError("the download is damaged")
            return json.loads(z.read("runtime.json").decode("utf-8"))
    except zipfile.BadZipFile as ex:
        raise ValueError(f"the download is damaged ({ex})")


def install_app_zip(zip_path, app_dir):
    """Replaces the files in app_dir with the zip's.  The old folder is kept as app.old until the next update; a failure puts it back."""
    info = zip_info(zip_path)
    if int(info.get("runtime", 0)) != int(version.RUNTIME):
        raise RuntimeError("runtime changed")
    new, old = app_dir + ".new", app_dir + ".old"
    for d in (new,):
        if os.path.exists(d):
            shutil.rmtree(d)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(new)
    if os.path.exists(old):
        shutil.rmtree(old, ignore_errors=True)
    try:
        os.replace(app_dir, old)
    except OSError:                                      # Windows refuses to rename a folder that is some program's current folder:
        shutil.copytree(new, app_dir, dirs_exist_ok=True)  # then the files are replaced one by one (.py files are not locked)
        shutil.rmtree(new, ignore_errors=True)
        return None
    try:
        os.replace(new, app_dir)
    except OSError:
        os.replace(old, app_dir)
        raise
    return old


def restart_command():
    """argv that starts the program again the way it was started."""
    return [sys.executable] + sys.argv
