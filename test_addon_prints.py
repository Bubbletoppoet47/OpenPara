"""Add-on fingerprints: a program update only offers the add-ons whose code really changed.  addon_print.fingerprint (same code = same fingerprint,
whatever the version number), tools/build_addons.py (fingerprint in addon.json, addons-index.json and the addon_prints.json of the program), and
addons.status / outdated (fingerprint first; the version number only for add-ons installed before fingerprints existed or a source checkout)."""
import os, sys, json, tempfile, zipfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD; os.environ["OPARA_NO_UPDATE"] = "1"; os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("OPARA_DEV_ADDONS", None)
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import addon_print as ap
import version, paths, addons
import build_addons as ba

# ------------------------------------------------------------------------------------------------------------ the fingerprint
def make(folder, files, manifest=None):
    os.makedirs(folder, exist_ok=True)
    m = {"id": "x", "name": "X", "version": "0.1.0", "requires": []}
    m.update(manifest or {})
    json.dump(m, open(os.path.join(folder, "addon.json"), "w"), indent=1)
    for n, t in files.items():
        p = os.path.join(folder, n); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(t)
T = tempfile.mkdtemp(prefix="opara_fp_")
make(os.path.join(T, "a"), {"m.py": "X = 1\n", "sub/n.py": "Y = 2\n", "assets/t.txt": "hello"})
make(os.path.join(T, "b"), {"assets/t.txt": "hello", "sub/n.py": "Y = 2\n", "m.py": "X = 1\n"}, {"version": "9.9.9"})      # other order, other version
fa, fb = ap.fingerprint(os.path.join(T, "a")), ap.fingerprint(os.path.join(T, "b"))
assert fa == fb and len(fa) == 64, "same code = same fingerprint, whatever the version number and the order the files were written in"
os.makedirs(os.path.join(T, "b", "__pycache__")); open(os.path.join(T, "b", "__pycache__", "m.cpython-312.pyc"), "wb").write(b"junk")
os.makedirs(os.path.join(T, "b", "site")); open(os.path.join(T, "b", "site", "pkg.py"), "w").write("p")
open(os.path.join(T, "b", "x.pyc"), "wb").write(b"j")
assert ap.fingerprint(os.path.join(T, "b")) == fa, "caches and the packages next to the add-on are not part of it"
json.dump({"id": "x", "name": "X", "version": "0.1.0", "requires": [], "fingerprint": "zz", "api": 7}, open(os.path.join(T, "b", "addon.json"), "w"))
assert ap.fingerprint(os.path.join(T, "b")) == fa, "the keys written by the build (version, fingerprint, api) are not part of it"
open(os.path.join(T, "b", "m.py"), "w").write("X = 2\n")
assert ap.fingerprint(os.path.join(T, "b")) != fa, "a changed file"
open(os.path.join(T, "b", "m.py"), "w").write("X = 1\n")
assert ap.fingerprint(os.path.join(T, "b")) == fa
open(os.path.join(T, "b", "new.py"), "w").write("")
assert ap.fingerprint(os.path.join(T, "b")) != fa, "a new file"
os.remove(os.path.join(T, "b", "new.py"))
os.rename(os.path.join(T, "b", "sub", "n.py"), os.path.join(T, "b", "sub", "o.py"))
assert ap.fingerprint(os.path.join(T, "b")) != fa, "a renamed file"
os.rename(os.path.join(T, "b", "sub", "o.py"), os.path.join(T, "b", "sub", "n.py"))
make(os.path.join(T, "c"), {"m.py": "X = 1\n", "sub/n.py": "Y = 2\n", "assets/t.txt": "hello"}, {"requires": [{"pip": "gmsh==4.15.2", "import": "gmsh"}]})
assert ap.fingerprint(os.path.join(T, "c")) != fa, "its packages (requires) are part of it"
assert ap.fingerprint(os.path.join(T, "a"), api=2) != fa, "another add-on API number changes every fingerprint"
print("OK fingerprint")

# ------------------------------------------------------------------------------------------------------------ the build
dist = os.path.join(T, "dist")
idx = ba.build(dist)
pr = ba.prints()
assert pr["api"] == getattr(version, "ADDON_API", 1) and set(pr["addons"]) == set(idx["addons"])
for aid, e in idx["addons"].items():
    assert e["fingerprint"] == pr["addons"][aid]
    with zipfile.ZipFile(os.path.join(dist, e["file"])) as z:
        m = json.loads(z.read("addon.json"))
    assert m["fingerprint"] == e["fingerprint"] and m["api"] == pr["api"] and m["version"] == version.__version__
assert idx["api"] == pr["api"]
assert ba.prints(release=True)["addons"].keys() == (pr["addons"].keys() - set(ba.not_released()))
assert ba.prints() == pr, "the same sources give the same fingerprints"
print("OK build")

# ------------------------------------------------------------------------------------------------------------ status and outdated
CODE = os.path.join(T, "program"); os.makedirs(CODE)
paths.CODE_DIR = CODE
addons.SRC_DIR = os.path.join(T, "no_src")
os.environ["OPARA_ADDON_BASE"] = "file://" + dist + "/"
def put_prints(d):
    json.dump({"api": 1, "addons": d}, open(os.path.join(CODE, addons.PRINTS_FILE), "w"))
put_prints(pr["addons"])
addons.install("partgen"); addons.install("truss")
assert addons.status("partgen") == "installed" and addons.status("truss") == "installed"
assert addons.installed_manifest("partgen")["fingerprint"] == pr["addons"]["partgen"]
assert addons.outdated() == []
# a program update: the version number grows (so the old rule would call BOTH add-ons old), only partgen's code changed
version.__version__ = "0.9.0"
assert addons.target_version() == "0.9.0" and addons._vkey("0.9.0") > addons._vkey(addons.installed_manifest("truss")["version"])
newp = dict(pr["addons"]); newp["partgen"] = "f" * 64
put_prints(newp)
assert addons.status("truss") == "installed" and addons.status("partgen") == "update"
assert addons.outdated() == ["partgen"], addons.outdated()
# the release of that version has the new partgen: installing it fixes the status
dist2 = os.path.join(T, "dist2"); shutil.copytree(dist, dist2)
zp = os.path.join(dist2, "addon-partgen.zip")
with zipfile.ZipFile(zp) as z:
    items = {n: z.read(n) for n in z.namelist()}
m = json.loads(items["addon.json"]); m["fingerprint"] = "f" * 64; m["version"] = "0.9.0"; items["addon.json"] = json.dumps(m).encode()
with zipfile.ZipFile(zp, "w") as z:
    for n, d in items.items():
        z.writestr(n, d)
import hashlib
ix = json.load(open(os.path.join(dist2, "addons-index.json"))); ix["addons"]["partgen"]["sha256"] = hashlib.sha256(open(zp, "rb").read()).hexdigest()
json.dump(ix, open(os.path.join(dist2, "addons-index.json"), "w"))
os.environ["OPARA_ADDON_BASE"] = "file://" + dist2 + "/"
addons.install("partgen")
assert addons.status("partgen") == "installed" and addons.outdated() == []
# the add-on API number changed: every fingerprint is new, so everything is offered
put_prints({k: "e" * 64 for k in pr["addons"]})
assert sorted(addons.outdated()) == ["partgen", "truss"]
# an add-on installed before fingerprints existed: the version number decides (older = update, same release = up to date)
mp = os.path.join(addons.installed_path("truss"), "addon.json")
m = json.load(open(mp)); m.pop("fingerprint"); m.pop("api"); m["version"] = "0.8.6"; json.dump(m, open(mp, "w"))
put_prints(pr["addons"])
assert addons.status("truss") == "update"
m["version"] = "0.9.0"; json.dump(m, open(mp, "w"))
assert addons.status("truss") == "installed"
# a program without the list (a source checkout) uses the version number as before
os.remove(os.path.join(CODE, addons.PRINTS_FILE))
assert addons.target_print("truss") is None
m["version"] = "0.8.6"; json.dump(m, open(mp, "w")); assert addons.status("truss") == "update"
m["version"] = "0.9.0"; json.dump(m, open(mp, "w")); assert addons.status("truss") == "installed"
# a damaged list is the same as none
open(os.path.join(CODE, addons.PRINTS_FILE), "w").write("{nope"); assert addons.target_print("truss") is None
print("OK status")
shutil.rmtree(T, ignore_errors=True)
print("OK test_addon_prints")
os._exit(0)
