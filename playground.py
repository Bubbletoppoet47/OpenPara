"""
playground.py - what only the Playground does at start-up (no Qt here, so it is testable): the first start offers to bring over your OpenPara
settings and to install the add-ons a normal OpenPara offers, so the Playground behaves like OpenPara.  gpd_app.py shows the questions.
Nothing of the normal OpenPara's data folder is ever changed: it is only read.
"""
import os
import shutil

import channel
import paths

SKIP_NAMES = {"addons.json", channel.STATE_FILE}
SKIP_PARTS = ("update", ".log", ".tmp", ".part", ".lock")


def normal_user_dir():
    """The data folder of the normal OpenPara (OPARA_NORMAL_USER_DIR overrides, for tests)."""
    d = os.environ.get("OPARA_NORMAL_USER_DIR")
    if d:
        return d
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "OpenPara")


def first_run_pending():
    return channel.is_playground() and not channel.state().get("first_run_done")


def mark_first_run_done():
    channel.save_state(first_run_done=True)


def copyable_settings():
    """Names of the files in the normal OpenPara's data folder that this Playground does not have yet (settings, material library ...)."""
    src, dst = normal_user_dir(), paths.user_dir()
    if os.path.abspath(src) == os.path.abspath(dst) or not os.path.isdir(src):
        return []
    out = []
    for n in sorted(os.listdir(src)):
        low = n.lower()
        if n in SKIP_NAMES or any(p in low for p in SKIP_PARTS) or not os.path.isfile(os.path.join(src, n)):
            continue
        if not os.path.exists(os.path.join(dst, n)):
            out.append(n)
    return out


def copy_settings():
    """Copies copyable_settings() into the Playground's folder; returns the names copied."""
    done = []
    for n in copyable_settings():
        try:
            shutil.copy2(os.path.join(normal_user_dir(), n), os.path.join(paths.user_dir(), n))
            done.append(n)
        except OSError:
            pass
    return done


def addons_to_offer():
    """The add-ons a normal OpenPara offers (shipped ones) that are not installed here, in install order."""
    import addons
    return [a for a in addons.CATALOG if addons.offered(a) and not addons.is_installed(a)]
