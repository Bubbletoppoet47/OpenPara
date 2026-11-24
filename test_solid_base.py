"""solid_base.SolidBase on its own: a window with NO physics (every hook at its default) still has the project, the part copy, the faces, the splits, the
element sizes, the mesh and its quality, save and open.  This is what the 3D Thermal and the 3D CFD windows stand on, so it must not need the elasticity."""
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk
import solid_base, solid_tab
import sim_project as sp
import unitctl, units

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


class Bare(solid_base.SolidBase):
    """No physics at all: the defaults of every hook.  It only has to offer what the base asks of a window: show_field()."""
    kind = "solid"
    label = "Bare window"

    def __init__(self, *a, **k):
        self.shown = []
        super().__init__(*a, **k)

    def show_field(self, mesh_only=False):
        self.shown.append(mesh_only)


T = tempfile.mkdtemp(prefix="opara_solid_base_")
d = pm.Document(); d.params = {"T": "10"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
r = sk.add_rect_corner(m, (0, 0), (100, 10))
m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())

w = Bare(threaded=False)
ok(set(w.setup) == {"dims", "splits", "bond_tol", "body_mats", "body_h", "h", "mesh"}, f"a new setup has only the geometry and mesh keys: {sorted(w.setup)}")
ok(not any(hasattr(w, a) for a in ("b_import", "b_refresh", "b_new")) and not w.b_save.isEnabled() and not w.b_mesh.isEnabled(), "before a project the buttons are off, and there is no Import source")
ok("Bare window" in w.src_lbl.text() and "press" not in w.src_lbl.text().lower(), "the project bar says what window it is, and gives no instructions")
ok(w.title() == "Bare window", "the tab title is the label until there is a project")
ok(w.create_project(os.path.join(T, "bar_base")) and w.path.endswith(".gpv") and sp.kind_of_folder(w.path) == "solid", "a project folder of the window's kind is made")
ok(w.import_file(part), f"the part is copied in: {MSGS}")
g = w.geom
ok(len(g["faces"]) == 6 and abs(g["volume"] - 10000) < 1e-6 and w.faces.count() == 6, "the part is analysed: 6 faces, volume 10000")
ok(w.dims.rowCount() >= 3 and "Bare window" in w.src_lbl.text(), "its dimensions are listed")
ok(not w.has_conditions() and w.patch_conditions(0) == [] and w.refresh_lists() is None, "the hooks of the conditions do nothing")

# picking and splitting a flat face into patches
top = next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], [0, 0, 1]) > 0.99)
w.picked(top, tuple(w.geom["faces"][top]["center"]))
ok(w.sel_faces == [top] and w.sel_vertex is not None, "a click picks the face and its nearest vertex")
ok(w.split_selected(2, 1) and len(w.geom["faces"]) == 7, "a flat face is split into two patches")
ok(w.split_list.count() == 1 and w.sz_table.rowCount() == 3, "the split face is listed with the sizes of its columns and rows")
w.select_faces([f["id"] for f in w.geom["faces"] if f.get("cell") is not None][:1])
ok(w.unsplit_selected() and len(w.geom["faces"]) == 6 and not w.setup["splits"], "unsplit puts the patches back together")
top = next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], [0, 0, 1]) > 0.99)
w.select_faces([top])
ok(w.split_selected(2, 1) and len(w.setup["splits"]) == 1, "and the face can be split again")

# a window with conditions of its own (a thermal one, say): splitting a face looks in ITS lists, not in supports and loads
import solid_geom as sg


class BareCond(Bare):
    CONDITION_KINDS = (("Heat flux", "fluxes"),)

    def new_setup(self):
        return dict(super().new_setup(), fluxes=[])

    def has_conditions(self):
        return bool(self.setup.get("fluxes"))


wc = BareCond(threaded=False)
ok(wc.create_project(os.path.join(T, "bar_cond")) and wc.import_file(part), "a window with its own condition list gets a project and a part")
topc = next(f["id"] for f in wc.geom["faces"] if np.dot(f["normal"], [0, 0, 1]) > 0.99)
wc.select_faces([topc])
ok(wc.split_selected(2, 1), "its top face is split into two patches")
patch = next(f["id"] for f in wc.geom["faces"] if f.get("cell") == (0, 0) or f.get("cell") == [0, 0])
wc.setup["fluxes"].append({"name": "Flux 1", "faces": [sg.face_sig(wc.geom, patch)]})
wc.setup["fluxes"].append({"name": "Flux on the whole bottom", "faces": [sg.face_sig(wc.geom, next(f["id"] for f in wc.geom["faces"] if f["normal"][2] < -0.99))]})
ok(wc.has_conditions() and wc.patch_conditions(patch) == ["Flux 1"], f"the condition on a patch is found by the base: {wc.patch_conditions(patch)}")
wc.select_faces([patch])
ok(wc.split_selected(1, 2) and [x["name"] for x in wc.setup["fluxes"]] == ["Flux on the whole bottom"], "a new split removes the condition on its patches and keeps the others")
ok(wc.has_conditions(), "and the window still has the one it kept")

# the element size of the part, a finer size on one face, the advanced options, and the mesh with its quality
w.set_size("6"); w.inputs_changed()
ok(abs(w.setup["h"] - 6.0 * 1e-3 / units.get(unitctl.system())["L_m"] * 1e3 / 1e3 * units.get(unitctl.system())["L_m"] * 1e3) < 1e3, "the size typed is read")
ok(w.run_mesh() and w.mesh_q is not None and "tetrahedra" in w.mesh_lbl.text(), f"the part is meshed: {w.mesh_lbl.text()}")
ok(w.shown and w.shown[-1] is True, "the window is asked to draw the mesh (show_field(mesh_only=True))")
ok(w.size_table.item(0, 2).text() not in ("", None), "the size table shows how many elements the part got")
w.outline.select("Mesh")
w.cb_adv.setChecked(True)
ok(w.adv_box.isVisibleTo(w) and w.setup["mesh"]["advanced"], "the advanced mesh options open")
w.select_faces([w.geom["faces"][0]["id"]])
w.e_face_h.setText("3")
ok(w.set_face_size() and len(w.setup["mesh"]["face_sizes"]) == 1 and w.face_table.rowCount() == 1, "a finer element size on one face is kept in the list")
ok(w.run_mesh() and w.quality_box.isVisibleTo(w) and "Overall" in w.quality_lbl.text(), "with the advanced options the mesh quality is shown")
ok(w.mesh_q["quality"]["elements"] > 0, "and the quality report counts the elements")

# the job machinery: a failing job reports, does not raise, and leaves the window usable
bad = []
ok(w.run_job(lambda progress, cancel: 1 / 0, lambda r: bad.append(r), "Failing") and not bad and "division" in w.status_lbl.text().lower(), "a failing job says why")
ok(w.job is None and w.b_mesh.isEnabled(), "and the window is usable again")

# save, reopen: the options, sizes and splits come back; the project kind is checked
ok(w.save() and os.path.isfile(sp.state_path(w.path)) and not w.is_dirty(), "the project is saved")
st = json.load(open(sp.state_path(w.path)))
ok(st["kind"] == "solid" and set(st["setup"]) >= {"splits", "mesh", "h"}, "the state file has the window's kind and the setup")
w2 = Bare.open_project(None, w.path, threaded=False)
ok(w2.setup["splits"] == w.setup["splits"] and w2.setup["mesh"]["face_sizes"] == w.setup["mesh"]["face_sizes"] and w2.cb_adv.isChecked(), "reopened: splits, sizes and options are back")
ok(len(w2.geom["faces"]) == len(w.geom["faces"]) and not w2.is_dirty(), "reopened: the same faces, and nothing is unsaved")
try:
    Bare.open_project(None, T)
    ok(False, "a folder that is not a project is refused")
except ValueError as ex:
    ok("Bare window" in str(ex), f"a folder that is not a project is refused, naming the window: {ex}")

# a change of the program's units: the length labels and tables follow
unitctl.set_units("in-lb-psi" if units.valid("in-lb-psi") else next(n for n in units.SYSTEMS if units.get(n)["L"] == "in"), persist=False)
ok("in" in w.size_table.horizontalHeaderItem(1).text() and "in" in w.hmin_label.text(), "after a change of units the size labels show the new unit")
unitctl.set_units("mm" if units.valid("mm") else units.DEFAULT, persist=False)

# the elasticity window is the base plus its own parts: nothing of the material or the loads is in the base
ok(not any(hasattr(solid_base.SolidBase, n) for n in ("put_material", "add_support", "add_load", "describe", "field_values", "build_adaptive")),
   "the base has no material, supports, loads or results")
ok(w.run_solve() is False and "no solver" in w.status_lbl.text(), "and its Solve button says there is no solver")
ok(issubclass(solid_tab.SolidWindow, solid_base.SolidBase) and solid_tab.SolidWindow.label == "3D FEA" and solid_tab.SolidWindow.kind == "solid", "the 3D FEA window derives from it")
ok(all(hasattr(solid_tab.SolidWindow, n) for n in ("put_material", "add_support", "add_load", "describe", "run_solve")), "and has the elasticity")

print("\nFAILED:", FAILS) if FAILS else print("\nOK solid base")
sys.exit(1 if FAILS else 0)
