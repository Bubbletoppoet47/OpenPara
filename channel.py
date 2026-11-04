"""
channel.py - which copy of OpenPara this is: the normal program ("release") or the OpenPara Playground ("playground").

The Playground is the same program built from the repository's dev branch.  It differs only in what this module says:
  * its name (window title, start-up card, About box), its data folder and its taskbar group, so it lives next to a normal OpenPara;
  * its update feed: the newest "dev-<version>" pre-release on GitHub, not the newest release;
  * its add-on downloads: from that same dev pre-release;
  * it also carries dev_addons/ (add-ons that are not released) and shared/ (code those add-ons use), loaded only in Full dev mode.
The Playground has two modes (Help > Playground mode, remembered in <user folder>/playground.json, OPARA_PLAYGROUND_MODE overrides):
  testing   (default) exactly what the next release would be: only the add-ons that ship; the menus match OpenPara.
  full      no restrictions: the unreleased add-ons of dev_addons/ are loaded too.
A playground build has a  channel.json  next to this file ({"channel": "playground"}), written by .github/workflows/playground.yml.
OPARA_CHANNEL=playground|release overrides it (tests).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEV_PREFIX = "dev-"


def _file():
    try:
        with open(os.path.join(HERE, "channel.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def name_of_channel():
    c = (os.environ.get("OPARA_CHANNEL") or _file().get("channel") or "release").strip().lower()
    return "playground" if c == "playground" else "release"


def is_playground():
    return name_of_channel() == "playground"


def app_name():
    return "OpenPara Playground" if is_playground() else "OpenPara"


def asset_prefix():
    """Start of the file names of the program zip and the installer in a GitHub release of this channel."""
    return "OpenPara-Playground-" if is_playground() else "OpenPara-"


def tag_for(version_text):
    """The GitHub tag of a version: v0.8.5 for a release, dev-0.8.5.123 for a playground build."""
    return (DEV_PREFIX if is_playground() else "v") + str(version_text)


def version_of_tag(tag):
    t = str(tag)
    return t[len(DEV_PREFIX):] if t.startswith(DEV_PREFIX) else t.lstrip("vV")


MODES = ("testing", "full")
STATE_FILE = "playground.json"


def _state_path():
    import paths
    return os.path.join(paths.user_dir(), STATE_FILE)


def state():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(**fields):
    d = state()
    d.update(fields)
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
    except OSError:
        pass


def mode():
    """'testing' or 'full' (only meaningful in the Playground; the normal program is always 'testing')."""
    if not is_playground():
        return "testing"
    m = (os.environ.get("OPARA_PLAYGROUND_MODE") or state().get("mode") or "testing").strip().lower()
    return m if m in MODES else "testing"


def set_mode(m):
    if m in MODES:
        save_state(mode=m)


def is_full_dev():
    return is_playground() and mode() == "full"


def title():
    """Window title: 'OpenPara', or 'OpenPara Playground (testing)' / '(full dev)'."""
    return app_name() if not is_playground() else f"{app_name()} ({'full dev' if mode() == 'full' else 'testing'})"


def dev_addons_dir():
    """<program folder>/dev_addons in a Playground build in Full dev mode (add-ons that are never released), else None."""
    d = os.path.join(HERE, "dev_addons")
    return d if is_full_dev() and os.path.isdir(d) else None


def shared_dir():
    d = os.path.join(HERE, "shared")
    return d if is_full_dev() and os.path.isdir(d) else None
