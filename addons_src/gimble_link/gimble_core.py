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

def list_models(folder=None):
    """[{'path', 'kind', 'file', 'size', 'ts', 'classes', 'label'}], newest first, of the Annotator's Models/Assist and Models/Scratch."""
    folder = folder or models_dir()
    out = []
    for kind, sub in KINDS.items():
        d = os.path.join(folder, sub)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if not f.lower().endswith(".pt"):
                continue
            pt = os.path.join(d, f)
            info = {}
            try:
                with open(os.path.splitext(pt)[0] + ".json", encoding="utf-8") as fh:
                    info = json.load(fh) or {}
            except (OSError, ValueError):
                pass
            try:
                ts = float(info.get("created") or os.path.getmtime(pt))
            except (OSError, TypeError, ValueError):
                continue
            size = info.get("size")
            label = f"{SIZE_NAMES.get(size, 'Model')} {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}"
            out.append({"path": pt, "kind": kind, "file": f, "size": size, "ts": ts, "classes": info.get("classes"), "label": label})
    out.sort(key=lambda m: (m["ts"], m["file"]), reverse=True)
    return out


# ---------------------------------------------------------------- the Gimble folder on the Pi

def find_gimble(link):
    """The folder of the Gimble programs on that computer; GimbleError in plain words when it is not there."""
    try:
        hits = link.find("gimble_detect.py", ROOTS, depth=5)
    except RL.LinkClosed:
        raise
    except RL.RemoteError as e:
        raise GimbleError(f"Could not look for the Gimble folder on {link.label()}: {e}")
    sep = link.info.get("sep") or "/"
    for p in hits:
        folder = p.rsplit(sep, 1)[0]
        if link.stat(link.join(folder, "gimble_pi.py")).get("exists"):
            return folder
    raise GimbleError(f"The Gimble folder was not found on {link.label()}. Is the thumb drive with Gimble_Pi plugged into it? "
                      "(It is looked for in /media, /mnt and the home folder.)")


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
           "running": []}
    out["model"] = read_json(link, link.join(folder, "model", "gimble_model.json"))
    st = link.stat(link.join(folder, "model", "gimble_model.onnx"))
    if st.get("exists"):
        out["model_time"], out["model_mb"] = st.get("mtime"), round(st.get("size", 0) / 1e6, 1)
    out["sessions"] = len(sessions(link, folder))
    try:
        out["free_gb"] = round(link.disk(folder)["free"] / 1e9, 1)
    except RL.RemoteError:
        pass
    if link.info.get("commands") and link.info.get("platform", "").startswith("linux"):
        try:
            # a Python that was started with one of the two programs (not an editor that has the file open)
            _code, text = link.run("pgrep -af 'python[^ ]* +[^ ]*gimble_(pi|detect)\\.py' || true", timeout=10)
            out["running"] = sorted({n for n in ("gimble_pi.py", "gimble_detect.py") if n in text})
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
    lines.append(f"Recordings on it:  {st['sessions']}")
    if st["free_gb"] is not None:
        lines.append(f"Free space on that drive:  {st['free_gb']} GB")
    if st["running"]:
        lines.append("Running there now:  " + ", ".join(st["running"]) + "  (Detect reads a new model when it is started again)")
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
