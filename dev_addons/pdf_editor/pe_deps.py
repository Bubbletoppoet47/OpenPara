"""pe_deps.py - packages the PDF editor downloads the first time a part of it needs them (PyMuPDF has its own file, pb_deps.py, from Page Break).

    voice support    pywin32 (about 10 MB): how Python talks to the Windows voices.  Needed to read aloud; Windows only.
    text reader      RapidOCR and what it needs: reads the words in a picture.  Needed only by Images -> PDF.

The Playground updates the program's files in place and the packages bundled with the program only change with a full installer, so these are
downloaded once into <user folder>/packages/<name> with the download-and-unpack code the add-ons use (addons._pip_install), and put on the search
path - last, so that a package the program itself bundles still wins.  Nothing in the program folder or in any system Python is touched.
"""
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

VOICE = "pdfeditor_voice"
OCR = "pdfeditor_ocr"
VOICE_PINS = ["pywin32>=306"]
VOICE_MB = 10
OCR_PINS = ["rapidocr>=3.0", "onnxruntime>=1.16", "opencv-python-headless>=4.8"]      # their own requirements come with them (ocr_installer)
OCR_MB = 100                                       # rough: the models are inside the RapidOCR download, nothing is fetched later
OCR_BUNDLED = {"numpy": "numpy", "pillow": "PIL", "shapely": "shapely"}      # wheel -> module: not downloaded again when the program already has it


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
    install(VOICE_PINS, VOICE, progress, installer, check=voice_ready)


# ------------------------------------------------------------------------------------------------------------- the text reader (OCR)
def ocr_ready():
    add_to_path(OCR)
    try:
        importlib.import_module("rapidocr")
        importlib.import_module("onnxruntime")
        importlib.import_module("PIL")
        importlib.import_module("numpy")
        return True
    except Exception:                                  # noqa: BLE001
        return False


def _bundled(module):
    """True when the program (or Python) has this module itself, not just the copy in the folder of the text reader."""
    try:
        spec = importlib.util.find_spec(module)
    except Exception:                                  # noqa: BLE001
        return False
    if spec is None or not spec.origin:
        return False
    return not os.path.abspath(spec.origin).lower().startswith(os.path.abspath(site_dir(OCR)).lower())


def ocr_installer(pins, target, progress):
    """Downloads the wheels of `pins` AND what they need (pip download), leaves out the big ones the program has already (OCR_BUNDLED), and unpacks the
    rest into `target`.  The program's own python runs pip; it is polled so the window stays alive."""
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
                    progress("Downloading the text reader ...", None)
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
            if name in OCR_BUNDLED and _bundled(OCR_BUNDLED[name]):
                continue
            if progress:
                progress("Unpacking " + w.split("-")[0] + " ...", None)
            addons.unpack_wheel(os.path.join(wheels, w), target)
    finally:
        shutil.rmtree(wheels, ignore_errors=True)


def install_ocr(progress=None, installer=None):
    install(OCR_PINS, OCR, progress, installer or ocr_installer, check=ocr_ready)
