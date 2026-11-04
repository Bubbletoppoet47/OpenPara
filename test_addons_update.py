"""Updating an add-on brings the packages it needs, also the ones the OLD copy already had (its folder is removed by the update), and the
start-up question offers out-of-date add-ons an update; 'No' is remembered for this version of the program."""
import os, sys, json, tempfile, zipfile, shutil, importlib
HERE = os.path.dirname(os.path.abspath(__file__))
UD = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = UD; os.environ["OPARA_NO_UPDATE"] = "1"; os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, HERE)
import addons, version

# a tiny package as a local wheel, found through a local "index" (no network)
WH = os.path.join(UD, "wheels"); os.makedirs(WH)
def make_wheel(name, ver, mod):
    fn = f"{name}-{ver}-py3-none-any.whl"
    with zipfile.ZipFile(os.path.join(WH, fn), "w") as z:
        z.writestr(f"{mod}.py", f"VALUE = {ver!r}\n")
        z.writestr(f"{name}-{ver}.dist-info/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: {ver}\n")
        z.writestr(f"{name}-{ver}.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: t\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{name}-{ver}.dist-info/RECORD", "")
make_wheel("openparatestpkg", "1.0", "opara_test_pkg")
os.environ["PIP_NO_INDEX"] = "1"; os.environ["PIP_FIND_LINKS"] = WH

# a release folder with add-on "needspkg" in two versions
def release(ver):
    out = os.path.join(UD, "rel" + ver); os.makedirs(out)
    src = os.path.join(UD, "src" + ver, "needspkg"); os.makedirs(src)
    json.dump({"id": "needspkg", "name": "Needs a package", "version": ver, "description": "t", "requires": [{"pip": "openparatestpkg==1.0", "import": "opara_test_pkg"}]},
              open(os.path.join(src, "addon.json"), "w"))
    open(os.path.join(src, "needs_mod.py"), "w").write("X = 1\n")
    zp = os.path.join(out, "addon-needspkg.zip")
    with zipfile.ZipFile(zp, "w") as z:
        for f in ("addon.json", "needs_mod.py"):
            z.write(os.path.join(src, f), f)
    import hashlib
    json.dump({"core": ver, "addons": {"needspkg": {"file": "addon-needspkg.zip", "sha256": hashlib.sha256(open(zp, "rb").read()).hexdigest(), "version": ver, "bytes": os.path.getsize(zp)}}},
              open(os.path.join(out, "addons-index.json"), "w"))
    return out
r1, r2 = release("0.1.0"), release("0.2.0")
addons.CATALOG["needspkg"] = {"name": "Needs a package", "description": "t"}
addons.SRC_DIR = os.path.join(UD, "no_src")
os.environ["OPARA_ADDON_BASE"] = "file://" + r1 + "/"
addons.install("needspkg")
site = os.path.join(addons.installed_path("needspkg"), "site")
assert os.path.isfile(os.path.join(site, "opara_test_pkg.py")), os.listdir(addons.installed_path("needspkg"))
import opara_test_pkg                                     # imported and loaded, like a running program that used it
assert opara_test_pkg.VALUE == "1.0"

# the update: the package is already importable (from the OLD copy), it must still be in the NEW copy
os.environ["OPARA_ADDON_BASE"] = "file://" + r2 + "/"
addons.install("needspkg")
assert json.load(open(os.path.join(addons.installed_path("needspkg"), "addon.json")))["version"] == "0.2.0"
assert os.path.isfile(os.path.join(addons.installed_path("needspkg"), "site", "opara_test_pkg.py")), "the update lost the package"
assert addons._importable_without("opara_test_pkg", None) and not addons._importable_without("opara_test_pkg", "needspkg")
# a package the base really has is not downloaded again
assert addons._missing_packages({"requires": [{"pip": "numpy==0", "import": "json"}]}, "needspkg") == []

# ---- the start-up question
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import ext, gpd_app
del os.environ["OPARA_NO_UPDATE"]
manifest_path = os.path.join(addons.installed_path("needspkg"), "addon.json")
m = json.load(open(manifest_path)); m["version"] = "0.0.1"; json.dump(m, open(manifest_path, "w"))
assert addons.status("needspkg") == "update" and addons.outdated() == ["needspkg"], (addons.status("needspkg"), addons.outdated())
asked = []
shell = gpd_app.AppShell.__new__(gpd_app.AppShell)
def fake_q(*a, **k):
    asked.append(a[2]); return QMessageBox.StandardButton.No
QMessageBox.question = staticmethod(fake_q)
gpd_app.AppShell.offer_addon_updates(shell)
assert len(asked) == 1 and "Needs a package" in asked[0] and "File > Add-ons" in asked[0]
gpd_app.AppShell.offer_addon_updates(shell)               # declined for this version: not asked again
assert len(asked) == 1 and addons.update_prompt_declined()
addons.set_update_prompt_declined(False)
# Yes: updates it (target version of an installed program is version.py's)
installed = []
import addons_dialog
addons_dialog.install_with_progress = lambda parent, aid: (installed.append(aid), True)[1]
shell.addons_changed = lambda: installed.append("changed")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
gpd_app.AppShell.offer_addon_updates(shell)
assert installed == ["needspkg", "changed"], installed
# nothing outdated: nothing asked
shutil.rmtree(addons.installed_path("needspkg")); asked.clear()
QMessageBox.question = staticmethod(fake_q)
gpd_app.AppShell.offer_addon_updates(shell); assert not asked
print("addon update ok")
