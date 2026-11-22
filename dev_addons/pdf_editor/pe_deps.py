"""pe_deps.py - packages the PDF editor downloads the first time a part of it needs them (PyMuPDF has its own file, pb_deps.py, from Page Break).

    voice support    pywin32 (about 10 MB): how Python talks to the Windows voices.  Needed to read aloud; Windows only.
    text reader      RapidOCR and what it needs: reads the words in a picture.  Needed only by Images -> PDF.
    natural voices   Kokoro (kokoro-onnx, sounddevice) and its model files (about 120 MB): the 28 English voices.  Needed only to read aloud with them.

The Playground updates the program's files in place and the packages bundled with the program only change with a full installer, so these are
downloaded once into <user folder>/packages/<name> with the download-and-unpack code the add-ons use (addons._pip_install), and put on the search
path - last, so that a package the program itself bundles still wins.  Nothing in the program folder or in any system Python is touched.
"""
import importlib
import importlib.util
import os
import hashlib
import shutil
import subprocess
import sys
import tempfile
import threading

VOICE = "pdfeditor_voice"
OCR = "pdfeditor_ocr"
VOICE_PINS = ["pywin32>=306"]
VOICE_MB = 10
OCR_PINS = ["rapidocr>=3.0", "onnxruntime>=1.16", "opencv-python-headless>=4.8"]      # their own requirements come with them (ocr_installer)
OCR_MB = 100                                       # rough: the models are inside the RapidOCR download, nothing is fetched later
OCR_BUNDLED = {"numpy": "numpy", "pillow": "PIL", "shapely": "shapely", "onnxruntime": "onnxruntime"}   # wheel -> module: not downloaded again when it is
                                                                                                    # already there (the program's own, or the other pack's)
NATURAL = "pdfeditor_natural"
NATURAL_PINS = ["kokoro-onnx>=0.5", "sounddevice>=0.4"]
NATURAL_BUNDLED = {"numpy": "numpy", "onnxruntime": "onnxruntime"}
NATURAL_MB = 160                                   # packages (about 40) + the model (92) + the voices (28), roughly
MODEL_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILES = [                                    # the int8 model (the smallest) and the voices: every voice is a small profile in the one voices file
    {"name": "kokoro-v1.0.int8.onnx", "bytes": 92361271, "sha256": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb", "what": "the voice model"},
    {"name": "voices-v1.0.bin", "bytes": 28214398, "sha256": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d", "what": "the voices"},
]


def site_dir(name):
    try:
        import paths
        base = paths.user_dir()
    except ImportError:
        base = os.path.join(os.path.expanduser("~"), ".openpara")
    return os.path.join(base, "packages", name)


def add_to_path(name):
    d = site_dir(name)
    if not os.path.isdir(d):
        return d
    for p in (d, os.path.join(d, "win32"), os.path.join(d, "win32", "lib"), os.path.join(d, "Pythonwin")):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    dll = os.path.join(d, "pywin32_system32")
    if os.path.isdir(dll) and sys.platform == "win32":
        try:
            os.add_dll_directory(dll)
        except (OSError, AttributeError):
            pass
        if dll.lower() not in os.environ.get("PATH", "").lower():
            os.environ["PATH"] = dll + os.pathsep + os.environ.get("PATH", "")
    importlib.invalidate_caches()
    return d


def add_all_to_path():
    """Every pack that is there: they share what they can (onnxruntime), so each needs the others' folders on the path."""
    for n in (OCR, NATURAL, VOICE):
        add_to_path(n)


_LOCK = threading.Lock()


def busy():
    """True while one of the downloads below is running (two at once would use the same folders)."""
    return _LOCK.locked()


class exclusive:
    def __enter__(self):
        if not _LOCK.acquire(blocking=False):
            raise RuntimeError("Another download is already running. Wait for it to finish.")

    def __exit__(self, *a):
        _LOCK.release()


def install(pins, name, progress=None, installer=None, check=None):
    """Downloads `pins` into site_dir(name).  progress(text, fraction_or_None); installer(pins, target, progress) is addons._pip_install unless a
    test passes its own.  check() -> truthy once the packages can be used.  Raises an Exception whose message says what went wrong."""
    if installer is None:
        import addons
        installer = addons._pip_install
    target = site_dir(name)
    new = target + ".new"
    shutil.rmtree(new, ignore_errors=True)
    try:
        installer(list(pins), new, progress)
        if not os.path.isdir(new) or not os.listdir(new):
            raise RuntimeError("The download did not contain what was asked for.")
        shutil.rmtree(target, ignore_errors=True)
        os.replace(new, target)
    finally:
        shutil.rmtree(new, ignore_errors=True)
    add_to_path(name)
    if check is not None and not check():
        raise RuntimeError("The packages were downloaded but could not be loaded on this computer.")


# ------------------------------------------------------------------------------------------------------------- the Windows voices
def load_sapi():
    """(pythoncom, win32com.client), or None (not Windows, or pywin32 is not there yet)."""
    if sys.platform != "win32":
        return None
    add_to_path(VOICE)
    try:
        import pythoncom
        import win32com.client
        return pythoncom, win32com.client
    except Exception:                                  # noqa: BLE001 - a broken install must read as "missing", not crash the tab
        for n in [m for m in sys.modules if m.split(".")[0] in ("pythoncom", "pywintypes", "win32com", "win32api")]:
            sys.modules.pop(n, None)                   # a failed import must not stick
        return None


def voice_ready():
    return load_sapi() is not None


def install_voice(progress=None, installer=None):
    with exclusive():
        install(VOICE_PINS, VOICE, progress, installer, check=voice_ready)


# ------------------------------------------------------------------------------------------------------------- the text reader (OCR)
def ocr_ready():
    add_all_to_path()
    try:
        importlib.import_module("rapidocr")
        importlib.import_module("onnxruntime")
        importlib.import_module("PIL")
        importlib.import_module("numpy")
        return True
    except Exception:                                  # noqa: BLE001
        return False


def _bundled(module, own):
    """True when this module can be had from somewhere other than the folder of pack `own` (the program itself, or another pack): it is then not
    downloaded again.  The pack's own folder does not count - it is about to be replaced."""
    add_all_to_path()
    try:
        spec = importlib.util.find_spec(module)
    except Exception:                                  # noqa: BLE001
        return False
    if spec is None or not spec.origin:
        return False
    return not os.path.abspath(spec.origin).lower().startswith(os.path.abspath(site_dir(own)).lower())


def _wheels_installer(skip, own, what):
    """An installer(pins, target, progress) that downloads the wheels of `pins` AND what they need (pip download), leaves out the big ones that are
    already there (`skip`: wheel -> module), and unpacks the rest into `target`.  The program's own python runs pip; it is polled so the window
    stays alive."""
    def installer(pins, target, progress):
        import addons
        import paths
        os.makedirs(target, exist_ok=True)
        wheels = tempfile.mkdtemp(prefix="opara_whl_")
        try:
            cmd = [paths.python_exe(), "-m", "pip", "download", "--dest", wheels, "--only-binary=:all:", "--disable-pip-version-check", "--no-input"] + list(pins)
            kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}          # CREATE_NO_WINDOW
            log = tempfile.TemporaryFile()
            p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, **kw)
            try:
                while p.poll() is None:
                    if progress:
                        progress(f"Downloading {what} ...", None)
                    try:
                        p.wait(0.3)
                    except subprocess.TimeoutExpired:
                        pass
            except BaseException:
                p.kill()
                raise
            if p.returncode != 0:
                log.seek(0)
                tail = log.read().decode("utf-8", "replace")[-1500:]
                raise RuntimeError("Downloading the packages failed (needs an internet connection):\n" + tail)
            for w in sorted(os.listdir(wheels)):
                if not w.endswith(".whl"):
                    continue
                name = w.split("-")[0].lower().replace("_", "-").replace(".", "-")
                if name in skip and _bundled(skip[name], own):
                    continue
                if progress:
                    progress("Unpacking " + w.split("-")[0] + " ...", None)
                addons.unpack_wheel(os.path.join(wheels, w), target)
        finally:
            shutil.rmtree(wheels, ignore_errors=True)
    return installer


def ocr_installer(pins, target, progress):
    _wheels_installer(OCR_BUNDLED, OCR, "the text reader")(pins, target, progress)


def natural_installer(pins, target, progress):
    _wheels_installer(NATURAL_BUNDLED, NATURAL, "the voice packages")(pins, target, progress)


def install_ocr(progress=None, installer=None):
    with exclusive():
        install(OCR_PINS, OCR, progress, installer or ocr_installer, check=ocr_ready)


# ------------------------------------------------------------------------------------------------------------- the natural voices (Kokoro)
def models_dir():
    try:
        import paths
        base = paths.user_dir()
    except ImportError:
        base = os.path.join(os.path.expanduser("~"), ".openpara")
    return os.path.join(base, "pdf_editor_models", "kokoro")


def model_path(name):
    return os.path.join(models_dir(), name)


def models_ready():
    for f in MODEL_FILES:
        try:
            if os.path.getsize(model_path(f["name"])) != f["bytes"]:
                return False
        except OSError:
            return False
    return True


def natural_packages_ready(deep=False):
    """The packages of the natural voices can be found (deep: and really imported - slow, so only after a download)."""
    add_all_to_path()
    try:
        for m in ("numpy", "onnxruntime", "kokoro_onnx", "sounddevice"):
            if deep:
                importlib.import_module(m)
            elif importlib.util.find_spec(m) is None:
                return False
        return True
    except Exception:                                  # noqa: BLE001
        return False


def natural_ready():
    """Cheap (no imports): the packages are there and so are the model files."""
    return natural_packages_ready() and models_ready()


def _fetch(url, dest, progress, what):
    import addons
    with addons._open(url) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if progress:
                progress(f"Downloading {what}: {got / 1e6:.0f} MB" + (f" of {total / 1e6:.0f} MB" if total else ""), (got / total) if total else None)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def install_natural(progress=None, installer=None, fetch=None):
    """Downloads what the natural voices need: the packages (once), then the two model files, each checked against its size and hash.  Raises an
    Exception whose message says what went wrong; a file that failed is never left behind as if it were good."""
    with exclusive():
        if not natural_packages_ready():
            install(NATURAL_PINS, NATURAL, progress, installer or natural_installer, check=lambda: natural_packages_ready(deep=True))
        os.makedirs(models_dir(), exist_ok=True)
        for f in MODEL_FILES:
            dest = model_path(f["name"])
            try:
                if os.path.getsize(dest) == f["bytes"]:
                    continue
            except OSError:
                pass
            part = dest + ".part"
            try:
                try:
                    (fetch or _fetch)(MODEL_BASE + f["name"], part, progress, f["what"])
                except Exception as e:                 # noqa: BLE001
                    raise RuntimeError(f"Downloading {f['what']} failed (needs an internet connection): {e}") from e
                if os.path.getsize(part) != f["bytes"] or _sha256(part) != f["sha256"]:
                    raise RuntimeError(f"The download of {f['what']} was damaged. Try again.")
                os.replace(part, dest)
            finally:
                try:
                    os.remove(part)
                except OSError:
                    pass
