"""3D FEA: screws, bolts and the contact joint are gone, and an old project still opens.

Model (no window): sm.migrate brings an old setup up to date (a contact joint and its screws are dropped, a bolt / pin hole support becomes a fixed one,
nothing else is touched, a second call changes nothing); the modules of the screws and the contact joint no longer exist.
Window: the buttons and tables of the screws are not there; a project that was saved with screws and a contact joint opens bonded, says so in plain words,
loses the result that was solved with the joint and keeps the one that does not depend on it; a bolt / pin hole support opens as a fixed support and its
result is kept; a new project solves a bonded assembly as before.   python test_solid_no_screws.py"""
import faulthandler
faulthandler.dump_traceback_later(175, exit=True)
import os, sys, tempfile, shutil, json, copy
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, asm_model as am
import solid_model as sm
import solid_tab
import sim_project as sp

FAILS = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------------------------------------------ the model
old = sm.default_setup()
old.update({"joint": "contact", "design": {"standard": "AISI"}, "screws": [{"name": "S1", "faces": [], "kind": "screw"}, {"name": "S2", "faces": [], "kind": "bolt"}]})
old["supports"] = [{"mode": "fixed", "faces": []}, {"mode": "bolt", "faces": []}, {"mode": "slide", "faces": []}]
keep = copy.deepcopy(old)
notes = sm.migrate(old)
ok(len(notes) == 2 and "2 screw(s)" in notes[0] and "fully bonded" in notes[0] and "1 bolt / pin hole" in notes[1], f"two plain notes: {notes}")
ok(not any(k in old for k in ("joint", "screws", "design")), "joint, screws and design are dropped from the setup")
ok([s["mode"] for s in old["supports"]] == ["fixed", "fixed", "slide"], f"the bolt support is a fixed one, the others are untouched: {[s['mode'] for s in old['supports']]}")
ok(old["loads"] == keep["loads"] and old["material"] == keep["material"] and old["h"] == keep["h"], "loads, material and element size are untouched")
ok(sm.migrate(old) == [], "a second call changes nothing and says nothing")
fresh = sm.default_setup()
ok(sm.migrate(fresh) == [] and not any(k in fresh for k in ("joint", "screws", "design")), "a new setup has nothing to migrate and no joint, screws or design")
ok(set(sm.MODES) == {"fixed", "slide", "bearing"}, f"the support kinds (no bolt / pin hole any more, a bearing instead): {sorted(sm.MODES)}")
b_old = {"supports": [{"mode": "bearing", "faces": []}, {"mode": "bolt", "faces": []}], "loads": []}
sm.migrate(b_old)
ok([s_["mode"] for s_ in b_old["supports"]] == ["bearing", "fixed"], f"migrate leaves a bearing support alone and turns only the old bolt into a fixed one: {[s_['mode'] for s_ in b_old['supports']]}")
for mod in ("solid_screw", "solid_contact"):
    try:
        __import__(mod)
        ok(False, f"{mod} must not exist any more")
    except ImportError:
        ok(True, f"{mod} is gone")

# ------------------------------------------------------------------------------------------------ the window
T = tempfile.mkdtemp(prefix="opara_nos_")
ALU = {"name": "Aluminium 6061-T6", "density": 2700.0, "E_MPa": 68900.0, "nu": 0.33, "Sy_MPa": 276.0, "Su_MPa": 310.0}


def make_part(path, w, depth, material=None):
    d = pm.Document()
    d.params = {"H": str(depth)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (w, w))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=w)
    m.add_con("dim_v", [("ln", r["lns"][1])], value=w)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    if material:
        d.material = material
    with open(path, "w", encoding="utf-8") as f:
        f.write(d.to_json())


ad = os.path.join(T, "asm")
os.makedirs(ad)
make_part(os.path.join(ad, "base.gpd"), 20.0, 30.0)
make_part(os.path.join(ad, "cap.gpd"), 20.0, 20.0, ALU)
a = am.Assembly()
a.add_component("base.gpd", fixed=True, pos=(0, 0, 0))
a.add_component("cap.gpd", fixed=False, pos=(0, 0, 30))
asm = os.path.join(ad, "stack.gpa")
open(asm, "w").write(a.to_json())

w = solid_tab.SolidWindow(threaded=False)
ok(w.create_project(os.path.join(T, "study")) and w.import_file(asm) and w.is_asm(), f"an assembly opens {MSGS[-1:]}")
texts = [b_.text().strip() for b_ in w.findChildren(QPushButton)]
ok(not any("Bolt" in t or "screw" in t.lower() for t in texts), "no bolt or screw button")
for attr in ("screw_table", "joint_combo", "joint_box", "b_screw", "design_box"):
    ok(not hasattr(w, attr), f"the window has no {attr}")
bottom = next(f["id"] for f in w.geom["faces"] if not f["interface"] and f["normal"][2] < -0.99)
topf = next(f["id"] for f in w.geom["faces"] if not f["interface"] and f["normal"][2] > 0.99)
w.select_faces([bottom]); w.add_support("fixed")
w.select_faces([topf]); w.add_load("force", {"f": [0.0, 0.0, -10000.0]})
w.set_size("8"); w.inputs_changed()
ok(w.run_solve() and w.result is not None, f"a bonded assembly solves: {w.status_lbl.text()[:80]}")
want = 10000.0 * (30 / 200000.0 + 20 / 68900.0) / 400.0
ok(abs(w.result["umax"] - want) / want < 0.05 and w.result["equilibrium"] < 1e-6, f"umax {w.result['umax']:.6f} against {want:.6f}")
ok("joint" not in w.result and "screws" not in w.result and "contact" not in w.result, "the result has no joint, screws or contact")
ok("Bodies (fully bonded)" in w.res_lbl.text(), "the report says the bodies are fully bonded")
w.save()
ok("joint" not in w.setup and "screws" not in w.setup, "the saved setup has no joint or screws")

# ---- an old project folder: the state file has a contact joint and screws
sf = sp.state_path(w.path)
st = json.load(open(sf, encoding="utf-8"))
st["setup"]["joint"] = "contact"
st["setup"]["screws"] = [{"name": "S1", "faces": [], "kind": "screw"}]
st["setup"]["design"] = {"standard": "AISI"}
json.dump(st, open(sf, "w", encoding="utf-8"))
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
ok("joint" not in w2.setup and "screws" not in w2.setup and "design" not in w2.setup, "reopened: the setup has no joint, screws or design")
ok("fully bonded" in w2.status_lbl.text() and "screw" in w2.status_lbl.text(), f"reopened: it says why ({w2.status_lbl.text()[:130]})")
ok(w2.ready() is None and len(w2.setup["supports"]) == 1 and len(w2.setup["loads"]) == 1, "the supports and loads are all still there")
ok(w2.run_solve() and abs(w2.result["umax"] - want) / want < 0.05, "and it solves, bonded, to the same answer")

# ---- the state a study or an undo hands over: setup AND result.  A result that was solved with the joint is dropped, one that was not is kept
good = w.export_state()
old_st = {"setup": copy.deepcopy(good["setup"]), "result": dict(good["result"], joint="contact", screws=[{"name": "S1", "V": 1.0}])}
old_st["setup"].update({"joint": "contact", "screws": [{"name": "S1", "faces": [], "kind": "screw"}], "design": {"standard": "AISI"}})
w3 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w3.geom is not None
w3.import_state(old_st)
ok(w3.result is None, "import_state: a result solved with the joint is not kept")
ok("cleared" in w3.status_lbl.text() and "fully bonded" in w3.status_lbl.text(), f"import_state: the note says so ({w3.status_lbl.text()[:170]})")
ok("joint" not in w3.setup and "screws" not in w3.setup, "import_state: and the setup is migrated")
new_st = {"setup": copy.deepcopy(good["setup"]), "result": good["result"]}
w5 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w5.geom is not None
w5.import_state(new_st)
ok(w5.result is not None and abs(w5.result["umax"] - want) / want < 0.05 and "fully bonded" not in w5.status_lbl.text(), "import_state: a current result is kept, with no note")

# ---- an old bolt / pin hole support is a fixed support and its result stays (it was the same thing)
bolt_st = {"setup": copy.deepcopy(good["setup"]), "result": good["result"]}
bolt_st["setup"]["supports"][0]["mode"] = "bolt"
w4 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w4.geom is not None
w4.import_state(bolt_st)
ok(w4.setup["supports"][0]["mode"] == "fixed", "import_state: a bolt / pin hole support is a fixed support")
ok("bolt / pin hole" in w4.status_lbl.text() and w4.result is not None, f"import_state: it says so and the result is kept ({w4.status_lbl.text()[:130]})")
ok(w4.ready() is None and w4.run_solve(), "and it solves")
st5 = json.load(open(sf, encoding="utf-8"))
st5["setup"]["supports"][0]["mode"] = "bolt"
json.dump(st5, open(sf, "w", encoding="utf-8"))
w6 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
ok(w6.setup["supports"][0]["mode"] == "fixed" and "bolt / pin hole" in w6.status_lbl.text(), "reopened from the folder: the same")

shutil.rmtree(T, ignore_errors=True)
print("FAILED:" if FAILS else "OK no screws", FAILS or "")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
