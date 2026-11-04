"""boot.py - what the playground's add-ons expect from the old Playground layout, for the repository layout.

In the repository (and in a Playground build) OpenPara's own code sits in the program folder itself, with shared/ and dev_addons/ beside it:
    <program folder>/*.py   shared/   dev_addons/<id>/   addons_src/<id>/
`import boot` gives the same names the old Playground's boot.py gave: ROOT, CORE (= the program folder), SHARED, ADDONS.
"""
import os
import sys

SHARED = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SHARED)
CORE = ROOT
ADDONS = os.path.join(ROOT, "dev_addons")
os.environ.setdefault("QT_API", "pyqt6")


def setup():
    for p in (SHARED, CORE):
        if p not in sys.path:
            sys.path.insert(0, p)


setup()
