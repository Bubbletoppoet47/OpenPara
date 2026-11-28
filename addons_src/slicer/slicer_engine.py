"""The Slicer add-on: finding the slicing engine.

The engine is Orca Slicer's slicing code (libslic3r), cut down to what slicing needs and built as the Python module  orca_core
(planning/design/slicer/PLAN.md, chapter 6; engines/orca_core/).  It is not part of the add-on's zip: it is a separate download
(an unpacked wheel, like the Trainer's torch) that this add-on puts on the path.

Until the module exists, everything in the Slicer add-on asks this file whether it can slice and shows the reason when it cannot.
It needs nothing but the standard library, so it also works where the engine is missing.
"""
import importlib
import os
import sys

MODULE = "orca_core"              # the name of the engine module (the extension file inside the wheel)
WHEEL_FOLDER = "orca_core"        # the folder inside the add-on's data folder that the wheel is unpacked to


def engine_folder(add_on_folder):
    """Where the unpacked engine wheel lives, next to the add-on's other downloaded files."""
    return os.path.join(add_on_folder, "engine", WHEEL_FOLDER)


def add_to_path(add_on_folder):
    """Puts the unpacked engine on sys.path (once); True when the folder exists."""
    folder = engine_folder(add_on_folder)
    if not os.path.isdir(folder):
        return False
    if folder not in sys.path:
        sys.path.insert(0, folder)
    return True


def load():
    """The engine module, or None.  Never raises: a missing or broken engine must not stop OpenPara from starting."""
    try:
        return importlib.import_module(MODULE)
    except Exception:                                      # noqa: BLE001  (ImportError, but also a DLL that fails to load)
        return None


def status(add_on_folder=None):
    """{"available": bool, "version": str or "", "reason": str}: whether slicing can run now, and in words why not.

    The reason is for the person: it says what is missing, not which Python call failed."""
    if add_on_folder:
        add_to_path(add_on_folder)
    try:
        mod = importlib.import_module(MODULE)
    except ModuleNotFoundError:
        return {"available": False, "version": "",
                "reason": "The slicing engine has not been downloaded yet. It is a separate download the first time you slice."}
    except Exception as e:                                 # noqa: BLE001
        return {"available": False, "version": "",
                "reason": "The slicing engine is there but cannot be loaded (%s: %s)." % (type(e).__name__, e)}
    return {"available": True, "version": str(getattr(mod, "__version__", "")), "reason": ""}
