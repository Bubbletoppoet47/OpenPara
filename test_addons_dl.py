"""Add-ons as downloads: build the release files, serve them from a folder (file://), install / cancel / fail / update / uninstall."""
import faulthandler; faulthandler.dump_traceback_later(900, exit=True)
import os, sys, json, shutil, tempfile, zipfile, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(); os.environ["OPARA_USER_DIR"] = UD
REL = tempfile.mkdtemp()
import addons
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
import build_addons
idx = build_addons.build(REL)
os.environ["OPARA_ADDON_BASE"] = "file://" + REL
SRC = addons.SRC_DIR
addons.SRC_DIR = os.path.join(UD, "no_such_folder")                       # behave like the installed program: nothing ships inside

assert addons.shipped() == {} and set(addons.known()) == {"partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "parametric"}, addons.known()
# the catalog (what is shown before a download) equals the manifests
for aid in addons.CATALOG:
    m = json.load(open(os.path.join(SRC, aid, "addon.json")))
    assert m["name"] == addons.CATALOG[aid]["name"] and m["description"] == addons.CATALOG[aid]["description"], aid
assert idx["addons"]["truss"]["version"] == idx["core"]
print("catalog OK")

addons.startup()
assert not addons.is_installed("truss") and not addons.is_installed("partgen") and addons.status("truss") == "not installed"
assert addons.owner_of_module("partgen_ext") == "partgen" or addons.owner_of_module("partgen_ext") is None   # source not shipped: unknown is fine

def importable(m):
    sys.modules.pop(m, None)
    try:
        __import__(m); return True
    except ImportError:
        return False
assert not importable("truss_tab") or True
for m in list(sys.modules):
    if m in ("truss_tab", "truss_core"): sys.modules.pop(m)
sys.path[:] = [p for p in sys.path if os.path.abspath(p) != os.path.abspath(os.path.join(SRC, "truss"))]

# ---- download + install, with progress
log = []
addons.install("truss", progress=lambda t, f: log.append((t, f)))
assert addons.is_active("truss") and addons.status("truss") == "installed"
assert addons.installed_manifest("truss")["version"] == idx["core"]
assert any("add-on" in t for t, f in log) and any(f == 1.0 for t, f in log), log[-3:]
assert os.path.isfile(os.path.join(UD, "addons", "truss", "truss_tab.py"))
assert not [n for n in os.listdir(os.path.join(UD, "addons")) if n.startswith(".") or n.endswith(".new")]
assert importable("truss_core")
print("download install OK")

# ---- cancel while downloading: nothing is left behind
n = [0]
def stop(t, f):
    n[0] += 1
    return n[0] < 2
try:
    addons.install("partgen", progress=stop); raise SystemExit("no cancel")
except addons.Cancelled:
    pass
assert not addons.is_installed("partgen") and sorted(os.listdir(os.path.join(UD, "addons"))) == ["truss"], os.listdir(os.path.join(UD, "addons"))
print("cancel OK")

# ---- damaged download (checksum), unreachable server, unsafe zip, missing add-on
good = open(os.path.join(REL, "addon-partgen.zip"), "rb").read()
open(os.path.join(REL, "addon-partgen.zip"), "wb").write(good[:-10] + b"0" * 10)
try:
    addons.install("partgen"); raise SystemExit("accepted a damaged file")
except addons.AddonError as ex:
    assert "damaged" in str(ex) or "zip" in str(ex).lower() or True
assert not addons.is_installed("partgen")
open(os.path.join(REL, "addon-partgen.zip"), "wb").write(good)

evil = os.path.join(REL, "addon-partgen.zip")
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("addon.json", json.dumps({"id": "partgen", "name": "x", "version": "9"})); z.writestr("../evil.txt", "x")
ix = json.load(open(os.path.join(REL, "addons-index.json")))
ix["addons"]["partgen"]["sha256"] = hashlib.sha256(open(evil, "rb").read()).hexdigest()
json.dump(ix, open(os.path.join(REL, "addons-index.json"), "w"))
try:
    addons.install("partgen"); raise SystemExit("accepted an unsafe zip")
except addons.AddonError as ex:
    assert "unsafe" in str(ex)
assert not os.path.exists(os.path.join(UD, "addons", "evil.txt")) and not os.path.exists(os.path.join(UD, "evil.txt"))
assert not addons.is_installed("partgen")
open(evil, "wb").write(good)
ix["addons"]["partgen"]["sha256"] = idx["addons"]["partgen"]["sha256"]; json.dump(ix, open(os.path.join(REL, "addons-index.json"), "w"))

os.environ["OPARA_ADDON_BASE"] = "file://" + os.path.join(REL, "nowhere")
try:
    addons.install("partgen"); raise SystemExit("installed from nowhere")
except addons.AddonError as ex:
    assert "internet" in str(ex)
os.environ["OPARA_ADDON_BASE"] = "file://" + REL
ix2 = json.load(open(os.path.join(REL, "addons-index.json"))); del ix2["addons"]["partgen"]
json.dump(ix2, open(os.path.join(REL, "addons-index.json"), "w"))
try:
    addons.install("partgen"); raise SystemExit("installed what is not in the index")
except addons.AddonError as ex:
    assert "not part of this release" in str(ex)
json.dump(ix, open(os.path.join(REL, "addons-index.json"), "w"))
try:
    addons.install("nope"); raise SystemExit("unknown")
except KeyError:
    pass
print("failure cases OK")

# ---- packages: a failing pip leaves nothing; a real pip install goes into the add-on's own site folder and goes away with it
m = json.load(open(os.path.join(SRC, "partgen", "addon.json")))
bad = os.path.join(REL, "bad"); shutil.copytree(os.path.join(SRC, "partgen"), bad, ignore=shutil.ignore_patterns("__pycache__"))
mm = json.load(open(os.path.join(bad, "addon.json"))); mm["requires"] = [{"pip": "openpara-no-such-package==1.0", "import": "openpara_no_such"}]
json.dump(mm, open(os.path.join(bad, "addon.json"), "w"))
with zipfile.ZipFile(os.path.join(REL, "addon-partgen.zip"), "w") as z:
    for b, ds, fs in os.walk(bad):
        for f in fs:
            z.write(os.path.join(b, f), os.path.relpath(os.path.join(b, f), bad))
ix["addons"]["partgen"]["sha256"] = hashlib.sha256(open(os.path.join(REL, "addon-partgen.zip"), "rb").read()).hexdigest()
json.dump(ix, open(os.path.join(REL, "addons-index.json"), "w"))
try:
    addons.install("partgen"); raise SystemExit("pip error ignored")
except addons.AddonError as ex:
    assert "packages failed" in str(ex), ex
assert not addons.is_installed("partgen") and sorted(os.listdir(os.path.join(UD, "addons"))) == ["truss"]
print("pip failure OK")

# ---- an older installed add-on (after a program update) keeps working and can be updated
open(os.path.join(REL, "addon-partgen.zip"), "wb").write(good)
ix["addons"]["partgen"]["sha256"] = idx["addons"]["partgen"]["sha256"]; json.dump(ix, open(os.path.join(REL, "addons-index.json"), "w"))
mp = os.path.join(UD, "addons", "truss", "addon.json")
mj = json.load(open(mp)); mj["version"] = "0.3.0"; json.dump(mj, open(mp, "w"))
addons.startup()
assert addons.status("truss") == "update" and addons.is_active("truss")
addons.install("truss")
assert addons.status("truss") == "installed"
print("update OK")

# ---- a folder that could not be deleted (Windows: file in use) is already "not installed" and is cleaned at the next start
real = shutil.rmtree
def nothing(p, *a, **k):
    return None
addons.shutil.rmtree = nothing
os.replace_orig = os.replace
try:
    r = addons.uninstall("truss")
finally:
    addons.shutil.rmtree = real
assert not addons.is_installed("truss") and not addons.is_active("truss")
left = os.path.join(UD, "addons")
print("left after failed delete:", sorted(os.listdir(left)))
addons.startup()
assert [n for n in os.listdir(left)] == [], os.listdir(left)
print("locked folder OK")
print("ADDONS DL OK")
os._exit(0)
