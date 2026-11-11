"""gimble_core.py - what the Annotator can do with the Gimble rig's Raspberry Pi over the network.  No Qt here, so it is testable.

The Pi runs the Remote helper (the Remote Computer add-on); `link` below is a remote_link.Link to it.  The Gimble's own programs are not
changed: this only puts files where they already look, and reads what they already write.

    find_gimble(link)                     the Gimble folder on the Pi (the one with gimble_pi.py and gimble_detect.py, on the thumb drive)
    status(link, folder)                  which model it holds, how many recordings, free space, whether a Gimble program is running
    list_models()                         the trained models on this PC (the Annotator's Models folder: Assist and Scratch versions)
    export_model(pt, out, label, ...)     .pt -> gimble_model.onnx + gimble_model.json, the form gimble_detect.py reads (a job in its own process)
    send_model(link, folder, onnx, json)  puts them in <folder>/model/ ; the model that was there is kept in model/previous/
    sessions(link, folder)                the recordings in <folder>/dataset/
    download_sessions(...)                copies recordings to this PC (files already here are left alone, so it can be continued)
    test_videos / download_videos         the videos recorded in Test model, with their tables of predictions
    update_programs(link, folder)         puts the Gimble programs this OpenPara carries (pi/) on the Gimble; start_program starts one

The Gimble's own programs live in this add-on's  pi/  folder (pi/app/*.py, the launchers, the read-me): that is their source.  On the
drive they are in <folder>/app/; settings/, model/, dataset/, test_videos/, calibration_data/ and logs/ are next to it.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

import remote_link as RL

HERE = os.path.dirname(os.path.abspath(__file__))
ANNOTATOR_APP = os.path.join(os.path.dirname(HERE), "annotator", "app")
JOB = os.path.join(HERE, "gimble_export_job.py")
PI_DIR = os.path.join(HERE, "pi")                    # the Gimble's own programs, as this OpenPara carries them (see update_programs)
ROOTS = ("/media", "/mnt", "/run/media", "~")
KINDS = {"assist": "Assist", "scratch": "Scratch"}
SIZE_NAMES = {"n": "Nano", "s": "Small", "m": "Medium", "l": "Large", "x": "Extra large"}


class GimbleError(RL.RemoteError):
    pass


def user_dir():
    try:
        import paths
        return paths.user_dir()
    except ImportError:
        return os.path.join(os.path.expanduser("~"), ".openpara")


def models_dir():
    return os.path.join(user_dir(), "Annotator", "Models")


def settings_file():
    return os.path.join(user_dir(), "gimble_link.json")


def load_settings():
    try:
        with open(settings_file(), encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**kw):
    s = load_settings()
    s.update(kw)
    tmp = settings_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, settings_file())


# ---------------------------------------------------------------- the models on this PC

def data_folders():
    """[(name, folder)] of the data folders trained models can be in: this program's own, and the one of the other OpenPara on this PC
    (OpenPara and OpenPara Playground never share a folder, but a model trained in one is wanted in the other)."""
    own = os.path.abspath(user_dir())
    out = [(os.path.basename(own), own)]
    for name in ("OpenPara", "OpenPara Playground"):
        d = os.path.join(os.path.dirname(own), name)
        if os.path.isdir(d) and os.path.abspath(d) != own:
            out.append((name, d))
    return out


def model_folders():
    """[(where, Models folder)]: every Annotator Models folder there is on this PC, this program's first."""
    return [(name, os.path.join(d, "Annotator", "Models")) for name, d in data_folders()]


def model_entry(pt, kind=None, where=""):
    """What is known about one .pt file (its info file next to it says size, classes, kind), or None when it cannot be read."""
    info = {}
    try:
        with open(os.path.splitext(pt)[0] + ".json", encoding="utf-8") as fh:
            info = json.load(fh) or {}
    except (OSError, ValueError):
        pass
    try:
        ts = float(info.get("created") or os.path.getmtime(pt))
    except (OSError, TypeError, ValueError):
        return None
    size = info.get("size")
    if kind is None and info.get("kind") in KINDS:
        kind = info["kind"]
    name = SIZE_NAMES.get(size) or os.path.splitext(os.path.basename(pt))[0][:24]
    return {"path": pt, "kind": kind, "file": os.path.basename(pt), "size": size, "ts": ts, "classes": info.get("classes"), "where": where,
            "label": f"{name} {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}"}


def list_models(folder=None):
    """[{'path', 'kind' ('assist' | 'scratch' | None = told when it is sent), 'file', 'size', 'ts', 'classes', 'label', 'where'}], newest
    first: the .pt files of every Models folder on this PC - in Assist/, in Scratch/, and lying directly in Models/."""
    out, seen = [], set()
    for where, mdir in ([("", folder)] if folder else model_folders()):
        for kind, sub in list(KINDS.items()) + [(None, "")]:
            d = os.path.join(mdir, sub) if sub else mdir
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                pt = os.path.join(d, f)
                if not f.lower().endswith(".pt") or not os.path.isfile(pt) or os.path.normcase(pt) in seen:
                    continue
                seen.add(os.path.normcase(pt))
                m = model_entry(pt, kind, where)
                if m:
                    out.append(m)
    out.sort(key=lambda m: (m["ts"], m["file"]), reverse=True)
    return out


# ---------------------------------------------------------------- the Gimble folder on the Pi

def find_gimble(link):
    """The Gimble folder on that computer (the one with dataset/ and model/); GimbleError in plain words when it is not there.
    The programs are in its app/ folder (the tidy layout), or directly in it (the layout before)."""
    try:
        hits = link.find("gimble_detect.py", ROOTS, depth=6)
    except RL.LinkClosed:
        raise
    except RL.RemoteError as e:
        raise GimbleError(f"Could not look for the Gimble folder on {link.label()}: {e}")
    sep = link.info.get("sep") or "/"
    folders = [p.rsplit(sep, 1)[0] for p in hits if f"{sep}old{sep}" not in p]
    folders.sort(key=lambda f: not f.endswith(sep + "app"))             # the tidy layout first: its old copies may still lie next to it
    for folder in folders:
        if link.stat(link.join(folder, "gimble_pi.py")).get("exists"):
            return folder.rsplit(sep, 1)[0] if folder.endswith(sep + "app") else folder
    raise GimbleError(f"The Gimble folder was not found on {link.label()}. Is the thumb drive with Gimble_Pi plugged into it? "
                      "(It is looked for in /media, /mnt and the home folder.)")


def programs_dir(link, folder):
    """Where the Gimble's programs are: <folder>/app in the tidy layout, else the folder itself."""
    app = link.join(folder, "app")
    return app if link.stat(link.join(app, "gimble_pi.py")).get("exists") else folder


def programs_version(link, folder):
    """The version of the programs on the Gimble ('2.0'), or None for the ones from before they had a version."""
    path = link.join(folder, "app", "VERSION")
    try:
        if link.stat(path).get("exists"):
            return link.read_file(path, 1000).decode("utf-8", "replace").strip() or None
    except RL.RemoteError:
        pass
    return None


def my_programs_version():
    try:
        with open(os.path.join(PI_DIR, "app", "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _vkey(v):
    return tuple(int(p) if p.isdigit() else 0 for p in str(v or "0").split("."))


def programs_outdated(st):
    """True when this OpenPara carries newer Gimble programs than the Gimble has."""
    return _vkey(st.get("programs")) < _vkey(my_programs_version())


def update_programs(link, folder, progress=None, stop=None):
    """Puts this OpenPara's Gimble programs on the Gimble: app/ (the programs), the launchers and the read-me.  Settings, calibration,
    the model, recordings and videos are not part of it and are never written.  Afterwards the files of the old layout are moved out of
    the main folder (to old/before_tidy/, by the Gimble's own tidy).  Returns (files sent, files tidied away or None)."""
    files = []
    for dp, dn, fn in os.walk(PI_DIR):
        dn[:] = sorted(d for d in dn if d != "__pycache__")
        for f in sorted(fn):
            if f.endswith((".pyc", ".bat")):                       # the .bat is the same tidy for a drive that sits in a Windows PC
                continue
            full = os.path.join(dp, f)
            files.append((os.path.relpath(full, PI_DIR).replace(os.sep, "/"), full, os.path.getsize(full)))
    if not any(r == "app/gimble_pi.py" for r, _f, _s in files):
        raise GimbleError("This OpenPara does not carry the Gimble programs (the add-on's pi folder is missing).")
    total = sum(sz for _r, _f, sz in files)
    done = 0
    for rel, full, size in files:
        link.upload(full, link.join(folder, *rel.split("/")), (lambda d, _t, b=done, r=rel: progress(b + d, total, r)) if progress else None, stop)
        done += size
    tidied = None
    if link.info.get("commands"):
        try:
            code, text = link.run(f'python3 "{link.join(folder, "app", "gimble_tidy.py")}"', cwd=folder, timeout=60)
            if code == 0 and text.strip().startswith("moved"):
                tidied = int(text.split()[1])
        except (RL.RemoteError, ValueError, IndexError):
            pass
    return len(files), tidied


def start_program(link, folder, which="test"):
    """Starts a Gimble program on the Gimble's own screen: 'test' (Test model), 'record' (Record data) or 'menu' (the start screen).
    GimbleError when one is running already (the camera can only be used by one)."""
    script = {"test": "gimble_detect.py", "record": "gimble_pi.py", "menu": "gimble_menu.py"}[which]
    st = status(link, folder)
    if st["running"]:
        raise GimbleError(f"{', '.join(st['running'])} is running on the Gimble. Close it there first (QUIT), then start this again.")
    path = link.join(programs_dir(link, folder), script)
    if not link.stat(path).get("exists"):
        raise GimbleError(f"{script} is not on the Gimble. Update the Gimble's programs first (the Status page).")
    return link.launch(f'python3 "{path}"', cwd=folder)


def read_json(link, path):
    try:
        if not link.stat(path).get("exists"):
            return None
        return json.loads(link.read_file(path, 1 << 20).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def status(link, folder):
    """{'computer', 'folder', 'model' (the json it holds, or None), 'model_time', 'model_mb', 'sessions', 'free_gb', 'running': [names]}"""
    out = {"computer": link.label(), "folder": folder, "model": None, "model_time": None, "model_mb": None, "sessions": 0, "free_gb": None,
           "running": [], "programs": None, "videos": 0}
    out["model"] = read_json(link, link.join(folder, "model", "gimble_model.json"))
    st = link.stat(link.join(folder, "model", "gimble_model.onnx"))
    if st.get("exists"):
        out["model_time"], out["model_mb"] = st.get("mtime"), round(st.get("size", 0) / 1e6, 1)
    out["sessions"] = len(sessions(link, folder))
    out["programs"] = programs_version(link, folder)
    out["videos"] = len(test_videos(link, folder))
    try:
        out["free_gb"] = round(link.disk(folder)["free"] / 1e9, 1)
    except RL.RemoteError:
        pass
    if link.info.get("commands") and link.info.get("platform", "").startswith("linux"):
        try:
            # a Python that was started with one of the two programs (not an editor that has the file open)
            _code, text = link.run("pgrep -af 'python[^ ]* +[^ ]*gimble_(pi|detect|menu)\\.py' || true", timeout=10)
            out["running"] = sorted({n for n in ("gimble_pi.py", "gimble_detect.py", "gimble_menu.py") if n in text})
        except RL.RemoteError:
            pass
    return out


def status_text(st):
    lines = [f"Gimble folder on {st['computer']}:  {st['folder']}"]
    m = st["model"]
    if m:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st["model_time"])) if st["model_time"] else "?"
        what = m.get("label") or (f"round {m.get('round')}" if m.get("round") is not None else m.get("source", "a model"))
        kind = {"assist": "Assist (boxes only)", "scratch": "Scratch (boxes + distance)"}.get(m.get("kind"), "boxes + distance")
        lines.append(f"Model on it:  {what}  -  {kind}, dated {when}, {st['model_mb']} MB")
        names = m.get("names") or []
        lines.append("Classes:  " + (", ".join(str(n) for n in names[:12]) + (f" ... ({len(names)} in all)" if len(names) > 12 else "")))
    elif st["model_time"]:
        lines.append("Model on it:  a model file is there, but its description (gimble_model.json) is missing.")
    else:
        lines.append("Model on it:  none yet.")
    lines.append(f"Recordings on it:  {st['sessions']}" + (f"      Test videos:  {st['videos']}" if st.get("videos") else ""))
    mine = my_programs_version()
    if st.get("programs"):
        lines.append(f"Gimble programs on it:  version {st['programs']}" + (f"  (this OpenPara carries {mine}: Update the Gimble's programs)"
                                                                           if programs_outdated(st) else ""))
    else:
        lines.append("Gimble programs on it:  the layout from before the tidy-up" + (f"  (this OpenPara carries version {mine}: Update the "
                                                                                   "Gimble's programs)" if mine else ""))
    if st["free_gb"] is not None:
        lines.append(f"Free space on that drive:  {st['free_gb']} GB")
    if st["running"]:
        lines.append("Running there now:  " + ", ".join(st["running"]) + "  (Test model reads a new model when it is started again)")
    return "\n".join(lines)


# ---------------------------------------------------------------- .pt -> what the Pi runs

def export_python():
    if os.environ.get("OPARA_GIMBLE_PYTHON"):
        return os.environ["OPARA_GIMBLE_PYTHON"]
    try:
        import paths
        return paths.python_exe()
    except ImportError:
        return sys.executable


def export_model(pt, out_dir, label="", on_step=None, stop=None, job=None, python=None):
    """Runs the export job and returns its last message {'onnx', 'json', 'kind', 'mb', 'names', 'checked'}.  on_step(text) says what it is
    doing; stop() -> True ends it.  GimbleError carries what went wrong (the job's own words, or the end of its log)."""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p), PYTHONIOENCODING="utf-8", YOLO_VERBOSE="False")
    here = [p for p in sys.path if p and os.path.isdir(p)]             # where this program finds its packages (the add-ons' folders too)
    cmd = [python or export_python(), job or JOB, "--weights", pt, "--out", out_dir, "--app", ANNOTATOR_APP, "--label", label,
           "--paths", os.pathsep.join(here)]
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
    log = tempfile.TemporaryFile()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, env=env, **kw)
    except OSError as e:
        raise GimbleError(f"The export could not be started ({e}).")
    result, error, tail = None, None, []
    try:
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if stop and stop():
                p.kill()
                raise RL.Stopped("Stopped.")
            if line.startswith("GIMBLE "):
                try:
                    msg = json.loads(line[7:])
                except ValueError:
                    continue
                if msg.get("tag") == "step" and on_step:
                    on_step(msg.get("text", ""))
                elif msg.get("tag") == "error":
                    error = msg.get("text")
                elif msg.get("tag") == "done":
                    result = msg
            elif line:
                tail = (tail + [line])[-12:]
        code = p.wait()
    finally:
        if p.poll() is None:
            p.kill()
    if error:
        raise GimbleError(error)
    if code != 0 or not result:
        log.seek(0)
        err = log.read().decode("utf-8", "replace").strip().splitlines()[-6:]
        raise GimbleError("The model could not be converted for the Pi. The end of the log:\n" + "\n".join(tail[-4:] + err))
    return result


def send_model(link, folder, onnx, meta_json, progress=None, stop=None):
    """Puts the two files into <folder>/model/ on the Pi.  The model that was there moves to model/previous/ first (one step back is kept).
    The .onnx is checked after the copy; the .json goes last, so a Detect that starts in between never pairs a new description with an
    old model."""
    mdir = link.join(folder, "model")
    prev = link.join(mdir, "previous")
    link.mkdir(prev)
    for name in ("gimble_model.onnx", "gimble_model.json"):
        if link.stat(link.join(mdir, name)).get("exists"):
            link.rename(link.join(mdir, name), link.join(prev, name), replace=True)
    link.upload(onnx, link.join(mdir, "gimble_model.onnx"), progress, stop)
    link.upload(meta_json, link.join(mdir, "gimble_model.json"))
    return link.join(mdir, "gimble_model.onnx")


def restore_previous(link, folder):
    """Puts the model from model/previous/ back (after a send that turned out worse).  GimbleError when there is none."""
    mdir = link.join(folder, "model")
    prev = link.join(mdir, "previous")
    if not link.stat(link.join(prev, "gimble_model.onnx")).get("exists"):
        raise GimbleError("There is no earlier model on the Gimble to go back to.")
    for name in ("gimble_model.onnx", "gimble_model.json"):
        if link.stat(link.join(prev, name)).get("exists"):
            link.rename(link.join(prev, name), link.join(mdir, name), replace=True)


# ---------------------------------------------------------------- recordings

def sessions(link, folder):
    """[{'name', 'path'}] of the recordings on the Pi (folders in dataset/), oldest first."""
    d = link.join(folder, "dataset")
    if not link.stat(d).get("exists"):
        return []
    return [{"name": name, "path": link.join(d, name)} for name, is_dir, _s, _m in link.ls(d)["entries"] if is_dir]


def test_videos(link, folder):
    """[{'name', 'path', 'size'}] of the videos recorded in Test model on the Gimble (test_videos/), oldest first."""
    d = link.join(folder, "test_videos")
    if not link.stat(d).get("exists"):
        return []
    return [{"name": name, "path": link.join(d, name), "size": size} for name, is_dir, size, _m in link.ls(d)["entries"]
            if not is_dir and name.lower().endswith((".mp4", ".avi"))]


def download_videos(link, folder, local_root, progress=None, stop=None):
    """Copies test_videos/ (the videos, and the tables of predictions next to them) into local_root/test_videos; what is already here
    with the same size is left alone.  Returns (files copied, files already here)."""
    d = link.join(folder, "test_videos")
    if not link.stat(d).get("exists"):
        return 0, 0
    return link.download_tree(d, os.path.join(local_root, "test_videos"), progress, stop)


def is_local_session(path):
    return os.path.isfile(os.path.join(path, "index.csv")) and os.path.isdir(os.path.join(path, "images"))


def download_sessions(link, items, local_root, progress=None, stop=None):
    """Copies the given recordings (from sessions()) into local_root/<name>.  progress(done bytes, total bytes, text).
    Returns (files copied, files that were already here)."""
    os.makedirs(local_root, exist_ok=True)
    copied = skipped = 0
    for i, s in enumerate(items):
        tag = f"{s['name']}  ({i + 1} of {len(items)})"
        c, k = link.download_tree(s["path"], os.path.join(local_root, s["name"]),
                                  (lambda d, t, _n, tag=tag: progress(d, t, tag)) if progress else None, stop)
        copied += c
        skipped += k
    return copied, skipped
