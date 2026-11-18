"""sh_deps.py - gets openpyxl (to read and write .xlsx files) when the program does not have it.

The Playground updates the program's files in place, while the packages that come with it change only with a full installer.  So Sheets downloads
openpyxl once, into <user folder>/packages/sheets, with the same download-and-unpack code the add-ons use, and puts that folder on the search path
(at every later start too).  Nothing in the program folder or in any system Python is touched.  The rest of Sheets needs no outside package.
"""
import importlib
import os
import shutil
import sys

PINS = ["openpyxl>=3.1", "et_xmlfile>=1.1"]


def site_dir():
    try:
        import paths
        base = paths.user_dir()
    except ImportError:
        base = os.path.join(os.path.expanduser("~"), ".openpara")
    return os.path.join(base, "packages", "sheets")


def add_to_path():
    d = site_dir()
    if os.path.isdir(d) and d not in sys.path:
        sys.path.append(d)                       # last: an openpyxl that the program itself bundles still wins
        importlib.invalidate_caches()
    return d


def openpyxl():
    """The openpyxl module, or None when it is not there."""
    add_to_path()
    try:
        return importlib.import_module("openpyxl")
    except ImportError:
        return None
    except Exception:                            # noqa: BLE001 - a broken install must read as "missing", not crash the tab
        return None


def matplotlib():
    """The matplotlib module (it comes with the Playground), or None."""
    try:
        return importlib.import_module("matplotlib")
    except ImportError:
        return None
    except Exception:                            # noqa: BLE001
        return None


def install(progress=None, installer=None):
    """Downloads openpyxl into site_dir().  progress(text, fraction_or_None); `installer(pins, target, progress)` is addons._pip_install unless a test
    passes its own.  Raises an Exception whose message says what went wrong (usually: no internet connection)."""
    if installer is None:
        import addons
        installer = addons._pip_install
    target = site_dir()
    new = target + ".new"
    shutil.rmtree(new, ignore_errors=True)
    try:
        installer(PINS, new, progress)
        if not os.path.isdir(new) or not os.listdir(new):
            raise RuntimeError("The download did not contain openpyxl.")
        shutil.rmtree(target, ignore_errors=True)
        os.replace(new, target)
    finally:
        shutil.rmtree(new, ignore_errors=True)
    for n in [m for m in sys.modules if m == "openpyxl" or m.startswith("openpyxl.")]:
        sys.modules.pop(n, None)                 # a failed earlier import must not stick
    mod = openpyxl()
    if mod is None:
        raise RuntimeError("openpyxl was downloaded but could not be loaded on this computer.")
    return mod
