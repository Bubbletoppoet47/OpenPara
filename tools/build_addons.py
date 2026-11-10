"""
build_addons.py <out-dir> [--release] - zip the add-ons in addons_src/ for the GitHub release and write addons-index.json (names, sizes, sha256).
The version inside each zipped addon.json is set to the program version (version.py), so an add-on always matches the release it came from.
--release leaves out the add-ons that are not released yet (addons.NOT_RELEASED): a normal release does not carry them; a Playground build
(no --release) carries every add-on.  Run from the repository root.
"""
import hashlib
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import version


def not_released():
    """addons.NOT_RELEASED, read from the file itself (this script also runs where the program's packages are not installed)."""
    import ast
    import re
    text = open(os.path.join(ROOT, "addons.py"), encoding="utf-8").read()
    return tuple(ast.literal_eval(re.search(r"^NOT_RELEASED\s*=\s*(\(.*?\))", text, re.M).group(1)))


def build(out, release=False):
    os.makedirs(out, exist_ok=True)
    src = os.path.join(ROOT, "addons_src")
    index = {"core": version.__version__, "addons": {}}
    skip = not_released() if release else ()
    for aid in sorted(os.listdir(src)):
        d = os.path.join(src, aid)
        mp = os.path.join(d, "addon.json")
        if not os.path.isfile(mp) or aid in skip:
            continue
        m = json.load(open(mp, encoding="utf-8"))
        assert m["id"] == aid, (m["id"], aid)
        m["version"] = version.__version__
        name = f"addon-{aid}.zip"
        zp = os.path.join(out, name)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo("addon.json", (2020, 1, 1, 0, 0, 0)), json.dumps(m, indent=1))
            for base, dirs, files in os.walk(d):
                dirs[:] = sorted(x for x in dirs if x != "__pycache__")
                for f in sorted(files):
                    if f == "addon.json" and base == d or f.endswith(".pyc"):
                        continue
                    full = os.path.join(base, f)
                    z.write(full, os.path.relpath(full, d).replace(os.sep, "/"))
        h = hashlib.sha256(open(zp, "rb").read()).hexdigest()
        index["addons"][aid] = {"file": name, "sha256": h, "version": version.__version__, "bytes": os.path.getsize(zp)}
    with open(os.path.join(out, "addons-index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1)
    return index


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    idx = build(args[0] if args else "dist", release="--release" in sys.argv[1:])
    for a, e in idx["addons"].items():
        print(a, e["file"], e["bytes"], "bytes")
