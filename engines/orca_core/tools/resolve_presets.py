#!/usr/bin/env python3
"""Flattens Orca's vendor presets: follows "inherits" up to the root and writes one standalone JSON per preset.

Orca's vendor profiles (resources/profiles/<Vendor>/{machine,process,filament}/**.json) are written as small differences on top of a parent
preset ("inherits": "<name>"). The engine and Orca's own command line take a preset without a parent as it is, so this script does the
resolving once, in the way Orca's PresetBundle does it: the child's keys replace the parent's, the parent is looked up by its "name" in the
same vendor folder (and in a second folder, for vendors that inherit from "Custom"/"fdm_*" presets kept elsewhere).

    python resolve_presets.py <Orca checkout>/resources/profiles/Elegoo <out folder> \
        "Elegoo Centauri Carbon 0.4 nozzle" "0.20mm Standard @Elegoo CC 0.4 nozzle" "Elegoo PLA @ECC"

writes <out>/machine.json, process.json, filament.json (for the first, second and third name, whichever kind they are) with "inherits"
removed, so `orca-slicer --load-settings "machine.json;process.json" --load-filaments filament.json` takes them as they are.
This is also what the profile bundle of OpenPara's slicer add-on (SLC-3) does at build time, so a bundle is the vendor's file, resolved.
"""
import json
import os
import sys


def index_presets(vendor_dir):
    """{(type, name): path} for every preset JSON under vendor_dir.  The type is the "type" key of the file."""
    out = {}
    for root, _dirs, files in os.walk(vendor_dir):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and "type" in d and "name" in d:
                out.setdefault((d["type"], d["name"]), path)
    return out


def resolve(name, kind, index, _seen=None):
    """The preset `name` of type `kind` with its parents merged in (child keys win).  Raises KeyError for a name that is not there."""
    _seen = _seen or []
    if (kind, name) in _seen:
        raise ValueError("preset %r inherits from itself: %s" % (name, " -> ".join(n for _k, n in _seen)))
    path = index.get((kind, name))
    if path is None:
        raise KeyError("no %s preset named %r" % (kind, name))
    with open(path, encoding="utf-8") as f:
        child = json.load(f)
    parent_name = child.get("inherits")
    merged = {}
    if parent_name:
        merged = resolve(parent_name, kind, index, _seen + [(kind, name)])
    merged.update(child)
    merged.pop("inherits", None)
    return merged


def find_kind(name, index):
    kinds = sorted({k for (k, n) in index if n == name})
    if not kinds:
        raise KeyError("no preset named %r" % name)
    # a machine preset and its "model" file can share a name; the one that is `instantiation: true` is the one to print with
    return kinds[0] if len(kinds) == 1 else ("machine" if "machine" in kinds else kinds[0])


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    vendor_dir, out_dir, names = argv[1], argv[2], argv[3:]
    index = index_presets(vendor_dir)
    os.makedirs(out_dir, exist_ok=True)
    for name in names:
        kind = find_kind(name, index)
        d = resolve(name, kind, index)
        d["from"] = "User"                                  # a user preset is taken as it is by the command line
        fn = os.path.join(out_dir, kind + ".json")
        with open(fn, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        print("%s: %s (%d keys) -> %s" % (kind, name, len(d), fn))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
