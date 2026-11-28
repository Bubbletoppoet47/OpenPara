#!/usr/bin/env python3
"""Builds the profile bundle of the slicer add-on (SLC-3, plan 6.6 and chapter 9): Orca's vendor profiles, unchanged, in one zip.

    python build_profiles.py <Orca checkout>/resources/profiles  profiles.zip  [--vendors Elegoo,Creality] [--all]

The zip has the same layout as Orca's folder (`Elegoo.json`, `Elegoo/machine/...`), so `orca_core.profiles.Profiles` reads the folder and the zip
the same way.  What goes in: the vendors asked for (default: Elegoo), always `OrcaFilamentLibrary` (the generic filaments, and the base presets
many vendors inherit from) and `Custom` (the generic printer types for a printer that is not listed), every file of each (the presets, and the pictures and
bed models the window will show).  `bundle.json` at the top says which Orca profile version it is made from, which vendors it holds and the
sha256 of each file, so the add-on can check what it downloaded.

The presets are not changed: resolving them (following "inherits") is done when they are read, in profiles.py, so a profile update from Orca
can be dropped in without a build step in between.
"""
import argparse
import hashlib
import json
import os
import sys
import zipfile

ALWAYS = ("OrcaFilamentLibrary", "Custom")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profiles", help="the resources/profiles folder of an Orca checkout")
    ap.add_argument("out", help="the zip to write")
    ap.add_argument("--vendors", default="Elegoo", help="comma-separated vendor names (default: Elegoo)")
    ap.add_argument("--all", action="store_true", help="every vendor (about 94 MB of profiles)")
    ap.add_argument("--orca-version", default="", help="written into bundle.json (for example 2.5.2)")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.profiles)
    present = sorted(n[:-5] for n in os.listdir(root) if n.endswith(".json") and os.path.isdir(os.path.join(root, n[:-5])))
    wanted = present if args.all else [v.strip() for v in args.vendors.split(",") if v.strip()]
    missing = [v for v in wanted if v not in present]
    if missing:
        print("These vendors are not in %s: %s" % (root, ", ".join(missing)), file=sys.stderr)
        return 2
    vendors = list(wanted) + [v for v in ALWAYS if v in present and v not in wanted]

    files = {}
    for v in vendors:
        files[v + ".json"] = os.path.join(root, v + ".json")
        for dirpath, _dirs, names in os.walk(os.path.join(root, v)):
            for n in names:
                full = os.path.join(dirpath, n)
                files[os.path.relpath(full, root).replace(os.sep, "/")] = full
    hotend = os.path.join(root, "hotend.stl")
    if os.path.isfile(hotend):
        files["hotend.stl"] = hotend

    manifest = {"orca_version": args.orca_version, "vendors": vendors, "files": {}}
    versions = {}
    for v in vendors:
        with open(os.path.join(root, v + ".json"), encoding="utf-8-sig") as f:
            versions[v] = json.load(f).get("version", "")
    manifest["vendor_versions"] = versions
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in sorted(files):
            with open(files[rel], "rb") as f:
                data = f.read()
            manifest["files"][rel] = hashlib.sha256(data).hexdigest()
            z.writestr(zipfile.ZipInfo(rel, (2026, 1, 1, 0, 0, 0)), data, zipfile.ZIP_DEFLATED, 9)         # a fixed date: the same input gives the same zip
        z.writestr(zipfile.ZipInfo("bundle.json", (2026, 1, 1, 0, 0, 0)), json.dumps(manifest, indent=1, sort_keys=True), zipfile.ZIP_DEFLATED, 9)
    print("%s: %d vendors (%s), %d files, %.1f MB" % (args.out, len(vendors), ", ".join(vendors), len(files), os.path.getsize(args.out) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
