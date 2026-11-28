"""
prepare_orca.py - checks an Orca Slicer checkout against ORCA_PIN and applies our patches to it.

    python prepare_orca.py <orca checkout> [--check] [--revert]

--check   only test that every patch would apply (this is how a new Orca release announces itself)
--revert  take our patches off again (git apply -R, in the reverse order)

The patches are in ../patches/*.patch, applied in name order with `git apply`. The checkout must be at the commit in ../ORCA_PIN.
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def pin():
    d = {}
    for line in open(os.path.join(ROOT, "ORCA_PIN"), encoding="utf-8"):
        if line.strip() and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            d[k.strip()] = v.strip()
    return d


def git(orca, *args, check=True):
    return subprocess.run(["git", "-C", orca] + list(args), capture_output=True, text=True, check=check)


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    orca = argv[1]
    flags = set(argv[2:])
    want = pin()["commit"]
    got = git(orca, "rev-parse", "HEAD").stdout.strip()
    if got != want:
        raise SystemExit("Orca checkout is at %s, ORCA_PIN says %s (%s)" % (got[:12], want[:12], pin()["tag"]))
    patches = sorted(glob.glob(os.path.join(ROOT, "patches", "*.patch")))
    if "--revert" in flags:
        for p in reversed(patches):
            r = git(orca, "apply", "-R", p, check=False)
            print(("reverted " if r.returncode == 0 else "NOT applied ") + os.path.basename(p))
        return 0
    bad = 0
    for p in patches:
        r = git(orca, "apply", "--check", p, check=False)
        if r.returncode != 0:
            print("DOES NOT APPLY: %s\n%s" % (os.path.basename(p), r.stderr.strip()))
            bad += 1
            continue
        if "--check" not in flags:
            git(orca, "apply", p)
        print(("ok      " if "--check" in flags else "applied ") + os.path.basename(p))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
