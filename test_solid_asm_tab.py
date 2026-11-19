"""The 3D FEA window with an ASSEMBLY: import a .gpa (the copy brings its parts), the bodies list with the materials of the parts, changing one body's
material, the bond distance, a part that touches nothing, supports and loads on faces of different bodies, the solve and the per-body results,
save and reopen, and that a parametric study is refused."""
import faulthandler
faulthandler.dump_traceback_later(175, exit=True)
import os, sys, tempfile, shutil, json
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
import pm_model as pm, sk_tools as sk, asm_model as am
import solid_tab
import sim_project as sp

T = tempfile.mkdtemp(prefix="opara_solid_asm_")
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
    assert d.solid is not None
    if material:
        d.material = material
    with open(path, "w", encoding="utf-8") as f:
        f.write(d.to_json())
    return d


def make_asm(folder, parts, name="stack.gpa"):
    os.makedirs(folder, exist_ok=True)
    a = am.Assembly()
    for i, (p, pos) in enumerate(parts):
        a.add_component(p, fixed=(i == 0), pos=pos)
    path = os.path.join(folder, name)
    open(path, "w").write(a.to_json())
    return path


ad = os.path.join(T, "asm")
os.makedirs(ad)
make_part(os.path.join(ad, "base.gpd"), 20.0, 30.0)                    # steel (the default of a part), 20 x 20 x 30
make_part(os.path.join(ad, "cap.gpd"), 20.0, 20.0, ALU)                # aluminium, 20 x 20 x 20
make_part(os.path.join(ad, "far.gpd"), 5.0, 5.0)
asm = make_asm(ad, [(os.path.join("base.gpd"), (0, 0, 0)), (os.path.join("cap.gpd"), (0, 0, 30))])

w = solid_tab.SolidWindow(threaded=False)
assert w.create_project(os.path.join(T, "stack_study"))
assert w.import_file(asm), MSGS
assert w.src["type"] == "asm" and w.is_asm() and len(w.geom["bodies"]) == 2, (w.src, MSGS)
g = w.geom
names = [b["name"] for b in g["bodies"]]
assert len(g["bonds"]) == 1 and abs(g["bonds"][0]["area"] - 400) < 1e-3 and not g["floating"], (g["bonds"], g["floating"], names)
assert w.body_table.rowCount() == 2
assert not w.dims.isVisibleTo(w) and w.b_split.isVisibleTo(w) and w.asm_box.isVisibleTo(w) and w.body_table.isVisibleTo(w)
assert "bonded" in w.asm_lbl.text() and "stack" in w.geo_lbl.text() and "2 bodies" in w.geo_lbl.text()
# the faces between the bodies are not listed for picking and are not drawn
hidden = [i for i in range(w.faces.count()) if w.faces.item(i).isHidden()]
assert hidden == [f["id"] for f in g["faces"] if f["interface"]] and len(hidden) == 1
P, Tr, F = __import__("solid_geom").display_mesh(g)
assert set(np.unique(F)) == {f["id"] for f in g["faces"] if not f["interface"]}
steel_row = names.index(next(n for n in names if "base" in n.lower()))
cap_row = 1 - steel_row
texts = [w.body_table.item(i, 1).text() for i in range(2)]
assert texts[cap_row] == "Aluminium 6061-T6" and "Steel" in texts[steel_row], texts
assert abs(g["bodies"][cap_row]["material"]["E"] - 68900.0) < 1e-6 and abs(g["bodies"][steel_row]["material"]["E"] - 200000.0) < 1e-6

# supports / loads on faces of different bodies
bottom = next(f["id"] for f in g["faces"] if not f["interface"] and f["normal"][2] < -0.99)
topf = next(f["id"] for f in g["faces"] if not f["interface"] and f["normal"][2] > 0.99)
assert "base" in w.face_label(bottom).lower() and "cap" in w.face_label(topf).lower()
w.select_faces([bottom]); assert w.add_support("fixed")
w.select_faces([topf]); assert w.add_load("force", {"f": [0.0, 0.0, -10000.0]})
w.e_h.setText("6"); w.inputs_changed()
assert w.ready() is None, w.ready()
assert w.run_mesh() and "tetrahedra" in w.mesh_lbl.text()
assert w.run_solve() and w.result is not None, w.status_lbl.text()
res = w.result
want = 10000.0 * (30 / 200000.0 + 20 / 68900.0) / 400.0
assert abs(res["umax"] - want) / want < 0.05 and res["equilibrium"] < 1e-6, (res["umax"], want)
assert [b["name"] for b in res["bodies"]] == names and res["bodies"][cap_row]["material"]["name"] == "Aluminium 6061-T6"
txt = w.res_lbl.text()
assert "Bodies (fully bonded)" in txt and names[0] in txt and names[1] in txt and "Aluminium 6061-T6" in txt and "Safety factor" in txt
w.cb_field.setCurrentIndex([i for i in range(w.cb_field.count()) if w.cb_field.itemData(i) == "fos"][0]); w.show_field()
vals, leg = w.field_values()
assert np.isfinite(vals).all() and abs(float(np.nanmin(vals))) > 0.5
w.e_probe.setText("10, 10, 45")
i, dist, un, vm = w.probe_node()
print("solve ok", res["umax"], want)

# change the material of the cap: it is kept for that body, shown in the table and used by the solver
w.body_table.selectRow(cap_row)
assert w.cur_body == cap_row and abs(float(w.e_E.text()) - 68900.0) < 1e-3, (w.cur_body, w.e_E.text())
w.e_E.setText("200000"); w.e_rho.setText(w.e_rho.text()); w.e_E.editingFinished.emit()
assert names[cap_row] in w.setup["body_mats"] and w.setup["body_mats"][names[cap_row]]["E"] == 200000.0 and names[steel_row] not in w.setup["body_mats"]
assert w.run_solve()
want2 = 10000.0 * (50 / 200000.0) / 400.0
assert abs(w.result["umax"] - want2) / want2 < 0.05, (w.result["umax"], want2)
w.body_table.selectRow(steel_row); w.body_table.selectRow(cap_row)
assert abs(float(w.e_E.text()) - 200000.0) < 1e-3                       # the box shows the body's own number again
print("materials ok")

# the setup survives save and reopen: the body materials, the bond distance, the assembly source
w.save()
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w2.is_asm() and w2.src["type"] == "asm" and len(w2.geom["bodies"]) == 2 and w2.setup["body_mats"][names[cap_row]]["E"] == 200000.0
assert len(w2.setup["supports"]) == 1 and len(w2.setup["loads"]) == 1 and w2.ready() is None
assert "assembly" in w2.src_lbl.text()
print("reopen ok")

# the original files are not needed after the import
shutil.rmtree(ad)
w3 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w3.is_asm() and len(w3.geom["bodies"]) == 2

# a part that touches nothing: reported, cannot be solved, and a bigger bond distance cures it
ad2 = os.path.join(T, "asm2")
os.makedirs(ad2)
make_part(os.path.join(ad2, "base.gpd"), 20.0, 30.0)
make_part(os.path.join(ad2, "cap.gpd"), 20.0, 20.0, ALU)
asm2 = make_asm(ad2, [("base.gpd", (0, 0, 0)), ("cap.gpd", (0, 0, 30.5))])                 # 0.5 mm apart
w4 = solid_tab.SolidWindow(threaded=False)
assert w4.create_project(os.path.join(T, "gap_study")) and w4.import_file(asm2)
assert w4.geom["bonds"] == [] and w4.geom["floating"], w4.geom["bonds"]
assert "touches no other body" in w4.asm_lbl.text() and "bond distance" in w4.asm_lbl.text().lower()
bot = next(f["id"] for f in w4.geom["faces"] if f["normal"][2] < -0.99)
tp = next(f["id"] for f in w4.geom["faces"] if f["normal"][2] > 0.99)
w4.select_faces([bot]); w4.add_support("fixed")
w4.select_faces([tp]); w4.add_load("force", {"f": [0.0, 0.0, -1000.0]})
assert w4.ready() and "not bonded" in w4.ready()
w4.e_bond.setText("0.6"); w4.e_bond.editingFinished.emit()
assert w4.setup["bond_tol"] == 0.6 and len(w4.geom["bonds"]) == 1 and not w4.geom["floating"]
assert len(w4.setup["supports"]) == 1 and w4.ready() is None, w4.ready()      # the faces were found again after the geometry changed
assert w4.run_solve() and w4.result is not None
print("bond distance ok")

# parametric study: refused for an assembly
MSGS.clear()
assert w4.open_study() is None and any("single part" in m for m in MSGS), MSGS
print("all ok")
