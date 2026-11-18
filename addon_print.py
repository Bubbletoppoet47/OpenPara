"""
addon_print.py - the FINGERPRINT of an add-on: a hash of what is in its folder (every file, addon.json without its version), plus the add-on API number
(version.ADDON_API).  Two copies of an add-on have the same fingerprint exactly when they are the same code.

Every release carries the add-ons of its version stamped with the program version, so before this an add-on counted as "old" after EVERY program update
and all of them were downloaded again.  Now tools/build_addons.py writes the fingerprint into each add-on's addon.json and into addons-index.json, and
into  addon_prints.json  inside the program ({id: fingerprint} of the add-ons of that build).  An installed add-on needs an update only when its
fingerprint differs from the one its program knows.  (No imports of the program: the build script uses this where the packages are not installed.)
"""
import hashlib
import json
import os

IGNORED_KEYS = ("version", "fingerprint", "api")          # the keys of addon.json that do not belong to the code


def _manifest_bytes(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        m = json.loads(raw.decode("utf-8"))
        for k in IGNORED_KEYS:
            m.pop(k, None)
        return json.dumps(m, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (ValueError, AttributeError):
        return raw


def fingerprint(folder, api=1):
    """The fingerprint (hex) of the add-on folder `folder`: its files in a fixed order, byte for byte; __pycache__ and .pyc are left out, so are the
    packages a user installed next to the add-on (site/) - they are not part of the add-on."""
    h = hashlib.sha256()
    h.update(f"api:{int(api)}\n".encode())
    for base, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "site"))
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            if rel == "addon.json":
                data = _manifest_bytes(full)
            else:
                with open(full, "rb") as f:
                    data = f.read()
            h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()
