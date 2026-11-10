"""The release workflow must put the folders the program reads at run time into the app folder (0.8.3 shipped without assets/, so the start-up
card had no logo and no Lora font)."""
import os, re
HERE = os.path.dirname(os.path.abspath(__file__))
wf = open(os.path.join(HERE, ".github", "workflows", "release.yml"), encoding="utf-8").read()
import splash
need = {"assets"}                      # folders under the program folder that splash.py / the icons read
assert os.path.isfile(os.path.join(HERE, "assets", "openpara-logo.svg")) and os.path.isfile(os.path.join(HERE, "assets", "fonts", "Lora-Variable.ttf"))
for d in need:
    assert re.search(r'Copy-Item %s -Destination "\$app\\%s"' % (d, d), wf), f"release.yml does not copy {d}/ into the app"
assert splash.asset("openpara-logo.svg").startswith(HERE)

# ---- what a release carries: every add-on of addons_src/ except the ones that are not released yet, and nothing of the Playground
import json, sys, tempfile, shutil
import addons, version
sys.path.insert(0, os.path.join(HERE, "tools"))
import build_addons
pg = open(os.path.join(HERE, ".github", "workflows", "playground.yml"), encoding="utf-8").read()
assert build_addons.not_released() == addons.NOT_RELEASED == ("render", "motor")
released = sorted(a for a in os.listdir(os.path.join(HERE, "addons_src")) if a not in addons.NOT_RELEASED)
assert released == ["annotator", "annotator_gimble", "parametric", "partgen", "simulation", "trainer", "truss"], released
out = tempfile.mkdtemp(prefix="opara_work_")
try:
    idx = build_addons.build(os.path.join(out, "rel"), release=True)
    assert sorted(idx["addons"]) == released and idx["core"] == version.__version__
    assert sorted(f for f in os.listdir(os.path.join(out, "rel")) if f.endswith(".zip")) == [f"addon-{a}.zip" for a in released]
    full = build_addons.build(os.path.join(out, "all"))
    assert set(full["addons"]) == set(released) | {"render", "motor"}, "a Playground build carries every add-on"
    for a in released:                                   # each manifest is complete (the dialog and the installer read it) and says this version
        import zipfile
        m = json.loads(zipfile.ZipFile(os.path.join(out, "rel", f"addon-{a}.zip")).read("addon.json"))
        assert m["id"] == a and m["version"] == version.__version__ and isinstance(m["requires"], list) and m["name"] == addons.CATALOG[a]["name"], a
finally:
    shutil.rmtree(out, ignore_errors=True)
assert "tools\\build_addons.py dist --release" in wf, "the release leaves out the add-ons that are not released"
assert "build_addons.py dist --release" not in pg, "the Playground builds every add-on"
for a in released:                                       # the Windows smoke test of the release installs every released add-on, and no other
    assert f"addons.install('{a}')" in wf and f"addons.install('{a}')" in pg, a
for a in addons.NOT_RELEASED:
    assert f"addons.install('{a}')" not in wf and f"addons.install('{a}')" in pg, a
for folder in ("dev_addons", "shared", "addons_src"):
    assert not re.search(r"Copy-Item %s " % folder, wf), f"release.yml must not copy {folder}/ into the app"
# the files the installer gets import nothing from the folders it does not get
for f in sorted(os.listdir(HERE)):
    if f.endswith(".py") and not f.startswith("test_"):
        text = open(os.path.join(HERE, f), encoding="utf-8").read()
        assert not re.search(r"^\s*(import|from)\s+(study_tab|study_ext|sim_tab|render_studio|motor_tab)\b", text, re.M) or f in ("gpd_app.py",), f
# the version: one number everywhere
for a in os.listdir(os.path.join(HERE, "addons_src")):
    assert json.load(open(os.path.join(HERE, "addons_src", a, "addon.json")))["version"] == version.__version__, a
assert splash.version_text() == version.__version__
print("release files ok")
