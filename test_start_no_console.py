"""The program starts without a console.

The shortcut starts OpenPara with pythonw.exe: there is no console, so sys.stdout and sys.stderr are None, and a write to them raises.  Once an add-on's
extension could not be loaded, addons.register_extensions wrote a warning to sys.stderr from inside its `except` - that raised in gpd_app's import, before
any window or error handler existed, and the program closed at once without a word (2D Thermal and an old Simulation add-on, 23 Nov 2026).
  1. streams.ensure() gives a missing stream a sink and leaves a real one alone;
  2. importing gpd_app with NO stdout / stderr and a broken add-on does not raise: the add-on is reported (addons.load_errors), the others load;
  3. the error window's hook (gpd_app.install_excepthook) works with no stderr, and so do addons.register_extensions / addons.startup on their own
     (an add-on that cannot be put in place is reported like one that cannot load);
  4. 2D Thermal says in plain words that the Simulation add-on is too old, instead of an AttributeError, and works with the current one.
"""
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import json
import os
import subprocess
import sys
import tempfile
import types

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ---- 1. streams.ensure
import streams
real_out, real_err = sys.stdout, sys.stderr
assert streams.ensure() == [] and sys.stdout is real_out and sys.stderr is real_err, "real streams are left alone"
try:
    sys.stdout = sys.stderr = None                       # what pythonw.exe gives the program
    fixed = streams.ensure()
    assert fixed == ["stdout", "stderr"], fixed
    sys.stderr.write("a warning nobody can see\n")
    print("a print nobody can see")
    sys.stdout.flush()
finally:
    sys.stdout, sys.stderr = real_out, real_err

# ---- 2 + 3. the real start (the import of gpd_app does addons.startup() and addons.register_extensions) with no console and a broken add-on
UD = tempfile.mkdtemp(prefix="opara_ud_")
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor"]}')
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for aid, ext_text in (("broken", "def register(ext):\n    raise RuntimeError('this add-on cannot load')\n"),
                      ("fine", "def register(ext):\n    ext.add_command('view', 'A fine view', lambda shell: None)\n")):
    d = os.path.join(DEV, aid)
    os.makedirs(d)
    json.dump({"name": aid.title() + " add-on", "description": "test", "extension": aid + "_ext"}, open(os.path.join(d, "addon.json"), "w"))
    open(os.path.join(d, aid + "_ext.py"), "w").write(ext_text)
RESULT = os.path.join(UD, "result.json")
CHILD = r'''
import sys, os, json, traceback
sys.stdout = sys.stderr = None                           # what pythonw.exe gives the program
sys.path.insert(0, %(here)r)
res = {}
try:
    import gpd_app, addons, ext
    res["streams_ok"] = sys.stdout is not None and sys.stderr is not None
    res["errors"] = sorted(addons.load_errors())
    res["fine_registered"] = [c["text"] for c in ext.commands("view")]
    # 3. the error window's hook with no stderr
    shown = []
    gpd_app.show_error_text = lambda *a, **k: shown.append(a[1] if len(a) > 1 else k.get("text"))
    gpd_app.install_excepthook()
    sys.stderr = None
    try:
        raise ValueError("a handler failed")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    res["hook_shown"] = len(shown) == 1 and "a handler failed" in shown[0]
    log = os.path.join(os.environ["OPARA_USER_DIR"], gpd_app.ERROR_LOG)
    res["hook_logged"] = os.path.exists(log) and "a handler failed" in open(log, encoding="utf-8").read()
    # the add-on loader on its own (not through gpd_app's guard): a message for the console never stops it
    sys.stderr = None
    addons.register_extensions(ext)
    res["again_errors"] = sorted(addons.load_errors())
    addons.shipped = lambda: {"zzz": {"id": "zzz", "name": "Zzz add-on"}}                       # an add-on of the program folder that cannot be put in place
    addons.status = lambda aid: "not installed"
    def refuse(aid, **k):
        raise RuntimeError("disk full")
    addons.install = refuse
    sys.stderr = None
    addons.startup()
    res["startup_errors"] = dict(addons.STARTUP_ERRORS)
    addons.register_extensions(ext)                                                                # (clears the load errors, not the start-up ones)
    res["merged"] = sorted(addons.load_errors())
except BaseException:
    res["crash"] = traceback.format_exc()
json.dump(res, open(%(out)r, "w"))
''' % {"here": HERE, "out": RESULT}
env = dict(os.environ, OPARA_USER_DIR=UD, OPARA_DEV_ADDONS=DEV, OPARA_NO_UPDATE="1", OPARA_CHANNEL="release", QT_QPA_PLATFORM="offscreen")
cp = subprocess.run([sys.executable, "-c", CHILD], env=env, capture_output=True, text=True, timeout=200)
assert os.path.exists(RESULT), ("the start closed without a word", cp.returncode, cp.stdout[-800:], cp.stderr[-1500:])
res = json.load(open(RESULT))
assert "crash" not in res, res.get("crash")
assert res["streams_ok"], res
assert res["errors"] == ["broken"], res
assert res["fine_registered"] == ["A fine view"], "the add-on after the broken one still registered: " + repr(res)
assert res["hook_shown"] and res["hook_logged"], res
assert res["again_errors"] == ["broken"], res
assert list(res["startup_errors"]) == ["zzz"] and "disk full" in res["startup_errors"]["zzz"], res
assert res["merged"] == ["broken", "zzz"], "the file > Add-ons list and the message after the start also carry add-ons that could not be put in place: " + repr(res)

# ---- 4. 2D Thermal and a Simulation add-on that is too old
sys.path[:0] = [os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "shared")]
import physics_store
import sim_project
import thermal_ext
thermal_ext.register(None)                               # the current Simulation add-on: fine
assert sim_project.EXT["thermal"] == ".gph" and "thermal" in physics_store.STATE_CONVERTERS
saved = dict(sys.modules)
try:
    old_sp = types.ModuleType("sim_project")             # the Simulation add-on of build .88: no register_kind
    sys.modules["sim_project"] = old_sp
    try:
        thermal_ext.register(None)
        raise SystemExit("an old Simulation add-on must be refused")
    except RuntimeError as ex:
        text = str(ex)
        assert "newer Simulation add-on" in text and "File > Add-ons" in text and "sim_project.register_kind" in text, text
        assert "AttributeError" not in text
finally:
    sys.modules.clear()
    sys.modules.update(saved)
try:
    thermal_ext.check_simulation((types.ModuleType("sim_tab"), "register_kind"))
    raise SystemExit("the window class needs register_kind too")
except RuntimeError as ex:
    assert "sim_tab.register_kind" in str(ex)
print("OK start without a console")
