"""
paths.py - where OpenPara keeps your own data.

The program folder is replaced by every update, so nothing of yours may live in it: the error log, your material library and the
settings are kept in  %LOCALAPPDATA%\\OpenPara  (Windows)  or  ~/.local/share/OpenPara  (elsewhere).  OPARA_USER_DIR overrides it (tests).
A file that is shipped with the program (materials.json) is copied there the first time it is needed.
"""
import os
import shutil
import sys

APP_NAME = "OpenPara"
CODE_DIR = os.path.dirname(os.path.abspath(__file__))


def user_dir():
    d = os.environ.get("OPARA_USER_DIR")
    if not d:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
        d = os.path.join(base, APP_NAME)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def user_file(name, seed=True):
    """Path of a data file in the user folder; when it does not exist yet and a file of that name sits next to the program, that one is copied
    (the shipped library, or the data an older copy of the program kept next to its code)."""
    p = os.path.join(user_dir(), name)
    if seed and not os.path.exists(p):
        src = os.path.join(CODE_DIR, name)
        if os.path.exists(src):
            try:
                shutil.copy2(src, p)
            except OSError:
                pass
    return p


def python_exe():
    """The console python.exe next to a (renamed) pythonw.exe: helper programs (render, mesh probe) need real pipes."""
    exe = sys.executable or "python"
    d, n = os.path.split(exe)
    if n.lower() in ("pythonw.exe", "openpara.exe"):
        c = os.path.join(d, "python.exe")
        if os.path.exists(c):
            return c
    return exe
