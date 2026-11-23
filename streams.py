"""streams.py - the program must start without a console.

The shortcut starts OpenPara with pythonw.exe (no console window).  Python then has NO standard output and NO standard error: sys.stdout and sys.stderr are
None, and  sys.stderr.write(...)  raises AttributeError.  A message meant for a console (an add-on that could not be loaded, a library's warning) must
never be able to stop the program, so the very first lines of gpd_app.py call ensure(): a missing stream becomes an empty sink.
"""
import os
import sys


def ensure():
    """Gives sys.stdout and sys.stderr a sink when the program runs without a console (they are None then).  -> the names that were replaced."""
    fixed = []
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
                fixed.append(name)
            except OSError:
                pass
    return fixed
