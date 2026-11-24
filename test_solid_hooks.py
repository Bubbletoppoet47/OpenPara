"""The 3D FEA window as the elasticity part of solid_base.SolidBase: what the base asks of it through its hooks.  The part's own material fills the boxes,
a bad number stops the reading before anything is stored, a changed setup stops the animation and says so, the supports and loads colour their faces, a new source
asks before it replaces conditions, an old project is brought up to date and its boxes filled, a change of units reaches the material boxes, the progress plan
knows the adaptive mesh and a mesh that is already made, and the project bar and the panel sections carry the window's own name.   python test_solid_hooks.py"""
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS, ASKED = [], []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: (ASKED.append(a[2] if len(a) > 2 else ""), QMessageBox.StandardButton.Yes)[1])
import pm_model as pm, sk_tools as sk
import solid_model as sm
import solid_tab
import solid_view as sv
import sim_project as sp
import unitctl, units

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


T = tempfile.mkdtemp(prefix="opara_solid_hooks_")
d = pm.Document(); d.params = {"T": "10"}
d.material = {"name": "Aluminium 6061-T6", "density": 2700.0, "E_MPa": 68900.0, "nu": 0.33, "Sy_MPa": 276.0, "Su_MPa": 310.0}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
r = sk.add_rect_corner(m, (0, 0), (100, 10))
m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())

w = solid_tab.SolidWindow(threaded=False)
ok("dims" in w.setup and w.setup["dims"] == {} and "supports" in w.setup and "adapt" in w.setup, "a new 3D FEA setup has the geometry keys and the elasticity ones")
ok(all(s_.key.startswith("solid/") for s_ in w.sections) and len(w.sections) == 6, "the six sections are kept under the window's own name")
ok(w.create_project(os.path.join(T, "bar_hooks")), "project made")
ok(w.src_lbl.text().startswith("<b>3D FEA</b> project <b>bar_hooks.gpv</b>"), f"the project bar names the window: {w.src_lbl.text()[:60]}")

# --- the part's own material fills the boxes (the default material is another one: nothing here is the default)
ASKED.clear()
ok(w.import_file(part) and not ASKED, f"the first source is copied in without a question: {ASKED}")
ok(w.e_E.text() == "68900" and abs(w.setup["material"]["E"] - 68900) < 1e-9 and abs(w.setup["material"]["nu"] - 0.33) < 1e-12 and abs(w.setup["material"]["rho"] - 2700) < 1e-9,
   f"the part's material is in the boxes and the setup: E {w.e_E.text()}")
ok(w.setup.get("mat_name") == "Aluminium 6061-T6" and w.mat_combo.currentData() == "Aluminium 6061-T6", "and it is picked in the library list")


def face(n):
    return next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], n) > 0.99)


left, right, top = face([-1, 0, 0]), face([1, 0, 0]), face([0, 0, 1])

# --- the supports and the loads colour their faces, the picked face over them
w.select_faces([left]); w.add_support("fixed")
w.select_faces([right]); w.add_load("force", {"f": [1000.0, 0.0, 0.0]})
w.select_faces([])
w.view_focus("conditions", None, [])                 # the view draws the supports and the loads together (the outline shows one node at a time)
cf = w.view.cell_face


def colour_of(fid):
    return tuple(np.round(w.view.rgb[np.where(cf == fid)[0][0]], 3))


ok(colour_of(left) == tuple(np.round(sv.SUPPORT, 3)) and colour_of(right) == tuple(np.round(sv.LOAD, 3)), f"a support face and a load face have their colours: {colour_of(left)} {colour_of(right)}")
w.select_faces([left])
ok(colour_of(left) == tuple(np.round(sv.PICK, 3)) and colour_of(right) == tuple(np.round(sv.LOAD, 3)), "and a picked face is coloured over its support")
w.select_faces([])

# --- a new source asks before it replaces supports and loads; with none it does not ask
ASKED.clear()
ok(w.import_file(part) and len(ASKED) == 1 and "replaces the copy" in ASKED[0], f"a source imported over supports and loads asks first: {len(ASKED)} question")
w.setup["supports"].clear(); w.setup["loads"].clear()
ASKED.clear()
ok(w.import_file(part) and not ASKED, "with no supports or loads it does not ask")
left, right, top = face([-1, 0, 0]), face([1, 0, 0]), face([0, 0, 1])
w.select_faces([left]); w.add_support("fixed")
w.select_faces([right]); w.add_load("force", {"f": [1000.0, 0.0, 0.0]})

# --- a bad number in the size table stops the reading before the material is stored
w.set_size("6"); w.inputs_changed()
w.e_E.setText("70000")
w.size_table.blockSignals(True); w.size_table.item(0, 1).setText("abc"); w.size_table.blockSignals(False)
try:
    w.read_inputs()
    ok(False, "a size that is not a number stops read_inputs")
except ValueError as ex:
    ok("not a number" in str(ex), f"a size that is not a number stops read_inputs: {ex}")
ok(abs(w.setup["material"]["E"] - 68900) < 1e-9, f"and the new E was not stored (E is still {w.setup['material']['E']})")
w.size_table.blockSignals(True); w.size_table.item(0, 1).setText("6"); w.size_table.blockSignals(False)
w.read_inputs()
ok(abs(w.setup["material"]["E"] - 70000) < 1e-9 and abs(w.setup["h"] - 6.0) < 1e-9, "with a good size the same call stores both")
w.e_E.setText("68900"); w.inputs_changed()

# --- the progress plan: a mesh stage until the mesh is made, the adaptive mesh has its own
rr = sm.resolve(w.geom, w.setup)
plain = w.job_plan(w.geom, rr)
ok(plain is not None and plain and plain[0][0] == "mesh", f"before meshing the plan starts with the mesh: {[x[0] for x in plain or []]}")
ok(w.run_mesh(), "meshed")
after = w.job_plan(w.geom, sm.resolve(w.geom, w.setup))
ok(after is not None and "mesh" not in [x[0] for x in after] and "assemble" in [x[0] for x in after], f"after meshing the plan has no mesh stage: {[x[0] for x in after or []]}")
w.cb_adapt.setChecked(True)
rr = sm.resolve(w.geom, w.setup)
ap = w.job_plan(w.geom, rr)
ok(bool(rr.get("adapt")) and ap is not None and ap != after and len(ap) > len(after), f"an adaptive setup gets the adaptive plan: {[x[0] for x in ap or []][:8]}")
w.cb_adapt.setChecked(False)
w.inputs_changed()

# --- a changed setup stops the animation and says so
w.set_size("6"); w.inputs_changed()
ok(w.run_solve() and w.result is not None, f"solved: {w.status_lbl.text()}")
w.anim_play()
ok(w.anim_timer.isActive(), "the animation is running")
w.select_faces([top]); w.add_load("pressure", {"p": 1.0})
ok(not w.anim_timer.isActive() and w.result is None, "a new load stops the animation and clears the result")
ok("changed since the last solve" in w.res_lbl.text(), f"and the results say so: {w.res_lbl.text()[:50]}")
w.invalidate()
ok(w.res_lbl.text() == "No result yet.", "with no result to lose it only says there is none")
w.setup["loads"].pop()
w.after_edit()

# --- a change of units reaches the material boxes
unitctl.set_units("in-lb-psi" if units.valid("in-lb-psi") else next(n for n in units.SYSTEMS if units.get(n)["L"] == "in"), persist=False)
psi = 68900.0 * 1e6 / units.get(unitctl.system())["S_Pa"]
ok(abs(float(w.e_E.text()) - psi) / psi < 1e-6, f"in the inch system E is shown in its stress unit: {w.e_E.text()} against {psi:.8g}")
unitctl.set_units("mm" if units.valid("mm") else units.DEFAULT, persist=False)
ok(abs(float(w.e_E.text()) - 68900) < 1e-6, "and back again")

# --- an old project opens: brought up to date, its boxes filled, its material and library name back
w.e_E.setText("70000"); w.inputs_changed()
ok(w.save(), "saved")
sf = sp.state_path(w.path)
st = json.load(open(sf))
st["setup"].update({"joint": "contact", "screws": [{"name": "S1", "faces": [], "kind": "bolt"}]})
st["setup"]["supports"].append({"mode": "bolt", "faces": [], "name": "Old bolt"})
json.dump(st, open(sf, "w"))
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
ok("joint" not in w2.setup and "screws" not in w2.setup and w2.setup["supports"][-1]["mode"] == "fixed", "an old project is brought up to date as it opens")
ok("fully bonded" in w2.status_lbl.text(), f"and says what was changed: {w2.status_lbl.text()[:70]}")
ok(w2.mat_combo.currentData() == "Aluminium 6061-T6", f"the library name is picked again: {w2.mat_combo.currentData()}")
ok(w2.e_E.text() == "70000" and abs(w2.setup["material"]["E"] - 70000) < 1e-9, f"with the project's numbers: E {w2.e_E.text()}")

print("\nFAILED:", FAILS) if FAILS else print("\nOK solid hooks")
sys.exit(1 if FAILS else 0)
