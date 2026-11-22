"""pb_deps.py - gets PyMuPDF for Page Break when the program does not have it.

The Playground updates the program's files in place; the packages bundled with it only change with a full installer.  So Page Break downloads
PyMuPDF itself, once, into the user folder (<user folder>/packages/pagebreak) with the same download-and-unpack code the add-ons use, and puts
that folder on the search path - at every later start too (pb_core calls add_to_path() before it imports PyMuPDF).  Nothing in the program
folder or in any system Python is touched.
"""
import importlib
import os
import shutil
import sys

PIN = "pymupdf>=1.24"


def site_dir():
    try:
        import paths
        base = paths.user_dir()
    except ImportError:
        base = os.path.join(os.path.expanduser("~"), ".openpara")
    return os.path.join(base, "packages", "pagebreak")


def add_to_path():
    d = site_dir()
    if os.path.isdir(d) and d not in sys.path:
        sys.path.append(d)                      # last: a PyMuPDF that the program itself bundles still wins
        importlib.invalidate_caches()
    return d


def load():
    """The PyMuPDF module, or None when it is not there."""
    add_to_path()
    for name in ("pymupdf", "fitz"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
        except Exception:                       # noqa: BLE001 - a broken install must read as "missing", not crash the tab
            continue
    return None


def install(progress=None, installer=None):
    """Downloads PyMuPDF into site_dir().  progress(text, fraction_or_None); `installer(pins, target, progress)` is addons._pip_install unless a
    test passes its own.  Raises an Exception whose message says what went wrong (usually: no internet connection)."""
    if installer is None:
        import addons
        installer = addons._pip_install
    target = site_dir()
    new = target + ".new"
    shutil.rmtree(new, ignore_errors=True)
    try:
        installer([PIN], new, progress)
        if not os.path.isdir(new) or not os.listdir(new):
            raise RuntimeError("The download did not contain PyMuPDF.")
        shutil.rmtree(target, ignore_errors=True)
        os.replace(new, target)
    finally:
        shutil.rmtree(new, ignore_errors=True)
    for n in [m for m in sys.modules if m in ("pymupdf", "fitz") or m.startswith(("pymupdf.", "fitz."))]:
        sys.modules.pop(n, None)               # a failed earlier import must not stick
    mod = load()
    if mod is None:
        raise RuntimeError("PyMuPDF was downloaded but could not be loaded on this computer.")
    return mod
