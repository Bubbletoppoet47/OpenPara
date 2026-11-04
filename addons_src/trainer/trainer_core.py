"""trainer_core.py - the Trainer's project and training jobs.  No Qt here, so it is testable.

A training project (a ".training" folder, marker training.json):

    training.json   settings + import log
    data/           a normal annotator dataset (annotator_core.Project): the zips you import are MERGED into it with the same code the
                    annotator uses, so a master zip made in either program can be handed to the other
    models/         Assist/ Scratch/  every model this project trained (as dated versions, the annotator's Models folder layout)
    runs/<id>/      one folder per training run: dataset/ (the frozen copy it trains on), job.json, log.txt, result.json, the Ultralytics output

Distortions are made only for TRAINING pictures; pictures of sets marked Validation are never distorted (the annotator's rule).
A run trains on a frozen copy of the data, so importing or editing while it runs changes nothing about that run.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ANNOTATOR_APP = os.path.join(os.path.dirname(HERE), "annotator", "app")
MARKER = "training.json"
FORMAT = "openpara-training"
HELPER_SCRIPT = os.path.join(HERE, "train_helper_job.py")

DISTORTION_TYPES = [   # key, label, range key, low limit, high limit, decimals, neutral value (the type "off")
    ("brightness", "Brightness", "brightness", 0.1, 3.0, 2, (1.0, 1.0)),
    ("contrast", "Contrast", "contrast", 0.1, 3.0, 2, (1.0, 1.0)),
    ("saturation", "Saturation (colour)", "saturation", 0.0, 3.0, 2, (1.0, 1.0)),
    ("blur", "Blur (radius, pixels)", "blur_radius", 0.0, 6.0, 1, (0.0, 0.0)),
    ("noise", "Sensor noise", "noise_sigma", 0.0, 40.0, 1, (0.0, 0.0)),
    ("jpeg", "JPEG compression (quality)", "jpeg_quality", 5, 100, 0, (100, 100)),
]

DEFAULTS = {
    "distortions": {"enabled": False, "count": 5, "types": {t[0]: True for t in DISTORTION_TYPES}, "ranges": {}, "blur_chance": 0.5},
    "model": {"type": "yolo", "size": "m", "epochs": 100, "patience": 30, "batch": 16, "imgsz": 640, "classes": None,
              "continue_from": None, "name": ""},
    "python": "",
}


def libs():
    """Imports the annotator's toolkit-free modules (annotator_core, dataset_zip, share_zip, model_library); raises if that add-on is missing."""
    if not os.path.isdir(ANNOTATOR_APP):
        raise RuntimeError("The Trainer uses the Annotator add-on's code (its merge and model files), and that add-on is not installed.")
    if ANNOTATOR_APP not in sys.path:
        sys.path.insert(0, ANNOTATOR_APP)
    import annotator_core as ac
    import dataset_zip as dz
    import model_library as ml
    import share_zip as sz
    return ac, dz, sz, ml


def user_dir():
    try:
        import paths
        return paths.user_dir()
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.expanduser("~"), ".openpara")


def annotator_models_dir():
    """The annotator's Models folder: what a model must be saved in to appear in the annotator's AI model box."""
    return os.path.join(user_dir(), "Annotator", "Models")


def untitled_dir():
    base = os.path.join(user_dir(), "Trainer", "untitled")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix="project_", dir=base)


# ---------------------------------------------------------------- model types

def model_types():
    """{key: spec}: the two built-in YOLO types plus what add-ons registered with ext.add_model_trainer."""
    common = {"script": HELPER_SCRIPT, "sizes": ("n", "s", "m", "l"), "default_size": "m", "models_key": "assist", "needs": [],
              "pretrained": "yolo26{size}.pt", "fallback": "yolo11{size}.pt"}
    out = {"yolo": dict(common, label="YOLO  (pretrained)", from_scratch=False),
           "yolo_scratch": dict(common, label="YOLO  (not pretrained: random starting weights)", from_scratch=True,
                                pretrained="yolo26{size}.yaml", fallback="yolo11{size}.yaml")}
    try:
        import ext
        for k, spec in ext.MODEL_TRAINERS.items():
            sp = dict(spec)
            sp.setdefault("label", k)
            sp.setdefault("sizes", ("n", "s", "m", "l"))
            sp.setdefault("default_size", sp["sizes"][0])
            sp.setdefault("models_key", "assist")
            sp.setdefault("needs", [])
            out[k] = sp
    except ImportError:
        pass
    return out


def default_me():
    """Who the data is stamped as: the name the annotator saved, else this Windows / Linux user (made once and remembered).  Never asks."""
    ac, dz, sz, ml = libs()
    cfg = sz.load_config()
    me = sz.identity(cfg)
    if me:
        return me
    import getpass
    import re
    try:
        raw = getpass.getuser()
    except Exception:  # noqa: BLE001
        raw = "user"
    name = re.sub(r"[^A-Za-z0-9_-]", "_", raw) or "user"
    if sz.person_name_error(name):
        name = "user"
    me = sz.set_identity(cfg, name)
    try:
        sz.save_config(cfg)
    except OSError:
        pass
    return me


# ---------------------------------------------------------------- the machine

def train_python():
    """The Python that runs training: OPARA_TRAIN_PYTHON / GIMBLE_TRAIN_PYTHON, else this one (or 'python' when OpenPara is a packaged program)."""
    for v in ("OPARA_TRAIN_PYTHON", "GIMBLE_TRAIN_PYTHON"):
        if os.environ.get(v):
            return os.environ[v]
    if getattr(sys, "frozen", False):
        return shutil.which("python") or shutil.which("python3") or "python"
    return sys.executable


_PROBE = ("import json,importlib.util as u\nd={}\n"
          "for m in ('torch','ultralytics'):\n"
          "    try:\n        d[m]=__import__(m).__version__\n    except Exception as e:\n        d[m]=None\n"
          "d['cuda']=False;d['gpu']=None;d['cuda_build']=None\n"
          "if d['torch']:\n    import torch\n    d['cuda']=bool(torch.cuda.is_available())\n    d['cuda_build']=torch.version.cuda\n"
          "    d['gpu']=torch.cuda.get_device_name(0) if d['cuda'] else None\n"
          "print('PROBE'+json.dumps(d))\n")


def check_env(python=None):
    """What training needs on this computer: {'python','torch','ultralytics','cuda','gpu','ok','problems':[...], 'warnings':[...]}."""
    python = python or train_python()
    info = {"python": python, "torch": None, "ultralytics": None, "cuda": False, "gpu": None}
    try:
        r = subprocess.run([python, "-c", _PROBE], capture_output=True, text=True, timeout=120)
        for line in r.stdout.splitlines():
            if line.startswith("PROBE"):
                info.update(json.loads(line[5:]))
        ran = any(line.startswith("PROBE") for line in r.stdout.splitlines())
    except (OSError, subprocess.SubprocessError, ValueError):
        ran = False
    problems, warnings = [], []
    if not ran:
        problems.append(f"Python for training could not be started ({python}). Set OPARA_TRAIN_PYTHON to a Python that has torch and ultralytics.")
    else:
        if not info["torch"]:
            problems.append("torch is not installed in the training Python.  Install it:  pip install torch torchvision  "
                            "(for an NVIDIA GPU use the CUDA build from pytorch.org).")
        if not info["ultralytics"]:
            problems.append("ultralytics is not installed in the training Python.  Install it:  pip install ultralytics")
        if info["torch"] and not info["cuda"]:
            if not info.get("cuda_build"):
                warnings.append(f"torch {info['torch']} in this Python is the CPU-only build, so it cannot use your GPU. Pick another Python above that has "
                                "the CUDA build, or install it here:  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124")
            else:
                warnings.append(f"torch {info['torch']} is the CUDA build ({info['cuda_build']}) but sees no GPU: check the NVIDIA driver "
                                "(run nvidia-smi) and that the GPU is not in use by something else.")
            warnings.append("Without a GPU, training runs on the CPU, which is very slow (fine for a tiny test).")
    info.update(ok=not problems, problems=problems, warnings=warnings)
    return info


def find_pythons():
    """Pythons on this computer that could be used for training (paths only; probe each with check_env)."""
    found = []

    def add(p):
        if p and os.path.isfile(p) and os.path.normcase(os.path.abspath(p)) not in [os.path.normcase(os.path.abspath(x)) for x in found]:
            found.append(os.path.abspath(p))
    for v in ("OPARA_TRAIN_PYTHON", "GIMBLE_TRAIN_PYTHON"):
        add(os.environ.get(v))
    if not getattr(sys, "frozen", False):
        add(sys.executable)
    for n in ("python", "python3"):
        add(shutil.which(n))
    home = os.path.expanduser("~")
    exe = "python.exe" if os.name == "nt" else "bin/python"
    sub = "Scripts" if os.name == "nt" else "bin"
    names = ("miniconda3", "anaconda3", "Miniconda3", "Anaconda3", ".conda", "venv", ".venv", "yolo_venv", "TrashDetection/venv", "TrashDetection/.venv",
             "TrashDetection_training/venv", "TrashDetection_training/.venv", "Gimble/venv", "Gimble/.venv", "yolo_runs/venv")
    import glob
    for n in names:
        base = os.path.join(home, *n.split("/"))
        add(os.path.join(base, exe))
        add(os.path.join(base, sub, "python.exe" if os.name == "nt" else "python"))
        for envdir in glob.glob(os.path.join(base, "envs", "*")):
            add(os.path.join(envdir, exe))
    return found


def probe_all(paths, progress=None):
    """check_env for each path, several at a time.  Returns the infos, best first (usable and with a GPU first)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as ex:
        infos = list(ex.map(check_env, paths))
    return sorted(infos, key=lambda i: (not i["ok"], not i["cuda"], paths.index(i["python"]) if i["python"] in paths else 99))


def checkpoint_info(python, path):
    """{'size', 'classes'} of a .pt model, from its info file next to it, else by loading it in the training Python."""
    ac, dz, sz, ml = libs()
    inf = ml.read_info(path) or {}
    if inf.get("size") and inf.get("classes"):
        return {"size": inf["size"], "classes": list(inf["classes"])}
    code = ("import json,re,sys\nfrom ultralytics import YOLO\nm=YOLO(sys.argv[1]);y=m.model.yaml\nn=m.names\n"
            "sc=y.get('scale') or (re.search(r'yolo\\d+([nslmx])',str(y.get('yaml_file',''))) or [None,None])[1]\n"
            "print('CKPT'+json.dumps({'size':sc,'classes':[n[k] for k in sorted(n)] if isinstance(n,dict) else list(n)}))\n")
    try:
        r = subprocess.run([python, "-c", code, path], capture_output=True, text=True, timeout=180)
        for line in r.stdout.splitlines():
            if line.startswith("CKPT"):
                return json.loads(line[4:])
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    raise ValueError(f"Could not read the size and classes of {os.path.basename(path)} with {python}. Is it a YOLO .pt model?")


def env_text(info):
    lines = [f"Training Python: {info['python']}"]
    if info.get("torch"):
        lines.append(f"torch {info['torch']}" + (f"  -  GPU: {info['gpu']}" if info.get("cuda") else "  -  no GPU"))
    if info.get("ultralytics"):
        lines.append(f"ultralytics {info['ultralytics']}")
    return "\n".join(lines + info["problems"] + info["warnings"])


# ---------------------------------------------------------------- distortions

def distortion_ranges(d):
    """The annotator's range dictionary for the chosen distortion types: a type that is off gets its 'no change' value."""
    ac = libs()[0]
    r = dict(ac.DEFAULT_DISTORTION_RANGES)
    for key, _label, rk, _lo, _hi, _dec, neutral in DISTORTION_TYPES:
        if key in d.get("ranges", {}):
            r[rk] = tuple(d["ranges"][key])
        if not d["types"].get(key, True):
            r[rk] = neutral
    r["blur_chance"] = float(d.get("blur_chance", 0.5)) if d["types"].get("blur", True) else 0.0
    return r


def _merge(base, new):
    out = json.loads(json.dumps(base))
    for k, v in (new or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class TrainingProject:
    def __init__(self, root):
        self.ac, self.dz, self.sz, self.ml = libs()
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.file = os.path.join(self.root, MARKER)
        self.data_dir = os.path.join(self.root, "data")
        self.models_dir = os.path.join(self.root, "models")
        self.runs_dir = os.path.join(self.root, "runs")
        self.cache_dir = os.path.join(self.root, "weights_cache")
        try:
            with open(self.file, encoding="utf-8") as f:
                self.meta = json.load(f)
        except (OSError, ValueError):
            self.meta = {}
        self.meta.setdefault("format", FORMAT)
        self.meta.setdefault("settings", {})
        self.meta.setdefault("imports", [])
        for d in (self.data_dir, self.runs_dir, self.cache_dir):
            os.makedirs(d, exist_ok=True)
        self.data = self.ac.Project(self.data_dir)
        self.save()

    def save(self):
        tmp = self.file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=2)
        os.replace(tmp, self.file)

    # ---- settings
    @property
    def settings(self):
        st = _merge(DEFAULTS, self.meta["settings"])
        if st["model"].get("type") == "helper":                     # the old name of the pretrained YOLO type
            st["model"]["type"] = "yolo"
        st["model"].pop("start", None)
        return st

    def set_settings(self, new):
        self.meta["settings"] = _merge(self.meta["settings"], new)
        self.save()

    # ---- data: merge zips in, hand a master zip out
    def plan_import(self, zip_path, me, progress_cb=None):
        """Looks at what importing the zip would do (nothing changes).  The plan has 'conflicts' to ask about; pass it to apply_import."""
        self.data.editor_id = me["id"]
        workdir = tempfile.mkdtemp(prefix="trainer_zip_")
        try:
            plan = self.dz.plan_zip(self.data, zip_path, workdir, me, progress_cb)
        except Exception:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        plan["_workdir"] = workdir
        plan["_zip"] = zip_path
        return plan

    def apply_import(self, plan, choices, me, progress_cb=None):
        self.data.editor_id = me["id"]
        try:
            res = self.dz.apply_zip(self.data, plan, choices, me, progress_cb)
        finally:
            shutil.rmtree(plan.get("_workdir", ""), ignore_errors=True)
        self.meta["imports"].append({"zip": os.path.basename(plan.get("_zip", "")), "time": time.time()})
        self.save()
        return res

    def discard_plan(self, plan):
        shutil.rmtree(plan.get("_workdir", ""), ignore_errors=True)

    def export_zip(self, zip_path, me, progress_cb=None):
        """One zip with every annotated picture of this project (a 'master' dataset): the annotator can import it, so can another Trainer."""
        self.data.editor_id = me["id"]
        return self.dz.export_zip(self.data, zip_path, me, progress_cb)

    # ---- sets and classes
    def sets(self):
        return self.data.session_summary()

    def set_role(self, session_id, role):
        n = self.data.set_session_role(session_id, role)
        self.data.save_manifest()
        return n

    def annotated_ids(self):
        return [i for i in self.data.list_images() if self.data.is_annotated(i)]

    def summary(self, classes=None):
        """Counts for the window: pictures and boxes per class on each side, for the chosen classes (None = all)."""
        names = list(self.data.classes)
        use = [c for c in names if classes is None or c in classes]
        idx = {names.index(c): n for n, c in enumerate(use)}
        out = {"classes": use, "train": 0, "val": 0, "unsplit": 0, "boxes": {"train": [0] * len(use), "val": [0] * len(use)}}
        for i in self.annotated_ids():
            side = "val" if self.data.is_val_image(i) else "train"
            out[side] += 1
            for b in self.data.get_boxes(i):
                if b[0] in idx:
                    out["boxes"][side][idx[b[0]]] += 1
        return out

    # ---- distortions (training pictures only)
    def clear_distortions(self):
        d = self.data
        d.manifest["distortions"] = {}
        for folder in (d.dist_images_dir, d.dist_labels_dir):
            for fn in os.listdir(folder):
                try:
                    os.remove(os.path.join(folder, fn))
                except OSError:
                    pass
        d.save_manifest()

    def prepare_distortions(self, progress_cb=None):
        """Makes the distorted copies the settings ask for (replacing earlier ones if the settings changed).  Validation sets get none.
        Returns the number of training pictures that have copies."""
        s = self.settings["distortions"]
        if not s["enabled"]:
            return 0
        ranges = distortion_ranges(s)
        sig = json.dumps([ranges, s["count"]], sort_keys=True, default=list)
        if self.meta.get("distortion_sig") != sig:
            self.clear_distortions()
            self.meta["distortion_sig"] = sig
            self.save()
        self.data.ensure_all_distortions(int(s["count"]), ranges, progress_cb)
        return sum(1 for i, v in self.data.manifest["distortions"].items() if v and not self.data.is_val_image(i))

    # ---- the frozen copy a run trains on
    def freeze(self, dest, classes=None, distortions=False):
        """Writes an Ultralytics-style dataset into dest from the data as it is NOW (pictures are hard-linked or copied).
        Returns (data_yaml, {'train', 'val', 'classes'}).  Distorted copies go to train only."""
        d = self.data
        names = list(d.classes)
        use = [c for c in names if classes is None or c in classes]
        remap = {names.index(c): n for n, c in enumerate(use)}
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        counts = {"train": 0, "val": 0}
        for split in ("train", "val"):
            os.makedirs(os.path.join(dest, "images", split))
            os.makedirs(os.path.join(dest, "labels", split))

        def put(split, name, src, boxes):
            try:
                os.link(src, os.path.join(dest, "images", split, name + ".jpg"))
            except OSError:
                shutil.copyfile(src, os.path.join(dest, "images", split, name + ".jpg"))
            with open(os.path.join(dest, "labels", split, name + ".txt"), "w", encoding="utf-8") as f:
                for c, xc, yc, w, h in boxes:
                    if c in remap:
                        f.write(f"{remap[c]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n")
            counts[split] += 1

        for i in self.annotated_ids():
            split = "val" if d.is_val_image(i) else "train"
            boxes = d.get_boxes(i)
            put(split, i, d.image_path(i), boxes)
            if distortions and split == "train":               # validation pictures are never distorted
                for v in d.manifest["distortions"].get(i, []):
                    p = os.path.join(d.dist_images_dir, v + ".jpg")
                    if os.path.exists(p):
                        put("train", v, p, boxes)
        yaml_path = os.path.join(dest, "data.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(f"path: {dest.replace(os.sep, '/')}\ntrain: images/train\nval: images/val\nnc: {len(use)}\nnames:\n")
            for n, c in enumerate(use):
                f.write(f"  {n}: {c}\n")
        counts["classes"] = use
        return yaml_path, counts

    # ---- models
    def list_models(self):
        out = []
        for key in self.ml.FOLDERS:
            out += self.ml.list_versions(self.models_dir, key)
        return sorted(out, key=lambda v: v["ts"], reverse=True)

    def newest_matching(self, key, size, classes):
        """The newest saved model of this size whose classes are exactly `classes` (to continue from), or None."""
        best = None
        for d in (self.models_dir, annotator_models_dir()):
            for v in self.ml.list_versions(d, key):
                if v["size"] == size and v["classes"] == list(classes) and (best is None or v["ts"] > best["ts"]):
                    best = v
        return best

    # ---- runs
    def start_run(self, me_name, progress_cb=None, python=None, **overrides):
        """Freezes the data and starts the training script in the background.  Returns a Job.
        overrides replace values of the saved model settings (type, size, epochs, classes, continue_from, name ...)."""
        s = self.settings
        m = dict(s["model"])
        m.update({k: v for k, v in overrides.items() if v is not None})
        types = model_types()
        spec = types.get(m["type"])
        if spec is None:
            raise ValueError(f"Unknown model type: {m['type']}")
        python = python or s.get("python") or train_python()
        prev = None
        if m.get("continue_from"):
            if not os.path.isfile(m["continue_from"]):
                raise ValueError(f"The model to continue from is not there: {m['continue_from']}")
            prev = checkpoint_info(python, m["continue_from"])
            m["size"] = prev["size"] or m["size"]
        if m["size"] not in spec["sizes"]:
            m["size"] = spec["default_size"]
        names = [c for c in self.data.classes if m.get("classes") is None or c in m["classes"]]
        if prev and prev["classes"] != names:
            raise ValueError("The model you are continuing from knows these classes:\n    " + ", ".join(prev["classes"])
                             + "\n\nbut the classes ticked here are:\n    " + ", ".join(names)
                             + "\n\nThey must be the same, in the same order. Tick exactly those classes, or untick \"Continue from existing model\".")
        if s["distortions"]["enabled"]:
            self.prepare_distortions(progress_cb)
        run_id = time.strftime("%Y%m%d_%H%M%S") + f"_{m['type']}_{m['size']}"
        run_dir, n = os.path.join(self.runs_dir, run_id), 1
        while os.path.exists(run_dir):
            n += 1
            run_dir = os.path.join(self.runs_dir, f"{run_id}_{n}")
        os.makedirs(run_dir)
        yaml_path, counts = self.freeze(os.path.join(run_dir, "dataset"), m.get("classes"), s["distortions"]["enabled"])
        if counts["train"] == 0:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise ValueError("There are no training pictures. Import a dataset and keep at least one set as Training.")
        if counts["val"] == 0:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise ValueError("There are no validation pictures. Mark at least one fully annotated set as Validation (the scores come from it).")
        job = {"data_yaml": yaml_path, "run_dir": run_dir, "type": m["type"], "size": m["size"], "epochs": int(m["epochs"]),
               "patience": int(m["patience"]), "batch": int(m["batch"]), "imgsz": int(m["imgsz"]), "workers": 2, "device": None,
               "classes": counts["classes"], "counts": {"train": counts["train"], "val": counts["val"]},
               "start_weights": m["continue_from"] if prev else None, "based_on": os.path.basename(m["continue_from"]) if prev else None,
               "from_scratch": bool(spec.get("from_scratch")),
               "pretrained": spec.get("pretrained", "yolo26{size}.pt"), "fallback": spec.get("fallback", "yolo11{size}.pt"),
               "models_key": spec["models_key"], "models_dirs": [self.models_dir, annotator_models_dir()],
               "trainer": (m.get("name") or "").strip() or me_name or "trainer", "lib_dir": ANNOTATOR_APP}
        with open(os.path.join(run_dir, "job.json"), "w", encoding="utf-8") as f:
            json.dump(job, f, indent=2)
        return Job.start(run_dir, spec["script"], python, cwd=self.cache_dir)


class Job:
    """A training script running in the background, logging to <run>/log.txt."""

    def __init__(self, run_dir, proc, log_path):
        self.run_dir, self.proc, self.log_path = run_dir, proc, log_path
        self.pos = 0
        self.stopped = False

    @classmethod
    def start(cls, run_dir, script, python, cwd=None):
        log_path = os.path.join(run_dir, "log.txt")
        log = open(log_path, "wb")
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x08000000                       # CREATE_NO_WINDOW
        else:
            kw["start_new_session"] = True                          # so Stop can end the whole group (the data loader workers too)
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([python, "-u", script, os.path.join(run_dir, "job.json")], stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, cwd=cwd or run_dir, env=env, **kw)
        log.close()
        return cls(run_dir, proc, log_path)

    def poll(self):
        """None while running, else the exit code."""
        return self.proc.poll()

    def read_log(self):
        """New text since the last call."""
        try:
            with open(self.log_path, "rb") as f:
                f.seek(self.pos)
                data = f.read()
        except OSError:
            return ""
        self.pos += len(data)
        return data.decode("utf-8", "replace")

    def stop(self):
        self.stopped = True
        if self.proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True, timeout=20)
            else:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            self.proc.kill()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def result(self):
        try:
            with open(os.path.join(self.run_dir, "result.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
